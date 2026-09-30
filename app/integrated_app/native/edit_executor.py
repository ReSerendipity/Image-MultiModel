"""
native/edit_executor.py — 进程内图像编辑（Qwen-Image 2.1 Edit）

评估报告 P1 的落地实现：把本地实测工作流 `workflows/blueprints/Edit/qwen_2_1_edit.json`
的**子图**（`Image Edit (Qwen Image 2.1)`，9 个内部节点）按代码复刻，不依赖外部 ComfyUI 进程。

节点 → 代码映射（蓝图节点 id 见 `workflows/blueprints/manifest.json`）：

| 蓝图节点 | 代码 |
|---|---|
| `UNETLoader` (451) `qwen_image_2.1_int8_convrot` | `_load_models(...)`（`comfy.sd.load_diffusion_model`） |
| `CLIPLoader` (453) `qwen3vl_8b_int8_convrot` + type `qwen_image` | `_load_models(...)`（`clip_type="qwen_image"` → 内核映射到 `text_encoders.qwen_image21`） |
| `VAELoader` (454) `qwen_image_2.1_vae_bf16` | `_load_models(...)`（64 latent 通道 / 下采样 16） |
| `TextEncodeQwenImage21` (474) | `encode_reference()`（参考图 → VAE latent + CLIP image slots） |
| `QwenImage21Cache` (469) | `apply_prefix_cache()`（KV 前缀缓存 device/dtype） |
| `ComfySwitchNode` (468) + `EmptyLatentImage` (456) | `build_edit_latent()`（**尺寸取参考图**，见下方注） |
| `KSampler` (458) | `edit()` 内 `comfy.samplers.sample`（euler / simple / denoise 1） |
| `VAEDecode` (457) | `comfy.sd.VAE.decode` |

⚠️ **latent 尺寸必须等于参考图（缩放后）尺寸**，不能用用户传的 width/height：
蓝图里 `TextEncodeQwenImage21` 的 latent 输出工具提示原文 —— "Empty latent on the first
reference image's size, to match with sampling as any other size shifts the edit."
（换尺寸会让编辑结果整体偏移）。故 `width/height` 在本路径下由参考图推导，用户值仅作
`resolution` 的兜底。

⚠️ 本模块**只支持内核 ≥ v0.37.0**（Qwen-Image 2.1 支持由上游 `6bfaacc6` 引入，
见 `comfy_kernel/UPGRADE_STRATEGY.md`）。旧内核会在 `load_diffusion_model` 阶段
报 `Could not detect model type`，本模块把它转成可读错误。
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any

import torch

from ..engine_interface import GenerationConfig, ProgressCallback
from . import executor, source

logger = logging.getLogger(__name__)

# ── 蓝图实证参数（qwen_2_1_edit.json 子图节点 458 / 474 / 469）────
EDIT_SAMPLER = "euler"
EDIT_SCHEDULER = "simple"
EDIT_RESOLUTION = 1024  # TextEncodeQwenImage21 的 resolution（参考图缩放到 ~1024²）
EDIT_LATENT_CHANNELS = 64  # Qwen-Image 2.1 VAE 输出通道
EDIT_LATENT_DOWNSCALE = 16  # Qwen-Image 2.1 VAE 空间下采样比
EDIT_ALIGN = 32  # 参考图尺寸对齐粒度
# 参考图上限：9 张与蓝图 image_1..image_10 对齐（实际取前 N 张）
EDIT_MAX_REFERENCES = 9


def _load_reference_tensor(path: str | Path) -> torch.Tensor:
    """把参考图解码为 ``[1, H, W, 3]`` 的 [0,1] RGB 张量。

    对齐 `native/seedvr.py::_image_bytes_to_tensor` 的既有惯例：**先魔数校验再解码**
    （阻断伪装成图片的非图片数据），失败一律抛 ValueError 由上层转成任务失败。
    """
    from PIL import Image

    from ..security.magic_check import validate_image_magic

    raw = Path(path).read_bytes()
    is_magic, _, error = validate_image_magic(raw)
    if not is_magic:
        raise ValueError(f"参考图魔数校验失败: {error}")

    import io

    img: Image.Image = Image.open(io.BytesIO(raw))
    img.verify()
    img = Image.open(io.BytesIO(raw))
    if img.mode != "RGB":
        img = img.convert("RGB")

    import numpy as np

    arr = np.asarray(img).astype("float32") / 255.0
    return torch.from_numpy(arr)[None, ...]  # [1,H,W,3]


def reference_target_size(width: int, height: int, resolution: int = EDIT_RESOLUTION) -> tuple[int, int]:
    """按蓝图语义把参考图尺寸规整到 ``resolution`` 量级、32 的倍数、保持长宽比。

    resolution<=0 时按原图尺寸对齐到 32 的倍数（蓝图 resolution=0 的语义）。
    """
    if resolution > 0:
        ratio = width / max(1, height)
        w = round(math.sqrt(resolution * resolution * ratio) / EDIT_ALIGN) * EDIT_ALIGN
        h = round(math.sqrt(resolution * resolution / ratio) / EDIT_ALIGN) * EDIT_ALIGN
    else:
        w = round(width / EDIT_ALIGN) * EDIT_ALIGN
        h = round(height / EDIT_ALIGN) * EDIT_ALIGN
    return max(EDIT_ALIGN, w), max(EDIT_ALIGN, h)


def build_edit_latent(width: int, height: int, batch_size: int = 1) -> torch.Tensor:
    """构造编辑起始 latent（全零，尺寸由参考图决定）。

    全零对齐蓝图 `TextEncodeQwenImage21` 的 latent 输出（``torch.zeros([1, 64, h//16, w//16])``）；
    denoise=1 下数值不参与，**尺寸**才决定编辑是否偏移。
    """
    shape = [max(1, batch_size), EDIT_LATENT_CHANNELS, height // EDIT_LATENT_DOWNSCALE, width // EDIT_LATENT_DOWNSCALE]
    return torch.zeros(shape, dtype=torch.float32)


def apply_prefix_cache(model: Any, device: str = "auto", dtype: str = "default") -> Any:
    """复刻蓝图 `QwenImage21Cache` 节点：给模型 clone 打上 KV 前缀缓存选项。

    编辑场景下前缀（参考图 latent 的 KV）每步都相同，缓存能显著省显存/时间；
    ``device="auto"`` 表示优先用空闲显存、其次内存（蓝图默认值）。
    """
    try:
        import comfy.model_management  # noqa: F401

        m = model.clone()
        m.model_options.setdefault("transformer_options", {})
        m.model_options["transformer_options"]["qwen_image21_cache"] = {"device": device, "dtype": dtype}
        return m
    except Exception as e:  # noqa: BLE001 — 缓存是优化项，失败不阻断编辑
        logger.warning("QwenImage21Cache 选项设置失败（忽略，按未缓存运行）: %s", e)
        return model


def encode_reference(
    clip: Any,
    vae: Any,
    image: torch.Tensor,
    prompt: str,
    negative_prompt: str,
    resolution: int = EDIT_RESOLUTION,
) -> tuple[list[Any], list[Any], int, int]:
    """复刻蓝图 `TextEncodeQwenImage21.execute`。

    Args:
        clip: 已加载的 Qwen3-VL-8B CLIP（clip_type=qwen_image → qwen_image21 tokenizer）
        vae: Qwen-Image 2.1 VAE（64 通道 / 下采样 16）
        image: ``[1, H, W, 3]`` 的 [0,1] RGB 参考图张量
        prompt: 编辑指令（不是"从零生成"的描述）
        negative_prompt: 负向提示词
        resolution: 参考图缩放目标边长

    Returns:
        ``(positive, negative, width, height)`` —— 条件已带 ``reference_latents``，
        width/height 为参考图规整后的实际尺寸（latent 尺寸据此推导）。
    """
    import comfy.utils
    import node_helpers

    samples = image[:1].movedim(-1, 1)  # [1,3,H,W]
    width, height = reference_target_size(samples.shape[3], samples.shape[2], resolution)

    if (width, height) == (samples.shape[3], samples.shape[2]):
        resized = image[:1]
    else:
        resized = comfy.utils.common_upscale(samples, width, height, "lanczos", "disabled").movedim(1, -1)

    rgb = resized[:, :, :, :3]
    if resized.shape[-1] > 3:
        # 视觉塔看的是"白底叠加 alpha"，VAE 保留全部通道 —— 与上游节点一致
        rgb = rgb * resized[:, :, :, 3:] + (1.0 - resized[:, :, :, 3:])

    ref_latents = [vae.encode(resized)]
    # 有 VAE 参考 latent 时视觉塔不再看图（keep_vision=False），图以 latent 形式拼接进序列
    keep_vision = False

    positive = clip.encode_from_tokens_scheduled(
        clip.tokenize(prompt, images=[rgb], keep_vision=keep_vision, prevent_empty_text=True)
    )
    negative = clip.encode_from_tokens_scheduled(
        clip.tokenize(negative_prompt, images=[rgb], keep_vision=keep_vision, prevent_empty_text=True)
    )
    positive = node_helpers.conditioning_set_values(positive, {"reference_latents": ref_latents}, append=True)
    negative = node_helpers.conditioning_set_values(negative, {"reference_latents": ref_latents}, append=True)
    return positive, negative, width, height


def _load_edit_models(model_paths: dict[str, str], comfy_root: str | None = None) -> executor.NativeModels:
    """加载编辑三件套（unet / text_encoder / vae），CLIP 显式按 ``qwen_image`` 类型加载。

    `executor._load_models` 走 CLIP 自动检测，对 Qwen3-VL-8B 会落到通用 qwen3vl 分支；
    编辑必须落到 `text_encoders.qwen_image21`（才有 image slots / keep_vision 语义），
    故此处显式传 ``clip_type="qwen_image"``。
    """
    models = executor._load_models(model_paths, comfy_root=comfy_root)
    te_path = model_paths.get("text_encoder")
    if te_path:
        import comfy.sd

        try:
            models.clip = comfy.sd.load_clip([te_path], clip_type="qwen_image")
        except Exception as e:  # noqa: BLE001 — 回落自动检测并告警（可能不支持编辑语义）
            logger.warning("CLIP 按 qwen_image 类型加载失败，回落自动检测（编辑语义可能不完整）: %s", e)
    return models


def edit(
    config: GenerationConfig,
    model_paths: dict[str, str],
    init_image_path: str | Path,
    on_progress: ProgressCallback | None = None,
    comfy_root: str | None = None,
    cancel_flag: list[bool] | None = None,
    cache_device: str = "auto",
    cache_dtype: str = "default",
    resolution: int = EDIT_RESOLUTION,
) -> list[torch.Tensor]:
    """进程内图像编辑（同步阻塞，供 async 层包在 executor 线程中调用）。

    Args:
        config: 生图配置；本路径使用 ``positive_prompt``（编辑指令）/ ``negative_prompt`` /
            ``steps`` / ``cfg`` / ``seed`` / ``batch_size``。
            **``width`` / ``height`` 被忽略**（尺寸由参考图推导，见模块文档注）。
        model_paths: unet / text_encoder / vae 绝对路径映射
        init_image_path: 参考图本地路径（须已过 PathGuard）
        on_progress: 进度回调 (pct, phase, extra)
        comfy_root: Comfy 源码根目录
        cancel_flag: 长度 1 列表，采样中置 True 抛 CancelledError 取消

    Returns:
        list[torch.Tensor]，每张为 [0,1] 范围 RGB 张量 (H,W,3)
    """
    if on_progress:
        on_progress(5, "Loading native models...", {})
    models = _load_edit_models(model_paths, comfy_root=comfy_root)
    models.model = apply_prefix_cache(models.model, cache_device, cache_dtype)

    import comfy.samplers

    try:
        # 1. 参考图 → latent + 条件
        if on_progress:
            on_progress(10, "Encoding reference image...", {})
        image = _load_reference_tensor(init_image_path)
        positive, negative, ref_w, ref_h = encode_reference(
            models.clip,
            models.vae,
            image,
            config.positive_prompt,
            config.negative_prompt,
            resolution=resolution,
        )

        # 2. 起始 latent（尺寸 = 参考图，全零）
        batch = max(1, config.batch_size)
        latent = build_edit_latent(ref_w, ref_h, batch).to(models.device)
        seed = executor._fixed_seed(config.seed)
        gen = torch.Generator(device=models.device).manual_seed(seed)
        noise = torch.randn(latent.shape, generator=gen, device=models.device, dtype=torch.float32)

        # 3. 采样（euler / simple / denoise=1，对齐蓝图 KSampler）
        if on_progress:
            on_progress(executor.SAMPLING_PCT_START, "Sampling...", {})
        cancel_flag = cancel_flag if cancel_flag is not None else [False]
        steps = max(1, config.steps)
        sigmas = comfy.samplers.calculate_sigmas(models.model_sampling, EDIT_SCHEDULER, steps)
        sampler_obj = comfy.samplers.sampler_object(EDIT_SAMPLER)
        callback = executor._make_sampling_callback(steps, on_progress, cancel_flag)
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
        images = executor._vae_decode(models.vae, sampled)
        if on_progress:
            on_progress(100, "Completed", {})
        # 编辑路径的输出携带梯度图（reference_latents 追加在 conditioning 上，
        # 与 txt2img 的 no_grad 上下文不同），落盘前必须 detach，否则
        # `_save_outputs` 的 numpy/PIL 转换会报 "Can't call numpy() on Tensor
        # that requires grad"
        return [images[i].detach() for i in range(images.shape[0])]
    finally:
        try:
            import comfy.model_management

            comfy.model_management.soft_empty_cache()
        except Exception as e:  # pragma: no cover - 环境相关
            logger.warning("soft_empty_cache failed: %s", e)


def check_kernel_support() -> tuple[bool, str]:
    """检查当前内核是否支持 Qwen-Image 2.1 编辑；返回 ``(ok, 原因)``。

    内核 < v0.37.0（上游 `6bfaacc6` 之前）缺少 `comfy/ldm/qwen_image21/`，
    表现为 `Could not detect model type` —— 这个报错对用户毫无信息量，
    故在装配/加载阶段就给出可读结论。

    注意：**不需要**先 `source.ensure_loaded()` —— 这里只看磁盘上的内核文件，
    因此在应用装配期（引擎尚未装载）也能给出正确结论。
    """
    try:
        loaded = source.get_comfy_root()
        root = Path(loaded) if loaded else source._default_comfy_root()
        if not (root / "comfy" / "ldm" / "qwen_image21" / "model.py").is_file():
            return False, (
                "当前 vendored 内核不支持 Qwen-Image 2.1 编辑（缺少 comfy/ldm/qwen_image21/）。"
                "需升级到内核 ≥ v0.37.0，见 comfy_kernel/UPGRADE_STRATEGY.md"
            )
        return True, ""
    except Exception as e:  # noqa: BLE001
        return False, f"内核能力探测失败: {e}"
