"""
history_db.py — SQLite 历史记录数据库

对应 MASTER_PLAN §4 / 附录 B3: history_db.py
对应 PRD §6.3: tasks / outputs / presets + WAL/FTS5 + 崩溃恢复
对应 MASTER_PLAN §8: 数据模型
"""

from __future__ import annotations

import inspect
import json
import logging
import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

# ── 搜索边界：FTS5 与 LIKE 的分工 ──────────────────────────────────
# 实测（sqlite 3.49.1）：unicode61 分词器不产出 CJK token（中文/日文/韩文
# 查询 MATCH 恒为 0）；而历史遗留库的索引为 trigram 语义，对 <3 字符查询
# 无法子串命中。两类查询统一回落 LIKE 子串匹配，保证「输入即所得」。
_CJK_SEARCH_RE = re.compile(r"[\u3000-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af\uff00-\uffef]")


def _escape_like(s: str) -> str:
    """转义 LIKE 通配符（配合 ``ESCAPE '\'`` 使用），使查询词按字面匹配。"""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


logger = logging.getLogger(__name__)


class HistoryDBClosedError(RuntimeError):
    """在 ``HistoryDB.close()`` 之后仍尝试使用数据库连接。

    触发场景：某线程先取到连接、另一线程随后 ``close()``，前者再写库。
    修复前这会走到 sqlite3 C 扩展的 use-after-close，表现为**解释器段错误**
    （pytest 只能报 ``worker crashed``，无任何 Python 栈）；护栏介入后改为
    抛出本异常，可捕获、可诊断。
    """


class _GuardedConnection:
    """``sqlite3.Connection`` 的关闭安全护栏代理。

    ``HistoryDB`` 以 ``check_same_thread=False`` 跨线程共享同一个连接。裸连接
    一旦被某线程 ``close()``，其它线程手里**已持有的对象引用不会失效**，继续
    ``execute()`` 会直接在 C 扩展层段错误（整个解释器崩掉，无法被 try/except
    捕获）。本代理保证调用方拿到的是护栏而非裸连接：

    - 所有数据库调用都在同一把 :class:`threading.RLock` 内完成，
      ``close()`` 必须拿到同一把锁 → 不可能在调用进行中拆掉连接；
    - 连接若已关闭，后续调用抛 :class:`HistoryDBClosedError`（明确异常，
      而非崩溃或静默重开一个新库）。
    """

    __slots__ = ("_conn", "_lock")

    def __init__(self, conn: sqlite3.Connection, lock: threading.RLock) -> None:
        object.__setattr__(self, "_conn", conn)
        object.__setattr__(self, "_lock", lock)

    # ── 内部 ─────────────────────────────────────────────────
    def _require(self) -> sqlite3.Connection:
        conn = object.__getattribute__(self, "_conn")
        if conn is None:
            raise HistoryDBClosedError(
                "HistoryDB 连接已关闭，无法继续访问数据库"
                "（典型原因：关闭流程先于工作线程写库，属 use-after-close 竞态）"
            )
        return conn

    @property
    def closed(self) -> bool:
        return object.__getattribute__(self, "_conn") is None

    def _invalidate(self) -> None:
        object.__setattr__(self, "_conn", None)

    # ── 高频 API：持锁调用，防止与 close() 交错 ────────────────
    def execute(self, *args: Any, **kwargs: Any) -> sqlite3.Cursor:
        lock = object.__getattribute__(self, "_lock")
        with lock:
            return self._require().execute(*args, **kwargs)

    def executescript(self, *args: Any, **kwargs: Any) -> sqlite3.Cursor:
        lock = object.__getattribute__(self, "_lock")
        with lock:
            return self._require().executescript(*args, **kwargs)

    def commit(self) -> None:
        lock = object.__getattribute__(self, "_lock")
        with lock:
            self._require().commit()

    def rollback(self) -> None:
        lock = object.__getattribute__(self, "_lock")
        with lock:
            self._require().rollback()

    def close(self) -> None:
        """幂等关闭：重复调用不报错。"""
        lock = object.__getattribute__(self, "_lock")
        with lock:
            conn = object.__getattribute__(self, "_conn")
            if conn is None:
                return
            object.__setattr__(self, "_conn", None)
            conn.close()

    # ── 其余属性转发（row_factory / cursor / total_changes …）──
    def __getattr__(self, name: str) -> Any:
        lock = object.__getattribute__(self, "_lock")
        with lock:
            attr = getattr(self._require(), name)
        # 只包装「方法」（C 层 builtin / 绑定方法）。类与常量原样返回——
        # 例如 ``row_factory`` 取值是 ``sqlite3.Row``（类，也可调用），
        # 误包装会让它变成一个函数，赋值回 row_factory 即静默失效。
        if inspect.isbuiltin(attr) or inspect.ismethod(attr):

            def _guarded(*args: Any, **kwargs: Any) -> Any:
                with lock:
                    return getattr(self._require(), name)(*args, **kwargs)

            return _guarded
        return attr

    def __setattr__(self, name: str, value: Any) -> None:
        if name in ("_conn", "_lock"):
            object.__setattr__(self, name, value)
            return
        lock = object.__getattribute__(self, "_lock")
        with lock:
            setattr(self._require(), name, value)

    def __bool__(self) -> bool:
        return object.__getattribute__(self, "_conn") is not None

    def __repr__(self) -> str:  # pragma: no cover - 仅调试用
        conn = object.__getattribute__(self, "_conn")
        return f"<_GuardedConnection {'closed' if conn is None else 'open'}>"


def _dir_size_bytes(path: Path) -> int:
    """递归统计目录体积（字节）。用于 cleanup_old_tasks 的 max_gb 口径
    （成本资源治理评估报告 P1-③：须度量目录本身，而非磁盘卷）。"""
    total = 0
    try:
        for root, _dirs, files in os.walk(path):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:  # noqa: PERF203 - 单文件失败不中断统计
                    continue
    except OSError:
        return 0
    return total


class HistoryDB:
    """
    SQLite 数据库管理器：
    - tasks 表：任务记录
    - outputs 表：输出文件
    - presets 表：预设
    - tasks_fts：全文检索（FTS5）
    - WAL 模式：崩溃恢复
    """

    SCHEMA_SQL = """
    -- 任务表
    CREATE TABLE IF NOT EXISTS tasks (
        task_id          TEXT PRIMARY KEY,
        engine           TEXT NOT NULL,
        mode             TEXT NOT NULL DEFAULT 'txt2img',  -- txt2img | batch
        status           TEXT NOT NULL DEFAULT 'pending',  -- pending|processing|completed|failed|cancelled
        prompt           TEXT DEFAULT '',
        negative_prompt  TEXT DEFAULT '',
        generation_config TEXT DEFAULT '{}',  -- JSON 22 项
        thumbnail        TEXT DEFAULT '',
        output_count     INTEGER DEFAULT 0,
        processing_time_s REAL DEFAULT 0,
        error            TEXT DEFAULT '',
        favorite         INTEGER DEFAULT 0,
        tags             TEXT DEFAULT '[]',  -- JSON 数组
        created_at       TEXT DEFAULT (datetime('now')),
        updated_at       TEXT DEFAULT (datetime('now')),
        interrupted_at_reboot INTEGER DEFAULT 0,
        -- 血缘 / 数据治理增强列（数据治理评估报告 §3.3 / §4.1）
        -- 作为基线列直接建表，保证全新库自带；旧库由 _apply_migrations 补齐。
        workflow_version TEXT DEFAULT '',
        lora_checksums   TEXT DEFAULT '[]',
        error_code       TEXT DEFAULT '',
        -- 软删除 / 回收站（防误删）：NULL=未删，非空=删除时间戳，可恢复
        deleted_at       TEXT DEFAULT NULL,
        -- 提交→worker 边界最小关联键：提交侧 HTTP request_id（日志 req= 同源）
        request_id       TEXT DEFAULT ''
    );

    -- 输出表（一对多）
    CREATE TABLE IF NOT EXISTS outputs (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id    TEXT NOT NULL,
        path       TEXT NOT NULL,
        format     TEXT DEFAULT 'png',
        file_size  INTEGER DEFAULT 0,
        width      INTEGER DEFAULT 0,
        height     INTEGER DEFAULT 0,
        seed       TEXT DEFAULT '',
        output_type TEXT DEFAULT 'original',  -- original|upscaled|compare
        created_at TEXT DEFAULT (datetime('now')),
        -- 输出文件指纹（数据治理报告 P2-4/Q1-①：图片自描述之外的输出级血缘）
        sha256     TEXT DEFAULT '',
        FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
    );

    -- 预设表
    CREATE TABLE IF NOT EXISTS presets (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        engine_name TEXT NOT NULL,
        name        TEXT NOT NULL,
        thumbnail   TEXT DEFAULT '',
        config      TEXT DEFAULT '{}',  -- JSON，不含 seed
        created_at  TEXT DEFAULT (datetime('now')),
        UNIQUE(engine_name, name)
    );

    -- 全文检索索引（trigram：中文/英文子串均可命中；<3 字符查询由 list_tasks 走 LIKE）
    CREATE VIRTUAL TABLE IF NOT EXISTS tasks_fts USING fts5(
        task_id UNINDEXED,
        prompt,
        tags,
        content='tasks',
        content_rowid='rowid',
        tokenize='trigram'
    );

    -- 容量日快照表（成本资源治理评估报告 §5-⑤：回答「磁盘还能撑多久 / 显卡够不够用」）
    CREATE TABLE IF NOT EXISTS capacity_snapshots (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_date  TEXT NOT NULL,               -- 快照归属日期（YYYY-MM-DD）
        peak_used_gb   REAL DEFAULT 0,              -- 当日 VRAM 已用峰值（GB）
        disk_used_gb   REAL DEFAULT 0,              -- 数据卷已用空间（GB）
        gpu_hours_24h  REAL DEFAULT 0,              -- 近 24h GPU·小时（processing_time_s 聚合）
        created_at     TEXT DEFAULT (datetime('now')),
        UNIQUE(snapshot_date)
    );

    -- 索引
    CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
    CREATE INDEX IF NOT EXISTS idx_tasks_engine ON tasks(engine);
    CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at);
    CREATE INDEX IF NOT EXISTS idx_tasks_favorite ON tasks(favorite);
    CREATE INDEX IF NOT EXISTS idx_outputs_task_id ON outputs(task_id);
    CREATE INDEX IF NOT EXISTS idx_outputs_path ON outputs(path);
    CREATE INDEX IF NOT EXISTS idx_capacity_snapshots_date ON capacity_snapshots(snapshot_date);
    """

    # 血缘 / 数据治理增强列（数据治理评估报告 §3.3 / §4.1）
    # 已在 CREATE TABLE 中作为基线列提供（保证全新库自带）；
    # 此处对旧库做向前兼容迁移。注意：SQLite 的 ALTER TABLE ADD COLUMN
    # *不支持* IF NOT EXISTS 语法（会报 near "EXISTS": syntax error），
    # 故改用 PRAGMA table_info 探测后逐项 ALTER，避免迁移静默失败导致
    # create_task 写入这些列时报 "no column named ..."。
    MIGRATION_COLUMNS = (
        ("workflow_version", "TEXT DEFAULT ''"),
        ("lora_checksums", "TEXT DEFAULT '[]'"),
        ("error_code", "TEXT DEFAULT ''"),
    )

    FTS_TRIGGER_SQL = """
    -- 注意：INSERT 必须显式携带 rowid（new.rowid），否则 UPDATE 触发器的
    -- "删除旧行→插入新行"会让新行落到 rowid=max+1，与 tasks.rowid 错位，
    -- list_tasks 的 JOIN tasks.rowid=tasks_fts.rowid 将匹配不到更新过的任务
    -- （历史库由 v6 迁移重建修复）。
    CREATE TRIGGER IF NOT EXISTS tasks_ai AFTER INSERT ON tasks BEGIN
        INSERT INTO tasks_fts(rowid, task_id, prompt, tags)
        VALUES (new.rowid, new.task_id, new.prompt, new.tags);
    END;
    CREATE TRIGGER IF NOT EXISTS tasks_ad AFTER DELETE ON tasks BEGIN
        INSERT INTO tasks_fts(tasks_fts, rowid, prompt, tags)
        VALUES ('delete', old.rowid, old.prompt, old.tags);
    END;
    CREATE TRIGGER IF NOT EXISTS tasks_au AFTER UPDATE ON tasks BEGIN
        INSERT INTO tasks_fts(tasks_fts, rowid, prompt, tags)
        VALUES ('delete', old.rowid, old.prompt, old.tags);
        INSERT INTO tasks_fts(rowid, task_id, prompt, tags)
        VALUES (new.rowid, new.task_id, new.prompt, new.tags);
    END;
    """

    # 数据库 schema 单调版本号（数据治理报告 P2-4）。
    # 1 = 基线 schema；2 = tasks 血缘增强列；3 = outputs.sha256 输出指纹；
    # 4 = tasks.deleted_at 软删除；5 = tasks.request_id 提交→worker 关联键；
    # 6 = FTS 触发器显式 rowid + trigram 重建（修复更新后任务从搜索消失）。
    # 迁移步骤见 _migrations()；改基线 schema 或加列时必须同步 +1 并注册迁移。
    SCHEMA_VERSION = 6

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # 关闭护栏锁：所有数据库调用与 close() 共用这一把锁，
        # 保证 close() 不可能在某次 execute() 进行中拆掉连接（否则段错误）。
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None
        self._guard: _GuardedConnection | None = None
        self._init_db()

    def _apply_migrations(self, conn: sqlite3.Connection) -> None:
        """版本化迁移（数据治理报告 P2-4）：PRAGMA user_version 单调推进。

        设计要点：
        - ``PRAGMA user_version`` 作单调版本号；迁移步骤按版本有序注册，
          仅执行 ``current < version`` 的步骤——可表达「数据回填」类迁移，
          不再单纯依赖 ``table_info`` 列探测。
        - **fail-closed**：单步迁移失败直接抛异常终止启动（旧实现只
          ``logger.warning`` 后继续跑，后续 ``create_task`` 必爆
          ``no column named ...``，把启动失败推迟成更难排查的运行时错误）。
        - 全新库：``SCHEMA_SQL`` 已含全部基线列，各迁移步骤探测后为 no-op，
          仅把 user_version 推进到 ``SCHEMA_VERSION``。
        """
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        for version, migrate in self._migrations():
            if current >= version:
                continue
            migrate(conn)  # 不捕获：单步失败 → 启动失败（fail-closed）
            conn.execute(f"PRAGMA user_version = {version}")
        if current < self.SCHEMA_VERSION:
            conn.commit()

    def _migrations(self) -> tuple[tuple[int, Any], ...]:
        """有序迁移注册表：(目标版本号, 迁移函数)。新迁移追加到末尾。"""
        return (
            (2, self._migrate_v2_lineage_columns),
            (3, self._migrate_v3_outputs_sha256),
            (4, self._migrate_v4_soft_delete),
            (5, self._migrate_v5_request_id),
            (6, self._migrate_v6_fts_rowid_alignment),
        )

    def _migrate_v5_request_id(self, conn: sqlite3.Connection) -> None:
        """v5：tasks 表补齐 request_id 列（提交→worker 边界最小关联键）。"""
        existing = {r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
        if "request_id" not in existing:
            conn.execute("ALTER TABLE tasks ADD COLUMN request_id TEXT DEFAULT ''")

    def _migrate_v6_fts_rowid_alignment(self, conn: sqlite3.Connection) -> None:
        """v6：FTS 触发器显式对齐 rowid + trigram 重建索引。

        根因（2026-09 搜索修复）：旧触发器在 UPDATE 时先 DELETE 旧 FTS 行再
        无 rowid INSERT，新行落到 ``rowid = max+1``，与 ``tasks.rowid`` 错位，
        ``list_tasks`` 的 ``JOIN tasks.rowid=tasks_fts.rowid`` 失配 ——
        更新过（如 completed）的任务从全文搜索中消失；且 unicode61 分词器
        不索引中文。修复：显式 rowid 的新触发器 + 按 trigram 重建索引
        （trigram 对 ≥3 字符的英文/中文子串均可命中；<3 字符由 LIKE 兜底）。
        幂等可重入：drop → create → rebuild。
        """
        conn.executescript(
            """
            DROP TRIGGER IF EXISTS tasks_ai;
            DROP TRIGGER IF EXISTS tasks_ad;
            DROP TRIGGER IF EXISTS tasks_au;
            DROP TABLE IF EXISTS tasks_fts;
            """
        )
        conn.executescript(self.SCHEMA_SQL)
        conn.executescript(self.FTS_TRIGGER_SQL)
        conn.execute("INSERT INTO tasks_fts(tasks_fts) VALUES('rebuild')")
        logger.info("FTS index rebuilt (trigram, rowid-aligned triggers) for schema v6")

    def _migrate_v4_soft_delete(self, conn: sqlite3.Connection) -> None:
        """v4：tasks 表补齐软删除列（回收站 / 防误删）。"""
        existing = {r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
        if "deleted_at" not in existing:
            conn.execute("ALTER TABLE tasks ADD COLUMN deleted_at TEXT DEFAULT NULL")

    def _migrate_v2_lineage_columns(self, conn: sqlite3.Connection) -> None:
        """v2：旧库补齐血缘增强列（向前兼容）。

        SQLite 的 ``ALTER TABLE ... ADD COLUMN`` 不支持 ``IF NOT EXISTS`` 语法，
        故先以 ``PRAGMA table_info`` 探测现有列，仅对缺失列执行 ALTER。
        ALTER 失败不再吞异常——直接抛出终止启动（fail-closed，P2-4）。
        """
        existing = {r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
        for col, ddl in self.MIGRATION_COLUMNS:
            if col in existing:
                continue
            conn.execute(f"ALTER TABLE tasks ADD COLUMN {col} {ddl}")

    def _migrate_v3_outputs_sha256(self, conn: sqlite3.Connection) -> None:
        """v3：outputs 表补齐输出文件指纹列（数据治理报告 Q1-①）。"""
        existing = {r[1] for r in conn.execute("PRAGMA table_info(outputs)").fetchall()}
        if "sha256" not in existing:
            conn.execute("ALTER TABLE outputs ADD COLUMN sha256 TEXT DEFAULT ''")

    def _init_db(self) -> None:
        """初始化数据库"""
        conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        # WAL 模式（崩溃恢复）
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(self.SCHEMA_SQL)
        conn.executescript(self.FTS_TRIGGER_SQL)
        # 血缘增强列迁移（向前兼容旧库；全新库已在 CREATE TABLE 中自带）
        self._apply_migrations(conn)
        conn.commit()
        self._conn = conn
        # 对外只暴露护栏代理，调用方拿不到裸连接，无法在 close() 之后误用
        self._guard = _GuardedConnection(conn, self._lock)
        logger.info(f"HistoryDB initialized at {self.db_path}")

    @property
    def conn(self) -> _GuardedConnection:
        """数据库连接（护栏代理）。

        返回值**不是**裸 ``sqlite3.Connection``，而是 :class:`_GuardedConnection`：
        接口一致（``execute`` / ``executescript`` / ``commit`` / ``row_factory``
        等全部转发），但连接被关闭后会抛 :class:`HistoryDBClosedError` 而不是
        在 C 扩展层段错误。连接为 ``None`` 时（含首次初始化与 ``close()`` 之后）
        仍按既有语义懒重开。
        """
        with self._lock:
            if self._guard is None or self._guard.closed:
                self._init_db()
            assert self._guard is not None
            return self._guard

    # ── 崩溃恢复 ──────────────────────────────────────────────
    def recover_stuck_tasks(self, max_processing_hours: float = 1.0) -> int:
        """
        清理卡死的 processing 任务（超过 max_processing_hours 小时）。

        Returns:
            清理的任务数量
        """
        conn = self.conn
        # 标记卡死任务为 interrupted
        cutoff = time.time() - max_processing_hours * 3600
        cutoff_str = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(cutoff))
        cur = conn.execute(
            "UPDATE tasks SET status='interrupted', interrupted_at_reboot=1, "
            "updated_at=datetime('now') "
            "WHERE status='processing' AND created_at < ?",
            (cutoff_str,),
        )
        conn.commit()
        count = cur.rowcount
        if count > 0:
            logger.warning(f"Recovered {count} stuck tasks (marked as interrupted)")
        return count

    def mark_stale_pending_interrupted(
        self,
        exclude_task_ids: list[str] | None = None,
        stale_after_s: float = 0.0,
    ) -> int:
        """启动时把遗留 pending 任务标记为 interrupted（成本资源治理评估报告 P2-⑥）。

        背景：``runtime.task_queue.auto_recover: false`` 时，上次会话中断的
        pending 任务没有任何执行者，会永久滞留为僵尸记录（实测 1500/3073 条）。
        在启动恢复（checkpoint 续跑）**之前**调用，并把待续跑任务排除在外。

        Args:
            exclude_task_ids: 需要保留 pending 的任务（即将由 checkpoint 续跑）。
            stale_after_s: 宽限期（秒）。>0 时仅标记 ``created_at`` 早于该阈值
                的 pending 任务——蓝绿部署重叠窗口 / pytest-xdist 并行 worker
                共享 DB 等场景下，**刚创建**的 pending 任务属于在飞任务，
                不得被另一实例的启动清扫误杀（CI run 33939248177 回归根因：
                journey 任务提交后数秒即被并行 worker 的启动清扫打成
                interrupted）。默认 0 保持"全量标记"的历史行为（单测依赖）。

        Returns:
            标记的任务数
        """
        conn = self.conn
        where = ["status='pending'"]
        params: list = []
        if stale_after_s > 0:
            where.append("created_at < datetime('now', ?)")
            params.append(f"-{float(stale_after_s)} seconds")
        exclude = [t for t in (exclude_task_ids or []) if t]
        if exclude:
            placeholders = ",".join("?" * len(exclude))
            where.append(f"task_id NOT IN ({placeholders})")
            params.extend(exclude)
        cur = conn.execute(
            "UPDATE tasks SET status='interrupted', interrupted_at_reboot=1, "
            f"updated_at=datetime('now') WHERE {' AND '.join(where)}",
            tuple(params),
        )
        conn.commit()
        count = cur.rowcount
        if count > 0:
            logger.warning(f"Marked {count} stale pending tasks as interrupted (stale-pending sweep)")
        return count

    # ── 容量日快照（成本资源治理评估报告 §5-⑤ / 必答三问 Q3）────
    def record_capacity_snapshot(
        self,
        snapshot_date: str,
        peak_used_gb: float,
        disk_used_gb: float,
        gpu_hours_24h: float,
    ) -> None:
        """写入（或按日期覆盖）一条容量日快照。UNIQUE(snapshot_date) 幂等。"""
        conn = self.conn
        conn.execute(
            "INSERT INTO capacity_snapshots (snapshot_date, peak_used_gb, disk_used_gb, gpu_hours_24h) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(snapshot_date) DO UPDATE SET "
            "peak_used_gb=excluded.peak_used_gb, disk_used_gb=excluded.disk_used_gb, "
            "gpu_hours_24h=excluded.gpu_hours_24h",
            (snapshot_date, round(peak_used_gb, 3), round(disk_used_gb, 3), round(gpu_hours_24h, 4)),
        )
        conn.commit()

    def list_capacity_snapshots(self, limit: int = 30) -> list[dict[str, Any]]:
        """读取最近 N 条容量快照（默认 30 天），按日期倒序。"""
        conn = self.conn
        rows = conn.execute(
            "SELECT snapshot_date, peak_used_gb, disk_used_gb, gpu_hours_24h, created_at "
            "FROM capacity_snapshots ORDER BY snapshot_date DESC LIMIT ?",
            (max(1, int(limit)),),
        ).fetchall()
        return [dict(r) for r in rows]

    def sum_processing_since(self, cutoff_epoch_s: float) -> float:
        """统计某时间点之后创建任务的 processing_time_s 总和（秒）。

        created_at 存 UTC 文本（datetime('now')），故 cutoff 亦按 UTC 换算。
        供容量快照的 gpu_hours_24h 使用（FinOps 失败入账后该口径自动覆盖失败任务）。
        """
        cutoff_str = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(cutoff_epoch_s))
        row = self.conn.execute(
            "SELECT COALESCE(SUM(processing_time_s), 0) FROM tasks WHERE created_at >= ?",
            (cutoff_str,),
        ).fetchone()
        return float(row[0] if row else 0.0)

    # ── 任务 CRUD ─────────────────────────────────────────────
    def create_task(
        self,
        task_id: str,
        engine: str,
        mode: str = "txt2img",
        prompt: str = "",
        negative_prompt: str = "",
        generation_config: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        workflow_version: str = "",
        lora_checksums: list[dict] | None = None,
        request_id: str = "",
    ) -> None:
        """创建新任务"""
        conn = self.conn
        conn.execute(
            "INSERT INTO tasks (task_id, engine, mode, prompt, negative_prompt, "
            "generation_config, tags, workflow_version, lora_checksums, request_id, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
            (
                task_id,
                engine,
                mode,
                prompt,
                negative_prompt,
                json.dumps(generation_config or {}, ensure_ascii=False),
                json.dumps(tags or [], ensure_ascii=False),
                workflow_version,
                json.dumps(lora_checksums or [], ensure_ascii=False),
                request_id or "",
            ),
        )
        conn.commit()

    def update_task_status(
        self,
        task_id: str,
        status: str,
        error: str = "",
        processing_time_s: float = 0,
        output_count: int = 0,
        thumbnail: str = "",
        error_code: str = "",
    ) -> None:
        """更新任务状态"""
        conn = self.conn
        conn.execute(
            "UPDATE tasks SET status=?, error=?, processing_time_s=?, "
            "output_count=?, thumbnail=?, error_code=?, updated_at=datetime('now') "
            "WHERE task_id=?",
            (status, error, processing_time_s, output_count, thumbnail, error_code, task_id),
        )
        conn.commit()

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        """获取任务详情（含 generation_config + 三路输出）"""
        conn = self.conn
        row = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if not row:
            return None
        task = dict(row)
        task["generation_config"] = json.loads(task.get("generation_config") or "{}")
        task["tags"] = json.loads(task.get("tags") or "[]")
        task["lora_checksums"] = json.loads(task.get("lora_checksums") or "[]")
        # 获取关联的输出
        outputs = conn.execute("SELECT * FROM outputs WHERE task_id=? ORDER BY id", (task_id,)).fetchall()
        task["outputs"] = [dict(o) for o in outputs]
        return task

    def list_tasks(
        self,
        status: str | None = None,
        engine: str | None = None,
        q: str | None = None,
        favorite: bool | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        """
        分页筛选任务列表。

        搜索（``q``）语义：
        - 含 CJK 或长度 < 3 的查询走 ``LIKE`` 子串匹配（FTS5 的 unicode61
          分词器不索引中文/日文/韩文，短查询也无法子串命中）；
        - 其余查询走 ``tasks_fts MATCH``，语法错误自动降级 LIKE，
          任何用户输入都不会让搜索 500。

        Returns:
            (tasks, total_count)
        """
        conn = self.conn
        where = []
        params: list = []

        # 回收站隔离：正常列表永远排除已软删除的任务
        where.append("deleted_at IS NULL")
        if status:
            where.append("status=?")
            params.append(status)
        if engine:
            where.append("engine=?")
            params.append(engine)
        if favorite is not None:
            where.append("favorite=?")
            params.append(1 if favorite else 0)
        if q:
            q = q.strip()
        if q:
            if _CJK_SEARCH_RE.search(q) or len(q) < 3:
                # FTS5 对 CJK 不可索引（unicode61 不产出中文 token），
                # 对 <3 字符查询也无子串命中能力（trigram 语义）→ LIKE 子串。
                pattern = f"%{_escape_like(q)}%"
                where.append("(prompt LIKE ? ESCAPE '\\' OR tags LIKE ? ESCAPE '\\' OR task_id LIKE ? ESCAPE '\\')")
                params.extend([pattern, pattern, pattern])
            else:
                where.append("tasks_fts MATCH ?")
                params.append(q)

        where_clause = " AND ".join(where) if where else "1=1"

        fts_used = "tasks_fts MATCH ?" in where
        try:
            if fts_used:
                # FTS5 路径：JOIN tasks_fts 按索引命中
                count_sql = (
                    f"SELECT COUNT(*) FROM tasks JOIN tasks_fts ON tasks.rowid=tasks_fts.rowid WHERE {where_clause}"
                )
                total = conn.execute(count_sql, params).fetchone()[0]
                offset = (page - 1) * page_size
                sql = (
                    "SELECT t.* FROM tasks t JOIN tasks_fts ON t.rowid=tasks_fts.rowid "
                    f"WHERE {where_clause} "
                    "ORDER BY t.created_at DESC LIMIT ? OFFSET ?"
                )
                rows = conn.execute(sql, params + [page_size, offset]).fetchall()
            else:
                # 常规 / LIKE 路径
                count_sql = f"SELECT COUNT(*) FROM tasks WHERE {where_clause}"
                total = conn.execute(count_sql, params).fetchone()[0]
                offset = (page - 1) * page_size
                sql = f"SELECT * FROM tasks WHERE {where_clause} ORDER BY created_at DESC LIMIT ? OFFSET ?"
                rows = conn.execute(sql, params + [page_size, offset]).fetchall()
        except sqlite3.OperationalError:
            if not fts_used:
                raise
            # FTS5 查询语法错误（引号/括号等特殊字符进入 MATCH）→ LIKE 兜底，
            # 保证任何用户输入都不会让搜索页 500。
            logger.warning("FTS5 MATCH failed for q=%r, falling back to LIKE", q)
            pattern = f"%{_escape_like(q)}%"
            like_where = [w for w in where if w != "tasks_fts MATCH ?"]
            like_where.append("(prompt LIKE ? ESCAPE '\\' OR tags LIKE ? ESCAPE '\\' OR task_id LIKE ? ESCAPE '\\')")
            like_params = params[:-1] + [pattern, pattern, pattern]
            like_clause = " AND ".join(like_where)
            total = conn.execute(f"SELECT COUNT(*) FROM tasks WHERE {like_clause}", like_params).fetchone()[0]
            offset = (page - 1) * page_size
            rows = conn.execute(
                f"SELECT * FROM tasks WHERE {like_clause} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                like_params + [page_size, offset],
            ).fetchall()
        tasks = []
        for r in rows:
            t = dict(r)
            t["generation_config"] = json.loads(t.get("generation_config") or "{}")
            t["tags"] = json.loads(t.get("tags") or "[]")
            tasks.append(t)
        return tasks, total

    def delete_tasks(self, task_ids: list[str], soft: bool = True) -> int:
        """批量删除任务。

        默认软删除（回收站）：仅标记 deleted_at，记录与磁盘文件均保留，可恢复。
        ``soft=False`` 时物理删除（含级联 outputs 行）。

        Returns:
            受影响行数
        """
        if not task_ids:
            return 0
        conn = self.conn
        placeholders = ",".join("?" * len(task_ids))
        if soft:
            # 防误删：标记删除时间戳，而非物理 DELETE
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
            cur = conn.execute(
                f"UPDATE tasks SET deleted_at=?, updated_at=datetime('now') WHERE task_id IN ({placeholders}) AND deleted_at IS NULL",
                [ts, *task_ids],
            )
        else:
            cur = conn.execute(f"DELETE FROM tasks WHERE task_id IN ({placeholders})", task_ids)
        conn.commit()
        return cur.rowcount

    def set_favorite(self, task_id: str, favorite: bool) -> None:
        """设置/取消收藏"""
        conn = self.conn
        conn.execute(
            "UPDATE tasks SET favorite=?, updated_at=datetime('now') WHERE task_id=?",
            (1 if favorite else 0, task_id),
        )
        conn.commit()

    # ── 输出 CRUD ─────────────────────────────────────────────
    def add_output(
        self,
        task_id: str,
        path: str,
        format: str = "png",
        file_size: int = 0,
        width: int = 0,
        height: int = 0,
        seed: str = "",
        output_type: str = "original",
        sha256: str = "",
    ) -> None:
        """添加输出记录（sha256 为输出文件指纹，数据治理报告 Q1-①）"""
        conn = self.conn
        conn.execute(
            "INSERT INTO outputs (task_id, path, format, file_size, width, height, seed, output_type, sha256) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (task_id, path, format, file_size, width, height, seed, output_type, sha256),
        )
        conn.commit()

    def clear_task_outputs(self, task_id: str) -> int:
        """清空某任务已登记的输出记录（重试幂等用）。

        worker 自动重试（P2-6）会重跑完整生成并再次 ``add_output``；若不清空，
        同一 ``task_id`` 会累积重复行，图库出现重复项。落库前调用本方法使重试
        幂等（见后端服务设计评估报告 P2-3）。

        Returns:
            删除的记录数
        """
        conn = self.conn
        cur = conn.execute("DELETE FROM outputs WHERE task_id=?", (task_id,))
        conn.commit()
        return int(cur.rowcount or 0)

    def list_outputs(
        self,
        output_type: str | None = None,
        favorite: bool | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        """
        分页查询输出文件（图库用）。
        JOIN tasks 获取 favorite 状态。
        """
        conn = self.conn
        where = []
        params: list = []
        if output_type:
            where.append("o.output_type=?")
            params.append(output_type)
        if favorite:
            where.append("t.favorite=1")
        # 回收站隔离：图库不展示已软删除任务的输出
        where.append("t.deleted_at IS NULL")

        where_clause = " AND ".join(where) if where else "1=1"
        total = conn.execute(
            f"SELECT COUNT(*) FROM outputs o JOIN tasks t ON o.task_id=t.task_id WHERE {where_clause}",
            params,
        ).fetchone()[0]

        offset = (page - 1) * page_size
        rows = conn.execute(
            f"SELECT o.*, t.engine, t.prompt, t.favorite, t.created_at "
            f"FROM outputs o JOIN tasks t ON o.task_id=t.task_id "
            f"WHERE {where_clause} "
            f"ORDER BY o.created_at DESC LIMIT ? OFFSET ?",
            params + [page_size, offset],
        ).fetchall()
        return [dict(r) for r in rows], total

    def set_output_favorite(self, file_path: str, favorite: bool) -> None:
        """标记输出文件收藏"""
        conn = self.conn
        conn.execute(
            "UPDATE tasks SET favorite=? WHERE task_id IN (SELECT task_id FROM outputs WHERE path=?)",
            (1 if favorite else 0, file_path),
        )
        conn.commit()

    # ── 预设 CRUD ─────────────────────────────────────────────
    def create_preset(
        self,
        engine_name: str,
        name: str,
        config: dict[str, Any],
        thumbnail: str = "",
    ) -> int:
        """创建预设，返回 id"""
        conn = self.conn
        try:
            cur = conn.execute(
                "INSERT INTO presets (engine_name, name, config, thumbnail) VALUES (?, ?, ?, ?)",
                (engine_name, name, json.dumps(config, ensure_ascii=False), thumbnail),
            )
            conn.commit()
            return cur.lastrowid or 0
        except sqlite3.IntegrityError:
            raise ValueError(f"Preset '{name}' for engine '{engine_name}' already exists")

    def list_presets(self, engine_name: str | None = None) -> list[dict[str, Any]]:
        """列出预设"""
        conn = self.conn
        if engine_name:
            rows = conn.execute(
                "SELECT * FROM presets WHERE engine_name=? ORDER BY created_at DESC",
                (engine_name,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM presets ORDER BY created_at DESC").fetchall()
        result = []
        for r in rows:
            p = dict(r)
            p["config"] = json.loads(p.get("config") or "{}")
            result.append(p)
        return result

    def get_preset(self, preset_id: int) -> dict[str, Any] | None:
        """获取预设"""
        conn = self.conn
        row = conn.execute("SELECT * FROM presets WHERE id=?", (preset_id,)).fetchone()
        if not row:
            return None
        p = dict(row)
        p["config"] = json.loads(p.get("config") or "{}")
        return p

    def update_preset(
        self,
        preset_id: int,
        name: str | None = None,
        config: dict[str, Any] | None = None,
        thumbnail: str | None = None,
    ) -> None:
        """更新预设"""
        conn = self.conn
        sets = []
        params: list = []
        if name is not None:
            sets.append("name=?")
            params.append(name)
        if config is not None:
            sets.append("config=?")
            params.append(json.dumps(config, ensure_ascii=False))
        if thumbnail is not None:
            sets.append("thumbnail=?")
            params.append(thumbnail)
        if not sets:
            return
        params.append(preset_id)
        conn.execute(f"UPDATE presets SET {', '.join(sets)} WHERE id=?", params)
        conn.commit()

    def delete_preset(self, preset_id: int) -> bool:
        """删除预设"""
        conn = self.conn
        cur = conn.execute("DELETE FROM presets WHERE id=?", (preset_id,))
        conn.commit()
        return cur.rowcount > 0

    def delete_presets(self, preset_ids: list[int]) -> int:
        """批量删除预设（按 id 列表，忽略不存在的 id）"""
        if not preset_ids:
            return 0
        conn = self.conn
        marks = ",".join("?" * len(preset_ids))
        cur = conn.execute(f"DELETE FROM presets WHERE id IN ({marks})", preset_ids)
        conn.commit()
        return cur.rowcount

    def add_task_tags(self, task_ids: list[str], tags: list[str]) -> int:
        """批量给任务加标签"""
        if not task_ids or not tags:
            return 0
        conn = self.conn
        count = 0
        for tid in task_ids:
            row = conn.execute("SELECT tags FROM tasks WHERE task_id=?", (tid,)).fetchone()
            if not row:
                continue
            existing = json.loads(row["tags"] or "[]")
            merged = list(set(existing) | set(tags))
            conn.execute(
                "UPDATE tasks SET tags=?, updated_at=datetime('now') WHERE task_id=?",
                (json.dumps(merged, ensure_ascii=False), tid),
            )
            count += 1
        conn.commit()
        return count

    def cleanup_old_tasks(
        self,
        keep_days: int = 30,
        max_gb: float = 0,
        protect_task_ids: set[str] | None = None,
    ) -> int:
        """
        清理超期任务（保留策略：天数/大小双阈值）。

        关键修复（COST_GOVERNANCE_ASSESSMENT P0）：清理任务时**同步删除磁盘上的
        实际输出图片**，否则仅删 DB 记录无法释放存储，磁盘仍会被写满。

        Args:
            keep_days: 保留天数（0 = 不按天数清理）
            max_gb: 输出目录最大 GB（0 = 不按大小清理）
            protect_task_ids: 白名单——这些任务**即使超期也不清理**。用于
                "会话图片生命周期"（评估报告第八章 C-11）：Agent 对话里引用过的
                图一旦被清理就会变成裂图，故由调用方传入活跃会话引用的 task_id。
                传 None / 空集合 = 不保护（与历史行为一致）。

        Returns:
            删除的任务数
        """
        outputs_dir = Path(self.db_path).parent.parent / "outputs"
        candidate_ids: list[str] = []

        if keep_days > 0:
            cutoff = time.time() - keep_days * 86400
            cutoff_str = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(cutoff))
            rows = self.conn.execute(
                "SELECT task_id FROM tasks WHERE created_at < ? AND favorite=0",
                (cutoff_str,),
            ).fetchall()
            candidate_ids.extend(r[0] for r in rows)

        if max_gb > 0 and outputs_dir.exists():
            try:
                # 成本资源治理评估报告 P1-③：此前用 shutil.disk_usage(outputs_dir).used
                # 度量的是**整个磁盘卷**的已用空间，而非 outputs 目录体积，导致
                # max_gb 语义（输出目录上限）与实现不符。改为遍历 outputs 目录求和。
                size_gb = _dir_size_bytes(outputs_dir) / (1024**3)
                if size_gb > max_gb:
                    total_rows = self.conn.execute(
                        "SELECT task_id FROM tasks WHERE favorite=0 ORDER BY created_at ASC"
                    ).fetchall()
                    n = len(total_rows)
                    if n > 0:
                        # 近似：按超额比例删除最旧任务（至少 1 个），避免一次删光
                        over_ratio = min(1.0, (size_gb - max_gb) / max(size_gb, 1e-6))
                        drop = max(1, int(n * over_ratio))
                        candidate_ids.extend(r[0] for r in total_rows[:drop])
            except Exception:
                pass

        if not candidate_ids:
            return 0
        # 会话引用保护：Agent 对话里展示过的图不能被清理成裂图（评估报告 C-11）
        if protect_task_ids:
            before = len(candidate_ids)
            candidate_ids = [t for t in candidate_ids if t not in protect_task_ids]
            protected = before - len(candidate_ids)
            if protected:
                logger.info("Cleanup: 跳过 %s 个被活跃会话引用的任务", protected)
            if not candidate_ids:
                return 0
        # 清理策略需真正释放磁盘空间 → 硬删除（文件 + DB 行）
        deleted = self.delete_tasks_with_files(list(dict.fromkeys(candidate_ids)), soft=False)
        if deleted > 0:
            logger.info(f"Cleanup: deleted {deleted} old tasks (keep_days={keep_days}, max_gb={max_gb})")
        return deleted

    def _delete_task_files(self, task_ids: list[str], outputs_dir: Path) -> None:
        """删除任务关联的磁盘文件：主输出图 + 缩略图（数据治理 P0-2/P1-1）。

        保留收藏任务不被删文件（调用方已过滤 favorite）。
        """
        task_ids = list(dict.fromkeys(task_ids))
        if not task_ids:
            return
        placeholders = ",".join("?" * len(task_ids))
        # 1) 删除实际图片文件
        rows = self.conn.execute(f"SELECT path FROM outputs WHERE task_id IN ({placeholders})", task_ids).fetchall()
        for (p,) in rows:
            try:
                fp = outputs_dir / p
                if fp.exists():
                    fp.unlink()
            except Exception as e:  # noqa: BLE001
                logger.debug("Failed to unlink output file %s: %s", p, e)
        # 2) 删除缩略图（data/cache/thumbs，命名含 task_id[:16] 前缀；另含 tasks.thumbnail 引用）
        thumbs_dir = Path(self.db_path).parent / "cache" / "thumbs"
        if thumbs_dir.is_dir():
            try:
                referenced = {
                    (r[0] or "").lstrip("/\\")
                    for r in self.conn.execute(
                        f"SELECT thumbnail FROM tasks WHERE task_id IN ({placeholders})", task_ids
                    ).fetchall()
                }
            except Exception:  # noqa: BLE001
                referenced = set()
            for tid in task_ids:
                prefix = tid[:16]
                for thumb in thumbs_dir.glob(f"{prefix}_*"):
                    try:
                        thumb.unlink()
                    except Exception as e:  # noqa: BLE001
                        logger.debug("Failed to unlink thumbnail %s: %s", thumb, e)
            for rel in referenced:
                if not rel:
                    continue
                fp = (thumbs_dir / rel) if not Path(rel).is_absolute() else Path(rel)
                if fp.exists():
                    try:
                        fp.unlink()
                    except Exception as e:  # noqa: BLE001
                        logger.debug("Failed to unlink referenced thumbnail %s: %s", fp, e)

    def delete_tasks_with_files(self, task_ids: list[str], soft: bool = True) -> int:
        """公开入口：删除任务及其磁盘文件（主图 + 缩略图）。

        默认软删除（回收站）：仅标记 deleted_at，**保留磁盘文件**，记录可恢复。
        ``soft=False`` 时物理删除文件 + DB 行（供清理策略 / 彻底清空使用）。

        供 DELETE /api/tasks 路由调用，消灭「只删 DB 不删文件」导致磁盘孤儿
        （数据治理报告 P0-2 / P1-1）。收藏任务不删文件。
        """
        if not task_ids:
            return 0
        if soft:
            # 回收站：保留文件，仅标记删除
            return self.delete_tasks(task_ids, soft=True)
        # 硬删除：先删磁盘文件，再删 DB（ON DELETE CASCADE 清理 outputs 行）
        outputs_dir = Path(self.db_path).parent.parent / "outputs"
        self._delete_task_files(task_ids, outputs_dir)
        placeholders = ",".join("?" * len(task_ids))
        cur = self.conn.execute(f"DELETE FROM tasks WHERE task_id IN ({placeholders})", task_ids)
        self.conn.commit()
        return cur.rowcount

    def restore_tasks(self, task_ids: list[str]) -> int:
        """从回收站恢复任务（清除 deleted_at 标记）。"""
        if not task_ids:
            return 0
        placeholders = ",".join("?" * len(task_ids))
        cur = self.conn.execute(
            f"UPDATE tasks SET deleted_at=NULL, updated_at=datetime('now') WHERE task_id IN ({placeholders})",
            task_ids,
        )
        self.conn.commit()
        return cur.rowcount

    def list_deleted_tasks(self, page: int = 1, page_size: int = 50) -> tuple[list[dict[str, Any]], int]:
        """列出回收站中的任务（已软删除）。"""
        conn = self.conn
        total = conn.execute("SELECT COUNT(*) FROM tasks WHERE deleted_at IS NOT NULL").fetchone()[0]
        offset = (page - 1) * page_size
        rows = conn.execute(
            "SELECT * FROM tasks WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC LIMIT ? OFFSET ?",
            [page_size, offset],
        ).fetchall()
        return [dict(r) for r in rows], total

    def purge_deleted_tasks(self, keep_days: int = 30) -> int:
        """彻底清理回收站中超过 keep_days 天的任务（删除 DB 行 + 磁盘文件）。

        保留期内的软删除记录可经 ``restore_tasks`` 恢复；超过保留期才物理删除，
        既防误删又避免回收站无限膨胀。
        """
        cutoff = time.time() - keep_days * 86400
        cutoff_str = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(cutoff))
        rows = self.conn.execute(
            "SELECT task_id FROM tasks WHERE deleted_at IS NOT NULL AND deleted_at < ?",
            (cutoff_str,),
        ).fetchall()
        ids = [r[0] for r in rows]
        if not ids:
            return 0
        outputs_dir = Path(self.db_path).parent.parent / "outputs"
        self._delete_task_files(ids, outputs_dir)
        placeholders = ",".join("?" * len(ids))
        cur = self.conn.execute(f"DELETE FROM tasks WHERE task_id IN ({placeholders})", ids)
        self.conn.commit()
        return cur.rowcount

    def aggregate_cost_by_engine(self) -> list[dict[str, Any]]:
        """按引擎聚合成本相关指标（FinOps 报表数据源）。

        Returns:
            [{"engine","tasks","completed","failed","total_processing_s","output_count"}, ...]
        """
        rows = self.conn.execute(
            "SELECT engine, COUNT(*) AS tasks, "
            "SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed, "
            "SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed, "
            "COALESCE(SUM(processing_time_s),0) AS total_processing_s, "
            "COALESCE(SUM(output_count),0) AS output_count "
            "FROM tasks GROUP BY engine"
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        """关闭数据库连接（幂等，且与所有数据库调用互斥）。

        必须在**没有任何工作线程还会写库之后**调用（见
        ``TaskQueue.stop()`` 的在飞任务排空）。护栏只能把误用变成明确异常，
        不能替代正确的关闭顺序。
        """
        with self._lock:
            guard = self._guard
            self._conn = None
            self._guard = None
            if guard is not None:
                guard.close()

    # ── 备份 / 灾难恢复（数据治理评估报告 §4.9）──────────────
    def backup(self, dest: str | Path | None = None, keep: int = 7) -> Path:
        """对数据库做一致性备份（SQLite VACUUM INTO）。

        Args:
            dest: 备份文件路径；默认 ``<db_dir>/<stem>.backup.<ts>.db``。
            keep: 保留最近 N 个备份，超出则删除最旧的（按文件名时间排序）。

        Returns:
            实际备份文件路径。

        Raises:
            sqlite3.OperationalError: VACUUM INTO 失败（如目标被占用）。
        """
        conn = self.conn
        if dest is None:
            ts = int(time.time())
            dest = self.db_path.parent / f"{self.db_path.stem}.backup.{ts}.db"
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        # VACUUM INTO 不接受参数绑定，路径为项目内部受控值（非用户输入）
        conn.execute(f"VACUUM INTO '{dest.as_posix()}'")
        # 清理旧备份，仅保留最近 keep 个
        try:
            backups = sorted(
                self.db_path.parent.glob(f"{self.db_path.stem}.backup.*.db"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for old in backups[keep:]:
                old.unlink(missing_ok=True)
        except Exception as e:  # noqa: BLE001 - 备份清理失败不阻断主流程
            logger.warning("Old backup cleanup skipped: %s", e)
        logger.info("HistoryDB backup -> %s", dest)
        return dest
