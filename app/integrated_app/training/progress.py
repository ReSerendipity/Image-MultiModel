"""training/progress.py — 训练进度回读（loss_log.db +  stdout 日志尾部）。

进度**不爬 tqdm**：AI-Toolkit 在 ``jobs/process/BaseSDTrainProcess.py`` 里把
每步 loss 通过 ``toolkit/logging_aitk.py`` 的 ``UILogger`` 写进
``<save_root>/loss_log.db``（sqlite：``steps(step, wall_time)`` /
``metrics(step, key, value_real, value_text)`` / ``metric_keys``）。
本模块只读这个库，进度带宽小（几 KB）且与训练实现解耦。

只读连接用 ``uri=file:...?mode=ro``：训练进程正在写（WAL 模式）时也不会
抢写锁、不会把 WAL 文件复制出来（对应 GOTCHAS #48 的坑点一）。
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: 回读时保留的最近步数（够画折线，又不至于把 payload 撑大）
RECENT_STEPS = 32


def loss_log_path(save_root: str | Path) -> Path:
    """AI-Toolkit 的 ``UILogger`` 把 loss 库写在 ``<save_root>/loss_log.db``。

    依据：``create_logger(...)`` 里 ``log_file = os.path.join(save_root, "loss_log.db")``，
    而 ``save_root = <training_folder>/<job name>``。
    """
    return Path(save_root) / "loss_log.db"


def read_loss_log(db_path: str | Path, recent: int = RECENT_STEPS) -> dict[str, Any]:
    """回读 loss_log.db，返回结构化进度。

    Returns:
        ``{"present": bool, "step": int|None, "keys": [str],
        "latest": {key: float}, "history": [{step, **metrics}]}``；
        库不存在/不可读时 ``present=False`` 且字段为空（不抛异常，供接口直出）。
    """
    db_path = Path(db_path)
    out: dict[str, Any] = {
        "present": db_path.exists(),
        "path": str(db_path),
        "step": None,
        "keys": [],
        "latest": {},
        "history": [],
    }
    if not db_path.exists():
        return out

    uri = f"file:{db_path.as_posix()}?mode=ro"
    con: sqlite3.Connection | None = None
    try:
        con = sqlite3.connect(uri, uri=True, timeout=1.0)
        rows = con.execute(
            """
            SELECT step, key, value_real
              FROM metrics
             WHERE value_real IS NOT NULL
             ORDER BY step
            """
        ).fetchall()
    except sqlite3.Error as e:  # 库被写坏/被强占：降级为空进度，不阻断接口
        logger.warning("读取训练 loss 库失败（已降级为空进度）: %s (%s)", db_path, e)
        return out
    finally:
        if con is not None:
            con.close()

    by_step: dict[int, dict[str, float]] = {}
    keys: list[str] = []
    for step, key, value in rows:
        bucket = by_step.setdefault(int(step), {})
        if key not in bucket:
            bucket[key] = float(value)
        if key not in keys:
            keys.append(key)
    if not by_step:
        return out

    ordered_steps = sorted(by_step)
    last = ordered_steps[-1]
    out["step"] = last
    out["keys"] = keys
    out["latest"] = dict(by_step[last])
    out["history"] = [{"step": s, **by_step[s]} for s in ordered_steps[-recent:]]
    return out


def tail_lines(log_path: str | Path, lines: int = 100, max_bytes: int = 1 << 16) -> list[str]:
    """读日志尾部若干行（只读最后 ``max_bytes``，避免整个训练日志进内存）。

    返回按时间顺序排列的行列表（不含行尾换行）。
    """
    path = Path(log_path)
    if not path.exists():
        return []
    try:
        size = path.stat().st_size
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            # whence=2 == io.SEEK_END：超大日志只回读尾部，不整份进内存
            if size > max_bytes:
                fh.seek(-max_bytes, 2)
            text = fh.read()
    except OSError as e:
        logger.warning("读取训练日志失败: %s (%s)", path, e)
        return []
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    all_lines = [ln for ln in text.split("\n") if ln]
    return all_lines[-lines:] if lines > 0 else all_lines
