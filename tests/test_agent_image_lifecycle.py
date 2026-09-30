"""
tests/test_agent_image_lifecycle.py — 会话图片生命周期（防裂图）

对应评估报告第八章 C-11：``history.cleanup_cron`` 会删旧图，而 Agent 对话里
引用过的历史图一旦被清理就变成裂图。

落地方式：会话库登记 ``referenced_task_ids``，历史清理把它当白名单跳过。
本文件覆盖：
- ``cleanup_old_tasks(protect_task_ids=...)``：被引用的超期任务及其磁盘文件都保留
- 不传白名单时行为与历史一致（照删）
- 白名单过滤后无剩余候选时返回 0 且不报错
- ``app_server._agent_referenced_task_ids()``：从会话库读取引用；库不存在/损坏时
  降级为空集合（不阻断清理）
"""

from __future__ import annotations

import time
from pathlib import Path

from app.integrated_app.agent.session_store import SqliteSessionStore
from app.integrated_app.history_db import HistoryDB


def _make_db(tmp_path: Path) -> tuple[HistoryDB, Path]:
    """建一个带 outputs 目录的 HistoryDB，返回 (db, outputs_dir)。"""
    db = HistoryDB(tmp_path / "data" / "history.db")
    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    return db, outputs_dir


def _add_old_task(db: HistoryDB, outputs_dir: Path, task_id: str) -> Path:
    """插入一个 3 天前的任务 + 一条输出记录，并在磁盘上落一个真实文件。"""
    old = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time() - 3 * 86400))
    db.conn.execute(
        "INSERT INTO tasks (task_id, engine, mode, status, created_at) VALUES (?, 'e1', 'txt2img', 'completed', ?)",
        (task_id, old),
    )
    rel = f"e1/20200101/{task_id}.png"
    fp = outputs_dir / rel
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_bytes(b"fake-png")
    db.conn.execute("INSERT INTO outputs (task_id, path, format) VALUES (?, ?, 'png')", (task_id, rel))
    db.conn.commit()
    return fp


# ── 白名单保护 ──────────────────────────────────────────────


def test_referenced_task_survives_cleanup(tmp_path: Path) -> None:
    db, outputs_dir = _make_db(tmp_path)
    keep_file = _add_old_task(db, outputs_dir, "TALKED-ABOUT")
    drop_file = _add_old_task(db, outputs_dir, "NEVER-REFERENCED")

    deleted = db.cleanup_old_tasks(keep_days=1, max_gb=0, protect_task_ids={"TALKED-ABOUT"})

    assert deleted == 1
    assert db.get_task("TALKED-ABOUT") is not None
    assert keep_file.exists(), "被会话引用的图不得被删除（否则对话里变裂图）"
    assert db.get_task("NEVER-REFERENCED") is None
    assert not drop_file.exists()


def test_no_whitelist_behaves_as_before(tmp_path: Path) -> None:
    db, outputs_dir = _make_db(tmp_path)
    fp = _add_old_task(db, outputs_dir, "T1")
    assert db.cleanup_old_tasks(keep_days=1, max_gb=0) == 1
    assert not fp.exists()
    assert db.get_task("T1") is None


def test_empty_whitelist_is_noop(tmp_path: Path) -> None:
    db, outputs_dir = _make_db(tmp_path)
    fp = _add_old_task(db, outputs_dir, "T2")
    assert db.cleanup_old_tasks(keep_days=1, max_gb=0, protect_task_ids=set()) == 1
    assert not fp.exists()


def test_all_candidates_protected_returns_zero(tmp_path: Path) -> None:
    """全部候选都被保护 → 返回 0 且不抛异常（不得因"没得删"而炸）。"""
    db, outputs_dir = _make_db(tmp_path)
    fp = _add_old_task(db, outputs_dir, "T3")
    assert db.cleanup_old_tasks(keep_days=1, max_gb=0, protect_task_ids={"T3"}) == 0
    assert fp.exists()


def test_protection_applies_to_size_based_cleanup(tmp_path: Path) -> None:
    """按体积清理的候选同样受白名单保护。"""
    db, outputs_dir = _make_db(tmp_path)
    fp = _add_old_task(db, outputs_dir, "BIG-REF")
    assert db.cleanup_old_tasks(keep_days=0, max_gb=0.000001, protect_task_ids={"BIG-REF"}) == 0
    assert fp.exists()


# ── app_server 侧的读取 ─────────────────────────────────────


def test_agent_referenced_task_ids_reads_session_db(tmp_path: Path, monkeypatch) -> None:
    from app.integrated_app import app_server

    db_path = tmp_path / "agent_sessions.db"
    store = SqliteSessionStore(db_path)
    session = store.get_or_create("s1")
    store.record_referenced_task(session, "T-A")
    store.record_referenced_task(session, "T-B")
    store.close()

    monkeypatch.setattr(
        "app.integrated_app.agent.session_store.default_session_db_path",
        lambda: db_path,
    )
    assert app_server._agent_referenced_task_ids() == {"T-A", "T-B"}


def test_agent_referenced_task_ids_missing_db_is_empty(tmp_path: Path, monkeypatch) -> None:
    from app.integrated_app import app_server

    monkeypatch.setattr(
        "app.integrated_app.agent.session_store.default_session_db_path",
        lambda: tmp_path / "nope.db",
    )
    assert app_server._agent_referenced_task_ids() == set()


def test_agent_referenced_task_ids_broken_db_is_empty(tmp_path: Path, monkeypatch) -> None:
    """库损坏时降级为空集合 —— 保护失效可以接受，阻断清理不可以。"""
    from app.integrated_app import app_server

    bad = tmp_path / "bad.db"
    bad.write_bytes(b"this is not a sqlite database at all")
    monkeypatch.setattr(
        "app.integrated_app.agent.session_store.default_session_db_path",
        lambda: bad,
    )
    assert app_server._agent_referenced_task_ids() == set()


def test_agent_referenced_task_ids_ignores_stale_sessions(tmp_path: Path, monkeypatch) -> None:
    """超过保留期的会话不再保护其图片（否则白名单会无限膨胀）。"""
    from app.integrated_app import app_server

    db_path = tmp_path / "agent_sessions.db"
    store = SqliteSessionStore(db_path)
    session = store.get_or_create("stale")
    store.record_referenced_task(session, "T-OLD")
    with store._lock:  # noqa: SLF001 — 直接改时间戳构造过期会话
        store._conn.execute(  # noqa: SLF001
            "UPDATE agent_sessions SET updated_at = datetime('now','-90 days') WHERE session_id='stale'"
        )
        store._conn.commit()  # noqa: SLF001
    store.close()

    monkeypatch.setattr(
        "app.integrated_app.agent.session_store.default_session_db_path",
        lambda: db_path,
    )
    assert app_server._agent_referenced_task_ids() == set()
