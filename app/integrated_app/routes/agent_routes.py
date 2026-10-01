"""
routes/agent_routes.py — Agent 对话端点(SSE 流式)+ 真实 tool 执行器装配

对应评估报告 P0 任务 4 / 5b(最小闭环的服务端半边 + 双模式)。

路由:
- GET  /api/agent/health  — LLM 大脑健康探测(只探测,不自动拉起外部 llama-server)
- POST /api/agent/chat    — 对话入口,返回 text/event-stream
- POST /api/agent/confirm — 双模式:确认/否决参数卡片(approve 才真正入队)

SSE 事件(data: {json}\n\n,终止 data: [DONE]):
- tool_call / task_created / tool_result / proposal / final / error
  (事件定义见 agent.orchestrator.AgentEvent)
- vlm_context (M2)：{{status, images}} — 多模态输入是否被编码为视觉上下文

装配约束(评估报告第八章 A3 铁律):
- tool 执行器只走 GenerationService / TaskQueue / registry(队列化),绝不复用 mcp_server 直调路径;
- orchestrator 懒创建并缓存于 app.state.agent_orchestrator —— 测试可预注入替身;
- 最小闭环为非流式 LLM(事件在 run_turn 完成后统一 flush);逐 token delta 留后续批次。
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator

from ..agent.llm_client import LLMClient, LLMError
from ..agent.orchestrator import MODE_AUTO, AgentOrchestrator, ProposalError
from ..agent.prompts import ModeName
from ..agent.session_store import InMemorySessionStore, SqliteSessionStore, default_session_db_path
from ..config import get_config, get_project_root
from ..engine_interface import get_registry
from ..model_manager import ensure_model_status_sse_observer
from ..security.path_guard import PathGuard, PathGuardError
from ..services.generation_service import GenerateRequest, GenerationService
from ..task_queue import TaskQueue

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent", tags=["agent"])

DEFAULT_ENGINE = "z_image_turbo_native"
_MAX_POLLED_RESULT_PATHS = 8
# M2 多模态输入：单轮附带图片上限（防请求体与显存被撑爆；视觉上下文通常只需几张参考图）
_MAX_CHAT_IMAGES = 8


class AgentImage(BaseModel):
    """Agent 聊天附带的图片（P2-vlm-chat M2）。

    ``path`` / ``b64`` 互斥且恰好其一；``role`` 仅作语义标识
    （input = 用户提问所依据的输入图，output = 对话中已生成的成品图），不影响编码方式。
    """

    path: str | None = Field(default=None, max_length=1024)
    b64: str | None = Field(default=None, max_length=8 * 1024 * 1024)
    role: Literal["input", "output"] = "input"

    @model_validator(mode="after")
    def _check_source(self) -> AgentImage:
        if bool(self.path) == bool(self.b64):
            raise ValueError("AgentImage 的 path 与 b64 必须恰好提供其一")
        return self


class AgentChatRequest(BaseModel):
    """POST /api/agent/chat 请求体。mode 为双模式档位(5b 已接入)。"""

    message: str = Field(min_length=1, max_length=8000)
    session_id: str | None = None
    mode: ModeName = MODE_AUTO
    # M2：本轮附带的图片（input/output 语义）；缺省或空表示纯文本轮次
    images: list[AgentImage] | None = None


def _ensure_data_uri(raw: str) -> str:
    """把裸 base64 规范为 data URI；已是完整 ``data:`` URI 则原样返回。

    仅做形态规范，不做内容鉴别——图片内容安全由 ``security/content_filter`` 的
    ``filter_image_for_vlm_input`` 负责（P2-vlm-chat M3）。
    """
    text = str(raw).strip()
    if text.startswith("data:"):
        return text
    return f"data:image/png;base64,{text}"


def _validate_images(images: list[AgentImage] | None) -> list[str]:
    """校验并归一化本轮图片，返回可直接交给 VLM 的引用列表（绝对路径或 data URI）。

    - 路径类必须落在 PathGuard 白名单内：防 ``../`` 穿越、防读取 outputs/ 之外的文件；
    - base64 类原样规范为 data URI；
    - 超过 ``_MAX_CHAT_IMAGES`` 张时截断。

    Raises:
        HTTPException: 422 — 路径越权被 PathGuard 拒绝。
    """
    if not images:
        return []
    refs: list[str] = []
    cfg = get_config()
    guard = PathGuard(cfg.security.allowed_base_dirs, cfg.project_root)
    for item in images[:_MAX_CHAT_IMAGES]:
        if item.b64:
            refs.append(_ensure_data_uri(item.b64))
            continue
        raw = str(item.path or "").strip()
        if not raw:
            continue
        try:
            refs.append(str(guard.resolve(raw)))
        except PathGuardError as exc:
            raise HTTPException(422, detail=f"图片路径越权被拒绝: {exc}") from exc
    return refs


class AgentConfirmRequest(BaseModel):
    """POST /api/agent/confirm 请求体:确认/否决参数卡片。

    ``params`` 为用户在卡片上手动修改的字段(可选);服务端仍会白名单 + 范围钳制。
    """

    session_id: str = Field(min_length=1, max_length=128)
    proposal_id: str = Field(min_length=1, max_length=64)
    action: Literal["approve", "reject"] = "approve"
    params: dict[str, Any] | None = None


def _normalize_output_path(raw: str) -> str:
    """把 Task.result 中的输出路径标准化为 /api/outputs/ 下的相对路径(正斜杠)。"""
    p = str(raw).replace("\\", "/")
    marker = "outputs/"
    if marker in p:
        p = p[p.index(marker) + len(marker) :]
    return p.lstrip("/")


def _list_lora_names() -> list[str]:
    """扫描 portable LoRA 目录(portable 是当前唯一模式);失败静默返回空。"""
    try:
        lora_dir = Path(get_project_root()) / "pretrained_models" / "loras"
        if not lora_dir.is_dir():
            return []
        return sorted(p.stem for p in lora_dir.glob("*.safetensors"))[:64]
    except OSError:
        return []


async def _execute_tool(app: Any, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """真实 tool 执行器:全部走队列化服务链(结构隔离,LLM 参数先经 validate_tool_args)。"""
    task_queue: TaskQueue = app.state.task_queue
    history_db = app.state.history_db

    if name == "generate_image":
        allowed = (
            "positive_prompt",
            "negative_prompt",
            "width",
            "height",
            "steps",
            "cfg",
            "seed",
            "batch_size",
        )
        req = GenerateRequest(**{k: args[k] for k in allowed if k in args})
        # SeedVR2/Eses 权重与组件未接入 portable(评估报告 P1 余量),Agent 链路显式关闭,防止任务失败
        req.seedvr2_enable = False
        req.eses_enable = False
        service = GenerationService(task_queue=task_queue, history_db=history_db)
        resp = await service.submit_txt2img(req)
        return {"task_id": resp.task_id, "status": "queued"}

    if name == "edit_image":
        return await _execute_edit_image(app, task_queue, history_db, args)

    if name == "get_task":
        tid = str(args["task_id"])
        for task in task_queue.list_tasks():
            if task.task_id == tid:
                results = [_normalize_output_path(p) for p in (task.result or [])][:_MAX_POLLED_RESULT_PATHS]
                return {
                    "task_id": tid,
                    "status": str(task.status.value),
                    "progress": task.progress,
                    "phase": task.phase,
                    "result_paths": results,
                    "error": task.error,
                }
        return {"task_id": tid, "status": "unknown"}

    if name == "list_engines":
        try:
            engines = [
                {"name": e.get("name"), "active": e.get("is_active", e.get("active", False))}
                for e in get_registry().list_engines()
            ]
        except Exception:  # noqa: BLE001 — registry 未就绪时降级为空清单
            engines = []
        return {"engines": engines, "default_engine": DEFAULT_ENGINE}

    if name == "list_loras":
        return {"loras": _list_lora_names()}

    return {"error": f"tool {name} 未实现"}


def _resolve_edit_reference(app: Any, args: dict[str, Any]) -> str:
    """解析 ``edit_image`` 的参考图路径（PathGuard 白名单内、存在的本地文件）。

    来源二选一：
    - ``task_id``：取该任务的**第一张输出**（对话里最自然的引用方式——
      "把刚才那张图的背景换成雪地"）；
    - ``reference_path``：PathGuard 白名单内的路径（如用户上传目录里的图）。

    Raises:
        ValueError: 两个来源都解析失败（消息会作为 error 事件回喂 LLM 与用户）。
    """
    task_id = str(args.get("task_id") or "").strip()
    reference_path = str(args.get("reference_path") or "").strip()

    if task_id:
        first = ""
        for task in app.state.task_queue.list_tasks():
            if task.task_id == task_id and task.result:
                first = str(task.result[0])
                break
        if not first:
            # 队列里没有（可能已完成很久被移出内存）→ 落库的 tasks/outputs 兜底
            try:
                record = app.state.history_db.get_task(task_id)
                outputs = (record or {}).get("outputs") or []
                originals = [o for o in outputs if o.get("output_type") == "original"]
                first = str((originals or outputs or [{}])[0].get("path") or "")
            except Exception:  # noqa: BLE001 — 历史库不可用时回退到报错
                first = ""
        if first:
            base = Path(get_project_root()) / get_config().output.base_dir
            candidate = Path(first)
            return str(candidate if candidate.is_absolute() else (base / candidate).resolve())
        raise ValueError(f"任务 {task_id} 没有可用的输出图片")

    if reference_path:
        from ..config import get_config as _get_config
        from ..security.path_guard import PathGuard, PathGuardError

        cfg = _get_config()
        guard = PathGuard(cfg.security.allowed_base_dirs, cfg.project_root)
        try:
            safe = guard.resolve(reference_path)
        except PathGuardError as e:
            raise ValueError(f"参考图路径越权被拒绝: {e}") from e
        if not Path(safe).is_file():
            raise ValueError(f"参考图不存在: {reference_path}")
        return str(safe)

    raise ValueError("edit_image 缺少参考图来源(task_id / reference_path)")


async def _execute_edit_image(
    app: Any,
    task_queue: TaskQueue,
    history_db: Any,
    args: dict[str, Any],
) -> dict[str, Any]:
    """``edit_image`` 工具执行：参考图解析 → 编辑模式入队（走 GenerationService 队列化链路）。"""
    cfg = get_config()
    edit_engine = None
    for name, ecfg in cfg.models.engines.items():
        if "edit" in (ecfg.supported_features or []):
            edit_engine = name
            break
    if edit_engine is None:
        return {"error": "当前配置没有支持编辑的引擎（需要 supported_features 含 edit）"}

    try:
        reference = _resolve_edit_reference(app, args)
    except ValueError as exc:
        return {"error": str(exc)}

    allowed = ("positive_prompt", "negative_prompt", "steps", "cfg", "seed", "batch_size", "edit_resolution")
    req = GenerateRequest(**{k: args[k] for k in allowed if k in args})
    req.engine_name = edit_engine
    req.edit_mode = True
    req.reference_image_path = reference
    req.seedvr2_enable = False
    req.eses_enable = False

    service = GenerationService(task_queue=task_queue, history_db=history_db)
    resp = await service.submit_txt2img(req)
    return {"task_id": resp.task_id, "status": "queued", "engine": edit_engine}


def _build_session_store() -> InMemorySessionStore:
    """会话存储：优先 SQLite 持久化（重启不丢会话与参数状态），失败回落内存版。

    持久化不可用（磁盘只读/目录不可建/DB 被占）时**不能让整个 Agent 不可用**——
    降级为内存版并显式告警，行为与 P0 骨架一致。
    """
    try:
        return SqliteSessionStore(default_session_db_path())
    except Exception:  # noqa: BLE001 — 持久化失败一律降级，不阻断对话
        logger.warning("Agent 会话持久化不可用，回落内存版（重启即丢会话）", exc_info=True)
        return InMemorySessionStore()


def _get_orchestrator(request: Request) -> AgentOrchestrator:
    """懒创建 orchestrator(缓存于 app.state,测试可预注入替身)。"""
    existing = getattr(request.app.state, "agent_orchestrator", None)
    if existing is not None:
        return existing

    # 引擎冷启动提示（评估报告 C-8）依赖 model_status SSE；而引擎的常态加载发生在
    # 任务 worker 里（不经过 /api/engine/load），故必须在应用装配期就把观察者挂上，
    # 否则首个生成请求的"模型加载中"事件永远不会推送。幂等，重复调用无副作用。
    ensure_model_status_sse_observer()

    loras = _list_lora_names()
    orchestrator = AgentOrchestrator(
        llm=LLMClient(),
        tool_executor=lambda name, args: _execute_tool(request.app, name, args),
        store=_build_session_store(),
        engines=[DEFAULT_ENGINE],
        loras=loras,
        mode=MODE_AUTO,
    )
    request.app.state.agent_orchestrator = orchestrator
    return orchestrator


@router.get("/health")
async def agent_health(request: Request) -> dict[str, Any]:
    """GET /api/agent/health — LLM 大脑在线状态(供 UI 提示,不抛异常)。"""
    orchestrator: AgentOrchestrator | None = getattr(request.app.state, "agent_orchestrator", None)
    llm = orchestrator.llm if orchestrator is not None else LLMClient()
    llm_ok = await llm.health_check()
    return {
        "llm_ok": llm_ok,
        "llm_base_url": llm.config.base_url,
        "llm_model": llm.config.model,
        "mode": getattr(orchestrator, "mode", MODE_AUTO) if orchestrator else MODE_AUTO,
    }


@router.post("/chat")
async def agent_chat(req: AgentChatRequest, request: Request) -> StreamingResponse:
    """POST /api/agent/chat — 对话 → SSE 事件流。CSRF 中间件统一校验 X-CSRF-Token。

    事件**边产边推**（``run_turn_stream`` 是 async generator）：LLM 的正文增量以
    ``delta`` 事件即时下发，首字延迟不再等于整轮耗时；工具调用/参数卡片/成图
    等事件同样即时可见。

    M2 多模态：请求体可带 ``images``（路径已过 PathGuard 白名单，越权返回 422）。
    图片会经 orchestrator 的视觉上下文通道编码后注入，并先发一条 ``vlm_context`` 事件
    上报状态（ok / unavailable / error），前端据此决定是否展示「已附带图片」。
    """
    # 路径校验放在建流之前：越权路径以 422 明确拒绝，而不是混进 SSE 错误流里
    image_refs = _validate_images(req.images)
    orchestrator = _get_orchestrator(request)

    async def event_stream() -> AsyncIterator[str]:
        try:
            async for event in orchestrator.run_turn_stream(req.session_id, req.message, req.mode, images=image_refs):
                payload = {"type": event.type, **event.data}
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        except LLMError as exc:
            logger.warning("Agent LLM 不可用: %s", exc)
            yield f"data: {json.dumps({'type': 'error', 'text': f'LLM 大脑不可用: {exc}'}, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001 — SSE 兜底,保证流以 error 事件收尾
            logger.exception("Agent 内部错误")
            yield f"data: {json.dumps({'type': 'error', 'text': f'Agent 内部错误: {exc}'}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/confirm")
async def agent_confirm(req: AgentConfirmRequest, request: Request) -> dict[str, Any]:
    """POST /api/agent/confirm — 双模式参数卡片:approve 才真正入队,reject 直接丢弃。

    入队仍走 ``_execute_tool`` → ``GenerationService.submit_txt2img``(队列化),
    不新增旁路;用户手改的参数经 ``approve_proposal`` 内的白名单 + 范围钳制。
    """
    orchestrator = _get_orchestrator(request)
    if req.action == "reject":
        try:
            return orchestrator.reject_proposal(req.session_id, req.proposal_id)
        except ProposalError as exc:
            raise HTTPException(400, detail=str(exc)) from exc

    try:
        return await orchestrator.approve_proposal(req.session_id, req.proposal_id, req.params)
    except ProposalError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    except ValueError as exc:  # 参数被改成非法值(如清空提示词)→ 400 而不是 500
        raise HTTPException(400, detail=str(exc)) from exc


__all__ = [
    "router",
    "AgentChatRequest",
    "AgentConfirmRequest",
    "_execute_tool",
    "_get_orchestrator",
]
