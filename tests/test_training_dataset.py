"""tests/test_training_dataset.py — 训练前数据集校验（T-14 数据准备第一块）。

不依赖真实训练数据：用 tmp_path 造「图 + 同名 txt」的最小数据集矩阵。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.integrated_app.training.dataset import DatasetError, validate_dataset


def _make(folder: Path, *, paired: int = 0, missing: int = 0, empty: int = 0, other: int = 0) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(paired):
        (folder / f"img_{i}.png").write_bytes(b"\x89PNG")
        (folder / f"img_{i}.txt").write_text(f"caption {i}", encoding="utf-8")
    for i in range(missing):
        (folder / f"missing_{i}.png").write_bytes(b"\x89PNG")  # 故意不配 txt
    for i in range(empty):
        (folder / f"empty_{i}.png").write_bytes(b"\x89PNG")
        (folder / f"empty_{i}.txt").write_text("", encoding="utf-8")  # 空 caption
    for i in range(other):
        (folder / f"notes_{i}.md").write_text("ignore me", encoding="utf-8")


def test_missing_dir_reports_not_ok(tmp_path):
    report = validate_dataset(tmp_path / "nope")
    assert report.exists is False
    assert report.ok is False


def test_fully_paired_is_ok(tmp_path):
    _make(tmp_path / "ds", paired=3)
    report = validate_dataset(tmp_path / "ds")
    assert report.image_count == 3
    assert report.paired_count == 3
    assert report.missing_caption == []
    assert report.empty_caption == []
    assert report.ok is True


def test_missing_caption_detected(tmp_path):
    _make(tmp_path / "ds", paired=1, missing=2)
    report = validate_dataset(tmp_path / "ds")
    assert report.image_count == 3
    assert report.paired_count == 1
    assert len(report.missing_caption) == 2
    assert report.ok is False


def test_empty_caption_detected(tmp_path):
    _make(tmp_path / "ds", paired=1, empty=1)
    report = validate_dataset(tmp_path / "ds")
    assert len(report.empty_caption) == 1
    assert report.ok is False


def test_other_files_are_ignored_not_breaking(tmp_path):
    _make(tmp_path / "ds", paired=1, other=2)
    report = validate_dataset(tmp_path / "ds")
    assert report.image_count == 1
    assert report.ok is True
    assert len(report.other_files) == 2


def test_caption_ext_is_configurable(tmp_path):
    ds = tmp_path / "ds"
    ds.mkdir()
    (ds / "a.jpg").write_bytes(b"\xff\xd8")
    (ds / "a.caption").write_text("x", encoding="utf-8")
    report = validate_dataset(ds, caption_ext="caption")
    assert report.image_count == 1
    assert report.paired_count == 1
    assert "caption" in report.caption_exts


def test_strict_raises_on_missing(tmp_path):
    _make(tmp_path / "ds", paired=1, missing=1)
    with pytest.raises(DatasetError, match="缺同名"):
        validate_dataset(tmp_path / "ds", strict=True)


def test_strict_raises_on_empty(tmp_path):
    _make(tmp_path / "ds", paired=1, empty=1)
    with pytest.raises(DatasetError, match="为空"):
        validate_dataset(tmp_path / "ds", strict=True)


def test_strict_raises_on_no_images(tmp_path):
    _make(tmp_path / "ds", other=1)
    with pytest.raises(DatasetError, match="没有任何图像"):
        validate_dataset(tmp_path / "ds", strict=True)


def test_to_dict_has_ok_key(tmp_path):
    _make(tmp_path / "ds", paired=2)
    d = validate_dataset(tmp_path / "ds").to_dict()
    assert d["ok"] is True
    assert d["image_count"] == 2
