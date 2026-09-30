"""
app_server.py — FastAPI 主应用入口

对应 MASTER_PLAN §4: app_server.py (FastAPI create_app + lifespan)
对应 MASTER_PLAN §3: 单页融合版 FastAPI 托管为 /
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import logging.handlers
import os
import pkgutil
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .checkpoint import TaskCheckpoint
from .config import get_config
from .cost_governance import (
    get_idle_unload_manager,
    get_metrics_store,
    get_vram_scheduler,
)
from .gpu_utils import VRAMLeakMonitor, get_gpu_info
from .history_db import HistoryDB
from .middleware.auth import AuthMiddleware
from .middleware.csrf import CSRFMiddleware
from .middleware.rate_limit import RateLimitMiddleware
from .middleware.request_id import RequestIDMiddleware
from .middleware.security_headers import SecurityHeadersMiddleware
from .model_registry import get_model_registry
from .observability.alerts import (
    get_alert_engine,
    health_unhealthy,
)
from .observability.generation_metrics import (
    classify_generation_error,
    record_generation_cancelled,
    record_generation_completed,
    record_generation_failed,
    record_generation_first_preview,
    record_generation_first_progress,
    record_generation_started,
    record_inference_duration,
    record_queue_wait,
)
from .observability.http_metrics import MetricsMiddleware
from .sse import get_sse_bus
from .task_queue import Task, TaskQueue

# ── 日志配置 ──────────────────────────────────────────────────
logger = logging.getLogger("integrated_app")


class VersionedStaticFiles(StaticFiles):
    """差异化缓存静态文件（来源：Seedvr2 VersionedStaticFiles / TTS_MultiModel CachedStaticFiles）。

    学习参考项目：前端开发时修改 HTML/CSS/JS 后刷新浏览器即生效（不命中旧缓存）；
    同时字体长缓存（30 天）、图片短期缓存（1 天）避免无谓重复下载。
    - CSS/JS/HTML/JSON：no-cache, must-revalidate（开发时经常改）
    - 字体（woff2/woff/ttf/eot/otf）：public, max-age=2592000（30 天）
    - 图片（png/jpg/jpeg/gif/svg/ico/webp）：public, max-age=86400（1 天）
    """

    def file_response(self, *args, **kwargs) -> Response:
        """重写 file_response，根据文件类型添加差异化的 Cache-Control 头。"""
        response = super().file_response(*args, **kwargs)
        if args:
            fp = str(args[0])
            if fp.endswith((".css", ".js", ".html", ".json")):
                response.headers["Cache-Control"] = "no-cache, must-revalidate"
                response.headers["Pragma"] = "no-cache"
            elif fp.endswith((".woff2", ".woff", ".ttf", ".eot", ".otf")):
                response.headers["Cache-Control"] = "public, max-age=2592000"
            elif fp.endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp")):
                response.headers["Cache-Control"] = "public, max-age=86400"
        return response


def _auto_discover_routers() -> list:
    """使用 pkgutil 递归发现并注册路由模块（P0-3: 来源 TTS_MultiModel）。

    遍历 ``integrated_app.routes`` 包下的所有模块，自动提取 ``router``
    APIRouter 实例。新增路由文件只需放到 routes/ 目录并在模块内定义
    ``router = APIRouter(prefix="/api/xxx", ...)`` 即可自动注册。

    Returns:
        list: 发现的 APIRouter 实例列表。
    """
    routers: list = []
    try:
        routes_pkg = importlib.import_module(".routes", package=__package__)
    except ImportError as e:
        logger.warning(f"[路由发现] 导入 routes 包失败: {e}")
        return routers

    if not hasattr(routes_pkg, "__path__"):
        return routers

    for _importer, modname, _ispkg in pkgutil.iter_modules(routes_pkg.__path__):
        try:
            mod = importlib.import_module(f".routes.{modname}", package=__package__)
            if hasattr(mod, "router"):
                routers.append(mod.router)
                logger.debug(f"[路由发现] 注册路由模块: routes.{modname}")
        except Exception as e:
            logger.warning(f"[路由发现] 导入 routes.{modname} 失败: {e}")

    return routers


def setup_logging(config) -> None:
    """配置日志：控制台 + 按大小轮转的文件（参数来自 config.yaml logging 段）。

    统一格式：时间戳 + 级别 + 进程/线程 + 模块位置 + 请求ID（request_id） + 消息，
    便于生产环境按 request_id 链路追踪、按 filename:lineno 快速定位。
    """
    log_cfg = config.logging
    log_dir = Path(config.project_root) / log_cfg.file
    log_dir.parent.mkdir(parents=True, exist_ok=True)

    # 日志级别支持环境变量 LOG_LEVEL 覆盖（优先级高于配置文件）
    level_name = os.environ.get("LOG_LEVEL", log_cfg.level).upper()
    log_level = getattr(logging, level_name, logging.INFO)

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [PID:%(process)d TID:%(thread)d] "
        "[%(name)s:%(filename)s:%(lineno)d] [req=%(request_id)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    from .middleware.request_id import RequestIDLogFilter

    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
    ]
    try:
        handlers.append(
            logging.handlers.RotatingFileHandler(
                str(log_dir),
                maxBytes=log_cfg.max_size_mb * 1024 * 1024,
                backupCount=log_cfg.backup_count,
                encoding="utf-8",
            )
        )
    except Exception as e:
        logger.warning(f"Could not set up file logging: {e}")

    for handler in handlers:
        handler.setFormatter(formatter)
        handler.addFilter(RequestIDLogFilter())

    logging.basicConfig(
        level=log_level,
        handlers=handlers,
        force=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # ── 启动 ──────────────────────────────────────────────────
    # get_config()（全局单例）而非 load_config()：后者每次重读 YAML 并**替换**
    # 单例，会（a）造成 create_app 与 lifespan 两份可能分歧的配置对象；
    # （b）打穿 conftest 对 db_path/uploads 的测试期重定向（数据治理 P2-3
    # 补跑曾借此对真实 data/uploads 误清扫）。
    config = get_config()
    app.state.config = config
    setup_logging(config)
    logger.info(f"=== Image MultiModel starting (v{config.version}) ===")
    logger.info(f"Project root: {config.project_root}")
    logger.info(f"Model mode: {config.models.model_source_mode}")

    # M3（2026-09-04 安全评估）：可选的最小 api_token bootstrap。
    # off-by-default：仅当 security.api_token.bootstrap=true 时生效，
    # 自动生成/复用 token 并启用鉴权（详见 security/auth_bootstrap.py）。
    from .security.auth_bootstrap import ensure_api_token

    ensure_api_token(config)

    # 数据治理：配置化 workflow 文件启动期准入校验（§4.4 / 中期 Schema 治理）
    # 拦截缺失/损坏文件并强制携带 schema_version；缺版本仅告警，不阻断启动。
    from .workflow_governance import validate_configured_workflows

    for _wf in validate_configured_workflows(config):
        for _err in _wf["errors"]:
            logger.error("[WORKFLOW-GOVERNANCE] engine=%s: %s", _wf["engine"], _err)
        for _warn in _wf["warnings"]:
            logger.warning("[WORKFLOW-GOVERNANCE] engine=%s: %s", _wf["engine"], _warn)

    # P0-2：按 config.yaml → cache 段初始化缓存命名空间。
    # 此前 CacheConfig 仅有声明、无任何消费者（死配置），此处为其唯一装配点。
    from .cache import build_caches_from_config

    build_caches_from_config(config)

    # P1-5 分布式追踪：按环境变量/配置初始化（降级为进程内 span 记录，
    # 安装 opentelemetry 后自动接入导出管线）。
    from .observability.tracing import configure_tracing

    configure_tracing()

    # P1-1: 核心模块完整性自检（来源：Seedvr2）
    # P0（任务书 2026-09-10）：enforce 接线——验签/哈希失败拒绝启动（fail-closed）。
    # enforce 开启的前提是签名密钥分发定案（CI Secret 注入 + 公钥入库），
    # 详见本地保留的 AI 开发规范 SOP-19（未随仓库发布）与本仓 security/secret_key.py。
    from .security.integrity_selfcheck import run_startup_selfcheck

    selfcheck_result = run_startup_selfcheck(enforce=config.security.integrity_selfcheck.enforce)
    app.state.integrity_selfcheck = selfcheck_result
    # 安全评估 H-04：skipped > 0 表示有核心模块未被 manifest 覆盖。
    # 此前这些模块被静默计入 skipped 且仍打印"自检通过"，属误导性日志，
    # 故此处将"有失败或有跳过"统一降级为 WARNING，避免虚假的安全信心。
    if selfcheck_result["failed"] or selfcheck_result["skipped"]:
        failed_files = selfcheck_result["failed_files"]
        logger.warning(
            "[SECURITY] 完整性自检未完全覆盖：通过 %s / 失败 %s / 跳过 %s%s",
            selfcheck_result["passed"],
            selfcheck_result["failed"],
            selfcheck_result["skipped"],
            f"，失败文件: {', '.join(failed_files)}" if failed_files else "",
        )

    # 初始化 HistoryDB
    db_path = Path(config.project_root) / config.output.history.db_path
    history_db = HistoryDB(db_path)
    app.state.history_db = history_db

    # 崩溃恢复：清理卡死任务
    recovered = history_db.recover_stuck_tasks()
    if recovered > 0:
        logger.warning(f"Recovered {recovered} stuck tasks from previous session")

    # 初始化 TaskQueue
    task_queue = TaskQueue(
        maxsize=config.runtime.task_queue.maxsize,
        cancel_timeout_s=config.runtime.task_queue.cancel_timeout_s,
        max_timeout_s=config.runtime.task_queue.max_timeout_s,
        # P2-6 批量自动重试：阈值来自 config.yaml → runtime.batch
        max_retries=config.runtime.batch.max_retries,
        retry_base_delay_s=config.runtime.batch.retry_base_delay_s,
        retry_max_delay_s=config.runtime.batch.retry_max_delay_s,
    )
    app.state.task_queue = task_queue
    # 注册进程级单例：供 RequestIDLogFilter 在 worker 线程回退读取在飞任务
    # 元数据（跨线程不共享 ContextVar，日志 req= 关联键兜底）。
    from .task_queue import set_task_queue

    set_task_queue(task_queue)

    # 注册 SSE 进度/状态回调
    sse_bus = get_sse_bus()

    # 每任务首进度/首预览去重（避免重复计数 first_progress/first_preview）
    _first_seen: dict[str, set[str]] = {}

    async def on_progress(task_id: str, progress: int, phase: str, extra: dict):
        await sse_bus.publish(
            "task_status",
            {
                "task_id": task_id,
                "progress": progress,
                "phase": phase,
                **extra,
            },
        )
        # MLOps P0-3：记录每个任务首次进度 / 首次预览（去重）
        flags = _first_seen.setdefault(task_id, set())
        if "progress" not in flags:
            flags.add("progress")
            record_generation_first_progress(extra.get("engine", "") or "")
        if "preview_b64" in extra and "preview" not in flags:
            flags.add("preview")
            record_generation_first_preview(extra.get("engine", "") or "")
            await sse_bus.publish(
                "preview",
                {
                    "task_id": task_id,
                    "b64": extra["preview_b64"],
                    "format": extra.get("preview_format", "jpg"),
                },
            )

    async def on_status(task_id: str, status, extra: dict | None = None):
        await sse_bus.publish(
            "task_status",
            {
                "task_id": task_id,
                "status": status.value if hasattr(status, "value") else str(status),
                **(extra or {}),
            },
        )
        # 同时发布 queue_status 事件（§1.6 SSE 补全）
        await sse_bus.publish("queue_status", task_queue.get_queue_status())

        # MLOps P0-3：生成链路生命周期指标埋点
        task = task_queue.get_task(task_id)
        engine = (task.engine if task else "") or (extra or {}).get("engine", "") or ""
        st = status.value if hasattr(status, "value") else str(status)
        if st == "processing":
            record_generation_started(engine)
            if task and task.started_at and task.created_at:
                record_queue_wait(engine, task.started_at - task.created_at)
        elif st == "completed":
            record_generation_completed(
                engine,
                (task.completed_at - task.created_at) if task and task.completed_at else 0.0,
            )
            if task and task.completed_at and task.started_at:
                record_inference_duration(engine, task.completed_at - task.started_at)
            _first_seen.pop(task_id, None)
        elif st == "failed":
            err = ((extra or {}).get("error", "") if extra else "") or (task.error if task else "")
            record_generation_failed(engine, classify_generation_error(err))
            _first_seen.pop(task_id, None)
        elif st == "cancelled":
            record_generation_cancelled(engine)
            _first_seen.pop(task_id, None)

    # TaskQueue 回调运行在 worker 线程 → 用主循环线程安全投递
    main_loop = asyncio.get_event_loop()

    def sync_on_progress(task_id, progress, phase, extra):
        asyncio.run_coroutine_threadsafe(on_progress(task_id, progress, phase, extra), main_loop)

    def sync_on_status(task_id, status, extra=None):
        asyncio.run_coroutine_threadsafe(on_status(task_id, status, extra), main_loop)

    task_queue.add_progress_callback(sync_on_progress)
    task_queue.add_status_callback(sync_on_status)

    # 启动 SSE 心跳
    heartbeat_task = asyncio.ensure_future(sse_bus.start_heartbeat())

    # 初始化成本治理单例（配置驱动）
    get_vram_scheduler().configure(config.runtime.vram_scheduler)
    get_idle_unload_manager().idle_unload_minutes = config.runtime.idle_unload_minutes

    # 启动 GPU 状态定期推送（§1.6 SSE 补全：每 2s 发布 gpu_status）
    # 同时持久化指标到 MetricsStore、运行泄漏监控、驱动 VRAM 动态调度（P1 成本可见性）
    async def gpu_monitor_loop():
        store = get_metrics_store()
        scheduler = get_vram_scheduler()
        leak = VRAMLeakMonitor()
        while True:
            try:
                gpu = get_gpu_info()
                sample = {
                    "name": gpu.gpu_name,
                    "backend": gpu.backend,
                    "total_vram_gb": gpu.total_vram_gb,
                    "used_vram_gb": gpu.used_vram_gb,
                    "free_vram_gb": gpu.free_vram_gb,
                }
                # torch 峰值分配/预留（无 torch 时缺省 0）
                try:
                    import torch

                    if torch.cuda.is_available():
                        sample["allocated_bytes"] = int(torch.cuda.max_memory_allocated() or 0)
                        sample["reserved_bytes"] = int(torch.cuda.memory_reserved() or 0)
                except Exception:
                    pass
                store.record_gpu(sample)
                await sse_bus.publish("gpu_status", {**sample, "timestamp": time.time()})
                # 显存泄漏监控（MLOps P1·可观测，生产接入）
                leak.sample()
                store.record_leak(leak.check_leak())
                # VRAM 水位感知动态 batch 上限
                free_pct = (gpu.free_vram_gb / gpu.total_vram_gb * 100.0) if gpu.total_vram_gb else None
                scheduler.update(free_pct)
                # MLOps P0-4：周期评估告警规则，驱动 for 时长与通知去重
                _evaluate_alerts()
            except Exception as e:
                logger.warning(f"GPU monitor error: {e}")
            await asyncio.sleep(2)

    gpu_monitor_task = asyncio.ensure_future(gpu_monitor_loop())

    # MLOps P0-4：基于当前进程状态聚合告警快照并驱动 AlertEngine 状态机
    def _evaluate_alerts() -> None:
        from .observability.metrics import get_metrics

        try:
            cfg = get_config()
            m = get_metrics()
            tq = app.state.task_queue
            maxsize = float(getattr(cfg.runtime.task_queue, "maxsize", 0) or 0)
            fill = min(1.0, tq.queue_size / maxsize) if maxsize else 0.0
            failed = m.generation_failed_total.total()
            completed = m.generation_completed_total.total()
            failure_rate = failed / (failed + completed) if (failed + completed) > 0 else 0.0
            g = get_metrics_store().latest_gpu
            gpu_free_pct = (g["free_vram_gb"] / g["total_vram_gb"] * 100.0) if g and g.get("total_vram_gb") else None
            disk_free_pct: float | None = None
            try:
                import shutil

                du = shutil.disk_usage("/")
                disk_free_pct = du.free / du.total * 100.0
            except Exception:
                disk_free_pct = None
            get_alert_engine().evaluate(
                {
                    "queue_fill_ratio": fill,
                    "generation_failure_rate": failure_rate,
                    "gpu_free_pct": gpu_free_pct,
                    "disk_free_pct": disk_free_pct,
                    "health_unhealthy": health_unhealthy(),
                    "now": time.time(),
                }
            )
        except Exception as e:  # noqa: BLE001
            logger.debug("alert evaluation skipped: %s", e)

    # P2 空闲自动卸载循环：空闲超阈值后卸载常驻引擎权重，避免空载计费
    async def idle_unload_loop():
        mgr = get_idle_unload_manager()
        while True:
            try:
                if mgr.should_unload():
                    await unload_all_engines(config)
                    mgr.note_unloaded()
                    logger.info("Idle unload triggered after %s min idle", mgr.idle_minutes)
            except Exception as e:  # noqa: BLE001
                logger.warning("Idle unload loop error: %s", e)
            await asyncio.sleep(30)

    # unload_all_engines 定义为模块级函数（见文件末尾），便于单测回归。

    idle_unload_task = asyncio.ensure_future(idle_unload_loop())

    # D6: 历史清理 cron 调度（修复空转：keep_days>0 OR max_gb>0 即启用）
    async def history_cleanup_cron():
        """每日 cron 维护任务：① 容量日快照 ② uploads TTL ③ 历史清理 ④ 配额告警。

        数据治理报告 P2-3：自实现 cron 补跑（misfire）——启动时若当日槽位
        已过（服务跨 03:00 未运行），立即补跑一轮维护，不再静默跳到明天。
        """
        import datetime as _dt

        # 环境开关：测试/CI 禁用维护 cron（IMM_DISABLE_MAINTENANCE_CRON=1）。
        # 用环境变量而非改配置单例：load_config(path) 会整体替换单例，测试期
        # 对 cleanup_cron 的修改可能被任何一次配置加载冲掉（GOTCHAS #13）。
        if os.environ.get("IMM_DISABLE_MAINTENANCE_CRON") == "1":
            logger.info("History maintenance cron disabled (IMM_DISABLE_MAINTENANCE_CRON=1)")
            return
        cron_expr = config.output.history.cleanup_cron
        keep_days = config.output.history.keep_days
        max_gb = config.output.history.max_gb
        if not cron_expr:
            logger.info("History maintenance cron disabled (no cron expr)")
            return
        parts = cron_expr.split()
        if len(parts) != 5:
            logger.warning(f"Invalid cron expression: {cron_expr}")
            return
        cron_min, cron_hour, _, _, _ = parts

        async def _run_maintenance() -> None:
            # ① 容量日快照（成本资源治理评估报告 §5-⑤：无条件执行，
            #    不依赖清理阈值——快照是容量规划数据源，清理只是消费者之一）
            try:
                from .cost_governance import build_capacity_snapshot, get_metrics_store

                snap = build_capacity_snapshot(history_db, get_metrics_store(), config.project_root)
                history_db.record_capacity_snapshot(
                    snapshot_date=snap["snapshot_date"],
                    peak_used_gb=snap["peak_used_gb"],
                    disk_used_gb=snap["disk_used_gb"],
                    gpu_hours_24h=snap["gpu_hours_24h"],
                )
                logger.info(
                    "Capacity snapshot recorded: %s (peak %.2fGB, disk %.1fGB, gpu %.3fh/24h)",
                    snap["snapshot_date"],
                    snap["peak_used_gb"],
                    snap["disk_used_gb"],
                    snap["gpu_hours_24h"],
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("Capacity snapshot failed: %s", e)
            # ② 上传图 TTL 清理（数据治理 P1-2：无条件随日维护联跑，
            #    与历史清理阈值解耦；ttl_s<=0 时 no-op）
            try:
                from .uploads_ttl import cleanup_expired_uploads

                deleted_up, freed_up = cleanup_expired_uploads(
                    Path(config.project_root) / config.output.uploads.cache_dir,
                    config.output.uploads.ttl_s,
                )
                if deleted_up:
                    logger.info(
                        "Uploads TTL cleanup: %d file(s) removed (%.1f KB)",
                        deleted_up,
                        freed_up / 1024,
                    )
            except Exception as e:  # noqa: BLE001
                logger.warning("Uploads TTL cleanup failed: %s", e)
            # ③ 清理（仅阈值启用时；快照与清理解耦）
            if keep_days <= 0 and max_gb <= 0:
                return
            # 灾难恢复：清理前先做一致性备份（数据治理评估报告 §4.9）
            try:
                history_db.backup()
            except Exception as e:  # noqa: BLE001
                logger.warning("History backup before cleanup failed: %s", e)
            # 执行清理（同步删除磁盘图片文件，真正释放存储）
            # 会话引用保护（评估报告 C-11）：Agent 对话里展示过的图被删会变裂图，
            # 故把活跃会话引用的 task_id 作为白名单传下去。取不到（Agent 未使用过 /
            # 会话库不可用）时退回不保护，不影响清理本身。
            protected = _agent_referenced_task_ids()
            deleted = history_db.cleanup_old_tasks(
                keep_days=keep_days,
                max_gb=max_gb,
                protect_task_ids=protected,
            )
            logger.info(f"History cleanup: deleted {deleted} tasks (keep_days={keep_days}, max_gb={max_gb})")
            # ④ 配额逼近告警（数据治理 P1-5）：删除量 0 但 outputs 超
            #    finops.storage_gb_budget 的 80% → warning + SSE 事件
            try:
                from .cost_governance import evaluate_storage_quota_proximity
                from .sse import get_sse_bus

                alert = evaluate_storage_quota_proximity(config.project_root, deleted)
                if alert:
                    await get_sse_bus().publish("finops_alert", alert)
            except Exception as e:  # noqa: BLE001
                logger.warning("Storage quota proximity check failed: %s", e)

        first_tick = True
        while True:
            try:
                now = _dt.datetime.now()
                next_run, missed_today = _compute_cron_next_run(now, cron_min, cron_hour)
                if first_tick and missed_today:
                    # P2-3 补跑：启动时当日槽位已过 → 立即补跑一轮再进入正常排程
                    first_tick = False
                    logger.info(
                        "Cron misfire backfill: today's %s:%s slot already passed, running maintenance now",
                        cron_hour,
                        cron_min,
                    )
                    await _run_maintenance()
                    continue
                first_tick = False
                sleep_s = (next_run - now).total_seconds()
                logger.info(f"History maintenance scheduled at {next_run}, sleeping {sleep_s:.0f}s")
                await asyncio.sleep(sleep_s)
                await _run_maintenance()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"History cleanup cron error: {e}")
                await asyncio.sleep(3600)  # 出错后 1h 重试

    cleanup_task = asyncio.ensure_future(history_cleanup_cron())

    # 初始化断点续跑 Checkpoint（§1.3）
    checkpoint_mgr = TaskCheckpoint(
        checkpoint_dir=str(Path(config.project_root) / config.runtime.task_queue.checkpoint_dir)
    )
    # 启动时扫描未完成 checkpoint（可恢复批量中断任务）
    pending_checkpoints = checkpoint_mgr.list_checkpoints()
    if pending_checkpoints:
        logger.info(f"Found {len(pending_checkpoints)} pending checkpoints for recovery")
    app.state.checkpoint_mgr = checkpoint_mgr

    # 启动清理：把遗留 pending 僵尸任务标记为 interrupted（成本资源治理评估报告 P2-⑥）。
    # auto_recover=false 时这些任务无执行者，会永久滞留（实测曾积压 1500/3073 条）。
    # 待续跑的 checkpoint 任务排除在外，保持 pending 以便下方恢复流程接管。
    # stale_after_s=300 宽限期：蓝绿部署重叠窗口（观察窗 120s）/ 并行 worker 共享 DB
    # 时，刚创建的 pending 属于在飞任务，不得被本实例启动清扫误杀
    # （CI run 33939248177：journey 任务提交数秒即被另一 worker 清扫成 interrupted）。
    try:
        _exclude_ids = [cp.get("task_id", "") for cp in pending_checkpoints]
        _stale = history_db.mark_stale_pending_interrupted(
            exclude_task_ids=_exclude_ids,
            stale_after_s=300.0,
        )
        if _stale > 0:
            logger.warning(f"Marked {_stale} stale pending tasks as interrupted at startup")
    except Exception as e:  # noqa: BLE001
        logger.warning("Stale pending sweep failed: %s", e)

    # 启动 TaskQueue Worker（M8: 支持 native + diffusers 双后端）
    # P2-2：worker 业务逻辑已下沉 services/task_worker.py，本文件回归纯装配。
    # 行为关键点（取消线程安全 / 重试幂等 / 尺寸回填 / 失败入账）见该模块 docstring。
    from .services.task_worker import make_worker_func

    worker_func = make_worker_func(task_queue, history_db, checkpoint_mgr)

    await task_queue.start(worker_func)
    app.state.task_queue = task_queue

    # 启动恢复：从断点续跑 checkpoint 重建未完成任务并续跑剩余槽位
    for cp in pending_checkpoints:
        try:
            cp_task_id = cp.get("task_id", "")
            cp_engine = cp.get("engine", "")
            cp_config = cp.get("config", {})
            cp_completed = cp.get("completed", 0)
            cp_total = cp.get("total", 0)
            if not cp_task_id or not cp_engine or cp_completed >= cp_total:
                checkpoint_mgr.delete(cp_task_id)
                continue
            logger.info(f"Resuming task {cp_task_id} from checkpoint ({cp_completed}/{cp_total})")
            # 构造续跑 Task，减少 batch_size 为剩余数量
            remaining_count = cp_total - cp_completed
            resume_config = dict(cp_config)
            resume_config["batch_size"] = remaining_count
            resume_task = Task(
                task_id=cp_task_id,
                engine=cp_engine,
                config=resume_config,
                mode="txt2img",
            )
            await task_queue.submit(resume_task)
        except Exception as e:
            logger.warning(f"Failed to resume checkpoint: {e}")

    # 初始化 ModelRegistry
    model_registry = get_model_registry()
    model_registry.init_from_config(config)
    app.state.model_registry = model_registry

    logger.info(f"=== Image MultiModel ready on http://{config.server.host}:{config.server.port} ===")

    yield

    # ── 关闭 ──────────────────────────────────────────────────
    logger.info("=== Image MultiModel shutting down ===")
    # 取消后台任务
    gpu_monitor_task.cancel()
    heartbeat_task.cancel()
    cleanup_task.cancel()
    idle_unload_task.cancel()
    await task_queue.stop()
    sse_bus.stop()
    history_db.close()
    logger.info("=== Image MultiModel stopped ===")


def _agent_referenced_task_ids() -> set[str]:
    """读取 Agent 会话库中被引用的 task_id（供历史清理做白名单，评估报告 C-11）。

    直连会话库文件而不依赖 app.state：维护 cron 可能在 Agent 尚未被使用时就跑，
    此时文件不存在 → 返回空集合（不保护，与历史行为一致）。
    任何异常都不得影响清理本身，故整体 try/except 降级为空集合。
    """
    try:
        from .agent.session_store import SqliteSessionStore, default_session_db_path

        path = default_session_db_path()
        if not path.exists():
            return set()
        store = SqliteSessionStore(path)
        try:
            return store.list_referenced_task_ids()
        finally:
            store.close()
    except Exception as e:  # noqa: BLE001 — 保护失败不阻断清理
        logger.warning("读取 Agent 会话引用失败（本次清理不启用会话保护）: %s", e)
        return set()


async def unload_all_engines(config) -> None:
    """遍历所有已加载引擎并卸载常驻权重（模块级，便于单测回归）。

    MLOps P1-7：在异步生命周期中直接 ``await`` 卸载，禁止在运行中的事件循环内
    阻塞式驱动新的事件循环（会触发 RuntimeError: This event loop is already
    running）。卸载前跳过当前 active 引擎，避免破坏在处理的请求引用。
    """
    try:
        from .model_manager import get_model_manager

        mm = get_model_manager()
        registry = get_model_registry()
        active = registry.get_active_engine_name()
        for name in config.models.engines:
            if name == active:
                logger.info("Skip unloading active engine %s", name)
                continue
            if mm.get_state(name).value == "loaded":
                try:
                    inst = registry.create_engine_instance(
                        engine_name=name,
                        display_name=config.models.engines[name].display_name,
                        display_name_en=config.models.engines[name].display_name_en,
                        backend=getattr(config.models.engines[name], "backend", "native"),
                        config=config.models.engines[name].model_dump(),
                    )
                    await mm.unload_engine(name, inst)
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"Idle unload of {name} failed: {e}")
    except Exception as e:  # noqa: BLE001
        logger.warning("unload_all_engines error: %s", e)


# P2-2：_probe_output_metadata 已随 worker 业务逻辑下沉 services/task_worker.py；
# 此处保留 re-export 以兼容既有引用路径（app_server._probe_output_metadata）。
from .services.task_worker import _probe_output_metadata  # noqa: E402,F401


def _compute_cron_next_run(now: Any, cron_min: str, cron_hour: str) -> tuple[Any, bool]:
    """计算 cron 下一次运行时间（模块级纯函数，便于单测回归）。

    Args:
        now: 当前 ``datetime.datetime``
        cron_min / cron_hour: cron 表达式的分/时字段（数字或 ``*``）

    Returns:
        ``(next_run, missed_today)``：``missed_today=True`` 表示当日槽位已过
        （仅 hour/min 均为显式数字时判定），调用方可据此触发补跑
        （数据治理报告 P2-3：自实现 cron 无 APScheduler misfire 机制，
        服务跨 03:00 未运行会导致当日维护被静默跳过）。
    """
    import datetime as _dt

    if cron_hour != "*" and cron_min != "*":
        slot = now.replace(hour=int(cron_hour), minute=int(cron_min), second=0, microsecond=0)
        if slot <= now:
            return slot + _dt.timedelta(days=1), True
        return slot, False
    # 通配符场景维持旧行为（无补跑语义：每个匹配时刻都应执行）
    target_hour = int(cron_hour) if cron_hour != "*" else now.hour
    target_min = int(cron_min) if cron_min != "*" else now.minute
    next_run = now.replace(hour=target_hour, minute=target_min, second=0, microsecond=0)
    if next_run <= now:
        next_run = next_run + _dt.timedelta(days=1)
    return next_run, False


def create_app(enable_rate_limit: bool = True) -> FastAPI:
    """创建 FastAPI 应用

    Args:
        enable_rate_limit: 是否启用速率限制中间件。压测/容量基线场景可关闭，
            避免干扰吞吐测量；生产默认开启。
    """
    config = get_config()

    app = FastAPI(
        title="Image MultiModel",
        description="Z-Image Turbo 图像生成 Web 应用（进程内原生引擎）",
        version=config.version,
        lifespan=lifespan,
    )

    # ── 中间件 ────────────────────────────────────────────────
    # 中间件栈按 Starlette 规则构建：**先 add 者位于最外层**。
    # 实际执行顺序（外 → 内）：
    #   SecurityHeaders → CORS → Auth → CSRF → RequestID → RateLimit → 路由
    # - SecurityHeaders 置最外层，确保 401/403/429 等中间件自身响应也带安全头
    # - Auth 置于 CSRF 之前，先确认身份再校验 CSRF token
    # - RequestID 置于 CSRF 之后，让拒绝响应同样携带 request_id 便于追溯

    # 安全响应头（CSP / nosniff / frame-ancestors，对应安全评估 M-02）
    app.add_middleware(SecurityHeadersMiddleware, config=config)

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.security.cors.allowed_origins,
        allow_credentials=config.security.cors.allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 认证（BasicAuth / Bearer Token，对应安全评估 C-01；默认关闭）
    app.add_middleware(AuthMiddleware, config=config)

    # CSRF（POST/PUT/DELETE 需 X-CSRF-Token 头，默认开启）
    if config.security.csrf.enabled:
        app.add_middleware(CSRFMiddleware)

    # RequestID
    app.add_middleware(RequestIDMiddleware)

    # P1-5 分布式追踪：为每个 HTTP 请求创建根 span（注册在 RequestID 之后，
    # 以便把 request_id 写入 span 属性；注册在 Metrics 之前，使耗时 span 覆盖完整链路）
    from .middleware.tracing import TracingMiddleware

    app.add_middleware(TracingMiddleware)

    # RateLimit
    if enable_rate_limit:
        app.add_middleware(
            RateLimitMiddleware,
            global_per_minute=config.security.rate_limit.global_per_minute,
            infer_per_minute=config.security.rate_limit.infer_per_minute,
            upload_per_minute=config.security.rate_limit.upload_per_minute,
        )

    # MLOps P0-2：HTTP 请求计数 / 延迟指标中间件（路径已归一化，避免高基数 label）
    app.add_middleware(MetricsMiddleware)

    # ── 路由自动发现（P0-3: 来源 TTS_MultiModel） ─────────────
    routers = _auto_discover_routers()
    for router in routers:
        app.include_router(router)
    logger.info(f"Auto-discovered {len(routers)} route modules")

    # ── 全局错误处理中间件（P1-4: 来源 TTS_MultiModel） ─────────
    from .middleware.error_handler import register_error_handlers

    register_error_handlers(app)

    # ── Jinja2 模板引擎 + 静态文件托管 ──────────────────────
    templates_dir = Path(__file__).parent / "templates"
    static_dir = Path(__file__).parent / "static"

    # 模板上下文辅助函数
    def _locale_for(lang: str) -> str:
        """把 BCP-47 语言代码映射到 locales 目录下的文件名（zh-CN -> zh）。"""
        return lang.split("-")[0].lower()

    # 静态文件托管（Jinja2 模板引用的 CSS/JS/图片）
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # 页面路由（服务端渲染）
    if templates_dir.exists():
        from jinja2 import Environment, FileSystemLoader, select_autoescape

        from .i18n import t as _i18n_t

        templates = Jinja2Templates(
            env=Environment(
                loader=FileSystemLoader(str(templates_dir)),
                autoescape=select_autoescape(["html"]),
            ),
        )
        # 模板内提供 _() 翻译函数（回退到当前语言）
        templates.env.globals["_"] = lambda key, **kw: _i18n_t(key, lang="zh", default=key, **kw)
        logger.info(f"Jinja2 templates loaded from: {templates_dir}")

        def _page_ctx(request: Request) -> dict:
            """构造模板渲染上下文（从 cookie 读取主题/语言，与前端 localStorage 保持一致）。"""
            config = get_config()
            return {
                "request": request,
                "config": config,
                "version": config.version,
                "lang": request.cookies.get("imm_lang", "zh-CN"),
                "theme": request.cookies.get("imm_theme", "dark"),
                "locale_file": _locale_for(request.cookies.get("imm_lang", "zh-CN")),
            }

        @app.get("/", include_in_schema=False)
        async def index(request: Request):
            return templates.TemplateResponse(request, "index.html", _page_ctx(request))

        @app.get("/{full_path:path}", include_in_schema=False)
        async def catch_all(request: Request, full_path: str):
            # 静态资源（css/js/images/其他）已由 /static mount 接管，这里不重复处理
            if full_path.startswith(("css/", "js/", "images/", "static/")):
                raise HTTPException(status_code=404, detail="Not Found")
            # 其余路径回退到首页模板（前端路由 / 局部刷新）
            return templates.TemplateResponse(request, "index.html", _page_ctx(request))

    return app


# ── 入口 ──────────────────────────────────────────────────────
app = create_app()


def _ssl_kwargs(config) -> dict:
    """按 ``config.server.ssl`` 构造 uvicorn SSL 关键字参数。

    对应安全评估 H-01：``server.ssl`` 此前是"死配置"——有配置项、有 Pydantic
    模型，但无任何代码读取，导致 HTTPS 从未真正生效。本函数让它可用；
    证书缺失时明确告警并回退 HTTP，而非静默忽略。

    Returns:
        dict: 供 ``uvicorn.run(**kwargs)`` 使用的参数；未启用时为空字典。
    """
    ssl_cfg = getattr(config.server, "ssl", None)
    if not ssl_cfg or not getattr(ssl_cfg, "enabled", False):
        return {}

    certfile = str(getattr(ssl_cfg, "certfile", "") or "")
    keyfile = str(getattr(ssl_cfg, "keyfile", "") or "")
    if not certfile or not keyfile:
        logger.warning("[SSL] ssl.enabled=true 但未配置 certfile/keyfile，已回退为 HTTP")
        return {}

    cert_path = Path(certfile)
    key_path = Path(keyfile)
    if not cert_path.is_absolute():
        cert_path = Path(config.project_root) / certfile
    if not key_path.is_absolute():
        key_path = Path(config.project_root) / keyfile

    if not cert_path.exists() or not key_path.exists():
        logger.warning("[SSL] 证书文件不存在（cert=%s, key=%s），已回退为 HTTP", cert_path, key_path)
        return {}

    logger.info("[SSL] 已启用 HTTPS: cert=%s", cert_path)
    return {"ssl_certfile": str(cert_path), "ssl_keyfile": str(key_path)}


def run():
    """直接运行（桌面壳 P1：支持 --host/--port 覆盖，由 Tauri 壳传入空闲端口）。

    命令行参数优先级高于 config.yaml server 段（桌面壳启动时指定可用端口，
    避免多实例端口冲突；普通 `python -m integrated_app.app_server` 不受影响）。
    """
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="Image MultiModel 服务端")
    parser.add_argument("--host", default=None, help="监听地址（默认取 config.yaml server.host）")
    parser.add_argument("--port", type=int, default=None, help="监听端口（默认取 config.yaml server.port）")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="禁止自动打开浏览器（桌面壳使用；Web 直启场景由 auto_open_browser 控制）",
    )
    args = parser.parse_args()

    config = get_config()
    uvicorn.run(
        "integrated_app.app_server:app",
        host=args.host or config.server.host,
        port=args.port or config.server.port,
        workers=config.server.workers,
        reload=False,
        **_ssl_kwargs(config),
    )


if __name__ == "__main__":
    run()
