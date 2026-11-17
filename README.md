# Tradeskill Portal

A local web portal that scores NSE (India) stocks 0-100 as rule-based purchase setups.
It runs on your own PC, uses free data, and needs only Python 3.9+ (no packages to install).

> Rule-based screening on free, possibly delayed data. Not investment advice.
> The broker is a paper (simulated) account. No real orders are ever sent.

## Run it

Windows: double-click `start.bat`.

Any OS:

```bash
python server.py
```

Then open http://127.0.0.1:8765

## Three modes

The portal asks which one you want each time it opens; switch any time at the top right.

| Mode | Holding | How it picks stocks |
|---|---|---|
| Scalping | Same day | 15-minute opening-range breakout, 2R target, sold by 15:15 |
| Trading | Up to 2–3 months | Base breakouts and pullbacks in uptrends, beating the Nifty over 3 months |
| Investing | 6–12 months | Leaders above a rising 200-day average with growing earnings |

Trading and Investing use daily prices (about 10 years), size each buy by risk per trade and a
per-stock cap, trail the stop after +1R, and include a portfolio backtest on all 250 stocks.
Each mode has its own limits and its own paper account.

## Screens

| Screen | What it does |
|---|---|
| Predictor | One 0-100 score per stock with a pass/fail line from every check |
| Scanner | Nifty LargeMidcap 250 ranked by daily chart setups |
| ORB scanner | 15-minute opening-range breakouts across the same 250 stocks |
| Entry / Exit / Time machine / Budget / Risk | One page per step of the trade plan |
| News | Watchlist headlines with the move from yesterday's close |
| Earnings | Latest reported quarters |
| Big deals | NSE bulk and block deals |
| Alerts | Price, percent-move and market-clock alerts that ring once |
| Paper broker | Simulated account with stop, target and 15:15 square-off |
| Limits | Your capital, max loss, daily loss, trade count and entry window |

## Data sources

Prices are tried in this order; the portal shows an alert when it switches:

1. Yahoo Finance (delayed quotes, daily and 5-minute bars)
2. NSE end-of-day file (daily bars only)
3. BSE end-of-day file (daily bars only)

Headlines come from Google News / Bing News RSS. Bulk and block deals and the index
constituent lists come from NSE's public files.

## Files

- `server.py` - the server and all scoring logic
- `static/` - the web pages (`index.html`, `app.css`, `app.js`)
- `nifty250.json`, `nifty50.json` - stock lists; edit these when the indices change
- `data/` - created at runtime (your limits, alerts, paper trades, cached files); not in git
