'use strict';
/* Trading / Investing: single-skill pages, scanner, portfolio backtest, broker, limits. */

const SKILLPAGES_LONG = {
  entry: 'Confirms the buy on a daily close: a base breakout or a pullback bounce, and refuses to chase once price runs away.',
  exit: 'Sets the stop before you buy, moves it to break-even after +1R, then trails it; also exits on the holding limit.',
  odds: 'Backtests the exact rules: on this stock, and as a full portfolio on all 250 stocks with your capital and limits.',
  budget: 'Sizes the buy so it risks no more than your risk per trade and puts no more than your cap into one stock.',
  risk: 'Checks the buy against your portfolio limits and returns PASS or BLOCK.',
};

function equityChart(curve, start) {
  if (!curve || curve.length < 2) return '';
  const W = 960, H = 240, L = 64, R = 12, T = 10, B = 24;
  const vals = curve.map(c => c[1]), lo = Math.min(...vals, start) * 0.97, hi = Math.max(...vals) * 1.02;
  const x = i => L + i / (curve.length - 1) * (W - L - R), y = v => T + (hi - v) / (hi - lo) * (H - T - B);
  let s = '';
  for (let k = 0; k <= 4; k++) { const v = lo + (hi - lo) * k / 4; s += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="var(--border)"/><text x="${L - 6}" y="${y(v) + 3}" text-anchor="end">${(v / 1e5).toFixed(1)}L</text>`; }
  let ly = '';
  curve.forEach((c, i) => { const yr = c[0].slice(0, 4); if (yr !== ly) { ly = yr; s += `<text x="${x(i)}" y="${H - 7}" text-anchor="middle">${yr}</text>`; } });
  s += `<line x1="${L}" x2="${W - R}" y1="${y(start)}" y2="${y(start)}" stroke="var(--muted)" stroke-dasharray="4 4"/>`;
  s += `<polyline points="${curve.map((c, i) => x(i).toFixed(1) + ',' + y(c[1]).toFixed(1)).join(' ')}" fill="none" stroke="var(--accent)" stroke-width="2"/>`;
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Account value over the backtest">${s}</svg>`;
}

async function portfolioBacktest(box, fresh) {
  box.innerHTML = `<div class="card"><h2>Portfolio backtest · all 250 stocks</h2><div class="empty">Running the ${MODES[S.mode].label} rules on about 9 years of daily prices with your capital and limits. The first run downloads history and can take a minute…</div></div>`;
  const my = S.nav;
  let b, err; try { b = await api('/api/backtest' + (fresh ? '?refresh=1' : '')); } catch (e) { err = e; }
  if (my !== S.nav) return;
  if (err) { box.innerHTML = failBox(err); return; }
  const cfg = b.settings, money = v => (v < 0 ? '−' : '') + inr(Math.abs(v), 0);
  box.innerHTML = `<div class="card"><div class="row" style="justify-content:space-between;margin-bottom:12px"><h2 style="margin:0">Portfolio backtest · ${esc(b.label)} · ${fdate(b.from)} to ${fdate(b.to)}</h2><button class="btn sm" id="rerun">Run again</button></div>
    <div class="kv" style="margin-top:0">
      <div><span>Start → end</span><b>${inr(b.start, 0)} → ${inr(b.final, 0)}</b></div><div><span>Total return</span><b class="${cls(b.total_pct)}">${sgn(b.total_pct)}</b></div>
      <div><span>Per year (CAGR)</span><b class="${cls(b.cagr)}">${sgn(b.cagr)}</b></div><div><span>Worst fall</span><b class="down">−${b.max_dd.toFixed(1)}%</b></div>
      <div><span>Trades</span><b>${b.trades}</b></div><div><span>Won</span><b>${b.win_rate != null ? b.win_rate.toFixed(0) + '%' : '–'}</b></div>
      <div><span>Average win / loss</span><b><span class="up">${money(b.avg_win || 0)}</span> / <span class="down">${money(b.avg_loss || 0)}</span></b></div>
      <div><span>Average per trade</span><b class="${cls(b.expectancy)}">${money(b.expectancy || 0)}</b></div></div>
    <div class="chart">${equityChart(b.curve, b.start)}</div>
    <div class="facts" style="margin-top:12px">
      <div><span>Profit factor</span><b class="mono">${b.profit_factor ? b.profit_factor.toFixed(2) : '–'}</b></div><div><span>Average holding</span><b class="mono">${b.avg_held ? b.avg_held.toFixed(0) + ' days' : '–'}</b></div>
      <div><span>Money invested, on average</span><b class="mono">${b.exposure.toFixed(0)}%</b></div><div><span>Drawdown pauses</span><b class="mono">${b.pauses}</b></div>
      <div><span>Tax estimate</span><b class="mono">${inr(b.tax_est, 0)}</b></div><div><span>Profit after costs and tax</span><b class="mono ${cls(b.after_tax)}">${money(b.after_tax)}</b></div>
      <div><span>Exits: target / trailing / stop</span><b class="mono">${b.exits.target} / ${b.exits.trail} / ${b.exits.stop}</b></div><div><span>Exits: time / trend broken</span><b class="mono">${b.exits.time} / ${b.exits['trend broken']}</b></div></div>
    <h2 style="margin-top:18px">Year by year</h2><div class="years">${b.yearly.map(y => `<div><span>${y.year}</span><b class="${cls(y.ret)}">${sgn(y.ret, 0)}</b></div>`).join('')}</div>
    <p class="note" style="margin-top:12px">Rules: risk ${inr(cfg.risk_per_trade, 0)} per trade, max ${inr(cfg.max_per_stock, 0)} per stock, up to ${cfg.max_positions} stocks, ${cfg.max_per_sector} per sector; buys at the next day's open, only when the Nifty filter allows; costs about 0.12% per side plus ₹16 per sale. Tax is a rough estimate (20% short-term, 12.5% long-term above ₹1.25 lakh a year). It uses today's index members, which flatters the past a little, and ${b.stocks} stocks had enough history. Past results do not promise future returns.</p></div>
    <div class="card"><h2>Latest backtest trades</h2><div class="tablewrap"><table><thead><tr><th>Stock</th><th>Bought</th><th>Sold</th><th class="num">Days</th><th class="num">Qty</th><th>Exit</th><th class="num">Result</th><th class="num">P&amp;L</th></tr></thead><tbody>
      ${b.recent.map(t => `<tr><td class="sym"><b>${esc(t.symbol)}</b><small>${esc(t.setup)}</small></td><td class="mono">${fdate(t.in)}</td><td class="mono">${fdate(t.out)}</td><td class="num">${t.held}</td><td class="num">${t.qty}</td><td><span class="tag">${esc(t.why)}</span></td><td class="num ${cls(t.r)}">${sgn(t.r, 2, 'R')}</td><td class="num ${cls(t.pnl)}">${money(t.pnl)}</td></tr>`).join('')}</tbody></table></div></div>`;
  $('#rerun', box).onclick = () => portfolioBacktest(box, true);
}

function skillLong(key, p, h1) {
  const c = p.checks.find(x => x.id === ({ entry: 'entry', exit: 'exit', odds: 'odds', budget: 'size', risk: 'risk' })[key]);
  const pl = p.plan, sz = p.size, st = p.settings, R = MODES[p.mode];
  const fact = (k, v, k2 = '') => `<div><span>${k}</span><b class="mono ${k2}">${v}</b></div>`;
  const chart = `<div class="card chart"><h2>Daily chart</h2>${dailyChart(p)}</div>`;
  let body = '';
  if (key === 'entry') {
    body = `<div class="card"><h2>Entry details</h2><div class="facts">
      ${fact('Setup', esc(pl.setup || 'None right now'))}${fact('Status', esc({ confirmed: 'Confirmed on the close', recent: 'Recent signal, still in buy zone', provisional: 'Today, confirm at 15:30 close', missed: 'Missed: price ran away', none: 'Waiting for a trigger' }[pl.state]))}
      ${fact(pl.trigger ? 'Buy above (daily close)' : 'Entry price', inr(pl.entry))}${fact('Price now', inr(p.price))}
      ${fact('Buy only if', p.mode === 'swing' ? 'Volume ≥ 1.5× its 50-day average' : 'Volume ≥ 1.3× its 50-day average')}${fact('Do not chase above', p.mode === 'swing' ? '5% over the signal close' : '8% over the signal close')}</div></div>${chart}`;
  } else if (key === 'exit') {
    body = `<div class="card"><h2>Exit plan</h2><div class="facts">
      ${fact('Stop', inr(pl.stop), 'down')}${fact('Risk per share', inr(pl.risk) + ' (' + pl.risk_pct.toFixed(1) + '%)')}
      ${fact('Target', pl.target ? inr(pl.target) + ' (2.5R)' : 'None: let winners run', pl.target ? 'up' : '')}${fact('After +1R', 'Stop moves to break-even')}
      ${fact('Then', p.mode === 'swing' ? 'Trail 3× daily range below the best close' : 'Trail 5× daily range below the best close')}${fact('Time exit', pl.hold_days + ' trading days (' + fdate(pl.hold_until) + ')')}
      ${p.mode === 'invest' ? fact('Trend exit', 'Close more than 3% below the 200-day average') : ''}${fact('Allowed stop range', p.mode === 'swing' ? '4% – 12% of price' : '8% – 20% of price')}</div></div>${chart}`;
  } else if (key === 'budget') {
    body = `<div class="card"><h2>Position size</h2><div class="kv" style="margin-top:0">
      <div><span>Shares</span><b>${sz.qty}</b></div><div><span>Capital used</span><b>${inr(sz.cost, 0)}</b></div>
      <div><span>Max loss</span><b class="down">${inr(sz.max_loss, 0)}</b></div><div><span>${pl.target ? 'Profit at target' : 'Costs (buy + sell)'}</span><b class="${pl.target ? 'up' : ''}">${inr(pl.target ? sz.reward : sz.costs, 0)}</b></div></div>
      <div class="facts">${fact('Your risk per trade', inr(st.risk_per_trade, 0))}${fact('Your max per stock', inr(st.max_per_stock, 0))}
      ${fact('Shares your risk allows', sz.by_risk)}${fact('Shares your cap allows', sz.by_cap)}
      ${fact('Size is limited by', esc(sz.limited_by))}${fact('Costs (buy + sell)', inr(sz.costs, 0))}
      ${pl.target ? fact('Profit after 20% tax', inr(sz.reward_after_tax, 0), 'up') : ''}${fact('Your capital', inr(st.capital, 0))}</div>
      <div class="row" style="margin-top:14px"><a class="btn sm" href="#/settings">Change my limits</a></div></div>`;
  } else if (key === 'risk') {
    body = `<div class="card"><div class="row" style="justify-content:space-between;margin-bottom:12px"><h2 style="margin:0">Portfolio limit checks</h2>
      <span class="pill ${p.risk.verdict === 'PASS' ? 'pass' : 'fail'}">${p.risk.verdict}</span></div><div class="checks">
      ${p.risk.checks.map(r => `<div class="check"><span class="ico ${r.ok ? 'pass' : 'fail'}">${r.ok ? '✓' : '✕'}</span><div><b>${esc(r.name)}</b><p>${esc(r.detail.replace(/Rs /g, '₹'))}</p></div><div class="pts">${r.ok ? 'ok' : 'block'}</div></div>`).join('')}</div>
      <div class="row" style="margin-top:14px"><a class="btn sm" href="#/settings">Change my limits</a></div></div>`;
  } else if (key === 'odds') {
    body = stockBacktestCard(p) + '<div id="pbt"></div>';
  }
  view.innerHTML = head(h1, `${R.label} mode · ${SKILLPAGES_LONG[key]}`, `${stockSelect(p.symbol)}<a class="btn" href="#/predictor/${encodeURIComponent(p.symbol)}">Full prediction</a>`) +
    `<div class="stack"><div class="card"><div class="checks">${checkRow(c)}</div></div>${body}</div>`;
  bindStock(s => { S.lastSymbol = s; try { localStorage.setItem('ts.symbol', s); } catch (e) { /* ignore */ } skillPage(key); });
  if (key === 'odds') portfolioBacktest($('#pbt'));
}

/* ---------------------------------------------------------------- scanner */
async function scannerLong(_arg, sub) {
  const strength = sub === 'orb', my = S.nav, inv = S.mode === 'invest';
  const title = strength ? 'Strength ranking' : 'Scanner';
  const statusPill = r => ({ confirmed: '<span class="pill pass">Buy zone</span>', recent: '<span class="pill pass">Buy zone</span>', provisional: '<span class="pill warn">Today, confirm at close</span>', missed: '<span class="pill">Missed</span>' })[r.status] || '';
  const draw = d => {
    setClock(d.clock);
    const alt = d.rows.filter(r => r.source !== 'Yahoo');
    if (alt.length && S.scanAlerted !== d.scanned_at) { S.scanAlerted = d.scanned_at; toast(`⚠ Data source switched for ${alt.length} stock${alt.length === 1 ? '' : 's'}: Yahoo Finance had no data, so exchange end-of-day prices are used for ${alt.slice(0, 6).map(r => r.symbol).join(', ')}.`, 'warnmsg'); }
    const f = S.scanFilterLong || 'all';
    let rows = d.rows.filter(r => strength || f === 'all' || (f === 'n50' ? r.nifty50 : f === 'buy' ? ['confirmed', 'recent', 'provisional'].includes(r.status) : f === 'up' ? (inv ? r.up_long : r.up_mid) : r.rs_pct >= 80));
    if (strength) rows = rows.slice().sort((a, b) => (b[inv ? 'rs6' : 'rs3'] ?? -999) - (a[inv ? 'rs6' : 'rs3'] ?? -999));
    const chips = [['all', 'All 250'], ['buy', 'In buy zone'], ['up', 'Uptrend'], ['rs', 'Top 20% strength'], ['n50', 'Nifty 50 only']].map(([k, l]) => `<button class="chip ${f === k ? 'on' : ''}" data-f="${k}">${l}</button>`).join('');
    view.innerHTML = head(title, `${MODES[S.mode].label} mode · ${d.universe} · ${rows.length} of ${d.rows.length} shown · daily prices · scanned ${d.scanned_at} IST`, '<button class="btn" id="rescan">Rescan</button>') +
      `<div class="stack">${d.regime ? '' : '<div class="banner">The Nifty is below its key moving averages. The rules hold off new buys until the market recovers; the list is for watching.</div>'}
      ${strength ? `<p class="note">Stocks ranked by how much they beat the Nifty over ${inv ? '6' : '3'} months. Leaders tend to keep leading; laggards tend to keep lagging.</p>` : `<div class="chips">${chips}</div>`}
      <div class="card"><div class="tablewrap" style="margin-top:-18px"><table><thead><tr><th>Stock</th><th class="num">Price</th><th class="num">Day</th><th>Setup</th><th>Trend</th><th class="num">vs Nifty 3m</th><th class="num">vs Nifty 6m</th><th class="num">From 52w high</th>${inv ? '<th class="num">Revenue</th><th class="num">Profit</th>' : ''}<th class="num">Rank</th></tr></thead>
      <tbody>${rows.map(r => `<tr class="click" data-s="${esc(r.symbol)}" tabindex="0"><td class="sym"><b>${esc(r.symbol)}</b><small>${esc(r.name)}${r.source !== 'Yahoo' ? ' · ' + esc(r.source) : ''}</small></td>
        <td class="num">${inr(r.price)}</td><td class="num ${cls(r.change_pct)}">${pct(r.change_pct)}</td>
        <td>${r.setup ? `<div class="row" style="gap:4px"><span class="tag hot" title="${esc(r.setup_detail)}">${esc(r.setup)}</span>${statusPill(r)}</div>` : r.trigger ? `<span class="muted">above ${inr(r.trigger, 0)}</span>` : '<span class="muted">–</span>'}</td>
        <td>${r.up_long && r.up_mid ? '<span class="up">Strong up</span>' : r.up_long || r.up_mid ? '<span class="up">Up</span>' : '<span class="muted">–</span>'}</td>
        <td class="num ${cls(r.rs3)}">${sgn(r.rs3)}</td><td class="num ${cls(r.rs6)}">${sgn(r.rs6)}</td><td class="num">${sgn(r.from_high)}</td>
        ${inv ? `<td class="num ${cls(r.rev_g)}" title="${esc(r.basis || '')}">${sgn(r.rev_g)}</td><td class="num ${cls(r.profit_g)}" title="${esc(r.basis || '')}">${sgn(r.profit_g)}</td>` : ''}
        <td class="num"><span class="rank ${r.rank >= 60 ? 'hi' : r.rank >= 30 ? 'mid' : ''}">${r.rank}</span></td></tr>`).join('') || `<tr><td colspan="${inv ? 11 : 9}" class="empty">No stocks match this filter right now.</td></tr>`}</tbody></table></div></div>
      ${d.failed.length ? `<p class="note">No data for: ${d.failed.map(x => esc(x.symbol)).join(', ')}.</p>` : ''}
      <p class="note">“Buy zone” means a setup confirmed on a recent daily close and the price has not run more than ${inv ? '8' : '5'}% past it. Click a row for the full score, plan and backtest.</p></div>`;
    view.querySelectorAll('.chip').forEach(c => c.onclick = () => { S.scanFilterLong = c.dataset.f; draw(d); });
    view.querySelectorAll('tr.click').forEach(tr => { const go = () => location.hash = '#/predictor/' + encodeURIComponent(tr.dataset.s); tr.onclick = go; tr.onkeydown = e => e.key === 'Enter' && go(); });
    $('#rescan').onclick = () => run(true);
  };
  const run = async fresh => {
    view.innerHTML = head(title, `Scanning 250 stocks on daily prices for ${MODES[S.mode].label.toLowerCase()} setups. The first scan of the day downloads 10 years of history and takes about a minute…`) + loading(3);
    let d, err; try { d = await api('/api/scan' + (fresh ? '?refresh=1' : '')); } catch (e) { err = e; }
    if (my !== S.nav) return;
    if (err) view.innerHTML = head(title, 'Scan failed') + failBox(err); else draw(d);
  };
  run(false);
}

/* ---------------------------------------------------------------- broker */
async function brokerLong() {
  const my = S.nav, label = MODES[S.mode].label;
  view.innerHTML = head('Paper broker', `Loading the ${label} paper account…`) + loading(2);
  const money = v => (v < 0 ? '−' : '+') + inr(Math.abs(v), 0);
  const load = async () => {
    let d, err; try { d = await api('/api/portfolio'); } catch (e) { err = e; }
    if (my !== S.nav) return;
    if (err) { view.innerHTML = head('Paper broker', '') + failBox(err); return; }
    setClock(d.clock);
    if (d.closed_now.length) toast(`Paper exits worked: ${d.closed_now.join(', ')}.`);
    view.innerHTML = head('Paper broker', `${esc(d.mode_label)} account · positions are held across days; stops, trailing stops and holding limits are worked on daily bars.`, '<span class="pill warn">Paper only · no real orders</span>') +
      `<div class="stack"><div class="kv" style="margin:0">
        <div><span>Equity</span><b>${inr(d.equity, 0)}</b></div><div><span>Cash</span><b>${inr(d.cash, 0)}</b></div>
        <div><span>Since start</span><b class="${cls(d.total_pnl)}">${money(d.total_pnl)}</b></div><div><span>Below peak</span><b class="${d.drawdown > 0 ? 'down' : ''}">${d.drawdown.toFixed(1)}%</b></div>
        <div><span>Open positions</span><b>${d.positions.length} of ${d.settings.max_positions}</b></div><div><span>Open risk</span><b>${inr(d.open_risk, 0)}</b></div>
        <div><span>Realised profit</span><b class="${cls(d.realised)}">${money(d.realised)}</b></div><div><span>Tax on it (rough)</span><b>${inr(Math.max(0, d.realised) * 0.2, 0)}</b></div></div>
      <div class="card"><h2>Holdings</h2>${d.positions.length ? `<div class="tablewrap"><table><thead><tr><th>Stock</th><th class="num">Qty</th><th class="num">Entry</th><th class="num">Last</th><th class="num">Stop</th><th class="num">Target</th><th class="num">Held</th><th class="num">P&amp;L</th><th></th></tr></thead><tbody>
        ${d.positions.map(p => `<tr><td class="sym"><b>${esc(p.symbol)}</b><small>${esc(p.setup || '')} · bought ${fdate(p.opened_date)}</small></td><td class="num">${p.qty}</td><td class="num">${inr(p.entry)}</td><td class="num">${inr(p.last)}</td>
          <td class="num down">${inr(p.stop)}${p.trailing ? ' <span class="tag">trailing</span>' : ''}</td><td class="num up">${p.target ? inr(p.target) : '–'}</td>
          <td class="num">${p.held || 0} d<small class="muted"> · until ${fdate(p.hold_until)}</small></td><td class="num ${cls(p.pnl)}">${money(p.pnl)}</td>
          <td class="num"><button class="btn sm" data-close="${p.id}">Sell now</button></td></tr>`).join('')}</tbody></table></div>`
        : `<div class="empty">No holdings. Use the scanner's “In buy zone” filter, then “Paper ${S.mode === 'swing' ? 'trade' : 'invest'}” on a prediction.</div>`}</div>
      <div class="card"><h2>Closed positions</h2>${d.trades.length ? `<div class="tablewrap"><table><thead><tr><th>Stock</th><th>Bought</th><th>Sold</th><th class="num">Days</th><th class="num">Entry</th><th class="num">Exit</th><th>Reason</th><th class="num">Result</th><th class="num">P&amp;L after costs</th><th>Tax</th></tr></thead><tbody>
        ${d.trades.map(t => `<tr><td class="mono"><b>${esc(t.symbol)}</b></td><td class="mono">${fdate(t.opened_date)}</td><td class="mono">${fdate(t.closed_date)}</td><td class="num">${t.held_days}</td><td class="num">${inr(t.entry)}</td><td class="num">${inr(t.exit)}</td>
          <td><span class="pill ${t.reason === 'target' || t.reason === 'trail' ? 'pass' : t.reason === 'stop' ? 'fail' : ''}">${esc(t.reason)}</span></td><td class="num ${cls(t.r)}">${sgn(t.r, 2, 'R')}</td><td class="num ${cls(t.pnl)}">${money(t.pnl)}</td><td>${esc(t.tax_type)}</td></tr>`).join('')}</tbody></table></div>` : '<div class="empty">No closed positions yet.</div>'}</div>
      <p class="note">This portal has no connection to a real brokerage. To buy for real, place the order yourself in your own broker app as a delivery (CNC) order.</p></div>`;
    view.querySelectorAll('[data-close]').forEach(b => b.onclick = async () => { try { await api('/api/orders/close', { id: b.dataset.close }); toast('Sold at market (paper).'); load(); } catch (e) { toast(e.message, 'bad'); } });
  };
  await load();
  S.timer = setInterval(load, 60000);
}

/* ---------------------------------------------------------------- limits, all modes */
async function settingsAll() {
  const my = S.nav;
  let st, err; try { st = await api('/api/status'); } catch (e) { err = e; }
  if (my !== S.nav) return;
  if (err) { view.innerHTML = head('Limits', '') + failBox(err); return; }
  const s = st.settings, m = S.mode;
  const num = (name, label, val, step = 1) => `<label>${label}<input name="${name}" type="number" min="0" step="${step}" value="${val}" required></label>`;
  const longForm = mm => { const c = st.modes[mm]; return `<form class="grid" id="lf">
      ${num('capital', 'Capital (₹)', c.capital, 1000)}${num('risk_per_trade', 'Risk per trade (₹)', c.risk_per_trade, 100)}
      ${num('max_per_stock', 'Max in one stock (₹)', c.max_per_stock, 1000)}${num('max_positions', 'Max stocks held', c.max_positions)}
      ${num('max_open_risk', 'Max total open risk (₹)', c.max_open_risk, 500)}${num('max_per_sector', 'Max stocks per sector', c.max_per_sector)}
      ${num('dd_pause_pct', 'Pause buys after a fall of (%)', c.dd_pause_pct, 0.5)}<button class="btn primary">Save ${MODES[mm].label} limits</button></form>`; };
  view.innerHTML = head('Limits', `Rules for ${MODES[m].label} mode. Every prediction is sized and checked against these. Switch mode at the top right to edit the others.`) +
    `<div class="stack"><div class="card"><h2>${MODES[m].label} · ${MODES[m].short}</h2>
    ${m === 'intraday' ? `<form class="grid" id="sf">
      <label>Capital per trade (₹)<input name="budget" type="number" min="1" step="1" value="${s.budget}" required></label>
      <label>Max loss per trade (₹)<input name="max_loss" type="number" min="1" step="1" value="${s.max_loss}" required></label>
      <label>Max loss per day (₹)<input name="daily_loss" type="number" min="1" step="1" value="${s.daily_loss}" required></label>
      <label>Max trades per day<input name="max_trades" type="number" min="1" max="50" step="1" value="${s.max_trades}" required></label>
      <label>Entries allowed from (IST)<input name="entry_start" type="time" value="${esc(s.entry_start)}" required></label>
      <label>Entries allowed until (IST)<input name="entry_end" type="time" value="${esc(s.entry_end)}" required></label>
      <button class="btn primary">Save Scalping limits</button></form>` : longForm(m)}</div>
    <div class="card"><h2>News watchlist</h2><form class="row" id="wf"><input name="watchlist" value="${esc(s.watchlist.join(', '))}" style="text-transform:uppercase;flex:1;min-width:220px"><button class="btn">Save watchlist</button></form></div>
    <div class="card"><h2>${MODES[m].label} paper account</h2><form class="row" id="pf"><label>Starting cash (₹)<input name="paper_cash" type="number" min="1000" step="1000" value="${m === 'intraday' ? 100000 : st.modes[m].capital}"></label>
      <button class="btn danger" style="align-self:flex-end">Reset paper account</button></form>
      <p class="note" style="margin-top:10px">Each mode has its own paper account. Resetting clears this mode's positions and history only.</p></div></div>`;
  const save = async (body, msg) => { try { await api('/api/settings', body); toast(msg); } catch (e) { toast(e.message, 'bad'); } };
  if (m === 'intraday') $('#sf').onsubmit = e => { e.preventDefault(); save(Object.fromEntries(new FormData(e.target)), 'Scalping limits saved.'); };
  else $('#lf').onsubmit = e => { e.preventDefault(); save({ mode_settings: { [m]: Object.fromEntries(new FormData(e.target)) } }, `${MODES[m].label} limits saved.`); };
  $('#wf').onsubmit = e => { e.preventDefault(); save({ watchlist: new FormData(e.target).get('watchlist').split(',').map(x => x.trim()).filter(Boolean) }, 'Watchlist saved.'); };
  $('#pf').onsubmit = e => {
    e.preventDefault(); const cash = +new FormData(e.target).get('paper_cash'), d = $('#dlg');
    $('#dlgBody').innerHTML = `<h3>Reset the ${MODES[m].label} paper account?</h3><p class="note">Its positions and history will be cleared and cash set to ${inr(cash, 0)}. This cannot be undone.</p>
      <div class="row" style="justify-content:flex-end;margin-top:16px"><button class="btn" value="cancel">Cancel</button><button class="btn primary" id="go">Reset</button></div>`;
    d.showModal();
    $('#go').onclick = async ev => { ev.preventDefault(); await save({ paper_cash: cash }, 'Paper account reset.'); d.close(); };
  };
}
