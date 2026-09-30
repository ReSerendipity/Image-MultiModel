"""
tests/test_edit_pipeline.py — 编辑链路（P1 Qwen-Image 2.1 Edit）的 CI 可测部分

真 GPU 端到端在 `tests/test_edit_e2e_gpu.py`（``slow`` 标记，CI 不跑）。
本文件用 **FakeEngine** 覆盖编辑链路的**装配与调度**：

- ``edit_mode=True`` 时 task mode=edit、参考图进入 GenerationConfig.init_image
- ``edit_mode=True`` 但缺参考图 / 引擎不支持 edit → 422（不得静默降级成文生图）
- worker 按 ``init_image`` 分发到 ``engine.infer_edit``
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.integrated_app.app_server import create_app
from app.integrated_app.config import get_config


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # 312/CI 环境无 CLIP 包：带参考图的请求会走 fail-closed 被拦。
    # 本文件验证的是**编辑链路的装配与调度**（不是内容过滤，那在 test_content_filter.py），
    # 故把图检降级为放行；真实部署仍保持 fail-closed。
    import app.integrated_app.security.content_filter as cf

    monkeypatch.setattr(cf, "filter_image_generation", lambda prompt, image_path, fail_closed: (True, ""))
    with TestClient(create_app()) as c:
        csrf = c.get("/api/health").headers.get("X-CSRF-Token", "")
        if csrf:
            c.headers["X-CSRF-Token"] = csrf
        yield c


def _make_reference() -> str:
    """在 outputs/ 白名单内造一张参考图，返回项目根相对路径。"""
    from PIL import Image

    cfg = get_config()
    outputs_root = Path(cfg.project_root) / cfg.output.base_dir
    rel_dir = outputs_root / "_edit_pipeline_test"
    rel_dir.mkdir(parents=True, exist_ok=True)
    fp = rel_dir / "ref.png"
    Image.new("RGB", (256, 256), (120, 160, 220)).save(fp)
    return f"outputs/{fp.relative_to(outputs_root).as_posix()}"


def _submit_edit(client: TestClient, **overrides):
    cfg = get_config()
    payload = {
        "positive_prompt": "把主体改成鲜红色，其余保持不变",
        "engine_name": "qwen_image_edit_native",
        "edit_mode": True,
        "reference_image_path": _make_reference(),
        "edit_resolution": 512,
        "steps": 4,
        "cfg": 1.0,
        "seed": 7,
        "batch_size": 1,
        "width": 512,
        "height": 512,
        **overrides,
    }
    return client.post("/api/generate", json=payload)


def _wait_terminal(client: TestClient, task_id: str, timeout_s: float = 15.0) -> dict:
    deadline = time.time() + timeout_s
    detail: dict = {}
    while time.time() < deadline:
        detail = client.get(f"/api/tasks/{task_id}").json()
        if detail.get("status") in ("completed", "failed", "cancelled"):
            return detail
        time.sleep(0.05)
    return detail


def test_edit_mode_queues_edit_task_and_completes(client: TestClient) -> None:
    """FakeEngine 下走完整编辑链路：入队 → worker 分发 infer_edit → 完成。"""
    resp = _submit_edit(client)
    assert resp.status_code == 200, resp.text[:300]
    task_id = resp.json()["task_id"]

    detail = _wait_terminal(client, task_id)
    assert detail.get("status") == "completed", detail
    assert detail.get("mode") == "edit", detail
    outputs = [o["path"] for o in (detail.get("outputs") or [])]
    assert outputs, detail


def test_edit_mode_without_reference_is_422(client: TestClient) -> None:
    """缺参考图必须 422 —— 静默降级成文生图会让用户拿到"没参考"的结果。"""
    resp = _submit_edit(client, reference_image_path="")
    assert resp.status_code == 422, resp.text[:300]


def test_edit_mode_on_engine_without_edit_is_422(client: TestClient) -> None:
    """引擎不支持 edit 必须显式拒绝，而不是悄悄当文生图跑。"""
    resp = _submit_edit(client, engine_name="z_image_turbo_native")
    assert resp.status_code == 422, resp.text[:300]
    assert "does not support image editing" in resp.text


def test_generation_config_carries_init_image(client: TestClient) -> None:
    """init_image 必须进入 GenerationConfig（worker 据此分发）。"""
    cfg = get_config()
    ref = _make_reference()
    resp = _submit_edit(client, reference_image_path=ref)
    assert resp.status_code == 200, resp.text[:300]
    task_id = resp.json()["task_id"]
    detail = client.get(f"/api/tasks/{task_id}").json()
    gen_cfg = detail.get("generation_config") or {}
    assert gen_cfg.get("init_image", "").endswith("ref.png"), gen_cfg.get("init_image")
    _ = cfg
