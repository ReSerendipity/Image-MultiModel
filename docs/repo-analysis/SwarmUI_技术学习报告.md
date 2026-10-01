# SwarmUI 技术学习报告（Image_MultiModel 竞品对标 · 代码级）

> **性质**：竞品对标学习报告（非建议文档）。事实来自 `C:\Users\Doro\reference_repos\Image_MultiModel\SwarmUI` 浅克隆 + `gh api` 实时核验。
> **核验**：**`mcmonkeyprojects/SwarmUI`** — 4,528★ / MIT / C#(.NET) / `pushed_at=2026-09-03`（当日活跃）。
> ⚠️ **owner 更正**：主报告 §2.8.3 / §4.3 旧写 `mcmonkey45/SwarmUI` 为**错误 owner**（`gh api` 返回 404）；正确 owner 为 **`mcmonkeyprojects`**，星数 4.5k 吻合。本次已修正。

## 一、概览
- **定位**：模块化 AI 图像生成 WebUI（v0.9.8 Beta，原名 StableSwarmUI），强调 powertools、高性能、可扩展。
- **许可**：**MIT**（宽松，可自由借鉴）。
- **跨模态**：支持图像（Krea 2 / SD / Flux）、视频（**MiniMax H3** / Wan / LTX-2）、部分音频（ACE-Step）——因此**同时是 MiniMax-H3-lite 的直接竞品**。

## 二、技术栈（README + 仓库结构）
- 后端：**C# / .NET 8（未来 .NET 10）**——与 Python 系 WebUI 技术栈迥异；前端 WebUI 监听端口 `7801`。（⚠️ 后端语言基于 README 声明；浅克隆 `--depth 1` 下 `src/` 内 `.cs` 文件计数返回空，未能实计数确认，待完整克隆核实——README 明确写 C#/.NET 8，暂信描述。）
- 双界面：Generate 标签（新手友好）+ **Comfy Workflow 标签**（原生原始图，节点式无限制编辑）。

## 三、核心能力
- **模块化后端（Modular Backend）**：易扩展新模型，与前端解耦。
- Generate 标签：自动工作流生成（auto-workflow-generation）、图像编辑器、Grid Generator 等 powertools。
- Comfy Workflow 标签：直接编辑底层节点图。
- 视频模型集成：**MiniMax H3 / Wan / LTX-2**（与 MiniMax-H3-lite 主线重叠）。

## 四、与 Image_MultiModel 对标点
- **视频能力重叠 MiniMax H3**：SwarmUI 已集成 MiniMax H3 视频模型——若 Image_MultiModel 未来扩展视频是参照；对 MiniMax-H3-lite 是直接竞品（见其竞品库报告）。
- **C#/.NET 后端架构**：若 Image_MultiModel 评估非 Python 推理服务（.NET hosting），可借鉴其模块化后端设计。
- **自动工作流生成** UX ↔ 本仓工作流体验对照。

## 五、许可与合规
- MIT：代码自由借鉴；模型权重（Flux/MiniMax H3 等）各有独立许可，须按本仓 `THIRD_PARTY_NOTICES.md` 登记。

## 六、可借鉴点（P1）
- 模块化后端 + 双界面（Generate / Comfy）的 UX 分层；Grid Generator 批量出图。
- 视频模型集成范式（MiniMax H3 / Wan / LTX-2）对 MiniMax-H3-lite 参照价值更高（见 T2）。

## 七、风险 / 不适用
- C#/.NET 栈与 Image_MultiModel（Python / ComfyUI）异构，借鉴限于架构思路，不宜整库引入。
- 构建依赖 DotNet SDK（Windows 11 自动化，Win10 需手动装）。

## 八、参考文件（克隆内可复核）
- `reference_repos/Image_MultiModel/SwarmUI/README.md`
- `reference_repos/Image_MultiModel/SwarmUI/src/`（C# 后端；浅克隆未拉取完整源码，`.cs` 源文件计数待完整克隆确认）
- `reference_repos/Image_MultiModel/SwarmUI/docs/`（官方文档）
