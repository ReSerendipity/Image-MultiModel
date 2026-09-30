"""
routes/engine_routes.py — 引擎加载 / 切换 / 卸载（PRD §2.3.3 + I-15）

对应 MASTER_PLAN §5.1: POST /api/engine/load, /unload, GET /api/engines
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..config import get_config
from ..engine_interface import get_registry
from ..i18n import get_error_message
from ..model_manager import ModelManager, ensure_model_status_sse_observer, get_model_manager
from ..model_registry import get_model_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/engine", tags=["engine"])


def _ensure_engine(registry: Any, engine_name: str, eng_cfg: Any) -> Any:
    """返回可用引擎实例；工厂缺失或为 ``None`` 占位时按 backend 构建并注册。

    Bugfix（本轮）：``model_registry.init_from_config`` 把每个引擎注册为
    ``_factories[name] = None`` 的「延迟注册」占位。此前本模块用
    ``if engine_name not in registry._factories`` 判空 —— 占位键存在，条件恒为
    假，于是真正的工厂永不注册，``registry.get()`` 一直返回 ``None``，
    加载链在 ``model_mgr.load_engine(name, None)`` → ``None.load()`` 处报
    ``'NoneType' object has no attribute 'load'``。改用 ``has_factory()`` 后，
    占位与缺失两种情形都会补上真实工厂。

    另外，工厂改为走 ``ModelRegistry.create_engine_instance``（按 ``backend``
    分发），而非此前硬编码的 NativeEngine，避免 ``backend: diffusers`` 的引擎
    被 UI 加载按钮构建成 native 引擎。
    """
    if not registry.has_factory(engine_name):
        instance = get_model_registry().create_engine_instance(
            engine_name=engine_name,
            display_name=eng_cfg.display_name,
            display_name_en=eng_cfg.display_name_en,
            backend=getattr(eng_cfg, "backend", "native"),
            config=eng_cfg.model_dump(),
        )
        registry.register(engine_name, lambda **_: instance)
    return registry.get(engine_name)


async def switch_engine_with_rollback(
    model_mgr: ModelManager,
    registry: Any,
    engine_name: str,
    eng_cfg: Any,
    *,
    load_engine=None,
    unload_engine=None,
    get_engine=None,
) -> dict[str, Any]:
    """加载 / 切换引擎，并在新引擎加载失败时回滚到切换前的活动引擎。

    P1·韧性（消除反模式 #6「切换无失败回滚 → 无引擎可用空窗」）：
    - 仅在加载成功后才 ``set_active(new)``；
    - 加载失败时 best-effort 回滚到 ``prev_active``，避免系统陷入
      「旧引擎已卸载、新引擎未加载」的空窗。

    Args:
        model_mgr: ModelManager 单例
        registry: 引擎注册表（InMemoryEngineRegistry）
        engine_name: 目标引擎名
        eng_cfg: 目标引擎配置（EngineConfig），用于错误文案
        load_engine / unload_engine / get_engine: 可注入，便于单测（默认走真实单例）

    Returns:
        dict: ``{"status", "rolled_back", "message", "engine_name"}``
    """
    load_engine = load_engine or model_mgr.load_engine
    unload_engine = unload_engine or model_mgr.unload_engine
    get_engine = get_engine or registry.get

    prev_active = registry.active_engine_name

    # 若当前有不同活动引擎，先卸载以释放显存
    if prev_active and prev_active != engine_name:
        try:
            await unload_engine(prev_active, get_engine(prev_active))
        except Exception as e:  # noqa: BLE001 - 卸载失败不阻断后续加载
            logger.warning("Failed to unload engine %s before switch: %s", prev_active, e)

    display = getattr(eng_cfg, "display_name", engine_name)
    try:
        await load_engine(engine_name, get_engine(engine_name))
    except Exception as e:  # noqa: BLE001 - 捕获加载失败以触发回滚
        logger.error("Engine '%s' load failed: %s", engine_name, e)
        rolled_back = False
        rollback_detail = ""
        if prev_active and prev_active != engine_name:
            try:
                await load_engine(prev_active, get_engine(prev_active))
                registry.set_active(prev_active)
                rolled_back = True
                rollback_detail = f"; 已回滚至 '{prev_active}'"
            except Exception as rb_e:  # noqa: BLE001
                logger.error("Rollback to '%s' also failed: %s", prev_active, rb_e)
                rollback_detail = f"; 回滚失败: {rb_e}"
        return {
            "engine_name": engine_name,
            "status": "error",
            "rolled_back": rolled_back,
            "message": f"引擎 '{display}' 加载失败: {e}{rollback_detail}",
        }

    # 加载成功后再设为活动引擎
    registry.set_active(engine_name)
    return {
        "engine_name": engine_name,
        "status": "loaded",
        "rolled_back": False,
        "message": f"Engine '{display}' loaded successfully",
    }


class EngineLoadRequest(BaseModel):
    """POST /api/engine/load 请求体"""

    engine_name: str


class EngineLoadResponse(BaseModel):
    engine_name: str
    status: str  # loading | loaded | error
    message: str = ""


@router.get("/engines")
async def list_engines(request: Request) -> dict[str, Any]:
    """GET /api/engines — 引擎列表（含元数据 + 加载状态）"""
    cfg = get_config()
    model_mgr = get_model_manager()
    registry = get_registry()

    engines = []
    for eng_name, eng_cfg in cfg.models.engines.items():
        state = model_mgr.get_state(eng_name).value
        engines.append(
            {
                "name": eng_name,
                "display_name": eng_cfg.display_name,
                "display_name_en": eng_cfg.display_name_en,
                "backend": eng_cfg.backend,
                "ready": state == "loaded",
                "state": state,
                "active": eng_name == registry.active_engine_name,
                "vram_gb": eng_cfg.vram_gb,
                "ram_gb": eng_cfg.ram_gb,
                "default_precision": eng_cfg.default_precision,
                "supported_features": eng_cfg.supported_features,
                "tags": eng_cfg.tags,
            }
        )

    return {
        "engines": engines,
        "active_engine": registry.active_engine_name,
        "count": len(engines),
    }


@router.post("/load")
async def load_engine(req: EngineLoadRequest, request: Request) -> dict[str, Any]:
    """POST /api/engine/load — 加载引擎（生成器进度 → SSE model_status）"""
    cfg = get_config()
    engine_name = req.engine_name

    if engine_name not in cfg.models.engines:
        raise HTTPException(404, detail=get_error_message("engine_not_found", name=engine_name))

    eng_cfg = cfg.models.engines[engine_name]
    registry = get_registry()
    model_mgr = get_model_manager()

    # 注册 SSE 观察者（幂等；同时覆盖 worker 按需加载这条常态路径）
    ensure_model_status_sse_observer()

    def resolve_engine(name: str) -> Any:
        """按需返回真实引擎实例（含切换前旧引擎的卸载路径）。"""
        target_cfg = cfg.models.engines.get(name)
        if target_cfg is None:
            # 不在配置中的引擎无从构建；已注册真实工厂时仍允许复用其实例
            return registry.get(name) if registry.has_factory(name) else None
        return _ensure_engine(registry, name, target_cfg)

    engine = resolve_engine(engine_name)
    if engine is None:  # pragma: no cover - 工厂已补齐，正常路径不可达
        raise HTTPException(500, detail=f"engine_factory_unavailable: {engine_name}")

    # P1·韧性：加载/切换 + 失败回滚（消除「无引擎可用」空窗）
    result = await switch_engine_with_rollback(
        model_mgr,
        registry,
        engine_name,
        eng_cfg,
        load_engine=model_mgr.load_engine,
        unload_engine=model_mgr.unload_engine,
        get_engine=resolve_engine,
    )
    return result


@router.post("/unload")
async def unload_engine(request: Request) -> dict[str, Any]:
    """POST /api/engine/unload — 卸载当前引擎"""
    registry = get_registry()
    model_mgr = get_model_manager()

    active = registry.active_engine_name
    if not active:
        return {"status": "ok", "message": "No active engine to unload"}

    engine = registry.get(active)
    if engine is None:
        # 幂等卸载：无活动实例时视为已卸载（对应测试体系评估 P2-9 修复
        # factory 为 None 的 TypeError → 500 已知问题）
        return {"status": "ok", "message": f"Engine '{active}' already unloaded"}
    try:
        await model_mgr.unload_engine(active, engine)
        return {
            "engine_name": active,
            "status": "unloaded",
            "message": f"Engine '{active}' unloaded",
        }
    except Exception as e:
        logger.error(f"Engine unload failed: {e}")
        raise HTTPException(500, detail=get_error_message("engine_unload_failed", detail=str(e)))
