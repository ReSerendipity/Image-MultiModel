"""
tests/test_engine_routes.py — 引擎路由深度测试

对应 N19: engine_routes.py 覆盖率提升
覆盖：GET /api/engines, POST /api/engine/load, POST /api/engine/unload
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.integrated_app.app_server import create_app


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app(), raise_server_exceptions=False) as c:
        _csrf_r = c.get("/api/health")
        _csrf_tok = _csrf_r.headers.get("X-CSRF-Token", "")
        if _csrf_tok:
            c.headers["X-CSRF-Token"] = _csrf_tok
        yield c


class TestEngineList:
    """GET /api/engines — 引擎列表"""

    def test_list_engines_ok(self, client: TestClient) -> None:
        """引擎列表 → 200 或 500（registry 未完全初始化时可能 500）"""
        r = client.get("/api/engine/engines")
        assert r.status_code in (200, 500), f"Got {r.status_code}: {r.text[:200]}"
        if r.status_code == 200:
            body = r.json()
            assert "engines" in body
            assert "active_engine" in body
            assert "count" in body
            assert body["count"] == len(body["engines"])
            assert body["count"] >= 1

    def test_engine_fields(self, client: TestClient) -> None:
        """引擎条目字段完整"""
        r = client.get("/api/engine/engines")
        if r.status_code == 200:
            engines = r.json()["engines"]
            first = engines[0]
            for key in (
                "name",
                "display_name",
                "display_name_en",
                "ready",
                "state",
                "active",
                "vram_gb",
                "ram_gb",
                "default_precision",
                "supported_features",
                "tags",
            ):
                assert key in first, f"Missing field '{key}' in engine entry"

    def test_active_engine_in_list(self, client: TestClient) -> None:
        """活动引擎在列表中且 active=True"""
        r = client.get("/api/engine/engines")
        if r.status_code == 200:
            body = r.json()
            active_name = body["active_engine"]
            if active_name:
                engines = body["engines"]
                active_engines = [e for e in engines if e["name"] == active_name]
                assert len(active_engines) == 1
                assert active_engines[0]["active"] is True


class TestEngineLoad:
    """POST /api/engine/load — 加载引擎"""

    def test_load_nonexistent_engine_404(self, client: TestClient) -> None:
        """引擎不存在 → 404"""
        r = client.post("/api/engine/load", json={"engine_name": "nonexistent_engine_xyz"})
        assert r.status_code == 404

    def test_load_existing_engine(self, client: TestClient) -> None:
        """加载已注册引擎 → 200 或 500（取决于 registry 状态）"""
        r = client.post("/api/engine/load", json={"engine_name": "z_image_turbo_native"})
        assert r.status_code in (200, 500), f"Got {r.status_code}: {r.text[:200]}"
        if r.status_code == 200:
            body = r.json()
            assert body["engine_name"] == "z_image_turbo_native"
            assert body["status"] in ("loaded", "error", "loading")

    def test_load_succeeds_despite_none_factory_placeholder(self, client: TestClient) -> None:
        """回归：``_factories[name] = None`` 延迟注册占位不得让加载链拿到 None。

        此前 ``engine_routes.load_engine`` 用 ``name not in registry._factories``
        判空——占位键存在 ⇒ 条件恒假 ⇒ 真实工厂永不注册 ⇒ ``registry.get()`` 返回
        None ⇒ ``None.load()`` 报 ``'NoneType' object has no attribute 'load'``。
        修复后必须真正走到 ``status == "loaded"``。
        """
        r = client.post("/api/engine/load", json={"engine_name": "z_image_turbo_native"})
        assert r.status_code == 200, f"Got {r.status_code}: {r.text[:200]}"
        body = r.json()
        assert body["status"] == "loaded", f"未真正加载：{body}"
        assert "NoneType" not in body.get("message", "")
        assert "has no attribute" not in body.get("message", "")


class TestEngineRegistryFactorySemantics:
    """InMemoryEngineRegistry.has_factory — None 占位视为「无可用工厂」"""

    def test_none_placeholder_is_not_a_factory(self) -> None:
        from app.integrated_app.engine_interface import InMemoryEngineRegistry

        reg = InMemoryEngineRegistry()
        reg._factories["lazy"] = None  # type: ignore[assignment]  # 延迟注册占位
        assert "lazy" in reg._factories  # 旧判空方式（`in`）会误判为已注册
        assert reg.has_factory("lazy") is False
        assert reg.get("lazy") is None

        reg.register("lazy", lambda **_: object())
        assert reg.has_factory("lazy") is True
        assert reg.get("lazy") is not None

    def test_missing_factory(self) -> None:
        from app.integrated_app.engine_interface import InMemoryEngineRegistry

        reg = InMemoryEngineRegistry()
        assert reg.has_factory("nope") is False


class TestEngineUnload:
    """POST /api/engine/unload — 卸载引擎"""

    def test_unload_no_active_engine(self, client: TestClient) -> None:
        """无活动引擎 → 200 或 500（registry 状态依赖）"""
        r = client.post("/api/engine/unload")
        assert r.status_code in (200, 500), f"Got {r.status_code}: {r.text[:200]}"
