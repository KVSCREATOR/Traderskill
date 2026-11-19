'use strict';
/* Three modes: Scalping (intraday), Trading (swing, 2-3 months), Investing (6-12 months).
   Loaded before app.js; uses its helpers ($, esc, inr, api, ...) only when called. */

const MODES = {
  intraday: { label: 'Scalping', short: 'Intraday', blurb: 'Buy and sell the same day. 15-minute opening-range breakouts, everything sold by 15:15.' },
  swing: { label: 'Trading', short: '2–3 months', blurb: 'Swing trades held up to about 3 months. Base breakouts and pullbacks in strong uptrends.' },
  invest: { label: 'Investing', short: '6–12 months', blurb: 'Positions held 6–12 months. Leaders in long uptrends with growing earnings.' },
};
const isLong = () => S.mode !== 'intraday';

function setMode(m, quiet) {
  if (!MODES[m]) m = 'swing';
  const changed = S.mode && S.mode !== m;
  S.mode = m;
  try { localStorage.setItem('ts.mode', m); } catch (e) { /* ignore */ }
  document.documentElement.dataset.mode = m;
  document.querySelectorAll('#modeSwitch button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.mode === m)));
  const sub = document.querySelector('.brand span');
  if (sub) sub.textContent = MODES[m].label + ' · ' + MODES[m].short;
  const orb = document.querySelector('#nav a[data-view="orb"] span');
  if (orb) orb.innerHTML = m === 'intraday' ? 'ORB scanner<small>nse-scanner</small>' : 'Strength ranking<small>nse-scanner</small>';
  const scan = document.querySelector('#nav a[data-view="scanner"] small');
  if (scan) scan.textContent = m === 'intraday' ? 'scanner' : 'scanner · daily';
  if (changed && !quiet) { toast(`Switched to ${MODES[m].label} (${MODES[m].short}).`); route(); }
}

function modeChooser() {
  return new Promise(resolve => {
    const d = $('#dlg');
    $('#dlgBody').innerHTML = `<h3>What do you want to do today?</h3><p class="note">You can switch any time from the top-right corner.</p>
      <div class="modecards">${Object.entries(MODES).map(([k, v]) => `<button type="button" class="modecard ${S.mode === k ? 'on' : ''}" data-m="${k}">
        <b>${v.label}</b><span class="tag">${v.short}</span><small>${v.blurb}</small></button>`).join('')}</div>`;
    const done = m => { d.close(); resolve(m); };
    d.querySelectorAll('.modecard').forEach(b => b.onclick = () => done(b.dataset.m));
    d.addEventListener('cancel', () => resolve(S.mode), { once: true });
    d.showModal();
    const cur = d.querySelector('.modecard.on') || d.querySelector('.modecard'); cur.focus();
  });
}

/* ---------------------------------------------------------------- daily chart */
/* Screener-style page header (big number + coloured pill) and coloured tiles, shared by Predictor, Scanner, My holdings. */
function scHead(label, big, chg, sub) {
  return `<div class="card sc-head"><div class="sc-price"><span class="sc-label">${label}</span><span class="sc-px">${big}</span>${chg != null ? `<span class="sc-pill ${chg >= 0 ? 'up' : 'down'}">${sgn(chg)}</span>` : ''}</div>${sub ? `<div class="sc-sub">${sub}</div>` : ''}</div>`;
}
function scTiles(items) {
  return `<div class="kv sc-kv" style="margin:0">${items.map(([l, v, c]) => `<div${c === 'up' ? ' class="tile-up"' : c === 'down' ? ' class="tile-down"' : ''}><span>${l}</span><b>${v}</b></div>`).join('')}</div>`;
}

/* Chart range buttons (1D … Max), shared by every time-series chart. Sessions = trading days back from the latest bar. */
const RANGE_KEYS = [['1d', '1D', 1], ['1w', '1W', 5], ['1m', '1M', 21], ['3m', '3M', 63], ['6m', '6M', 126], ['1y', '1Y', 252], ['3y', '3Y', 756], ['5y', '5Y', 1260], ['max', 'Max', Infinity]];
function rangeBar() {
  const cur = S.range || 'max';
  return `<div class="seg range-seg" role="group" aria-label="Chart range">${RANGE_KEYS.map(([k, l]) => `<button type="button" data-range="${k}" aria-pressed="${k === cur}">${l}</button>`).join('')}</div>`;
}
function sliceRange(arr) {
  const r = RANGE_KEYS.find(x => x[0] === (S.range || 'max'));
  return !r || r[2] === Infinity || !arr ? arr : arr.slice(-r[2]);
}
document.addEventListener('click', e => {
  const b = e.target.closest && e.target.closest('.range-seg [data-range]'); if (!b) return;
  S.range = b.dataset.range;
  try { if (S.chartRedraw) S.chartRedraw(); } catch (err) { /* chart left the page */ }
  document.querySelectorAll('.range-seg [data-range]').forEach(x => x.setAttribute('aria-pressed', String(x.dataset.range === S.range)));
});

function dailyChart(p) {
  const all = p.daily_bars || []; if (!all.length) return '<div class="empty">No daily bars.</div>';
  const bars = sliceRange(all);
  const swing = p.mode === 'swing', pl = p.plan, n = bars.length;
  const on = chartOn(), XP = 64;   // extra panels: RS vs Nifty, RSI
  const W = 960, R = 150, L = 8, T = 12, PH = 300, GAP = 8, VH = 70, B = 22;
  const rsTop = T + PH + GAP + VH + (on.rs ? GAP : 0), rsiTop = rsTop + (on.rs ? XP : 0) + (on.rsi ? GAP : 0);
  const H = rsiTop + (on.rsi ? XP : 0) + B;
  const lines = [['Entry', pl.entry, 'var(--accent)'], ['Stop', pl.stop, 'var(--fail)']];
  if (pl.target) lines.unshift(['Target', pl.target, 'var(--pass)']);
  if (pl.level && Math.abs(pl.level - pl.entry) / pl.entry > 0.004) lines.push([pl.level_label === '40-day high' ? '40d high' : '52w high', pl.level, 'var(--warn)']);
  const vals = bars.flatMap(b => [b.h, b.l]).concat(lines.map(l => l[1]));
  let lo = Math.min(...vals), hi = Math.max(...vals); const pad = (hi - lo) * 0.05 || 1; lo -= pad; hi += pad;
  const x = i => L + (i + 0.5) / n * (W - L - R), y = v => T + (hi - v) / (hi - lo) * PH, bw = Math.max(1.5, (W - L - R) / n * 0.62);
  const vTop = T + PH + GAP, vMax = Math.max(...bars.map(b => b.v || 0), 1), vy = v => vTop + VH - (v / vMax) * VH;
  let s = '', lastM = '', lastX = -99;
  const years = (new Date(bars[n - 1].d) - new Date(bars[0].d)) / 864e5 > 900;
  bars.forEach((b, i) => {
    const m = years ? b.d.slice(0, 4) : b.d.slice(0, 7);
    if (m !== lastM) {
      lastM = m;
      if (x(i) - lastX < 40) return;
      lastX = x(i);
      s += `<line x1="${x(i)}" x2="${x(i)}" y1="${T}" y2="${vTop + VH}" stroke="var(--border)"/><text x="${x(i)}" y="${H - 6}" text-anchor="middle">${years ? b.d.slice(0, 4) : new Date(b.d + 'T00:00:00').toLocaleDateString('en-IN', { month: 'short' }) + (b.d.slice(5, 7) === '01' ? ' ' + b.d.slice(2, 4) : '')}</text>`;
    }
  });
  // price scale on the right edge: about 6 round levels between the chart's low and high
  { const raw = (hi - lo) / 6, mag = 10 ** Math.floor(Math.log10(raw || 1)), step = [1, 2, 2.5, 5, 10].map(k => k * mag).find(z => z >= raw) || mag * 10;
    for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) {
      s += `<line x1="${L}" x2="${W - R}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}" stroke="var(--border)" stroke-dasharray="2 4"/><text x="${W - 4}" y="${(y(v) + 3.5).toFixed(1)}" text-anchor="end" style="fill:var(--muted);font-size:10px">${v >= 1000 ? v.toLocaleString('en-IN', { maximumFractionDigits: 0 }) : +v.toFixed(2)}</text>`;
    } }
  s += `<line x1="${L}" x2="${W - R}" y1="${vTop - GAP / 2}" y2="${vTop - GAP / 2}" stroke="var(--border)"/><text x="${W - R + 6}" y="${vTop + 10}">Volume</text>`;
  // volume: bars that clear the rule's volume test are drawn solid
  bars.forEach((b, i) => {
    if (!b.v) return;
    const spike = b.va && b.v >= pl.vol_x * b.va, c = b.c >= b.o ? 'var(--pass)' : 'var(--fail)';
    s += `<rect x="${x(i) - bw / 2}" y="${vy(b.v)}" width="${bw}" height="${vTop + VH - vy(b.v)}" fill="${c}" opacity="${spike ? 0.95 : 0.3}"/>`;
  });
  const va = bars.map((b, i) => b.va ? `${x(i).toFixed(1)},${vy(b.va).toFixed(1)}` : null).filter(Boolean);
  if (va.length > 1) s += `<polyline points="${va.join(' ')}" fill="none" stroke="var(--muted)" stroke-width="1.2"/>`;
  // moving averages (20-day only matters for Trading pullbacks)
  const avgs = [['s50', 'var(--warn)', ''], ['s200', 'var(--muted)', '5 4']];
  if (swing) avgs.unshift(['s20', 'var(--accent)', '2 3']);
  for (const [k, col, dash] of avgs) {
    const pts = bars.map((b, i) => b[k] != null ? `${x(i).toFixed(1)},${y(b[k]).toFixed(1)}` : null).filter(Boolean);
    if (pts.length > 1) s += `<polyline points="${pts.join(' ')}" fill="none" stroke="${col}" stroke-width="1.6" stroke-dasharray="${dash}"/>`;
  }
  bars.forEach((b, i) => {
    const c = b.c >= b.o ? 'var(--pass)' : 'var(--fail)';
    s += `<line x1="${x(i)}" x2="${x(i)}" y1="${y(b.h)}" y2="${y(b.l)}" stroke="${c}"/><rect x="${x(i) - bw / 2}" y="${y(Math.max(b.o, b.c))}" width="${bw}" height="${Math.max(1, Math.abs(y(b.o) - y(b.c)))}" fill="${c}"/>`;
  });
  // signal day marker
  const si = pl.signal_day ? bars.findIndex(b => b.d === pl.signal_day) : -1;
  if (si >= 0) { const sx = x(si), sy = y(bars[si].l) + 12; s += `<path d="M${sx} ${sy - 7} l6 10 h-12 z" fill="var(--accent)"><title>Signal: ${esc(pl.setup || '')} on ${fdate(pl.signal_day)}</title></path>`; }
  if (on.trail) {
    const tp = bars.map((b, i) => b.trail != null && b.trail > lo ? `${x(i).toFixed(1)},${y(b.trail).toFixed(1)}` : null).filter(Boolean);
    if (tp.length > 1) s += `<polyline points="${tp.join(' ')}" fill="none" stroke="#7F77DD" stroke-width="1.4" stroke-dasharray="1 3"/>`;
  }
  if (on.res) (p.results || []).forEach(r => {
    let k = bars.findIndex(b => (b.de || b.d) >= r.d); if (k < 0 || bars[0].d > r.d) return;
    const gx = x(k), col = r.growth == null ? 'var(--muted)' : r.growth >= 0 ? 'var(--pass)' : 'var(--fail)';
    s += `<g><title>Results for quarter ending ${fdate(r.q)} (date approx.)${r.growth != null ? ' · profit ' + sgn(r.growth) + ' vs previous quarter' : ''}</title><circle cx="${gx}" cy="${T + PH - 9}" r="8" fill="${col}" opacity=".9"/><text x="${gx}" y="${T + PH - 5.5}" text-anchor="middle" style="fill:#fff;font-weight:700">R</text></g>`;
  });
  const panel = (top, label, key, lo2, hi2, guides) => {
    const py = v => top + XP - (v - lo2) / (hi2 - lo2 || 1) * XP;
    let g = `<line x1="${L}" x2="${W - R}" y1="${top - GAP / 2}" y2="${top - GAP / 2}" stroke="var(--border)"/><text x="${W - R + 6}" y="${top + 10}">${label}</text>`;
    guides.forEach(v => { g += `<line x1="${L}" x2="${W - R}" y1="${py(v)}" y2="${py(v)}" stroke="var(--border)" stroke-dasharray="3 3"/><text x="${W - R + 6}" y="${py(v) + 3}" style="font-size:9px">${v}</text>`; });
    const pts = bars.map((b, i) => b[key] != null ? `${x(i).toFixed(1)},${py(b[key]).toFixed(1)}` : null).filter(Boolean);
    if (pts.length > 1) g += `<polyline points="${pts.join(' ')}" fill="none" stroke="var(--accent)" stroke-width="1.4"/>`;
    return g;
  };
  if (on.rs) { const v = bars.map(b => b.rs).filter(z => z != null); if (v.length) s += panel(rsTop, 'RS vs Nifty', 'rs', Math.min(...v), Math.max(...v), [100]); }
  if (on.rsi) s += panel(rsiTop, 'RSI 14', 'rsi', 0, 100, [30, 70]);
  s += candleHits(bars, i => x(i), (W - L - R) / n, T, T + PH, b => (b.tl ? esc(b.tl) : fdate(b.d)) + (b.va && b.v ? ` · vol ${(b.v / b.va).toFixed(1)}× avg` : ''));
  const lab = lines.map(l => ({ l, yy: y(l[1]) })).sort((a, b) => a.yy - b.yy);
  for (let i = 1; i < lab.length; i++) if (lab[i].yy - lab[i - 1].yy < 13) lab[i].yy = lab[i - 1].yy + 13;
  for (const { l, yy } of lab) s += `<line x1="${L}" x2="${W - R}" y1="${y(l[1])}" y2="${y(l[1])}" stroke="${l[2]}" stroke-width="1.2" stroke-dasharray="${l[0].includes('high') ? '2 3' : '6 4'}"/><text x="${W - R + 6}" y="${yy + 3.5}" style="fill:${l[2]}">${l[0]} ${l[1].toFixed(1)}</text>`;
  return `${rangeBar()}<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Daily candles with averages, rule levels and volume">${s}</svg>
    <div class="legend">${swing ? '<span><i style="background:var(--accent)"></i>20-day average</span>' : ''}<span><i style="background:var(--warn)"></i>50-${p.tf_unit || 'day'} average</span><span><i style="background:var(--muted)"></i>200-${p.tf_unit || 'day'} average</span>
    <span><i style="background:var(--warn);height:2px"></i>${esc(pl.level_label || 'breakout level')} (buy on a close above)</span>${si >= 0 ? '<span style="color:var(--accent)">▲ signal day</span>' : ''}
    ${on.trail ? '<span><i style="background:#7F77DD"></i>Trailing stop (rules: best close of 60 candles − ' + (swing ? 3 : 5) + '× range)</span>' : ''}${on.res ? '<span>R = results (green profit up, red down; date approx.)</span>' : ''}${on.rs ? '<span>RS vs Nifty rising = beating the market</span>' : ''}${on.rsi ? '<span>RSI above 70 = stretched, below 30 = washed out</span>' : ''}
    <span>Solid volume bars = at least ${pl.vol_x}× the 50-${p.tf_unit || 'day'} average${p.tf_unit ? '' : " (the rule's volume test)"}</span></div>`;
}

/* chart timeframes (Investing): 3-hour, daily (the rules' view), weekly, monthly, 6-monthly */
const TFS = [['3h', '3H'], ['1d', '1D'], ['1w', '1W'], ['1m', '1M'], ['6m', '6M']];
const TF_INFO = { '3h': ['3-hour', '3-hour candles · last year', '3-hour'], '1w': ['week', 'Weekly candles', 'week'], '1m': ['month', 'Monthly candles', 'month'], '6m': ['6-month', '6-monthly candles', '6-month'] };
function chartOn() { try { return Object.assign({ rs: false, trail: false, res: false, rsi: false }, JSON.parse(localStorage.getItem('ts.ind') || '{}')); } catch (e) { return { rs: false, trail: false, res: false, rsi: false }; } }
const IND = [['rs', 'RS vs Nifty'], ['trail', 'Trailing stop'], ['res', 'Results'], ['rsi', 'RSI']];
function indToggles() { const on = chartOn(); return `<div class="chips" id="indSeg" style="margin:0">${IND.map(([k, l]) => `<button type="button" class="chip ${on[k] ? 'on' : ''}" data-ind="${k}">${l}</button>`).join('')}</div>`; }
function bindTf(p) {
  let cur = p;   // the chart now on screen (daily or another timeframe)
  const redraw = () => { $('#chartBody').innerHTML = cur.daily_bars.length ? dailyChart(cur) : '<div class="empty">No candles for this timeframe.</div>'; };
  S.chartRedraw = redraw;   // the range buttons redraw the chart on screen
  document.querySelectorAll('#indSeg [data-ind]').forEach(b => b.onclick = () => {
    const on = chartOn(); on[b.dataset.ind] = !on[b.dataset.ind];
    try { localStorage.setItem('ts.ind', JSON.stringify(on)); } catch (e) { /* ignore */ }
    b.classList.toggle('on', on[b.dataset.ind]); redraw();
  });
  const seg = $('#tfSeg'); if (!seg) return;
  const dailyTitle = $('#chartTitle').textContent;
  seg.querySelectorAll('button').forEach(b => b.onclick = async () => {
    const tf = b.dataset.tf;
    seg.querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
    if (tf === '1d') { cur = p; redraw(); $('#chartTitle').textContent = dailyTitle; return; }
    $('#chartBody').innerHTML = '<div class="empty">Loading candles…</div>';
    let d; try { d = await api(`/api/candles?symbol=${encodeURIComponent(p.symbol)}&tf=${tf}`); } catch (e) { $('#chartBody').innerHTML = failBox(e); return; }
    if (seg.querySelector('[aria-pressed="true"]') !== b) return;
    const [unit, title] = TF_INFO[tf];
    const yrs = d.bars.length ? ((new Date(d.bars[d.bars.length - 1].d) - new Date(d.bars[0].d)) / 3.156e10).toFixed(1) : 0;
    $('#chartTitle').textContent = `${title} · ${d.bars.length} candles${tf === '3h' ? '' : ' · ' + yrs + ' years'}`;
    cur = Object.assign({}, p, { daily_bars: d.bars, results: d.results, tf_unit: unit, plan: Object.assign({}, p.plan, { signal_day: null }) });
    redraw();
  });
}

/* ---------------------------------------------------------------- predictor, Trading / Investing */
const SKILLS_LONG = [
  ['scanner', 'setup', 'scanner'], ['nse-scanner', 'trend', 'orb'], ['entry', 'entry', 'entry'], ['exit', 'exit', 'exit'],
  ['timemachine', 'odds', 'odds'], ['budget', 'size', 'budget'], ['risk', 'risk', 'risk'], ['market', 'regime', 'scanner'],
  ['news', 'news', 'news'], ['analyst', 'earnings', 'earnings'], ['big deals', 'deals', 'deals'], ['alerts', null, 'alerts'], ['broker', null, 'broker'],
];
const ptsCell = c => c.max ? `${c.points}/${c.max}<i><u style="width:${c.points / c.max * 100}%"></u></i>` : c.status === 'na' ? 'n/a' : 'gate';
const checkRow = c => `<div class="check"><span class="ico ${c.status}">${ICON[c.status]}</span>
  <div><b>${esc(c.title)}</b> <span class="tag">${esc(c.skill)}</span><p>${esc(c.detail)}</p></div><div class="pts">${ptsCell(c)}</div></div>`;
const fdate = s => s ? new Date(s + 'T00:00:00').toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }) : '–';
const sgn = (v, d = 1, u = '%') => v == null ? '–' : (v >= 0 ? '+' : '') + v.toFixed(d) + u;

function stockBacktestCard(p) {
  const b = p.backtest;
  if (!b || !b.trades) return `<div class="card"><h2>Backtest on ${esc(p.symbol)}</h2><div class="empty">Too few past signals on this stock to judge.</div></div>`;
  return `<div class="card"><h2>Backtest on ${esc(p.symbol)} · ${b.years} years</h2>
    <div class="facts">
      <div><span>Trades</span><b class="mono">${b.trades}</b></div><div><span>Won</span><b class="mono">${(b.win_rate * 100).toFixed(0)}%</b></div>
      <div><span>Average result</span><b class="mono ${cls(b.avg_r)}">${sgn(b.avg_r, 2, 'R')}</b></div><div><span>Average holding</span><b class="mono">${b.avg_days.toFixed(0)} days</b></div>
      <div><span>Average win</span><b class="mono up">${sgn(b.avg_win_pct)}</b></div><div><span>Average loss</span><b class="mono down">${sgn(b.avg_loss_pct)}</b></div></div>
    ${b.recent.length ? `<div class="tablewrap" style="margin-top:14px"><table><thead><tr><th>Bought</th><th>Sold</th><th>Setup</th><th class="num">Result</th><th>Exit</th></tr></thead><tbody>
      ${b.recent.map(t => `<tr><td class="mono">${fdate(t.in)}</td><td class="mono">${fdate(t.out)}</td><td>${esc(t.setup)}</td><td class="num ${cls(t.pct)}">${sgn(t.pct)}</td><td><span class="tag">${esc(t.why)}</span></td></tr>`).join('')}</tbody></table></div>` : ''}
    <p class="note" style="margin-top:10px">Same rules, one trade at a time, after costs. <a href="#/odds">See the full portfolio backtest on all 250 stocks →</a></p></div>`;
}

function renderLong(p) {
  const by = Object.fromEntries(p.checks.map(c => [c.id, c])), pl = p.plan, sz = p.size, t = p.trend;
  const verdictText = { qualifies: p.mode === 'swing' ? 'Trade qualifies' : 'Investment qualifies', wait: 'Wait', skip: 'Skip for now' }[p.verdict];
  const canTrade = !pl.trigger && p.risk.verdict === 'PASS';
  const strip = SKILLS_LONG.map(([n, c, page]) => `<a class="skill ${c && by[c] ? by[c].status : ''}" href="#/${page}${['news', 'earnings', 'deals'].includes(page) ? '/' + encodeURIComponent(p.symbol) : ''}" title="${esc(c && by[c] ? by[c].detail : 'Open ' + n)}">${n}</a>`).join('');
  view.innerHTML = head(`${esc(p.symbol)} <span class="muted" style="font-weight:400;font-size:15px">${esc(p.name)}</span>`,
    `${esc(p.mode_label)} mode · daily prices to ${fdate(p.asof)}${p.live ? ' (today\'s bar still forming)' : ''} · source: ${esc(p.source)}`,
    `${stockSelect(p.symbol)}<button class="btn" id="again">Refresh</button>`) +
    `<div class="stack">
    ${p.source !== 'Yahoo Finance' ? `<div class="banner">Yahoo Finance has no data for this stock, so prices come from the ${esc(p.source)} (about 75 days only). The 200-day average and the backtest need more history.</div>` : ''}
    <div class="skills">${strip}</div>
    <div class="card sc-head">
      <div class="sc-price"><span class="sc-label">Last price</span><span class="sc-px">${inr(p.price)}</span><span class="sc-pill ${p.change_pct >= 0 ? 'up' : 'down'}">${pct(p.change_pct)}</span><span class="muted" style="font-size:13px">on the day</span></div>
      <div class="sc-sub">${esc(p.mode_label)} rules · daily prices to ${fdate(p.asof)}${p.live ? ' · today\'s bar still forming' : ''}</div>
    </div>
    <div class="sc-grid">
      <div class="card score">${gauge(p.score, p.verdict)}<div class="verdict ${p.verdict}">${verdictText}</div><p>${esc(p.why)}</p><p class="note">${p.points} of ${p.max_points} points</p></div>
      <div class="card">
        <div class="kv">
          <div><span>${pl.trigger ? 'Buy above' : 'Entry'}</span><b>${inr(pl.entry)}</b></div>
          <div><span>Stop (${pl.risk_pct.toFixed(1)}%)</span><b class="down">${inr(pl.stop)}</b></div>
          <div><span>${pl.target ? 'Target' : 'Exit'}</span><b class="${pl.target ? 'up' : ''}">${pl.target ? inr(pl.target) : 'Trailing stop'}</b></div>
          <div><span>Hold up to</span><b>${fdate(pl.hold_until)}</b></div>
          <div><span>Shares</span><b>${sz.qty}</b></div>
          <div><span>Capital</span><b>${inr(sz.cost, 0)}</b></div>
          <div><span>Max loss</span><b class="down">${inr(sz.max_loss, 0)}</b></div>
          <div><span>${pl.target ? 'Profit at target' : 'Costs'}</span><b class="${pl.target ? 'up' : ''}">${pl.target ? inr(sz.reward, 0) : inr(sz.costs, 0)}</b></div></div>
        <div class="row"><button class="btn primary" id="paper" ${canTrade ? '' : 'disabled'}>Paper ${p.mode === 'swing' ? 'trade' : 'invest'}</button>${gttBtn(p)}
          <button class="btn" id="mkAlerts">Set ${pl.trigger ? 'trigger, ' : ''}stop${pl.target ? ' &amp; target' : ''} alerts</button>
          <span class="note">${canTrade ? 'Risk check: PASS' : pl.trigger ? 'No confirmed entry yet.' : 'Locked until the risk check passes.'}</span></div>
        ${pl.target ? `<p class="note" style="margin-top:8px">Profit shown after costs; about ${inr(sz.reward_after_tax, 0)} after 20% short-term capital gains tax.</p>` : ''}
      </div></div>
    <div class="card chart" id="chartCard"><div class="row" style="justify-content:space-between;margin-bottom:10px"><h2 style="margin:0" id="chartTitle">Daily chart · last ${p.daily_bars.length} sessions · ${p.mode === 'swing' ? 'Trading' : 'Investing'} rules</h2>
      <div class="row" style="gap:8px">${indToggles()}${p.mode === 'invest' ? `<div class="seg" id="tfSeg">${TFS.map(([k, l]) => `<button type="button" data-tf="${k}" aria-pressed="${k === '1d'}">${l}</button>`).join('')}</div>` : ''}</div></div><div id="chartBody">${dailyChart(p)}</div></div>
    <div class="card"><h2>Why this score</h2><div class="checks">${p.checks.map(checkRow).join('')}</div></div>
    <div class="grid2">${stockBacktestCard(p)}
      <div class="card"><h2>Trend and strength</h2>
        <div class="row" style="margin-bottom:12px">${p.setups.map(s => `<span class="tag hot" title="${esc(s.detail)}">${esc(s.label)}</span>`).join('') || '<span class="muted">No setup right now</span>'}</div>
        <div class="facts">
          <div><span>vs Nifty, 3 months</span><b class="mono ${cls(t.own3 - t.bench3)}">${t.own3 != null && t.bench3 != null ? sgn((t.own3 - t.bench3) * 100) : '–'}</b></div>
          <div><span>vs Nifty, 6 months</span><b class="mono ${cls(t.own != null && p.mode === 'invest' ? t.rs : null)}">${p.mode === 'invest' && t.rs != null ? sgn(t.rs) : '–'}</b></div>
          <div><span>52-week high</span><b class="mono">${inr(t.high52)}</b></div><div><span>From 52-week high</span><b class="mono">${sgn((p.price / t.high52 - 1) * 100)}</b></div>
          <div><span>50-day average</span><b class="mono">${inr(t.sma50)}</b></div><div><span>200-day average</span><b class="mono">${inr(t.sma200)}</b></div>
          <div><span>Daily range (ATR)</span><b class="mono">${inr(t.atr)}</b></div><div><span>RSI (14)</span><b class="mono">${t.rsi != null ? t.rsi.toFixed(0) : '–'}</b></div>
          <div><span>Market filter</span><b class="${t.regime ? 'up' : 'down'}">${t.regime ? 'Buy allowed' : 'Hold off'}</b></div><div><span>Holding limit</span><b class="mono">${pl.hold_days} trading days</b></div></div>
        <div class="row" style="margin-top:14px"><a class="btn sm" href="#/earnings/${encodeURIComponent(p.symbol)}">Earnings detail</a><a class="btn sm" href="#/news/${encodeURIComponent(p.symbol)}">Headlines</a><a class="btn sm" href="#/deals/${encodeURIComponent(p.symbol)}">Big deals</a></div></div>
    </div></div>`;
  $('#again').onclick = () => predictor(p.symbol);
  bindTf(p);
  bindStock(goPredict);
  $('#mkAlerts').onclick = async () => {
    const a = [{ type: 'below', symbol: p.symbol, level: +pl.stop.toFixed(2), label: 'Stop' }];
    if (pl.target) a.push({ type: 'above', symbol: p.symbol, level: +pl.target.toFixed(2), label: 'Target' });
    if (pl.trigger) a.unshift({ type: 'above', symbol: p.symbol, level: +pl.entry.toFixed(2), label: 'Buy trigger' });
    try { await api('/api/alerts', { alerts: a }); toast(`${a.length} alerts set for ${p.symbol}.`); askNotify(); pollAlerts(); } catch (e) { toast(e.message, 'bad'); }
  };
  $('#paper').onclick = () => confirmLong(p);
}

function confirmLong(p) {
  const pl = p.plan, sz = p.size, d = $('#dlg');
  $('#dlgBody').innerHTML = `<h3>Paper ${p.mode === 'swing' ? 'trade' : 'investment'} · ${esc(p.symbol)}</h3>
    <p class="note">Simulated delivery buy in your ${esc(p.mode_label)} paper account. No real money moves and nothing is sent to any broker.</p>
    <div class="facts"><div><span>Buy at market, about</span><b class="mono">${inr(p.price)}</b></div><div><span>Shares (resized at fill)</span><b class="mono">≈ ${sz.qty}</b></div>
    <div><span>Stop</span><b class="mono down">${inr(pl.stop)}</b></div><div><span>${pl.target ? 'Target' : 'Exit'}</span><b class="mono up">${pl.target ? inr(pl.target) : 'Trailing stop'}</b></div>
    <div><span>Max loss</span><b class="mono">${inr(sz.max_loss, 0)}</b></div><div><span>Hold up to</span><b class="mono">${fdate(pl.hold_until)}</b></div></div>
    <div class="row" style="justify-content:flex-end"><button class="btn" value="cancel">Cancel</button><button class="btn primary" id="go">Place paper order</button></div>`;
  d.showModal();
  $('#go').onclick = async e => {
    e.preventDefault(); $('#go').disabled = true;
    try { const r = await api('/api/orders', { symbol: p.symbol, confirm: true }); d.close(); toast(`Paper buy filled: ${r.position.qty} ${p.symbol} at ${inr(r.position.entry)}`); location.hash = '#/broker'; }
    catch (err) { d.close(); toast(err.message, 'bad'); }
  };
}
