# Image MultiModel

![Version](https://img.shields.io/badge/version-1.2.2-blue?style=for-the-badge) ![License](https://img.shields.io/badge/license-Apache2.0-green?style=for-the-badge) ![Python](https://img.shields.io/badge/python-3.10+-yellow?style=for-the-badge&logo=python&logoColor=white) ![GPU](https://img.shields.io/badge/GPU-NVIDIA%20CUDA-76B900?style=for-the-badge&logo=nvidia&logoColor=white) [![CI](https://github.com/ReSerendipity/Image_MultiModel/actions/workflows/ci.yml/badge.svg)](https://github.com/ReSerendipity/Image_MultiModel/actions) [![gitleaks](https://img.shields.io/badge/secret%20scan-gitleaks%20passing-0080FF?style=for-the-badge)](https://github.com/ReSerendipity/Image_MultiModel/actions/workflows/gitleaks.yml)

**Image MultiModel — 多模型 AI 图像生成平台：基于进程内原生引擎，复用 ComfyUI 源码接入 Z-Image Turbo / Qwen-Image 2.1 Edit / Flux.2 Klein 的「单页 Web UI」**

> **Image MultiModel** — A unified AI image generation platform powered by an in-process native engine (reusing local ComfyUI source) that hosts multiple diffusion backends: Z-Image Turbo for fast txt2img, Qwen-Image 2.1 Edit for instruction-driven image editing, and Flux.2 Klein 9B for high-quality photoreal txt2img — all fully decoupled from any external ComfyUI process.

---

参与贡献请遵循 [组织级贡献指南](https://github.com/ReSerendipity/.github/blob/main/CONTRIBUTING.md)（Conventional Commits + DCO 签名）。

## 界面预览

*浅色主题 — 生图工作台主页 / 高级参数 / 预设管理 / 历史记录 / 图片展示 / 批量模式*

> 界面截图：主页、高级参数、预设管理、历史记录、图片展示、批量模式共六张，可在线查看 [生图工作台演示页](https://reserendipity.github.io/Image_MultiModel/)。

---

## 功能亮点

| 特性 | 说明 |
|---|---|
| **原生进程内引擎** | 复用项目内 `comfy_kernel` 源码 + aki-v3 自定义节点，`sys.path` 注入后在同一进程内完成 加载→编码→采样→解码，**完全脱离外部 ComfyUI 进程** |
| **多引擎接入** | `config.yaml → models.engines.*` 声明式注册，同一 `NativeEngine` 框架下现内置 3 个引擎：`z_image_turbo_native`（默认）/ `qwen_image_edit_native`（编辑）/ `flux2_klein_native`（高质量），新引擎接入步骤见 `docs/roadmap/P2-multi-engine.md` |
| **Z-Image Turbo 工作流** | 内置 Z Image Turbo（阿里通义）高速文生图工作流，支持六层 LoRA 叠加、SeedVR2 超分、Eses 双图对比、显存预留 |
| **Qwen-Image 2.1 Edit** | 指令化图像编辑（支持参考图与透明图），需 Qwen Research License 授权方可商用（本项目默认非商用） |
| **显存预检** | 推理前自动估算 VRAM 需求，推荐精度（FP8/FP16）与 batch chunk 大小 |
| **批量任务队列** | 异步任务队列 + SSE 实时推送，支持批量生成、任务取消、断点恢复 |
| **预设管理** | 可保存常用参数组合为预设，一键加载复用 |
| **历史记录** | SQLite 历史数据库，支持搜索、筛选、分页、结果预览 |
| **DCT 数字水印** | 输出图像自动嵌入频域水印，包含 product_id + task_id + timestamp，可溯源 |
| **安全加固** | PathGuard 路径防护、CSRF 中间件、Rate Limit 限流、任务签名完整性校验 |
| **多语言界面** | 内置中文、繁体中文、英文、日文、韩文五种语言 |

---

## 环境要求

| 项目 | 要求 |
|---|---|
| **操作系统** | Windows 10/11（推荐） / Linux |
| **GPU** | NVIDIA CUDA GPU（推荐 8GB+ VRAM） |
| **Python** | **两种方式均可**：<br>• **推荐**：系统 Python 3.10+（3.12 最佳），需勾选 "Add Python to PATH"<br>• **备选**：内置 WinPython（`WPy64-312101/`），完全隔离无需系统 Python |
| **推理引擎** | 进程内原生引擎（复用项目内 `comfy_kernel` 源码），**无需外部 ComfyUI 进程** |

---

## 快速开始

### 方式一：使用系统 Python（推荐，节省磁盘空间）

1. 安装 [Python 3.10+](https://www.python.org/downloads/)，推荐 3.12.x。安装时**务必勾选 "Add Python to PATH"**
2. 验证安装：打开命令提示符（CMD），运行：
   ```bat
   python --version
   ```
   应显示类似 `Python 3.12.x`
3. 双击运行 **`install.bat`**（会自动检测系统 Python，安装 PyTorch CUDA 版 + 全部依赖）
4. **（可选）配置环境变量**
   - **新手**：跳过此步，默认便携模式即可使用
   - **高级用户**：复制 `.env.example` 为 `.env`，按需修改（`.env` 不入库，注意保管）
5. 确认模型文件已就位（存放于 `pretrained_models/`，portable 模式，完全自包含）
6. 双击运行：
   ```bat
   start.bat
   ```
7. 浏览器自动打开 Web UI（默认地址 `http://127.0.0.1:8288`）

> 💡 **优势**：进程内原生引擎复用项目内 `comfy_kernel` 源码，完全脱离外部 ComfyUI 进程，模型随 `pretrained_models/` 内置，可作便携包独立运行。

> 📌 **默认端口**：`8288`（可在 `config.yaml` → `server.port` 修改）。

> 📌 **模型路径模式**（`config.yaml` → `models.model_source_mode`）：
> - `portable`（当前默认）：模型路径指向项目内 `pretrained_models/` 目录，适合便携包模式（完全自包含，无外部链接）。
> - 切换模式后重启应用即可生效。

---

### 方式二：使用内置 WinPython（完全隔离，无需系统 Python）

1. 下载 [WinPython 3.12](https://github.com/winpython/winpython/releases) 并解压到项目根目录，确保：
   - `WPy64-312101/python/python.exe` 存在
2. 双击运行 **`install.bat`**（检测不到系统 Python 时会自动回退到 WinPython）
3. **（可选）配置环境变量**（参考上方说明）或确保模型已就位
4. 双击运行：
   ```bat
   start.bat
   ```

> 💡 `install.bat` / `start.bat` 会自动检测系统 Python。

---

### Docker

```bash
docker build -t image-multimodel .
docker run --gpus all -p 8288:8288 \
  -v ./pretrained_models:/app/pretrained_models \
  -v ./outputs:/app/outputs \
  image-multimodel
```

---

## 内置工作流

| 工作流 | 推荐显存 | 用途 | 引擎 key |
|---|---|---|---|
| **Z Image Turbo** | ~4GB+ | 高速文生图、实时预览 | `z_image_turbo_native` |
| **Qwen-Image 2.1 Edit** | ~11GB | 指令化图像编辑（支持参考图）、透明图 | `qwen_image_edit_native` |
| **Flux.2 Klein 9B (fp8)** | ~12GB（需 offload） | 高质量文生图（照片级），需 CPU/RAM 卸载 | `flux2_klein_native` |

---

## 原生进程内引擎

自 v1.2.0 起，平台**完全脱离外部 ComfyUI 进程**，统一走进程内原生引擎 `NativeEngine`：

- **不重新实现模型网络**：复用 `comfy_kernel/`（内含 `comfy/`、`comfy_extras/`、`comfy_execution/` 等顶层包）与 aki-v3 自定义节点源码。
- **`sys.path` 注入**：通过 `native/source.ensure_loaded()` 把该目录注入 `sys.path[0]`，在同一进程内调用 `comfy.sd` / `comfy.samplers` 完成推理。
- **统一引擎 key**：`config.yaml → models.engines.z_image_turbo_native`（`backend: native`）。

> ℹ️ 引擎与 comfy_kernel 的架构分工，公开硬约束子集见 [docs/AGENT_CONSTRAINTS.md](docs/AGENT_CONSTRAINTS.md)。

---

## 项目结构

```
Image_MultiModel/
├── app/                          # 应用入口与主程序
│   ├── clean_launch.py          # 启动清理 + 环境检测 + 启动 uvicorn
│   └── integrated_app/          # 主应用核心
│       ├── app_server.py        # FastAPI 应用 + 路由自动发现
│       ├── native/              # 进程内原生引擎（source/executor/engine/diffusers_engine/seedvr/lora/compares/vram/preview）
│       ├── routes/              # API 路由（config/engine/generate/governance/metrics/output/preprocess/preset/prompt/safety/system/task）
│       ├── security/            # PathGuard 路径防护 + 完整性校验（integrity_manifest.json）
│       ├── middleware/          # CSRF、限流、Request ID、安全头
│       ├── locales/             # i18n 五语言 JSON（zh/zh-tw/en/ja/ko）
│       ├── watermark.py         # DCT 频域不可感知数字水印
│       └── history_db.py / task_queue.py / gpu_utils.py
├── comfy_kernel/                 # vendored ComfyUI 内核（gitignored，不随仓库分发，克隆后按 docs/GPL_COMPLIANCE.md 自行获取）
├── workflows/                    # 工作流参考目录（gitignored，clean_launch 自动重建）
├── pretrained_models/            # 模型检查点存放（portable 模式，gitignored）
├── desktop/                      # 桌面分发：src-tauri（Tauri v2 壳）+ installer/setup.nsi（NSIS）
├── release/                      # 发布元数据（build_metadata.json、sbom.json）
├── scripts/                      # 打包/分卷/发布门禁/验签/水印等工具脚本
├── tests/                        # pytest + Hypothesis（含 e2e/integration/observability/release/smoke/frontend）
├── demo/                         # GitHub Pages 在线演示
├── config.yaml                   # 应用配置（版本权威位）
├── pyproject.toml                # 工具配置（pytest / ruff / coverage）
├── requirements.txt / requirements-lock.txt
├── start.bat / install.bat / start.sh / install.sh
└── README.md / CHANGELOG.md / THIRD_PARTY_NOTICES.md
```

---

## 技术栈

| 层级 | 技术 |
|---|---|
| 推理引擎 | 进程内原生引擎（复用本地 Comfy 源码）+ aki-v3 自定义节点 |
| 深度学习 | PyTorch (CUDA)、工作流：Z Image Turbo |
| Web 框架 | FastAPI + Uvicorn |
| 前端 | 单页应用（SPA，静态托管）+ SSE 实时推送 |
| 数据 | SQLite（历史）、YAML（配置）、JSON（工作流） |
| 安全 | PathGuard + CSRF + Rate Limit + Integrity Check + DCT Watermark |
| 工具链 | pytest + Hypothesis + factory-boy、ruff、coverage |

---

## 安全说明

- **网络绑定**：默认仅绑定 `127.0.0.1`，如需局域网访问请配置反向代理 + Basic Auth
- **路径防护**：PathGuard 对文件路径做规范化校验，防止 `../` 路径穿越读取任意文件
- **完整性**：`integrity_manifest.json` 对关键安全模块做 SHA256 校验
- **水印溯源**：所有输出图像自动嵌入 DCT 频域水印，可追溯 `product_id | task_id | timestamp`
- **CSRF**：表单提交 / POST 路由统一启用 CSRF Token 校验

---

## 高级功能

### 断点续跑

batch>100 时每 100 张自动落盘 checkpoint。应用崩溃后重启，未完成任务自动从断点续跑且无重复输出。

```bash
# checkpoint 存储位置
data/checkpoints/{task_id}.json
```

### 历史清理 cron

`config.yaml` 中 `output.history.cleanup_cron` 配置 cron 表达式（默认 `0 3 * * *` = 每天凌晨 3 点），`keep_days` 设置保留天数。启动时自动调度定时清理任务。

### 水印验证

```bash
# 验证输出图像中的水印
python scripts/verify_watermark.py outputs/z_image_turbo_native/20260814/xxx_original.png
```

---

## API 速查

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/health` | GET | 后端/引擎/队列/GPU/磁盘状态 |
| `/api/events` | GET (SSE) | 实时事件流（task_status / gpu_status / model_status / queue_status） |
| `/api/generate` | POST | 提交生成任务 |
| `/api/generate/batch` | POST | 批量生成 |
| `/api/engine/engines` | GET | 引擎列表 |
| `/api/engine/load` | POST | 加载引擎 |
| `/api/engine/unload` | POST | 卸载引擎 |
| `/api/config` | GET/PUT | 读取/保存配置 |
| `/api/tasks` | GET | 任务列表 |
| `/api/tasks/{id}/cancel` | POST | 取消任务 |
| `/api/agent/health` | GET | Agent LLM 大脑健康状态（本地 llama.cpp / 云 API，经 .env 配置） |
| `/api/agent/chat` | POST (SSE) | Agent 对话式生图（流式事件：tool_call / task_created / proposal / final / error；`mode` 三档 AUTO / CONFIRM / MANUAL_ASSIST） |
| `/api/agent/confirm` | POST | 双模式参数卡片确认/否决（`action=approve` 才真正入队，`reject` 直接丢弃） |

---

## 开发与测试

```bash
# 运行测试
python -m pytest -q

# 代码检查
python -m ruff check app tests

# 覆盖率
python -m pytest --cov=app/integrated_app --cov-report=term-missing

# E2E 测试（需先安装 Playwright）
pip install playwright pytest-playwright
playwright install chromium
python -m pytest tests/e2e -m e2e
```

---

## 模型许可说明

> 本表为**模型权重**的许可清单（项目代码为 Apache-2.0，见 [LICENSE](LICENSE)）。

### 非官方声明

- 本项目为**独立开源项目**，基于阿里通义实验室（Tongyi-MAI）开源模型 **Z-Image-Turbo**（Apache-2.0）构建，与阿里巴巴集团及通义品牌**无隶属关系**，并非通义官方出品。
- "Z-Image" 为阿里通义实验室的官方模型品牌名，本项目中仅作**描述性引用**以说明所集成的引擎，不暗示本项目的官方身份或获得官方背书。
- 项目内置的 SeedVR2 超分组件同为第三方集成，相关归属与免责说明见 [SeedVR2 项目声明](https://github.com/ReSerendipity/SeedVR2-lite)。

| 模型 | 引擎 key | 权重许可 | 商用 | 说明 |
|---|---|---|---|---|
| Z-Image Turbo（阿里通义） | `z_image_turbo_native` | Apache-2.0 | ✅ 可商用 | 默认引擎 |
| Qwen-Image 2.1（阿里通义） | `qwen_image_edit_native` | Qwen Research License | ❌ 仅限非商业 | 编辑引擎；商用需向千问团队另行申请 |
| FLUX.2 Klein 9B（Black Forest Labs） | `flux2_klein_native` | FLUX Non-Commercial | ❌ 仅限非商业 | 4B 变体为 Apache-2.0，9B/fp8/NVFP4 均为非商用 |
| SeedVR2（字节跳动，超分组件） | —（工作流内置） | Apache-2.0 | ✅ 可商用 | 见 NOTICE |

## 许可证

本项目采用 [Apache License 2.0](LICENSE) 开源协议。

---

## 桌面版（Windows）

> 🚧 **开发中**：Windows 桌面版正在开发，尚未正式发布。

桌面版将提供安装器与自动更新；正式发布后可从 [GitHub Releases](https://github.com/ReSerendipity/Image_MultiModel/releases) 下载获取，届时在本节补充安装与使用说明。
