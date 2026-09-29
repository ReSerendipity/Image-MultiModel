"""
tests/test_agent_routes.py — Agent 对话端点的契约与装配测试

覆盖:
- GET /api/agent/health:200 + llm_ok 布尔(本地无 llama-server 时为 False,不抛异常)
- POST /api/agent/chat(CSRF Double-Submit 流程):注入替身 orchestrator → SSE 事件流完整
- 真实装配 + LLM 离线(monkeypatch 指向必然拒绝的端口)→ SSE 以 error 事件收尾,不 500
- 请求体校验:空 message → 422
- _execute_tool 真实装配:generate_image 映射入队,engine 键不炸
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.integrated_app.agent.orchestrator import AgentEvent
from app.integrated_app.app_server import create_app


class FakeOrchestrator:
    """替身:返回固定事件序列,记录入参。"""

    def __init__(self, events: list[AgentEvent], mode: str = "AUTO") -> None:
        self.events = events
        self.mode = mode
        self.calls: list[tuple[str | None, str]] = []

    async def run_turn(self, session_id: str | None, message: str) -> list[AgentEvent]:
        self.calls.append((session_id, message))
        return self.events


@pytest.fixture()
def client() -> Any:
    with TestClient(create_app()) as c:
        yield c


def _csrf_post(client: TestClient, url: str, payload: dict[str, Any]) -> Any:
    health = client.get("/api/health")
    token = health.headers.get("X-CSRF-Token", "")
    return client.post(url, json=payload, headers={"X-CSRF-Token": token})


def _parse_sse(text: str) -> list[dict[str, Any]]:
    events = []
    for block in text.split("\n\n"):
        block = block.strip()
        if block.startswith("data:") and "[DONE]" not in block:
            events.append(json.loads(block[5:].strip()))
    return events


def test_agent_health_reports_llm_offline_gracefully(client: TestClient):
    resp = client.get("/api/agent/health")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["llm_ok"], bool)
    assert "llm_base_url" in body and "llm_model" in body


def test_chat_sse_full_flow_with_fake_orchestrator(client: TestClient):
    fake = FakeOrchestrator(
        [
            AgentEvent("tool_call", {"name": "generate_image", "args": {"positive_prompt": "cat"}, "violations": []}),
            AgentEvent("task_created", {"task_id": "TASK-1"}),
            AgentEvent("tool_result", {"name": "generate_image", "result": {"task_id": "TASK-1"}}),
            AgentEvent("final", {"text": "已提交生成任务。"}),
        ]
    )
    client.app.state.agent_orchestrator = fake

    resp = _csrf_post(client, "/api/agent/chat", {"message": "画一只猫"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(resp.text)
    assert [e["type"] for e in events] == ["tool_call", "task_created", "tool_result", "final"]
    assert events[1]["task_id"] == "TASK-1"
    assert "[DONE]" in resp.text
    assert fake.calls[0] == (None, "画一只猫")


def test_chat_real_assembly_llm_offline_yields_error_event(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("IMAGE_MM_AGENT_LLM_BASE_URL", "http://127.0.0.1:1/v1")
    # 不注入替身 → 走真实装配路径(LLMClient 懒创建时读 env)
    resp = _csrf_post(client, "/api/agent/chat", {"message": "你好"})
    assert resp.status_code == 200  # SSE 兜底:LLM 离线也绝不 500
    events = _parse_sse(resp.text)
    assert events, "应有 error 事件"
    assert events[-1]["type"] == "error"
    assert "LLM 大脑不可用" in events[-1]["text"]


def test_chat_empty_message_rejected(client: TestClient):
    resp = _csrf_post(client, "/api/agent/chat", {"message": ""})
    assert resp.status_code == 422


def test_chat_session_id_reaches_orchestrator(client: TestClient):
    fake = FakeOrchestrator([AgentEvent("final", {"text": "ok"})])
    client.app.state.agent_orchestrator = fake
    _csrf_post(client, "/api/agent/chat", {"message": "再来一张", "session_id": "sess-42"})
    assert fake.calls[0][0] == "sess-42"


def test_index_html_includes_chat_js(client: TestClient):
    """base.html scripts 块挂载 chat.js,页面可加载对话面板。"""
    resp = client.get("/")
    assert resp.status_code == 200
    assert "/static/js/chat.js" in resp.text


def test_tool_executor_generate_image_queues_task(client: TestClient):
    """真实 _execute_tool:generate_image 走 GenerationService 入队,engine 键不炸、返回 task_id。"""
    from app.integrated_app.routes.agent_routes import _execute_tool

    result = asyncio.run(
        _execute_tool(
            client.app,
            "generate_image",
            {"positive_prompt": "a cat on the moon", "steps": 10, "engine": "not_exist"},
        )
    )
    assert result["status"] == "queued"
    assert result["task_id"]
