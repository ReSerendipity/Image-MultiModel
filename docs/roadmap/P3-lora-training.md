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
| **transformer 权重管线能否跑通**（2026-10-02 实跑） | ✅ **已实证**：AI-Toolkit 能加载本机 comfy Z-Image 单文件，`torch.equal` 逐张比对 **50/50 一致**，参数量 **6,154,908,736** | `scripts/preflight_zimage_lora_load.py` rc=0（含融合 qkv 拆分验证） |
| transformer 权重的一个**必做适配** | ⚠️ comfy 权重带 `model.diffusion_model.` 前缀，AI-Toolkit **不剥离** → 直接喂会 `RuntimeError`（missing 全部 diffusers 键 / unexpected 全部 comfy 键）。**在内存改键名即可**（mmap 共享，无需复制 6GB） | GOTCHAS #46 |
| **TE 侧**（2026-10-02 实跑） | ✅ **已转换并验证**：comfy TE 是**逐层不同量化方案**的混合包（`q_proj` 有 `[4096,2560] F8_E4M3` 也有 `[4096,1280] U8` 打包，手搓反量化必错）→ 改由 AI-Toolkit 自己加载后落标准 HF 目录（补绑权 `lm_head`）。回读 398 张量 / 4.02B 参数，前向 37 层隐状态、logits `(1,7,151936)` 正常 | GOTCHAS #46.5 / #46.6 |
| **VAE 侧**（2026-10-02 实跑） | ✅ **已转换并验证**：comfy `ae.safetensors` 是 LDM 键风格且**没有** `quant_conv`（AI-Toolkit 自带 `convert_ldm_vae_checkpoint` 不适用）→ 自写映射覆盖 244/244 键，`strict=True` 零缺失，latent `(1,16,32,32)`，**重建 PSNR 40.24 dB** | GOTCHAS #46.4 / #46.7 |

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
| T-12 | 训练模块设计 / 实现 | ✅ **2026-10-02 完成**：最小 Z-Image LoRA job **实跑通过（rc=0）**，产物 LoRA **可被 `native/lora.py` 加载** | 见下方「T-12 实跑记录」 |
| T-13 | 训练 UI（轻前端 + 状态回写薄层） | ✅ **2026-10-03 完成**：编排薄层实装 + **真跑实证**（2 步 job rc=0，进度/产物/移交全链路通）；UI 面由 AI-Toolkit 自带前端承担，本仓只做编排与状态回写 | 无（见下方「T-13 编排薄层实装记录」） |
| T-14~T-16 | 其余训练相关（数据准备 / 采样 / 元数据） | ⬜ 未启动 | T-12 代码接入 |

## 阻塞 / 前置

- ⚠️ **reference_repos 部分恢复（2026-10-02）**：T-28 所需的 `sd-scripts` 已完整克隆到
  `C:\Users\Doro\reference_repos\sd-scripts`（git clone 成功）。**AI-Toolkit 整仓 clone 连续两次
  `fatal: the remote end hung up unexpectedly`**，改用 GitHub API（`api.github.com` 的 contents 接口）
  按需单文件拉取到 `reference_repos/AI-Toolkit-src/`（`z_image.py` / `resolver.py` / `flux.py` / `README.md`
  等）——**这条路比整仓 clone 稳得多，大仓研究建议默认走 API 按需拉**。
  ✅ **AI-Toolkit 完整工作区已拿到（2026-10-02）**：走 codeload zip（35,813,488 B，17 分钟），已解压到
  `C:\Users\Doro\reference_repos\AI-Toolkit\ai-toolkit-main`；依赖用 `--system-site-packages` 的独立
  venv（`C:\Users\Doro\AI-Toolkit-env`）共享本机 torch 2.11 / diffusers 0.40，只补装 peft / torchao /
  lycoris-lora / flatten_json / python-dotenv（**不污染项目 Python 环境**）。详见 GOTCHAS #46.1。
- ✅ **训练已在本机跑通过两次**（T-12 smoke job、T-13 编排薄层真跑，均 `rc=0`），选型不再是纯源码级实证。
  但选型阶段的文档口径保留：**选型结论来自源码级查证**，运行级证据是后补的（T-12 / T-13 实跑记录）。
  文档里仍不许把源码结论冒充跑通结论。
- 项目当前纯推理架构（已接入 5 个 native 引擎），训练模块需新建独立子系统（不与推理任务队列冲突）；
  训练产物要能被现有 `native/lora.py` 栈加载复用。

## T-12 实跑记录（2026-10-02，最小 smoke job）

**命令**：`cd reference_repos/AI-Toolkit/ai-toolkit-main && <AI-Toolkit-env python> run.py <job.yaml>`（`rc=0`）

**job 配置**（512² / 10 步 / rank 4 / adamw lr 1e-4 / bf16 / `cache_text_embeddings` / `low_vram`）：
- `model.name_or_path` = 本机 comfy Z-Image 单文件（fp8，带 `comfy_quant` 标记）
- `model.extras_name_or_path` = 本机组装的 extras 目录（`transformer/config.json` + 转换后的 `text_encoder/` + `vae/` + `tokenizer/`，全 HF 布局）
- `datasets` = 4 张 512² 图 + caption

**实测过程**：模型加载 → LoRA 网络 **240 modules** → 4 图分桶 `512x512` → latent 落盘缓存 →
基线采样 → 10 步训练（loss 从 `3.73e-01` 走到 `3.65e-01`，约 85–115 s/步，RTX 5070 Ti Laptop 11.9GB）→ 存档 + 采样。

**产物**（`zimage_lora_smoke/`）：`zimage_lora_smoke.safetensors` **21.3 MB**（480 键 = 240 模块 × lora_A/lora_B）、
step-5 中间存档、`optimizer.pt`、基线/最终采样图各 1 张。

**产物能否被 `native/lora.py` 加载**：✅ **能，且无静默丢弃**——走 comfy `load_lora_for_models` 实测
`patches = 180`、`"lora key not loaded"` 告警 **0 条**。180 = 30 层 × 6 模块
（`feed_forward.w1/w2/w3`、`adaLN_modulation.0`、`attention.qkv`、`attention.out`）；
diffusers 布局的 `to_q/to_k/to_v` 被 comfy **融合映射**到自己的 `qkv`（3→1，故 240 模块 → 180 patch，少 60），
`to_out.0` → `out`。判据是**「未加载告警为 0」而不是 patch 数**（详见 GOTCHAS #47）。

**口径边界（不许抬高）**：这是**管线跑通**的实证，**不是**「训出了好 LoRA」——10 步、4 张图、无收敛验证，
产物的实际视觉效果未评测。真实训练（数据量/步数/分辨率/评测）属后续 T-14~T-16 与 T-13 前端的工作。

## T-13 编排薄层实装记录（2026-10-03）

**定位边界（先划清，不许抬高）**：本仓**不出训练 UI**。AI-Toolkit 自带前端（仓库内 `ui/` 是 Next.js，
入口 `run_windows.bat` → `python -m manager launch`）承担训练界面的全部交互；本仓薄层只负责
「任务编排 → 调用 AI-Toolkit → 解析产出 → 状态回写 / 产物移交」，两者通过薄层产出的 `job.yaml` 与
`loss_log.db` 互通。

**新增模块**（新增文件，未改动任何 pinned 核心模块 → 完整性清单无需重签，`33/33 ✓` 保持通过）：

| 模块 | 职责 |
|---|---|
| `app/integrated_app/training/spec.py` | `TrainJobSpec`：job 参数模型 + 提交前校验（name 正则 / 路径绝对且存在 / model 是文件、extras-dataset 是目录 / resolution 16 倍数 / 数值下限 / dtype 白名单）+ 渲染 AI-Toolkit job 配置 |
| `app/integrated_app/training/store.py` | 状态记录：`<data>/training/jobs/<job_id>.json` 原子写（临时文件 + `fsync` + `os.replace`），全局写锁串行化后台泵与请求线程 |
| `app/integrated_app/training/progress.py` | 进度回读：只读 sqlite 回读 `loss_log.db` + stdout 日志尾部（尾读 `max_bytes` 上限） |
| `app/integrated_app/training/handoff.py` | 产物发现（终稿 / 中间档 / optimizer / 采样图 / config）+ 移交**规划**（只读给命令），搬运需显式发起 |
| `app/integrated_app/training/runner.py` | 编排核心：`submit`（校验→落 `job.yaml`→`Popen(run.py)`）→ 后台泵逐行落盘 `stdout.log` → 退出码定终态并回写 |
| `app/integrated_app/routes/train_routes.py` | HTTP 面 `/api/train/*`：`status / jobs / jobs/{id} / logs / artifacts / cancel / handoff / lora`（靠 `app_server` 的路由自动发现注册，**未改任何既有文件**） |

**真跑实证**（走薄层自己的 `submit()`，不是手敲 job.yaml）：

- 环境：`AITK_ROOT=<AI-Toolkit 仓库根>`、`AITK_PYTHON=<AI-Toolkit-env 解释器>`（**薄层不内置本机绝对路径**，
  两个环境变量驱动；`pre-commit` 的 `check_no_hardcoded_paths.py` 会拒收硬编码）。
- job：`t13_probe`，512² / **2 步** / rank 4 / adamw lr 1e-4 / bf16 / `low_vram` / `save_every=1` /
  `logging.use_ui_logger=True` / `log_every=1`，4 张 512² 图（latent/TE 缓存命中 T-12 那份）。
- 实测链路：`submit → running` →（轮询）`step=1 / total=2 / percent=50.0 / latest={learning_rate, loss/loss}` →
  `completed exit=0` → `artifacts` / `handoff_plan` / `logs` 全部正常返回。
- 产物（`data/training/<job_id>/t13_probe/`）：终稿 `t13_probe.safetensors` 21,318,744 B、
  中间档 `t13_probe_000000001.safetensors` 同体积（二者只差后缀，**所以判终稿必须名字精确相等**）、
  `optimizer.pt` 85.4 MB、`config.yaml`、采样图 2 张。
- 进度回读实证：`loss_log.db` 真实 schema = `steps(step, wall_time)` / `metrics(step, key, value_real, value_text)` /
  `metric_keys(key, first_seen_step, last_seen_step)`，WAL 模式；训练进程**正在写**时薄层用 `mode=ro` 只读连接
  照样读到数（不会抢写锁）。`use_ui_logger=False` 时根本不产这个库（T-12 那份就没有）。

**真跑抓出并修掉的两个真缺陷**（这正是"先真跑再下结论"的价值）：

1. 训练跑到 `completed` 后，接口回的 `progress.step` 仍是 `None`——因为进度刷新只改内存、非终态轮询不落盘，
   泵线程写终态时又没刷新。修：`_JobProcess._pump()` 定终态前补一次 `_refresh_progress()`，`cancel()` 同理。
2. 移交计划的 `target_dir` 成了**相对路径** `loras`——`Path("")` 归一化成 `Path(".")`，`str()` 是 `"."` **真值**，
   判空用 `str(Path(x))` 永远走"有值"分支。修：判空改用原始字符串。

（另在单测层抓到的两个：`training_folder` + `save_root` 双重拼接导致产物永远找不到；中间档识别按下划线判断会
把带下划线的 job 名自己的终稿误判成中间档。四条全部落 GOTCHAS #48.1~48.4 + 回归测试。）

**门禁**：`ruff check` / `ruff format --check` 全绿、`mypy app/integrated_app` `Success: no issues found in 105 source files`、
训练相关测试 **65 passed / 1 skipped**（`test_training_{spec,store,progress,handoff,runner}` + `test_train_routes`）、
`check_spec_refs --self` PASS、`check_config_refs` 通过、`check_integrity_manifest` `33/33 ✓`、
`check_no_hardcoded_paths` rc=0。

**口径边界**：这是**编排链路跑通**的实证（薄层能把事情送进 AI-Toolkit 并回读状态与产物），
**不是**「训练 UI 已完成」——交互界面仍是 AI-Toolkit 自带前端；真实训练的数据量/步数/收敛/视觉评测属 T-14~T-16。

## 验收（本 P3 立项目标）

- [x] T-34 决策记录（本文件 + README 索引）。
- [x] 训练后端选型 POC（2026-10-02 源码级实证）：路径 A（AI-Toolkit）胜出；路径 B 前提被证伪；sd-scripts 对 Z-Image 不适用。
- [x] T-22（Caption / Tagger 评估，改为不引入 SDNext，用 AI-Toolkit 内置 captioner + dataset_tools）。
- [x] T-28（sd-scripts LUMINA 深读：只吃 NextDiT_2B，且 `strict=False` 会静默错配）。
- [x] T-12 代码接入：安装 AI-Toolkit → 最小 Z-Image LoRA job 跑通（rc=0）→ 产出 LoRA 能被 `native/lora.py` 加载（180 patches / 0 条未加载告警）。
- [x] T-13 轻前端 / 状态回写薄层（2026-10-03：编排薄层实装 + 真跑实证 2 步 job rc=0；**UI 面采用 AI-Toolkit 自带前端，本仓只做编排与状态回写**，见「T-13 编排薄层实装记录」）。
- [ ] T-14~T-16（数据准备 / 采样 / 元数据）随 T-12 推进。
