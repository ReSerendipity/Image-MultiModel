"""
clean_launch.py — 启动加固（附录 E1）

安全启动 Image MultiModel 应用：
- 自动检测并使用 WinPython（不使用系统 Python）
- 检查 Python 版本
- 检查依赖
- 设置环境变量
- 启动 uvicorn
"""

import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

# ── 项目根目录 ───────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = Path(__file__).resolve().parent


# ── WinPython 自动检测 ───────────────────────────────────────
# 安全约束（M-05）：禁止硬编码其它项目 / 系统的绝对解释器路径。
# 这类硬编码既破坏可移植性，又可能被攻击者以同名路径劫持。仅允许：
# 项目内 .venv / 项目内 WPy64-*，以及用户通过环境变量
# IMM_EXTRA_PYTHON_DIRS 显式指定的目录。
def find_winpython():
    """查找带 CUDA 的 python.exe 路径（仅限项目内 + 用户显式指定）。"""
    # 0. 项目本地 .venv（隔离模型环境，最高优先，避免回落共享全局 Python）
    venv_py = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    if venv_py.exists():
        return str(venv_py)
    # 1. 项目内的 WinPython
    for wpy_dir in PROJECT_ROOT.glob("WPy64-*"):
        py = wpy_dir / "python" / "python.exe"
        if py.exists():
            return str(py)
    # 2. 用户显式指定的额外解释器目录（环境变量，绝不使用硬编码绝对路径）
    extra = os.environ.get("IMM_EXTRA_PYTHON_DIRS", "")
    for raw in extra.split(os.pathsep):
        raw = raw.strip()
        if not raw:
            continue
        cand = Path(raw)
        if cand.is_dir():
            py = cand / "python.exe" if cand.name != "python.exe" else cand
            if py.exists():
                try:
                    code = subprocess.run(
                        [str(py), "-c", "import torch; assert torch.cuda.is_available()"],
                        capture_output=True,
                        timeout=30,
                    )
                    if code.returncode == 0:
                        return str(py)
                except Exception:
                    pass
    # 3. 回退到当前 Python（如果上面都不存在）
    return sys.executable


# ── 环境变量（附录 E1）──────────────────────────────────────
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("MODELSCOPE_OFFLINE", "1")
os.environ.setdefault("COMFYUI_DISABLE_UPDATE_CHECK", "1")
# PyTorch 内存管理
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
# 工作目录
os.chdir(str(PROJECT_ROOT))


def check_python_version():
    """检查 Python 版本 ≥ 3.10"""
    if sys.version_info < (3, 10):
        print(f"[ERROR] Python 3.10+ required, got {sys.version}")
        sys.exit(1)
    print(f"[OK] Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
    print(f"[OK] Python executable: {sys.executable}")


def check_dependencies():
    """检查关键依赖。

    M-05：缺失时不再「pip install <未锁定包名>」（可能拉取最新/被投毒版本），
    而是从项目锁定的 requirements-lock.txt（版本钉死）统一安装。
    """
    required = {
        "fastapi": "fastapi",
        "uvicorn": "uvicorn",
        "pydantic": "pydantic",
        "yaml": "pyyaml",
        "aiohttp": "aiohttp",
    }
    missing = []
    for module, package in required.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(package)

    if missing:
        lock = PROJECT_ROOT / "requirements-lock.txt"
        print(f"[WARN] Missing packages: {', '.join(missing)}")
        if lock.exists():
            print(f"[INFO] 从锁定文件安装（版本钉死，避免投毒）: {lock}")
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(lock)])
        else:
            print(f"[ERROR] 依赖缺失且未找到锁定文件 {lock}，请先运行 install.bat/install.sh")
            print("        或手动执行: pip install -r requirements-lock.txt")
            sys.exit(1)
        print("[OK] Dependencies installed")
    else:
        print("[OK] All dependencies present")


def check_config():
    """检查 config.yaml 存在"""
    cfg_path = PROJECT_ROOT / "config.yaml"
    if not cfg_path.exists():
        print(f"[ERROR] config.yaml not found at {cfg_path}")
        sys.exit(1)
    print("[OK] config.yaml found")


def check_workflows():
    """检查工作流文件存在（目录缺失时自动创建，不再致命）。

    WHY 改为非致命：``workflows/`` 存放用户自己的 ComfyUI 工作流，随仓库
    分发不了——参考 JSON 已在清理提交中删除，目录当前未被 git 跟踪，也不在
    ``.gitignore`` 内（2026-09-25 修正：旧注释断言的 ``/workflows/`` 排除规则不存在，
    ``git check-ignore`` 无匹配），
    干净 checkout 后该目录必然不在磁盘。而 ``Performance Benchmarks`` 与 ``Startup
    Smoke`` 两个 job 都要启动应用 —— 结果每次推送都卡在这一行
    ``sys.exit(1)`` 上，CI 恒定报红，与被测代码质量毫无关系。

    目录本就按需生成，缺失时创建它即可，不构成启动阻断条件。
    """
    wf_dir = PROJECT_ROOT / "workflows"
    if not wf_dir.exists():
        # CI / 全新克隆环境：目录不随仓库分发（参考 JSON 已删、当前未被跟踪），按需创建
        wf_dir.mkdir(parents=True, exist_ok=True)
        print(f"[WARN] workflows/ directory not found, created: {wf_dir}")
    jsons = list(wf_dir.glob("*.json"))
    if not jsons:
        print("[WARN] No workflow JSON files found")
    else:
        for j in jsons:
            print(f"[OK] Workflow: {j.name}")


def check_models():
    """检查模型目录"""
    for d in ["text", "unet", "vae"]:
        p = PROJECT_ROOT / d
        if p.exists():
            files = list(p.rglob("*.safetensors"))
            print(f"[OK] {d}/ — {len(files)} model(s)")
        else:
            print(f"[WARN] {d}/ not found")


def check_winpython():
    """检查 WinPython 环境"""
    wpy_path = find_winpython()
    if "WPy64" in wpy_path:
        print(f"[OK] WinPython detected: {wpy_path}")
    else:
        print(f"[WARN] WinPython not found, using: {wpy_path}")
    return wpy_path


def find_available_port(start_port: int, host: str = "127.0.0.1", max_attempts: int = 200) -> int:
    """从 start_port 向上查找第一个可用的端口（bind 探测）。

    对齐 TTS_MultiModel / Seedvr2 的自动换端口策略：默认端口被占用时
    向上顺延，避免启动直接报 [Errno 10048] address already in use。

    Args:
        start_port: 起始端口号（含）。
        host: 绑定主机，默认 127.0.0.1。
        max_attempts: 最大尝试次数，默认 200（最多尝试到 start_port+199）。

    Returns:
        int: 找到的第一个可用端口。

    Raises:
        OSError: 指定范围内未找到可用端口。
    """
    import socket

    for offset in range(max_attempts):
        candidate = start_port + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, candidate))
                return candidate
            except OSError:
                continue
    raise OSError(f"在 {start_port}~{start_port + max_attempts} 范围内未找到可用端口")


def launch():
    """启动应用"""
    print("\n" + "=" * 60)
    print("  Image MultiModel — Launching...")
    print("=" * 60)

    check_winpython()
    check_python_version()
    check_dependencies()
    check_config()
    check_workflows()
    check_models()

    # 确保数据目录存在
    for d in ["data", "outputs", "logs"]:
        (PROJECT_ROOT / d).mkdir(parents=True, exist_ok=True)

    print("\n[INFO] Starting uvicorn...")
    print(f"[INFO] Project root: {PROJECT_ROOT}")
    print(f"[INFO] App dir: {APP_DIR}")

    # 添加 app 到 sys.path
    sys.path.insert(0, str(APP_DIR))

    # 启动
    import uvicorn

    from integrated_app.config import load_config

    cfg = load_config()

    # 端口被占用时自动向上顺延，避免启动失败（对齐 TTS_MultiModel / Seedvr2）
    host = cfg.server.host
    actual_port = find_available_port(cfg.server.port, host)
    if actual_port != cfg.server.port:
        print(f"[INFO] 端口 {cfg.server.port} 已被占用，自动切换到可用端口 {actual_port}")

    # 根据配置自动打开浏览器
    auto_open = getattr(cfg.server, "auto_open_browser", False)
    if auto_open:

        def _auto_open_browser(ip, port, timeout=300):
            url = f"http://{ip}:{port}"
            print(f"[INFO] 等待服务就绪后将自动打开浏览器: {url}")
            start_time = time.time()
            while time.time() - start_time < timeout:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(1)
                    if sock.connect_ex((ip, int(port))) == 0:
                        break
                time.sleep(1)
            else:
                print(f"[WARN] 等待服务就绪超时（{timeout}s），未自动打开浏览器")
                return
            time.sleep(2)
            print(f"[INFO] 服务就绪，正在弹出网页: {url}")
            webbrowser.open(url)

        threading.Thread(
            target=_auto_open_browser,
            args=(host, actual_port),
            daemon=True,
            name="auto-open-browser",
        ).start()

    uvicorn.run(
        "integrated_app.app_server:app",
        host=host,
        port=actual_port,
        workers=cfg.server.workers,
        reload=False,
    )


if __name__ == "__main__":
    # 如果找到的 CUDA Python 与当前运行的不是同一个，则重启为它
    wpy = find_winpython()
    if os.path.abspath(wpy) != os.path.abspath(sys.executable):
        print(f"[INFO] Relaunching with CUDA Python: {wpy}")
        os.execv(wpy, [wpy, __file__])
    else:
        launch()
