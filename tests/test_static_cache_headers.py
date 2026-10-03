"""静态资源 Cache-Control: no-cache 防回归（v1.3.0 发版阶段1 实测）。

uvicorn StaticFiles 默认不发 Cache-Control → 浏览器按启发式缓存陈旧 CSS/JS，
前端资产更新后老用户最长约一天拿不到新样式（appConfirm P0 修复即因此在
旧标签页不生效）。SecurityHeadersMiddleware 对 /static/ 响应统一注入
no-cache：允许存储但每次经 etag 再验证，本地服务 304 开销可忽略。
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


def test_static_css_sent_with_no_cache(client):
    r = client.get("/static/css/seed.css")
    assert r.status_code == 200
    assert r.headers.get("Cache-Control") == "no-cache"


def test_api_health_unaffected_by_cache_header(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.headers.get("Cache-Control") is None
