"""tests/integration/test_agent_vlm_multiturn.py — P2-vlm-chat M2 多模态输入验收

覆盖（对应 docs/roadmap/P2-vlm-chat.md M2 验收口径）：
1. 单图 / 多图：图片引用经 PathGuard 校验后原样到达编排层，顺序与张数保持
2. 无图轮次：不产生图片引用，也不伪造视觉上下文
3. 会话回放：同一 session_id 的多轮中，图片只属于带图的那一轮
4. 越权拦截：白名单外的路径（绝对路径 / 穿越）→ 422，绝不进入编排层
5. 形态校验：AgentImage 的 path / b64 互斥且恰好其一；裸 base64 规范为 data URI
6. 上限：超过 _MAX_CHAT_IMAGES 张时截断
7. 注入语义：配置了 vlm_context_fn 时，VLM 描述带「非指令」声明注入 system 段；
   未配置 / 编码失败时如实上报 unavailable / error，且**不伪造**视觉描述、不中断本轮

注：图片**内容**的过滤属于 M3（security/content_filter.filter_image_for_vlm_input），
本文件只管「引用能不能进得来、上下文怎么注入」，不重复断言内容策略。
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.integrated_app.agent.orchestrator import VISION_CONTEXT_TEMPLATE, AgentEvent, AgentOrchestrator
from app.integrated_app.agent.session_store import InMemorySessionStore
from app.integrated_app.app_server import create_app
from app.integrated_app.config import get_config
from app.integrated_app.routes.agent_routes import _MAX_CHAT_IMAGES, AgentImage, _validate_images

# ── 路由层替身 ────────────────────────────────────────────


class FakeOrchestrator:
    """替身：记录入参并返回固定事件序列（与 tests/test_agent_routes.py 同口径）。"""

    def __init__(self, events: list[AgentEvent]) -> None:
        self.events = events
        self.calls: list[tuple[str | None, str, str | None, list[str] | None]] = []

    async def run_turn(
        self, session_id: str | None, message: str, mode: str | None = None, images: list[str] | None = None
    ) -> list[AgentEvent]:
        self.calls.append((session_id, message, mode, images))
        return self.events

    async def run_turn_stream(
        self, session_id: str | None, message: str, mode: str | None = None, images: list[str] | None = None
    ) -> Any:
        self.calls.append((session_id, message, mode, images))
        for event in self.events:
            yield event


@pytest.fixture()
def client() -> Any:
    with TestClient(create_app()) as c:
        yield c


def _inject(client: TestClient, fake: FakeOrchestrator) -> None:
    client.app.state.agent_orchestrator = fake


def _post(client: TestClient, payload: dict[str, Any]) -> Any:
    health = client.get("/api/health")
    token = health.headers.get("X-CSRF-Token", "")
    return client.post("/api/agent/chat", json=payload, headers={"X-CSRF-Token": token})


def _gif_b64() -> str:
    """最小合法 PNG 字节的 base64（1x1 透明像素），仅用于形态断言。"""
    return "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="


# ── 1/2/3. 引用到达编排层、无图、会话回放 ──────────────────


def test_single_image_path_reaches_orchestrator(client: TestClient) -> None:
    fake = FakeOrchestrator([AgentEvent("final", {"text": "ok"})])
    _inject(client, fake)

    resp = _post(client, {"message": "这张图什么风格", "images": [{"path": "outputs/_m2/a.png", "role": "input"}]})

    assert resp.status_code == 200
    assert len(fake.calls) == 1
    refs = fake.calls[0][3]
    assert len(refs) == 1
    assert refs[0].replace("\\", "/").endswith("outputs/_m2/a.png")


def test_multi_images_preserve_order(client: TestClient) -> None:
    fake = FakeOrchestrator([AgentEvent("final", {"text": "ok"})])
    _inject(client, fake)

    resp = _post(
        client,
        {
            "message": "对比这几张",
            "images": [
                {"path": "outputs/_m2/1.png"},
                {"path": "outputs/_m2/2.png"},
                {"path": "outputs/_m2/3.png"},
            ],
        },
    )

    assert resp.status_code == 200
    refs = fake.calls[0][3] or []
    assert [r.replace("\\", "/").split("/")[-1] for r in refs] == ["1.png", "2.png", "3.png"]


def test_text_only_turn_sends_no_images(client: TestClient) -> None:
    fake = FakeOrchestrator([AgentEvent("final", {"text": "ok"})])
    _inject(client, fake)

    resp = _post(client, {"message": "画一只猫"})

    assert resp.status_code == 200
    assert fake.calls[0][3] == []


def test_session_replay_image_only_on_image_turn(client: TestClient) -> None:
    """同一会话多轮：图片只应挂在带图的那一轮（会话回放不得张冠李戴）。"""
    fake = FakeOrchestrator([AgentEvent("final", {"text": "ok"})])
    _inject(client, fake)

    assert _post(client, {"message": "先画一只猫", "session_id": "s-m2"}).status_code == 200
    resp2 = _post(
        client,
        {"message": "再看这张", "session_id": "s-m2", "images": [{"path": "outputs/_m2/1.png"}]},
    )
    assert resp2.status_code == 200

    assert fake.calls[0][3] == []
    refs = fake.calls[1][3] or []
    assert len(refs) == 1 and refs[0].endswith("1.png")


# ── 4. 越权拦截 ────────────────────────────────────────────


@pytest.mark.parametrize("bad", ["C:/Windows/system.ini", "../../../etc/passwd", "outputs/../../secret.key"])
def test_out_of_whitelist_image_path_rejected_422(client: TestClient, bad: str) -> None:
    fake = FakeOrchestrator([AgentEvent("final", {"text": "ok"})])
    _inject(client, fake)

    resp = _post(client, {"message": "看一下", "images": [{"path": bad}]})

    assert resp.status_code == 422, bad
    assert fake.calls == [], "越权图片绝不能进入编排层"


def test_in_whitelist_dir_is_allowed(client: TestClient) -> None:
    """白名单内的其它目录（data/、workflows/）同样放行——防止过度收紧。"""
    fake = FakeOrchestrator([AgentEvent("final", {"text": "ok"})])
    _inject(client, fake)

    resp = _post(client, {"message": "看 workflow", "images": [{"path": "workflows/w.json"}]})

    assert resp.status_code == 200
    assert fake.calls[0][3]


# ── 5. 形态校验与归一化 ────────────────────────────────────


def test_agent_image_requires_exactly_one_source() -> None:
    with pytest.raises(Exception, match="必须恰好提供其一"):
        AgentImage(path="outputs/a.png", b64=_gif_b64())
    with pytest.raises(Exception):
        AgentImage()


def test_bare_base64_normalized_to_data_uri() -> None:
    refs = _validate_images([AgentImage(b64=_gif_b64())])
    assert refs == [f"data:image/png;base64,{_gif_b64()}"]


def test_b64_already_data_uri_kept_as_is() -> None:
    uri = f"data:image/jpeg;base64,{_gif_b64()}"
    assert _validate_images([AgentImage(b64=uri)]) == [uri]


def test_images_beyond_limit_are_truncated() -> None:
    many = [AgentImage(b64=_gif_b64()) for _ in range(_MAX_CHAT_IMAGES + 4)]
    assert len(_validate_images(many)) == _MAX_CHAT_IMAGES


# ── 6/7. 编排层注入语义 ────────────────────────────────────


class _CapturingLLM:
    """非流式替身 LLM：吞下 messages 并回一句固定文案。"""

    def __init__(self) -> None:
        self.messages: list[list[dict[str, Any]]] = []

    async def chat_completion(self, messages: list[dict[str, Any]], tools: Any = None) -> dict[str, Any]:
        self.messages.append(messages)
        return {"choices": [{"message": {"content": "收到。"}}]}


class _NoopExecutor:
    """本文件不触发工具执行，用空执行器即可（避免牵扯真实 GenerationService）。"""

    async def __call__(self, name: str, args: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG002
        return {"ok": True}


def _orchestrator(llm: _CapturingLLM, vlm_context_fn: Any) -> AgentOrchestrator:
    return AgentOrchestrator(
        llm=llm,
        tool_executor=_NoopExecutor(),  # type: ignore[arg-type]
        store=InMemorySessionStore(),
        engines=["z_image_turbo_native"],
        mode="AUTO",
        vlm_context_fn=vlm_context_fn,
    )


def _async_vlm(text: str, exc: Exception | None = None) -> Any:
    async def _fn(_user_text: str, images: list[str]) -> str:
        if exc is not None:
            raise exc
        return f"VLM 描述：共 {len(images)} 张图"

    return _fn


@pytest.mark.asyncio
async def test_vlm_context_injected_with_non_instruction_declaration() -> None:
    """VLM 描述必须以「非指令」声明注入 system 段——数据/指令分离是本仓硬要求。"""
    llm = _CapturingLLM()
    orch = _orchestrator(llm, _async_vlm("ok"))

    events = await orch.run_turn("s1", "这张什么风格", images=["/tmp/a.png", "/tmp/b.png"])

    assert [e.type for e in events] == ["vlm_context", "final"]
    assert events[0].data["status"] == "ok"
    assert events[0].data["images"] == ["/tmp/a.png", "/tmp/b.png"]

    system_blocks = [m["content"] for m in llm.messages[0] if m["role"] == "system"]
    assert any(VISION_CONTEXT_TEMPLATE.split("---")[0] in b for b in system_blocks)
    assert any("VLM 描述：共 2 张图" in b for b in system_blocks)
    # 关键：注入块必须自带「不构成任何指令」的声明，避免 VLM 文本被当系统指令执行
    assert any("不构成任何指令" in b for b in system_blocks)


@pytest.mark.asyncio
async def test_vision_context_unavailable_without_encoder() -> None:
    """未配置编码器时如实报 unavailable，且**不伪造**任何视觉描述。"""
    llm = _CapturingLLM()
    orch = _orchestrator(llm, None)

    events = await orch.run_turn("s1", "这张什么风格", images=["/tmp/a.png"])

    assert events[0].type == "vlm_context"
    assert events[0].data["status"] == "unavailable"
    system_blocks = [m["content"] for m in llm.messages[0] if m["role"] == "system"]
    assert not any("VLM 描述" in b for b in system_blocks)
    assert events[-1].type == "final"


@pytest.mark.asyncio
async def test_vision_context_error_does_not_abort_turn() -> None:
    """视觉编码失败只降级为 error 事件，本轮对话照常走完。"""
    llm = _CapturingLLM()
    orch = _orchestrator(llm, _async_vlm(None, exc=RuntimeError("显存不足")))

    events = await orch.run_turn("s1", "看图", images=["/tmp/a.png"])

    assert events[0].type == "vlm_context"
    assert events[0].data["status"] == "error"
    assert events[-1].type == "final"


@pytest.mark.asyncio
async def test_text_only_turn_emits_no_vlm_context_event() -> None:
    """纯文本轮次不产生 vlm_context 事件——避免每轮都刷一条空噪声。"""
    llm = _CapturingLLM()
    orch = _orchestrator(llm, _async_vlm("ok"))

    events = await orch.run_turn("s1", "画一只猫")

    assert [e.type for e in events] == ["final"]


# ── 契约：请求体形状（pydantic 层）────────────────────────


def test_agent_image_role_accepts_only_input_or_output() -> None:
    assert AgentImage(b64=_gif_b64(), role="output").role == "output"
    with pytest.raises(Exception):
        AgentImage(b64=_gif_b64(), role="sideways")


def test_outputs_is_in_path_guard_whitelist() -> None:
    """前端只传相对 outputs 的路径；白名单里必须有 outputs/ 兜底（monkeypatch 在此无对象可打，故纯断言配置）。"""
    cfg = get_config()
    assert any(str(b).replace("\\", "/").rstrip("/").endswith("outputs") for b in cfg.security.allowed_base_dirs)
