"""training/store.py — 训练任务状态落库（薄层的状态回写载体）。

状态放**独立 JSON 文件**（``<training_root>/jobs/<job_id>.json``）而不是塞进
推理侧 ``history_db``：训练任务与生成任务语义不同（产物是权重而非图片，
状态机含 loss/step 字段），混表会让 ``native/lora.py`` 那套推理产物语义被污染。

写盘用「临时文件 + ``os.replace``」原子替换：训练进程在后台线程里持续回写，
前端/接口并发读不会读到半行 JSON（对应 GOTCHAS 里反复出现的「写一半被读到」类事故）。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 状态机：pending → running → completed / failed / cancelled
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

_TERMINAL = (STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED)


def is_terminal(status: str) -> bool:
    """状态是否终态（终态不再刷新进度）。"""
    return status in _TERMINAL


class TrainingStore:
    """``<training_root>/jobs`` 下的任务状态仓库（进程内单例由 runner 持有）。"""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.jobs_dir = self.root / "jobs"

    # ── 目录 ──────────────────────────────────────────────
    def ensure_ready(self) -> None:
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

    # ── 读写 ──────────────────────────────────────────────
    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        """原子写入一条状态记录（``updated_at`` 自动刷新）。"""
        self.ensure_ready()
        record = dict(record)
        record["updated_at"] = time.time()
        job_id = str(record.get("job_id") or "")
        if not job_id:
            raise ValueError("record 缺少 job_id")
        dst = self.jobs_dir / f"{job_id}.json"
        fd, tmp = tempfile.mkstemp(dir=str(self.jobs_dir), prefix=f".{job_id}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(record, fh, ensure_ascii=False, indent=2, default=str)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, dst)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return record

    def load(self, job_id: str) -> dict[str, Any] | None:
        """读取一条状态记录；不存在返回 None。"""
        path = self._safe_path(job_id)
        if path is None or not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            # 半行 JSON 只可能来自外部强杀；记录后按「不可读」返回，不让接口 500
            logger.warning("训练状态文件损坏，跳过: %s (%s)", path, e)
            return None

    def delete(self, job_id: str) -> bool:
        """删除一条状态记录。"""
        path = self._safe_path(job_id)
        if path is None or not path.exists():
            return False
        path.unlink()
        return True

    def list_all(self) -> list[dict[str, Any]]:
        """列出全部任务（按起始时间倒序，无起始时间的按创建时间倒序）。"""
        self.ensure_ready()
        records: list[dict[str, Any]] = []
        for path in self.jobs_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            records.append(data)
        records.sort(
            key=lambda r: float(r.get("started_at") or r.get("created_at") or 0.0),
            reverse=True,
        )
        return records

    # ── 内部 ──────────────────────────────────────────────
    def _safe_path(self, job_id: str) -> Path | None:
        """把 job_id 限制在 jobs 目录内（防路径穿越）。

        ``Path(...).name`` 把 ``../evil`` 直接压成 ``evil``，穿越不成立；
        再补上 ``.json`` 后缀——**别忘了后缀**：第一版漏了它，
        ``save`` 写 ``<id>.json`` 而 ``load`` 找 ``<id>``，状态永远读不到
        （测试 ``test_training_store.py`` 当场抓到）。
        """
        stem = Path(str(job_id)).name
        if not stem or stem in {".", ".."}:
            return None
        if not stem.endswith(".json"):
            stem = f"{stem}.json"
        return self.jobs_dir / stem


# 全局写锁：后台训练线程与测试可能并发写同一批状态文件
_WRITE_LOCK = threading.Lock()


def save_record(store: TrainingStore, record: dict[str, Any]) -> dict[str, Any]:
    """带全局写锁的状态回写（串行化后台线程与请求线程的交错写）。"""
    with _WRITE_LOCK:
        return store.save(record)
