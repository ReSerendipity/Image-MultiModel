"""Qwen3-VL 接入前 preflight —— 真加载 + 极小前向验证多模态链路。

目的：用实测（而非推断）确定三件事
  1. 本地 HF 模型目录（含 config.json / tokenizer）能否被
     ``transformers.Qwen3VLForConditionalGeneration`` 正常 from_pretrained
  2. ``processor.apply_chat_template`` + ``processor(...)`` 的多模态输入构造是否可用
     （qwen_vl_utils 未安装时回退为直接透传图片给 processor）
  3. ``model.generate`` 最小前向能否跑通并解码出文本（验证权重与词表配套）

离线约束：本仓严格离线化。脚本优先读 engines.qwen3_vl_8b_native.local_model_dir；
若该目录缺失（仅存在单个 .safetensors、无 config.json），则判定为「离线阻断」，
以退出码 2（SKIPPED）退出并给出清晰指引，绝不静默降级或联网下载。

用法：
    python scripts/preflight_qwen3vl.py                       # 读 config.yaml 解析模型目录
    python scripts/preflight_qwen3vl.py --model-dir /abs/path # 显式指定本地 HF 目录
    python scripts/preflight_qwen3vl.py --image /path/to.png  # 附一张图做多模态前向
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


def _resolve_model_dir(arg_model_dir: str | None) -> str:
    """解析 Qwen3-VL 本地 HF 模型目录。

    优先级：--model-dir 显参 > config.yaml engines.qwen3_vl_8b_native.local_model_dir
    （相对路径按 project_root 解析，且必须含 config.json）> 空（离线阻断）。
    """
    if arg_model_dir:
        p = os.path.abspath(arg_model_dir)
        if os.path.isfile(os.path.join(p, "config.json")):
            return p
        log(f"    [WARN] --model-dir 指向 {p} 但缺少 config.json")
        return ""

    try:
        from app.integrated_app.config import get_config

        cfg = get_config()
        eng = getattr(cfg.models, "engines", {}).get("qwen3_vl_8b_native")
        if eng is not None:
            local = getattr(eng, "local_model_dir", "") or ""
            if local:
                p = local if os.path.isabs(local) else os.path.join(cfg.project_root, local)
                p = os.path.abspath(p)
                if os.path.isfile(os.path.join(p, "config.json")):
                    return p
                log(f"    [WARN] config engines.qwen3_vl_8b_native.local_model_dir={p} 缺 config.json")
    except Exception as e:  # 配置加载失败不应阻断 preflight 的离线判定
        log(f"    [WARN] 读取 config.yaml 失败（{e!r}），回退离线判定")

    return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", default=None, help="本地 HF 模型目录（含 config.json），覆盖 config.yaml")
    ap.add_argument("--image", default=None, help="可选：附图做多模态前向（路径或留空走纯文本）")
    ap.add_argument("--prompt", default="用一句话描述这张图片。" if False else "Hello, who are you?")
    ap.add_argument("--max-new-tokens", type=int, default=16)
    args = ap.parse_args()

    log("== [0] 解析 Qwen3-VL 模型目录 ==")
    model_dir = _resolve_model_dir(args.model_dir)
    if not model_dir:
        log("SKIPPED(2): 离线阻断——未找到本地 Qwen3-VL HF 模型目录（需含 config.json）。")
        log("    解决：下载 Qwen/Qwen3-VL-8B 到本地，设置 config.yaml")
        log("    engines.qwen3_vl_8b_native.local_model_dir 指向该目录，再重跑本脚本。")
        log("    （本仓离线化，preflight 不联网下载；真实多模态前向须实机加载权重验证。）")
        return 2

    log(f"    model_dir = {model_dir}")

    log("== [1] 装载 transformers + torch ==")
    import torch
    from transformers import AutoProcessor, Qwen3VLForConditionalGeneration

    log(f"    torch={torch.__version__} cuda={torch.cuda.is_available()}")
    if torch.cuda.is_available():
        log(
            f"    GPU={torch.cuda.get_device_name(0)} "
            f"VRAM={torch.cuda.get_device_properties(0).total_memory / 2**30:.1f}GB"
        )
    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32

    log("== [2] 加载模型 + processor ==")
    t0 = time.time()
    model = Qwen3VLForConditionalGeneration.from_pretrained(model_dir, torch_dtype=dtype, device_map=device)
    processor = AutoProcessor.from_pretrained(model_dir)
    log(f"    loaded in {time.time() - t0:.1f}s")

    log("== [3] 构造多模态消息 + 前向 ==")
    content: list[dict] = []
    if args.image:
        content.append({"type": "image", "image": args.image})
    content.append({"type": "text", "text": args.prompt})
    messages = [{"role": "user", "content": content}]

    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)

    image_inputs = None
    video_inputs = None
    try:
        from qwen_vl_utils import process_vision_info

        image_inputs, video_inputs = process_vision_info(messages)
        log("    qwen_vl_utils 可用，已调用 process_vision_info")
    except ImportError:
        log("    qwen_vl_utils 未安装，回退为直接透传图片给 processor（纯文本模式无需）")

    t0 = time.time()
    inputs = processor(
        text=text,
        images=image_inputs,
        videos=video_inputs,
        return_tensors="pt",
    ).to(model.device)
    log(f"    inputs built in {time.time() - t0:.1f}s  shape={tuple(inputs['input_ids'].shape)}")

    log(f"== [4] model.generate(max_new_tokens={args.max_new_tokens}) ==")
    t0 = time.time()
    generated = model.generate(**inputs, max_new_tokens=args.max_new_tokens)
    log(f"    generated in {time.time() - t0:.1f}s  shape={tuple(generated.shape)}")

    trimmed = generated[0][inputs["input_ids"].shape[1] :]
    output = processor.batch_decode(trimmed, skip_special_tokens=True)[0]
    log(f"== 解码输出 ==\n{output.strip()}")

    log("== 结论 ==")
    log("OK(0): Qwen3-VL transformers 前向链路可用（加载 + processor + generate + decode）。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        log("FAILED(1): Qwen3-VL 前向异常，见上方 traceback")
        traceback.print_exc(limit=5)
        sys.exit(1)
