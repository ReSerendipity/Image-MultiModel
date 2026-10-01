# Kohya sd-scripts 技术学习报告（Image_MultiModel 训练对标 · 代码级）

> **性质**：竞品对标学习报告（非建议文档）。事实来自 `C:\Users\Doro\reference_repos\Image_MultiModel\sd-scripts` 浅克隆 + `gh api` 实时核验。
> **核验**：`Kohya-ss/sd-scripts` — **7,218★ / Apache-2.0 / Python** / `pushed_at=2026-08-02`；版本 0.11.1（2026-06-16）。

## 一、概览
- **定位**：SD 等图像模型的**训练 / 生成 / 工具脚本集**（LoRA 训练事实标准）。
- **许可**：**Apache-2.0**——与本仓同许可证，可自由借鉴训练逻辑，**无 GPL 传染风险**。

## 二、技术栈（README + 仓库结构）
- Python；训练脚本（`train_network.py` 等）+ diffusers 集成。
- 支持 `torch.compile`（Anima LoRA / LLLite，提速约 20%，需 Triton + MSVC 编译器）。
- 2026-06 大重构（0.11.0）提升可维护性。

## 三、核心能力
- **LoRA 训练**：SD / SDXL / SD3.5 / FLUX.1 / **LUMINA** / HunyuanImage-2.1 / **Anima**。
- Fine-tuning / DreamBooth（除 HunyuanImage-2.1）。
- Textual Inversion（SD / SDXL）。
- 量化训练：LLLite、Anima torch.compile。
- **LUMINA 支持** → 与用户本地 ComfyUI **Lumina2** 模型对应！

## 四、与 Image_MultiModel 对标点（关键）
- **Z-Image Base 已发布（2026-01-27）→ LoRA 训练底座具备**：sd-scripts 的 LoRA 训练范式可作本仓 LoRA 训练 UI 后端参照（⚠️ **已确认不支持 Z-Image**：复查报告对 sd-scripts 全仓搜索 `Z.?Image / zimage` 0 匹配，非「待验证」。若本仓主线为 **Z-Image** LoRA 训练，sd-scripts 不能直接用，需评估 AI-Toolkit 或自行扩展；若做 **LUMINA/Lumina2** LoRA 则 sd-scripts 现成可用）。
- **LUMINA 支持 ↔ 用户 Lumina2 模型**：若本仓做 Lumina LoRA，sd-scripts 是现成训练器。
- **低显存训练（LLLite / Anima）↔ 本仓低显存诉求**。

## 五、许可与合规
- Apache-2.0：训练逻辑可借鉴/改写；模型权重独立许可按 `THIRD_PARTY_NOTICES.md` 登记。

## 六、可借鉴点（P0/P1）
- **P0**：LoRA 训练管线（参数、元数据、采样策略）作为本仓训练模块后端参照。
- **P1**：torch.compile 加速、LLLite 低显存训练、训练文档体系（`docs/`）。

## 七、风险 / 不适用
- 纯脚本（无 UI）；本仓需自包 UI（**fluxgym 即 Kohya + Gradio UI 范例**，见同仓竞品报告）。
- ⚠️ **已确认不支持 Z-Image**（复查报告全仓搜索 `Z.?Image / zimage` 0 匹配，非待验证）；若本仓主线为 Z-Image LoRA 训练，sd-scripts 不能作为后端，需评估 AI-Toolkit 或自行扩展。

## 八、参考文件（克隆内可复核）
- `reference_repos/Image_MultiModel/sd-scripts/README.md`
- `reference_repos/Image_MultiModel/sd-scripts/docs/`（训练文档）
- `reference_repos/Image_MultiModel/sd-scripts/sdxl_train_network.py`（训练入口）
