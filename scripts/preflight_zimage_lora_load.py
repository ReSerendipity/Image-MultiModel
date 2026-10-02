#!/usr/bin/env python
"""preflight_zimage_lora_load — Z-Image LoRA 训练链路的**加载探针**（不训练，只验证权重管线）。

用途（P3/T-12 前置实证，2026-10-02）：
在真正跑训练 job 之前，先用 AI-Toolkit 自己的代码路径把本机 Z-Image 权重加载一遍，
并**逐张比对张量值**，回答三个问题：

1. AI-Toolkit 的 ``ZImageTransformer2DModel`` 能否吃 comfy 单文件权重（``convert_state_dict_on_load``
   的键改写 + ``.comfy_quant`` 融合量化键拆分是否落到正确模块）；
2. comfy 权重里的 ``model.diffusion_model.`` 前缀到底**有没有被剥离**（不剥离 = 所有键变成
   unexpected，模型会 ``strict=False`` 静默停在随机初始化，这正是 GOTCHAS #45 那类「静默错配」）；
3. 加载后的 diffusers 模型张量是否与源文件**数值一致**（不是只有形状对）。

门禁设计（沿用 preflight_* 家族的「探针先行」心法，见 GOTCHAS #43.3）：
- 任一步失败以非 0 退出码结束，绝不用「没报错」当作「加载正确」；
- 所有路径走仓库相对 ``pretrained_models/``（软链指向本机 ComfyUI 权重），不硬编码用户绝对目录。

用法::

    python scripts/preflight_zimage_lora_load.py                 # 全部检查
    python scripts/preflight_zimage_lora_load.py --src-file X    # 换一个 UNET 单文件
    python scripts/preflight_zimage_lora_load.py --aitk-root DIR # 指定 AI-Toolkit 工作区
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, NoReturn

REPO_ROOT = Path(__file__).resolve().parents[1]

# 本机 Z-Image 在仓库内的软链布局（pretrained_models/* -> ComfyUI-aki-v3/...）
UNET_DIR = REPO_ROOT / "pretrained_models" / "unet" / "Z-image_turbo-bf16"
VAE_FILE = REPO_ROOT / "pretrained_models" / "vae" / "FLUX.1-dev(Z-image(turbo))" / "ae.safetensors"
TE_DIR = REPO_ROOT / "pretrained_models" / "text_encoders" / "Z_image(turbo)"

# 训练器只从 HF 取「小文件」（config / tokenizer），大权重一律用本机文件
HF_CONFIG_REPO = "Tongyi-MAI/Z-Image-Turbo"
TRANSFORMER_CONFIG_PATH = "transformer/config.json"
TEXT_ENCODER_CONFIG_PATH = "text_encoder/config.json"
TOKENIZER_PATHS = [
    "tokenizer/tokenizer.json",
    "tokenizer/tokenizer_config.json",
    "tokenizer/vocab.json",
    "tokenizer/merges.txt",
]
VAE_CONFIG_PATH = "vae/config.json"


def _fail(msg: str) -> NoReturn:
    print(f"[FAIL] {msg}")
    raise SystemExit(1)


def pick_unet_file(cli_src: str | None = None) -> Path:
    if cli_src:
        p = Path(cli_src)
        if not p.is_file():
            _fail(f"--src-file 指向的文件不存在: {p}")
        return p
    if not UNET_DIR.exists():
        _fail(f"未找到 Z-Image UNET 目录: {UNET_DIR}")
    cands = sorted(f for f in UNET_DIR.iterdir() if f.is_file() and f.suffix.lower() == ".safetensors")
    if not cands:
        _fail(f"目录下没有 .safetensors: {UNET_DIR}")
    return cands[0]


def _hf_fetch(path: str) -> bytes:
    """拉取 HF 单个小文件（config / tokenizer），返回字节。

    默认走 ``huggingface_hub``（走系统信任链）。某些环境（本机 127.0.0.1 MITM 代理，
    证书只在 Windows schannel 信任库里、Python 侧无 CA 文件）会直接
    ``CERTIFICATE_VERIFY_FAILED``；这种环境必须**显式**设 ``AI_TRAIN_HF_INSECURE=1``
    才降级为免校验下载——默认值保持安全，避免把「关校验」变成默认行为。
    """
    try:
        from huggingface_hub import hf_hub_download

        local = hf_hub_download(HF_CONFIG_REPO, path)
        return Path(local).read_bytes()
    except Exception as e:  # noqa: BLE001 - 降级前先把原因打出来
        if os.environ.get("AI_TRAIN_HF_INSECURE") != "1":
            raise
        print(f"[WARN] hf_hub_download 失败（{type(e).__name__}），按 AI_TRAIN_HF_INSECURE=1 降级为免校验下载: {path}")
        import requests

        url = f"https://huggingface.co/{HF_CONFIG_REPO}/resolve/main/{path}"
        r = requests.get(url, timeout=120, verify=False)
        r.raise_for_status()
        return r.content


def prepare_hf_extras(workdir: Path) -> Path:
    """从 HF 拉**仅** config / tokenizer 小文件，组成本机 extras 目录（避开整仓权重下载）。"""
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "transformer").mkdir(exist_ok=True)
    (workdir / "text_encoder").mkdir(exist_ok=True)
    (workdir / "tokenizer").mkdir(exist_ok=True)
    (workdir / "vae").mkdir(exist_ok=True)

    for sub, path, optional in (
        ("transformer", TRANSFORMER_CONFIG_PATH, False),
        ("text_encoder", TEXT_ENCODER_CONFIG_PATH, False),
        # fast tokenizer 只需 tokenizer.json + tokenizer_config.json；
        # vocab.json / merges.txt 是 slow tokenizer 用的，缺了不阻塞（可选）
        ("tokenizer", "tokenizer/tokenizer.json", False),
        ("tokenizer", "tokenizer/tokenizer_config.json", False),
        ("tokenizer", "tokenizer/vocab.json", True),
        ("tokenizer", "tokenizer/merges.txt", True),
        ("vae", VAE_CONFIG_PATH, False),
    ):
        dst = workdir / sub / Path(path).name
        if dst.is_file() and dst.stat().st_size > 0:
            continue  # 已有缓存（可用 --extras-dir 预置，离线环境也能复现）
        try:
            data = _hf_fetch(path)
        except Exception as e:  # noqa: BLE001 - 探针要把「拉不到」显式报出来，不能吞
            if optional:
                print(f"[WARN] 可选文件拉取失败，跳过: {path} ({type(e).__name__})")
                continue
            _fail(f"HF 拉取小文件失败 {path}: {type(e).__name__}: {e}")
        dst.write_bytes(data)
    print(f"[OK] 已准备 extras 小文件目录（仅 config/tokenizer）: {workdir}")
    return workdir


def load_aitk(aitk_root: Path) -> None:
    """把 AI-Toolkit 工作区挂进 sys.path（按仓库根 ``run.py`` 的方式）。"""
    if not (aitk_root / "toolkit" / "models" / "v2" / "diffusion_models" / "z_image.py").is_file():
        _fail(f"未找到 AI-Toolkit 源码: {aitk_root / 'toolkit/models/v2/diffusion_models/z_image.py'}")
    if str(aitk_root) not in sys.path:
        sys.path.insert(0, str(aitk_root))


def probe_key_conversion(unet_file: Path) -> list[str]:
    """纯函数式验证：只对 state_dict 做键转换（不建模型），看前缀有没有被处理掉。"""
    from safetensors.torch import load_file
    from toolkit.models.v2.diffusion_models.z_image import ZImageTransformer2DModel

    sd = load_file(str(unet_file))
    src_keys = list(sd)
    has_prefix = sum(1 for k in src_keys if k.startswith("model.diffusion_model."))
    print(f"[INFO] 源文件键数={len(src_keys)}，带 model.diffusion_model. 前缀的={has_prefix}")

    converted = ZImageTransformer2DModel.convert_state_dict_on_load(dict(sd))
    conv_keys = list(converted)
    print(
        f"[INFO] 转换后键数={len(conv_keys)}，仍带前缀的={sum(1 for k in conv_keys if k.startswith('model.diffusion_model.'))}"
    )
    for k in conv_keys[:5]:
        print(f"[INFO]   样本键: {k}")

    if has_prefix and all(
        k.startswith("model.diffusion_model.") for k in conv_keys if "qkv" not in k and "quant" not in k
    ):
        # 转换没有剥离 comfy 前缀 —— 后面必须靠 import_comfy_quantized_layers 处理，
        # 因此这里不能判红，改由「真实加载 + 数值比对」来定案（见 probe_full_load）。
        print(
            "[WARN] convert_state_dict_on_load 未剥离 model.diffusion_model. 前缀，"
            "交由 import_comfy_quantized_layers 处理；以下用数值比对定案"
        )
    return conv_keys


COMFY_PREFIX = "model.diffusion_model."


def strip_comfy_prefix(state_dict: dict[str, Any]) -> dict[str, Any]:
    """剥掉 comfy 转存包常见的 ``model.diffusion_model.`` 前缀。

    **实证结论（2026-10-02，本机 NSFW 重打包版 Z-Image）**：AI-Toolkit 的
    ``convert_state_dict_on_load`` **不剥离**这个前缀。直接喂原始文件会让
    ``load_state_dict`` 报「missing 全部 diffusers 键 / unexpected 全部 comfy 键」
    （所幸这条路径是 strict 的，会炸而不是静默加载成随机模型）。
    在内存里改键名即可（safetensors 是 mmap 共享存储，不必复制 6GB 文件）。
    """
    return {(k[len(COMFY_PREFIX) :] if k.startswith(COMFY_PREFIX) else k): v for k, v in state_dict.items()}


def probe_full_load(unet_file: Path, extras: Path) -> dict[str, Any]:
    """走 AI-Toolkit 的真实加载路径（带前缀剥离适配），并和源文件逐张比数。"""
    import torch
    from safetensors.torch import load_file
    from toolkit.models.v2.diffusion_models.z_image import ZImageTransformer2DModel

    src = load_file(str(unet_file))
    sd = strip_comfy_prefix(src)
    print(f"[INFO] 已在内存剥离 comfy 前缀: {sum(1 for k in src if k.startswith(COMFY_PREFIX))}/{len(src)} 个键")

    # config_path 是「checkpoint 根 + subfolder」的组合：config 从
    # <extras>/transformer/config.json 取（与 HF 仓库布局一致），不是根目录的 config.json
    model = ZImageTransformer2DModel.load_from_state_dict(
        sd,
        torch.bfloat16,
        config_path=str(extras),
        subfolder=ZImageTransformer2DModel.aitk_subfolder,
    )

    # 用 AI-Toolkit 自己的键换算函数推导目标键，避免探针里手写第二套映射（会漂移）
    from toolkit.models.v2.diffusion_models.z_image import ZImageTransformer2DModel as _Z

    def _converted_key(src_key: str) -> str | None:
        one = _Z.convert_state_dict_on_load({src_key[len(COMFY_PREFIX) :]: None})  # type: ignore[arg-type]
        return next(iter(one), None) if one else None

    def _resolve(model_obj: Any, dotted: str) -> Any:
        holder = model_obj
        for part in dotted.split("."):
            if not hasattr(holder, part):
                return None
            holder = getattr(holder, part)
        return holder

    # 只挑非量化浮点权重做「数值一致」比对（量化键会被 OstrisLinear 重打包，不能直接比）
    float_keys = [
        k
        for k in src
        if src[k].is_floating_point()
        and not k.endswith(".comfy_quant")
        and not k.endswith(".weight_scale")
        and not k.endswith(".qkv.weight")  # 融合键由换算函数切分，单独看
    ]
    bad: list[str] = []
    checked = 0
    for src_key in float_keys[:50]:
        dst_key = _converted_key(src_key)
        if not dst_key:
            continue
        leaf = _resolve(model, dst_key)
        if leaf is None:
            bad.append(f"{src_key} -> {dst_key}: 模型上找不到该叶子（键改写未生效）")
            continue
        exp = src[src_key].to(torch.bfloat16)
        got = leaf.detach().to(torch.bfloat16)
        if exp.shape != got.shape:
            bad.append(f"{src_key} -> {dst_key}: 形状不符 {tuple(exp.shape)} vs {tuple(got.shape)}")
            continue
        if not torch.equal(exp, got):
            bad.append(f"{src_key} -> {dst_key}: 数值不一致（键前缀/换算错配）")
            continue
        checked += 1
        if checked <= 3:
            print(f"[OK] 数值一致: {src_key} -> {dst_key} {tuple(got.shape)}")

    # 融合 qkv：源文件是一个 qkv 融合张量，AI-Toolkit 应切成 to_q/to_k/to_v
    qkv_keys = [k for k in src if k.endswith(".attention.qkv.weight")]
    if qkv_keys:
        k0 = qkv_keys[0]
        base = k0[len(COMFY_PREFIX) :][: -len(".qkv.weight")]
        leaf = _resolve(model, base + ".to_q.weight")
        print(
            f"[INFO] 融合 qkv 样本: {k0} -> {base}.to_q.weight "
            + (f"{tuple(leaf.shape)}" if leaf is not None else "（未落地）")
        )
    print(f"[INFO] 数值逐张比对通过 {checked} 张（抽样 {len(float_keys[:50])} 个候选键）")
    if checked == 0:
        bad.append("没有任何一张张量比对通过：权重管线必然错配，不要继续往下走")

    n_params = sum(p.numel() for p in model.parameters())
    print(f"[INFO] 加载后参数量={n_params:,}")
    if bad:
        for b in bad:
            print(f"[FAIL] {b}")
        raise SystemExit(1)
    return {"params": n_params, "unet": str(unet_file), "extras": str(extras)}


def check_local_assets() -> None:
    for label, p in [("VAE", VAE_FILE), ("TE 目录", TE_DIR)]:
        if not p.exists():
            print(f"[WARN] {label} 不存在（本次探针不涉及，仅提示）: {p}")
        else:
            print(f"[OK] {label} 就位: {p}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src-file", default=None, help="Z-Image UNET 单文件（默认用 pretrained_models 软链目录内第一个）")
    ap.add_argument("--aitk-root", default=None, help="AI-Toolkit 工作区根目录（含 toolkit/ 与 main 分支源码）")
    ap.add_argument("--extras-dir", default=None, help="extras 小文件目录（默认临时目录）")
    args = ap.parse_args()

    unet = pick_unet_file(args.src_file)
    print(f"[INFO] UNET 单文件: {unet} ({unet.stat().st_size / 1e6:.1f} MB)")
    check_local_assets()

    # AI-Toolkit 是外部参考仓库，路径不属于本仓内容 → 只接受显式传参/环境变量，
    # 不内置任何本机默认路径（pre-commit 的端口可移植性门禁会拦截硬编码绝对路径）
    aitk_root = args.aitk_root or os.environ.get("AITK_ROOT")
    if not aitk_root:
        _fail("未指定 AI-Toolkit 工作区：用 --aitk-root <dir> 或环境变量 AITK_ROOT 指到含 toolkit/ 的仓库根")
    aitk_root = Path(aitk_root)
    load_aitk(aitk_root)
    print(f"[INFO] AI-Toolkit 工作区: {aitk_root}")

    import tempfile

    extras = Path(args.extras_dir) if args.extras_dir else Path(tempfile.gettempdir()) / "zimage_lora_extras"
    prepare_hf_extras(extras)

    probe_key_conversion(unet)
    result = probe_full_load(unet, extras)
    print(f"[PASS] Z-Image 权重管线探针通过: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
