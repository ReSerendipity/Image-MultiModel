#!/usr/bin/env python3
"""scripts/query_training_jobs.py — 训练 job 只读查询 CLI（MLOps M5）。

把散落的 ``data/training/jobs/<job_id>.json`` 抽成可过滤的只读视图，替代过去对
``docs/agents/GOTCHAS.md`` 的 grep 式回忆。本脚本**只读**：不写、不删、不提交任何 job。

用法示例::

    # 列全部 job（按开始时间倒序）
    python scripts/query_training_jobs.py

    # 只看失败的 job
    python scripts/query_training_jobs.py --status failed

    # 按名字模糊过滤（大小写不敏感）
    python scripts/query_training_jobs.py --name lora

    # 输出 JSON 给后续管道
    python scripts/query_training_jobs.py --status failed --json

    # 只看某引擎 arch
    python scripts/query_training_jobs.py --arch zimage
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _jobs_dir(project_root: Path) -> Path:
    return project_root / "data" / "training" / "jobs"


def load_jobs(project_root: Path) -> list[dict[str, Any]]:
    jobs_dir = _jobs_dir(project_root)
    if not jobs_dir.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for p in sorted(jobs_dir.glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        out.append(rec)
    out.sort(key=lambda r: float(r.get("started_at") or r.get("created_at") or 0.0), reverse=True)
    return out


def _short(rec: dict[str, Any]) -> dict[str, Any]:
    """压缩成一行可打印的摘要。"""
    spec = rec.get("spec") or {}
    env = rec.get("environment") or {}
    return {
        "job_id": rec.get("job_id"),
        "name": rec.get("name"),
        "status": rec.get("status"),
        "steps": rec.get("steps"),
        "arch": spec.get("arch"),
        "model": spec.get("model_path", "").split("/")[-1],
        "aitk_commit": env.get("aitk_commit", "unknown"),
        "aitk_torch": env.get("aitk_torch_version", "unknown"),
        "error": rec.get("error", ""),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="训练 job 只读查询（不写盘）")
    ap.add_argument("--status", help="按状态过滤：pending/running/completed/failed/cancelled")
    ap.add_argument("--name", help="按名字子串过滤（大小写不敏感）")
    ap.add_argument("--arch", help="按 spec.arch 过滤（如 zimage）")
    ap.add_argument("--json", action="store_true", help="输出完整 JSON 而非摘要表")
    ap.add_argument("--project-root", default=None, help="项目根（默认脚本上两级）")
    args = ap.parse_args()

    root = Path(args.project_root).resolve() if args.project_root else Path(__file__).resolve().parent.parent
    jobs = load_jobs(root)

    if args.status:
        jobs = [j for j in jobs if j.get("status") == args.status]
    if args.name:
        n = args.name.lower()
        jobs = [j for j in jobs if n in str(j.get("name", "")).lower()]
    if args.arch:
        jobs = [j for j in jobs if (j.get("spec") or {}).get("arch") == args.arch]

    if not jobs:
        print("(no matching jobs)")
        return 0

    if args.json:
        json.dump(jobs, sys.stdout, ensure_ascii=False, indent=2, default=str)
        print()
        return 0

    rows = [_short(j) for j in jobs]
    for r in rows:
        print(
            f"{r['job_id']:<12} {r['status']:<10} arch={r['arch']:<8} "
            f"steps={r['steps']:<5} aitk={r['aitk_commit'][:8]:<8} torch={r['aitk_torch']:<14} "
            f"{r['name']}  {r['error']}"
        )
    print(f"\n({len(rows)} job(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
