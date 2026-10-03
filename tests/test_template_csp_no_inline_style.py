"""CSP 内联样式防回归：模板不得包含 style=" 属性（P2-4 style-src 'self'）。

style-src 'self'（零 unsafe-inline）下，服务端 HTML 的内联 style 属性会被浏览器
整段剥离：#appConfirm 曾因 style="display:none" 失效、叠加 CSS 类
.app-confirm{display:flex}，导致空确认弹层常驻 z-index 10000 遮挡全页
（v1.3.0 发版阶段1 浏览器模拟实测发现，2026-10-03）。

约定：初始可见性一律走 CSS 类；动态切换走 JS CSSOM 属性赋值
（el.style.xxx 不受 CSP style-src 约束）。
"""

from __future__ import annotations

from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "app" / "integrated_app" / "templates"
SEED_CSS = Path(__file__).resolve().parents[1] / "app" / "integrated_app" / "static" / "css" / "seed.css"


def test_templates_contain_no_inline_style_attributes():
    offenders = []
    for tpl in sorted(TEMPLATES_DIR.rglob("*.html")):
        for lineno, line in enumerate(tpl.read_text(encoding="utf-8").splitlines(), start=1):
            if 'style="' in line:
                offenders.append(f"{tpl.name}:{lineno}")
    assert offenders == [], f"CSP style-src 'self' 会剥离模板内联 style 属性，禁止回归: {offenders}"


def test_app_confirm_hidden_by_css_default():
    css = SEED_CSS.read_text(encoding="utf-8")
    assert "#appConfirm{display:none}" in css, (
        "appConfirm 弹层必须由 CSS 默认隐藏（内联 style 属性在 CSP 下无效），显示/隐藏由 appConfirm() 的 CSSOM 赋值切换"
    )
