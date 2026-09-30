"""
tests/e2e/test_edit_e2e_gpu.py — 图像编辑端到端真机冒烟（P1 Qwen-Image 2.1 Edit）

⚠️ **真 GPU 用例**：加载 Qwen-Image-2.1 int8_convrot（~7.3GB）+ qwen3vl_8b（~9.4GB），
单次编辑实测峰值显存 ~13GB（Windows 共享显存兜底）、耗时 ~1 分钟。标记 ``slow``，
默认不跑。

用法（aki python，权重就位时）：
    python -m pytest tests/e2e/test_edit_e2e_gpu.py -m slow -q --timeout=900

跳过条件：无 GPU / 权重未就位 / 内核不支持 qwen_image21 —— 全部显式 skip 并给原因，
绝不静默假通过。

⚠️ 放在 ``tests/e2e/`` 的原因：该目录被 pyproject ``norecursedirs`` 排除，**不进主
pytest 收集面**。若放 ``tests/`` 下，本用例在无 GPU 的 CI 上会产生一条新的 skip ——
CI 的 junit skip 台账是「精确相等」门禁（.github/ci_skip_ledger.*.json），多一条
skip 就红。手动跑法见上方用法。
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.integrated_app.config import get_config
from app.integrated_app.native import edit_executor

pytestmark = [pytest.mark.slow, pytest.mark.integration]

EDIT_ENGINE = "qwen_image_edit_native"
EDIT_TIMEOUT_S = 900.0


def _reference_image(tmp_path: Path) -> Path:
    """生成一张确定性的参考图（纯 PIL 画一个色块组合，避免依赖已有产物）。"""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (768, 512), (235, 238, 242))
    d = ImageDraw.Draw(img)
    d.rectangle([240, 150, 520, 430], fill=(60, 90, 170))  # 蓝色主体
    d.ellipse([320, 90, 440, 210], fill=(232, 190, 160))  # 肤色圆
    fp = tmp_path / "edit_reference.png"
    img.save(fp)
    return fp


def _skip_reason() -> str | None:
    import torch

    if not torch.cuda.is_available():
        return "无 CUDA 设备"
    ok, reason = edit_executor.check_kernel_support()
    if not ok:
        return f"内核不支持: {reason}"
    cfg = get_config()
    eng = cfg.models.engines.get(EDIT_ENGINE)
    if eng is None:
        return f"config.models.engines 缺少 {EDIT_ENGINE}"
    if "edit" not in (eng.supported_features or []):
        return f"{EDIT_ENGINE} 未声明 edit 能力"
    from app.integrated_app.config_models import resolve_engine_model_paths

    missing = [
        k for k, v in resolve_engine_model_paths(eng, cfg.models, cfg.project_root).items() if not Path(v).is_file()
    ]
    if missing:
        return f"权重未就位: {missing}"
    return None


@pytest.fixture()
def edit_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    reason = _skip_reason()
    if reason:
        pytest.skip(reason)
    import os

    os.environ["IMM_FAKE_ENGINE"] = "0"  # 真引擎
    # aki python 未装 CLIP 包 → 带参考图的请求会走 fail-closed 被拦。
    # 本用例验证的是编辑链路本身，且 aki 环境本就装不了 CLIP，故测试内把
    # 图检降级为放行（真实部署仍保持 fail-closed，不受影响）。
    # 注意：generation_service 在函数体内 import，必须 patch 其来源模块。
    import app.integrated_app.security.content_filter as cf
    from app.integrated_app.app_server import create_app

    monkeypatch.setattr(cf, "filter_image_generation", lambda prompt, image_path, fail_closed: (True, ""))

    with TestClient(create_app()) as c:
        # CSRF Double-Submit：在 client 层统一挂 token（与 test_generate_routes 同一写法）
        csrf_tok = c.get("/api/health").headers.get("X-CSRF-Token", "")
        if csrf_tok:
            c.headers["X-CSRF-Token"] = csrf_tok
        yield c


def test_edit_image_end_to_end(edit_client: TestClient) -> None:
    """参考图 + 编辑指令 → 任务完成 → 输出图片落盘且可读。"""
    from PIL import Image

    cfg = get_config()
    outputs_root = Path(cfg.project_root) / cfg.output.base_dir
    ref_dir = outputs_root / "uploads_test"
    ref_dir.mkdir(parents=True, exist_ok=True)
    ref_file = _reference_image(ref_dir)
    ref_rel = str(ref_file.relative_to(outputs_root)).replace("\\", "/")
    # PathGuard 白名单口径：**项目根相对路径**（带 outputs/ 前缀）
    ref_guarded = f"outputs/{ref_rel}"

    resp = edit_client.post(
        "/api/generate",
        json={
            "positive_prompt": "把蓝色主体改成鲜红色，其余保持不变",
            "negative_prompt": "",
            "engine_name": EDIT_ENGINE,
            "edit_mode": True,
            "reference_image_path": ref_guarded,
            "edit_resolution": 512,
            "steps": 4,
            "cfg": 1.0,
            "seed": 7,
            "batch_size": 1,
            "width": 512,  # 编辑路径忽略 width/height（尺寸由参考图推导）
            "height": 512,
        },
    )
    assert resp.status_code == 200, resp.text[:300]
    task_id = resp.json()["task_id"]

    deadline = time.time() + EDIT_TIMEOUT_S
    detail = {}
    while time.time() < deadline:
        detail = edit_client.get(f"/api/tasks/{task_id}").json()
        if detail.get("status") in ("completed", "failed", "cancelled"):
            break
        time.sleep(3)

    assert detail.get("status") == "completed", f"编辑任务未成功: {detail}"
    outputs = [o["path"] for o in (detail.get("outputs") or []) if o.get("output_type") == "original"]
    assert outputs, f"无输出图片: {detail}"

    for rel in outputs:
        fp = outputs_root / rel
        assert fp.is_file(), f"输出文件缺失: {rel}"
        with Image.open(fp) as im:
            assert im.size[0] > 0 and im.size[1] > 0
