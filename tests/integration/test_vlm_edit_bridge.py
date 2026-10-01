"""tests/integration/test_vlm_edit_bridge.py — P2-vlm-chat M6 编辑指令桥接验收

对应 ``docs/roadmap/P2-vlm-chat.md`` 的 M6 验收口径：
「VLM 输出的自然语言修改建议解析为结构化 edit 指令 → 一键 POST /api/generate」。

实测更正（2026-10-01）：文档里写的 ``POST /api/generate?mode=edit`` **不存在**。
真实入口是 ``POST /api/generate`` 的**请求体字段** ``edit_mode: true`` +
``reference_image_path``（``services/generation_service.py`` 有显式守卫：
引擎不支持 edit、或缺参考图 → 422）。前端桥接因此按该契约发请求，本文件把「解析出的
intent 能落成一份合法的编辑请求」一并钉住，避免桥接指向不存在的端点。

覆盖：
1. 解析：模型吐出 ``[[EDIT]]...[[/EDIT]]`` → ``EditIntent(prompt, source)``
2. 不臆造：无标记块 / 标记块为空 / 只有起始标记 → ``None``（绝不猜 prompt 改用户的图）
3. 编排层：本轮带图 + 有标记 → ``final`` 事件带 ``edit_intent``（prompt / reference_images / engine_name），
   且标记块从正文里剥掉（标记是机器协议，不该出现在聊天气泡里）
4. 无图轮次即使有标记也不下发 intent（没有参考图就没法编辑）
5. 编辑引擎解析：注入的 ``edit_engine_fn`` 生效；抛异常不打断整轮回复
6. 契约：解析出的字段确实能被 ``GenerateRequest`` 接受且带上 ``edit_mode``
"""

from __future__ import annotations

from typing import Any

import pytest

from app.integrated_app.agent.orchestrator import AgentOrchestrator
from app.integrated_app.native.vlm_engine import (
    EDIT_MARKER_END,
    EDIT_MARKER_START,
    EditIntent,
    build_edit_few_shot,
    parse_edit_intent,
    strip_edit_block,
)
from app.integrated_app.services.generation_service import GenerateRequest

# ── 解析层（parse_edit_intent / strip_edit_block）────────────


def test_parse_extracts_prompt_and_source() -> None:
    text = f"这张背景有点闷。{EDIT_MARKER_START}把背景换成雪天，光线变成阴天{EDIT_MARKER_END}要吗？"
    intent = parse_edit_intent(text)
    assert isinstance(intent, EditIntent)
    assert intent is not None
    assert intent.prompt == "把背景换成雪天，光线变成阴天"
    # source 用于回显/审计，必须是原文里的真实片段
    assert intent.source in text


def test_parse_few_shot_teaches_markers_not_semantics() -> None:
    few = build_edit_few_shot()
    assert EDIT_MARKER_START in few and EDIT_MARKER_END in few
    # few-shot 只教格式与时机，不得替模型决定画面内容（否则就是臆造）
    assert "不要" in few


@pytest.mark.parametrize(
    "text",
    [
        "",
        None,
        "这张图氛围很好看啊",
        "能帮我分析一下构图吗？",
        f"{EDIT_MARKER_START}   {EDIT_MARKER_END}",  # 空块：不臆造 prompt
        f"{EDIT_MARKER_START}把背景换掉",  # 只有起始标记：残缺不算指令
    ],
)
def test_parse_returns_none_without_usable_block(text: Any) -> None:
    """没吐出可用标记块就一律 None——宁可前端不出现按钮，也不能把闲聊当编辑指令。"""
    assert parse_edit_intent(text) is None


def test_strip_edit_block_hides_machine_protocol() -> None:
    text = f"先说结论。{EDIT_MARKER_START}换背景{EDIT_MARKER_END}补充一句。"
    stripped = strip_edit_block(text)
    assert EDIT_MARKER_START not in stripped and EDIT_MARKER_END not in stripped
    assert "先说结论。" in stripped and "补充一句。" in stripped


# ── 编排层（AgentOrchestrator 事件序列）─────────────────────


class _FakeLLM:
    """替身 LLM：固定返回一段文本（可含编辑标记块），不做任何真实推理。"""

    def __init__(self, content: str) -> None:
        self.content = content

    async def chat_completion(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        return {"choices": [{"message": {"content": self.content, "role": "assistant"}}]}

    async def chat_completion_stream(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Any:
        yield {"type": "done", "message": {"content": self.content, "role": "assistant"}}


async def _executor(name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"status": "ok", "tool": name}


def _orch(
    content: str, edit_engine: str | None = "qwen_image_edit_native", *, engine_fn: Any = ...
) -> AgentOrchestrator:
    """构造编排器；``engine_fn=...``（默认）用固定值，传哨兵表示不注入，传 callable 用之。"""
    if engine_fn is None:
        return AgentOrchestrator(llm=_FakeLLM(content), tool_executor=_executor)
    if engine_fn is not ...:
        return AgentOrchestrator(llm=_FakeLLM(content), tool_executor=_executor, edit_engine_fn=engine_fn)
    return AgentOrchestrator(llm=_FakeLLM(content), tool_executor=_executor, edit_engine_fn=lambda: edit_engine)


async def _final_payload(content: str, images: list[str] | None, **kw: Any) -> dict[str, Any]:
    """跑一轮非流式，返回 final 事件的载荷。"""
    orch = _orch(content, **kw)
    events = await orch.run_turn("s-edit", "把背景换成雪天", None, images=images)
    finals = [e for e in events if e.type == "final"]
    assert len(finals) == 1
    return finals[0].data


async def test_final_carries_intent_when_turn_has_images() -> None:
    content = f"可以。{EDIT_MARKER_START}把背景换成雪天，加一点飘雪{EDIT_MARKER_END}"
    payload = await _final_payload(content, ["outputs/_m6/a.png"], edit_engine="qwen_image_edit_native")

    intent = payload.get("edit_intent")
    assert isinstance(intent, dict)
    assert intent["prompt"] == "把背景换成雪天，加一点飘雪"
    assert intent["engine_name"] == "qwen_image_edit_native"
    assert intent["reference_images"] == ["outputs/_m6/a.png"]
    # 标记块是机器协议：正文里不能再出现
    assert EDIT_MARKER_START not in payload["text"]
    assert "把背景换成雪天" in payload["text"]  # 但提示词要留在可审计的正文里


async def test_no_intent_for_plain_chat_text() -> None:
    payload = await _final_payload("这张图挺好看的，不需要改。", ["outputs/_m6/a.png"])
    assert "edit_intent" not in payload


async def test_no_intent_without_images_even_with_marker() -> None:
    """没参考图就没有编辑源，绝不下发无法执行的 intent。"""
    content = f"{EDIT_MARKER_START}把背景换成雪天{EDIT_MARKER_END}"
    payload = await _final_payload(content, None)
    assert "edit_intent" not in payload


async def test_engine_name_none_when_not_injected() -> None:
    content = f"{EDIT_MARKER_START}把背景换成雪天{EDIT_MARKER_END}"
    payload = await _final_payload(content, ["outputs/_m6/a.png"], engine_fn=None)
    assert payload["edit_intent"]["engine_name"] is None


async def test_engine_resolver_failure_does_not_break_turn() -> None:
    """编辑引擎解析异常不得吞掉整轮回复（兜底返回 None，前端按钮自动变 disabled）。"""

    def boom() -> str:
        raise RuntimeError("config unavailable")

    content = f"{EDIT_MARKER_START}把背景换成雪天{EDIT_MARKER_END}"
    payload = await _final_payload(content, ["outputs/_m6/a.png"], engine_fn=boom)
    assert payload["text"]  # 正文照常返回
    assert payload["edit_intent"]["engine_name"] is None


# ── 真实端点契约：intent 必须能落成一份合法编辑请求 ──────────


def test_intent_fields_are_accepted_by_generate_request() -> None:
    """桥接不发 ``?mode=edit``；``edit_mode`` + ``reference_image_path`` 才是真契约。"""
    prompt = "把背景换成雪天，加一点飘雪"
    intent: dict[str, Any] = {
        "prompt": prompt,
        "reference_images": ["outputs/_m6/a.png"],
        "engine_name": "qwen_image_edit_native",
    }
    req = GenerateRequest(
        positive_prompt=intent["prompt"],
        edit_mode=True,
        reference_image_path=intent["reference_images"][0],
        engine_name=intent["engine_name"],
        seedvr2_enable=False,
        eses_enable=False,
    )
    assert req.edit_mode is True
    assert req.positive_prompt == prompt
    assert req.reference_image_path == "outputs/_m6/a.png"
