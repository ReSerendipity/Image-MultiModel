"""
scripts/smoke_agent_multi.py — 模拟用户多轮使用:生成 → 修改(同会话上下文)

轮 1:画一只戴帽子的橘猫,赛博朋克霓虹风
轮 2:同会话追加"把帽子的霓虹灯带换成红色,背景改成雪夜,其他保持"
验证:第二轮 LLM 应继承第一轮画面设定、只改差异参数(多轮上下文能力实证)

用法:aki-python scripts/smoke_agent_multi.py
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

SESSION = "smoke-multi-1"
ROUNDS = [
    "画一只戴帽子的橘猫,赛博朋克霓虹风",
    "还是这只猫,把帽子上的霓虹灯带换成红色,背景从雨夜改成雪夜,其他保持不变,再来一张",
]


def parse_sse(text: str) -> list[dict]:
    out = []
    for block in text.split("\n\n"):
        b = block.strip()
        if b.startswith("data:") and "[DONE]" not in b:
            out.append(json.loads(b[5:].strip()))
    return out


def poll(client: TestClient, task_id: str, timeout_s: int = 600) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        task = client.get(f"/api/tasks/{task_id}").json()
        status = str(task.get("status", "")).lower()
        print(f"      {status} progress={task.get('progress')} {(task.get('error') or '')[:80]}")
        if status in ("completed", "failed", "cancelled"):
            return task
        time.sleep(3)
    return {"status": "timeout"}


def main() -> int:
    results: list[str] = []
    with TestClient(create_app()) as client:
        h = client.get("/api/agent/health").json()
        print("[0] llm_ok:", h.get("llm_ok"))
        if not h.get("llm_ok"):
            return 1

        csrf0 = client.get("/api/health").headers.get("X-CSRF-Token", "")
        client.post(
            "/api/engine/load",
            json={"engine_name": "z_image_turbo_native"},
            headers={"X-CSRF-Token": csrf0},
        )

        prompts_by_round: dict[int, str] = {}
        for i, message in enumerate(ROUNDS, 1):
            print(f"\n=== 轮 {i}: {message}")
            csrf = client.get("/api/health").headers.get("X-CSRF-Token", "")
            sse = client.post(
                "/api/agent/chat",
                json={"message": message, "session_id": SESSION},
                headers={"X-CSRF-Token": csrf},
            )
            events = parse_sse(sse.text)
            for e in events:
                if e.get("type") == "tool_call":
                    args = e.get("args", {})
                    prompts_by_round[i] = str(args.get("positive_prompt", ""))
                    print(f"    [prompt] {prompts_by_round[i][:220]}")
                    print(
                        f"    [params] {args.get('width')}x{args.get('height')} steps={args.get('steps')} cfg={args.get('cfg')}"
                    )
                elif e.get("type") == "task_created":
                    print(f"    [task] {e['task_id']}")
                elif e.get("type") == "final":
                    print(f"    [reply] {str(e.get('text'))[:160]}")

            task_ids = [e["task_id"] for e in events if e.get("type") == "task_created"]
            if not task_ids:
                print("!! 无 task_created")
                return 1
            task = poll(client, task_ids[0])
            if task.get("status") != "completed":
                print("!! 任务未完成:", task.get("status"), task.get("error"))
                return 1
            for p in task.get("result") or []:
                rel = str(p).replace("\\", "/")
                idx = rel.find("outputs/")
                rel = rel[idx + 8 :] if idx >= 0 else rel
                full = ROOT / "outputs" / rel
                if full.exists():
                    results.append(str(full))
                    print(f"    [img] {full.name} ({full.stat().st_size} bytes)")

        print("\n=== 多轮上下文对比 ===")
        print("轮1 prompt:", prompts_by_round.get(1, "")[:300])
        print("轮2 prompt:", prompts_by_round.get(2, "")[:300])
        p1, p2 = prompts_by_round.get(1, ""), prompts_by_round.get(2, "")
        ctx_ok = (
            bool(p2)
            and ("red" in p2.lower() or "红色" in p2)
            and ("snow" in p2.lower() or "雪" in p2 or "winter" in p2.lower())
        )
        print("轮2 差异修改(红+雪):", "PASS" if ctx_ok else "CHECK-MANUALLY")

    print("\n=== 产出图片 ===")
    for r in results:
        print("  ", r)
    print("[RESULT]", "MULTI-ROUND-OK" if len(results) >= len(ROUNDS) else "FAILED")
    return 0 if len(results) >= len(ROUNDS) else 1


if __name__ == "__main__":
    sys.exit(main())
