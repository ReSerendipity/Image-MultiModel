# workflows/blueprints — 外部 ComfyUI 工作流蓝图资产

> 来源:`C:\Users\Doro\APP\ComfyUI-aki-v3\ComfyUI\user\default\workflows\`(用户实机实测工作流)
> 接入日期:2026-09-29 ｜ 分析工具:`scripts/analyze_workflows.py` → `manifest.json`
> 用途:Agent 化 P1(编辑引擎)与 P2(多引擎)的**移植蓝图**,不参与运行时推理(引擎推理由 `native/` 代码构建,`config.yaml → workflow_file` 保持置空)。

## 目录结构

| 路径 | 内容 | 用途 |
|---|---|---|
| `Edit/` | qwen_2_1_edit / qwen_edit_2511 / flux2_klein_edit | **P1 编辑引擎蓝图**(优先级见下) |
| `Image/` | Z_image_turbo / Z_image / Qwen_image ×3 / Flux.2 Klein / flux.1-dev / krea2_turbo | P2 多引擎参考(Z_image_turbo 已实现,作对照) |
| `SeedVR2/` | SeedVR2 / 批量版 | 超分组件参考(native 已内置 seedvr) |
| `skills/` | 6 套提示词写作 SKILL.md(z-image/qwen/flux/krea2/midjourney/dalle3) | Agent L2 风格层素材 |
| `manifest.json` | 全量分析(节点构成/模型依赖/采样参数/LoRA) | 移植前的事实核查基线 |

## Edit 三条工作流移植优先级(P1)

| 工作流 | 优先级 | 关键参数(容器 positional 实测值) | 模型依赖 |
|---|---|---|---|
| `qwen_2_1_edit.json` | **首发** | steps=25, cfg=1, euler/simple, denoise=1, 1024×1024;UNet/TE/VAE = int8_convrot 三件套 | qwen_image_2.1_int8_convrot + qwen3vl_8b_int8_convrot + qwen_image_2.1_vae_bf16 |
| `qwen_edit_2511.json` | 二期 | ⚠️ 子图内 KSampler 为 40 步/cfg 3,但挂 Lightning-4steps LoRA——移植时步数按 LoRA 特性校正为 4,实机验证 | qwen_image_edit_2511(nvfp4/fp8mixed 双量化分支)+ qwen_2.5_vl_7b TE + Lightning LoRA |
| `flux2_klein_edit.json` | 按需 | 74 节点,SamplerCustomAdvanced + CFGGuider + Flux2Scheduler,9 组参考图 | flux-2-klein-9b-fp8 + qwen_3_8b TE + flux2-vae |

## 移植映射建议(JSON → native 引擎代码)

1. **UNetLoader / CLIPLoader / VAELoader 的 widgets** → `config.yaml` 新引擎条目的 `unet/text_encoder/vae` `sub_path`(权重需按 `mount_map` 落位 `pretrained_models/`);
2. **KSampler 7 元组**(seed/control/steps/cfg/sampler/scheduler/denoise)→ `native/executor.py` 采样参数映射,**以容器实例节点 widgets_values 为真值**(manifest 已双列出容器值与子图内部值);
3. **TextEncodeQwenImage21 / TextEncodeQwenImageEditPlus** → native 工作流构建器中的 TE 编码调用;接入前先 preflight:`comfy_kernel` + 自定义节点路径下 `import` 可用性验证;
4. **ComfySwitchNode 分支**(量化切换)→ 不移植到运行时,在 `config.yaml` 固化一个量化选择(12GB 显存:优先 int8_convrot / fp8);
5. **Lightning/ turbo LoRA**(`LoraLoaderModelOnly`)→ 引擎 `lora.py` 已有加载路径,作为引擎内置配方而非用户 LoRA 槽位。

## 已知坑(移植前必读)

- **widget 双处同步**:aki-v3 新版工作流 JSON 的 `widgets_values`(positional,运行时真值)与 `widgets_values_named`(前端元数据)可能不同步;子图容器与子图内部节点还可能三处冲突 → **读容器 positional,实机验证**;
- **显存预算**:RTX 5070 Ti Laptop = 12GB;qwen_2_1_edit(int8_convrot)已实机验证可行;Edit-2511(20B fp8)与 flux2_klein(9B fp8 + 多参考)需实测 offload;
- **qwen_edit_2511 提示词示例**:容器值内含英文指令示例("Change the furniture leather..."),是工作流保存时的测试值,不是固定参数。

## 复查方法

```bash
python scripts/analyze_workflows.py            # 重新生成 manifest.json(带摘要)
python scripts/analyze_workflows.py --quiet    # 静默生成
```
