"""training/handoff.py — 产物发现与「移交推理栈」规划。

AI-Toolkit 一次 sd_trainer 跑完，``<training_folder>/<job name>/`` 下会有：
``<name>.safetensors``（终稿 LoRA）、``<name>_<step>.safetensors``（中间档）、
``optimizer.pt``、``samples/``（baseline / 中途 / 终稿采样图）、``config.yaml``。

本模块只做三件只读 + 一件显式动作：

1. :func:`discover_artifacts` —— 扫产物（只读）；
2. :func:`final_lora_path` —— 定位终稿 LoRA（只读）；
3. :func:`plan_handoff` —— 算出「要被 ``native/lora.py`` 的 ``resolve_lora_paths``
   扫到，需要拷到哪个目录」，并给出命令（只读，不拷）；
4. :func:`copy_into_lora_dir` —— **人工显式调用**才真正搬运。

⚠️ 为什么第 4 步要显式：目标目录是 ``pretrained_models/loras``，而 ``pretrained_models/``
在 AGENTS.md 是**禁区目录**（禁止 AI 自动修改，须人工确认）。因此薄层默认**只给计划、
不自动搬**；只有调用方显式确认（API 的 ``confirm=true``）才执行复制，
并在日志里把「写入预置模型库目录」这件事如实打出来。
"""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: AI-Toolkit 的中间档命名：``<name>_<zero-padded step>.safetensors``
_INTERMEDIATE_RE = re.compile(r"_\d+$")


def save_root(training_folder: str | Path, job_name: str) -> Path:
    """AI-Toolkit 的存档目录：``training_folder/<job name>``。"""
    return Path(training_folder) / job_name


def final_lora_path(training_folder: str | Path, job_name: str) -> Path | None:
    """终稿 LoRA：``<save_root>/<job name>.safetensors``；不存在返回 None。

    中间档（``<name>_<step>.safetensors``）**不是**终稿——T-12 实跑里两者同为
    21.3MB、步长 5 步，差一个名字，靠"取最新文件"会拿到中间档。
    """
    candidate = save_root(training_folder, job_name) / f"{job_name}.safetensors"
    return candidate if candidate.is_file() else None


def discover_artifacts(training_folder: str | Path, job_name: str) -> list[dict[str, Any]]:
    """扫描一次训练的全部产物（只读、幂等）。

    Returns:
        ``[{"kind": "lora"|"lora_intermediate"|"optimizer"|"sample"|"config",
        "name": str, "path": str, "size_bytes": int, "mtime": float}]``，按类型与名称排序。
        ``sample`` 只收 ``samples/`` 下的图片。

    中间档（``<name>_<step>.safetensors``）**单独占一个 kind**：它同样是有价值的
    产物（训练中断时唯一能救回的权重），但绝不能当终稿（T-12 实跑里终稿与中间档
    同为 21.3MB，只差一个 ``_00000000X`` 后缀，靠"取最新"会拿错）。
    """
    root = save_root(training_folder, job_name)
    if not root.exists():
        return []

    items: list[dict[str, Any]] = []
    for p in sorted(root.glob("*.safetensors")):
        # 终稿：名字严格等于 <job name>.safetensors。中间档另立 kind，
        # 但**必须按名字精确判定**：早前按「stem 里含下划线」判断，把带下划线的
        # job 名（如 probe_lora）自己的终稿也误判成中间档了（测试当场抓到）。
        if p.name == f"{job_name}.safetensors":
            items.append(_stat(p, "lora"))
        elif _INTERMEDIATE_RE.search(p.stem):
            items.append(_stat(p, "lora_intermediate"))
    for p in sorted(root.glob("optimizer.pt")):
        items.append(_stat(p, "optimizer"))

    samples_dir = root / "samples"
    if samples_dir.is_dir():
        for p in sorted(samples_dir.iterdir()):
            if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                items.append(_stat(p, "sample"))

    cfg = root / "config.yaml"
    if cfg.is_file():
        items.append(_stat(cfg, "config"))

    items.sort(key=lambda it: (it["kind"], it["name"]))
    return items


def _stat(path: Path, kind: str) -> dict[str, Any]:
    st = path.stat()
    return {
        "kind": kind,
        "name": path.name,
        "path": str(path),
        "size_bytes": int(st.st_size),
        "mtime": float(st.st_mtime),
    }


def lora_resource_dir(config: Any, project_root: str | Path) -> Path:
    """``native/lora.py::resolve_lora_paths`` 实际扫的 LoRA 目录。

    与 ``config_models.scan_resource_files`` 同源规则：
    portable 模式 = ``<project_root>/<pretrained_models>/loras``，
    shared 模式 = ``<comfy_models_dir>/loras``。
    """
    project_root = Path(project_root)
    raw_mode = getattr(config, "model_source_mode", "") if config is not None else ""
    # pydantic 里可能是 str 也可能是 str-enum，两种都能取到字面量
    mode = str(getattr(raw_mode, "value", raw_mode) or "")
    if mode == "portable" and config is not None:
        sub_dirs = getattr(config.portable, "sub_dirs", None)
        lora_name = sub_dirs.get("lora", "loras") if isinstance(sub_dirs, dict) else "loras"
        internal = getattr(config.portable, "internal_models_dir", "pretrained_models")
        return project_root / internal / lora_name

    # 兜底一律按 shared 规则走；拿不到配置时退回 <project_root>/loras 并打警告，
    # 宁可给一个"看起来可疑"的默认值，也不能在移交预览时 500。
    if config is None or not mode:
        logger.warning(
            "拿不到 model_source_mode（config=%s），LoRA 目录回退为 %s；"
            "若与 native/lora.py 实际扫描路径不符，请补训练侧配置",
            type(config).__name__,
            project_root / "loras",
        )
    shared = getattr(config, "shared", None) if config is not None else None
    mount_map = getattr(shared, "mount_map", None) if shared is not None else None
    lora_name = mount_map.get("lora", "loras") if isinstance(mount_map, dict) else "loras"
    base_raw = str(getattr(shared, "comfy_models_dir", "") or "") if shared is not None else ""
    # ⚠️ 判空必须用原始字符串：``Path("")`` 会被归一化成 ``Path(".")``，
    # ``str(Path(".")) == "."`` 是**真值**，拿它当「有值」会走进 base 分支、
    # 返回相对路径 ``loras``（真跑里移交计划的 target_dir 就变成了相对路径，
    # 拷文件会写到进程 cwd 下）。
    if base_raw:
        return Path(base_raw) / lora_name
    return project_root / "loras"


def plan_handoff(config: Any, project_root: str | Path, lora_path: str | Path) -> dict[str, Any]:
    """给出「把 LoRA 搬进推理侧可见目录」的计划（**不执行**拷贝）。

    Returns:
        ``{"source": str, "target_dir": str, "target": str,
        "exists": bool, "copy_cmd": str}``
    """
    src = Path(lora_path)
    target_dir = lora_resource_dir(config, project_root)
    target = target_dir / src.name
    return {
        "source": str(src),
        "target_dir": str(target_dir),
        "target": str(target),
        "exists": target.exists(),
        "copy_cmd": f'copy /Y "{src}" "{target}"',
    }


def copy_into_lora_dir(
    config: Any, project_root: str | Path, lora_path: str | Path, dry_run: bool = False
) -> dict[str, Any]:
    """把 LoRA 拷进推理侧 LoRA 目录（**显式调用**，禁区目录写入会打日志告警）。

    Args:
        dry_run: 为 True 时只返回将要发生的动作，不落盘（供接口先给预览）。

    Returns:
        ``{"copied": bool, "target_dir": str, "target": str, "error": str|None}``
    """
    src = Path(lora_path)
    plan = plan_handoff(config, project_root, src)
    if not src.is_file():
        return {"copied": False, **plan, "error": f"源 LoRA 不存在: {src}"}
    if dry_run:
        return {"copied": False, **plan, "error": None}

    target_dir = Path(plan["target_dir"])
    if target_dir.is_symlink():
        # 目标是指针（junction/symlink）时明确报出来，避免 mkdir 静默附到宿主目录上
        return {"copied": False, **plan, "error": f"目标目录是指针，拒绝写入: {target_dir}"}
    if not target_dir.exists():
        return {"copied": False, **plan, "error": f"目标目录不存在: {target_dir}"}
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target_dir / src.name)
    except OSError as e:
        logger.warning(
            "训练产物移交失败（写入预置模型库目录 %s）：%s",
            target_dir,
            e,
        )
        return {"copied": False, **plan, "error": str(e)}

    logger.info(
        "训练产物已移交推理栈: %s → %s（该目录为 AGENTS.md 禁区，本次搬运由人工显式发起）",
        src,
        target_dir / src.name,
    )
    return {"copied": True, **plan, "error": None}
