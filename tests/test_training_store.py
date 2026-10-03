"""tests/test_training_store.py — 训练状态仓库（原子写 / 路径穿越 / 损坏兜底）"""

from __future__ import annotations

import pytest

from app.integrated_app.training.store import (
    STATUS_COMPLETED,
    STATUS_RUNNING,
    TrainingStore,
    is_terminal,
)


def _record(job_id: str = "job-1", **over: object) -> dict:
    rec = {
        "job_id": job_id,
        "name": "probe_lora",
        "status": STATUS_RUNNING,
        "created_at": 1.0,
        "started_at": 2.0,
        "steps": 4,
    }
    rec.update(over)
    return rec


def test_save_then_load(tmp_path):
    store = TrainingStore(tmp_path / "training")
    store.save(_record())
    loaded = store.load("job-1")

    assert loaded is not None
    assert loaded["status"] == STATUS_RUNNING
    assert isinstance(loaded["updated_at"], float)  # 回写时自动刷新时间戳


def test_save_is_atomic_no_half_json_on_disk(tmp_path):
    """后台线程持续回写时，读端只能看到完整 JSON。"""
    store = TrainingStore(tmp_path / "training")
    store.save(_record())
    leftovers = [p.name for p in (tmp_path / "training" / "jobs").iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_save_missing_job_id_rejected(tmp_path):
    store = TrainingStore(tmp_path / "training")
    with pytest.raises((ValueError, TypeError)):
        store.save({"status": STATUS_RUNNING})


def test_list_all_sorted_by_start_desc(tmp_path):
    store = TrainingStore(tmp_path / "training")
    store.save(_record("job-old", started_at=10.0))
    store.save(_record("job-new", started_at=30.0))
    store.save(_record("job-mid", started_at=20.0))

    ids = [r["job_id"] for r in store.list_all()]
    assert ids == ["job-new", "job-mid", "job-old"]


def test_delete(tmp_path):
    store = TrainingStore(tmp_path / "training")
    store.save(_record())
    assert store.delete("job-1") is True
    assert store.delete("job-1") is False
    assert store.load("job-1") is None


def test_path_traversal_is_blocked(tmp_path):
    store = TrainingStore(tmp_path / "training")
    store.save(_record())
    assert store.load("../jobs/evil") is None
    assert store.delete("../../etc/passwd") is False


def test_corrupt_file_returns_none_instead_of_500(tmp_path):
    store = TrainingStore(tmp_path / "training")
    store.ensure_ready()
    (tmp_path / "training" / "jobs" / "job-1.json").write_text('{"job_id": "job-1", "stat', encoding="utf-8")
    assert store.load("job-1") is None


def test_terminal_helpers():
    assert is_terminal(STATUS_COMPLETED) is True
    assert is_terminal("running") is False
