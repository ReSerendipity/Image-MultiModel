#!/usr/bin/env python
"""validate_lora_dataset — 训练前数据集就绪校验（T-14 数据准备第一块，2026-10-03）。

校验一个 AI-Toolkit 风格的训练数据集目录：图像（jpg/jpeg/png/webp/bmp）是否都有同名
``.<caption_ext>`` caption，且 caption 非空。训练前先过这一关，避免坏数据在训练进程里
（22 分钟起步）才炸。

本脚本只校验、不搬运、不改写任何文件。

用法::

    python scripts/validate_lora_dataset.py <数据集目录> [--caption-ext txt] [--strict] [--json]
    python scripts/validate_lora_dataset.py "C:/data/char_v1" --strict
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 让脚本既能在仓库根跑，也能被 pytest 以模块方式 import
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.integrated_app.training.dataset import DatasetError, validate_dataset  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="训练前数据集就绪校验（图 + 同名 caption）")
    ap.add_argument("folder", help="数据集目录（建议绝对路径）")
    ap.add_argument("--caption-ext", default="txt", help="caption 后缀，不含点（默认 txt）")
    ap.add_argument("--strict", action="store_true", help="发现缺/空 caption 即以非 0 退出")
    ap.add_argument("--json", action="store_true", help="输出 JSON 而非可读文本")
    args = ap.parse_args()

    folder = Path(args.folder)
    try:
        report = validate_dataset(folder, caption_ext=args.caption_ext, strict=args.strict)
    except DatasetError as e:
        print(str(e), file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(report.render_text())
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
