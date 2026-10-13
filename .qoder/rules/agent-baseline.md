---
paths:
  - "**/*"
---

# Image\_MultiModel — Agent 可分发基线约束（仓库跟踪层）

> 本文件随仓库分发（git 跟踪），是任何克隆 / CI 检出都能读到的**最小恒需约束集**。
> 更完整的治理文档（自进化协议、SOP、坑点累积、修订表）由维护者**本地保留**，未随仓库发布：
> 若工作区存在根 `AGENTS.md` 或 `docs/agents/` 下的细化文档，以它们为准；
> 冲突时的优先级：**代码与配置 > 本地 `AGENTS.md` > 本文件 > `README.md`**。
> 机器可验证的公开硬约束全文见 `docs/AGENT_CONSTRAINTS.md`（跟踪文件，随仓库分发）。

## 1. 🚫 禁区路径（禁止 AI 自动修改，必须人工确认）

- `comfy_kernel/` — vendored 上游 ComfyUI 源码，保持可与上游 diff 追踪；其目录内自带的
  上游 `AGENTS.md` 属该内核代码规范，不得删除 / 移动 / 改写。
- `pretrained_models/`、`model/` — 模型权重，误改导致推理静默劣化（改动需 SHA-256 复验）。
- `app/integrated_app/security/` — 安全边界模块，默认禁止自动修改。
- `release/`、`demo/assets/` — 发布元数据 / 演示产物，只通过构建与生成命令更新。
- `backups/` — 归档，只新增不修改。

## 2. ✅ 主验证命令（每组相关编辑后立即跑，勿累积）

- lint：`python -m ruff check app/ tests/`（格式化 `ruff format .`；全量 `pre-commit run --all-files`）
- type：`python -m mypy app/integrated_app`
- 测试 + 覆盖率：`pytest tests/ --cov=app/integrated_app --cov-report=term-missing --cov-fail-under=65 -q`
  （红线 65%，事实来源 `pyproject.toml` 的 fail_under；权威门禁由 **CI** 执行）
- push 前本地预检：`./precheck.ps1`（默认仅 lint/type、尽力而为；需本地覆盖率加 `-Full`）
- 文档路径引用完整性：`python scripts/check_spec_refs.py --self`
- 新克隆后启用钩子：`git config core.hooksPath .githooks`（或运行 `.githooks/install.sh`）

## 3. 🔌 入口、端口与调度

- 启动入口 `app/clean_launch.py`（或根 `start.bat` / `start.sh`），默认 `http://127.0.0.1:8288`。
- **只绑回环**：禁止 `0.0.0.0` 等全接口暴露；事实来源 `config.yaml` 的 `server.host` / `server.port`
  与 `app/integrated_app/config_models.py` 的 host 白名单校验器（非法值直接抛错）。
- 单 Worker 串行调度防 GPU OOM：`config.yaml` 的 `server.workers: 1`。

## 4. 🤝 远程同步与 CI 闭环

- 禁止静默直写远程；不得改动他人未提交的工作区内容。
- push ≠ 完成：`gh run list` / `gh run watch` 盯到 CI 终态，红了当场修；lint/type 真失败时修代码，
  不用 `--no-verify` 绕过钩子。
- 修复 Bug / 踩坑后须把坑点追加到 `docs/agents/GOTCHAS.md`（该文件随仓库分发）。

## 5. 🧹 构建产物滚动清理

- 每次构建后删除**前一轮**产物，只保留本轮；禁止 `target/`、`dist/`、`build/`、`installer-data/`、
  `tauri-release/` 及各类缓存目录跨轮堆积。
- 例外（不得清理）：模型权重目录、运行数据 `data/` 与 `outputs/`、签名密钥与证书。
