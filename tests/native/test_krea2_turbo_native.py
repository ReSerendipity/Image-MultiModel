"""krea2_turbo_native 接入验证（P2-multi-engine D 项，2026-10-02 已实证出图）。

覆盖（全部离线可跑，不加载 torch 之外的重依赖、不读权重）：
- config.yaml 中 ``krea2_turbo_native`` 引擎块结构正确
  （backend=native / 声明 txt2img / latent 16×Wan21 空间下采样 8 /
  unet 指向真实存在的文件 / 两处新字段 key_prefix 与 clip_type 就位）
- ``resolve_engine_load_options`` 只吐「加载选项」、不污染「路径字典」
  （后者会被 ``verify_weight_before_load`` 当文件逐个去验，见 GOTCHAS #41）
- executor 的两个加载定制入口（``_load_diffusion_model`` / ``_load_text_encoder``）
  能按 stub 断言到正确的委托行为（前缀剥离 / CLIP 枚举下发 / 缺省回落）
- NativeEngine 把 ``_model_paths`` 与 ``_load_options`` 合并后传给 executor

真实前向由 ``scripts/preflight_krea2_turbo.py`` 实证（2026-10-02：
512²/4 步/euler+simple 端到端出图，落盘 `outputs/_preflight_krea2/krea2_euler_simple.png`，
猫坐木桌与 prompt 吻合；对照实验还确认了 4D latent 会产出 61 帧废图，故 latent 必须是 5D）。
本测试不加载权重，只锁住「不依赖权重的接线事实」。
"""

from __future__ import annotations

import ast
import os
import types

import pytest
import yaml

from integrated_app.native import executor

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PREFLIGHT = os.path.join(REPO_ROOT, "scripts", "preflight_krea2_turbo.py")


def _load_cfg() -> dict:
    """读取 config.yaml 并取出 krea2_turbo_native 引擎块。"""
    with open(os.path.join(REPO_ROOT, "config.yaml"), encoding="utf-8") as f:
        engines = yaml.safe_load(f)["models"]["engines"]
    assert "krea2_turbo_native" in engines, "config.yaml 缺少 krea2_turbo_native 引擎块"
    return engines["krea2_turbo_native"]


def _preflight_literal(name: str, default=None):
    """从 preflight 脚本里静态取出顶层字面量常量（不 import，避免拉起 torch/comfy）。"""
    with open(PREFLIGHT, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id == name:
                return ast.literal_eval(node.value)
    assert default is not None, f"preflight 里找不到常量 {name}"
    return default


def _preflight_first_combo() -> tuple:
    """preflight 候选表的第一组 (sampler, scheduler)，即实测出图那组。"""
    raw = _preflight_literal("COMBOS")
    assert isinstance(raw, list) and raw, "preflight COMBOS 必须是非空列表"
    return tuple(raw[0])


# ── config 结构 ──────────────────────────────────────────────
def test_krea2_turbo_native_config_well_formed() -> None:
    cfg = _load_cfg()
    assert cfg["backend"] == "native"
    feats = cfg.get("supported_features") or []
    assert "txt2img" in feats, "krea2_turbo_native 必须声明 txt2img 能力（NativeEngine 能力守卫依赖此）"
    # Wan21 latent（comfy/latent_formats.py: Wan21.latent_channels=16，空间下采样 8）
    assert cfg.get("latent_channels") == 16
    assert cfg.get("latent_downscale") == 8


def test_krea2_two_new_load_fields_are_declared() -> None:
    """两处新字段必须就位——缺任何一个 Krea2 都会挂。"""
    cfg = _load_cfg()
    # GOTCHAS #41：AIO checkpoint 键带 model.diffusion_model. 前缀，必须先剥掉
    assert cfg["unet"]["key_prefix"] == "model.diffusion_model."
    # GOTCHAS #42：必须走 CLIPType.KREA2 枚举（12 层 tap=30720 维）
    assert cfg["text_encoder"]["clip_type"] == "krea2"


def test_krea2_weights_point_at_real_files() -> None:
    """三件套权重必须真实存在（2026-10-02 实证：均在 ComfyUI 模型库内，已挂 junction）。"""
    cfg = _load_cfg()
    expected = {
        "text_encoder": ("Krea2/qwen3-vl-4b-heretic_fp8_e4m3fn.safetensors", "text_encoders"),
        "unet": ("Krea2-turbo/krea2TurboNSFWAIO_v10.safetensors", "unet"),
        "vae": ("Krea2/qwen_image_vae.safetensors", "vae"),
    }
    for role, (sub_path, sub_dir) in expected.items():
        block = cfg.get(role)
        assert block, f"引擎块缺少 {role} 声明"
        abs_path = os.path.abspath(
            os.path.join(
                REPO_ROOT, "pretrained_models", block.get("sub_dir") or sub_dir, block.get("sub_path") or sub_path
            )
        )
        assert os.path.isfile(abs_path), f"config 指向的 {role} 不存在：{abs_path}"


def test_config_sampler_synced_with_preflight_first_combo() -> None:
    """config 的 sampler/scheduler 必须与 preflight 候选表首项（实测出图那组）一致，防两处漂移。"""
    cfg = _load_cfg()
    sampler, scheduler = _preflight_first_combo()
    assert cfg.get("sampler") == sampler, "config sampler 与 preflight 实测出图那组不一致"
    assert cfg.get("scheduler") == scheduler, "config scheduler 与 preflight 实测出图那组不一致"


def test_config_latent_constants_synced_with_preflight() -> None:
    """config 的 latent 口径必须与 preflight 用的显式常量一致（model.latent_format 实测 NoneType）。"""
    cfg = _load_cfg()
    assert cfg.get("latent_channels") == _preflight_literal("LATENT_CHANNELS")
    assert cfg.get("latent_downscale") == _preflight_literal("DEFAULT_SPACIAL_DOWNSCALE")


# ── 加载选项解析（纯函数）────────────────────────────────────
@pytest.fixture()
def cfg_obj():
    from integrated_app.config_models import AppConfig

    with open(os.path.join(REPO_ROOT, "config.yaml"), encoding="utf-8") as f:
        return AppConfig.from_yaml(yaml.safe_load(f), project_root=REPO_ROOT)


def test_resolve_engine_load_options_returns_both_keys(cfg_obj) -> None:
    from integrated_app.config_models import resolve_engine_load_options

    engine = cfg_obj.models.engines["krea2_turbo_native"]
    assert resolve_engine_load_options(engine, cfg_obj.models, REPO_ROOT) == {
        "unet_key_prefix": "model.diffusion_model.",
        "text_encoder_clip_type": "krea2",
    }


def test_resolve_engine_load_options_does_not_pollute_paths(cfg_obj) -> None:
    """加载选项绝不能混进路径字典：后者会被逐条当成文件去 verify_weight_before_load。"""
    from integrated_app.config_models import resolve_engine_load_options, resolve_engine_model_paths

    engine = cfg_obj.models.engines["krea2_turbo_native"]
    paths = resolve_engine_model_paths(engine, cfg_obj.models, REPO_ROOT)
    assert set(paths) == {"text_encoder", "unet", "vae"}
    assert resolve_engine_load_options(engine, cfg_obj.models, REPO_ROOT).keys() - set(paths)


def test_resolve_engine_load_options_empty_without_new_fields(cfg_obj) -> None:
    """历史引擎（不写新字段）必须返回空字典，行为与改动前完全一致。"""
    from integrated_app.config_models import resolve_engine_load_options

    engine = cfg_obj.models.engines["z_image_turbo_native"]
    assert resolve_engine_load_options(engine, cfg_obj.models, REPO_ROOT) == {}


# ── executor 加载定制（stub，不读权重）───────────────────────
def _comfy_stub(sd_keys=None):
    """构造最小 comfy 桩，便于断言 executor 的委托行为（不加载任何真实权重）。"""
    if sd_keys is None:
        sd_keys = {"model.diffusion_model.blocks.0.weight": (1, 1), "world": (2, 2)}
    calls: list[tuple] = []

    def _load_torch_file(path, return_metadata=False):
        calls.append(("load_torch_file", path, return_metadata))
        return dict(sd_keys), {"format": "pt"}

    sd = types.SimpleNamespace(
        CLIPType=types.SimpleNamespace(KREA2="<CLIPType.KREA2>", SD2="<CLIPType.SD2>"),
        load_diffusion_model=lambda path, **kw: ("default", path),
        load_diffusion_model_state_dict=lambda state_dict, **kw: ("state_dict", dict(state_dict)),
        load_clip=lambda paths, **kw: ("clip", tuple(paths), dict(kw)),
    )
    sd.load_diffusion_model_state_dict = lambda state_dict, **kw: (
        calls.append(("load_diffusion_model_state_dict", dict(state_dict))),
        ("state_dict", dict(state_dict)),
    )[1]
    utils = types.SimpleNamespace(load_torch_file=_load_torch_file)
    return types.SimpleNamespace(sd=sd, utils=utils), calls, sd


def test_load_diffusion_model_strips_key_prefix(monkeypatch) -> None:
    stub, calls, sd = _comfy_stub()
    monkeypatch.setattr(executor, "_comfy_runtime", lambda: stub)

    out = executor._load_diffusion_model("/w/aio.safetensors", "model.diffusion_model.")[1]

    assert set(out) == {"blocks.0.weight"}, "剥前缀后应只留 bare key"
    assert ("load_torch_file", "/w/aio.safetensors", True) in calls
    assert not any(c[0] == "default" for c in calls), "带前缀时不能走无前缀的默认入口"


def test_load_diffusion_model_raises_when_prefix_absent(monkeypatch) -> None:
    stub, _calls, _sd = _comfy_stub(sd_keys={"unet.blocks.0.weight": (1, 1)})
    monkeypatch.setattr(executor, "_comfy_runtime", lambda: stub)

    with pytest.raises(RuntimeError, match="剥前缀后为空"):
        executor._load_diffusion_model("/w/x.safetensors", "model.diffusion_model.")


def test_load_diffusion_model_defaults_without_prefix(monkeypatch) -> None:
    """不传前缀时必须原样走 comfy.sd.load_diffusion_model（历史行为）。"""
    stub, calls, sd = _comfy_stub()
    monkeypatch.setattr(executor, "_comfy_runtime", lambda: stub)

    out = executor._load_diffusion_model("/w/plain.safetensors")

    assert out == ("default", "/w/plain.safetensors")
    assert not any(c[0] == "load_torch_file" for c in calls)


def test_load_text_encoder_passes_clip_type_enum(monkeypatch) -> None:
    """clip_type=krea2 必须转成 CLIPType.KREA2 枚举下发给 load_clip（字符串不算）。"""
    stub, calls, sd = _comfy_stub()
    monkeypatch.setattr(executor, "_comfy_runtime", lambda: stub)

    kind, paths, kw = executor._load_text_encoder(["/w/te.safetensors"], "krea2")

    assert kind == "clip" and paths == ("/w/te.safetensors",)
    assert kw == {"clip_type": "<CLIPType.KREA2>"}


def test_load_text_encoder_without_clip_type(monkeypatch) -> None:
    """不传 clip_type 时必须走 comfy 自动检测（历史行为）。"""
    stub, _calls, _sd = _comfy_stub()
    monkeypatch.setattr(executor, "_comfy_runtime", lambda: stub)

    kind, _paths, kw = executor._load_text_encoder(["/w/te.safetensors"])

    assert kind == "clip" and kw == {}


def test_load_text_encoder_unknown_clip_type_falls_back(monkeypatch) -> None:
    """未知类型名不能炸，安全回落自动检测——否则 config 写错就是硬失败。"""
    stub, _calls, _sd = _comfy_stub()
    monkeypatch.setattr(executor, "_comfy_runtime", lambda: stub)

    kind, _paths, kw = executor._load_text_encoder(["/w/te.safetensors"], "not_a_clip")

    assert kind == "clip" and kw == {}


def test_load_text_encoder_accepts_uppercase_name(monkeypatch) -> None:
    stub, _calls, _sd = _comfy_stub()
    monkeypatch.setattr(executor, "_comfy_runtime", lambda: stub)

    _kind, _paths, kw = executor._load_text_encoder(["/w/te.safetensors"], "KREA2")
    assert kw == {"clip_type": "<CLIPType.KREA2>"}


# ── NativeEngine → executor 的合并传参 ───────────────────────
async def test_engine_merges_load_options_into_executor(monkeypatch) -> None:
    """engine 必须把「路径 + 加载选项」合并成一个字典交给 executor（缺选项 Krea2 跑不起来）。"""
    from integrated_app.engine_interface import GenerationConfig
    from integrated_app.native import executor as ex
    from integrated_app.native.engine import NativeEngine

    captured: dict = {}

    def fake_txt2img(config, model_paths, on_progress=None, cancel_flag=None):
        captured["config"] = config
        captured["model_paths"] = model_paths
        return []

    monkeypatch.setattr(ex, "txt2img", fake_txt2img)

    eng = NativeEngine(name="krea2_turbo_native")
    eng._ready = True
    eng._model_paths = {
        "text_encoder": "/w/te.safetensors",
        "unet": "/w/aio.safetensors",
        "vae": "/w/vae.safetensors",
    }
    eng._load_options = {"unet_key_prefix": "model.diffusion_model.", "text_encoder_clip_type": "krea2"}
    monkeypatch.setattr(eng, "_save_outputs", lambda images, config: [])

    cfg = GenerationConfig(positive_prompt="a cat sitting on a wooden table")
    await eng.infer_txt2img(cfg)

    mp = captured["model_paths"]
    for key in ("unet", "text_encoder", "vae", "unet_key_prefix", "text_encoder_clip_type"):
        assert key in mp, f"executor 收到的 model_paths 缺 {key}: {sorted(mp)}"
    assert mp["unet_key_prefix"] == "model.diffusion_model."


def test_registry_dispatches_native_engine_for_krea2(monkeypatch) -> None:
    monkeypatch.delenv("IMM_FAKE_ENGINE", raising=False)
    from integrated_app.model_registry import ModelRegistry
    from integrated_app.native.engine import NativeEngine

    eng = ModelRegistry().create_engine_instance(
        engine_name="krea2_turbo_native",
        display_name="Krea2-turbo (Native)",
        backend="native",
        config={"backend": "native", "role": ""},
    )
    assert isinstance(eng, NativeEngine)
