"""
tests/observability/test_overload_routes.py — P1-8 路由层过载接线集成测试

验证 generate_routes 在分级过载决策下正确返回：
- 95% → 429 + Retry-After 头 + queue_rejected_total{reason="queue_95"} 增长；
- 队列满（100%）→ 503；
- 正常水位 → 200 并成功入队。

通过 monkeypatch evaluate_overload 冻结决策，避免依赖真实队列填充竞态。
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.integrated_app.app_server import create_app
from app.integrated_app.observability.alerts import reset_alert_engine
from app.integrated_app.observability.metrics import get_metrics, reset_metrics
from app.integrated_app.overload_policy import OverloadDecision

pytestmark = pytest.mark.integration


@pytest.fixture()
def client():
    _prev_fake = os.environ.get("IMM_FAKE_ENGINE")
    os.environ["IMM_FAKE_ENGINE"] = "1"
    reset_metrics()
    reset_alert_engine()
    with TestClient(create_app()) as c:
        token = c.get("/api/health").headers.get("X-CSRF-Token", "")
        if token:
            c.headers["X-CSRF-Token"] = token
        yield c
    # 回填原值而不是直接 pop：conftest 用 setdefault 提供全局默认假引擎，
    # 直接 pop 会把这个默认一起丢掉，污染同进程（同 xdist worker）的后续测试文件。
    if _prev_fake is None:
        os.environ.pop("IMM_FAKE_ENGINE", "")
    else:
        os.environ["IMM_FAKE_ENGINE"] = _prev_fake
    reset_metrics()
    reset_alert_engine()


def _payload(**kw):
    base = {
        "positive_prompt": "overload",
        "cfg": 1.0,
        "steps": 4,
        "width": 256,
        "height": 256,
        "seed": 5,
        "batch_size": 1,
        "engine_name": "z_image_turbo_native",
    }
    base.update(kw)
    return base


def test_95_rejected_with_retry_after(client: TestClient, monkeypatch) -> None:
    import app.integrated_app.services.generation_service as gr

    monkeypatch.setattr(
        gr,
        "evaluate_overload",
        lambda fill, batch_size: OverloadDecision(
            action="reject_429",
            status=429,
            reason="queue_95",
            retry_after_s=10,
            tier=3,
            message="near full",
        ),
    )
    before = get_metrics().queue_rejected_total.value(reason="queue_95")
    r = client.post("/api/generate", json=_payload())
    assert r.status_code == 429, r.text[:200]
    assert r.headers.get("Retry-After") == "10"
    after = get_metrics().queue_rejected_total.value(reason="queue_95")
    assert after > before


def test_queue_full_returns_503(client: TestClient, monkeypatch) -> None:
    import app.integrated_app.services.generation_service as gr

    monkeypatch.setattr(
        gr,
        "evaluate_overload",
        lambda fill, batch_size: OverloadDecision(
            action="reject_503",
            status=503,
            reason="queue_full",
            retry_after_s=10,
            tier=4,
            message="queue full",
        ),
    )
    before = get_metrics().queue_rejected_total.value(reason="queue_full")
    r = client.post("/api/generate", json=_payload())
    assert r.status_code == 503, r.text[:200]
    after = get_metrics().queue_rejected_total.value(reason="queue_full")
    assert after > before


def test_normal_water_proceeds(client: TestClient, monkeypatch) -> None:
    import app.integrated_app.services.generation_service as gr

    monkeypatch.setattr(
        gr,
        "evaluate_overload",
        lambda fill, batch_size: OverloadDecision(
            action="proceed",
            status=200,
            reason="ok",
            retry_after_s=0,
            tier=0,
            message="ok",
        ),
    )
    r = client.post("/api/generate", json=_payload())
    assert r.status_code == 200
    tid = r.json()["task_id"]
    # 等待真正入队并被处理
    import time

    deadline = time.time() + 10
    while time.time() < deadline:
        st = client.get(f"/api/tasks/{tid}").json().get("status")
        if st in ("completed", "failed"):
            break
        time.sleep(0.05)
    assert st == "completed"
