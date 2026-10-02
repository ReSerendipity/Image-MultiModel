"""FLUX.1-dev 接入前 preflight（范式对齐 preflight_krea2_turbo.py）。

与 Krea2/Qwen-Image 的差异（2026-10-02 实证查证）：
- FLUX 用**双文本编码器** clip_l + t5xxl，必须 `clip_type="flux"`（CLIPType.FLUX=6），
  走 `comfy.text_encoders.flux.flux_clip(**t5xxl_detect(...))`；只给 t5xxl 会缺 clip_l 分支。
- latent 是 **4D** `[1, 16, H/8, W/8]`（latent_formats.Flux -> SD3，与 Wan21/Krea2 的 5D 不同）。
- guidance 不是 cfg：FLUX 的 guidance 走 `model_base.Flux.concat_cond` 里的
  `kwargs.get("guidance", 3.5)`，上游对应 comfy_extras 的 `Guidance` 节点；
  本 executor 没有该节点，故必须在编码后往 cond 字典里注入 `guidance` 键。
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

# GOTCHAS（2026-10-02）：本机 FLUX-1-dev 目录下 4 份都是纯 fp8 的 DiT（780 键，无 TE/VAE）。
# 四份都是 NSFW 系微调（文件名自证），精度/前缀各异：
#   Flux-Capacity-NSFW-V2-fp8  F8_E5M2（指数位为主、尾数位仅 3 位，精度很差）+ model. 前缀
#   fluxNSFWUNLOCKED           F8_E4M3 + model. 前缀   <-- 默认选它（精度档位正常 + 有前缀，
#                              可直接复用 Krea2 那套 unet_key_prefix 剥前缀逻辑）
#   pornworks-.../pornworks02   F8_E4M3 + **裸键**（无前缀）
UNET = r"pretrained_models\unet\FLUX-1-dev\fluxNSFWUNLOCKED.safetensors"
UNET_KEY_PREFIX = "model.diffusion_model."
# FLUX 双 TE：t5xxl + clip_l，两者缺一不可
TE = r"pretrained_models\text_encoders\FLUX-1-dev\t5xxl_fp8_e4m3fn.safetensors"
TE_EXTRA = r"pretrained_models\clip\FLUX.1-dev\clip_l.safetensors"
CLIP_TYPE = "flux"

# VAE：本机已有 junction pretrained_models/vae/FLUX.1-dev(Z-image(turbo) -> ae.safetensors
VAE = r"pretrained_models\vae\FLUX.1-dev(Z-image(turbo))\ae.safetensors"

# FLUX latent 口径（comfy/latent_formats.py: class Flux(SD3)）：16 通道 / 空间下采样 8
LATENT_CHANNELS = 16
DEFAULT_SPACIAL_DOWNSCALE = 8

# FLUX.1-dev 是 guidance 蒸馏模型：guidance 与 cfg 是两套参数（不要混用）
DEFAULT_GUIDANCE = 3.5
COMBOS = [("euler", "simple"), ("euler", "beta"), ("euler", "sgm_uniform")]


def log(msg: str) -> None:
    print(msg, flush=True)


def _resolve(arg: str | None, default: str) -> str:
    if arg:
        return arg
    return os.path.join(REPO_ROOT, default)


def _load_unet(unet_path: str):
    """读 AIO 风格权重 → 剥前缀 → 按状态字典装载。

    GOTCHAS（2026-10-02）：本机这份 FLUX 是**纯 DiT**（780 键，不含 TE/VAE），
    键带 `model.diffusion_model.` 前缀，`comfy.sd.load_diffusion_model` 没有 prefix 参数，
    故走「load_torch_file → 剥前缀 → load_diffusion_model_state_dict」。
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
    ap.add_argument("--te-extra", default=None, help="clip_l（FLUX 双编码器的第二个 TE）")
    ap.add_argument("--vae", default=None)
    ap.add_argument("--w", type=int, default=256)
    ap.add_argument("--h", type=int, default=256)
    ap.add_argument("--steps", type=int, default=4)
    ap.add_argument("--cfg", type=float, default=1.0)
    ap.add_argument("--guidance", type=float, default=DEFAULT_GUIDANCE)
    ap.add_argument("--ds", type=int, default=DEFAULT_SPACIAL_DOWNSCALE)
    ap.add_argument("--prompt", default="a cat sitting on a wooden table")
    ap.add_argument("--out", default="outputs/_preflight_flux1_dev")
    ap.add_argument("--probe-only", action="store_true", help="只加载三件套并打印探测结论，不采样")
    args = ap.parse_args()

    unet_path = _resolve(args.unet, UNET)
    te_path = _resolve(args.te, TE)
    te_extra = _resolve(args.te_extra, TE_EXTRA)
    vae_path = _resolve(args.vae, VAE)
    os.makedirs(args.out, exist_ok=True)

    log("== [0] 路径 ==")
    for tag, p in (("UNET", unet_path), ("TE(t5xxl)", te_path), ("TE(clip_l)", te_extra), ("VAE", vae_path)):
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

    log("== [2] 加载 UNET（检测架构族；检测 key = double_blocks.0.* + img_in.weight）==")
    t0 = time.time()
    model = _load_unet(unet_path)
    ms = model.get_model_object("model_sampling")
    lf = getattr(model, "latent_format", None)
    log(f"    loaded in {time.time() - t0:.1f}s")
    log(f"    model_sampling = {type(ms).__name__}  shift={getattr(ms, 'shift', '?')}")
    log(f"    latent_format  = {type(lf).__name__}")
    if lf is not None:
        log(f"    latent_channels={getattr(lf, 'latent_channels', '?')}（取自 latent_format，非常量兜底）")
    lch = LATENT_CHANNELS
    if lf is not None:
        lch = getattr(lf, "latent_channels", LATENT_CHANNELS)
    log(f"    latent_downscale={args.ds}(常量 latent_formats.Flux -> SD3)  —— 取不到时以常量兜底")
    if args.probe_only:
        log("== 结论（探测档）：UNET 已识别，架构族/采样/latent 口径如上 ==")
        return 0

    log("== [3] 加载文本编码器（FLUX 双 TE：t5xxl + clip_l，必须显式 clip_type=flux）==")
    t0 = time.time()
    clip = comfy.sd.load_clip([te_path, te_extra], clip_type=comfy.sd.CLIPType.FLUX)
    log(f"    loaded in {time.time() - t0:.1f}s")
    log(f"    clip class = {type(clip).__name__}")

    log("== [4] 加载 VAE ==")
    t0 = time.time()
    vae_sd = comfy.utils.load_torch_file(vae_path)
    vae = comfy.sd.VAE(sd=vae_sd)
    log(f"    loaded in {time.time() - t0:.1f}s  vae class = {type(vae).__name__}")

    log("== [5] 编码 prompt（并注入 guidance）==")
    tokens = clip.tokenize(args.prompt)
    positive_raw = clip.encode_from_tokens_scheduled(tokens)
    negative_raw = clip.encode_from_tokens_scheduled(clip.tokenize(""))
    # GOTCHAS（2026-10-02 查证）：FLUX 的 guidance 不在 cfg 通道上，而是
    # `model_base.Flux.concat_cond` 里的 `kwargs.get("guidance", 3.5)`；上游由 comfy_extras
    # 的 `Guidance` 节点往 cond 字典里写 "guidance" 键。executor 无该节点，故这里手工注入，
    # 否则 guidance 恒为默认 3.5、无法按参数调优。
    g = torch.FloatTensor([args.guidance])

    def _inject(conds, guidance: torch.Tensor):
        out = []
        for c in conds:
            d = dict(c[1])
            d["guidance"] = guidance
            out.append([c[0], d])
        return out

    positive = _inject(positive_raw, g)
    negative = _inject(negative_raw, g)
    log(f"    positive cond ok, len={len(positive)}  guidance={args.guidance}")

    ch = lch
    ds = args.ds
    # GOTCHAS（2026-10-02）：FLUX 走 latent_formats.Flux -> SD3，是 **4D** (1, c, h, w)，
    # 与 Krea2/Wan21 的 5D 不同——这里是图生像模型，没有时间维。
    lh, lw = args.h // ds, args.w // ds
    log(f"== [6] 构造空 latent: 1 x {ch} x {lh} x {lw}  (ds={ds}, latent_formats.Flux 4D) ==")
    latent = torch.zeros([1, ch, lh, lw], dtype=torch.float32)
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
            # GOTCHAS（2026-10-02，同 Krea2）：采样与 tiled VAE 解码必须整体放进 inference mode
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
                log(f"    decoded shape={tuple(images.shape)}")
            ok_combo = (sampler_name, sched_name)
            try:
                from PIL import Image

                arr = (images[0].detach().cpu().clamp(0, 1).numpy() * 255).astype("uint8")
                p = os.path.join(args.out, f"flux1_{sampler_name}_{sched_name}.png")
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
