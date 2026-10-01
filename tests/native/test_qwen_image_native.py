"""qwen_image_native 接入脚手架验证（P2-multi-engine D 项，权重阻断待补）。

覆盖（全部离线可跑，不依赖 torch/comfy/权重）：
- config.yaml 中 qwen_image_native 引擎块结构正确
  （backend=native / 声明 txt2img 能力 / latent 64x16 / 基座 unet 子路径已声明）
- model_registry 对 native backend（无 role）正确分发 NativeEngine
- 离线权重阻断：本地基座 unet 文件不存在（preflight 将退出码 2，不静默降级）

真实前向（comfy 加载 Qwen-Image 基座 UNet + 采样出图）需本地基座权重，
由 scripts/preflight_qwen_image.py 在权重就位后实证，本测试不覆盖（离线）。
"""

from __future__ import annotations

import os

import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_cfg() -> dict:
    """读取 config.yaml 并取出 qwen_image_native 引擎块。"""
    with open(os.path.join(REPO_ROOT, "config.yaml"), encoding="utf-8") as f:
        root = yaml.safe_load(f)
    engines = root["models"]["engines"]
    assert "qwen_image_native" in engines, "config.yaml 缺少 qwen_image_native 引擎块"
    return engines["qwen_image_native"]


def test_qwen_image_native_config_well_formed() -> None:
    cfg = _load_cfg()
    assert cfg["backend"] == "native"
    feats = cfg.get("supported_features") or []
    assert "txt2img" in feats, "qwen_image_native 必须声明 txt2img 能力（NativeEngine 能力守卫依赖此）"
    assert cfg.get("latent_channels") == 64
    assert cfg.get("latent_downscale") == 16
    # 基座 unet 子路径已声明（即便权重离线缺失，配置结构应完整）
    assert (cfg.get("unet") or {}).get("sub_path") == ("Qwen-Image-2.1/qwen_image_2.1_base_int8_convrot.safetensors")


def test_registry_dispatches_native_engine_for_qwen_image(monkeypatch) -> None:
    monkeypatch.delenv("IMM_FAKE_ENGINE", raising=False)
    from integrated_app.model_registry import ModelRegistry
    from integrated_app.native.engine import NativeEngine

    eng = ModelRegistry().create_engine_instance(
        engine_name="qwen_image_native",
        display_name="Qwen-Image 2.1 (Native)",
        backend="native",
        config={"backend": "native", "role": ""},
    )
    assert isinstance(eng, NativeEngine)


def test_qwen_image_native_base_unet_offline_blocked() -> None:
    """离线阻断断言：本地基座 unet 文件不存在，preflight 应退出码 2（不静默降级）。"""
    cfg = _load_cfg()
    sub_path = cfg["unet"]["sub_path"]
    sub_dir = cfg["unet"]["sub_dir"]
    abs_path = os.path.abspath(os.path.join(REPO_ROOT, "pretrained_models", sub_dir, sub_path))
    assert not os.path.isfile(abs_path), f"本地库已含基座 unet，应改走 preflight 实证路径而非离线阻断：{abs_path}"
