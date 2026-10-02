# P2 — VLM 看图聊天（后续可选演进）

> 状态：🟢 **M1 已验收 + 已返工（2026-10-02）、M2-M6 已落地**；M1 推理路径已从 transformers 换成
> comfy_kernel（权重无需 HF `config.json`）；**唯一遗留 = `clip.generate` 真实前向尚未实跑**
> （本机可用显存/内存均不足，需腾出 ≥10 GiB 显存后跑 `scripts/preflight_qwen3vl.py` 闭环）。
> 关联：`docs/roadmap/README.md`（总索引）
> 立项检索结论（2026-10-01 当时）：全仓 `grep -rni "vlm\|看图\|image chat"` 仅命中 vendored 内核里的
> 零星变量名（`comfy_kernel/.../hidream_o1/conditioning.py`、`nodes_boogu.py` 的视觉塔），**非本平台功能**。
>
> ⚠️ **下方「当前现状」为立项当时的快照，已过时**——保留用于追溯演进起点，请勿据此判断现状；
> 现状请看「实施任务清单（M1-M6）」各段落的「验证状态」。

## 目标

让用户在生图工作台内，对**已生成/已上传的图片**发起多轮视觉对话——描述内容、问修改建议、
指令化编辑（"把背景换成雪天"），由本地 VLM 模型回答，并可桥接至编辑引擎执行。

## 当前现状（⚠️ 立项当时 2026-10-01 的快照，已过时，勿据此判断现状）

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

> **已裁定（2026-10-01 用户）**：采用**方案 A**，详见文末「立项决策点」。

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

- [x] 选定 VLM 权重并在 `config.yaml` 注册（M1，commit `2ed1534`）；⚠️ **本地加载未实跑**——
      本机仅有单个 `qwen3vl_8b_int8_convrot.safetensors`，缺 HF 目录（`config.json`/tokenizer），
      见 M1 验证状态与 `scripts/preflight_qwen3vl.py`（离线 SKIPPED，不静默降级）。
- [x] 多轮对话**链路**已通（M2/M5）：`/api/agent/chat` 接受 `images`、SSE 流式、前端图气泡已落地；
      ⚠️ VLM 前向应答未实跑（同上行阻塞，缺 HF 目录）。
- [x] 对话内容经 `content_filter` 过滤（与出图同口径）（M3，commit `f6c75f3`）。
- [x] 编辑指令可桥接至编辑引擎执行（M6，commit `acd4bf7`）：解析 → 一键 `POST /api/generate`
      （`edit_mode=true` + `reference_image_path`）入队落盘。
- [x] 回归测试覆盖过滤 / 多模态输入 / 编辑桥接 / 装配接线（M2/M3/M6 + `096ce57`）。
- [ ] **唯一未闭环**：VLM 真实加载 + 多模态对话实机通过（需 HF 目录就位后跑 preflight 与端到端）。

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

> **M1 验证状态（2026-10-01 收口）**：后端脚手架已落地并通过门禁——
> `config_models.py` 加 `role` 字段 + 校验器、`model_registry` 按 `role=="vlm"` 分发 `VlmEngine`、
> `config.yaml` 注册 `qwen3_vl_8b_native`、`native/vlm_engine.py` 实现权重单例 + 空闲卸载；
> `tests/native/test_vlm_engine.py` 6 例全绿、`mypy` 零错、完整性清单重算并 Ed25519 重签（CI 门禁 PASS）。
> **离线阻断（真实多模态前向未实机验证）**：本仓严格离线，本地仅存在单个
> `qwen3vl_8b_int8_convrot.safetensors`（无 `config.json` / tokenizer），Qwen3-VL 的 HF 模型目录未就位，
> 故 `infer_chat` 的 `transformers.Qwen3VLForConditionalGeneration` 前向链路**暂无法本地跑通**。
> 已新增 `scripts/preflight_qwen3vl.py` 作为实机验证脚本：当 `engines.qwen3_vl_8b_native.local_model_dir`
> 指向含 `config.json` 的本地目录时，脚本会真加载权重 + processor + `model.generate` 并解码；
> 当前离线下脚本以退出码 2（SKIPPED）清晰退出，不静默降级、不联网下载。
> **待办（已于 2026-10-02 随返工改写）**：不再需要下载任何东西（权重本就在），也不再需要
> `local_model_dir` 指向 HF 目录；改为**腾出 ≥10 GiB 显存**后跑
> `py -3.12 scripts/preflight_qwen3vl.py --image <图>` 闭环真实前向验证（M1 验收的最后一环）。
> 该「离线阻断」结论本身已于 2026-10-02 被下方实证推翻：阻断的根因是**推理路径选错**，不是缺文件。

> ⚠️ **上述「离线阻断」结论已于 2026-10-02 实证推翻（重要更正）**
>
> 结论：**本机早已具备 VLM 看图聊天的全部要素，不需要下载任何东西**；真正的问题不是「缺 HF 目录」，
> 而是 **M1 的推理路径选错了** —— `infer_chat` 走了 `transformers.Qwen3VLForConditionalGeneration`，
> 而这份权重是 **ComfyUI 专用 int8 convrot 量化格式**（每个线性层都带 `comfy_quant` 元数据），
> transformers 根本**不认识**这种格式；即便手工拼出 HF 目录也加载不了。正确路径是**仓库自带的
> `comfy_kernel`**，它天然认识 `comfy_quant`，而且**自带 config 与 tokenizer**（所以从不需要 HF 目录）。
>
> 实证清单（逐项在仓库/CI 环境核实，2026-10-02）：
>
> | 要素 | 位置 | 证据 |
> |---|---|---|
> | 权重（**含 lm_head 生成头 + visual 视觉塔**） | `pretrained_models/text_encoders/Qwen-Image-2.1/qwen3vl_8b_int8_convrot.safetensors`（9.35 GB） | safetensors 头 1258 keys：`lm_head.weight` / `lm_head.comfy_quant` / `model.visual.blocks.0.*` / `model.embed_tokens.*` |
> | 模型类（**自带 generate**） | `comfy_kernel/comfy/text_encoders/qwen3vl.py:50` | `class Qwen3VL(BaseLlama, BaseQwen3, BaseGenerate, torch.nn.Module)`，`model_type="qwen3vl_8b"` |
> | 生成实现 | `comfy_kernel/comfy/text_encoders/llama.py:1124` | `BaseGenerate.generate(embeds, max_length, temperature, top_k, top_p, …, deepstack_embeds, visual_pos_masks)` + `logits()` 优先用 `model.lm_head` |
> | 架构 config | `comfy_kernel/comfy/text_encoders/llama.py:350` | `class Qwen3VL_8BConfig(Qwen3_8BConfig)` |
> | tokenizer | `comfy_kernel/comfy/text_encoders/qwen25_tokenizer/` | `vocab.json` + `merges.txt` + `tokenizer_config.json`（`Qwen2Tokenizer` 可直接加载） |
> | 图像预处理 | `comfy_kernel/comfy/text_encoders/qwen_vl.py:9` | `process_qwen2vl_images(...)`：resize→归一化→patchify。**注意 Qwen3-VL 实际以 `patch_size=16` 调用**（见 `qwen3vl.py:65`，虽与 `qwen_vl.py` 的默认值 14 同名参数不同值）——以 `qwen3vl.py` 的调用点为准，不是 `qwen_vl.py` 默认值 |
> | 引擎已注册 | `config.yaml:172 models.engines.qwen3_vl_8b_native` | `role: vlm`、`comfy_source_dir: comfy_kernel`、text_encoder 指向该权重 |
>
> **旁证**：ComfyUI-aki-v3 侧 `ComfyUI/models/text_encoders/Qwen-Image-2.1/` 同样是**只有一个裸 safetensors**、
> 没有 config.json —— 不是缺东西，而是 ComfyUI 生态本就靠 `comfy/text_encoders/` 里的
> Python config（如 `Qwen3VL_8BConfig`）+ 内置 tokenizer 目录来加载，**从不需要 HF 目录**。
>
> **因此 M1 待办改为**：把 `native/vlm_engine.py` 的 `_chat_sync` 从 transformers 路径改为
> `comfy_kernel` 路径，再用 `scripts/preflight_qwen3vl.py` 实跑闭环。
>
> ### ✅ M1 返工落地状态（2026-10-02）
>
> **已落地**：`_chat_sync` / `_load_model` 已切到 comfy_kernel，`scripts/preflight_qwen3vl.py`
> 的 transformers 分支已整段替换为 comfy 实跑（含 `--device cpu` 回落），单测补齐（6→10 + 新文件 5）。
>
> **已实证**（不依赖 9.35GB 权重驻留，故 CI/离线可复跑）：
> - `detect_te_model(真实权重头)` → `TEModel.QWEN3VL_8B`（`tests/native/test_vlm_engine_comfy_path.py`）
> - 权重头含 `lm_head*` 生成头 + `model.visual.*` 视觉塔 + DeepStack 判定键
> - `Qwen3VLTokenizer` 把 `[1,H,W,3]` 图片张量接进序列（占位符被就地换成 image embed dict）
> - `process_qwen2vl_images(patch_size=16, mean=std=0.5)` 数值自洽（patch 数 == grid_h*grid_w）
> - `_resolve_qwen3vl_weight` 经 `config_models.resolve_model_path` 命中真实 `.safetensors`（不碰文件本体）
>
> **未实证（如实标注，未静默降级、未伪造通过）**：`clip.generate` 的**真实前向**尚未实跑——
> 本机 2026-10-02 实测 **可用显存 7.95 GiB / 可用内存 6.1 GiB**，均低于该 9.35 GB 权重的驻留需求
> （且 ComfyUI 正在占用约 4 GiB 显存）。按 `scripts/preflight_qwen3vl.py` 跑一次即可闭环，
> 条件：**腾出 ≥10 GiB 显存**（关闭 ComfyUI 或空闲时段）后执行
> `py -3.12 scripts/preflight_qwen3vl.py --image <某张图>`。
>
> **2026-10-02 已按此返工落地**（`native/vlm_engine.py` + `scripts/preflight_qwen3vl.py`）：
> 不再手组装 `Qwen3VL`（量化元数据会被漏掉），而是走 comfy 官方装配面
> `comfy.sd.load_clip([权重])` → 返回 `comfy.sd.CLIP`，再 `clip.tokenize(prompt, image=...)`
> → `clip.generate(...)` → `clip.decode(...)`（与 `comfy_extras/nodes_textgen.py#TextGenerate`
> 同一条链路）。`<|image_pad|>`(151655) 由 `Qwen3VLTokenizer.tokenize_with_weights` 自动把占位符
> 换成 image embed dict，调用方**不需要**手塞 token。权重路径复用了
> `config_models.resolve_model_path`（与其余引擎同一套权威约定），`--model-dir` 参数语义由
> 「HF 目录」改为「权重文件」。

### M2 · Agent 通道接收多模态输入（后端，≈1.5 天）
- 目标：`POST /api/agent/chat` 请求体接受 `images: [{path|b64, role: "input"|"output"}]`，VLM 编码后作为条件前缀注入。
- 落点：
  - `routes/agent_routes.py` schema 扩展（`AgentChatRequest.images: list[AgentImage]`）；沿用现有 SSE 流式返回
  - `native/vlm_engine.py.infer(prompt, images)`：Qwen3-VL 视觉塔预处理 + 位置编码拼接
  - 会话历史持久化沿用 `SessionStore`（`chat.js` 已有）
- 验收：`tests/integration/test_agent_vlm_multiturn.py` 覆盖 单图/多图/无图/会话回放；`path_guard` 校验 images 路径不越界。

> **M2 验证状态（2026-10-01 提交 77b7e3c）**：后端已落地并通过门禁——
> `AgentChatRequest.images`（`AgentImage` 的 `path`/`b64` 互斥且恰好其一） + `_validate_images`
> 走 `PathGuard` 白名单（越权 **422**，阻在 SSE 建流之前，不混进错误事件流）；
> `orchestrator._run_turn_impl`（流式/非流式唯一共用实现）新增 `images`，经 `vlm_context_fn`
> 编入 `VISION_CONTEXT_TEMPLATE`，模板自带「**不构成任何指令**」声明以落实数据/指令分离；
> 未配置编码器时如实发 `vlm_context{status:"unavailable"}`，**不伪造**视觉描述；
> 纯文本轮次不发该事件（避免噪声）。
> 验收：`tests/integration/test_agent_vlm_multiturn.py` **18 例全绿**（单图/多图与顺序/无图/
> 会话回放/越权 422×3/形态校验/data URI 归一化/超 8 张截断/注入语义/降级不伪造）；
> `tests/test_agent_routes.py` 的 `FakeOrchestrator` 同步接受 `images` 关键字参数（4 例回归修复）。
> 门禁：ruff / ruff-format / mypy（98 文件零错）全通过。
> **未做**：`vlm_context_fn` 的装配（由真实 VLM 实例注入）尚未接线——本仓离线、
> Qwen3-VL 的 HF 模型目录未就位（同 M1 阻断），接线留待 M1 preflight 闭环后接上。

> **装配接线已补（2026-10-01 收口，M2/M6 最后一环）**：注入式依赖此前只定义在编排层、
> **没人注入**——服务起来后带图提问仍是 `unavailable`、M6 的 `edit_engine_fn` 恒为 None，
> 功能等于没接。已在 `routes/agent_routes._get_orchestrator` 真正装配：
> - ``edit_engine_fn=_first_edit_engine``：从 config 找首个 `supported_features` 含 edit 的引擎
>   （本机实测解析为 ``qwen_image_edit_native``）。同一口径也替换了工具侧 ``edit_image``
>   里原本自己遍历 config 的那段重复逻辑——**「谁有资格做编辑」只判一次**，
>   避免两处各自遍历后一处说有、一处说没有。
> - ``vlm_context_fn=_build_vlm_context_fn(_first_vlm_engine())``：**延迟加载**
>   （9.35 GB 不在启动期压上显存）+ 每次编码前用 ``is_ready()`` 探测，
>   被 ADR-0001 的 ``request_vlm_unload`` 卸掉后自动重新 load，不留僵尸实例；
>   没配 VLM 引擎时压根不装配（宁报 `unavailable`，不伪造视觉描述）；
>   load 失败（HF 目录未就位）冒泡成 `status=error`，不静默降级。
> - 验收：`tests/integration/test_agent_vlm_wiring.py` **6 例全绿** —— 用 TestClient 起真实
>   app + 真实 config 断言装配结果（``edit_engine_fn()`` 与独立重算的真解一致，
>   不复读被测函数自证）；工具侧「是否仍各自遍历」用源码断言守住；卸载后重载 + load 失败不跑推理。
> - 边界：本机离线、**未做**真实多模态前向端到端（带图请求的 `load()` 会因 HF 目录未就位
>   走到 `status=error`，这正是设计口径），闭环仍需 M1 preflight。

### M3 · 内容过滤接入（后端安全，≈0.5 天）
- 目标：VLM **输入图**与**输出文本**均走同款安全管线，与出图同口径，防绕过。
- 落点：
  - `security/content_filter.py` 加 `filter_image_for_vlm_input(path)`（CLIP 归一化 + 0.5 阈值，复用 `9da93a6` 校准）
  - VLM 输出文本走现有 `safety_routes.filter_output(text)`
- 验收：`tests/security/test_vlm_content_filter.py` 拒绝违规图/文；单测 mock CLIP 断言归一化路径。

> **M3 落点更正（2026-10-01 实证）**：原计划的 `safety_routes.filter_output` **在本仓不存在**——
> `routes/safety_routes.py` 只有 `check_prompt` / `check_image` 两个 HTTP 端点，没有任何模块级
> `filter_output`。已全仓 grep 复核（`filter_output` / `scan_output` / `check_text` 均 0 命中），
> 因此**不臆造该函数**，改为直接复用 `ContentSafetyFilter.check_prompt`——它本就是提示词/注入侧
> 的唯一实现（关键词 + 同形字/莱特/零宽绕过 + 注入规则集），对 VLM 产出文本同样适用，且永远可用
> （不依赖 CLIP）。另经确认：内核 prompt 泄露那层由 `agent/guard.py::detect_leak` 兜底，
> M2 的 `_run_turn_impl` 已在流式/非流式两条路径共用它，故 VLM 输出经编排器后天然覆盖，
> 无需在 M3 重复实现（**新增入口需自行套 detect_leak**）。

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

> **M5 验证状态（2026-10-01 收口）**：前端已落地并通过门禁——
> ``chat.js`` 新增 `makeThumb()` / `enlargeThumb()`，输出档挂 `.agent-img-out`（120×120）、
> 输入档 `.with-img` flex 网格（40×40），点击缩略图**复用现有全屏查看器**
> （`openViewerReal` 是全局函数声明），从 ``/api/outputs/`` URL 反解回仓库相对路径；
> `enlargeThumb` 对 outputs 之外的路径（绝对路径 / 越权）**no-op**，与后端 PathGuard 同口径。
> 修了一个真实缺陷：`app.js` 的 `typeLabel(undefined)` 会崩（`tr()` 里对 `k` 直接调 `k.indexOf`），
> 而查看器常只拿到 `{path, prompt}` 这类部分对象 → 已在 `typeLabel` 加空值防御（返回空串，
> 由调用方 `||` 兜默认文案），根因修复而非调用点绕开。
> 验收：`node tests/frontend/smoke.js` **78/78 全绿**（新增 `[agent image bubbles]` 9 项）；
> `scripts/render_pages.py` 重渲染后复跑仍全绿；全量 `pytest` 1283 passed / 0 failed。
> **未做**：中英日韩四语浏览器实测（本机只跑 jsdom 冒烟，无真人四语目检）——
> i18n 键已补齐 `btn_ask_ai` / `thumb_zoom` / `err_image_unavailable` 三语言组，视觉一致性待人工目检。

### M6 · 编辑指令桥接（可选，≈1.5 天）
- 目标：VLM 输出的自然语言修改建议（如「把背景换成雪天」）解析为结构化 edit 指令 → 一键发编辑请求。
- 落点：
  - `native/vlm_engine.py` 加 `parse_edit_intent(text) -> EditIntent | None`（prompt 里预置 few-shot）
  - `chat.js` 消息下方出现「执行编辑」按钮 → 携当前图 + intent 调 edit
- 验收：`tests/integration/test_vlm_edit_bridge.py` mock VLM 输出验证解析/调用链。

> **M6 落点更正（2026-10-01 实证）**：文档原写的 ``POST /api/generate?mode=edit`` **在本仓不存在**
> （与 M3 的 `filter_output` 同类的文档失真）。全仓 grep 复核：``generate_routes.py`` 只有
> `POST /api/generate`（txt2img）与 `POST /api/generate/batch`，**没有**任何 `mode=edit` 参数。
> 真实编辑入口是同一端点的**请求体字段** ``edit_mode: true`` + ``reference_image_path``
> （见 `services/generation_service.py`：引擎 `supported_features` 不含 edit、或缺参考图 → 422）。
> 故桥接按真实契约发 `POST /api/generate`，并在测试里把「intent 能落成一份合法编辑请求」钉住。
>
> **M6 验证状态（2026-10-01 收口）**：后端解析 + 编排下发 + 前端桥接已落地并通过门禁——
> `native/vlm_engine.py` 加 `EditIntent` / `parse_edit_intent` / `strip_edit_block` / `build_edit_few_shot`，
> 口径是**只认定界标记、绝不关键词猜**（没吐 `[[EDIT]]...[[/EDIT]]` 就返回 `None`，宁可前端不出按钮，
> 也不能把「这张图很好看」当 prompt 去改用户的图）；`orchestrator._run_turn_impl` 在**本轮带图**时才解析，
> 命中则随 `final` 事件下发 `edit_intent{prompt, source, reference_images, engine_name}`，
> 编辑引擎名由注入的 `edit_engine_fn` 解析（与 M2 `vlm_context_fn` 同款注入式，不读全局 config，抛异常也不吞掉整轮）；
> `strip_edit_block` **只摘标记符号、保留块内提示词**——用户点「执行编辑」前必须看得见将要执行什么，
> 整块删掉等于让人点一个看不见的动作。
> 前端 `chat.js` 在助手气泡下挂「执行编辑」按钮（`data-agent-edit` 可被断言识别），
> 点击才 `POST /api/generate`；`engine_name` 为 null（无编辑引擎）时按钮 **disabled + 说明文案**，
> **不静默降级**成普通文生图。i18n 五语言补 `btn_run_edit` / `edit_running` / `edit_no_engine`。
> 验收：`tests/integration/test_vlm_edit_bridge.py` **15 例全绿**（提取/不臆造×6/清空标记/编排下发/
> 无图不下发/引擎名 None/解析异常不打断/真实 GenerateRequest 契约）；
> `tests/frontend/smoke.js` `[agent edit bridge]` 11 项（按钮挂载 / 请求体 `edit_mode` / 参考图 /
> prompt 透传 / 后处理关闭 / 无引擎时 disabled）→ 冒烟 **89/89 全绿**；
> `mypy` 98 文件零错、`ruff check` 全通过、全量 `pytest` 1298 passed / 0 failed。
> **未做**：`vlm_context_fn` 与 `edit_engine_fn` 的真实装配接线（依赖 M1 preflight 闭环，本机 Qwen3-VL
> HF 目录未就位）；故前端按钮目前在**结构化的 mock intent → SSE 下发**路径上被验证，
> 尚未接真实 VLM 输出跑过端到端。

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

> **2026-10-01 用户裁定「全部都做」**：以下三项均勾选为「是」，M1 立即开工，M4-M5 前端与 M2-M3 后端同批纳入（按里程碑推进），M6 编辑桥接纳入范围（可延后到 M1-M5 稳定后）。

- [x] 是否启动 M1（VLM 引擎 + 显存策略）
- [x] 若启动，是否要求 M4-M5 前端 UI 与 M2-M3 后端同批发布
- [x] 是否包含 M6 编辑桥接（可延后到 M1-M5 稳定后）

以上任一决策为「是」即可开工；M1 完成前不合并 M2。
