"""桌面壳就绪契约端点防回归：/api/system/health 必须返回 JSON。

壳（desktop/src-tauri/src/health_check.rs）轮询 /api/system/health 并
reqwest .json() 解析 ``security.integrity``。该路由曾不存在——SPA catch-all
返回 index.html（200 text/html）→ 壳解析恒失败 → 桌面装后永远「启动超时」
（v1.3.0 发版阶段3 真机实测 P1，2026-10-03）。
"""

from __future__ import annotations

import os

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
        yield c
    if _prev_fake is None:
        os.environ.pop("IMM_FAKE_ENGINE", None)
    else:
        os.environ["IMM_FAKE_ENGINE"] = _prev_fake


def test_system_health_returns_json_with_integrity(client):
    r = client.get("/api/system/health")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert body["status"] == "ok"
    assert body["version"] == "1.3.0"
    integrity = body["security"]["integrity"]
    assert set(integrity) >= {"checked", "failed", "failed_files", "manifest_signed"}


def test_shell_readiness_payload_decodes_as_strict_json(client):
    """壳的 reqwest .json() 等价 strict JSON——响应体不得是 HTML 回退页。"""
    r = client.get("/api/system/health")
    raw = r.content
    assert raw.lstrip().startswith(b"{"), "/api/system/health 被 SPA catch-all 吞掉返回 HTML（壳启动必挂的根因）"
