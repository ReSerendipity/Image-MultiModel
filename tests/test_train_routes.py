"""tests/test_train_routes.py — 训练编排 HTTP 面（全打桩，不启动训练、不碰 GPU）

打桩策略：注入 ``app.state.training_runner = FakeRunner()``，
这样路由的错误映射（400/404/409/503）与状态合并都能被测到，
又不依赖本机 AI-Toolkit 工作区。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.integrated_app import training
from app.integrated_app import training as training_pkg
from app.integrated_app.app_server import create_app
from app.integrated_app.training.handoff import copy_into_lora_dir
from app.integrated_app.training.runner import TrainingUnavailable
from app.integrated_app.training.spec import TrainSpecError


class FakeRunner:
    """只实现路由用到的接口；产物目录是真的（tmp_path），便于验证产物发现。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.records: dict[str, dict] = {}
        self.cancel_calls: list[str] = []
        self.next_id = 0
        self._errors: dict[str, Exception | None] = {}
        self._handoff_calls: list[bool] = []

    # ── 环境 ──
    def describe_environment(self) -> dict:
        return {"available": True, "aitk_root": "/fake/aitk", "python": "py", "training_root": str(self.root)}

    # ── 任务 ──
    def submit(self, spec) -> dict:
        if self._errors.get("submit"):
            raise self._errors["submit"]
        # 与真 runner 同位置校验：坏参数在进进程前就被挡掉
        spec.validate()
        self.next_id += 1
        job_id = f"job-{self.next_id:03d}"
        save_root = self.root / job_id / spec.name
        save_root.mkdir(parents=True, exist_ok=True)
        (save_root / f"{spec.name}.safetensors").write_bytes(b"\x00" * 2048)  # 终稿
        (save_root / f"{spec.name}_000000002.safetensors").write_bytes(b"\x00" * 2048)  # 中间档
        (save_root / "samples").mkdir(exist_ok=True)
        (save_root / "samples" / "sample_step002.jpg").write_bytes(b"\xff\xd8\xff")
        rec = {
            "job_id": job_id,
            "name": spec.name,
            "status": "running",
            "created_at": 1.0,
            "started_at": 2.0,
            "finished_at": 0.0,
            "steps": spec.steps,
            # 与真 runner 同语义：记录里只放 training_folder，存档目录现场推导
            "training_folder": str(save_root.parent),
            "log_path": str(save_root.parent / "stdout.log"),
            "spec": spec.to_dict(),
        }
        self.records[job_id] = rec
        return rec

    def load(self, job_id: str) -> dict | None:
        return self.records.get(job_id)

    def status(self, job_id: str) -> dict | None:
        rec = self.records.get(job_id)
        if rec is None:
            return None
        merged = dict(rec)
        merged.setdefault("progress", {"step": 2, "total_steps": rec["steps"], "percent": 50.0, "latest": {}})
        return merged

    def list_jobs(self) -> list[dict]:
        return list(self.records.values())

    def logs(self, job_id: str, lines: int = 100) -> list[str]:
        rec = self.records.get(job_id)
        if rec is None:
            return []
        return ["step 1 loss 0.4", "step 2 loss 0.38"][-lines:]

    def artifacts(self, job_id: str) -> list[dict]:
        rec = self.records.get(job_id)
        if rec is None:
            return []
        return training.handoff.discover_artifacts(rec["training_folder"], rec["name"])

    def cancel(self, job_id: str) -> bool:
        self.cancel_calls.append(job_id)
        rec = self.records.get(job_id)
        if rec is None or rec["status"] != "running":
            return False
        rec["status"] = "cancelled"
        return True

    def handoff_plan(self, job_id: str) -> dict | None:
        rec = self.records.get(job_id)
        if rec is None:
            return None
        lora = training.handoff.final_lora_path(rec["training_folder"], rec["name"])
        if lora is None:
            return {"found": False, "reason": "终稿 LoRA 尚未产出"}
        plan = training.handoff.plan_handoff(None, Path(self.root), lora)
        plan.update({"found": True, "job_id": job_id})
        return plan

    def handoff_copy(self, job_id: str, dry_run: bool = False) -> dict | None:
        """与真 runner 同链路：dry_run 与否都走 handoff.copy_into_lora_dir（可被 spy 观测）。"""
        self._handoff_calls.append(bool(dry_run))
        rec = self.records.get(job_id)
        if rec is None:
            return None
        lora = training.handoff.final_lora_path(rec["training_folder"], rec["name"])
        if lora is None:
            return {"found": False, "reason": "终稿 LoRA 尚未产出"}
        result = training.handoff.copy_into_lora_dir(None, Path(self.root), lora, dry_run=bool(dry_run))
        result["found"] = True
        result["job_id"] = job_id
        return result


def _csrf_post(client: TestClient, url: str, payload: dict) -> Any:
    """CSRF 默认开启：POST 前先取 /api/health 下发的一次性 token（同 agent 路由测试）。"""
    token = client.get("/api/health").headers.get("X-CSRF-Token", "")
    return client.post(url, json=payload, headers={"X-CSRF-Token": token})


def _submit(client: TestClient, tmp_path: Path, **over: object) -> Any:
    return _csrf_post(client, "/api/train/jobs", _payload(tmp_path, **over))


def _payload(tmp_path: Path, **over: object) -> dict:
    model = tmp_path / "model.safetensors"
    model.write_bytes(b"\x00")
    extras = tmp_path / "extras"
    extras.mkdir(exist_ok=True)
    ds = tmp_path / "ds"
    ds.mkdir(exist_ok=True)
    return {
        "name": "probe_lora",
        "model_path": str(model),
        "extras_path": str(extras),
        "dataset_folder": str(ds),
        "steps": 4,
        "sample_prompts": ["a cat on a table"],
        **over,
    }


def _client_with(runner: FakeRunner) -> tuple[TestClient, FakeRunner]:
    app = create_app()
    app.state.training_runner = runner
    return TestClient(app), runner


def test_status_endpoint_reports_backend(tmp_path):
    runner = FakeRunner(tmp_path / "training")
    with _client_with(runner)[0] as c:
        resp = c.get("/api/train/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["total_jobs"] == 0


def test_submit_and_query(tmp_path):
    runner = FakeRunner(tmp_path / "training")
    client, _ = _client_with(runner)
    with client as c:
        resp = _submit(c, tmp_path)
        assert resp.status_code == 200, resp.text
        job_id = resp.json()["job_id"]
        status = c.get(f"/api/train/jobs/{job_id}")
    assert status.status_code == 200
    assert status.json()["status"] == "running"
    assert status.json()["progress"]["percent"] == 50.0


def test_submit_rejects_bad_spec(tmp_path):
    runner = FakeRunner(tmp_path / "training")
    client, _ = _client_with(runner)
    with client as c:
        resp = _submit(c, tmp_path, **{"name": "bad name"})
        assert resp.status_code == 400
        assert "name 非法" in resp.json()["error"]["message"]


@pytest.mark.parametrize(
    ("kind", "status_code"),
    [("unavailable", 503), ("invalid", 400), ("conflict", 409)],
)
def test_error_mapping(tmp_path, kind, status_code):
    """路由把训练层的异常翻译成统一错误封装（GOTCHAS #28 的 {success,error} 形态）。"""
    runner = FakeRunner(tmp_path / "training")
    runner._errors = {
        "submit": {
            "unavailable": TrainingUnavailable("AITK_ROOT 未配置"),
            "invalid": TrainSpecError("resolution 必须是 16 的倍数"),
            "conflict": RuntimeError("已有训练任务在运行中"),
        }[kind]
    }
    with _client_with(runner)[0] as c:
        resp = _submit(c, tmp_path)
    assert resp.status_code == status_code
    assert resp.json()["success"] is False
    assert "error" in resp.json()


def test_job_not_found(tmp_path):
    runner = FakeRunner(tmp_path / "training")
    with _client_with(runner)[0] as c:
        assert c.get("/api/train/jobs/nope").status_code == 404
        assert c.get("/api/train/jobs/nope/logs").status_code == 404
        assert c.get("/api/train/jobs/nope/artifacts").status_code == 404


def test_logs_and_artifacts(tmp_path):
    runner = FakeRunner(tmp_path / "training")
    client, _ = _client_with(runner)
    with client as c:
        job_id = _submit(c, tmp_path).json()["job_id"]
        logs = c.get(f"/api/train/jobs/{job_id}/logs?tail=2").json()
        arts = c.get(f"/api/train/jobs/{job_id}/artifacts").json()
    assert logs["lines"] == ["step 1 loss 0.4", "step 2 loss 0.38"]
    kinds = {a["kind"] for a in arts["artifacts"]}
    assert {"lora", "sample"} <= kinds, arts
    # 中间档不算终稿，但应当被产物清单发现
    assert any("000000002" in a["name"] for a in arts["artifacts"])


def test_cancel_running_ok_but_terminal_is_409(tmp_path):
    runner = FakeRunner(tmp_path / "training")
    client, _ = _client_with(runner)
    with client as c:
        job_id = _submit(c, tmp_path).json()["job_id"]
        assert _csrf_post(c, f"/api/train/jobs/{job_id}/cancel", {}).status_code == 200
        assert runner.cancel_calls == [job_id]
        assert _csrf_post(c, f"/api/train/jobs/{job_id}/cancel", {}).status_code == 409


def test_handoff_plan_is_readonly(tmp_path):
    runner = FakeRunner(tmp_path / "training")
    with _client_with(runner)[0] as c:
        job_id = _submit(c, tmp_path).json()["job_id"]
        plan = c.get(f"/api/train/jobs/{job_id}/handoff").json()
        lora = c.get(f"/api/train/jobs/{job_id}/lora").json()
    assert plan["found"] is True
    assert plan["target_dir"].endswith("loras")
    assert lora["exists"] is True
    assert lora["lora_path"].endswith("probe_lora.safetensors")


def test_handoff_copy_dry_run_does_not_touch_disk(tmp_path, monkeypatch):
    runner = FakeRunner(tmp_path / "training")
    seen: list[bool] = []

    def spy(*args, **kwargs):
        seen.append(bool(kwargs.get("dry_run", False)))
        return {"copied": False, "found": True, "dry_run": bool(kwargs.get("dry_run", False)), "error": None}

    monkeypatch.setattr(training.handoff, "copy_into_lora_dir", spy)
    with _client_with(runner)[0] as c:
        job_id = _submit(c, tmp_path).json()["job_id"]
        preview = _csrf_post(c, f"/api/train/jobs/{job_id}/handoff?dry_run=true", {}).json()
        real = _csrf_post(c, f"/api/train/jobs/{job_id}/handoff", {}).json()
    assert seen == [True, False]
    assert preview["dry_run"] is True


def test_handoff_plan_when_artifact_missing(tmp_path):
    runner = FakeRunner(tmp_path / "training")
    client, _ = _client_with(runner)
    with client as c:
        job_id = _submit(c, tmp_path).json()["job_id"]
        runner.records[job_id]["training_folder"] = str(tmp_path / "empty")
        assert c.get(f"/api/train/jobs/{job_id}/handoff").status_code == 409
        assert c.get(f"/api/train/jobs/{job_id}/lora").status_code == 409


def test_copy_into_lora_dir_refuses_junction(tmp_path, monkeypatch):
    """禁区目录护栏：目标是 junction/symlink 时明确拒绝，不静默附到宿主目录。"""
    target = tmp_path / "loras"
    target.mkdir()
    monkeypatch.setattr(training.handoff, "lora_resource_dir", lambda *a, **k: target)
    src = tmp_path / "probe_lora.safetensors"
    src.write_bytes(b"\x00")
    # 让 target 变成 symlink（Windows 无权限时跳过）
    try:
        target.rename(tmp_path / "loras_real")
        (tmp_path / "loras_real").mkdir()
        (tmp_path / "loras_real" / "x").write_text("", encoding="utf-8")
        __import__("os").symlink(tmp_path / "loras_real", target)
    except OSError:  # pragma: no cover - 权限不足的环境
        pytest.skip("当前环境不支持创建符号链接")
    out = copy_into_lora_dir(None, tmp_path, src)
    assert out["copied"] is False
    assert "拒绝写入" in out["error"]


def test_dataset_validate_rejects_relative_folder(tmp_path):
    runner = FakeRunner(tmp_path / "training")
    with _client_with(runner)[0] as c:
        resp = c.get("/api/train/datasets/validate?folder=relative/ds")
    assert resp.status_code == 400


def test_dataset_validate_reports_problems(tmp_path):
    runner = FakeRunner(tmp_path / "training")
    ds = tmp_path / "ds"
    ds.mkdir()
    (ds / "a.png").write_bytes(b"\x89PNG")  # 缺 caption
    with _client_with(runner)[0] as c:
        body = c.get(f"/api/train/datasets/validate?folder={ds}").json()
    assert body["ok"] is False
    assert body["image_count"] == 1
    assert len(body["missing_caption"]) == 1


def test_dataset_validate_ok(tmp_path):
    runner = FakeRunner(tmp_path / "training")
    ds = tmp_path / "ds"
    ds.mkdir()
    (ds / "a.png").write_bytes(b"\x89PNG")
    (ds / "a.txt").write_text("cat", encoding="utf-8")
    with _client_with(runner)[0] as c:
        body = c.get(f"/api/train/datasets/validate?folder={ds}").json()
    assert body["ok"] is True
    assert body["paired_count"] == 1


def test_dataset_validate_check_resolution_reports_decode(tmp_path):
    runner = FakeRunner(tmp_path / "training")
    ds = tmp_path / "ds"
    ds.mkdir()
    from PIL import Image

    Image.new("RGB", (512, 512), (10, 20, 30)).save(ds / "good.png")
    (ds / "good.txt").write_text("cat", encoding="utf-8")
    (ds / "bad.png").write_bytes(b"\x89PNG")  # 损坏
    with _client_with(runner)[0] as c:
        body = c.get(f"/api/train/datasets/validate?folder={ds}&check_resolution=true").json()
    assert body["ok"] is False  # bad.png 损坏
    assert body["corrupt_images"] == ["bad.png"]
    assert body["image_sizes"]["good.png"] == [512, 512]


def test_dataset_validate_default_does_not_decode(tmp_path):
    runner = FakeRunner(tmp_path / "training")
    ds = tmp_path / "ds"
    ds.mkdir()
    (ds / "bad.png").write_bytes(b"\x89PNG")  # 损坏，但默认不解码
    (ds / "bad.txt").write_text("x", encoding="utf-8")  # 配对齐全
    with _client_with(runner)[0] as c:
        body = c.get(f"/api/train/datasets/validate?folder={ds}").json()
    assert body["corrupt_images"] == []  # 默认不解码
    assert body["ok"] is True


def _make_valid_dataset(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "a.png").write_bytes(b"\x89PNG")  # 默认 preflight 不解码，文件级校验通过即可
    (folder / "a.txt").write_text("cat", encoding="utf-8")


def _preflight_payload(tmp_path: Path, **over: object) -> dict:
    model = tmp_path / "model.safetensors"
    model.write_bytes(b"\x00")
    extras = tmp_path / "extras"
    extras.mkdir(exist_ok=True)
    ds = tmp_path / "ds"
    _make_valid_dataset(ds)
    return {
        "name": "preflight_lora",
        "model_path": str(model),
        "extras_path": str(extras),
        "dataset_folder": str(ds),
        "steps": 4,
        **over,
    }


def test_preflight_ok(tmp_path):
    runner = FakeRunner(tmp_path / "training")
    with _client_with(runner)[0] as c:
        resp = _csrf_post(c, "/api/train/jobs/preflight", _preflight_payload(tmp_path))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["spec_errors"] == []
    assert body["dataset"]["ok"] is True


def test_preflight_reports_dataset_problem(tmp_path):
    # 数据集缺 caption → spec 通过但 dataset 不 ok
    runner = FakeRunner(tmp_path / "training")
    payload = _preflight_payload(tmp_path)
    ds = tmp_path / "ds"
    (ds / "a.txt").unlink()  # 移除 caption，制造缺 caption
    with _client_with(runner)[0] as c:
        body = _csrf_post(c, "/api/train/jobs/preflight", payload).json()
    assert body["ok"] is False
    assert body["dataset"] is not None
    assert body["dataset"]["ok"] is False
    assert len(body["dataset"]["missing_caption"]) == 1


def test_preflight_reports_spec_error(tmp_path):
    # 坏 name → 规格错，且不再跑数据集校验（dataset 为 None）
    runner = FakeRunner(tmp_path / "training")
    payload = _preflight_payload(tmp_path, name="bad name")
    with _client_with(runner)[0] as c:
        body = _csrf_post(c, "/api/train/jobs/preflight", payload).json()
    assert body["ok"] is False
    assert body["spec_errors"]
    assert "name 非法" in body["spec_errors"][0]
    assert body["dataset"] is None


def test_training_package_exports():
    """__init__ 的公开面（避免重构时把入口悄悄改名）。"""
    assert hasattr(training_pkg, "TrainJobSpec")
    assert hasattr(training_pkg, "TrainingRunner")
    assert hasattr(training_pkg, "validate_dataset")
