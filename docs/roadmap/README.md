# 能力演进路线图（P0/P1 已落地 · P2 后续可选）

> 本文档把 **Image MultiModel 的能力演进**按 P0/P1/P2 明确切片，使「后续可选演进」可追踪、可验收。
> 注意：仓库内另有的 P0/P1/P2 分级（见 `docs/repo-analysis/测试体系评估报告_2026-09-04.md` §5）是**缺陷严重度**维度，与本能力路线无关，请勿混淆。

## 缘起与现状

- 能力路线此前仅存在于提交历史与对话共识，**没有落在任何已提交文档**：
  - P0 会话持久化 / 流式 / 冷启动 / 图片保护 / 多标签 → `commit 891fdfe`
  - P1 编辑引擎（vendored 内核 v0.38.0 + Qwen-Image 2.1 Edit 原生接入）→ `commit 322ba54`
  - P2 多引擎接入 / VLM 看图聊天 → **未落地、未文档化**
- 代码注释引用的 `MASTER_PLAN`（见 `app/integrated_app/routes/engine_routes.py` 顶部「对应 MASTER_PLAN §5.1」）**仓库中不存在**，属悬空引用 → 本目录即作为其能力路线载体（另见 open issue：补/删该注释）。

## 能力切片总览

| 级别 | 方向 | 状态 | 文档 | 落地证据 |
|---|---|---|---|---|
| P0 | 会话持久化 + 流式 delta + 冷启动提示 + 图片保护 + 多标签页 | ✅ 已落地 | — | `commit 891fdfe`、i18n×5、SSE 分片解码 |
| P1 | 编辑引擎（Qwen-Image 2.1 Edit 原生接入） | ✅ 已落地 | `workflows/blueprints/README.md`（移植蓝图） | `commit 322ba54`、`native/edit_executor.py` |
| P2 | **native 多引擎接入** | 🔲 后续可选（架构就绪 + 蓝图就绪，未立项验收） | [P2-multi-engine.md](./P2-multi-engine.md) | `engine_routes.py` backend 分发 + `native/` 模块齐全 |
| P2 | **VLM 看图聊天** | 🔲 后续可选（空白，无设计/计划/代码） | [P2-vlm-chat.md](./P2-vlm-chat.md) | — |

## 判定原则（P2 为何「可选」）

- P2 不阻塞当前发布主线（v1.2.2 已具备：原生引擎出图 + 编辑 + 超分 + 历史 + 安全过滤 + 桌面分发）。
- 触发 P2 启动的硬条件（任一条满足即升为「待办」）：
  1. 用户侧出现明确的多引擎/看图聊天需求；
  2. 出现可复用的 VLM 权重与稳定的本地推理路径（显存预算内）；
  3. 竞品或评估方将「多引擎/多模态」列为必需维度。

## 待办（文档层）

- [ ] 任一 P2 升为「待办」时，将其文档状态由 🔲 改为 🟡 并填写验收证据。

## 关于 `MASTER_PLAN` 引用（澄清，非待办）

- `MASTER_PLAN` 是**项目级外部设计规格书**，全仓约 30 个模块头（如 `app_server.py`、`config.py`、`engine_routes.py`、`path_guard.py` 等）均以「对应 MASTER_PLAN §X」作交叉引用——这是**一致的既有约定**，并非本目录引入的悬空引用，**不应删除或改指本目录**。
- `docs/roadmap/` 是**仓库内能力演进追踪器**（聚焦 P0/P1/P2 功能切片），与 `MASTER_PLAN`（原始总体设计规格）职责不同、互补，不构成替代关系。
- 若未来某日 `MASTER_PLAN` 规格书决定入库，应在仓库根或 `docs/` 下建立对应文件，而非逐个改注释。
