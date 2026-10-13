#!/usr/bin/env python3
"""规范文件（AGENTS.md / README.md / .qoder/rules/agent-baseline.md）引用一致性门禁——双模：仓内自检 + 家族增强层。

背景（better-harness 发现）：旧版本脚本只是外部家族审计器（.spec_audit）的极薄包装，
在干净 CI checkout 中因找不到审计器而直接输出 "skip" 并以 0 退出——于是
docs-consistency.yml / structure-guard.yml 永远绿，实际从未校验任何文档路径引用
（正是 AGENTS.md 铁律 #6「证据绑定」禁止的"把不存在的门禁写成 CI 阻断"）。

现在拆成两层：

1. 仓内自检（self-check，始终执行，不依赖任何仓外组件）
   仅校验 AGENTS.md / README.md 中以反引号 inline code 或 markdown 相对链接出现的
   **仓内相对路径引用**是否真实存在。产出真实的 clean / gap 结论。
     - 本地（默认，未设 CI）＝严格模式：缺失即 gap。
     - CI（环境变量 CI 为真值）＝宽松模式：对落在被 .gitignore 排除、且干净 checkout
       不存在的仓内根（docs/、comfy_kernel/、model/ 等本地保留目录）的引用降级为 skip，
       避免"仅本地保留的文档"在 CI 里被误判为断链。
   这就是「本地 / CI 两种模式」的显式区分——"skip 即绿"不再无条件生效。

2. 家族增强层（enhancement，可选）
   若在本仓或父目录发现 .spec_audit/audit_spec_refs.py，则额外运行家族审计并合并结论。
   找不到增强层时**不再整门禁 skip**：本地自检结论即为权威结论，仅提示增强层不可用。

用法：
    python scripts/check_spec_refs.py                 # 自检（按 CI 环境变量自动定模式）+ 增强层（若在）
    python scripts/check_spec_refs.py --self          # 只跑仓内自检，跳过家族增强层
    python scripts/check_spec_refs.py --strict        # 强制严格模式（本地保留根也校验）
    python scripts/check_spec_refs.py --enh-gate      # 让家族增强层的高置信发现也驱动退出码
    python scripts/check_spec_refs.py --verbose       # 打印 clean 明细

退出码：0＝clean；1＝存在 gap（失效路径引用）。
仅依赖标准库 + git（宽松模式的 .gitignore 判定）。
"""

from __future__ import annotations

import json
import os
import re
import subprocess  # nosec B404（仅以参数列表调用 git / 审计器，无 shell=True）
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[1]
DEFAULT_DOCS = (
    "AGENTS.md",  # 本地保留（被 .gitignore 排除）：CI 检出里不存在 → 记为 skip，不判失败
    "README.md",
    # 可分发 agent 基线指令层（随仓库发布，干净克隆 / CI 检出必然存在）。
    # 纳入自检是为了让这一层的仓内路径引用同样受门禁约束，而不是写完就烂——
    # 因此这里出现的仓内路径一律必须是**被 git 跟踪**的路径（本地保留文档只用自然语言指代）。
    ".qoder/rules/agent-baseline.md",
)

# ── 抽取：inline code（单/双反引号）+ markdown 相对链接目标 ──────────────
_CODE_SPAN_RE = re.compile(r"(?<!`)`{1,2}(?!`)(.+?)(?<!`)`{1,2}(?!`)")
_LINK_TARGET_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_ANCHOR_RE = re.compile(r"[#?].*$")

# 被视为"路径引用"的文件扩展名（含点）。主要用于 markdown 链接目标。
_EXT_RE = re.compile(
    r"\.(md|py|pyi|yaml|yml|toml|json|txt|sh|bash|bat|cmd|ps1|nsi|rs|js|ts|html|css|csv|"
    r"ini|cfg|xml|nix|lock|go|java|kt|sql|png|jpe?g|gif|svg|ico|webp|pdf|zip|7z|whl|pem|env)$",
    re.IGNORECASE,
)
# 无路径分隔、但确为仓库根文件的裸名（始终校验）。
_BARE_NAMES = {"LICENSE", "NOTICE", "README", "CHANGELOG", "Dockerfile", "Makefile"}
_SEG_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-*")
_ABS_RE = re.compile(r"^([A-Za-z]:[\\/]|/|~/|\\\\)")

# 构建产物 / 缓存目录名（AGENTS.md 滚动清理铁律下"本就该不存在"，任一路径段命中即视为产物）。
_ARTIFACT_SEGS = {
    "target",
    "dist",
    "build",
    "__pycache__",
    "installer-data",
    "tauri-release",
    "staging",
    "htmlcov",
    "cover",
    "coverage",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    ".uv-cache",
    ".parcel-cache",
    ".hypothesis",
    ".benchmarks",
    ".trash",
}
# 安装/构建期动态生成的可选目录（非仓库静态内容）。
_OPTIONAL_EXACT = {"app/runtime", "release/packages"}
# 可选 / 版本化外部运行时目录（本机 Python 分发，非仓库内容）。
_RUNTIME_PATTERNS = [re.compile(r"^WPy\d"), re.compile(r"^WinPython", re.IGNORECASE)]
# 行内出现这些限定语时，其路径引用属"条件/计划"表述（铁律 #6 允许），不作失效判定。
_CONDITIONAL_MARKERS = (
    "若本仓存在",
    "当前本仓无",
    "计划，未实现",
    "（计划",
    "计划:",
    "计划:",
    "若存在",
    "尚未实现",
    "TODO",
)


def _seg_valid(s: str) -> bool:
    return bool(s) and set(s) <= _SEG_CHARS and s not in (".", "..")


def _looks_pathlike(norm: str, *, is_link: bool, children: set[str]) -> bool:
    """判断 token 是否为"仓内相对路径引用"。

    - inline code（is_link=False）：仅当它是嵌套路径（含内层 `/` 且首段确为仓库顶层条目）
      或命中裸文件名时才算——以此过滤端口号 / 配置键 / 引擎 key / 单词 / 模块路径等误报。
    - markdown 链接目标（is_link=True）：更宽松，嵌套路径 / 带扩展名 / 裸名均视为链接。
    """
    if not norm or " " in norm or "`" in norm:
        return False
    if "://" in norm or norm.startswith("mailto:") or _ABS_RE.match(norm):
        return False
    stripped = norm.rstrip("/")
    segs = [s for s in stripped.split("/") if s]
    if not segs or not all(_seg_valid(s) for s in segs):
        return False
    has_inner_slash = len(segs) >= 2
    name = segs[-1]
    if name in _BARE_NAMES and not has_inner_slash:
        return True
    if is_link:
        return has_inner_slash or bool(_EXT_RE.search(stripped)) or name in _BARE_NAMES
    # inline code
    if not has_inner_slash:
        return False
    return segs[0] in children


def _is_artifact_or_optional(norm: str) -> bool:
    stripped = norm.rstrip("/")
    segs = [s for s in stripped.split("/") if s]
    return (
        any(s in _ARTIFACT_SEGS or s.startswith("*") for s in segs)
        or stripped in _OPTIONAL_EXACT
        or any(stripped.startswith(e + "/") for e in _OPTIONAL_EXACT)
    )


def _is_runtime_dir(norm: str) -> bool:
    return any(p.search(seg) for seg in norm.split("/") if seg for p in _RUNTIME_PATTERNS)


def _line_is_conditional(line: str) -> bool:
    return any(m in line for m in _CONDITIONAL_MARKERS)


def _iter_candidates(text: str):
    """yield (lineno, token, is_link) —— 跳过围栏代码块，仅取 inline code 与相对链接目标。"""
    in_fence = False
    for i, line in enumerate(text.splitlines(), 1):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for m in _CODE_SPAN_RE.finditer(line):
            yield i, m.group(1).strip(), False
        for m in _LINK_TARGET_RE.finditer(line):
            yield i, m.group(1).strip(), True


def _normalize(token: str) -> str:
    ref = _ANCHOR_RE.sub("", token).strip()
    ref = ref.replace("\\", "/")
    ref = re.sub(r"^\./", "", ref)
    return ref


def _resolve_trailing_star(norm: str) -> tuple[str, bool]:
    """把 `app/**` / `comfy_kernel/**` 归一到通配前的真实目录前缀（trailing_glob=True）。

    返回 ("", False) 表示无法定址（如以通配结尾但前面无 `/` 的 `*.md`）。
    """
    if not any(ch in norm for ch in "*?"):
        return norm, False
    prefix = norm
    while prefix and prefix[-1] not in "/":
        prefix = prefix[:-1]
    if prefix.endswith("/"):
        return prefix, True
    return "", False


def _paths_ignored(root: Path, rel_paths: list[str]) -> set[str]:
    """用 git check-ignore --stdin 批量判定哪些相对路径被 .gitignore 命中（宽松模式用）。"""
    paths = sorted(set(rel_paths))
    if not paths:
        return set()
    try:
        proc = subprocess.run(  # nosec B603, B607（固定参数 git，只读判定）
            ["git", "-C", str(root), "check-ignore", "--stdin"],
            input="\n".join(paths),
            capture_output=True,
            text=True,
        )
    except OSError:
        return set()
    return {ln.strip() for ln in proc.stdout.splitlines() if ln.strip()}


def _is_ci_env() -> bool:
    return os.environ.get("CI", "").strip().lower() not in ("", "0", "false")


def run_self_check(
    root: Path,
    docs: list[Path] | None = None,
    *,
    strict: bool | None = None,
    verbose: bool = False,
) -> tuple[int, int, int, list[str]]:
    """仓内自检：返回 (checked, skipped, gap_count, gap_lines)。

    strict=None 时按 CI 环境变量自动定模式（本地=严格，CI=宽松）。
    宽松模式：被 .gitignore 排除、且其仓内根在干净 checkout 中不存在的本地保留引用降级为 skip。
    """
    lenient = (strict is False) if strict is not None else _is_ci_env()

    if docs is None:
        docs = [root / name for name in DEFAULT_DOCS]
    try:
        children = {p.name for p in root.iterdir()}
    except OSError:
        children = set()

    hits: dict[str, int] = {}  # rel -> 命中数（真实存在的引用）
    misses: dict[str, list[tuple[str, int, str]]] = {}  # rel -> [(doc, line, token)]
    skipped = 0
    root_missing_cache: dict[str, bool] = {}

    def _root_missing(rel: str) -> bool:
        comp = rel.split("/", 1)[0]
        if comp not in root_missing_cache:
            root_missing_cache[comp] = not (root / comp).exists()
        return root_missing_cache[comp]

    for doc in docs:
        if not doc.exists():
            # 文档本身缺失（如 CI 未 checkout 本地保留的 AGENTS.md）：记为 skip，不因此判失败。
            skipped += 1
            if verbose:
                print(f"  SKIP   (doc absent) {doc.name}")
            continue
        text = doc.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        rel_doc = doc.relative_to(root).as_posix() if doc.is_relative_to(root) else doc.name
        for lineno, token, is_link in _iter_candidates(text):
            norm = _normalize(token)
            if not norm or not _looks_pathlike(norm, is_link=is_link, children=children):
                continue
            resolved, trailing_glob = _resolve_trailing_star(norm)
            if resolved == "":
                skipped += 1  # 无法定址的通配（如 *.md）
                continue
            target = (root / resolved.rstrip("/")).resolve()
            hit = target.is_dir() if trailing_glob else target.exists()
            if hit:
                hits[resolved] = hits.get(resolved, 0) + 1
                continue
            # 未命中：先做与文件系统无关的静态过滤
            if _is_artifact_or_optional(norm) or _is_runtime_dir(norm):
                skipped += 1
                continue
            line_text = lines[lineno - 1] if 0 < lineno <= len(lines) else ""
            if _line_is_conditional(line_text):
                skipped += 1
                continue
            misses.setdefault(resolved, []).append((rel_doc, lineno, norm))

    # 宽松模式：把落在"被 gitignore 且其根不存在"的本地保留引用降级为 skip。
    if lenient and misses:
        ignored = _paths_ignored(root, list(misses))
        for rel in list(misses):
            if rel in ignored and _root_missing(rel):
                skipped += len(misses.pop(rel))

    gap_lines = [
        f"  GAP    {doc_name}:{lineno} -> {norm}  (路径不存在)"
        for rel in sorted(misses)
        for doc_name, lineno, norm in misses[rel]
    ]

    if verbose:
        for rel in sorted(hits):
            print(f"  OK     {rel}  ({hits[rel]}x)")

    return sum(hits.values()), skipped, len(gap_lines), gap_lines


def _family_enhancement(root: Path) -> tuple[bool, int]:
    """家族增强层（可选，默认 advisory）：找到并运行外部 .spec_audit 审计器并打印其结论。

    返回 (available, rc)：available=False 表示审计器不存在或自身执行异常（此时以本地自检为权威、
    不阻断）；available=True 时 rc 为家族审计器高置信结论（0=家族层通过，非 0=发现新问题），
    仅用于展示——除非调用方显式要求 --enh-gate，否则不驱动门禁退出码。

    注意：家族审计器在"有发现"时以非 0 退出（如 3），这是结论而非崩溃；故此处不得用 check=True。
    """
    auditors = [
        root / ".spec_audit" / "audit_spec_refs.py",
        root.parent / ".spec_audit" / "audit_spec_refs.py",
    ]
    auditor = next((p for p in auditors if p.is_file()), None)
    if auditor is None:
        print("[enhance] 家族审计器 (.spec_audit) 不可用：以本地自检结论为权威（已不再 'skip 即绿'，见 docstring）")
        return False, 0

    with tempfile.TemporaryDirectory(prefix="spec_audit_") as td:
        out = Path(td) / "current.json"
        out_md = Path(td) / "current.md"
        proc = subprocess.run(  # nosec B603, B607（固定参数运行已知审计器，无 shell=True）
            [sys.executable, str(auditor), "--project", root.name, "--json", str(out), "--md", str(out_md)],
            capture_output=True,
            text=True,
        )
        if not out.is_file():
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()
            note = tail[-1] if tail else f"exit={proc.returncode}"
            print(f"[enhance] 家族审计器执行异常，已忽略（本地自检仍为权威）：{note[:200]}")
            return False, 0
        try:
            data = json.loads(out.read_text(encoding="utf-8"))[0]
        except (ValueError, KeyError, IndexError) as exc:
            print(f"[enhance] 家族审计器输出解析失败，已忽略：{exc}")
            return False, 0

    hard = [f for f in data.get("findings", []) if f.get("status") == "PHANTOM" and f.get("tier") == "ASSERTIVE"]
    dl = data.get("dead_links", [])
    wf = data.get("workflows", {}).get("missing", [])
    pc = data.get("precommit", {}).get("declared_not_configured", [])
    print(
        f"[enhance] family auditor (advisory): phantom={len(hard)} dead_links={len(dl)} "
        f"bad_workflow={len(wf)} bad_hook={len(pc)}"
    )
    for x in hard:
        print(f"  PHANTOM {x['ref']}  in {', '.join(x['specs'])}")
    for d in dl:
        print(f"  DEAD    {d['spec']}:{d['line']} -> {d['link']}")
    return True, (1 if (hard or dl or wf or pc) else 0)


def main(argv: list[str]) -> int:
    args = argv[1:]
    self_only = "--self" in args or "--self-only" in args
    strict = True if "--strict" in args else None
    verbose = "--verbose" in args or "-v" in args

    docs: list[Path] | None = None
    if "--doc" in args:
        idx = args.index("--doc")
        docs = []
        for x in args[idx + 1 :]:
            if x.startswith("--"):
                break
            docs.append(Path(x) if Path(x).is_absolute() else REPO_ROOT / x)

    lenient = (strict is False) if strict is not None else _is_ci_env()
    mode = "lenient(CI)" if lenient else "strict(local)"
    print(f"[self-check] repo-internal reference integrity (mode={mode})")
    checked, skipped, gaps, gap_lines = run_self_check(REPO_ROOT, docs, strict=strict, verbose=verbose)
    for line in gap_lines:
        print(line)
    print(f"[self-check] {'FAIL' if gaps else 'PASS'}: checked={checked} skipped={skipped} gaps={gaps}")

    self_rc = 1 if gaps else 0
    if self_only:
        return self_rc

    # 门禁退出码由本地自检决定；家族增强层默认仅提示，除非显式 --enh-gate。
    available, enh_rc = _family_enhancement(REPO_ROOT)
    if "--enh-gate" in args and available and enh_rc:
        print("[enhance] --enh-gate 生效：家族审计器发现高置信问题，计入门禁退出码")
        return 1
    return self_rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
