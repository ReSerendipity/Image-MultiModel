"""qwen_image_native 接入验证（P2-multi-engine D 项，2026-10-02 已实证出图）。

覆盖（全部离线可跑，不依赖 torch/comfy/权重）：
- config.yaml 中 qwen_image_native 引擎块结构正确
  （backend=native / 声明 txt2img 能力 / latent 64x16 / unet 指向真实存在的文件）
- model_registry 对 native backend（无 role）正确分发 NativeEngine
- unet 指向真实文件、且与 edit 引擎共用同一份（架构实证）
- config 的 sampler/scheduler 与 preflight 候选表首项同步（防两处漂移）

真实前向由 `scripts/preflight_qwen_image.py` 实证（2026-10-02：
512²/8 步/euler+simple 采样 18.5s，VAE 解码落盘，出图与 prompt 吻合），
本测试不加载权重，只锁住「不依赖权重的接线事实」。
"""

from __future__ import annotations

import os
import re

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
    # unet 子路径指向本机真实文件（2026-10-02 实证：与 edit 共用同一份 UNET）
    assert (cfg.get("unet") or {}).get("sub_path") == ("Qwen-Image-2.1/qwen_image_2.1_int8_convrot.safetensors")


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


def test_qwen_image_native_unet_points_at_real_file() -> None:
    """权重就位断言（2026-10-02 反转为实证路径）。

    原语义是「本地无基座 unet ⇒ 离线阻断」。实测 `comfy/ldm/qwen_image21/model.py` 的
    ``QwenImage21Transformer2DModel.forward(..., ref_latents=None, image_slots=None)``
    里参考图 latent 是**可选**的——**同一份 UNET 既做 txt2img 也做 edit**，本机
    `qwen_image_2.1_int8_convrot.safetensors` 因此可直接文生图（已实跑出图：512²/8 步
    euler+simple）。故断言改为「config 指向的文件必须真实存在」。
    """
    cfg = _load_cfg()
    sub_path = cfg["unet"]["sub_path"]
    sub_dir = cfg["unet"]["sub_dir"]
    abs_path = os.path.abspath(os.path.join(REPO_ROOT, "pretrained_models", sub_dir, sub_path))
    assert os.path.isfile(abs_path), f"config 指向的 UNET 不存在，preflight 会退化到离线阻断分支：{abs_path}"
    # 必须与 edit 引擎指向**同一份**权重（本机仅此一份），否则这份测试就白测了
    with open(os.path.join(REPO_ROOT, "config.yaml"), encoding="utf-8") as f:
        edit_unet = yaml.safe_load(f)["models"]["engines"]["qwen_image_edit_native"]["unet"]["sub_path"]
    assert sub_path == edit_unet, "txt2img 与 edit 共用同一份 UNET（架构实证），配置不应指向不同文件"


def test_config_sampler_synced_with_preflight_candidates() -> None:
    """config 的 sampler/scheduler 必须与 preflight 候选表首项（实测出图那组）一致。

    防两处漂移：preflight 试出可用组合后会提示「回填到 config.yaml」，若有人改了
    preflight 的 COMBOS 却忘同步 config（或反之），这组断言会红。
    2026-10-02 实测：候选 (euler/simple, euler/beta, euler/sgm_uniform, dpmpp_2m/simple)
    中 euler+simple 首个即出图（512²/8 步，18.5s）。
    """
    cfg = _load_cfg()
    with open(os.path.join(REPO_ROOT, "scripts", "preflight_qwen_image.py"), encoding="utf-8") as fh:
        src = fh.read()
    m = re.search(r"COMBOS\s*=\s*\[(.*?)\]", src, re.S)
    assert m, "preflight 的 COMBOS 候选表格式变了（本测试的正则需同步）"
    first = re.search(r'\(\s*"([a-z0-9_]+)"\s*,\s*"([a-z0-9_]+)"\s*\)', m.group(1))
    assert first, "COMBOS 首项形如 ('euler', 'simple')，正则需同步"
    assert (cfg.get("sampler"), cfg.get("scheduler")) == (first.group(1), first.group(2)), (
        f"config 的 sampler/scheduler 应为 preflight 实测首项 {first.groups()}，"
        f"当前为 {(cfg.get('sampler'), cfg.get('scheduler'))}"
    )
