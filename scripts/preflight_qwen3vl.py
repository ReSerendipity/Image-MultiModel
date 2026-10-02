"""Qwen3-VL 接入前 preflight —— 真加载 + 极小前向验证多模态链路。

目的：用实测（而非推断）确定四件事
  1. ``config.yaml`` 声明的权重（``engines.qwen3_vl_8b_native.text_encoder.sub_path``）能否定位
  2. comfy_kernel 能否把该权重判成 ``TEModel.QWEN3VL_8B`` 并组装出 ``comfy.sd.CLIP``
     （判据键 ``model.visual.deepstack_merger_list.0.norm.weight``）
  3. ``clip.tokenize(image=...)`` 能否把图片占位符 ``<|image_pad|>`` 与像素张量对齐
  4. ``clip.generate`` + ``clip.decode`` 组成的极小前向能否跑通并解出文本（验证权重/词表配套）

关键口径（2026-10-02 实证返工）：本脚本**不走 transformers**。
本机 ``qwen3vl_8b_int8_convrot.safetensors`` 是 ComfyUI 专用 int8 convrot 量化格式
（每个线性层带 ``comfy_quant`` 张量），transformers 不认识；而 comfy_kernel 自带 config
（``comfy/text_encoders/llama.py`` 的 ``Qwen3VL_8BConfig``）与内置 ``qwen25_tokenizer``，
只需一份裸 safetensors 即可加载——**无需** HF 的 ``config.json``。

离线约束：本仓严格离线化。权重缺失时以退出码 2（SKIPPED）退出并给出清晰指引，
绝不静默降级或联网下载。

用法：
    python scripts/preflight_qwen3vl.py                       # 读 config.yaml 解析权重
    python scripts/preflight_qwen3vl.py --model-dir /abs/x.safetensors  # 显式指定权重文件
    python scripts/preflight_qwen3vl.py --image /path/to.png  # 附一张图做多模态前向
    python scripts/preflight_qwen3vl.py --device cpu          # CPU 回落（fp16，见 GOTCHAS）
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import traceback

# 保证从仓库任意位置运行都能 import app 包
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def log(msg: str) -> None:
    print(msg, flush=True)


def _resolve_weight(arg: str | None) -> str:
    """解析 Qwen3-VL 本地权重**文件**绝对路径。

    优先级：--model-dir 显参（指向 .safetensors）>
    config.yaml engines.qwen3_vl_8b_native.text_encoder.sub_path（经 resolve_model_path）>
    空（离线阻断）。
    """
    if arg:
        p = os.path.abspath(arg)
        if os.path.isfile(p):
            return p
        log(f"    [WARN] --model-dir 指向 {p} 但不是可读文件")
        return ""

    try:
        from app.integrated_app.config import get_config

        cfg = get_config()
        eng = getattr(cfg.models, "engines", {}).get("qwen3_vl_8b_native")
        if eng is not None:
            resolved = app_resolve_vlm_weight(eng, cfg)
            if resolved:
                return resolved
            log("    [WARN] config engines.qwen3_vl_8b_native.text_encoder 解析不到权重文件")
    except Exception as e:  # 配置加载失败不应阻断 preflight 的离线判定
        log(f"    [WARN] 读取 config.yaml 失败（{e!r}），回退离线判定")

    return ""


def app_resolve_vlm_weight(eng: object, cfg: object) -> str:
    """复用 app 侧权威解析器定位 VLM 权重，避免 preflight 另造一套路径约定。"""
    from app.integrated_app.native.vlm_engine import _resolve_qwen3vl_weight

    return _resolve_qwen3vl_weight(eng, cfg)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", default=None, help="本地 Qwen3-VL 权重 .safetensors 文件，覆盖 config.yaml")
    ap.add_argument("--image", default=None, help="可选：附图做多模态前向（路径或 data URI；不传走纯文本）")
    ap.add_argument("--prompt", default="用一句话描述这张图片。" if False else "Hello, who are you?")
    ap.add_argument("--max-new-tokens", type=int, default=16)
    ap.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"], help="推理设备；auto=有 CUDA 走 CUDA")
    ap.add_argument("--dtype", default="auto", choices=["auto", "fp16", "bf16", "fp32"], help="权重精度")
    args = ap.parse_args()

    log("== [0] 解析 Qwen3-VL 权重路径 ==")
    weight = _resolve_weight(args.model_dir)
    if not weight:
        log("SKIPPED(2): 离线阻断——未找到本地 Qwen3-VL 权重文件。")
        log("    解决：确认 config.yaml 的 models.engines.qwen3_vl_8b_native.text_encoder.sub_path")
        log("    指向真实的 *.safetensors（本机示例：Qwen-Image-2.1/qwen3vl_8b_int8_convrot.safetensors），")
        log("    或用 --model-dir 显式指定；再用本脚本重跑。")
        log("    （本仓离线化，preflight 不联网下载；真实多模态前向须实机加载权重验证。）")
        return 2

    log(f"    weight = {weight}")
    log(f"    size   = {os.path.getsize(weight) / 2**30:.2f} GiB")

    log("== [1] 装载 comfy_kernel 源码 ==")
    from app.integrated_app.native import source

    source.ensure_loaded()
    log(f"    comfy source = {source.get_comfy_root()}")

    import torch

    log(f"    torch={torch.__version__} cuda_available={torch.cuda.is_available()}")
    device = args.device
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype_name = args.dtype
    if dtype_name == "auto":
        # GOTCHAS：comfy 的 should_use_bf16(device) 对 CPU 恒返回 False，会走 fp32，
        # 8B 权重在 CPU 上即 ~32GB 内存；故 CPU 回落显式指定 fp16。
        dtype_name = "bf16" if device == "cuda" else "fp16"
    dtype = {"fp16": torch.float16, "bf16": torch.bfloat16, "fp32": torch.float32}[dtype_name]
    log(f"    device={device} dtype={dtype_name}")
    if device == "cuda" and torch.cuda.is_available():
        free, total = torch.cuda.mem_get_info()
        log(f"    VRAM total={total / 2**30:.1f}GiB free={free / 2**30:.1f}GiB")

    log("== [2] comfy.sd.load_clip（内部按权重键判 Qwen3VL_8B）==")
    import comfy.sd

    t0 = time.time()
    clip = comfy.sd.load_clip([weight], model_options={"dtype": dtype})
    log(f"    loaded in {time.time() - t0:.1f}s")
    log(f"    clip 类型 = {type(clip).__name__}（应含 tokenize/generate/decode）")
    for attr in ("tokenize", "generate", "decode"):
        assert hasattr(clip, attr), f"comfy.sd.CLIP 缺少 {attr}（comfy_kernel 版本漂移？）"

    log("== [3] 构造多模态输入（tokenize）==")
    image_batch = None
    if args.image:
        # GOTCHAS（2026-10-02）：这里必须拿模块级 build_image_batch，而不是引擎的静态方法
        # _load_image_batch——preflight 与引擎共用同一份实现才不会漂移。
        from app.integrated_app.native.vlm_engine import build_image_batch

        image_batch = build_image_batch([args.image])
        log(f"    image batch = {tuple(image_batch.shape)} dtype={image_batch.dtype}（应为 [1,H,W,3] 0~1 float）")

    t0 = time.time()
    tokens = clip.tokenize(args.prompt, image=image_batch, min_length=1, thinking=False)
    token_lists = list(tokens.values())[0] if isinstance(tokens, dict) else tokens
    flat = [t[0] for row in token_lists for t in row]
    # GOTCHAS：附图的 <|image_pad|>(151655) 会被 tokenizer **就地替换成 image embed dict**
    # （qwen3vl.py 的 tokenize_with_weights），所以「图接进去了」的判据是 embed dict 个数，
    # 而不是数 151655——数它恒为 0，会误报成「图片没接进去」。
    n_pad = sum(1 for t in flat if isinstance(t, dict) and t.get("type") == "image")
    log(f"    tokenize in {time.time() - t0:.3f}s  n_tokens={len(flat)}  image embed={n_pad}")
    if image_batch is not None and n_pad == 0:
        log("    [WARN] 附了图却没解析出 image embed ——图片未接进序列")
    if image_batch is None and n_pad > 0:
        log("    [WARN] 没附图却出现 image embed ——占位符派发错位")

    log(f"== [4] clip.generate(max_new_tokens={args.max_new_tokens}) ==")
    t0 = time.time()
    generated = clip.generate(
        tokens,
        do_sample=False,
        max_length=args.max_new_tokens,
        temperature=1.0,
        top_k=50,
        top_p=1.0,
        min_p=0.0,
        repetition_penalty=1.0,
        seed=0,
        mtp=False,
    )
    log(f"    generated in {time.time() - t0:.1f}s  n_ids={len(generated)}")

    log("== [5] clip.decode ==")
    output = clip.decode(generated)
    log("== 解码输出 ==")
    log(str(output).strip())

    log("== 结论 ==")
    log("OK(0): Qwen3-VL comfy_kernel 前向链路可用（权重定位 → load_clip → tokenize → generate → decode）。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        log("FAILED(1): Qwen3-VL 前向异常，见上方 traceback")
        traceback.print_exc(limit=5)
        sys.exit(1)
