// 前端單元測試：把 index.html / empopular/index.html 的 inline <script> 放進 vm 沙箱執行，
// 用最小 DOM stub 取代瀏覽器。零相依，執行：node --test tests/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const ROOT = new URL('../', import.meta.url);
const XSS = '<img src=x onerror=alert(1)>"\'&';

function inlineScript(rel) {
  const html = readFileSync(new URL(rel, ROOT), 'utf8');
  const all = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
  return all[all.length - 1]; // 最後一段是 app 本體（前面是 gtag）
}

function makeEl() {
  return { textContent: '', innerHTML: '', style: {}, dataset: {},
    classList: { add() {}, remove() {} }, addEventListener() {} };
}

// 執行頁面腳本；fetchImpl 給定時會攔截 fetch
function load(rel, { fetchImpl, now } = {}) {
  const els = {};
  const document = {
    getElementById: id => (els[id] ??= makeEl()),
    querySelectorAll: () => [],
  };
  const ctx = {
    document, console, Math, JSON, Object, Array, String, Number, Promise, isNaN, encodeURIComponent,
    setTimeout, Intl,
    Date: now ? class extends Date { constructor(...a) { super(...(a.length ? a : [now])); } static now() { return +now; } } : Date,
    fetch: fetchImpl ?? (() => new Promise(() => {})), // 預設永遠 pending，避免自動 loadData 噪音
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    window: { scrollTo() {} },
    DOMParser: class { parseFromString() { return { querySelectorAll: () => [] }; } },
  };
  vm.createContext(ctx);
  // function 宣告會掛在 ctx 上；let 宣告的 state 另外掛到 __state 供測試讀取
  vm.runInContext(inlineScript(rel) + '\n;globalThis.__state = typeof state !== "undefined" ? state : undefined;', ctx);
  return { ctx, els };
}

const sample = (o = {}) => ({
  pmid: '1', title: 'T', authors: ['A B', 'C D', 'E F'], journal: 'J', journalTier: 1,
  articleType: 'rct', pubDate: '2026-11-03', abstract: 'abs', keywords: ['k1'], meshTerms: [],
  impactScore: 70, url: 'https://pubmed.ncbi.nlm.nih.gov/1/', ...o,
});

// ── index.html ───────────────────────────────────────────
test('esc 跳脫 HTML 特殊字元', () => {
  const { ctx } = load('index.html');
  assert.equal(ctx.esc(XSS), '&lt;img src=x onerror=alert(1)&gt;&quot;&#39;&amp;');
  assert.equal(ctx.esc(null), '');
  assert.equal(ctx.esc(0), '0');
});

test('safeUrl 只放行 http(s)', () => {
  const { ctx } = load('index.html');
  assert.equal(ctx.safeUrl('https://pubmed.ncbi.nlm.nih.gov/1/'), 'https://pubmed.ncbi.nlm.nih.gov/1/');
  assert.equal(ctx.safeUrl('javascript:alert(1)'), '#');
  assert.equal(ctx.safeUrl('https://x/"onmouseover="a'), 'https://x/&quot;onmouseover=&quot;a');
  assert.equal(ctx.safeUrl(undefined), '#');
});

test('tierOf / typeOf 白名單', () => {
  const { ctx } = load('index.html');
  assert.equal(ctx.tierOf({ journalTier: 2 }), 2);
  assert.equal(ctx.tierOf({ journalTier: '1' }), 1);
  assert.equal(ctx.tierOf({ journalTier: '1 x" onclick="y' }), 3);
  assert.equal(ctx.typeOf({ articleType: 'meta-analysis' }), 'meta-analysis');
  assert.equal(ctx.typeOf({ articleType: 'x" onclick="y' }), 'original');
});

test('relDate 依本地日曆日計算，未來日期不出現負數', () => {
  const { ctx } = load('index.html');
  const now = new Date(2026, 10, 4, 6, 0); // 台灣清晨 06:00（產生器排程時間）
  assert.equal(ctx.relDate('2026-11-04', now), '今天');
  assert.equal(ctx.relDate('2026-11-03', now), '昨天');
  assert.equal(ctx.relDate('2026-11-01', now), '3 天前');
  assert.doesNotMatch(ctx.relDate('2026-12-01', now), /-|天前/);
  assert.doesNotMatch(ctx.relDate('2026-10-01', now), /天前/);
  assert.equal(ctx.relDate('', now), '');
  assert.equal(ctx.relDate('garbage', now), '');
  assert.equal(ctx.relDate('2026-00-00', now), '');
  assert.equal(ctx.relDate('2026-02-31', now), '');
});

test('sw 分數條寬度落在 5–100', () => {
  const { ctx } = load('index.html');
  assert.equal(ctx.sw(50, 100), 50);
  assert.equal(ctx.sw(0, 100), 5);
  assert.equal(ctx.sw(200, 100), 100);
  assert.equal(ctx.sw(10, 0), 100);
  assert.equal(ctx.sw(undefined, 100), 5);
});

test('renderCard / renderAOW 不會把第三方內容當 HTML', () => {
  const { ctx } = load('index.html');
  const a = sample({ title: XSS, journal: XSS, abstract: XSS, authors: [XSS], url: 'javascript:alert(1)',
    articleType: XSS, journalTier: XSS, impactScore: XSS });
  for (const html of [ctx.renderCard(a, 1, 80), ctx.renderAOW(a, 80)]) {
    assert.doesNotMatch(html, /<img/);
    assert.doesNotMatch(html, /javascript:/);
    assert.match(html, /&lt;img src=x/);
    assert.match(html, /class="tier-badge t3"/);
    assert.match(html, /class="type-badge original"/);
  }
});

test('renderCard 正常內容與作者截斷', () => {
  const { ctx } = load('index.html');
  const html = ctx.renderCard(sample(), 3, 80);
  assert.match(html, /<div class="article-rank">03<\/div>/);
  assert.match(html, /A B, C D 等/);
  assert.match(html, /隨機對照試驗/);
  assert.match(html, /href="https:\/\/pubmed\.ncbi\.nlm\.nih\.gov\/1\/"/);
  // 缺 authors 也不應丟例外
  assert.doesNotThrow(() => ctx.renderCard(sample({ authors: undefined }), 1, 80));
});

test('renderKeywords 跳脫 data-kw 屬性並依次數排序', () => {
  const { ctx } = load('index.html');
  const html = ctx.renderKeywords([
    sample({ keywords: ['sepsis', `a"b onmouseover="x`] }),
    sample({ keywords: ['sepsis'], meshTerms: ['Shock'] }),
  ]);
  assert.doesNotMatch(html, /data-kw="a"b/);
  assert.match(html, /data-kw="a&quot;b onmouseover=&quot;x"/);
  assert.ok(html.indexOf('sepsis') < html.indexOf('Shock'));
});

test('renderTypeDist 依 TYPE_ORDER 排序', () => {
  const { ctx } = load('index.html');
  const html = ctx.renderTypeDist([sample({ articleType: 'original' }), sample({ articleType: 'guideline' })]);
  assert.ok(html.indexOf('臨床指引') < html.indexOf('原著研究'));
});

test('renderPagination', () => {
  const { ctx } = load('index.html');
  assert.equal(ctx.renderPagination(new Array(30), 0, 30), '');
  const h = ctx.renderPagination(new Array(61), 1, 30);
  assert.match(h, /data-page="0"/);
  assert.match(h, /2 \/ 3/);
  assert.match(h, /data-page="2"/);
});

test('loadData 整合：讀 pulse.json → 渲染統計、精選與篩選', async () => {
  const data = {
    generatedAt: '2026-11-03T22:00:00.000Z',
    stats: { total: 3, byTier: { 1: 2, 2: 1 }, topScore: 80 },
    articles: [sample({ pmid: '1', title: 'Top', impactScore: 80 }),
      sample({ pmid: '2', title: 'Second', articleType: 'review', journalTier: 2 }),
      sample({ pmid: '3', title: `Bad ${XSS}`, keywords: ['sepsis'] })],
  };
  const { ctx, els } = load('index.html', {
    fetchImpl: async () => ({ ok: true, json: async () => data }),
  });
  await new Promise(r => setImmediate(r));
  assert.equal(els['stat-total'].textContent, 3);
  assert.equal(els['stat-tier1'].textContent, 2);
  assert.equal(els['live-label'].textContent, '即時');
  const html = els.content.innerHTML;
  assert.match(html, /本週精選/);
  assert.equal((html.match(/class="article-card/g) || []).length, 2); // 精選不重複出現在清單
  assert.doesNotMatch(html, /<img/);

  ctx.applyFilter('review');
  assert.equal(ctx.__state.filtered.length, 1);
  assert.doesNotMatch(els.content.innerHTML, /本週精選/);
  ctx.applyFilter('tier1');
  assert.equal(ctx.__state.filtered.length, 2);
  ctx.applyKeyword('SEPSIS');
  assert.deepEqual(ctx.__state.filtered.map(a => a.pmid), ['3']);
  assert.match(els.content.innerHTML, /「SEPSIS」共 1 筆結果/);
});

test('loadData 失敗時顯示錯誤且錯誤訊息被跳脫', async () => {
  const { els } = load('index.html', { fetchImpl: async () => { throw new Error(XSS); } });
  await new Promise(r => setImmediate(r));
  assert.match(els.content.innerHTML, /資料載入失敗/);
  assert.doesNotMatch(els.content.innerHTML, /<img/);
  assert.equal(els['live-label'].textContent, '錯誤');
});

// ── empopular/index.html ─────────────────────────────────
test('EM Popular：calcSize 級距', () => {
  const { ctx } = load('empopular/index.html');
  assert.equal(ctx.calcSize(1), null);
  assert.equal(ctx.calcSize(3), 1.0);
  assert.equal(ctx.calcSize(100), 2.6);
});

test('EM Popular：buildCloud 跳脫關鍵字、略過單次詞', () => {
  const { ctx } = load('empopular/index.html');
  const html = ctx.buildCloud([{ word: XSS, count: 5 }, { word: 'once', count: 1 }]);
  assert.doesNotMatch(html, /<img/);
  assert.match(html, /&lt;img/);
  assert.doesNotMatch(html, />once</);
  assert.match(ctx.buildCloud([]), /沒有符合的主題/);
});

test('EM Popular：getColor 對 __proto__/constructor 等字也回傳色碼', () => {
  const { ctx } = load('empopular/index.html');
  for (const w of ['constructor', '__proto__', 'toString']) assert.match(ctx.getColor(w), /^#[0-9A-F]{6}$/i);
});
