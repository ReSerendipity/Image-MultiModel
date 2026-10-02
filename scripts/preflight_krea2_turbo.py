"""Krea2-turbo 接入前 preflight —— 真加载 + 小分辨率实出图。

与 `preflight_flux2_klein.py` 同一范式（Klein 实证法），但有几处 Krea2 专属差异，
都是 2026-10-02 实测后才有意这么写的（不是抄 Klein）：

  1. **UNET 用 AIO 那份，不用 `krea2_turbo_fp8_scaled.safetensors`**。后者带
     `_quantization_metadata` + 纯 F8_E4M3 权重，safetensors 0.8.0 的 rust 后端打不开
     （`MetadataIncompleteBuffer` / "file not fully covered"），而**同目录的 AIO 文件能开**；
     AIO 是带 ``model.diffusion_model.`` 前缀的完整 checkpoint，故走
     ``load_torch_file`` → 剥前缀 → ``load_diffusion_model_state_dict``（详见 GOTCHAS #41/42）。
  2. latent 通道 = 16、空间下采样 = **8**（Wan21），且 ``model.latent_format`` 实测为 ``NoneType``
     ⇒ 只能按常量/config 造 latent，不能 ``getattr`` 去取（同 GOTCHAS #40 的坑）。
  3. **不需要**手工下发 shift：``Krea2.sampling_settings = {"shift": 1.15}`` 已在
     ``comfy/model_sampling.py`` 构造时自动读取，脚本只打印 ``model_sampling.shift`` 供核对。
  4. TE 是 Qwen3-VL-4B（``clip_target`` 用 ``qwen3vl_4b.transformer.`` 前缀做 llama_detect），
     与本仓 qwen3vl_8b 不是同一个文件，别指错。

目的（实测而非推断）：
  1. vendored comfy_kernel 能否把 Krea2 UNET 识别为 krea2（检测 key = ``txtfusion.projector.weight``）
  2. latent 口径（通道数 / 空间下采样比）与 executor 的 latent 口径是否一致
  3. qwen3-vl-4b 文本编码器能否被 load_clip 正常识别
  4. 12GB 显存下哪组 (sampler, scheduler) 能真正出图，以及耗时

用法：
    python scripts/preflight_krea2_turbo.py --probe-only        # 只加载三件套（秒级，不采样）
    python scripts/preflight_krea2_turbo.py                     # 默认 512x512 / 4 步
    python scripts/preflight_krea2_turbo.py --w 768 --steps 8
    python scripts/preflight_krea2_turbo.py --unet X --te Y --vae Z   # 显参试错，先验证再动 config
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

# GOTCHAS（2026-10-02）：UNET 只能用 AIO 那份。同目录的 krea2_turbo_fp8_scaled.safetensors
# 是带 _quantization_metadata 的纯 F8_E4M3 权重，safetensors 0.8.0 rust 后端打不开；
# AIO 那份带 model.diffusion_model. 前缀，下面 _load_unet() 会剥前缀。
UNET = r"pretrained_models\unet\Krea2-turbo\krea2TurboNSFWAIO_v10.safetensors"
TE = r"pretrained_models\text_encoders\Krea2\qwen3-vl-4b-heretic_fp8_e4m3fn.safetensors"
VAE = r"pretrained_models\vae\Krea2\qwen_image_vae.safetensors"

# 完整 checkpoint 里 DiT 权重的共同前缀（剥掉后才是 comfy 期望的 bare key）
UNET_KEY_PREFIX = "model.diffusion_model."

# 候选 (sampler, scheduler)：Krea2 是 turbo/蒸馏模型，步数少，用 classic 系调度
COMBOS = [
    ("euler", "simple"),
    ("euler", "beta"),
    ("euler", "sgm_uniform"),
]

# Krea2 走 Wan21 latent：16 通道 / 空间 8 倍下采样。
# model.latent_format 实测为 NoneType（与 qwen_image 同坑，见 GOTCHAS #40），
# 故这里必须是显式常量，不能试图从 model 上 getattr  latent_channels / spacial_downscale_ratio。
LATENT_CHANNELS = 16
DEFAULT_SPACIAL_DOWNSCALE = 8


def log(msg: str) -> None:
    print(msg, flush=True)


def _resolve(explicit: str | None, default: str) -> str:
    """显参优先，其次仓库相对路径（与 preflight_qwen_image.py 同口径）。"""
    if explicit:
        return explicit
    return default.replace("\\", "/")


def _load_unet(unet_path: str):
    """加载 Krea2 UNET：AIO checkpoint → 剥 ``model.diffusion_model.`` 前缀 → 状态字典入口。

    为什么不直接用 ``comfy.sd.load_diffusion_model``：
      * 该入口没有 prefix 参数，直接喂 AIO 会因 key 全带前缀而检测不出模型族；
      * 本机那份 fp8_scaled 权重又是 rust 后端读不了的（见模块 docstring / GOTCHAS #41）。
    """
    import comfy.sd as comfy_sd
    import comfy.utils as comfy_utils

    sd, _meta = comfy_utils.load_torch_file(unet_path, return_metadata=True)
    dit = {k[len(UNET_KEY_PREFIX) :]: v for k, v in sd.items() if k.startswith(UNET_KEY_PREFIX)}
    if not dit:
        raise RuntimeError(f"权重里没有 '{UNET_KEY_PREFIX}' 前缀的 DiT 键：{unet_path}")
    log(f"    DiT 键 {len(dit)} 个（已从 {len(sd)} 个键中剥掉 '{UNET_KEY_PREFIX}' 前缀）")
    return comfy_sd.load_diffusion_model_state_dict(dit)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unet", default=None)
    ap.add_argument("--te", default=None)
    ap.add_argument("--vae", default=None)
    ap.add_argument("--w", type=int, default=512)
    ap.add_argument("--h", type=int, default=512)
    ap.add_argument("--steps", type=int, default=4)
    ap.add_argument("--cfg", type=float, default=1.0)
    ap.add_argument("--ds", type=int, default=DEFAULT_SPACIAL_DOWNSCALE, help="latent 空间下采样比（默认 8 = Wan21）")
    ap.add_argument("--prompt", default="a cat sitting on a wooden table")
    ap.add_argument("--out", default="outputs/_preflight_krea2")
    ap.add_argument("--probe-only", action="store_true", help="只加载三件套并打印探测结论，不采样")
    args = ap.parse_args()

    unet_path = _resolve(args.unet, UNET)
    te_path = _resolve(args.te, TE)
    vae_path = _resolve(args.vae, VAE)
    os.makedirs(args.out, exist_ok=True)

    log("== [0] 路径 ==")
    for tag, p in (("UNET", unet_path), ("TE", te_path), ("VAE", vae_path)):
        log(f"    {tag} = {p}  exists={os.path.isfile(p)}")

    log("== [1] 装载 comfy_kernel 源码 ==")
    source.ensure_loaded(comfy_root="comfy_kernel")
    import comfy.model_management as mm
    import comfy.samplers
    import comfy.sd
    import comfy.utils
    import torch

    log(f"    torch={torch.__version__} cuda={torch.cuda.is_available()}")
    if torch.cuda.is_available():
        log(
            f"    GPU={torch.cuda.get_device_name(0)} "
            f"VRAM={torch.cuda.get_device_properties(0).total_memory / 2**30:.1f}GB"
        )

    log("== [2] 加载 UNet（检测架构族；检测 key = txtfusion.projector.weight）==")
    t0 = time.time()
    model = _load_unet(unet_path)
    ms = model.get_model_object("model_sampling")
    lf = getattr(model, "latent_format", None)
    log(f"    loaded in {time.time() - t0:.1f}s")
    log(
        f"    model_sampling = {type(ms).__name__}  shift={getattr(ms, 'shift', '?')}（由 Krea2.sampling_settings 自动下发）"
    )
    log(f"    latent_format  = {type(lf).__name__}")
    log(
        f"    latent_channels={LATENT_CHANNELS}(常量 Wan21) "
        f"spacial_downscale={args.ds}(常量 Wan21)  —— model 上取不到 latent_format，故用常量"
    )
    if args.probe_only:
        log("== 结论（探测档）：UNET 已识别，架构族/采样/latent 口径如上 ==")
        return 0

    log("== [3] 加载文本编码器（Qwen3-VL-4B，必须显式 type='krea2'）==")
    t0 = time.time()
    # GOTCHAS（2026-10-02 实跑报错）：load_clip 必须同时满足
    #   te_model == TEModel.QWEN3VL_4B（靠 model.visual.merger.linear_fc2.weight 的 shape==2560 判）
    #   且 clip_type == CLIPType.KREA2
    # 才走 krea2 分支（sd.py:1969，12 层 tap = 30720 维）。传字符串 "krea2" **不等于**枚举，
    # 会落到 else 分支按单层 2560 维建 TE，前向即报
    #   "Krea2 expects conditioning with 12x2560=30720 features ... but got 2560."
    clip = comfy.sd.load_clip([te_path], clip_type=comfy.sd.CLIPType.KREA2)
    log(f"    loaded in {time.time() - t0:.1f}s")
    log(f"    clip class = {type(clip).__name__}")

    log("== [4] 加载 VAE ==")
    t0 = time.time()
    vae_sd = comfy.utils.load_torch_file(vae_path)
    vae = comfy.sd.VAE(sd=vae_sd)
    log(f"    loaded in {time.time() - t0:.1f}s  vae class = {type(vae).__name__}")

    log("== [5] 编码 prompt ==")
    tokens = clip.tokenize(args.prompt)
    positive = clip.encode_from_tokens_scheduled(tokens)
    negative = clip.encode_from_tokens_scheduled(clip.tokenize(""))
    log(f"    positive cond ok, len={len(positive)}")

    ch = LATENT_CHANNELS
    ds = args.ds
    # GOTCHAS（2026-10-02 实跑）：Krea2 走 Wan21 latent，是 **5D** (1, c, t, h, w)，图生像 t=1。
    # 造 4D (1,c,h,w) 会被模型当成把空间维当时间维解析，采样出 (1,16,16,64,64)、
    # VAE 解码成 61 帧，落盘就是满屏条纹 + 雾化的废图（已目检确认）。
    lh, lw = args.h // ds, args.w // ds
    log(f"== [6] 构造空 latent: 1 x {ch} x 1 x {lh} x {lw}  (ds={ds}, Wan21 5D) ==")
    latent = torch.zeros([1, ch, 1, lh, lw], dtype=torch.float32)
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
            # GOTCHAS（2026-10-02 实跑）：采样与 VAE 解码必须整体放进 inference mode，
            # 否则 tiled 解码会在 inference tensor 上做原地更新，报
            #   "Inplace update to inference tensor outside InferenceMode is not allowed."
            with torch.inference_mode():
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
                # 与 comfy 的 VAEDecode 节点同口径（nodes.py:334）：5D 输出压成 4D，
                # 否则落盘时 PIL 报 "Cannot handle this data type"。
                if len(images.shape) == 5:
                    images = images.reshape(-1, images.shape[-3], images.shape[-2], images.shape[-1])
            log(f"    decoded shape={tuple(images.shape)}")
            ok_combo = (sampler_name, sched_name)
            # 落盘留证
            try:
                from PIL import Image

                # detach()：采样结果带 grad，直接 .numpy() 会抛错
                arr = (images[0].detach().cpu().clamp(0, 1).numpy() * 255).astype("uint8")
                p = os.path.join(args.out, f"krea2_{sampler_name}_{sched_name}.png")
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
