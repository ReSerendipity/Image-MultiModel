"""tests/test_training_runner.py — 编排核心（提交 / 泵线程 / 状态回写 / 移交）

不打桩速度路径：store 是真的（tmp_path 下的 TrainingStore）、job.yaml 是真的落盘、
loss_log.db 按 AI-Toolkit 真实 schema 建；只有**子进程**用假 Popen 顶替，
这样能覆盖「进程退出 → 终态 + 最后一步进度」这条真跑实证抓出来的回归点。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import yaml

from app.integrated_app.training import handoff, store
from app.integrated_app.training.runner import TrainingRunner, TrainingUnavailable
from app.integrated_app.training.spec import TrainJobSpec

JOB_NAME = "runner_lora"


@pytest.fixture()
def runner(tmp_path: Path) -> TrainingRunner:
    return TrainingRunner(project_root=tmp_path, config=None)


@pytest.fixture()
def spec(tmp_path: Path) -> TrainJobSpec:
    model = tmp_path / "model.safetensors"
    model.write_bytes(b"\x00")
    for d in ("extras", "ds"):
        (tmp_path / d).mkdir()
    return TrainJobSpec(
        name=JOB_NAME,
        model_path=str(model),
        extras_path=str(tmp_path / "extras"),
        dataset_folder=str(tmp_path / "ds"),
        steps=2,
        sample_every=0,
    )


def _seed_loss_db(save_root: Path, rows: list[tuple[int, str, float]]) -> None:
    """按 AI-Toolkit 的真实 schema 建 loss_log.db（schema 见 toolkit/logging_aitk.py）。"""
    save_root.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(save_root / "loss_log.db") as con:
        con.execute("CREATE TABLE steps (step INTEGER PRIMARY KEY, wall_time REAL)")
        con.execute(
            "CREATE TABLE metrics (step INTEGER, key TEXT, value_real REAL, value_text TEXT, PRIMARY KEY(step,key))"
        )
        con.executemany("INSERT INTO metrics VALUES (?,?,?,NULL)", rows)
        con.execute("INSERT INTO steps VALUES (?,0)", (rows[-1][0],))


class _FakeProc:
    """只实现 _JobProcess 会碰的三个部位：stdout 迭代、wait()、returncode。"""

    def __init__(self, lines: list[str], returncode: int = 0) -> None:
        self.stdout = iter(lines)
        self.returncode = returncode
        self.terminated = False

    def wait(self) -> int:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True


# ── 环境探测 ──────────────────────────────────────────────
def test_describe_environment_without_aitk_root(runner, monkeypatch):
    monkeypatch.delenv("AITK_ROOT", raising=False)
    env = runner.describe_environment()
    assert env["available"] is False
    assert "AITK_ROOT" in env["reason"]


def test_describe_environment_ok(runner, monkeypatch, tmp_path):
    aitk = tmp_path / "aitk"
    (aitk / "toolkit").mkdir(parents=True)
    (aitk / "run.py").write_text("", encoding="utf-8")
    monkeypatch.setenv("AITK_ROOT", str(aitk))
    env = runner.describe_environment()
    assert env["available"] is True
    assert env["aitk_root"] == str(aitk)


def test_submit_requires_backend(runner, spec, monkeypatch):
    monkeypatch.delenv("AITK_ROOT", raising=False)
    with pytest.raises(TrainingUnavailable):
        runner.submit(spec)


# ── 提交落盘 ──────────────────────────────────────────────
def _fake_backend(runner, tmp_path, monkeypatch) -> None:
    """把「后端就绪」与「起子进程」两件事都换成确定性的假货，别的全留真的。"""
    aitk = tmp_path / "aitk"
    (aitk / "toolkit").mkdir(parents=True)
    (aitk / "run.py").write_text("", encoding="utf-8")
    monkeypatch.setenv("AITK_ROOT", str(aitk))
    monkeypatch.setenv("AITK_PYTHON", str(tmp_path / "py.exe"))

    import subprocess

    class _NoopProc(_FakeProc):
        def __init__(self, *args, **kwargs) -> None:  # 测试里不真的起进程：stdout 立刻 EOF
            super().__init__([])

    monkeypatch.setattr(subprocess, "Popen", _NoopProc)
    runner._require_backend = lambda: (aitk, str(tmp_path / "py.exe"))  # type: ignore[method-assign]


def test_submit_writes_job_yaml_and_record(runner, spec, tmp_path, monkeypatch):
    _fake_backend(runner, tmp_path, monkeypatch)
    rec = runner.submit(spec)
    job_id = str(rec["job_id"])

    # job.yaml 真的落在 <data>/training/<job_id>/
    assert Path(rec["job_yaml"]).parent == runner.root / job_id
    cfg = yaml.safe_load(Path(rec["job_yaml"]).read_text(encoding="utf-8"))
    proc = cfg["config"]["process"][0]
    assert proc["training_folder"] == str(runner.root / job_id)
    # 进度回写的开关必须开着，否则 loss_log.db 不会出现
    assert proc["logging"]["use_ui_logger"] is True

    stored = runner.load(job_id)
    assert stored is not None
    # 记录里只放 training_folder，存档目录现场推导（回归：预拼 save_root 会拼成两层）
    assert "save_root" not in stored
    assert stored["training_folder"] == str(runner.root / job_id)
    assert handoff.save_root(stored["training_folder"], stored["name"]) == runner.root / job_id / JOB_NAME


def test_submit_is_serialized_on_gpu(runner, spec, tmp_path, monkeypatch):
    """同一时刻只允许一个训练（GPU 独占）；已有 running 记录时提交要被挡。"""
    _fake_backend(runner, tmp_path, monkeypatch)
    runner.store.save(
        {
            "job_id": "other",
            "name": "other",
            "status": store.STATUS_RUNNING,
            "created_at": 1.0,
            "started_at": 1.0,
            "finished_at": 0.0,
            "steps": 1,
            "training_folder": str(runner.root / "other"),
            "log_path": "",
            "progress": {},
        }
    )
    with pytest.raises(RuntimeError, match="已有训练任务在运行中"):
        runner.submit(spec)


def test_status_refreshes_progress_from_loss_db(runner, spec, tmp_path, monkeypatch):
    """非终态的 status() 会回读 loss 库，把 percent / latest / history 补齐。"""
    _fake_backend(runner, tmp_path, monkeypatch)
    job_id = str(runner.submit(spec)["job_id"])
    seed_root = runner.root / job_id / JOB_NAME
    _seed_loss_db(seed_root, [(1, "loss/loss", 0.47), (2, "loss/loss", 0.42), (3, "loss/loss", 0.39)])

    rec = runner.store.load(job_id)
    rec["status"] = store.STATUS_RUNNING
    runner.store.save(rec)

    out = runner.status(job_id)
    assert out["progress"]["step"] == 3
    assert out["progress"]["total_steps"] == 2
    assert out["progress"]["percent"] == 100.0  # 3/2 截断到 100（宁可饱满也不说谎报进度）
    assert out["progress"]["latest"]["loss/loss"] == 0.39
    assert [h["step"] for h in out["progress"]["history"]] == [1, 2, 3]
    # 非终态的轮询不会污染状态
    assert runner.load(job_id)["status"] == store.STATUS_RUNNING


# ── 泵：进程退出后的终态与进度 ─────────────────────────────
def test_pump_sets_terminal_status_and_persists_progress(runner, spec, tmp_path, monkeypatch):
    """回归真跑实证：训练结束后接口回的是「提交时的空 progress」，step 恒为 None。"""
    _fake_backend(runner, tmp_path, monkeypatch)
    rec = runner.submit(spec)
    job_id = str(rec["job_id"])

    # 训练跑到了第 2 步，loss 库是真的
    seed_root = runner.root / job_id / JOB_NAME
    _seed_loss_db(seed_root, [(1, "loss/loss", 0.47), (2, "loss/loss", 0.42)])

    log_path = runner.root / job_id / "stdout.log"
    log_path.write_text("pre-existing\n", encoding="utf-8")  # 泵是追加写，不是覆盖
    import app.integrated_app.training.runner as runner_mod

    proc = _FakeProc(["step 1\n", "step 2\n"])
    pump = runner_mod._JobProcess(job_id, proc, log_path, runner)  # type: ignore[arg-type]
    pump._pump()  # 不走线程，直接跑完，保证确定性

    after = runner.load(job_id)
    assert after is not None
    assert after["status"] == store.STATUS_COMPLETED
    assert after["exit_code"] == 0
    # 关键：终态记录里要带上最后一步，而不是提交时的空 progress
    assert after["progress"]["step"] == 2
    assert after["progress"]["percent"] == 100.0
    assert after["progress"]["latest"]["loss/loss"] == 0.42
    # stdout 泵**追加**进日志文件（重跑同一 job 不会把旧日志抹掉）
    assert runner.logs(job_id, lines=5) == ["pre-existing", "step 1", "step 2"]


def test_pump_marks_failed_on_nonzero_exit(runner, spec, tmp_path, monkeypatch):
    _fake_backend(runner, tmp_path, monkeypatch)
    job_id = str(runner.submit(spec)["job_id"])
    log_path = runner.root / job_id / "stdout.log"
    log_path.write_text("", encoding="utf-8")
    import app.integrated_app.training.runner as runner_mod

    pump = runner_mod._JobProcess(job_id, _FakeProc([], returncode=3), log_path, runner)  # type: ignore[arg-type]
    pump._pump()
    after = runner.load(job_id)
    assert after["status"] == store.STATUS_FAILED
    assert after["exit_code"] == 3
    assert "退出码 3" in after["error"]


# ── 取消 ──────────────────────────────────────────────────
def test_cancel_writes_terminal_state(runner, spec, tmp_path, monkeypatch):
    _fake_backend(runner, tmp_path, monkeypatch)
    job_id = str(runner.submit(spec)["job_id"])
    assert runner.cancel(job_id) is True
    assert runner.load(job_id)["status"] == store.STATUS_CANCELLED
    # 终态不能再取消
    assert runner.cancel(job_id) is False


def test_cancel_missing_job_is_false(runner):
    assert runner.cancel("nope") is False
