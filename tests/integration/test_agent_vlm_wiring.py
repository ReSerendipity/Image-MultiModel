"""tests/integration/test_agent_vlm_wiring.py — P2-vlm-chat M2/M6 装配接线验收

M2/M6 的注入式依赖（``vlm_context_fn`` / ``edit_engine_fn``）在编排层定义后，必须由
``routes/agent_routes._get_orchestrator`` **真正装配**才生效——否则服务起来后带图提问
照样是 ``unavailable``、编辑意图也拿不到引擎名，功能等于没接上。

本文件验证的是**装配层**（不是替身）：用 TestClient 起真实 app、读真实 config.yaml，
断言装配出的 orchestrator 上两个 fn 挂在真实引擎上。

覆盖：
1. 有 edit 引擎 → ``edit_engine_fn()`` 返回它，且与工具侧 ``edit_image`` **同一口径**
   （一处改了另一处自动跟着走，防判定漂移）
2. 有 role=vlm 引擎 → ``vlm_context_fn`` 已装配且是协程函数
3. 视觉上下文延迟加载：实例按需创建；被 ADR-0001 卸载（``is_ready()`` 变 False）后
   自动重载，不留"看着还在、实际已废"的僵尸实例
4. 退化路径：没配 VLM 引擎就不装配 fn（如实上报 unavailable，绝不伪造视觉描述）

注意：本机离线、Qwen3-VL 的 HF 目录未就位，故这里**不断言真实推理结果**，只断言
「接线存在且调度正确」；真实前向由 ``scripts/preflight_qwen3vl.py`` 闭环。
"""

from __future__ import annotations

import inspect
import re
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.integrated_app.app_server import create_app
from app.integrated_app.config import get_config
from app.integrated_app.routes import agent_routes as mod


@pytest.fixture(scope="module")
def client() -> Any:
    with TestClient(create_app()) as c:
        yield c


def _expected_edit_engine() -> str | None:
    """独立重算一遍「真解」：测试不跟着被测实现复读同一个函数，否则答案错了也全绿。"""
    cfg = get_config()
    for name, ecfg in cfg.models.engines.items():
        if "edit" in (ecfg.supported_features or []):
            return name
    return None


def test_edit_engine_fn_resolves_real_engine(client: TestClient) -> None:
    orch = mod._get_orchestrator(SimpleNamespace(app=client.app))
    assert orch.edit_engine_fn is not None
    assert orch.edit_engine_fn() == _expected_edit_engine()
    # 真实 config 里确实存在声明 edit 能力的引擎（本机 qwen_image_edit_native）
    assert orch.edit_engine_fn() is not None


def test_edit_engine_fn_shares_single_source_with_tool_path() -> None:
    """工具侧 edit_image 与 M6 桥接必须同口径：不再各自遍历 config 判 edit 能力。

    ⚠️ 只禁止**判定逻辑**（遍历 engines / 读 supported_features）；错误提示文案里
    提到 supported_features 是正常的，把它一并断言掉会让测试误报。
    """
    src = inspect.getsource(mod._execute_edit_image)
    duplicate = re.compile(r'for\s+\w+,\s*\w+\s+in\s+cfg\.models\.engines\.items\(\)|"\s*edit\s*"\s+in\s*\(')
    assert "_first_edit_engine()" in src, "工具侧没复用统一口径"
    assert not duplicate.search(src), "工具侧仍有重复的 edit 能力判定逻辑，会与 M6 桥接口径漂移"


def test_vlm_context_fn_is_wired_when_vlm_engine_configured(client: TestClient) -> None:
    has_vlm = mod._first_vlm_engine() is not None
    orch = mod._get_orchestrator(SimpleNamespace(app=client.app))
    if has_vlm:
        assert orch.vlm_context_fn is not None
        assert inspect.iscoroutinefunction(orch.vlm_context_fn)
    else:
        assert orch.vlm_context_fn is None


def test_no_vlm_engine_means_no_fake_encoder() -> None:
    """没配 VLM 引擎就不许装配假编码器（宁报 unavailable，不伪造视觉描述）。"""
    assert mod._build_vlm_context_fn(None) is None


class _FakeVlm:
    """替身引擎：只模拟 ready/load/infer 的调度语义，不做任何真实推理。"""

    def __init__(self, name: str, reply: str = "这张图的描述") -> None:
        self.name = name
        self._reply = reply
        self._ready = False
        self.loads = 0
        self.chats: list[tuple[str, list[str]]] = []

    def is_ready(self) -> bool:
        return self._ready

    async def load(self, on_progress: Any = None) -> None:
        self.loads += 1
        self._ready = True

    async def infer_chat(self, prompt: str, images: list[str] | None = None, on_progress: Any = None) -> str:
        self.chats.append((prompt, list(images or [])))
        return self._reply

    async def unload(self) -> None:
        self._ready = False


@pytest.mark.asyncio
async def test_vlm_context_reloads_after_unload(monkeypatch: pytest.MonkeyPatch) -> None:
    """被 ADR-0001 卸掉的 VLM 必须重新 load，否则会变成僵尸实例（调用成功但结果是空的）。"""
    fake = _FakeVlm("qwen3_vl_8b_native")
    monkeypatch.setattr(mod, "_create_vlm_engine", lambda name: fake)

    fn = mod._build_vlm_context_fn("qwen3_vl_8b_native")
    assert fn is not None

    out = await fn("问什么", ["outputs/a.png"])
    assert out == "这张图的描述"
    assert fake.loads == 1, "首次调用应触发按需加载"

    await fake.unload()  # 模拟生图请求触发的 request_vlm_unload
    await fn("再问一次", ["outputs/b.png"])
    assert fake.loads == 2, "被卸载后没有重新 load，VLM 会变成僵尸实例"
    assert fake.chats[-1] == ("再问一次", ["outputs/b.png"])


@pytest.mark.asyncio
async def test_vlm_load_failure_surfaces_as_error_not_fake_description(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """加载失败必须冒泡成异常（编排层转 status=error），绝不允许返回编造的描述。"""

    class _Broken(_FakeVlm):
        async def load(self, on_progress: Any = None) -> None:
            self.loads += 1
            raise RuntimeError("Qwen3-VL HF 模型目录未就位")

    fake = _Broken("qwen3_vl_8b_native")
    monkeypatch.setattr(mod, "_create_vlm_engine", lambda name: fake)

    fn = mod._build_vlm_context_fn("qwen3_vl_8b_native")
    assert fn is not None
    with pytest.raises(RuntimeError, match="未就位"):
        await fn("问什么", ["outputs/a.png"])
    assert fake.chats == [], "加载失败就绝不能在 engine 上跑出任何推理"
