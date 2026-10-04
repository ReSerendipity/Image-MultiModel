// tests/frontend/xss_regression.js — M-06 前端 XSS 修复回归测试（纯 Node，无 jsdom 依赖）
//
// 验证三处动态 HTML 注入（app.js 的 renderBFileList / renderStatEngines /
// renderBatchQueue）已用 escHtml() 转义，且 escHtml 本身能正确转义
// & < > " ' 五个危险字符（防 <img onerror> / 属性截断 等 XSS）。
//
// 运行：node tests/frontend/xss_regression.js   （断言失败 exit 1）

const fs = require('fs');
const path = require('path');

const APP_JS = path.join(__dirname, '..', '..', 'app', 'integrated_app', 'static', 'js', 'app.js');
const src = fs.readFileSync(APP_JS, 'utf-8');

let pass = 0, fail = 0;
function ok(cond, msg) {
  if (cond) { pass++; console.log('  ok  - ' + msg); }
  else { fail++; console.log('  FAIL- ' + msg); }
}

/* ── 1. 提取并验证 escHtml 行为（eval 真实源码，非复制）────────────── */
const escLine = src.split('\n').find((l) => l.trim().startsWith('function escHtml('));
ok(!!escLine, 'escHtml 函数存在于 app.js');
if (escLine) {
  // 仅 eval 这一行（自包含，无 DOM 依赖）
  // eslint-disable-next-line no-eval
  (0, eval)(escLine);
  const payload = '<img src=x onerror="alert(1)"> \' " &';
  const out = escHtml(payload);
  ok(!out.includes('<') && !out.includes('>'), 'escHtml 转义 < 与 >（阻断标签注入）');
  ok(out.includes('&lt;') && out.includes('&gt;'), 'escHtml 输出 &lt; &gt; 实体');
  ok(out.includes('&quot;') && out.includes('&#39;'), 'escHtml 转义 " 与 \'（阻断属性截断）');
  ok(out.includes('&amp;'), 'escHtml 转义 &');
  ok(escHtml(null) === '' && escHtml(undefined) === '' && escHtml(42) === '42', 'escHtml 处理 null/undefined/数字');
}

/* ── 2. 三处注入点均已使用 escHtml ──────────────────────────────── */
// M-06 (1) renderBFileList：文件名（用户上传文件名，攻击面）
ok(
  /f\.name\.replace\(\/</.test(src) === false,
  'renderBFileList 不再用脆弱的 replace(/</g)（已改用 escHtml）'
);
ok(/escHtml\(f\.name\)/.test(src), 'renderBFileList 用 escHtml(f.name) 转义文件名');

// M-06 (2) renderStatEngines：引擎 display_name / state（来自服务端配置）
ok(/escHtml\(e\.display_name\)/.test(src), 'renderStatEngines 用 escHtml(e.display_name) 转义');
ok(/escHtml\(st\)/.test(src), 'renderStatEngines 用 escHtml(st) 转义引擎状态');

// M-06 (3) renderBatchQueue：服务端返回的 r.detail（错误回显）
// 2026-10-04：兜底文案已 i18n 化（tr('batch_not_found')），转义属性不变，断言同步更新
ok(/escHtml\(r\.detail\|\|tr\('batch_not_found'\)\)/.test(src), 'renderBatchQueue 用 escHtml(r.detail) 转义错误回显');

console.log('\nXSS REGRESSION RESULT: pass=' + pass + ' fail=' + fail);
process.exit(fail ? 1 : 0);
