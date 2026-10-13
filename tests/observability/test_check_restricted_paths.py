"""
tests/observability/test_check_restricted_paths.py — 禁区路径强制评审守卫单测

覆盖 better-harness 修复：为 AGENTS.md 声明的禁区/高影响路径补一层「被跟踪」的强制评审。
用 importlib 直接加载 .github/scripts/check_restricted_paths.py，断言：

- 从 CODEOWNERS 的 RESTRICTED:BEGIN/END 区块解析受控前缀（忽略注释/空行/区块外条目）；
- 前缀匹配覆盖安全模块 / 发布目录 / vendored 内核 / 单个签名脚本，放行良性文件；
- 触碰禁区 → main 返回 1（硬阻断）；良性文件 → 返回 0；
- 维护者显式放行（RESTRICTED_APPROVED=1）→ 即便触碰禁区也返回 0；
- CODEOWNERS 缺失 RESTRICTED 区块 → fail-closed 返回 1（绝不静默放行）；
- 对真实仓内 CODEOWNERS，app/integrated_app/security/ 改动被拦下。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SPEC = _REPO_ROOT / ".github" / "scripts" / "check_restricted_paths.py"
_REAL_CODEOWNERS = _REPO_ROOT / ".github" / "CODEOWNERS"


@pytest.fixture()
def mod():
    spec = importlib.util.spec_from_file_location("check_restricted_paths", _SPEC)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture()
def fixture_codeowners(tmp_path):
    co = tmp_path / "CODEOWNERS"
    co.write_text(
        "* @default\n"
        "\n"
        "# === RESTRICTED:BEGIN  guard parses below ===\n"
        "# 说明行，应被忽略\n"
        "comfy_kernel/ @owner\n"
        "app/integrated_app/security/ @owner\n"
        "release/ @owner\n"
        "scripts/verify_watermark.py @owner\n"
        "# === RESTRICTED:END ===\n"
        "README.md @owner\n",
        encoding="utf-8",
    )
    return co


def test_parses_only_restricted_block(mod, fixture_codeowners):
    patterns = mod.load_restricted_patterns(fixture_codeowners.read_text(encoding="utf-8"))
    assert patterns == [
        "comfy_kernel/",
        "app/integrated_app/security/",
        "release/",
        "scripts/verify_watermark.py",
    ]


def test_match_and_offending(mod):
    patterns = ["comfy_kernel/", "app/integrated_app/security/", "release/", "scripts/verify_watermark.py"]
    changed = [
        "app/integrated_app/security/content_filter.py",
        "comfy_kernel/comfy/nodes.py",
        "release/sbom.json",
        "scripts/verify_watermark.py",
        "app/integrated_app/middleware/auth.py",
        "README.md",
    ]
    offend = mod.offending_files(changed, patterns)
    assert offend == [
        "app/integrated_app/security/content_filter.py",
        "comfy_kernel/comfy/nodes.py",
        "release/sbom.json",
        "scripts/verify_watermark.py",
    ]
    # 良性文件与未声明路径不落入受控集
    assert "README.md" not in offend
    assert "app/integrated_app/middleware/auth.py" not in offend


def test_prefix_does_not_over_match(mod):
    # app/integrated_app/security/ 前缀不应误伤 securityfoo.py（同级同名前缀文件）
    assert not mod._match("app/integrated_app/securityfoo.py", "app/integrated_app/security/")
    assert mod._match("app/integrated_app/security/x.py", "app/integrated_app/security/")
    # 精确文件条目不误伤兄弟文件
    assert mod._match("scripts/verify_watermark.py", "scripts/verify_watermark.py")
    assert not mod._match("scripts/verify_watermark.py.bak", "scripts/verify_watermark.py")


def test_main_blocks_restricted_and_passes_benign(mod, fixture_codeowners):
    co = str(fixture_codeowners)
    blocked = mod.main(
        ["prog", "--codeowners", co, "--file", "app/integrated_app/security/foo.py"],
        env={},
    )
    assert blocked == 1

    ok = mod.main(["prog", "--codeowners", co, "--file", "docs/readme.md"], env={})
    assert ok == 0


def test_main_override_allows_restricted(mod, fixture_codeowners):
    co = str(fixture_codeowners)
    rc = mod.main(
        ["prog", "--codeowners", co, "--file", "release/sbom.json"],
        env={"RESTRICTED_APPROVED": "1"},
    )
    assert rc == 0


def test_main_fail_closed_when_block_missing(mod, tmp_path):
    co = tmp_path / "CODEOWNERS"
    co.write_text("* @default\nscripts/ @owner\n", encoding="utf-8")
    rc = mod.main(["prog", "--codeowners", str(co), "--file", "README.md"], env={})
    assert rc == 1  # 无 RESTRICTED 区块 -> fail-closed，绝不静默放行


def test_main_listprints_patterns_exit_zero(mod, fixture_codeowners):
    rc = mod.main(["prog", "--codeowners", str(fixture_codeowners), "--list"], env={})
    assert rc == 0


def test_real_codeowners_blocks_security_change(mod):
    # 真实仓内 CODEOWNERS 必须把 app/integrated_app/security/ 声明为受控路径并拦下其改动
    assert _REAL_CODEOWNERS.is_file()
    # 防回归：脚本定位仓库根的 parents[] 若写错，DEFAULT_CODEOWNERS 会指向不存在的路径，
    # 使 main() 因“未找到 CODEOWNERS”而假性返回 1（并非真的拦下改动）。
    assert mod.DEFAULT_CODEOWNERS.is_file(), f"DEFAULT_CODEOWNERS 解析错误: {mod.DEFAULT_CODEOWNERS}"
    patterns = mod.load_restricted_patterns(_REAL_CODEOWNERS.read_text(encoding="utf-8"))
    assert "app/integrated_app/security/" in patterns
    assert "release/" in patterns
    assert "scripts/verify_watermark.py" in patterns
    # 走默认 CODEOWNERS：禁区改动 -> 阻断；良性改动 -> 放行（证明是“真拦下”而非“没找到”）
    assert mod.main(["prog", "--file", "app/integrated_app/security/path_guard.py"], env={}) == 1
    assert mod.main(["prog", "--file", "README.md"], env={}) == 0
