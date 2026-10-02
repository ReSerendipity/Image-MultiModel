"""
config_models.py — Pydantic 模型 + resolve_model_path() 双模式解析

对应 MASTER_PLAN §4 M0: config_models.py + resolve_model_path() 双模式解析
对应 PRD §10.2: shared/portable 双模式
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator


# ──────────────────────────────────────────────────────────────
#  1. Server 配置
# ──────────────────────────────────────────────────────────────
class SSLConfig(BaseModel):
    enabled: bool = False
    certfile: str = "app/cert.pem"
    keyfile: str = "app/key.pem"


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8288
    auto_open_browser: bool = True
    auto_load_default_engine: bool = False
    workers: int = 1
    ssl: SSLConfig = SSLConfig()

    @field_validator("host")
    @classmethod
    def host_must_be_loopback(cls, v: str) -> str:
        """安全强制：host 只读校验，不允许改成 0.0.0.0"""
        allowed = {"127.0.0.1", "localhost", "::1"}
        if v not in allowed:
            raise ValueError(f"host must be loopback (127.0.0.1 / localhost / ::1), got: {v}")
        return v


# ──────────────────────────────────────────────────────────────
#  2. 模型源双模式
# ──────────────────────────────────────────────────────────────
class SharedConfig(BaseModel):
    comfy_models_dir: str = ""
    mount_map: dict[str, str] = Field(
        default_factory=lambda: {
            "text": "text_encoders",
            "unet": "unet",
            "vae": "vae",
            "lora": "loras",
            "controlnet": "controlnet",
            "checkpoint": "checkpoints",
        }
    )
    symlink_strategy: str = "junction"


class PortableConfig(BaseModel):
    internal_models_dir: str = "model"
    sub_dirs: dict[str, str] = Field(
        default_factory=lambda: {
            "text": "text_encoders",
            "unet": "unet",
            "vae": "vae",
            "lora": "loras",
            "controlnet": "controlnet",
            "checkpoint": "checkpoints",
        }
    )


class ModelPaths(BaseModel):
    """单个模型文件的路径声明（如 text_encoder / unet / vae）

    两个可选加载字段（2026-10-02 Krea2 实证新增，缺省均为空串 = 历史行为）：
        key_prefix:     权重键的统一前缀；非空时加载前剥掉（Krea2 的 AIO checkpoint
                        用 ``model.diffusion_model.`` 前缀，见 GOTCHAS #41）
        clip_type:      CLIP 类型名；非空时显式下发（Krea2 必须是 ``krea2``
                        才能走 12 层 tap 分支，见 GOTCHAS #42）
    """

    sub_dir: str = ""
    sub_path: str = ""
    key_prefix: str = ""
    clip_type: str = ""


class EngineConfig(BaseModel):
    """引擎声明——对齐 TTS_MultiModel declarative engines

    backend == "native" 时，原生引擎复用本地 Comfy 源码在进程内执行，
    通过 comfy_source_dir / custom_nodes_dir 指向复用源码位置。
    backend == "diffusers" 时，使用 HuggingFace diffusers 管线（M8 新引擎）。
    """

    name: str
    display_name: str = ""
    display_name_en: str = ""
    backend: str = "native"
    # 引擎角色（P2-vlm-chat M1）："" 沿用历史行为（按 supported_features 判定）；
    # "vlm" 触发 VlmEngine 看图聊天分支（model_registry 按 role 分发）；
    # "t2i"/"edit" 为语义标注（当前仍由 supported_features 驱动原生引擎能力守卫）。
    role: str = ""
    # ── native 引擎字段（backend == "native" 时使用，deprecated）──

    @field_validator("role")
    @classmethod
    def _check_role(cls, v: str) -> str:
        allowed = {"", "t2i", "edit", "vlm"}
        if v not in allowed:
            raise ValueError(f"EngineConfig.role 必须是 {allowed} 之一，收到: {v!r}")
        return v

    workflow_file: str = ""
    parameter_schema: str = ""
    comfy_source_dir: str = ""
    custom_nodes_dir: str = ""
    seedvr2_source_dir: str = ""
    text_encoder: ModelPaths | None = None
    unet: ModelPaths | None = None
    vae: ModelPaths | None = None
    # ── diffusers 引擎字段（backend == "diffusers" 时使用）──
    model_id: str = ""  # HF model ID (e.g. "Tongyi-MAI/Z-Image-Turbo")
    local_model_dir: str = ""  # 本地目录名（相对于 internal_models_dir 或 comfy_models_dir）
    vram_gb: float = 16.0
    ram_gb: float = 24.0
    default_precision: str = "fp8"
    fallback_precision: str = "fp8"
    supported_features: list[str] = Field(default_factory=list)
    default_width: int = 1024
    default_height: int = 1024
    # native 引擎 latent 格式（缺省回退模型自查 / Z-Image 的 16/8）
    latent_channels: int | None = None
    latent_downscale: int | None = None
    # native 采样器 / 调度器（空串时执行器回退 Z-Image 默认 dpmpp_3m_sde_gpu / sgm_uniform）
    # Flux.2 Klein 实测可用组合：euler / simple（见 scripts/preflight_flux2_klein.py）
    sampler: str = ""
    scheduler: str = ""
    image_formats: list[str] = Field(default_factory=lambda: ["png"])
    license: str = ""
    tags: list[str] = Field(default_factory=list)
    # ── MLOps P2·治理：权重级 Model Card 元数据（消除反模式 #3）──
    weight_sha256: str = ""  # 主权重 SHA256（防供应链投毒 / 静默损坏）
    weight_version: str = ""  # 权重版本号（语义化，便于回滚与血缘）
    training_data_source: str = ""  # 训练数据来源（数据血缘溯源）
    compatibility_matrix: dict[str, list[str]] = Field(default_factory=dict)  # LoRA / ControlNet 兼容性矩阵


class DiffusersEngineConfig(BaseModel):
    """diffusers 引擎专属配置模型（M8 里程碑）

    对应 config.yaml → models.engines.{name} where backend == "diffusers"
    用于 ZImagePipeline.from_pretrained(local_dir) 加载完整模型目录。
    """

    name: str
    display_name: str = ""
    display_name_en: str = ""
    model_id: str = ""  # HF model ID (fallback if local_model_dir not found)
    local_model_dir: str = ""  # 本地目录名（相对于 internal_models_dir 或 comfy_models_dir）
    vram_gb: float = 10.0
    ram_gb: float = 16.0
    default_precision: str = "bf16"
    fallback_precision: str = "fp8"
    supported_features: list[str] = Field(default_factory=list)
    default_width: int = 1024
    default_height: int = 1024
    image_formats: list[str] = Field(default_factory=lambda: ["png"])
    license: str = "Apache-2.0"
    tags: list[str] = Field(default_factory=list)


class ModelsConfig(BaseModel):
    """模型源双模式配置"""

    model_source_mode: str = "shared"  # "shared" | "portable"
    default_engine: str = "z_image_turbo_native"
    shared: SharedConfig = SharedConfig()
    portable: PortableConfig = PortableConfig()
    # P2 跨实例模型共享缓存：指向一个多实例共享的权重根目录（如挂载卷/对象存储）。
    # 非空时，portable 模式解析权重优先使用该目录，缺失再回退 internal_models_dir，
    # 实现「N 副本部署 = 1 份权重下载/存储」（修复反模式 #3）。
    shared_cache_dir: str = ""
    engines: dict[str, EngineConfig] = Field(default_factory=dict)


# ──────────────────────────────────────────────────────────────
#  4. 推理参数
# ──────────────────────────────────────────────────────────────
class TorchCompileConfig(BaseModel):
    enabled: bool = False
    backend: str = "inductor"
    dynamic: bool = True
    mode: str = "default"


class InferenceConfig(BaseModel):
    default_steps: int = 8
    default_cfg: float = 1.0
    default_sampler: str = "dpmpp_3m_sde_gpu"
    default_scheduler: str = "sgm_uniform"
    default_seed: int = -1
    default_batch_size: int = 1
    default_format: str = "png"
    default_quality: int = 95
    enable_fp8_fallback: bool = True
    vram_headroom_gb: float = 2.0
    vram_multisample_rule: float = 1.5
    # 显存估算不足时是否放行（依赖 ComfyUI 低显存分块换入换出 --lowvram，如 12GB 笔记本跑 SeedVR2）
    vram_tight_continue: bool = True
    torch_compile: TorchCompileConfig = TorchCompileConfig()
    lora_max_units: int = 6


# ──────────────────────────────────────────────────────────────
#  5. 输出 & 命名
# ──────────────────────────────────────────────────────────────
class HistoryOutputConfig(BaseModel):
    db_path: str = "data/history.db"
    max_records: int = 50000
    keep_days: int = 0
    # P0 留存护栏：输出目录体积上限（GB）。0 = 不按大小清理。
    # cleanup 触发条件为 keep_days>0 OR max_gb>0（修复 history_cleanup_cron 空转）。
    max_gb: float = 0.0
    cleanup_cron: str = "0 3 * * *"


class UploadsConfig(BaseModel):
    cache_dir: str = "data/uploads"
    max_size_mb: int = 2000
    # M-03: 解压炸弹防护。单图像素总量（宽×高）上限，超过即拒绝（413）。
    max_pixels: int = 200_000_000  # 2 亿像素 ≈ 200MP
    ttl_s: int = 86400


class OutputConfig(BaseModel):
    base_dir: str = "outputs"
    naming_template: str = "{engine}_{date}_{taskid}_{seed}_{idx}"
    organize_by: str = "engine_date"
    # P0 输出压缩：图像格式与质量（webp 可显著降低存储与带宽成本）
    image_format: str = "png"  # png | webp | jpeg
    image_quality: int = 95  # 仅对 webp/jpeg 生效
    save_thumbnail: bool = True
    thumbnail_format: str = "png"  # png | webp
    thumbnail_quality: int = 90
    thumbnail_max_side: int = 512
    history: HistoryOutputConfig = HistoryOutputConfig()
    uploads: UploadsConfig = UploadsConfig()

    # ──────────────────────────────────────────────────────────────
    #  6. 预设 / 水印
    # ──────────────────────────────────────────────────────────────
    explicit_ai_label: bool = Field(
        default=True,
        description="P1-2 显式 AI 生成标识：输出文件名追加后缀（可关闭）；与 DCT 隐式水印相互独立",
    )
    explicit_ai_label_suffix: str = Field(
        default="_AI",
        description="P1-2：显式标识后缀内容",
    )


class PresetsConfig(BaseModel):
    dir: str = "data/presets"
    allow_engine_mix_presets: bool = True


class WatermarkConfig(BaseModel):
    enabled_in_code: bool = True
    method: str = "dct_frequency"
    product_id: str = "IMGMULTI-1"
    embed_timestamp: bool = True
    embed_task_id: bool = True
    strength: float = 0.008
    # P0（任务书 2026-09-10）：水印失败策略（报告2 §六合规落地）。
    # 原实现 fail-open（失败静默跳过）构成合规缺口；策略化后为：
    #   重试 1 次 → 写 .provenance.json 侧车元数据（默认 sidecar）→ 阻断产出（block）。
    # sidecar: 嵌入失败后以侧车 JSON 保留溯源信息（默认，不阻断用户产出）；
    # block:   嵌入失败直接阻断产出（合规强约束场景）。
    failure_mode: str = "sidecar"


# ──────────────────────────────────────────────────────────────
#  7. 运行时队列
# ──────────────────────────────────────────────────────────────
class TaskQueueConfig(BaseModel):
    maxsize: int = 100
    worker_mode: str = "single_serial"
    cancel_timeout_s: int = 5
    auto_recover: bool = False
    max_timeout_s: int = 86400
    id_format: str = "ulid"
    checkpoint_every: int = 100
    checkpoint_dir: str = "data/checkpoints"


class BatchConfig(BaseModel):
    max_retries: int = 2
    retry_base_delay_s: float = 1.0
    retry_max_delay_s: float = 30.0
    stop_on_error: bool = False


class SSEConfig(BaseModel):
    poll_interval_s: float = 0.5
    heartbeat_interval_s: int = 30
    max_duration_s: int = 3600
    preview_b64_max_width: int = 256


class VRamSchedulerConfig(BaseModel):
    """P2-1: ComfyUI VRAM 感知调度配置"""

    enabled: bool = False
    vram_high_watermark_pct: int = 90
    vram_low_watermark_pct: int = 70
    sample_interval_s: float = 0.5
    max_batch_size: int = 4
    min_batch_size: int = 1


class RuntimeConfig(BaseModel):
    task_queue: TaskQueueConfig = TaskQueueConfig()
    batch: BatchConfig = BatchConfig()
    sse: SSEConfig = SSEConfig()
    vram_scheduler: VRamSchedulerConfig = VRamSchedulerConfig()
    # 空闲自动卸载引擎的等待分钟数（0 表示禁用）。对应 app_server.lifespan 与
    # cost_governance 的 idle_unload_minutes 引用，此前缺失导致 create_app 启动失败。
    idle_unload_minutes: int = 0


# ──────────────────────────────────────────────────────────────
#  8. 安全
# ──────────────────────────────────────────────────────────────
class RateLimitConfig(BaseModel):
    infer_per_minute: int = 30
    upload_per_minute: int = 10
    global_per_minute: int = 600


class BasicAuthConfig(BaseModel):
    enabled: bool = False
    username: str = "admin"
    password_bcrypt_hash: str = ""


class APITokenConfig(BaseModel):
    enabled: bool = False
    tokens: list[str] = Field(default_factory=list)
    # off-by-default 安全增强（2026-09-04 安全评估 M3）：true 时首次启动自动
    # 生成 api_token 持久化到 <project_root>/.api_token 并启用鉴权，
    # 保护 /api/config PUT 等状态变更端点。见 security/auth_bootstrap.py。
    bootstrap: bool = False


class CORSConfig(BaseModel):
    allowed_origins: list[str] = Field(
        default_factory=lambda: [
            "http://127.0.0.1:8288",
            "http://localhost:8288",
            "ws://127.0.0.1:*",
        ]
    )
    allow_credentials: bool = True


class ModelFormatConfig(BaseModel):
    only_safetensors: bool = True
    warn_if_pickle_found: bool = True
    # MLOps P0-1: 权重加载前完整性校验（LoRA / checkpoint）
    verify_weights: bool = True
    weight_manifest_file: str = ""  # 相对项目根的权重 SHA256 清单；为空则不比对 hash
    # 安全默认 true：损坏/被篡改权重拒绝加载（抛 WeightIntegrityError），
    # 而非"告警后静默跳过该层"——后者会让恶意权重被无声丢弃、用户无感知。
    # （2026-09-04 安全评估 H2 修复）
    fail_closed_on_corrupt_weight: bool = True
    # 未登记 hash 的权重（用户自添/首次使用）是否允许加载：
    # true=允许但告警（Trust-On-First-Use 起步期）；manifest 覆盖齐全后可收紧为 false。
    allow_unregistered_weights: bool = True


class IntegritySelfcheckConfig(BaseModel):
    enabled: bool = True
    manifest_file: str = "app/integrated_app/security/integrity_manifest.json"
    # P0（任务书 2026-09-10）：验签/哈希失败拒绝启动（fail-closed）。
    # 发布配置 enforce: true；开发/CI 环境保持默认 false（验签失败仅告警），
    # 避免无签名环境（未执行 sign_integrity_manifest.py）锁死启动。
    enforce: bool = False


class CSRFConfig(BaseModel):
    """CSRF (Double-Submit Cookie) 防护开关"""

    enabled: bool = True


class ContentFilterConfig(BaseModel):
    """内容过滤（CLIP 安全检测）配置"""

    fail_closed_on_clip_missing: bool = True


class SecurityHeadersConfig(BaseModel):
    """安全响应头配置（对应安全评估 M-02）。

    Attributes:
        enabled: 是否下发安全响应头（默认开启）。
        csp: 自定义 CSP 策略串；为空时使用中间件内置默认策略。
    """

    enabled: bool = True
    csp: str = ""


class SecurityConfig(BaseModel):
    allowed_base_dirs: list[str] = Field(default_factory=lambda: ["outputs/", "data/", "workflows/", "model/"])
    # 只读图片接口（/api/safety/check-image 等）专用白名单。
    # 与 allowed_base_dirs 分离，避免通过图片检查接口读取 model/ 下的权重文件
    # （对应安全评估 M-07）。留空时回退到 allowed_base_dirs。
    image_read_base_dirs: list[str] = Field(default_factory=lambda: ["outputs/", "data/"])
    rate_limit: RateLimitConfig = RateLimitConfig()
    basic_auth: BasicAuthConfig = BasicAuthConfig()
    api_token: APITokenConfig = APITokenConfig()
    csrf: CSRFConfig = CSRFConfig()
    cors: CORSConfig = CORSConfig()
    model_format: ModelFormatConfig = ModelFormatConfig()
    integrity_selfcheck: IntegritySelfcheckConfig = IntegritySelfcheckConfig()
    content_filter: ContentFilterConfig = ContentFilterConfig()
    headers: SecurityHeadersConfig = SecurityHeadersConfig()


# ──────────────────────────────────────────────────────────────
#  9. GPU & 硬件
# ──────────────────────────────────────────────────────────────
class GPUMonitorConfig(BaseModel):
    sample_interval_s: int = 2
    history_points: int = 60


class GPUConfig(BaseModel):
    backend: str = "auto"
    device_ids: list[int] = Field(default_factory=lambda: [0])
    allow_fallback_to_cpu: bool = True
    low_vram_mode: str = "auto"
    monitor: GPUMonitorConfig = GPUMonitorConfig()


# ──────────────────────────────────────────────────────────────
#  10. UI & i18n
# ──────────────────────────────────────────────────────────────
class A11yConfig(BaseModel):
    focus_ring: bool = True
    reduce_motion: bool = False


class UIConfig(BaseModel):
    theme_default: str = "dark"
    accent_color: str = "#5e7d5a"
    font_pair: str = "instrument_serif_dm_sans"
    sidebar_collapsed_by_default: bool = False
    accordion_default_groups: list[str] = Field(default_factory=lambda: ["basic", "prompt"])
    history_page_size: int = 50
    preview_max_size_mb: int = 20
    a11y: A11yConfig = A11yConfig()


class I18nConfig(BaseModel):
    default_locale: str = "zh"
    available_locales: list[str] = Field(default_factory=lambda: ["zh", "en", "ja", "ko"])
    locale_dir: str = "app/integrated_app/locales"
    fallback_to_en: bool = True


# ──────────────────────────────────────────────────────────────
#  11. 日志 & 缓存
# ──────────────────────────────────────────────────────────────
class LoggingConfig(BaseModel):
    level: str = "INFO"
    file: str = "logs/app.log"
    max_size_mb: int = 50
    backup_count: int = 5
    include_traceback: bool = True
    mask_sensitive_headers: bool = True


class CacheConfig(BaseModel):
    dir: str = "data/cache"
    max_size_mb: int = 500
    ttl_s: int = 86400


# ──────────────────────────────────────────────────────────────
#  12. 加速
# ──────────────────────────────────────────────────────────────
class VLLMConfig(BaseModel):
    enabled: bool = False
    tensor_parallel_size: int = 1
    gpu_memory_utilization: float = 0.85


class TensorRTConfig(BaseModel):
    enabled: bool = False
    engine_cache_dir: str = "data/trt_engines"


class AccelerationConfig(BaseModel):
    vllm: VLLMConfig = VLLMConfig()
    tensorrt: TensorRTConfig = TensorRTConfig()


# ──────────────────────────────────────────────────────────────
#  13. 环境变量
# ──────────────────────────────────────────────────────────────
class EnvironmentConfig(BaseModel):
    HF_HUB_OFFLINE: str = "1"
    TRANSFORMERS_OFFLINE: str = "1"
    MODELSCOPE_OFFLINE: str = "1"
    COMFYUI_DISABLE_UPDATE_CHECK: str = "1"


# ──────────────────────────────────────────────────────────────
#  13b. FinOps 预算（P3）
# ──────────────────────────────────────────────────────────────
class FinOpsConfig(BaseModel):
    """成本预算阈值（反模式 #5 中的预算告警闭环）。

    数值为 0 表示该项不启用预算。告警在 /api/finops/budget 与指标循环中产生。
    """

    budget_gpu_hours_per_day: float = 0.0  # 单 GPU 日均 GPU·小时预算
    storage_gb_budget: float = 0.0  # 输出目录体积预算（GB）
    alert_level: str = "warning"  # warning | error


# ──────────────────────────────────────────────────────────────
#  顶层配置模型
# ──────────────────────────────────────────────────────────────
class AppConfig(BaseModel):
    """整个 config.yaml 的 Pydantic 映射"""

    version: str = "1.0.0"
    server: ServerConfig = ServerConfig()
    models: ModelsConfig = ModelsConfig()
    inference: InferenceConfig = InferenceConfig()
    output: OutputConfig = OutputConfig()
    presets: PresetsConfig = PresetsConfig()
    watermark: WatermarkConfig = WatermarkConfig()
    runtime: RuntimeConfig = RuntimeConfig()
    security: SecurityConfig = SecurityConfig()
    gpu: GPUConfig = GPUConfig()
    ui: UIConfig = UIConfig()
    i18n: I18nConfig = I18nConfig()
    logging: LoggingConfig = LoggingConfig()
    cache: CacheConfig = CacheConfig()
    acceleration: AccelerationConfig = AccelerationConfig()
    environment: EnvironmentConfig = EnvironmentConfig()
    finops: FinOpsConfig = FinOpsConfig()

    # 运行时注入（非 YAML 来源）
    project_root: str = ""

    @classmethod
    def from_yaml(cls, yaml_dict: dict[str, Any], project_root: str = "") -> AppConfig:
        """从 YAML 字典构建 AppConfig"""
        cfg = cls(**yaml_dict)
        cfg.project_root = str(Path(project_root).resolve())
        return cfg

    def to_yaml_dict(self) -> dict[str, Any]:
        """序列化回 YAML 可写的字典（脱敏）"""
        d = self.model_dump(exclude={"project_root"})
        # 脱敏：隐藏 auth_token / password
        if d.get("security", {}).get("basic_auth", {}).get("password_bcrypt_hash"):
            d["security"]["basic_auth"]["password_bcrypt_hash"] = "***REDACTED***"
        for t in d.get("security", {}).get("api_token", {}).get("tokens", []):
            pass  # tokens 脱敏在 route 层处理
        return d

    def get_safe_config_dict(self) -> dict[str, Any]:
        """返回脱敏后的配置字典，供前端读取"""
        d = self.to_yaml_dict()
        # api_token tokens 完全隐藏
        d["security"]["api_token"]["tokens"] = []
        return d


# ──────────────────────────────────────────────────────────────
#  resolve_model_path() —— 双模式解析核心
# ──────────────────────────────────────────────────────────────
def resolve_model_path(
    model_paths: ModelPaths,
    config: ModelsConfig,
    project_root: str | Path,
) -> str:
    """
    根据 model_source_mode (shared / portable) 解析模型的完整路径。

    shared 模式:
        {comfy_models_dir}/{mount_map[sub_dir]}/{sub_path}
        例如: {comfy_root}/models/text_encoders/Z_image(turbo)/qwen_3_4b_fp8_mixed.safetensors（comfy_root 由外部配置决定）

    portable 模式:
        {project_root}/{internal_models_dir}/{sub_dirs[sub_dir]}/{sub_path}
        例如: ./model/text_encoders/Z_image(turbo)/qwen_3_4b_fp8_mixed.safetensors

    Args:
        model_paths: 引擎配置中的 text_encoder / unet / vae 等 ModelPaths
        config: ModelsConfig 实例
        project_root: 项目根目录

    Returns:
        解析后的绝对路径字符串（使用正斜杠，跨平台兼容）
    """
    project_root = Path(project_root).resolve()

    if config.model_source_mode == "portable":
        # ── portable 模式 ──
        sub_dir_key = model_paths.sub_dir
        sub_dir_name = config.portable.sub_dirs.get(sub_dir_key, sub_dir_key)
        # P2 跨实例共享缓存：优先命中 shared_cache_dir，缺失再回退本地 internal_models_dir
        shared_cache = getattr(config, "shared_cache_dir", "") or ""
        if shared_cache:
            cache_base = Path(shared_cache) / sub_dir_name
            cache_cand = cache_base / model_paths.sub_path
            if cache_cand.exists():
                return str(cache_cand).replace("\\", "/")
        base = project_root / config.portable.internal_models_dir / sub_dir_name
    else:
        # ── shared 模式 ──
        sub_dir_key = model_paths.sub_dir
        sub_dir_name = config.shared.mount_map.get(sub_dir_key, sub_dir_key)
        base = Path(config.shared.comfy_models_dir) / sub_dir_name

    full_path = base / model_paths.sub_path
    # 统一用正斜杠返回
    return str(full_path).replace("\\", "/")


def resolve_engine_model_paths(
    engine: EngineConfig,
    config: ModelsConfig,
    project_root: str | Path,
) -> dict[str, str]:
    """
    解析一个引擎的所有模型路径（text_encoder / unet / vae）。

    Returns:
        {"text_encoder": "/abs/path/to/model.safetensors",
         "unet": "/abs/path/to/model.safetensors",
         "vae": "/abs/path/to/model.safetensors"}
    """
    result: dict[str, str] = {}
    for attr in ("text_encoder", "unet", "vae"):
        mp: ModelPaths | None = getattr(engine, attr, None)
        if mp and mp.sub_path:
            result[attr] = resolve_model_path(mp, config, project_root)
    return result


def resolve_engine_load_options(
    engine: EngineConfig,
    config: ModelsConfig,
    project_root: str | Path,
) -> dict[str, str]:
    """解析引擎的**加载选项**（不是路径），供 executor 按引擎族定制加载行为。

    2026-10-02 Krea2 实证新增。为何不和 :func:`resolve_engine_model_paths` 合并返回：
    后者的返回值会被当成「角色 → 权重绝对路径」逐条送去做
    ``verify_weight_before_load``（``native/engine.py`` 的 load 流程），
    混入非路径键会让权重完整性校验误把它当文件去验。故拆成独立函数、独立传参。

    支持两个键（缺省时返回空字典，行为与历史完全一致）：
        - ``unet_key_prefix``: ``ModelPaths.key_prefix``（UNET 键统一前缀，加载时剥掉）
        - ``text_encoder_clip_type``: ``ModelPaths.clip_type``（CLIP 类型名，如 ``krea2``）

    Args:
        engine: 引擎配置
        config: ModelsConfig 实例（本函数不改动它，保留参数以便未来扩展基于路径的解析）
        project_root: 项目根目录（同上，仅保持与 resolve_engine_model_paths 签名一致）

    Returns:
        {"unet_key_prefix": str, "text_encoder_clip_type": str} 的子集
    """
    del config, project_root  # 当前实现不依赖路径解析，保留形参以保证调用方签名一致
    result: dict[str, str] = {}
    unet = getattr(engine, "unet", None)
    key_prefix = getattr(unet, "key_prefix", "") or ""
    if key_prefix:
        result["unet_key_prefix"] = key_prefix
    te = getattr(engine, "text_encoder", None)
    clip_type = getattr(te, "clip_type", "") or ""
    if clip_type:
        result["text_encoder_clip_type"] = clip_type
    return result


def scan_resource_files(
    sub_dir_key: str,
    config: ModelsConfig,
    project_root: str | Path,
    extensions: tuple = (".safetensors", ".pt", ".bin", ".ckpt"),
) -> list[str]:
    """
    扫描某个子目录下的所有模型文件，返回相对路径列表。
    用于前端 LoRA 下拉等资源扫描。

    Args:
        sub_dir_key: "text" / "unet" / "vae" / "lora" / "checkpoint" / "controlnet"
        config: ModelsConfig 实例
        project_root: 项目根目录
        extensions: 允许的文件扩展名

    Returns:
        相对路径列表（相对于该子目录根）
    """
    project_root = Path(project_root).resolve()

    if config.model_source_mode == "portable":
        sub_dir_name = config.portable.sub_dirs.get(sub_dir_key, sub_dir_key)
        base = project_root / config.portable.internal_models_dir / sub_dir_name
    else:
        sub_dir_name = config.shared.mount_map.get(sub_dir_key, sub_dir_key)
        base = Path(config.shared.comfy_models_dir) / sub_dir_name

    # P0-2 缓存：目录遍历（尤其含 Junction 的 ComfyUI 模型目录）成本高。
    # 结果按「子目录 + 根路径 + 扩展名 + 共享缓存目录」缓存，由 model 命名空间
    # 的 TTL 兜底新鲜度（新放入的 LoRA 最长 1 小时内可见）。
    from .cache import get_cache

    cache_key = f"{sub_dir_key}|{base}|{sorted(extensions)}|{getattr(config, 'shared_cache_dir', '')}"
    cached = get_cache("model").get(cache_key)
    if cached is not None:
        return list(cached)

    if not base.exists() or not base.is_dir():
        return []

    results: list[str] = []
    # followlinks=True：模型目录可能由指向 ComfyUI 的 Junction（Windows 目录符号链接）构成，
    # 默认不跟随会导致 junction 内的模型在资源扫描中不可见。
    for root, _dirs, files in os.walk(base, followlinks=True):
        for f in files:
            if f.lower().endswith(extensions):
                rel = Path(root, f).relative_to(base)
                results.append(str(rel).replace("\\", "/"))

    # P2 跨实例共享缓存目录也纳入扫描范围（portable 模式）
    shared_cache = getattr(config, "shared_cache_dir", "") or ""
    if shared_cache and config.model_source_mode == "portable":
        extra = Path(shared_cache) / sub_dir_name
        if extra.exists() and extra.is_dir():
            for root, _dirs, files in os.walk(extra, followlinks=True):
                for f in files:
                    if f.lower().endswith(extensions):
                        rel = Path(root, f).relative_to(extra)
                        results.append(str(rel).replace("\\", "/"))

    results = sorted(results)
    get_cache("model").put(cache_key, results)
    return results
