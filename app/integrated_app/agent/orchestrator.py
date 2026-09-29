"""
agent/orchestrator.py — Agent 编排:tool-use 循环(评估报告任务 2 / 第八章 A1 的落地)

关键语义:
- 异步任务:generate_image 的 tool 执行器必须"入队即返回 task_id"(由注入的
  ToolExecutor 保证,接入 GenerationService.submit_txt2img),本循环绝不等待生成完成;
  成图由 SSE 事件推回会话。MAX_TOOL_ITERATIONS 防循环失控。
- 零信任:LLM 的 tool 参数经 validate_tool_args 服务端再校验,违规回喂自纠(≤1 轮)。
- 泄露防护:最终回复经 guard.detect_leak 检测,命中即替换为拒绝文案。
- 双模式(任务 5b):AUTO 直接执行;CONFIRM 产出参数卡片待用户确认后由
  approve_proposal() 执行;MANUAL_ASSIST 只产出建议、永不代执行。

ToolExecutor 协议:async (name: str, args: dict) -> dict
P0 接入点:routes/agent_routes.py 装配 generate_image → GenerationService.submit_txt2img。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from .guard import detect_leak
from .prompts import (
    KERNEL_PROMPT,
    MODE_AUTO,
    MODE_CONFIRM,
    MODE_MANUAL_ASSIST,
    MODES,
    build_system_prompt,
)
from .session_store import AgentSession, InMemorySessionStore
from .tools import TOOL_SCHEMAS, validate_tool_args

MAX_TOOL_ITERATIONS = 5

REFUSAL_TEXT = "(该回复因包含敏感信息模式被拦截,请调整问题后重试。)"

# 需要"人闸"的模式:不直接执行 generate_image,先出参数卡片
_GATED_MODES = {MODE_CONFIRM, MODE_MANUAL_ASSIST}


@dataclass
class AgentEvent:
    """SSE 事件形态:type ∈ delta | tool_call | tool_result | task_created | proposal | final | error。"""

    type: str
    data: dict[str, Any]


ToolExecutor = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


class ProposalError(ValueError):
    """提案不存在/已过期/已消费。"""


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

    def _system_prompt(self, session: AgentSession, mode: str) -> str:
        return build_system_prompt(
            engines=self.engines,
            active_engine=self.engines[0] if self.engines else "",
            loras=self.loras,
            mode=mode,
            session_summary=self.store.summary(session),
            param_state=session.param_state or None,
        )

    def _propose(self, session: AgentSession, args: dict[str, Any], mode: str) -> dict[str, Any]:
        """登记待确认提案(单槽位:新提案覆盖旧提案)。"""
        proposal = {
            "proposal_id": uuid.uuid4().hex[:12],
            "tool": "generate_image",
            "mode": mode,
            "manual": mode == MODE_MANUAL_ASSIST,
            "args": dict(args),
        }
        self.store.set_pending_proposal(session, proposal)
        return proposal

    async def run_turn(self, session_id: str | None, user_text: str, mode: str | None = None) -> list[AgentEvent]:
        """执行一轮对话,返回事件序列(SSE 接入时改为 async generator 逐事件推送)。"""
        active_mode = mode if mode in MODES else (self.mode if self.mode in MODES else MODE_AUTO)
        session = self.store.get_or_create(session_id)
        session.mode = active_mode
        self.store.append_user(session, user_text)
        messages: list[dict[str, Any]] = [{"role": "system", "content": self._system_prompt(session, active_mode)}]
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

                # 双模式人闸:CONFIRM/MANUAL_ASSIST 下 generate_image 不落库、不入队
                if name == "generate_image" and active_mode in _GATED_MODES:
                    proposal = self._propose(session, cleaned, active_mode)
                    events.append(
                        AgentEvent(
                            "proposal",
                            {
                                "proposal_id": proposal["proposal_id"],
                                "mode": active_mode,
                                "manual": proposal["manual"],
                                "args": proposal["args"],
                            },
                        )
                    )
                    result = {
                        "status": "awaiting_user_confirmation" if not proposal["manual"] else "suggestion_only",
                        "proposal_id": proposal["proposal_id"],
                        "note": (
                            "参数卡片已提交用户确认,尚未入队;不要声称已开始生成。"
                            if not proposal["manual"]
                            else "仅提供参数建议,未调用生成;引导用户到工作台自行执行。"
                        ),
                    }
                    self.store.append_tool(session, name, json.dumps(result, ensure_ascii=False)[:200])
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.get("id", ""),
                            "content": json.dumps(result, ensure_ascii=False),
                        }
                    )
                    continue

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

    # ── 双模式:提案确认 / 否决(任务 5b) ─────────────────────
    def _take_proposal(self, session: AgentSession, proposal_id: str) -> dict[str, Any]:
        proposal = session.pending_proposal
        if not proposal or proposal.get("proposal_id") != proposal_id:
            raise ProposalError("提案不存在或已过期,请重新发起需求。")
        return proposal

    def reject_proposal(self, session_id: str, proposal_id: str) -> dict[str, Any]:
        """否决提案:清除槽位,不产生任何任务。"""
        session = self.store.get_or_create(session_id)
        self._take_proposal(session, proposal_id)
        self.store.set_pending_proposal(session, None)
        self.store.append_tool(session, "generate_image", "用户否决了参数卡片")
        return {"status": "rejected", "proposal_id": proposal_id}

    async def approve_proposal(
        self,
        session_id: str,
        proposal_id: str,
        overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """确认并执行提案;``overrides`` 为用户在参数卡片上手动修改的字段。

        零信任:合并后的参数仍经 ``validate_tool_args`` 服务端再校验,用户改动
        同样受范围钳制与白名单约束。被手改的字段打 ``user_override`` 标,
        后续轮次的系统提示词会要求 LLM 沿用(评估报告第十章 #10)。
        """
        session = self.store.get_or_create(session_id)
        proposal = self._take_proposal(session, proposal_id)
        if proposal.get("manual"):
            raise ProposalError("纯手动辅助模式的提案不可代为执行,请到工作台自行生成。")

        merged = dict(proposal.get("args") or {})
        overrides = {k: v for k, v in (overrides or {}).items() if v is not None and v != ""}
        merged.update(overrides)
        cleaned, violations = validate_tool_args("generate_image", merged)

        self.store.set_param_state(session, cleaned)
        if overrides:
            self.store.mark_user_override(session, [k for k in overrides if k in session.param_state])
        self.store.set_pending_proposal(session, None)

        result = await self.tool_executor("generate_image", cleaned)
        result = dict(result)
        result["violations"] = violations
        self.store.append_tool(session, "generate_image", json.dumps(result, ensure_ascii=False)[:200])
        if result.get("task_id"):
            self.store.append_assistant(session, f"用户确认执行,任务已入队:{result['task_id']}")
        return result
