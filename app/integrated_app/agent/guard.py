"""
agent/guard.py — Agent 注入防御原语(评估报告第九章 9.2 的落地)

四个防御原语:
1. sanitize_data_item:文件系统枚举数据(LoRA/引擎名)入 prompt 前的消毒——
   文件名本身就是攻击面(换行/定界符伪造/指令片段)。
2. clamp_generate_params:服务端参数再校验(零信任),不信任 LLM 输出。
3. detect_leak:输出侧泄露检测(system prompt 指纹 / key 形态 / 绝对路径)。
4. sanitize_task_id:任务 ID 类自由文本的消毒。
"""

from __future__ import annotations

import re
from typing import Any

# 参数钳制范围(与 config.yaml inference 段对齐,取安全超集)
PARAM_RANGES: dict[str, tuple[float, float]] = {
    "width": (256, 2048),
    "height": (256, 2048),
    "steps": (1, 50),
    "cfg": (1.0, 10.0),
    "seed": (-1, 2**32 - 1),
    "batch_size": (1, 4),
}
INT_PARAMS = {"width", "height", "steps", "seed", "batch_size"}
ALLOWED_PARAM_KEYS = set(PARAM_RANGES) | {"positive_prompt", "negative_prompt"}

_DATA_SANITIZE_RE = re.compile(r"[\x00-\x1f<>`]+")
_KEY_LIKE_RE = re.compile(r"\b[A-Za-z0-9_\-]{32,}\b")
_ABS_PATH_RE = re.compile(r"\b[A-Za-z]:\\[^\s\"']+")


def sanitize_data_item(item: str) -> str:
    """枚举数据消毒:去控制字符/尖括号/反引号(防伪造定界符与换行注入),限长。"""
    cleaned = _DATA_SANITIZE_RE.sub(" ", str(item))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:120]


def sanitize_task_id(task_id: str) -> str:
    """任务 ID 消毒:仅允许 ULID/UUID/短横线数字字母。"""
    cleaned = re.sub(r"[^A-Za-z0-9\-]", "", str(task_id))
    return cleaned[:64]


def clamp_generate_params(args: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """工具参数服务端再校验:丢弃未知键、类型规整、范围钳制。

    返回 (cleaned_args, violations);violations 非空时调用方应把错误回喂 LLM。
    """
    cleaned: dict[str, Any] = {}
    violations: list[str] = []

    for key in ("positive_prompt", "negative_prompt"):
        if key in args:
            value = str(args[key])[:10000]
            if key == "positive_prompt" and not value.strip():
                violations.append("positive_prompt 不能为空")
            cleaned[key] = value

    for key, (low, high) in PARAM_RANGES.items():
        if key not in args:
            continue
        try:
            value = float(args[key])
        except (TypeError, ValueError):
            violations.append(f"{key} 不是数值: {args[key]!r}")
            continue
        original = value
        value = min(max(value, low), high)
        if key in INT_PARAMS:
            value = int(round(value))
            if key in ("width", "height"):
                value = max(256, int(round(value / 8) * 8))
        if value != original:
            violations.append(f"{key} 超出范围 [{low}, {high}],已钳制为 {value}")
        cleaned[key] = value

    unknown = set(args) - ALLOWED_PARAM_KEYS
    if unknown:
        violations.append(f"未知参数已丢弃: {sorted(unknown)}")
    return cleaned, violations


def detect_leak(text: str, kernel_fingerprints: list[str]) -> list[str]:
    """输出侧泄露检测。返回命中的规则名列表(空 = 通过)。"""
    hits: list[str] = []
    for fp in kernel_fingerprints:
        if fp and fp in text:
            hits.append("kernel_prompt_fingerprint")
            break
    if _KEY_LIKE_RE.search(text):
        hits.append("key_like_token")
    if _ABS_PATH_RE.search(text):
        hits.append("absolute_path")
    return hits
