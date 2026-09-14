/* 結合選択画面 (フロントエンド)。フレームワーク無し、素の JS。
 *
 * サーバ (gpmf_tool.webui.server) の JSON API を叩き、エクスプローラーの
 * 「詳細」表示に似た一覧を描く。状態はすべて `state` に持ち、大きな変化
 * (スキャン結果・並べ替え・表示切替) は render() で丸ごと描き直し、
 * チェック/選択だけは行単位で更新する。
 */
'use strict';

// ---------------------------------------------------------------------------
// トークン (初回 URL の ?t=… を保持し、以後は X-Token ヘッダで送る)
// ---------------------------------------------------------------------------
const TOKEN = (() => {
  const q = new URLSearchParams(location.search).get('t');
  try {
    if (q) { sessionStorage.setItem('gpmf_token', q); return q; }
    return sessionStorage.getItem('gpmf_token') || '';
  } catch (_) { return q || ''; }
})();

async function api(path, body) {
  const opt = { method: body === undefined ? 'GET' : 'POST',
                headers: { 'X-Token': TOKEN } };
  if (body !== undefined) {
    opt.headers['Content-Type'] = 'application/json';
    opt.body = JSON.stringify(body);
  }
  const r = await fetch(path, opt);
  let data = {};
  try { data = await r.json(); } catch (_) { /* 本文なし */ }
  if (!r.ok) throw new Error(data.error || ('HTTP ' + r.status));
  return data;
}
// <img>/<video> の src 用 (ヘッダを付けられないのでクエリでトークンを渡す)
function mediaUrl(path) {
  return path + (path.includes('?') ? '&' : '?') + 't=' + encodeURIComponent(TOKEN);
}

// ---------------------------------------------------------------------------
// 状態
// ---------------------------------------------------------------------------
const state = {
  folder: '', groups: [], scanned: false,
  scanning: false, joining: false, quit: false,
  showSolo: false, showThumbs: true, recursive: false, thumbSize: 'm',
  sort: { key: null, dir: 1 },
  selection: new Set(), anchor: null, focus: null,
  collapsed: new Set(),
  outDir: '', devices: [], deviceLabels: {}, device: 'hero9',
  gpx: '', fromVideo: false, rate: 10,
  detailsWidth: 300,
};

const PREFS_KEY = 'gpmf_webui_prefs';
function loadPrefs() {
  try {
    const p = JSON.parse(localStorage.getItem(PREFS_KEY) || '{}');
    for (const k of ['showSolo', 'showThumbs', 'recursive', 'thumbSize', 'device',
                     'fromVideo', 'rate', 'detailsWidth']) {
      if (p[k] !== undefined) state[k] = p[k];
    }
    if (p.colWidths) for (const c of COLS) if (p.colWidths[c.key]) c.width = p.colWidths[c.key];
    if (p.sort) state.sort = p.sort;
  } catch (_) { /* localStorage 不可 */ }
}
function savePrefs() {
  try {
    const colWidths = {};
    for (const c of COLS) colWidths[c.key] = c.width;
    localStorage.setItem(PREFS_KEY, JSON.stringify({
      showSolo: state.showSolo, showThumbs: state.showThumbs, recursive: state.recursive,
      thumbSize: state.thumbSize, device: state.device, fromVideo: state.fromVideo,
      rate: state.rate, detailsWidth: state.detailsWidth, colWidths, sort: state.sort,
    }));
  } catch (_) { /* 無視 */ }
}

// ---------------------------------------------------------------------------
// 列定義
// ---------------------------------------------------------------------------
const COLS = [
  { key: 'check', label: '', width: 34, sortable: false, cls: 'c-check' },
  { key: 'thumb', label: 'サムネイル', width: 150, sortable: false, cls: 'c-thumb' },
  { key: 'name', label: '名前', width: 230, sortable: true, cls: 'c-name' },
  { key: 'size', label: 'サイズ', width: 90, sortable: true, cls: 'c-size', right: true },
  { key: 'duration', label: '長さ', width: 80, sortable: true, cls: 'c-dur', right: true },
  { key: 'resolution', label: '解像度', width: 100, sortable: true, cls: 'c-res' },
  { key: 'created', label: '撮影日時', width: 140, sortable: true, cls: 'c-created' },
  { key: 'kind', label: '種類', width: 90, sortable: true, cls: 'c-kind' },
  { key: 'filler', label: '', width: 0, sortable: false, cls: 'c-filler' },
];
function visibleCols() {
  return COLS.filter(c => c.key !== 'thumb' || state.showThumbs);
}
function thumbWidthFor(size) {
  return { s: 64, m: 128, l: 192 }[size] + 22;
}

// ---------------------------------------------------------------------------
// 整形 (Python 側 browse.format_size / format_duration と同じ)
// ---------------------------------------------------------------------------
function fmtSize(n) {
  if (n >= 1024 ** 3) return (n / 1024 ** 3).toFixed(2) + ' GB';
  if (n >= 1024 ** 2) return Math.round(n / 1024 ** 2) + ' MB';
  if (n >= 1024) return Math.round(n / 1024) + ' KB';
  return n + ' B';
}
function fmtGB(n) { return (n / 1024 ** 3).toFixed(2) + ' GB'; }
function fmtDur(sec) {
  if (!sec || sec <= 0) return '-';
  const t = Math.round(sec);
  const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60;
  const p = v => String(v).padStart(2, '0');
  return h ? `${h}:${p(m)}:${p(s)}` : `${m}:${p(s)}`;
}
const CONF_JA = { high: '高', medium: '中', low: '低' };
const VENDOR_JA = { gopro: 'GoPro', dji: 'DJI', insta360: 'Insta360', sony: 'Sony', generic: '' };

// DOM ヘルパ
const $ = s => document.querySelector(s);
function el(tag, attrs, ...children) {
  const n = document.createElement(tag);
  if (attrs) for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') n.className = v;
    else if (k === 'text') n.textContent = v;
    else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children) {
    if (c === null || c === undefined || c === false) continue;
    n.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return n;
}

// ---------------------------------------------------------------------------
// グループ/エントリの導出
// ---------------------------------------------------------------------------
function checkedEntries(g) { return g.entries.filter(e => e.selected && !e.error); }
function groupTotals(g) {
  const es = checkedEntries(g);
  return { n: es.length,
           size: es.reduce((a, e) => a + (e.size || 0), 0),
           dur: es.reduce((a, e) => a + (e.duration || 0), 0) };
}
function groupTitle(g) {
  const t = groupTotals(g);
  if (!g.is_split) return `単独の動画 (${fmtDur(t.dur)})`;
  return `分割された1本の撮影 — ${t.n}個 / ${fmtDur(t.dur)} / ${fmtSize(t.size)}`;
}
function joinableGroups() {
  return state.groups.filter(g => g.is_split && checkedEntries(g).length >= 2);
}
function sortKey(e, key) {
  switch (key) {
    case 'name': return (e.name || '').toLowerCase();
    case 'size': return e.size || 0;
    case 'duration': return e.duration || 0;
    case 'resolution': return (e.width || 0) * (e.height || 0);
    case 'created': return e.created_iso || '';
    case 'kind': return e.kind_text || '';
    default: return 0;
  }
}
function cmp(a, b) { return a < b ? -1 : a > b ? 1 : 0; }
// 表示するグループ列 (フィルタ・並べ替え済み)。結合順は g.entries のまま。
function visibleGroups() {
  const gs = state.groups.filter(g => g.is_split || state.showSolo);
  const { key, dir } = state.sort;
  return gs.map(g => {
    let es = g.entries.slice();
    if (key) es.sort((a, b) => dir * cmp(sortKey(a, key), sortKey(b, key)) || cmp(a.name, b.name));
    return { g, entries: es };
  }).sort((A, B) => {
    if (!key) return 0;
    const a = A.entries[0] ? sortKey(A.entries[0], key) : '';
    const b = B.entries[0] ? sortKey(B.entries[0], key) : '';
    return dir * cmp(a, b);
  });
}
function findEntry(id) {
  for (const g of state.groups) for (const e of g.entries) if (e.id === id) return { g, e };
  return null;
}
function findGroup(id) { return state.groups.find(g => g.id === id) || null; }

// ---------------------------------------------------------------------------
// 描画: ヘッダ
// ---------------------------------------------------------------------------
let resizing = null;
function buildHeader() {
  const cols = visibleCols();
  const cg = $('#cols'); cg.replaceChildren();
  const tr = $('#head'); tr.replaceChildren();
  let total = 0;
  for (const c of cols) {
    const col = el('col', { class: c.cls });
    const w = c.key === 'thumb' ? thumbWidthFor(state.thumbSize) : c.width;
    if (c.key !== 'filler') { col.style.width = w + 'px'; total += w; }
    cg.append(col);
    const th = el('th', { class: `${c.cls}${c.sortable ? ' sortable' : ''}${c.right ? ' right' : ''}`,
                          'data-key': c.key });
    if (c.key === 'check') {
      const all = el('input', { type: 'checkbox', title: '表示中の全ファイルを選択/解除' });
      all.addEventListener('change', () => setAllChecked(all.checked));
      th.append(all);
    } else {
      th.append(el('span', { text: c.label }));
      if (state.sort.key === c.key) th.append(el('span', { class: 'sort-mark', text: state.sort.dir > 0 ? '▲' : '▼' }));
      if (c.sortable) th.addEventListener('click', () => { if (!resizing) toggleSort(c.key); });
    }
    if (c.key !== 'filler' && c.key !== 'check') {
      const rz = el('div', { class: 'resizer' });
      rz.addEventListener('mousedown', ev => startResize(ev, c, col, th));
      th.append(rz);
    }
    tr.append(th);
  }
  // 列幅の合計より広ければ余りは最後の空列が吸収し、狭ければ横スクロール
  const grid = $('#grid');
  grid.style.minWidth = total + 'px';
  grid.classList.toggle('no-thumbs', !state.showThumbs);
  grid.classList.remove('thumb-s', 'thumb-m', 'thumb-l');
  grid.classList.add('thumb-' + state.thumbSize);
}
function startResize(ev, c, col, th) {
  ev.preventDefault(); ev.stopPropagation();
  const startX = ev.clientX, startW = col.getBoundingClientRect().width;
  resizing = c.key;
  const move = e => {
    const w = Math.max(40, Math.round(startW + e.clientX - startX));
    c.width = w; col.style.width = w + 'px';
    let total = 0;
    for (const cc of visibleCols()) if (cc.key !== 'filler') total += (cc.key === 'thumb' ? thumbWidthFor(state.thumbSize) : cc.width);
    $('#grid').style.minWidth = total + 'px';
  };
  const up = () => {
    document.removeEventListener('mousemove', move);
    document.removeEventListener('mouseup', up);
    setTimeout(() => { resizing = null; }, 0);
    savePrefs();
  };
  document.addEventListener('mousemove', move);
  document.addEventListener('mouseup', up);
}
function toggleSort(key) {
  if (state.sort.key === key) {
    if (state.sort.dir > 0) state.sort.dir = -1;
    else state.sort = { key: null, dir: 1 };          // 3 回目で元の順に戻す
  } else state.sort = { key, dir: 1 };
  savePrefs();
  render();
}

// ---------------------------------------------------------------------------
// 描画: サムネイル (遅延読み込み + 画像→動画→プレースホルダの順で降格)
// ---------------------------------------------------------------------------
const thumbCache = new Map();   // entry id → element
const io = ('IntersectionObserver' in window)
  ? new IntersectionObserver(entries => {
      for (const it of entries) {
        if (!it.isIntersecting) continue;
        const img = it.target;
        io.unobserve(img);
        if (img.dataset.src) { img.src = img.dataset.src; delete img.dataset.src; }
      }
    }, { root: null, rootMargin: '200px' })
  : null;

function placeholder(e, broken) {
  const ph = el('div', { class: 'ph' + (broken ? ' broken' : '') },
    el('div', { class: 'film' }),
    el('div', { class: 'txt', text: broken ? '読めません'
      : [e.resolution_text !== '-' ? e.resolution_text : '', e.duration_text !== '-' ? e.duration_text : '']
        .filter(Boolean).join(' / ') || '動画' }));
  return ph;
}
function thumbFor(e) {
  if (thumbCache.has(e.id)) return thumbCache.get(e.id);
  const box = el('div', { class: 'thumb' });
  if (e.error) {
    box.append(placeholder(e, true));
  } else {
    const img = el('img', { alt: '' });
    img.dataset.src = mediaUrl('/api/thumb?id=' + e.id);
    img.addEventListener('error', () => {
      // 画像が無い (404) → ブラウザがデコードできれば動画の 1 コマを出す
      const v = el('video', { preload: 'metadata', muted: true, playsinline: true });
      v.muted = true;
      const t = e.duration && e.duration < 1.2 ? 0.1 : 1;
      v.src = mediaUrl('/api/file?id=' + e.id) + '#t=' + t;
      v.addEventListener('error', () => box.replaceChildren(placeholder(e, false)));
      box.replaceChildren(v);
    });
    box.append(img);
    if (io) io.observe(img); else img.src = img.dataset.src;
  }
  thumbCache.set(e.id, box);
  return box;
}

// ---------------------------------------------------------------------------
// 描画: 行
// ---------------------------------------------------------------------------
function td(cls, ...children) { return el('td', { class: cls }, ...children); }
function kindCell(e) {
  const c = td('c-kind');
  if (e.is_360) c.append(el('span', { class: 'kind-badge sph', text: '360度' }));
  if (e.has_gpmd) c.append(el('span', { class: 'kind-badge gopro', text: 'GoPro' }));
  else if (e.has_gps) c.append(el('span', { class: 'kind-badge gps', text: 'GPS' }));
  if (!c.childElementCount) c.append(el('span', { class: 'kind-badge', text: e.kind_text || '動画' }));
  return c;
}
function entryRow(g, e, i) {
  const key = 'e:' + e.id;
  const tr = el('tr', { class: 'item ' + (i % 2 ? 'even' : 'odd') + (e.error ? ' broken' : ''),
                        'data-key': key, 'data-group': g.id });
  if (e.error) tr.title = e.error; else if (e.warning) tr.title = e.warning;
  const cb = el('input', { type: 'checkbox' });
  cb.checked = !!e.selected && !e.error;
  cb.disabled = !!e.error;
  cb.addEventListener('click', ev => ev.stopPropagation());
  cb.addEventListener('mousedown', ev => ev.stopPropagation());
  cb.addEventListener('change', () => { e.selected = cb.checked; afterCheckChange(g); });
  tr.append(td('c-check', cb));
  if (state.showThumbs) tr.append(td('c-thumb', thumbFor(e)));
  const name = td('c-name');
  if (e.error) name.append(el('span', { class: 'warn-icon', title: e.error, text: '⚠' }));
  name.append(el('span', { class: 'fname', text: e.name }));
  if (!e.error && e.warning) name.append(el('span', { class: 'warn-icon soft', title: e.warning, text: '⚠' }));
  name.title = e.path;
  tr.append(name);
  tr.append(td('c-size right', e.size_text || fmtSize(e.size || 0)));
  tr.append(td('c-dur right', e.duration_text || fmtDur(e.duration)));
  tr.append(td('c-res', e.resolution_text || '-'));
  tr.append(td('c-created', e.created_text || '-'));
  tr.append(e.error ? td('c-kind', el('span', { class: 'kind-badge', text: '読めません' })) : kindCell(e));
  tr.append(td('c-filler'));
  tr.addEventListener('mousedown', ev => {
    if (ev.button !== 0) return;
    if (ev.shiftKey) ev.preventDefault();
    selectRow(key, ev);
  });
  tr.addEventListener('dblclick', () => { if (!e.error) { cb.checked = !cb.checked; e.selected = cb.checked; afterCheckChange(g); } });
  return tr;
}
function groupHead(g) {
  const collapsed = state.collapsed.has(g.id);
  const t = groupTotals(g);
  const cb = el('input', { type: 'checkbox', title: 'このグループの全ファイルを選択/解除' });
  const valid = g.entries.filter(e => !e.error);
  cb.checked = valid.length > 0 && t.n === valid.length;
  cb.indeterminate = t.n > 0 && t.n < valid.length;
  cb.disabled = valid.length === 0;
  cb.addEventListener('click', ev => ev.stopPropagation());
  cb.addEventListener('mousedown', ev => ev.stopPropagation());
  cb.addEventListener('change', () => setGroupChecked(g, cb.checked));
  const caret = el('span', { class: 'caret' + (collapsed ? ' collapsed' : ''), text: '▼', title: '折りたたみ/展開' });
  caret.addEventListener('mousedown', ev => ev.stopPropagation());
  caret.addEventListener('click', ev => { ev.stopPropagation(); toggleCollapse(g.id); });
  const head = el('div', { class: 'group-head' }, caret, cb,
    el('span', { class: 'gtitle', text: groupTitle(g) }));
  if (g.confidence && CONF_JA[g.confidence])
    head.append(el('span', { class: 'badge ' + g.confidence, text: '確度 ' + CONF_JA[g.confidence], title: '同じ撮影である確からしさ' }));
  if (g.vendor && VENDOR_JA[g.vendor]) head.append(el('span', { class: 'badge vendor', text: VENDOR_JA[g.vendor] }));
  const reason = g.reason || (g.is_split ? '撮影時刻が連続しているため、1本の撮影が分割されたものと判定' : '');
  if (reason) head.append(el('span', { class: 'greason', text: reason, title: reason }));
  head.append(el('span', { class: 'gline' }));
  head.append(el('span', { class: 'gtotals',
    text: `${g.entries.length} ファイル` + (g.entries.some(e => e.error) ? ` (読めない ${g.entries.filter(e => e.error).length})` : '') }));
  return head;
}
function groupRow(g) {
  const key = 'g:' + g.id;
  const tr = el('tr', { class: 'group', 'data-key': key, 'data-group': g.id });
  tr.append(el('td', { colspan: String(visibleCols().length) }, groupHead(g)));
  tr.addEventListener('mousedown', ev => { if (ev.button === 0) { if (ev.shiftKey) ev.preventDefault(); selectRow(key, ev); } });
  tr.addEventListener('dblclick', () => toggleCollapse(g.id));
  return tr;
}
function updateGroupRow(g) {
  const tr = $('#rows').querySelector(`tr.group[data-group="${g.id}"]`);
  if (tr) tr.firstChild.replaceChildren(groupHead(g));
}

function render() {
  buildHeader();
  const tbody = $('#rows');
  const frag = document.createDocumentFragment();
  const vis = visibleGroups();
  for (const { g, entries } of vis) {
    frag.append(groupRow(g));
    if (!state.collapsed.has(g.id)) entries.forEach((e, i) => frag.append(entryRow(g, e, i)));
  }
  tbody.replaceChildren(frag);
  // 空のとき
  const empty = $('#empty'), et = $('#empty-text');
  const nSolo = state.groups.filter(g => !g.is_split).length;
  if (!state.scanned) { et.textContent = 'フォルダを選んでスキャンすると、ここに動画が一覧表示されます。'; empty.classList.remove('hidden'); }
  else if (!state.groups.length) { et.textContent = 'このフォルダには動画 (.mp4 / .mov / .m4v / .360) が見つかりませんでした。'; empty.classList.remove('hidden'); }
  else if (!vis.length) { et.textContent = `分割された動画は見つかりませんでした。単独の動画 ${nSolo} 個は非表示です（「単独の動画も表示」で表示できます）。`; empty.classList.remove('hidden'); }
  else empty.classList.add('hidden');
  // 表示されなくなった選択は捨てる
  const keys = new Set(rowKeys());
  for (const k of [...state.selection]) if (!keys.has(k)) state.selection.delete(k);
  if (state.focus && !keys.has(state.focus)) state.focus = null;
  updateSelectionClasses();
  updateStatus();
  updateDetails();
}

// ---------------------------------------------------------------------------
// チェック (結合対象の取捨選択)
// ---------------------------------------------------------------------------
function afterCheckChange(g) {
  updateGroupRow(g);
  updateHeaderCheck();
  updateStatus();
  updateDetails();
}
function setGroupChecked(g, on) {
  for (const e of g.entries) if (!e.error) e.selected = on;
  for (const e of g.entries) {
    const cb = $('#rows').querySelector(`tr[data-key="e:${e.id}"] input[type=checkbox]`);
    if (cb) cb.checked = on && !e.error;
  }
  afterCheckChange(g);
}
function setAllChecked(on) {
  for (const { g } of visibleGroups()) {
    for (const e of g.entries) if (!e.error) e.selected = on;
  }
  render();
}
function updateHeaderCheck() {
  const all = $('#head input[type=checkbox]');
  if (!all) return;
  let n = 0, total = 0;
  for (const { g } of visibleGroups()) for (const e of g.entries) if (!e.error) { total++; if (e.selected) n++; }
  all.checked = total > 0 && n === total;
  all.indeterminate = n > 0 && n < total;
}
function toggleChecked(keys) {
  const touched = new Set();
  for (const k of keys) {
    if (k.startsWith('e:')) {
      const f = findEntry(k.slice(2));
      if (!f || f.e.error) continue;
      f.e.selected = !f.e.selected;
      const cb = $('#rows').querySelector(`tr[data-key="${k}"] input[type=checkbox]`);
      if (cb) cb.checked = f.e.selected;
      touched.add(f.g);
    } else if (k.startsWith('g:')) {
      const g = findGroup(k.slice(2));
      if (g) { const t = groupTotals(g); setGroupChecked(g, t.n < g.entries.filter(e => !e.error).length); }
    }
  }
  for (const g of touched) updateGroupRow(g);
  updateHeaderCheck(); updateStatus(); updateDetails();
}

// ---------------------------------------------------------------------------
// 選択 (ハイライト。チェックとは別)
// ---------------------------------------------------------------------------
function rowKeys() { return [...$('#rows').querySelectorAll('tr[data-key]')].map(tr => tr.dataset.key); }
function selectRow(key, ev) {
  const keys = rowKeys();
  if (ev && ev.shiftKey && state.anchor && keys.includes(state.anchor)) {
    const a = keys.indexOf(state.anchor), b = keys.indexOf(key);
    const [lo, hi] = a < b ? [a, b] : [b, a];
    state.selection = new Set(keys.slice(lo, hi + 1).filter(k => k.startsWith('e:')));
    if (key.startsWith('g:')) state.selection.add(key);
  } else if (ev && (ev.ctrlKey || ev.metaKey)) {
    if (state.selection.has(key)) state.selection.delete(key); else state.selection.add(key);
    state.anchor = key;
  } else {
    state.selection = new Set([key]);
    state.anchor = key;
  }
  state.focus = key;
  updateSelectionClasses();
  updateDetails();
  $('#scroll').focus({ preventScroll: true });
}
function updateSelectionClasses() {
  for (const tr of $('#rows').querySelectorAll('tr[data-key]')) {
    tr.classList.toggle('selected', state.selection.has(tr.dataset.key));
    tr.classList.toggle('focus', state.focus === tr.dataset.key);
  }
}
function toggleCollapse(gid) {
  if (state.collapsed.has(gid)) state.collapsed.delete(gid); else state.collapsed.add(gid);
  render();
}
function moveFocus(delta) {
  const keys = rowKeys();
  if (!keys.length) return;
  let i = keys.indexOf(state.focus);
  i = i < 0 ? (delta > 0 ? 0 : keys.length - 1) : Math.min(keys.length - 1, Math.max(0, i + delta));
  selectRow(keys[i], null);
  const tr = $('#rows').querySelector(`tr[data-key="${keys[i]}"]`);
  if (tr) tr.scrollIntoView({ block: 'nearest' });
}
$('#scroll').addEventListener('keydown', ev => {
  if (state.quit) return;
  const mod = ev.ctrlKey || ev.metaKey;
  if (ev.key === ' ') { ev.preventDefault(); toggleChecked(state.selection); }
  else if (mod && (ev.key === 'a' || ev.key === 'A')) {
    ev.preventDefault();
    state.selection = new Set(rowKeys().filter(k => k.startsWith('e:')));
    updateSelectionClasses(); updateDetails();
  } else if (ev.key === 'ArrowDown') { ev.preventDefault(); moveFocus(1); }
  else if (ev.key === 'ArrowUp') { ev.preventDefault(); moveFocus(-1); }
  else if (ev.key === 'Enter') {
    if (state.focus && state.focus.startsWith('g:')) { ev.preventDefault(); toggleCollapse(state.focus.slice(2)); }
  } else if (ev.key === 'ArrowLeft' || ev.key === 'ArrowRight') {
    if (state.focus && state.focus.startsWith('g:')) {
      const gid = state.focus.slice(2);
      const want = ev.key === 'ArrowLeft';
      if (state.collapsed.has(gid) !== want) { ev.preventDefault(); toggleCollapse(gid); }
    }
  } else if (ev.key === 'Escape') { state.selection.clear(); updateSelectionClasses(); updateDetails(); }
});

// ---------------------------------------------------------------------------
// ステータスバー / 詳細ペイン
// ---------------------------------------------------------------------------
function updateStatus() {
  const nFiles = state.groups.reduce((a, g) => a + g.entries.length, 0);
  const joinable = joinableGroups();
  let nSel = 0, bytes = 0;
  for (const g of state.groups) if (g.is_split) for (const e of checkedEntries(g)) { nSel++; bytes += e.size || 0; }
  const parts = [`動画 ${nFiles} 個`, `結合対象 ${joinable.length} 件`,
                 `選択中 ${nSel} ファイル 合計 ${fmtGB(bytes)}（出力に同容量の空きが必要）`];
  $('#status-text').textContent = parts.join(' / ');
  const can = joinable.length > 0 && !state.joining && !state.scanning && !state.quit;
  $('#btn-join').disabled = !can;
  $('#btn-join-gopro').disabled = !can;
}
function dl(pairs) {
  const d = el('dl', { class: 'dl' });
  for (const [k, v] of pairs) { if (v === null || v === undefined || v === '') continue; d.append(el('dt', { text: k }), el('dd', { text: String(v) })); }
  return d;
}
function updateDetails() {
  const body = $('#details-body'), title = $('#details-title');
  const sel = [...state.selection];
  body.replaceChildren();
  if (!sel.length) {
    title.textContent = '詳細';
    body.append(el('div', { class: 'hint' },
      '行をクリックすると詳しい情報が表示されます。', el('br'),
      'Ctrl/⌘+クリックで複数選択、Shift+クリックで範囲選択、', el('br'),
      'Space でチェックの切り替え、Ctrl/⌘+A で全選択。'));
    return;
  }
  if (sel.length > 1) {
    const es = sel.filter(k => k.startsWith('e:')).map(k => findEntry(k.slice(2))).filter(Boolean).map(f => f.e);
    title.textContent = `${sel.length} 件を選択中`;
    body.append(dl([
      ['ファイル数', es.length],
      ['合計サイズ', fmtSize(es.reduce((a, e) => a + (e.size || 0), 0))],
      ['合計の長さ', fmtDur(es.reduce((a, e) => a + (e.duration || 0), 0))],
      ['チェック済み', es.filter(e => e.selected && !e.error).length],
    ]));
    body.append(el('div', { class: 'hint', text: 'Space でチェックをまとめて切り替えできます。' }));
    return;
  }
  const key = sel[0];
  if (key.startsWith('g:')) {
    const g = findGroup(key.slice(2));
    if (!g) return;
    const t = groupTotals(g);
    title.textContent = g.is_split ? '分割された1本の撮影' : '単独の動画';
    body.append(dl([
      ['判定理由', g.reason || (g.is_split ? '撮影時刻が連続しているため、1本の撮影が分割されたものと判定' : '前後に連続する動画がありません')],
      ['確度', g.confidence ? (CONF_JA[g.confidence] || g.confidence) : null],
      ['メーカー', g.vendor ? (VENDOR_JA[g.vendor] || g.vendor) : null],
      ['ファイル数', `${g.entries.length} (結合対象 ${t.n})`],
      ['合計サイズ', fmtSize(t.size)],
      ['合計の長さ', fmtDur(t.dur)],
    ]));
    body.append(el('div', { class: 'hint', text: '結合される順番:' }));
    const ol = el('ol');
    for (const e of g.entries) ol.append(el('li', { class: (e.selected && !e.error) ? '' : 'off', text: e.name + (e.error ? '（読めません）' : '') }));
    body.append(ol);
    return;
  }
  const f = findEntry(key.slice(2));
  if (!f) return;
  const e = f.e;
  title.textContent = e.name;
  if (!e.error) {
    const img = el('img', { class: 'bigthumb', alt: '' });
    img.src = mediaUrl('/api/thumb?id=' + e.id);
    img.addEventListener('error', () => {
      const v = el('video', { class: 'bigthumb', preload: 'metadata', controls: true, muted: true, playsinline: true });
      v.src = mediaUrl('/api/file?id=' + e.id) + '#t=1';
      // 動画も描けなければ一覧と同じプレースホルダ (解像度 / 長さ)
      v.addEventListener('error', () => v.replaceWith(el('div', { class: 'bigthumb thumb' }, placeholder(e, false))));
      img.replaceWith(v);
    });
    body.append(img);
  }
  if (e.error) body.append(el('div', { class: 'err', text: '⚠ 読めません: ' + e.error }));
  if (e.warning) body.append(el('div', { class: 'warn', text: '⚠ ' + e.warning }));
  body.append(dl([
    ['パス', e.path],
    ['サイズ', e.size_text || fmtSize(e.size || 0)],
    ['長さ', e.duration_text || fmtDur(e.duration)],
    ['解像度', e.resolution_text],
    ['fps', e.fps ? e.fps.toFixed(2) : null],
    ['コーデック', e.codec || null],
    ['撮影日時', e.created_text],
    ['種類', e.kind_text],
    ['グループ', f.g.is_split ? `分割 (${f.g.entries.indexOf(e) + 1} / ${f.g.entries.length} 番目)` : '単独'],
    ['結合対象', e.error ? '不可' : (e.selected ? 'はい' : 'いいえ')],
  ]));
}

// ---------------------------------------------------------------------------
// スキャン
// ---------------------------------------------------------------------------
function setScanning(on, text) {
  state.scanning = on;
  $('#btn-scan').disabled = on || state.joining || state.quit;
  $('#btn-pick').disabled = on || state.joining || state.quit;
  const sp = $('#status-progress');
  sp.classList.toggle('hidden', !on);
  if (text !== undefined) $('#status-progress-text').textContent = text;
  updateStatus();
}
async function scan() {
  if (state.scanning || state.joining || state.quit) return;
  const folder = $('#folder').value.trim();
  if (!folder) { alert('フォルダを指定してください。'); $('#folder').focus(); return; }
  state.folder = folder;
  state.recursive = $('#opt-recursive').checked;
  state.groups = []; state.scanned = false; state.selection.clear(); state.collapsed.clear();
  thumbCache.clear();
  render();
  setScanning(true, '解析の準備中…');
  $('#status-fill').style.width = '0%';
  try {
    const { job } = await api('/api/scan', { path: folder, recursive: state.recursive });
    for (;;) {
      await sleep(250);
      const st = await api('/api/scan/' + job);
      if (st.state === 'running') {
        const pct = st.total ? Math.round(st.done * 100 / st.total) : 0;
        $('#status-fill').style.width = pct + '%';
        $('#status-progress-text').textContent = st.total ? `解析中 ${st.done}/${st.total}: ${st.current}` : '動画を探しています…';
        continue;
      }
      if (st.state === 'error') throw new Error(st.error || 'スキャンに失敗しました');
      state.groups = st.groups || [];
      state.scanJob = job;
      break;
    }
    state.scanned = true;
    if (!$('#outdir').value.trim()) { state.outDir = folder; $('#outdir').placeholder = folder; }
    await refreshRecent();
  } catch (e) {
    alert('スキャンできません: ' + e.message);
    state.scanned = false;
  } finally {
    setScanning(false);
    $('#btn-diag').disabled = !(state.scanned && state.scanJob);
    render();
  }
}
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// 判定の詳細 (診断テキスト)
async function showDiagnose() {
  if (!state.scanJob) return;
  const pre = $('#diag-text');
  pre.textContent = '読み込み中…';
  $('#diag-copied').classList.add('hidden');
  $('#diag').classList.remove('hidden');
  try {
    const { text } = await api('/api/diagnose?job=' + encodeURIComponent(state.scanJob));
    pre.textContent = text || '(情報がありません)';
  } catch (e) {
    pre.textContent = '取得できません: ' + e.message;
  }
}
async function copyDiagnose() {
  const text = $('#diag-text').textContent;
  let ok = false;
  try { await navigator.clipboard.writeText(text); ok = true; } catch (_) { /* 権限なし */ }
  if (!ok) {
    // クリップボード API が使えない場合は選択状態にしてユーザーに任せる
    const r = document.createRange(); r.selectNodeContents($('#diag-text'));
    const s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
    try { ok = document.execCommand('copy'); } catch (_) { ok = false; }
  }
  const done = $('#diag-copied');
  done.textContent = ok ? 'コピーしました' : 'コピーできません。テキストを選択して Ctrl/⌘+C を押してください';
  done.classList.remove('hidden');
}
async function refreshRecent() {
  try {
    const { recent } = await api('/api/recent', {});
    fillRecent(recent || []);
  } catch (_) { /* 無視 */ }
}
function fillRecent(list) {
  const sel = $('#recent');
  sel.replaceChildren(el('option', { value: '', text: '最近使ったフォルダ' }));
  for (const p of list) sel.append(el('option', { value: p, text: p }));
}

// ---------------------------------------------------------------------------
// ネイティブダイアログ
// ---------------------------------------------------------------------------
async function pickFolder(kind) {
  const target = kind === 'outdir' ? $('#outdir') : $('#folder');
  const btn = kind === 'outdir' ? $('#btn-outdir') : $('#btn-pick');
  btn.disabled = true;
  try {
    const initial = target.value.trim() || state.folder || null;
    const { path } = await api(kind === 'outdir' ? '/api/pick-outdir' : '/api/pick-folder', { initial });
    if (path) {
      target.value = path;
      if (kind === 'outdir') state.outDir = path;
      else await scan();
      return path;
    }
    if (path === null && !target.value) {
      target.placeholder = 'この環境ではダイアログを開けません。パスをここに直接入力してください';
      target.focus();
    }
    return null;
  } catch (e) {
    alert(e.message);
    return null;
  } finally {
    btn.disabled = state.scanning || state.joining || state.quit;
  }
}
async function pickGpx() {
  try {
    const { path } = await api('/api/pick-gpx', { initial: state.folder || null });
    if (path) { $('#gpx').value = path; state.gpx = path; }
    else if (path === null) $('#gpx').focus();
  } catch (e) { alert(e.message); }
}

// ---------------------------------------------------------------------------
// 結合
// ---------------------------------------------------------------------------
function setJoining(on) {
  state.joining = on;
  for (const id of ['btn-scan', 'btn-pick', 'btn-outdir', 'btn-quit']) $('#' + id).disabled = on || state.quit;
  updateStatus();
}
async function startJoin(gopro) {
  if (state.joining || state.scanning || state.quit) return;
  const groups = joinableGroups().map(g => ({ files: checkedEntries(g).map(e => e.path) }));
  if (!groups.length) { alert('結合対象がありません。2つ以上チェックされた分割グループが必要です。'); return; }
  let outDir = $('#outdir').value.trim() || state.outDir || state.folder;
  if (!outDir) { outDir = await pickFolder('outdir'); if (!outDir) return; }
  state.outDir = outDir;
  state.device = $('#device').value || state.device;
  state.gpx = $('#gpx').value.trim();
  state.fromVideo = $('#from-video').checked;
  state.rate = Number($('#rate').value) || 10;
  savePrefs();
  $('#gopro-pop').classList.add('hidden');
  const total = groups.reduce((a, g) => a + g.files.length, 0);
  const body = { groups, out_dir: outDir, gopro: !!gopro, device: state.device,
                 gpx: gopro ? (state.gpx || null) : null, from_video: gopro && state.fromVideo, rate: state.rate };
  setJoining(true);
  openProgress(`${groups.length} 件 (${total} ファイル) を結合しています…`);
  try {
    const { job } = await api('/api/join', body);
    await pollJoin(job, outDir);
  } catch (e) {
    progressFail(e.message);
  } finally {
    setJoining(false);
  }
}
let logShown = 0;
function openProgress(title) {
  logShown = 0;
  $('#progress-title').textContent = title;
  $('#progress-log').textContent = '';
  $('#progress-results').replaceChildren();
  $('#progress-fill').style.width = '0%';
  $('#progress-fill').classList.remove('err');
  $('#progress-text').textContent = '';
  $('#btn-open-outdir').disabled = true;
  $('#btn-progress-close').disabled = true;
  $('#progress').classList.remove('hidden');
}
function progressFail(msg) {
  $('#progress-title').textContent = '結合できませんでした';
  $('#progress-fill').classList.add('err');
  $('#progress-log').textContent += 'エラー: ' + msg + '\n';
  $('#btn-progress-close').disabled = false;
}
async function pollJoin(job, outDir) {
  const logEl = $('#progress-log');
  for (;;) {
    await sleep(400);
    const st = await api('/api/join/' + job);
    if (st.log && st.log.length > logShown) {
      const atBottom = logEl.scrollTop + logEl.clientHeight >= logEl.scrollHeight - 4;
      logEl.textContent += st.log.slice(logShown).join('\n') + '\n';
      logShown = st.log.length;
      if (atBottom) logEl.scrollTop = logEl.scrollHeight;
    }
    const pct = st.total ? Math.round(st.done * 100 / st.total) : 0;
    $('#progress-fill').style.width = pct + '%';
    $('#progress-text').textContent = `${st.done} / ${st.total} グループ`;
    renderResults(st.results || []);
    if (st.state === 'running') continue;
    const ok = (st.results || []).filter(r => !r.error).length;
    if (st.state === 'error' && !ok) {
      $('#progress-title').textContent = '結合できませんでした';
      $('#progress-fill').classList.add('err');
    } else if (st.error) {
      $('#progress-title').textContent = `結合おわり: ${ok} 本を作成 (一部失敗)`;
    } else {
      $('#progress-title').textContent = `結合おわり: ${ok} 本を作成しました`;
    }
    const open = $('#btn-open-outdir');
    open.disabled = false;
    open.onclick = () => api('/api/open', { path: outDir }).catch(e => alert(e.message));
    $('#btn-progress-close').disabled = false;
    break;
  }
}
function renderResults(results) {
  const box = $('#progress-results');
  box.replaceChildren();
  for (const r of results) {
    const row = el('div', { class: 'result' + (r.error ? ' fail' : '') });
    row.append(el('span', { class: 'rname', text: r.name || r.output }));
    if (r.error) row.append(el('span', { class: 'rmeta', text: r.error }));
    else {
      const d = r.duration_sec || 0;
      row.append(el('span', { class: 'rmeta', text: `${fmtDur(d)} / ${fmtGB(r.bytes || 0)}` + (r.gopro ? ` / ${r.gopro}` : '') + (r.shot_at ? ` / ${r.shot_at}` : '') }));
      row.append(el('span', { class: 'spacer' }));
      row.append(el('button', { class: 'btn small', type: 'button', text: '開く',
        onclick: () => api('/api/open', { path: r.output }).catch(e => alert(e.message)) }));
    }
    box.append(row);
  }
}

// ---------------------------------------------------------------------------
// 詳細ペインのリサイズ
// ---------------------------------------------------------------------------
(function setupSplitter() {
  const sp = $('#splitter'), det = $('#details');
  sp.addEventListener('mousedown', ev => {
    ev.preventDefault();
    const startX = ev.clientX, startW = det.getBoundingClientRect().width;
    sp.classList.add('active');
    const move = e => {
      const w = Math.min(window.innerWidth * 0.6, Math.max(200, Math.round(startW - (e.clientX - startX))));
      det.style.flexBasis = w + 'px'; det.style.width = w + 'px'; state.detailsWidth = w;
    };
    const up = () => { sp.classList.remove('active'); document.removeEventListener('mousemove', move); document.removeEventListener('mouseup', up); savePrefs(); };
    document.addEventListener('mousemove', move);
    document.addEventListener('mouseup', up);
  });
})();

// ---------------------------------------------------------------------------
// イベント配線 / 初期化
// ---------------------------------------------------------------------------
$('#btn-pick').addEventListener('click', () => pickFolder('folder'));
$('#btn-outdir').addEventListener('click', () => pickFolder('outdir'));
$('#btn-scan').addEventListener('click', scan);
$('#folder').addEventListener('keydown', ev => { if (ev.key === 'Enter') scan(); });
$('#outdir').addEventListener('change', () => { state.outDir = $('#outdir').value.trim(); });
$('#recent').addEventListener('change', () => {
  const p = $('#recent').value;
  if (p) { $('#folder').value = p; $('#recent').value = ''; scan(); }
});
$('#opt-solo').addEventListener('change', () => { state.showSolo = $('#opt-solo').checked; savePrefs(); render(); });
$('#opt-thumbs').addEventListener('change', () => { state.showThumbs = $('#opt-thumbs').checked; savePrefs(); render(); });
$('#opt-recursive').addEventListener('change', () => { state.recursive = $('#opt-recursive').checked; savePrefs(); });
$('#thumb-size').addEventListener('change', () => { state.thumbSize = $('#thumb-size').value; savePrefs(); render(); });
$('#btn-join').addEventListener('click', () => startJoin(false));
$('#btn-join-gopro').addEventListener('click', ev => { ev.stopPropagation(); $('#gopro-pop').classList.toggle('hidden'); });
$('#gopro-pop').addEventListener('click', ev => ev.stopPropagation());
document.addEventListener('click', () => $('#gopro-pop').classList.add('hidden'));
$('#btn-gopro-run').addEventListener('click', () => startJoin(true));
$('#btn-gpx').addEventListener('click', pickGpx);
$('#gpx').addEventListener('change', () => { state.gpx = $('#gpx').value.trim(); });
$('#device').addEventListener('change', () => { state.device = $('#device').value; savePrefs(); });
$('#from-video').addEventListener('change', () => { state.fromVideo = $('#from-video').checked; savePrefs(); });
$('#btn-progress-close').addEventListener('click', () => $('#progress').classList.add('hidden'));
$('#btn-diag').addEventListener('click', showDiagnose);
$('#btn-diag-copy').addEventListener('click', copyDiagnose);
$('#btn-diag-close').addEventListener('click', () => $('#diag').classList.add('hidden'));
document.addEventListener('keydown', ev => { if (ev.key === 'Escape') $('#diag').classList.add('hidden'); });
$('#btn-quit').addEventListener('click', async () => {
  if (state.joining) return;
  if (!confirm('結合画面を終了しますか？')) return;
  try { await api('/api/quit', {}); } catch (_) { /* 既に落ちている */ }
  state.quit = true;
  for (const b of document.querySelectorAll('button')) b.disabled = true;
  $('#bye').classList.remove('hidden');
});
window.addEventListener('resize', () => {
  const det = $('#details');
  if (window.innerWidth <= 900) { det.style.flexBasis = ''; det.style.width = ''; }
  else if (state.detailsWidth) { det.style.flexBasis = state.detailsWidth + 'px'; det.style.width = state.detailsWidth + 'px'; }
});

async function init() {
  loadPrefs();
  $('#opt-solo').checked = state.showSolo;
  $('#opt-thumbs').checked = state.showThumbs;
  $('#opt-recursive').checked = state.recursive;
  $('#thumb-size').value = state.thumbSize;
  $('#from-video').checked = state.fromVideo;
  $('#rate').value = state.rate;
  if (window.innerWidth > 900 && state.detailsWidth) {
    const det = $('#details'); det.style.flexBasis = state.detailsWidth + 'px'; det.style.width = state.detailsWidth + 'px';
  }
  render();
  let cfg;
  try {
    cfg = await api('/api/config');
  } catch (e) {
    $('#empty-text').textContent = 'サーバに接続できません (' + e.message + ')。アプリから開き直してください。';
    return;
  }
  const dev = $('#device');
  dev.replaceChildren();
  for (const d of cfg.devices || []) dev.append(el('option', { value: d, text: `${d} — ${(cfg.device_labels || {})[d] || ''}` }));
  // GUI 側で機種が指定されていればそれを優先、無ければ前回の選択を復元
  const want = (!cfg.device_explicit && (cfg.devices || []).includes(state.device))
    ? state.device : cfg.default_device;
  dev.value = (cfg.devices || []).includes(want) ? want : cfg.default_device;
  state.device = dev.value;
  fillRecent(cfg.recent || []);
  if (cfg.folder) { $('#folder').value = cfg.folder; scan(); }
  else $('#folder').focus();
}
init();
