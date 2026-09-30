"""
tests/test_config_save.py — 配置写回 + reload 测试

对应 TEST_AUDIT_REPORT P1-9: config save/reload 未测试
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

import yaml

from integrated_app.config import load_config, reload_config, save_config


@pytest.fixture
def tmp_config_file(tmp_path, project_root):
    """创建临时 config.yaml 副本"""
    src = project_root / "config.yaml"
    dst = tmp_path / "config.yaml"
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return dst


class TestConfigSave:
    """save_config() 测试"""

    def test_save_config_preserves_structure(self, tmp_config_file):
        """保存后结构不变"""
        config = load_config(str(tmp_config_file))
        original_version = config.version
        original_host = config.server.host

        save_config(config, str(tmp_config_file))

        # 重新加载
        config2 = load_config(str(tmp_config_file))
        assert config2.version == original_version
        assert config2.server.host == original_host

    def test_save_config_after_modify(self, tmp_config_file):
        """修改后保存 → 重新加载验证修改"""
        config = load_config(str(tmp_config_file))
        original_steps = config.inference.default_steps

        # 修改
        config.inference.default_steps = 15
        save_config(config, str(tmp_config_file))

        # 重新加载
        config2 = load_config(str(tmp_config_file))
        assert config2.inference.default_steps == 15

        # 恢复
        config2.inference.default_steps = original_steps
        save_config(config2, str(tmp_config_file))


class TestConfigReload:
    """reload_config() 测试"""

    def test_reload_picks_up_file_changes(self, tmp_config_file):
        """reload → 读取文件最新内容

        ⚠️ 断言必须相对**文件自身内容**，不能硬编码 10：真实 config.yaml 会被
        其它测试（如 test_api_contract 的 PUT /api/config）在运行期写回，
        xdist 同 worker 下若先跑写回、再跑本用例，副本里就是别的值
        （2026-09-30 CI 3.13 实测 assert 12 == 10）。修复 = 读文件取基线值。
        """
        raw = yaml.safe_load(tmp_config_file.read_text(encoding="utf-8"))
        baseline = int(raw["inference"]["default_steps"])

        config = load_config(str(tmp_config_file))
        assert config.inference.default_steps == baseline

        # 直接修改 YAML 文件
        raw["inference"]["default_steps"] = baseline + 10
        tmp_config_file.write_text(
            yaml.dump(raw, default_flow_style=False, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

        # reload
        config2 = reload_config()
        assert config2.inference.default_steps == baseline + 10

        # 恢复
        raw["inference"]["default_steps"] = baseline
        tmp_config_file.write_text(
            yaml.dump(raw, default_flow_style=False, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )


class TestConfigSafeDict:
    """get_safe_config_dict() 脱敏测试"""

    def test_api_token_redacted(self, project_root):
        """API token 被脱敏"""
        config = load_config()
        safe = config.get_safe_config_dict()
        security = safe.get("security", {})
        api_token = security.get("api_token", {})
        if "tokens" in api_token:
            assert api_token["tokens"] == [], "Tokens should be redacted in safe dict"

    def test_project_root_excluded(self, project_root):
        """project_root 不出现在 safe dict"""
        config = load_config()
        safe = config.get_safe_config_dict()
        assert "project_root" not in safe

    def test_server_info_present(self, project_root):
        """server 信息保留"""
        config = load_config()
        safe = config.get_safe_config_dict()
        assert "server" in safe
        assert "host" in safe["server"]
        assert safe["server"]["host"] == "127.0.0.1"
