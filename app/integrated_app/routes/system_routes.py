"""
routes/system_routes.py — health / SSE / GPU 状态

对应 MASTER_PLAN §5.1: GET /api/health
对应 MASTER_PLAN §5.2: SSE 单连接事件总线
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ..config import get_config
from ..gpu_utils import get_gpu_info_async
from ..observability.alerts import record_health_failure, record_health_success
from ..sse import get_sse_bus

logger = logging.getLogger(__name__)


def _disk_info() -> dict[str, Any]:
    """获取磁盘空间信息"""
    try:
        import shutil

        total, used, free = shutil.disk_usage("/")
        return {
            "total_gb": round(total / (1024**3), 1),
            "used_gb": round(used / (1024**3), 1),
            "free_gb": round(free / (1024**3), 1),
        }
    except Exception:
        return {"total_gb": 0, "used_gb": 0, "free_gb": 0}


router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
async def health_check(request: Request) -> dict[str, Any]:
    """
    GET /api/health — 后端/引擎/队列/资源状态摘要（真实数据源）

    包装层记录健康检查连续成功/失败（供 MLOps P0-4 ServiceUnhealthy 告警规则）。
    """
    try:
        payload = await _health_check_impl(request)
        record_health_success()
        return payload
    except Exception:
        record_health_failure()
        raise


async def _health_check_impl(request: Request) -> dict[str, Any]:
    """健康检查实现（无异常捕获，由 health_check 统一记录成败）。"""
    cfg = get_config()

    # 队列状态（来自 app.state.task_queue 实时统计）
    queue_status: dict[str, Any] = {}
    task_queue = getattr(request.app.state, "task_queue", None)
    if task_queue is not None:
        tasks = task_queue.list_tasks()
        status_count = {
            "pending": 0,
            "processing": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": 0,
        }
        for t in tasks:
            key = t.status.value if hasattr(t.status, "value") else str(t.status)
            if key in status_count:
                status_count[key] += 1
        queue_status = {
            "total": len(tasks),
            "pending": status_count["pending"],
            "processing": status_count["processing"],
            "completed": status_count["completed"],
            "failed": status_count["failed"],
            "cancelled": status_count["cancelled"],
        }

    # GPU 状态（P2-1：走线程池，避免 nvidia-smi 同步 subprocess 阻塞事件循环）
    gpu = await get_gpu_info_async()

    # 系统内存（psutil，requirements 已声明）
    memory_info: dict[str, Any] = {}
    try:
        import psutil

        vm = psutil.virtual_memory()
        memory_info = {
            "total_gb": round(vm.total / (1024**3), 1),
            "used_gb": round(vm.used / (1024**3), 1),
            "free_gb": round(vm.available / (1024**3), 1),
            "percent": vm.percent,
        }
    except Exception as e:
        logger.warning(f"Memory info unavailable: {e}")
        memory_info = {"total_gb": 0, "used_gb": 0, "free_gb": 0, "percent": 0}

    # 引擎状态（model_manager 真实加载状态）
    engines: list = []
    try:
        from ..engine_interface import get_registry
        from ..model_manager import get_model_manager

        registry = get_registry()
        model_mgr = get_model_manager()
        for eng_name, eng_cfg in cfg.models.engines.items():
            state = model_mgr.get_state(eng_name).value
            engines.append(
                {
                    "name": eng_name,
                    "display_name": eng_cfg.display_name,
                    "ready": state == "loaded",
                    "state": state,
                    "active": eng_name == registry.active_engine_name,
                }
            )
    except Exception as e:
        logger.warning(f"Engine state unavailable: {e}")
        for eng_name, eng_cfg in cfg.models.engines.items():
            engines.append(
                {
                    "name": eng_name,
                    "display_name": eng_cfg.display_name,
                    "ready": False,
                    "state": "unknown",
                    "active": eng_name == registry.active_engine_name,
                }
            )

    _health_payload = {
        "status": "ok",
        "version": cfg.version,
        "timestamp": time.time(),
        "server": {
            "host": cfg.server.host,
            "port": cfg.server.port,
        },
        "gpu": {
            "name": gpu.gpu_name,
            "backend": gpu.backend,
            "total_vram_gb": gpu.total_vram_gb,
            "used_vram_gb": gpu.used_vram_gb,
            "free_vram_gb": gpu.free_vram_gb,
        },
        "memory": memory_info,
        "disk": _disk_info(),
        "engines": engines,
        "queue": queue_status,
    }
    return _health_payload


@router.get("/system/health")
async def system_health_check(request: Request) -> dict[str, Any]:
    """
    GET /api/system/health — 桌面壳就绪契约端点（19dec0d B-2）

    壳（desktop/src-tauri/src/health_check.rs）以此路径做装后就绪探测并解析
    ``security.integrity``（篡改告警）。此前该路径不存在，被 SPA catch-all
    吞掉返回 index.html（200 text/html）→ 壳 JSON 解析恒失败 → 桌面装后
    永远「启动超时」（v1.3.0 发版阶段3 真机实测 P1，2026-10-03）。
    """
    payload = await _health_check_impl(request)
    integrity = getattr(request.app.state, "integrity_selfcheck", None) or {}
    payload["security"] = {
        "integrity": {
            "checked": bool(integrity.get("checked", False)),
            "failed": int(integrity.get("failed", 0) or 0),
            "failed_files": list(integrity.get("failed_files", []) or []),
            "manifest_signed": bool(integrity.get("manifest_signed", False)),
        }
    }
    return payload


@router.get("/events")
async def sse_events(request: Request) -> StreamingResponse:
    """
    GET /api/events — SSE 单连接事件总线

    事件类型: task_status / preview / model_status / gpu_status / queue_status / heartbeat
    """
    bus = get_sse_bus()
    queue = await bus.subscribe()

    async def event_stream():
        try:
            # 发送初始连接事件
            init_data = json.dumps({"type": "connected", "timestamp": time.time()})
            yield f"event: connected\ndata: {init_data}\n\n"

            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield msg
                except TimeoutError:
                    # 发送心跳
                    heartbeat = json.dumps({"timestamp": time.time()})
                    yield f"event: heartbeat\ndata: {heartbeat}\n\n"
        finally:
            bus.unsubscribe(queue)
            logger.info("SSE client disconnected")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/gpu")
async def gpu_status() -> dict[str, Any]:
    """GET /api/gpu — GPU 状态"""
    gpu = await get_gpu_info_async()
    return {
        "name": gpu.gpu_name,
        "backend": gpu.backend,
        "total_vram_gb": gpu.total_vram_gb,
        "used_vram_gb": gpu.used_vram_gb,
        "free_vram_gb": gpu.free_vram_gb,
    }
