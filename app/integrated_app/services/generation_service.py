"""
services/generation_service.py — 文生图 / 批量生成业务编排层

对应架构评估 P0-1（Fat Controller）：把原先散落在
``routes/generate_routes.py`` 中的业务编排（引擎校验 / 内容安全过滤 /
VRAM 预检 / VRAM 水位钳制 / 血缘落库 / 过载策略 / 队列提交 / 成本埋点）
下沉到 Service 层，使路由仅承担「API 契约 + 参数绑定 + 响应装配」。

设计要点：
- Service 通过构造函数注入 ``task_queue`` / ``history_db`` / ``config``，
  不再依赖 ``request.app.state``，可脱离 FastAPI 直接单测；
- 请求/响应 Pydantic 模型随之下沉（API 契约单一事实来源），
  路由层 re-export 以保证既有导入路径不变；
- 业务拒绝路径仍抛 ``HTTPException``（与重构前逐字节一致的
  status / detail / headers），保证对外契约零回归。
"""

from __future__ import annotations

import asyncio
import base64
import io
import itertools
import logging
import os
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field

from ..config import get_config
from ..cost_governance import get_vram_scheduler
from ..engine_interface import GenerationConfig
from ..gpu_utils import preflight_vram
from ..i18n import get_error_message
from ..lineage import compute_lora_checksums, compute_workflow_version
from ..middleware.request_id import get_request_id
from ..model_compat import is_lora_compatible
from ..observability.generation_metrics import (
    record_generation_accepted,
    record_generation_rejected,
    record_generation_submitted,
)
from ..observability.metrics import get_metrics
from ..overload_policy import evaluate_overload, fill_ratio_of
from ..task_queue import Task, TaskQueue

logger = logging.getLogger(__name__)


# ── 请求 / 响应模型（API 契约）────────────────────────────────
class GenerateRequest(BaseModel):
    """POST /api/generate 请求体"""

    # 8 基础
    positive_prompt: str = ""
    negative_prompt: str = ""
    cfg: float = 1.0
    steps: int = 8
    width: int = 1024
    height: int = 1024
    seed: int = -1
    batch_size: int = 1
    # LoRA 6 层
    lora_1_name: str = ""
    lora_1_strength: float = 1.0
    lora_2_name: str = ""
    lora_2_strength: float = 0.7
    lora_3_name: str = ""
    lora_3_strength: float = 0.5
    lora_4_name: str = ""
    lora_4_strength: float = 0.4
    lora_5_name: str = ""
    lora_5_strength: float = 0.3
    lora_6_name: str = ""
    lora_6_strength: float = 0.2
    # SeedVR2
    seedvr2_enable: bool = True
    seedvr2_resolution: int = 2048
    seedvr2_seed: int = -1
    seedvr2_color_correction: str = "lab"
    # Eses
    eses_enable: bool = True
    eses_compare_axis: str = "horizontal"
    # VRAM
    vram_enable: bool = True
    vram_reserved_gb: float = 0.6
    vram_mode: str = "auto"
    vram_seed: int = -1
    # 输出
    output_format: str = "png"
    output_prefix: str = ""
    # 引擎
    engine_name: str | None = None
    # 参考图（可选，用于生成前 CLIP 安全检测；二选一，均可为空，为空则跳过图检）
    reference_image_path: str | None = None  # 服务端图片路径（须在 PathGuard 白名单内）
    reference_image_b64: str | None = None  # Base64 图片数据（含或不含 data: 前缀）
    # 编辑模式（P1 Qwen-Image 2.1 Edit）：True 时参考图作为**编辑输入**（task mode=edit），
    # False 时参考图仅用于安全图检（历史行为）。引擎须声明 supported_features 含 edit。
    edit_mode: bool = False
    edit_resolution: int = 1024  # 参考图缩放目标边长（0 = 按原图）
    # 幂等键（P3-10）：客户端重传同一 key 时复用首次任务，避免重复生成
    idempotency_key: str | None = None


class GenerateResponse(BaseModel):
    task_id: str
    status: str = "pending"
    estimated_time_s: float | None = None
    estimated_vram_gb: float | None = None
    warning: str | None = None
    # 命中幂等缓存时置 True，前端可据此提示「复用已有任务」
    deduplicated: bool = False


class BatchGenerateRequest(BaseModel):
    """POST /api/generate/batch 请求体"""

    prompts: list[str] = Field(default_factory=list)  # Prompt 列表
    prompt_file: str | None = None  # Prompt 文件路径
    grid_dimensions: dict[str, list[Any]] = Field(default_factory=dict)  # Grid 6 维
    base_config: GenerateRequest = Field(default_factory=GenerateRequest)
    # 幂等键（P3-10）：与 base_config 无关，作用于整批
    idempotency_key: str | None = None


# ── 辅助：过载策略 / 参考图解析 ────────────────────────────────
def maybe_reject_overload(task_queue: TaskQueue, cfg: Any, batch_size: int) -> None:
    """P1-8 分级过载策略：入队前评估队列填充率，必要时抛 HTTPException。

    - 70%：仅观察（proceed）
    - 85%：大 batch 快速拒绝 429 + Retry-After
    - 95%：快速拒绝 429 + Retry-After
    - 100%：明确 503

    在创建 history 记录之前调用，避免孤儿记录。
    """
    maxsize = cfg.runtime.task_queue.maxsize
    fill = fill_ratio_of(task_queue.queue_size, maxsize)
    decision = evaluate_overload(fill, batch_size)
    if decision.action == "proceed":
        return
    record_generation_rejected(decision.reason)
    get_metrics().queue_rejected_total.inc(1.0, reason=decision.reason)
    headers = {"Retry-After": str(decision.retry_after_s)} if decision.retry_after_s else None
    raise HTTPException(status_code=decision.status, detail=decision.message, headers=headers)


def resolve_reference_image(req: GenerateRequest, cfg: Any) -> str | None:
    """解析请求中的参考图，返回可供 CLIP 检测的本地文件路径。

    无参考图（两个字段均为空）→ None，跳过 CLIP 图检（保持原有行为）。
    reference_image_path → PathGuard 校验 + 存在性检查（对齐 /api/safety/check-image）。
    reference_image_b64 → 解码 + 体积/像素上限 + 魔数校验 + PIL verify 后落盘。

    Raises:
        HTTPException: 字段冲突(400) / 路径不安全(403) / 文件不存在(404) / 解码失败(400)。
    """
    if req.reference_image_path and req.reference_image_b64:
        raise HTTPException(
            400,
            detail="Provide either reference_image_path or reference_image_b64, not both",
        )

    if req.reference_image_path:
        from ..security.path_guard import PathGuard, PathGuardError

        guard = PathGuard(cfg.security.allowed_base_dirs, cfg.project_root)
        try:
            safe_path = guard.resolve(req.reference_image_path)
        except PathGuardError:
            raise HTTPException(
                403,
                detail=get_error_message("path_traversal", path=req.reference_image_path),
            )
        if not safe_path.exists():
            raise HTTPException(
                404,
                detail=get_error_message("file_not_found", path=req.reference_image_path),
            )
        return str(safe_path)

    if req.reference_image_b64:
        b64 = req.reference_image_b64
        if b64.startswith("data:") and "," in b64:
            b64 = b64.split(",", 1)[1]
        try:
            img_data = base64.b64decode(b64)
        except Exception as e:
            raise HTTPException(400, detail=f"Reference image decode failed: {e}")

        # M-03: 体积 + 解压炸弹（像素）上限校验，超过即 413
        from ..security.upload_limits import enforce_upload_limits

        enforce_upload_limits(img_data, cfg.output.uploads.max_size_mb, cfg.output.uploads.max_pixels)

        # SECURITY: 魔数校验（对齐 preprocess_routes），阻断伪装/非图片数据
        from ..security.magic_check import validate_image_magic

        is_magic, _detected_type, error = validate_image_magic(img_data)
        if not is_magic:
            raise HTTPException(400, detail=f"Reference image decode failed: {error}")

        try:
            from PIL import Image

            img = Image.open(io.BytesIO(img_data))
            img.verify()  # 校验内容完整性（防"伪图片头但损坏内容"）
            img = Image.open(io.BytesIO(img_data))
            cache_dir = Path(cfg.project_root) / cfg.output.uploads.cache_dir
            cache_dir.mkdir(parents=True, exist_ok=True)
            safe_path = cache_dir / f"refcheck_{uuid.uuid4().hex}.png"
            img.convert("RGB").save(str(safe_path), format="PNG")
            return str(safe_path)
        except Exception as e:
            raise HTTPException(400, detail=f"Reference image decode failed: {e}")

    return None


# ── 业务编排服务 ───────────────────────────────────────────────
class GenerationService:
    """文生图 / 批量生成业务编排（Controller 与 Repository 之间的 Service 层）。"""

    def __init__(
        self,
        task_queue: TaskQueue,
        history_db: Any,
        config: Any = None,
    ) -> None:
        """构造服务。

        Args:
            task_queue: 全局单 Worker 串行任务队列。
            history_db: HistoryDB Repository 实例。
            config: AppConfig；为 None 时回落全局单例 ``get_config()``。
        """
        self._task_queue = task_queue
        self._history_db = history_db
        self._config = config if config is not None else get_config()

    # ── 单图 ──────────────────────────────────────────────────
    async def submit_txt2img(self, req: GenerateRequest) -> GenerateResponse:
        """提交 txt2img 任务：校验 → 安全过滤 → 预检 → 落库 → 入队。

        Raises:
            HTTPException: 与重构前一致（404/400/403/429/503）。
        """
        cfg = self._config
        engine_name = req.engine_name or cfg.models.default_engine

        # 幂等：同一 key 命中则复用首次任务（P3-10）——纯缓存命中不产生新任务，
        # 故排在空提示词拒绝之前（重放一个已受理的旧任务与本次 prompt 是否为空无关）。
        if req.idempotency_key:
            cached = _idempotency_get(req.idempotency_key)
            if cached is not None:
                logger.info("Idempotent replay for key=%s -> task %s", req.idempotency_key, cached)
                return GenerateResponse(task_id=cached, deduplicated=True)

        # 空/纯空白提示词拒绝（v1.3.0 发版阶段1 实测 P2：直连 /api/generate 曾
        # 接受空串，任务入队白占 GPU 产出无意义图；agent 路径的 guard 已拒绝，
        # 此处补 UI/直连 API 的最终闸。批次 base_config 合法留空，故不在模型层校验）。
        if not req.positive_prompt or not req.positive_prompt.strip():
            record_generation_rejected("empty_prompt")
            raise HTTPException(422, detail="positive_prompt 不能为空")

        # 引擎存在性
        if engine_name not in cfg.models.engines:
            record_generation_rejected("engine_not_found")
            raise HTTPException(404, detail=get_error_message("engine_not_found", name=engine_name))

        engine_cfg = cfg.models.engines[engine_name]

        # batch_size 边界
        if req.batch_size < 1 or req.batch_size > 9999:
            record_generation_rejected("batch_too_large")
            raise HTTPException(400, detail=get_error_message("batch_too_large"))

        # 内容安全过滤（CLIP 阻塞，卸载到线程池）
        from ..security.content_filter import filter_image_generation

        ref_image_path = resolve_reference_image(req, cfg)
        is_safe, reason = await asyncio.get_running_loop().run_in_executor(
            None,
            filter_image_generation,
            req.positive_prompt,
            ref_image_path,
            cfg.security.content_filter.fail_closed_on_clip_missing,
        )
        if not is_safe:
            record_generation_rejected("content_blocked")
            raise HTTPException(400, detail=get_error_message("content_blocked", reason=reason))

        # 显存预检
        vram_est = preflight_vram(
            engine_vram_gb=engine_cfg.vram_gb,
            width=req.width,
            height=req.height,
            batch_size=req.batch_size,
            enable_seedvr2=req.seedvr2_enable,
            fallback_precision=engine_cfg.fallback_precision,
            default_precision=engine_cfg.default_precision,
            multisample_rule=cfg.inference.vram_multisample_rule,
            headroom_gb=cfg.inference.vram_headroom_gb,
            allow_tight=cfg.inference.vram_tight_continue,
        )
        if not vram_est.can_run:
            record_generation_rejected("vram_insufficient")
            raise HTTPException(
                400,
                detail=get_error_message(
                    "vram_insufficient",
                    need=vram_est.needed_vram_gb,
                    avail=vram_est.available_vram_gb,
                ),
            )

        # VRAM 水位感知动态 batch 上限
        # 注：假引擎（IMM_FAKE_ENGINE=1）不消耗显存，钳制无意义；且真实 GPU 空闲水位
        # 在测试/CI 环境波动会导致 batch_size 被随机钳制，使生成结果不确定（flaky）。
        scheduler = get_vram_scheduler()
        if scheduler.enabled and os.environ.get("IMM_FAKE_ENGINE") != "1":
            clamped = scheduler.clamp(req.batch_size)
            if clamped != req.batch_size:
                logger.info("VRAM scheduler clamped batch_size %s -> %s", req.batch_size, clamped)
                req.batch_size = clamped

        gen_config = self._build_generation_config(req, engine_name, engine_cfg, init_image=ref_image_path)

        # 编辑模式守卫（P1）：参考图必须真正交给引擎，且引擎须声明 edit 能力，
        # 否则请求会被静默降级成普通文生图（用户看到的是"没参考图"的结果）。
        task_mode = "txt2img"
        if req.edit_mode:
            if "edit" not in (engine_cfg.supported_features or []):
                raise HTTPException(422, detail=f"Engine '{engine_name}' does not support image editing")
            if not ref_image_path:
                raise HTTPException(422, detail="edit_mode requires reference_image_path or reference_image_b64")
            task_mode = "edit"

        # P3-9 强制 LoRA 兼容性矩阵：不兼容的 LoRA 直接拒绝，避免无效推理占用 GPU
        self._validate_lora_compatibility(engine_cfg, gen_config.effective_lora_stack())

        # P1-8 分级过载策略：入队前评估，避免创建孤儿 history 记录
        maybe_reject_overload(self._task_queue, cfg, req.batch_size)
        task_id = self._task_queue.generate_task_id()
        # 提交→worker 边界最小关联键：随 Task 元组传入队列，worker 线程
        # 执行期绑定同一 ContextVar，日志 req=<同一id> 可串联整条链路。
        request_id = get_request_id()

        task = Task(
            task_id=task_id,
            engine=engine_name,
            config=gen_config.to_dict(),
            mode=task_mode,
            request_id=request_id,
        )

        # 血缘落库（P3-10 之前：先落库再入队，失败则补偿删除，见 submit 结果处理）
        self._history_db.create_task(
            task_id=task_id,
            engine=engine_name,
            mode=task_mode,
            prompt=req.positive_prompt,
            negative_prompt=req.negative_prompt,
            generation_config=gen_config.to_dict(),
            workflow_version=compute_workflow_version(engine_cfg, cfg.project_root),
            lora_checksums=compute_lora_checksums(gen_config.effective_lora_stack(), cfg),
            request_id=request_id,
        )

        record_generation_submitted(engine_name)
        success = await self._task_queue.submit(task)
        if not success:
            # P2-8：入队失败则回滚已创建的 history 记录，避免孤儿任务
            self._rollback_task(task_id)
            record_generation_rejected("queue_full")
            get_metrics().queue_rejected_total.inc(1.0, reason="full")
            raise HTTPException(503, detail=get_error_message("task_queue_full"))

        record_generation_accepted(engine_name)
        if req.idempotency_key:
            _idempotency_put(req.idempotency_key, task_id)

        est_time = req.batch_size * (2.0 + (3.0 if req.seedvr2_enable else 0))
        return GenerateResponse(
            task_id=task_id,
            status="pending",
            estimated_time_s=est_time,
            estimated_vram_gb=vram_est.needed_vram_gb,
            warning=vram_est.warning or None,
        )

    # ── 批量 ──────────────────────────────────────────────────
    async def submit_batch(self, req: BatchGenerateRequest) -> dict[str, Any]:
        """提交批量任务：Prompt 文件 × Grid 6 维笛卡尔积展开后逐条入队。"""
        cfg = self._config
        engine_name = req.base_config.engine_name or cfg.models.default_engine

        if req.idempotency_key:
            cached = _idempotency_get(req.idempotency_key)
            if cached is not None:
                logger.info("Idempotent batch replay key=%s", req.idempotency_key)
                return {"batch_id": cached, "total_tasks": 0, "task_ids": [], "deduplicated": True}

        if engine_name not in cfg.models.engines:
            record_generation_rejected("engine_not_found")
            raise HTTPException(404, detail=get_error_message("engine_not_found", name=engine_name))

        if req.base_config.batch_size < 1 or req.base_config.batch_size > 9999:
            record_generation_rejected("batch_too_large")
            raise HTTPException(400, detail=get_error_message("batch_too_large"))

        prompts = req.prompts
        if req.prompt_file:
            from ..security.path_guard import PathGuard

            guard = PathGuard(cfg.security.allowed_base_dirs, cfg.project_root)
            try:
                path = guard.resolve(req.prompt_file)
                prompts = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            except Exception as e:
                # 同 preset_routes：异常文本不外泄，细节入日志
                logger.warning("批量 prompt_file 读取失败 file=%r: %s", req.prompt_file, e, exc_info=True)
                raise HTTPException(400, detail="Cannot read prompt file") from e

        grid = req.grid_dimensions
        grid_keys = list(grid.keys())
        grid_values = [grid[k] for k in grid_keys]
        grid_combos = list(itertools.product(*grid_values)) if grid_values else [()]

        # 内容安全过滤：逐条过滤，任一命中即拒绝
        from ..security.content_filter import filter_image_generation

        ref_image_path = resolve_reference_image(req.base_config, cfg)
        for p in prompts:
            is_safe, reason = await asyncio.get_running_loop().run_in_executor(
                None,
                filter_image_generation,
                p,
                ref_image_path,
                cfg.security.content_filter.fail_closed_on_clip_missing,
            )
            if not is_safe:
                raise HTTPException(400, detail=get_error_message("content_blocked", reason=reason))

        total = len(prompts) * len(grid_combos)
        if total == 0:
            raise HTTPException(400, detail="No prompts or grid combinations provided")

        # P1-8 分级过载策略：批量本身即「大 batch」，85% 以上档位直接拒绝
        maybe_reject_overload(self._task_queue, cfg, total)
        batch_id = self._task_queue.generate_task_id()
        task_ids: list[str] = []
        # 提交→worker 边界最小关联键（与单图路径同源，批量共享同一 request_id）
        request_id = get_request_id()

        for prompt in prompts:
            for combo in grid_combos:
                gen_config_req = req.base_config.model_copy()
                gen_config_req.positive_prompt = prompt
                for i, key in enumerate(grid_keys):
                    if hasattr(gen_config_req, key):
                        setattr(gen_config_req, key, combo[i])

                # 请求层字段（edit_mode/edit_resolution/idempotency_key 等）不属于
                # GenerationConfig；from_dict 会按 dataclass 字段过滤，保证 worker 侧
                # GenerationConfig(**task.config) 不再因多余字段抛 TypeError。
                gen_config = GenerationConfig.from_dict(
                    gen_config_req.model_dump(exclude={"reference_image_path", "reference_image_b64"})
                )

                # P3-9 强制 LoRA 兼容性矩阵（逐条校验，避免整批因单条不兼容全部失败）
                self._validate_lora_compatibility(
                    cfg.models.engines[engine_name],
                    gen_config.effective_lora_stack(),
                )

                task_id = self._task_queue.generate_task_id()
                task = Task(
                    task_id=task_id,
                    engine=engine_name,
                    # 与单图路径一致：config 只存 GenerationConfig 字段。
                    # 此前直接存 GenerateRequest 的 model_dump —— 其中 edit_mode /
                    # edit_resolution / idempotency_key 等请求层字段会让 worker 的
                    # GenerationConfig(**task.config) 抛 TypeError，批量任务全挂。
                    config=gen_config.to_dict(),
                    mode="batch",
                    batch_id=batch_id,
                    request_id=request_id,
                )
                self._history_db.create_task(
                    task_id=task_id,
                    engine=engine_name,
                    mode="batch",
                    prompt=prompt,
                    generation_config=gen_config.to_dict(),
                    workflow_version=compute_workflow_version(cfg.models.engines[engine_name], cfg.project_root),
                    lora_checksums=compute_lora_checksums(gen_config.effective_lora_stack(), cfg),
                    request_id=request_id,
                )
                record_generation_submitted(engine_name)
                if await self._task_queue.submit(task):
                    record_generation_accepted(engine_name)
                    task_ids.append(task_id)
                else:
                    # P2-8：入队失败回滚该条 history 记录
                    self._rollback_task(task_id)
                    record_generation_rejected("queue_full")
                    get_metrics().queue_rejected_total.inc(1.0, reason="full")

        if req.idempotency_key:
            _idempotency_put(req.idempotency_key, batch_id)

        return {"batch_id": batch_id, "total_tasks": total, "task_ids": task_ids}

    # ── 内部辅助 ──────────────────────────────────────────────
    def _build_generation_config(
        self,
        req: GenerateRequest,
        engine_name: str,
        engine_cfg: Any,
        init_image: str | None = None,
    ) -> GenerationConfig:
        """把请求模型装配为引擎可消费的 GenerationConfig。"""
        return GenerationConfig(
            positive_prompt=req.positive_prompt,
            negative_prompt=req.negative_prompt,
            cfg=req.cfg,
            steps=req.steps,
            width=req.width,
            height=req.height,
            seed=req.seed,
            batch_size=req.batch_size,
            lora_1_name=req.lora_1_name,
            lora_1_strength=req.lora_1_strength,
            lora_2_name=req.lora_2_name,
            lora_2_strength=req.lora_2_strength,
            lora_3_name=req.lora_3_name,
            lora_3_strength=req.lora_3_strength,
            lora_4_name=req.lora_4_name,
            lora_4_strength=req.lora_4_strength,
            lora_5_name=req.lora_5_name,
            lora_5_strength=req.lora_5_strength,
            lora_6_name=req.lora_6_name,
            lora_6_strength=req.lora_6_strength,
            seedvr2_enable=req.seedvr2_enable,
            seedvr2_resolution=req.seedvr2_resolution,
            seedvr2_seed=req.seedvr2_seed,
            seedvr2_color_correction=req.seedvr2_color_correction,
            eses_enable=req.eses_enable,
            eses_compare_axis=req.eses_compare_axis,
            vram_enable=req.vram_enable,
            vram_reserved_gb=req.vram_reserved_gb,
            vram_mode=req.vram_mode,
            vram_seed=req.vram_seed,
            output_format=req.output_format,
            output_prefix=req.output_prefix,
            engine_name=engine_name,
            latent_channels=getattr(engine_cfg, "latent_channels", None),
            latent_downscale=getattr(engine_cfg, "latent_downscale", None),
            # 采样器/调度器按引擎下发：Flux.2 Klein 等非 Z-Image 架构族需显式指定
            sampler=getattr(engine_cfg, "sampler", None) or None,
            scheduler=getattr(engine_cfg, "scheduler", None) or None,
            init_image=init_image or "",
            edit_resolution=max(0, int(req.edit_resolution or 0)),
        )

    def _validate_lora_compatibility(self, engine_cfg: Any, lora_stack: list[dict]) -> None:
        """P3-9 强制 LoRA 兼容性矩阵：任一 LoRA 不兼容当前引擎即拒绝（422）。

        矩阵约定见 ``model_compat.is_lora_compatible``：显式声明的 LoRA 仅在与
        列表中的引擎组合时兼容；未声明的 LoRA 默认兼容（社区 LoRA 免注册部署）。
        """
        incompatible: list[str] = []
        for lora in lora_stack:
            if isinstance(lora, dict) and lora.get("name"):
                name = str(lora.get("name"))
                if not is_lora_compatible(engine_cfg, name):
                    incompatible.append(name)
        if incompatible:
            record_generation_rejected("lora_incompatible")
            raise HTTPException(
                422,
                detail=f"LoRA 与引擎 '{engine_cfg.name}' 不兼容：{', '.join(incompatible)}",
            )

    def _rollback_task(self, task_id: str) -> None:
        """入队失败时补偿删除 history 记录（P2-8：消除孤儿任务）。

        回滚失败仅告警，不掩盖原始的入队失败语义。
        """
        try:
            # 补偿清理（孤儿任务）应物理删除，不走回收站
            self._history_db.delete_tasks([task_id], soft=False)
        except Exception as e:  # noqa: BLE001 - 补偿失败不掩盖主错误
            logger.warning("Rollback history task %s failed: %s", task_id, e)


# ── 幂等键缓存（P3-10）────────────────────────────────────────
# 进程内 TTL 缓存：key -> task_id/batch_id。足以覆盖「客户端网络重试」这一
# 主要重复提交来源；跨进程场景需外置存储，此处刻意保持轻量。
_IDEMPOTENCY_CACHE: dict[str, tuple[float, str]] = {}
_IDEMPOTENCY_TTL_S: float = 300.0


def _idempotency_get(key: str) -> str | None:
    """返回幂等键对应的既有任务 ID；过期或不存在返回 None。"""
    import time

    hit = _IDEMPOTENCY_CACHE.get(key)
    if not hit:
        return None
    ts, value = hit
    if time.time() - ts > _IDEMPOTENCY_TTL_S:
        _IDEMPOTENCY_CACHE.pop(key, None)
        return None
    return value


def _idempotency_put(key: str, value: str) -> None:
    """写入幂等键映射，并顺带清理已过期条目（防无界增长）。"""
    import time

    now = time.time()
    for k in [k for k, (ts, _v) in _IDEMPOTENCY_CACHE.items() if now - ts > _IDEMPOTENCY_TTL_S]:
        _IDEMPOTENCY_CACHE.pop(k, None)
    _IDEMPOTENCY_CACHE[key] = (now, value)


def clear_idempotency_cache() -> None:
    """清空幂等缓存（供测试隔离使用）。"""
    _IDEMPOTENCY_CACHE.clear()


__all__ = [
    "BatchGenerateRequest",
    "GenerateRequest",
    "GenerateResponse",
    "GenerationService",
    "clear_idempotency_cache",
    "maybe_reject_overload",
    "resolve_reference_image",
]
