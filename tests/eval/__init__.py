"""tests/eval — Agent 提示词回归(eval)用例集与断言框架。

对应评估报告第九章 9.3:system prompt 模板入版本控制,每次改动必须跑 eval,
否则提示词调优就是盲改。分两层:

- **CI 层**(本目录的 pytest,mock LLM):确定性、可进覆盖率门禁。断言的是
  "即使 LLM 完全被注入攻陷,服务端各层防线仍然守住" —— 白名单、范围钳制、
  结构隔离、泄露检测。
- **本地手动层**(``scripts/eval_agent_prompt.py``):跑真 LLM,统计行为正确率,
  不进 CI(非确定性)。

用例集见 ``cases.py``;框架见 ``harness.py``;说明见 ``README.md``。
"""

from .cases import CASES, REQUIRED_CATEGORIES, EvalCase, Expect, Turn
from .harness import EvalResult, RecordingExecutor, run_case

__all__ = [
    "CASES",
    "REQUIRED_CATEGORIES",
    "EvalCase",
    "EvalResult",
    "Expect",
    "RecordingExecutor",
    "Turn",
    "run_case",
]
