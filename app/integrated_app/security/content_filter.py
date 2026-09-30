"""
security/content_filter.py — CLIP 安全内容检测器

对应全功能实施指南任务 1: CLIP 安全内容检测

设计要点（适配项目架构）：
- CLIP 模型 **懒加载**（首次调用 check_image 时才加载，避免 import 时卡住）
- CLIP 未安装时 **优雅降级**（check_prompt 关键词过滤仍然生效）
- 所有路径操作过 PathGuard
- 错误文案走 i18n 三层 fallback
- 全局单例通过 get_content_filter() 获取
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..cache import get_cache

logger = logging.getLogger(__name__)


# ── 结果数据类 ──────────────────────────────────────────────────
@dataclass
class SafetyResult:
    """安全检测结果。

    Attributes:
        is_safe: 是否安全（True=通过，False=拦截）。
        violation_type: 违规类型（安全时为 None）。
        confidence: 置信度 0.0~1.0。
        details: 附加详情字典。
    """

    is_safe: bool
    violation_type: str | None = None
    confidence: float = 1.0
    details: dict[str, Any] = field(default_factory=dict)


# ── 不安全关键词列表 ────────────────────────────────────────────
_UNSAFE_KEYWORDS: list[str] = [
    "naked",
    "nude",
    "sexy",
    "pornographic",
    "nsfw",
    "violent",
    "gore",
    "bloodbath",
    "massacre",
    "hate",
    "racist",
    "kill",
    "murder",
    "assassinate",
    "death",
    "suicide",
    "self-harm",
    "selfharm",
    "weapon",
    "bomb",
    "explosive",
    "terrorist",
    "drug",
    "cocaine",
    "heroin",
    "child abuse",
    "underage",
]

# CLIP 文本提示（英文，CLIP 原生支持英文最佳）
_UNSAFE_CLIP_PROMPTS: list[str] = [
    "a violent or gory image",
    "an explicit adult NSFW content image",
    "a hate speech or racist image",
    "a self-harm or suicide image",
    "an image depicting illegal drug use",
    "a weapon or explosive image",
]

# CLIP 相似度判定阈值（提取为常量，便于缓存键随阈值变化而失效）
# 2026-09-30 校准：归一化修复后实测 5 张干净图 max_sim 分布 0.219~0.384，
# 取 0.5（高于实测最大约 30% 余量；待真实边界图集进一步校准）。
_CLIP_THRESHOLD = 0.5

# ── 提示词绕过对抗（H-03 修复：纯关键词 .lower() 可被轻易绕过）─────────────
# 1) 同形字（Cyrillic / 数学单体等）映射到 ASCII
_HOMOGLYPH_MAP: dict[str, str] = {
    "а": "a",
    "е": "e",
    "о": "o",
    "с": "c",
    "і": "i",
    "ѕ": "s",
    "у": "y",
    "х": "x",
    "р": "p",
    "қ": "k",
    "п": "n",
    "ԛ": "q",
    "ԝ": "w",
    "һ": "h",
    "𝚊": "a",
    "𝚎": "e",
    "𝚘": "o",
    "𝚌": "c",
    "𝚒": "i",
    "𝚜": "s",
    "𝚝": "t",
    "𝚞": "u",
    "𝚔": "k",
    "ⅰ": "i",
}
# 2) 莱特字符（leetspeak）映射
_LEET_MAP: dict[str, str] = {
    "4": "a",
    "1": "i",
    "3": "e",
    "0": "o",
    "5": "s",
    "7": "t",
    "@": "a",
    "$": "s",
    "!": "i",
    "8": "b",
}
# 3) 用于"压缩匹配"的分隔符（含零宽字符），移除后检测 n a k e d 这类插入式绕过
_SEP_CHARS = set(" \u00a0\t\n\r\u200b\u200c\u200d\u2060\ufeff._/\\|-")
# 仅用于词内零宽字符清除（保留普通空格以维持词边界，供注入规则匹配）。
# 对应测试体系评估 P1-5 修复：i<zw>gno<zw>re 这类词内零宽插入此前绕过注入检测。
_ZW_CHARS = {"\u200b", "\u200c", "\u200d", "\u2060", "\ufeff"}


def _translate(text: str, table: dict[str, str]) -> str:
    """按字符映射表翻译字符串（同形字 / 莱特字符替换）。"""
    return "".join(table.get(ch, ch) for ch in text)


def _normalize_for_match(text: str) -> tuple[str, str]:
    """为关键词/注入匹配生成两种归一化形态。

    Returns:
        (保留空格的归一化串, 去除所有分隔符的紧凑串)。
        紧凑串用于检测 ``n a k e d`` 这类插入空格/零宽字符的绕过；
        空格串用于检测 ``child abuse`` 这类多词关键词。
    """
    nfkc = unicodedata.normalize("NFKC", text)
    t = _translate(nfkc, _HOMOGLYPH_MAP)
    t = _translate(t, _LEET_MAP)
    low = t.lower()
    # 词内零宽字符清除（保留普通空格）：修复 i<zw>gno<zw>re 注入绕过
    low = "".join(ch for ch in low if ch not in _ZW_CHARS)
    compact = "".join(ch for ch in low if ch not in _SEP_CHARS)
    return low, compact


# 4) Prompt Injection 规则集（指令覆写 / 分隔符逃逸 / 越狱标记）。
#    仅覆盖高置信度的越狱/覆写标记，避免误伤正常图像描述（如 "act as a photographer"
#    这类 role-play 不在此拦截，交由 CLIP 与人工审核兜底）。
_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore\s+(previous|prior|all\s+previous|above|earlier)\s+instructions?", re.I),
    re.compile(r"disregard\s+(previous|prior|all\s+previous|above|earlier)", re.I),
    re.compile(r"forget\s+(everything|all|previous|prior)", re.I),
    re.compile(r"<\|im_start\|>|<\|im_end\|>|<\|im_system\|>"),
    re.compile(r"<system>|\[system\]|\[/system\]"),
    re.compile(r"system\s+prompt", re.I),
    re.compile(r"jail ?break", re.I),
    re.compile(r"do\s+anything\s+now", re.I),
    re.compile(r"###\s*(system|instruction|prompt)", re.I),
    re.compile(r"\boverride\s+(safety|filter|security|guard)\b", re.I),
    re.compile(r"\bbypass\s+(filter|safety|security|guard|protection)\b", re.I),
]


class ContentSafetyFilter:
    """基于 CLIP 的内容安全过滤器。

    CLIP 模型懒加载，首次调用 ``check_image`` 时才加载到 GPU/CPU。
    如果 ``clip`` 包未安装，``check_image`` 返回保守放行结果，
    ``check_prompt`` 关键词过滤仍然生效。
    """

    def __init__(
        self,
        model_name: str = "ViT-B/32",
        fail_closed_on_clip_missing: bool = False,
    ) -> None:
        """初始化安全过滤器。

        Args:
            model_name: CLIP 模型名称（默认 ViT-B/32，体积小速度快）。
            fail_closed_on_clip_missing: CLIP 模型缺失时的降级策略。
                False=降级放行（fail-open，默认，向后兼容）；True=降级拦截（fail-closed）。
        """
        self._model_name: str = model_name
        self._fail_closed_on_clip_missing: bool = fail_closed_on_clip_missing
        self._model: Any = None
        self._preprocess: Any = None
        self._device: str = ""
        self._loaded: bool = False
        self._load_error: str | None = None

    # ── 降级策略（运行时可更新）──────────────────────────────────
    def set_fail_closed_on_clip_missing(self, value: bool) -> None:
        """运行时更新 CLIP 缺失时的降级策略（默认 fail-open）。

        Args:
            value: True=CLIP 缺失时拦截（fail-closed）；False=放行（fail-open）。
        """
        self._fail_closed_on_clip_missing = bool(value)

    # ── 模型懒加载 ──────────────────────────────────────────────
    def _ensure_loaded(self) -> bool:
        """懒加载 CLIP 模型。

        Returns:
            True 加载成功，False 加载失败（clip 未安装或其他错误）。
        """
        if self._loaded:
            return True
        if self._load_error is not None:
            return False

        try:
            import clip as clip_lib
            import torch
            from PIL import Image  # noqa: F401 — 确认 Pillow 可用

            self._device = "cuda" if torch.cuda.is_available() else "cpu"
            self._model, self._preprocess = clip_lib.load(self._model_name, device=self._device)
            self._loaded = True
            logger.info(f"CLIP 模型加载成功: {self._model_name} @ {self._device}")
            return True
        except ImportError:
            self._load_error = "clip 包未安装，图片安全检查降级为关键词过滤"
            logger.warning(self._load_error)
            return False
        except Exception as e:
            self._load_error = f"CLIP 模型加载失败: {e}"
            logger.error(self._load_error)
            return False

    # ── 图片安全检查 ────────────────────────────────────────────
    def check_image(self, image_path: str | Path, use_cache: bool = True) -> SafetyResult:
        """检查图片是否包含违规内容（带缓存）。

        CLIP 推理成本高（首次加载 2-5s，后续每张百 ms 级），对同一图片的
        重复检测走 ``safety`` 命名空间缓存。缓存键内容寻址（路径 + size +
        mtime + 阈值 + fail-closed 策略），文件被替换即自动失效。

        Args:
            image_path: 图片路径（已经过 PathGuard 校验）。
            use_cache: 是否启用缓存；False 时强制重新检测。

        Returns:
            SafetyResult: 安全检测结果。
        """
        if not use_cache:
            return self._check_image_uncached(image_path)

        key = self._cache_key(image_path)
        if key is None:
            return self._check_image_uncached(image_path)

        cached = get_cache("safety").get(key)
        if cached is not None:
            return SafetyResult(**cached)

        result = self._check_image_uncached(image_path)
        # 仅缓存确定性结果：CLIP 缺失 / 检查失败等降级结果不缓存，
        # 否则环境修复后仍会长期返回降级结论。
        if result.violation_type not in ("clip_unavailable", "check_error"):
            get_cache("safety").put(
                key,
                {
                    "is_safe": result.is_safe,
                    "violation_type": result.violation_type,
                    "confidence": result.confidence,
                    "details": result.details,
                },
            )
        return result

    def _cache_key(self, image_path: str | Path) -> str | None:
        """构造内容寻址缓存键；无法 stat 时返回 None（退化为不缓存）。"""
        try:
            p = Path(image_path)
            st = p.stat()
            return f"{p.resolve()}|{st.st_size}|{st.st_mtime}|{_CLIP_THRESHOLD}|{self._fail_closed_on_clip_missing}"
        except Exception:  # noqa: BLE001 - stat 失败即不缓存，不影响检测
            return None

    def _check_image_uncached(self, image_path: str | Path) -> SafetyResult:
        """实际执行 CLIP 图片安全检测（无缓存层）。

        如果 CLIP 未安装：默认返回降级放行（is_safe=True，向后兼容）；
        配置 fail_closed_on_clip_missing=True 时返回拦截（is_safe=False）。
        两种情况均在 details 中记录 degraded 降级信息。
        """
        if not self._ensure_loaded():
            details = {
                "degraded": True,
                "reason": self._load_error or "CLIP not available",
            }
            # 审计要求：CLIP 不可用时必须留下策略决策痕迹，便于事后判断
            # "某次放行是因为环境故障还是真实判定通过"（2026-09-04 安全评估 M1）。
            logger.warning(
                "[CONTENT-FILTER] CLIP 不可用，降级策略=%s，原因=%s",
                "fail-closed(拦截)" if self._fail_closed_on_clip_missing else "fail-open(放行)",
                details["reason"],
            )
            if self._fail_closed_on_clip_missing:
                # fail-closed：CLIP 不可用时拦截（violation_type 供上层区分原因）
                return SafetyResult(
                    is_safe=False,
                    violation_type="clip_unavailable",
                    confidence=0.0,
                    details=details,
                )
            # fail-open（默认，向后兼容）：降级放行，记录 degraded 标记
            return SafetyResult(
                is_safe=True,
                violation_type=None,
                confidence=0.0,
                details=details,
            )

        try:
            import torch
            from PIL import Image

            image = self._preprocess(Image.open(str(image_path))).unsqueeze(0).to(self._device)

            import clip as clip_lib

            text_tokens = clip_lib.tokenize(_UNSAFE_CLIP_PROMPTS).to(self._device)

            with torch.no_grad():
                image_features = self._model.encode_image(image)
                text_features = self._model.encode_text(text_tokens)
                # CLIP 标准用法:encode_* 返回未归一化特征,必须先 L2 归一化再做相似度。
                # 否则 softmax 被文本范数支配(实测各 prompt 范数 11.1~12.6,"NSFW" 最大),
                # 任何图片都会恒定命中某个 prompt(softmax≈1.0)→ 全量误拦。
                # 2026-09-30 修复:归一化后干净图 max_sim≈0.25(实测),详见评估报告第五轮。
                image_features = image_features / image_features.norm(dim=-1, keepdim=True)
                text_features = text_features / text_features.norm(dim=-1, keepdim=True)
                # 计算余弦相似度并 softmax
                similarities = (100.0 * image_features @ text_features.T).softmax(dim=-1)
                max_sim = similarities.max().item()
                max_idx = similarities.argmax().item()

            threshold = _CLIP_THRESHOLD
            if max_sim > threshold:
                return SafetyResult(
                    is_safe=False,
                    violation_type="content_warning",
                    confidence=max_sim,
                    details={
                        "similarity": max_sim,
                        "matched_prompt": _UNSAFE_CLIP_PROMPTS[max_idx],
                        "threshold": threshold,
                    },
                )

            return SafetyResult(
                is_safe=True,
                violation_type=None,
                confidence=1.0 - max_sim,
                details={"max_similarity": max_sim, "threshold": threshold},
            )

        except Exception as e:
            logger.error(f"图片安全检查失败: {e}")
            # 失败时保守策略：拒绝
            return SafetyResult(
                is_safe=False,
                violation_type="check_error",
                confidence=0.0,
                details={"error": str(e)},
            )

    # ── 提示词安全检查 ──────────────────────────────────────────
    def check_prompt(self, prompt: str) -> SafetyResult:
        """检查提示词是否包含违规关键词或注入指令。

        使用归一化后的关键词匹配 + 注入规则集，无需 CLIP 模型，始终可用。
        归一化可对抗：空格/零宽字符插入（``n a k e d``）、同形字
        （``nаkеd``）、莱特字符（``n4k3d``）等绕过手段。

        Args:
            prompt: 用户输入的提示词。

        Returns:
            SafetyResult: 安全检测结果。
        """
        if not prompt:
            return SafetyResult(is_safe=True, violation_type=None, confidence=1.0, details={})

        low, compact = _normalize_for_match(prompt)

        # 1) Prompt Injection 规则（指令覆写 / 分隔符逃逸 / 越狱标记）
        for pat in _INJECTION_PATTERNS:
            hit = pat.search(low) or pat.search(compact)
            if hit:
                return SafetyResult(
                    is_safe=False,
                    violation_type="prompt_injection",
                    confidence=0.9,
                    details={"pattern": pat.pattern, "match": hit.group(0)},
                )

        # 2) 不安全关键词（含同形字 / 莱特 / 分隔符绕过）
        for keyword in _UNSAFE_KEYWORDS:
            if keyword in low or keyword in compact:
                return SafetyResult(
                    is_safe=False,
                    violation_type=f"suspicious_keyword:{keyword}",
                    confidence=0.8,
                    details={"keyword": keyword},
                )

        return SafetyResult(
            is_safe=True,
            violation_type=None,
            confidence=1.0,
            details={},
        )


# ── 全局单例 ────────────────────────────────────────────────────
_content_filter: ContentSafetyFilter | None = None


def get_content_filter(
    fail_closed_on_clip_missing: bool | None = None,
) -> ContentSafetyFilter:
    """获取全局 ContentSafetyFilter 单例。

    Args:
        fail_closed_on_clip_missing: 可选。CLIP 缺失时是否 fail-closed 拦截。
            单例创建时作为初始值；单例已存在且该值不为 None 时同步更新。

    Returns:
        ContentSafetyFilter 实例。
    """
    global _content_filter
    if _content_filter is None:
        _content_filter = ContentSafetyFilter(fail_closed_on_clip_missing=bool(fail_closed_on_clip_missing))
    elif fail_closed_on_clip_missing is not None:
        _content_filter.set_fail_closed_on_clip_missing(fail_closed_on_clip_missing)
    return _content_filter


def filter_image_generation(
    prompt: str,
    image_path: str | Path | None = None,
    fail_closed_on_clip_missing: bool | None = None,
) -> tuple[bool, str]:
    """过滤图像生成请求（提示词 + 可选参考图）。

    集成到 generate 路由的入口函数：
    1. 先检查提示词（关键词匹配，始终生效）
    2. 再检查参考图（CLIP 检测，需模型加载）

    Args:
        prompt: 用户提示词。
        image_path: 可选的参考图路径（已过 PathGuard）。
        fail_closed_on_clip_missing: CLIP 缺失时是否拦截（None=跟随单例当前配置）。

    Returns:
        (is_safe, reason): 通过=True/原因="OK"；拦截=False/原因=违规详情。
    """
    cf = get_content_filter(fail_closed_on_clip_missing=fail_closed_on_clip_missing)

    # 检查提示词
    prompt_result = cf.check_prompt(prompt)
    if not prompt_result.is_safe:
        return False, f"prompt_blocked:{prompt_result.violation_type}"

    # 检查参考图（如果有）
    if image_path:
        img_result = cf.check_image(image_path)
        if not img_result.is_safe:
            return False, f"image_blocked:{img_result.violation_type}"

    return True, "OK"
