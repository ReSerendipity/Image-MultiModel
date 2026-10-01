// Image MultiModel 前端冒烟测试（jsdom）
// 运行：node tests/frontend/smoke.js（依赖 jsdom）
// 前置：python scripts/render_pages.py（渲染 Jinja2 模板到 _rendered/）
// 模拟后端数据，不依赖真实服务；断言失败 exit 1。
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const ROOT = path.join(__dirname, '..', '..');
const RENDERED = path.join(__dirname, '_rendered');
const HTML_FILE = path.join(RENDERED, 'index.html');
const APP_JS = path.join(ROOT, 'app', 'integrated_app', 'static', 'js', 'app.js');
// M4：Agent 抽屉由 chat.js 挂载，问 AI 入口的冒烟必须连它一起装（否则 window.agentAskWithImage 不存在）
const CHAT_JS = path.join(ROOT, 'app', 'integrated_app', 'static', 'js', 'chat.js');

/* ============ 模拟后端 ============ */
const MOCK = {
  '/api/health': {
    status: 'ok', version: '9.9.9',
    queue: { pending: 0, processing: 0 },
    gpu: { total_vram_gb: 24, free_vram_gb: 20, used_vram_gb: 4 },
    memory: { total_gb: 64, used_gb: 30, percent: 47 },
    disk: { total_gb: 1000, used_gb: 500 },
    engines: [{ name: 'z_image_turbo_native', display_name: 'Z-Image Turbo', state: 'loaded' }]
  },
  '/api/config': {
    version: '9.9.9',
    inference: { default_steps: 8, default_cfg: 1.0, default_seed: -1, default_batch_size: 1 },
    models: {
      default_engine: 'z_image_turbo_native',
      engines: { z_image_turbo_native: { display_name: 'Z-Image Turbo', default_width: 1024, default_height: 1024 } }
    }
  },
  // ⚠️ 坑（2026-09-01）：后端 GET /api/config/loras 返回 **相对路径字符串数组**
  // （config_routes.py: {"loras": files, "count": n, "mode": ...}），前端 app.js
  // 按字符串调用 p.split('/')。此前 mock 写成对象数组，导致下拉构建时抛
  // "TypeError: p.split is not a function"，该项被静默跳过（测试却仍显示通过）。
  '/api/config/loras': { loras: ['a.safetensors', 'b.safetensors'], count: 2, mode: 'portable' },
  '/api/outputs': {
    outputs: [{ path: 'fake_00001_.png', engine: 'z_image_turbo_native', prompt: 'a cat', output_type: 'original', width: 1024, height: 1024, created_at: '2026-08-17T12:00:00' }],
    total: 1
  },
  '/api/tasks': { tasks: [], total: 0 },
  '/api/presets': { presets: [] },
  '/api/engine/engines': {
    engines: [{ name: 'z_image_turbo_native', display_name: 'Z-Image Turbo', state: 'loaded', ready: true }],
    active_engine: 'z_image_turbo_native',
    count: 1
  }
};

// M6：记录所有 fetch 调用，供「执行编辑」桥接断言请求体形状（否则只能看到 ok）
const MOCK_CALLS = [];

function mockFetch(u, o) {
  u = String(u);
  const method = (o && o.method) || 'GET';
  const pathname = u.split('?')[0];
  MOCK_CALLS.push({ url: pathname, method: method, body: o && o.body ? String(o.body) : '' });
  const j = (x) => Promise.resolve({
    json: () => Promise.resolve(x), ok: true, status: 200,
    headers: { get: () => null }
  });
  if (MOCK[pathname]) {
    if (pathname === '/api/presets' && method === 'POST') return j({ id: 'p1', name: 'x' });
    return j(MOCK[pathname]);
  }
  if (method === 'POST' && pathname === '/api/generate') return j({ task_id: 't1', status: 'pending' });
  if (method === 'PUT' || method === 'DELETE') return j({});
  return Promise.reject(new Error('unmocked ' + u));
}

/* ============ EventSource polyfill（jsdom 无原生实现） ============ */
function FakeEventSource(url) {
  this.url = url;
  this._handlers = {};
  FakeEventSource.instances.push(this);
}
FakeEventSource.instances = [];
FakeEventSource.prototype.addEventListener = function (t, cb) {
  (this._handlers[t] = this._handlers[t] || []).push(cb);
};
FakeEventSource.prototype.close = function () {};
FakeEventSource.prototype.dispatch = function (t, data) {
  (this._handlers[t] || []).forEach(function (cb) { cb({ data: JSON.stringify(data) }); });
};

/* ============ 启动 ============ */
function boot(opts) {
  opts = opts || {};
  const errors = [];
  // ⚠️ 坑（2026-09-01）：FakeEventSource.instances 是跨 boot 共享的全局数组，
  // 若不重置，instances[0] 永远指向**第一轮** JSDOM 的 SSE 连接，后续各测试段
  // 的 es.dispatch() 会作用到早已废弃的 DOM 上，导致 SSE 相关断言静默失败。
  FakeEventSource.instances = [];
  const dom = new JSDOM(fs.readFileSync(HTML_FILE, 'utf-8'), {
    runScripts: 'dangerously', pretendToBeVisual: true, url: 'http://localhost/',
    beforeParse(w) {
      w.fetch = mockFetch;
      w.EventSource = FakeEventSource;
      w.alert = (m) => { if (opts.logAlerts) console.log('  [alert]', m); };
      w.confirm = () => true;
      w.addEventListener('error', (e) => errors.push(String((e.error && e.error.message) || e.message)));
      if (opts.theme) w.localStorage.setItem('imm_theme', opts.theme);
      if (opts.lang) w.localStorage.setItem('imm_lang', opts.lang);
    }
  });
  // jsdom 默认不拉取外部脚本：手动注入 app.js（+ chat.js，M4 起）执行
  const s = dom.window.document.createElement('script');
  s.textContent = fs.readFileSync(APP_JS, 'utf-8');
  dom.window.document.body.appendChild(s);
  const s2 = dom.window.document.createElement('script');
  s2.textContent = fs.readFileSync(CHAT_JS, 'utf-8');
  dom.window.document.body.appendChild(s2);
  return { dom, errors };
}

let pass = 0, fail = 0;
function assert(c, m) { if (c) { pass++; console.log('  ok - ' + m); } else { fail++; console.log('  FAIL - ' + m); } }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// 支持传入「选择器字符串」或「元素对象」。
// ⚠️ 坑（2026-09-01）：原实现只接受选择器字符串，而 test 中 click(d, jaBtn)
// 传入的是元素对象；querySelector(元素) 会把元素转成 "[object HTMLLIElement]"
// 这种非法选择器，导致 nwsapi 抛 DOMException 并让整个 smoke 进程崩溃退出。
const click = (d, target) => {
  const el = typeof target === 'string' ? d.querySelector(target) : target;
  if (!el) { fail++; console.log('  FAIL - click target not found: ' + target); return; }
  el.dispatchEvent(new d.defaultView.MouseEvent('click', { bubbles: true, cancelable: true }));
};

(async () => {
  /* ============ 骨架 + 后端数据加载 ============ */
  console.log('[boot + data load]');
  {
    const { dom, errors } = boot({});
    const d = dom.window.document;
    await sleep(350);
    assert(errors.length === 0, 'init no errors: ' + errors.join(' | '));
    assert(d.getElementById('sbConnText').textContent === 'CONN: OK', 'health → CONN: OK');
    assert(d.getElementById('aboutVersion').textContent === '9.9.9', 'health → about version 9.9.9');
    const engItems = [...d.querySelectorAll('#engMenu .ip-item')];
    assert(engItems.length === 1 && engItems[0].textContent === 'Z-Image Turbo', 'engine menu from /api/config');
    assert(d.getElementById('snapRes').textContent === '1024 × 1024', 'snap chips: 1024 × 1024');
    assert(d.getElementById('snapSteps').textContent === '8', 'snap chips: steps 8');
    const cards = [...d.querySelectorAll('#outGrid .r-card')];
    assert(cards.length === 1 && cards[0].textContent.includes('a cat'), 'recent outputs render 1 card');
    assert(d.getElementById('statLoras').textContent.includes('2 个文件'), 'LoRA scan: 2 files');
  }

  /* ============ Prompt 输入交互 ============ */
  console.log('[prompt input]');
  {
    const { dom, errors } = boot({});
    const d = dom.window.document;
    await sleep(350);
    assert(errors.length === 0, 'init no errors');
    const ta = d.getElementById('posPrompt');
    ta.value = '一只猫在窗边';
    ta.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
    assert(d.getElementById('posMeta').textContent.startsWith('6 字符'), 'char/token meta updates');
    click(d, '#clearPos');
    assert(ta.value === '', 'clear button empties prompt');
    click(d, '#negToggle');
    assert(d.getElementById('negBox').classList.contains('open'), 'negative prompt box opens');
  }

  /* ============ 主题 + 语言切换持久化 ============ */
  console.log('[theme + i18n]');
  {
    const { dom, errors } = boot({ theme: 'dark', lang: 'zh-CN' });
    const d = dom.window.document;
    await sleep(350);
    assert(errors.length === 0, 'init no errors');
    assert(d.documentElement.getAttribute('data-theme') === 'dark', 'stored theme pre-applied');
    click(d, '#themeToggle');
    assert(d.documentElement.getAttribute('data-theme') === 'light', 'theme toggles to light');
    assert(dom.window.localStorage.getItem('imm_theme') === 'light', 'theme persisted');
    const jaBtn = [...d.querySelectorAll('#langMenu .ip-item')].find(b => b.dataset.l === 'ja-JP');
    click(d, jaBtn);
    assert(d.documentElement.getAttribute('data-lang') === 'ja-JP', 'language switches to ja-JP');
    assert(dom.window.localStorage.getItem('imm_lang') === 'ja-JP', 'language persisted');
    assert(d.getElementById('genBtn').textContent.includes('生成'), 'btn label translated');
  }

  /* ============ 抽屉：高级参数 / 图库 / 批量 ============ */
  console.log('[drawers]');
  {
    const { dom, errors } = boot({});
    const d = dom.window.document;
    await sleep(350);
    assert(errors.length === 0, 'init no errors');
    click(d, '#drawerToggle');
    assert(d.getElementById('drawer').classList.contains('open'), 'advanced drawer opens');
    assert(d.getElementById('mTitle').textContent === '高级参数', 'drawer title 高级参数');
    click(d, '#drawerClose');
    assert(!d.getElementById('drawer').classList.contains('open'), 'drawer closes');
    click(d, '#openGallery');
    await sleep(50);
    assert(d.getElementById('galleryDrawer').classList.contains('open'), 'gallery drawer opens');
    const gCards = [...d.querySelectorAll('#gMasonry .g-card')];
    assert(gCards.length === 1 && gCards[0].textContent.includes('a cat'), 'gallery renders 1 card');
    click(d, '#openBatch');
    await sleep(50);
    assert(d.getElementById('batchDrawer').classList.contains('open'), 'batch drawer opens');
    assert(d.getElementById('bFileStat').textContent === '0 个 · 0 行', 'batch summary initial');
    assert(d.getElementById('bSubmit').getAttribute('data-i18n') === 'btn_generate_batch', 'batch submit button wired');
  }

  /* ============ 悬浮查看器：点击图库卡片打开 ============ */
  console.log('[viewer]');
  {
    const { dom, errors } = boot({});
    const d = dom.window.document;
    await sleep(350);
    assert(errors.length === 0, 'init no errors');
    click(d, '#openGallery');
    await sleep(50);
    click(d, '#gMasonry .g-card');
    assert(d.getElementById('viewer').classList.contains('show'), 'viewer opens on card click');
    assert(d.getElementById('vTitle').textContent === 'a cat', 'viewer title = prompt');
    // ⚠️ 坑（2026-09-01）：原断言额外要求 vImg.textContent !== ''，但 vImg 的
    // innerHTML 只有一个 <img> 标签，本身不含任何文本节点，textContent 恒为空串，
    // 该断言在任何情况下都不可能通过。改为校验 img 元素存在且 src 指向 outputs。
    const vImgEl = d.getElementById('vImg').querySelector('img');
    assert(!!vImgEl && vImgEl.getAttribute('src').includes('/api/outputs/'), 'viewer renders image');
    click(d, '#vClose');
    assert(!d.getElementById('viewer').classList.contains('show'), 'viewer closes');
  }

  /* ============ SSE：task_status 进度 → 完成 ============ */
  console.log('[sse]');
  {
    const { dom, errors } = boot({});
    const d = dom.window.document;
    await sleep(350);
    assert(errors.length === 0, 'init no errors');
    const es = FakeEventSource.instances[0];
    assert(!!es, 'EventSource created');
    // ⚠️ 坑（2026-09-01）：后端 native/engine.py 下发的 phase 是 **完整 i18n 键**
    // （如 'phase_sampling'），前端 trPhase() 直接用该键查 I18N 字典；
    // 传 'sampling' 会查不到而原样回显为英文裸键。此处需与后端契约保持一致。
    es.dispatch('task_status', { task_id: 't1', status: 'processing', progress: 40, phase: 'phase_sampling' });
    assert(d.getElementById('progFill').style.width === '40%', 'progress bar 40%');
    assert(d.getElementById('phaseText').textContent.includes('采样中'), 'phase text translated');
    es.dispatch('task_status', { task_id: 't1', status: 'completed', result: ['fake_00001_.png'] });
    assert(d.getElementById('phaseText').textContent.includes('完成'), 'completion updates phase text');
    assert(d.getElementById('progFill').style.width === '100%', 'progress bar 100%');
  }

  /* ============ 队列悬浮球 ============ */
  console.log('[queue pill]');
  {
    const { dom, errors } = boot({});
    const d = dom.window.document;
    await sleep(350);
    assert(errors.length === 0, 'init no errors');
    click(d, '#queuePill');
    await sleep(50);
    assert(d.getElementById('queuePop').classList.contains('show'), 'queue popover opens');
    assert(d.getElementById('queueItems').textContent.includes('队列空闲'), 'empty queue shows 队列空闲');
    assert(d.getElementById('qCancelBtn').getAttribute('type') === 'button', 'cancel button present');
  }

  /* ============ 可访问性抽查（aria / 键盘可达） ============ */
  console.log('[a11y spot-check]');
  {
    const { dom, errors } = boot({});
    const d = dom.window.document;
    await sleep(300);
    assert(errors.length === 0, 'init no errors');
    const iconBtns = [...d.querySelectorAll('.topbar .icon-btn')];
    assert(iconBtns.length >= 4 && iconBtns.every(b => b.tagName === 'BUTTON'), 'topbar buttons are buttons');
    assert(d.getElementById('genBtn').tagName === 'BUTTON', 'generate is a button');
    assert(d.getElementById('posPrompt').tagName === 'TEXTAREA', 'prompt is textarea');
    const viewerBtns = [...d.querySelectorAll('#viewer .v-tools button')];
    assert(viewerBtns.length >= 10 && viewerBtns.every(b => b.getAttribute('aria-label')), 'viewer tools have aria-label');
  }

  /* ============ M4「问 AI」入口（多模态首条上下文） ============ */
  console.log('[ask-ai entry]');
  {
    const { dom, errors } = boot({});
    const d = dom.window.document;
    await sleep(350);
    assert(errors.length === 0, 'init no errors');
    // 1) 静态入口存在：查看器工具条 + 历史详情按钮行
    assert(!!d.getElementById('vAskAI') && d.getElementById('vAskAI').getAttribute('type') === 'button',
      'viewer exposes #vAskAI button');
    assert(!!d.getElementById('ddAskAI') && d.getElementById('ddAskAI').getAttribute('type') === 'button',
      'history detail exposes #ddAskAI button');
    assert(d.getElementById('vAskAI').getAttribute('aria-label') === '问 AI', 'vAskAI has中文 aria-label');
    assert(d.getElementById('vAskAI').getAttribute('data-i18n') === 'btn_ask_ai', 'vAskAI carries i18n key');
    // 2) 画廊卡片悬浮按钮：DOM 里恒存在（仅靠 CSS 隐身），hover 前后都可断言
    click(d, '#openGallery');
    await sleep(60);
    const asks = [...d.querySelectorAll('#gMasonry .g-card .g-ask')];
    assert(asks.length >= 1, 'gallery card renders .g-ask button');
    assert(asks.every(b => b.tagName === 'BUTTON' && b.getAttribute('aria-label')), 'g-ask buttons have aria-label');
    assert(asks[0].getAttribute('aria-label') === '问 AI', 'g-ask label from chat.js i18n');
  }

  /* ============ M4：挂图开抽屉（不代用户编提问） ============ */
  console.log('[ask-ai opens drawer]');
  {
    const { dom, errors } = boot({});
    const d = dom.window.document;
    await sleep(350);
    assert(errors.length === 0, 'init no errors');
    const api = dom.window.agentAskWithImage;
    assert(typeof api === 'function', 'window.agentAskWithImage exposed by chat.js');
    // 画廊形态的相对段路径（非 outputs/ 前缀）也要能吃
    assert(api('fake_00001_.png', '') === true, 'accepts gallery-style relative path');
    const drawer = d.getElementById('agent-drawer');
    assert(drawer.classList.contains('open'), 'drawer auto-opens on ask-with-image');
    const thumbs = [...d.querySelectorAll('#agent-msgs .agent-msg.user img[data-agent-thumb]')];
    assert(thumbs.length === 1, 'user bubble carries 1 image thumb');
    assert(thumbs[0].getAttribute('src').includes('/api/outputs/'), 'thumb src points to /api/outputs');
    assert(d.getElementById('agent-input').value === '', "no prompt → input left empty (do not fake a question)");
    // 越界/绝对路径：拒绝挂载，且给出可读原因（不静默）
    assert(api('C:/Windows/system.ini', '') === false, 'rejects absolute out-of-tree path');
    assert(api('../../etc/passwd', '') === false, 'rejects traversal path');
    const errs = [...d.querySelectorAll('#agent-msgs .agent-msg.err')];
    assert(errs.length >= 1 && errs[0].textContent.indexOf('outputs') >= 0, 'rejection is surfaced to user');
  }

  /* ============ M4：g-ask 点击只挂图，不打开查看器 ============ */
  console.log('[g-ask does not hijack card click]');
  {
    const { dom, errors } = boot({});
    const d = dom.window.document;
    await sleep(350);
    assert(errors.length === 0, 'init no errors');
    click(d, '#openGallery');
    await sleep(60);
    click(d, '#gMasonry .g-card .g-ask');
    assert(!d.getElementById('viewer').classList.contains('show'), 'card click not triggered by g-ask (stopPropagation)');
    assert(d.getElementById('agent-drawer').classList.contains('open'), 'g-ask still opens agent drawer');
  }

  /* ============ M5：多轮图气泡（输入 40×40 / 输出 120×120 + 点击放大） ============ */
  console.log('[agent image bubbles]');
  {
    const { dom, errors } = boot({});
    const d = dom.window.document;
    await sleep(350);
    assert(errors.length === 0, 'init no errors');
    const internals = dom.window.__agentChatInternals;
    // 输出档：生成结果缩略 go 到 .agent-img-out（CSS 里 120×120）
    const outBox = d.createElement('div');
    d.getElementById('agent-msgs').appendChild(outBox);
    internals.renderOutputs(['outputs/2026/10/a.png'], outBox);
    const outImg = outBox.querySelector('img.agent-img-out');
    assert(!!outImg && outImg.getAttribute('data-agent-thumb') === '1', 'output thumb rendered with .agent-img-out');
    assert(outImg.getAttribute('src').includes('/api/outputs/'), 'output thumb src is /api/outputs');
    // 输入档：用户气泡带 .with-img（CSS 里 40×40）
    dom.window.agentAskWithImage('fake_00001_.png', '');
    const userBubble = d.querySelector('#agent-msgs .agent-msg.user.with-img');
    assert(!!userBubble, 'user bubble gets .with-img for flex thumbnail grid');
    const inImg = userBubble.querySelector('img[data-agent-thumb]');
    assert(inImg.getAttribute('title') === '点击放大', 'thumb carries enlarge hint (zh-CN)');
    // 点击放大 → 走现有全屏查看器：点哪张就渲染哪张（enlargeThumb 从 URL 反解回仓库相对路径）
    click(d, outImg);
    assert(d.getElementById('viewer').classList.contains('show'), 'output thumb click opens existing viewer');
    let vImg = d.getElementById('vImg').querySelector('img');
    assert(!!vImg && vImg.getAttribute('src').includes('a.png'), 'viewer renders the clicked output file');
    click(d, inImg);
    vImg = d.getElementById('vImg').querySelector('img');
    assert(!!vImg && vImg.getAttribute('src').includes('fake_00001_.png'), 'viewer renders the clicked input file');
    assert(internals.enlargeThumb('/not-an-outputs-path/x.png') === undefined, 'enlargeThumb no-ops off outputs');
  }

  /* ============ M6：编辑指令桥接（final.edit_intent → 「执行编辑」→ POST /api/generate） ============ */
  console.log('[agent edit bridge]');
  {
    const { dom, errors } = boot({});
    const d = dom.window.document;
    await sleep(350);
    assert(errors.length === 0, 'init no errors');
    const internals = dom.window.__agentChatInternals;
    const intent = {
      prompt: '把背景换成雪天，加一点飘雪',
      source: '[[EDIT]]把背景换成雪天，加一点飘雪[[/EDIT]]',
      reference_images: ['fake_00001_.png'],
      engine_name: 'qwen_image_edit_native'
    };
    // 走真实链路：final 事件 → 气泡 → 挂按钮（不经内部函数直调）
    internals.handleEvent({
      type: 'final',
      text: '可以。把背景换成雪天，加一点飘雪',
      edit_intent: intent
    });
    const btn = d.querySelector('#agent-msgs .agent-msg.agent .agent-edit-btn');
    assert(!!btn, 'final.edit_intent attaches an edit button under the bubble');
    assert(!!btn && !btn.disabled, 'edit button enabled when engine + reference image present');
    assert(!!btn && btn.getAttribute('data-agent-edit') === '1', 'edit button is machine-identifiable');
    MOCK_CALLS.length = 0;
    click(d, btn);
    await sleep(120);
    const gen = MOCK_CALLS.filter((c) => c.url === '/api/generate' && c.method === 'POST');
    assert(gen.length === 1, 'clicking posts exactly one /api/generate request');
    const body = gen.length ? JSON.parse(gen[0].body) : {};
    assert(body.edit_mode === true, 'edit_mode=true (real contract, not ?mode=edit)');
    assert(body.reference_image_path === 'fake_00001_.png', 'reference image is the attached output path');
    assert(body.positive_prompt === intent.prompt, 'positive_prompt = parsed intent prompt');
    assert(body.seedvr2_enable === false && body.eses_enable === false, 'post-processing off for edit runs');
    // 无编辑引擎：按钮禁用 + 如实说明，绝不静默降级成普通文生图
    internals.handleEvent({
      type: 'final',
      text: '可以。',
      edit_intent: { prompt: '换背景', reference_images: ['fake_00001_.png'], engine_name: null }
    });
    const disabled = d.querySelector('#agent-msgs .agent-msg.agent:last-of-type .agent-edit-btn');
    assert(!!disabled && disabled.disabled === true, 'no edit engine → button disabled, not a silent fallback');
    assert(!!disabled && disabled.textContent === '无可用编辑引擎', 'disabled button explains why');
  }

  console.log('\nRESULT: pass=' + pass + ' fail=' + fail);
  process.exit(fail ? 1 : 0);
})();
