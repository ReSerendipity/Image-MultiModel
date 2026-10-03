"""tests/test_training_progress.py — loss_log.db 回读 + 日志尾部

进度**不爬 tqdm**：AI-Toolkit 用 ``toolkit/logging_aitk.py`` 的 ``UILogger``
把每步 loss 写进 sqlite（schema 见 ``logging_aitk._init_schema``）。
这里按**同 schema** 造库，保证薄层读的是真实列，而不是照着猜测的名字硬编。
"""

from __future__ import annotations

import sqlite3

import pytest

from app.integrated_app.training.progress import loss_log_path, read_loss_log, tail_lines


def _build_loss_db(path, rows: list[tuple[int, str, float]]) -> None:
    """按 logging_aitk 的真实 schema 建库并写入（step/key/value_real）。"""
    con = sqlite3.connect(str(path))
    try:
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS steps (
                step      INTEGER PRIMARY KEY,
                wall_time REAL NOT NULL
            );
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS metrics (
                step       INTEGER NOT NULL,
                key        TEXT NOT NULL,
                value_real REAL,
                value_text TEXT,
                PRIMARY KEY (step, key)
            );
            """
        )
        for step, _key, _value in rows:
            con.execute("INSERT OR REPLACE INTO steps(step, wall_time) VALUES(?, ?)", (step, 1700000000.0 + step))
        con.executemany("INSERT OR REPLACE INTO metrics(step, key, value_real) VALUES(?, ?, ?)", rows)
        con.commit()
    finally:
        con.close()


def test_loss_log_path_follows_aitoolkit_layout(tmp_path):
    """save_root = training_folder/<job name>，loss_log.db 就落在 save_root 下。"""
    assert loss_log_path(tmp_path / "out" / "probe_lora") == tmp_path / "out" / "probe_lora" / "loss_log.db"


def test_read_loss_log(tmp_path):
    db = tmp_path / "loss_log.db"
    _build_loss_db(
        db,
        [
            (0, "learning_rate", 1e-4),
            (0, "loss/all", 0.400),
            (1, "loss/all", 0.380),
            (2, "loss/all", 0.365),
        ],
    )
    data = read_loss_log(db)

    assert data["present"] is True
    assert data["step"] == 2
    assert data["keys"] == ["learning_rate", "loss/all"]
    assert data["latest"]["loss/all"] == pytest.approx(0.365)
    # 每步只回一条 loss（同 key 取首次值）
    assert [row["step"] for row in data["history"]] == [0, 1, 2]
    assert data["history"][-1]["loss/all"] == pytest.approx(0.365)


def test_read_loss_log_recent_window(tmp_path):
    db = tmp_path / "loss_log.db"
    rows = [(s, "loss/all", 1.0 - s / 100) for s in range(100)]
    _build_loss_db(db, rows)
    data = read_loss_log(db, recent=5)
    assert len(data["history"]) == 5


def test_missing_db_degrades_to_empty(tmp_path):
    data = read_loss_log(tmp_path / "nope.db")
    assert data["present"] is False
    assert data["step"] is None
    assert data["history"] == []


def test_tail_lines_keeps_only_tail(tmp_path):
    log = tmp_path / "stdout.log"
    log.write_text("\n".join(f"line-{i}" for i in range(50)), encoding="utf-8")
    lines = tail_lines(log, lines=3)
    assert lines == ["line-47", "line-48", "line-49"]


def test_tail_lines_tolerates_utf8_noise(tmp_path):
    """Windows 训练日志混中文 + 非法字节：不能抛，整行保留（replace 兜底）。"""
    log = tmp_path / "stdout.log"
    log.write_bytes("中文注释 ok\nnext\n".encode() + b"\xff\xfe bad bytes\n")
    lines = tail_lines(log, lines=5)
    assert lines[0].startswith("中文注释")
    assert lines[1] == "next"
    assert "bad bytes" in lines[2]
    assert len(lines) == 3


def test_tail_lines_missing_file(tmp_path):
    assert tail_lines(tmp_path / "nope.log") == []
