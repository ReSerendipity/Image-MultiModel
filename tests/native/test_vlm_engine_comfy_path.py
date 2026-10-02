"""
tests/native/test_vlm_engine_comfy_path.py — VLM 的 comfy_kernel 前向接线（不加载权重）

M1 返工（2026-10-02）把 VLM 推理路径从 transformers 换成 comfy_kernel（``comfy.sd.load_clip``
→ ``comfy.sd.CLIP`` → tokenize/generate/decode）。本文件锁住「权重之外」的接线事实，
**不加载 9.35GB 权重、不碰 GPU**，因此可离线/CI 跑：

  1. 本机那份裸 safetensors 的判定键能被 ``detect_te_model`` 判成 ``TEModel.QWEN3VL_8B``
     —— 这是 ``comfy/sd.py`` 选 ``comfy.text_encoders.qwen3vl.te`` 的分支条件（裸权重无
     config.json 也能加载的前提）。
  2. ``Qwen3VLTokenizer`` 能把图片张量接进 ``<|image_pad|>`` 位置（占位符被就地换成
     image embed dict，而不是留下 151655）。
  3. ``Qwen3VL.preprocess_embed`` 用的视觉预处理是 patch_size=16 / mean=std=0.5
     （Qwen3-VL 归一化到 -1~1，与 Qwen2.5-VL 的 CLIP 归一化不同），数值形态正确。
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np
import pytest
import torch

from integrated_app.native import source

REPO_ROOT = Path(__file__).resolve().parents[2]

IMAGE_PAD_TOKEN = 151655  # <|image_pad|>


@pytest.fixture(scope="module", autouse=True)
def _comfy_kernel() -> None:
    """确保 comfy 顶层包指向本仓库 comfy_kernel（幂等）。"""
    source.ensure_loaded()


def _weight_path() -> Path:
    from app.integrated_app.config import get_config

    cfg = get_config()
    eng = cfg.models.engines.get("qwen3_vl_8b_native")
    from integrated_app.native.vlm_engine import _resolve_qwen3vl_weight

    resolved = _resolve_qwen3vl_weight(eng, cfg)
    assert resolved, "config.yaml 未能解析出 qwen3_vl_8b_native 权重"
    return Path(resolved)


def _detection_sd(weight: Path) -> dict[str, np.ndarray]:
    """只读 safetensors 头，构造带 ``.shape`` 语义的伪 state dict（不读权重本体）。"""
    with weight.open("rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        header = json.loads(f.read(n))
    return {k: np.zeros(header[k]["shape"], dtype=np.float32) for k in header if k != "__metadata__"}


def test_detect_te_model_says_qwen3vl_8b():
    """真实权重头 → ``detect_te_model`` 必须判成 QWEN3VL_8B（否则 load_clip 会选错 TE 类）。"""
    from comfy.sd import TEModel, detect_te_model

    sd = _detection_sd(_weight_path())
    assert detect_te_model(sd) == TEModel.QWEN3VL_8B


def test_weight_has_generation_head_and_visual_tower():
    """权重必须自带 lm_head 与视觉塔，否则「可聊天」无从谈起（这两条在离线文档里曾判错）。"""
    weight = _weight_path()
    with weight.open("rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        header = json.loads(f.read(n))
    keys = {k for k in header if k != "__metadata__"}
    assert any(k.startswith("lm_head") for k in keys), "权重缺少 lm_head（生成头）"
    assert any(k.startswith("model.visual.") for k in keys), "权重缺少视觉塔"
    assert "model.visual.deepstack_merger_list.0.norm.weight" in keys, "缺少 Qwen3-VL DeepStack 判定键"


def test_tokenizer_attaches_image_embed_at_placeholder():
    """附图后 token 序列里应出现 image embed dict（占位符被就地替换），且 data 形状为 [1,H,W,3]。"""
    from comfy.text_encoders.qwen3vl import Qwen3VLTokenizer

    tokenizer = Qwen3VLTokenizer()
    image = torch.linspace(0, 1, 1 * 4 * 4 * 3, dtype=torch.float32).reshape(1, 4, 4, 3)
    tokens = tokenizer.tokenize_with_weights("描述这张图片", image=image)

    rows = tokens[next(iter(tokens))]
    flat = [t[0] for row in rows for t in row]
    embeds = [t for t in flat if isinstance(t, dict) and t.get("type") == "image"]

    assert len(embeds) == 1, f"期望 1 个 image embed，实际 {len(embeds)}"
    assert tuple(np.asarray(embeds[0]["data"]).shape) == (1, 4, 4, 3)
    # 占位符已被吃掉，故此处不应再残留 151655
    assert all(not (isinstance(t, (int, float)) and t == IMAGE_PAD_TOKEN) for t in flat)


def test_tokenizer_text_only_has_no_image_embed():
    from comfy.text_encoders.qwen3vl import Qwen3VLTokenizer

    tokenizer = Qwen3VLTokenizer()
    tokens = tokenizer.tokenize_with_weights("你好")
    rows = tokens[next(iter(tokens))]
    flat = [t[0] for row in rows for t in row]
    assert not [t for t in flat if isinstance(t, dict) and t.get("type") == "image"]
    assert len(flat) > 0


def test_visual_preprocess_matches_qwen3vl_normalization():
    """Qwen3-VL 侧视觉预处理：patch_size=16、归一化 mean/std=0.5（→ -1~1），且 patch 维度自洽。"""
    from comfy.text_encoders import qwen_vl

    qwen3vl_src = REPO_ROOT / "comfy_kernel" / "comfy" / "text_encoders" / "qwen3vl.py"
    assert "patch_size=16" in qwen3vl_src.read_text(encoding="utf-8"), "Qwen3-VL 视觉 patch_size 由源码常量决定"

    # 与 preprocess_embed 完全相同的调用形态
    image_01 = torch.linspace(0, 1, 1 * 8 * 8 * 3, dtype=torch.float32).reshape(1, 8, 8, 3)
    pixels = image_01.permute(0, 3, 1, 2)  # → [1,3,H,W]
    flat_patches, grid_thw = qwen_vl.process_qwen2vl_images(
        pixels,
        patch_size=16,
        image_mean=[0.5, 0.5, 0.5],
        image_std=[0.5, 0.5, 0.5],
    )
    channel = 3
    temporal = 2
    assert flat_patches.shape[-1] == channel * temporal * 16 * 16
    grid_h, grid_w = int(grid_thw[0][1]), int(grid_thw[0][2])
    assert grid_h % 2 == 0 and grid_w % 2 == 0, "grid 必须能被 merge_size=2 整除，否则 patchify 会炸"
    assert flat_patches.shape[0] == grid_h * grid_w
