"""flux1_dev_native 接入验证（P2-multi-engine D 项，2026-10-02 已实证出图）。

覆盖（全部离线可跑，不加载 torch 之外的重依赖、不读权重）：
- config.yaml 中 ``flux1_dev_native`` 引擎块结构正确
  （backend=native / 声明 txt2img / latent 16×空间下采样 8 / guidance 3.5 /
   unet 指向真实存在的文件 / 双文本编码器 sub_paths 就位 / key_prefix 就位）
- ``resolve_engine_extra_model_paths`` / ``resolve_engine_load_options``
  能解析出「主 TE + 附加 TE」两条路径，且不污染「路径字典」
  （后者会被 ``verify_weight_before_load`` 当文件逐个去验，见 GOTCHAS #41）
- executor 的两个接线点：``_load_models`` 把双 TE 一次性交给 ``_load_text_encoder``，
  ``_encode_conditioning`` 在 guidance>0 时往 cond 字典注入 ``guidance`` 键

真实前向由 ``scripts/preflight_flux1_dev.py`` 实证（2026-10-02：
256²/4 步/euler+simple/guidance 3.5 端到端出图，落盘
`outputs/_preflight_flux1_dev/flux1_euler_simple.png`，猫趴木桌与 prompt 吻合）。
本测试不加载权重，只锁住「不依赖权重的接线事实」。
"""

from __future__ import annotations

import ast
import os
import sys
import types

import pytest
import yaml

from integrated_app.native import executor

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PREFLIGHT = os.path.join(REPO_ROOT, "scripts", "preflight_flux1_dev.py")


def _load_cfg(name: str = "flux1_dev_native") -> dict:
    with open(os.path.join(REPO_ROOT, "config.yaml"), encoding="utf-8") as f:
        engines = yaml.safe_load(f)["models"]["engines"]
    assert name in engines, f"config.yaml 缺少 {name} 引擎块"
    return engines[name]


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
    raw = _preflight_literal("COMBOS")
    assert isinstance(raw, list) and raw, "preflight COMBOS 必须是非空列表"
    return tuple(raw[0])


# ── config 结构 ──────────────────────────────────────────────
def test_flux1_dev_native_config_well_formed() -> None:
    cfg = _load_cfg()
    assert cfg["backend"] == "native"
    feats = cfg.get("supported_features") or []
    assert "txt2img" in feats, "flux1_dev_native 必须声明 txt2img 能力（NativeEngine 能力守卫依赖此）"
    # latent_formats.Flux 继承 SD3：16 通道 / 空间下采样 8
    assert cfg.get("latent_channels") == 16
    assert cfg.get("latent_downscale") == 8
    # FLUX guidance 与 cfg 是两套参数，缺失时 comfy 内建默认 3.5，显式写 3.5 便于溯源
    assert cfg.get("guidance") == 3.5


def test_flux1_dev_dual_text_encoder_declared() -> None:
    """GOTCHAS #43：FLUX.1-dev 是双 TE 架构，clip_l 必须挂在 sub_paths 上。"""
    cfg = _load_cfg()
    te = cfg["text_encoder"]
    assert te["clip_type"] == "flux"
    assert te["sub_path"].endswith("t5xxl_fp8_e4m3fn.safetensors")
    extras = te.get("sub_paths") or []
    assert len(extras) == 1, "clip_l 必须声明为一个附加项"
    extra = extras[0]
    # clip_l 在本机 ComfyUI 库挂在 models/clip/ 下，与 t5xxl 的 models/text_encoders/ 不同目录
    assert extra["sub_dir"] == "clip"
    assert extra["sub_path"].endswith("clip_l.safetensors")


def test_flux1_dev_junction_name_is_dot_not_hyphen() -> None:
    """GOTCHAS #43：VAE junction 名是 `FLUX.1-dev`（点号）。

    写成 `FLUX-1-dev(...)` 在 YAML 里语法完全合法、resolve 也照样拼出绝对路径，
    直到 load 时 verify_weight_before_load 才炸——故这里钉死写法。
    """
    cfg = _load_cfg()
    vae_path = cfg["vae"]["sub_path"]
    assert vae_path.startswith("FLUX.1-dev(Z-image(turbo))/")
    assert "FLUX-1-dev(" not in vae_path, "VAE junction 名误写成了连字符"


def test_flux1_dev_unet_key_prefix_declared() -> None:
    """本机 fluxNSFWUNLOCKED 键带 model.diffusion_model. 前缀，必须先剥（GOTCHAS #43）。"""
    cfg = _load_cfg()
    assert cfg["unet"]["key_prefix"] == "model.diffusion_model."
    assert cfg["unet"]["sub_path"].endswith("fluxNSFWUNLOCKED.safetensors")


def test_flux1_dev_weights_point_at_real_files() -> None:
    """GOTCHAS #43：roadmap 曾把该目录标为「未开工/权重阻断」，实际三件套 + clip_l 全在库里。"""
    cfg = _load_cfg()
    roles = {
        "text_encoder": ("text_encoders", "FLUX-1-dev/t5xxl_fp8_e4m3fn.safetensors"),
        "unet": ("unet", "FLUX-1-dev/fluxNSFWUNLOCKED.safetensors"),
        "vae": ("vae", "FLUX.1-dev(Z-image(turbo))/ae.safetensors"),
    }
    for role, (fallback_dir, fallback_path) in roles.items():
        block = cfg.get(role)
        assert block, f"引擎块缺少 {role} 声明"
        sub_dir = block.get("sub_dir") or fallback_dir
        sub_path = block.get("sub_path") or fallback_path
        abs_path = os.path.abspath(os.path.join(REPO_ROOT, "pretrained_models", sub_dir, sub_path))
        assert os.path.isfile(abs_path), f"config 指向的 {role} 不存在：{abs_path}"

    for extra in cfg["text_encoder"]["sub_paths"]:
        sub_dir = extra.get("sub_dir") or "text_encoders"
        abs_path = os.path.abspath(os.path.join(REPO_ROOT, "pretrained_models", sub_dir, extra["sub_path"]))
        assert os.path.isfile(abs_path), f"附加 TE 不存在：{abs_path}"


def test_config_sampler_synced_with_preflight_first_combo() -> None:
    """config 的 sampler/scheduler 必须与 preflight 候选表首项（实测出图那组）一致，防两处漂移。"""
    cfg = _load_cfg()
    sampler, scheduler = _preflight_first_combo()
    assert cfg.get("sampler") == sampler
    assert cfg.get("scheduler") == scheduler


def test_config_latent_and_guidance_synced_with_preflight() -> None:
    """config 的 latent 口径 / guidance 必须逐字等于 preflight 用的显式常量。"""
    cfg = _load_cfg()
    assert cfg.get("latent_channels") == _preflight_literal("LATENT_CHANNELS")
    assert cfg.get("latent_downscale") == _preflight_literal("DEFAULT_SPACIAL_DOWNSCALE")
    assert cfg.get("guidance") == _preflight_literal("DEFAULT_GUIDANCE")


# ── 加载选项解析（纯函数）────────────────────────────────────
@pytest.fixture()
def cfg_obj():
    from integrated_app.config_models import AppConfig

    with open(os.path.join(REPO_ROOT, "config.yaml"), encoding="utf-8") as f:
        return AppConfig.from_yaml(yaml.safe_load(f), project_root=REPO_ROOT)


def test_resolve_engine_load_options_returns_dual_te_and_guidance(cfg_obj) -> None:
    from integrated_app.config_models import resolve_engine_load_options

    engine = cfg_obj.models.engines["flux1_dev_native"]
    opts = resolve_engine_load_options(engine, cfg_obj.models, REPO_ROOT)
    assert opts["unet_key_prefix"] == "model.diffusion_model."
    assert opts["text_encoder_clip_type"] == "flux"
    assert opts["guidance"] == 3.5
    te_paths = opts["text_encoder_paths"]
    assert len(te_paths) == 2, "双 TE 必须吐出两条路径"
    assert te_paths[0].endswith("t5xxl_fp8_e4m3fn.safetensors")
    assert te_paths[1].endswith("clip_l.safetensors")
    for p in te_paths:
        assert os.path.isfile(p), f"text_encoder_paths 里的 {p} 不是真实文件"


def test_resolve_engine_load_options_no_dual_te_without_sub_paths(cfg_obj) -> None:
    """没写 sub_paths 的引擎不能凭空多出 text_encoder_paths（否则会覆盖单 TE 行为）。"""
    from integrated_app.config_models import resolve_engine_load_options

    engine = cfg_obj.models.engines["qwen_image_native"]
    assert resolve_engine_load_options(engine, cfg_obj.models, REPO_ROOT) == {}


def test_resolve_engine_load_options_does_not_pollute_paths(cfg_obj) -> None:
    """加载选项绝不能混进路径字典：后者会被逐条当成文件去 verify_weight_before_load。"""
    from integrated_app.config_models import resolve_engine_load_options, resolve_engine_model_paths

    engine = cfg_obj.models.engines["flux1_dev_native"]
    paths = resolve_engine_model_paths(engine, cfg_obj.models, REPO_ROOT)
    assert set(paths) == {"text_encoder", "unet", "vae"}
    assert resolve_engine_load_options(engine, cfg_obj.models, REPO_ROOT).keys() - set(paths)


def test_resolve_engine_extra_model_paths_resolves_clip_l_under_its_own_sub_dir(cfg_obj) -> None:
    """附加项用**自己**的 sub_dir（clip），不能被主 TE 的 text_encoders 顶掉。"""
    from integrated_app.config_models import resolve_engine_extra_model_paths

    engine = cfg_obj.models.engines["flux1_dev_native"]
    extras = resolve_engine_extra_model_paths(engine.text_encoder, cfg_obj.models, REPO_ROOT)
    assert len(extras) == 1
    resolved = extras[0].replace("\\", "/")
    assert "/clip/FLUX.1-dev/clip_l.safetensors" in resolved, resolved
    assert "text_encoders" not in resolved, f"clip_l 被顶到主 TE 目录了：{resolved}"


def test_resolve_engine_extra_model_paths_inherits_parent_sub_dir(cfg_obj) -> None:
    """附加项未写 sub_dir 时必须沿用主 sub_dir（纯函数，不查真实权重）。"""
    from integrated_app.config_models import ModelPaths, resolve_engine_extra_model_paths

    parent = ModelPaths(
        sub_dir="text_encoders", sub_path="a.safetensors", sub_paths=[ModelPaths(sub_path="b.safetensors")]
    )
    result = resolve_engine_extra_model_paths(parent, cfg_obj.models, REPO_ROOT)
    assert len(result) == 1
    resolved = result[0].replace("\\", "/")
    assert resolved.endswith("pretrained_models/text_encoders/b.safetensors"), resolved


# ── executor 接线（stub，不读权重）───────────────────────────
def _comfy_stub():
    calls: list[tuple] = []
    sd = types.SimpleNamespace(
        CLIPType=types.SimpleNamespace(FLUX="<CLIPType.FLUX>", SD2="<CLIPType.SD2>"),
        VAE=lambda sd=None: ("vae", sd),
        load_diffusion_model=lambda path, **kw: ("model", path),
        load_clip=lambda paths, **kw: ("clip", tuple(paths), dict(kw)),
    )
    utils = types.SimpleNamespace(load_torch_file=lambda path, **kw: ({"k": (1, 1)}, {}))
    return types.SimpleNamespace(sd=sd, utils=utils), calls, sd


def test_load_models_passes_both_text_encoders(monkeypatch) -> None:
    """GOTCHAS #43：双 TE 必须一次 load_clip 传两个文件（少一个前向就报 t5 维数不符）。"""
    stub, calls, _sd = _comfy_stub()
    monkeypatch.setattr(executor, "_comfy_runtime", lambda: stub)

    model = types.SimpleNamespace(
        get_model_object=lambda key: f"{key}-obj",
        latent_format=None,
    )
    monkeypatch.setattr(executor, "_load_diffusion_model", lambda p, prefix=None: model)
    captured: dict = {}

    def fake_load_text_encoder(paths, clip_type=None):
        captured["paths"] = list(paths)
        captured["clip_type"] = clip_type
        return "clip-stub"

    monkeypatch.setattr(executor, "_load_text_encoder", fake_load_text_encoder)
    monkeypatch.setattr(executor, "_resolve_device", lambda: "cpu")

    executor._load_models(
        {
            "unet": "/w/unet.safetensors",
            "text_encoder": "/w/t5xxl.safetensors",
            "text_encoder_paths": ["/w/t5xxl.safetensors", "/w/clip_l.safetensors"],
            "text_encoder_clip_type": "flux",
            "unet_key_prefix": "model.diffusion_model.",
            "vae": "/w/vae.safetensors",
        }
    )

    assert captured["paths"] == ["/w/t5xxl.safetensors", "/w/clip_l.safetensors"]
    assert captured["clip_type"] == "flux"
    assert calls == []


def test_load_models_falls_back_to_single_text_encoder(monkeypatch) -> None:
    """历史引擎（无 text_encoder_paths）必须回落到单个 text_encoder。"""
    stub, _calls, _sd = _comfy_stub()
    monkeypatch.setattr(executor, "_comfy_runtime", lambda: stub)

    model = types.SimpleNamespace(get_model_object=lambda key: f"{key}-obj", latent_format=None)
    monkeypatch.setattr(executor, "_load_diffusion_model", lambda p, prefix=None: model)
    captured: dict = {}

    def fake_load_text_encoder(paths, clip_type=None):
        captured["paths"] = list(paths)
        captured["clip_type"] = clip_type
        return "clip-stub"

    monkeypatch.setattr(executor, "_load_text_encoder", fake_load_text_encoder)
    monkeypatch.setattr(executor, "_resolve_device", lambda: "cpu")

    executor._load_models(
        {"unet": "/w/unet.safetensors", "text_encoder": "/w/te.safetensors", "vae": "/w/vae.safetensors"}
    )

    assert captured["paths"] == ["/w/te.safetensors"]
    assert captured["clip_type"] is None


def test_load_text_encoder_maps_flux_clip_type(monkeypatch) -> None:
    """clip_type=flux 必须映射成 CLIPType.FLUX 枚举（字符串不算，同 Krea2 的 #42 规则）。"""
    stub, _calls, _sd = _comfy_stub()
    monkeypatch.setattr(executor, "_comfy_runtime", lambda: stub)

    kind, paths, kw = executor._load_text_encoder(["/w/t5xxl.safetensors", "/w/clip_l.safetensors"], "flux")

    assert kind == "clip"
    assert paths == ("/w/t5xxl.safetensors", "/w/clip_l.safetensors")
    assert kw == {"clip_type": "<CLIPType.FLUX>"}


def _clip_stub(return_value=None):
    return types.SimpleNamespace(
        tokenize=lambda text: {"tokens": text},
        encode_from_tokens_scheduled=lambda tokens: [("<cond>", {"pooled": "x"})],
    )


def test_encode_conditioning_injects_guidance_when_configured() -> None:
    """GOTCHAS #43：FLUX guidance 不在 cfg 通道上，必须手工注入 cond 字典。"""
    out = executor._encode_conditioning(_clip_stub(), "a cat", guidance=3.5)
    assert [c[0] for c in out] == ["<cond>"]
    for _kind, payload in out:
        assert float(payload["guidance"].item()) == 3.5


def test_encode_conditioning_untouched_without_guidance() -> None:
    """guidance=0（缺省/历史引擎）必须原样返回，一条键都不能多。"""
    out = executor._encode_conditioning(_clip_stub(), "a cat")
    for kind, payload in out:
        assert kind == "<cond>"
        assert "guidance" not in payload


# ── txt2img 的 guidance 接线（stub 全链路，不读权重）──────────
class _FakeTensor:
    def to(self, *_a, **_kw):
        return self

    shape = (1, 16, 32, 32)


class _FakeImages(list):
    """既支持 ``images.shape[0]`` 又支持 ``images[i]``（对齐 executor.txt2img 的收尾写法）。"""

    shape = (1,)

    def __getitem__(self, i):  # type: ignore[override]
        return _FakeTensor()


def _fake_torch():
    return types.SimpleNamespace(
        Generator=lambda device: types.SimpleNamespace(manual_seed=lambda seed: None),
        randn=lambda *a, **kw: _FakeTensor(),
        inference_mode=lambda *a, **kw: lambda f: f,
        FloatTensor=lambda v: types.SimpleNamespace(item=lambda: v[0]),
        float32="f32",
    )


def _fake_comfy():
    samplers = types.SimpleNamespace(
        calculate_sigmas=lambda ms, name, steps: [1.0, 0.0],
        sampler_object=lambda name: ("sampler", name),
        sample=lambda model, noise, pos, neg, cfg, device, so, sigmas, **kw: _FakeTensor(),
    )
    mm = types.SimpleNamespace(soft_empty_cache=lambda: None)
    return types.SimpleNamespace(samplers=samplers, model_management=mm)


def test_txt2img_passes_guidance_to_conditioning(monkeypatch) -> None:
    """txt2img 必须把 model_paths['guidance'] 传给正/负两次编码（否则 FLUX 静默走内建默认 3.5）。"""
    captured: dict = {"guidance": [], "texts": [], "te_paths": []}

    def fake_encode_conditioning(clip, text, guidance=0.0):
        captured["guidance"].append(guidance)
        captured["texts"].append(text)
        return [("<c>", {"pooled": "x"})]

    monkeypatch.setattr(executor, "_encode_conditioning", fake_encode_conditioning)
    monkeypatch.setattr(
        executor,
        "_load_models",
        lambda model_paths=None, comfy_root=None: types.SimpleNamespace(
            model="m", clip="clip-stub", vae="v", device="cuda", model_sampling="ms", latent_format=None
        ),
    )
    monkeypatch.setattr(executor, "build_latent", lambda *a, **kw: _FakeTensor())
    monkeypatch.setattr(executor, "_vae_decode", lambda *a, **kw: _FakeImages())
    monkeypatch.setattr(executor, "torch", _fake_torch())
    fake_comfy = _fake_comfy()
    monkeypatch.setattr(executor, "_comfy_runtime", lambda: fake_comfy)
    # executor 在 txt2img 内直接 `import comfy.samplers`，故需预先塞进 sys.modules
    monkeypatch.setitem(sys.modules, "comfy", fake_comfy)
    monkeypatch.setitem(sys.modules, "comfy.samplers", fake_comfy.samplers)
    monkeypatch.setitem(sys.modules, "comfy.model_management", fake_comfy.model_management)

    from integrated_app.engine_interface import GenerationConfig

    cfg = GenerationConfig(positive_prompt="a cat on a table")
    executor.txt2img(
        cfg,
        {
            "unet": "/w/unet.safetensors",
            "text_encoder": "/w/t5xxl.safetensors",
            "vae": "/w/vae.safetensors",
            "guidance": 3.5,
        },
        on_progress=None,
        comfy_root=None,
        cancel_flag=[False],
    )

    assert captured["guidance"] == [3.5, 3.5], "guidance 必须同时注入正/负两条 cond"
    assert captured["texts"] == ["a cat on a table", ""]
