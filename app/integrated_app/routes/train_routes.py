"""routes/train_routes.py — 训练编排薄层的 HTTP 面（P3 roadmap T-13）

暴露的是**编排与状态**，不是训练能力本身：真正的训练由 AI-Toolkit 在独立子进程里跑，
本路由只负责「提交 / 查询 / 取消 / 看日志 / 产物移交」。

- ``GET  /api/train/status``   —— 训练后端是否就绪（AITK_ROOT / AITK_PYTHON 配置提示）
- ``POST /api/train/jobs``     —— 提交一次 LoRA 训练（立即返回 job_id，不阻塞等训练）
- ``GET  /api/train/jobs``     —— 任务列表
- ``GET  /api/train/jobs/{id}``—— 任务状态 + 进度（step / loss / 百分比）
- ``GET  /api/train/jobs/{id}/logs``     —— stdout 日志尾部
- ``GET  /api/train/jobs/{id}/artifacts``—— 产物清单（LoRA / 中间档 / 采样图）
- ``POST /api/train/jobs/{id}/cancel``   —— 取消
- ``GET  /api/train/jobs/{id}/handoff``  —— 产物移交计划（只读，告诉你会拷去哪）
- ``POST /api/train/jobs/{id}/handoff?dry_run=true`` —— 实际搬运（禁区目录写入，需人工确认）
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ..config import get_config
from ..training.dataset import validate_dataset
from ..training.handoff import final_lora_path
from ..training.runner import TrainingRunner, TrainingUnavailable
from ..training.spec import TrainJobSpec
from ..training.store import STATUS_RUNNING

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/train", tags=["training"])


class TrainJobRequest(BaseModel):
    """提交训练的请求体。

    ⚠️ 字段与 ``training.spec.TrainJobSpec`` **刻意一一对应**（有测试锁定同步），
    用 pydantic 声明是为了拿到 OpenAPI 文档与字段级校验；真正负责语义校验的是
    ``TrainJobSpec.validate()``（路径存在性 / 分辨率 16 倍数 / 数值下限等）。
    """

    name: str = Field(..., description="job 名，同时是 AI-Toolkit 存档目录名与产出 LoRA 基名")
    model_path: str = Field(..., description="训练底座（comfy 单文件 safetensors）")
    extras_path: str = Field(..., description="HF 布局 extras 目录")
    dataset_folder: str = Field(..., description="数据集目录（含同名 .txt caption）")

    arch: str = "zimage"
    resolution: int = 512
    steps: int = 10
    batch_size: int = 1
    gradient_accumulation: int = 1
    lr: float = 1e-4
    optimizer: str = "adamw"
    dtype: str = "bf16"
    net_dim: int = 4
    net_alpha: int = 4
    train_unet: bool = True
    train_text_encoder: bool = False
    gradient_checkpointing: bool = True
    cache_text_embeddings: bool = True
    cache_latents_to_disk: bool = True
    low_vram: bool = True
    device: str = "cuda:0"
    noise_scheduler: str = "flowmatch"

    save_every: int = 5
    max_step_saves_to_keep: int = 4

    sample_every: int = 10
    sample_start_step: int = 0
    sample_steps: int = 8
    sample_width: int = 512
    sample_height: int = 512
    sample_seed: int = 42
    guidance_scale: float = 1.0
    sample_prompts: list[str] = Field(default_factory=list)

    logging_log_every: int = 10


# ── 基础设施 ─────────────────────────────────────────────
def build_runner() -> TrainingRunner:
    """构造 runner（测试可 monkeypatch 本函数注入打桩实现）。"""
    cfg = get_config()
    return TrainingRunner(project_root=cfg.project_root, config=cfg)


def _runner_from_request(request: Request) -> TrainingRunner:
    """取 app.state 上缓存的 runner（与推理侧的 app 装配方式一致）。"""
    runner = getattr(request.app.state, "training_runner", None)
    if runner is None:
        runner = build_runner()
        request.app.state.training_runner = runner
    return runner


def _to_spec(payload: TrainJobRequest) -> TrainJobSpec:
    return TrainJobSpec(**payload.model_dump())


@router.get("/datasets/validate")
async def datasets_validate(
    request: Request,
    folder: str = Query(..., description="数据集目录（建议绝对路径）"),
    caption_ext: str = Query("txt", description="caption 后缀，不含点"),
    check_resolution: bool = Query(False, description="真实解码每张图：暴露损坏/报告尺寸/标分辨率异常"),
    min_size: int = Query(256, description="分辨率校验允许的最小边长"),
    max_size: int = Query(2048, description="分辨率校验允许的最大边长"),
) -> dict[str, Any]:
    """GET /api/train/datasets/validate?folder=<dir>&caption_ext=txt[&check_resolution=true]

    训练前先校验数据集（图 + 同名 caption 齐全、caption 非空）——T-14 数据准备。
    只校验、不搬运、不改写；校验失败时返回 200 + 报告（``ok:false``），
    路径非法/目录不存在传参错误才返回 400。

    ``check_resolution=true`` 时顺带真实解码每张图，报告 ``corrupt_images`` /
    ``image_sizes`` / ``resolution_issues``（解码是 IO 重活，默认不跑）。
    """
    from pathlib import Path

    path = Path(folder)
    if not path.is_absolute():
        raise HTTPException(400, detail=f"folder 必须是绝对路径（收到 {folder!r}）")
    report = validate_dataset(
        path,
        caption_ext=caption_ext,
        strict=False,
        check_resolution=check_resolution,
        min_size=min_size,
        max_size=max_size,
    )
    return report.to_dict()


# ── 状态 ─────────────────────────────────────────────────
@router.get("/status")
async def train_status(request: Request) -> dict[str, Any]:
    """GET /api/train/status — 训练后端可用性（未配置 AITK_ROOT 时给出可操作提示）"""
    runner = _runner_from_request(request)
    env = runner.describe_environment()
    jobs = runner.list_jobs()
    env["total_jobs"] = len(jobs)
    env["running"] = [j["job_id"] for j in jobs if j.get("status") == STATUS_RUNNING]
    return env


# ── 任务 ─────────────────────────────────────────────────
@router.post("/jobs")
async def submit_job(payload: TrainJobRequest, request: Request) -> dict[str, Any]:
    """POST /api/train/jobs — 提交一次 LoRA 训练（立即返回，训练在后台跑）"""
    runner = _runner_from_request(request)
    try:
        record = await asyncio.to_thread(runner.submit, _to_spec(payload))
    except TrainingUnavailable as e:
        raise HTTPException(503, detail=str(e)) from e
    except ValueError as e:  # TrainSpecError 等校验失败
        raise HTTPException(400, detail=str(e)) from e
    except RuntimeError as e:  # 已有任务在跑 / 并发冲突
        raise HTTPException(409, detail=str(e)) from e
    return record


@router.get("/jobs")
async def list_jobs(request: Request) -> dict[str, Any]:
    """GET /api/train/jobs — 训练任务列表（最近优先）"""
    runner = _runner_from_request(request)
    return {"jobs": runner.list_jobs(), "total": len(runner.list_jobs())}


@router.get("/jobs/{job_id}")
async def job_status(job_id: str, request: Request) -> dict[str, Any]:
    """GET /api/train/jobs/{id} — 状态 + 进度（step / loss / 百分比）"""
    runner = _runner_from_request(request)
    record = runner.status(job_id)
    if record is None:
        raise HTTPException(404, detail=f"训练任务不存在: {job_id}")
    return record


@router.get("/jobs/{job_id}/logs")
async def job_logs(job_id: str, request: Request, tail: int = Query(100, ge=1, le=2000)) -> dict[str, Any]:
    """GET /api/train/jobs/{id}/logs?tail=N — stdout 日志尾部"""
    runner = _runner_from_request(request)
    if runner.load(job_id) is None:
        raise HTTPException(404, detail=f"训练任务不存在: {job_id}")
    lines = await asyncio.to_thread(runner.logs, job_id, tail)
    return {"job_id": job_id, "tail": tail, "lines": lines}


@router.get("/jobs/{job_id}/artifacts")
async def job_artifacts(job_id: str, request: Request) -> dict[str, Any]:
    """GET /api/train/jobs/{id}/artifacts — 产物清单（LoRA / 中间档 / 采样图）"""
    runner = _runner_from_request(request)
    if runner.load(job_id) is None:
        raise HTTPException(404, detail=f"训练任务不存在: {job_id}")
    items = await asyncio.to_thread(runner.artifacts, job_id)
    return {"job_id": job_id, "artifacts": items}


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, request: Request) -> dict[str, Any]:
    """POST /api/train/jobs/{id}/cancel — 取消（进程终止，状态置 cancelled）"""
    runner = _runner_from_request(request)
    if runner.load(job_id) is None:
        raise HTTPException(404, detail=f"训练任务不存在: {job_id}")
    ok = await asyncio.to_thread(runner.cancel, job_id)
    if not ok:
        raise HTTPException(409, detail=f"任务已结束，无法取消: {job_id}")
    return {"job_id": job_id, "status": "cancelled"}


@router.get("/jobs/{job_id}/handoff")
async def handoff_plan(job_id: str, request: Request) -> dict[str, Any]:
    """GET /api/train/jobs/{id}/handoff — 移交计划（只读：告诉你会拷到哪个目录）"""
    runner = _runner_from_request(request)
    plan = runner.handoff_plan(job_id)
    if plan is None:
        raise HTTPException(404, detail=f"训练任务不存在: {job_id}")
    if not plan.get("found"):
        raise HTTPException(409, detail=str(plan.get("reason", "终稿 LoRA 未产出")))
    return plan


@router.post("/jobs/{job_id}/handoff")
async def handoff_copy(
    job_id: str,
    request: Request,
    dry_run: bool = Query(False, description="true=只预览不落盘"),
) -> dict[str, Any]:
    """POST /api/train/jobs/{id}/handoff?dry_run=true — 把终稿 LoRA 搬进推理侧可见目录

    目标目录是 ``pretrained_models/loras``（AGENTS.md 禁区目录），
    默认只给计划；显式调用且 ``dry_run=false`` 才真正复制。
    """
    runner = _runner_from_request(request)
    result = runner.handoff_copy(job_id, dry_run=dry_run)
    if result is None:
        raise HTTPException(404, detail=f"训练任务不存在: {job_id}")
    if not result.get("found"):
        raise HTTPException(409, detail=str(result.get("reason", "终稿 LoRA 未产出")))
    if result.get("error"):
        raise HTTPException(500, detail=str(result["error"]))
    return result


@router.get("/jobs/{job_id}/lora")
async def job_lora_path(job_id: str, request: Request) -> dict[str, Any]:
    """GET /api/train/jobs/{id}/lora — 终稿 LoRA 绝对路径（可直接喂推理栈）"""
    runner = _runner_from_request(request)
    record = runner.load(job_id)
    if record is None:
        raise HTTPException(404, detail=f"训练任务不存在: {job_id}")
    # 与 handoff/runner 同语义： training_folder + name 一次拼到存档目录。
    # **不要**读记录里的 save_root —— 那是同一个坑的另一面（预拼成
    # <job_dir>/<name>/<name> 后永远找不到终稿；测试 test_train_routes.py 抓到）。
    lora = final_lora_path(record.get("training_folder") or "", str(record.get("name") or ""))
    if lora is None:
        raise HTTPException(409, detail="终稿 LoRA 尚未产出（训练可能仍在进行）")
    return {"job_id": job_id, "lora_path": str(lora), "exists": True, "status": record.get("status")}
