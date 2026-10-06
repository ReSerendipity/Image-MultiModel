#!/usr/bin/env python3
"""scripts/migrate_add_rating_column.py — 幂等迁移：tasks.rating 列

对应 MLOps 评估 M6：history_db 缺少「用户反馈打分」字段，无 rating 列意味着
M6 反馈闭环无法落地。本脚本对 ``data/history.db`` 做一次 ``ALTER TABLE tasks
ADD COLUMN rating INTEGER DEFAULT 0``，并把 PRAGMA user_version 推进到 7。

幂等：
- ``rating`` 列已存在 → no-op，直接报「already migrated」；
- ``PRAGMA user_version >= 7`` → no-op；
- 可重复执行，不会报错。

回滚（如需）：
    SQLite 不支持 DROP COLUMN 之前的版本（3.35+ 才支持）。安全回滚步骤：
        1. 关闭所有占用 history.db 的进程（FastAPI / Tauri 后端）；
        2. 用迁移前的备份覆盖：
             copy data/history.backup-before-rating-*.db data/history.db
        3. 重启服务。
   本脚本不会自动回滚——回滚必须由人确认备份可恢复后手动做。

用法：
    python scripts/migrate_add_rating_column.py                # 迁移默认 data/history.db
    python scripts/migrate_add_rating_column.py --db PATH      # 指定库
    python scripts/migrate_add_rating_column.py --dry-run      # 只打印将做什么
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

TARGET_VERSION = 7
EXPECTED_BASELINE_VERSION = 6  # 迁移前应是 v6；高于此值只告警不阻断


def _has_rating_column(conn: sqlite3.Connection) -> bool:
    return any(r[1] == "rating" for r in conn.execute("PRAGMA table_info(tasks)").fetchall())


def migrate(db_path: Path, dry_run: bool = False) -> int:
    if not db_path.is_file():
        print(f"[ERR] DB not found: {db_path}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        current_version = conn.execute("PRAGMA user_version").fetchone()[0]
        existing = _has_rating_column(conn)
        row_count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        print(f"[info] db={db_path}")
        print(
            f"[info] current user_version={current_version}, tasks rows={row_count}, rating column present={existing}"
        )

        if existing and current_version >= TARGET_VERSION:
            print("[skip] rating column 已存在且 user_version 已到 v7 — no-op")
            return 0

        if existing and current_version < TARGET_VERSION:
            print(f"[warn] rating 列已存在但 user_version={current_version}<{TARGET_VERSION}，仅推进版本号")
            if not dry_run:
                conn.execute(f"PRAGMA user_version = {TARGET_VERSION}")
                conn.commit()
            return 0

        # 真正执行 ALTER
        print("[plan] ALTER TABLE tasks ADD COLUMN rating INTEGER DEFAULT 0")
        print(f"[plan] PRAGMA user_version = {TARGET_VERSION}")
        if dry_run:
            print("[dry-run] 未实际执行")
            return 0

        conn.execute("ALTER TABLE tasks ADD COLUMN rating INTEGER DEFAULT 0")
        conn.execute(f"PRAGMA user_version = {TARGET_VERSION}")
        conn.commit()

        # 复核
        after_cols = [r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()]
        after_rows = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        after_ver = conn.execute("PRAGMA user_version").fetchone()[0]
        assert "rating" in after_cols, "rating 列未加上"
        assert after_rows == row_count, f"行数变化：{row_count} -> {after_rows}（不应变）"
        assert after_ver == TARGET_VERSION, f"user_version 未推进：{after_ver}"
        print(
            f"[ok] 迁移完成：rating 列已加，tasks rows={after_rows}（与迁移前 {row_count} 一致），user_version={after_ver}"
        )
        return 0
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="幂等迁移：tasks.rating 列（MLOps M6）")
    ap.add_argument("--db", default=None, help="DB 路径（默认 <repo>/data/history.db）")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不执行")
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    db = Path(args.db) if args.db else repo_root / "data" / "history.db"
    return migrate(db, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
