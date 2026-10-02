"""
native/vlm_engine.py — VLM 看图聊天引擎（P2-vlm-chat M1）

复用 Qwen3-VL-8B 权重作为多模态决策器（方案 A：复用 Agent + VLM 模型）。

架构约束（详见 docs/roadmap/P2-vlm-chat.md）：
- **推理路径走 comfy_kernel，不走 transformers**（2026-10-02 实证返工）。本机那份
  ``qwen3vl_8b_int8_convrot.safetensors`` 是 **ComfyUI 专用 int8 convrot 量化格式**（每个线性层
  带 ``comfy_quant`` 张量），transformers 不认识该格式；但 comfy_kernel 侧完整具备 VLM 前向要素
  （视觉塔 + ``lm_head`` 生成头 + 内置 ``qwen25_tokenizer``），故多模态聊天由
  ``comfy.sd.load_clip()`` 构建 ``comfy.sd.CLIP``，再走
  ``clip.tokenize(image=...)`` → ``clip.generate(...)`` → ``clip.decode(...)``。
- 权重单例：``_VLM_CACHE`` 按**权重文件绝对路径**键控，同一路径的多次 acquire 共享一份
  ``comfy.sd.CLIP`` 实例；但与编辑引擎的 comfy CLIP 加载器**不是**同一份实例（跨加载器无法共享），
  该限制已在文档如实标注——不要误以为 VLM + 编辑引擎能省一份 9.35GB 常驻。
- 卸载策略：沿用 ADR-0001 空闲卸载（条目 ref_count 归零后 60s 主动 evict）；生图/编辑请求
  触发时由 worker 调 ``request_vlm_unload()`` 优先卸 VLM 保 T2I。
- 离线约束：本仓严格离线化，Qwen3-VL 权重需本地就位（``config.yaml``
  ``models.engines.qwen3_vl_8b_native.text_encoder.sub_path`` 声明子路径，经
  ``config_models.resolve_model_path`` 解析），否则 load() 报清晰错误，不静默降级、不联网下载。
  注意：**不需要** HF 的 ``config.json`` / tokenizer 文件——comfy 的 config 写在 Python 里
  （``comfy/text_encoders/llama.py`` 的 ``Qwen3VL_8BConfig``）、tokenizer 内置于
  ``comfy/text_encoders/qwen25_tokenizer/``，只有裸 safetensors 也可加载。

验证说明：``infer_chat`` 的多模态前向需实机加载权重（见 scripts/preflight_qwen3vl.py），
本模块的单测用 mock 覆盖编排逻辑与缓存/卸载，不触碰真实权重与 GPU。
"""

from __future__ import annotations

import asyncio
import logging
import os
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
# key = 规范化后的权重文件绝对路径；value = {model, processor, ref_count, last_used, timer}
# ``model`` 自 comfy_kernel 返回后即 ``comfy.sd.CLIP`` 实例（``processor`` 恒为 None，
# 保留键位是为了不破坏既有的 entry 结构），生成/解码都通过 ``model`` 完成。
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
        # comfy_kernel 侧持有的只是一个 CLIP 门面，真正占显存的是 ModelPatcher 里的
        # checkpoints；del 门面不会自动释放，必须显式丢引用 + empty_cache。
        del entry["model"]
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
        """解析 Qwen3-VL 权重文件路径并标记就绪（真权重在首次聊天时经 comfy_kernel 才上显存）。"""
        if on_progress:
            on_progress(10, "phase_loading_workflow", {})

        from ..config import get_config

        cfg = get_config()
        engine_cfg = cfg.models.engines.get(self._name)
        if engine_cfg is None:
            raise RuntimeError(f"Engine '{self._name}' not found in config.models.engines")

        self._model_dir = _resolve_qwen3vl_weight(engine_cfg, cfg)
        if not self._model_dir:
            raise RuntimeError(
                f"Engine '{self._name}' 无法定位 Qwen3-VL 权重：请在 config.yaml 的"
                f" engines.{self._name}.text_encoder.sub_path 声明权重相对子路径"
                f"（如 Qwen-Image-2.1/qwen3vl_8b_int8_convrot.safetensors），"
                f"或设置 engines.{self._name}.local_model_dir 指向本地目录"
                f"（本仓离线化，不自动下载，也不需要 config.json / tokenizer 文件）。"
            )

        if on_progress:
            on_progress(100, "phase_completed", {})
        self._ready = True
        logger.info("VlmEngine '%s' ready (weight=%s)", self._name, self._model_dir)

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
        clip = self._acquire()
        try:
            # 图片 → comfy 约定的 [N,H,W,3] float32（0~1）批；纯文本时传 None。
            image_batch = self._load_image_batch(images) if images else None

            if on_progress:
                on_progress(20, "phase_vlm_encoding", {})

            # tokenize 内部负责把 <|image_pad|> 占位符与图片张量一一对应（qwen3vl.py
            # Qwen3VLTokenizer.tokenize_with_weights），无需调用方手塞 token。
            tokens = clip.tokenize(prompt, image=image_batch, min_length=1, thinking=False)

            if cancel_flag[0]:
                raise asyncio.CancelledError("vlm chat cancelled")

            if on_progress:
                on_progress(50, "phase_vlm_generating", {})

            # 注意：``generate`` 返回的是**新生成的 token id 列表**（不含输入），
            # 故无需像 transformers 那样按 input length 截断。
            seed = int(self._config.get("seed") or 0)
            generated = clip.generate(
                tokens,
                do_sample=True,
                max_length=int(self._config.get("max_new_tokens") or 512),
                temperature=float(self._config.get("temperature", 1.0)),
                top_k=int(self._config.get("top_k", 50)),
                top_p=float(self._config.get("top_p", 1.0)),
                min_p=float(self._config.get("min_p", 0.0)),
                repetition_penalty=float(self._config.get("repetition_penalty", 1.0)),
                seed=seed,
                mtp=False,
            )
            if cancel_flag[0]:
                raise asyncio.CancelledError("vlm chat cancelled")

            output = clip.decode(generated)
            if on_progress:
                on_progress(100, "phase_completed", {})
            return output.strip()
        finally:
            self._release()

    @staticmethod
    def _load_image_batch(images: list[str]) -> Any:
        """类内委托到模块级 :func:`build_image_batch`，保证与 preflight 共用同一份实现。"""
        return build_image_batch(images)

    def _acquire(self) -> Any:
        """获取（或加载）单例 ``comfy.sd.CLIP``；ref_count +1，取消挂起的空闲定时器。"""
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
            return entry["model"]

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
        """经 comfy_kernel 构建 Qwen3-VL 的 ``comfy.sd.CLIP`` 门面（真权重在 acquire 时才上显存）。

        为什么走 ``comfy.sd.load_clip`` 而不是自己 ``new Qwen3VL(...)``：
        权重的 int8 convrot 量化元数据要由 ``comfy.utils.convert_old_quants`` /
        ``llama_detect`` 识别后经 ``model_options["quantization_metadata"]`` 下沉到各线性层，
        自己组装会漏掉量化分支，且还要自己拼视觉塔/DeepStack/mrope，属于重复实现官方路径。
        ``load_clip`` 内部会按权重键 ``model.visual.deepstack_merger_list.0.norm.weight``
        判定为 ``TEModel.QWEN3VL_8B`` 并选 ``comfy.text_encoders.qwen3vl.te``。
        """
        from . import source

        comfy_root = self._config.get("comfy_source_dir") or None
        source.ensure_loaded(comfy_root=comfy_root)

        import comfy.sd  # 保障 source.ensure_loaded 已把 comfy_kernel 置于 sys.path 头部

        logger.info("[VLM] loading Qwen3-VL via comfy_kernel from %s", self._model_dir)
        clip = comfy.sd.load_clip([self._model_dir])
        return {
            "model": clip,
            "processor": None,
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


def _decode_image_to_rgb(src: str) -> Any:
    """把图片源（绝对路径 / 相对 outputs 路径 / base64 data URI）解码为 ``[H,W,3]`` float32 0~1。

    Args:
        src: 图片来源字符串。

    Returns:
        numpy 数组，dtype=float32、取值范围 0~1、通道顺序 RGB。

    Raises:
        ValueError: 既不是可读文件也不是合法 base64。
    """
    import base64
    from io import BytesIO

    import numpy as np
    from PIL import Image

    def _from_pil(im: Any) -> Any:
        im = im.convert("RGB")
        return np.asarray(im, dtype=np.float32) / 255.0

    candidates: list[str] = []
    if os.path.isabs(src) or os.path.sep in src or "/" in src:
        candidates.append(src)
    # 相对路径按 outputs/ 兜底（前端气泡里的相对路径都相对该目录）
    try:
        from ..config import get_config

        cfg = get_config()
        base = Path(cfg.output.base_dir)
        if not base.is_absolute():
            base = Path(cfg.project_root) / base
        candidates.append(str(base / src))
    except Exception:  # noqa: BLE001 - 配置不可用时不强求相对路径兜底
        pass

    for c in candidates:
        if os.path.isfile(c):
            with Image.open(c) as im:
                return _from_pil(im)

    # 最后按 base64/data URI 解析
    payload = src.split(",", 1)[1] if src.startswith("data:") else src
    try:
        raw = base64.b64decode(payload, validate=True)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"图片既不是可读文件也不是合法 base64: {src[:64]}") from e
    with Image.open(BytesIO(raw)) as im:
        return _from_pil(im)


def build_image_batch(images: list[str]) -> Any:
    """把图片路径 / base64 拼成 comfy 约定形状的 ``[N,H,W,3]`` float32（0~1）张量。

    Qwen3-VL 侧 ``process_qwen2vl_images`` 期望输入 0~1 归一化（内部按 mean=std=0.5
    转成 -1~1），且只接受同一个批里分辨率一致（内部会按 patch 对齐 resize）。
    多图分辨率不一致时统一缩放到首图尺寸，避免 torch.stack 直接炸。

    GOTCHAS（2026-10-02）：本函数是 preflight 与引擎**共用**的实现——早期版本 preflight 直接
    import 引擎的静态方法，静态方法名一改 preflight 就 ImportError，且两份实现会漂移。故抽出
    模块级单一实现，类内静态方法来信委托。
    """
    import numpy as np
    import torch
    from PIL import Image

    tensors: list[Any] = []
    for img in images:
        try:
            arr = _decode_image_to_rgb(img)
        except Exception as e:  # noqa: BLE001 - 单张图坏掉不该拖垮整轮对话
            logger.warning("[VLM] 图片解码失败，按无图处理: %s", e)
            continue
        tensors.append(arr)
    if not tensors:
        return None
    h, w = tensors[0].shape[:2]
    if any(t.shape[:2] != (h, w) for t in tensors):
        logger.warning("[VLM] 多图分辨率不一致，统一缩放到 %dx%d", h, w)
        tensors = [
            np.asarray(Image.fromarray(t).resize((w, h), Image.Resampling.BILINEAR), dtype=np.float32) / 255.0
            for t in tensors
        ]
    return torch.from_numpy(np.stack(tensors, axis=0))


def _resolve_qwen3vl_weight(engine_cfg: Any, cfg: Any) -> str:
    """解析 Qwen3-VL 的**权重文件**绝对路径（不需要目录里有 config.json）。

    优先级：
    1. ``engines.<name>.text_encoder``（sub_dir + sub_path）经
       ``config_models.resolve_model_path`` 解析——与其余引擎同一套权威路径约定；
    2. ``engines.<name>.local_model_dir`` 指向的目录内递归找 ``qwen3vl*`` 的
       .safetensors（兼容顺手下载成 HF 目录的情况）；
    3. 空串（无法离线定位，由调用方报清晰错误）。
    """
    from ..config_models import ModelPaths, resolve_model_path

    model_paths: ModelPaths | None = getattr(engine_cfg, "text_encoder", None)
    sub_path = model_paths.sub_path if model_paths is not None else ""
    if sub_path:
        assert model_paths is not None
        resolved = resolve_model_path(model_paths, cfg.models, cfg.project_root)
        if os.path.isfile(resolved):
            return resolved
        logger.warning("[VLM] text_encoder.sub_path 解析为 %s 但文件不存在", resolved)

    local = getattr(engine_cfg, "local_model_dir", "") or ""
    if local:
        p = Path(local)
        if not p.is_absolute():
            p = Path(cfg.project_root) / local
        if p.is_dir():
            cands = sorted(p.glob("**/*.safetensors"))
            hit = next((c for c in cands if "qwen3vl" in c.name.lower()), cands[0] if cands else None)
            if hit is not None:
                return str(hit.resolve())
            logger.warning("[VLM] local_model_dir 指向 %s 但目录内无 safetensors", p)
    return ""
