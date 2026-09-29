"""
scripts/analyze_workflows.py — 工作流蓝图分析器(接入外部 ComfyUI 工作流的前置工具)

扫描 workflows/blueprints/ 下的 ComfyUI 工作流 JSON(Edit/Image/SeedVR2),
生成 manifest.json:节点构成、模型权重依赖、采样参数(容器实例值 vs 子图内部值)、LoRA 引用。

⚠️ GOTCHA(2026-09-23 验证):新版工作流格式的 widget 值存在多处来源——
子图实例节点(顶层 type 为 UUID)的 widgets_values 是容器注入的运行时真值候选,
子图内部节点的 widgets_values 可能被容器覆盖。移植时以容器 positional 为准、实机验证,
本脚本把两类值都列出,不做单边断言。

用法:
    python scripts/analyze_workflows.py            # 生成 manifest.json
    python scripts/analyze_workflows.py --quiet    # 只生成,不打印摘要

环境变量:
    IMAGE_MM_WORKFLOW_SOURCE   蓝图来源描述(默认 "external ComfyUI user/default/workflows")。
                               仅用于 manifest 溯源字段,不参与分析;填入本机绝对路径会在
                               pre-commit 的路径可移植性门禁被拦截,故默认值保持中性。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BLUEPRINT_DIR = Path(__file__).resolve().parent.parent / "workflows" / "blueprints"
DEFAULT_SOURCE = "external ComfyUI user/default/workflows (Edit/Image/SeedVR2)"
CATEGORIES = ("Edit", "Image", "SeedVR2")
MODEL_FILE_RE = re.compile(r"[A-Za-z0-9_\.\-\(\)]+\.(?:safetensors|gguf|pt|pth)")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

SAMPLER_NODE_TYPES = {"KSampler", "KSamplerAdvanced", "KSamplerSelect", "SamplerCustomAdvanced"}
LORA_NODE_TYPES = {"LoraLoader", "LoraLoaderModelOnly"}
KSEMAPLER_WIDGET_LABELS = (
    "seed",
    "control_after_generate",
    "steps",
    "cfg",
    "sampler_name",
    "scheduler",
    "denoise",
)


def _iter_nodes(wf: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """产出 (scope, node)。scope: 'top' 或 'subgraph:<name>'。"""
    pairs: list[tuple[str, dict[str, Any]]] = [("top", n) for n in wf.get("nodes", [])]
    for sg in wf.get("definitions", {}).get("subgraphs", []):
        name = sg.get("name") or sg.get("id", "?")
        for n in sg.get("nodes", []):
            pairs.append((f"subgraph:{name}", n))
    return pairs


def _labeled_widgets(node: dict[str, Any]) -> dict[str, Any] | None:
    if node.get("type") != "KSampler":
        return None
    widgets = node.get("widgets_values")
    if not isinstance(widgets, list):
        return None
    return dict(zip(KSEMAPLER_WIDGET_LABELS, widgets, strict=False))


def analyze_file(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        wf = json.load(fh)

    pairs = _iter_nodes(wf)
    class_counts = Counter(n.get("type", "?") for _, n in pairs)

    # 子图实例节点(顶层 type 为 UUID):容器注入值 = 运行时真值候选
    sg_ids = {sg.get("id"): sg.get("name") or sg.get("id") for sg in wf.get("definitions", {}).get("subgraphs", [])}
    container_instances: list[dict[str, Any]] = []
    for scope, n in pairs:
        if scope == "top" and UUID_RE.match(str(n.get("type", ""))):
            container_instances.append(
                {
                    "subgraph": sg_ids.get(n.get("type"), n.get("type")),
                    "title": n.get("title"),
                    "widgets_values": n.get("widgets_values"),
                }
            )

    samplers: list[dict[str, Any]] = []
    for scope, n in pairs:
        if n.get("type") in SAMPLER_NODE_TYPES:
            entry: dict[str, Any] = {"where": scope, "type": n.get("type"), "widgets_values": n.get("widgets_values")}
            labeled = _labeled_widgets(n)
            if labeled:
                entry["labeled"] = labeled
            samplers.append(entry)

    loras = sorted(
        {
            str((n.get("widgets_values") or [""])[0])
            for _, n in pairs
            if n.get("type") in LORA_NODE_TYPES and isinstance(n.get("widgets_values"), list) and n["widgets_values"]
        }
    )

    raw = json.dumps(wf, ensure_ascii=False)
    model_files = sorted(set(MODEL_FILE_RE.findall(raw)))

    subgraphs = [
        {"name": sg.get("name") or sg.get("id"), "node_count": len(sg.get("nodes", []))}
        for sg in wf.get("definitions", {}).get("subgraphs", [])
    ]

    return {
        "file": str(path.relative_to(BLUEPRINT_DIR)).replace("\\", "/"),
        "category": path.parent.name,
        "comfy_format_version": wf.get("version"),
        "top_node_count": len(wf.get("nodes", [])),
        "subgraphs": subgraphs,
        "class_counts": dict(class_counts.most_common()),
        "container_instances": container_instances,
        "samplers": samplers,
        "loras": loras,
        "model_files": model_files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze ComfyUI workflow blueprints")
    parser.add_argument("--quiet", action="store_true", help="只写 manifest,不打印摘要")
    args = parser.parse_args()

    entries: list[dict[str, Any]] = []
    for category in CATEGORIES:
        for path in sorted((BLUEPRINT_DIR / category).glob("*.json")):
            entries.append(analyze_file(path))

    manifest = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": os.environ.get("IMAGE_MM_WORKFLOW_SOURCE", DEFAULT_SOURCE),
        "gotcha": "widget 真值以子图实例节点(容器)的 positional widgets_values 为准,子图内部值可能被覆盖;移植前实机验证",
        "workflows": entries,
    }

    out = BLUEPRINT_DIR / "manifest.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.quiet:
        for e in entries:
            print(f"[{e['category']}] {e['file']}: top={e['top_node_count']} nodes, subgraphs={len(e['subgraphs'])}")
            if e["container_instances"]:
                for c in e["container_instances"]:
                    print(f"    容器实例 {c['subgraph']}: widgets={c['widgets_values']}")
            for s in e["samplers"]:
                print(f"    采样 {s['where']} {s['type']}: {s['widgets_values']}")
            if e["loras"]:
                print(f"    LoRA: {e['loras']}")
            print(
                f"    模型依赖 {len(e['model_files'])} 个: {', '.join(e['model_files'][:4])}{' ...' if len(e['model_files']) > 4 else ''}"
            )
        print(f"\nmanifest -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
