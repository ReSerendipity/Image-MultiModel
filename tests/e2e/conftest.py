"""
tests/e2e/conftest.py — Playwright E2E 测试公共 fixture

对应 REMAINING_TASKS_REPORT B7: Playwright E2E 落地
对应 N3: 截图比对/视觉回归工具基础设施

P2-5 改进：添加跨浏览器配置（Chromium + Firefox）
"""

from __future__ import annotations

import os

import pytest

try:
    import pytest_playwright  # noqa: F401

    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


@pytest.fixture(scope="session")
def base_url():
    """应用基础 URL（支持环境变量覆盖）"""
    return os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8288")


@pytest.fixture(autouse=True)
def _preset_agreement(page):
    """预置「首次使用协议」同意状态（v1.3.0 发版期修复）。

    全新浏览器 profile 无 localStorage，base.html 的使用前须知浮层
    （z-index 9999）会挡住一切点击 → E2E 全线 click 超时（09-15 浮层上线后
    E2E 实际处于长期破损态）。add_init_script 必须在首次导航前注册。
    """
    page.context.add_init_script("try{localStorage.setItem('image_mm:agreement:v1','2026-09-15')}catch(e){}")
    yield


@pytest.fixture(scope="session")
def screenshots_dir(tmp_path_factory):
    """截图目录（视觉回归基础）"""
    d = tmp_path_factory.mktemp("screenshots")
    return str(d)


@pytest.fixture
def screenshot(page, screenshots_dir):
    """截图函数 fixture"""

    def _screenshot(name: str):
        path = os.path.join(screenshots_dir, f"{name}.png")
        page.screenshot(path=path)
        return path

    return _screenshot


# ── P2-5: 跨浏览器配置 ──────────────────────────────────────
# 默认使用 Chromium；切换 Firefox：BROWSERS=firefox python -m pytest tests/e2e
# 多浏览器矩阵：BROWSERS=chromium,firefox python -m pytest tests/e2e
#
# ⚠️ 坑（2026-09-01）：此处曾自定义 pytest_generate_tests 对 "browser_name" 做
# metafunc.parametrize()，与 pytest-playwright 插件自带的 browser_name 参数化
# 冲突，报 "duplicate parametrization of 'browser_name'"，导致 6 个 e2e 文件在
# 收集阶段全部 ERROR —— E2E 维度长期"静默不执行"。正确做法是复用官方
# --browser 选项，仅在本 hook 中把 BROWSERS 环境变量映射过去。
def pytest_addoption(parser):
    """注册 E2E 专用命令行选项。

    Args:
        parser: pytest 参数解析器，用于注册自定义选项。
    """
    parser.addoption(
        "--update-snapshots",
        action="store_true",
        default=False,
        help="重新生成视觉回归基线快照（tests/e2e/__snapshots__/）",
    )


def pytest_configure(config):
    """把 BROWSERS 环境变量映射到 pytest-playwright 的 --browser 选项。

    Args:
        config: pytest 全局配置对象，用于读取/写入命令行选项值。
    """
    if not HAS_PLAYWRIGHT:
        return
    # 命令行显式传 --browser 时以命令行为准，不被环境变量覆盖
    if config.getoption("browser", default=None):
        return
    browsers = [b.strip() for b in os.environ.get("BROWSERS", "chromium").split(",") if b.strip()]
    config.option.browser = browsers


# 如果 playwright 未安装，自动跳过所有 E2E 测试
if not HAS_PLAYWRIGHT:

    def pytest_collection_modifyitems(items):
        skip_marker = pytest.mark.skip(reason="pytest-playwright not installed")
        for item in items:
            item.add_marker(skip_marker)
