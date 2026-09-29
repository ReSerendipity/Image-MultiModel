"""
agent/session_store.py — Agent 会话存储(骨架:内存版)

评估报告任务 3 的落地起点。P0 交付前升级为 SQLite 持久化(data/agent_sessions.db
或 history_db 新表),本骨架保持接口稳定以便无感替换:
    create / get_or_create / append_user / append_assistant / append_tool /
    set_param_state / mark_user_override / summary

参数状态表(param_state)承载"双模式一致性":确认模式下用户手改参数后
mark_user_override() 打标,prompts.build_system_prompt 据此提示 LLM 必须沿用。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentSession:
    session_id: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    param_state: dict[str, dict[str, Any]] = field(default_factory=dict)
    referenced_task_ids: list[str] = field(default_factory=list)
    # 双模式（评估报告任务 5b）：CONFIRM/MANUAL_ASSIST 下待用户确认的参数提案。
    # 单槽位即可——新提案覆盖旧提案，避免用户面对多个悬空卡片。
    pending_proposal: dict[str, Any] | None = None
    # 最近一轮生效的模式（供系统提示词与前端回显使用）
    mode: str = "AUTO"

    def history_for_llm(self) -> list[dict[str, Any]]:
        """返回可发给 LLM 的历史(排除工具原始负载,保留 role/content 语义)。"""
        return [
            {"role": m["role"], "content": m.get("content", "")}
            for m in self.messages
            if m.get("role") in ("user", "assistant") and m.get("content")
        ]


class InMemorySessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, AgentSession] = {}

    def get_or_create(self, session_id: str | None = None) -> AgentSession:
        if session_id and session_id in self._sessions:
            return self._sessions[session_id]
        sid = session_id or uuid.uuid4().hex[:16]
        self._sessions[sid] = AgentSession(session_id=sid)
        return self._sessions[sid]

    def append_user(self, session: AgentSession, text: str) -> None:
        session.messages.append({"role": "user", "content": text})

    def append_assistant(self, session: AgentSession, text: str) -> None:
        session.messages.append({"role": "assistant", "content": text})

    def append_tool(self, session: AgentSession, name: str, summary: str) -> None:
        session.messages.append({"role": "tool", "tool": name, "content": summary})

    def set_param_state(self, session: AgentSession, params: dict[str, Any], user_override: bool = False) -> None:
        for key, value in params.items():
            session.param_state[key] = {"value": value, "user_override": user_override}

    def set_pending_proposal(self, session: AgentSession, proposal: dict[str, Any] | None) -> None:
        """写入/清除待确认提案（双模式 5b）。"""
        session.pending_proposal = proposal

    def mark_user_override(self, session: AgentSession, keys: list[str]) -> None:
        for key in keys:
            if key in session.param_state:
                session.param_state[key]["user_override"] = True

    def summary(self, session: AgentSession, max_chars: int = 400) -> str:
        """极简摘要:最近 4 条消息拼接(正式版 P0 交付时换成滚动摘要)。"""
        tail = session.messages[-4:]
        text = " | ".join(f"{m['role']}:{(m.get('content') or '')[:60]}" for m in tail)
        return text[:max_chars]
