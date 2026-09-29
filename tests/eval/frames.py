"""tests/eval/frames.py — LLM 应答帧构造器(OpenAI chat.completions 兼容)。

单独成模块是为了打断 ``cases`` ⇄ ``harness`` 的循环导入:用例集与执行框架
都需要这些构造器。
"""

from __future__ import annotations

import json
from typing import Any


def resp(content: str | None = None, tool_calls: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """构造纯文本/带 tool_calls 的 LLM 响应。"""
    message: dict[str, Any] = {}
    if content is not None:
        message["content"] = content
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {"choices": [{"message": message}]}


def tool_call(name: str, args: dict[str, Any], call_id: str = "call_1") -> dict[str, Any]:
    """构造 tool_call 帧(arguments 为 JSON 字符串,与真实协议一致)。"""
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
    }


def raw_tool_call(name: str, arguments: str, call_id: str = "call_1") -> dict[str, Any]:
    """构造 arguments 非法 JSON 的 tool_call(覆盖容错路径)。"""
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}


__all__ = ["raw_tool_call", "resp", "tool_call"]
