"""
model_manager.py — 模型生命周期管理

对应 MASTER_PLAN §4 / 附录 A2: model_manager.py
对应 PRD §4.2: ModelManager 生命周期 → SSE
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ModelState(str, Enum):
    UNLOADED = "unloaded"
    LOADING = "loading"
    LOADED = "loaded"
    UNLOADING = "unloading"
    ERROR = "error"


class ModelManager:
    """
    模型生命周期管理器（观察者模式 → SSE 推送）。

    职责：
    - 管理引擎的 load / unload 生命周期
    - 推送 model_status 事件到 SSE
    - 防止重复加载
    """

    def __init__(self) -> None:
        self._states: dict[str, ModelState] = {}
        self._observers: list[Callable[[str, ModelState, dict], None]] = []

    def register_observer(self, cb: Callable[[str, ModelState, dict], None]) -> None:
        """注册状态变更观察者（→ SSE）"""
        self._observers.append(cb)

    def _notify(self, engine_name: str, state: ModelState, extra: dict | None = None) -> None:
        data = extra or {}
        for cb in self._observers:
            try:
                cb(engine_name, state, data)
            except Exception as e:
                logger.warning(f"ModelManager observer error: {e}")

    def get_state(self, engine_name: str) -> ModelState:
        return self._states.get(engine_name, ModelState.UNLOADED)

    async def load_engine(self, engine_name: str, engine: Any) -> None:
        """
        加载引擎模型。

        Args:
            engine_name: 引擎名称
            engine: 实现 ImageEngine Protocol 的实例
        """
        current = self.get_state(engine_name)
        if current == ModelState.LOADED:
            logger.info(f"Engine {engine_name} already loaded")
            return
        if current == ModelState.LOADING:
            logger.warning(f"Engine {engine_name} is already loading")
            return

        self._states[engine_name] = ModelState.LOADING
        self._notify(engine_name, ModelState.LOADING)

        try:
            await engine.load(
                on_progress=lambda pct, phase, extra: self._notify(
                    engine_name,
                    ModelState.LOADING,
                    {"progress": pct, "phase": phase, **(extra or {})},
                )
            )
            self._states[engine_name] = ModelState.LOADED
            self._notify(engine_name, ModelState.LOADED)
        except Exception as e:
            self._states[engine_name] = ModelState.ERROR
            self._notify(engine_name, ModelState.ERROR, {"error": str(e)})
            raise

    async def unload_engine(self, engine_name: str, engine: Any) -> None:
        """卸载引擎模型"""
        current = self.get_state(engine_name)
        if current == ModelState.UNLOADED:
            return

        if engine is None or not callable(getattr(engine, "unload", None)):
            # 无有效实例（factory 未构建 / 已释放）→ 视为已卸载，幂等返回。
            # 对应测试体系评估 P2-9 修复：factory 为 None 时原会抛
            # 'NoneType' object is not callable → 500 已知问题。
            self._states[engine_name] = ModelState.UNLOADED
            self._notify(engine_name, ModelState.UNLOADED)
            return

        self._states[engine_name] = ModelState.UNLOADING
        self._notify(engine_name, ModelState.UNLOADING)

        try:
            await engine.unload()
            self._states[engine_name] = ModelState.UNLOADED
            self._notify(engine_name, ModelState.UNLOADED)
        except Exception as e:
            self._states[engine_name] = ModelState.ERROR
            self._notify(engine_name, ModelState.ERROR, {"error": str(e)})
            raise

    def get_all_states(self) -> dict[str, dict[str, Any]]:
        """获取所有引擎状态摘要"""
        return {name: {"state": state.value} for name, state in self._states.items()}


# ── 全局单例 ──────────────────────────────────────────────────
_global_manager: ModelManager | None = None


def get_model_manager() -> ModelManager:
    global _global_manager
    if _global_manager is None:
        _global_manager = ModelManager()
    return _global_manager


# ── SSE 桥接（幂等） ──────────────────────────────────────────
_observer_registered = False


def ensure_model_status_sse_observer() -> bool:
    """幂等注册「ModelManager → SSE ``model_status``」观察者；返回是否本次注册。

    ⚠️ 为什么必须抽成公共函数（2026-09-30 修复）：
    该观察者此前**只在 ``POST /api/engine/load`` 里注册**。而引擎的常态加载路径是
    **任务 worker 在首个生成请求时按需加载**（``services/task_worker`` → ``create_engine_instance``
    → ``manager.load_engine``），这条路径从不经过 ``/api/engine/load`` —— 于是
    "模型加载中" 的 ``model_status`` 事件**在真实使用中根本不会推送**，前端无从
    显示加载进度（评估报告第八章 C-8 的"引擎冷启动提示"因此无法只靠前端实现）。
    现改为：应用装配期（Agent 路由首次使用 / 引擎加载端点）调用本函数，注册一次即全局生效。

    必须在**有运行中事件循环**的上下文调用（路由处理器/生命周期）；无循环时返回 False
    并告警，不抛异常。
    """
    global _observer_registered
    if _observer_registered:
        return False
    try:
        import asyncio

        from .sse import get_sse_bus

        main_loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("model_status SSE 观察者注册失败：当前无运行中的事件循环")
        return False

    sse_bus = get_sse_bus()
    manager = get_model_manager()

    def _on_model_status(engine_name: str, state: ModelState, extra: dict) -> None:
        payload = {"engine": engine_name, "state": state.value, **(extra or {})}
        if main_loop.is_closed():
            return
        # 先建协程再提交：提交失败（关服瞬间循环已停）必须显式 close()，
        # 否则留下 "coroutine 'SSEBus.publish' was never awaited" 的 RuntimeWarning。
        coro = sse_bus.publish("model_status", payload)
        try:
            asyncio.run_coroutine_threadsafe(coro, main_loop)
        except RuntimeError:  # pragma: no cover - 关服瞬间循环已停
            coro.close()
            logger.debug("model_status 推送跳过：事件循环已关闭")

    manager.register_observer(_on_model_status)
    _observer_registered = True
    logger.info("model_status SSE 观察者已注册")
    return True
