---
name: flux-image-prompt-writing
description: 编写 FLUX.1 / FLUX.1 Kontext / FLUX.2 图像生成提示词。当你需要将用户需求改写成 FLUX 提示词、或用户明确要求使用 FLUX 生图时使用。覆盖正向描述、自然语言模板、画面文字、真实感摄影、词序、长度与多图输入等写法规范。
---

# FLUX 图像提示词撰写

## 工作流

1. 判断生图任务类型：单图生成、参考图（Kontext）、还是 FLUX.2 长提示。
2. 参考 `references/prompting-guide.md` 中的官方规则。
3. 按「正向描述优先 → 自然语言 → 检查关键要素」的顺序组织最终提示词。

## 核心写法规则

- **不用 negative prompt**：用正向描述替代，如用 "sharp focus throughout" 代替 "no blur"。
- **自然语言优先**：模板 `[SUBJECT], [LOCATION], [STYLE], [CAMERA SETTINGS], [LIGHTING], [COLORS], [EFFECT], [ADDITIONAL ELEMENTS]` 是起点，不是铁律。
- **画面文字用引号包起来**：`"The Importance Of Being Non-Aligned"`。
- **真实感摄影要写相机/镜头/胶片**：`shot on Fujifilm X-T5, 35mm f/1.4` 比 "professional photo" 更有效。
- **词序敏感**：最重要的元素放在最前面。
- **多语言**：法语描述巴黎场景、日语描述动漫风格会更地道。

## 长度建议

| 长度 | 词数 | 适用场景 |
|---|---|---|
| 短 | 10–30 词 | 快速探索 |
| 中 | 30–80 词 | 大多数场景 |
| 长 | 80+ 词 | 复杂多主体 |

FLUX.2 最长支持 32K tokens。

注：FLUX.1 / FLUX.1 Kontext 的上下文仅约 512–1024 tokens，32K 为 FLUX.2 专属；用 FLUX.1 时仍走 10–80 词短/中档，不要照搬 32K。

## 多图输入

用自然语言明确每张图的作用：
`subject from image 1, style from image 2, background from image 3`

## 输出规则

- 先写最重要主体，再写位置、风格、镜头、光照、颜色、特效等。
- 涉及真实感摄影时给出具体相机/镜头/胶片型号。
- 需要画面内可见文字时用英文双引号包裹并保持原文。
- 不堆砌抽象形容词，尽量具体。
