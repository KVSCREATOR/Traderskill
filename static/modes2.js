'use strict';
/* Trading / Investing: single-skill pages, scanner, portfolio backtest, broker, limits. */

const SKILLPAGES_LONG = {
  entry: 'Confirms the buy on a daily close: a base breakout or a pullback bounce, and refuses to chase once price runs away.',
  exit: 'Sets the stop before you buy, moves it to break-even after +2R (Trading) or +1R (Investing), then trails it; also exits on the holding limit.',
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
      ${fact('Buy only if', p.mode === 'swing' ? 'Volume ≥ 1.5× its 50-day average' : 'Volume ≥ 1.3× its 50-day average')}${fact('Do not chase above', p.mode === 'swing' ? '5% over the signal close' : '8% over the signal close')}</div>
      <div class="row" style="margin-top:12px">${gttBtn(p)}<span class="note">Market closed? Set a GTT and the paper broker buys when the price reaches your trigger.</span></div></div>${chart}`;
  } else if (key === 'exit') {
    body = `<div class="card"><h2>Exit plan</h2><div class="facts">
      ${fact('Stop', inr(pl.stop), 'down')}${fact('Risk per share', inr(pl.risk) + ' (' + pl.risk_pct.toFixed(1) + '%)')}
      ${fact('Target', pl.target ? inr(pl.target) : 'None: let winners run', pl.target ? 'up' : '')}${fact(p.mode === 'swing' ? 'After +2R' : 'After +1R', 'Stop moves to break-even')}
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
    // Best odds: a completed buy signal, top-half strength vs the Nifty, market filter on, strongest first.
    // In the backtest, buying the strongest signals first beat a random pick (Trading ~11.5% vs ~9%/yr);
    // a stock's own past win rate did NOT predict its next trades, so it is not used.
    const best = r => d.regime && ['confirmed', 'recent'].includes(r.status) && r.rs_pct >= 50;
    let rows = d.rows.filter(r => strength || f === 'all' || (f === 'best' ? best(r) : f === 'n50' ? r.nifty50 : f === 'buy' ? ['confirmed', 'recent', 'provisional'].includes(r.status) : f === 'up' ? (inv ? r.up_long : r.up_mid) : r.rs_pct >= 80));
    if (strength || f === 'best') rows = rows.slice().sort((a, b) => (b[inv ? 'rs6' : 'rs3'] ?? -999) - (a[inv ? 'rs6' : 'rs3'] ?? -999));
    const bestNote = f === 'best' ? `<div class="card"><p style="margin:0"><b>Best odds</b> = a confirmed buy signal, stronger than at least half of the 250 stocks vs the Nifty, with the market filter on, strongest first. In the ${inv ? '2017–2026 backtest about 38% of Investing signals made money, averaging +0.56R' : '2017–2026 backtest about 39% of Trading signals made money, averaging +0.29R'} per trade: most trades lose a little, a few winners make the profit. ${d.regime ? '' : '<b>The market filter is off today, so the list is empty.</b>'} Past results do not promise future ones.</p></div>` : '';
    const chips = [['all', 'All 250'], ['best', '★ Best odds'], ['buy', 'In buy zone'], ['up', 'Uptrend'], ['rs', 'Top 20% strength'], ['n50', 'Nifty 50 only']].map(([k, l]) => `<button class="chip ${f === k ? 'on' : ''}" data-f="${k}">${l}</button>`).join('');
    view.innerHTML = head(title, `${MODES[S.mode].label} mode · ${d.universe} · ${rows.length} of ${d.rows.length} shown · daily prices · scanned ${d.scanned_at} IST`, '<button class="btn" id="rescan">Rescan</button>') +
      `<div class="stack">${d.regime ? '' : '<div class="banner">The Nifty is below its key moving averages. The rules hold off new buys until the market recovers; the list is for watching.</div>'}
      ${strength ? `<p class="note">Stocks ranked by how much they beat the Nifty over ${inv ? '6' : '3'} months. Leaders tend to keep leading; laggards tend to keep lagging.</p>` : `<div class="chips">${chips}</div>${bestNote}`}
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
      <div id="gttBox"></div>
      <p class="note">This portal has no connection to a real brokerage. To buy for real, place the order yourself in your own broker app as a delivery (CNC) order.</p></div>`;
    view.querySelectorAll('[data-close]').forEach(b => b.onclick = async () => { try { await api('/api/orders/close', { id: b.dataset.close }); toast('Sold at market (paper).'); load(); } catch (e) { toast(e.message, 'bad'); } });
    gttCard($('#gttBox'));
  };
  await load();
  S.timer = setInterval(load, 60000);
}

/* ---------------------------------------------------------------- forward test (live track record) */
async function journalPage() {
  const intro = 'Every buy signal the scanner finds is logged once. Its result is worked out from the next open after it was logged, with the same stop, trailing stop and holding limit, so it is a test on days the backtest never saw.';
  if (!isLong()) {
    view.innerHTML = head('Forward test', intro) + '<div class="card"><div class="empty">The forward test tracks Trading and Investing signals. Switch mode at the top right.</div></div>';
    return;
  }
  const my = S.nav;
  view.innerHTML = head('Forward test', intro) + loading(2);
  let d, err; try { d = await api('/api/journal'); } catch (e) { err = e; }
  if (my !== S.nav) return;
  if (err) { view.innerHTML = head('Forward test', intro) + failBox(err); return; }
  const r2 = v => v == null ? '–' : sgn(v, 2, 'R');
  const few = d.closed < 30;
  const verdict = !d.closed ? 'No closed trades yet. Results build up as signals finish (weeks for Trading, months for Investing).'
    : few ? `Only ${d.closed} closed so far: too few to judge. About 30+ are needed before the average means much.`
      : d.avg_r_closed >= d.expected_r * 0.5 ? 'Live results are in line with the backtest so far.'
        : d.avg_r_closed > 0 ? 'Live results are positive but weaker than the backtest. Keep watching.'
          : 'Live results are below zero. The rules are not working on new data so far; be careful.';
  const statusPill = r => r.status === 'closed' ? `<span class="pill ${r.r > 0 ? 'pass' : 'fail'}">${esc(r.why)}</span>`
    : r.status === 'open' ? '<span class="pill">open</span>' : `<span class="pill warn">${esc(r.status)}</span>`;
  view.innerHTML = head('Forward test', intro, `<span class="pill">${esc(d.label)} · ${esc(d.rules)}</span>`) +
    `<div class="stack"><div class="kv" style="margin:0">
      <div><span>Logged since</span><b>${d.since ? fdate(d.since) : '–'}</b></div><div><span>Signals logged</span><b>${d.signals}</b></div>
      <div><span>Closed / still open</span><b>${d.closed} / ${d.open}</b></div><div><span>Won (closed)</span><b>${d.win_rate != null ? d.win_rate.toFixed(0) + '%' : '–'}</b></div>
      <div><span>Average per trade (closed)</span><b class="${cls(d.avg_r_closed)}">${r2(d.avg_r_closed)}</b></div>
      <div><span>Average incl. open trades</span><b class="${cls(d.avg_r_all)}">${r2(d.avg_r_all)}</b></div>
      <div><span>Backtest expects</span><b>${r2(d.expected_r)}</b></div>
      <div><span>Higher scanner rank better?</span><b>${d.by_rank ? `rank ≥${d.by_rank.split}: ${r2(d.by_rank.high)} · below: ${r2(d.by_rank.low)}` : 'needs 10+ closed'}</b></div></div>
    <div class="card"><p style="margin:0">${esc(verdict)}</p></div>
    <div class="card"><h2>Signals</h2>${d.rows.length ? `<div class="tablewrap"><table><thead><tr><th>Stock</th><th>Signal day</th><th>Logged</th><th class="num">Rank</th><th>Bought</th><th class="num">Entry</th><th class="num">Exit / last</th><th class="num">Days</th><th>Status</th><th class="num">Result</th></tr></thead><tbody>
      ${d.rows.map(r => `<tr><td class="sym"><a href="#/predictor/${encodeURIComponent(r.symbol)}"><b>${esc(r.symbol)}</b></a><small>${esc(r.setup || '')}${r.regime ? '' : ' · market filter off'}</small></td>
        <td class="mono">${fdate(r.day)}</td><td class="mono">${fdate(r.logged)}</td><td class="num">${r.rank ?? '–'}</td>
        <td class="mono">${r.entry_day ? fdate(r.entry_day) : '–'}</td><td class="num">${r.entry ? inr(r.entry) : '–'}</td>
        <td class="num">${r.exit ? inr(r.exit) : r.last ? inr(r.last) : '–'}</td><td class="num">${r.days ?? '–'}</td>
        <td>${statusPill(r)}</td><td class="num ${cls(r.r)}">${r.r != null ? r2(r.r) : '–'}</td></tr>`).join('')}</tbody></table></div>`
      : '<div class="empty">Nothing logged yet. Open the Scanner in this mode once a day; every new buy signal it finds is logged here automatically.</div>'}</div>
    <p class="note">R = profit or loss as a multiple of the amount risked (entry minus first stop), after costs. These are rule results on paper, not advice.</p></div>`;
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

/* ---------------------------------------------------------------- GTT (good till triggered) paper orders, all modes */
function gttBtn(p) {
  S.gttP = p;
  return `<button class="btn" data-gtt>Set GTT order</button>`;
}
function gttDialog(p) {
  const pl = p.plan || {}, intra = p.mode === 'intraday' || S.mode === 'intraday', d = $('#dlg');
  const trig = pl.trigger || pl.entry || p.price, open = p.clock && p.clock.open;
  const num = (id, label, v, ph = '') => `<label>${label}<input id="${id}" type="number" step="0.05" min="0" value="${v != null ? (+v).toFixed(2) : ''}" placeholder="${ph}"></label>`;
  $('#dlgBody').innerHTML = `<h3>GTT order · ${esc(p.symbol)} · ${esc(MODES[S.mode].label)}</h3>
    <p class="note">Good Till Triggered: the paper broker buys automatically when the price reaches your trigger. ${open ? 'The market is open now; the GTT is checked from' : 'Set it now while the market is closed; it is checked from'} ${intra ? 'the next session, inside your entry window, for that one session only' : 'the next session on, for up to 1 year'}. Paper only: nothing is sent to any broker.</p>
    <div class="grid">${num('gTrig', 'Trigger price (₹)', trig)}
      ${intra ? num('gStop', 'Stop (₹)', pl.stop) + num('gTgt', 'Target (₹)', pl.target)
        : num('gStop', 'Stop (₹) · blank = rule stop', null, 'auto: ' + (pl.stop ? pl.stop.toFixed(2) : 'ATR rule'))}</div>
    <p class="note">Last price ${inr(p.price)}. A trigger above it buys a breakout; below it buys a dip. Shares are sized and risk-checked at the fill with your limits.</p>
    <div class="row" style="justify-content:flex-end"><button class="btn" value="cancel">Cancel</button><button class="btn primary" id="gGo">Place GTT</button></div>`;
  d.showModal();
  $('#gGo').onclick = async e => {
    e.preventDefault();
    const v = id => { const x = $('#' + id); return x && x.value !== '' ? +x.value : null; };
    const body = { symbol: p.symbol, trigger: v('gTrig'), stop: v('gStop'), confirm: true };
    if (intra) body.target = v('gTgt');
    $('#gGo').disabled = true;
    try { await api('/api/gtt', body); d.close(); toast(`GTT set: buy ${p.symbol} at ${inr(body.trigger)}.`); }
    catch (err) { $('#gGo').disabled = false; toast(err.message, 'bad'); }
  };
}
document.addEventListener('click', e => { if (e.target.closest && e.target.closest('[data-gtt]') && S.gttP) { e.preventDefault(); gttDialog(S.gttP); } });

async function gttCard(box) {
  if (!box) return;
  let d; try { d = await api('/api/gtt'); } catch (e) { box.innerHTML = ''; return; }
  const pill = o => ({ active: '<span class="pill warn">waiting</span>', triggered: '<span class="pill pass">bought</span>', rejected: '<span class="pill fail">rejected</span>' })[o.status] || `<span class="pill">${esc(o.status)}</span>`;
  box.innerHTML = `<div class="card"><h2>GTT orders</h2>${d.orders.length ? `<div class="tablewrap"><table><thead><tr><th>Stock</th><th>Set</th><th>Buy when price</th><th class="num">Stop</th><th class="num">Target</th><th>Valid till</th><th>Status</th><th></th></tr></thead><tbody>
    ${d.orders.map(o => `<tr><td class="mono"><b>${esc(o.symbol)}</b></td><td class="mono">${esc(o.created_at.slice(0, 16))}</td>
      <td class="mono">${o.direction === 'above' ? 'rises to' : 'falls to'} ${inr(o.trigger)}</td><td class="num down">${o.stop ? inr(o.stop) : 'rule'}</td><td class="num up">${o.target ? inr(o.target) : '–'}</td>
      <td class="mono">${o.expires ? fdate(o.expires) : 'next session'}</td><td>${pill(o)}<small class="muted" style="display:block">${esc(o.note || '')}</small></td>
      <td class="num">${o.status === 'active' ? `<button class="btn sm" data-gcancel="${o.id}">Cancel</button>` : ''}</td></tr>`).join('')}</tbody></table></div>`
    : '<div class="empty">No GTT orders. Use “Set GTT order” on a prediction or the Entry page.</div>'}</div>`;
  box.querySelectorAll('[data-gcancel]').forEach(b => b.onclick = async () => { try { await api('/api/gtt/cancel', { id: b.dataset.gcancel }); toast('GTT cancelled.'); gttCard(box); } catch (e) { toast(e.message, 'bad'); } });
}

/* ---------------------------------------------------------------- My holdings (Zerodha, read-only via the free Kite MCP server) */
const VERDICT = { exit: ['Exit signal', 'fail'], weak: ['Weak', 'warn'], hold: ['Hold', 'pass'], buy: ['Buy signal', 'pass'] };
async function holdingsPage() {
  const intro = 'Your real Zerodha holdings, read-only through Zerodha\'s free Kite MCP server. You sign in on Zerodha\'s own page; this portal never sees your password and cannot place orders.';
  const my = S.nav;
  view.innerHTML = head('My holdings', intro) + loading(2);
  let d, err; try { d = await api('/api/kite/holdings'); } catch (e) { err = e; }
  if (my !== S.nav) return;
  const connectBtn = label => `<button class="btn primary" id="kConnect">${label}</button>`;
  const bind = () => {
    const c = $('#kConnect'); if (c) c.onclick = async () => {
      c.disabled = true;
      try { const r = await api('/api/kite/connect', {}); location.href = r.url; }
      catch (e) { c.disabled = false; toast(e.message, 'bad'); }
    };
    const x = $('#kOff'); if (x) x.onclick = async () => { await api('/api/kite/disconnect', {}); toast('Disconnected from Zerodha.'); holdingsPage(); };
    const r = $('#kRefresh'); if (r) r.onclick = () => holdingsPage();
  };
  if (err) {
    const expired = /expired|Not connected|401/i.test(err.message);
    view.innerHTML = head('My holdings', intro, connectBtn(expired ? 'Connect Zerodha again' : 'Connect Zerodha')) + failBox(err);
    bind(); return;
  }
  if (!d.connected) {
    view.innerHTML = head('My holdings', intro) + `<div class="card"><h2>Connect your Zerodha account</h2>
      <ol class="note" style="line-height:1.8;margin:0 0 14px 18px"><li>Click <b>Connect Zerodha</b>. Zerodha's login page opens.</li>
      <li>Sign in with your Zerodha ID, password and 2FA there.</li><li>You come back here and your holdings load.</li></ol>
      <div class="row">${connectBtn('Connect Zerodha')}<span class="note">Free. Read-only. Zerodha asks you to log in again about once a day.</span></div></div>`;
    bind(); return;
  }
  if (d.kite_login) {
    view.innerHTML = head('My holdings', intro) + `<div class="card"><h2>One more Zerodha login</h2><p class="note">${esc(d.message)}</p>
      <div class="row"><a class="btn primary" href="${esc(d.kite_login)}" target="_blank" rel="noopener">Open Kite login</a><button class="btn" id="kRefresh">I have logged in · load holdings</button></div></div>`;
    bind(); return;
  }
  if (d.error) { view.innerHTML = head('My holdings', intro, connectBtn('Reconnect')) + failBox({ message: d.error }); bind(); return; }
  setClock(d.clock);
  const money = v => (v < 0 ? '−' : '+') + inr(Math.abs(v), 0);
  const tile = (label, v, txt) => `<div class="${v == null ? '' : v >= 0 ? 'tile-up' : 'tile-down'}"><span>${label}</span><b>${txt}</b></div>`;
  const tot = d.total_value || 1;
  view.innerHTML = head('My holdings', `Zerodha · connected ${esc(d.connected_at || '')} IST · read-only`, '<button class="btn" id="kRefresh">Refresh</button><button class="btn" id="kOff">Disconnect</button>') +
    `<div class="stack"><div class="kv" style="margin:0">
      <div><span>Current value</span><b>${inr(d.total_value, 0)}</b></div><div><span>Invested</span><b>${inr(d.total_cost, 0)}</b></div>
      ${tile('Total profit / loss', d.pnl, `${money(d.pnl)} (${d.pnl_pct != null ? sgn(d.pnl_pct) : '–'})`)}
      ${tile('Today', d.day_pnl, money(d.day_pnl))}</div>
    ${d.warnings.length ? `<div class="banner">${d.warnings.map(esc).join(' · ')}</div>` : ''}
    <div class="card"><h2>Holdings · ${d.rows.length}</h2>${d.rows.length ? `<div class="tablewrap"><table><thead><tr><th>Stock</th><th class="num">Qty</th><th class="num">Avg cost</th><th class="num">Price</th><th class="num">Today</th><th class="num">Value</th><th class="num">Weight</th><th class="num">Profit / loss</th><th>Trend</th><th class="num">From 52w high</th><th>What the rules say</th></tr></thead><tbody>
      ${d.rows.map(r => `<tr><td class="sym"><a href="#/predictor/${encodeURIComponent(r.symbol)}"><b>${esc(r.symbol)}</b></a><small>${esc(r.sector || r.exchange || '')}${r.flags.length ? ' · <span class="down">' + r.flags.map(esc).join('; ') + '</span>' : ''}</small></td>
        <td class="num">${r.qty}</td><td class="num">${r.avg != null ? inr(r.avg) : '–'}</td><td class="num">${r.ltp != null ? inr(r.ltp) : '–'}</td>
        <td class="num ${cls(r.day_pct)}">${r.day_pct != null ? sgn(r.day_pct) : '–'}</td><td class="num">${inr(r.value, 0)}</td><td class="num">${(r.value / tot * 100).toFixed(1)}%</td>
        <td class="num ${cls(r.pnl)}">${money(r.pnl)}<small class="chg" style="display:block">${r.pnl_pct != null ? sgn(r.pnl_pct) : ''}</small></td>
        <td><span class="pill ${r.trend === 'Strong up' ? 'pass' : r.trend === 'Below 200-day' ? 'fail' : ''}">${esc(r.trend)}</span></td>
        <td class="num">${r.from_high != null ? sgn(r.from_high) : '–'}</td>
        <td>${r.verdict ? `<span class="pill ${VERDICT[r.verdict][1]}">${VERDICT[r.verdict][0]}</span><small class="muted" style="display:block;max-width:230px">${esc(r.why)}${r.rule_stop ? ` · rule stop ${inr(r.rule_stop)} (${sgn(-r.to_stop)} away)` : ''}</small>` : '–'}</td></tr>`).join('')}</tbody></table></div>` : '<div class="empty">No holdings in this Zerodha account.</div>'}</div>
    ${d.sectors.length ? `<div class="card"><h2>By sector</h2><div class="facts">${d.sectors.map(([k, v]) => `<div><span>${esc(k)}</span><b class="mono">${inr(v, 0)} · ${(v / tot * 100).toFixed(1)}%</b></div>`).join('')}</div></div>` : ''}
    <p class="note"><b>What the rules say</b> applies the Investing rules (backtested Nov 2017–Nov 2026, ~11%/yr, 38% of trades won) to each holding: <b>Exit signal</b> = the rules would have sold (closed more than 3% below the 200-day average, or below the trailing stop); <b>Weak</b> = above the stop but the trend has turned down; <b>Hold</b> = uptrend intact; <b>Buy signal</b> = the entry rules fire now. “Rule stop” is the price where the rules would sell. These are mechanical rule results, not personal advice; the rules lose on most trades and still lost money in some years.</p>
    <p class="note">Trend uses the daily 50- and 200-day averages, the same as the Investing rules. This is a screening view of your own holdings, not advice to buy or sell. Prices from Zerodha; Zerodha does not share buy dates here, so the short- or long-term tax status is not shown.</p></div>`;
  bind();
}
