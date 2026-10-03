# TODO — Image-MultiModel 训练链路（P3 LoRA Training）

> 生成于 2026-10-03。记录 T-12 ~ T-14 收尾护栏（preflight）完成后的剩余工作与阻塞项。
> 标记约定：🟢 已完成 / 🔴 阻塞（待环境） / ⬜ 未启动 / 🧹 已清理。

## 已完成（已验证、已提交）

| 阶段 | 内容 | 提交 |
| --- | --- | --- |
| T-12 | 最小 Z-Image LoRA job 实跑通过 + 产物可被 `native/lora.py` 加载 | `6cdeaa1` |
| T-13 | 训练编排薄层实装 + 真跑实证（2 步 job rc=0） | `4ddc637` |
| T-14 第一块 | 训练前数据集文件级就绪校验 | `56be231` |
| T-14 第二块 | 解码级分辨率/完整性预检（`check_resolution` 真实解码） | `673d439` |
| T-14 收尾护栏 | 提交前综合自检 `preflight_spec` + `POST /api/train/jobs/preflight` + `scripts/preflight_train_job.py` CLI | `8550ce3` |

门禁全绿：ruff check/format、mypy 106 files `Success`、全量 pytest **1434 passed / 16 skipped / 1 xfailed / 0 failed / 0 error**、integrity-manifest **33/33** Ed25519 有效、no-hardcoded-paths、config-refs、spec-refs。

## 🔴 阻塞项（待训练环境 / GPU 就绪；本机无 GPU 实跑能力，按"先验证再下结"铁律暂缓）

- [ ] **T-14 caption 自动生成**：AI-Toolkit 内置 captioner / `dataset_tools` 自动写 caption（依赖推理 GPU）。
- [ ] **T-15 采样（sampling）**：训练后 / 独立采样流程接入（依赖 GPU 推理）。
- [ ] **T-16 元数据（metadata）**：训练产物元数据归档（依赖训练产出）。

> 上述三项均依赖 `AITK_ROOT` 指向可用的 AI-Toolkit 工作区 + GPU 推理。环境就绪后按优先级推进；
> 落地须以真机 / 实跑退出码验证，不依赖静态分析下结论。

## 🧹 残留清理（本次已解决）

- [x] `config.yaml.bak-20261002-qwen_image_subpath`（Oct 2 旧备份）→ 移至 `C:/Users/Doro/_imgmm_residual_backup_20261003/`（可还原，未删）。
- [x] `_deltest/`（Sep 17 测试残留）→ 同上移至可还原备份。
- [x] `.zcodeignore`（项目 ignore 配置，原未跟踪）→ 本次纳入 git 跟踪（如非预期可后续移除）。

## 下一步

1. 训练 / GPU 环境就绪后，优先推进 **T-14 caption 自动生成**（T-15、T-16 顺延）。
2. 可选：跨阶段一致性复查 T-12 ~ T-14。
3. 2026-10-03：本批提交已推送，`origin/main` == 本地 `main`；发版 v1.3.0 全流程由 release-cycle 技能执行。
