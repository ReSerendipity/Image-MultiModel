"""
tests/native/test_vlm_engine.py — VlmEngine 单元测试（P2-vlm-chat M1）

覆盖：role 分发、权重单例缓存（acquire/release + 空闲定时器）、优先级卸载
request_vlm_unload、以及 mock 下的 infer_chat 编排。全部不依赖 GPU / 真实权重。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from integrated_app.model_registry import ModelRegistry
from integrated_app.native import vlm_engine
from integrated_app.native.vlm_engine import VlmEngine, _resolve_qwen3vl_dir, request_vlm_unload


# ── 假模型 / 假处理器（mock transformers）─────────────────────
class FakeInputs(dict):
    def __init__(self):
        super().__init__()
        self["input_ids"] = SimpleNamespace(shape=(1, 5))

    def to(self, device):
        return self


class FakeProcessor:
    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True):
        return "PROMPT_TEMPLATE"

    def __call__(self, text=None, images=None, videos=None, return_tensors=None):
        return FakeInputs()

    def batch_decode(self, tokens, skip_special_tokens=True):
        return ["fake vlm answer"]


class FakeModel:
    device = "cpu"

    def generate(self, **kwargs):
        # 返回长度 15 的伪 token 序列，便于 infer_chat 截取
        return [[0, 0, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]]


@pytest.fixture
def fake_load(monkeypatch):
    """把 VlmEngine._load_model 替换成返回假模型/处理器，避免真实加载。"""

    def _fake_load(self):
        return {
            "model": FakeModel(),
            "processor": FakeProcessor(),
            "ref_count": 0,
            "last_used": 0.0,
            "timer": None,
        }

    monkeypatch.setattr(VlmEngine, "_load_model", _fake_load)


@pytest.fixture
def fake_dir(monkeypatch, tmp_path):
    """把 _resolve_qwen3vl_dir 替换成返回临时目录，避免依赖真实模型目录。"""
    monkeypatch.setattr(vlm_engine, "_resolve_qwen3vl_dir", lambda engine_cfg, cfg: str(tmp_path))
    return tmp_path


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


# ── 权重单例缓存 ────────────────────────────────────────────
def test_singleton_acquire_release(fake_load, fake_dir):
    eng = VlmEngine("qwen3_vl_8b_native", config={})
    eng._ready = True
    eng._model_dir = str(fake_dir)

    m1, p1 = eng._acquire()
    m2, p2 = eng._acquire()
    assert m1 is m2 and p1 is p2  # 同一单例

    eng._release()
    eng._release()  # ref_count 归零，应启动空闲定时器
    # 空闲定时器存在
    import threading

    with vlm_engine._VLM_CACHE_LOCK:
        entry = vlm_engine._VLM_CACHE[_resolve_qwen3vl_dir(None, None) if False else str(Path(fake_dir).resolve())]
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


# ── infer_chat 编排（mock transformers）──────────────────────
def test_infer_chat_smoke(fake_load, fake_dir, monkeypatch):
    monkeypatch.setattr("transformers.AutoProcessor.from_pretrained", classmethod(lambda cls, *a, **k: FakeProcessor()))
    monkeypatch.setattr(
        "transformers.Qwen3VLForConditionalGeneration.from_pretrained",
        classmethod(lambda cls, *a, **k: FakeModel()),
    )
    eng = VlmEngine("qwen3_vl_8b_native", config={})
    eng._ready = True
    eng._model_dir = str(fake_dir)

    out = asyncio.run(eng.infer_chat("describe this image", images=["fake.png"]))
    assert out == "fake vlm answer"


def test_infer_chat_requires_ready(fake_load, fake_dir):
    eng = VlmEngine("qwen3_vl_8b_native", config={})
    eng._ready = False  # 未加载
    with pytest.raises(RuntimeError):
        asyncio.run(eng.infer_chat("hi"))
