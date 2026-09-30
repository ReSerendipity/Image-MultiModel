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
from collections.abc import AsyncIterator, Awaitable, Callable
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
# 人闸生效的模式档位（AUTO 不闸）
_GATED_MODES = {MODE_CONFIRM, MODE_MANUAL_ASSIST}
# 需要人闸的「写」工具（SOP-8：闸口位置唯一，新增工具只改这里）
GATED_TOOLS = {"generate_image", "edit_image"}


@dataclass
class AgentEvent:
    """SSE 事件形态。

    type ∈ delta | tool_call | tool_result | task_created | proposal | final | error
    - ``delta``：流式正文增量（仅 ``run_turn_stream`` 产出）；
    - ``final``：``streamed=True`` 表示正文已通过 delta 逐字渲染过（前端勿重复追加）；
      ``replace=True`` 表示此前流出的内容作废、请用本事件文本整体覆盖气泡。
    """

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

    def _propose(
        self, session: AgentSession, args: dict[str, Any], mode: str, tool: str = "generate_image"
    ) -> dict[str, Any]:
        """登记待确认提案(单槽位:新提案覆盖旧提案)。"""
        proposal = {
            "proposal_id": uuid.uuid4().hex[:12],
            "tool": tool,
            "mode": mode,
            "manual": mode == MODE_MANUAL_ASSIST,
            "args": dict(args),
        }
        self.store.set_pending_proposal(session, proposal)
        return proposal

    async def run_turn(self, session_id: str | None, user_text: str, mode: str | None = None) -> list[AgentEvent]:
        """执行一轮对话，返回事件序列（非流式；测试与 eval 套件的入口）。"""
        return [event async for event in self._run_turn_impl(session_id, user_text, mode, stream=False)]

    async def run_turn_stream(
        self, session_id: str | None, user_text: str, mode: str | None = None
    ) -> AsyncIterator[AgentEvent]:
        """执行一轮对话，**逐事件**产出（流式；SSE 路由的入口）。

        与非流式的唯一差别是 LLM 通道：这里走 ``chat_completion_stream`` 并把
        content 增量包成 ``delta`` 事件即时产出；工具调用、人闸、泄露防护等
        逻辑与 ``run_turn`` 完全共用同一份实现（``_run_turn_impl``）。
        """
        async for event in self._run_turn_impl(session_id, user_text, mode, stream=True):
            yield event

    async def _consume_stream(
        self, messages: list[dict[str, Any]], holder: dict[str, Any]
    ) -> AsyncIterator[AgentEvent]:
        """消费一次流式响应：产出 delta 事件，把聚合后的消息放进 ``holder``。

        泄露防护在流式下必须**边流边查**：一旦累积文本命中内核指纹就立刻停止消费，
        由调用方把整条气泡替换成拒绝文案（已经流出去的字符无法撤回，故用 replace 语义）。
        """
        gen = self.llm.chat_completion_stream(messages, tools=TOOL_SCHEMAS)
        try:
            async for chunk in gen:
                if chunk.get("type") == "delta":
                    text = str(chunk.get("text") or "")
                    if not text:
                        continue
                    holder["text"] += text
                    yield AgentEvent("delta", {"text": text})
                    if detect_leak(holder["text"], [KERNEL_PROMPT[:40]]):
                        holder["leak"] = True
                        return
                elif chunk.get("type") == "done":
                    holder["message"] = chunk.get("message") or {}
        finally:
            aclose = getattr(gen, "aclose", None)
            if aclose is not None:
                await aclose()

    async def _run_turn_impl(
        self,
        session_id: str | None,
        user_text: str,
        mode: str | None,
        *,
        stream: bool,
    ) -> AsyncIterator[AgentEvent]:
        active_mode = mode if mode in MODES else (self.mode if self.mode in MODES else MODE_AUTO)
        session = self.store.get_or_create(session_id)
        self.store.set_mode(session, active_mode)
        self.store.append_user(session, user_text)
        messages: list[dict[str, Any]] = [{"role": "system", "content": self._system_prompt(session, active_mode)}]
        messages.extend(session.history_for_llm())

        final_text = ""
        final_streamed = False
        for _ in range(MAX_TOOL_ITERATIONS):
            if stream:
                holder: dict[str, Any] = {"text": "", "message": {}, "leak": False}
                async for event in self._consume_stream(messages, holder):
                    yield event
                if holder["leak"]:
                    # 已流出的内容整体作废：前端收到 replace=True 时用该文案覆盖气泡
                    self.store.append_assistant(session, REFUSAL_TEXT)
                    yield AgentEvent("final", {"text": REFUSAL_TEXT, "replace": True, "streamed": True})
                    return
                message = holder["message"] or {"content": holder["text"]}
            else:
                response = await self.llm.chat_completion(messages, tools=TOOL_SCHEMAS)
                message = (response.get("choices") or [{}])[0].get("message", {})

            tool_calls = message.get("tool_calls") or []

            if not tool_calls:
                final_text = str(message.get("content") or "")
                final_streamed = stream
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
                    yield AgentEvent("error", {"text": str(exc)})
                    return

                yield AgentEvent("tool_call", {"name": name, "args": cleaned, "violations": violations})

                # 双模式人闸:CONFIRM/MANUAL_ASSIST 下 generate_image 不落库、不入队
                if name in GATED_TOOLS and active_mode in _GATED_MODES:
                    proposal = self._propose(session, cleaned, active_mode, tool=name)
                    yield AgentEvent(
                        "proposal",
                        {
                            "proposal_id": proposal["proposal_id"],
                            "tool": name,
                            "mode": active_mode,
                            "manual": proposal["manual"],
                            "args": proposal["args"],
                        },
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
                if name in GATED_TOOLS and result.get("task_id"):
                    yield AgentEvent("task_created", {"task_id": result["task_id"]})
                    self.store.set_param_state(session, cleaned)
                    # 登记引用：历史清理任务据此跳过，防对话里的历史图变裂图
                    self.store.record_referenced_task(session, str(result["task_id"]))
                yield AgentEvent("tool_result", {"name": name, "result": result})
                # 评估报告 9.2 第 3 层:参数违规必须回喂 LLM 自纠(否则钳制对模型不可见,
                # 下一轮还会拿同样的越界值再来一次)。结果与违规一起放进 tool 消息。
                tool_payload: dict[str, Any] = {"result": result}
                if violations:
                    tool_payload["violations"] = violations
                    tool_payload["instruction"] = "上述参数已被服务端修正/丢弃,请采用修正后的值,不要重复原值。"
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": json.dumps(tool_payload, ensure_ascii=False),
                    }
                )
        else:
            final_text = "(已达单轮工具调用上限,请拆分需求后重试。)"

        if not final_text:
            final_text = "(本轮无文本回复。)"
            final_streamed = False
        # 泄露防护:命中即替换拒绝文案
        if detect_leak(final_text, [KERNEL_PROMPT[:40]]):
            final_text = REFUSAL_TEXT
            final_streamed = False  # 文本被整体替换，前端不能再按"已流式追加"处理
        self.store.append_assistant(session, final_text)
        payload: dict[str, Any] = {"text": final_text}
        if final_streamed:
            # 前端据此跳过重复追加（正文已通过 delta 逐字渲染过）
            payload["streamed"] = True
        yield AgentEvent("final", payload)

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

        tool = str(proposal.get("tool") or "generate_image")
        merged = dict(proposal.get("args") or {})
        overrides = {k: v for k, v in (overrides or {}).items() if v is not None and v != ""}
        merged.update(overrides)
        # 用提案自己的工具名校验/执行 —— edit_image 的参数白名单与 generate_image 不同
        cleaned, violations = validate_tool_args(tool, merged)

        self.store.set_param_state(session, cleaned)
        if overrides:
            self.store.mark_user_override(session, [k for k in overrides if k in session.param_state])
        self.store.set_pending_proposal(session, None)

        result = await self.tool_executor(tool, cleaned)
        result = dict(result)
        result["violations"] = violations
        self.store.append_tool(session, tool, json.dumps(result, ensure_ascii=False)[:200])
        if result.get("task_id"):
            # 注意:这里**不能**再 set_param_state(cleaned)——它会用 user_override=False
            # 覆盖上面刚打好的"用户已手改"标记。只补登记引用即可。
            self.store.record_referenced_task(session, str(result["task_id"]))
            self.store.append_assistant(session, f"用户确认执行,任务已入队:{result['task_id']}")
        return result
