#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ReSerendipity
# SPDX-License-Identifier: Apache-2.0
"""scripts/ops.py — 薄管理 CLI（status / health / backup）

把既有运维能力收敛为单入口，便于脚本化巡检与 CI/Agent 调用：

  status  — 离线巡检：配置端口 + 服务在线探测 + 关键目录磁盘占用 + git 简况（只读）
  health  — 在线健康：GET /api/health，退出码 0=健康 / 1=离线或异常
  backup  — 一致性备份：包装 scripts/backup_state.py backup（复用既有实现，不重造）

设计约束：
  - 只读优先：status/health 不写任何文件；backup 委托 backup_state.py（backup/verify/
    orphans/restore-drill 见该脚本 --help）
  - 零第三方依赖：status/health 仅用标准库（urllib/json/re/pathlib/subprocess）
  - 端口单一来源：config.yaml（server.port），解析失败回退 8288
  - 与 LOCAL_RULES 对齐：不删除、不覆盖本地内容；本 CLI 无任何破坏性子命令

用法：
  python scripts/ops.py status
  python scripts/ops.py health
  python scripts/ops.py backup [--backup-dir backups]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PORT = 8288
HEALTH_TIMEOUT = 3.0
# 磁盘占用统计目录（刻意不含 pretrained_models/model/comfy_kernel 禁区大目录）
USAGE_DIRS = ("outputs", "logs", "backups", "data")
WALK_FILE_LIMIT = 5000  # 超过则跳过统计，避免大目录拖慢巡检


def _read_port(root: Path = ROOT) -> int:
    """从 config.yaml 读取 server.port；解析失败回退 8288（与 AGENTS.md 口径一致）。"""
    cfg_path = root / "config.yaml"
    try:
        text = cfg_path.read_text(encoding="utf-8")
    except OSError:
        return DEFAULT_PORT
    try:
        import yaml  # 运行环境必有（config.py 同源依赖），缺省时降级正则

        data = yaml.safe_load(text)
        if isinstance(data, dict):
            srv = data.get("server")
            if isinstance(srv, dict) and srv.get("port"):
                return int(srv["port"])
    except Exception:
        pass
    m = re.search(r"^\s*port:\s*(\d+)\s*$", text, re.MULTILINE)
    return int(m.group(1)) if m else DEFAULT_PORT


_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({})
)  # 本机探测必须绕过系统代理（http_proxy 环境变量会把 127.0.0.1 打到代理上，得 502 假象）


def _probe(base: str) -> tuple[bool, str]:
    """探测服务 /api/health；返回 (在线?, 原始响应或错误摘要)。"""
    url = f"{base}/api/health"
    try:
        with _OPENER.open(url, timeout=HEALTH_TIMEOUT) as resp:
            return True, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except Exception as e:  # 连接拒绝/超时等
        return False, f"{type(e).__name__}: {e}"


def _dir_usage(path: Path) -> str:
    """统计目录磁盘占用（人读格式）；文件数超限或不存在时给出说明。"""
    if not path.exists():
        return "（不存在）"
    total = 0
    count = 0
    try:
        for f in path.rglob("*"):
            if f.is_file():
                count += 1
                if count > WALK_FILE_LIMIT:
                    return "（条目过多，跳过统计）"
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
    except OSError as e:
        return f"（统计失败: {type(e).__name__}）"
    mb = total / (1024 * 1024)
    return f"{count} 文件 / {mb:.1f} MB"


def _git_brief() -> str:
    """git 简况：最近提交 + 未提交变更数；git 不可用时降级说明。"""
    try:
        head = subprocess.run(
            ["git", "log", "-1", "--format=%h %s"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if head.returncode != 0:
            return "（非 git 仓库或 git 不可用）"
        n = len([ln for ln in dirty.stdout.splitlines() if ln.strip()])
        return f"{head.stdout.strip()} ｜ 未提交变更 {n} 项"
    except (OSError, subprocess.TimeoutExpired):
        return "（git 调用失败）"


def cmd_status(_args: argparse.Namespace) -> int:
    """离线巡检：端口 / 服务在线 / 目录占用 / git 简况。"""
    port = _read_port()
    base = f"http://127.0.0.1:{port}"
    online, raw = _probe(base)

    print("Image_MultiModel 运维巡检（只读）")
    print(f"  仓库根   : {ROOT}")
    print(f"  服务端口 : {port}（来源 config.yaml server.port）")
    if online:
        print(f"  服务状态 : ● 在线（{base}）")
        try:
            data = json.loads(raw)
            print(f"  /api/health 顶层键 : {', '.join(sorted(data.keys()))}")
        except json.JSONDecodeError:
            print("  服务状态 : ● 在线（响应非 JSON）")
    else:
        print(f"  服务状态 : ○ 离线（{raw}）——如需在线健康请先 python app/clean_launch.py")

    print("  目录占用 :")
    for d in USAGE_DIRS:
        print(f"    {d:<10}: {_dir_usage(ROOT / d)}")
    print(f"  git 简况 : {_git_brief()}")
    return 0


def cmd_health(args: argparse.Namespace) -> int:
    """在线健康：GET /api/health，退出码 0=健康 / 1=离线或异常。"""
    port = _read_port()
    base = f"http://127.0.0.1:{port}"
    online, raw = _probe(base)
    if not online:
        print(f"[health] 服务不可达：{base}/api/health → {raw}")
        print(f"[health] 排查：服务是否已启动（python app/clean_launch.py，默认 127.0.0.1:{port}）")
        return 1
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print(f"[health] 服务在线但响应非 JSON：{raw[:120]}")
        return 1

    print(f"[health] {base}/api/health → HTTP 200")
    # 防御式提取：打印顶层键 + 已知关键字段（结构演进不致崩）
    for key in ("status", "version"):
        if key in data:
            print(f"  {key}: {data[key]}")
    q = data.get("queue")
    if isinstance(q, dict):
        print(
            f"  队列: total={q.get('total')} pending={q.get('pending')} "
            f"processing={q.get('processing')} failed={q.get('failed')}"
        )
    mem = data.get("memory") or data.get("memory_info")
    if isinstance(mem, dict):
        print(f"  内存: {mem.get('used_gb')}/{mem.get('total_gb')} GB（{mem.get('percent')}%）")
    disk = data.get("disk")
    if isinstance(disk, dict):
        print(f"  磁盘: 剩余 {disk.get('free_gb')}/{disk.get('total_gb')} GB")
    engines = data.get("engines")
    if isinstance(engines, list):
        for e in engines:
            if isinstance(e, dict):
                mark = "●" if e.get("ready") else "○"
                active = "（活动）" if e.get("active") else ""
                print(f"  引擎 {mark} {e.get('name')} state={e.get('state')} {active}")
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    print("[health] 结论：健康")
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    """一致性备份：委托 scripts/backup_state.py backup，透传退出码。"""
    target = ROOT / "scripts" / "backup_state.py"
    if not target.exists():
        print(f"[backup] 找不到 {target}，无法委托备份")
        return 1
    cmd = [sys.executable, str(target), "backup", "--backup-dir", args.backup_dir]
    print(f"[backup] 委托执行：{' '.join(cmd)}")
    try:
        proc = subprocess.run(cmd, cwd=ROOT)
    except OSError as e:
        print(f"[backup] 启动失败：{e}")
        return 1
    if proc.returncode == 0:
        print(f"[backup] 完成。备份目录：{ROOT / args.backup_dir}")
    else:
        print(f"[backup] backup_state.py 退出码 {proc.returncode}（详见上方输出）")
    return proc.returncode


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="ops",
        description="Image_MultiModel 薄管理 CLI（status/health/backup，只读优先）",
    )
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="离线巡检：端口/服务在线/目录占用/git 简况")

    h = sub.add_parser("health", help="在线健康：GET /api/health（退出码 0/1）")
    h.add_argument("--json", action="store_true", help="追加输出完整 JSON")

    b = sub.add_parser("backup", help="一致性备份（委托 backup_state.py backup）")
    b.add_argument("--backup-dir", default="backups", help="备份输出目录（默认 backups）")

    args = ap.parse_args()
    return {"status": cmd_status, "health": cmd_health, "backup": cmd_backup}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
