/* 面板轮询读取的 fetch 缓存模式：必须让浏览器存副本并每次回源校验。

   服务端给用量那几个读接口发了 ETag + Cache-Control: no-cache，但那只在浏览器
   真的会发条件请求时才有用。面板原先一律用 `fetch(url, {cache:'no-store'})`：
   no-store 的语义是"连副本都别存"，于是浏览器既没有东西可校验，也永远不会带
   If-None-Match —— 服务端的 304 一次也拿不到，5 秒一轮的 10~100KB 照旧整份重传。
   这类接口现在走 POLL_READ（cache:'no-cache'：可存储、每次使用前回源校验）。

   反过来，登录轮询和密钥类读取必须留在 no-store：它们的响应体每一轮都不同
   （或者含机密），让浏览器存下来没有任何好处。这条也钉在这里，免得有人图省事
   把 getJSON 的默认值一改到底。

   Run with Node: node tests/_test_panel_poll_revalidate.js
*/
'use strict';
const assert = require('assert');
const {dashboardHtml, dashboardScript} = require('./_dashboard_source.js');

const html = dashboardHtml();

/* 取出一段源码里所有 name(...) 调用的实参文本（跳过字符串字面量里的括号）。 */
function callArgs(source, name) {
  const out = [];
  let idx = 0;
  while ((idx = source.indexOf(name + '(', idx)) !== -1) {
    let i = idx + name.length + 1;
    let depth = 1;
    const start = i;
    while (i < source.length && depth > 0) {
      const ch = source[i];
      if (ch === "'" || ch === '"' || ch === '`') {
        const quote = ch;
        i++;
        while (i < source.length && source[i] !== quote) {
          if (source[i] === '\\') i++;
          i++;
        }
      } else if (ch === '(') {
        depth++;
      } else if (ch === ')') {
        depth--;
      }
      i++;
    }
    out.push(source.slice(start, i - 1));
    idx = i;
  }
  return out;
}

const calls = callArgs(html, 'getJSON');

// 1) 轮询的用量读接口：每处调用都必须带上 POLL_READ。
const polled = calls.filter(args => /\/usage/.test(args) && !/\/usage\/recent/.test(args));
assert.ok(polled.length >= 6,
  `只扫到 ${polled.length} 处用量轮询调用，提取逻辑坏了（页面本身没坏）`);
for (const args of polled) {
  assert.ok(/\bPOLL_READ\b/.test(args),
    `轮询的用量读取必须允许回源校验（cache:'no-cache'），这一处没有：getJSON(${args})`);
}

// 2) 登录轮询与密钥类读取：绝不允许可缓存校验。
const sensitive = calls.filter(args => /\/accounts\/login\/poll|\/settings\/reveal/.test(args));
assert.ok(sensitive.length >= 2,
  `只扫到 ${sensitive.length} 处登录/密钥读取，提取逻辑坏了`);
for (const args of sensitive) {
  assert.ok(!/\bPOLL_READ\b/.test(args),
    `登录轮询与密钥读取必须留在 no-store，这一处不该可校验：getJSON(${args})`);
}

// 3) 选项本身：POLL_READ 就是 revalidate，且默认档仍是 no-store。
assert.ok(/const POLL_READ = \{revalidate: true\};/.test(html),
  'dashboard.html 里应当有 const POLL_READ = {revalidate: true};');

// 4) 跑一遍页面里真实的 getJSON，确认两档真的落到 fetch 的 cache 参数上。
const dom = require('./_dom_stub.js');
const seen = [];
dom.installDom({
  fetch: (url, options) => {
    seen.push({url: String(url), cache: (options || {}).cache});
    return Promise.resolve({
      status: 200, ok: true,
      json: () => Promise.resolve({}), text: () => Promise.resolve('{}'),
    });
  },
});
const api = new Function(dashboardScript() + '\n  return {getJSON, POLL_READ};')();

(async () => {
  // 页面自身在加载时就会发一次 /panel/status（它必须留在 no-store），所以按 URL
  // 取自己那一次，而不是按序号。
  const cacheOf = (url) => {
    const hit = seen.filter(c => c.url === url).pop();
    assert.ok(hit, '没抓到这次请求：' + url);
    return hit.cache;
  };

  await api.getJSON('/usage?realm=intl', api.POLL_READ);
  assert.strictEqual(cacheOf('/usage?realm=intl'), 'no-cache',
    "轮询读取必须用 cache:'no-cache'（可存储 + 每次回源校验），否则浏览器不会发 If-None-Match");

  await api.getJSON('/accounts/login/poll?state=x');
  assert.strictEqual(cacheOf('/accounts/login/poll?state=x'), 'no-store',
    '默认读取必须仍是 no-store（不存储、每次整份重取）');

  await api.getJSON('/settings/reveal?id=k');
  assert.strictEqual(cacheOf('/settings/reveal?id=k'), 'no-store',
    '密钥类读取必须留在 no-store');

  console.log(`panel poll revalidate assertions passed (${polled.length} polled reads checked)`);
})().catch(error => { console.error(error); process.exit(1); });
