---
name: krea2-image-prompt-writing
description: 编写 Krea 2（基于 FLUX.1 的 12B 美学微调，官方 FLUX 家族）图像生成提示词。当你需要为 Krea2 生图、追求强艺术导向与风格控制时使用。覆盖自然语言、支持并使用负面提示词、aspect_ratio 参数、creativity 与 CFG/步数规范。
---

# Krea 2 图像提示词撰写

## 工作流

1. 判断任务：写实/概念艺术/插画、是否用风格参考图或 moodboard。
2. 参考 `references/krea2-guide.md` 中的官方/社区写法。
3. 按「主体 → 媒介/摄影风格 → 环境 → 构图 → 光照 → 配色 → 质感 → 情绪 → 镜头」组织自然语言；排除项用负面提示词。

## 核心写法规则

- **自然语言为主，沿用 FLUX 式写法**：Krea2 源自 FLUX.1 美学微调（BFL 允许 Krea 在 FLUX 上训练风格化 checkpoint，并入官方 FLUX 家族），吃通顺描述句，不吃老式标签堆砌。
- **Krea2 支持并使用负面提示词（与 FLUX.2 不同！）**：社区与实测都表明加一条简单负面能显著提升，如 `ugly, distorted, watermark, text`。开源/ComfyUI 版可用负面字段；纯 API 版若无负面字段，则将排除写进主提示正向句。
- **比例走参数，不写进提示词**：Krea2 在 16:9 / 4:3（横、风景）与 2:3（竖、人像）表现最佳，极端比例会扭曲构图；Replicate 等接口用 `aspect_ratio` 枚举（1:1 / 16:9 / 3:4 / 9:16 / 4:3 / 3:2，默认 1:1）。
- **creativity 控制发挥度**：`raw`（字面）/ `low` / `medium`（默认）/ `high`（大幅发挥）。需要精准复现用 raw/low，要艺术发挥用 high。
- **CFG 与步数（开源/ComfyUI）**：CFG 建议 7–9，步数 20–30，采样器 DPM++ 2M Karras 或 Euler a。
- **避免过载与泛词**：一次 2–4 个关键主体；beautiful / amazing 这类空词无效，改写具体光照/情绪/构图。

## 长度建议

- 中短句 + 一个媒介词最佳；过长会被模型自行取舍。与 Midjourney 类似，靠"主体+风格词+一处光照"。

## 输出规则

- 主体第一，风格/镜头在后；排除项走负面提示词而非主提示否定句。
- 比例、creativity、CFG 等均为独立参数，不写进提示词正文。
- 追求电影感时 `cinematic` 一词影响很强（会触发整套构图规则）；风格偏向审美集中区，弱项含像素艺术等训练不足风格。
