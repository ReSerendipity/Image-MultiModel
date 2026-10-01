"""
tests/test_agent_routes.py — Agent 对话端点的契约与装配测试

覆盖:
- GET /api/agent/health:200 + llm_ok 布尔(本地无 llama-server 时为 False,不抛异常)
- POST /api/agent/chat(CSRF Double-Submit 流程):注入替身 orchestrator → SSE 事件流完整
- 真实装配 + LLM 离线(monkeypatch 指向必然拒绝的端口)→ SSE 以 error 事件收尾,不 500
- 请求体校验:空 message → 422;非法 mode → 422
- POST /api/agent/confirm:双模式参数卡片 approve/reject/失效 400
- _execute_tool 真实装配:generate_image 映射入队,engine 键不炸
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any, NamedTuple

import pytest
from fastapi.testclient import TestClient

from app.integrated_app.agent.orchestrator import AgentEvent, ProposalError
from app.integrated_app.app_server import create_app


class TurnCall(NamedTuple):
    """一轮对话的入参快照（M2 起含 images）。

    ``images`` 是路由层 PathGuard 校验通过后交给编排层的图片引用列表（裸 base64 已转 data URI）。
    """

    session_id: str | None
    message: str
    mode: str | None
    images: list[str] | None = None


class FakeOrchestrator:
    """替身:返回固定事件序列,记录入参。"""

    def __init__(self, events: list[AgentEvent], mode: str = "AUTO") -> None:
        self.events = events
        self.mode = mode
        self.calls: list[TurnCall] = []
        self.approvals: list[tuple[str, str, dict[str, Any] | None]] = []
        self.rejections: list[tuple[str, str]] = []

    async def run_turn(
        self, session_id: str | None, message: str, mode: str | None = None, images: list[str] | None = None
    ) -> list[AgentEvent]:
        self.calls.append(TurnCall(session_id, message, mode, images))
        return self.events

    async def run_turn_stream(
        self, session_id: str | None, message: str, mode: str | None = None, images: list[str] | None = None
    ) -> AsyncIterator[AgentEvent]:
        """SSE 路由走的是流式入口；替身按序产出同一批事件。"""
        self.calls.append(TurnCall(session_id, message, mode, images))
        for event in self.events:
            yield event

    async def approve_proposal(
        self, session_id: str, proposal_id: str, overrides: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self.approvals.append((session_id, proposal_id, overrides))
        return {"task_id": "TASK-OK", "status": "queued"}

    def reject_proposal(self, session_id: str, proposal_id: str) -> dict[str, Any]:
        self.rejections.append((session_id, proposal_id))
        return {"status": "rejected", "proposal_id": proposal_id}


class StaleProposalOrchestrator(FakeOrchestrator):
    """提案已失效的替身:confirm 必须映射为 400 而不是 500。"""

    async def approve_proposal(
        self, session_id: str, proposal_id: str, overrides: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        raise ProposalError("提案不存在或已过期,请重新发起需求。")

    def reject_proposal(self, session_id: str, proposal_id: str) -> dict[str, Any]:
        raise ProposalError("提案不存在或已过期,请重新发起需求。")


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
    assert fake.calls[0] == TurnCall(None, "画一只猫", "AUTO", [])


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


# ── 双模式(5b):mode 透传 + 参数卡片确认端点 ────────────────


def test_chat_passes_mode_through(client: TestClient):
    fake = FakeOrchestrator([AgentEvent("final", {"text": "ok"})])
    client.app.state.agent_orchestrator = fake
    _csrf_post(client, "/api/agent/chat", {"message": "画猫", "session_id": "s1", "mode": "CONFIRM"})
    assert fake.calls[0] == TurnCall("s1", "画猫", "CONFIRM", [])


def test_chat_rejects_unknown_mode(client: TestClient):
    resp = _csrf_post(client, "/api/agent/chat", {"message": "画猫", "mode": "SUPER_AUTO"})
    assert resp.status_code == 422


def test_chat_sse_proposal_event_shape(client: TestClient):
    """proposal 事件必须原样透出（前端参数卡片的唯一数据源）。"""
    fake = FakeOrchestrator(
        [
            AgentEvent(
                "proposal",
                {"proposal_id": "p1", "mode": "CONFIRM", "manual": False, "args": {"positive_prompt": "cat"}},
            ),
            AgentEvent("final", {"text": "请确认。"}),
        ]
    )
    client.app.state.agent_orchestrator = fake
    events = _parse_sse(_csrf_post(client, "/api/agent/chat", {"message": "画猫", "mode": "CONFIRM"}).text)
    assert events[0]["type"] == "proposal"
    assert events[0]["proposal_id"] == "p1"
    assert events[0]["args"]["positive_prompt"] == "cat"


def test_confirm_approve_forwards_params(client: TestClient):
    fake = FakeOrchestrator([AgentEvent("final", {"text": "ok"})])
    client.app.state.agent_orchestrator = fake
    resp = _csrf_post(
        client,
        "/api/agent/confirm",
        {"session_id": "s1", "proposal_id": "p1", "action": "approve", "params": {"steps": 20}},
    )
    assert resp.status_code == 200
    assert resp.json()["task_id"] == "TASK-OK"
    assert fake.approvals == [("s1", "p1", {"steps": 20})]


def test_confirm_reject_path(client: TestClient):
    fake = FakeOrchestrator([AgentEvent("final", {"text": "ok"})])
    client.app.state.agent_orchestrator = fake
    resp = _csrf_post(client, "/api/agent/confirm", {"session_id": "s1", "proposal_id": "p1", "action": "reject"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"
    assert fake.rejections == [("s1", "p1")]
    assert fake.approvals == []


def test_confirm_stale_proposal_is_400(client: TestClient):
    client.app.state.agent_orchestrator = StaleProposalOrchestrator([])
    resp = _csrf_post(client, "/api/agent/confirm", {"session_id": "s1", "proposal_id": "gone", "action": "approve"})
    assert resp.status_code == 400
    # 统一错误封装:{success:false, error:{code,message,detail}}（见 middleware/error_handler.py）
    err = resp.json()["error"]
    assert err["code"] == "HTTP_400"
    assert "过期" in err["message"]

    resp2 = _csrf_post(client, "/api/agent/confirm", {"session_id": "s1", "proposal_id": "gone", "action": "reject"})
    assert resp2.status_code == 400
    assert "过期" in resp2.json()["error"]["message"]


def test_confirm_requires_csrf(client: TestClient):
    """新端点必须同样受 CSRF 中间件保护（不得成为绕过口）。"""
    resp = client.post("/api/agent/confirm", json={"session_id": "s1", "proposal_id": "p1"})
    assert resp.status_code == 403


# ── edit_image（P1 Qwen-Image 2.1 Edit）─────────────────────


class _FakeApp:
    """替身 app.state：task_queue / history_db。"""

    def __init__(self, queue_tasks, history_record=None) -> None:
        self.state = type("S", (), {})()
        self.state.task_queue = type("Q", (), {"list_tasks": staticmethod(lambda **k: queue_tasks)})()
        self.state.history_db = type("H", (), {"get_task": staticmethod(lambda tid: history_record)})()


class _FakeTask:
    def __init__(self, task_id: str, result: list[str]) -> None:
        self.task_id = task_id
        self.result = result


def test_resolve_edit_reference_from_queue_task():
    from app.integrated_app.routes.agent_routes import _resolve_edit_reference

    app = _FakeApp([_FakeTask("T-1", [r"outputs\z_image_turbo_native\20260930\a.png"])])
    ref = _resolve_edit_reference(app, {"task_id": "T-1"})
    assert ref.replace("\\", "/").endswith("z_image_turbo_native/20260930/a.png")


def test_resolve_edit_reference_from_history_record():
    from app.integrated_app.routes.agent_routes import _resolve_edit_reference

    app = _FakeApp([], {"task_id": "T-2", "outputs": [{"path": "outputs/x/20260930/b.png", "output_type": "original"}]})
    ref = _resolve_edit_reference(app, {"task_id": "T-2"})
    assert ref.replace("\\", "/").endswith("x/20260930/b.png")


def test_resolve_edit_reference_missing_task_raises():
    import pytest

    from app.integrated_app.routes.agent_routes import _resolve_edit_reference

    app = _FakeApp([], None)
    with pytest.raises(ValueError, match="没有可用的输出图片"):
        _resolve_edit_reference(app, {"task_id": "NOPE"})


def test_resolve_edit_reference_rejects_traversal():
    """越权路径必须被拒（PathGuard 白名单外）。"""
    import pytest

    from app.integrated_app.routes.agent_routes import _resolve_edit_reference

    app = _FakeApp([], None)
    with pytest.raises(ValueError):
        _resolve_edit_reference(app, {"reference_path": r"C:/Windows/system.ini"})
    with pytest.raises(ValueError):
        _resolve_edit_reference(app, {"reference_path": "../../../etc/passwd"})


def test_execute_edit_image_wires_edit_mode_and_engine(monkeypatch: pytest.MonkeyPatch):
    """edit_image 必须以 edit_mode=True + 编辑引擎 + 参考图提交，走队列化服务链。"""
    from app.integrated_app.routes import agent_routes
    from app.integrated_app.routes.agent_routes import _execute_edit_image

    captured: dict[str, Any] = {}

    class FakeResp:
        task_id = "T-EDIT-1"

    class FakeService:
        def __init__(self, task_queue=None, history_db=None) -> None:
            captured["queue"] = task_queue
            captured["history"] = history_db

        async def submit_txt2img(self, req):
            captured["req"] = req
            return FakeResp()

    monkeypatch.setattr(agent_routes, "GenerationService", FakeService)
    # 指向一个真实存在的参考图（项目内 outputs 里随便一个已生成的 png 不保证存在，
    # 故临时造一个在 PathGuard 白名单目录内的文件）
    from pathlib import Path as _P

    from app.integrated_app.config import get_config

    cfg = get_config()
    outputs_root = _P(cfg.project_root) / cfg.output.base_dir
    ref_rel = "_smoke_edit_ref.png"
    ref_file = outputs_root / ref_rel
    ref_file.parent.mkdir(parents=True, exist_ok=True)
    ref_file.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    try:
        app = _FakeApp([], None)
        import asyncio

        result = asyncio.run(
            _execute_edit_image(
                app,
                app.state.task_queue,
                app.state.history_db,
                {"positive_prompt": "改成红色", "reference_path": f"outputs/{ref_rel}", "steps": 6},
            )
        )
    finally:
        ref_file.unlink(missing_ok=True)

    assert result.get("task_id") == "T-EDIT-1", result
    req = captured["req"]
    assert req.edit_mode is True
    assert req.engine_name == "qwen_image_edit_native"
    assert req.reference_image_path.endswith(ref_rel)
    assert req.seedvr2_enable is False and req.eses_enable is False
    assert req.steps == 6


def test_execute_edit_image_without_edit_engine_returns_error(monkeypatch: pytest.MonkeyPatch):
    from app.integrated_app.routes import agent_routes
    from app.integrated_app.routes.agent_routes import _execute_edit_image

    class _Cfg:
        project_root = "."

    class _Cfg2:
        output = type("O", (), {"base_dir": "outputs"})()
        models = type("M", (), {"engines": {}})()

    monkeypatch.setattr(agent_routes, "get_config", lambda: _Cfg2())
    result = asyncio.run(_execute_edit_image(_FakeApp([], None), None, None, {"positive_prompt": "x", "task_id": "T"}))
    assert "error" in result
    _ = _Cfg
