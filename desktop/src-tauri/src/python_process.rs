use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use anyhow::{Result, anyhow};
use serde::Serialize;
use tauri::{AppHandle, Emitter};
#[cfg(windows)]
use std::os::windows::process::CommandExt;

use crate::port_manager::find_free_port;

/// 请求 Python 服务本机优雅关闭（桌面端 B-5）。
/// 用裸 TcpStream 发 HTTP POST，避免为 reqwest 引入 blocking 依赖。
fn request_graceful_shutdown(port: u16) -> bool {
    use std::io::{Read, Write};
    use std::net::TcpStream;
    use std::time::Duration;

    let Ok(addr) = format!("127.0.0.1:{port}").parse::<std::net::SocketAddr>() else {
        return false;
    };
    let Ok(mut stream) = TcpStream::connect_timeout(&addr, Duration::from_millis(800)) else {
        return false;
    };
    let req = format!(
        "POST /api/system/shutdown HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
    );
    if stream.write_all(req.as_bytes()).is_err() {
        return false;
    }
    let _ = stream.set_read_timeout(Some(Duration::from_millis(1500)));
    let mut buf = [0u8; 128];
    let _ = stream.read(&mut buf);
    true
}

/// Python 进程状态
#[derive(Debug, Clone, Serialize)]
pub enum PythonStatus {
    Stopped,
    Starting,
    Running,
    Crashed,
}

/// Python 子进程管理器
pub struct PythonProcess {
    child: Option<Child>,
    port: u16,
    runtime_dir: PathBuf,
    app_dir: PathBuf,
    log_dir: PathBuf,
    status: PythonStatus,
    restart_count: u32,
    max_restarts: u32,
}

impl PythonProcess {
    pub fn new(runtime_dir: PathBuf, app_dir: PathBuf, log_dir: PathBuf) -> Self {
        Self {
            child: None,
            port: 0,
            runtime_dir,
            app_dir,
            log_dir,
            status: PythonStatus::Stopped,
            restart_count: 0,
            max_restarts: 3,
        }
    }

    /// 启动 Python 子进程
    pub fn start(&mut self) -> Result<u16> {
        // 找空闲端口
        let port = find_free_port()?;
        self.port = port;

        // 确定 Python 可执行文件路径
        let python_exe = self.runtime_dir.join("python.exe");
        if !python_exe.exists() {
            return Err(anyhow!("Python 可执行文件不存在: {}", python_exe.display()));
        }

        // 启动入口：本项目无 start_portable.py，以模块方式启动
        // `python -m integrated_app.app_server --host 127.0.0.1 --port <port>`
        let pkg_dir = self.app_dir.join("integrated_app");
        if !pkg_dir.is_dir() {
            return Err(anyhow!("应用代码目录不存在: {}", pkg_dir.display()));
        }

        // 确保日志目录存在
        std::fs::create_dir_all(&self.log_dir)?;
        let log_file = self.log_dir.join(format!(
            "python_{}.log",
            chrono::Local::now().format("%Y%m%d_%H%M%S")
        ));
        let log_writer = std::fs::File::create(&log_file)?;

        // 启动子进程
        let child = Command::new(&python_exe)
            .arg("-m")
            .arg("integrated_app.app_server")
            .arg("--host")
            .arg("127.0.0.1")
            .arg("--port")
            .arg(port.to_string())
            .current_dir(&self.app_dir)
            .stdout(Stdio::from(log_writer.try_clone()?))
            .stderr(Stdio::from(log_writer))
            .env("PYTHONNOUSERSITE", "1")
            .env("PYTHONUNBUFFERED", "1")
            .creation_flags(0x08000000) // CREATE_NO_WINDOW
            .spawn()?;

        self.child = Some(child);
        self.status = PythonStatus::Starting;
        log::info!("Python 进程已启动，PID={}, 端口={}", self.child.as_ref().unwrap().id(), port);

        Ok(port)
    }

    /// 标记为运行中
    pub fn mark_running(&mut self) {
        self.status = PythonStatus::Running;
        self.restart_count = 0;
    }

    /// 检查进程是否存活
    pub fn is_alive(&mut self) -> bool {
        if let Some(child) = &mut self.child {
            match child.try_wait() {
                Ok(None) => true,
                Ok(Some(status)) => {
                    log::warn!("Python 进程已退出，状态={}", status);
                    false
                }
                Err(_) => false,
            }
        } else {
            false
        }
    }

    /// 尝试重启（受 max_restarts 限制）
    pub fn try_restart(&mut self) -> Result<bool> {
        if self.restart_count >= self.max_restarts {
            self.status = PythonStatus::Crashed;
            return Ok(false);
        }
        self.restart_count += 1;
        log::info!("正在重启 Python 进程（第 {}/{} 次）", self.restart_count, self.max_restarts);
        self.stop()?;
        self.start()?;
        Ok(true)
    }

    /// 停止 Python 进程（Windows 下杀整棵进程树：uvicorn/torch 会 spawn 子进程，
    /// 只杀直接子进程会留下孤儿持有 app/ 文件句柄，导致更新换载 rename 失败）
    pub fn stop(&mut self) -> Result<()> {
        if let Some(mut child) = self.child.take() {
            let pid = child.id();
            #[cfg(windows)]
            {
                // B-5: 先请求本机 /api/system/shutdown 优雅关闭（停队列、卸载模型、
                // 关历史库），最多等 6 秒；未退出才 taskkill /F 强杀兜底（幂等）。
                let shutdown_sent = if self.port > 0 {
                    request_graceful_shutdown(self.port)
                } else {
                    false
                };
                if shutdown_sent {
                    log::info!("已请求 Python 服务优雅关闭（port={}）", self.port);
                    for _ in 0..60 {
                        match child.try_wait() {
                            Ok(Some(_)) => break,
                            Ok(None) => std::thread::sleep(std::time::Duration::from_millis(100)),
                            Err(_) => break,
                        }
                    }
                }
                // taskkill /T 级联终止子进程树；失败再回退 kill()
                let ok = Command::new("taskkill")
                    .args(["/PID", &pid.to_string(), "/T", "/F"])
                    .stdout(Stdio::null())
                    .stderr(Stdio::null())
                    .status()
                    .map(|s| s.success())
                    .unwrap_or(false);
                if !ok {
                    let _ = child.kill();
                }
            }
            #[cfg(not(windows))]
            {
                let _ = child.kill();
            }
            let _ = child.wait();
            log::info!("Python 进程树已停止（根 PID={pid}）");
        }
        // 兜底：扫描并终止所有属于本应用的 python 进程（父进程已退出的孤儿也一并清除，
        // 否则它们会持有 app/ 目录句柄/工作目录，导致更新换载 rename app 失败 os error 32）
        #[cfg(windows)]
        {
            let app_dir = resolve_app_dir();
            let marker = format!("{0}\\integrated_app.app_server", app_dir.display());
            // PowerShell -like 通配：反斜杠是字面字符，单引号按 PowerShell 规则双写转义
            let esc = marker.replace('\'', "''");
            let ps = format!(
                "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object {{ $_.CommandLine -like '*{esc}*' }} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }}"
            );
            let _ = Command::new("powershell")
                .args(["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", &ps])
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .status();
            log::info!("已扫描清除本应用残留 python 进程");
        }
        self.status = PythonStatus::Stopped;
        Ok(())
    }

    pub fn port(&self) -> u16 {
        self.port
    }

    pub fn status(&self) -> PythonStatus {
        self.status.clone()
    }
}

/// 全局共享的 Python 进程管理器
pub struct PythonState {
    pub process: Mutex<PythonProcess>,
}

/// 启动事件负载
#[derive(Serialize, Clone)]
struct StartupStatus {
    message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<String>,
}

/// 向发送启动状态
pub fn emit_startup_status(app: &AppHandle, message: &str, error: Option<String>) {
    let _ = app.emit("startup-status", StartupStatus {
        message: message.to_string(),
        error,
    });
}

/// 解析运行时目录：优先侧载 runtime，开发模式回退项目 .venv，再退系统 Python
pub fn resolve_runtime_dir(app_dir: &Path) -> PathBuf {
    // 1. 打包后（分层定案布局）：安装根下的 runtime/（app/ 的兄弟目录）
    //    v1.3.0 修复：壳 1.0.0 只认 app/runtime/，与桌面分发分层定案 §2 的
    //    <安装根>/runtime/ 布局不符，导致装后 Python 永远无法启动（P1，
    //    v1.3.0 阶段3 真机安装模拟实测发现）。
    if let Ok(exe) = std::env::current_exe() {
        let sibling = exe.parent().unwrap().join("runtime");
        if sibling.join("python.exe").exists() {
            return sibling;
        }
    }

    // 1b. 打包后（历史布局）：应用目录下的 runtime/
    let bundled = app_dir.join("runtime");
    if bundled.join("python.exe").exists() {
        return bundled;
    }

    // 2. 开发模式 A：app_dir 即项目根（.venv 在其下）
    let dev_local = app_dir.join(".venv").join("Scripts");
    if dev_local.join("python.exe").exists() {
        return dev_local;
    }

    // 2b. 开发模式 A'：app_dir 为 <root>/app（本项目开发布局），.venv 在上一级
    if let Some(parent) = app_dir.parent() {
        let dev_local2 = parent.join(".venv").join("Scripts");
        if dev_local2.join("python.exe").exists() {
            return dev_local2;
        }
    }

    // 3. 开发模式 B：app_dir 为 exe_dir/app，.venv 位于上两级（历史布局）
    let dev_venv = app_dir
        .parent()
        .and_then(|p| p.parent())
        .map(|p| p.join(".venv").join("Scripts"));
    if let Some(venv) = dev_venv {
        if venv.join("python.exe").exists() {
            return venv;
        }
    }

    // 4. 回退：系统 PATH 中的 python
    PathBuf::from("python")
}

/// 解析应用代码目录
pub fn resolve_app_dir() -> PathBuf {
    // 1. 打包后：优先当前可执行文件目录下的 app/（要求含 integrated_app/ 包，
    //    避免把无 payload 的裸壳目录误判为应用根）。
    if let Ok(exe) = std::env::current_exe() {
        let bundled = exe.parent().unwrap().join("app");
        if bundled.join("integrated_app").is_dir() {
            return bundled;
        }
    }

    // 2. 开发模式：CARGO_MANIFEST_DIR 上溯到项目根（desktop/src-tauri → 项目根）
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .to_path_buf();
    // 本项目 Python 包位于 <root>/app/integrated_app（app 为命名空间包根）
    if root.join("app").join("integrated_app").is_dir() {
        return root.join("app");
    }
    if root.join("integrated_app").is_dir() {
        return root;
    }

    root
}
