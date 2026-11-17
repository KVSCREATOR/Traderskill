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

First backtest results (Nov 2017 – Nov 2026, ₹2 lakh, owner's limits, after costs):
- Trading: +58% total, ~5.3%/yr, worst fall −27%, 800 trades, 36% won, profit factor 1.17.
- Investing: +111% total, ~8.9%/yr, worst fall −28%, 302 trades, 38% won, profit factor 1.70.
Trading rules are weak; improving them (without over-fitting) is the obvious next step.

Ideas not done: alerts on daily close for held positions; real results-date calendar
(currently estimated from the last reported quarter).
