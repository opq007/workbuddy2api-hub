/* The recent-requests table shows the reasoning effort each request ran at.

   record_usage() writes reasoning_effort onto the usage row, /usage/recent hands
   it to the panel, and the table renders it as a chip in its own 推理强度 column.
   Rows without the field (older rows, models without reasoning controls) show a
   dash there and otherwise render as before.

   The checks below address cells by the data-label the renderer already emits
   for the card layout, so they say which row carries which chip. They do not
   count the table's columns: another column appearing elsewhere is not a
   regression in this feature, and a suite that fails on it only teaches people
   to edit a number. What this feature owes the reader is the 推理强度 header and
   the chip landing in that cell of the row that ran at that effort.
   Run with Node.
*/
const assert = require('assert');
const {dashboardScript} = require('./_dashboard_source.js');

const script = dashboardScript();

// One shared fake DOM for every dashboard suite: tests/_dom_stub.js. Elements
// are persistent per id, so the rendered table can be read back.
const dom = require('./_dom_stub.js');
const {window: domWindow} = dom.installDom({
  fetch: url => {
    const payload = String(url).includes('/usage/recent')
      ? {rows: ROWS, total: 2, page: 1, total_pages: 1, accounts_map: {}}
      : {rows: [], total: 0, accounts_map: {}, accounts: [], slots: [], data: [],
         results: [], byAccount: []};
    return Promise.resolve({
      status: 200, ok: true,
      json: () => Promise.resolve(payload),
      text: () => Promise.resolve(JSON.stringify(payload)),
    });
  },
});
domWindow.ACCOUNTS = [];
global.ACCOUNTS = domWindow.ACCOUNTS;

const ROWS = [
  {iso: '2026-10-06T12:00:00', model: 'deepseek-v4.1-flash', stream: true,
   outcome: 'completed', elapsed_ms: 1200, ttft_ms: 800, tokens_per_sec: 100,
   prompt_tokens: 10, completion_tokens: 5, reasoning_tokens: 3, cache_hit_pct: 90,
   total_tokens: 15, credit: 0, account: 'uid-1', reasoning_effort: 'high'},
  {iso: '2026-10-06T12:01:00', model: 'hy3', stream: false, outcome: 'completed',
   elapsed_ms: 900, ttft_ms: null, prompt_tokens: 4, completion_tokens: 2,
   total_tokens: 6, credit: 0, account: 'uid-1'},
];

// The header cells, in order. Read from <th> rather than counted: the table is
// allowed to grow columns, and only the labels are this feature's contract.
function headerLabels(html) {
  const head = html.slice(html.indexOf('<thead>'), html.indexOf('</thead>'));
  return [...head.matchAll(/<th[^>]*>([\s\S]*?)<\/th>/g)].map(m => m[1].trim());
}

// One object per body row: data-label -> cell HTML. A cell is addressed by the
// label the renderer emits, so a row is read the same way whatever the column
// order or the number of columns turns out to be.
function bodyRows(html) {
  const body = html.slice(html.indexOf('<tbody>'), html.indexOf('</tbody>'));
  return [...body.matchAll(/<tr>([\s\S]*?)<\/tr>/g)].map(row => {
    const cells = {};
    for (const cell of row[1].matchAll(/<td([^>]*)>([\s\S]*?)<\/td>/g)) {
      const label = (cell[1].match(/data-label="([^"]*)"/) || [])[1];
      if (label) cells[label] = cell[2];
    }
    return cells;
  });
}

const chip = html => /class="badge-effort"/.test(html || '');

const api = new Function(script + `
  window.updateUI = updateUI;
  window.toast = toast;
  return { refresh };`)();

(async () => {
  window.VIEW_REALM = 'intl';
  await api.refresh();
  const rendered = dom.byId('recent').innerHTML;
  let checks = 0;
  const check = (label, cond, extra) => {
    checks += 1;
    assert.ok(cond, label + (extra ? '  [' + extra + ']' : ''));
  };

  const headers = headerLabels(rendered);
  const rows = bodyRows(rendered);
  const rowOf = model => rows.find(r => r['模型'] === model);
  const effortRow = rowOf('deepseek-v4.1-flash');
  const plainRow = rowOf('hy3');

  check('the table has a 推理强度 column',
        headers.includes('推理强度'), headers.join(' | '));
  check('the row that ran at an effort shows it in its 推理强度 cell',
        effortRow && chip(effortRow['推理强度']) && /^<span class="badge-effort">high<\/span>$/.test(effortRow['推理强度'].trim()),
        effortRow && effortRow['推理强度']);
  check('the chip is in the row it belongs to, not in a neighbour',
        rows.filter(r => chip(r['推理强度'])).length === 1
        && chip(effortRow && effortRow['推理强度']) && !chip(plainRow && plainRow['推理强度']),
        rows.map(r => r['模型'] + '=' + (r['推理强度'] || '')).join(', '));
  check('the model cell holds only the model name',
        effortRow && effortRow['模型'] === 'deepseek-v4.1-flash' && !chip(effortRow['模型']),
        effortRow && effortRow['模型']);
  check('the row without an effort shows a dash, not a chip',
        plainRow && !chip(plainRow['推理强度']) && /—/.test(plainRow['推理强度']),
        plainRow && plainRow['推理强度']);
  check('no other cell carries the effort chip',
        rows.every(r => Object.keys(r).every(label =>
          label === '推理强度' || !chip(r[label]))),
        rows.map(r => Object.keys(r).filter(l => chip(r[l])).join('/')).join(', '));

  console.log('recent-requests effort assertions passed (' + checks + ' checks)');
})();
