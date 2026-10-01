"""
tests/test_output_metadata_probe.py — 回归测试：产物落库元数据回填（E 项）

锁定 `docs/roadmap/P2-multi-engine.md` 开放问题「产物元数据入库未 stat 磁盘」的修复：
`task_worker._probe_output_metadata` 必须真实地读磁盘尺寸 / 像素，并在文件缺失时
优雅回退 (0, 0, 0)；worker 据此把非 0 的 file_size / width / height / sha256 写入
`HistoryDB.outputs`，而非恒为 0 / 空。

回归判据：若未来有人把 worker 改回「传常量 0」，本测试会失败。
"""

from __future__ import annotations

import pytest
from PIL import Image

from integrated_app.history_db import HistoryDB
from integrated_app.services.task_worker import _probe_output_metadata


@pytest.fixture
def db(tmp_path):
    d = HistoryDB(tmp_path / "meta.db")
    yield d
    d.close()


def _make_png(path, w=64, h=48):
    Image.new("RGB", (w, h), (10, 20, 30)).save(path, format="PNG")


def test_probe_returns_real_size_and_dims(tmp_path):
    p = tmp_path / "real.png"
    _make_png(p, 64, 48)
    size, w, h = _probe_output_metadata(str(p))
    assert size > 0
    assert w == 64
    assert h == 48


def test_probe_missing_file_returns_zeros(tmp_path):
    size, w, h = _probe_output_metadata(str(tmp_path / "nope.png"))
    assert (size, w, h) == (0, 0, 0)


def test_probe_empty_string_returns_zeros():
    assert _probe_output_metadata("") == (0, 0, 0)


def test_worker_chain_fills_nonzero_metadata(db, tmp_path):
    """模拟 worker 的 probe -> add_output 链路：确保非 0 元数据落库。"""
    p = tmp_path / "chain.png"
    _make_png(p, 128, 96)
    file_size, width, height = _probe_output_metadata(str(p))
    db.create_task(task_id="t-meta", engine="test", prompt="p")
    db.add_output(
        task_id="t-meta",
        path=str(p),
        format="png",
        file_size=file_size,
        width=width,
        height=height,
        output_type="original",
    )
    out = db.get_task("t-meta")["outputs"][0]
    assert out["file_size"] == file_size and file_size > 0
    assert out["width"] == 128 and out["height"] == 96
