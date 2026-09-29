"""tests/eval/harness.py — eval 执行框架(mock LLM + 全量 tool 记录 + 全局不变量)。

设计要点:
- **脚本化 LLM**:每个用例自带 LLM 应答脚本(逐轮 pop),保证 CI 确定性;
  注入类用例的脚本刻意写成"LLM 已被攻陷"的样子(照做注入、编造参数、调未知工具),
  于是断言的重心落在服务端防线上。
- **全量记录**:RecordingExecutor 记录每一次真实执行的 (工具名, 参数),
  "有没有真的执行"是本套件的核心可观测信号(CONFIRM/MANUAL_ASSIST 的人闸、
  未知工具拒绝,都靠它证伪)。
- **全局不变量**:无论哪个用例,执行过的工具必须都在白名单内、参数键必须都在
  允许集合内、数值必须在钳制范围内、最终回复不得泄露内核提示词/绝对路径/key。
  这些不变量对所有用例统一断言,避免"某个用例忘了查"。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.integrated_app.agent.guard import (
    ALLOWED_PARAM_KEYS,
    PARAM_RANGES,
    detect_leak,
)
from app.integrated_app.agent.orchestrator import AgentEvent, AgentOrchestrator
from app.integrated_app.agent.prompts import KERNEL_PROMPT
from app.integrated_app.agent.session_store import AgentSession, InMemorySessionStore
from app.integrated_app.agent.tools import DEFAULT_ENGINE, KNOWN_TOOLS

from .cases import EvalCase
from .frames import raw_tool_call, resp, tool_call

GENERATE_ALLOWED_KEYS = ALLOWED_PARAM_KEYS | {"engine"}

__all__ = [
    "EvalResult",
    "RecordingExecutor",
    "ScriptedLLM",
    "TurnResult",
    "check_expectations",
    "check_global_invariants",
    "raw_tool_call",
    "resp",
    "run_case",
    "tool_call",
]


class ScriptedLLM:
    """按脚本逐次应答的替身;脚本耗尽时返回一段纯文本(不静默失败)。"""

    def __init__(self, script: list[dict[str, Any]]) -> None:
        self.script = list(script)
        self.seen_system_prompts: list[str] = []
        self.calls: list[list[dict[str, Any]]] = []

    async def chat_completion(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        self.calls.append(messages)
        if messages and messages[0].get("role") == "system":
            self.seen_system_prompts.append(str(messages[0].get("content", "")))
        if not self.script:
            return resp(content="(脚本已耗尽)")
        return self.script.pop(0)


class RecordingExecutor:
    """记录真实执行的 tool 调用;返回可控的 task_id。"""

    def __init__(self, task_id: str = "TASK-EVAL") -> None:
        self.task_id = task_id
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, dict(args)))
        if name == "generate_image":
            return {"task_id": self.task_id, "status": "queued"}
        if name == "get_task":
            return {"task_id": args.get("task_id", ""), "status": "completed", "result_paths": ["outputs/a.png"]}
        if name == "list_engines":
            return {"engines": [{"name": DEFAULT_ENGINE, "active": True}], "default_engine": DEFAULT_ENGINE}
        if name == "list_loras":
            return {"loras": []}
        return {"error": f"tool {name} 未实现"}

    @property
    def names(self) -> list[str]:
        return [n for n, _ in self.calls]

    @property
    def generate_args(self) -> list[dict[str, Any]]:
        return [a for n, a in self.calls if n == "generate_image"]


@dataclass
class TurnResult:
    events: list[AgentEvent]
    llm: ScriptedLLM

    @property
    def types(self) -> list[str]:
        return [e.type for e in self.events]

    def first(self, event_type: str) -> dict[str, Any] | None:
        for e in self.events:
            if e.type == event_type:
                return e.data
        return None

    def all_of(self, event_type: str) -> list[dict[str, Any]]:
        return [e.data for e in self.events if e.type == event_type]

    @property
    def final_text(self) -> str:
        data = self.first("final")
        return str((data or {}).get("text", ""))


@dataclass
class EvalResult:
    case: EvalCase
    turns: list[TurnResult] = field(default_factory=list)
    executor: RecordingExecutor | None = None
    session: AgentSession | None = None
    store: InMemorySessionStore | None = None
    orchestrator: AgentOrchestrator | None = None

    @property
    def executed_names(self) -> list[str]:
        return self.executor.names if self.executor else []

    @property
    def generate_args(self) -> list[dict[str, Any]]:
        return self.executor.generate_args if self.executor else []


async def run_case(case: EvalCase) -> EvalResult:
    """按用例脚本跑完全部轮次,返回可断言的结果对象。"""
    store = InMemorySessionStore()
    executor = RecordingExecutor()
    orchestrator = AgentOrchestrator(
        llm=ScriptedLLM([]),  # 占位;每轮换成该轮的脚本
        tool_executor=executor,
        store=store,
        engines=case.engines,
        loras=case.loras,
        mode=case.mode,
    )

    result = EvalResult(case=case, executor=executor, store=store, orchestrator=orchestrator)
    for turn in case.turns:
        llm = ScriptedLLM(turn.llm)
        orchestrator.llm = llm
        events = await orchestrator.run_turn(case.session_id, turn.message, turn.mode or case.mode)
        result.turns.append(TurnResult(events=events, llm=llm))

    result.session = store.get_or_create(case.session_id)
    return result


# ── 全局不变量 ───────────────────────────────────────────────


def check_global_invariants(result: EvalResult) -> list[str]:
    """对所有用例统一断言的服务端硬约束;返回违规描述列表(空 = 通过)。

    这些是"零信任"的落点:即使脚本化 LLM 完全照做注入,也不允许出现
    白名单外的工具、白名单外的参数键、越界数值、泄露文本。
    """
    problems: list[str] = []

    for name, args in result.executor.calls if result.executor else []:
        if name not in KNOWN_TOOLS:
            problems.append(f"执行了白名单外工具: {name}")
        if name != "generate_image":
            continue
        unknown = set(args) - GENERATE_ALLOWED_KEYS
        if unknown:
            problems.append(f"generate_image 收到白名单外参数键: {sorted(unknown)}")
        for key, (low, high) in PARAM_RANGES.items():
            if key not in args:
                continue
            try:
                value = float(args[key])
            except (TypeError, ValueError):
                problems.append(f"{key} 非数值: {args[key]!r}")
                continue
            if not (low <= value <= high):
                problems.append(f"{key}={value} 越界 [{low}, {high}]")
        if args.get("engine") != DEFAULT_ENGINE:
            problems.append(f"engine 未回落默认: {args.get('engine')!r}")

    for turn in result.turns:
        text = turn.final_text
        if not text:
            continue
        if KERNEL_PROMPT[:40] in text:
            problems.append("最终回复泄露内核提示词")
        leaks = detect_leak(text, [KERNEL_PROMPT[:40]])
        # detect_leak 也会报 key_like / absolute_path;此处只校验其结论一致
        if leaks and "被拦截" not in text and "kernel_prompt_fingerprint" in leaks:
            problems.append(f"泄露检测命中但未拦截: {leaks}")

    return problems


def check_expectations(result: EvalResult) -> list[str]:
    """按用例逐轮断言;返回违规描述列表(空 = 通过)。"""
    problems: list[str] = []
    for index, (turn, expect) in enumerate(zip(result.turns, [t.expect for t in result.case.turns], strict=True), 1):
        prefix = f"第{index}轮"

        # 事件类型:按序子序列
        cursor = 0
        for want in expect.event_types:
            found = False
            while cursor < len(turn.types):
                if turn.types[cursor] == want:
                    cursor += 1
                    found = True
                    break
                cursor += 1
            if not found:
                problems.append(f"{prefix} 缺少事件 {want}(实际 {turn.types})")
                break

        for absent in expect.absent_event_types:
            if absent in turn.types:
                problems.append(f"{prefix} 出现了不应有的事件 {absent}")

        if expect.error_event and "error" not in turn.types:
            problems.append(f"{prefix} 期望 error 事件,实际 {turn.types}")

        for needle in expect.final_contains:
            if needle not in turn.final_text:
                problems.append(f"{prefix} 最终回复缺少 {needle!r}: {turn.final_text[:80]!r}")

        if expect.final_refusal and "被拦截" not in turn.final_text:
            problems.append(f"{prefix} 期望泄露拦截文案,实际 {turn.final_text[:80]!r}")

        prompt = turn.llm.seen_system_prompts[0] if turn.llm.seen_system_prompts else ""
        for needle in expect.system_prompt_contains:
            if needle not in prompt:
                problems.append(f"{prefix} system prompt 缺少 {needle!r}")
        for needle in expect.system_prompt_absent:
            if needle in prompt:
                problems.append(f"{prefix} system prompt 混入了 {needle!r}(数据未消毒/未定界)")

    if result.case.expect_executed_tools is not None:
        if result.executed_names != result.case.expect_executed_tools:
            problems.append(f"真实执行的工具序列不符: {result.executed_names} != {result.case.expect_executed_tools}")

    if result.case.expect_generate_args is not None:
        actual = result.generate_args[-1] if result.generate_args else {}
        for key, value in result.case.expect_generate_args.items():
            if actual.get(key) != value:
                problems.append(f"入队参数 {key} 不符: {actual.get(key)!r} != {value!r}")

    return problems
