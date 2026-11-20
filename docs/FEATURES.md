# Tradeskill Portal · Features

A private web portal for the Indian stock market (NSE), running 24×7 on a Synology NAS. It screens stocks with
tested rules, manages a paper (simulated) trading robot, reads your real Zerodha holdings (read-only), and talks
to you through Telegram.

> **Safety first.** The portal never places a real order. Zerodha access is read-only. Every result is a rule
> result on free, possibly delayed data, not personal investment advice.

Contents

1. [Three modes](#1-three-modes)
2. [Stock screens](#2-stock-screens)
3. [My scanner](#3-my-scanner)
4. [My holdings (real Zerodha account)](#4-my-holdings-real-zerodha-account)
5. [Research: Time machine and Forward test](#5-research-time-machine-and-forward-test)
6. [Paper trading and GTT orders](#6-paper-trading-and-gtt-orders)
7. [AI Robot (paper, self-running)](#7-ai-robot-paper-self-running)
8. [Telegram: alerts, reports and the chat bot](#8-telegram-alerts-reports-and-the-chat-bot)
9. [Your own notifications](#9-your-own-notifications)
10. [Limits, security and the portal itself](#10-limits-security-and-the-portal-itself)
11. [Data sources](#11-data-sources)
12. [Research results behind the rules](#12-research-results-behind-the-rules)
13. [Files](#13-files)

---

## 1. Three modes

Chosen when the portal opens and switchable at the top right. Each mode has its own rules, limits and paper account.

| Mode | Holding time | Rules |
|---|---|---|
| **Scalping** | Same day | 15-minute opening-range breakout (ORB), 2R target, closed by 15:15 |
| **Trading** (rules v2) | Up to 2–3 months | Base breakout (40-day high, base ≤25% deep, volume ≥1.5×) or pullback to the 20/50-day average in an uptrend; stronger than Nifty over 3 months; within 10% of the 52-week high; stop 2 ATR (4–12% of price); stop to break-even after +2R, then trails 3 ATR; time exit 60 trading days |
| **Investing** | 6–12 months | Above a rising 200-day average; 52-week-high breakout or pullback to the 50-day; stronger than Nifty over 6 months; stop 3 ATR (8–20%); trails 5 ATR; exits on a close well below the 200-day |

Common to Trading and Investing:

- **Market filter.** New buys only when the Nifty is above its 50- and 200-day averages (Trading) or its 200-day average (Investing).
- **Sizing.** Quantity = risk per trade ÷ risk per share, capped by the per-stock limit.
- **Limits.** Maximum positions, at most 2 per sector, and a total open-risk cap. New buys pause after a drawdown.
- **Costs.** Delivery charges (≈0.12% per side) plus the DP fee are included everywhere.

## 2. Stock screens

| Screen | What it shows |
|---|---|
| **Predictor** | One stock, every check, one 0–100 score and a verdict. It includes a daily chart (volume, averages, breakout line, signal marker, range buttons 1D…Max), the rule plan (entry, stop, quantity) and a GTT button. |
| **Scanner** | Nifty LargeMidcap 250, ranked by rule setups for the chosen mode, with ☆ to add a stock to a list. |
| **ORB scanner / Strength** | Scalping: live 15-minute opening-range breakouts. It shows the range in ATR, the charges in R and a "stop too tight for charges" warning. |
| **Entry / Exit / Budget / Risk** | One page per step of the trade plan: where to buy, where to sell, how much fits your money, and what can go wrong. |
| **News** | Headlines for your lists and holdings (Google / Bing RSS), each marked 🟢 positive, 🔴 negative or ⚪ neutral. |
| **Earnings** | Latest reported quarters (revenue and profit growth). |
| **Big deals** | NSE bulk and block deals. |
| **Alerts** | Price, percent-move and market-clock alerts that ring once (also on Telegram). |
| **History** | Orders, alerts and every Telegram message sent (deletable). |

## 3. My scanner

- **Lists.** Up to 20 named lists of up to 50 symbols each, used in all modes. News and Telegram follow these lists.
- **Source.** A list, your Zerodha holdings, or both.
- **Status.** Exit signal / Buy zone / Near trigger (≤3%) / Holding / Watching.
- **Columns.** Distance to the trigger, strength percentile against the 250, a 6-month hover chart, ⚠ when results are due within 7 days, and ⚠ when the sector is full.
- **Plan dialog.** Entry, ATR stop, quantity and risk checks lead to a paper GTT with a confirm box.

## 4. My holdings (real Zerodha account)

This connects to Zerodha's free hosted **Kite MCP** with **read-only** access: holdings, positions, profile and margins only. Orders, GTTs and alerts are refused in code. Zerodha's login ends every morning, so you tap the one-tap login link from Telegram or the portal. A **4-digit PIN** is asked every time the page opens.

| Tab | What it does |
|---|---|
| **Today** | Checklist in four groups (act / watch / for tomorrow / info). It covers exits, weak trends, your limits, rebalance due, lots turning long-term, results due, paper positions near their stop, buy signals with room, and list stocks near a breakout. Items can be ticked. |
| **Stops · Kite GTT** | The exact stop GTT to set in Kite for each holding: the trigger (Investing trailing stop, only ever raised), a limit 2% below, and the quantity. It flags new, raise, quantity change and hit. |
| **Live holdings** | Value, today, total P/L, a P&L treemap and the rule verdict per stock. |
| **Year record** | Every buy and sell (Console tradebook import, daily snapshots, manual trades), with FIFO lots and intraday detection. |
| **Tax** | STCG 20% / LTCG 12.5% above ₹1.25 lakh, set-off, cess, and the extra tax if sold today. **Tax harvest** lists which long-term gains to book before 31 March, then buy back the next day. |
| **Sectors** | Share per sector against your limit. |
| **What next** | A 6–12 month plan by the Investing rules and your limits: sells (exit, trims, sector or count limits, weak swaps), then a Nifty core fund buy, then stock buys ("next in line" when no place is free). |
| **You vs Nifty** | Your real return against the same money moved in and out of the Nifty 50 (XIRR). |
| **Core + satellite** | Target share in Nifty 50 / Sensex index funds (default 50%), the actual split, and the amount to move. Rebalance is due in April or when more than 10 points off. |
| **Funds** | Cash and margins. |
| **Import & add** | Console tradebook CSV import and manual trades (bonus = price 0). |

## 5. Research: Time machine and Forward test

- **Time machine.** A portfolio backtest of the Trading and Investing rules on all 250 stocks over about 9 years, after costs. It reports win rate, average win and loss, expectancy, worst fall, yearly returns and the equity curve.
  - **Benchmarks:** the Nifty with dividends and after tax, a monthly SIP, and core + satellite mixes.
  - **Daily vs weekly:** a comparison of checking the rules every day or once a week.
- **Forward test.** Every completed-day signal is logged once and then simulated from the next open, so the rules are judged on days the backtest never saw. You need about 30 closed trades before judging.

## 6. Paper trading and GTT orders

- **Paper broker.** One simulated account per mode, with stop, target and the 15:15 square-off for scalps. Positions are held across days.
- **Paper GTT.** "Buy when the price reaches X", set any time.
  - **Trading / Investing:** fills on daily bars from the next session, at the trigger or the gapped open. Valid 1 year.
  - **Scalping:** 5-minute bars, one session only.

## 7. AI Robot (paper, self-running)

The robot runs whenever the portal runs, resumes after a NAS restart, and never sends a real order. It starts with paper money (default ₹1,50,000) and has a goal of 2×.

### Strategies

Every strategy was tested on 2017–2026 data, split into two halves, after **all** charges. Only strategies that made money in both halves trade with money.

| Strategy | Kind | Backtest R per trade (2017–22 / 2022–26) |
|---|---|---|
| 📈 Short swing (Trading v2 rules) | Swing | +0.14 / +0.40 |
| 🪂 Dip buy in an uptrend (3 down days or RSI-2 < 10) | Swing | +0.27 / +0.43 |
| 🕯️ Bullish engulfing / hammer at the 20/50-day average | Swing | +0.28 / +0.25 |
| 🏔️ 52-week-high breakout on 1.5× volume | Swing | +0.13 / +0.45 |
| 🌅 Morning breakout scalp (ORB) | Scalp | lost after charges: off |
| 🧪 Afternoon momentum scalp | Scalp | −0.14 / −0.10: off |

All swings share the same exits: stop 2 ATR, break-even after +2R, then a 3 ATR trailing stop, and a 60-day time limit.

### How it trades

- **All session.** Every strategy is checked about every 3 minutes from 09:15 to 15:28.
  - A completed-day signal is bought while the price is within 3% of the signal close.
  - A signal forming today counts from 15:10 (close to how it was tested).
  - Stops are watched all day.
- **Sizing.**
  - Base risk is 1.5% of its money per trade, times a factor the strategy **earns from its last 20 trades** after charges (0.25× to 1.5×).
  - It trades smaller below its peak or when India VIX is above 22.
  - Your risk cap applies (default 2%).
  - Up to 10 swings at no more than 20% of the money each.
- **Safety.**
  - No new buys after −3% on the day, and a 1-week pause after −15% from the peak.
  - Scalps are never held overnight.
- **Auto on/off.** A strategy that is off keeps trading as a **shadow**: same signals, no money, full charges. After each close:
  - **On:** an off strategy is switched on after 20 shadow trades averaging at least +0.10R.
  - **Off:** a live strategy is switched off if its trades since it was switched on (at least 15) average below −0.10R.
- **Learning model.** A small logistic regression learns from every candidate. It may skip weak trades only after it beats chance on days it never trained on.
- **Real charges.** Zerodha intraday and delivery formulas (brokerage, STT, exchange, SEBI, stamp duty, GST, DP) plus 0.03% slippage each side. The tax estimate is shown too.

### Robot page

- **Top:** wealth, since start, goal progress, below-peak figure, free cash and the money line.
- **Strategy cards:** the switch, size, trades, won, net, charges, verdict and shadow results.
- **Positions:** open positions (capital used, P/L, stop) and closed trades (charges, net, R).
- **Diary:** every buy, sell, stop move and daily note, tagged by strategy, plus a **scorecard** after each close (best performer, "Good for you" / "Costing you money"). The diary is **kept 5 years** and can be deleted by hand: one entry, a day, a date range, a strategy, or text search.

## 8. Telegram: alerts, reports and the chat bot

Two bots: an **alert bot** that only sends, and a **chat bot** (e.g. `@das925chat`) that answers.

### Messages (each can be switched off or deleted)

| When | Message |
|---|---|
| 07:00 | Overnight global market news in Hindi |
| 08:45 | Morning plan: cues + news reading, with its track record |
| 09:32 | Day plan: indices, market filter, holdings by the rules, top setups |
| 10:00 | Exit signals on your holdings (only when there is one) |
| 12:00 | What next: the sell/buy plan |
| 13:00 | Rule buy signals you have room for |
| 15:32 | Market close: indices, breadth, gainers and losers, world |
| 15:35 | Holdings today: value, best and worst, rule actions, limits, Today list, Kite stop GTTs |
| Live | Price alerts, trend changes, −10% holdings, loss + bad news, rule-stop breaks, big market moves, Zerodha buys and sells, paper and GTT events |
| Live | **Robot live:** every real robot buy and sell, and each strategy auto on/off |
| After close | **Robot trading alert:** wealth, today, bought, closed, open (time editable, default 15:32) |
| Sunday | Weekly summary |

- **Quiet rule.** Alerts about a stock are sent once, then stay quiet until you tap **🔔 Allow again**.
- **Format.** Every message has a bold title and **fixed-width tables** that fit a phone. If Telegram refuses the formatting, the message is sent as plain text.

### Chat bot

- **Menu.** A permanent bottom menu (Today, Holdings, Stops, Plan, Market, News, Alerts, Scanner, More, **🤖 Robot**). Inline buttons update the same message.
- **Typed commands.** `HAL`, `news HAL`, `alert HAL below 4500`, `add HAL to My list`, `remove HAL`, `paper buy HAL`, `limit max_per_stock 80000`, `core 40`, `robot`, `robot risk 1.5`, `robot alert 15:45`, plus `/help`.
- **Plain questions.** English, Hindi or Hinglish ("aaj kya karna hai"). An AI service, if set, routes questions it can't match.
- **Robot screens.** Overview, live positions, sold trades (paged), strategies + shadow, today, diary, charges and tax, risk and alert settings.
- **Changes.** Anything that changes data asks **✅ Confirm**. From Telegram, the robot's risk cap and report time are the only robot settings you can change.
- **People.** The owner has full access. Others can be added by chat ID as full or **view-only**, and strangers are ignored.
- **Hindi.** Words are translated; tables stay in English. If the AI takes more than **7 seconds**, the answer is sent in English.

## 9. Your own notifications

Build your own alerts from **32 tested building blocks**, without writing code:

- **Holding checks:** profit or loss in % or ₹, day move, near stop, long-term soon, results soon, weight, deals.
- **Portfolio checks:** day P&L, drawdown, per-stock cap, sector limit.
- **Price and indicator checks:** above/below, day %, 50/200-day crosses, 52-week high/low, volume, RSI, gap.
- **Market checks:** Nifty move or level, VIX.
- **Other:** Investing verdict changes, news keywords and scheduled summaries.

Each one has a scope (holdings, some holdings, a stock, a list, all) and a timing (market hours, at the close, or at a set time on chosen days). You also choose how often it may repeat.

## 10. Limits, security and the portal itself

- **Limits page.**
  - Per-mode capital, risk per trade, per-stock cap, positions, per sector, open risk and drawdown pause.
  - Telegram setup, the bot switches and the AI service (Gemini, OpenAI, Claude or any OpenAI-compatible service, with an optional backup).
  - Holdings PIN, and a Restart button.
- **Security.**
  - The portal password is required, and access is HTTPS only through the NAS reverse proxy.
  - Keys and tokens live only on the NAS (`data/`, owner-only files) and are never in git.
  - Wrong passwords lock the portal for 15 minutes.
- **Self-updating.** The server checks its Python files every 5 seconds and restarts itself only if they all compile. If one doesn't, it keeps running the last good version and shows the error.

## 11. Data sources

| Data | Source (in order) |
|---|---|
| Prices | Yahoo Finance (delayed): daily ~10 years, 5-minute 60 days → NSE end-of-day file → BSE end-of-day file (a pop-up says when it switches) |
| News | Google News / Bing News RSS |
| Deals, index lists, holidays | NSE public files |
| Your account | Zerodha Kite MCP (read-only) |

## 12. Research results behind the rules

- **Trading rules, 2017–2026 backtest:** about 11.4% a year, worst fall −25%.
- **Investing rules:** about 10.7% a year, worst fall −34%.
- **Nifty bought and held:** about 12.2% a year with dividends, worst fall −38%.
- **Core + satellite (50% Nifty + 50% Trading rules):** about the Nifty's return with a worst fall about 40% smaller. This is the design the holdings tools follow.
- **Scalping (opening-range breakout):** no edge after charges in two 60-day studies.
- **Robot strategy study (20 Nov 2026):** combining strategies gives a typical 4–7% a year with 30–40% worst falls on ₹1.5 lakh (shuffled order tests). No tested rule set doubles money quickly.

Past results flatter the rules slightly, because they use today's index members (survivorship bias).

## 13. Files

| File | Purpose |
|---|---|
| `server.py` | HTTP server, data fetch, Scalping engine, alerts, paper broker, API |
| `longterm.py` | Trading and Investing engines, backtests, scanner, paper accounts |
| `robot.py`, `static/robot.js` | AI Robot engine and page (data in `data/robot.json`, diary in `data/robot_diary.jsonl`) |
| `kite.py`, `ledger.py`, `static/holdings.js` | Zerodha link and My holdings (data in `data/ledger.json`) |
| `mylist.py`, `static/myscan.js` | My scanner |
| `gtt.py` | Paper GTT orders |
| `telegram.py`, `bot.py`, `reports.py`, `daily.py`, `custom.py`, `tgfmt.py` | Telegram alerts, chat bot, reports, own notifications, message tables |
| `ai.py` | Optional AI service connector |
| `history.py` | Action log |
| `static/` | Web pages (`index.html`, `app.css`, `app.js`, `modes.js`, `modes2.js`, …) |
| `nifty250.json`, `nifty50.json` | Stock lists |
| `Dockerfile`, `docker-compose.yml`, `NAS.md` | Running on the Synology NAS |
| `data/` | Created at runtime: settings, accounts, caches, tokens. **Never in git.** |
