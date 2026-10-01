"""
model_registry.py — 引擎注册表桥接 + 引擎工厂（M8 diffusers 迁移）

对应 MASTER_PLAN §4 / 附录 A3: model_registry.py
对应 PRD §4.2: Registry → SSE 桥接
对应 M8: diffusers 引擎工厂方法（按 backend 分发）
"""

from __future__ import annotations

import logging
import os
from typing import Any

from .engine_interface import ImageEngine, get_registry
from .model_manager import get_model_manager

logger = logging.getLogger(__name__)


class ModelRegistry:
    """
    引擎注册表 + ModelManager 桥接：
    - 注册引擎到 InMemoryEngineRegistry
    - 注册 ModelManager 观察者 → SSE
    - 提供 list / get / activate / deactivate 接口
    - create_engine_instance() 工厂方法（M8: 按 backend 分发）
    """

    def __init__(self) -> None:
        self._registry = get_registry()
        self._manager = get_model_manager()
        self._initialized = False

    def init_from_config(self, config: Any) -> None:
        """
        从 AppConfig 初始化引擎注册。

        Args:
            config: AppConfig 实例
        """
        if self._initialized:
            return

        for engine_name, engine_cfg in config.models.engines.items():
            # 懒注册：工厂函数在 get() 时才实例化
            # 这里注册工厂 + 配置
            logger.info(f"Registering engine: {engine_name}")

            # 注册为可延迟实例化的引擎
            self._registry._factories[engine_name] = None  # type: ignore
            self._registry._configs[engine_name] = {
                "name": engine_name,
                "display_name": engine_cfg.display_name,
                "display_name_en": engine_cfg.display_name_en,
                "backend": getattr(engine_cfg, "backend", "native"),
                "config": engine_cfg.model_dump(),
            }

        # 设置默认引擎
        default_engine = config.models.default_engine
        if default_engine in config.models.engines:
            self._registry.set_active(default_engine)

        # 数据治理报告 P2-2：权重指纹启动登记（内存态，手工登记值不覆盖）。
        # 磁盘留档由 scripts/generate_weight_manifest.py 的权重清单承担。
        try:
            from .model_card import register_weight_fingerprint

            for engine_name, engine_cfg in config.models.engines.items():
                fp = register_weight_fingerprint(engine_cfg, config.models, config.project_root)
                if fp:
                    logger.info("Weight fingerprint registered: %s (%s…)", engine_name, fp[:12])
        except Exception as e:  # noqa: BLE001 - 指纹登记失败不阻断引擎注册
            logger.warning("Weight fingerprint registration failed: %s", e)

        self._initialized = True
        logger.info(f"ModelRegistry initialized with {len(config.models.engines)} engines")

    def list_engines(self) -> list[dict[str, Any]]:
        """列出所有引擎（含状态）"""
        engines = self._registry.list_engines()
        # 补充 ModelManager 状态
        for eng in engines:
            state = self._manager.get_state(eng["name"])
            eng["model_state"] = state.value
        return engines

    def get_active_engine_name(self) -> str | None:
        return self._registry.active_engine_name

    def set_active(self, name: str) -> None:
        self._registry.set_active(name)

    def get_engine_config(self, name: str) -> dict[str, Any] | None:
        return self._registry._configs.get(name)

    def create_engine_instance(
        self,
        engine_name: str,
        display_name: str = "",
        display_name_en: str = "",
        backend: str = "native",
        config: dict[str, Any] | None = None,
    ) -> ImageEngine:
        """创建引擎实例（M8: 按 backend 分发）

        根据 backend 类型创建对应的引擎实例：
        - "diffusers": ZImageDiffusersEngine（M8 新引擎，Apache-2.0）
        - "native": NativeEngine（deprecated，保留回滚）

        Args:
            engine_name: 引擎唯一标识符
            display_name: UI 显示名称
            display_name_en: 英文显示名称
            backend: 后端类型（"native" / "diffusers"）
            config: 引擎配置字典（从 EngineConfig.model_dump() 获取）

        Returns:
            ImageEngine: 实现了 ImageEngine Protocol 的引擎实例

        Raises:
            ValueError: 未知的 backend 类型
        """
        # 测试体系评估 P0-2：假引擎测试缝。仅当显式设置 IMM_FAKE_ENGINE=1 时返回
        # 无 GPU 的 FakeEngine，使 prompt→进度→输出 旅程在 CI 可复现。生产环境不设置
        # 该变量，绝不生效。
        if os.environ.get("IMM_FAKE_ENGINE") == "1":
            from .testing.fake_engine import FakeEngine

            logger.info("Using FakeEngine (IMM_FAKE_ENGINE=1) for engine: %s", engine_name)
            return FakeEngine(
                name=engine_name,
                display_name=display_name,
                display_name_en=display_name_en,
                config=config or {},
            )

        if backend == "diffusers":
            from .native.diffusers_engine import ZImageDiffusersEngine

            logger.info(f"Creating diffusers engine: {engine_name}")
            return ZImageDiffusersEngine(
                name=engine_name,
                display_name=display_name,
                display_name_en=display_name_en,
                config=config or {},
            )
        elif backend == "native":
            # P2-vlm-chat M1：role == "vlm" 走 VlmEngine 看图聊天分支；
            # 其余沿用 NativeEngine（comfy_kernel 进程内推理）。
            role = (config or {}).get("role", "") if isinstance(config, dict) else ""
            if role == "vlm":
                from .native.vlm_engine import VlmEngine

                logger.info(f"Creating VLM engine: {engine_name}")
                return VlmEngine(
                    name=engine_name,
                    display_name=display_name,
                    display_name_en=display_name_en,
                    config=config or {},
                )
            from .native.engine import NativeEngine

            logger.info(f"Creating native engine: {engine_name}")
            return NativeEngine(
                name=engine_name,
                display_name=display_name,
                display_name_en=display_name_en,
                config=config or {},
            )
        else:
            raise ValueError(f"Unknown backend: {backend!r}, expected 'native' or 'diffusers'")


# ── 全局单例 ──────────────────────────────────────────────────
_global_registry_bridge: ModelRegistry | None = None


def get_model_registry() -> ModelRegistry:
    global _global_registry_bridge
    if _global_registry_bridge is None:
        _global_registry_bridge = ModelRegistry()
    return _global_registry_bridge
