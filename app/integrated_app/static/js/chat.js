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
      mode_label: '模式',
      mode_auto: '全自动',
      mode_confirm: '执行前确认',
      mode_manual: '纯手动辅助',
      proposal_title: '待确认参数',
      p_prompt: '正向提示词',
      p_negative: '负向提示词',
      p_width: '宽',
      p_height: '高',
      p_steps: '步数',
      p_cfg: 'CFG',
      p_seed: '种子',
      p_batch: '张数',
      btn_execute: '执行',
      btn_reject: '取消',
      btn_workbench: '带去工作台',
      proposal_executed: '已按确认参数入队：{id}',
      proposal_rejected: '已取消该参数卡片',
      proposal_manual_note: '纯手动辅助模式：不会代为生成，请到工作台执行。',
      proposal_error: '参数卡片操作失败：{msg}',
      wb_filled: '参数已回填工作台，可直接生成或继续调整。',
      model_loading: '模型加载中… {pct}%',
      model_loading_no_pct: '模型加载中…（首次生成需数十秒，请稍候）',
      model_ready: '模型已就绪',
      model_failed: '模型加载失败，请查看服务端日志。',
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
      mode_label: '模式',
      mode_auto: '全自動',
      mode_confirm: '執行前確認',
      mode_manual: '純手動輔助',
      proposal_title: '待確認參數',
      p_prompt: '正向提示詞',
      p_negative: '負向提示詞',
      p_width: '寬',
      p_height: '高',
      p_steps: '步數',
      p_cfg: 'CFG',
      p_seed: '種子',
      p_batch: '張數',
      btn_execute: '執行',
      btn_reject: '取消',
      btn_workbench: '帶去工作台',
      proposal_executed: '已依確認參數排隊：{id}',
      proposal_rejected: '已取消該參數卡片',
      proposal_manual_note: '純手動輔助模式：不會代為生成，請至工作台執行。',
      proposal_error: '參數卡片操作失敗：{msg}',
      wb_filled: '參數已回填工作台，可直接生成或繼續調整。',
      model_loading: '模型載入中… {pct}%',
      model_loading_no_pct: '模型載入中…（首次生成需數十秒，請稍候）',
      model_ready: '模型已就緒',
      model_failed: '模型載入失敗，請查看服務端日誌。',
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
      mode_label: 'Mode',
      mode_auto: 'Auto',
      mode_confirm: 'Confirm first',
      mode_manual: 'Manual assist',
      proposal_title: 'Parameters to confirm',
      p_prompt: 'Positive prompt',
      p_negative: 'Negative prompt',
      p_width: 'Width',
      p_height: 'Height',
      p_steps: 'Steps',
      p_cfg: 'CFG',
      p_seed: 'Seed',
      p_batch: 'Batch',
      btn_execute: 'Run',
      btn_reject: 'Cancel',
      btn_workbench: 'Send to workbench',
      proposal_executed: 'Queued with confirmed parameters: {id}',
      proposal_rejected: 'Parameter card dismissed',
      proposal_manual_note: 'Manual assist mode: nothing is generated for you — run it in the workbench.',
      proposal_error: 'Parameter card action failed: {msg}',
      wb_filled: 'Parameters filled into the workbench — generate or keep tuning.',
      model_loading: 'Loading model… {pct}%',
      model_loading_no_pct: 'Loading model… (first run can take tens of seconds)',
      model_ready: 'Model ready',
      model_failed: 'Model failed to load — check the server logs.',
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
      mode_label: 'モード',
      mode_auto: '全自動',
      mode_confirm: '実行前に確認',
      mode_manual: '手動アシスト',
      proposal_title: '確認するパラメータ',
      p_prompt: 'ポジティブプロンプト',
      p_negative: 'ネガティブプロンプト',
      p_width: '幅',
      p_height: '高さ',
      p_steps: 'ステップ',
      p_cfg: 'CFG',
      p_seed: 'シード',
      p_batch: '枚数',
      btn_execute: '実行',
      btn_reject: 'キャンセル',
      btn_workbench: 'ワークベンチへ',
      proposal_executed: '確認したパラメータでキューに追加: {id}',
      proposal_rejected: 'パラメータカードを破棄しました',
      proposal_manual_note: '手動アシストモード: 代行生成は行いません。ワークベンチで実行してください。',
      proposal_error: 'パラメータカードの操作に失敗: {msg}',
      wb_filled: 'パラメータをワークベンチに反映しました。生成するか、そのまま調整できます。',
      model_loading: 'モデル読み込み中… {pct}%',
      model_loading_no_pct: 'モデル読み込み中…（初回は数十秒かかります）',
      model_ready: 'モデル準備完了',
      model_failed: 'モデルの読み込みに失敗しました。サーバーログを確認してください。',
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
      mode_label: '모드',
      mode_auto: '완전 자동',
      mode_confirm: '실행 전 확인',
      mode_manual: '수동 보조',
      proposal_title: '확인할 매개변수',
      p_prompt: '긍정 프롬프트',
      p_negative: '부정 프롬프트',
      p_width: '너비',
      p_height: '높이',
      p_steps: '스텝',
      p_cfg: 'CFG',
      p_seed: '시드',
      p_batch: '장수',
      btn_execute: '실행',
      btn_reject: '취소',
      btn_workbench: '작업대로 보내기',
      proposal_executed: '확인한 매개변수로 대기열에 추가: {id}',
      proposal_rejected: '매개변수 카드를 취소했습니다',
      proposal_manual_note: '수동 보조 모드: 대신 생성하지 않습니다. 작업대에서 실행하세요.',
      proposal_error: '매개변수 카드 처리 실패: {msg}',
      wb_filled: '매개변수를 작업대에 채웠습니다. 바로 생성하거나 계속 조정하세요.',
      model_loading: '모델 로딩 중… {pct}%',
      model_loading_no_pct: '모델 로딩 중… (첫 실행은 수십 초 걸립니다)',
      model_ready: '모델 준비 완료',
      model_failed: '모델 로딩 실패 — 서버 로그를 확인하세요.',
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
    '#agent-fab{position:fixed;right:22px;bottom:86px;z-index:9990;width:52px;height:52px;',
    'border-radius:50%;border:none;background:var(--seed-primary,#e8822a);color:#fff;font-size:22px;cursor:pointer;',
    'box-shadow:0 4px 14px rgba(0,0,0,.18);transition:transform .15s ease}',
    '#agent-fab:hover{transform:scale(1.06)}',
    '#agent-drawer{position:fixed;right:22px;bottom:150px;z-index:9991;width:380px;max-height:70vh;',
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
    '.agent-msg.streaming::after{content:"▍";opacity:.55;animation:agent-blink 1s steps(2,start) infinite}',
    '@keyframes agent-blink{to{visibility:hidden}}',
    '#agent-form{display:flex;border-top:1px solid rgba(0,0,0,.12)}',
    '#agent-input{flex:1;border:none;padding:10px 12px;font-size:13px;outline:none}',
    '#agent-send{border:none;background:var(--seed-primary,#e8822a);color:#fff;padding:0 16px;cursor:pointer}',
    '#agent-mode{border:1px solid rgba(0,0,0,.15);border-radius:6px;font-size:12px;padding:2px 4px;background:#fff}',
    '.agent-card{border:1px solid #c9d6c6;background:#f7faf6;border-radius:8px;padding:8px 10px;margin:8px 0}',
    '.agent-card .ac-title{font-size:12px;font-weight:600;color:#3f5a3c;margin-bottom:6px}',
    '.agent-card .ac-note{font-size:11px;color:#8a6d3b;margin-bottom:6px}',
    '.agent-card label{display:block;font-size:11px;color:#666;margin:6px 0 2px}',
    '.agent-card input,.agent-card textarea{width:100%;box-sizing:border-box;font-size:12px;padding:4px 6px;',
    'border:1px solid rgba(0,0,0,.15);border-radius:5px;font-family:inherit}',
    '.agent-card .ac-grid{display:grid;grid-template-columns:1fr 1fr;gap:0 8px}',
    '.agent-card .ac-full{grid-column:1 / -1}',
    '.agent-card .ac-btns{display:flex;gap:8px;margin-top:9px}',
    '.agent-card .ac-btns button{flex:1;font-size:12px;padding:5px 0;border-radius:6px;cursor:pointer;border:1px solid rgba(0,0,0,.15)}',
    '.agent-card .ac-primary{background:#5e7d5a;color:#fff;border-color:#5e7d5a}',
    '.agent-card.done{opacity:.6}'
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
      if (tries > 150) {
        clearInterval(timer);
        taskFinished();
        statusLine.textContent = t('task_timeout', { id: taskId });
        return;
      }
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
            taskFinished();
            statusLine.textContent = t('task_done', { id: taskId });
            renderOutputs(info.paths, target);
          } else if (info.status === 'failed' || info.status === 'interrupted') {
            clearInterval(timer);
            taskFinished();
            statusLine.className = 'agent-msg err';
            statusLine.textContent = t('task_failed', { id: taskId, err: info.error || t('task_unknown') });
          } else if (info.status === 'cancelled') {
            clearInterval(timer);
            taskFinished();
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

  /* ============ 会话 / 模式（双模式 5b） ============ */
  var MODES = ['AUTO', 'CONFIRM', 'MANUAL_ASSIST'];
  var MODE_LABEL_KEY = { AUTO: 'mode_auto', CONFIRM: 'mode_confirm', MANUAL_ASSIST: 'mode_manual' };
  var _sessionId = null;
  var _mode = 'AUTO';

  function sessionId() {
    if (_sessionId) return _sessionId;
    // 会话 id 存 sessionStorage：**每标签页独立**（多标签页 = 多个会话，互不串台），
    // 但刷新页面仍能续上同一会话。localStorage 会让所有标签页共用同一会话（串台），
    // 内存变量又扛不住刷新 —— sessionStorage 恰好是这两者的正确中间态。
    var sid = null;
    try {
      sid = window.sessionStorage.getItem('imm_agent_session');
    } catch (e) { /* 隐私模式下可能抛错 */ }
    if (!sid) {
      sid = 'web-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10);
      try {
        window.sessionStorage.setItem('imm_agent_session', sid);
      } catch (e) { /* 忽略 */ }
    }
    _sessionId = sid;
    return _sessionId;
  }

  function currentMode() {
    return MODES.indexOf(_mode) >= 0 ? _mode : 'AUTO';
  }

  /* ============ 参数卡片 ============ */
  var PROPOSAL_FIELDS = [
    { key: 'positive_prompt', label: 'p_prompt', type: 'textarea' },
    { key: 'negative_prompt', label: 'p_negative', type: 'text' },
    { key: 'width', label: 'p_width', type: 'number', min: 256, max: 2048, step: 8 },
    { key: 'height', label: 'p_height', type: 'number', min: 256, max: 2048, step: 8 },
    { key: 'steps', label: 'p_steps', type: 'number', min: 1, max: 50, step: 1 },
    { key: 'cfg', label: 'p_cfg', type: 'number', min: 1, max: 10, step: 0.1 },
    { key: 'seed', label: 'p_seed', type: 'number', min: -1, step: 1 },
    { key: 'batch_size', label: 'p_batch', type: 'number', min: 1, max: 4, step: 1 }
  ];
  // 工作台表单元素 id（templates/index.html）：带去工作台时回填
  var WB_TARGETS = {
    positive_prompt: 'posPrompt',
    negative_prompt: 'negPrompt',
    width: 'width',
    height: 'height',
    steps: 'steps',
    cfg: 'cfg',
    seed: 'seed',
    batch_size: 'batchSize'
  };

  function renderProposal(evt) {
    var box = document.getElementById('agent-msgs');
    var card = el('div', 'agent-card');
    card.appendChild(el('div', 'ac-title', t('proposal_title')));
    if (evt.manual) card.appendChild(el('div', 'ac-note', t('proposal_manual_note')));

    var inputs = {};
    var grid = el('div', 'ac-grid');
    PROPOSAL_FIELDS.forEach(function (f) {
      var wrap = el('div');
      if (f.type === 'textarea') wrap.className = 'ac-full';
      wrap.appendChild(el('label', null, t(f.label)));
      var input = document.createElement(f.type === 'textarea' ? 'textarea' : 'input');
      if (f.type === 'textarea') {
        input.rows = 3;
      } else {
        input.type = f.type; // ⚠️ 必须显式设置：否则 number 字段退化成 text，collect() 会把它当字符串上行
      }
      if (f.type === 'number') {
        if (f.min !== undefined) input.min = f.min;
        if (f.max !== undefined) input.max = f.max;
        if (f.step !== undefined) input.step = f.step;
      }
      var v = (evt.args || {})[f.key];
      input.value = v === undefined || v === null ? '' : v;
      input.dataset.field = f.key;
      wrap.appendChild(input);
      inputs[f.key] = input;
      grid.appendChild(wrap);
    });
    card.appendChild(grid);

    var btns = el('div', 'ac-btns');
    var primary = el('button', 'ac-primary', evt.manual ? t('btn_workbench') : t('btn_execute'));
    primary.type = 'button';
    var secondary = el('button', null, t('btn_reject'));
    secondary.type = 'button';
    btns.appendChild(primary);
    btns.appendChild(secondary);
    card.appendChild(btns);
    box.appendChild(card);
    box.scrollTop = box.scrollHeight;

    function collect() {
      var params = {};
      Object.keys(inputs).forEach(function (k) {
        var raw = inputs[k].value;
        if (raw === '') return;
        params[k] = inputs[k].type === 'number' ? Number(raw) : raw;
      });
      return params;
    }

    function lock() {
      card.classList.add('done');
      primary.disabled = true;
      secondary.disabled = true;
    }

    primary.addEventListener('click', function () {
      if (evt.manual) {
        fillWorkbench(collect());
        addMsg('sys', t('wb_filled'));
        lock();
        return;
      }
      primary.disabled = true;
      postConfirm({
        session_id: sessionId(),
        proposal_id: evt.proposal_id,
        action: 'approve',
        params: collect()
      }).then(function (res) {
        lock();
        if (res && res.task_id) {
          taskStarted();
          var m = addMsg('agent', t('proposal_executed', { id: res.task_id }));
          pollTask(res.task_id, m);
        } else {
          addMsg('sys', t('proposal_rejected'));
        }
      }).catch(function (err) {
        primary.disabled = false;
        addMsg('err', t('proposal_error', { msg: err.message }));
      });
    });

    secondary.addEventListener('click', function () {
      secondary.disabled = true;
      postConfirm({
        session_id: sessionId(),
        proposal_id: evt.proposal_id,
        action: 'reject'
      }).then(function () {
        lock();
        addMsg('sys', t('proposal_rejected'));
      }).catch(function (err) {
        secondary.disabled = false;
        addMsg('err', t('proposal_error', { msg: err.message }));
      });
    });
  }

  function postConfirm(payload) {
    return fetch('/api/agent/confirm', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken() || '' },
      body: JSON.stringify(payload)
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (body) {
        if (r.ok) return body;
        // ⚠️ 本项目错误响应是统一封装 {success:false, error:{code,message,detail}}
        // （middleware/error_handler.py::_build_error_response），不是 FastAPI 默认的 {detail}。
        var msg = (body && body.detail) ||
          (body && body.error && (body.error.message || body.error.detail)) ||
          ('HTTP ' + r.status);
        throw new Error(msg);
      });
    });
  }

  /** 把参数卡片的值回填到主工作台表单（手动/自动双模式并存的「带参数跳工作台」）。 */
  function fillWorkbench(params) {
    Object.keys(WB_TARGETS).forEach(function (k) {
      if (params[k] === undefined) return;
      var node = document.getElementById(WB_TARGETS[k]);
      if (!node) return;
      node.value = params[k];
      // 触发 input/change，让 app.js 的 stepper 与参数快照同步
      node.dispatchEvent(new Event('input', { bubbles: true }));
      node.dispatchEvent(new Event('change', { bubbles: true }));
    });
    var drawer = document.getElementById('agent-drawer');
    if (drawer) drawer.classList.remove('open');
  }

  /* ============ 引擎冷启动提示（model_status SSE） ============ */
  // 引擎默认不预加载：首个生成请求会触发数十秒的加载。这里消费 model_status，
  // 在"有在飞任务"期间显示加载进度，否则用户会以为卡死。
  var _activeTasks = 0;
  var _modelLine = null;

  function taskStarted() {
    _activeTasks += 1;
  }

  function taskFinished() {
    _activeTasks = Math.max(0, _activeTasks - 1);
    if (_activeTasks === 0) _modelLine = null;
  }

  function updateModelStatus(d) {
    if (_activeTasks <= 0) return; // 没有在飞任务时不打扰用户
    var state = String((d && d.state) || '').toLowerCase();
    if (state === 'loading') {
      if (!_modelLine) _modelLine = addMsg('sys', '');
      var pct = typeof d.progress === 'number' ? d.progress : null;
      _modelLine.textContent = pct === null ? t('model_loading_no_pct') : t('model_loading', { pct: pct });
      var box = document.getElementById('agent-msgs');
      if (box) box.scrollTop = box.scrollHeight;
    } else if (state === 'loaded') {
      if (_modelLine) {
        _modelLine.textContent = t('model_ready');
        _modelLine = null;
      }
    } else if (state === 'error') {
      if (!_modelLine) _modelLine = addMsg('err', '');
      _modelLine.textContent = t('model_failed');
      _modelLine = null;
    }
  }

  function watchModelStatus() {
    // 复用 app.js 的全局唯一 SSE 连接（base.html 里 app.js 先于 chat.js 执行，
    // 其顶层 `var evt` 即 window.evt）；拿不到时自建一条。
    var src = null;
    try {
      src = window.evt;
    } catch (e) { /* 忽略 */ }
    if (!src || typeof src.addEventListener !== 'function') {
      if (typeof EventSource !== 'function') return; // 环境不支持（如 jsdom）
      try {
        src = new EventSource('/api/events');
      } catch (e) {
        return;
      }
    }
    src.addEventListener('model_status', function (e) {
      try {
        updateModelStatus(JSON.parse(e.data));
      } catch (err) { /* 忽略坏帧 */ }
    });
  }

  /* ============ SSE 事件 ============ */
  // 流式正文气泡：delta 逐字追加到同一个气泡；final 收尾（可能整体替换）
  var _streamBubble = null;

  function streamBubble() {
    if (_streamBubble && _streamBubble.isConnected) return _streamBubble;
    _streamBubble = addMsg('agent', '');
    _streamBubble.classList.add('streaming');
    return _streamBubble;
  }

  function endStream(text, replace) {
    if (replace) {
      // 流式期间已渲染的内容作废（如泄露拦截）：整体覆盖
      var bubble = streamBubble();
      bubble.textContent = text || '';
      bubble.classList.remove('streaming');
    } else if (_streamBubble) {
      if (text) _streamBubble.textContent = text; // 以服务端最终文本为准（防分片丢字）
      _streamBubble.classList.remove('streaming');
    } else {
      addMsg('agent', text);
    }
    _streamBubble = null;
  }

  function handleEvent(evt) {
    if (!evt || !evt.type) return;
    if (evt.type === 'delta') {
      var bubble = streamBubble();
      bubble.textContent += evt.text || '';
      var box = document.getElementById('agent-msgs');
      if (box) box.scrollTop = box.scrollHeight;
    } else if (evt.type === 'tool_call') {
      // 工具调用意味着本轮还有后续动作，先把流式气泡收尾，避免与后续文本粘连
      if (_streamBubble) { _streamBubble.classList.remove('streaming'); _streamBubble = null; }
      var v = evt.violations && evt.violations.length ? evt.violations.join('; ') : '';
      addMsg('sys', v ? t('tool_call_fixed', { name: evt.name, v: v }) : t('tool_call', { name: evt.name }));
    } else if (evt.type === 'task_created') {
      taskStarted();
      var m = addMsg('agent', t('task_queued', { id: evt.task_id }));
      pollTask(evt.task_id, m);
    } else if (evt.type === 'proposal') {
      renderProposal(evt);
    } else if (evt.type === 'final') {
      endStream(evt.text, !!evt.replace);
    } else if (evt.type === 'error') {
      if (_streamBubble) { _streamBubble.classList.remove('streaming'); _streamBubble = null; }
      addMsg('err', evt.text);
    }
  }

  function send(text, btn) {
    addMsg('user', text);
    btn.disabled = true;
    _streamBubble = null; // 新一轮重置流式气泡
    fetch('/api/agent/chat', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken() || '' },
      // session_id 必须稳定复用，否则每轮都是新会话、多轮上下文（「再来一张」）失效
      body: JSON.stringify({ message: text, session_id: sessionId(), mode: currentMode() })
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
    if (_nodes.modeLabel) _nodes.modeLabel.textContent = t('mode_label');
    var opts = _nodes.mode && _nodes.mode.options;
    if (opts) {
      for (var i = 0; i < opts.length; i++) {
        var key = MODE_LABEL_KEY[opts[i].value];
        if (key) opts[i].textContent = t(key);
      }
    }
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
    fab.setAttribute('aria-label', 'AI 对话生图');
    fab.textContent = '✦';

    var drawer = el('div');
    drawer.id = 'agent-drawer';
    var head = el('div');
    head.id = 'agent-head';
    var titleWrap = el('span');
    titleWrap.style.display = 'flex';
    titleWrap.style.alignItems = 'center';
    titleWrap.style.gap = '8px';
    var title = el('span');
    var modeLabel = el('span');
    modeLabel.style.fontSize = '11px';
    modeLabel.style.color = '#777';
    var modeSel = document.createElement('select');
    modeSel.id = 'agent-mode';
    MODES.forEach(function (mv) {
      var o = document.createElement('option');
      o.value = mv;
      o.textContent = mv;
      modeSel.appendChild(o);
    });
    // 模式持久化（与 app.js 的 imm_theme / imm_lang 同一 localStorage 约定）
    try {
      var saved = window.localStorage.getItem('imm_agent_mode');
      if (MODES.indexOf(saved) >= 0) _mode = saved;
    } catch (e) { /* 隐私模式下 localStorage 可能抛错 */ }
    modeSel.value = currentMode();
    modeSel.addEventListener('change', function () {
      _mode = MODES.indexOf(modeSel.value) >= 0 ? modeSel.value : 'AUTO';
      try { window.localStorage.setItem('imm_agent_mode', _mode); } catch (e) { /* 忽略 */ }
    });
    titleWrap.appendChild(title);
    titleWrap.appendChild(modeLabel);
    titleWrap.appendChild(modeSel);
    head.appendChild(titleWrap);
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

    _nodes = { fab: fab, title: title, input: input, send: sendBtn, mode: modeSel, modeLabel: modeLabel };
    applyAgentLang();
    watchLang();
    watchModelStatus();

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
      currentLang: currentLang,
      currentMode: currentMode,
      renderProposal: renderProposal,
      fillWorkbench: fillWorkbench,
      sessionId: sessionId,
      updateModelStatus: updateModelStatus,
      taskStarted: taskStarted,
      taskFinished: taskFinished
    };
  }
})();
