"""training/ — LoRA 训练编排薄层（P3 roadmap T-13）。

职责边界（只做薄层，不重复造训练器）：

- **编排**：把训练请求渲染成 AI-Toolkit 的 job 配置并拉起 ``run.py``；
- **状态回写**：任务状态落 ``data/training/jobs/<job_id>.json``，
  训练进度回读 AI-Toolkit 写的 ``loss_log.db``；
- **产物移交**：定位终稿 LoRA，并（在人工确认后）搬进 ``native/lora.py`` 可见的 LoRA 目录。

**不做**权重格式适配（comfy 前缀剥离、TE/VAE 转换已在 T-12 探针与
``scripts/preflight_zimage_lora_load.py`` 侧解决）、**不做**数据标注（AI-Toolkit
内置 captioner/dataset_tools）、**不出**训练 UI（UI 面用 AI-Toolkit 自带前端）。
"""

from .runner import TrainingRunner, TrainingUnavailable
from .spec import TrainJobSpec, TrainSpecError
from .store import TrainingStore

__all__ = ["TrainJobSpec", "TrainSpecError", "TrainingRunner", "TrainingUnavailable", "TrainingStore"]
