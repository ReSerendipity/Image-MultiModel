# P3 — LoRA 训练模块（T-34 决策=是 · 2026-10-01 立项）

> 关联：T-34（决策：是否做 LoRA 训练模块）= **是**；`docs/roadmap/README.md` 能力切片总览；
> `docs/repo-analysis/学习报告全量待办任务清单_20260912.md` 领域 C（LoRA 训练）。
> 本文件即 T-34 验收所需的「决策记录」（写入 roadmap）。

## 决策记录（T-34）

- **裁定**：**做** LoRA 训练模块（2026-10-01，用户「全部都做」授权）。
- **依据**：学习报告借鉴价值矩阵把 LoRA 训练列为 P0 高价值（fluxgym / sd-scripts 均为 ★★★）
  但项目当前是**纯推理服务**（无训练模块、无训练路线图）。本决策解除对 T-12~T-16、T-22 的阻塞。
- **落点**：本文件即决策记录，并在 `docs/roadmap/README.md` 能力切片总览新增 P3 行。
- **后端选型（T-12 POC，2026-10-02 源码级实证）**：采用**路径 A — AI-Toolkit 后端 + 轻前端**；
  路径 B（自扩展）与 sd-scripts 均被实证否掉，依据见下节「事实约束」。

## 事实约束（来自复查报告代码级实证，非臆测）

| 约束 | 结论 | 证据 |
|---|---|---|
| sd-scripts 是否支持 Z-Image | ❌ **确认不支持**（2026-10-02 已完整克隆后复核：全仓 `z.?image` / `zimage` **0 匹配**，非「待验证」） | 本机 `C:\Users\Doro\reference_repos\sd-scripts`，`grep -ril "zimage\|z-image" .` 空 |
| sd-scripts 的 LUMINA 训练器能训谁 | ⚠️ **只吃自家 `NextDiT_2B` 结构**：`library/lumina_util.py:47` 硬编码 `NextDiT_2B_GQA_patch2_Adaln_Refiner`，`load_state_dict(..., strict=False)` | `library/lumina_models.py:822` `class NextDiT` 子模块为 `t_embedder/cap_embedder/context_refiner/x_embedder/noise_refiner/layers/norm_final/final_layer/rope_embedder`，**无 `dec_net`** |
| AI-Toolkit 是否支持 Z-Image | ✅ **确认支持**（2026-10-02 源码级）：`toolkit/models/v2/diffusion_models/z_image.py` → `class ZImageTransformer2DModel(DiffusersZImageTransformer2DModel, OstrisModelMixin)` | 同文件 `aitk_comfy_repo = "Comfy-Org/z_image_turbo"`；`convert_state_dict_on_load` 处理 comfy 键（qkv 融合拆 to_q/to_k/to_v、`x_embedder.`→`all_x_embedder.2-1.`、`final_layer.`→`all_final_layer.2-1.`、`.attention.out.`→`.attention.to_out.0.`、`q_norm/k_norm`→`norm_q/norm_k`） |
| AI-Toolkit 认不认本机 Comfy 权重 | ✅ 认，且**直接复用 ComfyUI 目录布局**：`aitk_comfy_weight_names` 列出 `z_image_turbo_int8_convrot.safetensors` / `z_image_turbo_bf16.safetensors`；并专门处理 comfy 的 `.attention.qkv.comfy_quant` 融合量化键（拆成 to_q/to_k/to_v） | 本机 Z-Image 引擎跑的正是 int8_convrot 那份；AI-Toolkit v2 的 `comfy_precision_rank()` 按文件名自动挑量化档位 |
| AI-Toolkit 是否支持 Windows | ✅ 官方支持（`README.md`：`Windows: double-click run_windows.bat`；安装只需 git） | 本机为 Windows 11 + RTX 5070 Ti Laptop 11.9GB，硬约束满足 |
| 本机 ComfyUI（aki-v3）有无训练节点 | ⚠️ **原路线「路径 B 基于 aki-v3 训练节点」前提不成立**：`ComfyUI/custom_nodes/` 下 17 个节点包里**没有任何训练类节点**（无 train / LoRA 训练 / optimizer），全部是推理/加速/显存类 | `ls ComfyUI-aki-v3/ComfyUI/custom_nodes` 全量枚举 + 对 `train/lora/optimizer` 关键字 grep 无命中 |
| 项目当前状态 | 纯推理（多引擎：Z-Image / Qwen-Image 2.1 / Krea2 / FLUX.1-dev / Flux.2 Klein）；`native/lora.py` 仅推理时 LoRA 栈加载，非训练 | 本仓接入记录（`d858d51` 等）+ 复查报告 §3.0 / §3.3 |

## 关键推论

1. **Z-Image LoRA 训练不能直用 sd-scripts**（已复核确认）→ 走 **AI-Toolkit**（T-12 已实证支持 Z-Image + comfy 格式 + int8_convrot）。
2. **sd-scripts 的 LUMINA 训练器≠「能训 Lumina2」**：它硬编码 `NextDiT_2B` 结构，只适用于 Lumina 官方 NextDiT 权重；**训 Z-Image 会「静默错配」**——`strict=False` 不会报键名错误，缺 `dec_net` 整套解码分支也能加载成功，最后训出结构错乱的模型（详见 GOTCHAS #45）。
3. **训练 UI** → 取 AI-Toolkit 自带的轻 UI（它本身就带 `ui/` + `run_windows.bat`，无需 fluxgym 那套 Gradio 外壳），本仓侧只做「任务编排 + 状态回写 + 产物移交推理引擎」的薄层。
4. **Caption / Tagger** → **不需要 SDNext**：AI-Toolkit 内置 `extensions_built_in/captioner`（LMM/LLM 打标）与 `dataset_tools`（数据集合理/分桶）。若将来要 WD14 / DeepDanbooru 这类传统 tagger，再单独接节点，不在 T-22 主路径内。

## 候选实现路径（已选型，2026-10-02）

- ✅ **路径 A — AI-Toolkit 后端 + 轻前端（采用）**：复用 AI-Toolkit 训练器（原生 Z-Image / comfy 权重布局 / Windows 官方支持），本仓只做编排层：job 配置生成 → 调用 AI-Toolkit → 解析产出 LoRA → 回写 `native/lora.py` 可用的栈。
- ❌ **路径 B — 自扩展（否决）**：前提「aki-v3 已装训练节点」被实测证伪（custom_nodes 内无任何训练节点），等于从零自研 LoRA 训练器 + 优化器 + 采样，成本远高于复用 AI-Toolkit。
- ❌ **sd-scripts 路径（否决）**：Z-Image 全仓 0 匹配；LUMINA 训练器结构硬编码且与本机 Z-Image 架构（`zimage_pixel` 像素空间、带 `dec_net`）不兼容。仅作 Lumina 官方权重的备选参考实现保留在 `reference_repos/sd-scripts`。

## 待办（挂原清单 T 项）

| T 项 | 内容 | 状态 | 阻塞 |
|---|---|---|---|
| T-28 | sd-scripts LUMINA 训练深读 | ✅ **2026-10-02 完成**：`load_lumina_model` 硬编码 `NextDiT_2B_GQA_patch2_Adaln_Refiner`（`library/lumina_util.py:47`），`NextDiT` 无 `dec_net`；Z-Image 全仓 0 匹配 → 结论「仅适用于 Lumina 官方 NextDiT 权重，不适用于本机 Z-Image」 | 无（reference_repos/sd-scripts 已克隆） |
| T-22 | Caption / Tagger 评估 | ✅ **2026-10-02 完成**：**不引入 SDNext**——改用 AI-Toolkit 内置 `extensions_built_in/captioner` + `dataset_tools`。例外：若将来要 WD14/DeepDanbooru 传统 tagger 需另接节点 | 无 |
| T-12 | 训练模块设计 / 实现 | 🟡 **选型已定（路径 A）+ 证据链已落**；代码接入未启动 | 下一步：安装 AI-Toolkit 并跑最小 Z-Image LoRA job 做实证（本机未安装，本机 `reference_repos/AI-Toolkit` 未整仓克隆成功——大仓 clone 两次被远端掐断） |
| T-13 | 训练 UI（轻前端 + 状态回写薄层） | ⬜ 待 T-12 实跑验证后设计 | T-12 最小 job 跑通 |
| T-14~T-16 | 其余训练相关（数据准备 / 采样 / 元数据） | ⬜ 未启动 | T-12 代码接入 |

## 阻塞 / 前置

- ⚠️ **reference_repos 部分恢复（2026-10-02）**：T-28 所需的 `sd-scripts` 已完整克隆到
  `C:\Users\Doro\reference_repos\sd-scripts`（git clone 成功）。**AI-Toolkit 整仓 clone 连续两次
  `fatal: the remote end hung up unexpectedly`**，改用 GitHub API（`api.github.com` 的 contents 接口）
  按需单文件拉取到 `reference_repos/AI-Toolkit-src/`（`z_image.py` / `resolver.py` / `flux.py` / `README.md`
  等）——**这条路比整仓 clone 稳得多，大仓研究建议默认走 API 按需拉**。
  若要把 AI-Toolkit 真正装起来跑训练，仍需想办法拿到完整工作区（重试 clone / 下载 codeload zip / 换镜像）。
- ⚠️ **训练尚未在本机跑过一次**：选型是**源码级实证**，不是运行级实证。T-12 代码接入的前置条件是
  「AI-Toolkit 可安装 + 最小 Z-Image LoRA job 跑通」，文档里不许把源码结论冒充跑通结论。
- 项目当前纯推理架构（已接入 5 个 native 引擎），训练模块需新建独立子系统（不与推理任务队列冲突）；
  训练产物要能被现有 `native/lora.py` 栈加载复用。

## 验收（本 P3 立项目标）

- [x] T-34 决策记录（本文件 + README 索引）。
- [x] 训练后端选型 POC（2026-10-02 源码级实证）：路径 A（AI-Toolkit）胜出；路径 B 前提被证伪；sd-scripts 对 Z-Image 不适用。
- [x] T-22（Caption / Tagger 评估，改为不引入 SDNext，用 AI-Toolkit 内置 captioner + dataset_tools）。
- [x] T-28（sd-scripts LUMINA 深读：只吃 NextDiT_2B，且 `strict=False` 会静默错配）。
- [ ] T-12 代码接入：安装 AI-Toolkit → 最小 Z-Image LoRA job 跑通 → 产出 LoRA 能被 `native/lora.py` 加载。
- [ ] T-13 轻前端 / 状态回写薄层（待 T-12 最小 job 跑通后设计）。
- [ ] T-14~T-16（数据准备 / 采样 / 元数据）随 T-12 推进。
