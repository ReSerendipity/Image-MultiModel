#!/usr/bin/env python3
"""scripts/build_release_metadata.py — P1-10 不可变版本 artifact 元数据生成器。

评估 §9-P1-10 要求：
  1. Compose 镜像从 `latest` 改为 Git SHA / 语义版本 tag；
  2. 镜像、代码、workflow、comfy_kernel、模型 manifest 形成可追溯版本；
  3. 发布前生成 SBOM、镜像 digest 和配置快照。

本脚本产出：
  - `.env`            → `IMAGE_TAG` / `IMAGE_DIGEST`（供 docker-compose.yml 插值，禁止 latest）
  - `<out>/build_metadata.json` → Git/配置/workflow/模型/comfy_kernel 的可追溯快照
  - `<out>/sbom.json`           → CycloneDX 1.5 精简 SBOM（解析 requirements-lock.txt）

comfy_kernel 溯源边界：
  `comfy_kernel/` 是独立嵌套 git 仓库且被 .gitignore 排除（禁区，不入本仓跟踪面），
  干净 checkout / CI 上该目录不存在，tree_digest 只能给出 present=false + 空摘要。
  为此仓内跟踪一份来源凭证 `kernel_provenance.json`（{origin, upstream_commit,
  captured_at}）：目录缺失时 meta.artifacts.comfy_kernel 回填 `provenance`（凭证）；
  目录存在时额外记录 `upstream`（本机嵌套仓实时 commit/origin）。内核结构摘要
  （digest）仍仅本机可生成——这是有意边界，跨机可比的是 commit 级溯源而非文件树摘要。

用法：
    python scripts/build_release_metadata.py                    # 开发/本地：tag = git-<sha12>
    python scripts/build_release_metadata.py --version v2.0.1   # 发布：tag = 2.0.1
    python scripts/build_release_metadata.py --dev              # 等价于默认（显式声明本地构建）
    python scripts/build_release_metadata.py --verify           # 校验既有产物与工作树是否漂移
    python scripts/build_release_metadata.py --no-model-hash    # 跳过模型权重哈希（大仓库加速）
    python scripts/build_release_metadata.py --capture-provenance  # 刷新内核来源凭证（只读查询 comfy_kernel 嵌套仓）
    python scripts/build_release_metadata.py --root <dir>       # 测试用：替换工作树根（模拟干净 checkout）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA_VERSION = "1.0"

# 语义版本：v2.0.1 / 2.0.1 / 2.0.1-rc.1
_SEMVER_RE = re.compile(r"^v?\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
# git tag：git-<7~40 位十六进制>
_GITTAG_RE = re.compile(r"^git-[0-9a-f]{7,40}$")
# 明确禁止的可变 tag
_FORBIDDEN_TAGS = {"latest", "", "dev", "stable", "main", "master", "edge", "nightly"}

# 超过该体积的文件只记录 size，不计算 sha256（避免大权重拖慢发布）
_MODEL_HASH_LIMIT_BYTES = 512 * 1024 * 1024

_ENV_KEYS = ("IMAGE_TAG", "IMAGE_DIGEST")


# ────────────────────────── Git 信息 ──────────────────────────
def _git(root: Path, *args: str) -> str:
    """执行 git 子命令，失败（非仓库 / 未安装）时返回空串。"""
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception:  # pragma: no cover - git 缺失 / 超时
        return ""
    if out.returncode != 0:
        return ""
    return out.stdout.strip()


def git_sha(root: Path = ROOT) -> str:
    return _git(root, "rev-parse", "HEAD")


def git_describe(root: Path = ROOT) -> str:
    return _git(root, "describe", "--tags", "--always", "--dirty")


def git_dirty(root: Path = ROOT) -> bool:
    return bool(_git(root, "status", "--porcelain"))


# ────────────────────────── Tag 规则 ──────────────────────────
def is_valid_image_tag(tag: str) -> bool:
    """镜像 tag 必须为语义版本或 git-<sha>，且不得为 latest 等可变 tag。"""
    if not tag or tag.strip().lower() in _FORBIDDEN_TAGS:
        return False
    return bool(_SEMVER_RE.match(tag) or _GITTAG_RE.match(tag))


def derive_image_tag(sha: str, version: str = "") -> str:
    """由语义版本 / Git SHA 推导不可变镜像 tag。

    Args:
        sha: 完整 Git SHA；为空时回退为 `git-unknown`（会被 is_valid_image_tag 拒绝）。
        version: 发布版本号（`v2.0.1` 或 `2.0.1`）；为空时使用 `git-<sha[:12]>`。
    """
    if version:
        return version[1:] if version.startswith("v") else version
    short = sha[:12] if sha else "unknown"
    return f"git-{short}"


# ────────────────────────── 哈希 / 快照 ──────────────────────────
def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def read_kernel_provenance(root: Path) -> dict:
    """读取仓内跟踪的内核来源凭证 kernel_provenance.json；缺失/损坏返回空 dict。"""
    path = root / "kernel_provenance.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):  # pragma: no cover - 损坏凭证降级为空
        return {}
    return data if isinstance(data, dict) else {}


def capture_kernel_provenance(root: Path = ROOT) -> int:
    """从本机 comfy_kernel/ 嵌套仓（只读 git 查询）刷新 kernel_provenance.json。

    comfy_kernel/ 是禁区：本函数只运行只读的 `git rev-parse` / `git remote` /
    `git log`，绝不改写内核仓内容。
    """
    kb = root / "comfy_kernel"
    if not kb.is_dir():
        print("[FAIL] comfy_kernel/ 目录不存在，无法采集凭证（可在有内核的机器上运行本命令）")
        return 1
    commit = _git(kb, "rev-parse", "HEAD")
    date = _git(kb, "log", "-1", "--format=%aI")
    origin = ""
    for line in _git(kb, "remote", "-v").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "origin" and "(fetch)" in line:
            origin = parts[1]
            break
    version = ""
    ver_file = kb / "comfyui_version.py"
    if ver_file.is_file():
        m = re.search(r"__version__\s*=\s*[\"']([^\"']+)[\"']", ver_file.read_text(encoding="utf-8", errors="replace"))
        version = m.group(1) if m else ""
    doc = {
        "schema_version": "1.0",
        "path": "comfy_kernel",
        "origin": origin,
        "remote_name": "origin",
        "upstream_commit": commit,
        "upstream_commit_date": date,
        "upstream_version": version,
        "captured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "note": (
            "comfy_kernel/ 为独立嵌套 git 仓库且被 .gitignore 排除（禁区，不入本仓跟踪面）；"
            "本凭证为其来源快照，干净 checkout 下 build_release_metadata.py 以此回填 "
            "meta.artifacts.comfy_kernel.provenance。更新方式：在 comfy_kernel/ 内只读运行 "
            "`git rev-parse HEAD` 与 `git remote -v`，或直接运行 "
            "`python scripts/build_release_metadata.py --capture-provenance`。"
        ),
    }
    if not commit or not origin:
        print("[FAIL] 未能从 comfy_kernel/ 读到 HEAD 或 origin，不写入残缺凭证")
        return 1
    out = root / "kernel_provenance.json"
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[INFO] 已刷新 {out}（upstream={origin}@{commit[:12]}）")
    return 0


def kernel_upstream_live(kernel_dir: Path) -> dict:
    """本机 comfy_kernel/ 嵌套仓的实时溯源（只读）；非 git 仓库时返回空 dict。"""
    commit = _git(kernel_dir, "rev-parse", "HEAD")
    if not commit:
        return {}
    origin = ""
    for line in _git(kernel_dir, "remote", "-v").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "origin" and "(fetch)" in line:
            origin = parts[1]
            break
    return {"commit": commit, "origin": origin, "commit_date": _git(kernel_dir, "log", "-1", "--format=%aI")}


def tree_digest(root: Path, rel_dir: str, absent_payload: dict | None = None) -> dict:
    """对目录做「结构摘要」：文件名 + 体积排序后取 sha256。

    用于 comfy_kernel/ 这类上千文件的 vendored 目录 —— 逐个哈希过慢，
    结构摘要足以在发布追溯中证明「当时用的是哪一份上游副本」。

    Args:
        absent_payload: 目录缺失时的补充字段（如 {"provenance": 来源凭证}），
            使干净 checkout 也能回答「当时用的是哪份上游内核」而非留空。
    """
    base = root / rel_dir
    if not base.is_dir():
        out = {"path": rel_dir, "present": False, "file_count": 0, "total_bytes": 0, "digest": ""}
        if absent_payload:
            out.update(absent_payload)
        return out
    entries: list[tuple[str, int]] = []
    for p in base.rglob("*"):
        if p.is_file():
            try:
                entries.append((p.relative_to(base).as_posix(), p.stat().st_size))
            except OSError:  # pragma: no cover - 权限/竞态
                continue
    entries.sort()
    payload = "\n".join(f"{rel}:{size}" for rel, size in entries)
    return {
        "path": rel_dir,
        "present": True,
        "file_count": len(entries),
        "total_bytes": sum(size for _, size in entries),
        "digest": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    }


def model_manifest(root: Path, with_hash: bool = True) -> dict:
    """生成 model/ 目录清单（名称 + 体积，可选 sha256）。"""
    base = root / "model"
    files: list[dict] = []
    if base.is_dir():
        for p in sorted(base.rglob("*")):
            if not p.is_file():
                continue
            try:
                size = p.stat().st_size
            except OSError:  # pragma: no cover
                continue
            item = {"path": p.relative_to(base).as_posix(), "bytes": size, "sha256": ""}
            if with_hash and size <= _MODEL_HASH_LIMIT_BYTES:
                item["sha256"] = sha256_file(p)
            files.append(item)
    return {
        "path": "model",
        "file_count": len(files),
        "total_bytes": sum(f["bytes"] for f in files),
        "hashed": with_hash,
        "files": files,
    }


def config_snapshot(root: Path) -> dict:
    """配置快照：config.yaml 内容哈希（不含敏感值原文）。"""
    cfg = root / "config.yaml"
    if not cfg.is_file():
        return {"path": "config.yaml", "present": False, "sha256": "", "bytes": 0}
    return {
        "path": "config.yaml",
        "present": True,
        "sha256": sha256_file(cfg),
        "bytes": cfg.stat().st_size,
    }


def workflow_snapshot(root: Path) -> dict:
    """workflow JSON 清单：逐个哈希（文件数少，可精确定位变更）。"""
    base = root / "workflows"
    files: list[dict] = []
    if base.is_dir():
        for p in sorted(base.rglob("*.json")):
            files.append({"path": p.relative_to(root).as_posix(), "sha256": sha256_file(p)})
    return {"path": "workflows", "file_count": len(files), "files": files}


# ────────────────────────── SBOM ──────────────────────────
def parse_requirements(text: str) -> list[tuple[str, str]]:
    """解析 `name==version` 行；忽略注释、空行、`-r`/`--` 指令与 extras。"""
    out: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        if "==" not in line:
            continue
        name, _, version = line.partition("==")
        name = name.split("[", 1)[0].strip()
        version = version.split(";", 1)[0].strip()
        if name and version:
            out.append((name, version))
    return out


def build_sbom(requirements_text: str, image_tag: str, git_sha_value: str) -> dict:
    """构造 CycloneDX 1.5 精简 SBOM。"""
    components = [
        {
            "type": "library",
            "name": name,
            "version": version,
            "purl": f"pkg:pypi/{name.lower()}@{version}",
            "bom-ref": f"pkg:pypi/{name.lower()}@{version}",
        }
        for name, version in sorted(parse_requirements(requirements_text))
    ]
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
            "component": {
                "type": "application",
                "name": "image-multimodel",
                "version": image_tag,
                "bom-ref": "image-multimodel",
            },
            "properties": [
                {"name": "git.sha", "value": git_sha_value or "unknown"},
                {"name": "image.tag", "value": image_tag},
            ],
        },
        "components": components,
    }


# ────────────────────────── 汇总 ──────────────────────────
def build_metadata(
    root: Path = ROOT,
    version: str = "",
    with_model_hash: bool = True,
) -> dict:
    """汇总可追溯元数据（纯读取，不写文件；便于单测）。"""
    sha = git_sha(root)
    tag = derive_image_tag(sha, version)
    lock = root / "requirements-lock.txt"
    provenance = read_kernel_provenance(root)
    kb_dir = root / "comfy_kernel"
    kernel_kwargs: dict = {}
    if kb_dir.is_dir():
        # 目录在场：摘要可全量生成；同时记录实时溯源，并与入库凭证交叉标注一致性
        live = kernel_upstream_live(kb_dir)
        kernel_kwargs["upstream"] = live or None
        if live and provenance:
            kernel_kwargs["provenance_matches"] = live.get("commit") == provenance.get("upstream_commit")
    else:
        # 目录缺失（干净 checkout / CI）：回填入库来源凭证，而非留下空白
        kernel_kwargs["provenance"] = provenance or "N/A（仓内无 kernel_provenance.json，内核溯源不可回答）"
    kernel = tree_digest(root, "comfy_kernel", kernel_kwargs if not kb_dir.is_dir() else None)
    if kb_dir.is_dir():
        kernel.update(kernel_kwargs)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "image_tag": tag,
        "image_tag_valid": is_valid_image_tag(tag),
        "git": {
            "sha": sha,
            "short_sha": sha[:12] if sha else "",
            "describe": git_describe(root),
            "dirty": git_dirty(root),
        },
        "build": {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        },
        "artifacts": {
            "config": config_snapshot(root),
            "workflows": workflow_snapshot(root),
            "model": model_manifest(root, with_hash=with_model_hash),
            "comfy_kernel": kernel,
        },
        "requirements_lock_sha256": sha256_file(lock) if lock.is_file() else "",
    }


# ────────────────────────── .env 合并写入 ──────────────────────────
def merge_env_file(path: Path, updates: dict[str, str]) -> str:
    """把 updates 合并进 .env，保留其余行；返回最终内容。"""
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    out: list[str] = []
    seen: set[str] = set()
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in updates:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out.append(line)
    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}")
    return "\n".join(out) + "\n"


# ────────────────────────── 校验模式 ──────────────────────────
def verify(root: Path, out_dir: Path, strict: bool = False) -> list[str]:
    """校验既有产物是否与当前工作树漂移；返回问题列表（空 = 通过）。

    Args:
        strict: True 时追加「工作树必须干净」检查（仅正式发布使用；
            PR 构建工作树天然 dirty，不应因此失败）。
    """
    problems: list[str] = []
    meta_path = out_dir / "build_metadata.json"
    if not meta_path.is_file():
        return [f"缺少 {meta_path}，请先运行本脚本生成发布元数据"]

    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    tag = str(meta.get("image_tag", ""))
    if not is_valid_image_tag(tag):
        problems.append(f"image_tag={tag!r} 不是不可变 tag（须为语义版本或 git-<sha>，禁止 latest）")

    if strict and meta.get("git", {}).get("dirty"):
        problems.append("生成元数据时工作树为 dirty，不可用于正式发布")

    cur_cfg = config_snapshot(root)
    old_cfg = meta.get("artifacts", {}).get("config", {})
    if old_cfg.get("present") and cur_cfg.get("sha256") != old_cfg.get("sha256"):
        problems.append("config.yaml 快照已漂移（配置在元数据生成后被修改）")

    cur_wf = {f["path"]: f["sha256"] for f in workflow_snapshot(root)["files"]}
    old_wf = {f["path"]: f["sha256"] for f in meta.get("artifacts", {}).get("workflows", {}).get("files", [])}
    if cur_wf != old_wf:
        problems.append("workflows/ 快照已漂移")

    sbom_path = out_dir / "sbom.json"
    if not sbom_path.is_file():
        problems.append(f"缺少 {sbom_path}（SBOM 必须在发布前生成）")
    return problems


# ────────────────────────── CLI ──────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="P1-10 不可变版本 artifact 元数据生成器")
    ap.add_argument("--version", default="", help="发布版本号（v2.0.1 / 2.0.1）；留空则用 git-<sha>")
    ap.add_argument("--dev", action="store_true", help="显式声明本地构建（等价于不传 --version）")
    ap.add_argument("--out", default="release", help="产物输出目录（默认 release/）")
    ap.add_argument("--digest", default="", help="镜像 digest（sha256:...）；有则写入 .env 的 IMAGE_DIGEST")
    ap.add_argument("--no-model-hash", action="store_true", help="跳过模型权重 sha256（仅记录体积）")
    ap.add_argument("--verify", action="store_true", help="校验模式：检查产物是否漂移，不写文件")
    ap.add_argument("--strict", action="store_true", help="配合 --verify：额外要求工作树干净（正式发布门禁）")
    ap.add_argument("--root", default="", help="测试用：替换工作树根（如指向不存在目录以模拟干净 checkout）")
    ap.add_argument(
        "--capture-provenance",
        action="store_true",
        help="从本机 comfy_kernel/ 嵌套仓只读采集并刷新 kernel_provenance.json",
    )
    args = ap.parse_args()

    root = Path(args.root).resolve() if args.root else ROOT
    out_dir = root / args.out

    if args.capture_provenance:
        return capture_kernel_provenance(root)

    if args.verify:
        problems = verify(root, out_dir, strict=args.strict)
        if problems:
            print("[FAIL] 发布元数据校验未通过：")
            for p in problems:
                print(f"  - {p}")
            return 1
        print("[PASS] 发布元数据校验通过（tag 不可变、快照无漂移、SBOM 存在）")
        return 0

    version = "" if args.dev else args.version
    meta = build_metadata(root, version=version, with_model_hash=not args.no_model_hash)
    tag = meta["image_tag"]

    if not is_valid_image_tag(tag):
        print(f"[FAIL] 推导出的镜像 tag={tag!r} 不可用于发布（须为语义版本或 git-<sha>）")
        print("       若非 Git 仓库，请用 --version 显式指定语义版本号")
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "build_metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    lock = root / "requirements-lock.txt"
    lock_text = lock.read_text(encoding="utf-8") if lock.is_file() else ""
    sbom = build_sbom(lock_text, tag, meta["git"]["sha"])
    (out_dir / "sbom.json").write_text(json.dumps(sbom, indent=2, ensure_ascii=False), encoding="utf-8")

    env_path = root / ".env"
    env_text = merge_env_file(env_path, {"IMAGE_TAG": tag, "IMAGE_DIGEST": args.digest})
    env_path.write_text(env_text, encoding="utf-8")

    print(f"[INFO] 镜像 tag          : {tag}")
    print(f"[INFO] Git SHA           : {meta['git']['sha'] or 'unknown'}{' (dirty)' if meta['git']['dirty'] else ''}")
    print(f"[INFO] SBOM 组件数       : {len(sbom['components'])}")
    print(f"[INFO] model 文件数      : {meta['artifacts']['model']['file_count']}")
    kb = meta["artifacts"]["comfy_kernel"]
    if kb["present"]:
        print(
            f"[INFO] comfy_kernel 摘要 : {kb['digest'][:16] or 'N/A'}"
            f" ({kb['file_count']} files, upstream={str((kb.get('upstream') or {}).get('commit', ''))[:12]})"
        )
    else:
        prov = kb.get("provenance")
        if isinstance(prov, dict):
            print(
                f"[INFO] comfy_kernel    : 目录缺失，来源凭证 {prov.get('origin', 'N/A')}@{str(prov.get('upstream_commit', ''))[:12] or 'N/A'}"
            )
        else:
            print(f"[INFO] comfy_kernel    : 目录缺失，{prov}")
    print(f"[INFO] 已写出 {out_dir / 'build_metadata.json'}")
    print(f"[INFO] 已写出 {out_dir / 'sbom.json'}")
    print("[INFO] 已更新 .env（IMAGE_TAG / IMAGE_DIGEST）")
    if meta["git"]["dirty"]:
        print("[WARN] 工作树为 dirty，该元数据仅可用于本地构建；正式发布前请提交全部改动")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
