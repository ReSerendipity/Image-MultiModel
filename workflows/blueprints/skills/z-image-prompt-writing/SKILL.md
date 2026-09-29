---
name: z-image-prompt-writing
description: 编写 Z-Image（Z-Image / Z-Image-Turbo，6B S3-DiT，Apache 2.0 开源）图像生成提示词。当你需要为 Z-Image 生图、尤其是中英文双语与中文文字渲染时使用。覆盖双语自然语言、质量修饰词、引号包文字、变体差异（Base 支持负面 / Turbo 不支持）与 Prompt Enhancer 规范。
---

# Z-Image 图像提示词撰写

## 工作流

1. 确认变体：Base（50 步，支持负面提示词）还是 Turbo（8 步，不支持负面提示词）。
2. 参考 `references/z-image-guide.md` 中的官方/社区写法。
3. 按「主体+细节 → 风格词 → 光照 → 构图 → 质量修饰词」组织；Turbo 不写负面，用正向限制句替代。

## 核心写法规则

- **双语自然语言，中文原生友好**：Z-Image 用 mT5 多语言编码器，中英文都直接可用，且中文语义理解强（旗袍不会被翻成 qipao）。可中英混排。
- **结构公式（按优先级）**：`[主体+细节] + [风格词] + [光照] + [构图] + [质量修饰词]`。详细具体的描述远优于空泛形容词。
- **质量修饰词真的有用**：`ultra-detailed`、`high-resolution`、`crisp`、`sharp` 在 Z-Image 上比多数开源模型更顶用；写实类加 `photorealistic, RAW photo, cinematic lighting`。
- **文字渲染用引号**：图片内文字直接描述并放引号，如 `a poster with the words 欢迎光临 in red`，中英文都准（这是 Z-Image 相对同尺寸模型的最大优势，中英双语文字渲染最强）。
- **变体决定负面提示词**：
  - **Turbo：不支持负面提示词**（推理不用 CFG，官方 pipeline 忽略 negative 字段）。所有限制写进主提示正向句：`fully clothed, plain background, no text, no watermark`。
  - **Base：支持负面提示词**，可用 `blurry, low quality, deformed hands, bad anatomy, extra limbs, watermark, text overlay`。
- **Prompt Enhancer（PE）补细节**：内置 PE 会填空，但可预测性靠你自己写细；PE 补小洞、你锁定方向最佳。

## 长度建议

- 实践推荐 80–250 词：清晰、结构化、稍长更好；文学化长句反而不如技术化长句。单张图建议 2–4 个关键主体，过多请求会被模型自行取舍。

## 输出规则

- 主体明确、材质/光照具体、构图有约束（居中、三分法、浅景深）。
- Turbo 比例与分辨率由外部参数控制（上限约 4MP），不写进提示词。
- 需要中文文字渲染时，把目标文字用引号包住并写明字体/颜色/位置。
