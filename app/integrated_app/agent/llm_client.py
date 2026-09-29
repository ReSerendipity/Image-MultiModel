"""
agent/llm_client.py — OpenAI 兼容 LLM 客户端(本地 llama.cpp / 云 API 双适配)

设计要点(评估报告第八/九章):
- tool 调用阶段用非流式(llama.cpp 流式 tool_calls 分片聚合易坑),最终回复流式留 TODO;
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

import os
from dataclasses import dataclass
from typing import Any

import httpx


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
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if tools:
            payload["tools"] = tools
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
