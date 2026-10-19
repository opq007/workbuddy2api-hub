/* 账号区折叠：默认展开、能恢复、能往返，且折叠不挡账号逻辑。
 *
 * 折叠本身很好写坏，坏法都很安静：首屏没存过偏好却收起了；收起后标题和计数
 * 一起被藏掉，用户再也点不回来；`aria-expanded` 和 chevron 指向、正文可见性
 * 三者不同步；账号轮询（15s 的 loadAccounts）或 realm 切换顺手把区域顶开；
 * 又或者偏好走了 localStorage —— 那样换一台浏览器就丢，且违反了 issue 里
 * 「必须存在部署自己的数据目录」的约定。
 *
 * 所以这里既看结构也跑行为：结构上钉住开关是真按钮、标题与计数在可折叠正文
 * 之外、正文容器是 #accountsBody.collapse；行为上把 dashboard 的整段脚本配
 * 一套假 DOM 跑起来，喂不同的 /settings 载荷，断言归一化、往返与「账号逻辑
 * 不碰折叠状态」。
 *
 * Run with Node: node tests/_test_accounts_collapse.js
 */
'use strict';
const assert = require('assert');
const {dashboardHtml, dashboardScript} = require('./_dashboard_source.js');
const dom = require('./_dom_stub.js');

const html = dashboardHtml();
const script = dashboardScript();

/* ---- 1. 结构：真按钮、aria 契约、标题/计数留在正文之外 ---------------- */

const toggleTag = html.match(/<button[^>]*id="accountsToggle"[^>]*>/);
assert.ok(toggleTag, 'dashboard.html 里找不到账号区折叠开关 #accountsToggle');
assert.ok(/type="button"/.test(toggleTag[0]),
  '折叠开关必须是真按钮（type="button"）：键盘可达性靠它，而不是给标题挂 click');
assert.ok(/aria-expanded="true"/.test(toggleTag[0]),
  '首屏（JS 还没跑）必须是展开：aria-expanded="true"');
assert.ok(/aria-controls="accountsBody"/.test(toggleTag[0]),
  'aria-controls 必须指向被折叠的正文 #accountsBody');
assert.ok(/onclick="toggleAccountsSection\(/.test(toggleTag[0]),
  '按钮要接上 toggleAccountsSection');

assert.ok(/<div id="accountsBody" class="collapse">/.test(html),
  '正文容器应该是 #accountsBody.collapse（0fr 收起，没有动画也正确）');
assert.ok(/class="collapse-inner"/.test(html),
  '正文需要一个 collapse-inner 承载 overflow:hidden');

const countAt = html.indexOf('id="acctCount"');
const bodyAt = html.indexOf('id="accountsBody"');
assert.ok(countAt > 0 && bodyAt > 0 && countAt < bodyAt,
  '账号计数必须在可折叠正文之外：收起后标题与计数仍要可见');

/* ---- 2. 行为：把整段 dashboard 脚本配假 DOM 跑起来 -------------------- */

let SETTINGS = {};
const calls = [];

dom.installDom();
global.fetch = (url, options) => {
  calls.push({url: url, body: options && options.body});
  const payload = url === '/settings' ? SETTINGS : {accounts: [], slots: [], results: []};
  return Promise.resolve({
    status: 200, ok: true,
    json: () => Promise.resolve(payload),
    text: () => Promise.resolve(JSON.stringify(payload)),
  });
};

const realLog = console.log;
console.log = () => {};
let api;
try {
  api = new Function(script + `
    return {
      loadSettings: loadSettings,
      toggleAccountsSection: toggleAccountsSection,
      accountsCollapsed: accountsCollapsed,
      loadAccounts: loadAccounts,
      refreshActiveRealm: refreshActiveRealm,
    };`)();
} catch(e) {
  console.log = realLog;
  console.error('脚本求值失败:', e.message);
  process.exit(1);
}

// getElementById 而不是 dom.byId：后者只返回页面自己碰过的元素，而 acctCount
// 是页面上别的代码在写，这里要能把它取出来看。
const element = id => document.getElementById(id);
const expanded = () => element('accountsToggle').getAttribute('aria-expanded');
const collapsedClass = () => element('accountsBody').classList.contains('collapsed');

function check(label, ok, detail) {
  assert.ok(ok, label + (detail === undefined ? '' : '  -> ' + detail));
}

(async () => {
  // 2a. 后端没存过这个字段：展开（今天的既有行为）。
  SETTINGS = {version: 'v1.6.17'};
  await api.loadSettings(true);
  check('缺省应是展开', api.accountsCollapsed() === false, expanded());
  check('缺省时正文不带 collapsed', collapsedClass() === false);
  check('缺省时 aria-expanded=true', expanded() === 'true', expanded());

  // 2b. 存过 true：恢复成收起。
  SETTINGS = {accounts_collapsed: true};
  await api.loadSettings(true);
  check('恢复折叠', api.accountsCollapsed() === true);
  check('恢复折叠时正文带 collapsed', collapsedClass() === true);
  check('恢复折叠时 aria-expanded=false', expanded() === 'false', expanded());

  // 2c. 存过 false / 存坏了：一律展开，且不能被真值字符串骗到。
  for(const bad of [false, 'true', 'false', 1, 0, null, {}, [], 'yes']){
    SETTINGS = {accounts_collapsed: bad};
    await api.loadSettings(true);
    check('损坏值应回落到展开: ' + JSON.stringify(bad),
      api.accountsCollapsed() === false && expanded() === 'true' && !collapsedClass(),
      'aria=' + expanded());
  }

  // 2d. 显式往返：走既有 /settings/save 通道，一个键的 patch。
  SETTINGS = {};
  await api.loadSettings(true);
  calls.length = 0;
  await api.toggleAccountsSection();
  let saves = calls.filter(c => c.url === '/settings/save');
  check('折叠要 POST /settings/save', saves.length === 1, JSON.stringify(calls));
  assert.deepStrictEqual(JSON.parse(saves[0].body), {accounts_collapsed: true},
    '保存的载荷必须只有这一个键');
  check('折叠后正文带 collapsed', collapsedClass() === true);
  check('折叠后 aria-expanded=false', expanded() === 'false', expanded());

  await api.toggleAccountsSection();
  saves = calls.filter(c => c.url === '/settings/save');
  assert.deepStrictEqual(JSON.parse(saves[saves.length - 1].body), {accounts_collapsed: false},
    '展开要把 false 存回去');
  check('展开后正文不带 collapsed', collapsedClass() === false);
  check('展开后 aria-expanded=true', expanded() === 'true', expanded());

  // 2e. 收起之后，标题按钮与计数都还在（折叠只改正文容器）。
  element('acctCount').textContent = '(5 个账号)';
  SETTINGS = {accounts_collapsed: true};
  await api.loadSettings(true);
  check('收起后计数文本未被清空', element('acctCount').textContent === '(5 个账号)',
    element('acctCount').textContent);
  check('收起后标题按钮仍在文档里', element('accountsToggle').isConnected === true);

  // 2f. 账号刷新与 realm 切换不得把区域顶开，也不得改 aria。
  await api.loadAccounts();
  check('账号轮询（loadAccounts）后仍是收起', collapsedClass() === true && expanded() === 'false',
    'aria=' + expanded());
  await api.refreshActiveRealm();
  check('realm 切换后仍是收起', collapsedClass() === true && expanded() === 'false',
    'aria=' + expanded());
  element('acctCount').textContent = '(9 个账号)';   // 计数变化
  check('计数变化后仍是收起', collapsedClass() === true && expanded() === 'false');

  // 2g. 折叠状态只有两个写入口：恢复（loadSettings）与显式切换。账号渲染、
  //     realm 切换、轮询里一个都没有——上面 2f 的行为断言是它的行为侧证据。
  const callSites = script.split('applyAccountsCollapsed(').length - 1;
  check('applyAccountsCollapsed 只应有两个调用点（定义体 + 两处调用共 3 次出现）',
    callSites === 3, '出现 ' + callSites + ' 次');

  // 偏好必须留在部署自己的数据目录里：折叠块里不许出现浏览器存储。注释先剥掉，
  // 否则「不用 localStorage」这句话本身就会误报。
  const start = script.indexOf('账号区折叠开始');
  const end = script.indexOf('账号区折叠结束');
  check('折叠块必须能被测试定位', start > 0 && end > start);
  const blockCode = script.slice(start, end)
    .replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '');
  check('折叠块不得使用 localStorage / sessionStorage',
    !/localStorage|sessionStorage/.test(blockCode));
  check('折叠块必须把偏好发给服务端（/settings/save）',
    blockCode.indexOf("'/settings/save'") >= 0);

  console.log = realLog;
  console.log('账号区折叠断言通过（结构 7 项 + 行为 20 项）');
})().catch(e => {
  console.log = realLog;
  console.error(e && e.stack || e);
  process.exit(1);
});
