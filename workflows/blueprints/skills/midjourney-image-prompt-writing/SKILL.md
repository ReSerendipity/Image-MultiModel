---
name: midjourney-image-prompt-writing
description: 编写 Midjourney (V7) 图像生成提示词。当你需要将用户需求改写成 Midjourney 提示词、或用户明确要求使用 Midjourney 生图时使用。覆盖自然语言主体、参数后缀（--ar/--style raw/--stylize/--no/--sref）、词序、风格强度与比例规范。
---

# Midjourney 图像提示词撰写

## 工作流

1. 判断任务：写实摄影、插画/概念艺术、风格参考迁移，还是角色/物体锁定。
2. 参考 `references/midjourney-guide.md` 中的官方参数与写法。
3. 按「主体 + 场景 + 光照 + 镜头/媒介 + 参数后缀」组织，参数永远放在最后。

## 核心写法规则

- **自然语言为主，但保留少量媒介词**：V7 已能读通顺句子，比老式标签堆砌更好；仍建议短句 + 一个媒介词（如 `editorial photography`、`watercolor concept art`、`product catalog shot`）。避免纯 SDXL 式 `word, word, word` 长标签。
- **参数统一放在句末**：`--ar 16:9`、`--style raw`、`--stylize 100`、`--chaos 20`、`--no text, watermark`、`--sref <url>`、`--oref <url>`、`--v 7`。参数前留空格、参数内不加逗号/句号等标点。
- **词序敏感**：模型从左到右加权，主体（hero）放最前。
- **否定用 `--no` 而非主提示里的 "no xxx"**：`--no text, watermark, blurry, extra fingers`。主提示里写 "no glasses" 效果差，改用正向描述（"clear unobstructed eyes"）。
- **写实摄影加 `--style raw`**：默认 MJ 会做"美学增强"让一切像画；要照片感就加 `--style raw` 并配合中低 `--stylize`，再给相机语言（如 `shot on Leica M11`）。
- **比例走参数 `--ar`，不写进提示词正文**：`--ar 1:1` / `16:9` / `9:16` / `4:5` / `2:3` / `21:9`。

## 长度建议

- 单段 15–60 词通常足够；过长反而稀释。写「主体 + 环境 + 一处光照 + 一个媒介/风格词」即可。
- 风格强度：`--stylize 0` 最贴近描述，`--stylize 1000` 最强 MJ 美学；写实取 0–50，艺术取 200–600。

## 输出规则

- 主体第一、环境第二、情绪第三、风格参考最后。
- 参数块永远在末尾；一次只调一个旋钮（stylize/chaos/raw 不要一起改，否则难定位原因）。
- 需要文字渲染时把目标文字放进提示词（如 `a poster that reads "Spring Festival"`），但 MJ 文字能力弱，长文字易错，建议只放短词或后期用设计软件加。
- 不要在参数里加标点，不要把场景词放在参数块之后。
