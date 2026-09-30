"""
tests/observability/test_metrics_route.py — /api/metrics 与 /api/alerts 集成测试

MLOps P0-2 / P0-3 / P0-4：在真实（假引擎）应用实例上验证：
- /api/metrics 暴露标准 exposition 且包含生成链路与资源指标；
- 一次完整生成后 generation_completed_total 增长、端到端延迟直方图有样本；
- HTTP 中间件记录 http_requests_total（路径已归一化）；
- /api/alerts 返回结构化健康摘要与告警列表（runbook 链接）。

无 GPU：通过 IMM_FAKE_ENGINE=1 启用 FakeEngine。
"""

from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

from app.integrated_app.app_server import create_app
from app.integrated_app.observability.alerts import reset_alert_engine
from app.integrated_app.observability.metrics import get_metrics, reset_metrics

pytestmark = pytest.mark.integration


@pytest.fixture()
def client():
    _prev_fake = os.environ.get("IMM_FAKE_ENGINE")
    os.environ["IMM_FAKE_ENGINE"] = "1"
    reset_metrics()
    reset_alert_engine()
    with TestClient(create_app()) as c:
        health = c.get("/api/health")
        token = health.headers.get("X-CSRF-Token", "")
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


def _wait_terminal(c: TestClient, task_id: str, timeout_s: float = 10.0) -> dict:
    deadline = time.time() + timeout_s
    d: dict = {}
    while time.time() < deadline:
        d = c.get(f"/api/tasks/{task_id}").json()
        if d.get("status") in ("completed", "failed", "cancelled"):
            return d
        time.sleep(0.05)
    pytest.fail(f"task {task_id} timeout, last {d.get('status')}")


def _wait_metric(m, before: float, timeout_s: float = 5.0) -> None:
    """轮询等待生成计数指标实际增长。

    与 ``_wait_terminal`` 配合：status=completed 落到 HistoryDB 后，异步埋点的
    计数器可能尚未在主循环执行。这里显式等待计数器越过 ``before``，消除
    「读到 completed 但指标未增」的竞态（flaky）。
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if m.generation_completed_total.total() > before:
            return
        time.sleep(0.02)
    pytest.fail("generation_completed_total 未在超时内增长（生成可能 failed）")


def test_metrics_endpoint_exposes_core_series(client: TestClient) -> None:
    body = client.get("/api/metrics/prometheus").text
    for name in (
        "http_requests_total",
        "generation_submitted_total",
        "queue_depth",
        "gpu_memory_used_bytes",
        "sse_connected",
        "disk_free_bytes",
    ):
        assert f"# TYPE {name}" in body, f"missing {name} in /api/metrics"


def test_generation_lifecycle_counters_increment(client: TestClient) -> None:
    m = get_metrics()
    before = m.generation_completed_total.total()
    payload = {
        "positive_prompt": "metrics test",
        "cfg": 1.0,
        "steps": 4,
        "width": 256,
        "height": 256,
        "seed": 3,
        "batch_size": 1,
        "engine_name": "z_image_turbo_native",
    }
    r = client.post("/api/generate", json=payload)
    assert r.status_code == 200, r.text[:200]
    tid = r.json()["task_id"]
    _wait_terminal(client, tid)
    # 指标埋点（record_generation_completed）经由事件循环异步投递
    # （task_queue worker 线程 → run_coroutine_threadsafe 到主循环），可能略晚于
    # /api/tasks 读到的 completed 状态。轮询等待计数器实际增长，避免与异步埋点
    # 竞争的偶发误判（flaky）。若生成确实 failed，计数器不会增长，此处会如实失败。
    _wait_metric(m, before, timeout_s=5.0)
    after = m.generation_completed_total.total()
    assert after > before, "generation_completed_total did not increment"
    # 端到端延迟直方图应有样本
    rendered = m.render()
    assert any("generation_duration_seconds_count" in ln for ln in rendered.splitlines())


def test_submitted_accepted_rejected_counters(client: TestClient) -> None:
    m = get_metrics()
    sub_before = m.generation_submitted_total.total()
    acc_before = m.generation_accepted_total.total()
    payload = {
        "positive_prompt": "ok",
        "cfg": 1.0,
        "steps": 4,
        "width": 256,
        "height": 256,
        "seed": 9,
        "batch_size": 1,
        "engine_name": "z_image_turbo_native",
    }
    r = client.post("/api/generate", json=payload)
    assert r.status_code == 200
    _wait_terminal(client, r.json()["task_id"])
    assert m.generation_submitted_total.total() > sub_before
    assert m.generation_accepted_total.total() > acc_before


def test_http_metrics_recorded_with_normalized_path(client: TestClient) -> None:
    m = get_metrics()
    before = m.http_requests_total.value(method="GET", route="/api/health", status="200")
    client.get("/api/health")
    after = m.http_requests_total.value(method="GET", route="/api/health", status="200")
    assert after > before, "http_requests_total not incremented for /api/health"


def test_path_normalization_avoids_high_cardinality(client: TestClient) -> None:
    # 访问带 task_id 的任务详情，路径应被归一化为 {id}
    payload = {
        "positive_prompt": "norm",
        "cfg": 1.0,
        "steps": 4,
        "width": 256,
        "height": 256,
        "seed": 1,
        "batch_size": 1,
        "engine_name": "z_image_turbo_native",
    }
    r = client.post("/api/generate", json=payload)
    tid = r.json()["task_id"]
    client.get(f"/api/tasks/{tid}")
    rendered = get_metrics().render()
    # 不应出现原始 task_id 作为 label 值
    assert tid not in rendered, "task_id leaked into metric labels (cardinality risk)"


def test_alerts_endpoint_structure(client: TestClient) -> None:
    d = client.get("/api/alerts").json()
    assert d["status"] == "ok"
    assert "generation_health" in d
    assert "alerts" in d
    assert isinstance(d["alerts"], list)
    for a in d["alerts"]:
        assert "name" in a and "severity" in a and "runbook" in a
