"""
scripts/smoke_edit_real.py — P1 编辑链路真实出图 + 显存峰值验证

背景:另一会话实测 edit_resolution=1024 时峰值显存 13.23GB(12GB 卡靠共享显存),
建议默认降到 512 但未实跑确认。本脚本:
  阶段 A:Agent 全链编辑(不指定 resolution,观察 LLM 默认行为)
  阶段 B:明确要求 edit_resolution=512 的编辑
两阶段均采样 nvidia-smi 显存峰值,输出对比。

前置:.env(IMAGE_MM_AGENT_LLM_*);qwen_image_edit_native 权重就位;参考图在 outputs/。
用法:aki-python scripts/smoke_edit_real.py [参考图相对 outputs 的路径]
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))

from app.integrated_app.config import _load_dotenv  # noqa: E402

_load_dotenv()

from fastapi.testclient import TestClient  # noqa: E402

from app.integrated_app.app_server import create_app  # noqa: E402

REF_DEFAULT = "outputs/z_image_turbo_native/20260929/000001a0ed794e3e_0_AI.png"


class VramSampler:
    """每秒采样 nvidia-smi 显存占用,记录峰值(MiB)。"""

    def __init__(self) -> None:
        self.peak = 0
        self.samples: list[int] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                out = (
                    subprocess.run(
                        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    .stdout.strip()
                    .splitlines()
                )
                used = int(out[0])
                self.samples.append(used)
                self.peak = max(self.peak, used)
            except Exception:  # noqa: BLE001 — 采样失败不阻塞主链路
                pass
            self._stop.wait(1.0)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> int:
        self._stop.set()
        self._thread.join(timeout=3)
        return self.peak


def parse_sse(text: str) -> list[dict]:
    out = []
    for block in text.split("\n\n"):
        b = block.strip()
        if b.startswith("data:") and "[DONE]" not in b:
            out.append(json.loads(b[5:].strip()))
    return out


def run_edit(client: TestClient, csrf: str, message: str, tag: str, sampler: VramSampler) -> tuple[bool, str]:
    print(f"\n=== {tag}: {message[:80]}")
    sse = client.post(
        "/api/agent/chat", json={"message": message, "session_id": "smoke-edit-1"}, headers={"X-CSRF-Token": csrf}
    )
    events = parse_sse(sse.text)
    for e in events:
        if e.get("type") == "tool_call":
            print(
                f"    [tool] {e.get('name')} edit_resolution={e.get('args', {}).get('edit_resolution')} "
                f"ref={str(e.get('args', {}).get('reference_path') or e.get('args', {}).get('task_id'))[:60]}"
            )
        elif e.get("type") == "task_created":
            print(f"    [task] {e['task_id']}")
        elif e.get("type") == "final":
            print(f"    [reply] {str(e.get('text'))[:120]}")
        elif e.get("type") == "error":
            print(f"    [ERR] {str(e.get('text'))[:200]}")
    task_ids = [e["task_id"] for e in events if e.get("type") == "task_created"]
    if not task_ids:
        return False, ""
    deadline = time.time() + 600
    task: dict = {}
    while time.time() < deadline:
        task = client.get(f"/api/tasks/{task_ids[0]}").json()
        status = str(task.get("status", "")).lower()
        if status in ("completed", "failed", "cancelled"):
            break
        time.sleep(3)
    print(f"    [status] {status}")
    if status != "completed":
        print("    [error]", (task.get("error") or "")[:200])
        return False, ""
    peak = sampler.peak
    print(f"    [VRAM peak so far] {peak} MiB ({peak / 1024:.2f} GiB)")
    for p in task.get("result_paths") or task.get("result") or []:
        print(f"    [out] {p}")
    return True, str(task.get("result_paths") or task.get("result") or "")


def main() -> int:
    ref = sys.argv[1] if len(sys.argv) > 1 else REF_DEFAULT
    sampler = VramSampler()
    with TestClient(create_app()) as client:
        h = client.get("/api/agent/health").json()
        print("[0] llm_ok:", h.get("llm_ok"))
        if not h.get("llm_ok"):
            return 1
        csrf0 = client.get("/api/health").headers.get("X-CSRF-Token", "")
        r = client.post(
            "/api/engine/load", json={"engine_name": "qwen_image_edit_native"}, headers={"X-CSRF-Token": csrf0}
        )
        body = r.json()
        print("[1] engine load:", body.get("status"), body.get("message", "")[:120])
        if body.get("status") not in ("loaded", "loading"):
            return 1

        sampler.start()
        time.sleep(2)

        ok_a, _ = run_edit(
            client,
            csrf0,
            f"编辑这张图: {ref} 。把背景改成雪夜,飘雪、积雪地面,其他保持不变。",
            "阶段 A(LLM 默认 resolution)",
            sampler,
        )
        peak_a = sampler.peak

        ok_b, _ = run_edit(
            client,
            csrf0,
            f"编辑这张图: {ref} 。把背景改成黄昏金色光晕,其他保持不变。必须使用 edit_resolution=512 以节省显存。",
            "阶段 B(显式 512)",
            sampler,
        )
        peak_total = sampler.stop()

    print("\n=== 显存峰值对比 ===")
    print(f"阶段 A 后峰值(A,LLM 默认): {peak_a} MiB ({peak_a / 1024:.2f} GiB)")
    print(f"全程峰值(A+B): {peak_total} MiB ({peak_total / 1024:.2f} GiB)")
    verdict = "OK-UNDER-12GB" if peak_total <= 12288 else "OVER-12GB-SHARED-MEM"
    print("[RESULT]", "EDIT-OK " + verdict if (ok_a and ok_b) else "EDIT-FAILED")
    return 0 if (ok_a and ok_b) else 1


if __name__ == "__main__":
    sys.exit(main())
