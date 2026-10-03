#!/usr/bin/env python
"""preflight_train_job — 训练提交前综合自检（T-14 收尾护栏，2026-10-03）。

聚合「规格校验 + 数据集可用性」，在真正的 22 分钟训练之前把坏参数/坏数据集挡下来：
- 规格：name 正则 / 路径绝对且存在 / model 是文件、extras-dataset 是目录 /
  resolution 16 倍数 / 数值下限 / dtype 白名单（``TrainJobSpec.validate``）；
- 数据集：图 + 同名 caption 齐全、无损坏、分辨率在 ``[min_size,max_size]``
  （``validate_dataset``，``--check-resolution`` 才真实解码）。

只校验、不启动训练、不搬运、不改写任何文件。

用法::

    python scripts/preflight_train_job.py --name my_lora \
        --model-path C:/.../base.safetensors --extras-path C:/.../extras \
        --dataset-folder C:/data/char_v1 [--check-resolution] [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 让脚本既能在仓库根跑，也能被 pytest 以模块方式 import
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.integrated_app.training.runner import preflight_spec  # noqa: E402
from app.integrated_app.training.spec import TrainJobSpec  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="训练提交前综合自检（规格 + 数据集）")
    ap.add_argument("--name", required=True, help="job 名（AI-Toolkit 存档目录名）")
    ap.add_argument("--model-path", required=True, help="训练底座（comfy 单文件 safetensors）")
    ap.add_argument("--extras-path", required=True, help="HF 布局 extras 目录")
    ap.add_argument("--dataset-folder", required=True, help="数据集目录（含同名 .txt caption）")
    ap.add_argument("--check-resolution", action="store_true", help="真实解码每张图：暴露损坏/报告尺寸/标分辨率异常")
    ap.add_argument("--min-size", type=int, default=256, help="分辨率校验允许的最小边长（默认 256）")
    ap.add_argument("--max-size", type=int, default=2048, help="分辨率校验允许的最大边长（默认 2048）")
    ap.add_argument("--json", action="store_true", help="输出 JSON 而非可读文本")
    args = ap.parse_args()

    spec = TrainJobSpec(
        name=args.name,
        model_path=args.model_path,
        extras_path=args.extras_path,
        dataset_folder=args.dataset_folder,
    )
    report = preflight_spec(
        spec, check_resolution=args.check_resolution, min_size=args.min_size, max_size=args.max_size
    )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        lines = [f"提交前自检：{'[OK] 通过' if report['ok'] else '[FAIL] 未通过'}"]
        if report["spec_errors"]:
            lines.append("  规格错误：")
            for e in report["spec_errors"]:
                lines.append(f"    - {e}")
        ds = report.get("dataset")
        if ds is not None:
            if ds.get("ok"):
                decoded = f"，已解码 {len(ds.get('image_sizes', {}))} 张" if args.check_resolution else ""
                lines.append(f"  数据集可用：{ds.get('image_count')} 图 / {ds.get('paired_count')} 配对{decoded}")
            else:
                lines.append(f"  数据集问题：{ds.get('error') or '见下方字段'}")
                for f in ("missing_caption", "empty_caption", "corrupt_images", "resolution_issues"):
                    items = ds.get(f) or []
                    if items:
                        lines.append(f"    - {f}: {len(items)} 项（例：{items[0]}）")
        print("\n".join(lines))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
