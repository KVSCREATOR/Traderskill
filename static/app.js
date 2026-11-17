'use strict';
const $ = (s, r = document) => r.querySelector(s);
const view = $('#view');
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const inr = (v, d = 2) => v == null || isNaN(v) ? '–' : '₹' + Number(v).toLocaleString('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d });
const pct = (v, d = 2) => v == null || isNaN(v) ? '–' : (v >= 0 ? '+' : '') + v.toFixed(d) + '%';
const cls = v => v == null ? 'muted' : v >= 0 ? 'up' : 'down';
const hm = m => String(Math.floor(m / 60)).padStart(2, '0') + ':' + String(m % 60).padStart(2, '0');
const crore = v => v == null ? '–' : '₹' + (v / 1e7).toLocaleString('en-IN', { maximumFractionDigits: 0 }) + ' cr';
const ago = ts => { const s = Date.now() / 1000 - ts; return s < 3600 ? Math.max(1, Math.round(s / 60)) + 'm ago' : s < 86400 ? Math.round(s / 3600) + 'h ago' : Math.round(s / 86400) + 'd ago'; };

let S = { mode: null, clock: null, settings: null, universe: [], scanFilter: 'all', onlyNew: false, lastSymbol: null, timer: null };
try { S.lastSymbol = localStorage.getItem('ts.symbol'); } catch (e) { /* storage blocked */ }

async function api(path, body) {
  if (body) { if (!('mode' in body)) body = Object.assign({ mode: S.mode }, body); }
  else path += (path.includes('?') ? '&' : '?') + 'mode=' + encodeURIComponent(S.mode || 'intraday');
  const r = await fetch(path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : undefined);
  const j = await r.json().catch(() => ({ error: 'Bad response from server' }));
  if (!r.ok) throw new Error(j.error || 'Request failed');
  return j;
}
function toast(msg, kind = '') {
  const t = document.createElement('div');
  t.className = 'toast ' + kind; t.textContent = msg;
  $('#toasts').append(t); setTimeout(() => t.remove(), kind === 'ring' ? 15000 : kind === 'warnmsg' ? 12000 : 5000);
}
const loading = n => '<div class="stack">' + '<div class="skeleton"></div>'.repeat(n || 2) + '</div>';
const failBox = e => `<div class="err">${esc(e.message || e)}</div>`;
const head = (title, sub, right = '') => `<div class="head"><div><h1>${title}</h1><p>${sub}</p></div><div class="row">${right}</div></div>`;

/* ---------------------------------------------------------------- shell */
function setClock(c) {
  if (!c) return; S.clock = c;
  const el = $('#mkt');
  el.textContent = 'NSE ' + c.label; el.className = 'pill ' + (c.open ? 'pass' : c.label === 'Pre-open' ? 'warn' : '');
}
setInterval(() => {
  $('#ist').textContent = new Date().toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour12: false }) + ' IST';
}, 1000);

$('#theme').onclick = () => {
  const cur = document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  const next = cur === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem('ts.theme', next); } catch (e) { /* ignore */ }
};
try { const t = localStorage.getItem('ts.theme'); if (t) document.documentElement.dataset.theme = t; } catch (e) { /* ignore */ }

$('#search').onsubmit = e => {
  e.preventDefault();
  const v = $('#symbol').value.trim().toUpperCase().replace(/\.NS$/, '');
  if (v) location.hash = '#/predictor/' + encodeURIComponent(v);
};

const VIEWS = { predictor, scanner, orb: a => scanner(a, 'orb'), entry: () => skillPage('entry'), exit: () => skillPage('exit'), odds: () => skillPage('odds'),
  budget: () => skillPage('budget'), risk: () => skillPage('risk'), news, earnings, alerts, broker, deals, congress: deals, settings: settingsAll, journal: journalPage, holdings: holdingsPage };
function route() {
  clearInterval(S.timer); S.timer = null; S.nav = (S.nav || 0) + 1;
  const [, name = 'predictor', arg] = location.hash.split('/');
  const fn = VIEWS[name] || predictor;
  const on = name === 'congress' ? 'deals' : VIEWS[name] ? name : 'predictor';
  document.querySelectorAll('#nav a').forEach(a => a.classList.toggle('on', a.dataset.view === on));
  holdBar(name); refreshHeld(name);
  fn(arg ? decodeURIComponent(arg) : null);
}
addEventListener('hashchange', route);

/* pop-up alert whenever prices come from a fallback source instead of Yahoo Finance */
const sourceSeen = {};
function sourceAlert(p) {
  if (sourceSeen[p.symbol] === p.source) return;      // alert once per switch, not on every refresh
  const was = sourceSeen[p.symbol]; sourceSeen[p.symbol] = p.source;
  if (p.source === 'Yahoo Finance') { if (was) toast(`${p.symbol}: Yahoo Finance data is back. Live prices restored.`); return; }
  const why = p.source.startsWith('BSE') ? 'Yahoo Finance and NSE have no data' : 'Yahoo Finance has no data';
  toast(`⚠ Data source switched for ${p.symbol}: ${why}, so prices now come from the ${p.source}${p.asof ? ' (as of ' + p.asof + ')' : ''}. ${p.mode && p.mode !== 'intraday' ? 'Only about 75 days of history, so long-term checks are limited.' : 'Daily data only; no entry, stop, target or odds.'}`, 'warnmsg');
}

/* stock drop-down: every Nifty 250 stock */
function stockSelect(cur) {
  const opt = u => `<option value="${esc(u.symbol)}" ${u.symbol === cur ? 'selected' : ''}>${esc(u.symbol)} — ${esc(u.name)}</option>`;
  const known = S.universe.some(u => u.symbol === cur);
  return `<select class="stockpick" aria-label="Choose a stock from the Nifty 250">
    ${!cur ? '<option value="" selected disabled>Choose from 250 stocks…</option>' : !known ? `<option value="${esc(cur)}" selected>${esc(cur)}</option>` : ''}
    <optgroup label="Nifty 50">${S.universe.filter(u => u.nifty50).map(opt).join('')}</optgroup>
    <optgroup label="Other large and mid caps">${S.universe.filter(u => !u.nifty50).map(opt).join('')}</optgroup></select>`;
}
function bindStock(fn) { const s = $('.stockpick', view); if (s) s.onchange = () => s.value && fn(s.value); }
const goPredict = s => { location.hash = '#/predictor/' + encodeURIComponent(s); };

/* ---------------------------------------------------------------- predictor */
const SKILLS = [
  ['scanner', 'setup', 'scanner'], ['nse-scanner', 'setup', 'orb'], ['entry', 'entry', 'entry'], ['exit', 'exit', 'exit'],
  ['timemachine', 'odds', 'odds'], ['budget', 'size', 'budget'], ['risk', 'risk', 'risk'], ['news', 'news', 'news'],
  ['analyst', 'earnings', 'earnings'], ['big deals', 'deals', 'deals'], ['alerts', null, 'alerts'], ['broker', null, 'broker'],
];
const ICON = { pass: '✓', fail: '✕', warn: '!', na: '–' };

function gauge(score, verdict) {
  const len = Math.PI * 84, col = { qualifies: 'var(--pass)', wait: 'var(--warn)', skip: 'var(--fail)' }[verdict];
  return `<svg class="gauge" viewBox="0 0 200 118" role="img" aria-label="Setup score ${score} out of 100">
    <path d="M16 104 A84 84 0 0 1 184 104" fill="none" stroke="var(--surface-2)" stroke-width="14" stroke-linecap="round"/>
    <path d="M16 104 A84 84 0 0 1 184 104" fill="none" stroke="${col}" stroke-width="14" stroke-linecap="round" stroke-dasharray="${(len * score / 100).toFixed(1)} ${len.toFixed(1)}"/>
    <text class="big" x="100" y="94" text-anchor="middle">${score}</text>
    <text class="sub" x="100" y="113" text-anchor="middle">SETUP SCORE / 100</text></svg>`;
}

/* clickable candles: an invisible strip over each candle carries its prices */
function candleHits(bars, cx, slot, top, bottom, when) {
  return bars.map((b, i) => {
    const prev = i > 0 ? bars[i - 1].c : null;
    return `<rect class="hit" x="${(cx(i) - slot / 2).toFixed(1)}" y="${top}" width="${slot.toFixed(2)}" height="${bottom - top}" fill="transparent"
      data-ohlc="${esc(JSON.stringify({ t: when(b), o: b.o, h: b.h, l: b.l, c: b.c, v: b.v, p: prev }))}"/>`;
  }).join('');
}
function showCandle(rect, pin) {
  const card = rect.closest('.chart'); if (!card) return;
  const d = JSON.parse(rect.dataset.ohlc);
  let tip = card.querySelector('.ctip');
  if (!tip) { tip = document.createElement('div'); tip.className = 'ctip'; card.appendChild(tip); }
  const chg = d.p ? (d.c / d.p - 1) * 100 : null, col = d.c >= d.o ? 'up' : 'down';
  tip.innerHTML = `<b>${esc(d.t)}</b><span>Open</span><i>${inr(d.o)}</i><span>High</span><i>${inr(d.h)}</i><span>Low</span><i>${inr(d.l)}</i>
    <span>Close</span><i class="${col}">${inr(d.c)}</i>${chg != null ? `<span>Change</span><i class="${cls(chg)}">${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%</i>` : ''}${d.v ? `<span>Volume</span><i>${Math.round(d.v).toLocaleString('en-IN')}</i>` : ''}`;
  card.querySelectorAll('.hit.on').forEach(r => r.classList.remove('on')); rect.classList.add('on');
  const cr = card.getBoundingClientRect(), rr = rect.getBoundingClientRect();
  let left = rr.left - cr.left + rr.width + 10; tip.hidden = false;
  if (left + tip.offsetWidth > cr.width - 8) left = rr.left - cr.left - tip.offsetWidth - 10;
  tip.style.left = Math.max(8, left) + 'px'; tip.style.top = '44px';
  tip.classList.toggle('pinned', !!pin);
}
document.addEventListener('click', e => {
  const r = e.target.closest && e.target.closest('rect.hit');
  if (r) return showCandle(r, true);
  if (!e.target.closest || !e.target.closest('.ctip')) document.querySelectorAll('.ctip').forEach(t => { t.hidden = true; t.classList.remove('pinned'); });
});
document.addEventListener('mouseover', e => {
  const r = e.target.closest && e.target.closest('rect.hit');
  if (!r) return;
  const tip = r.closest('.chart')?.querySelector('.ctip');
  if (!tip || !tip.classList.contains('pinned')) showCandle(r, false);
});
document.addEventListener('mouseout', e => {
  if (!e.target.closest || !e.target.closest('rect.hit') || (e.relatedTarget && e.relatedTarget.closest && e.relatedTarget.closest('rect.hit'))) return;
  const tip = e.target.closest('.chart')?.querySelector('.ctip');
  if (tip && !tip.classList.contains('pinned')) { tip.hidden = true; e.target.classList.remove('on'); }
});

function candleChart(p) {
  const bars = p.bars || []; if (!bars.length) return '<div class="empty">No intraday bars for this session.</div>';
  const W = 960, H = 280, L = 8, R = 92, T = 12, B = 24, pl = p.plan;
  const lines = pl ? [['Target', pl.target, 'var(--pass)'], ['Entry', pl.entry, 'var(--accent)'], ['OR high', pl.or_high, 'var(--muted)'], ['Stop', pl.stop, 'var(--fail)']] : [];
  let lo = Math.min(...bars.map(b => b.l), ...lines.map(l => l[1])), hi = Math.max(...bars.map(b => b.h), ...lines.map(l => l[1]));
  const pad = (hi - lo) * 0.06 || 1; lo -= pad; hi += pad;
  const x = m => L + (m - 555) / 375 * (W - L - R), y = v => T + (hi - v) / (hi - lo) * (H - T - B), bw = (W - L - R) / 75 * 0.62;
  let s = '';
  for (let m = 555; m <= 930; m += 45) s += `<line x1="${x(m)}" x2="${x(m)}" y1="${T}" y2="${H - B}" stroke="var(--border)" stroke-width="1"/><text x="${x(m)}" y="${H - 7}" text-anchor="middle">${hm(m)}</text>`;
  s += `<rect x="${x(555)}" y="${T}" width="${x(570) - x(555)}" height="${H - T - B}" fill="var(--accent)" opacity=".07"/>`;
  for (const b of bars) {
    const c = b.c >= b.o ? 'var(--pass)' : 'var(--fail)', cx = x(b.m) + (W - L - R) / 150;
    s += `<line x1="${cx}" x2="${cx}" y1="${y(b.h)}" y2="${y(b.l)}" stroke="${c}" stroke-width="1.2"/><rect x="${cx - bw / 2}" y="${y(Math.max(b.o, b.c))}" width="${bw}" height="${Math.max(1.2, Math.abs(y(b.o) - y(b.c)))}" fill="${c}"/>`;
  }
  s += candleHits(bars, i => x(bars[i].m) + (W - L - R) / 150, (W - L - R) / 75, T, H - B, b => hm(b.m) + ' IST');
  // de-overlap labels
  const lab = lines.map(l => ({ l, yy: y(l[1]) })).sort((a, b) => a.yy - b.yy);
  for (let i = 1; i < lab.length; i++) if (lab[i].yy - lab[i - 1].yy < 13) lab[i].yy = lab[i - 1].yy + 13;
  for (const { l, yy } of lab) {
    s += `<line x1="${L}" x2="${W - R}" y1="${y(l[1])}" y2="${y(l[1])}" stroke="${l[2]}" stroke-width="1.2" stroke-dasharray="${l[0] === 'OR high' ? '2 4' : '6 4'}"/>
      <text x="${W - R + 6}" y="${yy + 3.5}" style="fill:${l[2]}">${l[0]} ${l[1].toFixed(1)}</text>`;
  }
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="5-minute candles with entry, stop and target">${s}</svg>`;
}

async function predictor(sym) {
  sym = sym || S.lastSymbol;
  if (!sym) {
    view.innerHTML = head('Purchase predictor', `${MODES[S.mode].label} mode · runs every skill on one NSE stock and rolls it into a single score.`) +
      `<div class="card empty"><p style="font-size:15px;color:var(--text);font-weight:600">Pick a stock to analyse</p>
       <p style="margin:6px 0 16px">Choose any Nifty 250 stock from the list, or start from the scanner's best setups.</p>
       <div class="row" style="justify-content:center;margin-bottom:14px">${stockSelect(null)}</div>
       <div class="row" style="justify-content:center">${['RELIANCE', 'HDFCBANK', 'INFY', 'TCS', 'SBIN'].map(s => `<a class="btn" href="#/predictor/${s}">${s}</a>`).join('')}
       <a class="btn primary" href="#/scanner">Open scanner</a></div></div>`;
    bindStock(goPredict);
    return;
  }
  S.lastSymbol = sym; try { localStorage.setItem('ts.symbol', sym); } catch (e) { /* ignore */ }
  $('#symbol').value = sym;
  const my = S.nav;
  view.innerHTML = head(esc(sym), `Running every ${MODES[S.mode].label} check on live data…`, stockSelect(sym)) + loading(3);
  bindStock(goPredict);
  const load = async quiet => {
    let p;
    try { p = await api('/api/predict?symbol=' + encodeURIComponent(sym)); }
    catch (e) { if (!quiet && my === S.nav) { view.innerHTML = head(esc(sym), 'Could not analyse this symbol', stockSelect(sym)) + failBox(e); bindStock(goPredict); } return; }
    if (my !== S.nav) return;
    setClock(p.clock); renderPredict(p); sourceAlert(p);
  };
  await load(false);
  S.timer = setInterval(() => { if (S.clock && S.clock.open && !$('#dlg').open) load(true); }, 60000);
}

function oddsCard(od, h) {
  return `<div class="card"><h2>Time machine · ${od ? od.runs.toLocaleString('en-IN') : 0} replays</h2>
        ${od ? `<div class="bar"><div class="t" style="width:${od.p_target * 100}%">${(od.p_target * 100).toFixed(0)}%</div><div class="s" style="width:${od.p_stop * 100}%">${(od.p_stop * 100).toFixed(0)}%</div><div class="n" style="width:${od.p_timeout * 100}%"></div></div>
        <div class="legend"><span><i style="background:var(--pass)"></i>Target first</span><span><i style="background:var(--fail)"></i>Stop first</span><span><i style="background:var(--na)"></i>Neither by 15:15 (${(od.p_timeout * 100).toFixed(0)}%)</span></div>
        <div class="facts" style="margin-top:14px">
          <div><span>Expected result</span><b class="${cls(od.ev_r)} mono">${od.ev_r >= 0 ? '+' : ''}${od.ev_r.toFixed(2)}R</b></div>
          <div><span>Break-even hit rate</span><b class="mono">33%</b></div>
          <div><span>Past sessions traded</span><b class="mono">${h ? h.trades + ' of ' + h.sessions : '–'}</b></div>
          <div><span>Past won / lost / timed out</span><b class="mono">${h ? `${h.wins} / ${h.losses} / ${h.timeouts}` : '–'}</b></div>
          <div><span>Past average</span><b class="${cls(h && h.avg_r)} mono">${h && h.avg_r != null ? (h.avg_r >= 0 ? '+' : '') + h.avg_r.toFixed(2) + 'R' : '–'}</b></div>
          <div><span>Bars resampled</span><b class="mono">${od.bars_sampled.toLocaleString('en-IN')}</b></div></div>
        <p class="note" style="margin-top:10px">Each replay rebuilds the rest of the day from real 5-minute bars of the last ${od.days} sessions${od.conditioned ? ', using bars that followed a breakout' : ''}. Past behaviour does not guarantee the next trade.</p>`
        : '<div class="empty">No valid plan to replay.</div>'}</div>`;
}

function renderPredict(p) {
  if (p.mode && p.mode !== 'intraday') return renderLong(p);
  const by = Object.fromEntries(p.checks.map(c => [c.id, c])), pl = p.plan, sz = p.size, od = p.odds, h = p.history;
  const verdictText = { qualifies: 'Setup qualifies', wait: 'Wait', skip: 'Skip for now' }[p.verdict];
  const sess = p.session ? new Date(p.session + 'T00:00:00').toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }) : '';
  const canTrade = pl && p.risk && p.risk.verdict === 'PASS' && by.exit.status !== 'fail';
  const strip = SKILLS.map(([n, c, page]) => `<a class="skill ${c && by[c] ? by[c].status : ''}" href="#/${page}${['news', 'earnings', 'deals'].includes(page) ? '/' + encodeURIComponent(p.symbol) : ''}" title="${esc(c && by[c] ? by[c].detail : 'Open ' + n)}">${n}</a>`).join('');

  view.innerHTML = head(`${esc(p.symbol)} <span class="muted" style="font-weight:400;font-size:15px">${esc(p.name)}</span>`,
    !p.intraday ? `End-of-day prices only${p.asof ? ' · as of ' + esc(p.asof) : ''} · source: ${esc(p.source)}` : p.live ? `Live session · quotes are free and may be delayed · refreshes every minute` : `Replay of the ${sess} session · market is ${esc(p.clock.label.toLowerCase())}`,
    `${stockSelect(p.symbol)}<button class="btn" id="again">Refresh</button>`) +
    `<div class="stack">
    ${!p.intraday ? `<div class="banner">${p.source.startsWith('NSE') ? 'Yahoo Finance has no data for this stock, so prices come from NSE\'s end-of-day file' : p.source.startsWith('BSE') ? 'Neither Yahoo Finance nor NSE has data for this stock, so prices come from BSE\'s end-of-day file' : 'No 5-minute bars are available for this stock'}. Daily chart, news and earnings are scored; entry, stop, target, odds and sizing need intraday data and are not available.</div>` : p.live ? '' : `<div class="banner">The market is not open, so entry and risk gates cannot pass. The score below replays the last session to show how the plan is built.</div>`}
    <div class="skills" aria-label="Skills used">${strip}</div>
    <div class="hero">
      <div class="card score">${gauge(p.score, p.verdict)}<div class="verdict ${p.verdict}">${verdictText}</div><p>${esc(p.why)}</p>
        <p class="note">${p.points} of ${p.max_points} points</p></div>
      <div class="card">
        <div class="quote"><span class="px">${inr(p.price)}</span><span class="${cls(p.change_pct)} mono">${pct(p.change_pct)}</span>
          <span class="muted">vs yesterday's close ${inr(p.prev_close)}</span></div>
        ${pl ? `<div class="kv">
          <div><span>${pl.trigger ? 'Entry trigger' : 'Entry'}</span><b>${inr(pl.entry)}</b></div>
          <div><span>Stop</span><b class="down">${inr(pl.stop)}</b></div>
          <div><span>Target (2R)</span><b class="up">${inr(pl.target)}</b></div>
          <div><span>Risk / share</span><b>${inr(pl.risk)}</b></div>
          <div><span>Shares</span><b>${sz ? sz.qty : '–'}</b></div>
          <div><span>Capital</span><b>${sz ? inr(sz.cost, 0) : '–'}</b></div>
          <div><span>Max loss</span><b class="down">${sz ? inr(sz.max_loss, 0) : '–'}</b></div>
          <div><span>Reward</span><b class="up">${sz ? inr(sz.reward, 0) : '–'}</b></div></div>
          <div class="row"><button class="btn primary" id="paper" ${canTrade ? '' : 'disabled'}>Paper trade this plan</button>
          <button class="btn" id="mkAlerts">Set entry, stop &amp; target alerts</button>${gttBtn(p)}
          <span class="note">${canTrade ? 'Risk check: PASS' : 'Paper order is locked until the risk check passes.'}</span></div>`
        : `<div class="empty">No opening range yet, so there is no trade plan. The range forms 09:15–09:30 IST.</div>`}
      </div>
    </div>
    <div class="card chart"><h2>${sess} session · 5-minute candles</h2>${candleChart(p)}</div>
    <div class="card"><h2>Why this score</h2><div class="checks">${p.checks.map(c => `
      <div class="check"><span class="ico ${c.status}">${ICON[c.status]}</span>
        <div><b>${esc(c.title)}</b> <span class="tag">${esc(c.skill)}</span><p>${esc(c.detail)}</p></div>
        <div class="pts">${c.max ? `${c.points}/${c.max}<i><u style="width:${c.points / c.max * 100}%"></u></i>` : 'n/a'}</div></div>`).join('')}</div></div>
    <div class="grid2">
      ${oddsCard(od, h)}
      <div class="card"><h2>Daily picture</h2>
        <div class="row" style="margin-bottom:12px">${p.setups.length ? p.setups.map(s => `<span class="tag hot" title="${esc(s.detail)}">${esc(s.label)}</span>`).join('') : '<span class="muted">No daily setup today</span>'}</div>
        <div class="facts">
          <div><span>Trend</span><b>${p.daily.trend_up ? 'Up' : 'Not up'}</b></div>
          <div><span>RSI (14)</span><b class="mono">${p.daily.rsi != null ? p.daily.rsi.toFixed(0) : '–'}</b></div>
          <div><span>20-day high</span><b class="mono">${inr(p.daily.high20)}</b></div>
          <div><span>Relative volume</span><b class="mono">${p.daily.rvol != null ? p.daily.rvol.toFixed(1) + 'x' : '–'}</b></div>
          <div><span>20-day average</span><b class="mono">${inr(p.daily.sma20)}</b></div>
          <div><span>50-day average</span><b class="mono">${inr(p.daily.sma50)}</b></div>
          <div><span>Typical day range</span><b class="mono">${inr(p.daily.atr)}</b></div>
          <div><span>Opening range</span><b class="mono">${pl ? pl.or_low.toFixed(1) + ' – ' + pl.or_high.toFixed(1) : '–'}</b></div></div>
        <div class="row" style="margin-top:14px"><a class="btn sm" href="#/earnings/${encodeURIComponent(p.symbol)}">Earnings detail</a><a class="btn sm" href="#/news/${encodeURIComponent(p.symbol)}">Headlines</a><a class="btn sm" href="#/deals/${encodeURIComponent(p.symbol)}">Big deals</a></div>
      </div>
    </div></div>`;

  $('#again').onclick = () => predictor(p.symbol);
  bindStock(goPredict);
  if (pl) {
    $('#mkAlerts').onclick = async () => {
      const a = [{ type: 'below', symbol: p.symbol, level: +pl.stop.toFixed(2), label: 'Stop' }, { type: 'above', symbol: p.symbol, level: +pl.target.toFixed(2), label: 'Target' }];
      if (pl.trigger) a.unshift({ type: 'above', symbol: p.symbol, level: +pl.entry.toFixed(2), label: 'Entry trigger' });
      try { await api('/api/alerts', { alerts: a }); toast(`${a.length} alerts set for ${p.symbol}. Keep this tab open to hear them.`); askNotify(); pollAlerts(); }
      catch (e) { toast(e.message, 'bad'); }
    };
    $('#paper').onclick = () => confirmOrder(p);
  }
}

function confirmOrder(p) {
  const pl = p.plan, sz = p.size, d = $('#dlg');
  $('#dlgBody').innerHTML = `<h3>Paper order · ${esc(p.symbol)}</h3><p class="note">Simulated bracket order in the built-in paper account. No real money moves and nothing is sent to any broker.</p>
    <div class="facts"><div><span>Buy at market, about</span><b class="mono">${inr(p.price)}</b></div>
    <div><span>Shares (resized at fill)</span><b class="mono">≈ ${sz.qty}</b></div>
    <div><span>Stop</span><b class="mono down">${inr(pl.stop)}</b></div><div><span>Target</span><b class="mono up">${inr(pl.target)}</b></div>
    <div><span>Max loss</span><b class="mono">${inr(sz.max_loss, 0)}</b></div><div><span>Auto square-off</span><b class="mono">15:15 IST</b></div></div>
    <div class="row" style="justify-content:flex-end"><button class="btn" value="cancel">Cancel</button><button class="btn primary" id="go" value="ok">Place paper order</button></div>`;
  d.showModal();
  $('#go').onclick = async e => {
    e.preventDefault(); $('#go').disabled = true;
    try { const r = await api('/api/orders', { symbol: p.symbol, confirm: true }); d.close(); toast(`Paper order filled: ${r.position.qty} ${p.symbol} at ${inr(r.position.entry)}`); location.hash = '#/broker'; }
    catch (err) { d.close(); toast(err.message, 'bad'); }
  };
}

/* ---------------------------------------------------------------- single-skill pages */
const SKILLPAGES = {
  entry: ['Entry', 'entry', 'Confirms the moment to enter: the first completed 5-minute close above the 09:15–09:30 opening range.'],
  exit: ['Exit', 'exit', 'Sets the stop and target before you enter, and refuses plans whose stop is too tight or too wide.'],
  odds: ['Time machine', 'odds', 'Replays the plan 10,000 times on this stock\'s own 5-minute bars to show the odds.'],
  budget: ['Budget', 'size', 'Sizes the trade in whole shares so it fits both your capital and your max loss.'],
  risk: ['Risk', 'risk', 'Checks the proposed order against your limits and returns PASS or BLOCK.'],
};
async function skillPage(key) {
  const [title, cid, blurb] = SKILLPAGES[key], sym = S.lastSymbol, my = S.nav;
  if (!sym) {
    view.innerHTML = head(title, blurb) + `<div class="card empty"><p style="margin-bottom:14px">Pick a stock first. Type a symbol above, or choose one:</p>
      <div class="row" style="justify-content:center">${['RELIANCE', 'HDFCBANK', 'INFY', 'TCS', 'SBIN'].map(s => `<button class="btn" data-pick="${s}">${s}</button>`).join('')}</div></div>`;
    view.querySelectorAll('[data-pick]').forEach(b => b.onclick = () => { S.lastSymbol = b.dataset.pick; try { localStorage.setItem('ts.symbol', S.lastSymbol); } catch (e) { /* ignore */ } skillPage(key); });
    return;
  }
  $('#symbol').value = sym;
  const h1 = `${title} <span class="muted" style="font-weight:400;font-size:15px">${esc(sym)}</span>`;
  view.innerHTML = head(h1, blurb) + loading(2);
  let p, err; try { p = await api('/api/predict?symbol=' + encodeURIComponent(sym)); } catch (e) { err = e; }
  if (my !== S.nav) return;
  if (err) { view.innerHTML = head(h1, blurb) + failBox(err); return; }
  setClock(p.clock); sourceAlert(p);
  if (p.mode !== 'intraday') return skillLong(key, p, h1);
  const c = p.checks.find(x => x.id === cid), pl = p.plan, sz = p.size, st = p.settings;
  const fact = (k, v, k2 = '') => `<div><span>${k}</span><b class="mono ${k2}">${v}</b></div>`;
  const chart = `<div class="card chart"><h2>${esc(p.session || '')} session · 5-minute candles</h2>${candleChart(p)}</div>`;
  const noPlan = '<div class="card empty">No opening range yet, so there is no trade plan. The range forms 09:15–09:30 IST.</div>';
  let body = noPlan;
  if (key === 'odds') body = oddsCard(p.odds, p.history);
  else if (pl && key === 'entry') {
    const dist = (p.price - pl.entry) / pl.risk;
    body = `<div class="card"><h2>Entry details</h2><div class="facts">
      ${fact('Opening range low', inr(pl.or_low))}${fact('Opening range high', inr(pl.or_high))}
      ${fact('Status', pl.trigger ? 'Waiting for breakout' : 'Confirmed at ' + pl.entry_time)}${fact(pl.trigger ? 'Entry trigger' : 'Entry price', inr(pl.entry))}
      ${fact('Price now', inr(p.price))}${fact('Distance from entry', (dist >= 0 ? '+' : '') + dist.toFixed(1) + 'R', cls(dist))}
      ${fact('Entries allowed', esc(st.entry_start) + ' – ' + esc(st.entry_end) + ' IST')}${fact('Session', p.live ? 'Live' : 'Replay · market ' + esc(p.clock.label.toLowerCase()))}</div>
      <div class="row" style="margin-top:12px">${gttBtn(p)}<span class="note">Market closed? Set a GTT for the next session; it buys only inside your entry window.</span></div></div>${chart}`;
  } else if (pl && key === 'exit') {
    body = `<div class="card"><h2>Exit plan</h2><div class="facts">
      ${fact('Stop (range midpoint)', inr(pl.stop), 'down')}${fact('Target (2R)', inr(pl.target), 'up')}
      ${fact('Risk per share', inr(pl.risk))}${fact('Reward per share', inr(pl.risk * 2))}
      ${fact('Risk as % of entry', pl.risk_pct.toFixed(2) + '%')}${fact('Allowed risk band', '0.15% – 2.50%')}
      ${fact('Typical day range', inr(p.daily.atr))}${fact('Forced square-off', '15:15 IST')}</div></div>${chart}`;
  } else if (pl && sz && key === 'budget') {
    body = `<div class="card"><h2>Position size</h2><div class="kv" style="margin-top:0">
      <div><span>Shares</span><b>${sz.qty}</b></div><div><span>Capital used</span><b>${inr(sz.cost, 0)}</b></div>
      <div><span>Max loss</span><b class="down">${inr(sz.max_loss, 0)}</b></div><div><span>Reward at target</span><b class="up">${inr(sz.reward, 0)}</b></div></div>
      <div class="facts">${fact('Entry', inr(pl.entry))}${fact('Stop', inr(pl.stop))}
      ${fact('Your capital per trade', inr(st.budget, 0))}${fact('Your max loss per trade', inr(st.max_loss, 0))}
      ${fact('Shares your capital allows', Math.floor(st.budget / pl.entry))}${fact('Shares your max loss allows', Math.floor(st.max_loss / pl.risk))}
      ${fact('Size is limited by', esc(sz.limited_by))}${fact('Capital left unused', inr(Math.max(0, st.budget - sz.cost), 0))}</div>
      <div class="row" style="margin-top:14px"><a class="btn sm" href="#/settings">Change my limits</a></div></div>`;
  } else if (p.risk && key === 'risk') {
    body = `<div class="card"><div class="row" style="justify-content:space-between;margin-bottom:12px"><h2 style="margin:0">Limit checks</h2>
      <span class="pill ${p.risk.verdict === 'PASS' ? 'pass' : 'fail'}">${p.risk.verdict}</span></div><div class="checks">
      ${p.risk.checks.map(r => `<div class="check"><span class="ico ${r.ok ? 'pass' : 'fail'}">${r.ok ? '✓' : '✕'}</span><div><b>${esc(r.name)}</b><p>${esc(r.detail.replace(/Rs /g, '₹'))}</p></div><div class="pts">${r.ok ? 'ok' : 'block'}</div></div>`).join('')}</div>
      <div class="row" style="margin-top:14px"><a class="btn sm" href="#/settings">Change my limits</a></div></div>`;
  }
  view.innerHTML = head(h1, blurb, `${stockSelect(sym)}<a class="btn" href="#/predictor/${encodeURIComponent(sym)}">Full prediction</a>`) + `<div class="stack">
    <div class="card"><div class="checks"><div class="check"><span class="ico ${c.status}">${ICON[c.status]}</span>
      <div><b>${esc(c.title)}</b> <span class="tag">${esc(c.skill)}</span><p>${esc(c.detail)}</p></div>
      <div class="pts">${c.max ? `${c.points}/${c.max}<i><u style="width:${c.points / c.max * 100}%"></u></i>` : 'n/a'}</div></div></div></div>
    ${body}</div>`;
  bindStock(s => { S.lastSymbol = s; try { localStorage.setItem('ts.symbol', s); } catch (e) { /* ignore */ } skillPage(key); });
}

/* ---------------------------------------------------------------- scanner */
async function scanner(_arg, mode) {
  if (isLong()) return scannerLong(_arg, mode);
  const title = mode === 'orb' ? 'ORB scanner' : 'Scanner';
  const my = S.nav;
  const draw = d => {
    setClock(d.clock);
    const alt = d.rows.filter(r => r.source !== 'Yahoo');
    if (alt.length && S.scanAlerted !== d.scanned_at) {
      S.scanAlerted = d.scanned_at;
      toast(`⚠ Data source switched for ${alt.length} stock${alt.length === 1 ? '' : 's'}: Yahoo Finance had no data, so end-of-day prices from ${[...new Set(alt.map(r => r.source.split(' ')[0]))].join(' and ')} are used for ${alt.slice(0, 6).map(r => r.symbol).join(', ')}${alt.length > 6 ? ' and others' : ''}.`, 'warnmsg');
    }
    const f = mode === 'orb' ? 'orb' : S.scanFilter, ord = r => r.orb.state === 'waiting' ? 1 : ({ open: 0, target: 2, stop: 3 })[r.orb.outcome];
    const rows = mode === 'orb' ? d.rows.filter(r => r.orb.state !== 'none').sort((x, y) => ord(x) - ord(y) || y.rank - x.rank)
      : d.rows.filter(r => f === 'all' || (f === 'mine' ? heldSyms().includes(r.symbol) : f === 'n50' ? r.nifty50 : f === 'orb' ? r.orb.state === 'confirmed' : r.setups.some(s => s.id === f)));
    const chips = [['all', 'All 250'], ...(heldSyms().length ? [['mine', '◉ My holdings']] : []), ['n50', 'Nifty 50 only'], ['breakout', '20-day breakout'], ['flag', 'Bull flag'], ['bounce', 'Oversold bounce'], ['orb', 'Opening-range breakout']]
      .map(([k, l]) => `<button class="chip ${f === k ? 'on' : ''}" data-f="${k}">${l}</button>`).join('');
    const orb = r => r.orb.state === 'confirmed'
      ? `<span class="pill ${r.orb.outcome === 'stop' ? 'fail' : 'pass'}">${r.orb.time}${r.orb.outcome === 'target' ? ' · target hit' : r.orb.outcome === 'stop' ? ' · stopped' : ''}</span>`
      : r.orb.state === 'waiting' ? '<span class="pill">waiting</span>' : '<span class="muted">–</span>';
    view.innerHTML = head(title, `${mode === 'orb' ? '15-minute opening-range breakouts · live trades first · ' : ''}${d.universe} · ${rows.length} of ${d.rows.length} stocks shown · scanned ${d.scanned_at} IST · ${d.rows[0] && d.rows[0].live ? 'live session' : 'last session'}`,
      `<button class="btn" id="rescan">Rescan</button>`) +
      `<div class="stack">${mode === 'orb' ? '' : `<div class="chips">${chips}</div>`}<div class="card"><div class="row tablebar" style="margin-top:0"><input type="search" data-tfind placeholder="Search stock, name or sector" style="width:240px"><button class="btn sm" data-sortreset>Default order</button><span class="note" style="margin:0">Click a column heading to sort.</span></div><div class="tablewrap"><table>
      <thead><tr><th>Stock</th><th class="num">Price</th><th class="num">Day</th><th>Daily setups</th><th>15-min ORB</th><th class="num">RSI</th><th class="num">Rel vol</th><th>Trend</th><th class="num">Rank</th></tr></thead>
      <tbody>${rows.map(r => `<tr class="click" data-s="${esc(r.symbol)}" tabindex="0">
        <td class="sym"><b>${esc(r.symbol)}</b><small>${esc(r.name)}${r.source !== 'Yahoo' ? ' · ' + esc(r.source) : ''}</small></td><td class="num">${inr(r.price)}</td><td class="num ${cls(r.change_pct)}">${pct(r.change_pct)}</td>
        <td><div class="row" style="gap:4px">${r.setups.map(s => `<span class="tag ${s.id === 'near' ? '' : 'hot'}" title="${esc(s.detail)}">${esc(s.label)}</span>`).join('') || '<span class="muted">–</span>'}</div></td>
        <td>${orb(r)}</td><td class="num">${r.rsi != null ? r.rsi.toFixed(0) : '–'}</td><td class="num">${r.rvol != null ? r.rvol.toFixed(1) + 'x' : '–'}</td>
        <td>${r.trend_up ? '<span class="up">Up</span>' : '<span class="muted">–</span>'}</td>
        <td class="num"><span class="rank ${r.rank >= 60 ? 'hi' : r.rank >= 30 ? 'mid' : ''}">${r.rank}</span></td></tr>`).join('') || `<tr><td colspan="9" class="empty">No stocks match this filter right now.</td></tr>`}</tbody></table></div></div>
      ${d.failed.length ? `<p class="note">No data for: ${d.failed.map(x => esc(x.symbol)).join(', ')}. Edit nifty250.json if the index has changed.</p>` : ''}
      <p class="note">Rank is a quick sort of chart setups only. Click a row for the full 100-point score with entry, exits, odds, sizing and risk.</p></div>`;
    view.querySelectorAll('.chip').forEach(c => c.onclick = () => { S.scanFilter = c.dataset.f; draw(d); });
    view.querySelectorAll('tr.click').forEach(tr => { const go = () => location.hash = '#/predictor/' + encodeURIComponent(tr.dataset.s); tr.onclick = go; tr.onkeydown = e => e.key === 'Enter' && go(); });
    $('#rescan').onclick = () => run(true);
  };
  const run = async fresh => {
    view.innerHTML = head(title, `Scanning ${S.universe.length || 250} stocks for daily setups and opening-range breakouts. The first scan takes up to a minute…`) + loading(3);
    let d, err; try { d = await api('/api/scan' + (fresh ? '?refresh=1' : '')); } catch (e) { err = e; }
    if (my !== S.nav) return;
    if (err) view.innerHTML = head(title, 'Scan failed') + failBox(err); else draw(d);
  };
  run(false);
}

/* ---------------------------------------------------------------- news */
async function news(sym) {
  view.innerHTML = head('News', 'Fetching headlines…') + loading(2);
  const my = S.nav;
  const mine = !sym && S.newsHoldings && heldSyms().length;
  let d, err; try { d = await api('/api/news' + (sym ? '?symbol=' + encodeURIComponent(sym) : mine ? '?holdings=1' : '')); } catch (e) { err = e; }
  if (my !== S.nav) return;
  if (err) { view.innerHTML = head('News', 'Could not load headlines') + failBox(err); return; }
  const draw = () => {
    const ids = d.watch.flatMap(w => w.items.filter(i => i.new).map(i => i.id));
    view.innerHTML = head('News', sym ? `Headlines for ${esc(sym)} from the last 3 days` : (mine ? 'Your Zerodha holdings' : 'Your watchlist') + ', with each move from yesterday\'s close',
      `${!sym && heldSyms().length ? `<div class="chips" style="margin:0"><button class="chip ${mine ? '' : 'on'}" data-nw="0">Watchlist</button><button class="chip ${mine ? 'on' : ''}" data-nw="1">◉ My holdings</button></div>` : ''}<label class="row" style="flex-direction:row;font-weight:500"><input type="checkbox" id="onlyNew" ${S.onlyNew ? 'checked' : ''}> Only new</label>
       <button class="btn" id="markRead" ${ids.length ? '' : 'disabled'}>Mark ${ids.length} as read</button>`) +
      `<div class="stack">${d.watch.map(w => {
        const items = w.items.filter(i => !S.onlyNew || i.new);
        return `<div class="card"><div class="row" style="justify-content:space-between;margin-bottom:6px">
          <div class="row"><a href="#/predictor/${encodeURIComponent(w.symbol)}"><b class="mono">${esc(w.symbol)}</b></a><span class="muted">${esc(w.name)}</span></div>
          <div class="row"><span class="mono">${inr(w.price)}</span><span class="mono ${cls(w.change_pct)}">${pct(w.change_pct)}</span></div></div>
          ${w.error ? `<p class="muted">${esc(w.error)}</p>` : items.length ? items.map(i => `<div class="newsitem"><span class="dot ${i.new ? '' : 'old'}" title="${i.new ? 'New' : 'Seen'}"></span>
            <div style="flex:1;min-width:0"><a href="${esc(i.link)}" target="_blank" rel="noopener noreferrer">${esc(i.title)}</a>
            ${i.caution.length ? `<span class="pill warn" style="margin-left:6px">${esc(i.caution.join(', '))}</span>` : ''}
            <div><small>${esc(i.source)} · ${ago(i.ts)}</small></div></div></div>`).join('')
          : `<p class="muted">${S.onlyNew ? 'Nothing new since you last marked as read.' : 'No headlines in the last 3 days.'}</p>`}</div>`;
      }).join('')}
      ${sym ? '' : '<p class="note">Change the watchlist under Limits. Caution tags are a simple keyword match, not a judgement of the story.</p>'}</div>`;
    $('#onlyNew').onchange = e => { S.onlyNew = e.target.checked; draw(); };
    view.querySelectorAll('[data-nw]').forEach(b => b.onclick = () => { S.newsHoldings = b.dataset.nw === '1'; news(); });
    $('#markRead').onclick = async () => { await api('/api/news/seen', { ids }); d.watch.forEach(w => w.items.forEach(i => i.new = false)); draw(); };
  };
  draw();
}

/* ---------------------------------------------------------------- earnings */
async function earnings(sym) {
  sym = sym || S.lastSymbol || 'RELIANCE';
  view.innerHTML = head('Earnings', `Latest reported quarters for ${esc(sym)}`) + loading(2);
  const my = S.nav;
  let d, err; try { d = await api('/api/earnings?symbol=' + encodeURIComponent(sym)); } catch (e) { err = e; }
  if (my !== S.nav) return;
  if (err) { view.innerHTML = head('Earnings', esc(sym)) + failBox(err) + pick(); bind(); return; }
  const c = d.compare, g = (v, unit = '%') => v == null ? '–' : `<span class="${cls(v)}">${v >= 0 ? '+' : ''}${v.toFixed(1)}${unit}</span>`;
  function pick() { return `<form class="row" id="epick" style="margin-top:14px"><input id="esym" placeholder="Symbol" list="symbols" style="text-transform:uppercase;width:170px"><button class="btn">Load</button></form>`; }
  function bind() { $('#epick').onsubmit = e => { e.preventDefault(); const v = $('#esym').value.trim().toUpperCase(); if (v) location.hash = '#/earnings/' + encodeURIComponent(v); }; }
  // green = up / profit, red = down / loss
  const tile = (label, v, unit = '%') => `<div class="${v == null ? '' : v >= 0 ? 'tile-up' : 'tile-down'}"><span>${label}</span><b>${v == null ? '–'
    : `<span class="arrow">${v >= 0 ? '▲' : '▼'}</span>${v >= 0 ? '+' : ''}${v.toFixed(1)}${unit}`}</b></div>`;
  const qs = d.quarters;   // oldest first
  const cell = (q, i, key, fmt, isMoney) => {
    const v = q[key], p = i > 0 ? qs[i - 1][key] : null;
    if (v == null) return '<td class="num">–</td>';
    let c = '', chg = '';
    if (isMoney && v < 0) c = 'cell-down';                                  // a loss is always red
    if (p != null) {
      const diff = key === 'net_margin' ? v - p : (p !== 0 ? (v - p) / Math.abs(p) * 100 : null);
      if (diff != null) {
        if (!c) c = diff >= 0 ? 'cell-up' : 'cell-down';
        chg = `<small class="chg">${diff >= 0 ? '▲ +' : '▼ '}${diff.toFixed(1)}${key === 'net_margin' ? ' pts' : '%'}</small>`;
      }
    }
    return `<td class="num ${c}">${fmt(v)}${chg}</td>`;
  };
  const pctf = v => v.toFixed(1) + '%', epsf = v => '₹' + v.toFixed(2);
  const bars = (title, key, fmt) => {
    const pts = qs.map((q, i) => ({ d: q.date, v: q[key], p: i > 0 ? qs[i - 1][key] : null })).filter(x => x.v != null);
    if (pts.length < 2) return '';
    const W = 420, H = 190, L = 8, R = 8, T = 18, B = 26;
    const hi = Math.max(0, ...pts.map(x => x.v)), lo = Math.min(0, ...pts.map(x => x.v)), span = (hi - lo) || 1;
    const y = v => T + (hi - v) / span * (H - T - B), bw = (W - L - R) / pts.length;
    let s = `<line x1="${L}" x2="${W - R}" y1="${y(0)}" y2="${y(0)}" stroke="var(--border)"/>`;
    pts.forEach((x, i) => {
      const col = x.v < 0 || (x.p != null && x.v < x.p) ? 'var(--fail)' : x.p == null ? 'var(--na)' : 'var(--pass)';
      const x0 = L + i * bw + bw * 0.18, w = bw * 0.64, top = Math.min(y(x.v), y(0)), h = Math.max(2, Math.abs(y(x.v) - y(0)));
      s += `<rect x="${x0}" y="${top}" width="${w}" height="${h}" rx="3" fill="${col}"><title>${x.d}: ${fmt(x.v)}</title></rect>`;
      s += `<text x="${x0 + w / 2}" y="${x.v >= 0 ? top - 4 : top + h + 12}" text-anchor="middle">${fmt(x.v).replace(' cr', '')}</text>`;
      s += `<text x="${x0 + w / 2}" y="${H - 8}" text-anchor="middle">${x.d.slice(2, 7)}</text>`;
    });
    return `<div class="card"><h2>${title}</h2><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${title} by quarter">${s}</svg></div>`;
  };
  view.innerHTML = head(`Earnings <span class="muted" style="font-weight:400;font-size:15px">${esc(sym)}</span>`, 'Reported numbers only. No stock call.', pick()) +
    `<div class="stack">${c ? `<div class="kv" style="margin:0">
      ${tile('Revenue ' + esc(c.basis), c.revenue)}${tile('Net profit ' + esc(c.basis), c.net_income)}
      ${tile('EPS ' + esc(c.basis), c.eps)}${tile('Net margin change', c.margin_delta, ' pts')}</div>` : ''}
    <div class="echarts">${bars('Revenue', 'revenue', crore)}${bars('Net profit', 'net_income', crore)}${bars('Net margin', 'net_margin', pctf)}${bars('Diluted EPS', 'eps', epsf)}</div>
    <p class="legend muted" style="margin:0;font-size:12px"><span style="color:var(--pass)">■</span> up on the previous quarter &nbsp; <span style="color:var(--fail)">■</span> down, or a loss &nbsp; <span style="color:var(--na)">■</span> first quarter shown</p>
    <div class="card"><div class="tablewrap" style="margin-top:-18px"><table><thead><tr><th>Quarter ending</th><th class="num">Revenue</th><th class="num">Operating profit</th><th class="num">Net profit</th><th class="num">Net margin</th><th class="num">Diluted EPS</th></tr></thead>
    <tbody>${qs.map((q, i) => `<tr><td class="mono">${q.date}</td>${cell(q, i, 'revenue', crore, true)}${cell(q, i, 'op_income', crore, true)}${cell(q, i, 'net_income', crore, true)}
      ${cell(q, i, 'net_margin', pctf, true)}${cell(q, i, 'eps', epsf, true)}</tr>`).reverse().join('')}</tbody></table></div></div>
    <p class="note">Source: ${esc(d.source)}. Comparison is ${c ? esc(c.basis) + ' against the quarter ending ' + c.vs : 'unavailable'}; year-on-year is used when the year-ago quarter is published, otherwise the nearest earlier quarter.</p></div>`;
  bind();
}

/* ---------------------------------------------------------------- alerts */
const ATYPE = { above: 'Price at or above', below: 'Price at or below', pct_up: 'Up % from yesterday\'s close', pct_down: 'Down % from yesterday\'s close' };
const CLOCKS = { open: 'Market open · 09:15', preclose: '15 min to close · 15:15', close: 'Market close · 15:30' };
function askNotify() { try { if ('Notification' in window && Notification.permission === 'default') Notification.requestPermission(); } catch (e) { /* ignore */ } }
function beep() {
  try {
    const ac = new (window.AudioContext || window.webkitAudioContext)();
    [0, 0.22, 0.44].forEach(t => { const o = ac.createOscillator(), g = ac.createGain(); o.frequency.value = 880; o.connect(g); g.connect(ac.destination); g.gain.setValueAtTime(0.18, ac.currentTime + t); g.gain.exponentialRampToValueAtTime(0.001, ac.currentTime + t + 0.18); o.start(ac.currentTime + t); o.stop(ac.currentTime + t + 0.2); });
  } catch (e) { /* audio blocked */ }
}
async function pollAlerts() {
  let d; try { d = await api('/api/alerts'); } catch (e) { return null; }
  setClock(d.clock);
  for (const a of d.fired) {
    toast('🔔 ' + a.message, 'ring'); beep();
    try { if ('Notification' in window && Notification.permission === 'granted') new Notification('Tradeskill alert', { body: a.message }); } catch (e) { /* ignore */ }
  }
  const armed = d.alerts.filter(a => !a.fired_at).length, b = $('#alertBadge');
  b.hidden = !armed; b.textContent = armed;
  if (location.hash.startsWith('#/alerts') && d.fired.length) drawAlerts(d);
  return d;
}
setInterval(pollAlerts, 30000);

function drawAlerts(d) {
  const desc = a => a.type === 'clock' ? CLOCKS[a.level] : `${ATYPE[a.type]} ${a.type.startsWith('pct') ? a.level + '%' : inr(a.level)}`;
  view.innerHTML = head('Alerts', 'Each alert rings once. Checked every 30 seconds on delayed quotes while this tab is open.') +
    `<div class="stack"><div class="card"><h2>New alert</h2><form class="grid" id="af">
      <label>Symbol<input name="symbol" list="symbols" required style="text-transform:uppercase" value="${esc(S.lastSymbol || '')}"></label>
      <label>Condition<select name="type">${Object.entries(ATYPE).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select></label>
      <label>Level (₹ or %)<input name="level" type="number" step="0.05" min="0.05" required></label>
      <button class="btn primary">Add alert</button></form>
      <div class="row" style="margin-top:14px"><span class="note">Market clock:</span>${Object.entries(CLOCKS).map(([k, v]) => `<button class="btn sm" data-clock="${k}">${v}</button>`).join('')}</div></div>
    <div class="card">${d.alerts.length ? `<div class="tablewrap" style="margin-top:-18px"><table><thead><tr><th>Alert</th><th>Condition</th><th class="num">Last price</th><th>Status</th><th></th></tr></thead><tbody>
      ${d.alerts.slice().reverse().map(a => `<tr><td class="sym"><b>${esc(a.symbol || 'NSE clock')}</b>${a.label ? `<small>${esc(a.label)}</small>` : ''}</td><td>${esc(desc(a))}</td>
        <td class="num">${a.last ? inr(a.last) : '–'}</td><td>${a.fired_at ? `<span class="pill warn">Rang ${esc(a.fired_at.slice(5, 16))}</span>` : '<span class="pill pass">Armed</span>'}</td>
        <td class="num">${a.fired_at ? `<button class="btn sm" data-rearm="${a.id}">Re-arm</button> ` : ''}<button class="btn sm danger" data-del="${a.id}">Delete</button></td></tr>`).join('')}</tbody></table></div>`
      : '<div class="empty">No alerts yet. Add one above, or use “Set entry, stop &amp; target alerts” on a prediction.</div>'}</div></div>`;
  const post = async (path, body) => { try { await api(path, body); drawAlerts(await pollAlerts()); } catch (e) { toast(e.message, 'bad'); } };
  $('#af').onsubmit = e => { e.preventDefault(); askNotify(); const f = new FormData(e.target); post('/api/alerts', { alerts: [{ symbol: f.get('symbol'), type: f.get('type'), level: +f.get('level') }] }); };
  view.querySelectorAll('[data-clock]').forEach(b => b.onclick = () => { askNotify(); post('/api/alerts', { alerts: [{ type: 'clock', level: b.dataset.clock }] }); });
  view.querySelectorAll('[data-del]').forEach(b => b.onclick = () => post('/api/alerts/delete', { id: b.dataset.del }));
  view.querySelectorAll('[data-rearm]').forEach(b => b.onclick = () => post('/api/alerts/rearm', { id: b.dataset.rearm }));
}
async function alerts() {
  view.innerHTML = head('Alerts', 'Loading…') + loading(2);
  const my = S.nav, d = await pollAlerts();
  if (my !== S.nav) return;
  if (d) drawAlerts(d); else view.innerHTML = head('Alerts', '') + failBox(new Error('Could not load alerts. Is the server running?'));
}

/* ---------------------------------------------------------------- broker */
async function broker() {
  if (isLong()) return brokerLong();
  const my = S.nav;
  view.innerHTML = head('Paper broker', 'Loading the paper account…') + loading(2);
  const load = async () => {
    let d, err; try { d = await api('/api/portfolio'); } catch (e) { err = e; }
    if (my !== S.nav) return;
    if (err) { view.innerHTML = head('Paper broker', '') + failBox(err); return; }
    setClock(d.clock);
    view.innerHTML = head('Paper broker', 'Simulated account. Orders come only from a prediction with a risk PASS and your confirmation.', '<span class="pill warn">Paper only · no real orders</span>') +
      `<div class="stack"><div class="kv" style="margin:0">
        <div><span>Equity</span><b>${inr(d.equity, 0)}</b></div><div><span>Cash</span><b>${inr(d.cash, 0)}</b></div>
        <div><span>Today</span><b class="${cls(d.day_pnl)}">${d.day_pnl >= 0 ? '+' : '−'}${inr(Math.abs(d.day_pnl), 0)}</b></div>
        <div><span>Since start</span><b class="${cls(d.total_pnl)}">${d.total_pnl >= 0 ? '+' : '−'}${inr(Math.abs(d.total_pnl), 0)}</b></div></div>
      <div class="card"><h2>Open positions</h2>${d.positions.length ? `<div class="tablewrap"><table><thead><tr><th>Stock</th><th class="num">Qty</th><th class="num">Entry</th><th class="num">Last</th><th class="num">Stop</th><th class="num">Target</th><th class="num">P&amp;L</th><th></th></tr></thead><tbody>
        ${d.positions.map(p => `<tr><td class="sym"><b>${esc(p.symbol)}</b><small>opened ${esc(p.opened_at.slice(11, 16))}</small></td><td class="num">${p.qty}</td><td class="num">${inr(p.entry)}</td><td class="num">${inr(p.last)}</td>
          <td class="num down">${inr(p.stop)}</td><td class="num up">${inr(p.target)}</td><td class="num ${cls(p.pnl)}">${p.pnl >= 0 ? '+' : '−'}${inr(Math.abs(p.pnl), 0)}</td>
          <td class="num"><button class="btn sm" data-close="${p.id}">Close now</button></td></tr>`).join('')}</tbody></table></div>`
        : '<div class="empty">No open positions. Stops, targets and the 15:15 square-off are worked automatically while this page is open.</div>'}</div>
      <div class="card"><h2>Closed trades</h2>${d.trades.length ? `<div class="tablewrap"><table><thead><tr><th>Stock</th><th>Closed</th><th class="num">Qty</th><th class="num">Entry</th><th class="num">Exit</th><th>Exit reason</th><th class="num">Result</th><th class="num">P&amp;L</th></tr></thead><tbody>
        ${d.trades.map(t => `<tr><td class="mono"><b>${esc(t.symbol)}</b></td><td class="mono">${esc(t.closed_at.slice(5, 16))}</td><td class="num">${t.qty}</td><td class="num">${inr(t.entry)}</td><td class="num">${inr(t.exit)}</td>
          <td><span class="pill ${t.reason === 'target' ? 'pass' : t.reason === 'stop' ? 'fail' : ''}">${esc(t.reason)}</span></td><td class="num ${cls(t.r)}">${t.r >= 0 ? '+' : ''}${t.r.toFixed(2)}R</td>
          <td class="num ${cls(t.pnl)}">${t.pnl >= 0 ? '+' : '−'}${inr(Math.abs(t.pnl), 0)}</td></tr>`).join('')}</tbody></table></div>` : '<div class="empty">No closed trades yet.</div>'}</div>
      <p class="note">This portal has no connection to a real brokerage. To take a trade for real, place it yourself in your own broker app.</p></div>`;
    view.querySelectorAll('[data-close]').forEach(b => b.onclick = async () => { try { await api('/api/orders/close', { id: b.dataset.close }); toast('Position closed at market.'); load(); } catch (e) { toast(e.message, 'bad'); } });
    if (!$('#gttBox')) view.querySelector('.stack')?.insertAdjacentHTML('beforeend', '<div id="gttBox"></div>');
    gttCard($('#gttBox'));
  };
  await load();
  S.timer = setInterval(load, 30000);
}

/* ---------------------------------------------------------------- big deals */
async function deals(sym) {
  const my = S.nav;
  view.innerHTML = head('Big deals', 'Loading NSE bulk and block deals…') + loading(2);
  let d, err; try { d = await api('/api/deals' + (sym ? '?symbol=' + encodeURIComponent(sym) : '')); } catch (e) { err = e; }
  if (my !== S.nav) return;
  if (err) { view.innerHTML = head('Big deals', '') + failBox(err); return; }
  const day = s => new Date(s + 'T00:00:00').toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });
  const cr = v => '₹' + (v / 1e7).toLocaleString('en-IN', { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + ' cr';
  const draw = () => {
    const f = S.dealFilter || 'all';
    const rows = d.rows.filter(r => f === 'all' || (f === 'nifty' ? r.nifty : f === 'buy' ? r.side === 'BUY' : f === 'sell' ? r.side === 'SELL' : r.kind === 'block'));
    const chips = [['all', 'All'], ['nifty', 'Nifty 50 only'], ['buy', 'Buys'], ['sell', 'Sells'], ['block', 'Block deals']]
      .map(([k, l]) => `<button class="chip ${f === k ? 'on' : ''}" data-f="${k}">${l}</button>`).join('');
    const span = d.from ? (d.from === d.to ? day(d.to) : day(d.from) + ' to ' + day(d.to)) : 'no data yet';
    view.innerHTML = head(sym ? `Big deals <span class="muted" style="font-weight:400;font-size:15px">${esc(sym)}</span>` : 'Big deals',
      `Named large buyers and sellers on NSE · ${span} · ${d.days_stored} trading day${d.days_stored === 1 ? '' : 's'} stored`,
      `<form class="row" id="df"><input id="dsym" list="symbols" placeholder="Filter by symbol" value="${esc(sym || '')}" style="width:170px;text-transform:uppercase"><button class="btn">Filter</button>${sym ? '<a class="btn" href="#/deals">Show all</a>' : ''}</form>`) +
      `<div class="stack"><div class="chips">${chips}</div>
      ${d.failed.length ? `<div class="banner">Could not refresh the ${esc(d.failed.join(' and '))} deal file from NSE just now; showing what is stored.</div>` : ''}
      <div class="card"><div class="tablewrap" style="margin-top:-18px"><table>
        <thead><tr><th>Date</th><th>Stock</th><th>Buyer / seller</th><th>Side</th><th class="num">Quantity</th><th class="num">Price</th><th class="num">Value</th><th>Type</th></tr></thead>
        <tbody>${rows.map(r => `<tr class="click" data-s="${esc(r.symbol)}" tabindex="0"><td class="mono">${day(r.date)}</td>
          <td class="sym"><b>${esc(r.symbol)}</b><small>${esc(r.name)}</small></td><td>${esc(r.client)}</td>
          <td><span class="pill ${r.side === 'BUY' ? 'pass' : 'fail'}">${r.side === 'BUY' ? 'Buy' : 'Sell'}</span></td>
          <td class="num">${r.qty.toLocaleString('en-IN')}</td><td class="num">${inr(r.price)}</td><td class="num">${cr(r.value)}</td>
          <td><span class="tag">${esc(r.kind)}</span></td></tr>`).join('')
          || `<tr><td colspan="8" class="empty">${sym ? 'No bulk or block deals stored for ' + esc(sym) + '.' : 'No deals match this filter.'}</td></tr>`}</tbody></table></div></div>
      <p class="note">Source: ${esc(d.source)}. A bulk deal is one client trading more than 0.5% of a company's shares in a day; a block deal is a single large negotiated trade. NSE's free file covers only the latest trading day, so history builds up here each day you open the portal. Deals in a stock add up to 5 points to its score when buying clearly outweighs selling. Click a row to predict that stock.</p>
      <div class="card"><h2>Other Indian disclosures · official NSE pages</h2>
        <div class="row">${d.links.map(l => `<a class="btn sm" href="${esc(l.url)}" target="_blank" rel="noopener noreferrer">${esc(l.label)} ↗</a>`).join('')}</div>
        <p class="note" style="margin-top:10px">NSE does not offer these as open data files, so the portal links to them instead of reading them. They do not feed the score.</p></div></div>`;
    view.querySelectorAll('.chip').forEach(c => c.onclick = () => { S.dealFilter = c.dataset.f; draw(); });
    view.querySelectorAll('tr.click').forEach(tr => { const go = () => location.hash = '#/predictor/' + encodeURIComponent(tr.dataset.s); tr.onclick = go; tr.onkeydown = e => e.key === 'Enter' && go(); });
    $('#df').onsubmit = e => { e.preventDefault(); const v = $('#dsym').value.trim().toUpperCase().replace(/\.NS$/, ''); location.hash = v ? '#/deals/' + encodeURIComponent(v) : '#/deals'; };
  };
  draw();
}

/* ---------------------------------------------------------------- settings */
async function settings() {
  const my = S.nav;
  let st, err; try { st = await api('/api/status'); } catch (e) { err = e; }
  if (my !== S.nav) return;
  if (err) { view.innerHTML = head('Limits', '') + failBox(err); return; }
  const s = st.settings;
  view.innerHTML = head('Limits', 'Your budget and risk rules. Every prediction is sized and checked against these.') +
    `<div class="stack"><div class="card"><h2>Budget · position sizing</h2><form class="grid" id="sf">
      <label>Capital per trade (₹)<input name="budget" type="number" min="1" step="1" value="${s.budget}" required></label>
      <label>Max loss per trade (₹)<input name="max_loss" type="number" min="1" step="1" value="${s.max_loss}" required></label>
      <label>Max loss per day (₹)<input name="daily_loss" type="number" min="1" step="1" value="${s.daily_loss}" required></label>
      <label>Max trades per day<input name="max_trades" type="number" min="1" max="50" step="1" value="${s.max_trades}" required></label>
      <label>Entries allowed from (IST)<input name="entry_start" type="time" value="${esc(s.entry_start)}" required></label>
      <label>Entries allowed until (IST)<input name="entry_end" type="time" value="${esc(s.entry_end)}" required></label>
      <label style="grid-column:1/-1">News watchlist (comma separated NSE symbols)<input name="watchlist" value="${esc(s.watchlist.join(', '))}" style="text-transform:uppercase"></label>
      <button class="btn primary">Save limits</button></form></div>
    <div class="card"><h2>Paper account</h2><form class="row" id="pf"><label>Starting cash (₹)<input name="paper_cash" type="number" min="1000" step="1000" value="100000"></label>
      <button class="btn danger" style="align-self:flex-end">Reset paper account</button></form>
      <p class="note" style="margin-top:10px">Resetting clears all paper positions and trade history.</p></div></div>`;
  $('#sf').onsubmit = async e => {
    e.preventDefault(); const f = Object.fromEntries(new FormData(e.target));
    f.watchlist = f.watchlist.split(',').map(x => x.trim()).filter(Boolean);
    try { await api('/api/settings', f); toast('Limits saved.'); } catch (err) { toast(err.message, 'bad'); }
  };
  $('#pf').onsubmit = e => {
    e.preventDefault(); const cash = +new FormData(e.target).get('paper_cash'), d = $('#dlg');
    $('#dlgBody').innerHTML = `<h3>Reset the paper account?</h3><p class="note">All paper positions and trade history will be cleared and cash set to ${inr(cash, 0)}. This cannot be undone.</p>
      <div class="row" style="justify-content:flex-end;margin-top:16px"><button class="btn" value="cancel">Cancel</button><button class="btn primary" id="go">Reset</button></div>`;
    d.showModal();
    $('#go').onclick = async ev => { ev.preventDefault(); try { await api('/api/settings', { paper_cash: cash }); toast('Paper account reset.'); } catch (err) { toast(err.message, 'bad'); } d.close(); };
  };
}

/* ---------------------------------------------------------------- boot */
(async () => {
  try {
    const st = await api('/api/status');
    setClock(st.clock); S.settings = st.settings; S.universe = st.universe; S.modes = st.modes;
    $('#symbols').innerHTML = st.universe.map(u => `<option value="${esc(u.symbol)}">${esc(u.name)}</option>`).join('');
  } catch (e) { toast('Server not reachable. Start it with start.bat.', 'bad'); }
  let saved = null; try { saved = localStorage.getItem('ts.mode'); } catch (e) { /* ignore */ }
  setMode(saved || 'swing', true);
  document.querySelectorAll('#modeSwitch button').forEach(b => b.onclick = () => setMode(b.dataset.mode));
  setMode(await modeChooser(), true);   // ask every time the portal opens
  await loadHeld();
  route(); pollAlerts();
})();
