# P2 — VLM 看图聊天（后续可选演进）

> 状态：🟡 待办（VLM 权重已确认：**Qwen3-VL-8B int8_convrot**，本机已挂载且已验证可加载）
> 关联：`docs/roadmap/README.md`（总索引）
> 检索结论：全仓 `grep -rni "vlm\|看图\|image chat"` 仅命中 vendored 内核里的零星变量名
> （`comfy_kernel/.../hidream_o1/conditioning.py`、`nodes_boogu.py` 的视觉塔），**非本平台功能**。

## 目标

让用户在生图工作台内，对**已生成/已上传的图片**发起多轮视觉对话——描述内容、问修改建议、
指令化编辑（"把背景换成雪天"），由本地 VLM 模型回答，并可桥接至编辑引擎执行。

## 当前现状（如实记录）

- 架构：现有 Agent 通道（`/api/agent/*` + LLM 决策）面向**文生图/编辑指令**，不消费图片输入；
- 模型：本地仅部署文生图/编辑权重（Z-Image / Qwen-Image / Flux.2 Klein 等），**无 VLM 权重**；
- 代码：零 VLM 推理路径、零看图聊天端点、零前端对话 UI；
- 文档：除本文件外无任何设计/计划。

## 设计选项（待立项时二选一或组合）

| 方案 | 描述 | 优点 | 风险/成本 |
|---|---|---|---|
| A. 复用 Agent + VLM 模型 | 在现有 Agent 通道挂一个 VLM 模型，图片作为多模态输入进入 LLM 决策链 | 复用 SSE 流式、会话持久化、i18n；改动面小 | 需新增本地 VLM 权重（如 Qwen2.5-VL / Qwen3-VL 系，已在编辑 TE 中部分出现）并保证 12GB 预算 |
| B. 独立看图聊天服务 | 新建 `native/vlm_chat.py` + `/api/vlm/chat` 端点 + 前端对话面板 | 职责清晰、可独立迭代 | 重复造会话/流式/持久化轮子，与 Agent 通道割裂 |

**倾向**：方案 A（复用现有 Agent + 多模态模型）优先，避免重复建设；仅在需要独立多模态能力时再拆 B。

## 已确认 VLM 权重（阻塞项已解除）

| 项 | 结论 | 证据 |
|---|---|---|
| 选定权重 | **Qwen3-VL-8B（`qwen3vl_8b_int8_convrot.safetensors`）** | `pretrained_models/text_encoders/Qwen-Image-2.1/qwen3vl_8b_int8_convrot.safetensors`，**9.35 GB** |
| 已挂载 | ✅ 是 | 已随 P1 编辑引擎落位，config 引用 `Qwen-Image-2.1/qwen3vl_8b_int8_convrot.safetensors` |
| 已验证可加载 | ✅ 是 | 该权重**正是编辑引擎的 text encoder**，Edit 链路实机跑通即为其可加载的实证 |
| 体积 | 9.35 GB | 12GB VRAM 可容纳（余量约 2.6GB，需配合卸载策略） |
| 备选（暂不选） | `qwen3vl_32b_minimax_h3_abliterated_nvfp4.safetensors`（32B nvfp4） | aki-v3 `models/text_encoders/`；32B 体积与 KV-cache 对 12GB 过载，且为 abliterated 变体 |

> 注：Qwen3-VL 是**视觉-语言模型**（含视觉塔），可同时承担 TE 与看图聊天职责——复用同一权重可省一份显存。

## 依赖与阻塞项（⚠️ blocking）

- ~~⚠️ 本地 VLM 权重缺失~~ → **已解除**（见上，Qwen3-VL-8B 本机已有且已验证）。
- ⚠️ **显存预算**：文生图引擎常驻 + VLM 并发会出现 VRAM 争用，需明确加载策略（空闲卸载沿用 `ADR-0001-idle-unload-policy.md` 或请求级卸载）。
- 前端：需在现有工作台增加「看图聊天」入口与多模态消息渲染（图片缩略图 + 气泡）。
- 安全：看图内容同样须经 `content_filter` 管线（与出图同款 CLIP 归一化过滤），避免绕过。

## 验收标准（升为「待办」后）

- [ ] 选定 VLM 权重并在 `config.yaml` 注册，本地加载成功（显存预算内）；
- [ ] 用户可对图片发起多轮对话，VLM 返回有效文本（SSE 流式）；
- [ ] 对话内容经 `content_filter` 过滤（与出图同口径）；
- [ ] 可选：对话中的编辑指令可桥接至编辑引擎执行并落盘；
- [ ] 回归测试覆盖 VLM 加载/对话/过滤。

## 启动条件（见总索引「判定原则」）

用户明确需求 / 出现稳定本地 VLM 推理路径 / 评估方将「多模态」列为必需维度 —— 任一满足即升为「待办」。

---

## 实施任务清单（M1-M6 · 2026-10-01 立项细化）

> 采用**方案 A**：复用现有 Agent 通道 (`/api/agent/*` + SSE 流式 + 会话持久化 + i18n) 挂一个 VLM 模型作为多模态决策器。里程碑按「最小可验证切片」切分，每 M 可独立提交，全部走 mypy + pytest 门禁。

### M1 · VLM 模型注册与显存策略（后端，≈1 天）
- 目标：Qwen3-VL-8B int8_convrot 权重在启动期/请求期能按需加载，与文生图引擎共享 12 GB 预算不 OOM。
- 落点：
  - `config.yaml → models.engines.qwen3_vl_8b_native`（`backend: native`、`role: vlm`）；`config_models.py` 允许 `role ∈ {t2i, edit, vlm}`
  - 新增 `app/integrated_app/native/vlm_engine.py`：封装 Qwen3-VL 视觉塔 + LLM forward，接口对齐 `NativeEngine`（load / infer / unload）
  - **共享 TE**：编辑引擎与 VLM 同为 Qwen3-VL-8B 权重——`model_registry` 加同权重单例复用（`weight_sha256` 相同即共享加载，避免两份 9.35 GB 常驻）
  - **卸载策略**：沿用 `ADR-0001-idle-unload-policy.md`；VLM 空闲 60s 主动 unload；生图/编辑请求触发时优先卸 VLM 保 T2I
- 验收：`tests/native/test_vlm_engine.py` 覆盖 load/unload/权重单例复用/显存不重叠；`mypy app/integrated_app` 零错。

### M2 · Agent 通道接收多模态输入（后端，≈1.5 天）
- 目标：`POST /api/agent/chat` 请求体接受 `images: [{path|b64, role: "input"|"output"}]`，VLM 编码后作为条件前缀注入。
- 落点：
  - `routes/agent_routes.py` schema 扩展（`AgentChatRequest.images: list[AgentImage]`）；沿用现有 SSE 流式返回
  - `native/vlm_engine.py.infer(prompt, images)`：Qwen3-VL 视觉塔预处理 + 位置编码拼接
  - 会话历史持久化沿用 `SessionStore`（`chat.js` 已有）
- 验收：`tests/integration/test_agent_vlm_multiturn.py` 覆盖 单图/多图/无图/会话回放；`path_guard` 校验 images 路径不越界。

### M3 · 内容过滤接入（后端安全，≈0.5 天）
- 目标：VLM **输入图**与**输出文本**均走同款安全管线，与出图同口径，防绕过。
- 落点：
  - `security/content_filter.py` 加 `filter_image_for_vlm_input(path)`（CLIP 归一化 + 0.5 阈值，复用 `9da93a6` 校准）
  - VLM 输出文本走现有 `safety_routes.filter_output(text)`
- 验收：`tests/security/test_vlm_content_filter.py` 拒绝违规图/文；单测 mock CLIP 断言归一化路径。

### M4 · 前端「问 AI」入口（前端，≈1 天）
- 目标：图片查看器、历史详情、画廊卡片增加「问 AI」按钮 → 打开 Agent 抽屉并把该图作为首条上下文。
- 落点：
  - `templates/index.html`：查看器 `.v-tools` 加 `vAskAI`；`histDetail .btn-row-6` 加 `ddAskAI`；`gallery .g-meta` hover 加悬浮按钮
  - `static/js/chat.js`：`openWithImage(path, prompt)` 把图片缩略图 + 用户输入拼首条消息发送；沿用现有 `send()`
  - `applyLang` / I18N 五语言补 `btn_ask_ai` 键
- 验收：`tests/frontend/smoke.js` 新增 3 用例（入口存在 / aria-label / 点击打开抽屉）。

### M5 · 多轮对话 UI 与图气泡（前端，≈1 天）
- 目标：Agent 抽屉内消息渲染支持图片缩略图（输入/输出各 40×40/120×120 双档）+ 文本气泡，样式对齐现有工作台。
- 落点：
  - `chat.js.renderMessage(msg)` 分支：`msg.images?.length` 时前置缩略图网格
  - `static/css/seed.css` 补 `.agent-msg.with-img`（flex）
  - 图片点击放大 → 走现有查看器
- 验收：smoke 覆盖含图消息渲染；浏览器实测中英日韩四语视觉一致。

### M6 · 编辑指令桥接（可选，≈1.5 天）
- 目标：VLM 输出的自然语言修改建议（如「把背景换成雪天」）解析为结构化 edit 指令 → 一键 `POST /api/generate?mode=edit`。
- 落点：
  - `native/vlm_engine.py` 加 `parse_edit_intent(text) -> EditIntent | None`（prompt 里预置 few-shot）
  - `chat.js` 消息下方出现「执行编辑」按钮 → 携当前图 + intent 调 edit
- 验收：`tests/integration/test_vlm_edit_bridge.py` mock VLM 输出验证解析/调用链。

### 回归门禁（每 M 收口都跑）
- `py -3.12 -m mypy app/integrated_app`（ratchet 零错）
- `py -3.12 -m pytest tests/ --ignore=tests/frontend -q`（全量 0 failed）
- `py -3.12 scripts/render_pages.py` + `node tests/frontend/smoke.js`（M4/M5 后必跑）
- 改动核心模块（`config_models.py` / `native/vlm_engine.py` 若加入清单）后 → `generate_integrity_manifest.py` + `sign_integrity_manifest.py`
- 提交前 `pre-commit run --all-files`（ruff / DCO / secret / structure guard）

### 显存与耗时预算（12 GB 场景预期）
| 场景 | 常驻 | 请求期峰值 | 备注 |
|---|---|---|---|
| 仅 VLM 加载 | ~9.35 GB | ~10.5 GB | int8_convrot 权重 + KV |
| 生图并发 VLM | 触发卸载 | 保 T2I ~10 GB | ADR-0001 |
| 编辑并发 VLM | 共享 TE（同权重） | ~11 GB | M1 单例复用 |

**首次推理耗时目标**：512×512 输入图 + 200 字提问 ≤ 15s（预热后 5-8s）；超预算则回退 fp4 量化变体（M1 附条件）。

### 立项决策点（用户勾选后方可启动）
- [ ] 是否启动 M1（VLM 引擎 + 显存策略）
- [ ] 若启动，是否要求 M4-M5 前端 UI 与 M2-M3 后端同批发布
- [ ] 是否包含 M6 编辑桥接（可延后到 M1-M5 稳定后）

以上任一决策为「是」即可开工；M1 完成前不合并 M2。
