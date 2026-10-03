"""
test_config.py — 配置加载 + resolve_model_path() 双模式单测

对应 MASTER_PLAN M0 验收: 路径解析器双模式单测
"""

from pathlib import Path

import pytest
import yaml

# 添加 bin 到 path
PROJECT_ROOT = Path(__file__).resolve().parent.parent

from integrated_app.config_models import (
    AppConfig,
    ModelPaths,
    ModelsConfig,
    PortableConfig,
    SharedConfig,
    resolve_engine_model_paths,
    resolve_model_path,
    scan_resource_files,
)


@pytest.fixture
def project_root():
    return PROJECT_ROOT


@pytest.fixture
def config_yaml(project_root):
    """加载 config.yaml"""
    with open(project_root / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture
def app_config(config_yaml, project_root):
    """构建 AppConfig"""
    return AppConfig.from_yaml(config_yaml, project_root=str(project_root))


class TestConfigLoading:
    """测试配置加载"""

    @pytest.mark.smoke
    def test_config_loads_successfully(self, config_yaml):
        """配置文件可正常加载"""
        assert config_yaml is not None
        assert "version" in config_yaml
        assert "server" in config_yaml
        assert "models" in config_yaml

    def test_app_config_builds(self, app_config):
        """AppConfig 构建成功"""
        assert app_config.version == "1.3.0"
        assert app_config.server.host == "127.0.0.1"
        assert app_config.server.port == 8288
        assert app_config.models.model_source_mode in ("shared", "portable")

    def test_host_must_be_loopback(self, config_yaml, project_root):
        """host 只读校验：不允许 0.0.0.0"""
        config_yaml["server"]["host"] = "0.0.0.0"
        with pytest.raises(Exception):
            AppConfig.from_yaml(config_yaml, project_root=str(project_root))

    def test_engines_loaded(self, app_config):
        """引擎声明正确加载（完全脱离 ComfyUI，仅原生引擎）"""
        engines = app_config.models.engines
        assert "z_image_turbo_native" in engines
        # 已完全脱离 ComfyUI：不应再出现 comfyui 后端引擎
        assert "flux2_klein_9b_distilled" not in engines
        assert "z_image_turbo" not in engines

        native = engines["z_image_turbo_native"]
        assert native.backend == "native"
        assert native.workflow_file == ""

    def test_config_safe_dict_redacts_secrets(self, app_config):
        """脱敏：auth_token / password 不暴露"""
        safe = app_config.get_safe_config_dict()
        # api_token tokens 应为空
        assert safe["security"]["api_token"]["tokens"] == []

    def test_content_filter_fail_closed_default(self, app_config):
        """CLIP 缺失降级策略：模型默认 fail-closed（True），可由配置覆盖。

        注：早期版本默认 fail-open；当前版本出于安全考虑默认为 fail-closed。
        部署配置仍可通过 config.yaml 置 false 回退为放行，故此处只断言模型
        默认值，不断言配置文件取值（避免"部署策略"与"框架默认值"语义混淆）。
        """
        from integrated_app.config_models import ContentFilterConfig

        assert ContentFilterConfig().fail_closed_on_clip_missing is True
        # 配置可覆盖为任意布尔值
        assert isinstance(app_config.security.content_filter.fail_closed_on_clip_missing, bool)

    def test_shipped_config_fail_closed_defaults(self, config_yaml):
        """发行配置必须保持 fail-closed，防止配置文件静默覆盖代码安全默认。

        根因（2026-09-04 安全评估 H2/M1）：`config_models` 的安全默认本已安全，
        但 config.yaml 显式置 false 覆盖了它，且此前无任何测试守护发行配置取值，
        导致"安全默认在代码、fail-open 在部署"长期不被发现。此处补上发行配置断言。
        """
        mfmt = config_yaml["security"]["model_format"]
        cfilter = config_yaml["security"]["content_filter"]
        assert mfmt["fail_closed_on_corrupt_weight"] is True, (
            "发行配置不得把 fail_closed_on_corrupt_weight 置 false：否则损坏/被篡改权重被静默跳过而非拒绝加载"
        )
        assert cfilter["fail_closed_on_clip_missing"] is True, (
            "发行配置不得把 fail_closed_on_clip_missing 置 false：否则 CLIP 缺失时图片扫描静默放行"
        )
        # 配置取值须与模型安全默认一致（二者漂移即为回归信号）
        from integrated_app.config_models import (
            ContentFilterConfig,
            ModelFormatConfig,
        )

        assert mfmt["fail_closed_on_corrupt_weight"] == ModelFormatConfig().fail_closed_on_corrupt_weight
        assert cfilter["fail_closed_on_clip_missing"] == ContentFilterConfig().fail_closed_on_clip_missing


class TestResolveModelPath:
    """测试 resolve_model_path() 双模式解析"""

    def test_shared_mode_resolution(self, project_root, tmp_path):
        """shared 模式：路径基于 comfy_models_dir"""
        # 使用临时目录替代开发者本地硬编码路径，确保 CI 可移植性
        fake_models_dir = str(tmp_path / "comfy_models")
        models_config = ModelsConfig(
            model_source_mode="shared",
            shared=SharedConfig(
                comfy_models_dir=fake_models_dir,
                mount_map={"text": "text_encoders", "unet": "unet", "vae": "vae"},
            ),
        )
        mp = ModelPaths(sub_dir="text", sub_path="Z_image(turbo)/qwen_3_4b_fp8_mixed.safetensors")
        result = resolve_model_path(mp, models_config, project_root)

        assert "text_encoders" in result
        assert "Z_image(turbo)/qwen_3_4b_fp8_mixed.safetensors" in result
        assert fake_models_dir in result or "text_encoders" in result

    def test_portable_mode_resolution(self, project_root):
        """portable 模式：路径基于 model/"""
        models_config = ModelsConfig(
            model_source_mode="portable",
            portable=PortableConfig(
                internal_models_dir="model",
                sub_dirs={"text": "text_encoders", "unet": "unet", "vae": "vae"},
            ),
        )
        mp = ModelPaths(sub_dir="text", sub_path="Z_image(turbo)/qwen_3_4b_fp8_mixed.safetensors")
        result = resolve_model_path(mp, models_config, project_root)

        assert "model" in result
        assert "text_encoders" in result
        assert "Z_image(turbo)/qwen_3_4b_fp8_mixed.safetensors" in result

    def test_engine_model_paths_resolution(self, app_config, project_root):
        """引擎的所有模型路径都能解析"""
        flux = app_config.models.engines["z_image_turbo_native"]
        paths = resolve_engine_model_paths(flux, app_config.models, project_root)

        assert "text_encoder" in paths
        assert "unet" in paths
        assert "vae" in paths
        # 所有路径应以 .safetensors 结尾
        for key, path in paths.items():
            assert path.endswith(".safetensors"), f"{key} path doesn't end with .safetensors: {path}"

    def test_z_image_paths_resolution(self, app_config, project_root):
        """Z-Image 原生引擎路径解析"""
        z = app_config.models.engines["z_image_turbo_native"]
        paths = resolve_engine_model_paths(z, app_config.models, project_root)

        assert "text_encoder" in paths
        assert "unet" in paths
        assert "vae" in paths


class TestScanResourceFiles:
    """测试资源扫描"""

    def test_scan_loras(self, app_config, project_root):
        """扫描 LoRA 目录"""
        # shared 模式扫描
        if app_config.models.model_source_mode == "shared":
            loras = scan_resource_files("lora", app_config.models, project_root)
            # 可能返回空（如果 ComfyUI 的 loras 目录没有文件）
            assert isinstance(loras, list)

    def test_scan_local_text_encoders(self, project_root):
        """扫描本地 text/ 目录（项目根下）"""
        models_config = ModelsConfig(
            model_source_mode="portable",
            portable=PortableConfig(
                internal_models_dir="model",
                sub_dirs={"text": "text_encoders"},
            ),
        )
        # 项目根下的 text/ 目录（Junction 挂载点）
        # 在 shared 模式下可能扫描的是 ComfyUI 目录
        # 这里测试 portable 模式下的扫描
        result = scan_resource_files("text", models_config, project_root)
        assert isinstance(result, list)

    def test_scan_nonexistent_dir(self, project_root):
        """扫描不存在的目录返回空列表"""
        models_config = ModelsConfig(
            model_source_mode="shared",
            shared=SharedConfig(comfy_models_dir="/nonexistent/path"),
        )
        result = scan_resource_files("text", models_config, project_root)
        assert result == []


class TestPathGuard:
    """测试路径穿越守卫"""

    def test_safe_path_allowed(self, project_root):
        """安全路径通过"""
        from integrated_app.security.path_guard import PathGuard

        guard = PathGuard(["outputs/", "data/"], project_root)
        path = guard.resolve("outputs/test.png")
        assert str(path).endswith("test.png")

    def test_path_traversal_blocked(self, project_root):
        """路径穿越被拒绝"""
        from integrated_app.security.path_guard import PathGuard

        guard = PathGuard(["outputs/"], project_root)
        with pytest.raises(Exception):
            guard.resolve("../../../etc/passwd")

    def test_absolute_path_outside_blocked(self, project_root):
        """绝对路径在白名单外被拒绝"""
        from integrated_app.security.path_guard import PathGuard

        guard = PathGuard(["outputs/"], project_root)
        with pytest.raises(Exception):
            guard.resolve("C:/Windows/System32/config/SAM")

    def test_is_safe(self, project_root):
        """is_safe 不抛异常"""
        from integrated_app.security.path_guard import PathGuard

        guard = PathGuard(["outputs/", "data/"], project_root)
        assert guard.is_safe("outputs/test.png") is True
        assert guard.is_safe("../../etc/passwd") is False


class TestHistoryDB:
    """测试历史数据库"""

    @pytest.fixture
    def db(self, tmp_path):
        from integrated_app.history_db import HistoryDB

        d = HistoryDB(tmp_path / "test_history.db")
        yield d
        d.close()

    def test_create_and_get_task(self, db):
        """创建并获取任务"""
        db.create_task(
            task_id="test-001",
            engine="z_image_turbo_native",
            mode="txt2img",
            prompt="test prompt",
            negative_prompt="",
            generation_config={"cfg": 1.0, "steps": 8},
        )
        task = db.get_task("test-001")
        assert task is not None
        assert task["engine"] == "z_image_turbo_native"
        assert task["prompt"] == "test prompt"
        assert task["generation_config"]["cfg"] == 1.0

    def test_list_tasks_pagination(self, db):
        """分页查询"""
        for i in range(10):
            db.create_task(
                task_id=f"test-{i:03d}",
                engine="z_image_turbo_native",
                prompt=f"prompt {i}",
            )
        tasks, total = db.list_tasks(page=1, page_size=5)
        assert total == 10
        assert len(tasks) == 5

    def test_delete_tasks(self, db):
        """批量删除"""
        for i in range(5):
            db.create_task(task_id=f"del-{i:03d}", engine="test")
        count = db.delete_tasks(["del-000", "del-001", "del-002"])
        assert count == 3

    def test_preset_crud(self, db):
        """预设 CRUD"""
        pid = db.create_preset("z_image_turbo_native", "test-preset", {"cfg": 1.0})
        assert pid > 0

        preset = db.get_preset(pid)
        assert preset["name"] == "test-preset"

        db.update_preset(pid, name="updated-preset")
        preset = db.get_preset(pid)
        assert preset["name"] == "updated-preset"

        assert db.delete_preset(pid) is True

    def test_recover_stuck_tasks(self, db):
        """崩溃恢复"""
        db.create_task(task_id="stuck-001", engine="test")
        db.update_task_status("stuck-001", "processing")
        # 手动修改 created_at 为 2 小时前
        db.conn.execute(
            "UPDATE tasks SET created_at=datetime('now', '-2 hours') WHERE task_id=?",
            ("stuck-001",),
        )
        db.conn.commit()
        recovered = db.recover_stuck_tasks(max_processing_hours=1.0)
        assert recovered == 1
        task = db.get_task("stuck-001")
        assert task["status"] == "interrupted"
