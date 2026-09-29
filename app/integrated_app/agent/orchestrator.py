"""
agent/orchestrator.py — Agent 编排:tool-use 循环(评估报告任务 2 / 第八章 A1 的落地)

关键语义:
- 异步任务:generate_image 的 tool 执行器必须"入队即返回 task_id"(由注入的
  ToolExecutor 保证,接入 GenerationService.submit_txt2img),本循环绝不等待生成完成;
  成图由 SSE 事件推回会话。MAX_TOOL_ITERATIONS 防循环失控。
- 零信任:LLM 的 tool 参数经 validate_tool_args 服务端再校验,违规回喂自纠(≤1 轮)。
- 泄露防护:最终回复经 guard.detect_leak 检测,命中即替换为拒绝文案。

ToolExecutor 协议:async (name: str, args: dict) -> dict
P0 接入点:routes/agent_routes.py 装配 generate_image → GenerationService.submit_txt2img。
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from .guard import detect_leak
from .prompts import KERNEL_PROMPT, MODE_AUTO, build_system_prompt
from .session_store import AgentSession, InMemorySessionStore
from .tools import TOOL_SCHEMAS, validate_tool_args

MAX_TOOL_ITERATIONS = 5

REFUSAL_TEXT = "(该回复因包含敏感信息模式被拦截,请调整问题后重试。)"


@dataclass
class AgentEvent:
    """SSE 事件形态:type ∈ delta | tool_call | tool_result | task_created | final | error。"""

    type: str
    data: dict[str, Any]


ToolExecutor = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


class AgentOrchestrator:
    def __init__(
        self,
        llm: Any,
        tool_executor: ToolExecutor,
        store: InMemorySessionStore | None = None,
        *,
        engines: list[str] | None = None,
        loras: list[str] | None = None,
        mode: str = MODE_AUTO,
    ) -> None:
        self.llm = llm
        self.tool_executor = tool_executor
        self.store = store or InMemorySessionStore()
        self.engines = engines or ["z_image_turbo_native"]
        self.loras = loras or []
        self.mode = mode

    def _system_prompt(self, session: AgentSession) -> str:
        return build_system_prompt(
            engines=self.engines,
            active_engine=self.engines[0] if self.engines else "",
            loras=self.loras,
            mode=self.mode,
            session_summary=self.store.summary(session),
            param_state=session.param_state or None,
        )

    async def run_turn(self, session_id: str | None, user_text: str) -> list[AgentEvent]:
        """执行一轮对话,返回事件序列(SSE 接入时改为 async generator 逐事件推送)。"""
        session = self.store.get_or_create(session_id)
        self.store.append_user(session, user_text)
        messages: list[dict[str, Any]] = [{"role": "system", "content": self._system_prompt(session)}]
        messages.extend(session.history_for_llm())

        events: list[AgentEvent] = []
        final_text = ""
        for _ in range(MAX_TOOL_ITERATIONS):
            response = await self.llm.chat_completion(messages, tools=TOOL_SCHEMAS)
            message = (response.get("choices") or [{}])[0].get("message", {})
            tool_calls = message.get("tool_calls") or []

            if not tool_calls:
                final_text = str(message.get("content") or "")
                break

            messages.append({"role": "assistant", "content": message.get("content") or "", "tool_calls": tool_calls})
            for tc in tool_calls:
                fn = tc.get("function", {})
                name = str(fn.get("name", ""))
                try:
                    raw_args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    raw_args = {}
                try:
                    cleaned, violations = validate_tool_args(name, raw_args)
                except ValueError as exc:
                    events.append(AgentEvent("error", {"text": str(exc)}))
                    return events

                events.append(AgentEvent("tool_call", {"name": name, "args": cleaned, "violations": violations}))
                result = await self.tool_executor(name, cleaned)
                self.store.append_tool(session, name, json.dumps(result, ensure_ascii=False)[:200])
                if name == "generate_image" and result.get("task_id"):
                    events.append(AgentEvent("task_created", {"task_id": result["task_id"]}))
                    self.store.set_param_state(session, cleaned)
                events.append(AgentEvent("tool_result", {"name": name, "result": result}))
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
        else:
            final_text = "(已达单轮工具调用上限,请拆分需求后重试。)"

        if not final_text:
            final_text = "(本轮无文本回复。)"
        # 泄露防护:命中即替换拒绝文案
        if detect_leak(final_text, [KERNEL_PROMPT[:40]]):
            final_text = REFUSAL_TEXT
        self.store.append_assistant(session, final_text)
        events.append(AgentEvent("final", {"text": final_text}))
        return events
