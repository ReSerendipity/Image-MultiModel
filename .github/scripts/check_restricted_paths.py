#!/usr/bin/env python3
"""structure-guard 禁区路径强制评审守卫：按 CODEOWNERS 声明的高影响路径过滤变更并强制独立审批。

背景（better-harness 发现）：AGENTS.md 把 comfy_kernel/、app/integrated_app/security/、release/、
demo/assets/、model/、backups/ 及签名/完整性工具脚本声明为「禁区」（禁止 AI 自动修改，须人工确认），
CODEOWNERS 也把分区 owner 声明齐全。但在单维护者 + 未开启 GitHub 分支保护的现实下，这些声明没有
任何「被跟踪」的强制层——PR 触碰禁区照样被默认 owner 一路放行。本守卫补一层仓内可见、可测、会红的
强制评审，与外部分支保护叠加。

工作方式：
  1. 从 .github/CODEOWNERS 的 RESTRICTED:BEGIN/END 区块解析受控路径前缀（单一事实来源，避免脚本与
     CODEOWNERS 两份清单漂移）。找不到区块即 fail-closed，绝不静默放行（吸取 check_spec_refs 教训）。
  2. 计算本次变更涉及的文件：CI 用 PR base/head SHA（或 GITHUB_EVENT_PATH），本地用与 main 的
     merge-base，再退化到暂存区/工作区。
  3. 只要有文件落入受控前缀即判 FAIL（硬阻断），输出需「独立 owner 审批 / 维护者显式放行」的动作项。
  4. 仅当维护者给出显式放行（环境变量 RESTRICTED_APPROVED=1，或 PR 带标签 restricted-approved）才放行。

GitHub 侧真正的 required review from CODEOWNERS 属外部授权，需在仓库分支保护里另行开启。

用法：
    python .github/scripts/check_restricted_paths.py                       # CI：按 env/GITHUB_EVENT 定变更集
    python .github/scripts/check_restricted_paths.py --file a --file b      # 指定变更文件（测试/手动）
    python .github/scripts/check_restricted_paths.py --from BASE --to HEAD  # 指定 diff 区间
    python .github/scripts/check_restricted_paths.py --codeowners PATH      # 指定 CODEOWNERS（默认仓内）
    python .github/scripts/check_restricted_paths.py --list                 # 打印解析到的受控路径前缀

退出码：0＝无禁区改动或已显式放行；1＝存在禁区改动（阻断）或配置缺失/无法定集（fail-closed）。
仅依赖标准库 + git。
"""

from __future__ import annotations

import json
import os
import subprocess  # nosec B404（仅以参数列表调用 git，无 shell=True）
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[2]  # .../.github/scripts/<file>.py -> 仓库根（本脚本比 scripts/ 深一层）
DEFAULT_CODEOWNERS = REPO_ROOT / ".github" / "CODEOWNERS"

BEGIN_MARK = "RESTRICTED:BEGIN"
END_MARK = "RESTRICTED:END"
EXEMPT_ENV = "RESTRICTED_APPROVED"
EXEMPT_LABELS = {"restricted-approved", "area:restricted-approved"}
TRUE_VALUES = {"1", "true", "yes", "on"}
_BASE_REFS = ("origin/main", "main", "origin/master", "master")


def load_restricted_patterns(text: str) -> list[str]:
    """从 CODEOWNERS 文本的 RESTRICTED 区块提取受控路径前缀（每行首个空白分隔 token）。"""
    patterns: list[str] = []
    inside = False
    for raw in text.splitlines():
        line = raw.strip()
        if BEGIN_MARK in line:
            inside = True
            continue
        if END_MARK in line:
            inside = False
            continue
        if not inside or not line or line.startswith("#"):
            continue
        token = line.split()[0]
        if token.startswith("/"):
            token = token[1:]
        if token and token not in patterns:
            patterns.append(token)
    return patterns


def _match(file: str, pattern: str) -> bool:
    f = file.replace("\\", "/")
    if pattern.endswith("*"):
        return f.startswith(pattern[:-1].lstrip("/"))
    if pattern.endswith("/"):
        return f.startswith(pattern.lstrip("/"))
    p = pattern.lstrip("/")
    return f == p or f.startswith(p + "/")


def offending_files(changed: list[str], patterns: list[str]) -> list[str]:
    return sorted({f for f in changed for p in patterns if _match(f, p)})


def _run_git(args: list[str], cwd: Path) -> str | None:
    try:
        proc = subprocess.run(  # nosec B603, B607（固定参数 git，只读查询）
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def _diff_names(base: str, head: str, cwd: Path) -> list[str] | None:
    out = _run_git(["diff", "--name-only", base, head], cwd)
    if out is None:
        return None
    return [x.replace("\\", "/") for x in out.splitlines() if x]


def _load_event(env: dict[str, str]) -> dict:
    ev = env.get("GITHUB_EVENT_PATH")
    if not ev:
        return {}
    p = Path(ev)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def resolve_changed_files(
    files_arg: list[str],
    base: str | None,
    head: str | None,
    event: dict,
    env: dict[str, str],
    cwd: Path,
) -> tuple[list[str], str]:
    """返回 (变更文件列表, 定集方式 how)。

    how ∈ {explicit, sha, failed, mergebase, dirty}；failed 表示给了 base/head 却取不到
    （浅克隆丢提交），CI 下应据此 fail-closed。
    """
    if files_arg:
        return [x.replace("\\", "/") for x in files_arg], "explicit"

    base = base or env.get("BASE_SHA") or env.get("RESTRICTED_BASE_SHA")
    head = head or env.get("HEAD_SHA") or env.get("RESTRICTED_HEAD_SHA")
    pr = event.get("pull_request") or {}
    base = base or (pr.get("base") or {}).get("sha")
    head = head or (pr.get("head") or {}).get("sha")

    if base and head:
        names = _diff_names(base, head, cwd)
        return (names, "sha") if names is not None else ([], "failed")

    for ref in _BASE_REFS:
        mb = _run_git(["merge-base", ref, "HEAD"], cwd)
        if mb:
            names = _diff_names(mb, "HEAD", cwd)
            if names is not None:
                return names, "mergebase"

    staged = _run_git(["diff", "--name-only", "--cached"], cwd) or ""
    worktree = _run_git(["diff", "--name-only", "HEAD"], cwd) or ""
    untracked = _run_git(["ls-files", "--others", "--exclude-standard"], cwd) or ""
    combined = {x.replace("\\", "/") for block in (staged, worktree, untracked) for x in block.splitlines() if x}
    return sorted(combined), "dirty"


def is_approved(env: dict[str, str], event: dict) -> bool:
    if env.get(EXEMPT_ENV, "").strip().lower() in TRUE_VALUES:
        return True
    labels = {
        lab.get("name", "") for lab in (event.get("pull_request") or {}).get("labels") or [] if isinstance(lab, dict)
    }
    return bool(labels & EXEMPT_LABELS)


def _is_ci(env: dict[str, str]) -> bool:
    if env.get("GITHUB_ACTIONS", "").strip().lower() in TRUE_VALUES:
        return True
    return env.get("CI", "").strip().lower() not in ("", "0", "false")


def main(argv: list[str], env: dict[str, str] | None = None) -> int:
    environment = dict(os.environ if env is None else env)
    args = argv[1:]

    files_arg: list[str] = []
    base = head = co_path = None
    list_only = verbose = False

    i = 0
    while i < len(args):
        a = args[i]
        if a == "--file" and i + 1 < len(args):
            files_arg.append(args[i + 1])
            i += 2
            continue
        if a == "--files":
            i += 1
            while i < len(args) and not args[i].startswith("--"):
                files_arg.append(args[i])
                i += 1
            continue
        if a == "--from" and i + 1 < len(args):
            base = args[i + 1]
            i += 2
            continue
        if a == "--to" and i + 1 < len(args):
            head = args[i + 1]
            i += 2
            continue
        if a == "--codeowners" and i + 1 < len(args):
            co_path = args[i + 1]
            i += 2
            continue
        if a == "--list":
            list_only = True
        elif a in ("--verbose", "-v"):
            verbose = True
        i += 1

    co = Path(co_path) if co_path else DEFAULT_CODEOWNERS
    if not co.is_file():
        print(f"FAIL: 未找到 CODEOWNERS：{co}")
        return 1
    text = co.read_text(encoding="utf-8", errors="replace")
    patterns = load_restricted_patterns(text)
    if not patterns:
        print(
            f"FAIL: {co.name} 中未找到 RESTRICTED:BEGIN/END 区块。守卫 fail-closed，拒绝静默放行——请补回禁区声明区块。"
        )
        return 1

    if list_only:
        print("\n".join(patterns))
        return 0

    event = _load_event(environment)
    files, how = resolve_changed_files(files_arg, base, head, event, environment, REPO_ROOT)
    in_ci = _is_ci(environment)

    if how == "failed" and in_ci:
        print(
            "FAIL: 无法确定本次变更文件集（base/head SHA 在浅克隆中不可用）。守卫 fail-closed——"
            "请确认 checkout 使用 fetch-depth: 0 且 BASE_SHA/HEAD_SHA 有效。"
        )
        return 1

    offend = offending_files(files, patterns)
    if verbose or not offend:
        print(f"[restricted-guard] change-set={len(files)} files via {how}; restricted patterns={len(patterns)}")

    if not offend:
        print("restricted-paths: OK (no restricted path touched)")
        return 0

    if is_approved(environment, event):
        print(f"restricted-paths: PASS（维护者显式放行）— 本次触碰 {len(offend)} 个禁区路径：")
        for f in offend:
            print(f"  APPROVED   {f}")
        return 0

    ann = "::error::" if in_ci else ""
    print(
        f"{ann}restricted-paths: FAIL — 禁区/高影响路径被修改，需不同于默认路由的独立 owner 审批"
        "（默认 CODEOWNERS 路由不足以放行）。"
    )
    for f in offend:
        print(f"  RESTRICTED {f}")
    print("  放行方式：维护者显式确认 —— 给 PR 打标签 restricted-approved，或运行环境设 RESTRICTED_APPROVED=1；")
    print("  并（外部授权）在仓库分支保护里开启 required review from CODEOWNERS。")
    print(f"\nstructure-guard: 禁区改动 {len(offend)} 个文件被阻断。")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
