/*
 * chat.js — Agent 对话浮动面板（最小闭环前端半边）
 *
 * 依赖契约:
 * - POST /api/agent/chat（SSE 流；CSRF Double-Submit:X-CSRF-Token 头）
 * - GET  /api/tasks/{task_id}（轮询任务状态；两种载荷形态都要吃）
 * - GET  /api/agent/health（LLM 离线提示）
 * 事件:tool_call / task_created / tool_result / final / error / [DONE]
 *
 * ⚠️ 字段兼容（2026-09-29 修复，评估报告第十章遗留问题 #1）:
 *   `/api/tasks/{id}` 由 `task_routes.get_task` 直出 **history_db 行结构**，
 *   与内存 Task 对象不同：
 *     - status 为**小写** pending|processing|completed|failed|cancelled|interrupted
 *       （此前前端只比大写 'COMPLETED'，永远判不出完成 → 图片永不回显）；
 *     - 输出在 `outputs: [{path, output_type, ...}]`，**没有** `result` 字段
 *       （此前读 `task.result` 恒为 undefined）；
 *     - 无 progress/phase 字段（进度只在内存 Task 上）。
 *   `normalizeTask()` 统一两种形态，调用方只看归一化结果。
 *
 * i18n:五语言（zh-CN / zh-TW / en-US / ja-JP / ko-KR），语言取自
 *   `document.documentElement[data-lang]`（与 app.js 的 I18N 键一致），
 *   并用 MutationObserver 跟随语言切换即时重绘静态文案。
 */
(function () {
  'use strict';

  /* ============ i18n ============ */
  var I18N = {
    'zh-CN': {
      title: 'AI 对话生图',
      fab: 'AI 对话生图',
      input_ph: '描述你想生成的图片…',
      send: '发送',
      tool_call: '调用 {name}',
      tool_call_fixed: '调用 {name}（参数已自动修正：{v}）',
      task_queued: '任务已排队：{id}',
      task_running: '生成中…（{id}）',
      task_progress: '生成中… {pct}%',
      task_done: '任务完成（{id}）',
      task_failed: '任务失败（{id}）：{err}',
      task_cancelled: '任务已取消（{id}）',
      task_timeout: '任务轮询超时：{id}',
      task_unknown: '未知原因',
      img_alt: '生成结果',
      img_skipped: '任务完成，但有 {n} 个输出路径不可经 /api/outputs 访问，已跳过',
      err_request: '请求失败：{msg}（请确认服务与 LLM 大脑在线）'
    },
    'zh-TW': {
      title: 'AI 對話生圖',
      fab: 'AI 對話生圖',
      input_ph: '描述你想生成的圖片…',
      send: '傳送',
      tool_call: '呼叫 {name}',
      tool_call_fixed: '呼叫 {name}（參數已自動修正：{v}）',
      task_queued: '任務已排隊：{id}',
      task_running: '生成中…（{id}）',
      task_progress: '生成中… {pct}%',
      task_done: '任務完成（{id}）',
      task_failed: '任務失敗（{id}）：{err}',
      task_cancelled: '任務已取消（{id}）',
      task_timeout: '任務輪詢逾時：{id}',
      task_unknown: '未知原因',
      img_alt: '生成結果',
      img_skipped: '任務完成，但有 {n} 個輸出路徑無法經 /api/outputs 存取，已略過',
      err_request: '請求失敗：{msg}（請確認服務與 LLM 大腦在線）'
    },
    'en-US': {
      title: 'AI Chat Generate',
      fab: 'AI chat generation',
      input_ph: 'Describe the image you want…',
      send: 'Send',
      tool_call: 'Calling {name}',
      tool_call_fixed: 'Calling {name} (args auto-corrected: {v})',
      task_queued: 'Task queued: {id}',
      task_running: 'Generating… ({id})',
      task_progress: 'Generating… {pct}%',
      task_done: 'Task completed ({id})',
      task_failed: 'Task failed ({id}): {err}',
      task_cancelled: 'Task cancelled ({id})',
      task_timeout: 'Task polling timed out: {id}',
      task_unknown: 'unknown reason',
      img_alt: 'Generated result',
      img_skipped: 'Task completed, but {n} output path(s) are not reachable via /api/outputs and were skipped',
      err_request: 'Request failed: {msg} (check that the service and the LLM brain are online)'
    },
    'ja-JP': {
      title: 'AI 対話生成',
      fab: 'AI 対話生成',
      input_ph: '生成したい画像を説明してください…',
      send: '送信',
      tool_call: '{name} を呼び出し',
      tool_call_fixed: '{name} を呼び出し（引数を自動修正: {v}）',
      task_queued: 'タスクをキューに追加: {id}',
      task_running: '生成中…（{id}）',
      task_progress: '生成中… {pct}%',
      task_done: 'タスク完了（{id}）',
      task_failed: 'タスク失敗（{id}）: {err}',
      task_cancelled: 'タスクをキャンセルしました（{id}）',
      task_timeout: 'タスクのポーリングがタイムアウト: {id}',
      task_unknown: '不明な理由',
      img_alt: '生成結果',
      img_skipped: 'タスク完了。ただし {n} 件の出力パスは /api/outputs から取得できないためスキップしました',
      err_request: 'リクエスト失敗: {msg}（サービスと LLM ブレインの起動を確認してください）'
    },
    'ko-KR': {
      title: 'AI 대화 생성',
      fab: 'AI 대화 생성',
      input_ph: '생성할 이미지를 설명하세요…',
      send: '전송',
      tool_call: '{name} 호출',
      tool_call_fixed: '{name} 호출 (인자 자동 수정: {v})',
      task_queued: '작업 대기열 추가: {id}',
      task_running: '생성 중… ({id})',
      task_progress: '생성 중… {pct}%',
      task_done: '작업 완료 ({id})',
      task_failed: '작업 실패 ({id}): {err}',
      task_cancelled: '작업 취소됨 ({id})',
      task_timeout: '작업 폴링 시간 초과: {id}',
      task_unknown: '알 수 없는 원인',
      img_alt: '생성 결과',
      img_skipped: '작업은 완료되었으나 {n}개의 출력 경로를 /api/outputs 로 가져올 수 없어 건너뛰었습니다',
      err_request: '요청 실패: {msg} (서비스와 LLM 두뇌가 온라인인지 확인하세요)'
    }
  };
  var DEFAULT_LANG = 'zh-CN';
  var LANG_ALIASES = {
    'zh': 'zh-CN', 'zh-cn': 'zh-CN', 'zh-hans': 'zh-CN',
    'zh-tw': 'zh-TW', 'zh-hant': 'zh-TW', 'zh-hk': 'zh-TW',
    'en': 'en-US', 'en-us': 'en-US', 'en-gb': 'en-US',
    'ja': 'ja-JP', 'ja-jp': 'ja-JP',
    'ko': 'ko-KR', 'ko-kr': 'ko-KR'
  };

  function currentLang() {
    var raw = document.documentElement.getAttribute('data-lang') || DEFAULT_LANG;
    if (I18N[raw]) return raw;
    return LANG_ALIASES[String(raw).toLowerCase()] || DEFAULT_LANG;
  }

  function t(key, vars) {
    var dict = I18N[currentLang()] || I18N[DEFAULT_LANG];
    var text = dict[key] || I18N[DEFAULT_LANG][key] || key;
    if (vars) {
      Object.keys(vars).forEach(function (k) {
        text = text.split('{' + k + '}').join(String(vars[k]));
      });
    }
    return text;
  }

  /* ============ CSRF ============ */
  var _csrfToken = null;
  function csrfToken() {
    if (_csrfToken) return _csrfToken;
    try {
      var r = new XMLHttpRequest();
      r.open('GET', '/api/health', false); // 同步取 token（与 app.js 的懒获取策略一致）
      r.send(null);
      var tok = r.getResponseHeader('X-CSRF-Token');
      if (tok) _csrfToken = tok;
    } catch (e) { /* 离线时后续 POST 会得到 403，面板提示 */ }
    return _csrfToken;
  }

  /* ============ 样式 / DOM 原语 ============ */
  var STYLE = [
    '#agent-fab{position:fixed;right:22px;bottom:22px;z-index:9990;width:52px;height:52px;',
    'border-radius:50%;border:none;background:#5e7d5a;color:#fff;font-size:22px;cursor:pointer;',
    'box-shadow:0 4px 14px rgba(0,0,0,.18)}',
    '#agent-drawer{position:fixed;right:22px;bottom:86px;z-index:9991;width:380px;max-height:70vh;',
    'display:none;flex-direction:column;background:#fff;border:1px solid rgba(0,0,0,.15);',
    'border-radius:12px;box-shadow:0 8px 28px rgba(0,0,0,.16);overflow:hidden}',
    '#agent-drawer.open{display:flex}',
    '#agent-head{padding:10px 14px;background:#eef2ec;font-weight:500;font-size:14px;display:flex;justify-content:space-between}',
    '#agent-msgs{flex:1;overflow-y:auto;padding:10px 14px;font-size:13px;line-height:1.6}',
    '.agent-msg{margin:6px 0;white-space:pre-wrap;word-break:break-word}',
    '.agent-msg.user{color:#1f2937}',
    '.agent-msg.agent{color:#0f6e56}',
    '.agent-msg.sys{color:#888;font-size:12px}',
    '.agent-msg.err{color:#a32d2d;font-size:12px}',
    '.agent-msg img{max-width:100%;border-radius:8px;margin-top:4px;border:1px solid rgba(0,0,0,.1)}',
    '#agent-form{display:flex;border-top:1px solid rgba(0,0,0,.12)}',
    '#agent-input{flex:1;border:none;padding:10px 12px;font-size:13px;outline:none}',
    '#agent-send{border:none;background:#5e7d5a;color:#fff;padding:0 16px;cursor:pointer}'
  ].join('');

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function addMsg(cls, text) {
    var box = document.getElementById('agent-msgs');
    var m = el('div', 'agent-msg ' + cls, text);
    box.appendChild(m);
    box.scrollTop = box.scrollHeight;
    return m;
  }

  /* ============ 任务载荷归一化 ============ */
  var TERMINAL = { completed: 1, failed: 1, cancelled: 1, interrupted: 1 };
  var MAX_OUTPUTS = 4;

  function normalizeStatus(raw) {
    return String(raw == null ? '' : raw).trim().toLowerCase();
  }

  /**
   * 把 history_db 行结构 / 内存 Task 结构统一成
   * `{status, paths, error, progress, phase}`。
   */
  function normalizeTask(task) {
    var out = { status: '', paths: [], error: '', progress: null, phase: '' };
    if (!task || typeof task !== 'object') return out;

    out.status = normalizeStatus(task.status);
    out.error = task.error || task.error_code || '';
    if (typeof task.progress === 'number') out.progress = task.progress;
    out.phase = task.phase || '';

    // 形态 A：history_db（outputs 为对象数组，取 original 优先）
    var outputs = task.outputs;
    if (Object.prototype.toString.call(outputs) === '[object Array]' && outputs.length) {
      var originals = outputs.filter(function (o) {
        return o && String(o.output_type || 'original') === 'original';
      });
      var picked = originals.length ? originals : outputs;
      out.paths = picked.map(function (o) {
        return (o && (o.path || o.file)) || '';
      }).filter(Boolean);
      return out;
    }

    // 形态 B：内存 Task（result 为路径数组；tool_result 里叫 result_paths）
    var raw = task.result || task.result_paths;
    if (Object.prototype.toString.call(raw) === '[object Array]') {
      out.paths = raw.filter(Boolean);
    }
    return out;
  }

  /**
   * 输出路径 → /api/outputs 可用 URL。
   * 只接受能落到 outputs/ 基目录内的相对路径；绝对路径或越界路径返回 null
   * （避免把本机绝对路径渲染成必然 403/404 的 <img>）。
   */
  function outputUrl(rawPath) {
    var path = String(rawPath || '').replace(/\\/g, '/').trim();
    if (!path) return null;
    var idx = path.indexOf('outputs/');
    if (idx >= 0) {
      path = path.slice(idx + 'outputs/'.length);
    } else if (/^[A-Za-z]:\//.test(path) || path.charAt(0) === '/') {
      return null; // 绝对路径不在 outputs/ 下 → 不可经 /api/outputs 访问
    }
    path = path.replace(/^\/+/, '');
    if (!path) return null;
    return '/api/outputs/' + path.split('/').map(encodeURIComponent).join('/');
  }

  /* ============ 任务轮询 ============ */
  function pollTask(taskId, target) {
    var tries = 0;
    var statusLine = addMsg('sys', t('task_running', { id: taskId }));
    var timer = setInterval(function () {
      tries += 1;
      if (tries > 150) { clearInterval(timer); statusLine.textContent = t('task_timeout', { id: taskId }); return; }
      fetch('/api/tasks/' + encodeURIComponent(taskId), { credentials: 'same-origin' })
        .then(function (r) {
          if (r.status === 404) return null; // 尚未落库/已清理：下一轮再试
          if (!r.ok) throw new Error('HTTP ' + r.status);
          return r.json();
        })
        .then(function (task) {
          if (!task) return;
          var info = normalizeTask(task);

          if (info.status === 'completed') {
            clearInterval(timer);
            statusLine.textContent = t('task_done', { id: taskId });
            renderOutputs(info.paths, target);
          } else if (info.status === 'failed' || info.status === 'interrupted') {
            clearInterval(timer);
            statusLine.className = 'agent-msg err';
            statusLine.textContent = t('task_failed', { id: taskId, err: info.error || t('task_unknown') });
          } else if (info.status === 'cancelled') {
            clearInterval(timer);
            statusLine.textContent = t('task_cancelled', { id: taskId });
          } else if (info.progress !== null) {
            statusLine.textContent = t('task_progress', { pct: info.progress });
          }
        })
        .catch(function () { /* 下一轮重试 */ });
    }, 2000);
  }

  function renderOutputs(paths, target) {
    var shown = 0;
    var skipped = 0;
    (paths || []).slice(0, MAX_OUTPUTS).forEach(function (p) {
      var url = outputUrl(p);
      if (!url) { skipped += 1; return; }
      var img = document.createElement('img');
      img.src = url;
      img.alt = t('img_alt');
      img.addEventListener('error', function () { img.style.display = 'none'; });
      target.appendChild(img);
      shown += 1;
    });
    if (!shown && !skipped) return;
    if (skipped) addMsg('sys', t('img_skipped', { n: skipped }));
  }

  /* ============ SSE 事件 ============ */
  function handleEvent(evt) {
    if (!evt || !evt.type) return;
    if (evt.type === 'tool_call') {
      var v = evt.violations && evt.violations.length ? evt.violations.join('; ') : '';
      addMsg('sys', v ? t('tool_call_fixed', { name: evt.name, v: v }) : t('tool_call', { name: evt.name }));
    } else if (evt.type === 'task_created') {
      var m = addMsg('agent', t('task_queued', { id: evt.task_id }));
      pollTask(evt.task_id, m);
    } else if (evt.type === 'final') {
      addMsg('agent', evt.text);
    } else if (evt.type === 'error') {
      addMsg('err', evt.text);
    }
  }

  function send(text, btn) {
    addMsg('user', text);
    btn.disabled = true;
    fetch('/api/agent/chat', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken() || '' },
      body: JSON.stringify({ message: text })
    }).then(function (resp) {
      if (!resp.ok || !resp.body) { throw new Error('HTTP ' + resp.status); }
      var reader = resp.body.getReader();
      var decoder = new TextDecoder();
      var buffer = '';
      function pump() {
        return reader.read().then(function (chunk) {
          if (chunk.done) { btn.disabled = false; return; }
          // ⚠️ 必须是 chunk.value：chunk 本身是 {done, value} 读取结果对象，
          // 直接喂给 TextDecoder.decode() 会抛
          // "The 'input' argument must be an instance of SharedArrayBuffer,
          //  ArrayBuffer or ArrayBufferView"，整条 SSE 流被 .catch 吞成
          // "请求失败"——浏览器端对话在修复前完全不可用（2026-09-29 修复）。
          buffer += decoder.decode(chunk.value, { stream: true });
          var parts = buffer.split('\n\n');
          buffer = parts.pop();
          parts.forEach(function (block) {
            var line = block.trim();
            if (line.indexOf('data:') !== 0) return;
            var payload = line.slice(5).trim();
            if (payload === '[DONE]') { btn.disabled = false; return; }
            try { handleEvent(JSON.parse(payload)); } catch (e) { /* 忽略坏帧 */ }
          });
          return pump();
        });
      }
      return pump();
    }).catch(function (err) {
      addMsg('err', t('err_request', { msg: err.message }));
      btn.disabled = false;
    });
  }

  /* ============ 语言跟随 ============ */
  var _nodes = null;

  function applyAgentLang() {
    if (!_nodes) return;
    _nodes.fab.title = t('fab');
    _nodes.title.textContent = t('title');
    _nodes.input.placeholder = t('input_ph');
    _nodes.send.textContent = t('send');
  }

  function watchLang() {
    if (typeof MutationObserver !== 'function') return;
    var mo = new MutationObserver(function (records) {
      records.forEach(function (rec) {
        if (rec.attributeName === 'data-lang') applyAgentLang();
      });
    });
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-lang'] });
  }

  /* ============ 初始化 ============ */
  function init() {
    if (document.getElementById('agent-fab')) return;
    var style = document.createElement('style');
    style.textContent = STYLE;
    document.head.appendChild(style);

    var fab = el('button');
    fab.id = 'agent-fab';
    fab.type = 'button';
    fab.textContent = '✦';

    var drawer = el('div');
    drawer.id = 'agent-drawer';
    var head = el('div');
    head.id = 'agent-head';
    var title = el('span');
    head.appendChild(title);
    var close = el('span', null, '—');
    close.style.cursor = 'pointer';
    close.addEventListener('click', function () { drawer.classList.remove('open'); });
    head.appendChild(close);
    var msgs = el('div');
    msgs.id = 'agent-msgs';
    var form = el('div');
    form.id = 'agent-form';
    var input = el('input');
    input.id = 'agent-input';
    var sendBtn = el('button');
    sendBtn.id = 'agent-send';
    sendBtn.type = 'button';
    form.appendChild(input);
    form.appendChild(sendBtn);
    drawer.appendChild(head);
    drawer.appendChild(msgs);
    drawer.appendChild(form);

    _nodes = { fab: fab, title: title, input: input, send: sendBtn };
    applyAgentLang();
    watchLang();

    fab.addEventListener('click', function () { drawer.classList.toggle('open'); });
    sendBtn.addEventListener('click', function () {
      var text = input.value.trim();
      if (!text) return;
      input.value = '';
      send(text, sendBtn);
    });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); sendBtn.click(); }
    });

    document.body.appendChild(fab);
    document.body.appendChild(drawer);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // 测试缝：jsdom 冒烟测试可直接校验归一化逻辑（不影响运行时行为）
  if (typeof window !== 'undefined') {
    window.__agentChatInternals = {
      normalizeTask: normalizeTask,
      normalizeStatus: normalizeStatus,
      outputUrl: outputUrl,
      t: t,
      currentLang: currentLang
    };
  }
})();
