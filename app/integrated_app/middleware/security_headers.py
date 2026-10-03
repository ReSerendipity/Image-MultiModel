"""
middleware/security_headers.py — 安全响应头中间件

对应安全评估 M-02：项目此前未下发任何安全响应头（CSP / nosniff /
frame-ancestors / Referrer-Policy），且 CORS ``allowed_origins`` 中混入了
``ws://127.0.0.1:*`` 这类非法的 HTTP origin（WebSocket 不受 CORS 约束，该条目
既无效又容易被误读为"通配端口"）。

本模块统一补齐安全响应头。CSP 默认策略（P2-4 收紧，后端服务设计评估报告）：
``script-src 'self'`` 与 ``style-src 'self'``——内联脚本、属性式事件处理器与
内联样式属性全部禁止。前端已配合完成全面去内联：
- base.html 防闪烁脚本外置 theme-init.js；
- app.js 生成 HTML 的 onclick/onerror 属性改 data-act + 事件绑定；
- 全部内联 style 属性（index.html 52 处 + app.js 31 处）类化为
  seed.css 末尾的工具类层；动态进度条宽度改 JS CSSOM 属性赋值
  （``el.style.width`` 不受 CSP 约束）。
工具类层位于 seed.css 文件末尾，与既有单类规则同特异性时以本层为准，
保证与原内联属性视觉等价。
其余照旧：禁用 object/embed（防插件执行）、``frame-ancestors 'none'``（防
点击劫持）、``base-uri 'self'``（防 base 标签劫持相对 URL）。

置于中间件栈最外层，确保中间件自身产生的 401/403/429 响应也携带安全头。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

# 默认 CSP（P2-4 收官：script-src 与 style-src 均收紧为 'self'）
_DEFAULT_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data: blob:; "
    "connect-src 'self'; "
    "font-src 'self' data:; "
    "object-src 'none'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)

# 与安全相关的固定响应头
_BASE_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """为所有 HTTP 响应注入安全响应头。

    Args:
        app: ASGI 应用。
        config: 可选的 AppConfig；为空时回退全局单例。
            读取 ``config.security.headers.enabled`` 与 ``.csp``。
    """

    def __init__(self, app, config: Any = None) -> None:
        super().__init__(app)
        self._config = config

    def _get_headers_config(self) -> Any | None:
        if self._config is not None:
            return getattr(getattr(self._config, "security", None), "headers", None)
        try:
            from ..config import get_config

            cfg = get_config()
            if cfg is None:
                return None
            return getattr(getattr(cfg, "security", None), "headers", None)
        except Exception:  # noqa: BLE001 - 配置不可用时按"已启用"处理，安全默认开
            return None

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)

        # 静态资源强制再验证（2026-10-03 发版阶段1 实测）：uvicorn StaticFiles
        # 不发 Cache-Control，浏览器按启发式缓存陈旧 CSS/JS——前端资产更新后
        # 老用户最长约一天拿不到新样式（appConfirm P0 修复即因此未在旧标签页
        # 生效）。no-cache = 允许存储但每次经 etag 再验证，本地服务 304 开销可忽略。
        if request.url.path.startswith("/static/"):
            response.headers.setdefault("Cache-Control", "no-cache")

        cfg = self._get_headers_config()
        # 未配置时安全默认为"开启"
        enabled = True if cfg is None else bool(getattr(cfg, "enabled", True))
        if not enabled:
            return response

        for key, value in _BASE_HEADERS.items():
            response.headers.setdefault(key, value)

        csp = getattr(cfg, "csp", "") if cfg is not None else ""
        response.headers.setdefault("Content-Security-Policy", csp or _DEFAULT_CSP)

        return response


__all__ = ["SecurityHeadersMiddleware", "_DEFAULT_CSP"]
