# 模型权重放置说明（本安装包不含模型）

本安装包**不包含模型权重**。请按下面指引下载并放置，完成后在应用「设置 → 完整资源扫描」或重启即可使用。

## 默认引擎：Z-Image Turbo（需要 3 个文件）

下载地址（魔搭 ModelScope，官方 Comfy-Org 发布）：
https://modelscope.cn/models/Comfy-Org/z_image_turbo/files

| 文件（仓库内路径） | 放置到本目录下的位置 | 体积 |
|---|---|---|
| `split_files/diffusion_models/z_image_turbo_int8_convrot.safetensors` | `pretrained_models\unet\Z-image-turbo\` | ~5.8 GB |
| `split_files/text_encoders/qwen_3_4b_fp8_mixed.safetensors` | `pretrained_models\text_encoders\Z_image(turbo)\` | ~5.3 GB |
| `split_files/vae/ae.safetensors` | `pretrained_models\vae\Z_image(turbo)\` | ~0.3 GB |

## 通用规则

- 本目录（`pretrained_models/`）即应用「设置 → 模型源模式 = portable · pretrained_models」指向的模型根目录。
- 其他引擎（Qwen-Image 2.1 / Edit、Flux.2 Klein、FLUX.1-dev、Krea2-turbo、Qwen3-VL）同样把权重放入
  `text / unet / vae / clip` 对应子目录，文件名需与 `config.yaml` 各引擎 `sub_path` 一致。
- 放置完成后：应用内「设置 → 完整资源扫描」，或重启应用。
- 权重完整性：默认引擎的 `weight_sha256` 钉版在 `app/config.yaml`；替换为自选权重时请同步更新该钉版。

> 提示：模型体积较大，请确认安装盘剩余空间充足（默认引擎约 12 GB）。
