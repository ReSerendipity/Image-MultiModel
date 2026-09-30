"""
native/engine.py — NativeEngine（ImageEngine 进程内引擎实现）

在应用进程内复用本地 Comfy 源码直接推理，不依赖外部 ComfyUI 进程。

实现 ImageEngine Protocol：is_ready / load / unload / infer_txt2img / cancel。
Phase 1 保证：出图 + 保存 + DCT 水印 + 缩略图。
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import get_config
from ..config_models import resolve_engine_model_paths
from ..engine_interface import GenerationConfig, ProgressCallback
from ..security.path_guard import PathGuard
from . import edit_executor, executor, output_pipeline

logger = logging.getLogger(__name__)

# 采样阶段 -> i18n 阶段键（与 comfy/engine.py 风格一致）
PHASE_KEY_MAP = {
    "Loading native models...": "phase_loading_workflow",
    "Encoding prompts...": "phase_patching",
    "Sampling...": "phase_sampling",
    "Decoding...": "phase_sampling",
    "Completed": "phase_completed",
}


def _map_phase(phase_text: str) -> str:
    """把 executor 阶段文案映射为 i18n 键。"""
    if phase_text in PHASE_KEY_MAP:
        return PHASE_KEY_MAP[phase_text]
    if phase_text.startswith("Sampling "):
        return "phase_sampling"
    return phase_text


class NativeEngine:
    """进程内原生引擎（复用本地 Comfy 源码推理）。"""

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
        self._model_paths: dict[str, str] = {}
        self._thumbnail_path = ""

    # ── 协议属性 ────────────────────────────────────────────
    @property
    def name(self) -> str:
        return self._name

    @property
    def display_name(self) -> str:
        return self._display_name

    def is_ready(self) -> bool:
        return self._ready

    # ── 协议方法 ────────────────────────────────────────────
    async def load(self, on_progress: ProgressCallback | None = None) -> None:
        """解析模型路径并装载 Comfy 源码（模型按需在首次推理时加载）。"""
        if on_progress:
            on_progress(10, _map_phase("Loading native models..."), {})

        cfg = get_config()
        engine_cfg = cfg.models.engines.get(self._name)
        if engine_cfg is None:
            raise RuntimeError(f"Engine '{self._name}' not found in config.models.engines")

        self._model_paths = resolve_engine_model_paths(engine_cfg, cfg.models, cfg.project_root)
        if not self._model_paths:
            raise RuntimeError(f"Engine '{self._name}' has no resolvable model paths")

        # H-02 修复：默认引擎此前完全未调用 verify_weight_before_load，
        # 导致 config 中的 verify_weights / only_safetensors 对默认引擎形同虚设。
        # 与 diffusers_engine / lora 对齐：在加载前对每个已解析的权重文件做完整性校验。
        # 模型按需在首次推理时落地，文件尚未就位（file_not_found）时跳过校验，
        # 与现有懒加载行为一致；仅当配置 fail_closed_on_corrupt_weight 时对损坏权重拒绝加载。
        mfmt = cfg.security.model_format
        if mfmt.verify_weights and self._model_paths:
            try:
                from ..security.weight_integrity import (
                    WeightIntegrityError,
                    resolve_expected_sha256,
                    verify_weight_before_load,
                )

                for role, raw in self._model_paths.items():
                    if not raw:
                        continue
                    # 期望 hash 从权重清单解析；未登记(unregistered)的权重走
                    # allow_unregistered_weights 策略（TOFU 起步期允许加载但无篡改检测）。
                    expected_sha256, registered = resolve_expected_sha256(str(raw), cfg)
                    if not registered:
                        if not mfmt.allow_unregistered_weights:
                            msg = (
                                f"引擎 '{self._name}' 权重 '{role}' 未在完整性清单登记，"
                                f"且 allow_unregistered_weights=false: {raw}"
                            )
                            if mfmt.fail_closed_on_corrupt_weight:
                                raise WeightIntegrityError(msg)
                            logger.warning("%s，跳过该权重", msg)
                            continue
                        logger.info(
                            "[NATIVE] 权重 '%s' 未在完整性清单登记，允许加载但无篡改检测: %s",
                            role,
                            raw,
                        )
                    try:
                        res = verify_weight_before_load(
                            str(raw),
                            expected_sha256=expected_sha256,
                            allow_non_safetensors=not mfmt.only_safetensors,
                        )
                    except Exception as e:  # noqa: BLE001 - 单文件校验异常不阻断
                        logger.warning("[NATIVE] 权重 '%s' 校验异常（已放行）: %s", role, e)
                        continue
                    if not res.ok:
                        if res.error == "file_not_found":
                            # 权重文件尚未就位（便携模型未下载 / 懒加载），跳过，不阻断启动
                            logger.debug("[NATIVE] 权重 '%s' 尚未就位，跳过加载前校验: %s", role, raw)
                            continue
                        msg = f"引擎 '{self._name}' 权重 '{role}' 完整性校验失败: {res.error}"
                        if mfmt.fail_closed_on_corrupt_weight:
                            raise WeightIntegrityError(msg)
                        logger.warning("%s，跳过该权重", msg)
            except WeightIntegrityError:
                raise
            except Exception as e:  # noqa: BLE001 - 校验模块不可用不阻断启动
                logger.warning("[NATIVE] 权重完整性校验初始化失败（已跳过）: %s", e)

        # 装载 Comfy 源码（幂等），不在此处加载 8B 权重
        from . import source

        comfy_root = self._config.get("comfy_source_dir") or None
        if comfy_root:
            # Gotcha #16：相对路径需拼项目根为绝对路径，避免基于进程 cwd 解析到错误位置
            p = Path(comfy_root)
            if not p.is_absolute():
                p = Path(cfg.project_root) / p
            comfy_root = str(p.resolve())
        source.ensure_loaded(comfy_root=comfy_root)

        if on_progress:
            on_progress(100, _map_phase("Completed"), {})
        self._ready = True
        logger.info("NativeEngine '%s' loaded (model paths resolved)", self._name)

    async def unload(self) -> None:
        """卸载引擎：释放缓存并标记未就绪。"""
        try:
            import comfy.model_management

            comfy.model_management.soft_empty_cache()
        except Exception as e:  # pragma: no cover - 环境相关
            logger.warning("unload cache clear failed: %s", e)
        self._ready = False
        self._model_paths = {}
        logger.info("NativeEngine '%s' unloaded", self._name)

    async def infer_txt2img(
        self,
        config: GenerationConfig,
        on_progress: ProgressCallback | None = None,
    ) -> list[str]:
        """执行进程内文生图推理，返回输出图像绝对路径列表。"""
        if not self._ready or not self._model_paths:
            raise RuntimeError("Native engine not ready, please load first")

        # 能力守卫（P1）：仅支持编辑的引擎（如 qwen_image_edit_native）走 txt2img
        # 会用错 latent 格式（2.1 是 64 通道/16 下采样，Z-Image 是 16/8）产出垃圾图，
        # 故在引擎层显式拒绝，提示用户提供参考图或换引擎。
        features = set(self._config.get("supported_features") or [])
        if "edit" in features and "txt2img" not in features:
            raise ValueError(
                f"引擎 '{self._name}' 仅支持图像编辑(edit)：请提供参考图走编辑链路，"
                "或选择支持文生图的引擎(如 z_image_turbo_native)"
            )

        self._cancel_requested = False
        cancel_flag = [False]

        def cancel_cb() -> None:
            cancel_flag[0] = True

        # P1-5 分布式追踪：推理作为独立 span，父链可来自 HTTP 根 span
        # （跨线程上下文不自动传播，故此处直接打开根 span，仅记录引擎/批次维度）
        from ..observability.tracing import get_tracer

        tracer = get_tracer("native_engine")

        # 推理为同步阻塞（线程池隔离事件循环），支持取消
        loop = asyncio.get_event_loop()
        with tracer.start_span(
            "infer_txt2img",
            attributes={
                "engine": self._name,
                "batch_size": getattr(config, "batch_size", None),
                "width": getattr(config, "width", None),
                "height": getattr(config, "height", None),
            },
        ):
            fut = loop.run_in_executor(
                None,
                lambda: executor.txt2img(config, self._model_paths, on_progress=on_progress, cancel_flag=cancel_flag),
            )

            # 注册取消：内部标志置位 + 取消 future
            watcher = asyncio.create_task(self._watch_cancel(fut, cancel_cb))
            try:
                images = await fut
            finally:
                watcher.cancel()
                self._cancel_requested = False

        return self._save_outputs(images, config)

    async def infer_edit(
        self,
        config: GenerationConfig,
        on_progress: ProgressCallback | None = None,
    ) -> list[str]:
        """执行进程内图像编辑（Qwen-Image 2.1 Edit，参考图 + 编辑指令）。"""
        if not self._ready or not self._model_paths:
            raise RuntimeError("Native engine not ready, please load first")
        init_image = (getattr(config, "init_image", "") or "").strip()
        if not init_image:
            raise ValueError("infer_edit requires GenerationConfig.init_image (reference image path)")

        self._cancel_requested = False
        cancel_flag = [False]

        def cancel_cb() -> None:
            cancel_flag[0] = True

        from ..observability.tracing import get_tracer

        tracer = get_tracer("native_engine")
        loop = asyncio.get_event_loop()
        with tracer.start_span(
            "infer_edit",
            attributes={
                "engine": self._name,
                "edit_resolution": getattr(config, "edit_resolution", None),
            },
        ):
            fut = loop.run_in_executor(
                None,
                lambda: edit_executor.edit(
                    config,
                    self._model_paths,
                    init_image,
                    on_progress=on_progress,
                    cancel_flag=cancel_flag,
                    resolution=int(getattr(config, "edit_resolution", 0) or 1024),
                ),
            )
            watcher = asyncio.create_task(self._watch_cancel(fut, cancel_cb))
            try:
                images = await fut
            finally:
                watcher.cancel()
                self._cancel_requested = False

        return self._save_outputs(images, config)

    async def cancel(self) -> None:
        """取消当前推理（置位取消标志）。"""
        self._cancel_requested = True
        logger.info("NativeEngine '%s' cancel requested", self._name)

    def request_cancel(self) -> None:
        """线程安全的取消请求（可由 executor 线程调用）。

        仅置位内部标志 ``_cancel_requested``；推理循环里的 ``_watch_cancel`` 任务
        会在下一个采样步边界调用 ``cancel_cb`` 把 ``cancel_flag[0]`` 置 True，从而
        由 executor 在采样步内抛出 ``CancelledError`` 干净中止——避免从 executor 线程
        调用 async ``cancel()`` 触发 “no running event loop” 异常（此前靠异常中止
        “碰巧” 收敛为 cancelled，非设计语义，见后端服务设计评估报告 P1-2）。
        """
        self._cancel_requested = True
        logger.info("NativeEngine '%s' cancel requested (thread-safe)", self._name)

    # ── 内部辅助 ────────────────────────────────────────────
    async def _watch_cancel(self, fut: Any, cancel_cb: Any) -> None:
        """监控取消标志；用户在推理中调用 cancel() 时触发内部取消。"""
        while not fut.done():
            if self._cancel_requested:
                cancel_cb()
                return
            await asyncio.sleep(0.05)

    def _save_outputs(self, images: list[Any], config: GenerationConfig) -> list[str]:
        """把解码后的图像张量落盘 + 嵌入 DCT 水印 + 生成缩略图。

        输出命名：outputs/{engine}/{date}/{taskid}_{idx}.{ext}
        ext 取自 cfg.output.image_format（P0 WebP/有损压缩）。
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
        image_format = cfg.output.image_format
        image_quality = cfg.output.image_quality
        thumb_format = cfg.output.thumbnail_format
        thumb_quality = cfg.output.thumbnail_quality
        out_ext = image_format.lower()
        if out_ext == "jpg":
            out_ext = "jpeg"
        thumb_dir: Path | None = None
        if thumb_enabled:
            thumb_dir = guard.ensure_dir(Path("data") / "cache" / "thumbs")

        saved: list[str] = []
        metadata = output_pipeline.build_generation_metadata(task_id, config, self._name)
        for idx, img_tensor in enumerate(images):
            width, height = img_tensor.shape[1], img_tensor.shape[0]
            # P1-2 显式 AI 生成标识：文件名默认追加 _AI 后缀（config.output 可关闭）
            _lbl = cfg.output.explicit_ai_label_suffix if cfg.output.explicit_ai_label else ""
            fname = f"{task_id[:16]}_{idx}{_lbl}.{out_ext}"
            path = engine_dir / fname
            output_pipeline.finalize_output(
                path,
                img_tensor,
                is_tensor=True,
                wm_enabled=wm_enabled,
                product_id=product_id,
                task_id=task_id[:16],
                thumb_enabled=thumb_enabled,
                thumb_dir=thumb_dir,
                thumb_name=f"{task_id[:16]}_{idx}_thumb.{thumb_format.lower()}",
                thumb_max_side=thumb_max_side,
                image_format=image_format,
                image_quality=image_quality,
                thumb_format=thumb_format,
                thumb_quality=thumb_quality,
                metadata=metadata,
                watermark_failure_mode=watermark_failure_mode,
            )

            # 存相对路径（相对 outputs/ 目录），供前端 /api/outputs/<rel> 直接访问
            base = (Path(cfg.project_root) / cfg.output.base_dir).resolve()
            rel = str(path.relative_to(base)).replace("\\", "/")
            saved.append(rel)
        return saved
