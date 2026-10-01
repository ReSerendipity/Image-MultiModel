# FluxGym 技术学习报告（Image_MultiModel LoRA 训练 UI 对标 · 代码级）

> **性质**：竞品对标学习报告（非建议文档）。事实来自 `C:\Users\Doro\reference_repos\Image_MultiModel\fluxgym` 浅克隆 + `gh api` 实时核验。
> **核验**：`cocktailpeanut/fluxgym` — **3,252★ / MIT / Python(Gradio)** / `pushed_at=2026-07-28`。

## 一、概览
- **定位**：极简 FLUX LoRA 训练 WebUI，**低显存（12 / 16 / 20GB）友好**。
- **许可**：**MIT**（前端）+ **Apache-2.0**（内嵌 Kohya 后端）——双层均宽松。
- **架构**：前端 Gradio（fork AI-Toolkit），后端 **Kohya sd-scripts**（见同仓竞品报告）。

## 二、技术栈（README + 仓库结构）
- Python + Gradio；训练后端为 Kohya sd-scripts。（⚠️ 集成方式待完整克隆确认·T-04：浅克隆 `--depth 1` 下 `sd-scripts/` 目录不可见；但 `app.py` 第 21 行 `import train_network`、第 456 行 shell 调用 `sd-scripts/flux_train_network.py`，表明以 submodule / vendored 方式引入 Kohya。README 未声明 submodule 细节，确切机制待完整克隆 `git submodule update --init` 后核实。）
- Advanced 标签默认隐藏，暴露 **100% Kohya 功能**。

## 三、核心能力
- 低显存 FLUX LoRA 训练（12 / 16 / 20GB）。
- 自动下载模型（`models.yaml` 可扩展基模）。
- 自动采样图生成、自定义分辨率、Publish to HuggingFace。
- Docker 支持。

## 四、与 Image_MultiModel 对标点（关键）
- **「Kohya 训练器 + 极简 Gradio UI」组合范式**：正是本仓若做 LoRA 训练 UI 的现成模板（后端复用 sd-scripts，前端轻量 Gradio / 类 Gradio）。
- **低显存训练 UX ↔ 本仓低显存诉求**：预设配置友好。
- **模型自动下载 + models.yaml 可扩展 ↔ 本仓模型管理**：基模注册范式。

## 五、许可与合规
- MIT（前端）+ Apache-2.0（Kohya 后端）：双层宽松，无传染风险；模型权重独立许可按 `THIRD_PARTY_NOTICES.md` 登记。

## 六、可借鉴点（P0/P1）
- **P0**：LoRA 训练 UI 的「轻前端 + 强后端」分层（本仓训练模块可直接套用）。
- **P1**：低显存训练配置预设、自动采样图、Docker 化分发。

## 七、风险 / 不适用
- 专注 FLUX（非 Z-Image）；需扩展基模支持 Z-Image 才能直接服务本仓主线。
- Gradio 前端 ≠ 本仓既有前端形态（可仅借鉴分层，不复用 UI 框架）。

## 八、参考文件（克隆内可复核）
- `reference_repos/Image_MultiModel/fluxgym/README.md`
- `reference_repos/Image_MultiModel/fluxgym/app.py`（Gradio 前端）
- `reference_repos/Image_MultiModel/fluxgym/models.yaml`（基模注册）
