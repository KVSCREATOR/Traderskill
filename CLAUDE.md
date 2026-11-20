# Tradeskill Portal — context for Claude Code

Read this first when continuing work on this project (on any PC).

## What it is
A local web portal (Python 3.9+ standard library only, no packages) that scores
Indian NSE stocks as purchase setups. `python server.py` → http://127.0.0.1:8765
(or double-click `start.bat`). Indian market ONLY — the owner explicitly removed all
US-market features (the US "pelosi"/Congress screen was replaced by NSE "Big deals").

## Owner preferences (keep these)
- Indian stock market only. Prices in ₹, times in IST.
- Owner writes short, informal messages; when something is ambiguous, ask briefly,
  otherwise pick a sensible default and say so.
- Paper (simulated) broker only. Never send real orders; never give personal
  investment advice (not a licensed advisor) — the portal is a screening tool.
- When Yahoo Finance has no data for a stock: fall back to NSE end-of-day file, then
  BSE end-of-day file, and show a pop-up alert whenever the source switches.
- Commit author: `KVSCREATOR <KVSCREATOR@users.noreply.github.com>` (keep the
  owner's personal email out of git history).
- Backup + remote collaboration: private repo https://github.com/KVSCREATOR/Traderskill
  — commit and push after each finished change.

## Owner's trading parameters
- Capital: ₹2,00,000.
- Risk per trade: ₹2,500.
- Up to 10 stocks held at once; no more than ₹25,000 in any one stock.
- Holding: up to 2–3 months for trading; 6–12 months for investing.

## Architecture
- `server.py` — HTTP server + all logic: data fetch (Yahoo → NSE → BSE fallback),
  intraday engine (15-min opening-range breakout, 2R target, 15:15 square-off,
  Monte Carlo "time machine"), earnings, news (Google/Bing RSS), NSE bulk/block deals,
  budget/risk checks, alerts, paper broker. State in `data/state.json` (git-ignored).
- `static/index.html`, `app.css`, `app.js` — single-page UI, hash routes
  (`#/predictor/SYM`, `#/scanner`, `#/orb`, `#/entry`, `#/exit`, `#/odds`, `#/budget`,
  `#/risk`, `#/news`, `#/earnings`, `#/deals`, `#/alerts`, `#/broker`, `#/settings`).
- `nifty250.json` (Nifty LargeMidcap 250 from NSE's official list), `nifty50.json`.
- Menu has one entry per skill: scanner, nse-scanner (ORB), entry, exit, timemachine,
  budget, risk, news, analyst (earnings), big deals (replaces pelosi), alerts, broker.

## Work in progress (Nov 2026) — three modes
Owner asked for three versions selectable at the top-right, and a chooser on opening:
1. **Scalping** = existing intraday engine (keep as is).
2. **Trading** = swing, hold up to 2–3 months (~60 trading days).
3. **Investing** = hold 6–12 months.

Agreed design for Trading/Investing (daily bars, ~10 years of history):
- Setups: base breakout (40-day high, base ≤25% deep, volume ≥1.5×), pullback to
  20/50-day average in an uptrend; Investing: long uptrend (above rising 200-day),
  52-week-high breakout or pullback to 50-day.
- Relative strength vs Nifty (3-month for trading, 6-month for investing).
- Market filter: Nifty above 50/200-day averages (trading), above 200-day (investing).
- Exit: ATR-based stop (trading 4–12% of price, investing 8–20%), trading target 2.5R,
  move stop to break-even after +1R then trail; time exit (60 / 250 trading days);
  investing also exits on close well below the 200-day average.
- Sizing: qty = min(risk ₹2,500 / risk-per-share, ₹25,000 / price); max 10 positions,
  max 2 per sector, total open risk cap, pause new buys after a 10% account drawdown.
- Costs: delivery ≈0.12% per side + ₹16 DP charge on sells. Tax: STCG 20% (<12 months),
  LTCG 12.5% above ₹1.25 lakh.
- Time machine for these modes = portfolio backtest of the rules on all 250 stocks
  (win rate, avg win/loss, expectancy, max drawdown, CAGR, yearly returns, equity curve).
  Note: survivorship bias (uses today's index members).
- Separate paper accounts per mode (₹2 lakh each); positions held across days.
- Code: `longterm.py` (Trading + Investing engines, backtests, scanner, paper accounts),
  wired into `server.py`; every API call takes `mode=intraday|swing|invest`.
  UI: `static/modes.js` (chooser, top-right switch, predictor + daily chart) and
  `static/modes2.js` (skill pages, scanner, portfolio backtest, broker, limits).

## Status (17 Nov 2026)
DONE and tested in the browser: three modes, chooser on every open, top-right switch,
mode-aware Predictor / Scanner / Strength ranking / Entry / Exit / Time machine /
Budget / Risk / Paper broker / Limits; per-mode settings and paper accounts.

Trading rules v2 (adopted 17 Nov 2026, owner asked to improve them):
- Changes vs v1: no fixed 2.5R target (trail only), only buy within 10% of the 52-week
  high, stop to break-even after +2R instead of +1R.
- Method (to avoid over-fitting): each change tested alone, then combinations, scored
  separately on Dec 2017–Jun 2022 and Jul 2022–Nov 2026; then every signal on all stocks
  (no portfolio limits) measured in R: v1 +0.15R/trade → v2 +0.30R (+0.10→+0.16 in
  period A, +0.20→+0.42 in period B); nudging each setting kept +0.27 to +0.33R.
- History now starts after any one-day move < −35% or > +60% (unadjusted demerger /
  split / bonus: MOTILALOFS, TMPV, VEDL).

Backtest results (Nov 2017 – Nov 2026, ₹2 lakh, owner's limits, after costs):
- Trading v2: ₹5.25 lakh, ~11.5%/yr, worst fall −25%, 535 trades, 39% won, profit factor 1.70
  (v1 was ~5.3%/yr, PF 1.17).
- Investing: ₹4.98 lakh, ~11.0%/yr, worst fall −28%, 312 trades, 38% won, profit factor 1.90.
Both have losing years (e.g. 2018, 2019, 2022); results flatter the past slightly because
they use today's index members.

Forward test (added 17 Nov 2026): Research > Forward test (`#/journal`, `/api/journal`).
The scanner logs each completed-day Trading/Investing signal once (`state.json` → `journal`);
the result is simulated from the first open after the log date with the same rules, shown in
R vs the backtest's +0.29R (Trading) / +0.56R (Investing). Needs ~30+ closed trades to judge.

Prediction features tested 17 Nov 2026 and REJECTED (did not help in both periods):
momentum 12-1 filter (tiny gain, inside noise, bigger drawdown), momentum ranking for
Investing (12.9%/yr but neighbouring settings 6–11% → luck), Stage 2 (150-day rising),
VCP / volatility contraction, sector strength, India VIX filter, NSE delivery % (2020–26
only: better 2020–22, worse Jul 2022–26 in both modes, every threshold). Lesson: shuffling
the order signals are bought moves Trading CAGR 6.6–10.3%, so portfolio gains of 1–2%/yr
are noise; judge per-signal R in both periods. Promoter buying and earnings surprise need
history not freely available — judge them via the forward test instead.

GTT orders (added 17 Nov 2026, `gtt.py`, `/api/gtt`): paper "buy when price reaches X" for all
modes, set any time (meant for when the market is closed). Trading/Investing: daily bars from the
next session, fill at trigger or the gapped open, rule stop (ATR) unless given, valid 1 year.
Scalping: 5-min bars inside the entry window, one session only, user stop + target, 15:15
square-off. Sized and risk-checked at the fill. Buttons on Predictor and Entry; list on Paper broker.

My holdings (added 17 Nov 2026, `kite.py`, `#/holdings`): read-only link to the owner's real
Zerodha account via Zerodha's FREE hosted Kite MCP server (https://mcp.kite.trade/mcp), not the
paid Kite Connect API. OAuth 2.1 + PKCE with dynamic client registration (public client,
redirect http://127.0.0.1:8765/api/kite/callback); token kept only in data/state.json → "kite".
Tools are grouped: holdings = tool `portfolio` with mode=holdings. READ_TOOLS allows ONLY
`portfolio` with modes holdings/positions/profile/margins; `orders`, `gtt`, `alerts` etc. are
refused in code. Zerodha's login expires about daily → "Connect Zerodha" again.

Rule-consistency audit (17 Nov 2026): live Trading/Investing stop now uses the signal day's ATR
(as the backtest); GTT breakouts fill like the rules (Trading/Investing: next open after a daily
close above the trigger, skipped if the open runs > max_ext; Scalping: on a completed 5-min close
above); dip GTTs (trigger below price) fill on touch. Daily chart: volume panel (solid bars pass
the rule's volume test), 20-day avg (Trading), 40-day / 52-week breakout line, signal-day marker;
Investing shows 270 sessions. My holdings verdict follows the selected mode (Scalping → Investing).
Holdings extras (quick-pick bar, Scanner chip, News switch) hide whenever Zerodha is not reachable.

## WHERE TO WORK (since 18 Nov 2026) — the NAS folder is the one and only copy
- Edit the project in `Z:\tradeskill` (= `\\192.168.1.200\docker\tradeskill`, mapped as drive Z: on the PC).
  It is a git clone of https://github.com/KVSCREATOR/Traderskill — commit and push from there.
  `D:\Projects\tradeskill` on the PC is an OLD snapshot: do not edit or run it.
- The container runs the code straight from that folder (docker-compose mounts `./:/app` and `./data:/app/data`),
  so NO rebuild for code changes:
  - static/ (pages, styles, scripts): visible on a browser refresh;
  - *.py: the server checks every 5 s, compiles all .py files and restarts itself (os.execv) only if they compile;
    if one has an error it keeps running the last good version and shows the error on Limits -> Portal program.
    Limits also has a "Restart portal" button (`POST /api/admin/restart`, `GET /api/admin/code`). AUTO_RESTART=0 disables.
  - Rebuild in Container Manager only for Dockerfile / docker-compose.yml / Python-version changes.
- Before saving Python edits on the NAS, compile-check them (a copy in the scratchpad + `compile()`); node cannot
  `--check` files on a UNC path, so copy JS locally first. The live portal picks changes up immediately.
- Network to the NAS is slow (~100 ms): run big copies / git fetches in the background.
- Do not type the owner's NAS, DSM, Zerodha or portal passwords; the owner signs in. DSM uses a self-signed
  certificate that the in-app browser refuses, so DSM clicks are the owner's.

Running on the owner's Synology DS925+ (since 17 Nov 2026): Container Manager project
`tradeskill` at /volume1/docker/tradeskill (built from the Dockerfile, data/ on the volume,
tradeskill.env holds PORTAL_PASSWORD). Open at https://192.168.1.200:8766 = DSM reverse proxy
(HTTPS 8766 -> 127.0.0.1:8765); Zerodha MCP only accepts https or loopback return URLs.
Since 18 Nov 2026 docker-compose publishes `127.0.0.1:8765:8765`, so plain HTTP 8765 is not
reachable from the LAN (owner asked to close it); 8766 HTTPS is the only way in.
PUBLIC_URL can also come from data/public_url.txt. The PC copy is stopped: run ONE copy only.
To update the NAS: copy changed files into the share, then Project -> Build. See NAS.md.

Telegram notifications (added 18 Nov 2026, `telegram.py`, Limits → Telegram, `/api/telegram*`): SEND-ONLY
bot; token from TELEGRAM_BOT_TOKEN (tradeskill.env) or data/telegram_token.txt, never sent to the browser.
Connect finds the chat that pressed Start via getUpdates. Kinds (each on/off): alert, signals, holdings, paper,
summary. A background watcher thread (started in server main) runs check_alerts + GTT checks every 30 s from
09:00–15:45 on weekdays, paper books every 5 min, and once a day from 15:45 sends buy signals for
watchlist + Zerodha holdings, holdings at Exit/Weak (Investing rules) and a daily summary.
Kind `zerodha`: every ~2 min (09:15–15:45) compares Zerodha positions' day_buy/day_sell qty with the last
look (state telegram.zsnap) and sends BUY/SELL messages; first look of the day is silent. Read-only (positions).

Scheduled reports (added 18 Nov 2026, `reports.py`, page `#/notifications`): on trading days only (weekday, not in
settings.holidays, and for 09:32+ the Nifty must have traded today) the watcher sends 08:45 morning outlook (weighted
global cues -> Positive/Mixed/Negative, hit rate judged at 09:32 vs Nifty move, state telegram.outlook_calls), 09:32 day
plan, 15:32 market close, 15:35 holdings (day gains/losses, rule actions, own-limit breaches, buy signals). These replace
the old 15:45 messages. Every notify() is appended to data/notify_log.jsonl (sent / failed / not sent + reason).
Framing agreed with owner: outlook = reading of cues, not a forecast; actions = rule results, not personal advice.

My scanner (added 19 Nov 2026, `mylist.py`, `static/myscan.js`, `#/myscan`, `/api/mylists`, `/api/myscan`, `/api/spark`):
named lists (state "mylists", up to 20 × 50, any NSE symbol, same lists in all modes; settings.watchlist = union of
the lists, so News + Telegram follow them). Sources: list / Zerodha holdings / both. Columns: status (Exit signal /
Buy zone / Near trigger ≤3% / Holding / Watching), distance to trigger, strength percentile vs the 250, plan dialog
(entry, ATR stop, qty, risk checks) → paper GTT confirm box, capacity bar, paper + Zerodha exit levels, ⚠ results
within 7 days (estimate), ⚠ sector full, 6-month hover chart. ☆ buttons on Scanner rows and next to every GTT button.
Client caches a scan 15 min. Phase 2 ideas: Telegram exit alert on close, paper sell GTT, daily My-scanner report.

My holdings yearly record + PIN (added 19 Nov 2026, `ledger.py`, `static/holdings.js`, tabs inside `#/holdings`):
owner asked to keep it all in My holdings (not History). 4-digit PIN asked EVERY time the page opens (route() clears
S.pinTok); PBKDF2 hash in state "holdings_pin"; 5 wrong -> locked, reset needs PORTAL_PASSWORD; change under Limits.
Unlock gives a 30-min token sent as header X-Pin-Token (never the PIN); /api/kite/holdings, /api/kite/extras and
/api/ledger* require it. Data in data/ledger.json (kept when Zerodha disconnects): Console tradebook CSV imports
(dedupe by trade_id; tradebook overrides auto day totals for its date range), daily snapshots (holdings, funds,
verdicts, buy ideas) on page open (max every 2 min) + reports.eod 15:35, today's buys/sells from positions, manual
trades (bonus = price 0). FIFO lots; same-day buy+sell = intraday; LT = sold after 12 months; tax est. STCG 20%,
LTCG 12.5% above 1.25 lakh, set-off ST loss vs LT, +4% cess, no surcharge. Tabs: Live, Year record, Tax, Sectors,
What next (Investing rule verdicts, own limits, tax timing, Best-odds buys with room), Funds, Import & add.
TESTING NOTE: never import server.py from a test without setting BOTH S.DATA and S.STATE_FILE to a temp folder.

Scalping signal study (19 Nov 2026, 7,988 ORB trades, 250 stocks, 24 Aug-18 Nov 2026, Yahoo 5-min max 60 days,
charges 0.11% of price per round trip): the ORB alone averaged -0.18R/trade after charges (-0.28R / -0.09R by half;
gross ~ +0.01R) -> NO edge after costs. Only "opening range 0.5-1x ATR" better in both halves (-0.15R / +0.01R);
stop < 0.4% of price -0.44R (charges). REJECTED (mixed/noise): NR7, daily uptrend, above prior-day high, VWAP,
breakout by 10:30, Nifty above open / up on day, stronger than Nifty, opening volume 1.5x/2x, gap buckets.
Scanner now shows range in ATR + charges in R per ORB, tag "range 0.5-1 ATR", warning "stop too tight for charges",
chip "Range 0.5-1 ATR, stop not too tight" (server: scan_one orb.or_atr / risk_pct / cost_r, ORB_COST).

Scalping EXIT study (19 Nov 2026, same 60 days, 8,015 ORB trades, avg R after charges, halves split 6 Oct):
baseline (stop OR mid, 2R, 15:15) -0.28 / -0.10. No help (mixed): targets 1R/1.5R/3R/none, exit by 11:30/13:00,
break-even after +0.5R/+1R, trailing, entries till 10:30/12:00, stop OR low (+0.10/+0.05 borderline), 0.25 ATR,
0.75%/1%. WORSE: stop at breakout-bar low (-0.57/-0.34). BETTER both halves, monotonic: ATR stop 0.5 (-0.15/-0.02),
0.75 (-0.11/-0.01), 1.0 (-0.08/-0.00); + OR 0.5-1 ATR filter (-0.11/+0.05). Still not positive in both halves:
no exit makes the ORB a reliable winner after charges. Engine NOT changed (owner pref "keep Scalping as is") unless asked.

Nifty comparison (added 19 Nov 2026, longterm.benchmark, Time machine for Trading/Investing): same capital, same days,
ETF-like costs, Nifty taxed once at the end (LTCG), dividends estimated +1.3%/yr (NIFTY_DIV), plus a monthly SIP (XIRR).
Result Dec 2017-Nov 2026 (default limits): Trading rules 11.4%/yr, 9.6% after tax, worst fall -25%; Investing 10.7%,
9.1% after tax, -34%. Nifty bought and held: 10.8% price only / ~12.2% with dividends, ~11.5% / 10.8% after tax,
worst fall -38%. SIP XIRR ~10.4%. => After tax the rules TRAIL holding the Nifty by ~1.7-1.9%/yr; their only edge is a
smaller worst fall.
Owner answers (19 Nov 2026): goal = long-term wealth with SMALLER FALLS; under 15 min a day; some real trades, some
paper; NO paid AI (keep everything free).
Core + satellite test (19 Nov 2026, Nifty with ~1.3% dividends + rules, rebalanced each April, pre-tax):
100% Nifty 12.2%/yr worst -38.3%; 70/30 Nifty/Trading 12.3% -28.7%; 50/50 Nifty/Trading 12.2% -22.5%
(both halves: worst fall 22.5 vs 38.3 to Jun 2022, 11.3 vs 15.3 after); 100% Trading 11.4% -25.2%.
50/50 Nifty/Investing 11.6% -25.7%. => 50/50 Nifty + Trading rules keeps about the Nifty's return with ~40% smaller
worst fall (after-tax roughly 11.0% vs Nifty ~11.6%). REJECTED: Nifty 200-day rule (hold only above 200-day, else
liquid fund 6%): worst fall ~19% but only 7.8-8.8%/yr pre-tax (vs 12.3%) plus extra short-term tax.
Core + satellite BUILT (19 Nov 2026): Time machine shows the mix table (longterm.mixes, from the daily backtest curve);
My holdings tab "Core + satellite" (ledger._core_view): target % (default 50) + list of index ETFs counted as core
(ledger.CORE_DEFAULT, editable) + Nifty/Sensex index mutual funds (snapshot now saves Coin MFs); shows actual split,
amount to move, "rebalance due" in April or when > 10 points off. POST /api/ledger/core. Stored in ledger.json "core".
Today checklist BUILT (19 Nov 2026): first tab of My holdings (ledger.today, GET /api/ledger/today, ticks POST
/api/ledger/today/done kept 30 days in ledger.json "today_done"); groups act / watch / for tomorrow / info: Zerodha not
connected, exit + weak verdicts, own limits, rebalance due, lots turning long-term within 30 days, results within 7 days,
paper positions near stop / closed today, paper GTTs, Trading-rule buy signals with room, list stocks within 3% of
breakout. Same list (short) appended to the 15:35 Telegram eod message (reports.eod -> LG.today_lines).
DONE 20 Nov 2026: index funds in the core list (ledger.core_symbols(), default CORE_DEFAULT) are outside the stock
limits everywhere: per-stock cap + stock count in ledger.report next.limits / slots, kite.holdings flags + warning,
reports.eod breach line; _plan(snap, cfg, core) never sells them and does not count them as stocks, but their value
stays in the total that sector shares are measured against. Today tab still not viewed in a browser.

19 Nov 2026 (evening session), all committed + pushed, checked in the owner's Chrome:
- Look: screener-style, light by default (◐ for dark), 15px text, more colour tokens (--info/--violet/--pink).
  Every page's title bar (.head) is a header card; card h2 indigo; every .kv tile has a coloured top edge.
  Predictor, Scanner (all modes) and every My holdings tab have scHead() big-number card + scTiles() count tiles
  (helpers in modes.js). My holdings button moved to the top bar. P&L treemap on Live holdings (pnlMap, modes2.js).
- Range buttons 1D…Max (rangeBar/sliceRange in modes.js) on the predictor daily chart and the backtest equity chart.
- 3-6 month plan (What next tab, ledger._plan): sells/buys from the TRADING rules (kite adds verdict_t and fit_t,
  snapshot stores them), limits = the owner's Investing limits (same as the rest of My holdings). Sells: exit,
  over per-stock cap (trim), sector over limit, over stock count; weak-trend holdings swapped for Best-odds buys;
  cash includes sale proceeds; "next in line" buys when no place is free. News per sell line (planNews).
- News matching (server._news_match): one-word matches need market words and must not be part of another
  company's name ("Astral Foods", "Gold & Silver"); 12 real headlines tested.
- Investing default max per stock = 50,000 (owner's saved value is still 1,00,000).
- Git on the NAS share needs: git -c safe.directory='%(prefix)///192.168.1.200/docker/tradeskill' -C Z:\ ...
- The in-app browser rejects the NAS certificate; use the owner's Chrome (owner types the PIN).

Ideas not done: alerts on daily close for held positions; real results-date calendar
(currently estimated from the last reported quarter).

## Owner decisions 20 Nov 2026 (plan for best profit in 20-30 min a day)
- The rules manage the owner's REAL stocks (~Rs 12.3 lakh in Zerodha), not a Rs 2 lakh test amount.
- Limits (state.json settings.modes, swing AND invest): capital 12,30,000; risk per trade 15,000 (1.25%, as tested);
  max per stock 1,50,000; 10 stocks; 2 per sector; total open risk 1,50,000; pause after 10% (swing) / 15% (invest) fall.
- Core + satellite target 50% (ledger.json core.target; owner chose 50% Nifty). So the rules manage the stock HALF:
  limits now capital 6,15,000; risk 7,500 (1.25%); max per stock 75,000; open risk 75,000; 10 stocks; 2 per sector.
  Core counts only Nifty 50 / Sensex funds (INDEX_MF regex; core ETF list CORE_DEFAULT). On 20 Nov: core 0%, move ~6.17 lakh.
  Idea: the plan should route trim/sell proceeds into the Nifty fund until the core reaches its target.
- Real holdings are judged by the INVESTING rules everywhere: kite.holdings rmode is always 'invest' (page mode ignored),
  the What next plan (ledger._plan) uses snapshot 'verdict' + 'fit' (Investing) with horizon 6-12 months, Today list and
  the 15:35 Telegram today_lines use 'invest', the 12:00 plan message says Investing rules. verdict_t/fit_t still computed.
- Scalping: keep the mode and the ORB menu entry as is (owner said keep). ORB shows only in Scalping mode by design.
- Telegram cut (owner chose 'evening list + alerts'): state telegram.on ON = eod (15:35), alert, gtt, zerodha, paper,
  stopalert, login, weekly; everything else OFF (switches on Limits -> Telegram; nothing deleted).
- Pace: owner chose 'show everything now' - the What next plan lists every sell/buy at once (no weekly limit).
- Menu simplified (owner chose): main = Predictor, Scanner, ORB/Strength, Time machine, Forward test, Limits; folded
  <details id=navMore> 'More' = Entry, Exit, Budget, Risk, News, Earnings, Big deals, Alerts, Paper broker, History (opens
  itself when one of its pages is shown; red dot when alerts ring). No hash -> #/holdings (Today tab) is the start page.
- BUILT 20 Nov 2026: My holdings > 'Stops · Kite GTT' tab (#/holdings/stops; ledger.stops / stops_done / stop_lines,
  GET /api/ledger/stops, POST /api/ledger/stops/done). Trigger = Investing trailing stop (kite._verdict trail_stop, saved in
  snapshots; older snapshots fall back to rule_stop), rounded down to 0.05, ratcheted up only (ledger.json 'stops'
  {sym: high, kite, kite_qty, kite_at}); limit 2% under trigger; ask to raise only when 2%+ above the GTT set.
  Status hit/new/raise/qty/ok; core index funds skipped; sold stocks forgotten. Today 'act' item + 15:35 Telegram lines.
  The 200-day close rule is NOT a GTT (close-based) - it stays an exit verdict in Today. Not yet viewed in a browser (PIN).
- BUILT 20 Nov 2026: plan fills the Nifty core first. report() computes core_v = _core_view(...) once and passes it to
  _plan(snap, cfg, core, core_v): sell proceeds + free cash buy a Nifty 50 fund (held core ETF or NIFTYBEES) up to
  core_v['move']; only the rest buys stocks. plan['core_buy'] = amount, need, short, fund, target, pct_now, pct_after
  (after every sell/trim/buy). Shown first in the What next Buy column and the 12:00 whatnext message. 20 Nov: 0% -> 49%.
- BUILT 20 Nov 2026: My holdings > 'You vs Nifty' tab (ledger.vs_nifty, GET /api/ledger/vsnifty). Start = day before the
  first trade on record; shares held then count as money in at that close (qty = snapshot qty - net trades since);
  every buy/sell copied into Nifty 50 (price index) at that day's close; end = last snapshot value. XIRR via
  longterm._xirr. Dividends/charges out on both sides; stocks with no price history left out and listed. 20 Nov 2026
  (206 days from 28 Apr): you +23k / 2.9%/yr vs Nifty +77k / 9.6%/yr (test run, no network: NSE/STLTECH/NIFTYBEES left out).
- BUILT 20 Nov 2026: weekly-check backtest. longterm.portfolio_backtest(mode, refresh, weekly) - weekly=True: act only
  after the close on each ISO week's last trading day (close-based exits flagged in the week sold then; stop raised only
  then, but stop GTT works daily; the week's signals bought at next open if within max_ext of the signal close).
  Research switches weekly='buys' / 'stops'. data['halves'] = CAGR to / after 2022-07-01. GET /api/backtest?weekly=1;
  Time machine shows a daily-vs-weekly card (modes2.weeklyCompare). Daily path verified identical to the old code.
  Results (limits 6.15L/7.5k/75k, Feb 2018-Nov 2026, pre-tax CAGR, to Jun22 / after, worst fall):
  Investing daily 9.7% (7.8/11.8) -27.2%; weekly 15.6% (20.2/11.2) -21.4%; buys-only weekly 16.6% (22.2/11.4); stops-only 11.1% -37.1%.
  Trading daily 7.1% (3.9/10.5) -23.6%; weekly 9.4% (6.2/12.7) -18.6%.
  => weekly does NOT cost profit (Trading better in both halves; Investing gain is all in the first half = likely luck,
  second half -0.6%/yr). Owner's routine can be weekly + daily GTT stops. Rules NOT changed.
- BUILT 20 Nov 2026: tax-harvest. ledger._harvest(tax, holdings, today) -> report tax['harvest'] (current FY): room =
  Rs 1.25 lakh - long-term gains booked after set-off; long lots (or turning long by 31 Mar) with gains, biggest gain per
  share first, partial lots; saved = used x LTCG rate x 1.04; charges both sides + DP. Undated lots (before the tradebook)
  listed as 'maybe'. Tax tab card + Today item in Feb (watch) / Mar (act) when >= Rs 5,000 can be booked. Sell, buy back
  NEXT trading day (same day = intraday). Note: records start 28 Apr 2026, so dated lots turn long-term from Apr 2027.
- All items from the 20 Nov plan are built. Ideas left: alerts on daily close for held positions; real results calendar.
  March tax-harvest reminder.
