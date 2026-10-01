# P3 — LoRA 训练模块（T-34 决策=是 · 2026-10-01 立项）

> 关联：T-34（决策：是否做 LoRA 训练模块）= **是**；`docs/roadmap/README.md` 能力切片总览；
> `docs/repo-analysis/学习报告全量待办任务清单_20260912.md` 领域 C（LoRA 训练）。
> 本文件即 T-34 验收所需的「决策记录」（写入 roadmap）。

## 决策记录（T-34）

- **裁定**：**做** LoRA 训练模块（2026-10-01，用户「全部都做」授权）。
- **依据**：学习报告借鉴价值矩阵把 LoRA 训练列为 P0 高价值（fluxgym / sd-scripts 均为 ★★★）
  但项目当前是**纯推理服务**（无训练模块、无训练路线图）。本决策解除对 T-12~T-16、T-22 的阻塞。
- **落点**：本文件即决策记录，并在 `docs/roadmap/README.md` 能力切片总览新增 P3 行。

## 事实约束（来自复查报告代码级实证，非臆测）

| 约束 | 结论 | 证据 |
|---|---|---|
| sd-scripts 是否支持 Z-Image | ❌ **确认不支持**（全仓搜索 `Z.?Image / zimage` 0 匹配，非「待验证」） | 复查报告 §四 #9 |
| sd-scripts 是否支持 LUMINA | ✅ 支持（`lumina_train.py` / `lumina_train_network.py`） | 复查报告 §四 #8 |
| fluxgym 集成方式 | 轻前端（Gradio）+ 强后端（Kohya sd-scripts）；submodule / vendored 确切机制待完整克隆确认 | 复查报告 §四 #6 |
| 项目当前状态 | 纯推理（Z-Image Turbo 单引擎）；`native/lora.py` 仅推理时 LoRA 栈加载，非训练 | 复查报告 §3.0 / §3.3 |

## 关键推论

1. **Z-Image LoRA 训练不能直用 sd-scripts** → 需评估 **AI-Toolkit**（是否支持 Z-Image 待验证）或
   **自扩展**（基于 ComfyUI aki-v3 训练节点 / diffusers 训练脚本）。
2. **Lumina2 LoRA 训练** → sd-scripts 现成可用（T-28 深读后确认），与用户本地 Lumina2 对应。
3. **训练 UI** → 借鉴 fluxgym「轻前端 + 强后端」分层（T-13），但 fluxgym 专注 FLUX，需扩展基模支持 Z-Image / Lumina2。
4. **Caption / Tagger** → SDNext 内置 25+ LLM/VLM + DeepDanbooru（T-22 评估），若做训练数据准备则引入。

## 候选实现路径（待选型，不臆造架构参数）

- **路径 A — AI-Toolkit 后端 + 轻前端**：评估 AI-Toolkit 对 Z-Image 的支持度；若支持，复用其训练器 + 自包轻量 UI（fluxgym 分层范式）。
- **路径 B — 自扩展**：基于 ComfyUI aki-v3 的 LoRA 训练能力（本机已装）或 diffusers 训练脚本，自研训练模块 + UI。
- **LUMINA 路径**：sd-scripts 直接（若本仓做 Lumina2 LoRA），无需 Z-Image 适配。

## 待办（挂原清单 T 项）

| T 项 | 内容 | 状态 | 阻塞 |
|---|---|---|---|
| T-12 | 训练模块设计 / 实现 | ⬜ 待路径选型 | 训练后端选型（A/B）+ reference_repos 就位 |
| T-13 | 训练 UI（fluxgym 分层模板） | ⬜ 待 T-12 | T-12 |
| T-22 | Caption / Tagger 评估（SDNext 内置） | ⬜ 待评估 | 训练路线图确认 |
| T-28 | sd-scripts LUMINA 训练深读 | ⬜ 阻塞 | reference_repos 缺失（本地无 sd-scripts 克隆） |
| T-14~T-16 | 其余训练相关（数据准备 / 采样 / 元数据） | ⬜ 未启动 | T-12 路径选型 |

## 阻塞 / 前置

- ⛔ **reference_repos 缺失**：本机 `C:\Users\Doro\reference_repos\Image_MultiModel\` 当前不存在。
  T-28（LUMINA 深读）、T-04 / T-05 / T-06 复验、训练后端源码研究均受阻。需恢复参考克隆后推进实证。
- ⛔ **训练后端选型未定**：AI-Toolkit 是否支持 Z-Image 需实测；路径 A/B 决策未做。
- 项目当前纯推理架构，训练模块需新建独立子系统（不与推理任务队列冲突）。

## 验收（本 P3 立项目标）

- [x] T-34 决策记录（本文件 + README 索引）。
- [ ] 训练后端选型 POC（AI-Toolkit vs 自扩展，含 Z-Image / Lumina2 适配验证）。
- [ ] T-12 设计评审通过（不臆造架构参数，以实证为准）。
- [ ] T-13 / T-22 / T-28 随选型推进。
