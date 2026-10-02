# 能力演进路线图（P0/P1 已落地 · P2 首项已验收 · VLM 已立项 · P3 LoRA 训练已立项）

> 本文档把 **Image MultiModel 的能力演进**按 P0/P1/P2 明确切片，使「后续可选演进」可追踪、可验收。
> 注意：仓库内另有的 P0/P1/P2 分级（见 `docs/repo-analysis/测试体系评估报告_2026-09-04.md` §5）是**缺陷严重度**维度，与本能力路线无关，请勿混淆。

## 缘起与现状

- 能力路线此前仅存在于提交历史与对话共识，**没有落在任何已提交文档**：
  - P0 会话持久化 / 流式 / 冷启动 / 图片保护 / 多标签 → `commit 891fdfe`
  - P1 编辑引擎（vendored 内核 v0.38.0 + Qwen-Image 2.1 Edit 原生接入）→ `commit 322ba54`
  - P2 多引擎接入 → `P2-multi-engine.md` 已文档化（Flux.2 Klein 验收）；VLM 看图聊天 → `P2-vlm-chat.md` 已立项，M1 已验收 + 返工、**M2-M6 已落地**；`clip.generate` 真实前向已实跑闭环（2026-10-02 preflight OK(0)，含换图对照实验）
- 代码注释引用的 `MASTER_PLAN`（见 `app/integrated_app/routes/engine_routes.py` 顶部「对应 MASTER_PLAN §5.1」）**仓库中不存在**，属悬空引用 → 本目录即作为其能力路线载体（另见 open issue：补/删该注释）。

## 能力切片总览

| 级别 | 方向 | 状态 | 文档 | 落地证据 |
|---|---|---|---|---|
| P0 | 会话持久化 + 流式 delta + 冷启动提示 + 图片保护 + 多标签页 | ✅ 已落地 | — | `commit 891fdfe`、i18n×5、SSE 分片解码 |
| P1 | 编辑引擎（Qwen-Image 2.1 Edit 原生接入） | ✅ 已落地 | `workflows/blueprints/README.md`（移植蓝图） | `commit 322ba54`、`native/edit_executor.py` |
| P2 | **native 多引擎接入** | 🟢 **首项已验收**（Flux.2 Klein 9B fp8 端到端跑通） | [P2-multi-engine.md](./P2-multi-engine.md) | commit `f82457d` + 2026-10-01 端到端任务 `f806a6edb0af4277`（1235 pytest pass / mypy 0 err / 512² 243s 出图 335 KB） |
| P2 | **VLM 看图聊天** | 🟢 M1 已验收（commit `2ed1534`）；**M2/M3/M4/M5/M6 已落地**（`77b7e3c` / `f6c75f3` / `0821a45` / `acd4bf7`）+ 装配接线 `096ce57` | [P2-vlm-chat.md](./P2-vlm-chat.md) | Agent 通道多模态输入 + 内容过滤 + 前端问 AI/图气泡 + 编辑指令桥接均已通过门禁；**M1 已于 2026-10-02 返工**（推理路径 transformers → comfy_kernel，权重无需 HF config.json）；**已于 2026-10-02 闭环**：结束占用显存的 ComfyUI 后腾出 10.8 GiB，`scripts/preflight_qwen3vl.py` 退出码 OK(0)（权重 8.71 GiB → load_clip → tokenize(image embed=1) → generate 8 token/24.9s → decode），并换图对照证明视觉分支参与前向；**无遗留** |
| P3 | **LoRA 训练模块** | 🟡 已立项（T-34 决策=是，2026-10-01）· 选型已完成（2026-10-02，路径 A=AI-Toolkit） | [P3-lora-training.md](./P3-lora-training.md) | 决策记录 + 约束分析；**T-22/T-28 已实证收口，T-12 选型定案**；AI-Toolkit 未在本机安装、训练尚未跑过，T-12 代码接入待「最小 Z-Image LoRA job 跑通」 |

## 判定原则（P2 为何「可选」）

- P2 不阻塞当前发布主线（v1.2.2 已具备：原生引擎出图 + 编辑 + 超分 + 历史 + 安全过滤 + 桌面分发）。
- 触发 P2 启动的硬条件（任一条满足即升为「待办」）：
  1. 用户侧出现明确的多引擎/看图聊天需求；
  2. 出现可复用的 VLM 权重与稳定的本地推理路径（显存预算内）；
  3. 竞品或评估方将「多引擎/多模态」列为必需维度。

## 待办（文档层）

- [ ] 任一 P2 升为「待办」时，将其文档状态由 🔲 改为 🟡 并填写验收证据。
- [x] P2 多引擎首项（Flux.2 Klein 9B）已验收；后续候选引擎（Qwen_image_native / krea2_turbo_native 等）待触发条件满足时按 `P2-multi-engine.md` 步骤接入。
- [x] P2 VLM 看图聊天立项：M1-M6 里程碑已写入 `P2-vlm-chat.md` 实施任务清单；**2026-10-01 用户裁定「全部都做」**，M1 已验收（commit `2ed1534`），**M2/M3/M4（`77b7e3c`/`f6c75f3`/`0821a45`）、M5/M6（`0821a45`/`acd4bf7`）、装配接线（`096ce57`）已落地并通过门禁**（远端未 push）。**M1 已完成 comfy_kernel 返工（2026-10-02）**：`_chat_sync`/`_load_model` 改走 `comfy.sd.load_clip` → `clip.tokenize/generate/decode`，不再需要 HF 目录；**M1 真实前向已实跑闭环（2026-10-02）**：preflight 退出码 OK(0) + 换图对照实验；无遗留。
- [x] 学习报告借鉴 38 项归口：见 [learning-report-tasks.md](./learning-report-tasks.md)；**分组 ① T-01~T-05 已修正入库（commit `5fb7517`+`f6f5268`），T-06 因 reference_repos 缺失阻塞**；领域 B/E/G 分别挂到 P2 各里程碑。
- [x] P3 LoRA 训练立项：T-34 决策=是（2026-10-01），见 [P3-lora-training.md](./P3-lora-training.md)。
- [x] T-28 / T-22 实证收口 + T-12 选型定案（2026-10-02）：`reference_repos/sd-scripts` 已克隆并完成 LUMINA 训练深读（只吃硬编码 `NextDiT_2B`，`strict=False` 会静默错配）；改用 AI-Toolkit 内置 `captioner` + `dataset_tools`，不引入 SDNext；训练后端采用**路径 A（AI-Toolkit）**，路径 B 前提被证伪（aki-v3 无任何训练节点）。依据见 [P3-lora-training.md](./P3-lora-training.md) 事实约束表与 GOTCHAS #45。

## 关于 `MASTER_PLAN` 引用（澄清，非待办）

- `MASTER_PLAN` 是**项目级外部设计规格书**，全仓约 30 个模块头（如 `app_server.py`、`config.py`、`engine_routes.py`、`path_guard.py` 等）均以「对应 MASTER_PLAN §X」作交叉引用——这是**一致的既有约定**，并非本目录引入的悬空引用，**不应删除或改指本目录**。
- `docs/roadmap/` 是**仓库内能力演进追踪器**（聚焦 P0/P1/P2 功能切片），与 `MASTER_PLAN`（原始总体设计规格）职责不同、互补，不构成替代关系。
- 若未来某日 `MASTER_PLAN` 规格书决定入库，应在仓库根或 `docs/` 下建立对应文件，而非逐个改注释。
