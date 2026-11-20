/* AI Robot page (paper only). Self-contained: adds its own menu entry and route, so removing this file
   (and its <script> line + robot.py) removes the whole feature without touching anything else. */
(function () {
  const nav = document.querySelector('#nav a[data-view="journal"]');
  if (nav && !document.querySelector('#nav a[data-view="robot"]')) {
    nav.insertAdjacentHTML('afterend', '<a href="#/robot" data-view="robot"><i>🤖</i><span>AI Robot<small>paper · runs by itself</small></span></a>');
  }
  const SL = { orb: '🌅', swing: '📈', pm: '🧪' };
  const money = v => (v < 0 ? '−' : '+') + inr(Math.abs(v), 0);

  function curve(pts, cap) {
    if (!pts || pts.length < 2) return '<p class="note">The money line appears after two trading days.</p>';
    const W = 640, H = 140, vals = pts.map(p => p.equity).concat([cap]);
    const lo = Math.min(...vals), hi = Math.max(...vals), sx = i => i / (pts.length - 1) * W, sy = v => H - (v - lo) / ((hi - lo) || 1) * (H - 10) - 5;
    const line = pts.map((p, i) => `${i ? 'L' : 'M'}${sx(i).toFixed(1)},${sy(p.equity).toFixed(1)}`).join(' ');
    const up = pts[pts.length - 1].equity >= cap;
    return `<svg viewBox="0 0 ${W} ${H}" class="rb-curve" role="img" aria-label="Money over time">
      <line x1="0" x2="${W}" y1="${sy(cap)}" y2="${sy(cap)}" stroke="var(--border)" stroke-dasharray="4 4"/>
      <path d="${line}" fill="none" stroke="${up ? 'var(--pass)' : 'var(--fail)'}" stroke-width="2.5"/></svg>
      <p class="note" style="margin:4px 0 0">${esc(pts[0].date)} → ${esc(pts[pts.length - 1].date)} · dashed line = starting money</p>`;
  }

  async function robotPage() {
    const my = S.nav;
    view.innerHTML = head('🤖 AI Robot', 'Paper money only · decides and trades by itself · you stay in control') + loading(2);
    let d; try { d = await api('/api/robot'); } catch (e) { view.innerHTML = head('🤖 AI Robot', 'Not available') + failBox(e); return; }
    if (my !== S.nav) return;
    const prog = Math.max(0, Math.min(100, (d.equity - d.capital) / (d.goal - d.capital) * 100));
    const dd = (1 - d.equity / (d.peak || d.equity)) * 100;
    const ch = d.charges || {};
    view.innerHTML = head('🤖 AI Robot', `Paper only · started ${esc(d.started || 'now')} · never sends a real order`,
      `<label class="row" style="gap:8px;margin:0"><b>${d.on ? 'Running' : 'Stopped'}</b><span class="switch"><input type="checkbox" id="rbOn" ${d.on ? 'checked' : ''}><span></span></span></label>`) + `
    <div class="card rb-top">
      <div class="kv sc-kv" style="margin:0">
        <div><span>Money now</span><b>${inr(d.equity, 0)}</b></div>
        <div class="${d.gain_pct >= 0 ? 'tile-up' : 'tile-down'}"><span>Since start</span><b>${money(d.equity - d.capital)} (${sgn(d.gain_pct)})</b></div>
        <div><span>Goal (2×)</span><b>${inr(d.goal, 0)}</b></div>
        <div class="${dd > 5 ? 'tile-down' : ''}"><span>Below the peak</span><b>${dd.toFixed(1)}%</b></div>
        <div><span>Free cash</span><b>${inr(d.cash, 0)}</b></div></div>
      <div class="rb-bar" title="Progress to 2×"><i style="width:${prog.toFixed(1)}%"></i></div>
      <p class="note" style="margin:6px 0 0">${prog.toFixed(1)}% of the way to doubling.${d.pace ? ` Pace ${sgn(d.pace.per_day_pct)} a day${d.pace.days_to_double ? ` → about ${d.pace.days_to_double} trading days to 2× at this pace` : ''}.` : ' Pace shows after 5 trading days.'}
      ${d.pause_until ? ` <b class="down">New entries paused until ${esc(d.pause_until)} (fell 15% from the peak).</b>` : ''}</p>
      ${curve(d.curve, d.capital)}
    </div>

    <div class="card"><h2>How the robot decides</h2>
      <p class="note" style="margin-top:0">Each strategy starts at a size that matches how well it was tested, then <b>earns or loses its share by its own results after all charges</b> (last 20 trades). It trades smaller when below the peak or when India VIX is above 22, stops for the day after −3%, pauses a week after −15%. Never more than your cap per trade.</p>
      <div class="rb-strats">${d.strategies.map(s => `<div class="rb-strat ${s.on ? '' : 'off'}">
        <div class="row" style="justify-content:space-between"><b>${SL[s.id] || ''} ${esc(s.label)}</b><span class="switch"><input type="checkbox" data-rbs="${s.id}" ${s.on ? 'checked' : ''}><span></span></span></div>
        <p class="note">${esc(s.why)}</p>
        <div class="rb-nums"><span>Size <b>${s.factor}×</b></span><span>Trades <b>${s.n}</b></span><span>Won <b>${s.n ? Math.round(s.won / s.n * 100) + '%' : '–'}</b></span>
          <span>Net <b class="${cls(s.net)}">${money(s.net)}</b></span><span>Charges <b>${inr(s.charges, 0)}</b></span></div>
        <p class="note" style="margin:6px 0 0">${esc(s.factor_why)}</p></div>`).join('')}</div>
      <div class="row" style="gap:10px;margin-top:12px;align-items:center"><span class="note" style="margin:0">Most it may risk on one trade:</span>
        <select id="rbCap" class="sel">${[0.5, 1, 1.5, 2, 2.5, 3].map(v => `<option value="${v}" ${+d.risk_cap === v ? 'selected' : ''}>${v}% of its money</option>`).join('')}</select></div>
    </div>

    <div class="card"><h2>Open positions · ${d.positions.length}</h2>${d.positions.length ? `<p class="note" style="margin-top:0">Capital in use: <b>${inr(d.positions.reduce((a, p) => a + p.entry * p.qty, 0), 0)}</b> in stocks · money blocked <b>${inr(d.positions.reduce((a, p) => a + p.margin, 0), 0)}</b> (scalps need only 20% margin) · free cash ${inr(d.cash, 0)}</p>` : ''}${d.positions.length ? `<div class="tablewrap"><table><thead><tr><th>Stock</th><th>Type</th><th class="num">Qty</th><th class="num">Entry</th><th class="num">Capital used</th><th class="num">Now</th><th class="num">Stop</th><th class="num">Target</th><th class="num">P/L</th><th>Why</th></tr></thead><tbody>
      ${d.positions.map(p => { const pl = ((p.last || p.entry) - p.entry) * p.qty; return `<tr><td><a href="#/predictor/${encodeURIComponent(p.symbol)}"><b>${esc(p.symbol)}</b></a><small class="muted" style="display:block">${esc(p.opened)}</small></td>
        <td>${SL[p.strat] || ''} ${p.kind === 'intraday' ? 'Scalp' : 'Swing'}</td><td class="num">${p.qty}</td><td class="num">${inr(p.entry)}</td><td class="num"><b>${inr(p.entry * p.qty, 0)}</b>${p.kind === 'intraday' ? `<small class="muted" style="display:block">margin ${inr(p.margin, 0)}</small>` : ''}</td><td class="num">${inr(p.last)}</td><td class="num">${inr(p.stop)}</td><td class="num">${p.target ? inr(p.target) : 'trail'}</td>
        <td class="num ${cls(pl)}"><b>${money(pl)}</b></td><td><small>${esc(p.why)} · risk ${p.risk_pct}%</small></td></tr>`; }).join('')}</tbody></table></div>` : '<p class="note">No open positions. The robot looks for trades 09:35–10:30 (morning breakouts), 09:20–15:00 (swings) and 14:30 (afternoon test).</p>'}</div>

    <div class="card"><h2>Charges and tax (what changes your money)</h2>
      <div class="rb-nums wide"><span>Brokerage <b>${inr(ch.brokerage || 0)}</b></span><span>STT <b>${inr(ch.stt || 0)}</b></span><span>Exchange <b>${inr(ch.exchange || 0)}</b></span>
        <span>SEBI <b>${inr(ch.sebi || 0)}</b></span><span>Stamp duty <b>${inr(ch.stamp || 0)}</b></span><span>GST <b>${inr(ch.gst || 0)}</b></span><span>DP <b>${inr(ch.dp || 0)}</b></span><span>Total <b>${inr(ch.total || 0)}</b></span></div>
      <p class="note">Every trade pays real Zerodha charges plus 0.03% slippage each side; all results above are <b>after</b> charges. If this were real money, estimated tax on profits so far: scalps (business income, assumed 30% slab) <b>${inr(d.tax_est.intraday, 0)}</b> · swings (short-term gains 20%) <b>${inr(d.tax_est.swing, 0)}</b>.</p></div>

    <div class="card"><h2>Learning model</h2><p style="margin:0"><span class="pill ${d.model.ready ? 'pass' : ''}">${d.model.ready ? 'Active' : 'Watching'}</span> ${esc(d.model.why || '')}</p>
      <p class="note">Learns from every trade the robot considered (${d.samples} so far): time, volume, range, Nifty, VIX, news. Allowed to skip weak trades only after it predicts better than chance on days it never trained on. Retrains every day after the close.</p></div>

    <div class="card"><h2>Closed trades · ${d.trades.length}</h2>${d.trades.length ? `<div class="tablewrap"><table><thead><tr><th>Closed</th><th>Stock</th><th>Type</th><th class="num">Qty</th><th class="num">Buy</th><th class="num">Sell</th><th class="num">Capital used</th><th class="num">Charges</th><th class="num">Net</th><th class="num">R</th><th>Exit</th></tr></thead><tbody>
      ${d.trades.map(t => `<tr><td class="mono">${esc(t.closed.slice(5))}</td><td><b>${esc(t.symbol)}</b></td><td>${SL[t.strat] || ''} ${t.kind === 'intraday' ? 'Scalp' : 'Swing'}</td><td class="num">${t.qty}</td><td class="num">${inr(t.entry)}</td><td class="num">${inr(t.exit)}</td><td class="num">${inr(t.entry * t.qty, 0)}</td>
        <td class="num">${inr(t.charges.total)}</td><td class="num ${cls(t.net)}">${money(t.net)}</td><td class="num ${cls(t.r)}">${t.r.toFixed(2)}</td><td><small>${esc(t.reason)}</small></td></tr>`).join('')}</tbody></table></div>` : '<p class="note">None yet.</p>'}</div>

    <div class="card"><h2>Robot diary</h2><ul class="rb-log">${d.log.length ? d.log.map(l => `<li class="${esc(l.kind)}"><span class="mono">${esc(l.at.slice(5))}</span> ${esc(l.text)}</li>`).join('') : '<li>Nothing yet. Entries appear as the robot works.</li>'}</ul></div>

    <div class="card"><h2>Your controls</h2>
      <form class="cnform" autocomplete="off" onsubmit="return false"><div class="cngrid">
        <label>Portal password <small class="muted">(for the two buttons below)</small><input id="rbPw" type="password" autocomplete="current-password"></label>
        <label>Start money for a reset (₹)<input id="rbCapital" inputmode="numeric" value="${Math.round(d.capital)}"></label>
        <label>Robot trading alert time <small class="muted">(trading days, HH:MM)</small><input id="rbAlertAt" value="${esc(d.alert_at)}" maxlength="5"></label></div>
        <div class="row" style="gap:8px;justify-content:flex-end"><button class="btn" type="button" id="rbAlertSave">Save alert time</button><button class="btn" type="button" id="rbAlertTest">Send test alert now</button></div>
        <div class="row" style="gap:8px;justify-content:flex-end"><button class="btn" type="button" id="rbClose">Close all positions now</button><button class="btn danger" type="button" id="rbReset">Reset the robot</button></div></form>
      <p class="note">The robot keeps working whatever else the portal does, and after a NAS restart it carries on: scalps left open are squared off at the 15:20 price, swings catch up on missed days. Telegram: “🤖 ROBOT TRADING ALERT” after the close (time above), plus 09:35 buys and 15:00 scalps closed; switch it off in the Telegram table on the Limits page. Paper only; no strategy is promised to make money.</p></div>`;
    const go = async body => { try { const r = await api('/api/robot', body); toast(r.message); robotPage(); } catch (e) { toast(e.message, 'bad'); } };
    $('#rbOn').onchange = e => go({ action: e.target.checked ? 'on' : 'off' });
    view.querySelectorAll('[data-rbs]').forEach(x => x.onchange = () => go({ action: 'strat', id: x.dataset.rbs, on: x.checked }));
    $('#rbCap').onchange = e => go({ action: 'risk_cap', value: +e.target.value });
    $('#rbAlertSave').onclick = () => go({ action: 'alert_at', value: $('#rbAlertAt').value.trim() });
    $('#rbAlertTest').onclick = () => go({ action: 'alert_test' });
    $('#rbClose').onclick = async () => { if (await askConfirm('Close every robot position?', 'All open paper positions are sold at the latest price.', 'Close all')) go({ action: 'close_all', password: $('#rbPw').value }); };
    $('#rbReset').onclick = async () => { if (await askConfirm('Reset the robot?', 'All its trades, history and learning are wiped and it starts again with the money you entered.', 'Reset')) go({ action: 'reset', password: $('#rbPw').value, capital: +$('#rbCapital').value }); };
    clearInterval(S.timer); S.timer = setInterval(() => { if (location.hash.startsWith('#/robot') && !document.querySelector('#rbPw:focus, #rbCapital:focus, #rbAlertAt:focus')) robotPage(); }, 60000);
  }

  VIEWS.robot = robotPage;
  if (location.hash.startsWith('#/robot')) route();
})();
