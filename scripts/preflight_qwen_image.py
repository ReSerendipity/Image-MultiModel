"""Qwen-Image 2.1 原生文生图接入前 preflight —— 真加载 + 小分辨率实出图。

目的：用实测（而非推断）确定四件事（沿用 Flux.2 Klein 实证法）
  1. vendored comfy_kernel 能否把 Qwen-Image 基座 UNet 识别为 qwen_image 架构族
  2. latent 格式（通道数 / 下采样比）—— Qwen-Image 2.1 为 64 通道 / 16 下采样（edit 块实测）
  3. qwen3vl_8b 文本编码器被识别成哪个 TEModel
  4. 哪组 (sampler, scheduler) 能真正出图，以及 12GB 显存下的可行性/耗时

离线约束：本仓严格离线化。脚本优先读 config.yaml 的 qwen_image_native 引擎块解析
本地模型路径；若基座 unet 缺失（本地库仅有 edit unet），以退出码 2（SKIPPED）退出
并给出清晰指引，绝不静默降级、不联网下载。

用法：
    python scripts/preflight_qwen_image.py               # 读 config.yaml qwen_image_native
    python scripts/preflight_qwen_image.py --w 512 --steps 8
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import traceback

# 保证从仓库任意位置运行都能 import app 包
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def log(msg: str) -> None:
    print(msg, flush=True)


def _resolve_paths(args: argparse.Namespace) -> dict[str, str]:
    """解析 unet / text_encoder / vae 绝对路径。

    优先级：--unet/--te/--vae 显参 > config.yaml engines.qwen_image_native 的
    sub_path。显参优先；否则复用 app 的 ``resolve_engine_model_paths``（与
    NativeEngine.load 同口径，自动处理 shared/portable 两种 model_source_mode，
    避免路径解析与运行时漂移）。返回字典；任一缺失则对应键为空。
    """
    if args.unet and args.te and args.vae:
        return {
            "unet": os.path.abspath(args.unet),
            "text_encoder": os.path.abspath(args.te),
            "vae": os.path.abspath(args.vae),
        }
    try:
        from app.integrated_app.config import get_config
        from app.integrated_app.config_models import resolve_engine_model_paths

        cfg = get_config()
        eng = getattr(cfg.models, "engines", {}).get("qwen_image_native")
        if eng is not None:
            paths = resolve_engine_model_paths(eng, cfg.models, cfg.project_root)
            if paths:
                return {k: os.path.abspath(v) for k, v in paths.items()}
    except Exception as e:  # 配置加载失败不应阻断 preflight 的离线判定
        log(f"    [WARN] 读取 config.yaml 失败（{e!r}），回退离线判定")
    return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unet", default=None)
    ap.add_argument("--te", default=None)
    ap.add_argument("--vae", default=None)
    ap.add_argument("--w", type=int, default=512)
    ap.add_argument("--h", type=int, default=512)
    ap.add_argument("--steps", type=int, default=8)
    ap.add_argument("--cfg", type=float, default=1.0)
    ap.add_argument("--prompt", default="a cat sitting on a wooden table")
    ap.add_argument("--out", default="outputs/_preflight_qwen_image")
    args = ap.parse_args()

    paths = _resolve_paths(args)
    unet = paths.get("unet", "")
    te = paths.get("text_encoder", "")
    vae = paths.get("vae", "")

    log("== [0] 解析 Qwen-Image 基座权重路径 ==")
    log(f"    unet={unet}")
    log(f"    te  ={te}")
    log(f"    vae ={vae}")
    missing = [
        role for role, p in (("unet", unet), ("text_encoder", te), ("vae", vae)) if not p or not os.path.isfile(p)
    ]
    if missing:
        log(
            "SKIPPED(2): 离线阻断——基座权重缺失："
            + ", ".join(missing)
            + "（本地库仅有 Qwen-Image 2.1 的 edit unet，非 txt2img 基座）。"
        )
        log("    解决：下载 Qwen-Image 2.1 基座 txt2img checkpoint 到对应 sub_dir，")
        log("    确认 config.yaml engines.qwen_image_native.unet.sub_path 指向真实文件，再重跑本脚本。")
        log("    （本仓离线化，preflight 不联网下载。）")
        return 2

    os.makedirs(args.out, exist_ok=True)

    log("== [1] 装载 comfy_kernel 源码 ==")
    from app.integrated_app.native import source

    source.ensure_loaded(comfy_root="comfy_kernel")
    import comfy.model_management as mm
    import comfy.samplers
    import comfy.sd
    import torch

    log(f"    torch={torch.__version__} cuda={torch.cuda.is_available()}")
    if torch.cuda.is_available():
        log(
            f"    GPU={torch.cuda.get_device_name(0)} "
            f"VRAM={torch.cuda.get_device_properties(0).total_memory / 2**30:.1f}GB"
        )

    log("== [2] 加载 UNet（检测架构族）==")
    t0 = time.time()
    model = comfy.sd.load_diffusion_model(unet)
    ms = model.get_model_object("model_sampling")
    lf = getattr(model, "latent_format", None)
    log(f"    loaded in {time.time() - t0:.1f}s")
    log(f"    model_sampling = {type(ms).__name__}")
    log(f"    latent_format  = {type(lf).__name__}")
    log(
        f"    latent_channels={getattr(lf, 'latent_channels', '?')} "
        f"downscale={getattr(lf, 'spacial_downscale_ratio', '?')}"
    )

    log("== [3] 加载文本编码器（qwen3vl_8b）==")
    t0 = time.time()
    clip = comfy.sd.load_clip([te])
    log(f"    loaded in {time.time() - t0:.1f}s")
    log(f"    clip class = {type(clip).__name__}")

    log("== [4] 加载 VAE ==")
    vae_sd = comfy.utils.load_torch_file(vae)
    vae_obj = comfy.sd.VAE(sd=vae_sd)
    log(f"    vae class = {type(vae_obj).__name__}")

    log("== [5] 编码 prompt ==")
    tokens = clip.tokenize(args.prompt)
    positive = clip.encode_from_tokens_scheduled(tokens)
    negative = clip.encode_from_tokens_scheduled(clip.tokenize(""))

    ch = int(getattr(lf, "latent_channels", 64))
    ds = int(getattr(lf, "spacial_downscale_ratio", 16))
    log(f"== [6] 构造空 latent: 1 x {ch} x {args.h // ds} x {args.w // ds} ==")
    latent = torch.zeros([1, ch, args.h // ds, args.w // ds], dtype=torch.float32)
    device = mm.get_torch_device()
    latent = latent.to(device)
    noise = torch.randn(
        latent.shape, generator=torch.Generator(device=device).manual_seed(1), device=device, dtype=torch.float32
    )

    # 候选 (sampler, scheduler)：Qwen-Image 系常用 euler + simple/beta/sgm_uniform
    COMBOS = [
        ("euler", "simple"),
        ("euler", "beta"),
        ("euler", "sgm_uniform"),
        ("dpmpp_2m", "simple"),
    ]

    ok_combo = None
    for sampler_name, sched_name in COMBOS:
        log(f"== [7] 试采样 sampler={sampler_name} scheduler={sched_name} ==")
        try:
            t0 = time.time()
            sigmas = comfy.samplers.calculate_sigmas(ms, sched_name, args.steps)
            sampler_obj = comfy.samplers.sampler_object(sampler_name)
            sampled = comfy.samplers.sample(
                model,
                noise,
                positive,
                negative,
                args.cfg,
                device,
                sampler_obj,
                sigmas,
                latent_image=latent,
                seed=1,
            )
            log(f"    sampled in {time.time() - t0:.1f}s  shape={tuple(sampled.shape)}")
            images = vae_obj.decode(sampled)
            log(f"    decoded shape={tuple(images.shape)}")
            ok_combo = (sampler_name, sched_name)
            try:
                from PIL import Image

                arr = (images[0].detach().cpu().clamp(0, 1).numpy() * 255).astype("uint8")
                p = os.path.join(args.out, f"qwen_{sampler_name}_{sched_name}.png")
                Image.fromarray(arr).save(p)
                log(f"    SAVED {p}")
            except Exception as e:  # 落盘失败不影响结论
                log(f"    save skipped: {e}")
            break
        except Exception:
            log("    FAILED:\n" + traceback.format_exc(limit=3))
        finally:
            try:
                mm.soft_empty_cache()
            except Exception:
                pass

    log("== 结论 ==")
    if ok_combo:
        log(f"OK: sampler={ok_combo[0]} scheduler={ok_combo[1]} 可用于 config.yaml")
        log("    （回填 engines.qwen_image_native.sampler / .scheduler 后视为接入完成）")
        return 0
    log("FAILED: 所有候选 (sampler, scheduler) 均未出图，见上方 traceback")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        log("FAILED(1): Qwen-Image 原生接入异常，见上方 traceback")
        traceback.print_exc(limit=5)
        sys.exit(1)
