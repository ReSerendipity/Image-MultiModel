"""
tests/native/test_vlm_engine.py — VlmEngine 单元测试（P2-vlm-chat M1）

覆盖：role 分发、权重单例缓存（acquire/release + 空闲定时器）、优先级卸载
request_vlm_unload、以及 mock 下的 infer_chat 编排；另有一条针对 config.yaml 真实配置的
**离线可跑**断言（不加载 9.35GB 权重，只验证路径解析）。

全部不依赖 GPU / 真实权重。M1 返工（2026-10-02）把推理路径从 transformers 换成
comfy_kernel（``comfy.sd.load_clip`` → ``comfy.sd.CLIP``），故 mock 由 FakeModel/FakeProcessor
改为 FakeClip。
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from integrated_app.model_registry import ModelRegistry
from integrated_app.native import vlm_engine
from integrated_app.native.vlm_engine import VlmEngine, request_vlm_unload


# ── 假 comfy CLIP（mock comfy.sd.CLIP）────────────────────────
class FakeClip:
    """记录调用面并返回可预测结果的 ``comfy.sd.CLIP`` 替身。"""

    calls: list[str] = []

    def __init__(self) -> None:
        self.calls = []
        self.generated = [11, 12, 13]

    def tokenize(self, text: str, **kwargs: object) -> dict:
        self.calls.append(("tokenize", text, kwargs.get("image")))
        return {"clip_qwen3vl_8b": [[(151655, 1.0), (972, 1.0)]]}

    def generate(self, tokens: object, **kwargs: object) -> list[int]:
        self.calls.append(("generate", kwargs.get("max_length")))
        return self.generated

    def decode(self, token_ids: object, skip_special_tokens: bool = True) -> str:
        self.calls.append(("decode", list(token_ids)))
        return "fake vlm answer"


@pytest.fixture
def fake_load(monkeypatch):
    """把 VlmEngine._load_model 替换成返回假 comfy CLIP，避免真实加载 9.35GB 权重。"""

    def _fake_load(self) -> dict:
        return {
            "model": FakeClip(),
            "processor": None,
            "ref_count": 0,
            "last_used": 0.0,
            "timer": None,
        }

    monkeypatch.setattr(VlmEngine, "_load_model", _fake_load)


@pytest.fixture
def fake_dir(monkeypatch, tmp_path):
    """把 _resolve_qwen3vl_weight 替换成返回临时路径，避免依赖真实权重文件。"""
    monkeypatch.setattr(vlm_engine, "_resolve_qwen3vl_weight", lambda engine_cfg, cfg: str(tmp_path))
    return tmp_path


@pytest.fixture
def tiny_png(tmp_path) -> str:
    """生成一张 4x2 的 PNG，供图片批构造用例使用。"""
    import numpy as np
    from PIL import Image

    path = tmp_path / "tiny.png"
    Image.fromarray(np.full((2, 4, 3), 128, dtype=np.uint8)).save(path)
    return str(path)


# ── role 分发 ────────────────────────────────────────────────
def test_registry_dispatches_vlm_engine(monkeypatch):
    # 测试环境常置 IMM_FAKE_ENGINE=1 使工厂返回 FakeEngine；此处取消以验证真实分发。
    monkeypatch.delenv("IMM_FAKE_ENGINE", raising=False)
    eng = ModelRegistry().create_engine_instance(
        engine_name="qwen3_vl_8b_native",
        backend="native",
        config={"backend": "native", "role": "vlm"},
    )
    assert isinstance(eng, VlmEngine)


def test_registry_dispatches_native_engine_without_role(monkeypatch):
    monkeypatch.delenv("IMM_FAKE_ENGINE", raising=False)
    eng = ModelRegistry().create_engine_instance(
        engine_name="z_image_turbo_native",
        backend="native",
        config={"backend": "native", "role": ""},
    )
    from integrated_app.native.engine import NativeEngine

    assert isinstance(eng, NativeEngine)


# ── 权重解析（离线可跑，不碰权重文件本身）────────────────────
def test_resolve_weight_hits_real_config_file():
    """config.yaml 里声明的 sub_path 必须能解析到真实存在的 .safetensors。

    这条断言锁住「comfy_kernel 只需裸权重、不需要 config.json」这一口径：
    解析结果必须是文件而非目录。
    """
    from integrated_app.config import get_config

    cfg = get_config()
    eng = cfg.models.engines.get("qwen3_vl_8b_native")
    assert eng is not None, "config.yaml 缺少 models.engines.qwen3_vl_8b_native"
    resolved = vlm_engine._resolve_qwen3vl_weight(eng, cfg)
    assert resolved.endswith(".safetensors"), f"解析结果应为权重文件，实际 {resolved!r}"
    assert Path(resolved).is_file(), f"解析出的权重文件不存在: {resolved}"
    assert "qwen3vl" in Path(resolved).name.lower()


def test_resolve_weight_returns_empty_when_nothing_declared():
    empty = SimpleNamespace(local_model_dir="", text_encoder=None)
    assert vlm_engine._resolve_qwen3vl_weight(empty, SimpleNamespace(project_root="/nonexistent")) == ""


# ── 权重单例缓存 ────────────────────────────────────────────
def test_singleton_acquire_release(fake_load, fake_dir):
    eng = VlmEngine("qwen3_vl_8b_native", config={})
    eng._ready = True
    eng._model_dir = str(fake_dir)

    m1 = eng._acquire()
    m2 = eng._acquire()
    assert m1 is m2  # 同一单例

    eng._release()
    eng._release()  # ref_count 归零，应启动空闲定时器
    with vlm_engine._VLM_CACHE_LOCK:
        entry = vlm_engine._VLM_CACHE[str(Path(fake_dir).resolve())]
        assert entry["ref_count"] == 0
        assert isinstance(entry.get("timer"), threading.Timer)


def test_request_vlm_unload_evicts(fake_load, fake_dir):
    eng = VlmEngine("qwen3_vl_8b_native", config={})
    eng._ready = True
    eng._model_dir = str(fake_dir)
    eng._acquire()
    key = str(Path(fake_dir).resolve())
    assert key in vlm_engine._VLM_CACHE
    request_vlm_unload()
    assert key not in vlm_engine._VLM_CACHE


# ── infer_chat 编排（mock comfy）─────────────────────────────
def test_infer_chat_smoke(fake_load, fake_dir):
    eng = VlmEngine("qwen3_vl_8b_native", config={})
    eng._ready = True
    eng._model_dir = str(fake_dir)

    out = asyncio.run(eng.infer_chat("describe this image", images=["fake.png"]))
    assert out == "fake vlm answer"


def test_infer_chat_passes_image_batch_to_tokenize(fake_load, fake_dir, tiny_png):
    """图片必须被拼成 comfy 约定的 [1,H,W,3] float32(0~1) 批再交给 tokenize。"""
    eng = VlmEngine("qwen3_vl_8b_native", config={})
    eng._ready = True
    eng._model_dir = str(fake_dir)
    asyncio.run(eng.infer_chat("看这张图", images=[tiny_png]))

    clip = vlm_engine._VLM_CACHE[str(Path(fake_dir).resolve())]["model"]
    tokenize_call = [c for c in clip.calls if c[0] == "tokenize"][0]
    image = tokenize_call[2]
    assert image is not None
    assert tuple(image.shape) == (1, 2, 4, 3)
    assert str(image.dtype) in ("torch.float32", "torch.float16")
    assert float(image.min()) >= 0.0 and float(image.max()) <= 1.0


def test_infer_chat_text_only_passes_none(fake_load, fake_dir):
    eng = VlmEngine("qwen3_vl_8b_native", config={})
    eng._ready = True
    eng._model_dir = str(fake_dir)
    asyncio.run(eng.infer_chat("你好"))

    clip = vlm_engine._VLM_CACHE[str(Path(fake_dir).resolve())]["model"]
    tokenize_call = [c for c in clip.calls if c[0] == "tokenize"][0]
    assert tokenize_call[2] is None


def test_infer_chat_requires_ready(fake_load, fake_dir):
    eng = VlmEngine("qwen3_vl_8b_native", config={})
    eng._ready = False  # 未加载
    with pytest.raises(RuntimeError):
        asyncio.run(eng.infer_chat("hi"))
