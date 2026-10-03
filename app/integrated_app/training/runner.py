"""training/runner.py — 训练编排薄层的核心（提交训练 / 回写状态 / 取消 / 读日志）。

一次提交的完整链路：:

    TrainJobSpec.validate()  →  落 job.yaml  →  Popen(AI-Toolkit run.py <job.yaml>)
      →  stdout 逐行落 <job_dir>/stdout.log（后台泵线程）
      →  状态回写 <training_root>/jobs/<job_id>.json（原子替换）
      →  进度回读 <training_folder>/<name>/loss_log.db（只读 sqlite）

关于"轻前端"：本薄层只负责编排与状态回写，**不出训练 UI**。UI 面由 AI-Toolkit
自带前端承担（``run_windows.bat`` → ``python -m manager launch``，仓库内 ``ui/``
为 Next.js 前端），两者通过本模块产出的 job 文件与 loss 库互通。

关于解释器与工作区：AI-Toolkit 有独立依赖（torch/peft/optimum 等），
不由本仓 Python 承担 → 必须显式给两个环境变量：

- ``AITK_ROOT``：AI-Toolkit 仓库根（需含 ``run.py`` 与 ``toolkit/``）；
- ``AITK_PYTHON``：跑训练的解释器（否则用 ``sys.executable`` 会缺依赖）。

（**不内置本机绝对路径**：``scripts/check_no_hardcoded_paths.py`` 在 pre-commit 会拒收。）
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from . import handoff, progress, store
from .spec import TrainJobSpec

logger = logging.getLogger(__name__)

#: 训练根目录（相对项目根）：产物、job、日志、状态都在这里，data/ 已在 .gitignore
TRAINING_SUBDIR = "training"

#: 单个训练任务默认上限：LoRA 训练动辄几十步，兜底 24 小时
DEFAULT_TIMEOUT_S = 24 * 3600


class TrainingUnavailable(RuntimeError):
    """训练后端未就绪（AI-Toolkit 工作区/解释器缺失或未配置）。"""


class _JobProcess:
    """后台泵：把子进程 stdout 逐行落盘，并在进程退出时收尾状态。"""

    def __init__(self, job_id: str, proc: subprocess.Popen, log_path: Path, runner: TrainingRunner) -> None:
        self.job_id = job_id
        self.proc = proc
        self.log_path = log_path
        self.runner = runner
        self.stop = threading.Event()
        self._thread = threading.Thread(target=self._pump, name=f"train-pump-{job_id}", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _pump(self) -> None:  # noqa: C901 - 泵函数分支都是必要的状态迁移
        with self.log_path.open("a", encoding="utf-8", errors="replace") as fh:
            try:
                for line in self.proc.stdout or ():
                    fh.write(line if line.endswith("\n") else f"{line}\n")
                    fh.flush()
            except (ValueError, OSError):  # 子进程关闭管道
                pass
            self.proc.wait()
            exit_code = int(self.proc.returncode or 0)

        # 进程已退出：不再依赖 loss 库（可能还没 flush），用退出码定终态
        status = store.STATUS_COMPLETED if exit_code == 0 else store.STATUS_FAILED
        record = self.runner.load(self.job_id) or {}  # 终态以最新记录为底色（含取消态）
        # 先把进度刷到最新：终态记录也要带上最后一步 step/loss，
        # 否则接口在训练结束后回的是"提交时那条空 progress"（真跑实证抓到：
        # 跑到 completed 后 step 仍为 None，尽管 loss_log.db 里已有第 2 步）。
        self.runner._refresh_progress(record)
        record.update(
            {
                "status": status,
                "exit_code": exit_code,
                "finished_at": time.time(),
                "error": "" if exit_code == 0 else f"AI-Toolkit 退出码 {exit_code}",
            }
        )
        self.runner.save(record)
        self.runner._forget(self.job_id)
        logger.info("训练任务 %s 结束: status=%s exit_code=%s", self.job_id, status, exit_code)


class TrainingRunner:
    """训练编排器（进程内单例由调用方持有，默认不随 app 生命周期自动创建）。"""

    def __init__(
        self,
        project_root: str | Path,
        config: Any | None = None,
        aitk_root: str | Path | None = None,
        python_executable: str | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self.project_root = Path(project_root)
        self.config = config
        self.timeout_s = float(timeout_s)
        self.root = self.project_root / "data" / TRAINING_SUBDIR
        self.store = store.TrainingStore(self.root)
        self.store.ensure_ready()
        # 同一时刻只允许一个训练任务（GPU 独占，避免与推理队列互抢显存）
        self._lock = threading.Lock()
        self._procs: dict[str, subprocess.Popen] = {}

    # ── 环境探测 ──────────────────────────────────────────
    def describe_environment(self) -> dict[str, Any]:
        """训练后端是否就绪（供接口给出可操作的原因，而不是一句"服务不可用"）。"""
        aitk_root = Path(str(aitk_root_env() or ""))
        ok = aitk_root.is_dir() and (aitk_root / "run.py").is_file() and (aitk_root / "toolkit").is_dir()
        python = python_env() or sys.executable
        return {
            "available": bool(ok),
            "aitk_root": str(aitk_root) if aitk_root else "",
            "python": python,
            "training_root": str(self.root),
            "reason": "" if ok else "未配置 AITK_ROOT（指向含 run.py + toolkit/ 的 AI-Toolkit 仓库根）",
        }

    def _require_backend(self) -> tuple[Path, str]:
        aitk_root = Path(str(aitk_root_env() or ""))
        if not (aitk_root.is_dir() and (aitk_root / "run.py").is_file()):
            raise TrainingUnavailable(
                "未指定 AI-Toolkit 工作区：请设置环境变量 AITK_ROOT 指向含 run.py 的 AI-Toolkit 仓库根"
            )
        python = python_env() or sys.executable
        return aitk_root, python

    # ── 提交 ──────────────────────────────────────────────
    def submit(self, spec: TrainJobSpec) -> dict[str, Any]:
        """校验 → 落 job.yaml → 起训练子进程（返回后台记录，不等训练结束）。"""
        spec.validate()
        aitk_root, python = self._require_backend()

        with self._lock:
            running = [r.get("job_id") for r in self.store.list_all() if r.get("status") == store.STATUS_RUNNING]
            if running:
                raise RuntimeError(f"已有训练任务在运行中: {running[0]}（GPU 串行，同时只允许一个）")

            job_id = uuid.uuid4().hex[:12]
            job_dir = self.root / job_id
            job_dir.mkdir(parents=True, exist_ok=True)
            job_yaml = job_dir / "job.yaml"
            log_path = job_dir / "stdout.log"
            training_folder = str(job_dir)

            record = {
                "job_id": job_id,
                "name": spec.name,
                "status": store.STATUS_PENDING,
                "created_at": time.time(),
                "started_at": time.time(),
                "finished_at": 0.0,
                "exit_code": None,
                "error": "",
                "steps": spec.steps,
                "job_yaml": str(job_yaml),
                "log_path": str(log_path),
                # 记录里只存 training_folder（与 AI-Toolkit 的同名键同义：产出落在
                # <training_folder>/<job name>/）。**不要再预拼 save_root**：
                # handoff.final_lora_path / discover_artifacts 都是
                # 「training_folder + name」语义，预拼会拼出两层 job 名导致
                # 永远找不到产物（测试 test_train_routes.py 当场抓到）。
                # save_root 现场用 handoff.save_root() 推导。
                "training_folder": training_folder,
                "aitk_root": str(aitk_root),
                "python": python,
                "spec": spec.to_dict(),
                # 进度字段：由 status() 每次回读 loss 库回填
                "progress": {"step": None, "latest": {}, "history": []},
            }
            self.store.save(record)
            job_yaml.write_text(spec.render_yaml(training_folder), encoding="utf-8")

            env = dict(os.environ)
            # AI-Toolkit 会打印含中文/符号的中文注释，Windows 控制台默认 cp936 会抛异常
            env["PYTHONIOENCODING"] = "utf-8"
            proc = subprocess.Popen(  # noqa: S603 - 参数仅为显式指定的解释器与 run.py
                [python, str(aitk_root / "run.py"), str(job_yaml)],
                cwd=str(aitk_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            self._procs[job_id] = proc

        record["status"] = store.STATUS_RUNNING
        pump = _JobProcess(job_id, proc, log_path, self)
        self.store.save(record)
        pump.start()
        logger.info("训练任务已提交: job_id=%s name=%s steps=%s（aitk=%s）", job_id, spec.name, spec.steps, aitk_root)
        return self.load(job_id) or record

    # ── 查询 ──────────────────────────────────────────────
    def load(self, job_id: str) -> dict[str, Any] | None:
        return self.store.load(job_id)

    def status(self, job_id: str) -> dict[str, Any] | None:
        """状态 + 进度（合并 store 记录与 loss 库；终态不再刷新进度）。"""
        record = self.store.load(job_id)
        if record is None:
            return None

        rec = dict(record)
        if not store.is_terminal(str(rec.get("status") or "")):
            self._refresh_progress(rec)
        return rec

    def _refresh_progress(self, rec: dict[str, Any]) -> None:
        """回读 loss 库刷新 progress；超时兜底判 failed。"""
        db = progress.loss_log_path(self._save_root_of(rec))
        data = progress.read_loss_log(db)
        step = data.get("step")
        total = int(rec.get("steps") or 0)
        rec["progress"] = {
            "present": bool(data.get("present")),
            "step": step,
            "total_steps": total,
            "percent": round(min(100.0, 100.0 * (step or 0) / total), 2) if total else 0.0,
            "latest": data.get("latest") or {},
            "history": data.get("history") or [],
        }

        started = float(rec.get("started_at") or 0.0)
        if self.timeout_s > 0 and started and time.time() - started > self.timeout_s:
            rec["status"] = store.STATUS_FAILED
            rec["error"] = f"超过任务上限 {self.timeout_s}s，按超时判定失败（请查 stdout.log）"
            self.save(rec)

    def logs(self, job_id: str, lines: int = 100) -> list[str]:
        record = self.store.load(job_id)
        path = Path(str((record or {}).get("log_path") or ""))
        return progress.tail_lines(path, lines=lines)

    def list_jobs(self) -> list[dict[str, Any]]:
        return self.store.list_all()

    def artifacts(self, job_id: str) -> list[dict[str, Any]]:
        record = self.store.load(job_id)
        if not record:
            return []
        name = str(record.get("name") or "")
        if not name:
            return []
        return handoff.discover_artifacts(record.get("training_folder") or "", name)

    def _save_root_of(self, rec: dict[str, Any]) -> Path:
        """由「training_folder + name」推导 AI-Toolkit 的存档目录。"""
        return handoff.save_root(rec.get("training_folder") or "", str(rec.get("name") or ""))

    # ── 取消 / 清理 ───────────────────────────────────────
    def cancel(self, job_id: str) -> bool:
        """请求终止训练（Windows 下 ``terminate()`` 即 TerminateProcess）。"""
        record = self.store.load(job_id)
        if record is None:
            return False
        if store.is_terminal(str(record.get("status") or "")):
            return False
        proc = self._procs.get(job_id)
        self._refresh_progress(record)  # 取消时也带上此刻真实进度，别回一个空 progress
        record["status"] = store.STATUS_CANCELLED
        record["finished_at"] = time.time()
        record["error"] = (record.get("error") or "") + " 已请求取消"
        self.save(record)
        if proc is not None:
            try:
                proc.terminate()
            except OSError as e:
                logger.warning("取消训练进程失败: %s (%s)", job_id, e)
            self._forget(job_id)
        return True

    def forget(self, job_id: str) -> None:
        """清掉进程句柄（收尾后调用，避免句柄表无限增长）。"""
        self._forget(job_id)

    # ── 移交 ──────────────────────────────────────────────
    def handoff_plan(self, job_id: str) -> dict[str, Any] | None:
        record = self.store.load(job_id)
        if not record:
            return None
        lora = handoff.final_lora_path(record.get("training_folder") or "", str(record.get("name") or ""))
        if lora is None:
            return {"found": False, "reason": "终稿 LoRA 尚未产出（训练可能仍在进行）"}
        plan = handoff.plan_handoff(self.config, self.project_root, lora)
        plan["found"] = True
        plan["job_id"] = job_id
        return plan

    def handoff_copy(self, job_id: str, dry_run: bool = False) -> dict[str, Any] | None:
        record = self.store.load(job_id)
        if not record:
            return None
        lora = handoff.final_lora_path(record.get("training_folder") or "", str(record.get("name") or ""))
        if lora is None:
            return {"found": False, "reason": "终稿 LoRA 尚未产出（训练可能仍在进行）"}
        result = handoff.copy_into_lora_dir(self.config, self.project_root, lora, dry_run=dry_run)
        result["found"] = True
        result["job_id"] = job_id
        return result

    # ── 内部 ──────────────────────────────────────────────
    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        return store.save_record(self.store, record)

    def _forget(self, job_id: str) -> None:
        with self._lock:
            self._procs.pop(job_id, None)


def aitk_root_env() -> str | None:
    """AI-Toolkit 仓库根（环境变量 ``AITK_ROOT``）。"""
    return os.environ.get("AITK_ROOT") or None


def python_env() -> str | None:
    """训练解释器（环境变量 ``AITK_PYTHON``）；未设置时调用方回退 ``sys.executable``。"""
    return os.environ.get("AITK_PYTHON") or None
