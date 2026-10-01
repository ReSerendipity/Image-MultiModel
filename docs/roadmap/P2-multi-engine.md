# P2 — native 多引擎接入（后续可选演进）

> 状态：🟡 待办（目标引擎已选定：**Flux.2 Klein 9B fp8**；权重本机三件套齐全）
> 关联：`workflows/blueprints/README.md`（移植参考蓝图）、`docs/roadmap/README.md`（总索引）

## 已选定目标引擎：Flux.2 Klein 9B（fp8）

选定依据（本机实扫证据，非估算）：

| 组件 | 选定文件 | 体积 | 来源 |
|---|---|---|---|
| UNet | `FLUX-2-klein-9b/DarkBeast-Klein9b-V2-BFS-FP8.safetensors`（或 `BigLoveKlein2_fp8`，同 8.46GB） | 8.46 GB | aki-v3 `models/unet/FLUX-2-klein-9b/` |
| Text Encoder | `FLUX-2-klein-9b/qwen_3_8b_fp8mixed.safetensors` | 8.07 GB | aki-v3 `models/text_encoders/FLUX-2-klein-9b/` |
| VAE | `FLUX.2-klein-9b/`（目录已存在） | — | aki-v3 `models/vae/FLUX.2-klein-9b/` |

**内核可行性（vendored `comfy_kernel` v0.38.0）**：
- `comfy_kernel/comfy/model_detection.py:266` → `dit_config["image_model"] = "flux2"`（可识别 Flux2 权重）
- `comfy_kernel/comfy/model_base.py` → 含 flux2 基类
- `comfy_kernel/comfy/latent_formats.py:197` → `class Flux2(LatentFormat)`（Flux2 latent 格式齐备）

**未走 diffusers 后端的原因**：`native/diffusers_engine.py` 是 **Z-Image 专用**（`ZImagePipeline`），非通用 Flux 路径；故新增引擎走 **native 后端 + 扩展 executor 到 Flux2 族**。

⚠️ **显存现实（须实测）**：UNet 8.46GB + TE 8.07GB ≈ **16.5GB**，超出 RTX 5070 Ti Laptop 的 12GB VRAM
→ 必须依赖 CPU/RAM offload（ComfyUI DynamicVRAM 机制），可接受但会降速；需实机验证 offload 可行性与耗时。

## 目标

在现有「进程内原生引擎 `NativeEngine`」框架内，把更多文生图/图生图模型接入为独立引擎条目，
让用户可在引擎菜单切换（如 Z-Image 系列、Qwen-Image、Flux.2 Klein、Krea2、flux.1-dev），
而非仅 `z_image_turbo_native` 与 `qwen_image_edit_native`。

## 当前已就绪（无需从零搭建）

| 能力 | 现状 | 证据 |
|---|---|---|
| backend 分发机制 | 按 `config.yaml` 引擎条目的 `backend` 字段，经 `ModelRegistry.create_engine_instance` 分发 `native` / `diffusers` / `comfy` | `app/integrated_app/routes/engine_routes.py:27-49` |
| native 推理模块 | `native/` 已含 `source / executor / engine / edit_executor / diffusers_engine / seedvr / lora / compares / vram / preview` | `app/integrated_app/native/` |
| 已注册引擎 | `z_image_turbo_native`（`config.yaml:36`，`backend: native`）、`qwen_image_edit_native`（`config.yaml:82`，`backend: native`） | `config.yaml` |
| 移植事实基线 | 6 类文生图工作流的节点构成/模型依赖/采样参数/LoRA 已分析落地 | `workflows/blueprints/manifest.json` + `scripts/analyze_workflows.py` |

## 候选引擎（来自蓝图 `workflows/blueprints/Image/`）

| 工作流（蓝图） | 候选引擎 key（建议） | 关键参数（容器 positional 实测） | 显存评估（12GB） |
|---|---|---|---|
| Z_image_turbo | ✅ 已实现 `z_image_turbo_native` | steps=8/cfg=1/euler | 已验证可行 |
| Z_image | `z_image_native` | 需实测 | 待实测 |
| Qwen_image ×3 | `qwen_image_native` | steps=8/cfg=1（见蓝图注） | int8_convrot 可纳入预算 |
| Flux.2 Klein | `flux2_klein_native` | 9B fp8 + qwen3_8b TE | 需 offload 实测 |
| flux.1-dev | `flux1_dev_native` | 12B fp8 | 边界，需 offload |
| krea2_turbo | `krea2_turbo_native` | turbo 低步数 | 待实测 |

## 接入步骤（每新增一个引擎）

1. 权重落位：按 `mount_map` 把模型放入 `pretrained_models/`，在 `config.yaml → models.engines.<key>` 填 `unet/text_encoder/vae` 的 `sub_path`；
2. 采样映射：`native/executor.py` 增加该模型的 KSampler 7 元组（seed/control/steps/cfg/sampler/scheduler/denoise）映射，以**容器 positional 为运行时真值**；
3. TE 编码：在 native 工作流构建器接入对应 `TextEncode*`（如 `TextEncodeQwenImage21`），接入前先 preflight `comfy_kernel` + 自定义节点路径 `import` 可用性；
4. preflight 自检：启动期校验权重存在 + 量化分支（12GB 优先 int8_convrot / fp8）；
5. 回归测试：补 `tests/test_native_*.py` 覆盖新引擎加载/出图（沿用现有 `NativeEngine` 安全测试范式，含 `PathGuard` 路径穿越拒绝）。

## 验收标准（升为「待办」后）

- [x] 目标引擎在 `config.yaml` 注册（`flux2_klein_native`，2026-09-30）、配置解析 + 三权重路径可达已验证；
- [x] 实机（RTX 5070 Ti 12GB）出图成功 —— preflight 实测：UNet+TE+VAE 真加载，512²/4 步出图成功并存盘
      （`outputs/_preflight_flux2klein/klein_euler_simple.png`，照片级质量；采样含 offload 约 28~112s 视负载）；
- [x] 采样参数实测确定：`sampler=euler` + `scheduler=simple`（euler/beta、euler/sgm_uniform 未及测，首组合即通过）；
- [x] 回归测试全绿——2026-10-01 UI/UX 审计 P4 收尾后全量 pytest 跑通（**1235 passed / 7 skipped / 0 failed**，163s），mypy ratchet 定向 `app/integrated_app` 同时零错；本次改动涉及 `history_db.py` 已在 hash 监管内，重跑 generate→sign 两步后清单会签完整；
- [x] `POST /api/engine/load` + `POST /api/generate` 真实 API 端到端冒烟——2026-10-01 于 8288 服务实测：`engine_name=flux2_klein_native` 先加载（18s，17GB 权重）后提交 `512×512 / steps=4 / cfg=1.0 / seed=42`，任务 `f806a6edb0af4277` 最终 **completed**，总耗时 243s（含 offload），产物 `outputs/flux2_klein_native/20261001/000001a0f70c9e35_0_AI.png`（335 KB 真实 PNG）；发现小遗留：`outputs.file_size/width/height/sha256` 入库时为 0/空（未 stat 磁盘），不阻塞验收，已归入下方开放问题。

## 实现记录（2026-09-30）

| 改动 | 文件 | 说明 |
|---|---|---|
| sampler/scheduler 下发 | `engine_interface.py`（GenerationConfig）、`config_models.py`（EngineConfig）、`generation_service.py`、`native/executor.py` | 采样器/调度器不再硬编码 Z-Image 常量；按引擎配置下发，空值回退 Z-Image 默认 |
| 引擎注册 | `config.yaml` → `models.engines.flux2_klein_native` | `latent_channels: 128` / `latent_downscale: 16` **必须显式**（实测 `model.latent_format` 为 None，缺省会误回退 Z-Image 的 16/8）；`sampler: euler` / `scheduler: simple` |
| 权重挂载 | `pretrained_models/{unet,text_encoders,vae}` 三个 junction | 与既有引擎同款做法，指向 aki-v3 真实权重 |
| preflight 脚本 | `scripts/preflight_flux2_klein.py` | 真加载+小分辨率出图的接入前自检工具（复用于未来新引擎） |

**⚠️ 改动核心模块后的必做步骤（2026-09-30 实证踩坑）**：`config_models.py` / `engine_interface.py` 在完整性清单内，
改动后启动会因清单过期直接拒绝启动（enforce）。必须依次执行：
`python scripts/generate_integrity_manifest.py` → `python scripts/sign_integrity_manifest.py`。

## 开放问题 / 阻塞项

- ⚠ **产物元数据入库未 stat 磁盘（2026-10-01 端到端冒烟发现）**：任务 completed 后 `history_db.outputs` 行的 `file_size / width / height / sha256` 均为 0/空，磁盘上真实 PNG 存在（335 KB）；不阻塞出图与展示（前端直接读文件），但影响历史统计、去重与图库卡片预渲染。下一小步：`native/preview.py` 或 `generation_service` 写 outputs 前用 `PIL.Image.open + stat` 与 `hashlib.sha256` 补上；参考 `tests/integration/test_forward_path_api.py` 的产物断言。
- ⚠️ widget 双处同步坑：aki-v3 工作流 JSON 的 `widgets_values`（positional）与 `widgets_values_named` 可能不同步，子图容器与内部还可能三处冲突 → **移植时一律读容器 positional 并实机验证**（详见蓝图「已知坑」）。
- 多引擎 UI 过滤：README 已移除「全部 / Native」过滤项、简化为直接列引擎；新增引擎后需确认前端引擎列表渲染无回归。
- 无独立阻塞，架构层已支持。
