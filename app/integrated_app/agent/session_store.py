"""
agent/session_store.py — Agent 会话存储（内存版 + SQLite 持久化版）

两个实现共享同一接口，路由侧可无感替换：
    get_or_create / append_user / append_assistant / append_tool /
    set_param_state / set_pending_proposal / mark_user_override /
    record_referenced_task / summary / prune

- ``InMemorySessionStore``：进程内字典，测试与降级用；
- ``SqliteSessionStore``：落 ``data/agent_sessions.db``（路径由 ``config.output.history.db_path``
  的同级目录推导，故 conftest 的 HistoryDB 隔离会自动覆盖它），重启后会话与参数状态不丢。

参数状态表(param_state)承载"双模式一致性"：确认模式下用户手改参数后
``mark_user_override()`` 打标，``prompts.build_system_prompt`` 据此提示 LLM 必须沿用。

``referenced_task_ids`` 承载"会话图片生命周期"：历史清理任务据此跳过被活跃会话引用的
输出文件，避免对话里的历史图变成裂图。
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_PRUNE_DAYS = 30

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_sessions (
    session_id        TEXT PRIMARY KEY,
    messages          TEXT NOT NULL DEFAULT '[]',
    param_state       TEXT NOT NULL DEFAULT '{}',
    referenced_tasks  TEXT NOT NULL DEFAULT '[]',
    pending_proposal  TEXT,
    mode              TEXT NOT NULL DEFAULT 'AUTO',
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_updated ON agent_sessions(updated_at);
"""


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
    """进程内实现（默认；测试与持久化不可用时的降级路径）。"""

    def __init__(self) -> None:
        self._sessions: dict[str, AgentSession] = {}

    # ── 持久化钩子（内存版为空操作，SQLite 版覆写）──────────
    def _on_change(self, session: AgentSession) -> None:
        """每次会话状态变更后调用；内存版无需处理。"""

    def _on_created(self, session: AgentSession) -> None:
        """新会话创建后调用。"""

    # ── 接口 ────────────────────────────────────────────────
    def get_or_create(self, session_id: str | None = None) -> AgentSession:
        if session_id and session_id in self._sessions:
            return self._sessions[session_id]
        sid = session_id or uuid.uuid4().hex[:16]
        session = AgentSession(session_id=sid)
        self._sessions[sid] = session
        self._on_created(session)
        return session

    def append_user(self, session: AgentSession, text: str) -> None:
        session.messages.append({"role": "user", "content": text})
        self._on_change(session)

    def append_assistant(self, session: AgentSession, text: str) -> None:
        session.messages.append({"role": "assistant", "content": text})
        self._on_change(session)

    def append_tool(self, session: AgentSession, name: str, summary: str) -> None:
        session.messages.append({"role": "tool", "tool": name, "content": summary})
        self._on_change(session)

    def set_param_state(self, session: AgentSession, params: dict[str, Any], user_override: bool = False) -> None:
        for key, value in params.items():
            session.param_state[key] = {"value": value, "user_override": user_override}
        self._on_change(session)

    def set_pending_proposal(self, session: AgentSession, proposal: dict[str, Any] | None) -> None:
        """写入/清除待确认提案（双模式 5b）。"""
        session.pending_proposal = proposal
        self._on_change(session)

    def mark_user_override(self, session: AgentSession, keys: list[str]) -> None:
        for key in keys:
            if key in session.param_state:
                session.param_state[key]["user_override"] = True
        self._on_change(session)

    def set_mode(self, session: AgentSession, mode: str) -> None:
        session.mode = mode
        self._on_change(session)

    def record_referenced_task(self, session: AgentSession, task_id: str) -> None:
        """登记会话引用的生成任务（供历史清理跳过，防对话里的图变裂图）。"""
        if not task_id or task_id in session.referenced_task_ids:
            return
        session.referenced_task_ids.append(task_id)
        # 只保留最近 N 个，避免会话无限膨胀
        session.referenced_task_ids = session.referenced_task_ids[-50:]
        self._on_change(session)

    def list_referenced_task_ids(self, max_age_days: int = DEFAULT_PRUNE_DAYS) -> set[str]:
        """返回所有（未过期）会话引用的 task_id 集合；清理任务据此白名单。"""
        return {tid for s in self._sessions.values() for tid in s.referenced_task_ids}

    def prune(self, max_age_days: int = DEFAULT_PRUNE_DAYS) -> int:
        """清理过期会话；内存版无时间戳，返回 0（不误删）。"""
        return 0

    def summary(self, session: AgentSession, max_chars: int = 400) -> str:
        """极简摘要:最近 4 条消息拼接(正式版 P0 交付时换成滚动摘要)。"""
        tail = session.messages[-4:]
        text = " | ".join(f"{m['role']}:{(m.get('content') or '')[:60]}" for m in tail)
        return text[:max_chars]

    def close(self) -> None:
        """内存版无资源需要释放。"""


def default_session_db_path() -> Path:
    """会话库落点：与 HistoryDB 同目录（故 conftest 的 HistoryDB 隔离自动覆盖它）。"""
    from ..config import get_config

    cfg = get_config()
    history = Path(cfg.project_root) / cfg.output.history.db_path
    return history.parent / "agent_sessions.db"


class SqliteSessionStore(InMemorySessionStore):
    """SQLite 持久化实现。

    写入策略：``AgentSession`` 对象是工作副本，每次变更整行 upsert（会话体量小，
    换取实现简单与一致）。连接用 ``check_same_thread=False`` + ``RLock`` 串行化，
    兼容事件循环线程与 ``asyncio.to_thread`` 线程。
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        super().__init__()
        self._db_path = Path(db_path) if db_path is not None else default_session_db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
        logger.info("Agent 会话库已就绪: %s", self._db_path)

    # ── 持久化钩子 ──────────────────────────────────────────
    def _on_created(self, session: AgentSession) -> None:
        self._persist(session)

    def _on_change(self, session: AgentSession) -> None:
        self._persist(session)

    def _persist(self, session: AgentSession) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO agent_sessions "
                "(session_id, messages, param_state, referenced_tasks, pending_proposal, mode, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, datetime('now')) "
                "ON CONFLICT(session_id) DO UPDATE SET "
                "messages=excluded.messages, param_state=excluded.param_state, "
                "referenced_tasks=excluded.referenced_tasks, pending_proposal=excluded.pending_proposal, "
                "mode=excluded.mode, updated_at=datetime('now')",
                (
                    session.session_id,
                    json.dumps(session.messages, ensure_ascii=False),
                    json.dumps(session.param_state, ensure_ascii=False),
                    json.dumps(session.referenced_task_ids, ensure_ascii=False),
                    None
                    if session.pending_proposal is None
                    else json.dumps(session.pending_proposal, ensure_ascii=False),
                    session.mode,
                ),
            )
            self._conn.commit()

    # ── 读取 ────────────────────────────────────────────────
    @staticmethod
    def _row_to_session(row: sqlite3.Row) -> AgentSession:
        def _loads(raw: Any, fallback: Any) -> Any:
            try:
                return json.loads(raw) if raw else fallback
            except (TypeError, ValueError):
                return fallback

        return AgentSession(
            session_id=row["session_id"],
            messages=_loads(row["messages"], []),
            param_state=_loads(row["param_state"], {}),
            referenced_task_ids=_loads(row["referenced_tasks"], []),
            pending_proposal=_loads(row["pending_proposal"], None),
            mode=row["mode"] or "AUTO",
        )

    def get_or_create(self, session_id: str | None = None) -> AgentSession:
        sid = session_id or uuid.uuid4().hex[:16]
        with self._lock:
            row = self._conn.execute("SELECT * FROM agent_sessions WHERE session_id=?", (sid,)).fetchone()
        if row is not None:
            session = self._row_to_session(row)
            # 同步进内存字典：同一进程内的后续读取走缓存，减少磁盘往返
            self._sessions[sid] = session
            return session
        session = AgentSession(session_id=sid)
        self._sessions[sid] = session
        self._persist(session)
        return session

    def list_referenced_task_ids(self, max_age_days: int = DEFAULT_PRUNE_DAYS) -> set[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT referenced_tasks FROM agent_sessions WHERE updated_at >= datetime('now', ?)",
                (f"-{int(max_age_days)} days",),
            ).fetchall()
        ids: set[str] = set()
        for row in rows:
            try:
                ids.update(json.loads(row["referenced_tasks"]) or [])
            except (TypeError, ValueError):
                continue
        return ids

    def prune(self, max_age_days: int = DEFAULT_PRUNE_DAYS) -> int:
        """删除超过 max_age_days 未更新的会话；返回删除条数。"""
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM agent_sessions WHERE updated_at < datetime('now', ?)",
                (f"-{int(max_age_days)} days",),
            )
            self._conn.commit()
            removed = cur.rowcount or 0
        if removed:
            logger.info("Agent 会话清理: 删除 %s 条超过 %s 天的会话", removed, max_age_days)
        return removed

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error:  # pragma: no cover - 关闭期竞态不阻断收尾
                logger.warning("Agent 会话库关闭失败", exc_info=True)
