'use strict';
/* ---------------------------------------------------------------- My scanner: your own lists, plan, GTT, exits */
const MY = { lists: null, notes: {}, cache: {}, spark: {} };
try { MY.list = localStorage.getItem('ts.mylist') || null; MY.src = localStorage.getItem('ts.mysrc') || 'list'; } catch (e) { MY.src = 'list'; }
const mySave = () => { try { localStorage.setItem('ts.mylist', MY.list || ''); localStorage.setItem('ts.mysrc', MY.src); } catch (e) { /* ignore */ } };
const myActive = () => (MY.lists || []).find(l => l.id === MY.list) || (MY.lists || [])[0];

async function myLoad() {
  try { const d = await api('/api/mylists'); MY.lists = d.lists; MY.notes = d.notes; } catch (e) { MY.lists = MY.lists || []; }
  myStars();
}
function starBtn(sym, big) {
  const l = myActive(), on = !!(l && l.symbols.includes(sym));
  return `<button type="button" class="${big ? 'btn' : 'star'} ${on ? 'on' : ''}" data-star="${esc(sym)}" title="${on ? 'Remove from' : 'Add to'} ${esc(l ? l.name : 'My list')}">${on ? '★' : '☆'}${big ? (on ? ' In ' : ' Add to ') + esc(l ? l.name : 'My list') : ''}</button>`;
}
function myStars() {
  const l = myActive();
  document.querySelectorAll('[data-star]').forEach(b => {
    const on = !!(l && l.symbols.includes(b.dataset.star)), big = b.classList.contains('btn');
    b.classList.toggle('on', on); b.textContent = (on ? '★' : '☆') + (big ? (on ? ' In ' : ' Add to ') + (l ? l.name : 'My list') : '');
    b.title = (on ? 'Remove from ' : 'Add to ') + (l ? l.name : 'My list');
  });
}
async function myAct(body, quiet) {
  const d = await api('/api/mylists', Object.assign({ list: (myActive() || {}).id || 'main' }, body));
  MY.lists = d.lists; MY.notes = d.notes; if (d.list) MY.list = d.list; mySave(); MY.cache = {};
  if (!quiet && d.message) toast(d.message);
  myStars(); return d;
}
// capture phase: a star inside a clickable row must not open the Predictor
document.addEventListener('click', async e => {
  const b = e.target.closest && e.target.closest('[data-star]');
  if (!b) return;
  e.preventDefault(); e.stopPropagation();
  const sym = b.dataset.star, l = myActive();
  if (!MY.lists) await myLoad();
  try { await myAct({ action: l && l.symbols.includes(sym) ? 'remove' : 'add', symbols: [sym] }); } catch (err) { toast(err.message, 'bad'); }
}, true);

const MYSTATE = { exit: ['fail', 'Exit signal'], buy: ['pass', 'Buy zone'], near: ['warn', 'Near trigger'], holding: ['hold', 'Holding'], watching: ['', 'Watching'] };

async function myScanPage() {
  const my = S.nav, long = S.mode !== 'intraday';
  if (!MY.lists) await myLoad();
  if (my !== S.nav) return;
  let filt = 'all';
  const key = () => [S.mode, (myActive() || {}).id, MY.src].join('|');

  const draw = d => {
    setClock(d.clock);
    const l = myActive(), inv = S.mode === 'invest';
    const rowsAll = d.rows;
    const best = r => d.regime && ['confirmed', 'recent'].includes(r.status) && r.rs_pct >= 50;
    const rows = rowsAll.filter(r => filt === 'all' || (filt === 'up' ? (inv ? r.up_long : (r.up_mid ?? r.trend_up)) : filt === 'rs' ? r.rs_pct >= 80 : filt === 'best' ? best(r) : r.state === filt));
    const count = k => rowsAll.filter(r => r.state === k).length;
    const tabs = MY.lists.map(x => `<button class="chip ${x.id === l.id ? 'on' : ''}" data-list="${esc(x.id)}">${esc(x.name)} <small>${x.symbols.length}</small></button>`).join('') +
      '<button class="chip" id="myNew">＋ New list</button>';
    const srcs = [['list', 'My list'], ['holdings', '◉ My holdings'], ['both', 'List + holdings']].map(([k, t]) =>
      `<button type="button" data-src="${k}" class="${MY.src === k ? 'on' : ''}" ${k !== 'list' && !d.held_connected ? 'disabled title="Zerodha is not connected"' : ''}>${t}</button>`).join('') + '<button type="button" data-src="all">All 250 →</button>';
    const fchips = [['all', 'All'], ['buy', `Buy zone ${count('buy')}`], ['near', `Near trigger ${count('near')}`], ['holding', `Holding ${count('holding')}`], ['exit', `Exit signal ${count('exit')}`],
      ['up', 'Uptrend'], ...(long ? [['rs', 'Top 20% strength'], ['best', '★ Best odds']] : [])].map(([k, t]) => `<button class="chip ${filt === k ? 'on' : ''}" data-f="${k}">${t}</button>`).join('');
    const c = d.capacity, bar = (v, m) => `<div class="capbar"><i style="width:${Math.min(100, m ? v / m * 100 : 0).toFixed(0)}%" class="${m && v / m >= 0.9 ? 'full' : ''}"></i></div>`;
    const cap = c && long ? `<div class="card capgrid">
      <div><span>Positions</span><b>${c.positions} / ${c.max_positions}</b>${bar(c.positions, c.max_positions)}</div>
      <div><span>Money in stocks</span><b>${inr(c.invested, 0)} / ${inr(c.capital, 0)}</b>${bar(c.invested, c.capital)}</div>
      <div><span>Open risk</span><b>${inr(c.open_risk, 0)} / ${inr(c.max_open_risk, 0)}</b>${bar(c.open_risk, c.max_open_risk)}</div>
      <div><span>Paper cash</span><b>${inr(c.cash, 0)}</b><small class="${c.drawdown >= c.dd_pause ? 'down' : 'muted'}">${c.drawdown.toFixed(1)}% below peak · pause at ${c.dd_pause}%</small></div></div>` : '';
    const stateCell = r => {
      const [k, t] = MYSTATE[r.state] || ['', r.state];
      let sub = '';
      if (r.paper && long) {
        const p = r.paper;
        sub = `Paper ${p.qty} @ ${inr(p.entry)} · stop ${inr(p.stop)}${p.trailing ? ' (trailing)' : ''} · ${p.r_now != null ? (p.r_now >= 0 ? '+' : '') + p.r_now.toFixed(1) + 'R' : ''} · day ${p.held}/${p.hold}${p.r_now != null && p.r_now < (S.mode === 'invest' ? 1 : 2) ? ' · break-even at ' + inr(p.be_level) : ''}${p.below200 ? ' · <b class="down">closed below 200-day</b>' : ''}`;
      } else if (r.paper) sub = `Paper ${r.paper.qty} · stop ${inr(r.paper.stop)} · target ${inr(r.paper.target)}`;
      if (r.zerodha) {
        const z = r.zerodha;
        sub += `${sub ? '<br>' : ''}Zerodha ${z.qty} sh${z.pnl_pct != null ? ' · ' + pct(z.pnl_pct, 1) : ''}${z.rule_stop ? ' · rule stop ' + inr(z.rule_stop) : ''}${z.why ? ' · ' + esc(z.why) : ''}`;
      }
      if (r.state === 'buy' && r.status === 'provisional') sub = (sub ? sub + '<br>' : '') + 'Today: confirm at the close';
      return `<span class="pill ${k}">${t}</span>${sub ? `<small class="cellsub">${sub}</small>` : ''}`;
    };
    const tags = r => {
      const out = [];
      if (r.results && r.results.days >= -5 && r.results.days <= 7) out.push(`<span class="tag warn" title="Estimated from the last reported quarter">⚠ results ~${new Date(r.results.date).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}</span>`);
      if (long && r.sector_held >= r.sector_max && r.state !== 'holding') out.push(`<span class="tag warn" title="${esc(r.industry)}">⚠ sector full ${r.sector_held}/${r.sector_max}</span>`);
      if (!r.in_250) out.push('<span class="tag">outside 250</span>');
      if (MY.notes[r.symbol]) out.push(`<span class="tag note-tag" title="${esc(MY.notes[r.symbol])}">✎ ${esc(MY.notes[r.symbol].slice(0, 28))}${MY.notes[r.symbol].length > 28 ? '…' : ''}</span>`);
      return out.length ? `<div class="row" style="gap:4px;margin-top:3px">${out.join('')}</div>` : '';
    };
    const inList = r => l.symbols.includes(r.symbol);
    const tbody = rows.map(r => `<tr class="click" data-s="${esc(r.symbol)}" tabindex="0">
      <td class="sym" data-spark="${esc(r.symbol)}">${starBtn(r.symbol)}<b>${esc(r.symbol)}</b><small>${esc(r.name)}${r.source && r.source !== 'Yahoo' ? ' · ' + esc(r.source) : ''}</small>${tags(r)}</td>
      <td>${stateCell(r)}</td>
      <td class="num">${inr(r.price)}</td><td class="num ${cls(r.change_pct)}">${pct(r.change_pct)}</td>
      ${long ? `<td>${r.setup ? `<span class="tag hot" title="${esc(r.setup_detail)}">${esc(r.setup)}</span>` : r.trigger ? `<span class="muted">above ${inr(r.trigger, 0)}</span>` : '<span class="muted">–</span>'}</td>
        <td class="num">${r.dist_trigger != null ? `<span class="${r.dist_trigger <= 3 ? 'warn-t' : ''}">${pct(r.dist_trigger, 1)}</span>` : '<span class="muted">–</span>'}</td>
        <td class="num">${r.rs_pct != null ? r.rs_pct : '–'}</td><td class="num">${pct(r.from_high, 1)}</td>`
      : `<td>${(r.setups || []).map(s => `<span class="tag hot">${esc(s.label || s.id)}</span>`).join(' ') || '<span class="muted">–</span>'}</td>
        <td>${r.orb && r.orb.state === 'confirmed' ? `<span class="pill pass">${esc(r.orb.time)}</span>` : r.orb && r.orb.state === 'waiting' ? '<span class="pill">waiting</span>' : '<span class="muted">–</span>'}</td>
        <td class="num">${r.dist_trigger != null ? pct(r.dist_trigger, 1) : '–'}</td>`}
      <td class="num"><span class="rank ${r.rank >= 60 ? 'hi' : r.rank >= 30 ? 'mid' : ''}">${r.rank ?? '–'}</span></td>
      <td class="acts">${long ? `<button class="btn sm" data-plan="${esc(r.symbol)}">Plan</button><button class="btn sm" data-mgtt="${esc(r.symbol)}">GTT</button>` : `<button class="btn sm" data-open="${esc(r.symbol)}">Open</button>`}
        <button class="btn sm ghost" data-note="${esc(r.symbol)}" title="Note">✎</button>${inList(r) ? `<button class="btn sm ghost" data-rm="${esc(r.symbol)}" title="Remove from ${esc(l.name)}">✕</button>` : ''}</td></tr>`).join('');
    const empty = !rowsAll.length ? (MY.src === 'list' ? `${esc(l.name)} is empty. Add stocks above, with ☆ on the Scanner, or on the Predictor.` : 'No holdings found (Zerodha not connected?).') : 'No stocks match this filter.';
    view.innerHTML = head('My scanner', `${MODES[S.mode].label} mode · ${rowsAll.length} stock${rowsAll.length === 1 ? '' : 's'} · ${rows.length} shown · scanned ${d.scanned_at} IST (${d.secs}s)`, '<button class="btn" id="rescan">Rescan</button>') +
      `<div class="stack">
      <div class="card"><div class="chips" style="margin-bottom:10px">${tabs}</div>
        <div class="row" style="gap:8px;flex-wrap:wrap">
          <div class="seg" id="mySrc">${srcs}</div>
          <form id="myAdd" class="row" style="gap:6px;flex:1;min-width:240px" autocomplete="off"><input id="myAddSym" list="symbols" placeholder="Add any NSE symbol, e.g. KALYANKJIL" style="text-transform:uppercase;flex:1;min-width:160px" spellcheck="false"><button class="btn primary">➕ Add</button></form>
          ${d.held_connected && d.held_count ? `<button class="btn" id="myAddHeld">Add all ${d.held_count} holdings to ${esc(l.name)}</button>` : ''}
          <button class="btn ghost sm" id="myRen">Rename</button>${MY.lists.length > 1 ? '<button class="btn ghost sm" id="myDel">Delete list</button>' : ''}
        </div></div>
      ${d.regime === false ? '<div class="banner">The Nifty is below its key moving averages. The rules hold off new buys until the market recovers.</div>' : ''}
      ${cap}
      <div class="chips">${fchips}</div>
      <div class="card"><div class="row tablebar" style="margin-top:0"><input type="search" data-tfind placeholder="Search stock, name or sector" style="width:240px"><button class="btn sm" data-sortreset>Default order</button><span class="note" style="margin:0">Hover a stock for its 6-month chart. Click a row for the full Predictor.</span></div>
      <div class="tablewrap"><table><thead><tr><th>Stock</th><th>Status</th><th class="num">Price</th><th class="num">Day</th>
        ${long ? '<th>Setup</th><th class="num">To trigger</th><th class="num">Strength %ile</th><th class="num">From 52w high</th>' : '<th>Daily setups</th><th>15-min ORB</th><th class="num">To OR high</th>'}
        <th class="num">Rank</th><th></th></tr></thead>
        <tbody>${tbody || `<tr><td colspan="${long ? 10 : 9}" class="empty">${empty}</td></tr>`}</tbody></table></div></div>
      ${d.failed.length ? `<p class="note">No data for: ${d.failed.map(x => esc(x.symbol)).join(', ')}.</p>` : ''}
      <p class="note">Status: <b>Buy zone</b> = a setup confirmed on a recent daily close, not run too far · <b>Near trigger</b> = within 3% of the breakout level · <b>Exit signal</b> = an exit rule fired on a holding. Results dates are estimates. Rule results, not personal advice; GTTs and orders are paper only.</p></div>`;

    view.querySelectorAll('[data-list]').forEach(b => b.onclick = () => { MY.list = b.dataset.list; mySave(); myStars(); run(false); });
    view.querySelectorAll('#mySrc [data-src]').forEach(b => b.onclick = () => { if (b.dataset.src === 'all') { location.hash = '#/scanner'; return; } MY.src = b.dataset.src; mySave(); run(false); });
    view.querySelectorAll('[data-f]').forEach(b => b.onclick = () => { filt = b.dataset.f; draw(d); });
    $('#rescan').onclick = () => run(true);
    $('#myNew').onclick = async () => { const n = prompt('Name of the new list (e.g. Study, Banks):'); if (!n) return; try { await myAct({ action: 'create', name: n }); run(false); } catch (e) { toast(e.message, 'bad'); } };
    $('#myRen').onclick = async () => { const n = prompt('New name for ' + l.name + ':', l.name); if (!n) return; try { await myAct({ action: 'rename', name: n }); draw(d); } catch (e) { toast(e.message, 'bad'); } };
    if ($('#myDel')) $('#myDel').onclick = async () => { if (!confirm(`Delete the list ${l.name} (${l.symbols.length} stocks)? This cannot be undone.`)) return; try { await myAct({ action: 'delete' }); run(false); } catch (e) { toast(e.message, 'bad'); } };
    $('#myAdd').onsubmit = async e => {
      e.preventDefault(); const v = $('#myAddSym').value.trim().toUpperCase().replace(/\.NS$/, ''); if (!v) return;
      const btn = e.target.querySelector('button'); btn.disabled = true;
      try { await myAct({ action: 'add', symbols: [v] }); run(true); } catch (err) { btn.disabled = false; toast(err.message, 'bad'); }
    };
    if ($('#myAddHeld')) $('#myAddHeld').onclick = async () => { try { await myAct({ action: 'addmany', symbols: (S.held && S.held.symbols) || d.rows.filter(r => r.zerodha).map(r => r.symbol) }); run(false); } catch (e) { toast(e.message, 'bad'); } };
    const byS = Object.fromEntries(rowsAll.map(r => [r.symbol, r]));
    view.querySelectorAll('tr.click').forEach(tr => {
      const go = () => location.hash = '#/predictor/' + encodeURIComponent(tr.dataset.s);
      tr.onclick = e => { if (!e.target.closest('button')) go(); }; tr.onkeydown = e => e.key === 'Enter' && e.target === tr && go();
    });
    view.querySelectorAll('[data-plan]').forEach(b => b.onclick = () => myPlan(byS[b.dataset.plan], d));
    view.querySelectorAll('[data-mgtt]').forEach(b => b.onclick = () => myGtt(byS[b.dataset.mgtt], d));
    view.querySelectorAll('[data-open]').forEach(b => b.onclick = () => location.hash = '#/predictor/' + encodeURIComponent(b.dataset.open));
    view.querySelectorAll('[data-rm]').forEach(b => b.onclick = async () => { try { await myAct({ action: 'remove', symbols: [b.dataset.rm] }); d.rows = d.rows.filter(r => r.symbol !== b.dataset.rm || MY.src !== 'list'); draw(d); } catch (e) { toast(e.message, 'bad'); } });
    view.querySelectorAll('[data-note]').forEach(b => b.onclick = async () => {
      const s = b.dataset.note, n = prompt(`Note for ${s} (blank = remove):`, MY.notes[s] || ''); if (n === null) return;
      try { await myAct({ action: 'note', symbols: [s], note: n }); draw(d); } catch (e) { toast(e.message, 'bad'); }
    });
    sparkHover(view);
    if (typeof tableTools === 'function') tableTools(view);
  };

  const run = async fresh => {
    const k = key(), hit = MY.cache[k];
    if (hit && !fresh && Date.now() - hit.at < 15 * 60 * 1000) { draw(hit.d); return; }
    const l = myActive();
    view.innerHTML = head('My scanner', `Scanning ${MY.src === 'list' ? esc(l ? l.name : 'your list') : 'your stocks'} with the ${MODES[S.mode].label} rules. Stocks new to the portal download 10 years of history first…`) + loading(3);
    let d, err;
    try { d = await api(`/api/myscan?source=${MY.src}&list=${encodeURIComponent(l ? l.id : '')}`); } catch (e) { err = e; }
    if (my !== S.nav) return;
    if (err) { view.innerHTML = head('My scanner', 'Scan failed') + failBox(err); return; }
    MY.lists = d.lists; MY.notes = d.notes; MY.cache[k] = { at: Date.now(), d };
    draw(d);
  };
  run(false);
}

function myPlan(r, d) {
  const p = r.plan, dlg = $('#dlg');
  if (!p) return;
  $('#dlgBody').innerHTML = `<h3>Plan · ${esc(r.symbol)} · ${esc(MODES[S.mode].label)}</h3>
    <p class="note">${p.at_trigger ? `Not in the buy zone yet: the plan is for a daily close above the trigger ${inr(p.entry)}${r.dist_trigger != null ? ` (${pct(r.dist_trigger, 1)} away)` : ''}.` : `In the buy zone now (${esc(r.setup || '')}). Entry at about the current price.`}</p>
    <div class="kv">
      <div><span>Entry</span><b>${inr(p.entry)}</b></div><div><span>Stop (ATR rule)</span><b class="down">${inr(p.stop)}</b><small>${p.risk_pct.toFixed(1)}% below</small></div>
      <div><span>Quantity</span><b>${p.qty} shares</b><small>limited by ${esc(p.limited_by)}</small></div><div><span>Amount</span><b>${inr(p.cost, 0)}</b></div>
      <div><span>Max loss incl. costs</span><b class="down">${inr(p.max_loss, 0)}</b></div><div><span>Exit</span><b>No fixed target</b><small>break-even after +${S.mode === 'invest' ? 1 : 2}R, then trail</small></div>
    </div>
    <h4 style="margin:12px 0 6px">Risk check · <span class="pill ${p.verdict === 'PASS' ? 'pass' : 'fail'}">${p.verdict}</span></h4>
    <ul class="checks">${p.checks.map(c => `<li class="${c.ok ? 'ok' : 'bad'}">${c.ok ? '✓' : '✕'} <b>${esc(c.name)}</b> · ${esc(c.detail)}</li>`).join('')}</ul>
    ${r.results && r.results.days >= -5 && r.results.days <= 7 ? `<p class="note"><b>⚠ Results expected around ${esc(r.results.date)}</b> (estimate): the price can gap on that day.</p>` : ''}
    <div class="row" style="justify-content:flex-end"><button class="btn" value="cancel">Close</button><a class="btn" href="#/predictor/${encodeURIComponent(r.symbol)}">Full Predictor</a><button class="btn primary" id="planGtt">Set paper GTT…</button></div>`;
  dlg.showModal();
  $('#planGtt').onclick = e => { e.preventDefault(); dlg.close(); myGtt(r, d); };
}
function myGtt(r, d) {
  const p = r.plan || {};
  gttDialog({ symbol: r.symbol, price: r.price, clock: d.clock, mode: S.mode, plan: { entry: p.entry, stop: p.stop }, size: { qty: p.qty } });
}

/* hover chart: 6 months of closes with the 50 / 200-day averages */
function sparkHover(root) {
  if (matchMedia('(hover: none)').matches) return;
  let tip = $('#sparkTip'), timer;
  if (!tip) { tip = document.createElement('div'); tip.id = 'sparkTip'; tip.hidden = true; document.body.append(tip); }
  root.querySelectorAll('[data-spark]').forEach(td => {
    td.onmouseenter = () => {
      clearTimeout(timer);
      timer = setTimeout(async () => {
        const s = td.dataset.spark;
        try { MY.spark[s] = MY.spark[s] || await api('/api/spark?symbol=' + encodeURIComponent(s)); } catch (e) { return; }
        if (!td.matches(':hover')) return;
        tip.innerHTML = sparkSvg(MY.spark[s]);
        const b = td.getBoundingClientRect();
        tip.style.left = Math.min(innerWidth - 340, b.right + 8) + 'px'; tip.style.top = Math.max(8, Math.min(innerHeight - 190, b.top - 40)) + 'px';
        tip.hidden = false;
      }, 250);
    };
    td.onmouseleave = () => { clearTimeout(timer); tip.hidden = true; };
  });
}
function sparkSvg(d) {
  const W = 320, H = 150, all = [...d.c, ...d.sma50.filter(Boolean), ...d.sma200.filter(Boolean)];
  const lo = Math.min(...all), hi = Math.max(...all), n = d.c.length;
  const x = i => (i / (n - 1) * (W - 10) + 5).toFixed(1), y = v => (H - 18 - (v - lo) / (hi - lo || 1) * (H - 30)).toFixed(1);
  const line = a => a.map((v, i) => v == null ? null : `${x(i)},${y(v)}`).filter(Boolean).join(' ');
  const last = d.c[n - 1], first = d.c[0];
  return `<div class="spark-h"><b>${esc(d.symbol)}</b> <span class="${last >= first ? 'up' : 'down'}">${pct((last / first - 1) * 100, 1)}</span> <small class="muted">6 months</small></div>
    <svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}"><polyline points="${line(d.sma200)}" class="sp-200"/><polyline points="${line(d.sma50)}" class="sp-50"/><polyline points="${line(d.c)}" class="sp-c"/>
    <text x="5" y="${H - 3}" class="sp-t">${esc(d.d[0])}</text><text x="${W - 5}" y="${H - 3}" text-anchor="end" class="sp-t">${inr(last)}</text></svg>
    <div class="spark-k"><i class="k-c"></i>price <i class="k-50"></i>50-day <i class="k-200"></i>200-day</div>`;
}

VIEWS.myscan = myScanPage;
myLoad();
if (location.hash.startsWith('#/myscan')) setTimeout(route, 0);
