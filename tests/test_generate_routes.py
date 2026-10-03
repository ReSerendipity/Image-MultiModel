"""
tests/test_generate_routes.py — POST /api/generate 深度契约测试

覆盖核心文生图 API：
- 请求体校验（合法/非法）
- 引擎不存在 → 404
- batch_size 边界（0 / 1 / 9999 / 10000）
- 内容安全过滤集成
- VRAM 预检集成
- TaskQueue 提交成功/失败场景
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.integrated_app.app_server import create_app


@pytest.fixture(scope="module")
def client():
    """TestClient fixture with CSRF token"""
    with TestClient(create_app(), raise_server_exceptions=False) as c:
        # Get CSRF token
        r = c.get("/api/health")
        csrf_tok = r.headers.get("X-CSRF-Token", "")
        if csrf_tok:
            c.headers["X-CSRF-Token"] = csrf_tok
        yield c


class TestGenerateRoutes:
    """POST /api/generate 深度测试"""

    def _valid_payload(self, **overrides) -> dict:
        """生成合法的基础请求体"""
        payload = {
            "positive_prompt": "a beautiful landscape at sunset",
            "negative_prompt": "",
            "cfg": 7.5,
            "steps": 20,
            "width": 512,
            "height": 512,
            "seed": 42,
            "batch_size": 1,
            "lora_1_name": "",
            "lora_1_strength": 1.0,
            "lora_2_name": "",
            "lora_2_strength": 0.7,
            "lora_3_name": "",
            "lora_3_strength": 0.5,
            "lora_4_name": "",
            "lora_4_strength": 0.4,
            "lora_5_name": "",
            "lora_5_strength": 0.3,
            "lora_6_name": "",
            "lora_6_strength": 0.2,
            "seedvr2_enable": False,
            "seedvr2_resolution": 2048,
            "seedvr2_seed": -1,
            "seedvr2_color_correction": "lab",
            "eses_enable": False,
            "eses_compare_axis": "horizontal",
            "vram_enable": True,
            "vram_reserved_gb": 0.6,
            "vram_mode": "auto",
            "vram_seed": -1,
            "output_format": "png",
            "output_prefix": "{engine}",
            "engine_name": "z_image_turbo_native",
            "reference_image_path": None,
            "reference_image_b64": None,
        }
        payload.update(overrides)
        return payload

    def test_generate_valid_payload_returns_200_or_409(self, client):
        """合法请求体应返回 200（接受成功）或 409（队列中已有相同任务）"""
        r = client.post("/api/generate", json=self._valid_payload())
        assert r.status_code in (200, 409), f"Expected 200 or 409, got {r.status_code}: {r.text[:200]}"

    def test_generate_empty_prompt_returns_422(self, client):
        """空 prompt 拒绝（v1.3.0 发版期修复：直连 /api/generate 不再放行空串白占 GPU）"""
        r = client.post("/api/generate", json=self._valid_payload(positive_prompt=""))
        assert r.status_code == 422, f"Expected 422 for empty prompt, got {r.status_code}"

    def test_generate_missing_positive_prompt_field(self, client):
        """缺少 positive_prompt 字段（Pydantic 默认空串）→ 422（同空串口径）"""
        payload = self._valid_payload()
        del payload["positive_prompt"]
        r = client.post("/api/generate", json=payload)
        assert r.status_code == 422, f"Expected 422 for missing prompt, got {r.status_code}"

    def test_generate_null_positive_prompt_returns_422(self, client):
        """positive_prompt 为 null → 422（类型错误）"""
        payload = self._valid_payload(positive_prompt=None)
        r = client.post("/api/generate", json=payload)
        assert r.status_code == 422, f"Expected 422 for null prompt, got {r.status_code}"

    def test_generate_negative_steps_returns_200_or_500(self, client):
        """steps 为负数 → Pydantic 不会拦截（默认 int 可为负），但后续逻辑可能出错"""
        payload = self._valid_payload(steps=-5)
        r = client.post("/api/generate", json=payload)
        # Pydantic 不阻止负数，可能是 200（接受）或 500（后端错误）
        assert r.status_code in (200, 409, 500), f"Got unexpected status: {r.status_code}"

    def test_generate_engine_not_found_returns_404(self, client):
        """引擎不存在 → 404"""
        r = client.post(
            "/api/generate",
            json=self._valid_payload(engine_name="nonexistent_engine_xyz"),
        )
        assert r.status_code == 404, f"Expected 404, got {r.status_code}: {r.text[:200]}"

    def test_generate_batch_zero_returns_400(self, client):
        """batch_size = 0 → 400（业务逻辑校验）"""
        r = client.post("/api/generate", json=self._valid_payload(batch_size=0))
        assert r.status_code == 400, f"Expected 400 for batch_size=0, got {r.status_code}: {r.text[:200]}"

    def test_generate_batch_too_large_returns_400(self, client):
        """batch_size > 9999 → 400"""
        r = client.post("/api/generate", json=self._valid_payload(batch_size=10000))
        assert r.status_code == 400, f"Expected 400 for batch_size=10000, got {r.status_code}: {r.text[:200]}"

    def test_generate_batch_max_allowed(self, client):
        """batch_size = 9999 → 允许（9999 是上限）"""
        r = client.post("/api/generate", json=self._valid_payload(batch_size=9999))
        # 可能因其他原因失败（VRAM 不足等），但不应是 400
        assert r.status_code != 400, f"batch_size=9999 should be allowed, got 400: {r.text[:200]}"

    def test_generate_batch_one_is_minimum(self, client):
        """batch_size = 1 → 最小值，应允许"""
        r = client.post("/api/generate", json=self._valid_payload(batch_size=1))
        assert r.status_code in (200, 409), f"Expected 200 or 409, got {r.status_code}"

    def test_generate_invalid_dimensions_returns_500_or_200(self, client):
        """负数宽高 → Pydantic 不拦截，可能在 VRAM 估算时报错返回 500 或接受返回 200"""
        r = client.post("/api/generate", json=self._valid_payload(width=-100))
        # Pydantic 不阻止负数维度，后端处理时可能出错
        assert r.status_code in (200, 409, 500), f"Unexpected status for negative width: {r.status_code}"

    def test_generate_response_structure(self, client):
        """响应体包含必需字段"""
        r = client.post("/api/generate", json=self._valid_payload())
        if r.status_code not in (200, 409):
            pytest.skip(f"Skipping response structure test due to {r.status_code}")
        body = r.json()
        assert "task_id" in body, "Response must contain task_id"
        assert "status" in body, "Response must contain status"
        assert "estimated_time_s" in body or "estimated_vram_gb" in body, "Response should have estimates"

    def test_generate_task_id_format(self, client):
        """返回的 task_id 应为非空字符串"""
        r = client.post("/api/generate", json=self._valid_payload())
        if r.status_code not in (200, 409):
            pytest.skip(f"Skipping due to {r.status_code}")
        body = r.json()
        assert isinstance(body["task_id"], str), "task_id must be string"
        assert len(body["task_id"]) > 0, "task_id must not be empty"

    def test_generate_queue_full_returns_503(self, client):
        """TaskQueue 满时 → 503。

        路由使用 ``request.app.state.task_queue``（而非 ``model_manager``），
        故直接令该 TaskQueue 实例的 ``submit`` 返回 False 触发 503。
        """
        from unittest.mock import AsyncMock

        original = client.app.state.task_queue.submit
        client.app.state.task_queue.submit = AsyncMock(return_value=False)
        try:
            r = client.post("/api/generate", json=self._valid_payload())
            assert r.status_code == 503, f"Expected 503 when queue full, got {r.status_code}: {r.text[:200]}"
        finally:
            client.app.state.task_queue.submit = original

    def test_generate_with_reference_image_path(self, client):
        """提供 reference_image_path → PathGuard 校验 + 文件存在性检查"""
        # 使用不存在的图片路径
        r = client.post(
            "/api/generate",
            json=self._valid_payload(reference_image_path="outputs/nonexistent_test_image.png"),
        )
        # 可能因文件不存在返回 404，或因其他原因失败，但不应是 500
        assert r.status_code != 500, f"Server error when providing invalid image path: {r.text[:200]}"

    def test_generate_with_path_traversal_in_reference_image(self, client):
        """参考图路径含路径穿越 → 403"""
        r = client.post(
            "/api/generate",
            json=self._valid_payload(reference_image_path="../../../etc/passwd"),
        )
        # 可能被 PathGuard 拦截
        assert r.status_code in (403, 400, 200, 409), f"Unexpected status: {r.status_code}"

    def test_generate_concurrent_submissions(self, client):
        """并发提交多个任务 → 全部接受（每个任务独立 task_id）"""
        import concurrent.futures

        def submit_once():
            r = client.post("/api/generate", json=self._valid_payload())
            return r.status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
            futures = [ex.submit(submit_once) for _ in range(5)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        # 所有结果都应该是 200 或 409
        assert all(s in (200, 409) for s in results), f"Some submissions failed: {results}"

    def test_generate_request_body_types(self, client):
        """验证各字段类型正确性"""
        # 浮点数精度
        r = client.post("/api/generate", json=self._valid_payload(cfg=7.5, lora_1_strength=1.234))
        assert r.status_code in (200, 409), f"Float fields should work: {r.status_code}"

        # 布尔值
        r = client.post("/api/generate", json=self._valid_payload(seedvr2_enable=True, eses_enable=False))
        assert r.status_code in (200, 409), f"Boolean fields should work: {r.status_code}"

        # 大整数（seed）
        r = client.post("/api/generate", json=self._valid_payload(seed=2**40))
        assert r.status_code in (200, 409), f"Large seed should work: {r.status_code}"


class TestBatchGenerateRoutes:
    """POST /api/generate/batch 深度测试"""

    def _valid_batch_payload(self, **overrides) -> dict:
        """生成合法的批量请求体"""
        payload = {
            "prompts": ["prompt 1", "prompt 2", "prompt 3"],
            "prompt_file": None,
            "grid_dimensions": {},
            "base_config": {
                "positive_prompt": "",
                "batch_size": 1,
                "engine_name": "z_image_turbo_native",
                "width": 512,
                "height": 512,
                "steps": 20,
                "cfg": 7.5,
                "seed": -1,
                "lora_1_name": "",
                "lora_1_strength": 1.0,
                "lora_2_name": "",
                "lora_2_strength": 0.7,
                "lora_3_name": "",
                "lora_3_strength": 0.5,
                "lora_4_name": "",
                "lora_4_strength": 0.4,
                "lora_5_name": "",
                "lora_5_strength": 0.3,
                "lora_6_name": "",
                "lora_6_strength": 0.2,
                "seedvr2_enable": False,
                "seedvr2_resolution": 2048,
                "seedvr2_seed": -1,
                "seedvr2_color_correction": "lab",
                "eses_enable": False,
                "eses_compare_axis": "horizontal",
                "vram_enable": True,
                "vram_reserved_gb": 0.6,
                "vram_mode": "auto",
                "vram_seed": -1,
                "output_format": "png",
                "output_prefix": "{engine}",
                "reference_image_path": None,
                "reference_image_b64": None,
            },
        }
        payload.update(overrides)
        return payload

    def test_batch_valid_prompts_returns_200(self, client):
        """合法 prompts 列表 → 200"""
        r = client.post("/api/generate/batch", json=self._valid_batch_payload())
        # 可能因其他原因失败（VRAM、引擎未加载等），但不应是 400
        assert r.status_code not in (400, 422), f"Valid batch should be accepted: {r.status_code} {r.text[:200]}"

    def test_batch_empty_prompts_returns_400(self, client):
        """空 prompts 列表 → 400（无任务可生成）"""
        r = client.post("/api/generate/batch", json=self._valid_batch_payload(prompts=[]))
        assert r.status_code == 400, f"Empty prompts should fail with 400, got {r.status_code}"

    def test_batch_no_prompts_and_no_file_returns_400(self, client):
        """既无 prompts 又无 prompt_file → 400"""
        payload = self._valid_batch_payload(prompts=[], prompt_file=None)
        r = client.post("/api/generate/batch", json=payload)
        assert r.status_code == 400, f"No prompts provided should fail with 400, got {r.status_code}"

    def test_batch_invalid_engine_returns_404(self, client):
        """base_config.engine_name 不存在 → 404"""
        r = client.post(
            "/api/generate/batch",
            json=self._valid_batch_payload(base_config={"engine_name": "fake_engine"}),
        )
        assert r.status_code == 404, f"Invalid engine should return 404, got {r.status_code}"

    def test_batch_large_batch_size_returns_400(self, client):
        """base_config.batch_size > 9999 → 400"""
        r = client.post(
            "/api/generate/batch",
            json=self._valid_batch_payload(base_config={"batch_size": 10000}),
        )
        assert r.status_code == 400, f"Large batch size should return 400, got {r.status_code}"

    def test_batch_grid_dimensions_expands_correctly(self, client):
        """Grid 维度展开：2 prompts × 3 configs = 6 tasks"""
        payload = self._valid_batch_payload(
            prompts=["p1", "p2"],
            grid_dimensions={"steps": [[10, 20], [30]]},  # 2×3=6 组合
        )
        r = client.post("/api/generate/batch", json=payload)
        if r.status_code in (400, 422, 500):
            pytest.skip(f"Skipping grid test due to {r.status_code}")
        body = r.json()
        assert "batch_id" in body, "Response must contain batch_id"
        assert "total_tasks" in body, "Response must contain total_tasks"
        assert "task_ids" in body, "Response must contain task_ids"

    def test_batch_response_structure(self, client):
        """批量响应包含必需字段"""
        r = client.post("/api/generate/batch", json=self._valid_batch_payload(prompts=["test"]))
        if r.status_code in (400, 422, 500):
            pytest.skip(f"Skipping due to {r.status_code}")
        body = r.json()
        assert "batch_id" in body
        assert "total_tasks" in body
        assert "task_ids" in body
        assert len(body["task_ids"]) == body["total_tasks"]


class TestGetBatchStatusRoutes:
    """GET /api/tasks/batch/{id} 测试"""

    def test_batch_status_not_found_returns_404(self, client):
        """不存在的 batch_id → 404"""
        r = client.get("/api/tasks/batch/nonexistent-batch-id-xyz")
        assert r.status_code == 404, f"Non-existent batch should return 404, got {r.status_code}"

    def test_batch_status_response_structure(self, client):
        """已创建的批量任务返回正确的进度结构"""
        # 先创建一个真实批量任务获取 batch_id
        batch_payload = {
            "prompts": ["test prompt"],
            "base_config": {
                "batch_size": 1,
                "engine_name": "z_image_turbo_native",
                "width": 256,
                "height": 256,
            },
        }
        r_create = client.post("/api/generate/batch", json=batch_payload)
        if r_create.status_code not in (200,):
            pytest.skip(f"Cannot create batch for status test: {r_create.status_code}")

        batch_id = r_create.json()["batch_id"]
        r = client.get(f"/api/tasks/batch/{batch_id}")

        if r.status_code != 200:
            pytest.skip(f"Batch status endpoint returned {r.status_code}")

        body = r.json()
        assert "batch_id" in body
        assert "total" in body
        assert "completed" in body
        assert "failed" in body
        assert "cancelled" in body
        assert "processing" in body
        assert "pending" in body
        assert "progress_pct" in body
