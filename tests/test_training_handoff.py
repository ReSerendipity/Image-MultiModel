"""tests/test_training_handoff.py — 产物发现与移交规划（路径语义的回归网）。

这一层全是**路径拼接**，而路径拼接的两个经典坑都在这踩过：

1. 「终稿 / 中间档」靠什么区分（早前按「名字里含下划线」判，把 ``probe_lora``
   自己的终稿判成了中间档）；
2. ``Path("")`` 归一化成 ``Path(".")`` 导致的**相对路径**移交目标（真跑实证抓到）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.integrated_app.training import handoff


@pytest.fixture()
def training_folder(tmp_path: Path) -> Path:
    """造一个与 AI-Toolkit 同构的存档目录：<training_folder>/<name>/"""
    tf = tmp_path / "jobs" / "abc123"
    save = tf / "probe_lora"
    (save / "samples").mkdir(parents=True)
    (save / "probe_lora.safetensors").write_bytes(b"\x00" * 100)  # 终稿
    (save / "probe_lora_000000002.safetensors").write_bytes(b"\x00" * 90)  # 中间档
    (save / "optimizer.pt").write_bytes(b"\x00" * 10)
    (save / "config.yaml").write_text("job: extension\n", encoding="utf-8")
    (save / "samples" / "sample_000000002_0.jpg").write_bytes(b"\xff\xd8")
    (save / "samples" / "notes.txt").write_text("x", encoding="utf-8")  # 非图片，要被过滤
    return tf


def _kinds(items: list[dict]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for it in items:
        out.setdefault(it["kind"], []).append(it["name"])
    return out


# ── 路径语义 ──────────────────────────────────────────────
def test_save_root_is_training_folder_plus_job_name(training_folder):
    assert handoff.save_root(training_folder, "probe_lora") == training_folder / "probe_lora"


def test_final_lora_only_matches_exact_name(training_folder):
    """终稿是「<name>.safetensors」**精确同名**；中间档不能顶替它。"""
    assert handoff.final_lora_path(training_folder, "probe_lora") == training_folder / "probe_lora" / (
        "probe_lora.safetensors"
    )
    assert handoff.final_lora_path(training_folder, "probe_lora_000000002") is None


def test_final_lora_none_when_not_written_yet(training_folder):
    handoff.final_lora_path(training_folder, "probe_lora").unlink()
    assert handoff.final_lora_path(training_folder, "probe_lora") is None


# ── 产物发现 ──────────────────────────────────────────────
def test_discover_artifacts_separates_final_and_intermediate(training_folder):
    items = handoff.discover_artifacts(training_folder, "probe_lora")
    kinds = _kinds(items)
    # 终稿不能因为名字里带下划线就被误判成中间档（回归：早前的 _STEP_SUFFIX_MARK）
    assert kinds["lora"] == ["probe_lora.safetensors"]
    assert kinds["lora_intermediate"] == ["probe_lora_000000002.safetensors"]
    assert kinds["optimizer"] == ["optimizer.pt"]
    assert kinds["config"] == ["config.yaml"]
    assert kinds["sample"] == ["sample_000000002_0.jpg"]


def test_discover_artifacts_skips_non_image_samples(training_folder):
    kinds = _kinds(handoff.discover_artifacts(training_folder, "probe_lora"))
    assert "notes.txt" not in " ".join(kinds["sample"])


def test_discover_artifacts_empty_when_folder_missing(tmp_path):
    assert handoff.discover_artifacts(tmp_path / "nope", "probe_lora") == []


# ── 移交目标的目录解析 ─────────────────────────────────────
def test_lora_resource_dir_portable(tmp_path):
    """portable 模式：``<project_root>/<internal_models_dir>/<sub_dirs.lora>``。"""
    config = _config("portable", portable_lora="loras", comfy="")
    out = handoff.lora_resource_dir(config, tmp_path)
    assert out == tmp_path / "pretrained_models" / "loras"
    assert out.is_absolute()  # 回归：曾经返回相对路径


def test_lora_resource_dir_shared_uses_comfy_models_dir(tmp_path):
    config = _config("shared", portable_lora="", comfy=r"D:/models")
    assert handoff.lora_resource_dir(config, tmp_path) == Path(r"D:/models") / "loras"


def test_lora_resource_dir_falls_back_absolute_when_config_missing(tmp_path):
    """拿不到配置时回退 <project_root>/loras，且**必须是绝对路径**。

    回归：``Path("")`` → ``Path(".")`` 的 ``str()`` 是真值，
    旧代码因此走进 base 分支返回相对路径 ``loras``（真跑实证抓到）。
    """
    out = handoff.lora_resource_dir(None, tmp_path)
    assert out == tmp_path / "loras"
    assert out.is_absolute()
    assert str(out) == str(tmp_path / "loras")


def _config(mode: str, *, portable_lora: str, comfy: str) -> object:
    """最小可用的配置替身（只实现 handoff 会读到的属性）。"""

    class _Sub:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    class _Cfg:
        def __init__(self):
            self.model_source_mode = mode
            self.portable = _Sub(sub_dirs={"lora": portable_lora or None}, internal_models_dir="pretrained_models")
            self.shared = _Sub(
                mount_map={"lora": portable_lora or None} if portable_lora else None, comfy_models_dir=comfy
            )

    return _Cfg()


# ── 移交计划（只读） ───────────────────────────────────────
def test_plan_handoff_is_readonly_and_absolute(training_folder, tmp_path):
    lora = handoff.final_lora_path(training_folder, "probe_lora")
    plan = handoff.plan_handoff(None, tmp_path, lora)
    # plan 里的路径全是 str（要能直接进 JSON 响应），判绝对要自己包一层 Path
    assert Path(plan["target_dir"]).is_absolute()
    assert plan["target"] == str(tmp_path / "loras" / "probe_lora.safetensors")
    assert plan["exists"] is False
    assert plan["copy_cmd"]  # 只给命令，不执行


def test_plan_handoff_reports_already_exists(tmp_path):
    lora = tmp_path / "x.safetensors"
    lora.write_bytes(b"\x00")
    (tmp_path / "loras").mkdir()
    (tmp_path / "loras" / "x.safetensors").write_bytes(b"\x00")
    plan = handoff.plan_handoff(None, tmp_path, lora)
    assert plan["exists"] is True


# ── 显式搬运（禁区目录护栏） ───────────────────────────────
def test_copy_dry_run_writes_nothing(tmp_path):
    lora = tmp_path / "x.safetensors"
    lora.write_bytes(b"\x00")
    (tmp_path / "loras").mkdir()
    out = handoff.copy_into_lora_dir(None, tmp_path, lora, dry_run=True)
    assert out["copied"] is False
    assert not (tmp_path / "loras" / "x.safetensors").exists()


def test_copy_actually_copies(tmp_path):
    lora = tmp_path / "x.safetensors"
    lora.write_bytes(b"\x00")
    (tmp_path / "loras").mkdir()
    out = handoff.copy_into_lora_dir(None, tmp_path, lora)
    assert out["copied"] is True
    assert (tmp_path / "loras" / "x.safetensors").read_bytes() == b"\x00"


def test_copy_reports_missing_source(tmp_path):
    out = handoff.copy_into_lora_dir(None, tmp_path, tmp_path / "ghost.safetensors")
    assert out["copied"] is False
    assert "不存在" in out["error"]


def test_copy_refuses_missing_target_dir(tmp_path):
    lora = tmp_path / "x.safetensors"
    lora.write_bytes(b"\x00")
    out = handoff.copy_into_lora_dir(None, tmp_path, lora)
    assert out["copied"] is False
    assert "不存在" in out["error"]


def test_copy_refuses_pointer_target(tmp_path):
    """目标是 junction/symlink 时明确拒绝，不静默附到宿主目录。"""
    host = tmp_path / "host"
    host.mkdir()
    (host / "x").write_text("", encoding="utf-8")
    link = tmp_path / "loras"
    try:
        import os

        os.symlink(host / "x", link)
    except OSError:  # pragma: no cover - 无权限环境跳过
        pytest.skip("当前环境不支持创建符号链接")
    lora = tmp_path / "y.safetensors"
    lora.write_bytes(b"\x00")
    out = handoff.copy_into_lora_dir(None, tmp_path, lora)
    assert out["copied"] is False
    assert "拒绝写入" in out["error"]
    assert not (host / "y.safetensors").exists()
