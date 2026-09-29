// tests/frontend/agent_chat.js — Agent 对话面板（chat.js）前端冒烟测试（jsdom）
//
// 运行：node tests/frontend/agent_chat.js
// 前置：npm install（tests/package.json 的 jsdom）；不需要渲染模板、不需要后端。
//
// 重点回归（评估报告第十章遗留问题 #1）：
//   GET /api/tasks/{id} 返回的是 **history_db 行结构**（status 小写、输出在
//   outputs[].path、无 result 字段），而 chat.js 早期按内存 Task 结构读取
//   （大写 COMPLETED + task.result），导致任务完成后图片永不回显。
//   本测试用真实形态的载荷驱动一遍「入队 → 轮询 → 出图」，防止再次回归。
//
// ⚠️ 坑（沿用 smoke.js 的教训）：jsdom 不提供 fetch / TextDecoder，必须自己注入；
//   轮询用的是 setInterval，测试里把它换成短周期，否则要等 2s × N 轮。

const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const ROOT = path.join(__dirname, '..', '..');
const CHAT_JS = path.join(ROOT, 'app', 'integrated_app', 'static', 'js', 'chat.js');

let pass = 0;
let fail = 0;
function assert(cond, msg) {
  if (cond) { pass++; console.log('  ok - ' + msg); } else { fail++; console.log('  FAIL - ' + msg); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* ============ 后端替身 ============ */

// history_db 行结构（task_routes.get_task 的真实形态）
const HISTORY_DB_TASK = {
  task_id: 't-hdb-1',
  engine: 'z_image_turbo_native',
  mode: 'txt2img',
  prompt: 'a cyberpunk cat',
  negative_prompt: '',
  status: 'completed', // ⚠️ 小写
  error: '',
  error_code: '',
  processing_time_s: 12.5,
  output_count: 2,
  thumbnail: '',
  created_at: '2026-09-29 12:00:00',
  updated_at: '2026-09-29 12:00:12',
  generation_config: {},
  tags: [],
  lora_checksums: [],
  outputs: [
    { id: 1, task_id: 't-hdb-1', path: 'z_image_turbo_native/20260929/aaa_0_AI.png', output_type: 'original', width: 1024, height: 1024 },
    { id: 2, task_id: 't-hdb-1', path: 'z_image_turbo_native/20260929/aaa_1_AI.png', output_type: 'upscaled', width: 2048, height: 2048 }
  ]
};

const SSE_FRAMES = [
  'data: {"type":"tool_call","name":"generate_image","args":{"positive_prompt":"a cyberpunk cat"},"violations":[]}\n\n',
  'data: {"type":"task_created","task_id":"t-hdb-1"}\n\n',
  'data: {"type":"final","text":"已提交生成任务。"}\n\n',
  'data: [DONE]\n\n'
];

function sseBody(frames) {
  const encoder = new TextEncoder();
  const chunks = frames.map((f) => encoder.encode(f));
  let i = 0;
  return {
    getReader() {
      return {
        read() {
          if (i < chunks.length) return Promise.resolve({ done: false, value: chunks[i++] });
          return Promise.resolve({ done: true, value: undefined });
        }
      };
    }
  };
}

function makeFetch(taskPayload, calls) {
  return function fetchMock(url, opts) {
    const u = String(url);
    const method = (opts && opts.method) || 'GET';
    calls.push(method + ' ' + u);
    if (u.indexOf('/api/agent/chat') === 0) {
      return Promise.resolve({ ok: true, status: 200, body: sseBody(SSE_FRAMES) });
    }
    if (u.indexOf('/api/tasks/') === 0) {
      if (!taskPayload) return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(taskPayload) });
    }
    return Promise.reject(new Error('unmocked ' + u));
  };
}

function boot(opts) {
  opts = opts || {};
  const errors = [];
  const calls = [];
  const dom = new JSDOM('<!DOCTYPE html><html lang="zh-CN" data-lang="zh-CN"><head></head><body></body></html>', {
    runScripts: 'dangerously',
    pretendToBeVisual: true,
    url: 'http://localhost/',
    beforeParse(w) {
      w.fetch = makeFetch(opts.task, calls);
      w.TextDecoder = TextDecoder;
      w.TextEncoder = TextEncoder;
      // CSRF 懒获取走同步 XHR：替身直接给一个 token，避免真实网络请求
      w.XMLHttpRequest = function () {
        this.open = function () {};
        this.send = function () {};
        this.getResponseHeader = function () { return 'csrf-test-token'; };
      };
      // 轮询周期 2000ms → 5ms，让测试不必等待
      w.setInterval = (fn, ms) => setInterval(fn, 5);
      w.clearInterval = (id) => clearInterval(id);
      w.addEventListener('error', (e) => errors.push(String((e.error && e.error.message) || e.message)));
    }
  });
  const s = dom.window.document.createElement('script');
  s.textContent = fs.readFileSync(CHAT_JS, 'utf-8');
  dom.window.document.body.appendChild(s);
  // jsdom 构造后 readyState 仍是 'loading'，chat.js 会挂 DOMContentLoaded 监听；
  // 这里主动派发一次让 init() 立即执行（init 有 #agent-fab 幂等守卫，重复派发安全）。
  if (dom.window.document.readyState === 'loading') {
    dom.window.document.dispatchEvent(new dom.window.Event('DOMContentLoaded'));
  }
  return { dom, errors, calls };
}

/* ============ 用例 ============ */
(async () => {
  console.log('[骨架挂载 + i18n]');
  {
    const { dom, errors } = boot({});
    const d = dom.window.document;
    assert(errors.length === 0, 'init 无异常: ' + errors.join(' | '));
    assert(!!d.getElementById('agent-fab'), 'fab 已挂载');
    assert(!!d.getElementById('agent-drawer'), 'drawer 已挂载');
    assert(d.getElementById('agent-input').placeholder.includes('描述'), 'zh-CN 占位文案');
    assert(d.getElementById('agent-send').textContent === '发送', 'zh-CN 发送按钮');

    // 语言切换跟随（app.js 的 applyLang 会改 data-lang）
    d.documentElement.setAttribute('data-lang', 'en-US');
    await sleep(30);
    assert(d.getElementById('agent-input').placeholder.includes('Describe'), 'en-US 占位文案已跟随');
    assert(d.getElementById('agent-send').textContent === 'Send', 'en-US 发送按钮已跟随');
    assert(d.getElementById('agent-head').textContent.includes('AI Chat Generate'), 'en-US 标题已跟随');

    d.documentElement.setAttribute('data-lang', 'ja-JP');
    await sleep(30);
    assert(d.getElementById('agent-send').textContent === '送信', 'ja-JP 发送按钮已跟随');

    const api = dom.window.__agentChatInternals;
    assert(api.t('task_done', { id: 'x' }).indexOf('x') >= 0, 'i18n 变量插值可用');
    assert(api.currentLang() === 'ja-JP', 'currentLang 读取 data-lang');
  }

  console.log('[载荷归一化：history_db vs 内存 Task]');
  {
    const { dom } = boot({});
    const api = dom.window.__agentChatInternals;

    const a = api.normalizeTask(HISTORY_DB_TASK);
    assert(a.status === 'completed', 'history_db 小写 status 归一化: ' + a.status);
    assert(a.paths.length === 1, 'outputs 有 original 时只取 original（跳过 upscaled）: ' + a.paths.length);
    assert(a.paths[0] === 'z_image_turbo_native/20260929/aaa_0_AI.png', 'original 优先，路径正确');

    // outputs 里没有 original 时回退全部
    const b = api.normalizeTask({ status: 'COMPLETED', outputs: [{ path: 'x.png', output_type: 'upscaled' }] });
    assert(b.status === 'completed' && b.paths[0] === 'x.png', '大写 status 也兼容（内存 Task）');

    const b2 = api.normalizeTask({ status: 'completed', outputs: [{ path: 'u.png', output_type: 'upscaled' }, { path: 'c.png', output_type: 'compare' }] });
    assert(b2.paths.length === 2, '无 original 时回退全部输出');

    // 内存 Task 形态
    const c = api.normalizeTask({ status: 'completed', result: ['outputs/a.png', 'outputs/b.png'] });
    assert(c.paths.length === 2 && c.paths[0] === 'outputs/a.png', '内存 Task result 数组兼容');

    // 空/异常载荷不得抛错
    assert(api.normalizeTask(null).paths.length === 0, 'null 载荷安全');
    assert(api.normalizeTask({}).status === '', '空对象安全');

    // 输出 URL
    assert(api.outputUrl('z_image_turbo_native/20260929/a.png') === '/api/outputs/z_image_turbo_native/20260929/a.png',
      '相对路径 → /api/outputs/...');
    assert(api.outputUrl('outputs\\2026\\a b.png') === '/api/outputs/2026/a%20b.png',
      '反斜杠 + 空格 → 规范化并转义');
    assert(api.outputUrl('C:\\Users\\Doro\\AppData\\Local\\Temp\\fake_0000.png') === null,
      'outputs/ 之外的绝对路径 → 不渲染（避免必然 403/404）');
    assert(api.outputUrl('') === null, '空路径 → null');
  }

  console.log('[端到端：入队 → 轮询 history_db → 出图]');
  {
    const { dom, errors, calls } = boot({ task: HISTORY_DB_TASK });
    const d = dom.window.document;
    d.getElementById('agent-input').value = '画一只赛博朋克橘猫';
    d.getElementById('agent-send').dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }));
    await sleep(200);

    assert(calls.some((c) => c.indexOf('POST /api/agent/chat') === 0), 'POST /api/agent/chat 已发出');
    assert(calls.some((c) => c.indexOf('GET /api/tasks/t-hdb-1') === 0), '轮询 GET /api/tasks/{id} 已发出');

    const text = d.getElementById('agent-msgs').textContent;
    assert(text.includes('调用 generate_image'), 'tool_call 事件已渲染');
    assert(text.includes('任务完成'), '完成态已渲染: ' + text.slice(0, 120));

    const imgs = [...d.querySelectorAll('#agent-msgs img')];
    assert(imgs.length === 1, '恰好渲染 1 张图（original 优先）');
    assert(imgs.length === 1 && imgs[0].src === 'http://localhost/api/outputs/z_image_turbo_native/20260929/aaa_0_AI.png',
      '图片 URL 正确: ' + (imgs[0] && imgs[0].src));
    assert(errors.length === 0, '端到端无异常: ' + errors.join(' | '));
  }

  console.log('[失败态与取消态]');
  {
    const { dom } = boot({ task: { status: 'failed', error: 'VRAM 不足', outputs: [] } });
    const d = dom.window.document;
    d.getElementById('agent-input').value = 'x';
    d.getElementById('agent-send').dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }));
    await sleep(200);
    const text = d.getElementById('agent-msgs').textContent;
    assert(text.includes('任务失败') && text.includes('VRAM 不足'), '失败原因回显: ' + text.slice(0, 120));
    assert(d.querySelectorAll('#agent-msgs img').length === 0, '失败态不出图');
  }

  {
    const { dom } = boot({ task: { status: 'interrupted', error: '', outputs: [] } });
    const d = dom.window.document;
    d.getElementById('agent-input').value = 'x';
    d.getElementById('agent-send').dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }));
    await sleep(200);
    assert(d.getElementById('agent-msgs').textContent.includes('任务失败'), 'interrupted 归入失败态');
  }

  console.log('[任务 404 不误判]');
  {
    const { dom } = boot({ task: null }); // 始终 404
    const d = dom.window.document;
    d.getElementById('agent-input').value = 'x';
    d.getElementById('agent-send').dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }));
    await sleep(120);
    const text = d.getElementById('agent-msgs').textContent;
    assert(!text.includes('任务失败'), '404 不得被当成失败');
    assert(text.includes('生成中'), '404 期间保持「生成中」: ' + text.slice(0, 120));
  }

  console.log('\nRESULT: pass=' + pass + ' fail=' + fail);
  process.exit(fail === 0 ? 0 : 1);
})();
