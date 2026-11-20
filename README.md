# Tradeskill Portal

A private web portal for the Indian stock market (NSE). It screens stocks with tested rules, reads your
Zerodha holdings (read-only), runs a self-learning **paper** trading robot, and keeps you informed through a
Telegram bot. It runs 24×7 on a Synology NAS and needs only Python 3.9+ (no packages to install).

> Rule-based screening on free, possibly delayed data. Not investment advice.
> No real orders are ever sent: the broker and the robot are paper (simulated), and Zerodha access is read-only.

## Documentation

| Document | For |
|---|---|
| [docs/FEATURES.md](docs/FEATURES.md) | Every feature in detail: modes, screens, My holdings, robot, Telegram, research results |
| [docs/MANUAL.md](docs/MANUAL.md) | How to use it: daily routine, Zerodha login, robot, Telegram commands, troubleshooting, glossary |
| [NAS.md](NAS.md) | Installing and updating on the Synology NAS (Container Manager, HTTPS, Tailscale) |
| [CLAUDE.md](CLAUDE.md) | Developer notes: design decisions, studies and status |

## At a glance

- **Three modes:** Scalping (same day), Trading (up to 2–3 months) and Investing (6–12 months). Each has its own rules, limits and paper account.
- **Screens:** Predictor (0–100 score), Scanner (Nifty LargeMidcap 250), ORB scanner, My scanner (your lists), Entry, Exit, Budget, Risk, News, Earnings, Big deals, Alerts, Paper broker, History.
- **My holdings (Zerodha, read-only, PIN):**
  - Today checklist, Kite stop GTTs, live holdings, year record.
  - Tax with tax harvesting, sectors, the What next plan, You vs Nifty, Core + satellite, funds, and tradebook import.
- **Research:** Time machine (9-year portfolio backtest after costs, against the Nifty, a SIP and core + satellite mixes) and the Forward test journal.
- **AI Robot (paper):**
  - 4 tested swing strategies, checked all session.
  - It earns its size from its own results after charges, switches strategies on and off itself (off ones keep trading as a shadow), and has safety stops.
  - Its diary and strategy scorecard are kept 5 years.
- **Telegram:**
  - Scheduled reports, live alerts and instant robot trades.
  - A chat bot with a full menu (including 🤖 Robot), typed commands and Hindi/English answers.
  - Every message has neat phone-width tables.
- **Your own notifications:** 32 building blocks, with no code to write.

## Run it

On the NAS: see [NAS.md](NAS.md). Code changes in the NAS folder go live by themselves: pages on refresh, and Python after an automatic, compile-checked restart.

On a PC (Windows: double-click `start.bat`):

```bash
python server.py
```

Then open http://127.0.0.1:8765

## Data sources

| Data | Source |
|---|---|
| Prices | Yahoo Finance (delayed) → NSE end-of-day file → BSE end-of-day file (a pop-up says when it switches) |
| News | Google News / Bing News RSS |
| Deals, index lists, holidays | NSE public files |
| Your account | Zerodha Kite MCP (free, read-only) |

`data/` is created at runtime (settings, accounts, caches, tokens) and is never uploaded to git.
