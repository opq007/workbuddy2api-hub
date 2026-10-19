/* 面板轮询与重渲染的健康契约：请求单飞、无变化跳过重写、登录轮询定时器清理。
 *
 * 这四条都是"浏览器里才看得见、代码上看不出来"的问题，实测数据在 PR 里：
 *
 *  1. getJSON 没有请求单飞：冷窗口下同一个 /usage 会同时飞好几份完全相同的
 *     请求，各自在服务端重跑聚合，还把后面的 /accounts、/scheduler 堵在连接
 *     池里。这里钉住：同一 URL 并发只发一份、结果共享、落定后恢复常态、
 *     超过 60 秒的挂死登记项会被换掉且旧请求落定不误删新登记项。
 *  2. #recent 每 5 秒全量重写，数据没变也重写（100 行时一次 50~65ms 的强制
 *     布局）。这里钉住：内容指纹不变就不写 DOM，行数据或账号昵称一变立刻写。
 *  3. 日志终端每 2 秒全量重写（2000 行时约 700KB/次、layout 250~320ms）。
 *     这里钉住：没有新行一个字节都不动、有新行只 append、过滤变化才整表重画、
 *     超上限只从头部删"被挤出且当前过滤下画过"的条数。
 *  4. panelSessionLost() 不清 loginTimer：弹窗开着时会话失效，这个标签页每
 *     2.5 秒打一次 401 永不停止。这里钉住：会话失效后登录轮询定时器必须被清掉，
 *     且之后不再发出任何轮询请求。
 *
 * 另外把 i18n 观察者路径也过一遍：EN 下翻译结果、data-no-i18n 子树、日志终端
 * 跳过这些行为不受 allowed() 缓存与 doAttrs() 短路影响，且缓存确实在生效。
 *
 * Run with Node: node tests/_test_panel_poll_health.js
 */
'use strict';
const assert = require('assert');
const {dashboardHtml, dashboardScript} = require('./_dashboard_source.js');
const dom = require('./_dom_stub.js');

const html = dashboardHtml();
const script = dashboardScript();

function okJson(payload, status){
  const code = status || 200;
  return {status: code, ok: code < 400,
          json: () => Promise.resolve(payload),
          text: () => Promise.resolve(JSON.stringify(payload))};
}
function errRes(status){
  return {status: status, ok: false,
          json: () => Promise.resolve({}), text: () => Promise.resolve('')};
}

// 面板脚本作用域里的函数与状态（let 声明在 new Function 体内，只能由返回的
// 闭包读写）。
const EXPORTS = [
  'getJSON', 'POLL_READ', 'panelSessionLost', 'pollLogin', 'fetchNewLogs',
  'setLogFilterLevel', 'refresh', 'setCostCurrency', 'logMatchesFilter', 'logFilterKey',
  'WB_I18N: window.WB_I18N',
  'getLoginTimer: () => loginTimer', 'setLoginTimer: (t) => { loginTimer = t; }',
  'getLoginState: () => loginState', 'setLoginState: (s) => { loginState = s; }',
  'getPanelReady: () => PANEL_READY',
  'getLastRecentFp: () => lastRecentFp',
  'getLogEntries: () => logEntries', 'setLogEntries: (e) => { logEntries = e; }',
  'getLastLogId: () => lastLogId', 'setLastLogId: (v) => { lastLogId = v; }',
  'getLogDomCount: () => logDomCount',
].join(',');

// 每个用例一份新的全局环境：按 URL 前缀路由 fetch（长前缀优先），没命中的一律
// 答 {authenticated:false} —— 启动时的 /panel/status 就落在这里，面板停在门控
// 页，自己不起任何定时器，测试环境保持干净。
function boot(routes, options){
  const opts = options || {};
  const calls = [];
  const table = Object.keys(routes || {}).sort((a, b) => b.length - a.length);
  const fetchImpl = (url, init) => {
    const u = String(url);
    const rec = {url: u, init: init || {}};
    calls.push(rec);
    for (const prefix of table){
      if (u.startsWith(prefix)) return routes[prefix](u, rec.init, rec);
    }
    return Promise.resolve(okJson({authenticated: false}));
  };
  const installed = dom.installDom(Object.assign({}, opts, {fetch: fetchImpl}));
  if (opts.beforeEval) opts.beforeEval(installed);
  const api = new Function(script + '\nreturn {' + EXPORTS + '};')();
  return {api, calls, dom: installed,
          callsTo: (prefix) => calls.filter(c => c.url.startsWith(prefix)).length};
}

let checks = 0;
function check(ok, msg){
  assert.ok(ok, msg);
  checks += 1;
}

(async () => {
  /* 1) 单飞：同一 URL 的三份并发只发一份请求，结果共享；落定后恢复常态。 */
  {
    const pending = [];
    const {api, callsTo} = boot({
      '/usage?realm=intl': (url) => new Promise(resolve => pending.push({url, resolve})),
    });
    const url = '/usage?realm=intl';
    const p1 = api.getJSON(url, api.POLL_READ);
    const p2 = api.getJSON(url, api.POLL_READ);
    const p3 = api.getJSON(url, api.POLL_READ);
    check(pending.length === 1,
      '同一 URL 并发时只应发一份请求，实际 ' + pending.length + ' 份');
    pending[0].resolve(okJson({requests: 7}));
    const got = await Promise.all([p1, p2, p3]);
    for (const g of got) assert.deepStrictEqual(g, {requests: 7});

    const p4 = api.getJSON(url, api.POLL_READ);
    check(pending.length === 2,
      '上一份落定后登记项必须摘除，下一次轮询要发新请求');
    pending[1].resolve(okJson({requests: 8}));
    assert.deepStrictEqual(await p4, {requests: 8});
    check(callsTo(url) === 2, '总共只应有 2 次真实 fetch');
  }

  /* 2) 不同 URL、以及同一 URL 不同 cache 档位：绝不合并。 */
  {
    const pending = [];
    const {api} = boot({
      '/usage': (url) => new Promise(resolve => pending.push({url, resolve})),
    });
    const a = api.getJSON('/usage?realm=cn', api.POLL_READ);
    const b = api.getJSON('/usage?realm=cn');            // no-store 档，语义不同
    const c = api.getJSON('/usage?realm=all', api.POLL_READ);
    check(pending.length === 3,
      '不同 URL / 不同 cache 档位不能互相顶替，实际 ' + pending.length + ' 份');
    pending.forEach(p => p.resolve(okJson({})));
    await Promise.all([a, b, c]);
  }

  /* 3) 失败也共享：并发撞上 401 只发一份，两个调用方都拿到 unauthorized。 */
  {
    const pending = [];
    const {api} = boot({
      '/accounts/login/poll': (url) => new Promise(resolve => pending.push({url, resolve})),
    });
    const url = '/accounts/login/poll?state=s1';
    const p1 = api.getJSON(url);
    const p2 = api.getJSON(url);
    check(pending.length === 1, '并发轮询只应发一份请求');
    pending[0].resolve(errRes(401));
    await assert.rejects(p1, /unauthorized/);
    await assert.rejects(p2, /unauthorized/);
    check(document.getElementById('panelLoginMsg').textContent === '会话已失效，请重新输入密码',
      '401 之后闸门提示必须已经摆好');
  }

  /* 4) 挂死保护：超过 60 秒没落定的登记项视为已死，放行新请求；旧请求之后
        落定也不能把新的登记项误删。 */
  {
    const pending = [];
    const {api} = boot({
      '/usage/slow': (url) => new Promise(resolve => pending.push({url, resolve})),
    });
    const url = '/usage/slow';
    const realNow = Date.now;
    let fake = realNow();
    Date.now = () => fake;
    try {
      const p1 = api.getJSON(url);
      check(pending.length === 1, '第一份请求在飞');
      fake += 61000;                                   // 越过 60s 上限
      const p2 = api.getJSON(url);
      check(pending.length === 2, '超过上限必须换发新请求，不能永远陪挂');
      pending[0].resolve(okJson({gen: 1}));            // 旧的那份现在才落定
      await p1;
      const p3 = api.getJSON(url);                     // 新登记项还在飞：应共享它
      check(pending.length === 2, '旧请求落定不得误删新登记项');
      pending[1].resolve(okJson({gen: 2}));
      assert.deepStrictEqual(await p2, {gen: 2});
      assert.deepStrictEqual(await p3, {gen: 2});
    } finally {
      Date.now = realNow;
    }
  }

  /* 5) #recent：同样的数据不再重写，行数据或账号昵称一变立刻重画。 */
  {
    const rows = [
      {at: 100, iso: '2026-10-09T01:02:03', model: 'm1', account: 'u1', stream: true,
       outcome: 'completed', elapsed_ms: 12, ttft_ms: 3, tokens_per_sec: 9.9,
       prompt_tokens: 10, completion_tokens: 20, reasoning_tokens: 0,
       cache_hit_pct: 0, total_tokens: 30, credit: 0.5, cost_cny: 0.01,
       cost_backfilled: false},
      {at: 99, iso: '2026-10-09T01:01:03', model: 'm2', account: 'u2', stream: false,
       outcome: 'failed', error: 'boom', elapsed_ms: 20, ttft_ms: 5, tokens_per_sec: 1.5,
       prompt_tokens: 1, completion_tokens: 2, reasoning_tokens: 0,
       cache_hit_pct: null, total_tokens: 3, credit: 0.2, cost_cny: 0.02,
       cost_backfilled: true},
    ];
    const recentPayload = {total: 2, page: 1, total_pages: 1, usd_cny: 7.2, rows: rows};
    const usagePayload = {requests: 5, cost_cny: 1.5, usd_cny: 7.2, realm: 'intl',
                          log_file: 'usage.jsonl',
                          accounts_map: {u1: {nickname: '甲'}, u2: {nickname: '乙'}}};
    const perfPayload = {errors: 0, success_rate_pct: 100};
    const {api} = boot({
      '/usage/recent': () => Promise.resolve(okJson(recentPayload)),
      '/usage/perf': () => Promise.resolve(okJson(perfPayload)),
      '/usage': () => Promise.resolve(okJson(usagePayload)),
    });
    const el = document.getElementById('recent');   // 桩里按 id 现场建，取到的是同一个
    let writes = 0;
    let current = '';
    Object.defineProperty(el, 'innerHTML', {
      configurable: true,
      get(){ return current; },
      set(v){ writes += 1; current = String(v); },
    });

    await api.refresh();
    check(writes === 1, '第一次刷新必须画表');
    check(current.includes('m1') && current.includes('甲'),
      '表格内容应来自最新数据（模型与昵称）');

    await api.refresh();
    await api.refresh();
    check(writes === 1,
      '数据没变就不该重写 #recent（省下的正是解析与强制布局），实际重写 ' + writes + ' 次');

    rows[0].total_tokens = 31;                    // 同一行的数字变了（回填/补数）
    await api.refresh();
    check(writes === 2, '行数据变化必须立刻重画');

    usagePayload.accounts_map.u1.nickname = '甲甲';  // 行没变、昵称变了
    await api.refresh();
    check(writes === 3, '账号昵称变化也要重画（账号列直接取它）');

    // 显示币种（CNY/USD）不在行数据里，指纹必须把它算进去：切换币种时
    // setCostCurrency() 会就地重刷表格，被指纹挡住的话价格列会停在旧币种上。
    check(current.includes('￥'), '人民币模式下价格列应带 ￥');
    api.setCostCurrency('USD');
    await new Promise(r => setImmediate(r));
    await new Promise(r => setImmediate(r));
    check(writes === 4, '切换显示币种必须重画价格列（指纹漏了 costCurrency 就会卡住）');
    check(current.includes('$') && !current.includes('￥'),
      '重画后的价格列应换成美元符号');
    api.setCostCurrency('CNY');
    await new Promise(r => setImmediate(r));
    await new Promise(r => setImmediate(r));
    check(writes === 5, '切回人民币也要重画');
  }

  /* 6) 日志终端：没有新行一个字节都不动；有新行只 append；过滤变化整表重画；
        超上限只从头部删"被挤出且当前过滤下画过"的条数。 */
  {
    const all = [];
    for (let i = 1; i <= 2000; i++){
      all.push({id: i, time: '10:00:00', level: i <= 5 ? 'ERROR' : 'INFO',
                tag: 'system', msg: 'm' + i});
    }
    const queue = [];
    const {api} = boot({ '/logs': () => Promise.resolve(okJson(queue.shift())) });
    const body = document.getElementById('logTerminalBody');
    let innerWrites = 0;
    const appends = [];
    let removals = 0;
    const origRemove = body.removeChild;
    body.removeChild = (node) => { removals += 1; return origRemove(node); };
    // 桩 DOM 不解析 HTML：把 log-line 的条数折算成子节点，模拟浏览器行为，
    // 这样头部裁剪与 append 的条数都能在测试里数出来。
    const mount = (h) => {
      const n = (String(h).match(/class="log-line"/g) || []).length;
      for (let i = 0; i < n; i++){
        const line = dom.makeElement('div');
        line.className = 'log-line';
        body.appendChild(line);
      }
    };
    Object.defineProperty(body, 'innerHTML', {
      configurable: true,
      get(){ return ''; },
      set(v){ innerWrites += 1; body.children.length = 0; mount(v); },
    });
    body.insertAdjacentHTML = (pos, h) => { appends.push(String(h)); mount(h); };

    const errCount = () => api.getLogEntries().filter(e => e.level === 'ERROR').length;
    const newLine = (id, level) => ({id: id, time: '10:00:0' + (id % 10),
                                     level: level || 'INFO', tag: 'system', msg: 'm' + id});

    queue.push({logs: all, max_id: 2000});
    await api.fetchNewLogs(true);
    check(innerWrites === 1, '首次进入整表渲染一次');
    check(body.children.length === 2000 && api.getLogDomCount() === 2000,
      '满缓冲时 DOM 行数与缓冲一致');

    queue.push({logs: [all[1999]], max_id: 2000});      // 一条新行都没有
    await api.fetchNewLogs(false);
    check(innerWrites === 1, '没有新行就不该重写终端');
    check(appends.length === 0, '没有新行就不该 append');
    check(removals === 0, '没有新行就不该删 DOM 行');

    queue.push({logs: [all[1999], newLine(2001)], max_id: 2001});
    await api.fetchNewLogs(false);
    check(innerWrites === 1, '有新行也只 append，不整表重写');
    check(appends.length === 1 && appends[0].includes('m2001'),
      'append 的内容必须恰好是新增的那行');
    check(removals === 1, '缓冲挤出的 1 条旧行要从 DOM 头部删掉');
    check(body.children.length === 2000 && api.getLogDomCount() === 2000,
      'append 1 行 + 头部删 1 行，总量仍是上限');

    api.setLogFilterLevel('ERROR');
    check(innerWrites === 2, '过滤变化必须整表重画');
    check(body.children.length === errCount() && api.getLogDomCount() === errCount(),
      '过滤后 DOM 行数应等于缓冲里匹配的条数，实际 ' + body.children.length + ' / ' + errCount());

    const removalsBefore = removals;
    const appendsBefore = appends.length;
    queue.push({logs: [newLine(2001), newLine(2002)], max_id: 2002});
    await api.fetchNewLogs(false);
    check(removals === removalsBefore + 1,
      '被挤出的旧行是 ERROR，在当前过滤下画着，必须从头部删 1');
    check(appends.length === appendsBefore, '新行是 INFO，被过滤掉，不该 append');
    check(body.children.length === errCount() && api.getLogDomCount() === errCount(),
      '过滤下的 DOM 与缓冲里匹配的条数保持一致');

    queue.push({logs: [newLine(2002), newLine(2003, 'ERROR'), newLine(2004, 'ERROR')], max_id: 2004});
    await api.fetchNewLogs(false);
    check(removals === removalsBefore + 3, '被挤出的 2 条 ERROR 要删，INFO 那条不删');
    check(appends.length === appendsBefore + 1 && appends[appends.length - 1].includes('m2003'),
      '新增的 ERROR 行要 append 进去');
    check(body.children.length === errCount() && api.getLogDomCount() === errCount(),
      '多步增删之后 DOM 仍与缓冲里匹配的条数一致');

    api.setLogFilterLevel('WARN');                      // 没有任何 WARN 行：空态
    check(innerWrites === 3 && body.children.length === 0,
      '匹配不到就画空态');
    queue.push({logs: [newLine(2004), newLine(2005)], max_id: 2005});
    await api.fetchNewLogs(false);
    check(innerWrites === 4 && appends.length === appendsBefore + 1,
      '空态下不能把新行 append 到"暂无匹配"旁边，必须走整表重画');
  }

  /* 7) 会话失效必须停掉「添加账号」弹窗的登录轮询（loginTimer），之后不再发请求。 */
  {
    const {api, callsTo} = boot({
      '/accounts/login/poll': () => Promise.resolve(errRes(401)),
    }, {realTimers: true});
    api.setLoginState('state-1');
    const timer = setInterval(api.pollLogin, 20);
    api.setLoginTimer(timer);
    try {
      check(api.getLoginTimer() !== null, '前置条件：登录轮询定时器在跑');
      await api.pollLogin();                            // 第一次轮询：401 → 会话失效
      check(api.getLoginTimer() === null,
        '会话失效后必须清掉登录轮询定时器（否则每 2.5 秒一个 401，永不停止）');
      check(api.getPanelReady() === false, '会话失效后 PANEL_READY 必须落下');
      const polls = callsTo('/accounts/login/poll');
      await new Promise(r => setTimeout(r, 120));       // 等几个定时器周期
      check(callsTo('/accounts/login/poll') === polls,
        '会话失效之后不允许再发出任何登录轮询请求');
    } finally {
      if (api.getLoginTimer()) clearInterval(api.getLoginTimer());
    }
  }

  /* 8) i18n 观察者路径：EN 下翻译照旧、跳过规则照旧；allowed() 缓存与
        hasAttributes() 短路确实在生效，且不改变任何结果。 */
  {
    const {api} = boot({}, {beforeEval: () => localStorage.setItem('wb-lang', 'en')});
    check(window.WB_I18N.current() === 'en', '语言应被 localStorage 里的偏好定成 en');

    const htmlEl = document.documentElement;
    htmlEl.parentNode = document;      // 真 DOM 里 documentElement 的父节点就是 document

    const plain = dom.makeElement('div');
    const t1 = document.createTextNode('添加');
    plain.appendChild(t1);
    htmlEl.appendChild(plain);

    const blocked = dom.makeElement('div');
    blocked.setAttribute('data-no-i18n', '1');
    const t2 = document.createTextNode('添加');
    blocked.appendChild(t2);
    htmlEl.appendChild(blocked);

    const attr = dom.makeElement('button');
    attr.setAttribute('title', '7天内到期');
    htmlEl.appendChild(attr);

    const term = document.getElementById('logTerminalBody');
    const t3 = document.createTextNode('添加');
    term.appendChild(t3);

    // 面板的 i18n 会给元素挂 __wbAttr 这类 expando，并在 walk 时读回；桩 DOM 对
    // 未建模成员的读取一律抛错（这是它防回归的设计），所以测试里先把它摆好。
    for (const node of [htmlEl, plain, blocked, attr, term]) node.__wbAttr = null;

    // 计数：allowed() 沿链对每个元素只应探测一次 data-no-i18n；没有属性的元素
    // 不该被逐个 ATTRS 探测（doAttrs 的 hasAttributes 短路）。
    let htmlChainProbes = 0;
    const realHtmlHas = htmlEl.hasAttribute.bind(htmlEl);
    htmlEl.hasAttribute = (k) => {
      if (k === 'data-no-i18n') htmlChainProbes += 1;   // doAttrs 探的是 ATTRS，不算
      return realHtmlHas(k);
    };
    let attrProbes = 0;
    const realPlainHas = plain.hasAttribute.bind(plain);
    plain.hasAttribute = (k) => {
      if (k !== 'data-no-i18n') attrProbes += 1;
      return realPlainHas(k);
    };

    window.WB_I18N.apply();
    check(t1.data === 'Add', 'EN 下普通文本必须被翻译，实得 ' + JSON.stringify(t1.data));
    check(t2.data === '添加', 'data-no-i18n 子树必须保持原文');
    check(term.childNodes[0].data === '添加', '日志终端内容不参与翻译');
    check(attr.getAttribute('title') === 'expiring within 7 days', '属性也要翻译');
    check(attrProbes === 0, '没有属性的元素不该被逐个 ATTRS 探测（hasAttributes 短路）');
    check(htmlChainProbes === 1,
      '第一次 walk：根元素的祖先链只应被探测一次，实际 ' + htmlChainProbes + ' 次');

    const firstWalk = htmlChainProbes;
    window.WB_I18N.apply();
    check(htmlChainProbes === firstWalk,
      'allowed() 结果按元素缓存后，第二次 walk 不应再沿链重复探测祖先');
    check(t1.data === 'Add' && t2.data === '添加'
          && attr.getAttribute('title') === 'expiring within 7 days',
      '重复 apply 的结果必须一致（缓存不得改变行为）');
  }

  console.log('panel poll health assertions passed (' + checks + ' checks)');
})().catch(error => { console.error(error); process.exit(1); });
