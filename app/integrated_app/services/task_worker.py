"""services/task_worker.py — TaskQueue worker 业务逻辑（自 app_server.py 下沉）。

后端服务设计评估报告 P2-2：此前 ``app_server.py`` 在 lifespan 装配函数里内嵌了
约 100 行 worker 业务逻辑（引擎装配、LoRA VRAM 预检、进度/取消联动、产物落库
与错误分类），装配与业务混杂。本模块以工厂函数 :func:`make_worker_func` 返回
与原实现**行为一致**的 worker 闭包，``app_server.py`` 回归纯装配职责。

行为保持不变的关键点（勿在重构中丢失）：
- ``prog`` 回调可能由 executor 线程（采样步内）调用 → 取消走线程安全的
  ``engine.request_cancel()``（P1-2），不得用 ``asyncio.create_task``；
- 落库前先 ``clear_task_outputs`` 使重试幂等（P2-3）；
- ``_probe_output_metadata`` 回填真实尺寸（SOPS #49：缺回填会让发布冒烟误判）；
- 失败路径也回填 ``processing_time_s``（FinOps 入账，成本治理报告 P1-②）。
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Callable
from pathlib import Path

from ..checkpoint import TaskCheckpoint
from ..config import get_config
from ..cost_governance import get_idle_unload_manager
from ..engine_interface import GenerationConfig
from ..history_db import HistoryDB
from ..task_queue import Task, TaskQueue

logger = logging.getLogger(__name__)


def _probe_output_metadata(path: str) -> tuple[int, int, int]:
    """读取产物文件的真实字节数与像素尺寸，供历史库落盘回填。

    历史库 `add_output` 的 file_size/width/height 默认全为 0；若不回填，
    图库与 `/api/tasks/{id}` 拿不到尺寸，发布冒烟的 `--require-real-output`
    也会把真实部署误判成假产物（判据是 0 字节 / 0 尺寸）。这里容忍任何异常
    ——元数据缺失不应阻断落库，最多只是字段仍为 0。

    Args:
        path: 产物路径，可为绝对路径，或相对项目根 / `outputs/` 的相对路径

    Returns:
        (file_size, width, height)：读取失败时对应项回退为 0
    """
    norm = str(path or "").replace("\\", "/")
    if not norm:
        return 0, 0, 0
    root = Path(__file__).resolve().parents[2].as_posix()
    real = next(
        (c for c in (norm, f"outputs/{norm}", f"{root}/{norm}", f"{root}/outputs/{norm}") if os.path.isfile(c)),
        None,
    )
    if not real:
        return 0, 0, 0
    try:
        size = os.path.getsize(real)
    except OSError:
        return 0, 0, 0
    width = height = 0
    try:
        from PIL import Image  # type: ignore

        with Image.open(real) as im:
            width, height = im.size
    except Exception:
        width = height = 0
    return size, width, height


def make_worker_func(
    task_queue: TaskQueue,
    history_db: HistoryDB,
    checkpoint_mgr: TaskCheckpoint,
) -> Callable[[Task], None]:
    """构造 TaskQueue worker 闭包。

    Args:
        task_queue: 任务队列（用于进度通知）
        history_db: 历史库（worker 线程内同步写，RLock 已串行化）
        checkpoint_mgr: 断点续跑管理器

    Returns:
        worker 函数，交由 ``task_queue.start()`` 在单线程池中执行。
    """

    def worker_func(task):
        # 提交→worker 边界的最小关联键：HTTP 提交侧的 request_id 随 Task 元组
        # 传入，在此绑定到当前（线程池）上下文，使本线程全部日志携带同一
        # ``req=<同一id>``，与提交行 ``Task submitted:`` 可用同一 id 过滤串联。
        from ..middleware.request_id import reset_request_id, set_request_id

        req_token = None
        if getattr(task, "request_id", ""):
            req_token = set_request_id(task.request_id)
        try:
            _process_task(task)
        finally:
            if req_token is not None:
                reset_request_id(req_token)

    def _process_task(task):
        logger.info(f"Worker processing task: {task.task_id} ({task.engine})")
        started = time.time()
        # P2 标记活跃，避免推理进行中误触发空闲卸载
        get_idle_unload_manager().mark_activity()
        try:
            cfg = get_config()
            ecfg = cfg.models.engines.get(task.engine)
            if not ecfg:
                raise RuntimeError(f"Engine '{task.engine}' not found in config")

            # M8: 使用工厂方法按 backend 分发引擎
            from ..model_registry import get_model_registry

            registry = get_model_registry()
            backend = getattr(ecfg, "backend", "native")
            engine = registry.create_engine_instance(
                engine_name=task.engine,
                display_name=getattr(ecfg, "display_name", task.engine),
                display_name_en=getattr(ecfg, "display_name_en", ""),
                backend=backend,
                config=ecfg.model_dump(),
            )
            gen = GenerationConfig(**task.config)

            # MLOps P0-2: 多 LoRA 叠加 VRAM 增量预检（best-effort，仅告警不阻断）
            try:
                from ..gpu_utils import get_gpu_info, preflight_vram_with_loras
                from ..native import lora as _lora_mod

                stack = gen.effective_lora_stack()
                if stack:
                    gpu_info = get_gpu_info()
                    if gpu_info.backend != "cpu":  # 无 GPU 环境跳过，避免噪声
                        lora_paths = _lora_mod.resolve_lora_paths(cfg.models, cfg.project_root)
                        est = preflight_vram_with_loras(
                            ecfg.vram_gb,
                            stack,
                            width=gen.width,
                            height=gen.height,
                            batch_size=getattr(gen, "batch_size", 1),
                            lora_paths=lora_paths,
                            enable_seedvr2=False,
                            default_precision=ecfg.default_precision,
                            fallback_precision=ecfg.fallback_precision,
                            multisample_rule=cfg.inference.vram_multisample_rule,
                            headroom_gb=cfg.inference.vram_headroom_gb,
                            gpu_info=gpu_info,
                            allow_tight=cfg.inference.vram_tight_continue,
                        )
                        if not est.can_run:
                            logger.warning(
                                "[VRAM-PRECHECK] LoRA 栈可能超出显存 (增量 %.2fGB): %s",
                                est.lora_increment_gb,
                                est.warning,
                            )
            except Exception as e:  # noqa: BLE001 - 预检失败不阻断主推理
                logger.debug("LoRA VRAM 预检异常（已忽略）: %s", e)

            def prog(pct, phase, extra):
                task.progress = pct
                task.phase = phase
                task_queue._notify_progress(task.task_id, pct, phase, extra or {})
                # P1-2：本回调可能由 executor 线程（采样步内）调用，该线程无事件
                # 循环，不能用 asyncio.create_task(engine.cancel())。改用线程安全的
                # 标志置位，由 _watch_cancel 在下一采样步边界设置 cancel_flag。
                if task.cancel_requested and not engine._cancel_requested:
                    engine.request_cancel()

            async def run():
                await engine.load(on_progress=prog)
                if task.cancel_requested:
                    await engine.cancel()
                    raise asyncio.CancelledError("cancelled before start")
                # 编辑路径（P1）：参考图非空 → 走 infer_edit（Qwen-Image 2.1 Edit）。
                # 声明 edit 能力的引擎才走编辑分支；否则照旧 txt2img（保持历史行为）。
                wants_edit = bool((gen.init_image or "").strip()) and "edit" in (ecfg.supported_features or [])
                if wants_edit:
                    return await engine.infer_edit(gen, on_progress=prog)
                return await engine.infer_txt2img(gen, on_progress=prog)

            outputs = asyncio.run(run())
            task.result = outputs or []

            # 查找缩略图路径（engine._fetch_outputs 可能已生成缩略图）
            thumb = outputs[0] if outputs else ""
            # 如果引擎返回了缩略图，使用它；否则用第一个输出
            if hasattr(engine, "_thumbnail_path") and engine._thumbnail_path:
                thumb = engine._thumbnail_path

            # P2-3：先清空本任务已有的 outputs 记录，使重试（P2-6）落库幂等，
            # 避免同一 task_id 累积重复行导致图库出现重复项。
            history_db.clear_task_outputs(task.task_id)
            out_types = ("original", "upscaled", "compare")
            for i, p in enumerate(outputs or []):
                # 回填产物真实尺寸/字节数：历史库此前恒为 0，导致图库与
                # /api/tasks/{id} 拿不到尺寸，且发布冒烟的真实产物校验会误判
                file_size, width, height = _probe_output_metadata(p)
                # 数据治理 Q1-①：输出文件指纹落库（图片自描述之外的第二条溯源链）
                try:
                    from ..security.weight_integrity import compute_file_sha256

                    out_sha256 = compute_file_sha256(p)
                except OSError:
                    out_sha256 = ""
                history_db.add_output(
                    task.task_id,
                    p,
                    cfg.output.image_format,
                    file_size=file_size,
                    width=width,
                    height=height,
                    output_type=out_types[i] if i < len(out_types) else "original",
                    sha256=out_sha256,
                )

            # 状态更新放在 outputs 落库之后：此前先写 completed 再逐条 add_output，
            # 存在竞态——按状态轮询的调用方（集成测试/前端/冒烟脚本）命中
            # completed 时图库查询可能还是空（状态已终态、产物未就位）。
            history_db.update_task_status(
                task.task_id,
                "completed",
                processing_time_s=time.time() - started,
                output_count=len(outputs or []),
                thumbnail=thumb,
            )

            # 批量任务断点续跑：完成时清理 checkpoint
            if task.batch_id:
                checkpoint_mgr.delete(task.task_id)
        except asyncio.CancelledError:
            history_db.update_task_status(task.task_id, "cancelled")
            task.error = "cancelled"
            return
        except Exception as e:
            logger.exception(f"Task {task.task_id} worker error")
            from ..lineage import classify_error

            # 成本资源治理评估报告 P1-②：失败任务同样消耗了 GPU/加载时间，
            # 必须入账，否则 FinOps 的 est_gpu_hours 系统性低估（实测 204 笔失败全为 0s）。
            history_db.update_task_status(
                task.task_id,
                "failed",
                error=str(e),
                error_code=classify_error(e),
                processing_time_s=time.time() - started,
            )
            task.error = str(e)
            raise

    return worker_func


__all__ = ["make_worker_func", "_probe_output_metadata"]
