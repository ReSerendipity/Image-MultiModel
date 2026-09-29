/*
 * chat.js — Agent 对话浮动面板(最小闭环前端半边)
 *
 * 依赖契约:
 * - POST /api/agent/chat(SSE 流;CSRF Double-Submit:X-CSRF-Token 头)
 * - GET  /api/tasks/{task_id}(轮询任务状态;Task.result → /api/outputs/<path> 图片)
 * - GET  /api/agent/health(LLM 离线提示)
 * 事件:tool_call / task_created / tool_result / final / error / [DONE]
 * 说明:P0 骨架中文文案硬编码,i18n 五语言接入留后续批次(评估报告任务 5)。
 */
(function () {
  'use strict';

  var _csrfToken = null;
  function csrfToken() {
    if (_csrfToken) return _csrfToken;
    try {
      var r = new XMLHttpRequest();
      r.open('GET', '/api/health', false); // 同步取 token(与 app.js 的懒获取策略一致)
      r.send(null);
      var t = r.getResponseHeader('X-CSRF-Token');
      if (t) _csrfToken = t;
    } catch (e) { /* 离线时后续 POST 会得到 403,面板提示 */ }
    return _csrfToken;
  }

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

  function pollTask(taskId, target) {
    var tries = 0;
    var timer = setInterval(function () {
      tries += 1;
      if (tries > 150) { clearInterval(timer); addMsg('err', '任务轮询超时: ' + taskId); return; }
      fetch('/api/tasks/' + encodeURIComponent(taskId), { credentials: 'same-origin' })
        .then(function (r) { return r.json(); })
        .then(function (task) {
          if (task.status === 'COMPLETED') {
            clearInterval(timer);
            addMsg('sys', '任务完成(' + taskId + ')');
            (task.result || []).slice(0, 4).forEach(function (p) {
              var path = String(p).replace(/\\/g, '/');
              var idx = path.indexOf('outputs/');
              if (idx >= 0) path = path.slice(idx + 8);
              var img = document.createElement('img');
              img.src = '/api/outputs/' + path;
              img.alt = '生成结果';
              target.appendChild(img);
            });
          } else if (task.status === 'FAILED') {
            clearInterval(timer);
            addMsg('err', '任务失败(' + taskId + '): ' + (task.error || '未知原因'));
          } else if (task.status === 'CANCELLED') {
            clearInterval(timer);
            addMsg('sys', '任务已取消(' + taskId + ')');
          }
        })
        .catch(function () { /* 下一轮重试 */ });
    }, 2000);
  }

  function handleEvent(evt) {
    if (evt.type === 'tool_call') {
      addMsg('sys', '调用 ' + evt.name + (evt.violations && evt.violations.length ? '(参数已自动修正: ' + evt.violations.join('; ') + ')' : ''));
    } else if (evt.type === 'task_created') {
      var m = addMsg('agent', '任务已排队:' + evt.task_id);
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
          buffer += decoder.decode(chunk, { stream: true });
          var parts = buffer.split('\n\n');
          buffer = parts.pop();
          parts.forEach(function (block) {
            var line = block.trim();
            if (!line.startsWith('data:')) return;
            var payload = line.slice(5).trim();
            if (payload === '[DONE]') { btn.disabled = false; return; }
            try { handleEvent(JSON.parse(payload)); } catch (e) { /* 忽略坏帧 */ }
          });
          return pump();
        });
      }
      return pump();
    }).catch(function (err) {
      addMsg('err', '请求失败:' + err.message + '(请确认服务与 LLM 大脑在线)');
      btn.disabled = false;
    });
  }

  function init() {
    if (document.getElementById('agent-fab')) return;
    var style = document.createElement('style');
    style.textContent = STYLE;
    document.head.appendChild(style);

    var fab = el('button');
    fab.id = 'agent-fab';
    fab.type = 'button';
    fab.title = 'AI 对话生图';
    fab.textContent = '✦';

    var drawer = el('div');
    drawer.id = 'agent-drawer';
    var head = el('div');
    head.id = 'agent-head';
    head.appendChild(el('span', null, 'AI 对话生图'));
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
    input.placeholder = '描述你想生成的图片…';
    var sendBtn = el('button');
    sendBtn.id = 'agent-send';
    sendBtn.type = 'button';
    sendBtn.textContent = '发送';
    form.appendChild(input);
    form.appendChild(sendBtn);
    drawer.appendChild(head);
    drawer.appendChild(msgs);
    drawer.appendChild(form);

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
})();
