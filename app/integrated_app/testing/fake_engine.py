"""
fake_engine.py — 测试用假引擎（无 GPU 推理）

对应测试体系评估 P0-2：E2E / 集成生成流程去 GPU 化。

仅当环境变量 ``IMM_FAKE_ENGINE=1`` 时由 ``model_registry.create_engine_instance``
返回，生产环境不设置该变量，绝不生效。假引擎实现 ``ImageEngine`` 协议，
``infer_txt2img`` 写出若干合法的 1×1 PNG 并返回其绝对路径，使完整
prompt → 进度 → 输出 旅程在无 GPU 环境下也能跑通（用于 CI 可复现的 E2E / 集成）。
"""

from __future__ import annotations

import asyncio
import base64
import tempfile
from pathlib import Path
from typing import Any

from ..engine_interface import GenerationConfig, ProgressCallback

# 1×1 透明 PNG（base64 解码，免依赖 PIL）
_FAKE_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
_FAKE_PNG = base64.b64decode(_FAKE_PNG_B64)


class FakeEngine:
    """无 GPU 的假引擎，用于测试生成链路。

    属性 ``name`` / ``display_name`` / ``is_ready`` / ``_cancel_requested`` /
    ``_thumbnail_path`` 均按 ``app_server.worker_func`` 的运行期访问方式提供。
    """

    def __init__(
        self,
        name: str = "fake",
        display_name: str = "Fake Engine",
        display_name_en: str = "Fake Engine",
        config: dict[str, Any] | None = None,
    ) -> None:
        self._name = name
        self._display_name = display_name
        self._display_name_en = display_name_en
        self._config = config or {}
        self._ready = False
        self._cancel_requested = False
        self._out_dir = Path(tempfile.mkdtemp(prefix="imm_fake_"))
        self._thumbnail_path: str = ""

    @property
    def name(self) -> str:
        return self._name

    @property
    def display_name(self) -> str:
        return self._display_name

    def is_ready(self) -> bool:
        return self._ready

    async def load(self, on_progress: ProgressCallback | None = None) -> None:
        if on_progress:
            on_progress(0, "load", {})
        await asyncio.sleep(0.01)
        self._ready = True
        if on_progress:
            on_progress(100, "load", {})

    async def unload(self) -> None:
        self._ready = False

    async def cancel(self) -> None:
        self._cancel_requested = True

    async def infer_txt2img(
        self,
        config: GenerationConfig,
        on_progress: ProgressCallback | None = None,
    ) -> list[str]:
        """写出 batch_size 个合法 1×1 PNG，模拟进度并尊重取消。

        Returns:
            list[str]: 输出图片绝对路径列表（长度 = 实际产出数）。
        """
        batch = max(1, int(getattr(config, "batch_size", 1) or 1))
        import sys as _sys

        print(f"[FAKE_ENGINE] batch_size={getattr(config, 'batch_size', None)!r} -> writing {batch}", file=_sys.stderr)
        paths: list[str] = []
        for i in range(batch):
            if self._cancel_requested:
                break
            if on_progress:
                on_progress(int((i + 1) / batch * 100), "generating", {"index": i})
            p = self._out_dir / f"fake_{i:04d}.png"
            p.write_bytes(_FAKE_PNG)
            paths.append(str(p))
            await asyncio.sleep(0.001)
        self._thumbnail_path = paths[0] if paths else ""
        return paths

    async def infer_edit(
        self,
        config: GenerationConfig,
        on_progress: ProgressCallback | None = None,
    ) -> list[str]:
        """假编辑：与 infer_txt2img 同语义（CI 用），供 edit 链路的测试复用。"""
        return await self.infer_txt2img(config, on_progress=on_progress)
