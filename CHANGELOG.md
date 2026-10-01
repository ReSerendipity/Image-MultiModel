# Changelog

All notable changes to Image MultiModel will be documented in this file.

> **版本史说明（2026-09-15）**：2026-08-10 曾以 v2.0.0 发布，随后版本号重启为 1.x（1.1.0 → 1.2.2 现行基线，权威位 config.yaml）；远端 v1.5.0 / v1.5.1 tag 为 release-please 时代产物，经 2026-09-05 裁决不再作为版本基线、亦未收录于本 CHANGELOG。详见 docs/release-governance.md。

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

***

## \[Unreleased]

### Added

- **增量包 Ed25519 签名链（2026-09-11 收口）**：`scripts/package_app.py` 打包即对 `app-v{ver}.zip` 签 Ed25519（`.sig.ed25519`，复用完整性清单密钥对，零新依赖；`--no-sign` 调试逃生门）；`scripts/release_gate.py` gate-5 对每个增量包回验签。
- **CI 桌面增量包自动构建（2026-09-11 收口）**：`release.yml` 新增 `desktop-package` job（windows-latest）——清单门禁 → 私钥注入（Secret）→ 打包签名 → 验签 → 便携诊断 → 壳 `cargo check --locked` → 上传增量包三件套到 GitHub Release；壳完整 build 仍由本机发布流程执行。
- **桌面化分发（P1-3）**：Tauri v2 壳（`desktop/src-tauri`：单实例/托盘/崩溃自启/窗口状态记忆/隐藏控制台/增量更新器）；NSIS 安装器（`desktop/installer/setup.nsi`：分卷解压/运行中进程自动终止/卸载清理）；分层定案（`docs/桌面分发分层定案-20260910.md`）；增量应用包打包（`scripts/package_app.py`）；Release 分卷切片（`scripts/split_release_volumes.py`，900MB/卷 + SHA256SUMS 全覆）；版本单一来源闸门（`scripts/check_config_refs.py` 扩展，config.yaml 权威位一致性校验）。
- **发布质量（P2）**：安装环境诊断（`scripts/diag_portable_verify.py`：cryptography→清单→验签→自检→enforce 五环节）；发布门禁五步（`scripts/release_gate.py`：构建→静态→测试→签名→发布物）；闭源编译评估（`docs/闭源编译评估-Cython-pyd-20260910.md`，含公开声明）。
- **服务端支撑**：`app_server.run()` 支持 `--host/--port`（桌面壳传入空闲端口）。
- **Flux.2 Klein 9B（fp8）原生引擎（2026-09-30 接入）**：`config.yaml → models.engines.flux2_klein_native`，`backend: native`；权重三件套（UNet 8.46GB + Qwen3-8B TE 8.07GB + Flux.2 VAE）以 junction 挂载到 `pretrained_models/`；实机 RTX 5070 Ti 12GB preflight 512²/4 步出图验证通过（含 offload 28~112s）。采样器与调度器不再硬编码 Z-Image 常量：`GenerationConfig` / `EngineConfig` 新增 `sampler`/`scheduler` 字段，`native/executor.py` 按引擎配置下发，空值回退至原 Z-Image 默认；`latent_channels: 128` 与 `latent_downscale: 16` 必须显式写入配置（实测 `model.latent_format` 为 None，缺省会误回退至 Z-Image 的 16/8）。接入前自检工具 `scripts/preflight_flux2_klein.py` 可作为后续新引擎的标准模板。
- **能力演进 roadmap 入库（2026-09-30）**：`docs/roadmap/README.md` 将 P0/P1 已落地能力与 P2 后续可选项（多引擎、VLM 看图聊天）切片可追踪；`P2-multi-engine.md` 与 `P2-vlm-chat.md` 分别目标引擎与 VLM 权重选定、实施步骤与验收标准写入仓库。

### Security

- **桌面端完整性**：壳健康检查解析 `/api/system/health` 的 `security.integrity`（含 manifest_signed），完整性失败在托盘展示篡改告警。
- **更新签名**：独立生成 Tauri 更新签名密钥对（私钥 `desktop/src-tauri/tauri.key` gitignore + 离线备份，公钥入库并写入 `tauri.conf.json` pubkey）。
### Fixed

- **修复会话级 HistoryDB 隔离 fixture 因装饰器被注释吞掉而从未生效**：`tests/conftest.py` 里 `# ── 反模式 #4 防护 … ──@pytest.fixture(autouse=True, scope="session")` 把装饰器写进了注释行，`_isolate_history_db_for_tests` 退化为普通函数、pytest 不收集 → 各 xdist worker 直连真实 `data/history.db`，并发 `PRAGMA journal_mode=WAL` 报 `sqlite3.OperationalError: database is locked`（CI 34562117669 复发）。现装饰器独占一行；并对 `load_config`/`load_validated_config` 加包装，使配置单例被整体替换后重定向依然生效；新增 `tests/test_history_db_isolation.py` 锁定契约（FIX_LOG #2）

- **修复 xdist 跨 worker 的 `database is locked` 竞态**：conftest 会话级 HistoryDB 隔离此前只重定向顶层 `integrated_app.config` 单例，而 `create_app()` 经 `app.integrated_app.*` 相对导入使用**另一份配置单例**（两身份为独立模块对象），重定向失效导致多 worker 并发初始化真实 `data/history.db` 时加锁失败；现同时重定向两份单例（CI 33957856101 复现，FIX_LOG #1）

- **修复** **`config.yaml`** **中失效的** **`bin/`** **路径残留**：`security.integrity_selfcheck.manifest_file` 与 `i18n.locale_dir` 由不存在的 `bin/integrated_app/...` 改为 `app/integrated_app/...`（bin→app 重命名后未同步，会导致完整性自检清单与语言词表无法定位）

- **补齐配置引用门禁脚本** `scripts/check_config_refs.py`：AST 解析 `config_models.py` 提取配置模型字段，扫描 `app/` 代码引用，对账 `config.yaml` security 段「声明即消费」，修复 `tests/test_config_refs_gate.py` 三例因缺脚本而恒失败的问题

- **修复版本漂移测试**：`tests/test_config.py::test_app_config_builds` 断言由过期的 `2.0.0` 改为 `1.2.2`（对齐 `config.yaml`）

- **根治 config.yaml 测试污染（2026-09-11 收口）**：conftest 新增会话级字节快照保护——此前配置保存 API（`config_routes.save_config(cfg)` 无路径参数）会把测试期内存重定向的临时路径（`imm-hist-<pid>`）写回真实 `config.yaml`；现任何测试对真实配置文件的写入均在会话结束被回滚（全量 pytest 后 config.yaml SHA256 不变）

- **修复 mypy scripts 2 个预存类型错误（2026-09-11 收口）**：`fix_encoding_diag.py` 的 `line` 未初始化 None 索引；`post_deploy_smoke.py` 的 `get_json` 返回类型未收窄（`mypy scripts` → Success 35 文件）

- **UI/UX 审计 P1 修复（2026-10-01）**：
  - 历史中文搜索不可用——`history_db.py` FTS5 `unicode61` 不索引 CJK，含中文/长度 <3 的查询自动降级为 LIKE，并用 rowid 读取避免结果集与 tasks 行映射漂移；FTS5 MATCH 语法错误（引号/括号等）自动回退 LIKE，任何输入不再导致搜索页 500；新增 `tests/test_history_db_search.py` 锁定中文/英文/混合关键词与分页行为
  - 分享按钮无反应——`app.js` 重写 `shareCurrent()`，先拉取当前任务产物与提示词，拼装为剪贴板文本后 `navigator.clipboard.writeText`，失败回退到 `prompt` 方案
  - 无引擎就绪预检——`genBtn` 提交前自动 `POST /api/engine/preflight`，引擎未就绪时弹 appConfirm 提示先加载，避免默默入队后卡住

- **UI/UX 审计 P2/P3 修复（2026-10-01）**：顶部栏悬停、设置下拉、关于面板社交链接 SVG 图标与版权文案、历史筛选新增「已取消」、状态 `st_*` 五语言全补齐 + `tr()` 未知键回退剥前缀、抽屉标题与提示全 i18n、EULA 隐私描述改为「提示词与生成结果均不出设备」、新增应用内 `appConfirm()` 模态全面替换原生 `window.confirm/alert`、手风琴序号 02→01、「模块」→「功能」、a11y aria-label/title 补齐（种子/默认随机骰、批量按钮、复选/单选、图库 chip、表格表头）、VRAM 状态口径统一为「可用 x.x / xx.x GB」、LoRA 滑杆选择器修正为栈内 `input[type=range]` 统一绑定、`histPurge` 无可清理项自动禁用、FAB 与 AI 对话发送按钮按品牌色统一

- **UI/UX 审计 P4 修复（2026-10-01）**：
  - 深水区 i18n 补齐——五语言字典新增约 130 键，覆盖设置面板（引擎与模型/运行/保留策略/配置 全部 label + option）、关于面板正文（副标题/描述/作者版本协议/6 项 feature/版权行）、批量面板（dropzone/每行 batch/16 倍数/网格笛卡尔积 hint/批次估算/任务队列 + 动态估算行内嵌 `<b>` 数字）、高级参数抽屉全部 label（基础/LoRA/SeedVR2/对比+显存预留/输出）、历史详情（任务详情/尺寸·seed/耗时·时间/重绘/预设/ZIP）、历史筛选下拉与 Purge/Clear、状态抽屉、预设面板、查看器标题、队列 popover 与状态行；动态文案全部走 `tr()`（包括分享/预设保存/删除确认的 appConfirm 消息与按钮）
  - 右下角控件堆叠修复——`#agent-fab` 从 `bottom:22px` 上移至 `86px`，避开队列胶囊 `bottom:44~78px` 区间；`#agent-drawer` 同步上移至 `150px`；`.viewer` z-index 从 120 提至 9993（压过 FAB 9990，`app-confirm` 10000 仍最高），实测查看器打开时 FAB 被完整覆盖

### Changed

- **完整性清单会签流程规范化（2026-10-01）**：`generate_integrity_manifest.py` 仅重生成 SHA256，未签名清单在 enforce 模式下仍会拒启；标准两步变为「generate → sign」，已写入 `docs/roadmap/P2-multi-engine.md` 与 `docs/GOTCHAS.md`。
- **默认引擎** **`z_image_turbo_native`** **的** **`workflow_file`** **置空**：引擎推理由代码/native 构建，不再引用不存在的 `workflows/Z_image_turbo.json`；`workflows/` 收敛为用户自放 ComfyUI 工作流的参考目录（`.gitignore` 排除，启动时自动重建空目录）

- **新增根级** **`AGENTS.md`**（家族自进化协议 v1.3）：补齐此前缺失的项目级 Agent 规范，并明确 `comfy_kernel/AGENTS.md` 为 vendored 上游 ComfyUI 文件、非本项目 AGENTS

### Removed

- **停用 release-please 自动发版**：删除 `.github/workflows/release-please.yml`、`release-please-config.json`、`.release-please-manifest.json`（用户裁决，与 `docs/release-governance.md`「config.yaml 顶层 version 为唯一权威版本位 + 手动打 tag 发布」的明文政策对齐）。v1.5.0 / v1.5.1 为该机制时代的历史产物，原地保留不再延续；后续发布走 `release.yml`（tag 驱动 / workflow_dispatch），版本位三处（config.yaml + AGENTS.md + CHANGELOG）人工同步

***

## \[1.2.2] - 2026-08-14

### Fixed

- **修复原生引擎 worker 不消费任务**（`task_queue.py`）：`asyncio.wait_for(queue.get(), timeout=1.0)` 在该运行环境下超时不触发导致 worker 永久挂起、任务永远 pending。改为 `get_nowait()` + `asyncio.sleep(0.2)` 轮询取任务，彻底避开 `wait_for` 超时机制

- **修复原生引擎 latent 参数错误**（`native/executor.py`）：Z-Image 使用 FLUX AE，latent 应为 **16 通道 / 8 倍下采样**（原代码误用 SD3 的 4 通道 / 8 倍下采样，导致输出分辨率减半为 384×384）。修正后恢复 768×768

- **修复 VAE 解码传参**（`native/executor.py`）：`vae.decode()` 应直接传 latent 张量，而非 `{"samples": ...}`（Comfy 的 `VAEDecode` 节点语义）

- **修复服务跑在 CPU 版 torch 上**：服务此前运行在 `torch 2.13.0+cpu`（无 CUDA），推理报 `Torch not compiled with CUDA enabled`。`bin/clean_launch.py` 的 `find_winpython()` 新增系统级 CUDA Python 候选（`C:\Python312`，torch 2.13.0+cu132），并修正重启逻辑（检测到非当前 CUDA Python 即切换）

### Changed

- **模型来源切换为 portable（便携独立运行）**：`config.yaml → models.model_source_mode` 由 `shared`（指向本机外部 ComfyUI-aki-v3 模型目录）改为 `portable`，模型放入项目内 `pretrained_models/`，无任何外部链接 / junction，可作便携包独立运行

- **unet 改用 FP8 模型**：`config.yaml` 引擎 `z_image_turbo_native` 的 unet 指向 `Z-image_turbo-bf16/zimageTurboNSFWByStable_2602NSFWFP8.safetensors`（FP8，约 5.9GB），`default_precision` 同步设为 `fp8`，出图更快

- **补装原生引擎依赖**：`einops`、`torchsde`、`comfy-aimdo==0.4.13`、`comfy-kitchen==0.2.30`（源自 `references/ComfyUI/requirements.txt` 与本机 ComfyUI-aki-v3）

***

## \[1.2.1] - 2026-08-14

### Fixed

- **修复** **`index.html`** **mojibake 乱码**：文件中文曾因多次 GBK/UTF-8 往返编码被破坏（页面出现 `?` 乱码），且自动修复脚本用 `errors="replace"` 进一步丢失 1118 个字符。已从干净的 git 提交 `014edd3` 重建全量中文，恢复为纯 UTF-8（0 乱码字符）

### Changed

- **前端 UI 优化**：顶部栏图标按钮添加文字标签（主题、颜色、字体、关于、设置、模型、语言），移除冗余的「全部 / Native」引擎过滤选项，引擎选择简化为直接显示引擎列表

- **彻底脱离 ComfyUI 前端残留**：移除「释放显存」按钮（`freeVramBtn`，对应已删除的 `/engine/free` 端点）、「ComfyUI 后端」状态面板（local/gpu-cluster · 8188）、状态栏 `CONN: LOCAL:8188`、关于面板「统一驱动 ComfyUI」副标题与「驱动本地 ComfyUI」特性条目

- **引擎引用统一为** **`z_image_turbo_native`**：硬编码引擎菜单 / `engineSelect` / 预设默认引擎 / 快照与状态栏文本统一为 `Z-Image Turbo（原生）`

***

## \[1.2.0] - 2026-08-13

### Added

- **原生进程内引擎（双后端模式）**（MASTER\_PLAN M7）：

  - `bin/integrated_app/native/` 包：`source.py`（复用 `references/ComfyUI` + aki-v3 自定义节点源码，`sys.path` 注入）、`executor.py`（复用 `comfy.sd` / `comfy.samplers` 完成 加载→CLIP编码→采样→VAE解码）、`engine.py`（`NativeEngine` 实现 `ImageEngine` Protocol，输出经 `PathGuard` 校验落盘 + DCT 水印 + 缩略图）

  - `lora.py` / `seedvr.py` / `compares.py` / `vram.py` / `preview.py`：原生引擎 Phase 3 能力扩展

  - `config.yaml` 新增 `z_image_turbo_native`（`backend: native`），无需外部 ComfyUI 进程即可在进程内出图

- **后端模式切换**：`routes/engine_routes.py` 按引擎配置的 `backend` 字段分发 `ComfyEngine` / `NativeEngine`；前端引擎菜单顶部支持「全部 / ComfyUI / 原生」过滤

- **动态 LoRA 栈**：`engine_interface.py` 的 `GenerationConfig` 新增 `lora_stack` 动态字段（不局限于旧 6 层，空时回退旧字段）

- **原生引擎安全测试**：`tests/test_native_security.py`（`_save_outputs` 路径穿越攻击向量：`../`、绝对路径、恶意引擎名，全部被 `PathGuard` 拒绝）

### Security

- 原生引擎输出落盘路径经 `PathGuard` 校验，验证 `../` 穿越 / 绝对路径 / 恶意引擎名注入向量全部拒绝

***

## \[1.1.0] - 2026-08-13

### Added

- **CLIP 安全内容检测**（全功能实施指南 P0 任务1）：

  - `security/content_filter.py`：基于 CLIP 的图片安全检测 + 关键词提示词过滤

  - CLIP 模型懒加载，未安装时优雅降级为纯关键词过滤

  - `routes/safety_routes.py`：`POST /api/safety/check-prompt` + `POST /api/safety/check-image`

  - 集成到 `/api/generate` 生成流程，违规提示词自动拦截

  - 27 个不安全关键词覆盖（NSFW / 暴力 / 仇恨 / 自残 / 毒品 / 武器等）

- **Fooocus 风格提示词扩展**（全功能实施指南 P0 任务2）：

  - `prompt_expander.py`：智能提示词扩写系统

  - 6 种预设风格（cinematic / anime / photorealistic / oil\_painting / digital\_art / fantasy）

  - 自动质量增强（masterpiece / best quality / ultra detailed / 8k）+ keyword:weight 加权语法

  - 5 种场景智能推荐（portrait / landscape / still\_life / architecture / fantasy）

  - `routes/prompt_routes.py`：`POST /api/prompt/expand` + `POST /api/prompt/suggest` + `GET /api/prompt/styles` + `GET /api/prompt/scenes`

- **ControlNet 预处理器系统**（全功能实施指南 P0 任务3）：

  - `preprocessors/canny.py`：Canny 边缘检测（自适应百分位阈值）

  - `preprocessors/midas.py`：MiDaS 深度估计（DPT\_Large 模型懒加载）

  - `preprocessors/openpose.py`：OpenPose 人体姿态检测（controlnet\_aux 懒加载）

  - `PreprocessorProtocol` 协议 + 注册表模式，支持扩展自定义预处理器

  - `routes/preprocess_routes.py`：`POST /api/preprocess/canny` + `POST /api/preprocess/depth` + `POST /api/preprocess/pose` + `GET /api/preprocess/list`

  - Base64 图片输入输出，无需文件 I/O

- **i18n 新增 9 个后端错误 key**（5 种语言同步）：`content_blocked` / `prompt_expand_success` / `prompt_suggest_success` / `preprocess_canny_success` / `preprocess_depth_success` / `preprocess_pose_success` / `preprocess_failed` / `preprocess_not_available`

- **新增依赖**：`clip-anytorch>=2.0.0`（CLIP 安全检测）、`controlnet-aux>=0.0.9`（OpenPose 预处理）

### Security

- 生成流程集成 CLIP 内容安全过滤，违规提示词自动拦截（400 响应）

- 安全检测路由的图片路径过 PathGuard 校验

***

## \[2.0.0] - 2026-08-10

### Added

- **ComfyUI 工作流引擎架构**：Engine / Client / Workflow 三层抽象，支持多后端负载均衡

  - `comfy/client.py`：HTTP + WebSocket 双通道客户端，自动重连（≤3 次指数退避）

  - `comfy/engine.py`：ComfyEngine 实现 ImageEngine Protocol（load / unload / infer\_txt2img / cancel）

  - `comfy/workflow.py`：WorkflowManager Patcher 6 步（深拷贝→模式切换→link 重连→widgets patch→batch chunk→节点校验）

- **内置工作流**：Z-Image Turbo（高速低显存）

  - 每引擎一份 Schema YAML（`comfy/schemas/`），节点 ID 严格对齐 `widgets_values` 下标

- **VRAM 预检 + 精度推荐系统**：推理前估算显存需求（×1.5 系数），推荐 FP8/FP16 精度与 batch chunk 大小

- **批量任务队列**：异步单 Worker 串行 + SSE 实时推送 + 任务取消 + 断点恢复

  - batch>100 时每 100 张自动落盘 checkpoint，崩溃重启自动续跑

- **预设管理系统**：SQLite 存储，支持 CRUD + 导入导出 + 一键应用回填

- **历史记录系统**：SQLite（WAL + FTS5 全文检索），支持搜索 / 筛选 / 分页 / 批量删除 / ZIP 导出 / 标签

- **DCT 频域数字水印**：输出图像自动嵌入 `product_id + task_id + timestamp`，可溯源验证

  - `scripts/verify_watermark.py` CLI 验证工具

- **安全加固体系**：

  - PathGuard 路径防护（规范化校验，防 `../` 路径穿越）

  - CSRF 中间件（Token 头注入，防御跨站请求伪造）

  - Rate Limit 限流（推理 / 上传 / 全局三维度）

  - Integrity Manifest 完整性校验（SHA256 校验关键安全模块）

  - Basic Auth / API Token 鉴权（可配置开关）

- **i18n 五种语言**：中文 / 繁体中文 / 英文 / 日文 / 韩文，前端 JS 字典 + localStorage 持久化 + 防闪烁

- **8 种布局方案 Figma 原型对比**（`prototypes/figma-refactor/layout-compare/`）：

  - a-creative / b-split / c-collapsible / d-drawer / e-wizard / f-pipeline / g-master-detail / h-minimal

  - 最终选定 d-drawer（抽屉式）布局：移动端适配好、操作路径短、空间利用率高

- **GPU 状态监控**：SSE `gpu_status` 事件实时推送显存使用情况

- **实时预览**：WS `b_preview` → base64 → SSE `comfy_preview` → 前端采样中实时预览

- **释放显存功能**：`POST /api/engine/free` → ComfyUI `/free` → SSE 刷新

- **历史清理 cron**：`config.yaml` 配置 cron 表达式 + `keep_days` 保留天数

- **日志轮转**：RotatingFileHandler，按大小自动轮转保留 N 份

- **辅助脚本体系**（8 个）：

  - `benchmark.py`：性能基准（首页 / 历史 / health / SSE 四指标）

  - `check_wcag.py`：WCAG 无障碍检查

  - `generate_integrity_manifest.py`：完整性清单生成

  - `migrate_outputs.py`：输出目录结构迁移（旧平铺 → engine/date）

  - `pack_portable.ps1`：便携包 7 步打包

  - `setup_symlinks.ps1`：模型符号链接设置（shared 模式 Junction 维护）

  - `test_portable_mode.py`：便携模式验证

  - `verify_watermark.py`：水印 CLI 验证

- **测试体系**：40+ 个测试文件，287 passed / 0 failed

  - Hypothesis 属性测试、Factory Boy 测试工厂、PathGuard 攻击测试、SQL 注入测试

  - Playwright E2E（POM 页面对象模型 + 4 个场景）

- **Pre-commit 钩子**：ruff + format + trailing-whitespace + check-yaml 等 6 项

- **CI 工作流**：lint + test（3.12/3.13 矩阵）+ SAST（pip-audit）+ smoke 测试

- **Docker 支持**：Dockerfile + docker-compose.yml 双配置

- **WCAG AA 无障碍**：对比度校准（accent #6b5bb8 5.51:1 / primary #7c5fd6 4.70:1）

- **双模式模型路径**：`shared`（与 ComfyUI 共享）/ `portable`（项目自包含）

### Changed

- 从 v1.x 单体架构重构为 ComfyUI 客户端 / 服务端分离架构

- 前端从 Jinja2 + HTMX 多页模板改为单页融合版（SPA + REST + SSE）

- 历史存储从 JSON 文件改为 SQLite（WAL + FTS5）

- HTTP 客户端从 httpx 改为 aiohttp（与 ComfyUI WebSocket 生态兼容）

- 主题色从薰衣草紫 #8b7bd8 调整为 #6b5bb8（WCAG AA 对比度达标）

- 覆盖率门槛设为 75%（fail\_under=75）

### Security

- 加入 PathGuard 路径防护，修复路径穿越漏洞（14 类攻击全拒绝）

- 加入 CSRF 中间件，防御跨站请求伪造

- 加入 Rate Limit 限流，防止滥用

- 加入 Integrity Manifest，关键安全模块 SHA256 校验

- 加入 DCT 频域水印，输出图像可溯源

- 默认仅绑定 `127.0.0.1`，config.yaml host 字段只读

### Fixed

- `task_queue.py:97` f-string 语法错误（缺左花括号导致应用无法启动）

- 水印 DCT 嵌入 uint8 回绕问题（MIN\_Q 2→8、新增 MAX\_Q=16、引擎裁剪 \[0,255]）

- 集成测试 8 个 `UnraisableExceptionWarning` 清零

- outputs/ 旧平铺 PNG 迁移到 engine/date 目录结构

- `logging.handlers` 导入缺失导致 RotatingFileHandler 不工作

- i18n 新增 18 个 `btn_*` 键（5 语），消除界面裸键

- WCAG AA 对比度不达标色值修复

***

## \[1.0.0] - 2026-08-08

### Added

- 项目初始骨架：config.yaml + 2 个工作流 JSON + pretrained\_models 目录结构

- MASTER\_PLAN.md 总体规划文档（M0\~M10 里程碑分解）

- PRD.md 产品需求文档

- 基础测试：test\_config + test\_workflow（39 例）
