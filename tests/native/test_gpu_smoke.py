"""tests/native/test_gpu_smoke.py — GPU 路径最小冒烟（MLOps M1 补验）。

补齐历史缺口：此前 tests/native/ 下 5 个测试全部是「离线接线事实」断言，
torch/CUDA 在 pytest 路径上零覆盖。本文件在 GPU 可用时跑真实 torch 算子，
在 CPU CI 上 GPU 用例自动 skip（不飘红），CPU 可跑的用例照常通过。

覆盖：
- torch.cuda.is_available() / 设备名 / 算力（sm_120 Blackwell）
- 一次 GPU matmul + 显存峰值读数（证明 CUDA kernel 真能跑）
- native.vram.get_gpu_memory_info() 返回合理值（pynvml/torch 双路兜底）
- native 关键模块在装好 torch 后能 import（engine / vram / source）
- preprocessors.canny 真跑一张合成图（CPU，无需 GPU）
"""

from __future__ import annotations

import numpy as np
import pytest

torch = pytest.importorskip("torch", reason="torch 未安装")
CUDA_AVAILABLE = torch.cuda.is_available()

requires_cuda = pytest.mark.skipif(not CUDA_AVAILABLE, reason="无 CUDA GPU，跳过")


# ── 1. torch / CUDA 真 sanity ─────────────────────────────────
@requires_cuda
def test_torch_cuda_available_and_device() -> None:
    assert CUDA_AVAILABLE
    name = torch.cuda.get_device_name(0)
    cap = torch.cuda.get_device_capability(0)
    assert cap[0] >= 7, f"算力 {cap} 过低，现代扩散模型一般需要 sm_70+"
    assert isinstance(name, str) and name, "GPU 名应为非空字符串"


@requires_cuda
def test_gpu_matmul_runs_and_reports_vram_peak() -> None:
    """真跑一次 GPU matmul，并读出峰值显存——证明 CUDA kernel 真能执行。"""
    torch.cuda.reset_peak_memory_stats()
    a = torch.randn(2048, 2048, device="cuda", dtype=torch.float32)
    b = torch.randn(2048, 2048, device="cuda", dtype=torch.float32)
    c = a @ b
    torch.cuda.synchronize()
    assert c.shape == (2048, 2048)
    peak_mb = torch.cuda.max_memory_allocated() / (1024**2)
    assert peak_mb > 50, f"峰值显存异常低: {peak_mb:.1f} MB"
    del a, b, c
    torch.cuda.empty_cache()


# ── 2. native.vram 真读 GPU 显存 ─────────────────────────────
@requires_cuda
def test_vram_get_gpu_memory_info_returns_real_values() -> None:
    from integrated_app.native.vram import get_gpu_memory_info

    total_gb, used_gb = get_gpu_memory_info()
    assert total_gb is not None, "GPU 可用时 total_gb 不应为 None"
    assert used_gb is not None, "GPU 可用时 used_gb 不应为 None"
    assert 8.0 < total_gb < 80.0, f"消费卡 total={total_gb:.1f}GB 异常"
    assert 0.0 <= used_gb < total_gb, f"used={used_gb:.1f}GB 不合理"


# ── 3. native 关键模块在装好 torch 后能 import ────────────────
def test_native_core_modules_import_with_torch_installed() -> None:
    """装 torch 后，native 核心模块应能 import 干净（过去 CPU CI 走不到这里）。"""
    import integrated_app.native.engine as eng_mod  # noqa: F401
    import integrated_app.native.source as src_mod  # noqa: F401
    import integrated_app.native.vram as vram_mod  # noqa: F401

    assert callable(vram_mod.get_gpu_memory_info)
    assert hasattr(src_mod, "_default_comfy_root")


# ── 4. preprocessors.canny 真跑合成图（CPU，不需要 GPU）──────
def test_canny_preprocessor_runs_on_synthetic_image() -> None:
    """Canny 边缘检测：左黑右白图应在中线附近检出边缘。"""
    pytest.importorskip("cv2", reason="opencv 未安装")
    from integrated_app.preprocessors.canny import CannyPreprocessor

    img = np.zeros((256, 256, 3), dtype=np.uint8)
    img[:, 128:, :] = 255
    out = CannyPreprocessor().process(img)
    assert out.shape == (256, 256)
    assert out.dtype == np.uint8
    edge_cols = np.where(out.any(axis=0))[0]
    assert len(edge_cols) > 0, "左右分界处应检出边缘"
    assert out.sum() < out.size * 255 * 0.5, "边缘图不应几乎全白"


def test_canny_rejects_empty_image() -> None:
    from integrated_app.preprocessors.canny import CannyPreprocessor

    with pytest.raises(ValueError):
        CannyPreprocessor().process(np.zeros((0, 0, 3), dtype=np.uint8))
