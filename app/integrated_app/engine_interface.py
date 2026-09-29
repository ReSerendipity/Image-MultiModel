"""
engine_interface.py — ImageEngine Protocol + InMemoryEngineRegistry

对应 MASTER_PLAN §4 / 附录 A1: engine_interface.py
对应 PRD §4.1: ImageEngine Protocol 4 方法 + Registry
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ── 进度回调类型 ──────────────────────────────────────────────
ProgressCallback = Callable[[int, str, dict[str, Any] | None], None]
# 参数: (progress_pct, phase_text, extra_data)


# ── generation_config 类型 ────────────────────────────────────
@dataclass
class GenerationConfig:
    """
    generation_config 22 项（PRD 2.4.2/2.5.2 / MASTER_PLAN §5.3）

    8 基础 + LoRA 6 层 × (name, strength) + SeedVR2 + Eses + VRAM + 输出 + 引擎版本
    """

    # ── 8 基础参数 ──
    positive_prompt: str = ""
    negative_prompt: str = ""
    cfg: float = 1.0
    steps: int = 8
    width: int = 1024
    height: int = 1024
    seed: int = -1
    batch_size: int = 1

    # ── LoRA 6 层（id=16~21） ──
    lora_1_name: str = ""
    lora_1_strength: float = 1.0
    lora_2_name: str = ""
    lora_2_strength: float = 0.7
    lora_3_name: str = ""
    lora_3_strength: float = 0.5
    lora_4_name: str = ""
    lora_4_strength: float = 0.4
    lora_5_name: str = ""
    lora_5_strength: float = 0.3
    lora_6_name: str = ""
    lora_6_strength: float = 0.2

    # ── 动态 LoRA 栈（不局限于 6 层；优先使用，空则回退旧 6 层字段）──
    lora_stack: list[dict] = field(default_factory=list)  # [{name, strength}, ...]

    # ── SeedVR2 超分（id=61/62/63） ──
    seedvr2_enable: bool = True
    seedvr2_resolution: int = 2048
    seedvr2_seed: int = -1
    seedvr2_color_correction: str = "lab"

    # ── Eses 双图对比（id=59） ──
    eses_enable: bool = True
    eses_compare_axis: str = "horizontal"

    # ── ReservedVRAM（id=60） ──
    vram_enable: bool = True
    vram_reserved_gb: float = 0.6
    vram_mode: str = "auto"
    vram_seed: int = -1

    # ── 输出 ──
    output_format: str = "png"
    output_prefix: str = ""

    # ── 引擎版本 / 工作流 SHA256 ──
    engine_name: str = ""
    workflow_sha256: str = ""

    # ── native latent 格式（由引擎 config 下发；None 时执行器自查）──
    latent_channels: int | None = None
    latent_downscale: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """序列化为 JSON 可存储的字典"""
        return {k: v for k, v in self.__dict__.items()}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> GenerationConfig:
        """从字典恢复"""
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore
        return cls(**{k: v for k, v in d.items() if k in known})

    def effective_lora_stack(self) -> list[dict]:
        """返回实际生效的 LoRA 栈。

        优先使用动态 ``lora_stack``；为空时回退到旧 6 层字段
        （``lora_N_name`` + ``lora_N_strength``），供前端自定义数量与旧数据兼容。
        """
        if self.lora_stack:
            return [dict(x) for x in self.lora_stack if x.get("name")]
        stack: list[dict] = []
        for i in range(1, 7):
            name = getattr(self, f"lora_{i}_name", "") or ""
            if name:
                stack.append({"name": name, "strength": getattr(self, f"lora_{i}_strength", 1.0)})
        return stack


# ── ImageEngine Protocol ─────────────────────────────────────
@runtime_checkable
class ImageEngine(Protocol):
    """
    引擎协议（PRD §4.1）：
    - is_ready / load / unload / infer_txt2img / cancel
    """

    @property
    def name(self) -> str:
        """引擎唯一标识"""
        ...

    @property
    def display_name(self) -> str:
        """引擎显示名称"""
        ...

    def is_ready(self) -> bool:
        """引擎是否已加载就绪"""
        ...

    async def load(self, on_progress: ProgressCallback | None = None) -> None:
        """
        加载引擎模型到 GPU。

        Args:
            on_progress: 加载进度回调 (pct, phase, extra)
        """
        ...

    async def unload(self) -> None:
        """卸载引擎模型，释放 GPU 显存"""
        ...

    async def infer_txt2img(
        self,
        config: GenerationConfig,
        on_progress: ProgressCallback | None = None,
    ) -> list[str]:
        """
        执行文生图推理。

        Args:
            config: 完整的 generation_config
            on_progress: 推理进度回调

        Returns:
            输出图像路径列表（original / upscaled / compare）
        """
        ...

    async def cancel(self) -> None:
        """取消当前推理（发送 /interrupt + 清理队列）"""
        ...


# ── InMemoryEngineRegistry ───────────────────────────────────
class InMemoryEngineRegistry:
    """
    引擎注册表（附录 A1）
    - register(name, engine_class, config)
    - get(name) → engine instance
    - list_engines() → [name, display_name, ready]
    """

    def __init__(self) -> None:
        self._factories: dict[str, Callable[..., ImageEngine]] = {}
        self._instances: dict[str, ImageEngine] = {}
        self._configs: dict[str, dict[str, Any]] = {}
        self._active: str | None = None

    def register(
        self,
        name: str,
        factory: Callable[..., ImageEngine],
        config: dict[str, Any] | None = None,
    ) -> None:
        """注册引擎工厂"""
        self._factories[name] = factory
        self._configs[name] = config or {}
        logger.info(f"Engine registered: {name}")

    def has_factory(self, name: str) -> bool:
        """是否已注册**可实例化**的工厂。

        ``model_registry.init_from_config`` 以 ``_factories[name] = None`` 做
        「延迟注册」占位，此时 ``get()`` 会返回 ``None``（表示尚无实例）。
        调用方若需要「能拿到实例」，必须用本方法判空而不是 ``name in _factories``
        ——后者对 None 占位也返回 True，会让调用链拿到 None 并在
        ``engine.load()`` 处炸成 ``'NoneType' object has no attribute 'load'``。
        """
        return self._factories.get(name) is not None

    def get(self, name: str) -> ImageEngine | None:
        """获取引擎实例（懒加载）。

        返回 None 表示尚无已构建实例（如工厂为 None 的延迟注册引擎，
        其实际实例由 ``create_engine_instance`` 构建）。调用方应将其视为
        "未加载" 处理。对应测试体系评估 P2-9 修复：此前 factory=None 时
        ``None(**config)`` 抛 TypeError。
        """
        if name not in self._factories:
            raise KeyError(f"Engine not registered: {name}")
        if name in self._instances:
            return self._instances[name]
        factory = self._factories[name]
        if factory is None:
            return None
        self._instances[name] = factory(**self._configs.get(name, {}))
        return self._instances[name]

    def list_engines(self) -> list[dict[str, Any]]:
        """列出所有已注册引擎"""
        result = []
        for name, factory in self._factories.items():
            eng = self._instances.get(name)
            result.append(
                {
                    "name": name,
                    "display_name": getattr(eng, "display_name", name) if eng else name,
                    "ready": eng.is_ready() if eng else False,
                    "active": name == self._active,
                }
            )
        return result

    def set_active(self, name: str) -> None:
        """设置当前活动引擎"""
        if name not in self._factories:
            raise KeyError(f"Engine not registered: {name}")
        self._active = name

    @property
    def active_engine_name(self) -> str | None:
        return self._active

    def get_active(self) -> ImageEngine | None:
        if self._active:
            return self.get(self._active)
        return None

    def clear(self) -> None:
        """清除所有引擎实例"""
        for eng in self._instances.values():
            try:
                import asyncio

                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(eng.unload())
                else:
                    loop.run_until_complete(eng.unload())
            except Exception as e:
                logger.warning(f"Error unloading engine: {e}")
        self._instances.clear()
        self._active = None


# ── 全局注册表单例 ────────────────────────────────────────────
_global_registry: InMemoryEngineRegistry | None = None


def get_registry() -> InMemoryEngineRegistry:
    global _global_registry
    if _global_registry is None:
        _global_registry = InMemoryEngineRegistry()
    return _global_registry
