# Third-Party Notices（第三方组件声明）

> 更新日期：2026-09-02。本清单非穷尽：完整依赖以 `requirements.txt` / `requirements-lock.txt`
> 及安装环境的 `pip freeze` 为准；各组件许可以其官方仓库与包内 LICENSE 为准。

## 项目主许可

Image MultiModel 项目代码采用 [Apache License 2.0](LICENSE)。

## 核心推理引擎

### z_image_turbo_native（默认引擎，backend: native）

- **组件**：进程内原生引擎，复用本地 `comfy_kernel/`（vendored ComfyUI 内核源码）实现 Z-Image-Turbo 推理
- **引擎 key**：`config.yaml → models.engines.z_image_turbo_native`（`backend: native`）
- **上游**：<https://github.com/Comfy-Org/ComfyUI>（Comfy-Org）
- **许可（核心合规点）**：vendored `comfy_kernel/` 为 [GNU GPL v3.0](https://www.gnu.org/licenses/gpl-3.0.html)
- **分发义务**：分发本项目需遵守 GPL-3.0（随附许可文本、提供源码获取方式、保留版权声明）；`comfy_kernel/` 作为独立 git 仓库由 `.gitignore` 排除，使用前需满足其许可要求。**源码获取方式与分发前自查清单见 `docs/GPL_COMPLIANCE.md`**（vendored 版本 0.32.0，源码对应提交 `9883be7c`）

### Z-Image-Turbo 模型权重（Apache-2.0）

- **组件**：Z-Image-Turbo 模型权重（用户自行下载并放置于 `model/` 目录）
- **上游**：<https://huggingface.co/Tongyi-MAI/Z-Image-Turbo>（通义实验室）
- **许可**：[Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0)；再分发需保留原版权声明

### qwen_image_edit_native（P1 编辑引擎，backend: native，2026-09 接入）

- **组件**：进程内原生引擎，同一 `comfy_kernel/` + `native/edit_executor.py` 走 Qwen-Image 2.1 编辑工作流（Qwen3-VL-8B int8_convrot 作 TE）
- **引擎 key**：`config.yaml → models.engines.qwen_image_edit_native`（`backend: native`）
- **上游**：<https://github.com/QwenLM/Qwen-Image-2.1>（通义千问团队）
- **模型权重许可**：**Qwen Research License**（[官网条款](https://qwenlm.github.io/qwen-research-license/)，非 Apache 2.0）
- **商用**：❌ **仅限非商业**（研究/评估/个人使用）；商业落地需向千问团队单独申请商业授权。官方已澄清**用户输出的图像不属于授权材料**，权利归用户
- **分发义务**：随附 `LICENSE_QWEN_RESEARCH` 或等价引用文本；本项目源码本身仍 Apache-2.0，但打包分发如内含权重（便携包 `pretrained_models/` 挂载模式）需遵守 Qwen Research License 再分发条款；发布前对照 `docs/LICENSE_COMPLIANCE.md`

### flux2_klein_native（P2 多引擎接入首个新引擎，backend: native，2026-09-30 接入）

- **组件**：进程内原生引擎，走 Flux.2 Klein 9B fp8（UNet 8.46 GB + Qwen3-8B TE 8.07 GB + Flux.2 VAE），RTX 5070 Ti 12GB 依赖 offload
- **引擎 key**：`config.yaml → models.engines.flux2_klein_native`（`backend: native`，`latent_channels: 128` / `latent_downscale: 16` 必须显式）
- **上游**：<https://huggingface.co/black-forest-labs/FLUX.2-klein-9B>（Black Forest Labs）
- **模型权重许可**：**FLUX Non-Commercial License**（9B / fp8 / NVFP4 变体均为非商用；官方同时发布 **4B 蒸馏版为 Apache-2.0**，如需商用可切换到 4B）
- **商用**：❌ **仅限非商业**（研究/评估/个人使用），任何商业 API/产品集成均禁止；官方另提供商业授权申请通道
- **分发义务**：随附 FLUX Non-Commercial License 全文与 Black Forest Labs 版权声明；如内含权重（便携包模式）不得用于任何商业分发场景；发布前对照 `docs/LICENSE_COMPLIANCE.md`
- **本项目使用位置**：仅默认权重挂载与本地端到端 preflight；README/许可表已明确标注非商用；桌面分发如需含权重发布，请先切换到 4B 变体或获取商业授权

## 主要 Python 依赖（许可类型为常见归类，以各包 LICENSE 为准）

| 组件 | 常见许可类型 | 说明 |
|---|---|---|
| torch / torchvision / torchaudio | BSD-3-Clause | 推理框架 |
| fastapi | MIT | Web 框架 |
| uvicorn | BSD-3-Clause | ASGI 服务器 |
| pydantic / pydantic-core | MIT | 数据校验 |
| aiohttp | Apache-2.0 | 异步 HTTP 客户端 |
| aiofiles | Apache-2.0 | 异步文件 IO |
| websockets | BSD-3-Clause | WebSocket |
| numpy | BSD-3-Clause | 数值计算 |
| Pillow | HPND（PIL Software License） | 图像处理 |
| opencv-python-headless | Apache-2.0 | 视觉处理 |
| safetensors | Apache-2.0 | 模型权重加载 |
| einops | MIT | 张量重排 |
| transformers | Apache-2.0 | 模型库 |
| PyYAML | MIT | 配置解析 |
| comfy-aimdo | GPL-3.0 | 原生引擎进程内依赖（`tests/conftest.py` 有 `import comfy_aimdo`）；上游 `LICENSE` 首行明示 "GNU General Public License v3.0"。GitHub 标 `NOASSERTION` 仅因许可正文前置了非标准声明，不影响判定。**义务范围同 `comfy_kernel/`**，见 `docs/GPL_COMPLIANCE.md` |
| comfy-kitchen | Apache-2.0 | 原生引擎进程内依赖；与 GPL 无冲突 |

> 商用分发前，建议对 `requirements-lock.txt` 锁定的依赖版本做一次完整许可扫描；尤其注意 `comfy_kernel/` 的 GPL-3.0 义务。
