"""tests/test_training_dataset.py — 训练前数据集校验（T-14 数据准备第一块）。

不依赖真实训练数据：用 tmp_path 造「图 + 同名 txt」的最小数据集矩阵。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

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


def _make_real(
    folder: Path, name: str, size: tuple[int, int] = (64, 64), *, paired: bool = True, ext: str = "png"
) -> None:
    """造一张用 Pillow 真实编码的图像（可被解码校验解码）。"""
    folder.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (123, 45, 67)).save(folder / f"{name}.{ext}")
    if paired:
        (folder / f"{name}.txt").write_text("caption", encoding="utf-8")


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


# ── T-14 第二块：解码级校验（check_resolution）──
def test_check_resolution_off_ignores_corrupt_by_default(tmp_path):
    # 默认不解码：损坏图（仅 magic bytes）不应被标成 corrupt，caption 齐全则 ok 仍 True
    _make(tmp_path / "ds", paired=1)
    report = validate_dataset(tmp_path / "ds")
    assert report.corrupt_images == []
    assert report.image_sizes == {}
    assert report.resolution_issues == []
    assert report.ok is True


def test_check_resolution_detects_corrupt(tmp_path):
    _make(tmp_path / "ds", paired=1)  # 假 PNG，无法解码
    report = validate_dataset(tmp_path / "ds", check_resolution=True)
    assert report.corrupt_images == ["img_0.png"]
    assert "img_0.png" not in report.image_sizes
    assert report.ok is False


def test_check_resolution_reports_real_sizes(tmp_path):
    ds = tmp_path / "ds"
    _make_real(ds, "a", size=(512, 512))
    _make_real(ds, "b", size=(1024, 768))
    report = validate_dataset(ds, check_resolution=True)
    assert report.image_sizes["a.png"] == [512, 512]
    assert report.image_sizes["b.png"] == [1024, 768]
    assert report.corrupt_images == []
    assert report.resolution_issues == []
    assert report.ok is True


def test_resolution_issue_flagged_below_min(tmp_path):
    ds = tmp_path / "ds"
    _make_real(ds, "tiny", size=(32, 32))
    report = validate_dataset(ds, check_resolution=True)  # 默认边界 [256, 2048]
    assert report.resolution_issues  # 非空
    assert "tiny.png" in report.resolution_issues[0]
    assert report.ok is False


def test_resolution_issue_bypassed_with_wide_bounds(tmp_path):
    ds = tmp_path / "ds"
    _make_real(ds, "tiny", size=(32, 32))
    report = validate_dataset(ds, check_resolution=True, min_size=16, max_size=4096)
    assert report.resolution_issues == []
    assert report.ok is True


def test_strict_raises_on_corrupt(tmp_path):
    _make(tmp_path / "ds", paired=1)  # 假 PNG
    with pytest.raises(DatasetError, match="无法解码"):
        validate_dataset(tmp_path / "ds", strict=True, check_resolution=True)


def test_strict_raises_on_resolution(tmp_path):
    ds = tmp_path / "ds"
    _make_real(ds, "tiny", size=(32, 32))
    with pytest.raises(DatasetError, match="分辨率超出"):
        validate_dataset(ds, strict=True, check_resolution=True)


def test_to_dict_includes_decode_fields(tmp_path):
    _make(tmp_path / "ds", paired=1)
    d = validate_dataset(tmp_path / "ds").to_dict()
    assert "corrupt_images" in d and d["corrupt_images"] == []
    assert "image_sizes" in d and d["image_sizes"] == {}
    assert "resolution_issues" in d and d["resolution_issues"] == []
