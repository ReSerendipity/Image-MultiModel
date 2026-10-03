"""tests/test_training_spec.py — 训练规格校验 + AI-Toolkit job 渲染（不跑训练）

校验是「提交前拦截」的第一道闸门：T-12 实跑一次训练 22 分钟，
不能每次都靠真的跑一遍才发现路径写错或分辨率不满足 16 倍数。
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
import yaml

from app.integrated_app.routes.train_routes import TrainJobRequest
from app.integrated_app.training.spec import TrainJobSpec, TrainSpecError


def _valid_spec(tmp_path: Path, **over: object) -> TrainJobSpec:
    """一条必然合法的规格（路径全部指向临时目录里的真实文件/目录）。

    用法：``_valid_spec(tmp_path, steps=0)`` —— 只覆盖想测的字段，
    其余取"能跑通"的默认值（避免测试自身构造出 TypeError 而不是被测的校验错误）。
    """
    over = dict(over)
    model = tmp_path / "model.safetensors"
    model.write_bytes(b"\x00")
    extras = tmp_path / "extras"
    extras.mkdir(exist_ok=True)
    dataset = tmp_path / "ds"
    dataset.mkdir(exist_ok=True)
    defaults: dict[str, object] = {
        "name": "probe_lora",
        "model_path": str(model),
        "extras_path": str(extras),
        "dataset_folder": str(dataset),
        "steps": 4,
        "save_every": 2,
        "logging_log_every": 2,
        "sample_prompts": ["a cat on a table"],
    }
    # 显式字段与 **over 只能有一套：覆盖项统一从 over 里取，剩下的补默认值
    kwargs = {key: over.pop(key, value) for key, value in defaults.items()}
    kwargs.update(over)  # type: ignore[arg-type]
    return TrainJobSpec(**kwargs)  # type: ignore[arg-type]


# ── 校验 ─────────────────────────────────────────────────
def test_valid_spec_passes(tmp_path):
    spec = _valid_spec(tmp_path)
    assert spec.validate() is spec


def test_reject_bad_name(tmp_path):
    for bad in ("", "../escape", "a/b", "wéird name"):
        with pytest.raises(TrainSpecError):
            _valid_spec(tmp_path, name=bad).validate()


def test_reject_relative_or_missing_paths(tmp_path):
    with pytest.raises(TrainSpecError):
        _valid_spec(tmp_path, model_path="relative/model.safetensors").validate()
    with pytest.raises(TrainSpecError):
        _valid_spec(tmp_path, model_path=str(tmp_path / "nope.safetensors")).validate()


def test_reject_path_that_is_a_directory(tmp_path):
    with pytest.raises(TrainSpecError):
        _valid_spec(tmp_path, model_path=str(tmp_path)).validate()


def test_reject_bad_resolution(tmp_path):
    for bad in (500, 513, 4096):
        with pytest.raises(TrainSpecError):
            _valid_spec(tmp_path, resolution=bad).validate()


def test_reject_bad_numbers(tmp_path):
    for field, bad in (("steps", 0), ("batch_size", 0), ("net_dim", 0), ("lr", 0.0), ("dtype", "int8")):
        with pytest.raises(TrainSpecError):
            _valid_spec(tmp_path, **{field: bad}).validate()


def test_save_every_clamped_to_steps(tmp_path):
    spec = _valid_spec(tmp_path, steps=3, save_every=99)
    spec.validate()
    assert spec.save_every == 3


# ── 渲染 ─────────────────────────────────────────────────
def test_job_config_matches_aitoolkit_shape(tmp_path):
    spec = _valid_spec(tmp_path)
    out = tmp_path / "jobs"  # 用真实绝对路径，避免 Windows 分隔符差异（Path 会原样保留）
    cfg = spec.to_job_config(out)

    assert cfg["job"] == "extension"
    proc = cfg["config"]["process"][0]
    assert proc["type"] == "sd_trainer"
    assert proc["training_folder"] == str(out)
    assert proc["network"] == {"type": "lora", "linear": 4, "linear_alpha": 4}
    assert proc["train"]["steps"] == 4
    assert proc["model"]["arch"] == "zimage"
    assert proc["model"]["extras_name_or_path"] == spec.extras_path
    assert proc["datasets"][0]["resolution"] == [512]
    # 结构化进度回写的开关（薄层读 loss_log.db 的前提）
    assert proc["logging"]["use_ui_logger"] is True
    assert cfg["meta"]["name"] == "[name]"


def test_job_config_training_folder_is_per_job(tmp_path):
    spec = _valid_spec(tmp_path)
    job_a = tmp_path / "job-a"
    job_b = tmp_path / "job-b"
    proc_a = spec.to_job_config(job_a)["config"]["process"][0]
    proc_b = spec.to_job_config(job_b)["config"]["process"][0]
    assert proc_a["training_folder"] == str(job_a)
    assert proc_b["training_folder"] == str(job_b)
    assert proc_a["training_folder"] != proc_b["training_folder"]


def test_render_yaml_is_parseable(tmp_path):
    text = _valid_spec(tmp_path).render_yaml(tmp_path / "jobs")
    loaded = yaml.safe_load(text)
    assert loaded["config"]["process"][0]["type"] == "sd_trainer"


# ── 契约：pydantic 请求体与 dataclass 规格字段必须同步 ────
def test_request_model_covers_every_spec_field():
    """漏字段会让前端提交体静默丢参数——用测试锁死两条 schema 的对应关系。"""
    spec_fields = {f.name for f in dataclasses.fields(TrainJobSpec)}
    api_fields = set(TrainJobRequest.model_fields)
    missing = spec_fields - api_fields
    assert not missing, f"TrainJobRequest 缺少字段（会在构建 TrainJobSpec 时抛 TypeError）: {sorted(missing)}"
