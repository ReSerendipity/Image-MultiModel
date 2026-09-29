"""
scripts/smoke_agent_real.py — Agent 真实出图冒烟(云 LLM 决策 + 本地引擎推理)

链路:agent health → engine/load → POST /api/agent/chat(SSE)
      → task_created → 轮询 /api/tasks/{id} → COMPLETED → 验证图片文件落盘

前置:
- .env 含 IMAGE_MM_AGENT_LLM_*(ModelScope 测试 API,密钥不入库)
- pretrained_models 权重 junction 就位(unet/text/vae)
- 运行环境:aki-v3 python(torch 2.9.1+cu130 + fastapi;系统 312 暂无 torch)

用法:
    aki-python scripts/smoke_agent_real.py "画一只戴帽子的橘猫,赛博朋克霓虹风"
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))

from app.integrated_app.config import _load_dotenv  # noqa: E402

_load_dotenv()

from fastapi.testclient import TestClient  # noqa: E402

from app.integrated_app.app_server import create_app  # noqa: E402


def parse_sse(text: str) -> list[dict]:
    out = []
    for block in text.split("\n\n"):
        b = block.strip()
        if b.startswith("data:") and "[DONE]" not in b:
            out.append(json.loads(b[5:].strip()))
    return out


def main() -> int:
    prompt = sys.argv[1] if len(sys.argv) > 1 else "画一只戴帽子的橘猫,赛博朋克霓虹风"
    with TestClient(create_app()) as client:
        h = client.get("/api/agent/health").json()
        print("[1] agent health:", json.dumps(h, ensure_ascii=False))
        if not h.get("llm_ok"):
            print("!! LLM 大脑不在线")
            return 1

        print("[2] loading engine z_image_turbo_native(首次加载 30~90s,请耐心)...")
        csrf0 = client.get("/api/health").headers.get("X-CSRF-Token", "")
        r = client.post(
            "/api/engine/load",
            json={"engine_name": "z_image_turbo_native"},
            headers={"X-CSRF-Token": csrf0},
        )
        print("    ", r.status_code, r.text[:300])
        if r.status_code != 200:
            return 1

        csrf = client.get("/api/health").headers.get("X-CSRF-Token", "")
        print("[3] agent chat:", prompt)
        sse = client.post("/api/agent/chat", json={"message": prompt}, headers={"X-CSRF-Token": csrf})
        print("    status:", sse.status_code)
        events = parse_sse(sse.text)
        for e in events:
            brief = {k: str(v)[:140] for k, v in e.items()}
            print("    <", e.get("type"), json.dumps(brief, ensure_ascii=False)[:300])
        task_ids = [e["task_id"] for e in events if e.get("type") == "task_created"]
        if not task_ids:
            print("!! 无 task_created 事件")
            return 1
        task_id = task_ids[0]

        print("[4] polling task", task_id, "(首次推理含模型加载,最长 10 分钟)")
        deadline = time.time() + 600
        status = None
        task: dict = {}
        while time.time() < deadline:
            task = client.get(f"/api/tasks/{task_id}").json()
            status = str(task.get("status", "")).lower()  # TaskStatus 枚举 JSON 序列化为小写
            print(
                "    ", status, f"progress={task.get('progress')}", task.get("phase"), (task.get("error") or "")[:100]
            )
            if status in ("completed", "failed", "cancelled"):
                break
            time.sleep(3)
        if status != "completed":
            print("!! 任务未完成:", status)
            return 1

        print("[5] verify output files")
        ok = False
        for p in task.get("result") or []:
            rel = str(p).replace("\\", "/")
            idx = rel.find("outputs/")
            rel = rel[idx + 8 :] if idx >= 0 else rel
            full = ROOT / "outputs" / rel
            exists = full.exists()
            size = full.stat().st_size if exists else 0
            print("    ", rel, "exists=", exists, "size=", size)
            ok = ok or (exists and size > 10000)

        print("[RESULT]", "REAL-IMAGE-OK" if ok else "FAILED")
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
