"""空提示词 422 + 桌面壳优雅停机端点防回归（v1.3.0 发版期实测两处 P2）。

- 空/纯空白 positive_prompt 直连 /api/generate 必须 422（此前放行白占 GPU）；
- /api/system/shutdown 是 CSRF 保护端点（壳走 double-submit），触发 SIGINT 优雅退出。
"""

from __future__ import annotations

import os
import signal

import pytest
from fastapi.testclient import TestClient

from app.integrated_app.app_server import create_app

pytestmark = [pytest.mark.smoke, pytest.mark.integration]


@pytest.fixture()
def client():
    prev = os.environ.get("IMM_FAKE_ENGINE")
    os.environ["IMM_FAKE_ENGINE"] = "1"
    with TestClient(create_app(), raise_server_exceptions=False) as c:
        r = c.get("/api/health")
        tok = r.headers.get("X-CSRF-Token", "")
        if tok:
            c.headers["X-CSRF-Token"] = tok
        yield c
    if prev is None:
        os.environ.pop("IMM_FAKE_ENGINE", None)
    else:
        os.environ["IMM_FAKE_ENGINE"] = prev


def _payload(**over):
    base = {"width": 512, "height": 512, "steps": 4, "batch_size": 1}
    base.update(over)
    return base


def test_empty_prompt_rejected_422(client):
    r = client.post("/api/generate", json=_payload(positive_prompt=""))
    assert r.status_code == 422


def test_whitespace_prompt_rejected_422(client):
    r = client.post("/api/generate", json=_payload(positive_prompt="   \t \n"))
    assert r.status_code == 422


def test_valid_prompt_not_422(client):
    r = client.post("/api/generate", json=_payload(positive_prompt="一只柯基"))
    assert r.status_code != 422


def test_shutdown_requires_csrf():
    # 全新 client 不带 CSRF token → 中间件 403（证明它是受保护端点，非裸放行）
    with TestClient(create_app(), raise_server_exceptions=False) as c:
        r = c.post("/api/system/shutdown")
        assert r.status_code == 403


def test_shutdown_triggers_graceful_sigint(client, monkeypatch):
    calls = []
    monkeypatch.setattr(signal, "raise_signal", lambda sig: calls.append(sig))
    r = client.post("/api/system/shutdown")
    assert r.status_code == 200
    assert r.json()["status"] == "shutting_down"
    assert calls == [signal.SIGINT]
