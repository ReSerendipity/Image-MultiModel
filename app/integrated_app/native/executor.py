"""
native/executor.py — 进程内 Z-Image 文生图执行器

复用本地 Comfy 源码（comfy.sd / comfy.samplers / comfy.model_management 等）
在同一进程内完成：unet/clip/vae 加载 -> CLIP 编码 -> 采样 -> VAE 解码。

Phase 1 只做核心出图链路（UNET->CLIP->VAE->encode->KSampler->decode），
SeedVR2 / ESES / ReservedVRAM 等留到 Phase 3。
"""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass
from typing import Any

import torch

from ..engine_interface import GenerationConfig, ProgressCallback
from . import source

logger = logging.getLogger(__name__)

# Z-Image (Lumina2/Flux latent) 采样参数（对齐 workflow 的 ModelSamplingAuraFlow shift=3）
ZIMAGE_SAMPLER = "dpmpp_3m_sde_gpu"
ZIMAGE_SCHEDULER = "sgm_uniform"
ZIMAGE_STEPS = 8
ZIMAGE_CFG = 1.0

# 空 latent 的形状（Z-Image 使用 FLUX AE，16 通道 / 8 倍下采样）
LATENT_CHANNELS = 16
SPATIAL_DOWNSCALE = 8
# 采样进度区间：从 20% 到 90%（前后各留 10% 给加载/解码）
SAMPLING_PCT_START = 20
SAMPLING_PCT_END = 90


@dataclass
class NativeModels:
    """一次装载的本地 Comfy 模型集合。"""

    model: Any  # comfy model patcher（diffusion_model）
    clip: Any  # comfy.sd.CLIP
    vae: Any  # comfy.sd.VAE
    device: Any  # torch.device
    model_sampling: Any  # 采样用 model_sampling 对象
    latent_format: Any  # 模型对应的 latent 格式对象（决定 latent 通道数/下采样比）


def latent_shape(
    batch_size: int,
    width: int,
    height: int,
    channels: int = LATENT_CHANNELS,
    downscale: int = SPATIAL_DOWNSCALE,
) -> list[int]:
    """计算空 latent 的形状（按模型 latent 格式下采样）。

    Args:
        batch_size: 批量大小
        width: 图像宽度（像素）
        height: 图像高度（像素）
        channels: latent 通道数
        downscale: 空间下采样比（默认 8）

    Returns:
        [batch, channels, height // downscale, width // downscale]
    """
    return [batch_size, channels, height // downscale, width // downscale]


def build_latent(
    batch_size: int,
    width: int,
    height: int,
    channels: int = LATENT_CHANNELS,
    downscale: int = SPATIAL_DOWNSCALE,
) -> torch.Tensor:
    """构造全零空 latent（对齐 EmptySD3LatentImage 语义）。"""
    shape = latent_shape(batch_size, width, height, channels, downscale)
    return torch.zeros(shape, dtype=torch.float32, device="cpu")


def _resolve_device() -> torch.device:
    """优先 GPU，CPU 兜底。"""
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def _comfy_runtime() -> Any:
    """惰性装载 comfy 运行时并取回 `comfy` 模块。

    ``comfy`` 只在真正要跑模型时才需要（且要求 ``comfy_root`` 已进 ``sys.path``，
    见 :func:`source.ensure_loaded`），故不能在模块顶层 ``import comfy``——那会让
    整个 app 一导入就背上限 comfy 源码。这里统一走惰性入口，下面的加载定制
    函数都通过它取 comfy.sd / comfy.utils，避免「函数内局部 import 只绑到局部名」
    造成的 ``NameError``/静态检查报 ``F821``。
    """
    import comfy  # noqa: PLC0415  # 惰性导入：仅在真正加载/推理时才需要 comfy 源码
    import comfy.model_management  # noqa: F401,PLC0415  # 初始化模型管理
    import comfy.samplers  # noqa: F401,PLC0415
    import comfy.sd  # noqa: F401,PLC0415
    import comfy.utils  # noqa: F401,PLC0415

    return comfy


def _load_diffusion_model(unet_path: str, unet_key_prefix: str | None = None) -> Any:
    """加载 UNET；``unet_key_prefix`` 非空时先剥前缀再走状态字典入口。

    2026-10-02 Krea2 实证引入：本机 Krea2-turbo 只有带 ``model.diffusion_model.`` 前缀的
    完整 checkpoint（AIO 版）才被 safetensors rust 后端读得了——那份纯 fp8 的
    ``krea2_turbo_fp8_scaled.safetensors`` 带 ``_quantization_metadata``，rust 后端 0.8.0
    会报 "file not fully covered"（详见 GOTCHAS #41）。故 AIO 走「读文件 → 剥前缀 →
    ``load_diffusion_model_state_dict``」，``load_diffusion_model`` 本身没有 prefix 参数。
    """
    comfy_rt = _comfy_runtime()
    if not unet_key_prefix:
        return comfy_rt.sd.load_diffusion_model(unet_path)
    sd, _metadata = comfy_rt.utils.load_torch_file(unet_path, return_metadata=True)
    sd = {k[len(unet_key_prefix) :]: v for k, v in sd.items() if k.startswith(unet_key_prefix)}
    if not sd:
        raise RuntimeError(f"权重里没有 '{unet_key_prefix}' 前缀的 DiT 键，剥前缀后为空：{unet_path}")
    return comfy_rt.sd.load_diffusion_model_state_dict(sd)


def _load_text_encoder(te_paths: list[str], clip_type: str | None = None) -> Any:
    """加载 CLIP；``clip_type`` 命中 ``CLIPType`` 枚举时显式下发。

    2026-10-02 Krea2 实证引入：Krea2 的 TE 是 Qwen3-VL-4B，必须走 ``CLIPType.KREA2``
    分支（sd.py 要求 ``clip_type == CLIPType.KREA2`` 且 ``te_model == TEModel.QWEN3VL_4B``
    同时成立才会取 12 层 tap = 30720 维）；传字符串 ``"krea2"`` **不等于**枚举，会落回
    通用分支按单层 2560 维建 TE，前向即报 "expects ... 12x2560=30720 ... but got 2560"
    （详见 GOTCHAS #42）。
    """
    comfy_rt = _comfy_runtime()
    if not clip_type:
        return comfy_rt.sd.load_clip(te_paths)
    clip_type_enum = getattr(comfy_rt.sd.CLIPType, str(clip_type).upper(), None)
    if clip_type_enum is None:
        return comfy_rt.sd.load_clip(te_paths)
    return comfy_rt.sd.load_clip(te_paths, clip_type=clip_type_enum)


def _load_models(
    model_paths: dict[str, str],
    comfy_root: str | None = None,
) -> NativeModels:
    """加载 unet / clip / vae 到本地 Comfy 运行时。

    Args:
        model_paths: 含 ``unet`` / ``text_encoder`` / ``vae`` 键的模型绝对路径映射
        comfy_root: Comfy 源码根目录（传给 source.ensure_loaded）

    Returns:
        装载好的 NativeModels 对象

    ``model_paths`` 支持三个可选键（均缺省时行为与历史完全一致，见 GOTCHAS #41/42）：
        - ``text_encoder``: 文本编码器权重
        - ``unet``: 扩散主干权重
        - ``unet_key_prefix``: UNET 权重键的统一前缀（非空时先剥前缀再加载，Krea2 AIO 需要）
        - ``text_encoder_clip_type``: CLIP 类型名（如 ``krea2``，内部映射为 ``CLIPType.KREA2`` 枚举）

    Raises:
        RuntimeError: 缺少必需模型路径或模型加载失败
    """
    source.ensure_loaded(comfy_root=comfy_root)
    comfy_rt = _comfy_runtime()

    unet_path = model_paths.get("unet")
    te_path = model_paths.get("text_encoder")
    vae_path = model_paths.get("vae")
    if not unet_path or not te_path or not vae_path:
        raise RuntimeError(
            "Native engine requires 'unet', 'text_encoder' and 'vae' model paths, "
            f"got keys: {sorted(model_paths.keys())}"
        )

    device = _resolve_device()

    # 加载 unet（Z-Image 自动检测为 Lumina2/ZImage，内置 ModelSamplingDiscreteFlow shift=3）
    model = _load_diffusion_model(unet_path, model_paths.get("unet_key_prefix"))
    model_sampling = model.get_model_object("model_sampling")
    latent_format = getattr(model, "latent_format", None)

    # 加载 clip（Z-Image 用 qwen_image 类型，load_clip 自动检测；Krea2 需显式 clip_type=krea2）
    clip = _load_text_encoder([te_path], model_paths.get("text_encoder_clip_type"))

    # 加载 vae
    vae_sd = comfy_rt.utils.load_torch_file(vae_path)
    vae = comfy_rt.sd.VAE(sd=vae_sd)

    return NativeModels(
        model=model,
        clip=clip,
        vae=vae,
        device=device,
        model_sampling=model_sampling,
        latent_format=latent_format,
    )


def _encode_conditioning(clip: Any, text: str) -> list[Any]:
    """用 CLIP 对文本做编码，返回 Comfy conditioning 列表。

    对齐 CLIPTextEncode 节点：``clip.tokenize(text)`` + ``encode_from_tokens_scheduled``。
    Z-Image tokenizer 已在 ``z_image.tokenize_with_weights`` 内置 llama_template。
    """
    tokens = clip.tokenize(text)
    return clip.encode_from_tokens_scheduled(tokens)


def _vae_decode(vae: Any, latent: torch.Tensor) -> torch.Tensor:
    """VAE 解码，返回 [0,1] 范围 RGB 张量 (B,H,W,3)。

    对齐 Comfy 的 VAEDecode 节点：直接把 latent 张量传给 ``vae.decode``。
    """
    return vae.decode(latent)


def _make_sampling_callback(
    steps: int,
    on_progress: ProgressCallback | None,
    cancel_flag: list[bool],
) -> Any:
    """构造采样回调：上报进度 + 支持取消。

    Args:
        cancel_flag: 长度 1 列表，``cancel_flag[0]`` 为 True 时抛 CancelledError
    """

    def cb(step: int, _x0: Any, _x: Any, total_steps: int) -> None:
        if cancel_flag[0]:
            raise asyncio.CancelledError("Native generation cancelled by user")
        if total_steps > 0 and on_progress:
            inner = int(step / total_steps * 100)
            pct = SAMPLING_PCT_START + int(inner * (SAMPLING_PCT_END - SAMPLING_PCT_START) / 100)
            on_progress(pct, f"Sampling {step}/{total_steps}", {})

    return cb


def _fixed_seed(seed: int) -> int:
    """把 -1 解析为固定随机种子，保证确定性/可复现。"""
    if seed < 0:
        return 120429878797176  # 与 workflow 默认 seed 一致
    return seed


def txt2img(
    config: GenerationConfig,
    model_paths: dict[str, str],
    on_progress: ProgressCallback | None = None,
    comfy_root: str | None = None,
    cancel_flag: list[bool] | None = None,
) -> list[torch.Tensor]:
    """进程内 Z-Image 文生图（同步阻塞，供 async 层包在 executor 线程中调用）。

    Args:
        config: 生图配置（prompt / steps / cfg / width / height / seed / batch_size）
        model_paths: unet / text_encoder / vae 绝对路径映射；
            另可带可选键 ``unet_key_prefix``（UNET 键前缀，Krea2 AIO 用）与
            ``text_encoder_clip_type``（CLIP 类型名，Krea2 取 ``krea2``）。
            两者缺省时行为与历史完全一致（见 GOTCHAS #41/42）。
        on_progress: 进度回调 (pct, phase, extra)
        comfy_root: Comfy 源码根目录
        cancel_flag: 长度 1 列表，采样中置 True 抛 CancelledError 取消

    Returns:
        list[torch.Tensor]，每张为 [0,1] 范围 RGB 张量 (H,W,3)
    """
    if on_progress:
        on_progress(5, "Loading native models...", {})
    models = _load_models(model_paths, comfy_root=comfy_root)

    import comfy.samplers  # noqa: F401  # 复用已装载的本地 Comfy 源码

    try:
        # 1. CLIP 编码
        if on_progress:
            on_progress(10, "Encoding prompts...", {})
        positive = _encode_conditioning(models.clip, config.positive_prompt)
        negative = _encode_conditioning(models.clip, config.negative_prompt)

        # 2. 构造空 latent 与噪声（通道数/下采样比按引擎 config 下发，否则查模型，最后回退 Z-Image 默认 16/8）
        batch = max(1, config.batch_size)
        lf = models.latent_format
        channels = config.latent_channels or int(getattr(lf, "latent_channels", None) or LATENT_CHANNELS)
        downscale = int(config.latent_downscale or getattr(lf, "spacial_downscale_ratio", None) or SPATIAL_DOWNSCALE)
        latent = build_latent(batch, config.width, config.height, channels, downscale).to(models.device)
        seed = _fixed_seed(config.seed)
        gen = torch.Generator(device=models.device).manual_seed(seed)
        noise = torch.randn(latent.shape, generator=gen, device=models.device, dtype=torch.float32)

        # 3. 采样
        if on_progress:
            on_progress(SAMPLING_PCT_START, "Sampling...", {})
        cancel_flag = cancel_flag if cancel_flag is not None else [False]
        steps = max(1, config.steps)
        # 采样器/调度器按引擎下发（Z-Image 常量仅作缺省回退）：
        # Flux.2 Klein 等架构族不通用于 Z-Image 的 dpmpp_3m_sde_gpu / sgm_uniform，
        # 实测可用组合为 euler / simple（见 scripts/preflight_flux2_klein.py）。
        scheduler_name = getattr(config, "scheduler", None) or ZIMAGE_SCHEDULER
        sampler_name = getattr(config, "sampler", None) or ZIMAGE_SAMPLER
        logger.info("native sampling: sampler=%s scheduler=%s steps=%s", sampler_name, scheduler_name, steps)
        sigmas = comfy.samplers.calculate_sigmas(models.model_sampling, scheduler_name, steps)
        sampler_obj = comfy.samplers.sampler_object(sampler_name)
        callback = _make_sampling_callback(steps, on_progress, cancel_flag)
        sampled = comfy.samplers.sample(
            models.model,
            noise,
            positive,
            negative,
            config.cfg,
            models.device,
            sampler_obj,
            sigmas,
            latent_image=latent,
            callback=callback,
            seed=seed,
        )

        # 4. VAE 解码
        if on_progress:
            on_progress(95, "Decoding...", {})
        images = _vae_decode(models.vae, sampled)
        if on_progress:
            on_progress(100, "Completed", {})

        # images: (B,H,W,3) in [0,1]
        return [images[i] for i in range(images.shape[0])]
    finally:
        # 尽力清理显存，避免影响后续任务
        try:
            import comfy.model_management

            comfy.model_management.soft_empty_cache()
        except Exception as e:  # pragma: no cover - 环境相关
            logger.warning("soft_empty_cache failed: %s", e)


def tentative_vram_gb(width: int, height: int, batch_size: int) -> float:
    """粗略估算本 PoC 推理的显存占用（供 load 阶段上报，非精确）。"""
    pixels = width * height * batch_size
    return max(1.0, round_pixels(pixels) / 1e9 * 0.5)


def round_pixels(pixels: int) -> int:
    """把像素数向上取整为 8 的倍数（对齐 latent 下采样对齐）。"""
    return int(math.ceil(pixels / 8.0) * 8.0)
