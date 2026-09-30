"""
agent/tools.py — Agent 工具 schema 与校验(评估报告第九章 9.2 第 3 层的落地)

暴露 5 个工具:generate_image / **edit_image**(P1) / list_engines / list_loras / get_task。

设计约束:
- LLM 输出只能经 validate_tool_args() 结构化进入生成链(结构隔离,无自由文本通道);
- generate_image 参数经 guard.clamp_generate_params 服务端再校验(零信任);
- edit_image 参数经 guard.clamp_edit_params 同等校验,并做**引用图来源校验**:
  LLM 只能给 ``task_id``(复用本会话已生成图)或 ``reference_path``(PathGuard 白名单内
  路径),**不能**传任意路径/base64 —— 防止被诱导读盘。
- tool 描述即 prompt,保持简洁且不含敏感信息。
"""

from __future__ import annotations

from typing import Any

from .guard import clamp_edit_params, clamp_generate_params, sanitize_task_id

# OpenAI tools 格式(JSON Schema)
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
            "name": "edit_image",
            "description": (
                "编辑一张已有图片。参考图来自本会话已生成的某个任务(传 task_id),"
                "或用户指定的服务端路径(传 reference_path)。"
                "prompt 写**编辑指令**(要怎么改),不要写完整的场景描述。"
                "返回 task_id,完成后推送结果图片。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "positive_prompt": {"type": "string", "description": '编辑指令,如"把背景换成雪地"'},
                    "negative_prompt": {"type": "string", "description": "负向提示词"},
                    "task_id": {
                        "type": "string",
                        "description": "参考图来源:已有生成任务的 ID(取其第一张输出);与 reference_path 二选一",
                    },
                    "reference_path": {
                        "type": "string",
                        "description": "参考图来源:服务端图片路径(PathGuard 白名单内);与 task_id 二选一",
                    },
                    "steps": {"type": "integer", "description": "采样步数,1~50"},
                    "cfg": {"type": "number", "description": "CFG,1.0~10.0"},
                    "seed": {"type": "integer", "description": "种子,-1 为随机"},
                    "batch_size": {"type": "integer", "description": "单次张数,1~4"},
                    "edit_resolution": {
                        "type": "integer",
                        "description": "参考图缩放目标边长,0=按原图;512 显存最省,1024 效果最好",
                    },
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
DEFAULT_EDIT_ENGINE = "qwen_image_edit_native"
# 编辑参考图的合法来源键（与生成参数白名单分开管理）
EDIT_REFERENCE_KEYS = {"task_id", "reference_path"}


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

    if name == "edit_image":
        cleaned, violations = clamp_edit_params(args)
        return cleaned, violations

    # generate_image:engine 是合法键但不在 clamp 白名单内,先单独取出
    engine = str(args.get("engine", "")).strip()
    rest = {k: v for k, v in args.items() if k != "engine"}
    cleaned, violations = clamp_generate_params(rest)

    # P0 单引擎:白名单外的 engine 一律回落默认并记录违规(P2 多引擎时替换为枚举校验)
    if engine and engine != DEFAULT_ENGINE:
        violations.append(f"engine {engine!r} 不可用,已回落默认引擎")
    cleaned["engine"] = DEFAULT_ENGINE
    return cleaned, violations
