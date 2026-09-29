# tests/frontend — 前端冒烟测试（jsdom）

不依赖真实后端、不启动 FastAPI 服务的前端冒烟测试：把 Jinja2 模板渲染成静态
HTML 后，在 jsdom 中注入 `app.js` 执行，并 mock 所有 `/api/*` 请求。

## 文件

| 文件 | 说明 |
|------|------|
| `smoke.js` | 冒烟测试脚本（约 40 条断言）：骨架、后端数据加载、Prompt 交互、主题/语言持久化、抽屉（高级参数/图库/批量）、悬浮查看器、SSE 进度、队列悬浮球、a11y 抽查 |
| `agent_chat.js` | Agent 对话面板（`static/js/chat.js`）冒烟（35 条断言）：浮动面板挂载、i18n × 5 语言跟随、`/api/tasks/{id}` **两种载荷形态**（history_db 行结构 / 内存 Task）归一化、`/api/outputs` URL 构建、SSE 分片解码、端到端「入队→轮询→出图」、失败/取消/中断/404 态。不需要渲染模板 |
| `xss_regression.js` | 前端 XSS 转义回归（纯 Node） |
| `_rendered/` | `scripts/render_pages.py` 的渲染产物（git 可忽略，本地生成） |

## 前置条件

1. `npm install`（安装 jsdom，与 Playwright 共用 tests/package.json）
2. 渲染模板（**仅 `smoke.js` 需要**）：

```bash
python scripts/render_pages.py
# → tests/frontend/_rendered/index.html
```

## 运行

```bash
node tests/frontend/smoke.js        # 需先 render_pages.py
node tests/frontend/agent_chat.js   # 自包含，无需渲染
# 或一次跑完：
npm run test:frontend
```

全部断言通过输出 `RESULT: pass=N fail=0` 且退出码 0；任一失败退出码 1。

## 语法检查（无需安装依赖）

```bash
node --check tests/frontend/smoke.js
```

## 维护约定

- mock 路由集中在 `MOCK` 对象，新增页面逻辑涉及的接口在此追加。
- 修改 `templates/*.html` 或 `static/js/app.js` 后：先重跑 `render_pages.py` 再跑 smoke。
- 断言风格：`assert(condition, '描述')`，保持全绿再提交。
