"""
conftest.py — pytest 共享 fixture 与路径注入

对应 TEST_AUDIT_REPORT P0-3: 消除 9 个测试文件的 sys.path.insert 重复
"""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# ── 统一路径注入 ────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = PROJECT_ROOT / "app"
TESTS_DIR = Path(__file__).resolve().parent

# 避免重复插入
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
# 使 `from factories import ...`（tests/factories.py）可直接导入
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

# ── 无 GPU 测试环境默认启用假引擎 ──────────────────────────
# 测试/CI 环境无可用 GPU（亦无 comfy/torch 推理栈），所有「提交生成 → worker 处理」
# 的集成测试必须走 FakeEngine 才能可复现。生产环境不设置该变量，绝不生效。
# 统一在此置默认，避免各测试文件各自 setdefault 的竞态导致 batch_size 被 VRAM
# 调度器随机钳制（生成结果不确定 / flaky）。
os.environ.setdefault("IMM_FAKE_ENGINE", "1")


# ── 共享 fixture ────────────────────────────────────────────
@pytest.fixture
def project_root():
    """项目根目录"""
    return PROJECT_ROOT


@pytest.fixture
def tmp_db(tmp_path):
    """临时 HistoryDB 实例（自动关闭）"""
    from integrated_app.history_db import HistoryDB

    db = HistoryDB(tmp_path / "test_history.db")
    yield db
    db.close()


@pytest.fixture
def path_guard(project_root):
    """PathGuard 实例（4 个白名单目录）"""
    from integrated_app.security.path_guard import PathGuard

    return PathGuard(
        allowed_base_dirs=["outputs/", "data/", "workflows/", "model/"],
        project_root=str(project_root),
    )


# ── 环境感知：原生引擎栈不可用时跳过相关测试 ──────────────────
def _torch_is_functional() -> bool:
    """检测当前环境是否具备可用的 PyTorch（部分环境仅有占位/损坏的 torch）。"""
    try:
        import torch

        return bool(hasattr(torch, "tensor") and hasattr(torch, "__version__"))
    except Exception:  # pragma: no cover - 导入异常即视为不可用
        return False


def _comfy_available() -> bool:
    """检测原生引擎运行所需的 comfy 扩展是否可用。

    两项缺一不可：pip 包 ``comfy_aimdo``（comfy 运行扩展）+ 仓库内 vendored
    ``comfy_kernel/comfy`` 源码。v1.3.0 发版期修复：comfy_kernel 被 gitignore
    不随检出分发，此前只查 pip 包导致 CI（装了 torch+comfy_aimdo）上
    tests/native/ 下依赖 vendored 源码的测试（test_vlm_engine_comfy_path 等）
    以 RuntimeError 爆炸而非优雅跳过（Release 工作流 tag 推送实测）。
    """
    try:
        import comfy_aimdo  # noqa: F401

    except Exception:  # pragma: no cover - 依赖缺失
        return False
    vendored = Path(__file__).resolve().parents[1] / "comfy_kernel" / "comfy"
    return vendored.is_dir()


_TORCH_OK = _torch_is_functional()
_COMFY_OK = _comfy_available()
_ENGINE_OK = _TORCH_OK and _COMFY_OK

# 依赖原生引擎栈（torch + comfy）的测试文件：环境不可用时整体跳过
_NATIVE_TEST_FILES = {
    "test_preprocessors.py",
    "test_generate_routes.py",
    "test_forward_batch_and_cancel.py",
    "test_forward_path_api.py",
}


def pytest_collection_modifyitems(config, items):
    """原生引擎栈（torch / comfy_aimdo）不可用时，跳过依赖它的测试。

    仅作用于缺失可用 PyTorch 或 comfy 扩展的环境；在完整环境上
    ``_ENGINE_OK`` 为 True，本钩子不生效，全部测试照常执行。
    """
    if _ENGINE_OK:
        return
    skip_marker = pytest.mark.skip(reason="原生引擎栈不可用（缺 PyTorch 或 comfy 内核源码），跳过引擎相关测试")
    for item in items:
        name = Path(item.path).name
        # tests/native/ 整目录都依赖原生引擎栈或本机权重（v1.3.0 修复：
        # 此前按文件名前缀过滤，test_vlm_engine_comfy_path / 各引擎
        # weight-point-at-real-files 等文件漏网，CI 无 vendored 源码/权重时炸红）
        norm_path = str(item.path).replace("\\", "/")
        in_native_dir = "/tests/native/" in norm_path
        if in_native_dir or name.startswith("test_native_") or name in _NATIVE_TEST_FILES:
            item.add_marker(skip_marker)


# ── 反模式 #3 防护：消除测试间共享全局状态（对应测试体系评估 P2-8）────
@pytest.fixture(autouse=True)
def _restore_fake_engine_env():
    """每个用例结束后把 IMM_FAKE_ENGINE 恢复到会话默认值。

    根因（2026-09-30 CI run 36656528279 实测）：多个测试文件用
    ``os.environ["IMM_FAKE_ENGINE"] = "1"`` 后 ``finally: os.environ.pop(...)``，
    而本文件用 ``setdefault`` 提供全局默认 —— 直接 pop 会**把默认一起丢掉**。
    xdist 按文件分 worker，某个 worker 里先跑完这些文件，后续文件（如
    ``test_engine_routes.py``）就会去构建真 NativeEngine，在无 comfy/torch
    的 CI 环境里直接失败：本地单文件跑绿、CI 整轮红。

    这里做一次全局兜底：无论哪个用例怎么折腾这个变量，用例结束后都回到
    会话默认值；用例内部仍可按需临时改动。修测试文件本身（回填原值）是
    第一道防线，本夹具是第二道，二者互补。
    """
    default = os.environ.get("IMM_FAKE_ENGINE", "1")
    yield
    os.environ["IMM_FAKE_ENGINE"] = default


@pytest.fixture(autouse=True)
def _clear_dependency_overrides():
    """每个测试结束后重置 app.dependency_overrides，避免跨测试状态污染。

    说明：路由测试沿用模块级 TestClient（函数级 `with TestClient` 会触发
    lifespan 关闭竞争导致偶发 hang，故不强行改为函数级）。此处通过自动清理
    FastAPI 的依赖覆盖注册表，消除"共享全局状态"这一主要污染面。
    """
    from integrated_app.app_server import app

    yield
    app.dependency_overrides.clear()


# ── 反模式 #3 防护（续）：重置限流器命中桶 ───────────────────────
@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    """每个用例前后清空限流器命中计数，避免模块级共享 client 累积请求

    耗尽 per-IP 限流预算（infer 30/min）使后续用例误判 429。生产运行时
    本夹具同样运行，但测试间隔内无请求累积，对行为无影响。

    注意：测试环境 sys.path 同时包含 ``PROJECT_ROOT`` 与 ``PROJECT_ROOT/app``，
    同一份 ``rate_limit.py`` 可能被加载为 ``integrated_app.middleware.rate_limit``
    与 ``app.integrated_app.middleware.rate_limit`` 两个模块对象（取决于首个
    导入方的写法）。运行中的中间件用哪一个，重置就必须瞄准同一个。这里两个
    名字都尝试重置，确保无论 app 以哪种形式加载都能清空对应桶。
    """
    import sys

    def _reset_all():
        for modname in (
            "integrated_app.middleware.rate_limit",
            "app.integrated_app.middleware.rate_limit",
        ):
            mod = sys.modules.get(modname)
            if mod is not None and hasattr(mod, "reset_rate_limiters"):
                mod.reset_rate_limiters()

    _reset_all()
    yield
    _reset_all()


# ── 反模式 #4 防护：config.yaml 文件快照恢复（防测试写回污染真实配置）──
@pytest.fixture(autouse=True, scope="session")
def _protect_config_yaml_file():
    """测试/CI 环境：保护项目根 config.yaml 不被测试写回污染（根治收尾时
    ``git checkout -- config.yaml`` 的被迫操作）。

    根因：``_isolate_history_db_for_tests`` 把内存配置单例的 ``db_path`` /
    ``cache_dir`` 重定向到临时目录（``imm-hist-<pid>-``），但
    ``config_routes.save_config(cfg)``（配置保存 API，config_path=None 时写
    ``_config_path`` = 真实 config.yaml）会在测试调用该端点时把临时路径落盘；
    生产不受影响（不加载本 conftest），但测试会话结束后真实配置被污染。

    修复：会话开始时对 config.yaml 做字节快照，结束时与当前内容比对，不一致
    即恢复快照。任何测试对真实配置文件的写入都被回滚——测试修改真实配置属于
    反模式，回滚即期望行为。快照在 fixture 实例化时采集（早于任何测试代码），
    恢复在最后一个测试之后（session 级 finally）。
    """
    cfg_file = PROJECT_ROOT / "config.yaml"
    snapshot = cfg_file.read_bytes() if cfg_file.exists() else None
    yield
    if snapshot is not None:
        try:
            if cfg_file.read_bytes() != snapshot:
                cfg_file.write_bytes(snapshot)
        except OSError:  # noqa: S110 - 只读/占用等极端情况不阻断会话收尾
            pass


# ── 反模式 #4 防护：隔离 HistoryDB，消除 xdist 跨 worker 共享 DB 的锁竞争 ──
@pytest.fixture(autouse=True, scope="session")
def _isolate_history_db_for_tests():
    """测试/CI 环境：将应用 HistoryDB 重定向到每进程（每 xdist worker）临时目录。

    根因：``create_app()`` 复用全局配置单例，其 ``output.history.db_path`` 默认
    为 ``data/history.db``（项目根下的固定相对路径）。pytest-xdist 多 worker 并
    行时，每个 worker 进程都打开同一个物理文件，并发写入触发 SQLite
    ``database is locked``；生成 worker 捕获该异常后将任务标记为 ``failed``，
    于是 ``generation_completed_total`` 不增（``test_generation_lifecycle_counters_
    increment`` 偶发失败），``test_run_profile_completes_serial`` 也偶发 sqlite 锁
    失败。这都是共享 DB 竞争的表象，而非被测逻辑缺陷。

    修复：按 worker 进程（pid）分配独立临时目录，使各 worker 的 HistoryDB 互不
    干扰；worker 内测试串行执行，无锁竞争。生产不加载本 conftest，且 db_path 仅
    在测试期被覆盖，生产行为不受影响。

    注意：刻意不使用 pytest 的 tmp_path/tmp_path_factory —— Windows 上其
    ``pytest-current`` 符号链接清理会抛 PermissionError [WinError 5]（与被测代码
    无关，见 test_capacity_baseline._make_root 的同类规避）。
    """
    from integrated_app.config import get_config as _get_config_top

    try:
        # app 代码全部使用相对导入：经 `app.integrated_app.*` 导入时，
        # 其配置单例与顶层 `integrated_app.*` 身份是**两个独立模块对象**
        # （实测 `top is pkg == False`）。conftest 必须同时重定向两份单例，
        # 否则 create_app()（走 app. 身份）仍指向真实 data/history.db，
        # xdist 多 worker 并发初始化即触发 `database is locked`
        # （2026-09-05 CI 33957856101 复现，见 FIX_LOG #1）。
        from app.integrated_app.config import get_config as _get_config_pkg
    except ImportError:  # 兜底：仅存在单一导入身份的环境
        _get_config_pkg = None

    cfgs = []
    for _get in (_get_config_top, _get_config_pkg):
        if _get is None:
            continue
        try:
            cfgs.append(_get())
        except Exception:  # noqa: BLE001 - 任一身份不可用时不阻塞其余身份
            continue
    assert cfgs, "至少一个导入身份的配置单例必须可用"

    originals = []
    # 维护 cron 用环境开关禁用（见 app_server.history_cleanup_cron）：
    # load_config(path) 会整体替换配置单例，仅改 cleanup_cron 字段可能被冲掉。
    original_disable_env = os.environ.get("IMM_DISABLE_MAINTENANCE_CRON")
    os.environ["IMM_DISABLE_MAINTENANCE_CRON"] = "1"
    worker_tmp = Path(tempfile.mkdtemp(prefix=f"imm-hist-{os.getpid()}-"))
    for cfg in cfgs:
        originals.append(
            (
                cfg,
                cfg.output.history.db_path,
                cfg.output.uploads.cache_dir,
                cfg.output.history.cleanup_cron,
            )
        )
        cfg.output.history.db_path = str(worker_tmp / "history.db")
        # uploads 目录重定向为第二道防线（cron 已关，正常不会扫到真实上传文件）
        cfg.output.uploads.cache_dir = str(worker_tmp / "uploads")
        cfg.output.history.cleanup_cron = ""

    def _redirect(cfg):
        """对任一 AppConfig 施加测试期重定向（幂等）。"""
        cfg.output.history.db_path = str(worker_tmp / "history.db")
        cfg.output.uploads.cache_dir = str(worker_tmp / "uploads")
        cfg.output.history.cleanup_cron = ""
        return cfg

    # ── 第二道防线：拦截「配置单例被整体替换」这条打穿路径 ──────────────
    # 上面只改了**当前**单例对象的字段。但 ``load_config()`` /
    # ``load_validated_config()`` / ``reload_config()`` 都会 ``global _config``
    # **整体替换**单例（见 app/integrated_app/config.py:151/156/323），
    # 替换后的新对象 db_path 回到默认 ``data/history.db``，本次重定向全部失效；
    # 之后同 worker 的 ``create_app()`` 就落回真实 data/history.db，
    # xdist 多 worker 并发初始化时 ``PRAGMA journal_mode=WAL`` 报
    # ``database is locked``（2026-09-11 CI 34562117669 复发）。
    # 2026-09-05 的修法只覆盖了「双导入身份」，没覆盖「单例被替换」这条路径，
    # 故此处换机制：包一层配置构造入口，对**每次**新产出的 AppConfig 重新施加
    # 同一份重定向，与单例是否被替换无关（幂等，不改变生产行为——生产不加载本
    # conftest）。
    patched: list[tuple[object, str, object]] = []
    for _mod_name in ("integrated_app.config", "app.integrated_app.config"):
        _mod = sys.modules.get(_mod_name)
        if _mod is None:
            continue
        for _fname in ("load_config", "load_validated_config"):
            _orig = getattr(_mod, _fname, None)
            if _orig is None:
                continue
            patched.append((_mod, _fname, _orig))

            def _make_wrapper(_orig_fn):
                def _wrapper(*args, **kwargs):
                    return _redirect(_orig_fn(*args, **kwargs))

                return _wrapper

            setattr(_mod, _fname, _make_wrapper(_orig))

    def _cleanup():
        shutil.rmtree(worker_tmp, ignore_errors=True)

    atexit.register(_cleanup)
    try:
        yield
    finally:
        for _mod, _fname, _orig in patched:
            setattr(_mod, _fname, _orig)
        for cfg, db_path, uploads_dir, cleanup_cron in originals:
            cfg.output.history.db_path = db_path
            cfg.output.uploads.cache_dir = uploads_dir
            cfg.output.history.cleanup_cron = cleanup_cron
        if original_disable_env is None:
            os.environ.pop("IMM_DISABLE_MAINTENANCE_CRON", None)
        else:
            os.environ["IMM_DISABLE_MAINTENANCE_CRON"] = original_disable_env
        _cleanup()
