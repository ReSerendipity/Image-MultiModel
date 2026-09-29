"""
agent — 内置对话式 Agent 编排包(P0 骨架)

评估报告《Image_MultiModel-Agent化改造工作量评估-20260929》P0 前置交付:
- prompts.py   系统提示词分层组装(L0~L3,每轮全量重建)
- guard.py     注入防御原语(数据消毒 / 参数钳制 / 泄露检测)
- tools.py     工具 schema 与校验(P0 四工具;edit_image P1 接入)
- llm_client.py OpenAI 兼容客户端(本地 llama.cpp / 云 API 双适配,非流式 tool 阶段)
- orchestrator.py tool-use 循环(异步任务语义:入队即返回,不等待生成)
- session_store.py 会话存储骨架(内存版,接口向 SQLite 演进稳定)

尚未接入(后续批次):
- routes/agent_routes.py(POST /api/agent/chat,SSE 流式)
- GenerationService 真实 tool 执行器装配
- SQLite 会话持久化与 history_db 挂接
- config.yaml agent 段(当前走 .env 环境变量,零 config 侵入)
"""

from .orchestrator import AgentEvent, AgentOrchestrator  # noqa: F401
from .session_store import AgentSession, InMemorySessionStore  # noqa: F401
