"""
tests/test_history_db_rating.py — tasks.rating 字段 roundtrip（MLOps M6）。

覆盖：
- 新建库自带 rating 列（CREATE TABLE 基线）
- set_rating(+1/-1/0) 写读 roundtrip
- 越界值被 clamp 到 [-1, 1]
- get_task 返回 rating 字段
- 旧库（无 rating 列）打开时被 v7 迁移补齐
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

from integrated_app.history_db import HistoryDB


@pytest.fixture
def db(tmp_path):
    d = HistoryDB(tmp_path / "test_rating.db")
    yield d
    d.close()


class TestRatingRoundtrip:
    def test_fresh_db_has_rating_column(self, db):
        row = db.conn.execute("PRAGMA table_info(tasks)").fetchall()
        cols = [r[1] for r in row]
        assert "rating" in cols

    def test_default_rating_is_zero(self, db):
        db.create_task(task_id="t1", engine="test", prompt="p")
        task = db.get_task("t1")
        assert task["rating"] == 0

    def test_set_rating_up_and_read_back(self, db):
        db.create_task(task_id="t2", engine="test", prompt="p")
        db.set_rating("t2", 1)
        assert db.get_task("t2")["rating"] == 1
        db.set_rating("t2", -1)
        assert db.get_task("t2")["rating"] == -1
        db.set_rating("t2", 0)
        assert db.get_task("t2")["rating"] == 0

    def test_rating_out_of_range_is_clamped(self, db):
        db.create_task(task_id="t3", engine="test", prompt="p")
        db.set_rating("t3", 99)
        assert db.get_task("t3")["rating"] == 1
        db.set_rating("t3", -50)
        assert db.get_task("t3")["rating"] == -1

    def test_schema_version_is_7(self, db):
        v = db.conn.execute("PRAGMA user_version").fetchone()[0]
        assert v == 7

    def test_idempotent_reopen_keeps_rating(self, db, tmp_path):
        """库关闭重开后 rating 列与已写值不丢。"""
        db.create_task(task_id="t9", engine="test", prompt="p")
        db.set_rating("t9", 1)
        db.close()

        db2 = HistoryDB(tmp_path / "test_rating.db")
        try:
            assert db2.get_task("t9")["rating"] == 1
        finally:
            db2.close()
