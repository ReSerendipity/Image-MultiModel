"""
tests/release/test_build_release_metadata.py — P1-10 不可变版本 artifact 测试

覆盖：
- 镜像 tag 规则（语义版本 / git-<sha> 合法，latest 等浮动 tag 非法）；
- requirements 解析与 CycloneDX SBOM 构造；
- 配置 / workflow / 模型 / comfy_kernel 快照可追溯；
- 内核来源凭证 kernel_provenance.json：干净 checkout（目录缺失）回填 provenance，
  无凭证时显式 N/A；目录存在时记录实时 upstream 溯源；
- .env 合并写入保留既有变量；
- --verify 能发现 tag 非法、SBOM 缺失与快照漂移。
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

_SPEC = Path(__file__).resolve().parents[2] / "scripts" / "build_release_metadata.py"


@pytest.fixture()
def mod():
    spec = importlib.util.spec_from_file_location("build_release_metadata", _SPEC)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


@pytest.fixture()
def tmp_root():
    root = Path(tempfile.mkdtemp(prefix="imm-rel-"))
    yield root
    shutil.rmtree(root, ignore_errors=True)


# ────────────────────────── tag 规则 ──────────────────────────
@pytest.mark.parametrize(
    "tag,expected",
    [
        ("2.0.1", True),
        ("v2.0.1", True),
        ("2.0.1-rc.1", True),
        ("git-ceabe3946d5b", True),
        ("latest", False),  # 浮动 tag，必须拒绝
        ("", False),
        ("dev", False),
        ("stable", False),
        ("main", False),
        ("nightly", False),
        ("git-xyz", False),  # 非十六进制
        ("random-string", False),
    ],
)
def test_is_valid_image_tag(mod, tag, expected):
    assert mod.is_valid_image_tag(tag) is expected


def test_derive_image_tag_from_version(mod):
    assert mod.derive_image_tag("abc123", "v2.0.1") == "2.0.1"
    assert mod.derive_image_tag("abc123", "2.0.1") == "2.0.1"


def test_derive_image_tag_from_sha(mod):
    sha = "ceabe3946d5b7005847f690cdd3483853f00a6b0"
    assert mod.derive_image_tag(sha) == "git-ceabe3946d5b"


def test_derive_image_tag_without_sha_is_invalid(mod):
    tag = mod.derive_image_tag("")
    assert tag == "git-unknown"
    assert mod.is_valid_image_tag(tag) is False  # 非 Git 仓库时必须由 --version 兜底


# ────────────────────────── SBOM ──────────────────────────
def test_parse_requirements(mod):
    text = "\n".join(
        [
            "# comment",
            "",
            "fastapi==0.115.0",
            "uvicorn[standard]==0.30.6",
            "torch>=2.4.0",  # 非锁定行，跳过
            "-r other.txt",  # 指令行，跳过
            "PyYAML==6.0.2 ; python_version>='3.8'",  # 带 marker
        ]
    )
    got = mod.parse_requirements(text)
    assert got == [
        ("fastapi", "0.115.0"),
        ("uvicorn", "0.30.6"),
        ("PyYAML", "6.0.2"),
    ]


def test_build_sbom_cyclonedx_shape(mod):
    sbom = mod.build_sbom("fastapi==0.115.0\npydantic==2.9.0\n", "2.0.1", "deadbeef")
    assert sbom["bomFormat"] == "CycloneDX"
    assert sbom["specVersion"] == "1.5"
    assert [c["name"] for c in sbom["components"]] == ["fastapi", "pydantic"]
    assert sbom["components"][0]["purl"] == "pkg:pypi/fastapi@0.115.0"
    assert sbom["metadata"]["component"]["version"] == "2.0.1"
    props = {p["name"]: p["value"] for p in sbom["metadata"]["properties"]}
    assert props["git.sha"] == "deadbeef"


# ────────────────────────── 快照 / 清单 ──────────────────────────
def test_config_and_workflow_snapshot(mod, tmp_root):
    (tmp_root / "config.yaml").write_text("runtime: {}\n", encoding="utf-8")
    wf = tmp_root / "workflows"
    wf.mkdir()
    (wf / "a.json").write_text("{}", encoding="utf-8")

    cfg = mod.config_snapshot(tmp_root)
    assert cfg["present"] is True and cfg["sha256"]

    snap = mod.workflow_snapshot(tmp_root)
    assert snap["file_count"] == 1
    assert snap["files"][0]["path"].startswith("workflows/")

    # 内容变更必须反映到快照
    (tmp_root / "config.yaml").write_text("runtime: {changed: true}\n", encoding="utf-8")
    assert mod.config_snapshot(tmp_root)["sha256"] != cfg["sha256"]


def test_model_manifest_hashes_small_files_only(mod, tmp_root):
    mdir = tmp_root / "model" / "unet"
    mdir.mkdir(parents=True)
    (mdir / "small.safetensors").write_bytes(b"x" * 16)

    man = mod.model_manifest(tmp_root)
    assert man["file_count"] == 1
    assert man["files"][0]["sha256"]  # 小文件已哈希

    man_nohash = mod.model_manifest(tmp_root, with_hash=False)
    assert man_nohash["hashed"] is False
    assert man_nohash["files"][0]["sha256"] == ""


def test_tree_digest_detects_change(mod, tmp_root):
    d = tmp_root / "comfy_kernel"
    d.mkdir()
    (d / "a.py").write_text("v1", encoding="utf-8")
    first = mod.tree_digest(tmp_root, "comfy_kernel")
    assert first["present"] is True and first["file_count"] == 1

    (d / "b.py").write_text("new", encoding="utf-8")
    second = mod.tree_digest(tmp_root, "comfy_kernel")
    assert second["digest"] != first["digest"] and second["file_count"] == 2


def test_tree_digest_missing_dir(mod, tmp_root):
    assert mod.tree_digest(tmp_root, "comfy_kernel")["present"] is False


def test_tree_digest_missing_dir_with_absent_payload(mod, tmp_root):
    got = mod.tree_digest(tmp_root, "comfy_kernel", {"provenance": {"upstream_commit": "abc"}})
    assert got["present"] is False and got["digest"] == ""
    assert got["provenance"] == {"upstream_commit": "abc"}


# ────────────────────── 内核来源凭证 ──────────────────────
def test_read_kernel_provenance_variants(mod, tmp_root):
    assert mod.read_kernel_provenance(tmp_root) == {}  # 文件不存在
    p = tmp_root / "kernel_provenance.json"
    p.write_text("not-json{{", encoding="utf-8")
    assert mod.read_kernel_provenance(tmp_root) == {}  # 损坏降级为空
    p.write_text(
        json.dumps({"origin": "https://example.invalid/x.git", "upstream_commit": "deadbeef"}), encoding="utf-8"
    )
    assert mod.read_kernel_provenance(tmp_root)["upstream_commit"] == "deadbeef"


def test_build_metadata_backfills_provenance_when_kernel_absent(mod, tmp_root):
    p = tmp_root / "kernel_provenance.json"
    p.write_text(
        json.dumps({"origin": "https://example.invalid/x.git", "upstream_commit": "cafe1234"}), encoding="utf-8"
    )
    ck = mod.build_metadata(tmp_root, version="9.9.9", with_model_hash=False)["artifacts"]["comfy_kernel"]
    assert ck["present"] is False
    assert ck["provenance"]["upstream_commit"] == "cafe1234"
    assert ck["provenance"]["origin"] == "https://example.invalid/x.git"


def test_build_metadata_explicit_na_without_provenance_file(mod, tmp_root):
    ck = mod.build_metadata(tmp_root, version="9.9.9", with_model_hash=False)["artifacts"]["comfy_kernel"]
    assert ck["present"] is False
    assert isinstance(ck["provenance"], str) and "N/A" in ck["provenance"]


def test_build_metadata_records_live_upstream_when_kernel_present(mod, tmp_root):
    (tmp_root / "comfy_kernel").mkdir()
    ck = mod.build_metadata(tmp_root, version="9.9.9", with_model_hash=False)["artifacts"]["comfy_kernel"]
    assert ck["present"] is True and ck["digest"]
    # 临时目录非 git 仓库：实时溯源不可得，显式置空而非报错
    assert ck["upstream"] is None
    assert "provenance" not in ck


def test_kernel_upstream_live_non_git_dir(mod, tmp_root):
    d = tmp_root / "comfy_kernel"
    d.mkdir()
    assert mod.kernel_upstream_live(d) == {}


# ────────────────────────── .env 合并 ──────────────────────────
def test_merge_env_file_preserves_other_keys(mod, tmp_root):
    env = tmp_root / ".env"
    env.write_text("MY_SECRET=keep\nIMAGE_TAG=old\n", encoding="utf-8")
    text = mod.merge_env_file(env, {"IMAGE_TAG": "2.0.1", "IMAGE_DIGEST": "sha256:abc"})
    assert "MY_SECRET=keep" in text
    assert "IMAGE_TAG=2.0.1" in text
    assert "IMAGE_TAG=old" not in text
    assert "IMAGE_DIGEST=sha256:abc" in text


def test_merge_env_file_creates_when_missing(mod, tmp_root):
    env = tmp_root / ".env"
    text = mod.merge_env_file(env, {"IMAGE_TAG": "git-abc1234"})
    assert text.strip() == "IMAGE_TAG=git-abc1234"


# ────────────────────────── verify ──────────────────────────
def _write_release(mod, tmp_root, tag="2.0.1", with_sbom=True, dirty=False):
    (tmp_root / "config.yaml").write_text("runtime: {}\n", encoding="utf-8")
    (tmp_root / "workflows").mkdir(exist_ok=True)
    (tmp_root / "workflows" / "a.json").write_text("{}", encoding="utf-8")
    out = tmp_root / "release"
    out.mkdir(exist_ok=True)
    meta = mod.build_metadata(tmp_root, version=tag, with_model_hash=False)
    meta["git"]["dirty"] = dirty
    meta["artifacts"]["config"] = mod.config_snapshot(tmp_root)
    meta["artifacts"]["workflows"] = mod.workflow_snapshot(tmp_root)
    (out / "build_metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    if with_sbom:
        (out / "sbom.json").write_text(json.dumps(mod.build_sbom("", tag, "x")), encoding="utf-8")
    return out


def test_verify_passes_on_clean_release(mod, tmp_root):
    out = _write_release(mod, tmp_root)
    assert mod.verify(tmp_root, out, strict=True) == []


def test_verify_fails_when_missing(mod, tmp_root):
    problems = mod.verify(tmp_root, tmp_root / "release")
    assert problems and "build_metadata.json" in problems[0]


def test_verify_fails_on_latest_tag(mod, tmp_root):
    out = _write_release(mod, tmp_root, tag="latest")
    problems = mod.verify(tmp_root, out)
    assert any("latest" in p for p in problems)


def test_verify_fails_on_missing_sbom(mod, tmp_root):
    out = _write_release(mod, tmp_root, with_sbom=False)
    assert any("sbom.json" in p for p in mod.verify(tmp_root, out))


def test_verify_detects_config_drift(mod, tmp_root):
    out = _write_release(mod, tmp_root)
    (tmp_root / "config.yaml").write_text("runtime: {changed: 1}\n", encoding="utf-8")
    assert any("config.yaml" in p for p in mod.verify(tmp_root, out))


def test_verify_detects_workflow_drift(mod, tmp_root):
    out = _write_release(mod, tmp_root)
    (tmp_root / "workflows" / "b.json").write_text("{}", encoding="utf-8")
    assert any("workflows/" in p for p in mod.verify(tmp_root, out))


def test_verify_strict_flags_dirty(mod, tmp_root):
    out = _write_release(mod, tmp_root, dirty=True)
    assert mod.verify(tmp_root, out, strict=False) == []  # PR 构建允许 dirty
    assert any("dirty" in p for p in mod.verify(tmp_root, out, strict=True))


# ────────────────────────── 端到端元数据 ──────────────────────────
def test_build_metadata_shape(mod, tmp_root):
    (tmp_root / "config.yaml").write_text("runtime: {}\n", encoding="utf-8")
    (tmp_root / "requirements-lock.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
    meta = mod.build_metadata(tmp_root, version="v2.0.1", with_model_hash=False)
    assert meta["image_tag"] == "2.0.1"
    assert meta["image_tag_valid"] is True
    assert meta["schema_version"] == "1.0"
    assert set(meta["artifacts"]) == {"config", "workflows", "model", "comfy_kernel"}
    assert meta["requirements_lock_sha256"]
    assert meta["build"]["python_version"]
