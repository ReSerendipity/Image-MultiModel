"""training/dataset.py — 训练数据集就绪校验（roadmap T-14「数据准备」）。

AI-Toolkit 的 ``datasets`` 条目要的是「一个目录 + 同名 caption 文件」：

- ``<name>.<img_ext>`` 配 ``<name>.txt``（薄层默认 ``caption_ext="txt"``，与 T-12 实跑一致）；
- 目录里可以再放其它无关文件，但不配对 / 空的 caption 会让训练在进程里才炸。

T-12 实跑一次 22 分钟，**不能每次都靠跑一遍才发现 caption 漏了**。本模块在提交前先确认
数据集满足最低可用条件——**只校验、不搬运、不改写**任何文件。

模块分两块能力：
1. 文件级校验（T-14 第一块，默认开）：图 + 同名 caption 存在且非空、孤立文件提示。
2. 解码级校验（T-14 第二块，``check_resolution=True`` 显式开启）：用 Pillow 真实解码每张图，
   暴露「文件后缀对但内容损坏 / 截断」的假图像，并报告真实尺寸、标出超出
   ``[min_size, max_size]`` 的分辨率异常。解码是 IO 重活，故默认不跑，避免拖慢预检。
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

#: 解码校验默认尺寸边界（任一维度的边长超出即算分辨率异常）
DEFAULT_MIN_SIZE = 256
DEFAULT_MAX_SIZE = 2048


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
    # ── 解码级校验（仅 check_resolution=True 时填充）──
    corrupt_images: list[str] = field(default_factory=list)
    image_sizes: dict[str, list[int]] = field(default_factory=dict)  # 文件名 -> [width, height]
    resolution_issues: list[str] = field(default_factory=list)  # 人类可读："<name> 123x45（超出 [256,2048]）"

    @property
    def ok(self) -> bool:
        """是否达到可用条件：目录在、有图、全部配对、caption 非空、无损坏、无分辨率异常。

        后两项（corrupt_images / resolution_issues）仅在显式开启解码校验时才可能被填充，
        故默认（不解码）路径下与旧口径完全一致——保持向后兼容。
        """
        return (
            self.exists
            and self.image_count > 0
            and not self.missing_caption
            and not self.empty_caption
            and not self.corrupt_images
            and not self.resolution_issues
        )

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
            "corrupt_images": self.corrupt_images,
            "image_sizes": self.image_sizes,
            "resolution_issues": self.resolution_issues,
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
        # 解码级
        if self.corrupt_images:
            lines.append(f"  [损坏图像] {len(self.corrupt_images)} 张无法解码（例：{self.corrupt_images[0]}）")
        if self.image_sizes:
            sample = list(self.image_sizes.items())[:5]
            sizes = ", ".join(f"{name}={sz[0]}x{sz[1]}" for name, sz in sample)
            lines.append(f"  [尺寸] 已解码 {len(self.image_sizes)} 张：{sizes}")
        if self.resolution_issues:
            lines.append(f"  [分辨率异常] {len(self.resolution_issues)} 张超出边界（例：{self.resolution_issues[0]}）")
        lines.append("[OK] 数据集可用" if self.ok else "[FAIL] 数据集不可用")
        return "\n".join(lines)


def validate_dataset(
    folder: str | Path,
    caption_ext: str = DEFAULT_CAPTION_EXT,
    strict: bool = False,
    *,
    check_resolution: bool = False,
    min_size: int = DEFAULT_MIN_SIZE,
    max_size: int = DEFAULT_MAX_SIZE,
) -> DatasetReport:
    """校验一个 AI-Toolkit 风格的训练数据集目录（图 + 同名 caption）。

    Args:
        folder: 数据集目录（不要求绝对；但为空/不存在会进报告）。
        caption_ext: caption 文件后缀（不含点），默认 ``txt``。
        strict: 为 True 时，发现缺 caption / 空 caption / 无图 / 损坏 / 分辨率异常即抛
            :class:`DatasetError`（CLI / CI 门禁用）；False 时只回报告不抛（接口用）。
        check_resolution: 为 True 时**真实解码**每张图——暴露损坏/截断的假图像、记录真实
            尺寸、标出超出 ``[min_size, max_size]`` 的分辨率异常。解码是 IO 重活，默认关。
        min_size: 解码校验时允许的最小边长（默认 256）。
        max_size: 解码校验时允许的最大边长（默认 2048）。

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
            if check_resolution:
                _inspect_image(p, report, min_size=min_size, max_size=max_size)
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
        if report.corrupt_images:
            raise DatasetError(
                f"{len(report.corrupt_images)} 张图像无法解码（损坏/截断，例：{report.corrupt_images[0]}）"
            )
        if report.resolution_issues:
            raise DatasetError(
                f"{len(report.resolution_issues)} 张图像分辨率超出 [{min_size},{max_size}]（例：{report.resolution_issues[0]}）"
            )

    return report


def _inspect_image(p: Path, report: DatasetReport, *, min_size: int, max_size: int) -> None:
    """真实解码一张图：记录尺寸、标记损坏、标出分辨率越界。

    仅在 ``check_resolution=True`` 时调用，故默认路径零 Pillow 依赖、零 IO 开销。
    Pillow 在函数内懒加载——若环境没装也不会拖垮文件级校验（仅记 warning 跳过）。
    """
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover —— 项目硬依赖 Pillow，仅作防御
        logger.warning("未安装 Pillow，跳过图像解码校验：%s", p.name)
        return
    try:
        with Image.open(p) as im:
            im.load()  # 强制完整解码，暴露截断/损坏（仅 open 不会真正读像素数据）
            width, height = im.size
    except Exception as exc:  # UnidentifiedImageError / OSError / SyntaxError / ValueError
        logger.warning("图像解码失败 %s：%s", p.name, exc)
        report.corrupt_images.append(p.name)
        return
    report.image_sizes[p.name] = [width, height]
    if width < min_size or height < min_size or width > max_size or height > max_size:
        report.resolution_issues.append(f"{p.name} {width}x{height}（超出 [{min_size},{max_size}]）")
