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
    let rows = d.rows.filter(r => strength || f === 'all' || (f === 'mine' ? heldSyms().includes(r.symbol) : f === 'best' ? best(r) : f === 'n50' ? r.nifty50 : f === 'buy' ? ['confirmed', 'recent', 'provisional'].includes(r.status) : f === 'up' ? (inv ? r.up_long : r.up_mid) : r.rs_pct >= 80));
    if (strength || f === 'best') rows = rows.slice().sort((a, b) => (b[inv ? 'rs6' : 'rs3'] ?? -999) - (a[inv ? 'rs6' : 'rs3'] ?? -999));
    const bestNote = f === 'best' ? `<div class="card"><p style="margin:0"><b>Best odds</b> = a confirmed buy signal, stronger than at least half of the 250 stocks vs the Nifty, with the market filter on, strongest first. In the ${inv ? '2017–2026 backtest about 38% of Investing signals made money, averaging +0.56R' : '2017–2026 backtest about 39% of Trading signals made money, averaging +0.29R'} per trade: most trades lose a little, a few winners make the profit. ${d.regime ? '' : '<b>The market filter is off today, so the list is empty.</b>'} Past results do not promise future ones.</p></div>` : '';
    const chips = [['all', 'All 250'], ...(heldSyms().length ? [['mine', '◉ My holdings']] : []), ['best', '★ Best odds'], ['buy', 'In buy zone'], ['up', 'Uptrend'], ['rs', 'Top 20% strength'], ['n50', 'Nifty 50 only']].map(([k, l]) => `<button class="chip ${f === k ? 'on' : ''}" data-f="${k}">${l}</button>`).join('');
    view.innerHTML = head(title, `${MODES[S.mode].label} mode · ${d.universe} · ${rows.length} of ${d.rows.length} shown · daily prices · scanned ${d.scanned_at} IST`, '<button class="btn" id="rescan">Rescan</button>') +
      `<div class="stack">${d.regime ? '' : '<div class="banner">The Nifty is below its key moving averages. The rules hold off new buys until the market recovers; the list is for watching.</div>'}
      ${strength ? `<p class="note">Stocks ranked by how much they beat the Nifty over ${inv ? '6' : '3'} months. Leaders tend to keep leading; laggards tend to keep lagging.</p>` : `<div class="chips">${chips}</div>${bestNote}`}
      <div class="card"><div class="row tablebar" style="margin-top:0"><input type="search" data-tfind placeholder="Search stock, name or sector" style="width:240px"><button class="btn sm" data-sortreset>Default order</button><span class="note" style="margin:0">Click a column heading to sort.</span></div><div class="tablewrap"><table><thead><tr><th>Stock</th><th class="num">Price</th><th class="num">Day</th><th>Setup</th><th>Trend</th><th class="num">vs Nifty 3m</th><th class="num">vs Nifty 6m</th><th class="num">From 52w high</th>${inv ? '<th class="num">Revenue</th><th class="num">Profit</th>' : ''}<th class="num">Rank</th></tr></thead>
      <tbody>${rows.map(r => `<tr class="click" data-s="${esc(r.symbol)}" tabindex="0"><td class="sym">${starBtn(r.symbol)}<b>${esc(r.symbol)}</b><small>${esc(r.name)}${r.source !== 'Yahoo' ? ' · ' + esc(r.source) : ''}</small></td>
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
    <div class="card" id="tgBox"><h2>Telegram notifications</h2><div class="empty">Loading…</div></div>
    <div class="card" id="pinBox"></div>
    <div class="card"><h2>News watchlist</h2><p class="note" style="margin:0">News and the Telegram buy-signal message now follow your <a href="#/myscan">My scanner</a> lists (${s.watchlist.length} stock${s.watchlist.length === 1 ? '' : 's'}: ${esc(s.watchlist.slice(0, 12).join(', '))}${s.watchlist.length > 12 ? '…' : ''}). Add or remove stocks there.</p></div>
    <div class="card"><h2>${MODES[m].label} paper account</h2><form class="row" id="pf"><label>Starting cash (₹)<input name="paper_cash" type="number" min="1000" step="1000" value="${m === 'intraday' ? 100000 : st.modes[m].capital}"></label>
      <button class="btn danger" style="align-self:flex-end">Reset paper account</button></form>
      <p class="note" style="margin-top:10px">Each mode has its own paper account. Resetting clears this mode's positions and history only.</p></div></div>`;
  const save = async (body, msg) => { try { await api('/api/settings', body); toast(msg); } catch (e) { toast(e.message, 'bad'); } };
  if (m === 'intraday') $('#sf').onsubmit = e => { e.preventDefault(); save(Object.fromEntries(new FormData(e.target)), 'Scalping limits saved.'); };
  else $('#lf').onsubmit = e => { e.preventDefault(); save({ mode_settings: { [m]: Object.fromEntries(new FormData(e.target)) } }, `${MODES[m].label} limits saved.`); };
  tgCard($('#tgBox'));
  codeBox($('#tgBox'));
  pinCard($('#pinBox'));
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
  return `<button class="btn" data-gtt>Set GTT order</button>${typeof starBtn === 'function' ? starBtn(p.symbol, true) : ''}`;
}
function gttDialog(p) {
  const pl = p.plan || {}, intra = p.mode === 'intraday' || S.mode === 'intraday', d = $('#dlg');
  // pl.trigger is a price in Scalping but a yes/no flag in Trading/Investing: never use a flag as a price
  const trig = (typeof pl.trigger === 'number' ? pl.trigger : null) || pl.entry || p.price, open = p.clock && p.clock.open;
  const sugg = p.size && p.size.qty ? p.size.qty : null;
  const num = (id, label, v, ph = '') => `<label>${label}<input id="${id}" type="number" step="0.05" min="0" value="${v != null ? (+v).toFixed(2) : ''}" placeholder="${ph}"></label>`;
  $('#dlgBody').innerHTML = `<h3>GTT order · ${esc(p.symbol)} · ${esc(MODES[S.mode].label)}</h3>
    <p class="note">Good Till Triggered: the paper broker buys automatically when the price reaches your trigger. ${open ? 'The market is open now; the GTT is checked from' : 'Set it now while the market is closed; it is checked from'} ${intra ? 'the next session, inside your entry window, for that one session only' : 'the next session on, for up to 1 year'}. Paper only: nothing is sent to any broker.</p>
    <div class="grid">${num('gTrig', 'Trigger price (₹)', trig)}
      <label>Quantity (shares) · blank = size by your limits<input id="gQty" type="number" step="1" min="1" value="${sugg || ''}" placeholder="${sugg ? 'suggested ' + sugg : 'auto'}"></label>
      ${intra ? num('gStop', 'Stop (₹)', pl.stop) + num('gTgt', 'Target (₹)', pl.target)
        : num('gStop', 'Stop (₹) · blank = rule stop', null, 'auto: ' + (pl.stop ? pl.stop.toFixed(2) : 'ATR rule'))}</div>
    <p class="note">Last price ${inr(p.price)}. <b>Trigger above the price</b> = breakout, filled the way the rules trade it: ${intra ? 'on the first completed 5-minute bar that closes at or above the trigger' : 'at the next day’s open after a daily close at or above the trigger, skipped if that open has run too far'}. <b>Trigger below the price</b> = dip buy, filled when the price touches it. Shares are sized and risk-checked at the fill with your limits.</p>
    <div class="row" style="justify-content:flex-end"><button class="btn" value="cancel">Cancel</button><button class="btn primary" id="gGo">Place GTT</button></div>`;
  d.showModal();
  $('#gGo').onclick = async e => {
    e.preventDefault();
    const v = id => { const x = $('#' + id); return x && x.value !== '' ? +x.value : null; };
    const body = { symbol: p.symbol, trigger: v('gTrig'), stop: v('gStop'), qty: v('gQty'), confirm: true };
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
function fitBlock(f) {
  if (!f) return '';
  if (f.error) return `<div class="card"><h2>Sector fit</h2><div class="empty">Could not work out sector fit: ${esc(f.error)}</div></div>`;
  const over = f.sectors.filter(z => z.over), moodPill = m => m ? `<span class="pill ${m === 'Strong' ? 'pass' : m === 'Weak' ? 'fail' : ''}">${m}</span>` : '–';
  const vpill = v => `<span class="pill ${VERDICT[v][1]}">${VERDICT[v][0]}</span>`;
  return `<div class="card"><h2>Sector fit</h2>
    <h3 style="margin:4px 0 8px;font-size:14px">1 · Too much in one sector</h3>
    ${over.length ? `<div class="tablewrap"><table><thead><tr><th>Sector</th><th class="num">Share</th><th class="num">Stocks</th><th>Trim first, per the rules</th></tr></thead><tbody>
      ${over.map(z => `<tr><td><b>${esc(z.sector)}</b></td><td class="num down">${z.pct.toFixed(1)}%</td><td class="num ${z.stocks > f.max_per_sector ? 'down' : ''}">${z.stocks}</td>
        <td>${z.trim.length ? z.trim.map(t => `<b class="mono">${esc(t.symbol)}</b> ${vpill(t.verdict)}`).join(' &nbsp; ') : '<span class="muted">All holdings here still pass the rules. To rebalance, the smallest gainer is usually trimmed first.</span>'}</td></tr>`).join('')}</tbody></table></div>`
      : `<p class="note">No sector is over ${f.limit_pct}% of your portfolio or over ${f.max_per_sector} stocks. Balanced by your limits.</p>`}
    <p class="note">Limits: no sector above ${f.limit_pct}% of the value, and no more than ${f.max_per_sector} stocks per sector (your Investing limit). Change the stock limit on the Limits page.</p>
    <h3 style="margin:16px 0 8px;font-size:14px">2 · Sector mood (all 250 stocks)</h3>
    <div class="tablewrap"><table><thead><tr><th>Sector</th><th class="num">Your share</th><th>Mood</th><th class="num">Stocks in long uptrend</th><th class="num">6-month vs Nifty</th><th>Your exit signals here</th></tr></thead><tbody>
      ${f.sectors.filter(z => z.mood).sort((a, b) => (b.uptrend_pct || 0) - (a.uptrend_pct || 0)).map(z => `<tr><td>${esc(z.sector)}</td><td class="num">${z.pct ? z.pct.toFixed(1) + '%' : '–'}</td><td>${moodPill(z.mood)}</td>
        <td class="num">${z.uptrend_pct.toFixed(0)}%</td><td class="num ${cls(z.rs6)}">${z.rs6 != null ? sgn(z.rs6) : '–'}</td><td class="mono">${z.exits.length ? '<span class="down">' + z.exits.map(esc).join(', ') + '</span>' : '–'}</td></tr>`).join('')}</tbody></table></div>
    <p class="note">For information only: in the Nov 2026 backtest, picking stocks by sector strength did <b>not</b> improve results, so mood alone is not a reason to buy or sell.</p>
    <h3 style="margin:16px 0 8px;font-size:14px">3 · Rule buy signals in sectors you have room for</h3>
    ${!f.regime ? '<p class="note">The market filter is off (Nifty below its 200-day average), so the Investing rules make no new buys right now.</p>'
      : f.buys.length ? `<div class="tablewrap"><table><thead><tr><th>Stock</th><th>Sector</th><th>Setup</th><th class="num">Price</th><th class="num">6-month vs Nifty</th></tr></thead><tbody>
        ${f.buys.map(b => `<tr class="click" onclick="location.hash='#/predictor/${encodeURIComponent(b.symbol)}'"><td class="sym"><b>${esc(b.symbol)}</b><small>${esc(b.name)}</small></td><td>${esc(b.sector || '')}</td><td>${esc(b.setup || '')}</td><td class="num">${inr(b.price)}</td><td class="num ${cls(b.rs6)}">${b.rs6 != null ? sgn(b.rs6) : '–'}</td></tr>`).join('')}</tbody></table></div>`
      : '<p class="note">No Investing buy signals right now in sectors you have room for.</p>'}
    <p class="note">These are the scanner's “Best odds” Investing signals (confirmed, top-half strength vs the Nifty, market filter on), leaving out stocks you hold and sectors you are already over the limit in. Click one for its full plan, stop and size. Rule results, not personal advice: about 38% of these signals made money in the backtest.</p></div>`;
}
async function holdingsPage() {
  const intro = 'Your real Zerodha holdings, read-only through Zerodha\'s free Kite MCP server. You sign in on Zerodha\'s own page; this portal never sees your password and cannot place orders.';
  const my = S.nav;
  if (!S.pinTok) return pinGate(holdingsPage);   // asked every time the page opens
  if (S.hTab && S.hTab !== 'live') return ledgerPage(S.hTab);
  view.innerHTML = head('My holdings', intro) + hTabs('live') + loading(2);
  let d, err; try { d = await api('/api/kite/holdings'); } catch (e) { err = e; }
  if (my !== S.nav) return;
  if (err && pinNeeded(err)) { S.pinTok = null; return pinGate(holdingsPage); }
  if (!err && d.connected && !d.kite_login && !d.error) api('/api/ledger?refresh=1').catch(() => {});   // keep the yearly record current
  const connectBtn = label => `<button class="btn primary" id="kConnect">${label}</button>`;
  const bind = () => {
    const c = $('#kConnect'); if (c) c.onclick = async () => {
      c.disabled = true;
      try { const r = await api('/api/kite/connect', {}); location.href = r.url; }
      catch (e) { c.disabled = false; toast(e.message, 'bad'); }
    };
    const x = $('#kOff'); if (x) x.onclick = async () => { await api('/api/kite/disconnect', {}); dropHeld(); toast('Disconnected from Zerodha.'); holdingsPage(); };
    const r = $('#kRefresh'); if (r) r.onclick = () => holdingsPage();
  };
  if (err || !d.connected || d.kite_login || d.error) dropHeld();
  if (err) {
    const expired = /expired|Not connected|401/i.test(err.message);
    view.innerHTML = head('My holdings', intro, connectBtn(expired ? 'Connect Zerodha again' : 'Connect Zerodha')) + hTabs('live') + failBox(err) + '<p class="note">Your saved record (Year record, Tax, Sectors, Funds) stays available in the tabs above while Zerodha is disconnected.</p>';
    bind(); return;
  }
  if (!d.connected) {
    view.innerHTML = head('My holdings', intro) + hTabs('live') + `<div class="card"><h2>Connect your Zerodha account</h2>
      <ol class="note" style="line-height:1.8;margin:0 0 14px 18px"><li>Click <b>Connect Zerodha</b>. Zerodha's login page opens.</li>
      <li>Sign in with your Zerodha ID, password and 2FA there.</li><li>You come back here and your holdings load.</li></ol>
      <div class="row">${connectBtn('Connect Zerodha')}<span class="note">Free. Read-only. Zerodha asks you to log in again about once a day.</span></div></div>
      <p class="note">Your saved record (Year record, Tax, Sectors, Funds) stays available in the tabs above while Zerodha is disconnected.</p>`;
    bind(); return;
  }
  if (d.kite_login) {
    view.innerHTML = head('My holdings', intro) + hTabs('live') + `<div class="card"><h2>One more Zerodha login</h2><p class="note">${esc(d.message)}</p>
      <div class="row"><a class="btn primary" href="${esc(d.kite_login)}" target="_blank" rel="noopener">Open Kite login</a><button class="btn" id="kRefresh">I have logged in · load holdings</button></div></div>`;
    bind(); return;
  }
  if (d.error) { view.innerHTML = head('My holdings', intro, connectBtn('Reconnect')) + hTabs('live') + failBox({ message: d.error }); bind(); return; }
  setClock(d.clock);
  const money = v => (v < 0 ? '−' : '+') + inr(Math.abs(v), 0);
  const tile = (label, v, txt) => `<div class="${v == null ? '' : v >= 0 ? 'tile-up' : 'tile-down'}"><span>${label}</span><b>${txt}</b></div>`;
  const tot = d.total_value || 1;
  view.innerHTML = head('My holdings', `Zerodha · connected ${esc(d.connected_at || '')} IST · read-only`, '<button class="btn" id="kAlerts">Set rule-stop alerts</button><button class="btn" id="kRefresh">Refresh</button><button class="btn" id="kOff">Disconnect</button>') + hTabs('live') +
    `<div class="stack"><div class="kv" style="margin:0">
      <div><span>Current value</span><b>${inr(d.total_value, 0)}</b></div><div><span>Invested</span><b>${inr(d.total_cost, 0)}</b></div>
      ${tile('Total profit / loss', d.pnl, `${money(d.pnl)} (${d.pnl_pct != null ? sgn(d.pnl_pct) : '–'})`)}
      ${tile('Today', d.day_pnl, money(d.day_pnl))}</div>
    ${d.warnings.length ? `<div class="banner">${d.warnings.map(esc).join(' · ')}</div>` : ''}
    <div class="card"><h2>Holdings · <span id="hCount">${d.rows.length}</span></h2>${d.rows.length ? `<div class="row tablebar"><input id="hFind" type="search" placeholder="Search stock or sector" style="width:200px">
      <div class="chips" style="margin:0">${[['all', 'All'], ['exit', 'Exit signal'], ['weak', 'Weak'], ['hold', 'Hold'], ['buy', 'Buy signal'], ['up', 'In profit'], ['down', 'In loss'], ['cap', 'Over cap']].map(([k, l]) => `<button class="chip ${k === 'all' ? 'on' : ''}" data-hf="${k}">${l}</button>`).join('')}</div>
      <button class="btn sm" data-sortreset>Default order</button><span class="note" style="margin:0">Click a column heading to sort.</span></div><div class="tablewrap"><table><thead><tr><th>Stock</th><th class="num">Qty</th><th class="num">Avg cost</th><th class="num">Price</th><th class="num">Today</th><th class="num">Value</th><th class="num">Weight</th><th class="num">Profit / loss</th><th>Trend</th><th class="num">From 52w high</th><th>What the ${esc(d.rules_label)} rules say</th><th>Latest news</th></tr></thead><tbody>
      ${d.rows.map(r => `<tr data-v="${esc(r.verdict || '')}" data-pl="${r.pnl >= 0 ? 'up' : 'down'}" data-cap="${r.flags.some(f => f.includes('cap')) ? 1 : 0}" data-txt="${esc((r.symbol + ' ' + (r.sector || '')).toLowerCase())}"><td class="sym"><a href="#/predictor/${encodeURIComponent(r.symbol)}"><b>${esc(r.symbol)}</b></a><small>${esc(r.sector || r.exchange || '')}${r.flags.length ? ' · <span class="down">' + r.flags.map(esc).join('; ') + '</span>' : ''}</small>${holdDetail(r)}</td>
        <td class="num">${r.qty}</td><td class="num">${r.avg != null ? inr(r.avg) : '–'}</td><td class="num">${r.ltp != null ? inr(r.ltp) : '–'}</td>
        <td class="num ${cls(r.day_pct)}">${r.day_pct != null ? sgn(r.day_pct) : '–'}</td><td class="num">${inr(r.value, 0)}</td><td class="num">${(r.value / tot * 100).toFixed(1)}%</td>
        <td class="num ${cls(r.pnl)}">${money(r.pnl)}<small class="chg" style="display:block">${r.pnl_pct != null ? sgn(r.pnl_pct) : ''}</small></td>
        <td><span class="pill ${r.trend === 'Strong up' ? 'pass' : r.trend === 'Below 200-day' ? 'fail' : ''}">${esc(r.trend)}</span></td>
        <td class="num">${r.from_high != null ? sgn(r.from_high) : '–'}</td>
        <td>${r.verdict ? `<span class="pill ${VERDICT[r.verdict][1]}">${VERDICT[r.verdict][0]}</span><small class="muted" style="display:block;max-width:230px">${esc(r.why)}${r.rule_stop ? ` · rule stop ${inr(r.rule_stop)} (${sgn(-r.to_stop)} away)` : ''}</small>` : '–'}</td><td class="hnews" data-hn="${esc(r.symbol)}"><span class="muted">Loading…</span></td></tr>`).join('')}</tbody></table></div>` : '<div class="empty">No holdings in this Zerodha account.</div>'}</div>
    ${d.sectors.length ? `<div class="card"><h2>By sector</h2><div class="facts">${d.sectors.map(([k, v]) => `<div><span>${esc(k)}</span><b class="mono">${inr(v, 0)} · ${(v / tot * 100).toFixed(1)}%</b></div>`).join('')}</div></div>` : ''}
    <div id="kExtras"><div class="card"><div class="empty">Loading positions, mutual funds and funds…</div></div></div>
    ${fitBlock(d.fit)}
    <p class="note"><b>What the rules say</b> applies the ${esc(d.rules_label)} rules${S.mode === 'intraday' ? ' (Scalping is same-day only, so long-held stocks are judged by the Investing rules; switch to Trading or Investing at the top right)' : ''} to each holding. ${d.rules_mode === 'swing' ? 'Trading rules: backtested ~11.5%/yr, 39% of trades won; <b>Exit signal</b> = below the trailing stop (60-day high close minus 3× the daily range);' : 'Investing rules: backtested ~11%/yr, 38% of trades won; <b>Exit signal</b> = closed more than 3% below the 200-day average, or below the trailing stop (60-day high close minus 5× the daily range);'} <b>Weak</b> = above the stop but the trend has turned down; <b>Hold</b> = uptrend intact; <b>Buy signal</b> = the entry rules fire now. “Rule stop” is the price where the rules would sell. These are mechanical rule results, not personal advice; the rules lose on most trades and still lost money in some years.</p>
    <p class="note">Trend uses the daily 50- and 200-day averages, the same as the Investing rules. This is a screening view of your own holdings, not advice to buy or sell. Prices from Zerodha; Zerodha does not share buy dates here, so the short- or long-term tax status is not shown.</p></div>`;
  S.held = { connected: true, symbols: d.rows.map(r => r.symbol) }; holdBar('holdings');
  const ka = $('#kAlerts'); if (ka) ka.onclick = async () => {
    const a = d.rows.filter(r => r.rule_stop && r.ltp && r.rule_stop < r.ltp).map(r => ({ type: 'below', symbol: r.symbol, level: +r.rule_stop.toFixed(2), label: 'Rule stop' }));
    if (!a.length) { toast('No holdings above their rule stop to watch.', 'bad'); return; }
    try { await api('/api/alerts', { alerts: a }); toast(`${a.length} rule-stop alerts set. They ring once when a price falls to its rule stop.`); askNotify(); pollAlerts(); } catch (e) { toast(e.message, 'bad'); }
  };
  extrasBox($('#kExtras'));
  makeCollapsible(view);
  holdNews(my);
  let hf = 'all';
  const applyF = () => {
    const q = ($('#hFind')?.value || '').trim().toLowerCase(); let n = 0;
    view.querySelectorAll('tr[data-v]').forEach(tr => {
      const ok = (!q || tr.dataset.txt.includes(q)) && (hf === 'all' || tr.dataset.v === hf || tr.dataset.pl === hf || (hf === 'cap' && tr.dataset.cap === '1'));
      tr.hidden = !ok; if (ok) n++;
    });
    const c = $('#hCount'); if (c) c.textContent = n === d.rows.length ? n : `${n} of ${d.rows.length}`;
  };
  view.querySelectorAll('[data-hf]').forEach(b => b.onclick = () => { hf = b.dataset.hf; view.querySelectorAll('[data-hf]').forEach(x => x.classList.toggle('on', x === b)); applyF(); });
  const hfind = $('#hFind'); if (hfind) hfind.oninput = applyF;
  bind();
}


/* ---------------------------------------------------------------- Zerodha holdings shown around the portal */
async function loadHeld() { try { S.held = await api('/api/kite/held'); } catch (e) { S.held = null; } S.heldAt = Date.now(); }
// Zerodha not reachable (disconnected, login expired, server down): hide every holdings extra
function dropHeld() { S.held = null; S.heldAt = Date.now(); const b = $('#holdbar'); if (b) b.hidden = true; }
// re-check on page changes (at most every 60 s); hide the bar at once if access is lost
async function refreshHeld(name) {
  if (Date.now() - (S.heldAt || 0) < 60000) return;
  const had = heldSyms().length; await loadHeld();
  if (had !== heldSyms().length) holdBar(name);   // lost access: hide; regained: show
}
function heldSyms() { return S.held && S.held.connected ? S.held.symbols : []; }
const PICK_VIEWS = { predictor: 'predictor', entry: 'entry', exit: 'exit', odds: 'odds', budget: 'budget', risk: 'risk', news: 'news', earnings: 'earnings' };
function holdBar(name) {
  const bar = $('#holdbar'); if (!bar) return;
  const syms = heldSyms();
  if (!syms.length || !PICK_VIEWS[name]) { bar.hidden = true; return; }
  bar.hidden = false;
  const by = Object.fromEntries(((S.held && S.held.items) || []).map(h => [h.symbol, h]));
  // 7 shades by profit %: dark red <= -10, red -10..-5, light red -5..-1, white -1..+1, light green +1..+5, green +5..+10, dark green >= +10
  const shade = p => p == null ? 'pl0' : p <= -10 ? 'plm3' : p <= -5 ? 'plm2' : p <= -1 ? 'plm1' : p < 1 ? 'pl0' : p < 5 ? 'plp1' : p < 10 ? 'plp2' : 'plp3';
  bar.innerHTML = `<span class="muted">◉ My holdings</span>${syms.map(x => { const p = by[x] && by[x].pnl_pct;
    return `<button class="chip pl ${shade(p)}" data-hp="${esc(x)}" title="${esc(x)}${p != null ? ' · profit ' + (p >= 0 ? '+' : '') + p.toFixed(1) + '%' : ''}">${esc(x)}${p != null ? `<small>${p >= 0 ? '+' : ''}${p.toFixed(1)}%</small>` : ''}</button>`; }).join('')}
    <span class="pl-key" title="Colour = profit or loss on your average cost"><i class="plm3"></i><i class="plm2"></i><i class="plm1"></i><i class="pl0"></i><i class="plp1"></i><i class="plp2"></i><i class="plp3"></i></span>`;
  bar.querySelectorAll('[data-hp]').forEach(b => b.onclick = () => {
    const sym = b.dataset.hp; S.lastSymbol = sym; try { localStorage.setItem('ts.symbol', sym); } catch (e) { /* ignore */ }
    if (['predictor', 'news', 'earnings'].includes(name)) location.hash = `#/${name}/${encodeURIComponent(sym)}`;
    else if (location.hash === '#/' + name) route(); else location.hash = '#/' + name;
  });
}
const LABELS = { live_balance: 'Live balance', opening_balance: 'Opening balance', cash: 'Cash', collateral: 'Collateral (pledged)', intraday_payin: 'Added today',
  adhoc_margin: 'Ad-hoc margin', debits: 'Used (debits)', exposure: 'Exposure', span: 'SPAN', option_premium: 'Option premium', holding_sales: 'Holding sales',
  turnover: 'Turnover', payout: 'Withdrawal requested', m2m_realised: 'Realised M2M', m2m_unrealised: 'Unrealised M2M', delivery: 'Delivery' };
const nice = k => LABELS[k] || k.replace(/_/g, ' ').replace(/^./, c => c.toUpperCase());
function holdDetail(r) {
  const x = r.detail; if (!x) return '';
  const q = v => v == null ? '–' : v;
  const f = (k, v) => `<div><span>${k}</span><b class="mono">${v}</b></div>`;
  return `<details class="hdet"><summary>Details</summary><div class="facts">
    ${f('Exchange · product', esc((x.exchange || '–') + ' · ' + (x.product || '–')))}${f('ISIN', esc(x.isin || '–'))}
    ${f('Settled qty', q(x.settled_qty))}${f('T1 qty (not yet settled)', q(x.t1_qty))}
    ${f('Opening qty', q(x.opening_qty))}${f('Realised qty', q(x.realised_qty))}
    ${f('Used today (sold)', q(x.used_qty))}${f('Pledged / collateral qty', q(x.collateral_qty) + (x.collateral_type ? ' · ' + esc(x.collateral_type) : ''))}
    ${f('Authorised to sell (TPIN)', q(x.authorised_qty) + (x.authorised_date ? ' · ' + esc(String(x.authorised_date).slice(0, 10)) : ''))}${f("Yesterday's close", x.close != null ? inr(x.close) : '–')}
    ${f('Day change', x.day_change != null ? inr(x.day_change) + (x.day_change_pct != null ? ' (' + sgn(x.day_change_pct) + ')' : '') : '–')}${f('P&amp;L as Zerodha shows it', x.zerodha_pnl != null ? inr(x.zerodha_pnl, 0) : '–')}
    ${x.mtf ? f('MTF (margin trading)', esc(Object.entries(x.mtf).map(([k, v]) => nice(k) + ' ' + v).join(', '))) : ''}
    ${x.discrepancy ? f('Data check', '<span class="down">Zerodha flags a quantity mismatch</span>') : ''}</div></details>`;
}
// Latest-news column on My holdings: newest headlines per stock, green = positive, red = negative
async function holdNews(my) {
  let d; try { d = await api('/api/news?holdings=1'); } catch (e) { d = null; }
  if (my !== S.nav) return;
  const by = {}; (d ? d.watch : []).forEach(w => { by[w.symbol] = w; });
  view.querySelectorAll('td[data-hn]').forEach(td => {
    const w = by[td.dataset.hn];
    if (!w || w.error || !w.items.length) { td.innerHTML = `<span class="muted">${w && w.error ? 'Unavailable' : 'No news in 3 days'}</span>`; return; }
    const tones = { pos: 0, neg: 0 }; w.items.forEach(i => { if (tones[i.tone] != null) tones[i.tone]++; });
    td.innerHTML = w.items.slice(0, 2).map(i => `<a class="tone-${i.tone || 'neu'}" href="${esc(i.link)}" target="_blank" rel="noopener noreferrer" title="${esc(i.source)} · ${ago(i.ts)}">${esc(i.title)}</a>`).join('')
      + `<small><a href="#/news/${encodeURIComponent(w.symbol)}">${w.items.length} in 3 days</a>${tones.pos ? ` · <span class="up">${tones.pos} positive</span>` : ''}${tones.neg ? ` · <span class="down">${tones.neg} negative</span>` : ''}</small>`;
  });
}
async function extrasBox(box) {
  if (!box) return;
  let x; try { x = await api('/api/kite/extras'); } catch (e) { box.innerHTML = failBox(e); return; }
  const money = v => (v < 0 ? '−' : '+') + inr(Math.abs(v), 0);
  const f = x.funds, mfv = x.mfs.reduce((a, m) => a + m.value, 0), mfc = x.mfs.reduce((a, m) => a + m.cost, 0);
  box.innerHTML = `${f ? `<div class="kv" style="margin:0 0 14px"><div><span>Funds available (equity)</span><b>${f.net != null ? inr(f.net, 0) : '–'}</b></div><div><span>Cash balance</span><b>${f.cash != null ? inr(f.cash, 0) : '–'}</b></div>
      <div><span>Mutual funds value</span><b>${inr(mfv, 0)}</b></div><div class="${mfv - mfc >= 0 ? 'tile-up' : 'tile-down'}"><span>Mutual funds profit / loss</span><b>${money(mfv - mfc)}${mfc ? ' (' + sgn((mfv / mfc - 1) * 100) + ')' : ''}</b></div></div>` : ''}
    <div class="card"><h2>Open positions · ${x.positions.length}</h2>${x.positions.length ? `<div class="tablewrap"><table><thead><tr><th>Stock</th><th>Product</th><th class="num">Qty</th><th class="num">Avg</th><th class="num">Price</th><th class="num">P&amp;L</th></tr></thead><tbody>
      ${x.positions.map(p => `<tr><td class="mono"><b>${esc(p.symbol)}</b><small class="muted" style="display:block">${esc(p.exchange || '')}${p.overnight_qty ? ' · overnight ' + p.overnight_qty : ''}${p.day_buy || p.day_sell ? ' · today +' + (p.day_buy || 0) + ' / −' + (p.day_sell || 0) : ''}${p.realised ? ' · realised ' + inr(p.realised, 0) : ''}</small></td><td>${esc(p.product || '')}</td><td class="num">${p.qty}</td><td class="num">${p.avg != null ? inr(p.avg) : '–'}</td><td class="num">${p.ltp != null ? inr(p.ltp) : '–'}</td><td class="num ${cls(p.pnl)}">${money(p.pnl)}</td></tr>`).join('')}</tbody></table></div>`
      : '<div class="empty">No open intraday or overnight positions.</div>'}</div>
    <div class="card"><h2>Mutual funds (Coin) · ${x.mfs.length}</h2>${x.mfs.length ? `<div class="tablewrap"><table><thead><tr><th>Fund</th><th class="num">Units</th><th class="num">Avg NAV</th><th class="num">NAV</th><th class="num">Value</th><th class="num">Profit / loss</th></tr></thead><tbody>
      ${x.mfs.map(m => `<tr><td>${esc(m.fund)}<small class="muted" style="display:block">NAV date ${esc(m.nav_date || '–')}</small></td><td class="num">${m.units.toFixed(3)}</td><td class="num">${inr(m.avg)}</td><td class="num">${inr(m.nav)}</td><td class="num">${inr(m.value, 0)}</td>
        <td class="num ${cls(m.pnl)}">${money(m.pnl)}<small class="chg" style="display:block">${m.pnl_pct != null ? sgn(m.pnl_pct) : ''}</small></td></tr>`).join('')}</tbody></table></div>`
      : '<div class="empty">No mutual funds in Coin.</div>'}</div>
    ${Object.keys(x.margins || {}).length ? `<div class="card"><h2>Funds and margins</h2><div class="grid2">${Object.entries(x.margins).map(([seg, m]) => `<div>
      <h2 style="margin-bottom:8px">${seg === 'equity' ? 'Equity' : 'Commodity'}${m.enabled === false ? ' · not enabled' : ''} · net ${m.net != null ? inr(m.net, 0) : '–'}</h2>
      <div class="facts" style="grid-template-columns:1fr">${Object.entries(m.available).map(([k, v]) => `<div><span>${esc(nice(k))}</span><b class="mono">${inr(v, 0)}</b></div>`).join('')}
      ${Object.entries(m.utilised).filter(([, v]) => v).map(([k, v]) => `<div><span>Used · ${esc(nice(k))}</span><b class="mono">${inr(v, 0)}</b></div>`).join('')}</div></div>`).join('')}</div></div>` : ''}
    ${x.profile ? `<div class="card"><h2>Zerodha account</h2><div class="facts">
      <div><span>Name</span><b>${esc(x.profile.name || '–')}</b></div><div><span>Client ID</span><b class="mono">${esc(x.profile.user_id || '–')}</b></div>
      <div><span>Broker · account type</span><b>${esc((x.profile.broker || '–') + ' · ' + (x.profile.type || '–'))}</b></div><div><span>Demat consent</span><b>${esc(x.profile.demat_consent || '–')}</b></div>
      <div><span>Exchanges</span><b>${esc(x.profile.exchanges || '–')}</b></div><div><span>Products</span><b>${esc(x.profile.products || '–')}</b></div></div>
      <p class="note" style="margin-top:8px">Read-only. The portal cannot place, change or cancel orders.</p></div>` : ''}
    ${x.errors.length ? `<p class="note down">${x.errors.map(esc).join(' · ')}</p>` : ''}`;
  makeCollapsible(box);
}

/* My holdings: every block below the holdings table can be collapsed; the choice is remembered */
function makeCollapsible(root) {
  let saved = {}; try { saved = JSON.parse(localStorage.getItem('ts.fold') || '{}'); } catch (e) { /* ignore */ }
  root.querySelectorAll('.card').forEach(card => {
    const h = card.querySelector('h2'); if (!h || card.dataset.fold) return;
    const key = h.textContent.replace(/[·\d,]+/g, '').trim().slice(0, 40);
    card.dataset.fold = key;
    const btn = document.createElement('button');
    btn.type = 'button'; btn.className = 'btn sm foldbtn';
    const set = shut => { card.classList.toggle('folded', shut); btn.textContent = shut ? 'Expand ▾' : 'Collapse ▴'; btn.setAttribute('aria-expanded', String(!shut)); };
    btn.onclick = () => { const shut = !card.classList.contains('folded'); set(shut); saved[key] = shut; try { localStorage.setItem('ts.fold', JSON.stringify(saved)); } catch (e) { /* ignore */ } };
    card.insertBefore(btn, card.firstChild);
    set(/^Holdings/i.test(key) ? false : !!saved[key]);   // Holdings always opens expanded
  });
}


/* ---------------------------------------------------------------- click a column heading to sort (every table) */
function cellVal(td) {
  const raw = (td ? td.innerText : '').trim().replace(/\s+/g, ' ');
  // dates (2026-04-29, 2026-04-29 10:03, 2026-11-19 12:11:07) and times (09:40) sort as text, oldest first
  const dt = raw.match(/^(\d{4}-\d{2}-\d{2})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?/);
  if (dt) return dt[1] + ' ' + (dt[2] ? dt[2].padStart(2, '0') + ':' + dt[3] + ':' + (dt[4] || '00') : '00:00:00');
  const tm = raw.match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?(?!\d)/);
  if (tm) return tm[1].padStart(2, '0') + ':' + tm[2] + ':' + (tm[3] || '00');
  const t = (td ? td.innerText : '').trim().split('\n')[0].replace(/[₹,\s]/g, '').replace(/−/g, '-').replace(/[%RL]|pts|cr|d$/g, '');
  const n = parseFloat(t);
  return /^[+-]?\d/.test(t) && !isNaN(n) ? n : (td ? td.innerText.trim().toLowerCase() : '');
}
document.addEventListener('click', e => {
  const th = e.target.closest && e.target.closest('thead th');
  if (!th || !th.innerText.trim()) return;
  const table = th.closest('table'), tbody = table.tBodies[0]; if (!tbody) return;
  const col = [...th.parentNode.children].indexOf(th);
  const dir = th.dataset.dir === 'asc' ? 'desc' : 'asc';
  table.querySelectorAll('thead th').forEach(x => { delete x.dataset.dir; });
  th.dataset.dir = dir;
  [...tbody.rows].forEach((r, i) => { if (r.dataset.oi == null) r.dataset.oi = i; });   // remember the system order
  const rows = [...tbody.rows].filter(r => r.cells.length > col);
  rows.sort((a, b) => {
    const x = cellVal(a.cells[col]), y = cellVal(b.cells[col]);
    const c = typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y));
    return dir === 'asc' ? c : -c;
  });
  rows.forEach(r => tbody.appendChild(r));
});

/* Default order: back to the system's own ranking. Search: hide rows that do not match. */
document.addEventListener('click', e => {
  const b = e.target.closest && e.target.closest('[data-sortreset]'); if (!b) return;
  const table = b.closest('.card')?.querySelector('table'); const tbody = table && table.tBodies[0]; if (!tbody) return;
  table.querySelectorAll('thead th').forEach(x => { delete x.dataset.dir; });
  [...tbody.rows].filter(r => r.dataset.oi != null).sort((x, y) => x.dataset.oi - y.dataset.oi).forEach(r => tbody.appendChild(r));
});
document.addEventListener('input', e => {
  const inp = e.target.closest && e.target.closest('[data-tfind]'); if (!inp) return;
  const q = inp.value.trim().toLowerCase(), tbody = inp.closest('.card')?.querySelector('tbody'); if (!tbody) return;
  [...tbody.rows].forEach(r => { if (r.cells.length > 1) r.hidden = !!q && !r.innerText.toLowerCase().includes(q); });
});


/* ---------------------------------------------------------------- scrolling index strip */
async function tickerLoad() {
  let d; try { d = await api('/api/indices'); } catch (e) { return; }
  const box = $('#ticker'), run = $('#tkRun'); if (!box || !d.rows.length) return;
  const open = d.clock && d.clock.open;
  box.querySelector('.tk-live b').textContent = open ? 'Live' : 'Closed';
  box.classList.toggle('closed', !open);
  // stock names link to their prediction page (index / world names are not single stocks)
  const item = r => `<span class="tk-it">${r.link ? `<a class="tk-a" href="#/predictor/${encodeURIComponent(r.name)}" title="Open ${esc(r.name)}">${esc(r.name)}</a>` : `<b>${esc(r.name)}</b>`} ${r.price.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
    ${r.pct == null ? '' : `<span class="${r.pct >= 0 ? 'up' : 'down'}">${r.pct >= 0 ? '▲ +' : '▼ '}${r.pct.toFixed(2)}%</span>`}</span>`;
  // each line holds its items twice for a seamless loop; the duration follows the line's length,
  // so all three lines move at the same speed on screen
  const fill = (el, list) => {
    if (!el) return;
    const sig = list.map(r => r.name).join('|');
    if (el.dataset.sig === sig && el.children.length === list.length * 2) {
      // same items: update the numbers in place so the scroll keeps going instead of restarting
      [...el.children].forEach((sp, k) => { const r = list[k % list.length]; const tmp = document.createElement('span'); tmp.innerHTML = item(r); sp.innerHTML = tmp.firstElementChild.innerHTML; });
      el.dataset.kept = '1';
      return;
    }
    const html = list.map(item).join('');
    el.innerHTML = html + html;
    el.dataset.sig = sig; el.dataset.kept = '';
    el.closest('.tk-line').hidden = !list.length;
  };
  fill($('#tkN50'), (d.nifty50 || []).map(r => Object.assign({ link: true }, r))); fill(run, d.rows); fill($('#tkWorld'), d.world || []);
  // your Zerodha holdings: only while Zerodha is connected (hidden otherwise)
  if (Date.now() - (S.heldAt || 0) > 60000) await loadHeld();
  const mine = heldSyms().length ? (S.held.items || []).filter(h => h.ltp).map(h => ({ name: h.symbol, price: h.ltp, pct: h.day_pct, link: true })) : [];
  const mineEl = $('#tkMine'); if (mineEl) { fill(mineEl, mine); mineEl.closest('.tk-line').hidden = !mine.length; }
  box.hidden = false;
  setTimeout(() => box.querySelectorAll('.tk-run').forEach(el => {
    if (el.dataset.kept) return;   // numbers updated in place: keep the running speed
    el.style.animationDuration = Math.max(20, el.scrollWidth / 2 / TK_SPEED) + 's';
  }), 50);
}
const TK_SPEED = 45;   // pixels per second, same for every line

/* show / hide each ticker line (remembered on this device) */
const TK_OFF_KEY = 'ts.tkoff';
let TK_OFF = null;   // kept in memory too, so hiding works even where storage is blocked
function tkOffList() {
  if (!TK_OFF) { try { TK_OFF = JSON.parse(localStorage.getItem(TK_OFF_KEY) || '[]'); } catch (e) { TK_OFF = []; } }
  if (!Array.isArray(TK_OFF)) TK_OFF = [];
  return TK_OFF;
}
function tkToggles() {
  const off = tkOffList();
  document.querySelectorAll('#ticker .tk-line').forEach(line => {
    const run = line.querySelector('.tk-run'), tag = line.querySelector('.tk-tag');
    if (!run || !tag) return;
    const id = run.id;
    if (!tag.querySelector('.tk-eye')) {
      const label = tag.textContent.trim();
      tag.innerHTML = `<span class="tk-name">${esc(label)}</span><button type="button" class="tk-eye" data-tk="${esc(id)}"></button>`;
      line.querySelector('.tk-view').insertAdjacentHTML('afterend', `<button type="button" class="tk-stub" data-tk="${esc(id)}">${esc(label)} line hidden · click to show</button>`);
    }
    const isOff = off.includes(id);
    line.classList.toggle('off', isOff);
    const eye = tag.querySelector('.tk-eye');
    eye.textContent = isOff ? '◌' : '◉';
    eye.title = (isOff ? 'Show the ' : 'Hide the ') + tag.querySelector('.tk-name').textContent + ' line';
    eye.setAttribute('aria-pressed', String(!isOff));
  });
}
document.addEventListener('click', e => {
  const b = e.target.closest && e.target.closest('#ticker [data-tk]');
  if (!b) return;
  e.preventDefault();
  const id = b.dataset.tk, off = tkOffList(), i = off.indexOf(id);
  if (i >= 0) off.splice(i, 1); else off.push(id);
  try { localStorage.setItem(TK_OFF_KEY, JSON.stringify(off)); } catch (err) { /* storage blocked: works until reload */ }
  tkToggles();
});
addEventListener("load", () => { tkToggles(); tickerLoad(); setInterval(tickerLoad, 60000); });


/* ---------------------------------------------------------------- Telegram (send-only) on the Limits page */
// when each Telegram message goes out, and its group (shown in the settings table)
const TG_WHEN = {
  hello: ['On NAS start', 'System'], morning: ['First start after 06:00', 'Morning'], update: ['08:45 if changed', 'Morning'],
  login: ['From 07:00, every 30 min', 'Zerodha'], signin: ['First login of the day', 'Zerodha'], plan: ['09:32', 'Market'],
  stopalert: ['Market hours', 'Alerts'], move: ['Market hours', 'Alerts'], alert: ['When it rings', 'Alerts'],
  zerodha: ['Within ~2 min', 'Zerodha'], paper: ['When it happens', 'Paper'], close: ['15:32', 'Market'], eod: ['15:35', 'Market'],
  weekly: ['Sunday 10:00', 'Weekly'], gtt: ['When you save a GTT', 'Paper'],
};
function tgCollapsed() { try { return localStorage.getItem('ts.tgCollapsed') === '1'; } catch (e) { return false; } }
async function tgCard(box) {
  if (!box) return;
  let d; try { d = await api('/api/telegram'); } catch (e) { box.innerHTML = '<h2>Telegram notifications</h2>' + failBox(e); return; }
  const steps = `<ol class="note" style="line-height:1.8;margin:6px 0 12px 18px">
      <li>In Telegram, open <b>@BotFather</b> (blue tick), send <code>/newbot</code>, choose a name and a username ending in <code>bot</code>.</li>
      <li>Open your new bot from BotFather's link and press <b>Start</b>.</li>
      <li>Put the token BotFather gave you in <code>tradeskill.env</code> on the NAS as <code>TELEGRAM_BOT_TOKEN=...</code>, then Stop → Build → Start the project.
        (On a PC copy: save it alone in <code>data/telegram_token.txt</code> and restart.)</li>
      <li>Come back here and click <b>Connect</b>.</li></ol>`;
  let body;
  if (!d.token_set) body = `<p class="note">No bot token found yet.</p>${steps}`;
  else if (!d.connected) body = `<p class="note">Bot token found. Press <b>Start</b> on your bot in Telegram, then:</p>
      <div class="row" style="margin-top:10px"><button class="btn primary" id="tgConn">Connect</button></div>`;
  else body = `<div class="row" style="margin-bottom:12px"><span class="pill pass">Connected to ${esc(d.name || 'you')}</span>
      <button class="btn sm" id="tgTest">Send test message</button><button class="btn sm" id="tgOff">Disconnect</button>
      ${d.last_sent ? `<span class="note">Last message ${esc(d.last_sent.slice(5, 16))}</span>` : ''}</div>
      <div class="row tablebar" style="margin:0 0 10px"><span class="note" style="margin:0">${d.kinds.filter(([k]) => d.on[k]).length} of ${d.kinds.length} switched on</span>
        <button class="btn sm" data-tgall="1">All on</button><button class="btn sm" data-tgall="0">All off</button></div>
      <div class="tablewrap"><table class="tgtable"><thead><tr><th class="num">#</th><th>Message</th><th>When</th><th>Group</th><th class="num">On / off</th></tr></thead><tbody>
      ${d.kinds.map(([k, l], i) => { const w = TG_WHEN[k] || ['', 'Other']; const what = l.replace(/^\d\d:\d\d\s*/, '');
        return `<tr><td class="num muted">${i + 1}</td><td>${esc(what)}</td><td class="mono">${esc(w[0])}</td><td><span class="pill">${esc(w[1])}</span></td>
        <td class="num"><label class="switch" title="${d.on[k] ? 'On' : 'Off'}"><input type="checkbox" data-tg="${k}" ${d.on[k] ? 'checked' : ''}><span></span></label></td></tr>`; }).join('')}
      </tbody></table></div>`;
  box.innerHTML = `<div class="row" style="justify-content:space-between;margin-bottom:12px"><h2 style="margin:0">Telegram notifications</h2>
      <button class="btn sm" data-collapse="tg">${tgCollapsed() ? 'Expand ▼' : 'Collapse ▲'}</button></div><div class="cbody" ${tgCollapsed() ? 'hidden' : ''}>${body}
    ${d.last_error ? `<p class="note down" style="margin-top:8px">Last send failed: ${esc(d.last_error)}</p>` : ''}
    <p class="note" style="margin-top:10px">Send-only: the bot messages you but cannot read commands, buy or sell. Alerts, GTTs and paper exits are checked every 30 seconds in market hours even with no page open.</p></div>`;
  const act = async (path, body, msg) => { try { await api(path, body || {}); if (msg) toast(msg); tgCard(box); } catch (e) { toast(e.message, 'bad'); } };
  const cb = box.querySelector('[data-collapse]'); if (cb) cb.onclick = () => { try { localStorage.setItem('ts.tgCollapsed', tgCollapsed() ? '0' : '1'); } catch (e) { /* ignore */ } tgCard(box); };
  box.querySelectorAll('[data-tgall]').forEach(b => b.onclick = () => act('/api/telegram/settings', { on: Object.fromEntries(d.kinds.map(([k]) => [k, b.dataset.tgall === '1'])) },
    b.dataset.tgall === '1' ? 'All Telegram messages switched on.' : 'All Telegram messages switched off.'));
  holidayBox(box);
  const c = $('#tgConn'); if (c) c.onclick = () => act('/api/telegram/connect', {}, 'Telegram connected. Check your phone for the test message.');
  const tt = $('#tgTest'); if (tt) tt.onclick = () => act('/api/telegram/test', {}, 'Test message sent.');
  const off = $('#tgOff'); if (off) off.onclick = () => act('/api/telegram/disconnect', {}, 'Telegram disconnected.');
  box.querySelectorAll('[data-tg]').forEach(x => x.onchange = () => act('/api/telegram/settings', { on: { [x.dataset.tg]: x.checked } }));
}


/* ---------------------------------------------------------------- Notifications: schedule, run now, full history */
// every message type, in the order of the day (matches the Telegram settings table)
const NKIND = { hello: 'NAS start greeting', morning: 'Morning plan (first start after 06:00)', update: '08:45 update (if changed)',
  login: 'Zerodha login link', signin: 'Zerodha sign-in summary', plan: '09:32 Day plan', stopalert: 'Below rule stop', move: 'Big market move',
  alert: 'Price alert', zerodha: 'Zerodha buy/sell', paper: 'Paper trade', close: '15:32 Market close', eod: '15:35 Your holdings',
  weekly: 'Sunday 10:00 weekly', gtt: 'GTT saved' };
const NRUN = ['morning', 'update', 'login', 'signin', 'plan', 'close', 'eod', 'weekly'];
async function notifPage() {
  const my = S.nav;
  view.innerHTML = head('Notifications', 'Scheduled reports and every message the portal has sent or tried to send.') + loading(2);
  let d, err; try { d = await api('/api/notify_log?limit=1000'); } catch (e) { err = e; }
  if (my !== S.nav) return;
  if (err) { view.innerHTML = head('Notifications', '') + failBox(err); return; }
  let f = 'all', q = '';
  const draw = () => {
    const rows = d.rows.filter(r => (f === 'all' || r.kind === f) && (!q || r.text.toLowerCase().includes(q)));
    const chips = [['all', 'All']].concat(Object.entries(NKIND)).map(([k, l]) => `<button class="chip ${f === k ? 'on' : ''}" data-nk="${k}">${esc(l)}</button>`).join('');
    view.innerHTML = head('Notifications', `${d.total} logged · newest first · market reports run on NSE trading days only`,
      '<a class="btn" href="#/settings">Telegram settings</a>') +
      `<div class="stack"><div class="card"><h2>Run a report now</h2><div class="row" style="flex-wrap:wrap">${NRUN.map(k => `<button class="btn" data-run="${k}">${esc(NKIND[k])}</button>`).join('')}</div>
        <p class="note" style="margin-top:8px">Builds the report from live data right away, logs it here and sends it to Telegram if that kind is switched on. Handy to preview before the scheduled time.</p></div>
      <div class="card"><div class="row tablebar"><input id="nFind" type="search" placeholder="Search messages" value="${esc(q)}" style="width:220px"><div class="chips" style="margin:0">${chips}</div></div>
        ${rows.length ? rows.map(r => `<div class="nlog"><div class="row" style="justify-content:space-between"><b>${esc(NKIND[r.kind] || r.kind)}</b>
          <span class="note">${esc(r.ts)} · <span class="${r.status === 'sent' ? 'up' : r.status === 'failed' ? 'down' : 'muted'}">${esc(r.status)}</span>${r.error ? ' · ' + esc(r.error) : ''}</span></div>
          <pre>${esc(r.text)}</pre></div>`).join('') : '<div class="empty">No messages yet.</div>'}</div></div>`;
    view.querySelectorAll('[data-nk]').forEach(b => b.onclick = () => { f = b.dataset.nk; draw(); });
    const fi = $('#nFind'); fi.oninput = () => { q = fi.value.trim().toLowerCase(); const pos = fi.selectionStart; draw(); const n = $('#nFind'); n.focus(); n.setSelectionRange(pos, pos); };
    view.querySelectorAll('[data-run]').forEach(b => b.onclick = async () => {
      b.disabled = true; b.textContent = 'Building…';
      try { await api('/api/reports/run', { kind: b.dataset.run }); toast('Report built and logged.'); } catch (e) { toast(e.message, 'bad'); }
      notifPage();
    });
  };
  draw();
}

/* holiday list on the Limits page (inside the Telegram box) */
async function holidayBox(box) {
  let st; try { st = await api('/api/status'); } catch (e) { return; }
  const days = (st.settings.holidays || []).join(', ');
  box.insertAdjacentHTML('beforeend', `<form class="row" id="holF" style="margin-top:14px"><label style="flex:1;min-width:260px">NSE holidays (no reports on these dates, YYYY-MM-DD, comma separated)
    <input name="h" value="${esc(days)}" placeholder="2026-12-25, 2027-01-26"></label><button class="btn" style="align-self:flex-end">Save holidays</button></form>`);
  $('#holF').onsubmit = async e => { e.preventDefault(); try { await api('/api/settings/holidays', { holidays: new FormData(e.target).get('h') }); toast('Holidays saved.'); } catch (err) { toast(err.message, 'bad'); } };
}


/* ---------------------------------------------------------------- Restart portal (Limits page) */
async function codeBox(after) {
  let d; try { d = await api('/api/admin/code'); } catch (e) { return; }
  after.insertAdjacentHTML('afterend', `<div class="card" id="codeBox"><h2>Portal program</h2>
    <div class="row"><span class="pill ${d.error ? 'fail' : 'pass'}">${d.error ? 'Code error: still running the last good version' : 'Running'}</span>
    <span class="note">Started ${esc(d.started || '–')} · auto-restart on code changes: ${d.auto_restart ? 'on' : 'off'}</span>
    <button class="btn sm" id="rsBtn">Restart portal</button></div>
    ${d.error ? `<p class="note down" style="margin-top:8px">${esc(d.error)}</p>` : ''}
    <p class="note" style="margin-top:8px">The portal runs the files in the NAS folder directly. Page changes show on a browser refresh; Python changes are checked for errors and picked up within about 10 seconds. Use the button if you want to restart by hand.</p></div>`);
  $('#rsBtn').onclick = async () => {
    try { const r = await api('/api/admin/restart', {}); toast(r.message); setTimeout(() => location.reload(), 6000); }
    catch (e) { toast(e.message, 'bad'); }
  };
}

/* ---------------------------------------------------------------- History: everything in one place (replaces Notifications) */
const HCAT = [['all', 'All'], ['order', 'Paper orders'], ['gtt', 'GTT'], ['alert', 'Alerts'], ['message', 'Messages'], ['action', 'Your actions']];
const HICON = { order: '₹', gtt: '🎯', alert: '🔔', message: '✉', action: '✎' };
async function historyPage() {
  const my = S.nav;
  view.innerHTML = head('History', 'Everything in the portal: your paper orders, GTTs, alerts, Telegram messages and your actions.') + loading(3);
  let d, err; try { d = await api('/api/history'); } catch (e) { err = e; }
  if (my !== S.nav) return;
  if (err) { view.innerHTML = head('History', '') + failBox(err); return; }
  let f = S.histCat || 'all', q = '', mf = 'all';
  const statusCls = s => /sent|win|triggered|done/.test(s || '') ? 'pass' : /fail|loss|rejected|error/.test(s || '') ? 'fail' : /active|open/.test(s || '') ? 'warn' : '';
  const draw = () => {
    const rows = d.rows.filter(r => (f === 'all' || r.cat === f) && (mf === 'all' || r.mode === mf)
      && (!q || (r.title + ' ' + (r.detail || '')).toLowerCase().includes(q)));
    const chips = HCAT.map(([k, l]) => `<button class="chip ${f === k ? 'on' : ''}" data-hc="${k}">${esc(l)}${k !== 'all' ? ` <small class="muted">${d.counts[k] || 0}</small>` : ''}</button>`).join('');
    const mchips = [['all', 'All modes'], ['intraday', 'Scalping'], ['swing', 'Trading'], ['invest', 'Investing']]
      .map(([k, l]) => `<button class="chip ${mf === k ? 'on' : ''}" data-hm="${k}">${l}</button>`).join('');
    view.innerHTML = head('History', `${d.total} records · newest first · kept permanently on the NAS`,
      '<button class="btn" id="hCsv">Download CSV</button><a class="btn" href="#/settings">Telegram settings</a>') +
      `<div class="stack">
      ${f === 'message' ? `<div class="card"><h2>Run a report now</h2><div class="row" style="flex-wrap:wrap">${NRUN.map(k => `<button class="btn" data-run="${k}">${esc(NKIND[k])}</button>`).join('')}</div>
        <p class="note" style="margin-top:8px">Builds the message from live data right away, logs it here and sends it to Telegram if that kind is switched on.</p></div>` : ''}
      <div class="card"><div class="row tablebar"><input id="hSearch" type="search" placeholder="Search history" value="${esc(q)}" style="width:220px">
        <div class="chips" style="margin:0">${chips}</div></div>
        <div class="row tablebar"><div class="chips" style="margin:0">${mchips}</div><span class="note" style="margin:0">${rows.length} shown</span>
          <button class="btn sm" data-sortreset>Default order</button></div>
        ${rows.length ? `<div class="tablewrap"><table class="htable"><thead><tr><th>When (IST)</th><th>Type</th><th>Mode</th><th>What</th><th>Status</th></tr></thead><tbody>
        ${rows.slice(0, 1500).map(r => `<tr><td class="mono" style="white-space:nowrap">${esc((r.ts || '').slice(0, 16))}</td>
          <td><span class="pill">${HICON[r.cat] || ''} ${esc((HCAT.find(c => c[0] === r.cat) || [0, r.cat])[1])}${r.kind ? ' · ' + esc(NKIND[r.kind] || r.kind) : ''}</span></td>
          <td>${esc(r.mode_label || '–')}</td>
          <td><b>${esc(r.title)}</b>${r.detail && r.detail !== r.title ? `<details><summary class="muted">details</summary><pre class="hpre">${esc(r.detail)}</pre></details>` : ''}</td>
          <td><span class="pill ${statusCls(r.status)}">${esc(r.status || '')}</span>${r.error ? `<small class="down" style="display:block">${esc(r.error)}</small>` : ''}</td></tr>`).join('')}
        </tbody></table></div>${rows.length > 1500 ? '<p class="note">Showing the newest 1,500. Search or filter to narrow down, or download the CSV for everything.</p>' : ''}`
        : '<div class="empty">Nothing here yet.</div>'}</div></div>`;
    view.querySelectorAll('[data-hc]').forEach(b => b.onclick = () => { f = S.histCat = b.dataset.hc; draw(); });
    view.querySelectorAll('[data-hm]').forEach(b => b.onclick = () => { mf = b.dataset.hm; draw(); });
    const si = $('#hSearch'); si.oninput = () => { q = si.value.trim().toLowerCase(); const pos = si.selectionStart; draw(); const n = $('#hSearch'); n.focus(); n.setSelectionRange(pos, pos); };
    view.querySelectorAll('[data-run]').forEach(b => b.onclick = async () => {
      b.disabled = true; b.textContent = 'Building…';
      try { await api('/api/reports/run', { kind: b.dataset.run }); toast('Report built and logged.'); } catch (e) { toast(e.message, 'bad'); }
      historyPage();
    });
    $('#hCsv').onclick = () => {
      const cell = v => '"' + String(v == null ? '' : v).replace(/"/g, '""') + '"';
      const csv = ['When,Type,Kind,Mode,What,Status,Details'].concat(d.rows.map(r => [r.ts, r.cat, r.kind || '', r.mode_label || '', r.title, r.status || '', r.detail || ''].map(cell).join(','))).join('\r\n');
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' }));
      a.download = 'tradeskill-history-' + new Date().toISOString().slice(0, 10) + '.csv'; a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    };
  };
  draw();
}
