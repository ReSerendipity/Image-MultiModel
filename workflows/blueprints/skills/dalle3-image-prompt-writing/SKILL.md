---
name: dalle3-image-prompt-writing
description: 编写 DALL·E 3 图像生成提示词。当你需要将用户需求改写成 DALL·E 3 提示词、或用户明确要求使用 DALL·E 3 / ChatGPT 生图时使用。覆盖自然语言长描述、引号包文字、否定用正向表述、ChatGPT 自动增强与比例/尺寸规范。
---

# DALL·E 3 图像提示词撰写

## 工作流

1. 判断任务：是否需渲染文字、是否经 ChatGPT 自动增强、目标比例。
2. 参考 `references/dalle3-guide.md` 中的官方最佳实践。
3. 按「主体+动作 → 环境+时间 → 光照+配色 → 风格/媒介+质量词」组织自然语言长句。

## 核心写法规则

- **纯自然语言，无需任何特殊语法**：DALL·E 3 在自然语言上训练，整段描述句比关键词标签效果好得多。不要写 `word, word, word`。
- **不用独立的 negative prompt**：DALL·E 3 没有负面提示词字段。排除内容要写进主提示的正向表述，如 `clean background with no text`、`no people visible`。
- **文字渲染：精确文字放引号内**：`a logo with the word "Still" in thin sans-serif`。DALL·E 3 文字能力强于多数模型，但长文字/复杂排版仍建议只放 1–2 个词，多次重试；精确排版可后期用设计软件加。
- **比例写进提示词或走 API 尺寸**：提示词里写 `wide landscape format` / `tall portrait format`；API 固定三档 1024×1024 / 1792×1024（横）/ 1024×1792（竖）。
- **借助 ChatGPT 自动增强**：在 ChatGPT 里给简略想法，它会扩写成详细提示；可做会话式微调（"让光更暖"），无需掌握复杂语法。

## 长度建议

- 越长越细越可控：一段包含主体、环境、光照、风格、构图的自然语言描述；避免自相矛盾（如 "photorealistic abstract"）与元素过载（一次聚焦一个主概念 + 支撑细节）。

## 输出规则

- 四段式：主体+动作 / 环境+时间 / 光照+配色 / 风格+质量词。
- 明确空间关系：`the cat is on the left, the dog is on the right`。
- 排除项写成正向描述，不写 "no xxx" 独立字段。
- 文字用引号包裹并保持原文。
- 不要与 Midjourney / FLUX 混用 `--ar`、`--no` 等参数语法——DALL·E 3 不吃这些。
