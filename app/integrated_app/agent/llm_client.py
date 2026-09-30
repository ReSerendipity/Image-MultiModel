"""
agent/llm_client.py — OpenAI 兼容 LLM 客户端(本地 llama.cpp / 云 API 双适配)

设计要点(评估报告第八/九章):
- 提供两条通道:``chat_completion``(非流式,一次性返回)与 ``chat_completion_stream``
  (流式,逐分片产出)。工具调用阶段两条通道都会聚合 ``tool_calls``——llama.cpp 的流式
  ``tool_calls`` 是**分片增量**的,必须按 ``index`` 累积合并,这里统一处理;
- 配置经环境变量注入(.env 由 config._load_dotenv 加载,零 config.yaml 侵入);
- 健康探测:llama-server 是外部进程,不自动拉起,只探测 + 明确降级;
- api_key 绝不进入 system prompt / 日志。

环境变量:
    IMAGE_MM_AGENT_LLM_BASE_URL   默认 http://127.0.0.1:8081/v1
    IMAGE_MM_AGENT_LLM_API_KEY    默认 not-needed(llama.cpp 不校验)
    IMAGE_MM_AGENT_LLM_MODEL      默认 qwen3.6-35b-a3b
    IMAGE_MM_AGENT_LLM_TEMPERATURE 默认 0.3
    IMAGE_MM_AGENT_LLM_MAX_TOKENS 默认 1024
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_SSE_DATA_PREFIX = "data:"


class LLMError(RuntimeError):
    """LLM 调用失败(网络/协议/非 200)。"""


@dataclass(frozen=True)
class AgentLLMConfig:
    base_url: str = "http://127.0.0.1:8081/v1"
    api_key: str = "not-needed"
    model: str = "qwen3.6-35b-a3b"
    temperature: float = 0.3
    max_tokens: int = 1024
    timeout_s: float = 120.0

    @classmethod
    def from_env(cls) -> AgentLLMConfig:
        return cls(
            base_url=os.environ.get("IMAGE_MM_AGENT_LLM_BASE_URL", cls.base_url),
            api_key=os.environ.get("IMAGE_MM_AGENT_LLM_API_KEY", cls.api_key),
            model=os.environ.get("IMAGE_MM_AGENT_LLM_MODEL", cls.model),
            temperature=float(os.environ.get("IMAGE_MM_AGENT_LLM_TEMPERATURE", cls.temperature)),
            max_tokens=int(os.environ.get("IMAGE_MM_AGENT_LLM_MAX_TOKENS", cls.max_tokens)),
        )


class LLMClient:
    """OpenAI 兼容 /v1/chat/completions 客户端(非流式,tool 阶段安全)。"""

    def __init__(self, config: AgentLLMConfig | None = None) -> None:
        self.config = config or AgentLLMConfig.from_env()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

    async def chat_completion(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        """非流式 chat.completions。返回响应 JSON dict;tools 可传空列表。"""
        payload = self._payload(messages, tools)
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout_s) as client:
                resp = await client.post(
                    f"{self.config.base_url.rstrip('/')}/chat/completions",
                    json=payload,
                    headers=self._headers(),
                )
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM 请求失败: {exc}") from exc
        if resp.status_code != 200:
            raise LLMError(f"LLM 返回 {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    async def chat_completion_stream(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AsyncIterator[dict[str, Any]]:
        """流式 chat.completions。

        产出两类事件：
        - ``{"type": "delta", "text": <增量文本>}``：仅当分片带 content 时产出；
        - ``{"type": "done", "message": {"content": ..., "tool_calls": [...]}}``：收尾，
          聚合后的完整消息（``tool_calls`` 按 ``index`` 累积合并）。

        失败一律转成 ``LLMError``；已流出的文本由调用方决定是否回滚（本项目的
        orchestrator 用「泄露命中则整体替换」的策略处理）。
        """
        payload = self._payload(messages, tools)
        payload["stream"] = True
        content_parts: list[str] = []
        tool_calls: dict[int, dict[str, Any]] = {}

        try:
            async with httpx.AsyncClient(timeout=self.config.timeout_s) as client:
                async with client.stream(
                    "POST",
                    f"{self.config.base_url.rstrip('/')}/chat/completions",
                    json=payload,
                    headers=self._headers(),
                ) as resp:
                    if resp.status_code != 200:
                        body = (await resp.aread()).decode("utf-8", errors="replace")
                        raise LLMError(f"LLM 返回 {resp.status_code}: {body[:200]}")
                    async for line in resp.aiter_lines():
                        chunk = self._parse_sse_line(line)
                        if chunk is None:
                            continue
                        for choice in chunk.get("choices") or []:
                            delta = choice.get("delta") or {}
                            text = delta.get("content")
                            if text:
                                content_parts.append(str(text))
                                yield {"type": "delta", "text": str(text)}
                            self._accumulate_tool_calls(tool_calls, delta.get("tool_calls"))
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM 流式请求失败: {exc}") from exc

        message: dict[str, Any] = {"content": "".join(content_parts)}
        if tool_calls:
            message["tool_calls"] = [tool_calls[i] for i in sorted(tool_calls)]
        yield {"type": "done", "message": message}

    # ── 内部工具 ────────────────────────────────────────────
    def _payload(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if tools:
            payload["tools"] = tools
        return payload

    @staticmethod
    def _parse_sse_line(line: str) -> dict[str, Any] | None:
        """解析一行 SSE；非 data 行/心跳/[DONE]/坏 JSON 一律返回 None。"""
        line = (line or "").strip()
        if not line or not line.startswith(_SSE_DATA_PREFIX):
            return None
        raw = line[len(_SSE_DATA_PREFIX) :].strip()
        if not raw or raw == "[DONE]":
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.debug("忽略无法解析的流式分片: %s", raw[:120])
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _accumulate_tool_calls(acc: dict[int, dict[str, Any]], fragments: Any) -> None:
        """按 index 合并流式 tool_calls 分片。

        OpenAI 兼容协议的流式 tool_calls 形如
        ``[{"index":0,"id":"call_1","function":{"name":"gen","arguments":"{\\"a\\":"}}]``，
        name 可能只来一次、arguments 是逐段拼接的字符串；缺失 index 时按 0 处理。
        """
        if not isinstance(fragments, list):
            return
        for frag in fragments:
            if not isinstance(frag, dict):
                continue
            try:
                idx = int(frag.get("index", 0))
            except (TypeError, ValueError):
                idx = 0
            slot = acc.setdefault(
                idx,
                {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
            )
            if frag.get("id"):
                slot["id"] = str(frag["id"])
            if frag.get("type"):
                slot["type"] = str(frag["type"])
            fn = frag.get("function")
            if isinstance(fn, dict):
                if fn.get("name"):
                    slot["function"]["name"] = str(fn["name"])
                if fn.get("arguments"):
                    slot["function"]["arguments"] += str(fn["arguments"])

    async def health_check(self) -> bool:
        """GET {base_url}/models 探测;任何异常返回 False(不抛出)。"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{self.config.base_url.rstrip('/')}/models",
                    headers=self._headers(),
                )
            return resp.status_code == 200
        except httpx.HTTPError:
            return False
