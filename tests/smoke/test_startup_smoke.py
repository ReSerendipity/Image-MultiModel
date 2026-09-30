"""
tests/smoke/test_startup_smoke.py — P0-1 启动契约 smoke

对应评估 §9-P0-1「先修启动契约并跑真实启动 smoke」：
启动应用 → GET /api/health → 提交一个假引擎任务并等待完成 →
拉取 /api/metrics 与 /api/alerts → 关闭服务。任何一步失败即判定
启动契约未闭环。

无 GPU：IMM_FAKE_ENGINE=1 启用 FakeEngine，覆盖「提交假引擎任务」路径。
"""

from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

from app.integrated_app.app_server import create_app
from app.integrated_app.observability.alerts import reset_alert_engine
from app.integrated_app.observability.metrics import reset_metrics

pytestmark = [pytest.mark.smoke, pytest.mark.integration]


@pytest.fixture()
def client():
    _prev_fake = os.environ.get("IMM_FAKE_ENGINE")
    os.environ["IMM_FAKE_ENGINE"] = "1"
    reset_metrics()
    reset_alert_engine()
    with TestClient(create_app()) as c:  # 上下文退出即触发优雅关闭
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


def _wait_terminal(c: TestClient, task_id: str, timeout_s: float = 15.0) -> dict:
    deadline = time.time() + timeout_s
    last: dict = {}
    while time.time() < deadline:
        last = c.get(f"/api/tasks/{task_id}").json()
        if last.get("status") in ("completed", "failed", "cancelled"):
            return last
        time.sleep(0.05)
    pytest.fail(f"task {task_id} 未在 {timeout_s}s 内结束，最后状态 {last.get('status')}")


def test_app_boots_and_health_ok(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert body.get("status") in ("ok", "healthy", True) or "ok" in str(body).lower()


def test_fake_generation_completes(client: TestClient) -> None:
    payload = {
        "positive_prompt": "startup smoke",
        "cfg": 1.0,
        "steps": 4,
        "width": 256,
        "height": 256,
        "seed": 7,
        "batch_size": 1,
        "engine_name": "z_image_turbo_native",
    }
    r = client.post("/api/generate", json=payload)
    assert r.status_code == 200, r.text[:200]
    tid = r.json()["task_id"]
    result = _wait_terminal(client, tid)
    assert result["status"] == "completed", result


def test_metrics_and_alerts_endpoints_serve(client: TestClient) -> None:
    # 先产生一次生成，确保指标有样本
    payload = {
        "positive_prompt": "metrics smoke",
        "cfg": 1.0,
        "steps": 4,
        "width": 256,
        "height": 256,
        "seed": 11,
        "batch_size": 1,
        "engine_name": "z_image_turbo_native",
    }
    tid = client.post("/api/generate", json=payload).json()["task_id"]
    _wait_terminal(client, tid)

    metrics = client.get("/api/metrics/prometheus")
    assert metrics.status_code == 200
    assert "http_requests_total" in metrics.text

    alerts = client.get("/api/alerts")
    assert alerts.status_code == 200
    assert alerts.json()["status"] == "ok"


def test_graceful_shutdown_no_error(client: TestClient) -> None:
    # 触发一次生成后让 fixture 的上下文管理器执行 shutdown 路径
    payload = {
        "positive_prompt": "shutdown smoke",
        "cfg": 1.0,
        "steps": 4,
        "width": 256,
        "height": 256,
        "seed": 13,
        "batch_size": 1,
        "engine_name": "z_image_turbo_native",
    }
    tid = client.post("/api/generate", json=payload).json()["task_id"]
    _wait_terminal(client, tid)
    # 若 shutdown 抛异常，TestClient 上下文退出会传播，用例即失败
