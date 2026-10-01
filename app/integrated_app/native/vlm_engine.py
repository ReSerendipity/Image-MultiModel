"""
native/vlm_engine.py — VLM 看图聊天引擎（P2-vlm-chat M1）

复用 Qwen3-VL-8B 权重作为多模态决策器（方案 A：复用 Agent + VLM 模型）。

架构约束（详见 docs/roadmap/P2-vlm-chat.md）：
- ``comfy_kernel`` 仅把 Qwen3-VL 当 **text_encoder** 用于编辑/描述工作流，不提供本地多模态
  聊天前向；故 VLM 走 ``transformers`` 的 ``Qwen3VLForConditionalGeneration`` 路径。
- 权重单例：同一 transformers 加载器内的多次 load 共享一份实例（``_VLM_CACHE`` 按权重目录
  键控）；但与编辑引擎的 comfy CLIP 加载器**不是**同一份实例（跨加载器无法共享），该限制已在
  文档如实标注——不要误以为 VLM + 编辑引擎能省一份 9.35GB 常驻。
- 卸载策略：沿用 ADR-0001 空闲卸载（条目 ref_count 归零后 60s 主动 evict）；生图/编辑请求
  触发时由 worker 调 ``request_vlm_unload()`` 优先卸 VLM 保 T2I。
- 离线约束：本仓严格离线化，Qwen3-VL 的 HF 模型目录（含 config.json / tokenizer / 权重）需
  本地就位（config.local_model_dir 指向），否则 load() 报清晰错误，不静默降级。

验证说明：``infer_chat`` 的多模态前向依赖本地 Qwen3-VL-8B 模型目录 + ``qwen_vl_utils``，
须实机加载权重验证（见 scripts/preflight_qwen3vl.py）；本模块的单测用 mock 覆盖编排逻辑。
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..engine_interface import ProgressCallback

logger = logging.getLogger(__name__)

# ── M6 编辑指令桥接（VLM 自然语言 → 结构化 edit 请求） ─────────
# VLM 输出是**自由文本**，「把背景换成雪天」这类修改建议无法直接喂给编辑引擎。
# 故用定界标记让模型在**可执行的编辑指令**处显式包裹一段提示词，编排器再解析。
# 设计口径（评估报告 9.2 数据/指令分离）：
# - 只有模型**主动吐出标记块**才算编辑意图；纯聊天文本一律解析为 None，
#   **绝不靠关键词猜**（猜出来的 prompt 会静默改掉用户的图）。
# - 解析在后端完成，前端只拿到结构化 intent，不复用 VLM 原文当 prompt。
EDIT_MARKER_START = "[[EDIT]]"
EDIT_MARKER_END = "[[/EDIT]]"
_EDIT_BLOCK_RE = re.compile(
    re.escape(EDIT_MARKER_START) + r"(?P<prompt>.*?)" + re.escape(EDIT_MARKER_END),
    re.DOTALL,
)


@dataclass(frozen=True)
class EditIntent:
    """从 VLM 输出解析出的可执行编辑指令。

    Attributes:
        prompt: 编辑正向提示词 → ``GenerateRequest.positive_prompt``（唯一会被真正执行的文本）。
        source: 命中的原始输出片段，用于回显/审计（**不参与执行**）。
    """

    prompt: str
    source: str = ""


def parse_edit_intent(text: Any) -> EditIntent | None:
    """解析 VLM 输出里的编辑意图块；未命中定界标记时返回 ``None``。

    Args:
        text: VLM 返回的整段文本（流式拼接后的最终文本）。

    Returns:
        标记块存在且内部提示词非空 → ``EditIntent``；
        无标记块 / 块内为空 / 只有起始标记没有结束标记 → ``None``。

    注意：**不做事前关键词猜测**——没标记就不是编辑指令，宁可前端不出按钮，
    也不能把「这张图很好看」当 prompt 去改用户的图。
    """
    if not text:
        return None
    raw = str(text)
    match = _EDIT_BLOCK_RE.search(raw)
    if match is None:
        return None
    prompt = (match.group("prompt") or "").replace("\r\n", "\n").strip()
    if not prompt:
        logger.debug("[VLM] 编辑标记块为空，按无意图处理（不臆造 prompt）")
        return None
    return EditIntent(prompt=prompt, source=raw[max(0, match.start()) : match.end()])


def strip_edit_block(text: Any) -> str:
    """把编辑标记**符号**摘掉，但保留块内提示词。

    为什么保留：标记块里装的就是「将要执行的编辑提示词」，用户点「执行编辑」之前
    必须能看见它——把整块删掉等于让用户去点一个看不见的动作。仅 ``[[EDIT]]`` /
    ``[[/EDIT]]`` 是机器协议，不该出现在聊天气泡里。
    """
    if not text:
        return ""
    out = _EDIT_BLOCK_RE.sub(lambda m: m.group("prompt") or "", str(text))
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def build_edit_few_shot() -> str:
    """喂给 VLM 的 few-shot 系统提示：让「可执行的图片修改」显式包裹标记块。

    只教模型**何时**包裹、包裹什么，不做任何语义猜测；模型不吐标记时解析器安全返回 None。
    """
    return (
        "【编辑指令格式】当用户想要**修改**已附带的图片（换背景/改颜色/去掉某个物体/重画某个区域等）时，"
        "在回答中先写一句自然语言说明，再用下面这对标记把**给编辑引擎的正向提示词**包起来，"
        f"形如：{EDIT_MARKER_START}把背景换成雪天，光线变成阴天{EDIT_MARKER_END}。\n"
        "- 包在标记里的是**编辑提示词本身**（中文、具体、只描述这次要做到的画面），不要把用户原话整个抄进去。\n"
        "- 只问不改、纯讨论、描述图片内容的，**不要**加标记块。\n"
        "- 一次只能给一个编辑指令；需要多个改动时合并成一句。\n"
        "- 若用户这次只是提问或闲聊，正常回答即可，绝不输出标记块。"
    )


# ── 权重单例缓存 ──────────────────────────────────────────────
# key = 规范化后的 HF 模型目录；value = {model, processor, ref_count, last_used, timer}
_VLM_CACHE: dict[str, dict[str, Any]] = {}
_VLM_CACHE_LOCK = threading.Lock()
_VLM_IDLE_SECONDS = 60.0


def _cuda_available() -> bool:
    try:
        import torch

        return torch.cuda.is_available()
    except Exception:  # pragma: no cover - torch 不可用
        return False


def _cache_key_for(model_dir: str) -> str:
    return str(Path(model_dir).resolve())


def request_vlm_unload() -> None:
    """生图/编辑请求优先卸 VLM（ADR-0001）：立即释放所有已加载 VLM 实例。

    由 worker 在 t2i/edit 任务启动前调用，确保 12GB 预算优先保 T2I。
    """
    with _VLM_CACHE_LOCK:
        for key in list(_VLM_CACHE.keys()):
            _evict(key)


def _evict(key: str) -> None:
    entry = _VLM_CACHE.pop(key, None)
    if entry is None:
        return
    timer = entry.get("timer")
    if timer is not None:
        timer.cancel()
    try:
        import torch

        del entry["model"]
        del entry["processor"]
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception as e:  # pragma: no cover - 环境相关
        logger.warning("VLM evict failed: %s", e)
    logger.info("VLM instance evicted: %s", key)


class VlmEngine:
    """进程内 VLM 看图聊天引擎（Qwen3-VL-8B 多模态决策器）。"""

    def __init__(
        self,
        name: str,
        display_name: str = "",
        display_name_en: str = "",
        config: dict[str, Any] | None = None,
    ) -> None:
        self._name = name
        self._display_name = display_name or name
        self._display_name_en = display_name_en or name
        self._config = config or {}
        self._ready = False
        self._cancel_requested = False
        self._model_dir = ""
        self._device = "cuda" if _cuda_available() else "cpu"

    # ── 协议属性 ────────────────────────────────────────────
    @property
    def name(self) -> str:
        return self._name

    @property
    def display_name(self) -> str:
        return self._display_name

    def is_ready(self) -> bool:
        return self._ready

    # ── 协议方法 ────────────────────────────────────────────
    async def load(self, on_progress: ProgressCallback | None = None) -> None:
        """解析 Qwen3-VL 模型目录并标记就绪（权重按需在首次聊天时加载到缓存）。"""
        if on_progress:
            on_progress(10, "phase_loading_workflow", {})

        from ..config import get_config

        cfg = get_config()
        engine_cfg = cfg.models.engines.get(self._name)
        if engine_cfg is None:
            raise RuntimeError(f"Engine '{self._name}' not found in config.models.engines")

        self._model_dir = _resolve_qwen3vl_dir(engine_cfg, cfg)
        if not self._model_dir:
            raise RuntimeError(
                f"Engine '{self._name}' 无法解析 Qwen3-VL 模型目录：需本地 HF 模型目录"
                f"（含 config.json / tokenizer），请设置 engines.{self._name}.local_model_dir"
                f" 指向已下载的 Qwen3-VL-8B 目录（本仓离线化，不自动下载）。"
            )

        if on_progress:
            on_progress(100, "phase_completed", {})
        self._ready = True
        logger.info("VlmEngine '%s' ready (model_dir=%s)", self._name, self._model_dir)

    async def unload(self) -> None:
        """卸载引擎：释放其缓存实例并标记未就绪。"""
        if self._model_dir:
            _evict(_cache_key_for(self._model_dir))
        self._ready = False
        logger.info("VlmEngine '%s' unloaded", self._name)

    async def infer_txt2img(self, config: Any, on_progress: ProgressCallback | None = None) -> list[str]:
        raise NotImplementedError("VlmEngine 仅支持看图聊天(infer_chat)，不支持文生图")

    async def infer_edit(self, config: Any, on_progress: ProgressCallback | None = None) -> list[str]:
        raise NotImplementedError("VlmEngine 仅支持看图聊天(infer_chat)，不支持图像编辑")

    async def cancel(self) -> None:
        """取消当前聊天（置位取消标志）。"""
        self._cancel_requested = True
        logger.info("VlmEngine '%s' cancel requested", self._name)

    def request_cancel(self) -> None:
        """线程安全的取消请求（可由 executor 线程调用）。"""
        self._cancel_requested = True
        logger.info("VlmEngine '%s' cancel requested (thread-safe)", self._name)

    # ── VLM 专属方法 ────────────────────────────────────────
    async def infer_chat(
        self,
        prompt: str,
        images: list[str] | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> str:
        """多模态聊天：images 为图片路径或 base64 字符串；返回 VLM 文本。

        Args:
            prompt: 用户文本问题。
            images: 图片路径列表（相对 outputs/ 或绝对路径）或 base64 data URI。
            on_progress: 进度回调。
        """
        if not self._ready:
            raise RuntimeError("VLM engine not ready, please load first")
        if on_progress:
            on_progress(5, "phase_vlm_encoding", {})

        self._cancel_requested = False
        cancel_flag = [False]

        def cancel_cb() -> None:
            cancel_flag[0] = True

        loop = asyncio.get_event_loop()
        fut = loop.run_in_executor(
            None,
            lambda: self._chat_sync(prompt, images or [], cancel_flag, on_progress),
        )
        watcher = asyncio.create_task(self._watch_cancel(fut, cancel_cb))
        try:
            result = await fut
        finally:
            watcher.cancel()
            self._cancel_requested = False
        return result

    # ── 内部辅助 ────────────────────────────────────────────
    def _chat_sync(
        self,
        prompt: str,
        images: list[str],
        cancel_flag: list[bool],
        on_progress: ProgressCallback | None,
    ) -> str:
        model, processor = self._acquire()
        try:
            from transformers import Qwen3VLForConditionalGeneration  # noqa: F401

            # 构建多模态消息；图片按路径 / base64 透传，交由 processor 处理。
            content: list[dict[str, Any]] = []
            for img in images:
                content.append({"type": "image", "image": img})
            content.append({"type": "text", "text": prompt})
            messages = [{"role": "user", "content": content}]

            text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)

            # qwen_vl_utils.process_vision_info 负责把 image/base64 解析为模型输入；
            # 未安装时回退为直接把 PIL/路径透传给 processor（较新 transformers 支持）。
            image_inputs = None
            video_inputs = None
            try:
                from qwen_vl_utils import process_vision_info

                image_inputs, video_inputs = process_vision_info(messages)
            except ImportError:  # pragma: no cover - 依赖可选
                logger.warning("qwen_vl_utils 未安装；回退为直接透传图片给 processor（需较新 transformers）")

            if on_progress:
                on_progress(20, "phase_vlm_encoding", {})
            inputs = processor(
                text=text,
                images=image_inputs,
                videos=video_inputs,
                return_tensors="pt",
            ).to(model.device)

            if on_progress:
                on_progress(50, "phase_vlm_generating", {})
            generated = model.generate(
                **inputs,
                max_new_tokens=int((self._config.get("max_new_tokens")) or 512),
            )
            if cancel_flag[0]:
                raise asyncio.CancelledError("vlm chat cancelled")

            # 截去输入部分，仅保留新生成 token。
            trimmed = generated[0][inputs["input_ids"].shape[1] :]
            output = processor.batch_decode(trimmed, skip_special_tokens=True)[0]
            if on_progress:
                on_progress(100, "phase_completed", {})
            return output.strip()
        finally:
            self._release()

    def _acquire(self) -> tuple[Any, Any]:
        """获取（或加载）单例模型；ref_count +1，取消挂起的空闲定时器。"""
        key = _cache_key_for(self._model_dir)
        with _VLM_CACHE_LOCK:
            entry = _VLM_CACHE.get(key)
            if entry is None:
                entry = self._load_model()
                _VLM_CACHE[key] = entry
            entry["ref_count"] += 1
            entry["last_used"] = time.time()
            timer = entry.get("timer")
            if timer is not None:
                timer.cancel()
                entry["timer"] = None
            return entry["model"], entry["processor"]

    def _release(self) -> None:
        """ref_count -1；归零后启动 60s 空闲定时器主动 evict（ADR-0001）。"""
        key = _cache_key_for(self._model_dir)
        with _VLM_CACHE_LOCK:
            entry = _VLM_CACHE.get(key)
            if entry is None:
                return
            entry["ref_count"] -= 1
            if entry["ref_count"] <= 0:
                timer = threading.Timer(_VLM_IDLE_SECONDS, lambda: _evict(key))
                timer.daemon = True
                entry["timer"] = timer
                timer.start()
                logger.info("VLM instance idle timer started (%ss): %s", _VLM_IDLE_SECONDS, key)

    def _load_model(self) -> dict[str, Any]:
        import torch
        from transformers import AutoProcessor, Qwen3VLForConditionalGeneration

        dtype = torch.float16 if self._device == "cuda" else torch.float32
        logger.info("[VLM] loading Qwen3-VL from %s (dtype=%s)", self._model_dir, dtype)
        model = Qwen3VLForConditionalGeneration.from_pretrained(
            self._model_dir, torch_dtype=dtype, device_map=self._device
        )
        processor = AutoProcessor.from_pretrained(self._model_dir)
        return {
            "model": model,
            "processor": processor,
            "ref_count": 0,
            "last_used": time.time(),
            "timer": None,
        }

    async def _watch_cancel(self, fut: Any, cancel_cb: Any) -> None:
        """监控取消标志；用户在聊天中调用 cancel() 时触发内部取消。"""
        while not fut.done():
            if self._cancel_requested:
                cancel_cb()
                return
            await asyncio.sleep(0.05)


def _resolve_qwen3vl_dir(engine_cfg: Any, cfg: Any) -> str:
    """解析 Qwen3-VL 的 HF 模型目录。

    优先级：engines.<name>.local_model_dir（本地已下载的 HF 仓库目录，含 config.json）>
    HF cache 中的 model_id> 空（无法离线加载）。
    """
    local = getattr(engine_cfg, "local_model_dir", "") or ""
    if local:
        p = Path(local)
        if not p.is_absolute():
            p = Path(cfg.project_root) / local
        if (p / "config.json").is_file():
            return str(p.resolve())
        logger.warning("[VLM] local_model_dir 指向 %s 但缺少 config.json", p)
    # HF cache 解析（离线环境通常不可用，仅作兼容）
    model_id = getattr(engine_cfg, "model_id", "") or ""
    if model_id:
        try:
            from transformers.utils import cached_files  # type: ignore

            files = cached_files(model_id, [""], local_files_only=True)
            if files:
                return str(Path(list(files.values())[0]).resolve())
        except Exception as e:  # pragma: no cover - 离线环境
            logger.debug("[VLM] HF cache 解析失败（离线）: %s", e)
    return ""
