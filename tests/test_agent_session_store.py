"""
tests/test_agent_session_store.py — Agent 会话存储（SQLite 持久化 + 降级）测试

覆盖评估报告第十章遗留 #6（SQLite 会话持久化）：
- 跨实例持久化：新开一个 store 仍能读到会话（模拟重启）
- 字段往返：messages / param_state / pending_proposal / mode / referenced_tasks
- prune：超期会话被删、未超期保留；list_referenced_task_ids 同样按时间过滤
- 降级：DB 不可用时 _build_session_store 回落内存版而不是让 Agent 整体不可用
- 落点：default_session_db_path 与 HistoryDB 同目录（故 conftest 隔离自动覆盖）
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.integrated_app.agent.session_store import (
    InMemorySessionStore,
    SqliteSessionStore,
    default_session_db_path,
)


@pytest.fixture()
def store(tmp_path: Path) -> SqliteSessionStore:
    s = SqliteSessionStore(tmp_path / "agent_sessions.db")
    yield s
    s.close()


# ── 持久化 ──────────────────────────────────────────────────


def test_session_survives_new_store_instance(store: SqliteSessionStore, tmp_path: Path) -> None:
    """模拟进程重启：换一个 store 实例仍能读到完整会话。"""
    session = store.get_or_create("s-restart")
    store.append_user(session, "画一只猫")
    store.append_assistant(session, "好的")
    store.set_param_state(session, {"steps": 8, "seed": 42})
    store.set_pending_proposal(session, {"proposal_id": "p1", "args": {"steps": 20}})
    store.set_mode(session, "CONFIRM")
    store.record_referenced_task(session, "TASK-1")
    store.close()

    reopened = SqliteSessionStore(tmp_path / "agent_sessions.db")
    try:
        again = reopened.get_or_create("s-restart")
        assert [m["content"] for m in again.messages] == ["画一只猫", "好的"]
        assert again.param_state["steps"] == {"value": 8, "user_override": False}
        assert again.param_state["seed"]["value"] == 42
        assert again.pending_proposal == {"proposal_id": "p1", "args": {"steps": 20}}
        assert again.mode == "CONFIRM"
        assert again.referenced_task_ids == ["TASK-1"]
    finally:
        reopened.close()


def test_history_for_llm_filters_tool_messages(store: SqliteSessionStore) -> None:
    session = store.get_or_create("s-hist")
    store.append_user(session, "u1")
    store.append_tool(session, "generate_image", "task_id=T1")
    store.append_assistant(session, "a1")
    assert [m["role"] for m in session.history_for_llm()] == ["user", "assistant"]


def test_mark_user_override_persists(store: SqliteSessionStore, tmp_path: Path) -> None:
    session = store.get_or_create("s-ov")
    store.set_param_state(session, {"steps": 8})
    store.mark_user_override(session, ["steps"])
    store.close()

    reopened = SqliteSessionStore(tmp_path / "agent_sessions.db")
    try:
        assert reopened.get_or_create("s-ov").param_state["steps"]["user_override"] is True
    finally:
        reopened.close()


def test_unknown_session_id_creates_empty(store: SqliteSessionStore) -> None:
    session = store.get_or_create("brand-new")
    assert session.session_id == "brand-new"
    assert session.messages == [] and session.param_state == {}


def test_auto_generated_session_id(store: SqliteSessionStore) -> None:
    session = store.get_or_create(None)
    assert len(session.session_id) >= 16
    assert store.get_or_create(session.session_id) is not None


def test_record_referenced_task_is_deduped_and_capped(store: SqliteSessionStore) -> None:
    session = store.get_or_create("s-ref")
    store.record_referenced_task(session, "T1")
    store.record_referenced_task(session, "T1")
    assert session.referenced_task_ids == ["T1"]
    store.record_referenced_task(session, "")
    assert session.referenced_task_ids == ["T1"]

    for i in range(60):
        store.record_referenced_task(session, f"T{i:03d}")
    assert len(session.referenced_task_ids) == 50  # 只留最近 50 个


# ── 清理 ────────────────────────────────────────────────────


def _age_session(store: SqliteSessionStore, session_id: str, days: int) -> None:
    with store._lock:  # noqa: SLF001 — 测试直接改时间戳，构造"过期"状态
        store._conn.execute(  # noqa: SLF001
            "UPDATE agent_sessions SET updated_at = datetime('now', ?) WHERE session_id=?",
            (f"-{days} days", session_id),
        )
        store._conn.commit()  # noqa: SLF001


def test_prune_removes_only_stale(store: SqliteSessionStore) -> None:
    store.get_or_create("fresh")
    store.get_or_create("stale")
    _age_session(store, "stale", 40)

    removed = store.prune(max_age_days=30)
    assert removed == 1
    with store._lock:  # noqa: SLF001
        ids = {r[0] for r in store._conn.execute("SELECT session_id FROM agent_sessions")}  # noqa: SLF001
    assert ids == {"fresh"}


def test_list_referenced_task_ids_skips_stale(store: SqliteSessionStore) -> None:
    fresh = store.get_or_create("fresh")
    store.record_referenced_task(fresh, "T-FRESH")
    stale = store.get_or_create("stale")
    store.record_referenced_task(stale, "T-STALE")
    _age_session(store, "stale", 40)

    ids = store.list_referenced_task_ids(max_age_days=30)
    assert ids == {"T-FRESH"}


def test_inmemory_store_prune_is_noop() -> None:
    s = InMemorySessionStore()
    session = s.get_or_create("x")
    s.record_referenced_task(session, "T1")
    assert s.prune() == 0  # 内存版无时间戳，不得误删
    assert s.list_referenced_task_ids() == {"T1"}


# ── 降级与落点 ──────────────────────────────────────────────


def test_build_session_store_falls_back_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """DB 建不起来时回落内存版，绝不因此让 Agent 整体不可用。"""
    from app.integrated_app.routes import agent_routes

    def boom(*_a: object, **_k: object) -> None:
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(agent_routes, "SqliteSessionStore", boom)
    store = agent_routes._build_session_store()
    assert isinstance(store, InMemorySessionStore)


def test_build_session_store_uses_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.integrated_app.routes import agent_routes

    monkeypatch.setattr(agent_routes, "default_session_db_path", lambda: tmp_path / "s.db")
    store = agent_routes._build_session_store()
    try:
        assert isinstance(store, SqliteSessionStore)
        assert (tmp_path / "s.db").exists()
    finally:
        store.close()


def test_default_session_db_path_sits_next_to_history_db() -> None:
    """与 HistoryDB 同目录 —— conftest 的 HistoryDB 隔离会自动覆盖本库。"""
    from app.integrated_app.config import get_config

    cfg = get_config()
    history = Path(cfg.project_root) / cfg.output.history.db_path
    assert default_session_db_path() == history.parent / "agent_sessions.db"


def test_schema_is_idempotent(tmp_path: Path) -> None:
    """重复打开同一文件不得报错（CREATE TABLE IF NOT EXISTS）。"""
    for _ in range(3):
        s = SqliteSessionStore(tmp_path / "s.db")
        s.get_or_create("x")
        s.close()
