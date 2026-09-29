"""
agent/tools.py — Agent 工具 schema 与校验(评估报告第九章 9.2 第 3 层的落地)

P0 暴露 4 个工具:generate_image / list_engines / list_loras / get_task。
edit_image 计划 P1 接入(蓝图:workflows/blueprints/Edit/),届时在 TOOL_SCHEMAS 追加,
schema 现已预留 engine 字段保证对话兼容。

设计约束:
- LLM 输出只能经 validate_tool_args() 结构化进入生成链(结构隔离,无自由文本通道);
- generate_image 参数经 guard.clamp_generate_params 服务端再校验(零信任);
- tool 描述即 prompt,保持简洁且不含敏感信息。
"""

from __future__ import annotations

from typing import Any

from .guard import clamp_generate_params, sanitize_task_id

# OpenAI tools 格式(JSON Schema);engine 字段为 P2 多引擎预留,P0 固定默认引擎
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": "提交一张文生图任务。返回 task_id,生成完成后由系统推送结果图片。",
            "parameters": {
                "type": "object",
                "properties": {
                    "engine": {
                        "type": "string",
                        "description": "引擎名,默认 z_image_turbo_native;仅可使用系统能力清单中列出的引擎",
                    },
                    "positive_prompt": {"type": "string", "description": "正向提示词"},
                    "negative_prompt": {"type": "string", "description": "负向提示词"},
                    "width": {"type": "integer", "description": "宽度,256~2048"},
                    "height": {"type": "integer", "description": "高度,256~2048"},
                    "steps": {"type": "integer", "description": "采样步数,1~50"},
                    "cfg": {"type": "number", "description": "CFG,1.0~10.0"},
                    "seed": {"type": "integer", "description": "种子,-1 为随机"},
                    "batch_size": {"type": "integer", "description": "单次张数,1~4"},
                },
                "required": ["positive_prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_engines",
            "description": "列出可用引擎及其加载状态。无参数。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_loras",
            "description": "列出当前可用的 LoRA 名称。无参数。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_task",
            "description": "查询生成任务状态与结果。",
            "parameters": {
                "type": "object",
                "properties": {"task_id": {"type": "string", "description": "任务 ID"}},
                "required": ["task_id"],
            },
        },
    },
]

KNOWN_TOOLS = {t["function"]["name"] for t in TOOL_SCHEMAS}
NO_ARG_TOOLS = {"list_engines", "list_loras"}
DEFAULT_ENGINE = "z_image_turbo_native"


def validate_tool_args(name: str, args: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """校验并清洗工具参数。返回 (cleaned, violations);unknown tool 直接报错。"""
    if name not in KNOWN_TOOLS:
        raise ValueError(f"未知工具: {name}")
    if name in NO_ARG_TOOLS:
        return {}, ([f"{name} 不接受参数"] if args else [])

    if name == "get_task":
        task_id = sanitize_task_id(str(args.get("task_id", "")))
        if not task_id:
            return {}, ["task_id 缺失或非法"]
        extra = set(args) - {"task_id"}
        return ({"task_id": task_id}, [f"未知参数已丢弃: {sorted(extra)}"] if extra else [])

    # generate_image:engine 是合法键但不在 clamp 白名单内,先单独取出
    engine = str(args.get("engine", "")).strip()
    rest = {k: v for k, v in args.items() if k != "engine"}
    cleaned, violations = clamp_generate_params(rest)

    # P0 单引擎:白名单外的 engine 一律回落默认并记录违规(P2 多引擎时替换为枚举校验)
    if engine and engine != DEFAULT_ENGINE:
        violations.append(f"engine {engine!r} 不可用,已回落默认引擎")
    cleaned["engine"] = DEFAULT_ENGINE
    return cleaned, violations
