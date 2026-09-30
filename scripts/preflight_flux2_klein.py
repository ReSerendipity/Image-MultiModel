"""Flux.2 Klein 接入前 preflight —— 真加载 + 小分辨率实出图。

目的：用实测（而非推断）确定四件事
  1. vendored comfy_kernel 能否把 Klein UNet 识别为 flux2（image_model / out_channels）
  2. latent 格式（通道数 / 下采样比）—— executor 会从 model.latent_format 自动读取
  3. qwen_3_8b 文本编码器被识别成哪个 TEModel（预期 QWEN3_8B=20）
  4. 哪组 (sampler, scheduler) 能真正出图，以及 12GB 显存下的可行性/耗时

用法：
    python scripts/preflight_flux2_klein.py            # 默认 512x512 / 4 步
    python scripts/preflight_flux2_klein.py --w 768 --steps 8
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

from app.integrated_app.native import source  # noqa: E402

UNET = r"pretrained_models\unet\FLUX-2-klein-9b\BigLoveKlein2_fp8.safetensors"
TE = r"pretrained_models\text_encoders\FLUX-2-klein-9b\qwen_3_8b_fp8mixed.safetensors"
VAE = r"pretrained_models\vae\FLUX.2-klein-9b\flux2-vae.safetensors"

# 候选 (sampler, scheduler)：Flux 系常用 euler + simple/beta/sgm_uniform
COMBOS = [
    ("euler", "simple"),
    ("euler", "beta"),
    ("euler", "sgm_uniform"),
]


def log(msg: str) -> None:
    print(msg, flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--w", type=int, default=512)
    ap.add_argument("--h", type=int, default=512)
    ap.add_argument("--steps", type=int, default=4)
    ap.add_argument("--cfg", type=float, default=1.0)
    ap.add_argument("--prompt", default="a cat sitting on a wooden table")
    ap.add_argument("--out", default="outputs/_preflight_flux2klein")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)

    log("== [1] 装载 comfy_kernel 源码 ==")
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
    model = comfy.sd.load_diffusion_model(UNET)
    ms = model.get_model_object("model_sampling")
    lf = getattr(model, "latent_format", None)
    log(f"    loaded in {time.time() - t0:.1f}s")
    log(f"    model_sampling = {type(ms).__name__}")
    log(f"    latent_format  = {type(lf).__name__}")
    log(
        f"    latent_channels={getattr(lf, 'latent_channels', '?')} "
        f"downscale={getattr(lf, 'spacial_downscale_ratio', '?')}"
    )

    log("== [3] 加载文本编码器（qwen_3_8b）==")
    t0 = time.time()
    clip = comfy.sd.load_clip([TE])
    log(f"    loaded in {time.time() - t0:.1f}s")
    log(f"    clip class = {type(clip).__name__}")

    log("== [4] 加载 VAE ==")
    vae_sd = comfy.utils.load_torch_file(VAE)
    vae = comfy.sd.VAE(sd=vae_sd)
    log(f"    vae class = {type(vae).__name__}")

    log("== [5] 编码 prompt ==")
    tokens = clip.tokenize(args.prompt)
    positive = clip.encode_from_tokens_scheduled(tokens)
    negative = clip.encode_from_tokens_scheduled(clip.tokenize(""))
    log(f"    positive cond ok, len={len(positive)}")

    ch = int(getattr(lf, "latent_channels", 128))
    ds = int(getattr(lf, "spacial_downscale_ratio", 16))
    log(f"== [6] 构造空 latent: 1 x {ch} x {args.h // ds} x {args.w // ds} ==")
    latent = torch.zeros([1, ch, args.h // ds, args.w // ds], dtype=torch.float32)
    device = mm.get_torch_device()
    latent = latent.to(device)
    noise = torch.randn(
        latent.shape, generator=torch.Generator(device=device).manual_seed(1), device=device, dtype=torch.float32
    )

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
            images = vae.decode(sampled)
            log(f"    decoded shape={tuple(images.shape)}")
            ok_combo = (sampler_name, sched_name)
            # 落盘留证
            try:
                from PIL import Image

                # detach()：采样结果带 grad，直接 .numpy() 会抛错
                arr = (images[0].detach().cpu().clamp(0, 1).numpy() * 255).astype("uint8")
                p = os.path.join(args.out, f"klein_{sampler_name}_{sched_name}.png")
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
        return 0
    log("FAILED: 所有候选 (sampler, scheduler) 均未出图，见上方 traceback")
    return 1


if __name__ == "__main__":
    sys.exit(main())
