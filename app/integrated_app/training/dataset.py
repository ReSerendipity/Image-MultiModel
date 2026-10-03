"""training/dataset.py — 训练数据集就绪校验（roadmap T-14「数据准备」第一块）。

AI-Toolkit 的 ``datasets`` 条目要的是「一个目录 + 同名 caption 文件」：

- ``<name>.<img_ext>`` 配 ``<name>.txt``（薄层默认 ``caption_ext="txt"``，与 T-12 实跑一致）；
- 目录里可以再放其它无关文件，但不配对 / 空的 caption 会让训练在进程里才炸。

T-12 实跑一次 22 分钟，**不能每次都靠跑一遍才发现 caption 漏了**。本模块在提交前先确认
数据集满足最低可用条件——**只校验、不搬运、不改写**任何文件。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: AI-Toolkit 默认 caption 后缀（与 TrainJobSpec 渲染的 ``caption_ext`` 对齐）
DEFAULT_CAPTION_EXT = "txt"

#: 薄层认可的图像扩展名（与 discover_artifacts 的采样图白名单同源）
SUPPORTED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


class DatasetError(ValueError):
    """数据集不满足最低可用条件（strict 模式下抛出）。"""


@dataclass
class DatasetReport:
    """一次数据集校验的结果（可直接 JSON 化给接口 / CLI）。"""

    folder: str
    exists: bool
    image_count: int = 0
    paired_count: int = 0
    caption_exts: set[str] = field(default_factory=set)
    missing_caption: list[str] = field(default_factory=list)
    empty_caption: list[str] = field(default_factory=list)
    other_files: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """是否达到最低可用条件：目录在、有图、全部配对、caption 非空。"""
        return self.exists and self.image_count > 0 and not self.missing_caption and not self.empty_caption

    def to_dict(self) -> dict[str, Any]:
        return {
            "folder": self.folder,
            "exists": self.exists,
            "image_count": self.image_count,
            "paired_count": self.paired_count,
            "caption_exts": sorted(self.caption_exts),
            "missing_caption": self.missing_caption,
            "empty_caption": self.empty_caption,
            "other_files": self.other_files,
            "ok": self.ok,
        }

    def render_text(self) -> str:
        if not self.exists:
            return f"[FAIL] 数据集目录不存在：{self.folder}"
        if self.image_count == 0:
            return f"[FAIL] 目录里没有任何图像（支持的扩展名：{sorted(SUPPORTED_IMAGE_EXTS)}）：{self.folder}"
        lines = [
            f"数据集：{self.folder}",
            f"  图像 {self.image_count} 张，配对 caption {self.paired_count} 个",
            f"  caption 后缀：{sorted(self.caption_exts) or '（无）'}",
        ]
        if self.missing_caption:
            lines.append(
                f"  [缺 caption] {len(self.missing_caption)} 张图的同名 .txt 缺失（例：{self.missing_caption[0]}）"
            )
        if self.empty_caption:
            lines.append(f"  [空 caption] {len(self.empty_caption)} 个 txt 内容为空（例：{self.empty_caption[0]}）")
        if self.other_files:
            lines.append(f"  [其它文件] {len(self.other_files)} 个（不参与训练，仅提示）：{self.other_files[0]}")
        lines.append("[OK] 数据集可用" if self.ok else "[FAIL] 数据集不可用")
        return "\n".join(lines)


def validate_dataset(
    folder: str | Path,
    caption_ext: str = DEFAULT_CAPTION_EXT,
    strict: bool = False,
) -> DatasetReport:
    """校验一个 AI-Toolkit 风格的训练数据集目录（图 + 同名 caption）。

    Args:
        folder: 数据集目录（不要求绝对；但为空/不存在会进报告）。
        caption_ext: caption 文件后缀（不含点），默认 ``txt``。
        strict: 为 True 时，发现缺 caption / 空 caption / 无图即抛 :class:`DatasetError`
            （CLI / CI 门禁用）；False 时只回报告不抛（接口用）。

    Returns:
        :class:`DatasetReport`：各项计数与是否可用。
    """
    folder = Path(folder)
    report = DatasetReport(folder=str(folder), exists=folder.is_dir())

    ext = caption_ext.strip().lstrip(".")
    report.caption_exts.add(ext)

    if not report.exists:
        if strict:
            raise DatasetError(f"数据集目录不存在：{folder}")
        return report

    for p in sorted(folder.iterdir()):
        if not p.is_file():
            continue
        suffix = p.suffix.lower()
        if suffix in SUPPORTED_IMAGE_EXTS:
            report.image_count += 1
            caption = p.with_suffix(f".{ext}")
            if not caption.is_file():
                report.missing_caption.append(p.name)
            elif caption.stat().st_size == 0:
                report.empty_caption.append(p.name)
            else:
                report.paired_count += 1
        elif suffix == f".{ext}":
            # 仅当没有同名图像时才算「孤立 caption」；与图像配对的 caption 已在上一步计数
            base_image_present = any(p.with_suffix(img_ext).is_file() for img_ext in SUPPORTED_IMAGE_EXTS)
            if not base_image_present:
                report.other_files.append(p.name)
        else:
            report.other_files.append(p.name)

    if strict:
        if report.image_count == 0:
            raise DatasetError(f"目录里没有任何图像（支持 {sorted(SUPPORTED_IMAGE_EXTS)}）：{folder}")
        if report.missing_caption:
            raise DatasetError(
                f"{len(report.missing_caption)} 张图缺同名 .{ext} caption（例：{report.missing_caption[0]}）"
            )
        if report.empty_caption:
            raise DatasetError(
                f"{len(report.empty_caption)} 个 .{ext} caption 内容为空（例：{report.empty_caption[0]}）"
            )

    return report
