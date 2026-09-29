"""
scripts/smoke_comfy_qwen21.py — 多模型测试:Qwen-Image 2.1(经本地 ComfyUI 8188 桥)

DEV-ONLY(本机运维/冒烟脚本,默认值指向本机 ComfyUI 安装,不参与分发):
  - 需本机已装 ComfyUI-aki-v3 且权重就位;路径可用环境变量覆盖:
      IMAGE_MM_COMFY_OUTPUT   ComfyUI 输出目录(默认 <用户主目录>/APP/ComfyUI-aki-v3/ComfyUI/output)
      IMAGE_MM_COMFY_BASE     ComfyUI 服务地址(默认 http://127.0.0.1:8188)
  - 本文件头部含 DEV-ONLY 标记,故 scripts/check_no_hardcoded_paths.py 豁免其默认值。

背景:Image_MultiModel native 引擎当前仅实现 z_image_turbo 工作流构建器(评估报告 P2 多引擎
余量)。本轮多模型验证走"ComfyUI 桥":蓝图 UI 工作流手工内联为 API 格式(裁剪 SeedVR2/
LoRA 占位/BatchPrompt 分支),提交 8188 /prompt,轮询 /history 验证真实出图。

前置:ComfyUI 已监听 127.0.0.1:8188;权重在 aki models(天然就位)。
用法:aki-python scripts/smoke_comfy_qwen21.py "提示词(可中文)"
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

BASE = os.environ.get("IMAGE_MM_COMFY_BASE", "http://127.0.0.1:8188")
COMFY_OUTPUT = os.environ.get(
    "IMAGE_MM_COMFY_OUTPUT",
    str(Path.home() / "APP" / "ComfyUI-aki-v3" / "ComfyUI" / "output"),
)
PREFIX = "qwen21_agent_smoke"

POS = (
    sys.argv[1]
    if len(sys.argv) > 1
    else (
        "一只戴着黑色宽檐礼帽的橘猫,赛博朋克风格,帽檐上缠绕着发光的蓝色LED灯带,"
        "背景是雨夜的未来都市街道,霓虹招牌倒影,电影级布光,高细节写实,8K"
    )
)
NEG = "blurry, low quality, deformed, extra limbs, watermark, text"


def build_prompt_api(seed: int) -> dict:
    """Qwen-Image 2.1 API 格式工作流(自 blueprints/Image/Qwen_image_2_1_t2i.json 内联裁剪)。"""
    return {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": "Qwen-Image-2.1\\qwen_image_2.1_int8_convrot.safetensors",
                "weight_dtype": "default",
            },
        },
        "2": {
            "class_type": "CLIPLoader",
            "inputs": {
                "clip_name": "Qwen-Image-2.1\\qwen3vl_8b_int8_convrot.safetensors",
                "type": "qwen_image",
                "device": "default",
            },
        },
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "Qwen-Image-2.1\\qwen_image_2.1_vae_bf16.safetensors"}},
        "4": {
            "class_type": "TextEncodeQwenImage21",
            "inputs": {"clip": ["2", 0], "prompt": POS, "negative_prompt": "", "resolution": 1024},
        },
        "5": {
            "class_type": "TextEncodeQwenImage21",
            "inputs": {"clip": ["2", 0], "prompt": "", "negative_prompt": NEG, "resolution": 1024},
        },
        "6": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
        "7": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "positive": ["4", 0],
                "negative": ["5", 0],
                "latent_image": ["6", 0],
                "seed": seed,
                "steps": 25,
                "cfg": 1.0,
                "sampler_name": "euler",
                "scheduler": "simple",
                "denoise": 1.0,
            },
        },
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": PREFIX}},
    }


def post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def main() -> int:
    stats = json.loads(urllib.request.urlopen(BASE + "/system_stats", timeout=10).read())
    print("[1] ComfyUI online:", stats.get("system", {}).get("os"), "|", stats.get("devices", [{}])[0].get("name", ""))

    seed = int(time.time()) % (2**31)
    api_prompt = build_prompt_api(seed)
    resp = post("/prompt", {"prompt": api_prompt, "client_id": "agent-smoke"})
    prompt_id = resp.get("prompt_id")
    if not prompt_id:
        print("!! submit failed:", json.dumps(resp, ensure_ascii=False)[:400])
        return 1
    print("[2] queued prompt_id:", prompt_id)

    deadline = time.time() + 600
    history: dict = {}
    while time.time() < deadline:
        time.sleep(5)
        history = json.loads(urllib.request.urlopen(f"{BASE}/history/{prompt_id}", timeout=30).read())
        if prompt_id in history:
            break
        print("    ...generating(Qwen 2.1 25 步,首次加载权重较慢)")
    if prompt_id not in history:
        print("!! 超时")
        return 1

    status_obj = history[prompt_id].get("status", {})
    status_str = status_obj.get("status_str", "?")
    completed = status_obj.get("completed", False)
    print(f"[3] status: {status_str} completed={completed}")
    if status_str != "success":
        msgs = [m for m in status_obj.get("messages", []) if m[0] in ("execution_error", "execution_interrupted")]
        print("!! errors:", json.dumps(msgs, ensure_ascii=False)[:500])
        return 1

    outs = history[prompt_id].get("outputs", {})
    ok = False
    for _node, payload in outs.items():
        for img in payload.get("images", []):
            full = COMFY_OUTPUT + "\\" + img.get("subfolder", "") + "\\" + img["filename"]
            import os

            exists = os.path.exists(full)
            size = os.path.getsize(full) if exists else 0
            print(f"[4] {img['filename']} exists={exists} size={size}")
            ok = ok or (exists and size > 50000)

    print("[RESULT]", "QWEN21-OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
