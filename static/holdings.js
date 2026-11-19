'use strict';
/* ---------------------------------------------------------------- My holdings: PIN gate + yearly Zerodha record */
const HTABS = [['today', 'Today'], ['live', 'Live holdings'], ['record', 'Year record'], ['tax', 'Tax'], ['sectors', 'Sectors'], ['next', 'What next'], ['core', 'Core + satellite'], ['funds', 'Funds'], ['import', 'Import & add']];

/* One plan for the whole account, Trading rules, 3-6 months: what to sell and what to buy, sector by sector.
   Built in ledger._plan from the last snapshot. Mechanical rule results, not advice. */
function planBlock(p) {
  if (!p) return '';
  if (p.stale) return `<div class="card plan-card"><h2>Your ${esc(p.horizon)} plan</h2><p class="note">${esc((p.notes || [''])[0])}</p></div>`;
  const sells = p.sells.length ? `<ul class="nlist">${p.sells.map(s => `<li><b class="down">${s.all ? 'Sell all' : 'Sell ' + s.qty}</b> <a href="#/predictor/${encodeURIComponent(s.symbol)}"><b>${esc(s.symbol)}</b></a> · ${esc(s.sector)} · ${esc(s.reason)}${s.all ? '' : ` (${s.qty} shares, ${inr(s.value, 0)})`}${s.pnl_pct != null ? ` · <span class="${cls(s.pnl_pct)}">${sgn(s.pnl_pct)}</span>` : ''} · <span data-pn="${esc(s.symbol)}" class="muted">news…</span></li>`).join('')}</ul>`
    : '<p class="note">Nothing to sell: holdings are within your limits.</p>';
  const buys = p.buys.length ? `<ul class="nlist">${p.buys.map(b => `<li><b class="up">Buy ${b.qty}</b> <a href="#/predictor/${encodeURIComponent(b.symbol)}"><b>${esc(b.symbol)}</b></a> · ${esc(b.sector)} · ${esc(b.setup || '')} at ${inr(b.price)} · about ${inr(b.amount, 0)}${b.rs6 != null ? ` · 6-month vs Nifty ${sgn(b.rs6)}` : ''} · <a href="#/news/${encodeURIComponent(b.symbol)}">news</a></li>`).join('')}</ul>`
    : (p.waiting && p.waiting.length
      ? `<p class="note">No free place after the sells. Next in line when a place frees up:</p><ul class="nlist">${p.waiting.map(b => `<li><a href="#/predictor/${encodeURIComponent(b.symbol)}"><b>${esc(b.symbol)}</b></a> · ${esc(b.sector)} · ${esc(b.setup || '')}${b.price ? ' at ' + inr(b.price) : ''}${b.rs6 != null ? ` · 6-month vs Nifty ${sgn(b.rs6)}` : ''} · <a href="#/news/${encodeURIComponent(b.symbol)}">news</a></li>`).join('')}</ul>`
      : '<p class="note">No buy signal fits right now.</p>');
  const keeps = p.keeps.length ? `<ul class="nlist">${p.keeps.map(k => `<li><a href="#/predictor/${encodeURIComponent(k.symbol)}"><b>${esc(k.symbol)}</b></a> · ${esc(k.sector)} · ${esc(k.verdict || '')}${k.pnl_pct != null ? ` · <span class="${cls(k.pnl_pct)}">${sgn(k.pnl_pct)}</span>` : ''}</li>`).join('')}</ul>` : '<p class="note">None.</p>';
  return `<div class="card plan-card">
    <h2>Your ${esc(p.horizon)} plan · Trading rules</h2>
    <p class="note" style="margin-top:0">As of ${esc(p.as_of || '')} · holdings ${p.before.holdings} now → ${p.after.max - p.free_slots} after the sells → ${p.after.holdings} with the buys (limit ${p.after.max}) · cash ${p.cash != null ? inr(p.cash, 0) : 'unknown'}${p.cash_after != null ? ` → ${inr(p.cash_after, 0)} after the sells` : ''}${p.per_stock ? ` · your limit ${inr(p.per_stock, 0)} per stock (Limits › Investing)` : ''}</p>
    <div class="grid2">
      <div><h2 class="plan-sell-h">Sell</h2>${sells}</div>
      <div><h2 class="plan-buy-h">Buy</h2>${buys}</div>
    </div>
    <h2 style="margin-top:14px">Keep</h2>${keeps}
    <ul class="nlist">${p.notes.map(n => `<li class="muted">${esc(n)}</li>`).join('')}</ul>
  </div>`;
}
// fills the news cells of the plan (same news feed as the holdings table)
async function planNews(my) {
  let d; try { d = await api('/api/news?holdings=1'); } catch (e) { d = null; }
  if (my !== S.nav) return;
  const by = {}; ((d && d.watch) || []).forEach(w => { by[w.symbol] = w; });
  document.querySelectorAll('[data-pn]').forEach(el => {
    const w = by[el.dataset.pn];
    if (!w || w.error) { el.textContent = w && w.error ? 'news unavailable' : 'no news in 3 days'; return; }
    const top = (w.items || []).slice(0, 1).map(i => `<a class="tone-${i.tone || 'neu'}" href="${esc(i.link)}" target="_blank" rel="noopener noreferrer">${esc(i.title)}</a>`).join('');
    el.innerHTML = (top || 'no news in 3 days') + ` <small class="muted">${(w.items || []).length} in 3 days</small>`;
  });
}
function hTabs(active) {
  return `<div class="htabs" role="tablist">${HTABS.map(([k, l]) => `<button type="button" role="tab" class="${k === active ? 'on' : ''}" aria-selected="${k === active}" data-htab="${k}">${l}</button>`).join('')}
    <button type="button" class="htab-lock" data-hlock title="Lock My holdings">🔒 Lock</button></div>`;
}
document.addEventListener('click', e => {
  const t = e.target.closest && e.target.closest('[data-htab]');
  if (t) { e.preventDefault(); S.hTab = t.dataset.htab; holdingsPage(); return; }
  const l = e.target.closest && e.target.closest('[data-hlock]');
  if (l) { e.preventDefault(); S.pinTok = null; S.ledger = null; holdingsPage(); }
});
const pinNeeded = e => /PIN needed/i.test((e && e.message) || '');

/* ---- PIN screen: set (first time / reset with the portal password) or unlock */
async function pinGate(then) {
  const my = S.nav;
  view.innerHTML = head('My holdings', 'Protected by your PIN') + loading(1);
  let st; try { st = await api('/api/ledger/pin'); } catch (e) { view.innerHTML = head('My holdings', 'PIN check failed') + failBox(e); return; }
  if (my !== S.nav) return;
  const n = st.length || 4;
  const pinIn = (id, label) => `<label>${label}<input id="${id}" type="password" inputmode="numeric" pattern="[0-9]*" maxlength="${n}" autocomplete="off" class="pin-in"></label>`;
  if (!st.set || st.locked || S.pinReset) {
    const why = !st.set ? `Set a ${n}-digit PIN for My holdings. It is asked every time the page opens.` : st.locked ? `Locked after 5 wrong PINs. Set a new PIN with the portal password.` : 'Forgot the PIN? Set a new one with the portal password.';
    view.innerHTML = head('My holdings', 'Protected by your PIN') + `<div class="card pin-card"><h2>${!st.set ? 'Set your PIN' : 'Reset your PIN'}</h2><p class="note">${why}</p>
      <form id="pinSet" class="grid" autocomplete="off">${pinIn('p1', 'New PIN')}${pinIn('p2', 'New PIN again')}
      ${st.password_needed ? '<label>Portal password<input id="pPw" type="password" autocomplete="current-password"></label>' : ''}
      <div class="row" style="grid-column:1/-1"><button class="btn primary">Save PIN</button>${st.set && !st.locked ? '<button type="button" class="btn" id="pBack">Back</button>' : ''}</div></form>
      <p class="note">The PIN is stored only as a salted hash on your NAS. Change it any time under Limits.</p></div>`;
    $('#p1').focus();
    if ($('#pBack')) $('#pBack').onclick = () => { S.pinReset = false; pinGate(then); };
    $('#pinSet').onsubmit = async e => {
      e.preventDefault();
      const a = $('#p1').value, b = $('#p2').value;
      if (a !== b) { toast('The two PINs are not the same.', 'bad'); return; }
      try {
        await api('/api/ledger/pin/set', { pin: a, password: $('#pPw') ? $('#pPw').value : '' });
        const u = await api('/api/ledger/unlock', { pin: a });
        S.pinTok = u.token; S.pinReset = false; toast('PIN saved.'); then();
      } catch (err) { toast(err.message, 'bad'); }
    };
    return;
  }
  let pin = '';
  view.innerHTML = head('My holdings', 'Protected by your PIN') + `<div class="card pin-card"><h2>Enter your PIN</h2>
    <div class="pin-dots" aria-hidden="true">${'<i></i>'.repeat(n)}</div>
    <input id="pinHidden" type="password" inputmode="numeric" pattern="[0-9]*" maxlength="${n}" autocomplete="off" class="pin-in" aria-label="PIN">
    <div class="pin-pad">${[1, 2, 3, 4, 5, 6, 7, 8, 9, '', 0, '⌫'].map(k => k === '' ? '<span></span>' : `<button type="button" data-k="${k}">${k}</button>`).join('')}</div>
    <p class="note">${st.tries_left < 5 ? `<b>${st.tries_left} tries left</b> before it locks. ` : ''}<a href="#" id="pinForgot">Forgot PIN?</a></p></div>`;
  const inp = $('#pinHidden'), dots = view.querySelectorAll('.pin-dots i');
  const show = () => dots.forEach((d, i) => d.classList.toggle('on', i < pin.length));
  const go = async () => {
    try { const u = await api('/api/ledger/unlock', { pin }); S.pinTok = u.token; then(); }
    catch (err) { toast(err.message, 'bad'); pin = ''; inp.value = ''; show(); if (/locked/i.test(err.message)) pinGate(then); }
  };
  const key = k => { if (k === '⌫') pin = pin.slice(0, -1); else if (pin.length < n) pin += k; inp.value = pin; show(); if (pin.length === n) go(); };
  view.querySelectorAll('.pin-pad [data-k]').forEach(b => b.onclick = () => key(b.dataset.k));
  inp.oninput = () => { pin = inp.value.replace(/\D/g, '').slice(0, n); inp.value = pin; show(); if (pin.length === n) go(); };
  inp.focus();
  $('#pinForgot').onclick = e => { e.preventDefault(); S.pinReset = true; pinGate(then); };
}

/* ---- Today: the 15-minute daily checklist */
async function todayPage() {
  const my = S.nav;
  view.innerHTML = head('My holdings', 'Building today\'s checklist…') + hTabs('today') + loading(3);
  let t; try { t = await api('/api/ledger/today'); }
  catch (e) { if (pinNeeded(e)) { S.pinTok = null; return pinGate(holdingsPage); } view.innerHTML = head('My holdings', 'Checklist could not load') + hTabs('today') + failBox(e); return; }
  if (my !== S.nav) return;
  const G = [['act', 'Act today', 'fail'], ['watch', 'Watch', 'warn'], ['tomorrow', 'For tomorrow', 'pass'], ['info', 'For information', '']];
  const total = t.items.filter(x => x.group !== 'info').length, done = t.items.filter(x => x.group !== 'info' && x.done).length;
  const item = x => `<li class="${x.done ? 'done' : ''}"><label><input type="checkbox" data-tid="${esc(x.id)}" ${x.done ? 'checked' : ''}> <span>${esc(x.text)}</span></label>${x.link ? ` <a href="${esc(x.link)}" class="tlink">open →</a>` : ''}</li>`;
  view.innerHTML = head('My holdings', `Today · ${new Date(t.date).toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'short' })} · buy ideas by the ${esc(t.mode_label)} rules · built ${esc(t.at.slice(11, 16))} IST`,
    '<button class="btn" id="tRefresh">Refresh</button>') + hTabs('today') +
    `<div class="stack">${scHead("Today's checklist", total ? `${done} <span class="muted" style="font-size:16px">of ${total} done</span>` : '0', null, t.connected ? 'Zerodha connected' : 'Zerodha not connected')}
    ${(() => { const n = g => t.items.filter(x => x.group === g).length; return scTiles([['Act today', n('act'), n('act') ? 'down' : ''], ['Watch', n('watch'), ''], ['For tomorrow', n('tomorrow'), ''], ['For information', n('info'), '']]); })()}
    <div class="card"><div class="row" style="justify-content:space-between"><h2 style="margin:0">${total ? `${done} of ${total} checked` : 'Nothing to act on today'}</h2>
      <span class="note" style="margin:0">${t.connected ? 'Zerodha connected' : 'Zerodha not connected'}${t.snapshot_at ? ' · holdings as of ' + esc(t.snapshot_at) : ''}</span></div>
      ${total ? `<div class="capbar" style="margin-top:10px"><i style="width:${(done / total * 100).toFixed(0)}%"></i></div>` : ''}</div>
    ${G.map(([g, label, pill]) => { const xs = t.items.filter(x => x.group === g); return xs.length ? `<div class="card"><h2>${pill ? `<span class="pill ${pill}">${xs.length}</span> ` : ''}${label}</h2><ul class="tlist">${xs.map(item).join('')}</ul></div>` : ''; }).join('')}
    <p class="note">A 15-minute routine after 15:30: work down the list, open what needs a look, tick it off. The same list comes in the 15:35 Telegram message. Exits, buy signals and limits are rule results; long-term dates and results dates come from your records (results dates are estimates). Not personal advice: you place any real order yourself in Zerodha.</p></div>`;
  $('#tRefresh').onclick = () => todayPage();
  view.querySelectorAll('[data-tid]').forEach(cb => cb.onchange = async () => {
    cb.closest('li').classList.toggle('done', cb.checked);
    try { await api('/api/ledger/today/done', { id: cb.dataset.tid, done: cb.checked }); } catch (e) { toast(e.message, 'bad'); }
    const all = [...view.querySelectorAll('.tlist [data-tid]')].filter(c => !c.closest('.card').querySelector('h2').textContent.includes('For information'));
    const n = all.filter(c => c.checked).length, h = view.querySelector('.card h2');
    if (h && all.length) h.textContent = `${n} of ${all.length} checked`;
    const bar = view.querySelector('.card .capbar i'); if (bar && all.length) bar.style.width = (n / all.length * 100).toFixed(0) + '%';
  });
}

/* ---- yearly record tabs */
async function ledgerPage(tab, fresh) {
  if (tab === 'today') return todayPage();
  const my = S.nav;
  if (!S.ledger || fresh || (S.ledgerFy && S.ledger.fy !== S.ledgerFy)) {
    view.innerHTML = head('My holdings', 'Loading your Zerodha record…') + hTabs(tab) + loading(3);
    const rg = S.ledgerRange || {};
    let d; try { d = await api('/api/ledger?refresh=' + (S.ledger && !fresh ? '0' : '1') + (S.ledgerFy ? '&fy=' + encodeURIComponent(S.ledgerFy) : '')
      + (rg.from ? '&from=' + encodeURIComponent(rg.from) : '') + (rg.to ? '&to=' + encodeURIComponent(rg.to) : '')); }
    catch (e) { if (pinNeeded(e)) { S.pinTok = null; return pinGate(holdingsPage); } view.innerHTML = head('My holdings', 'Record could not load') + hTabs(tab) + failBox(e); return; }
    if (my !== S.nav) return;
    S.ledger = d;
  }
  const d = S.ledger, t = d.totals || {}, money = v => v == null ? '–' : (v < 0 ? '−' : '+') + inr(Math.abs(v), 0), plain = v => v == null ? '–' : inr(v, 0);
  const status = d.connected ? `<span class="pill pass">Zerodha connected</span> record updated ${esc(d.snapshot_at || 'now')}`
    : `<span class="pill warn">Zerodha not connected</span> showing the last record${d.snapshot_at ? ' from ' + esc(d.snapshot_at) : ''} · <a href="#" data-htab="live">connect</a>`;
  const fySel = `<select id="lFy" aria-label="Financial year">${d.fys.map(f => `<option value="${esc(f)}" ${f === d.fy ? 'selected' : ''}>FY ${esc(f)}</option>`).join('')}</select>`;
  const right = `${fySel}<button class="btn" id="lRefresh">Refresh</button><button class="btn" id="lCsv">Download CSV</button>`;
  const tile = (label, txt, v, sub) => `<div class="${v == null ? '' : v >= 0 ? 'tile-up' : 'tile-down'}"><span>${label}</span><b>${txt}</b>${sub ? `<small class="muted" style="display:block">${sub}</small>` : ''}</div>`;
  const tx = d.tax, rg = d.range || {};
  const per_ = rg.custom ? (rg.from.slice(0, 7) === rg.to.slice(0, 7) && rg.from.endsWith('-01') && new Date(rg.to.slice(0, 4), +rg.to.slice(5, 7), 0).getDate() === +rg.to.slice(8)
    ? new Date(rg.from).toLocaleDateString('en-IN', { month: 'long', year: 'numeric' }) : `${rg.from} – ${rg.to}`) : 'FY ' + d.fy;
  const curM = rg.custom && rg.from.slice(0, 7) === rg.to.slice(0, 7) ? rg.from.slice(0, 7) : '';
  const filterBar = `<div class="card lfilter"><div class="row" style="gap:8px;flex-wrap:wrap;align-items:flex-end">
    <b style="align-self:center">Period:</b>
    <button type="button" class="chip ${rg.custom ? '' : 'on'}" id="lfYear">Whole FY ${esc(d.fy)}</button>
    <label>Month<input type="month" id="lfMonth" value="${esc(curM)}"></label>
    <label>From<input type="date" id="lfFrom" value="${rg.custom ? esc(rg.from) : ''}"></label>
    <label>To<input type="date" id="lfTo" value="${rg.custom ? esc(rg.to) : ''}"></label>
    <button type="button" class="btn" id="lfApply">Show range</button>
    <span class="note" style="margin:0">Showing <b>${esc(per_)}</b>${rg.custom ? ' · tax stays for the whole FY ' + esc(d.fy) : ''}</span></div></div>`;
  const summary = `<div class="kv sc-kv" style="margin:0">
    ${tile('Bought · ' + esc(per_), plain(totals(d).buy_value), null, `${totals(d).buys} trades · ${fmtQ(totals(d).buy_qty)} shares`)}
    ${tile('Sold · ' + esc(per_), plain(totals(d).sell_value), null, `${totals(d).sells} trades · ${fmtQ(totals(d).sell_qty)} shares`)}
    ${(() => { const k = kind => d.realised.filter(r => r.kind === kind && r.pnl != null).reduce((s, r) => s + r.pnl, 0);
      return tile('Profit booked · ' + esc(per_), money(totals(d).realised), totals(d).realised, `short ${money(k('short'))} · long ${money(k('long'))} · intraday ${money(k('intraday'))}`); })()}
    ${tile('Estimated tax (delivery)', inr(tx.total_tax, 0), null, `STCG ${(tx.st_rate * 100).toFixed(0)}% · LTCG ${(tx.lt_rate * 100).toFixed(1)}% · incl. 4% cess`)}
    ${tile('Holdings value', plain(totals(d).value), null, `invested ${plain(totals(d).cost)}`)}
    ${tile('Not yet booked (unrealised)', money(totals(d).unrealised), totals(d).unrealised, `short-term ${money(totals(d).unreal_short)} · long-term ${money(totals(d).unreal_long)}`)}
    ${tile('Funds available', d.funds && d.funds.net != null ? inr(d.funds.net, 0) : '–', null, d.funds ? `cash ${d.funds.cash != null ? inr(d.funds.cash, 0) : '–'} · used ${d.funds.used != null ? inr(d.funds.used, 0) : '–'}` : 'no record yet')}
    ${d.charges.zerodha != null ? tile('Charges (Zerodha P&amp;L)', inr(d.charges.zerodha, 0), null, `my estimate was ${inr(d.charges.total, 0)}`)
      : tile('Charges (estimate)', inr(d.charges.total, 0), null, `delivery ${inr(d.charges.delivery, 0)} · intraday ${inr(d.charges.intraday, 0)}`)}</div>
    ${d.pnl ? `<p class="note" style="margin:6px 0 0">Zerodha P&amp;L statement (${esc(d.pnl.file || '')}${d.pnl.from ? ', ' + esc(d.pnl.from) + ' – ' + esc(d.pnl.to) : ''}): realised ${money(d.pnl.realised)}${d.pnl.differ.length ? ` · <b class="down">differs from the tradebook for ${d.pnl.differ.map(esc).join(', ')}</b> (usually trades before the tradebook starts, or a bonus / split)` : ' · matches the tradebook'}.</p>` : ''}`;
  const empty = !d.records.trades && !d.records.snapshots;
  const startHelp = empty ? `<div class="banner">No record yet. ${d.connected ? 'The first snapshot is being saved now; ' : 'Connect Zerodha on Live holdings, and '}upload your Console tradebook under <a href="#" data-htab="import">Import &amp; add</a> to fill in past buys and sells.</div>` : '';
  const mism = d.holdings.filter(h => h.mismatch);
  const undated = mism.filter(h => h.unknown_qty > 0), other = mism.filter(h => !(h.unknown_qty > 0));
  const first = d.records.first_trade;
  const prevFy = (() => { if (!first) return null; const [y, m] = first.split('-').map(Number); const s = (m >= 4 ? y : y - 1) - 1; return { label: `${s}-${String((s + 1) % 100).padStart(2, '0')}`, from: `1 Apr ${s}`, to: `31 Mar ${s + 1}` }; })();
  const mismBox = mism.length ? `<div class="banner">${undated.length ? `<b>${undated.length} holding${undated.length === 1 ? ' has' : 's have'} shares bought before your tradebook starts${first ? ' (' + esc(first) + ')' : ''}</b>, so their buy dates and tax status are not known yet: ${undated.map(h => `${esc(h.symbol)} ${fmtQ(h.unknown_qty)}`).join(', ')}.
      ${prevFy ? `Next: download the Console tradebook for <b>FY ${prevFy.label}</b> (${prevFy.from} – ${prevFy.to}), upload it, and repeat for earlier years until this message goes.` : ''}` : ''}
    ${other.length ? `<div style="margin-top:6px">${other.map(h => `<b>${esc(h.symbol)}</b>: ${esc(h.mismatch)}`).join(' · ')}</div>` : ''} <a href="#" data-htab="import">Import &amp; add</a></div>` : '';
  const T = (cols, rows, emptyMsg, id) => `<div class="tablewrap"><table ${id ? `id="${id}"` : ''}><thead><tr>${cols.map(c => `<th class="${c[1] || ''}">${c[0]}</th>`).join('')}</tr></thead><tbody>${rows.join('') || `<tr><td colspan="${cols.length}" class="empty">${emptyMsg}</td></tr>`}</tbody></table></div>`;
  let body = '';
  if (tab === 'record') {
    body = `${filterBar}${summary}${mismBox}
      <div class="card"><h2>Stock by stock · ${esc(per_)}</h2>${T([['Stock'], ['Bought', 'num'], ['Avg buy', 'num'], ['Sold', 'num'], ['Avg sell', 'num'], ['Holding now', 'num'], ['Booked profit', 'num'], ...(d.pnl ? [['Zerodha P&amp;L', 'num']] : []), ['First / last trade']],
        d.per_stock.map(p => `<tr><td class="sym"><a href="#/predictor/${encodeURIComponent(p.symbol)}"><b>${esc(p.symbol)}</b></a><small>${esc(p.sector)}</small></td>
          <td class="num">${fmtQ(p.buy_qty)}<small class="chg" style="display:block">${inr(p.buy_value, 0)}</small></td><td class="num">${p.avg_buy != null ? inr(p.avg_buy) : '–'}</td>
          <td class="num">${fmtQ(p.sell_qty)}<small class="chg" style="display:block">${inr(p.sell_value, 0)}</small></td><td class="num">${p.avg_sell != null ? inr(p.avg_sell) : '–'}</td>
          <td class="num">${fmtQ(p.remaining)}</td>
          <td class="num ${cls(p.realised)}">${p.buy_qty || p.sell_qty ? money(p.realised) : '–'}<small class="chg" style="display:block">${[p.short ? 'ST ' + money(p.short) : '', p.long ? 'LT ' + money(p.long) : '', p.intraday ? 'intraday ' + money(p.intraday) : '', p.unknown_qty ? fmtQ(p.unknown_qty) + ' sh cost unknown' : ''].filter(Boolean).join(' · ')}</small></td>
          ${d.pnl ? `<td class="num ${cls(p.z_realised)}">${p.z_realised != null ? money(p.z_realised) : '–'}${d.pnl.differ.includes(p.symbol) ? '<small class="down" style="display:block">differs</small>' : p.only_zerodha ? '<small class="muted" style="display:block">not in tradebook</small>' : ''}</td>` : ''}
          <td class="mono">${esc(p.first || '–')}<small class="muted" style="display:block">${esc(p.last || '')}</small></td></tr>`), 'No buys or sells recorded in this year yet.')}</div>
      ${d.pnl && (Object.keys(d.pnl.summary || {}).length || (d.pnl.other || []).length) ? `<div class="card"><h2>From Zerodha's P&amp;L statement</h2><div class="grid2">
        <div>${T([['Item'], ['Amount', 'num']], Object.entries(d.pnl.summary || {}).map(([k, v]) => `<tr><td>${esc(k)}</td><td class="num">${inr(v, 2)}</td></tr>`), 'No summary lines.')}</div>
        <div>${T([['Date'], ['Other debits and credits'], ['Amount', 'num']], (d.pnl.other || []).map(o => `<tr><td class="mono">${esc(o.date || '–')}</td><td>${esc(o.what)}</td><td class="num ${cls(o.amount)}">${inr(o.amount, 2)}</td></tr>`), 'None.')}</div></div></div>` : ''}
      <div class="card"><h2>Month by month · all ${d.months.length} months on record</h2><div class="scrollbox">${T([['Month'], ['FY'], ['Buys', 'num'], ['Bought', 'num'], ['Sells', 'num'], ['Sold', 'num'], ['Booked profit', 'num']],
        d.months.slice().reverse().map(m => { const inP = m.month >= (rg.from || '').slice(0, 7) && m.month <= (rg.to || '').slice(0, 7);
          return `<tr class="click ${inP ? 'inper' : ''}" data-month="${esc(m.month)}" title="Show only ${esc(m.month)}"><td class="mono">${new Date(m.month + '-01').toLocaleDateString('en-IN', { month: 'short', year: 'numeric' })}</td><td class="mono muted">${esc(fyOfMonth(m.month))}</td><td class="num">${m.buys}</td><td class="num">${inr(m.buy_value, 0)}</td><td class="num">${m.sells}</td><td class="num">${inr(m.sell_value, 0)}</td><td class="num ${cls(m.realised)}">${money(m.realised)}</td></tr>`; }), 'Nothing on record yet.')}</div>
        <p class="note">Every month on record, newest first; highlighted rows are in the period shown. Click a month to show only that month.</p></div>
      <div class="card"><h2>Every buy and sell · ${d.trades.length}</h2><div class="row tablebar"><input type="search" data-tfind placeholder="Search stock or date" style="width:220px"></div>${T([['Date'], ['Stock'], ['Buy / sell'], ['Qty', 'num'], ['Price', 'num'], ['Value', 'num'], ['From']],
        d.trades.map(x => `<tr><td class="mono">${esc(x.date)}${x.time ? ' <small class="muted">' + esc(x.time.slice(0, 5)) + '</small>' : ''}</td><td><b>${esc(x.symbol)}</b></td><td><span class="pill ${x.side === 'buy' ? 'pass' : 'fail'}">${x.side === 'buy' ? 'Buy' : 'Sell'}</span>${x.product ? ' <small class="muted">' + esc(x.product) + '</small>' : ''}</td>
          <td class="num">${fmtQ(x.qty)}</td><td class="num">${inr(x.price)}</td><td class="num">${inr(x.value, 0)}</td><td class="muted">${{ tradebook: 'Tradebook', zerodha: 'Zerodha (day total)', manual: 'Added by hand' }[x.source] || esc(x.source)}</td></tr>`), 'No trades this year.')}</div>
      <div class="card"><h2>Profit booked on each sale · ${d.realised.length}</h2>${T([['Sold on'], ['Stock'], ['Type'], ['Qty', 'num'], ['Bought on'], ['Buy', 'num'], ['Sell', 'num'], ['Profit', 'num']],
        d.realised.map(r => `<tr><td class="mono">${esc(r.date)}</td><td><b>${esc(r.symbol)}</b></td><td>${{ short: '<span class="pill warn">Short-term</span>', long: '<span class="pill pass">Long-term</span>', intraday: '<span class="pill">Intraday</span>', unknown: '<span class="pill fail">Cost unknown</span>' }[r.kind]}</td>
          <td class="num">${fmtQ(r.qty)}</td><td class="mono">${esc(r.buy_date || '–')}</td><td class="num">${r.buy != null ? inr(r.buy) : '–'}</td><td class="num">${inr(r.sell)}</td><td class="num ${cls(r.pnl)}">${r.pnl != null ? money(r.pnl) : '–'}</td></tr>`), 'No sales this year.')}</div>`;
  } else if (tab === 'tax') {
    const row = (k, v, c) => `<tr><td>${k}</td><td class="num ${c || ''}">${v}</td></tr>`;
    const lots = [];
    d.holdings.filter(h => h.counted).forEach(h => h.lots.forEach(l => lots.push(`<tr><td><b>${esc(h.symbol)}</b></td><td class="mono">${esc(l.date || 'unknown')}</td><td class="num">${fmtQ(l.qty)}</td><td class="num">${l.price != null ? inr(l.price) : '–'}</td>
      <td class="num">${l.days_held != null ? l.days_held : '–'}</td><td>${l.long === true ? '<span class="pill pass">Long-term</span>' : l.long === false ? '<span class="pill warn">Short-term</span>' : '<span class="pill">Date unknown</span>'}</td>
      <td class="mono">${l.long === false ? esc(l.long_from) + ` <small class="muted">(${l.days_to_long} days)</small>` : '–'}</td><td class="num ${cls(l.gain)}">${l.gain != null ? money(l.gain) : '–'}</td></tr>`)));
    body = `<div class="grid2"><div class="card"><h2>Capital-gains tax estimate · FY ${esc(d.fy)}</h2><div class="tablewrap"><table><tbody>
      ${row('Short-term gains (held 12 months or less)', money(tx.short_gain), cls(tx.short_gain))}${row('Long-term gains (held over 12 months)', money(tx.long_gain), cls(tx.long_gain))}
      ${row('Short-term after set-off', money(tx.short_after_setoff))}${row('Long-term after set-off', money(tx.long_after_setoff))}
      ${row('Long-term exemption', inr(tx.long_exempt, 0))}${row('Long-term taxable', inr(tx.long_taxable, 0))}
      ${row(`Tax on short-term (${(tx.st_rate * 100).toFixed(0)}%)`, inr(tx.st_tax, 0))}${row(`Tax on long-term (${(tx.lt_rate * 100).toFixed(1)}%)`, inr(tx.lt_tax, 0))}
      ${row('Health &amp; education cess (4%)', inr(tx.cess, 0))}${row('<b>Estimated tax</b>', '<b>' + inr(tx.total_tax, 0) + '</b>')}
      ${tx.if_sold_today != null ? (tx.if_sold_today >= 0 ? row('Extra tax if every holding were sold today', inr(tx.if_sold_today, 0)) : row('Tax saved if every holding were sold today (losses offset gains)', inr(-tx.if_sold_today, 0), 'up')) : ''}
      ${tx.carry_short_loss < 0 || tx.carry_long_loss < 0 ? row('Loss to carry forward (8 years)', money(tx.carry_short_loss + tx.carry_long_loss)) : ''}</tbody></table></div></div>
      <div class="card"><h2>Intraday and charges</h2><div class="tablewrap"><table><tbody>${row('Intraday profit (taxed at your income slab, not estimated)', money(tx.intraday), cls(tx.intraday))}
      ${row('Charges on delivery trades (estimate)', inr(d.charges.delivery, 0))}${row('Charges on intraday trades (estimate)', inr(d.charges.intraday, 0))}</tbody></table></div>
      <p class="note">Surcharge is not included. Rates: shares sold from 23 Jul 2024 on, STCG 20% and LTCG 12.5% above ₹1.25 lakh a year. Same-day buy and sell of a stock counts as intraday. Estimate only: Zerodha Console → Reports → Tax P&amp;L is the official statement; check with your tax adviser.</p></div></div>
      <div class="card"><h2>Each lot you hold · when it turns long-term</h2>${T([['Stock'], ['Bought on'], ['Qty', 'num'], ['Buy price', 'num'], ['Days held', 'num'], ['Status'], ['Long-term from'], ['Gain now', 'num']], lots, 'No open lots.')}</div>`;
  } else if (tab === 'sectors') {
    const maxV = Math.max(1, ...d.sectors.map(s => s.value));
    body = `<div class="card"><h2>By sector</h2>${T([['Sector'], ['Stocks'], ['Value', 'num'], ['Share', 'num'], [''], ['Not yet booked', 'num'], ['Booked in FY ' + esc(d.fy), 'num']],
      d.sectors.map(s => `<tr><td><b>${esc(s.sector)}</b>${s.over ? ' <span class="pill fail">over limit</span>' : ''}</td><td>${s.stocks.map(esc).join(', ') || '<span class="muted">sold out</span>'}</td><td class="num">${inr(s.value, 0)}</td><td class="num">${s.pct.toFixed(1)}%</td>
        <td style="min-width:120px"><div class="capbar"><i style="width:${(s.value / maxV * 100).toFixed(0)}%" class="${s.over ? 'full' : ''}"></i></div></td><td class="num ${cls(s.pnl)}">${money(s.pnl)}</td><td class="num ${cls(s.realised)}">${money(s.realised)}</td></tr>`), 'No holdings recorded yet.')}
      <p class="note">Over limit = more than ${d.settings.max_per_sector} stocks or more than 25% of the value in one sector (your Limits). Sectors from NSE's index list; stocks outside the Nifty 250 show as Other.</p></div>`;
  } else if (tab === 'next') {
    const nx = d.next, li = (arr, f) => arr.length ? `<ul class="nlist">${arr.map(f).join('')}</ul>` : '<p class="note">None.</p>';
    const it = x => `<li><a href="#/predictor/${encodeURIComponent(x.symbol)}"><b>${esc(x.symbol)}</b></a> ${x.why ? '· ' + esc(x.why) : ''}${x.rule_stop ? ` · rule stop ${inr(x.rule_stop)}` : ''}${x.pnl != null ? ` · <span class="${cls(x.pnl)}">${money(x.pnl)}</span>` : ''}${x.next_long ? ` · long-term on ${esc(x.next_long.date)}` : ''}</li>`;
    body = planBlock(nx.plan) + `<div class="grid2">
      <div class="card"><h2><span class="pill fail">Sell</span> Exit signal (rules) · ${nx.exit.length}</h2>${li(nx.exit, it)}</div>
      <div class="card"><h2><span class="pill warn">Watch</span> Weak trend · ${nx.weak.length}</h2>${li(nx.weak, it)}</div>
      <div class="card"><h2><span class="pill pass">Keep</span> Uptrend intact · ${nx.keep.length}</h2>${li(nx.keep, it)}</div>
      <div class="card"><h2><span class="pill hold">Add</span> Buy signal again · ${nx.buy_more.length}</h2>${li(nx.buy_more, it)}</div></div>
      ${nx.unknown && nx.unknown.length ? `<div class="card"><h2>No rule result yet · ${nx.unknown.length}</h2><p class="note">Connect Zerodha (Live holdings tab) once so the rules can judge these: ${nx.unknown.map(x => esc(x.symbol)).join(', ')}.</p></div>` : ''}
      <div class="card"><h2>Your own limits</h2>${li(nx.limits, x => `<li>${esc(x)}</li>`)}</div>
      <div class="card"><h2>Tax timing</h2>${li(nx.tax, x => `<li>${esc(x)}</li>`)}</div>
      <div class="card"><h2>Rule buy signals you have room for</h2><p class="note">${nx.slots} free place${nx.slots === 1 ? '' : 's'} of ${d.settings.max_positions} · up to ${inr(nx.per_stock, 0)} each · funds available ${nx.cash != null ? inr(nx.cash, 0) : 'unknown'}${nx.regime === false ? ' · <b>market filter is off: the Investing rules hold off new buys</b>' : ''}</p>
        ${li(nx.buys || [], b => `<li><a href="#/predictor/${encodeURIComponent(b.symbol)}"><b>${esc(b.symbol)}</b></a> · ${esc(b.sector || '')} · ${esc(b.setup || '')} at ${inr(b.price)}${b.rs6 != null ? ` · 6-month vs Nifty ${sgn(b.rs6)}` : ''}</li>`)}</div>
      <p class="note">Sell / keep / add come from the Investing rules (backtested Nov 2017–Nov 2026: ~11%/yr, 38% of trades won, losing years too). Buy ideas are the scanner's “Best odds” signals in sectors where you are under your limit. These are mechanical rule results and facts about your own records, not personal investment advice; decide and place any real order yourself in Zerodha.</p>`;
  } else if (tab === 'core') {
    const c = d.core, pctA = c.actual;
    const bar = pctA == null ? '' : `<div class="corebar" title="Core ${pctA.toFixed(0)}% · target ${c.target}%"><i style="width:${pctA.toFixed(1)}%"></i><b style="left:${c.target}%"></b></div>
      <div class="row" style="justify-content:space-between;font-size:12px;color:var(--muted)"><span>Index funds (core) ${pctA.toFixed(0)}%</span><span>target ${c.target}% ▲</span><span>Stocks (satellite) ${(100 - pctA).toFixed(0)}%</span></div>`;
    const act = !c.total ? '<p class="note">No holdings recorded yet: connect Zerodha once.</p>'
      : Math.abs(c.move) < Math.max(2000, c.total * 0.02) ? `<p><b class="up">On target.</b> Nothing to move.</p>`
      : `<p>${c.due ? '<b>Rebalance due</b>' : 'Next check: April'} · to get back to ${c.target}% index funds: <b>${c.move > 0 ? 'move about ' + inr(c.move, 0) + ' from stocks into the index fund' : 'move about ' + inr(-c.move, 0) + ' from the index fund into stocks'}</b>${c.due ? '' : ` (now ${c.off.toFixed(0)} points off; the plan rebalances each April or when more than 10 points off)`}.</p>`;
    const li = arr => arr.length ? `<ul class="nlist">${arr.map(x => `<li>${esc(x.name)} <small class="muted">${esc(x.kind)}</small> · ${inr(x.value, 0)}</li>`).join('')}</ul>` : '<p class="note">None.</p>';
    body = `<div class="card"><h2>Your split: index funds (core) vs stocks (satellite)</h2>
      <div class="kv" style="margin:0 0 12px"><div><span>Core · index funds</span><b>${inr(c.core_value, 0)}</b></div><div><span>Satellite · stocks</span><b>${inr(c.sat_value, 0)}</b></div>
        <div><span>Core share now</span><b>${pctA != null ? pctA.toFixed(1) + '%' : '–'}</b></div><div><span>Your target</span><b>${c.target}%</b></div></div>
      ${bar}${act}</div>
      <div class="grid2"><div class="card"><h2>Core · ${c.core.length}</h2>${li(c.core)}</div><div class="card"><h2>Satellite · ${c.satellite.length}</h2>${li(c.satellite)}</div></div>
      ${c.other_mf.length ? `<div class="card"><h2>Other mutual funds (not counted)</h2>${li(c.other_mf)}</div>` : ''}
      <div class="card"><h2>Your target</h2><form id="coreF" class="grid">
        <label>Share in index funds (%)<input name="target" type="number" min="0" max="100" step="5" value="${c.target}"></label>
        <label style="grid-column:span 2">Index funds that count as core (NSE symbols, comma separated)<input name="symbols" value="${esc(c.symbols.join(', '))}" style="text-transform:uppercase"></label>
        <label class="row" style="gap:6px;align-self:end"><input type="checkbox" name="count_mf" ${c.count_mf ? 'checked' : ''}> Count Nifty / Sensex index mutual funds as core</label>
        <div class="row" style="grid-column:1/-1"><button class="btn primary">Save target</button></div></form>
      <p class="note">Tested 19 Nov 2026 (Dec 2017 – Nov 2026, before tax): 50% Nifty with dividends + 50% Trading rules made about 12.2% a year with a worst fall of −22.5%, against 12.2% and −38.3% for the Nifty alone; 70/30 made 12.3% with −28.7%. See Time machine for the full table. The satellite part is your other stocks, best run by the rules (Scanner / What next). Rule results, not personal advice.${c.mf_known ? '' : ' Mutual funds are counted from the next snapshot while Zerodha is connected.'}</p></div>`;
  } else if (tab === 'funds') {
    const f = d.funds;
    body = `${f ? `<div class="kv" style="margin:0"><div><span>Funds available</span><b>${f.net != null ? inr(f.net, 0) : '–'}</b></div><div><span>Cash balance</span><b>${f.cash != null ? inr(f.cash, 0) : '–'}</b></div><div><span>Opening balance</span><b>${f.opening != null ? inr(f.opening, 0) : '–'}</b></div><div><span>Used (margin)</span><b>${f.used != null ? inr(f.used, 0) : '–'}</b></div></div>` : '<div class="banner">No funds recorded yet: connect Zerodha.</div>'}
      <div class="card"><h2>Day by day · ${d.funds_history.length} records</h2>${T([['Date'], ['Saved at'], ['Funds available', 'num'], ['Cash', 'num'], ['Used', 'num'], ['Holdings value', 'num'], ['Invested', 'num']],
        d.funds_history.slice().reverse().map(r => `<tr><td class="mono">${esc(r.date)}</td><td class="mono muted">${esc((r.at || '').slice(11, 16))}</td><td class="num">${r.net != null ? inr(r.net, 0) : '–'}</td><td class="num">${r.cash != null ? inr(r.cash, 0) : '–'}</td><td class="num">${r.used != null ? inr(r.used, 0) : '–'}</td><td class="num">${r.value != null ? inr(r.value, 0) : '–'}</td><td class="num">${r.cost != null ? inr(r.cost, 0) : '–'}</td></tr>`), 'No records yet.')}
      <p class="note">Saved whenever you open My holdings while Zerodha is connected, and every trading day after the close. Kept on the NAS even when Zerodha is disconnected.</p></div>`;
  } else if (tab === 'import') {
    const man = Object.values(d.trades).filter(x => x.source === 'manual');
    body = `${mismBox}<div class="card"><h2>Upload Zerodha's P&amp;L statement</h2>
      <p class="note">Console → Reports → P&amp;L → Segment Equity → pick the financial year → Download (Excel or CSV). Adds Zerodha's own profit per stock beside the record, stocks the tradebook misses, the real charges and other debits / credits. Uploading the same year again replaces it. ${d.pnl ? `<b>FY ${esc(d.fy)} saved ${esc(d.pnl.at)}</b> (${esc(d.pnl.file || '')}).` : 'Nothing saved for this year yet.'}</p>
      <div class="row"><input type="file" id="plFile" accept=".xlsx,.csv"><button class="btn primary" id="plGo">Import P&amp;L</button></div></div>
      <div class="card"><h2>Upload your Zerodha tradebook</h2>
      <ol class="note" style="line-height:1.8;margin:0 0 12px 18px"><li>Open <a href="https://console.zerodha.com/reports/tradebook" target="_blank" rel="noopener">Zerodha Console → Reports → Tradebook</a> and sign in there.</li>
      <li>Segment <b>Equity</b>; date range from your <b>first ever purchase</b> of the shares you still hold up to today (Console allows one year per download: download each year).</li>
      <li>Click Download → CSV, then pick the file(s) here. Uploading the same trades twice is safe: duplicates are skipped.</li></ol>
      <div class="row"><input type="file" id="tbFile" accept=".csv,text/csv" multiple><button class="btn primary" id="tbGo">Import</button></div>
      ${d.imports.length ? `<h3 style="margin:14px 0 6px">Imported</h3>${T([['When'], ['File'], ['Trades from – to'], ['Added', 'num'], ['Skipped', 'num']], d.imports.slice().reverse().map(i => `<tr><td class="mono">${esc(i.at)}</td><td>${esc(i.file || '')}</td><td class="mono">${esc(i.from)} – ${esc(i.to)}</td><td class="num">${i.added}</td><td class="num">${i.skipped}</td></tr>`), '')}` : ''}</div>
      <div class="card"><h2>Add a trade by hand</h2><p class="note">For bonus shares (price 0), a split, shares moved in from another broker, or a day the portal missed.</p>
      <form id="manF" class="grid"><label>Date<input name="date" type="date" required></label><label>Stock<input name="symbol" list="symbols" required style="text-transform:uppercase"></label>
        <label>Buy or sell<select name="side"><option value="buy">Buy</option><option value="sell">Sell</option></select></label><label>Quantity<input name="qty" type="number" min="0.001" step="any" required></label>
        <label>Price (₹)<input name="price" type="number" min="0" step="0.01" required></label><label>Note<input name="note" maxlength="80"></label><div class="row" style="grid-column:1/-1"><button class="btn primary">Add trade</button></div></form>
      ${man.length ? T([['Date'], ['Stock'], ['Buy / sell'], ['Qty', 'num'], ['Price', 'num'], ['Note'], ['']], man.map(x => `<tr><td class="mono">${esc(x.date)}</td><td><b>${esc(x.symbol)}</b></td><td>${esc(x.side)}</td><td class="num">${fmtQ(x.qty)}</td><td class="num">${inr(x.price)}</td><td>${esc(x.note || '')}</td><td><button class="btn sm ghost" data-mdel="${esc(x.id)}">Delete</button></td></tr>`), '') : ''}
      <p class="note">Only this financial year's hand-added trades are listed here; switch the year at the top to see others.</p></div>
      <div class="card"><h2>Your record</h2><p class="note">${d.records.trades} trades and ${d.records.snapshots} daily snapshots saved on the NAS${d.records.first_trade ? `, first trade ${esc(d.records.first_trade)}` : ''}. Nothing is deleted when Zerodha disconnects.</p></div>`;
  }
  const tv = totals(d), scTop = scHead('Holdings value', plain(tv.value), tv.cost ? tv.unrealised / tv.cost * 100 : null,
    `${esc(per_)} · invested ${plain(tv.cost)} · ${d.holdings.length} holding${d.holdings.length === 1 ? '' : 's'} · pill = profit not yet booked`);
  view.innerHTML = head('My holdings', status, right) + hTabs(tab) + `<div class="stack">${scTop}${startHelp}${body}</div>`;
  if (tab === 'next') planNews(S.nav);
  $('#lFy').onchange = e => { S.ledgerFy = e.target.value; S.ledgerRange = null; S.ledger = null; ledgerPage(tab); };
  const setRange = (from, to) => {
    S.ledgerRange = from || to ? { from, to } : null;
    if (from) S.ledgerFy = fyOfMonth(from.slice(0, 7));   // tax and Zerodha P&L follow the year the period starts in
    S.ledger = null; ledgerPage(tab);
  };
  if ($('#lfYear')) {
    $('#lfYear').onclick = () => setRange(null, null);
    $('#lfMonth').onchange = e => { const m = e.target.value; if (!m) return; const [y, mo] = m.split('-').map(Number); setRange(m + '-01', `${m}-${String(new Date(y, mo, 0).getDate()).padStart(2, '0')}`); };
    $('#lfApply').onclick = () => { const a = $('#lfFrom').value, b = $('#lfTo').value; if (!a && !b) { toast('Pick a From and / or To date.', 'bad'); return; } setRange(a, b); };
    view.querySelectorAll('tr[data-month]').forEach(tr => tr.onclick = () => { const m = tr.dataset.month, [y, mo] = m.split('-').map(Number); setRange(m + '-01', `${m}-${String(new Date(y, mo, 0).getDate()).padStart(2, '0')}`); });
  }
  $('#lRefresh').onclick = () => ledgerPage(tab, true);
  $('#lCsv').onclick = async () => {
    try {
      const r = await api('/api/ledger/csv?fy=' + encodeURIComponent(d.fy));
      const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([r.csv], { type: 'text/csv' })); a.download = r.name; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    } catch (e) { toast(e.message, 'bad'); }
  };
  if (tab === 'core') {
    $('#coreF').onsubmit = async e => {
      e.preventDefault(); const f = new FormData(e.target);
      try {
        const r = await api('/api/ledger/core', { target: +f.get('target'), symbols: String(f.get('symbols') || '').split(',').map(x => x.trim()).filter(Boolean), count_mf: f.get('count_mf') === 'on' });
        toast(r.message); S.ledger = null; ledgerPage('core');
      } catch (err) { toast(err.message, 'bad'); }
    };
  }
  if (tab === 'import') {
    $('#tbGo').onclick = async () => {
      const files = [...$('#tbFile').files]; if (!files.length) { toast('Pick the tradebook CSV file first.', 'bad'); return; }
      $('#tbGo').disabled = true;
      for (const f of files) {
        try { const r = await api('/api/ledger/import', { csv: await f.text(), name: f.name }); toast(`${f.name}: ${r.message}`); } catch (e) { toast(`${f.name}: ${e.message}`, 'bad'); }
      }
      S.ledger = null; ledgerPage('import');
    };
    $('#plGo').onclick = async () => {
      const f = $('#plFile').files[0]; if (!f) { toast('Pick the P&L file first.', 'bad'); return; }
      $('#plGo').disabled = true;
      try {
        const bytes = new Uint8Array(await f.arrayBuffer()); let bin = '';
        for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
        const r = await api('/api/ledger/pnl', { b64: btoa(bin), name: f.name }); toast(r.message);
        S.ledgerFy = r.fy; S.ledger = null; ledgerPage('record');
      } catch (e) { $('#plGo').disabled = false; toast(e.message, 'bad'); }
    };
    $('#manF').onsubmit = async e => {
      e.preventDefault(); const body = Object.fromEntries(new FormData(e.target)); body.action = 'add';
      try { const r = await api('/api/ledger/manual', body); toast(r.message); S.ledger = null; ledgerPage('import'); } catch (err) { toast(err.message, 'bad'); }
    };
    view.querySelectorAll('[data-mdel]').forEach(b => b.onclick = async () => {
      try { const r = await api('/api/ledger/manual', { action: 'delete', id: b.dataset.mdel }); toast(r.message); S.ledger = null; ledgerPage('import'); } catch (err) { toast(err.message, 'bad'); }
    });
  }
}
function fyOfMonth(m) { const [y, mo] = m.split('-').map(Number); const s = mo >= 4 ? y : y - 1; return `${s}-${String((s + 1) % 100).padStart(2, '0')}`; }
function totals(d) { return d.totals_cache || (d.totals_cache = d.totals || {}); }
const fmtQ = v => v == null ? '–' : (Math.round(v * 1000) / 1000).toLocaleString('en-IN');

/* ---- Limits: change / reset the PIN */
function pinCard(box) {
  if (!box) return;
  box.innerHTML = `<h2>My holdings PIN</h2><p class="note">Asked every time My holdings opens. 4 digits.</p>
    <form id="pinChg" class="grid" autocomplete="off"><label>Current PIN<input id="pcOld" type="password" inputmode="numeric" maxlength="4" class="pin-in"></label>
      <label>New PIN<input id="pcNew" type="password" inputmode="numeric" maxlength="4" class="pin-in"></label><label>New PIN again<input id="pcNew2" type="password" inputmode="numeric" maxlength="4" class="pin-in"></label>
      <div class="row" style="grid-column:1/-1"><button class="btn primary">Change PIN</button><a href="#/holdings" id="pcForgot" class="btn ghost">Forgot it? Reset with the portal password</a></div></form>`;
  $('#pinChg').onsubmit = async e => {
    e.preventDefault();
    if ($('#pcNew').value !== $('#pcNew2').value) { toast('The two new PINs are not the same.', 'bad'); return; }
    try { const r = await api('/api/ledger/pin/change', { old: $('#pcOld').value, pin: $('#pcNew').value }); toast(r.message); e.target.reset(); S.pinTok = null; }
    catch (err) { toast(err.message, 'bad'); }
  };
  $('#pcForgot').onclick = () => { S.pinReset = true; };
}
