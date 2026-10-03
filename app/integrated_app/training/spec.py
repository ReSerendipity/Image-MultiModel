"""training/spec.py — LoRA 训练任务规格与 AI-Toolkit job 配置渲染。

T-13「状态回写薄层」的输入侧：把一次训练请求落成 AI-Toolkit 能吃的 job 配置
（``run.py <job.yaml>``），并做**提交前校验**，避免把明显坏的参数送进一个要跑
几十分钟的训练进程才失败。

设计前提（2026-10-02 实证，见 ``docs/roadmap/P3-lora-training.md`` / GOTCHAS #46）：

- 本机 Z-Image 走 comfy 单文件权重 + HF 布局 extras（``extras_name_or_path``）；
- AI-Toolkit **不剥** comfy 的 ``model.diffusion_model.`` 前缀（探针侧已在内存
  改键适配），因此本薄层**不负责权重格式适配**，只负责编排与状态回写；
- ``logging.use_ui_logger=true`` 会让 AI-Toolkit 把每一步的 loss 写进
  ``<save_root>/loss_log.db``（sqlite），薄层据此做结构化进度回写，
  而不是去爬 tqdm 行（见 GOTCHAS #48）。

本模块**不改动**任何 comfy/diffusers 权重，也不执行训练。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# AI-Toolkit 自带的 Z-Image 实现（toolkit/models/v2/diffusion_models/z_image.py）
DEFAULT_ARCH = "zimage"

# job 名会作为 AI-Toolkit 的存档子目录名（save_root = training_folder/<name>），
# 必须能安全用于文件系统与 YAML 标量。
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")

# resolution 只接受 16 的倍数（分桶/VAE/latent 对齐的实操下限），
# 且必须落在训练显存能承受的区间（RTX 5070 Ti Laptop 11.9GB，见 T-12 实跑记录）。
_RESOLUTION_MIN = 256
_RESOLUTION_MAX = 2048
_RESOLUTION_STEP = 16

# sample 尺寸与训练分辨率解耦：采样可以更大，但同样受 16 倍数约束
_SAMPLE_SIZE_MIN = 256
_SAMPLE_SIZE_MAX = 2048


class TrainSpecError(ValueError):
    """训练规格校验失败（提交前就拒绝，不进训练进程）。"""


@dataclass
class TrainJobSpec:
    """一次 LoRA 训练任务的完整规格。

    Attributes:
        name: job 名（同时是 AI-Toolkit 存档子目录名、产出 LoRA 的基名）。
        model_path: 训练底座（comfy 单文件 safetensors，如 Z-Image turbo fp8）。
        extras_path: HF 布局的 extras 目录（transformer/text_encoder/vae/tokenizer）。
        dataset_folder: 数据集目录（含 <stem>.txt caption）。
        arch: AI-Toolkit 模型 arch，默认 ``zimage``（唯一已实证的）。
        resolution: 训练分辨率（正方形，16 的倍数）。
        steps: 训练步数。
        batch_size / gradient_accumulation: 有效 batch = 二者之积。
        lr / optimizer / dtype: 优化器与精度（默认值对齐 T-12 smoke job）。
        net_dim / net_alpha: LoRA rank 与 alpha。
        train_unet / train_text_encoder: 是否训练文本编码器（默认不训，省显存）。
        gradient_checkpointing / cache_text_embeddings / cache_latents_to_disk:
            显存与缓存开关。
        low_vram: AI-Toolkit 的 low_vram 模式（11.9GB 笔记本必需）。
        save_every / max_step_saves_to_keep: 中间存档节奏与保留数。
        sample_*: 采样验证配置（AI-Toolkit 训练中途自带的 sample）。
        logging_log_every: 写 loss_log.db 的节奏（每 N 步）。
    """

    name: str
    model_path: str
    extras_path: str
    dataset_folder: str

    arch: str = DEFAULT_ARCH
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
    sample_prompts: list[str] = field(default_factory=list)

    logging_log_every: int = 10

    # ── 校验 ──────────────────────────────────────────────
    def validate(self) -> TrainJobSpec:
        """逐项校验；任何一项不合法抛 :class:`TrainSpecError`。

        校验在**提交前**完成，坏参数不会进到训练进程里才炸
        （T-12 实跑一次 22 分钟，不能每次都靠跑一遍才发现路径写错）。
        """
        self._check_name()
        self._check_paths()
        self._check_numbers()
        self._check_samples()
        return self

    def _check_name(self) -> None:
        if not self.name or not _NAME_RE.match(self.name):
            raise TrainSpecError(
                f"name 非法：{self.name!r}（只接受字母数字开头、长度 ≤64，"
                f"允许 _ - . ；该名字会作为 AI-Toolkit 的存档目录名）"
            )

    def _check_paths(self) -> None:
        for label, raw in (
            ("model_path", self.model_path),
            ("extras_path", self.extras_path),
            ("dataset_folder", self.dataset_folder),
        ):
            if not raw:
                raise TrainSpecError(f"{label} 为空")
            p = Path(raw)
            if not p.is_absolute():
                raise TrainSpecError(f"{label} 必须是绝对路径（收到 {raw!r}）")
            if not p.exists():
                raise TrainSpecError(f"{label} 路径不存在：{raw}")

        # model_path 必须是权重文件，extras/dataset 必须是目录
        if not Path(self.model_path).is_file():
            raise TrainSpecError(f"model_path 不是文件：{self.model_path}")
        for label in ("extras_path", "dataset_folder"):
            if not Path(getattr(self, label)).is_dir():
                raise TrainSpecError(f"{label} 不是目录：{getattr(self, label)}")

    def _check_numbers(self) -> None:
        if not 1 <= self.resolution <= _RESOLUTION_MAX:
            raise TrainSpecError(f"resolution 越界：{self.resolution}（允许 {_RESOLUTION_MIN}~{_RESOLUTION_MAX}）")
        if self.resolution % _RESOLUTION_STEP != 0:
            raise TrainSpecError(f"resolution 必须是 {_RESOLUTION_STEP} 的倍数（{self.resolution}）")
        for label in ("steps", "batch_size", "gradient_accumulation", "net_dim", "net_alpha", "save_every"):
            value = getattr(self, label)
            if value < 1:
                raise TrainSpecError(f"{label} 必须 ≥1（收到 {value}）")
        if self.lr <= 0:
            raise TrainSpecError(f"lr 必须 >0（收到 {self.lr}）")
        if not self.arch:
            raise TrainSpecError("arch 为空")
        if self.dtype not in ("bf16", "float16", "float32"):
            raise TrainSpecError(f"dtype 只支持 bf16/float16/float32（收到 {self.dtype}）")
        if self.save_every > self.steps:
            # 不是错误，只是没有中间存档；给出提示级降级（不改语义）
            self.save_every = self.steps

    def _check_samples(self) -> None:
        if self.sample_width == self.sample_height == 0:
            return
        for label in ("sample_width", "sample_height"):
            value = getattr(self, label)
            if not _SAMPLE_SIZE_MIN <= value <= _SAMPLE_SIZE_MAX:
                raise TrainSpecError(f"{label} 越界：{value}（允许 {_SAMPLE_SIZE_MIN}~{_SAMPLE_SIZE_MAX}）")
        if self.sample_steps < 1:
            raise TrainSpecError(f"sample_steps 必须 ≥1（收到 {self.sample_steps}）")
        if not self.sample_prompts:
            # 空 prompts 会让 AI-Toolkit 用内置默认 prompt，属合法但需显式知会
            self.sample_prompts = []

    # ── 渲染 ──────────────────────────────────────────────
    def to_job_config(self, training_folder: str | Path) -> dict[str, Any]:
        """渲染 AI-Toolkit 的 job 配置（与 T-12 实跑过的结构一致）。

        Args:
            training_folder: AI-Toolkit 的 ``process.training_folder``，薄层传入
                ``<data>/training/<job_id>``（产出落在 ``<job_id>/<name>/``）。

        Returns:
            可直接 ``yaml.safe_dump`` 的 job 字典（键序与 T-12 实跑 job 对齐）。
        """
        training_folder = str(Path(training_folder))
        sample = {
            "sampler": self.noise_scheduler,
            "sample_every": self.sample_every,
            "sample_start_step": self.sample_start_step,
            "width": self.sample_width,
            "height": self.sample_height,
            "prompts": list(self.sample_prompts) or [" "],
            "neg": "",
            "seed": self.sample_seed,
            "walk_seed": False,
            "guidance_scale": self.guidance_scale,
            "sample_steps": self.sample_steps,
        }
        return {
            "job": "extension",
            "config": {
                "name": self.name,
                "process": [
                    {
                        "type": "sd_trainer",
                        "training_folder": training_folder,
                        "device": self.device,
                        "network": {"type": "lora", "linear": self.net_dim, "linear_alpha": self.net_alpha},
                        "save": {
                            "dtype": "float16",
                            "save_every": self.save_every,
                            "max_step_saves_to_keep": self.max_step_saves_to_keep,
                        },
                        "datasets": [
                            {
                                "folder_path": self.dataset_folder,
                                "caption_ext": "txt",
                                "caption_dropout_rate": 0.0,
                                "shuffle_tokens": False,
                                "cache_latents_to_disk": self.cache_latents_to_disk,
                                "resolution": [self.resolution],
                            }
                        ],
                        "train": {
                            "batch_size": self.batch_size,
                            "steps": self.steps,
                            "gradient_accumulation": self.gradient_accumulation,
                            "train_unet": self.train_unet,
                            "train_text_encoder": self.train_text_encoder,
                            "gradient_checkpointing": self.gradient_checkpointing,
                            "noise_scheduler": self.noise_scheduler,
                            "optimizer": self.optimizer,
                            "lr": self.lr,
                            "dtype": self.dtype,
                            "cache_text_embeddings": self.cache_text_embeddings,
                        },
                        "model": {
                            "name_or_path": self.model_path,
                            "extras_name_or_path": self.extras_path,
                            "arch": self.arch,
                            "quantize": False,
                            "low_vram": self.low_vram,
                        },
                        "sample": sample,
                        # 结构化进度回写的开关：AI-Toolkit 会写 <save_root>/loss_log.db
                        "logging": {
                            "use_ui_logger": True,
                            "log_every": self.logging_log_every,
                            "verbose": True,
                        },
                    }
                ],
            },
            "meta": {"name": "[name]", "version": "1.0"},
        }

    def render_yaml(self, training_folder: str | Path) -> str:
        """把 job 配置渲染成 YAML 文本。"""
        import yaml

        return yaml.safe_dump(self.to_job_config(training_folder), allow_unicode=True, sort_keys=False)

    def to_dict(self) -> dict[str, Any]:
        """序列化为可入库的 dict（去掉私有属性，保持与 dataclass 字段一致）。"""
        return asdict(self)
