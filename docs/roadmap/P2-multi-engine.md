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
| Qwen-Image 2.1 基座 | ✅ `qwen_image_native`（2026-10-02 已实证出图） | steps=8/cfg=1 + latent 64/16 | 512²/8 步采样 18.5s 可行；1024²（引擎默认）未实跑 |
| Flux.2 Klein | ✅ `flux2_klein_native`（已验收） | 9B fp8 + qwen3_8b TE | 已验证可行（euler/simple） |
| flux.1-dev | ✅ `flux1_dev_native`（2026-10-02 已实证出图） | 12B fp8 + **双 TE**（t5xxl + clip_l）+ **guidance 3.5** | 256²/4 步 euler+simple 可行；1024²（引擎默认）未实跑 |
| krea2_turbo | ✅ `krea2_turbo_native`（2026-10-02 已实证出图） | turbo 低步数 + latent 16/Wan21 空间 8 | 512²/4 步 euler+simple 可行；1024²（引擎默认）未实跑 |

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

- ✅ **产物元数据入库已 stat 磁盘（2026-10-01 冒烟发现 → 已由 `fb955b7` 修复，2026-10-01 复核关闭）**：`services/task_worker.py` 的 `_probe_output_metadata()` 真读磁盘尺寸/像素、`compute_file_sha256()` 落输出指纹，worker 落库时把非 0 的 `file_size / width / height / sha256` 写入 `history_db.outputs`（见 L200–219）。回归测试 `tests/test_output_metadata_probe.py` 锁定该行为（probe 真实尺寸 + worker 链路落库非 0）。本开放问题关闭。

- ✅ **`qwen_image_native` 已于 2026-10-02 实证出图闭环（原「权重阻断」结论被实证推翻）**：`config.yaml` 已注册 `qwen_image_native`（`backend: native` / `supported_features: [txt2img]` / `latent_channels: 64` / `latent_downscale: 16`，latent 沿用 Qwen-Image 2.1 edit 同架构实测值）；`model_registry` 对 native backend（无 role）正确分发 `NativeEngine`，**复用现有 txt2img 链路，无需新引擎类**；新增 `scripts/preflight_qwen_image.py`（Klein 实证法复用：真加载 UNet/TE/VAE + 试 (sampler,scheduler) 出图）与回归测试 `tests/native/test_qwen_image_native.py`（config 结构 + 分发 + 离线阻断断言）。
  **「权重阻断」是被实证推翻的旧结论（2026-10-02）**：旧判据是「本地库仅有 edit 基座 unet，缺 txt2img 基座」，从而把 `qwen_image_native.unet.sub_path` 写成一个**根本不存在的文件名** `qwen_image_2.1_base_int8_convrot.safetensors`，preflight 因此永久走 SKIPPED(2) 分支。实测订正：
  - **架构层**：`comfy_kernel/comfy/ldm/qwen_image21/model.py` 的 `QwenImage21Transformer2DModel.forward(..., ref_latents=None, image_slots=None)` 中参考图 latent **可选**，`build_sequence` 在 `ref_latents` 为空时只处理文本 token —— **同一份 UNET 既做 txt2img 也做 edit**，`qwen_image_edit_native` 用的就是本机唯一那份 `qwen_image_2.1_int8_convrot.safetensors`，它可直接文生图，不需要额外下载。
  - **实证**：`scripts/preflight_qwen_image.py --unet <真> --te <真> --vae <真> --w 512 --h 512 --steps 8` → `model_sampling=ModelSampling`、采样 `(1,64,32,32)` 18.5s、VAE 解码 `(1,512,512,4)`、落盘 `outputs/_preflight_qwen_image/qwen_euler_simple.png`（出图内容 = 灰白猫趴木桌，与 prompt `a cat sitting on a wooden table` 吻合，已人工目检）。
  - **落地**：`config.yaml` 的 `unet.sub_path` 改为真实文件、回填 `sampler=euler` / `scheduler=simple`；回归测试 `tests/native/test_qwen_image_native.py` 由「离线阻断断言」反转为「unet 指向真实文件 + 与 edit 共用同一份 + sampler/scheduler 与 preflight COMBOS 首项同步」。
  - **观察（未改代码）**：preflight 日志里 `latent_format = NoneType`，即 Qwen-Image 的 model 对象不挂 `latent_format` 属性，latent 尺寸实际由 `config.yaml` 的 `latent_channels=64` / `latent_downscale=16` 驱动（与实测一致）。**改这两个 config 值前必须重跑 preflight**，否则会静默按旧尺寸造 latent。

- ✅ **`krea2_turbo_native` 已于 2026-10-02 实证出图闭环（2026-10-01 评估时的「权重阻断」结论同样被推翻）**：`config.yaml` 已注册 `krea2_turbo_native`（`backend: native` / `supported_features: [txt2img]` / `unet.key_prefix: model.diffusion_model.` / `text_encoder.clip_type: krea2` / `latent_channels: 16` / `latent_downscale: 8` / `sampler=euler` / `scheduler=simple`）；新增 `scripts/preflight_krea2_turbo.py` 与回归测试 `tests/native/test_krea2_turbo_native.py`（17 例：config 结构/权重存在/两处新字段/sampler 与 preflight COMBOS 首项同步、加载选项解析不污染路径字典、executor 两处加载定制的委托行为、engine→executor 合并传参的变异可测断言）。
  推翻要点（详见 `docs/agents/GOTCHAS.md` #41/#42）：
  - **权重其实一直在本机**：`unet/Krea2-turbo/`、`text_encoders/Krea2/`、`vae/Qwen-image-2512-edit + Krea2/` 三处都在 ComfyUI 模型库里，只是本仓 `pretrained_models/` 没挂 junction、config 没写；上一版「权重阻断」是把 `pretrained_models/*` 下**已 junction 的三组**当成了全部。
  - **UNET 只能用 AIO 那份**：同目录 `krea2_turbo_fp8_scaled.safetensors` 被 safetensors rust 后端 0.8.0 拒绝（`file not fully covered`，多轮受控对照实验排除 junction/体积/头覆盖/量化元数据后判定为该文件 fp8 描述符问题）；AIO 那份走「`load_torch_file` → 剥 `model.diffusion_model.` 前缀 → `load_diffusion_model_state_dict`」（`load_diffusion_model` 无 prefix 参数）。
  - **TE 必须枚举、latent 必须 5D**：Krea2 的 TE 要 `CLIPType.KREA2` **枚举**（字符串 `"krea2"` 不等价 → 单层 2560 维 → 前向 30720 维报错）；latent 必须 `[1,16,1,H/8,W/8]`，4D 会被当 16 个时间帧产出 61 帧废图（已目检）。
  - **实证**：512²/4 步/euler+simple → `sampled (1,16,1,64,64)` → `decoded (1,512,512,3)` → 落盘 `outputs/_preflight_krea2/krea2_euler_simple.png`（黑白猫端坐木桌，与 prompt `a cat sitting on a wooden table` 吻合，已人工目检）。
- ✅ **`flux1_dev_native` 已于 2026-10-02 实证出图闭环（2026-10-01 评估时的「权重阻断」是第三次被推翻）**：`config.yaml` 已注册 `flux1_dev_native`，且为它新增了两处**向后兼容**的 schema 能力：
  - `ModelPaths.sub_paths`（同角色的附加权重，各带自己的 `sub_dir`）——FLUX 的 clip_l 挂在 `models/clip/FLUX.1-dev/`、t5xxl 挂在 `models/text_encoders/FLUX-1-dev/`，现有「一角色一 sub_dir」表达不了；
  - `EngineConfig.guidance`（FLUX 系 guidance，0 = 不注入，沿用 `model_base.Flux.concat_cond` 内建 3.5）。
  新增 `scripts/preflight_flux1_dev.py` 与回归测试 `tests/native/test_flux1_dev_native.py`（18 例，含三处接线的**变异验证**）。**至此 P2-multi-engine D 项目标引擎全部实证收口，无未开工项。**
  推翻要点（详见 `docs/agents/GOTCHAS.md` #43 及 43.1/43.2/43.3）：
  - **权重一直在本机**：`unet/FLUX-1-dev/` 4 份 + `text_encoders/FLUX-1-dev/t5xxl_fp8_e4m3fn.safetensors` + `clip/FLUX.1-dev/clip_l.safetensors` + `vae/FLUX.1-dev(Z-image(turbo))/ae.safetensors` 全在 ComfyUI 模型库，只是没建 junction、没写 config。
  - **选 `fluxNSFWUNLOCKED`**：fp8 **E4M3**（`Flux-Capacity-NSFW-V2-fp8` 是 E5M2 精度更差），且键带 `model.diffusion_model.` 前缀可直接复用剥前缀逻辑；另两份 `pornworks*` 是裸键。
  - **三处架构适配**（缺一不动图）：双 TE 一次 `load_clip` 传两个文件 / guidance 手工注入 cond 字典（executor 无 comfy_extras `Guidance` 节点）/ latent 是 **4D `[1,16,H/8,W/8]`**（`latent_formats.Flux` 继承 SD3，与 Krea2 的 5D 相反）。
  - **实证**：256²/4 步/euler+simple/guidance 3.5 → 采样 `(1,16,32,32)` 15.3s → `decoded (1,256,256,3)` → 落盘 `outputs/_preflight_flux1_dev/flux1_euler_simple.png`（橘白猫趴木桌，与 prompt `a cat sitting on a wooden table` 吻合，已人工目检）。
  - **拼写级坑**：VAE junction 名是 `FLUX.1-dev`（点号）不是 `FLUX-1-dev`；写错在 YAML 里语法合法、`resolve` 也照样拼路径，直到 load 才炸——已靠解析探针逐条 `exists` 兜住，并写进测试。
- ⚠️ widget 双处同步坑：aki-v3 工作流 JSON 的 `widgets_values`（positional）与 `widgets_values_named` 可能不同步，子图容器与内部还可能三处冲突 → **移植时一律读容器 positional 并实机验证**（详见蓝图「已知坑」）。
- 多引擎 UI 过滤：README 已移除「全部 / Native」过滤项、简化为直接列引擎；新增引擎后需确认前端引擎列表渲染无回归。
- 无独立阻塞，架构层已支持。
