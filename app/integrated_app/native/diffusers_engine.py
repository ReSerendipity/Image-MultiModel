"""
diffusers_engine.py — ZImageDiffusersEngine（M8 diffusers 迁移）

基于 HuggingFace diffusers ZImagePipeline 的原生引擎实现。
替代 comfy_kernel 复用方案，消除 GPL-3.0 许可依赖。

实现 ImageEngine Protocol：is_ready / load / unload / infer_txt2img / cancel

架构对齐：
- TTS_MultiModel 引擎模式（声明式配置 + 懒导入）
- Seedvr2 Toolkit 独立推理模式（无 ComfyUI 依赖）

模型加载策略：
1. 优先从本地模型目录加载（portable/shared 双模式）
2. 本地目录不存在时，提示用户下载官方模型仓库
"""

from __future__ import annotations

import logging
import os
import random
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import get_config
from ..engine_interface import GenerationConfig, ProgressCallback
from ..security.path_guard import PathGuard
from . import output_pipeline

logger = logging.getLogger(__name__)

# 采样阶段 -> i18n 阶段键
PHASE_KEY_MAP = {
    "Loading model...": "phase_loading_model",
    "Encoding prompts...": "phase_encoding",
    "Sampling...": "phase_sampling",
    "Decoding...": "phase_decoding",
    "Post-processing...": "phase_postprocessing",
    "Completed": "phase_completed",
}


def _map_phase(phase_text: str) -> str:
    """把引擎阶段文案映射为 i18n 键。"""
    if phase_text in PHASE_KEY_MAP:
        return PHASE_KEY_MAP[phase_text]
    if phase_text.startswith("Sampling"):
        return "phase_sampling"
    return phase_text


class ZImageDiffusersEngine:
    """Z-Image diffusers 引擎（M8 新引擎，Apache-2.0）

    基于 HuggingFace diffusers ZImagePipeline 实现文生图推理。
    与 NativeEngine（comfy_kernel 复用）相比：
    - 无需 comfy_kernel/ 目录，消除 GPL-3.0 许可依赖
    - 直接从 diffusers 加载完整模型目录（model_index.json + components）
    - 支持 LoRA 栈注入（PEFT 接口）
    - 支持 SeedVR2 后处理超分
    """

    def __init__(
        self,
        name: str,
        display_name: str = "",
        display_name_en: str = "",
        config: dict[str, Any] | None = None,
    ) -> None:
        self._name = name
        self._display_name = display_name or name
        self._display_name_en = display_name_en or name
        self._config = config or {}
        self._ready = False
        self._cancel_requested = False
        self._pipe: Any = None
        self._model_dir: Path | None = None

    # ── 协议属性 ────────────────────────────────────────────
    @property
    def name(self) -> str:
        return self._name

    @property
    def display_name(self) -> str:
        return self._display_name

    def is_ready(self) -> bool:
        return self._ready and self._pipe is not None

    # ── 协议方法 ────────────────────────────────────────────
    async def load(self, on_progress: ProgressCallback | None = None) -> None:
        """加载 diffusers 管线到 GPU。

        步骤：
        1. 解析模型目录路径（portable/shared 双模式）
        2. 使用 ZImagePipeline.from_pretrained() 加载
        3. 选择精度（bf16 / fp8 fallback）
        """
        if on_progress:
            on_progress(5, _map_phase("Loading model..."), {})

        cfg = get_config()
        engine_cfg = cfg.models.engines.get(self._name)
        if engine_cfg is None:
            raise RuntimeError(f"Engine '{self._name}' not found in config.models.engines")

        # 解析本地模型目录
        local_model_dir = engine_cfg.local_model_dir or ""
        if not local_model_dir:
            raise RuntimeError(
                f"Engine '{self._name}' requires 'local_model_dir' in config. "
                f"Please download the diffusers-format model from HuggingFace: {engine_cfg.model_id}"
            )

        # portable 模式：model/{local_model_dir}
        # shared 模式：{comfy_models_dir}/{local_model_dir}
        if cfg.models.model_source_mode == "portable":
            base_dir = Path(cfg.project_root) / cfg.models.portable.internal_models_dir
        else:
            base_dir = (
                Path(cfg.models.shared.comfy_models_dir)
                if cfg.models.shared.comfy_models_dir
                else Path(cfg.project_root)
            )

        self._model_dir = base_dir / local_model_dir

        if not self._model_dir.exists():
            raise RuntimeError(
                f"Model directory not found: {self._model_dir}\n"
                f"Please download the diffusers-format model:\n"
                f"  huggingface-cli download {engine_cfg.model_id} --local-dir {self._model_dir}\n"
                f"Or use a mirror: modelscope download --model {engine_cfg.model_id} --local_dir {self._model_dir}"
            )

        # 导入 diffusers（懒导入，避免启动时重型依赖阻塞）
        import torch
        from diffusers import ZImagePipeline

        # 选择精度（默认 bf16，可配置 fallback_precision）
        precision = getattr(engine_cfg, "default_precision", "bf16")
        if precision == "fp8":
            # fp8 需要 torch 2.1+ 且 GPU 支持
            if not hasattr(torch, "float8_e4m3fn"):
                logger.warning("FP8 not supported on this torch version, falling back to bf16")
                precision = "bf16"

        dtype = torch.float8_e4m3fn if precision == "fp8" else torch.bfloat16

        if on_progress:
            on_progress(20, _map_phase("Loading model..."), {})

        # 加载管线（local_files_only=True 确保离线模式）
        try:
            self._pipe = ZImagePipeline.from_pretrained(
                str(self._model_dir),
                torch_dtype=dtype,
                local_files_only=True,
            )
        except Exception as e:
            logger.error(f"Failed to load ZImagePipeline from {self._model_dir}: {e}")
            raise RuntimeError(
                f"Failed to load diffusers pipeline from {self._model_dir}. "
                f"Ensure the directory contains model_index.json and all components. "
                f"Error: {e}"
            ) from e

        if on_progress:
            on_progress(50, _map_phase("Loading model..."), {})

        # GPU 内存优化
        device = "cuda" if torch.cuda.is_available() else "cpu"
        if device == "cuda":
            # bf16 模式：直接 to("cuda")
            # fp8 模式：使用 enable_model_cpu_offload() 减少显存峰值
            if precision == "fp8":
                self._pipe.enable_model_cpu_offload()
                logger.info("Enabled CPU offload for FP8 mode")
            else:
                self._pipe.to(device)
                logger.info("Moved pipeline to CUDA (bf16)")
        else:
            logger.warning("CUDA not available, running on CPU (very slow)")

        if on_progress:
            on_progress(100, _map_phase("Completed"), {})

        self._ready = True
        logger.info(f"ZImageDiffusersEngine '{self._name}' loaded from {self._model_dir}")

    async def unload(self) -> None:
        """卸载引擎：释放 GPU 显存并标记未就绪。"""
        if self._pipe is not None:
            try:
                del self._pipe
                self._pipe = None
                # 强制清理 GPU 缓存
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    logger.info("CUDA cache cleared")
            except Exception as e:
                logger.warning(f"Error during unload: {e}")

        # 卸载 SeedVR2（如果已加载，避免显存泄漏）
        try:
            from ..services.seedvr2_service import get_seedvr2_service

            svr = get_seedvr2_service()
            if svr.is_loaded:
                await svr.unload()
        except Exception as e:
            logger.debug(f"SeedVR2 unload skipped: {e}")

        self._ready = False
        self._model_dir = None
        logger.info(f"ZImageDiffusersEngine '{self._name}' unloaded")

    async def infer_edit(
        self,
        config: GenerationConfig,
        on_progress: ProgressCallback | None = None,
    ) -> list[str]:
        """diffusers 后端暂不支持编辑（P1 编辑走 NativeEngine/Qwen-Image 2.1）。"""
        raise NotImplementedError("diffusers engine does not support image editing")

    async def infer_txt2img(
        self,
        config: GenerationConfig,
        on_progress: ProgressCallback | None = None,
    ) -> list[str]:
        """执行文生图推理，返回输出图像绝对路径列表。

        步骤：
        1. 参数映射（GenerationConfig → diffusers Pipeline kwargs）
        2. LoRA 栈注入（如果配置了 lora_stack）
        3. 生成图像（ZImagePipeline.__call__）
        4. 后处理（SeedVR2 超分，如果启用）
        5. 保存输出（水印 + 缩略图）
        """
        if not self._ready or self._pipe is None:
            raise RuntimeError("Diffusers engine not ready, please load first")

        self._cancel_requested = False

        if on_progress:
            on_progress(10, _map_phase("Encoding prompts..."), {})

        # ── 1. LoRA 栈注入 ──
        lora_stack = config.effective_lora_stack()
        if lora_stack:
            await self._apply_lora_stack(lora_stack, on_progress)

        # ── 2. 构建 diffusers 参数 ──
        import torch

        # seed 处理：-1 表示随机，否则使用固定种子
        seed = config.seed if config.seed >= 0 else random.randint(0, 2**32 - 1)
        generator = torch.Generator(device="cpu").manual_seed(seed)

        # 采样步数（默认 50，但 Turbo 模型通常用 4-8 步）
        num_inference_steps = config.steps if config.steps > 0 else 50

        # guidance_scale（默认 5.0，但 Turbo 模型通常用 1.0-3.0）
        guidance_scale = config.cfg if config.cfg > 0 else 5.0

        if on_progress:
            on_progress(20, _map_phase("Sampling..."), {})

        # ── 3. 调用 diffusers 管线 ──
        try:
            outputs = self._pipe(
                prompt=config.positive_prompt,
                negative_prompt=config.negative_prompt if config.negative_prompt else None,
                width=config.width,
                height=config.height,
                num_inference_steps=num_inference_steps,
                guidance_scale=guidance_scale,
                num_images_per_prompt=config.batch_size,
                generator=generator,
                output_type="pil",
            )
        except Exception as e:
            logger.error(f"ZImagePipeline inference failed: {e}")
            raise RuntimeError(f"Diffusers inference failed: {e}") from e

        if on_progress:
            on_progress(80, _map_phase("Decoding..."), {})

        # ── 4. 后处理（SeedVR2 超分）──
        images = outputs.images  # list[PIL.Image.Image]
        if config.seedvr2_enable and config.seedvr2_resolution > config.width:
            images = await self._apply_seedvr2_upscale(
                images,
                config.seedvr2_resolution,
                config.seedvr2_color_correction,
                on_progress,
            )

        if on_progress:
            on_progress(95, _map_phase("Post-processing..."), {})

        # ── 5. 保存输出 ──
        saved_paths = self._save_outputs(images, config, seed)

        if on_progress:
            on_progress(100, _map_phase("Completed"), {})

        return saved_paths

    async def cancel(self) -> None:
        """取消当前推理（置位取消标志）。"""
        self._cancel_requested = True
        logger.info(f"ZImageDiffusersEngine '{self._name}' cancel requested")

    # ── 内部辅助 ────────────────────────────────────────────
    async def _apply_lora_stack(
        self,
        lora_stack: list[dict],
        on_progress: ProgressCallback | None = None,
    ) -> None:
        """注入 LoRA 栈到管线。

        使用 diffusers PEFT 接口：load_lora_weights() + set_adapters()

        Args:
            lora_stack: [{"name": "lora_path", "strength": 0.8}, ...]
            on_progress: 进度回调
        """
        logger.info(f"Applying LoRA stack: {len(lora_stack)} layers")

        cfg = get_config()
        # LoRA 路径解析（相对于 portable.loras 或 shared.loras）
        if cfg.models.model_source_mode == "portable":
            lora_base = (
                Path(cfg.project_root)
                / cfg.models.portable.internal_models_dir
                / cfg.models.portable.sub_dirs.get("lora", "loras")
            )
        else:
            lora_base = (
                Path(cfg.models.shared.comfy_models_dir) / cfg.models.shared.mount_map.get("lora", "loras")
                if cfg.models.shared.comfy_models_dir
                else Path(cfg.project_root) / "loras"
            )

        adapter_names = []
        adapter_weights = []

        for i, lora_cfg in enumerate(lora_stack):
            lora_name = lora_cfg.get("name", "")
            lora_strength = lora_cfg.get("strength", 1.0)

            if not lora_name:
                continue

            # 解析 LoRA 文件路径
            lora_path = lora_base / lora_name
            if not lora_path.exists():
                logger.warning(f"LoRA file not found: {lora_path}, skipping")
                continue

            # MLOps P0-1: 加载前完整性校验（损坏/非白名单格式拒绝或告警跳过）
            try:
                from ..security.weight_integrity import (
                    WeightIntegrityError,
                    resolve_expected_sha256,
                    verify_weight_before_load,
                )

                mfmt = cfg.security.model_format
                if mfmt.verify_weights:
                    # 期望 hash 从清单解析；未登记权重走 allow_unregistered_weights 策略
                    expected_sha256, registered = resolve_expected_sha256(str(lora_path), cfg)
                    if not registered and not mfmt.allow_unregistered_weights:
                        msg = f"LoRA '{lora_name}' 未在完整性清单登记，且 allow_unregistered_weights=false: {lora_path}"
                        if mfmt.fail_closed_on_corrupt_weight:
                            raise WeightIntegrityError(msg)
                        logger.warning("%s，跳过该层", msg)
                        continue
                    res = verify_weight_before_load(
                        str(lora_path),
                        expected_sha256=expected_sha256,
                        allow_non_safetensors=not mfmt.only_safetensors,
                    )
                    if not res.ok:
                        msg = f"LoRA '{lora_name}' 完整性校验失败: {res.error}"
                        if mfmt.fail_closed_on_corrupt_weight:
                            raise WeightIntegrityError(msg)
                        logger.warning("%s，跳过该层", msg)
                        continue
            except WeightIntegrityError:
                raise
            except Exception as e:  # noqa: BLE001 - 校验异常不阻断
                logger.warning("LoRA 校验异常（已放行）: %s", e)

            adapter_name = f"lora_{i}"
            try:
                self._pipe.load_lora_weights(str(lora_path), adapter_name=adapter_name)
                adapter_names.append(adapter_name)
                adapter_weights.append(lora_strength)
                logger.debug(f"Loaded LoRA: {lora_name} (strength={lora_strength})")
            except Exception as e:
                logger.warning(f"Failed to load LoRA {lora_name}: {e}")

        # 激活所有 adapter
        if adapter_names:
            try:
                self._pipe.set_adapters(adapter_names, adapter_weights)
                logger.info(f"Activated {len(adapter_names)} LoRA adapters")
            except Exception as e:
                logger.warning(f"Failed to set adapters: {e}")

    async def _apply_seedvr2_upscale(
        self,
        images: list[Any],
        target_resolution: int,
        color_correction: str,
        on_progress: ProgressCallback | None = None,
    ) -> list[Any]:
        """使用 SeedVR2 后处理超分（集成 SeedVR2Service）。

        生命周期管理：
        1. 首次调用时懒加载 SeedVR2 模型（不影响冷启动）
        2. 逐张图片超分（临时保存到磁盘，SeedVR2 接口要求文件路径）
        3. 超分完成后自动卸载 SeedVR2（释放显存给主引擎）

        Args:
            images: list[PIL.Image.Image]
            target_resolution: 目标分辨率（长边）
            color_correction: 色彩校正模式（"lab" / "none"）
            on_progress: 进度回调

        Returns:
            超分后的图像列表（PIL.Image.Image）
        """
        from PIL import Image

        if on_progress:
            on_progress(85, _map_phase("Post-processing..."), {"seedvr2": "starting"})

        try:
            from ..services.seedvr2_service import get_seedvr2_service

            svr = get_seedvr2_service()
            if not svr.available:
                logger.warning("SeedVR2-lite not installed, skipping upscale")
                return images

            # 懒加载模型（首次调用时才加载）
            cfg = get_config()
            await svr.ensure_loaded(
                model_size="3b",
                precision="fp16",
                project_root=cfg.project_root,
            )

            upscaled = []
            total = len(images)
            for i, img in enumerate(images):
                if on_progress:
                    pct = 85 + int(5 * (i + 1) / total)
                    on_progress(
                        pct,
                        _map_phase("Post-processing..."),
                        {
                            "seedvr2": f"upscaling {i + 1}/{total}",
                        },
                    )

                # SeedVR2 接口要求文件路径 → 临时保存
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                    img.save(tmp.name, format="PNG")
                    tmp_path = tmp.name

                try:
                    output_path = await svr.upscale_single(
                        image_path=tmp_path,
                        target_resolution=target_resolution,
                        color_correction=color_correction,
                        seed=self._last_seed if hasattr(self, "_last_seed") else -1,
                    )
                    upscaled.append(Image.open(output_path).copy())
                finally:
                    # 清理临时文件
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass

            if on_progress:
                on_progress(90, _map_phase("Post-processing..."), {"seedvr2": "completed"})

            return upscaled
        except Exception as e:
            logger.warning(f"SeedVR2 upscale failed: {e}, returning original images")
            return images

    def _save_outputs(
        self,
        images: list[Any],
        config: GenerationConfig,
        seed: int,
    ) -> list[str]:
        """保存输出图像（水印 + 缩略图）。

        输出命名：outputs/{engine}/{date}/{taskid}_{seed}_{idx}.png

        Args:
            images: list[PIL.Image.Image]
            config: GenerationConfig
            seed: 实际使用的种子

        Returns:
            保存的相对路径列表（相对 outputs/ 目录）
        """
        cfg = get_config()
        guard = PathGuard(cfg.security.allowed_base_dirs, cfg.project_root)

        date_str = datetime.now().strftime("%Y%m%d")
        engine_dir = guard.ensure_dir(Path(cfg.output.base_dir) / self._name / date_str)
        task_id = config.workflow_sha256 or f"{int(time.time() * 1000):016x}"

        wm_enabled = cfg.watermark.enabled_in_code
        product_id = cfg.watermark.product_id
        watermark_failure_mode = cfg.watermark.failure_mode
        thumb_enabled = cfg.output.save_thumbnail
        thumb_max_side = cfg.output.thumbnail_max_side
        thumb_dir: Path | None = None
        if thumb_enabled:
            thumb_dir = guard.ensure_dir(Path("data") / "cache" / "thumbs")

        saved: list[str] = []
        # 数据治理 P1-4：生成参数写入 PNG tEXt（水印后嵌入，防剥离）
        metadata = output_pipeline.build_generation_metadata(task_id, config, self._name)
        for idx, img in enumerate(images):
            # 命名：{taskid}_{seed}_{idx}.png
            # P1-2 显式 AI 生成标识：与 native 引擎同款后缀（config.output 可关闭）
            _lbl = cfg.output.explicit_ai_label_suffix if cfg.output.explicit_ai_label else ""
            fname = f"{task_id[:16]}_{seed}_{idx}{_lbl}.png"
            path = engine_dir / fname
            output_pipeline.finalize_output(
                path,
                img,
                is_tensor=False,
                wm_enabled=wm_enabled,
                product_id=product_id,
                task_id=task_id[:16],
                thumb_enabled=thumb_enabled,
                thumb_dir=thumb_dir,
                thumb_name=f"{task_id[:16]}_{seed}_{idx}_thumb.png",
                thumb_max_side=thumb_max_side,
                metadata=metadata,
                watermark_failure_mode=watermark_failure_mode,
            )

            # 存相对路径（相对 outputs/ 目录），供前端 /api/outputs/<rel> 直接访问
            base = (Path(cfg.project_root) / cfg.output.base_dir).resolve()
            rel = str(path.relative_to(base)).replace("\\", "/")
            saved.append(rel)

            # ── EsEs 双图对比（M9）──
            # 当 batch > 1 且启用 EsEs 时，生成第一张与当前张的对比图
            if config.eses_enable and len(images) > 1 and idx > 0:
                compare_img = output_pipeline.generate_compare_image(
                    images[0],
                    img,
                    config.eses_compare_axis,
                )
                compare_fname = f"{task_id[:16]}_{seed}_{idx}_compare.png"
                compare_path = engine_dir / compare_fname
                output_pipeline.finalize_output(
                    compare_path,
                    compare_img,
                    is_tensor=False,
                    wm_enabled=wm_enabled,
                    product_id=product_id,
                    task_id=task_id[:16],
                    thumb_enabled=thumb_enabled,
                    thumb_dir=thumb_dir,
                    thumb_name=f"{task_id[:16]}_{seed}_{idx}_compare_thumb.png",
                    thumb_max_side=thumb_max_side,
                    metadata=metadata,
                    watermark_failure_mode=watermark_failure_mode,
                )

                compare_rel = str(compare_path.relative_to(base)).replace("\\", "/")
                saved.append(compare_rel)

        return saved
