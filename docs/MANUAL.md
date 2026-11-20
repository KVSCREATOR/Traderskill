# Tradeskill Portal · User manual

How to use the portal, the AI Robot and the Telegram bot day to day. For what every part does, see
[FEATURES.md](FEATURES.md). For installing on the NAS, see [NAS.md](../NAS.md).

> The portal never places a real order. Everything it shows is a rule result, not personal investment advice.

Contents

1. [Opening the portal](#1-opening-the-portal)
2. [Your daily routine (about 15 minutes)](#2-your-daily-routine-about-15-minutes)
3. [Connecting Zerodha](#3-connecting-zerodha)
4. [Looking at a stock](#4-looking-at-a-stock)
5. [Lists and My scanner](#5-lists-and-my-scanner)
6. [My holdings, step by step](#6-my-holdings-step-by-step)
7. [Paper trading and GTTs](#7-paper-trading-and-gtts)
8. [The AI Robot](#8-the-ai-robot)
9. [Telegram](#9-telegram)
10. [Your own notifications](#10-your-own-notifications)
11. [Settings and limits](#11-settings-and-limits)
12. [Troubleshooting](#12-troubleshooting)
13. [Glossary](#13-glossary)

---

## 1. Opening the portal

1. Open **https://\<NAS address\>:8766** in a browser. From outside home, use the NAS Tailscale address (`https://100.x.y.z:8766`) with the Tailscale app signed in.
2. Sign in with the portal password (set in `tradeskill.env` on the NAS). After 5 wrong tries it locks for 15 minutes.
3. Pick a mode when asked: **Scalping**, **Trading** or **Investing**. You can switch any time at the top right.
4. The start page is **My holdings → Today**. **◐** at the top right switches between dark and light.

The portal runs 24×7 on the NAS: the robot, alerts and reports keep working with your PC switched off.

## 2. Your daily routine (about 15 minutes)

| Time | What to do | Where |
|---|---|---|
| Morning (before 09:15) | Read the 08:45 morning plan. Tap the Zerodha login link (the login ends every morning). | Telegram |
| 09:32 | Read the day plan: market filter, holdings by the rules, top setups. | Telegram |
| Any time | Open **📋 Today** and work through the 🔴 act items, then the 🟡 watch items. Tick them when done. | Bot or portal |
| After a sell/buy decision | Set or raise the Kite stop GTTs shown in **🛡 Stops**, then tap ✓ when done. | Bot or portal → Kite |
| 15:35 | Read the holdings report: what the rules say for tomorrow. | Telegram |
| Evening | Glance at the **🤖 Robot** report: wealth, today, trades. | Telegram |

**Weekly is enough.** The backtest showed that checking the rules once a week (with daily GTT stops in Kite) did not cost profit.

## 3. Connecting Zerodha

1. Tap the one-tap login link (from the morning Telegram message, **⚙️ Settings → 🔑 Zerodha login link** in the bot, or **My holdings** in the portal).
2. Sign in on Zerodha's own page. The portal gets **read-only** access to holdings, positions, profile and margins. It cannot place, change or cancel orders.
3. The login ends every morning. Repeat this once a day when you want live holdings.
4. My holdings asks for your **4-digit PIN** every time it opens. You can change the PIN under **Limits**. After 3 wrong tries it locks, and only the portal password can reset it.

## 4. Looking at a stock

- **Portal:** type the symbol (e.g. `RELIANCE`) in the box at the top, then **Predict**.
- **Telegram:** just send the symbol, e.g. `HAL`.

You get:

- **Score and verdict:** a 0–100 score and a verdict for the current mode.
- **Rule plan:** entry, stop and quantity sized by your limits.
- **Your holding**, if you hold it: quantity, average price, P/L and the holding stop.
- **Chart:** a daily chart with volume, averages, the breakout line and the signal day. Use the range buttons 1D…Max.
- **Next steps:** buttons for **News**, **Alert…**, **➕ My list** and **Paper buy / GTT**.

## 5. Lists and My scanner

- Open **★ My scanner** at the top. Create up to 20 lists, then add symbols there, with ☆ on any Scanner row, or from Telegram: `add HAL to My list` and `remove HAL`.
- Choose the source: a list, your Zerodha holdings, or both.
- Read the **status** column:
  - **Exit signal:** the rules say sell.
  - **Buy zone:** a fresh signal.
  - **Near trigger:** within 3% of a breakout.
  - **Holding** or **Watching:** nothing to do yet.
- **Plan** opens the entry, stop and quantity, plus the risk checks. From there, **Paper GTT** saves a simulated buy order.

## 6. My holdings, step by step

1. **Today:** your checklist. Do the 🔴 items first.
2. **Stops · Kite GTT:** for each holding, open Kite → GTT and set a **sell** GTT with the trigger, limit and quantity shown. The trigger is only ever raised. When the page says **RAISE**, edit that GTT in Kite, then tick ✓ here.
3. **What next:** the plan for the next 6–12 months:
   - **Sells:** exits, trims over your per-stock cap, sector or count limits, weak swaps.
   - **Nifty core first:** the amount to put into the Nifty index fund until the core target is reached.
   - **Buys:** stocks with room, plus "next in line" when no place is free.
4. **Tax:** the estimated tax this financial year. From February, **Tax harvest** lists long-term gains to book tax-free (up to ₹1.25 lakh). Sell, then buy back the **next** trading day, never the same day.
5. **You vs Nifty:** whether your own picks beat the Nifty. Judge it only after 12 months of records.
6. **Core + satellite:** set the share you want in Nifty 50 / Sensex index funds (default 50%). Rebalance in April or when the split is more than 10 points off.
7. **Import & add:** import Zerodha Console's tradebook CSV so lots, dates and tax are exact. Add bonus shares as a trade at price 0.

## 7. Paper trading and GTTs

- **Paper broker:** a simulated account per mode. Buy from the Predictor, My scanner or Telegram (`paper buy HAL`). Close from the broker page or the bot's **🧾 Paper** screen.
- **Paper GTT:** a "buy when the price reaches X" order, set even when the market is closed.
  - **Trading / Investing:** fills from the next session at the trigger or the gapped open, using the rule stop. Valid 1 year.
  - **Scalping:** the same session only, with your stop and target.
- **Real GTT:** to place the same order in your real account, open Kite → GTT yourself. The portal shows the link.

## 8. The AI Robot

Open **🤖 AI Robot** in the menu (or **🤖 Robot** in Telegram). It trades **paper money only**, by itself.

### What you see

- **Top tiles:** Money now, Since start, Goal (2×), Below the peak, Free cash, and progress to doubling. The money line appears after two trading days.
- **How the robot decides:** one card per strategy. Each card shows the switch, size factor, trades, won, net and charges, its verdict (🏆 best so far / Good for you / Costing you money), and its **shadow** results while it's off.
- **Open positions:** quantity, entry, capital used, now, stop, target and P/L.
- **Closed trades:** buy, sell, charges, net and R.
- **Charges and tax:** what the robot paid, and the tax it would owe on real money.
- **Robot diary:** see below.
- **Your controls:** the portal password, start money for a reset, and the alert time. Two buttons need the password: **Close all positions** and **Reset**.

### What you can change

| Setting | Where | Notes |
|---|---|---|
| Robot on / off | Switch at the top right | Off keeps positions but stops managing them |
| A strategy on / off | Switch on its card | The robot reviews it after the next close and may switch it back by results |
| Most it may risk per trade | Drop-down under the cards, or Telegram `robot risk 1.5` | 0.25%–3%. The robot often uses less by itself |
| Daily report time | Your controls, or Telegram `robot alert 15:45` | Trading days only |
| Close all / Reset | Your controls | Needs the portal password |

You don't need to manage the strategies. Off strategies keep trading as a **shadow** (no money). One that earns at least +0.10R per trade over 20 shadow trades is switched **on**. A live one that loses more than −0.10R per trade is switched **off**. Each switch is written in the diary and sent to Telegram.

### The diary

- **What it records:** every buy, sell, stop raise, the daily notes per strategy, and the after-close **📊 Strategy scorecard** (best performer, what suits your goal).
- **Filters:** strategy, entry type, From/To dates, and a text search (e.g. `RELIANCE`).
- **Deleting:** **✕** deletes one entry. **Delete shown** deletes everything that matches the filter; with no filter, that's the whole diary. Both ask you to confirm, and the delete is permanent.
- **Keeping:** entries are kept for 5 years, then removed automatically.

### Reading the numbers

- **R:** the result in units of the risk taken. +1R means it made what it had risked; −1R means the stop was hit.
- **Net:** the result after every charge and slippage.
- **Size factor:** how much of the normal size a strategy has earned from its last 20 trades. "Learning" means it has fewer than 15 trades.

## 9. Telegram

### Set up (once)

1. **Limits → Telegram:** connect the **alert bot** (press Start in the bot, then **Connect**).
2. **Limits → Telegram → Chat with the bot:** set the **chat bot** token (portal password), then switch **Answer my messages** on.
3. Optional: choose the language (Hindi/English) and add other people by chat ID as **full** or **view-only**.

### Using the chat bot

Tap the bottom menu:

```
📋 Today    💼 Holdings   🛡 Stops
🧭 Plan     📈 Market     📰 News
🔔 Alerts   📊 Scanner    ☰ More
            🤖 Robot
```

Or type:

| Type | Does |
|---|---|
| `HAL` | Stock card |
| `news HAL` / `📰 News` | Headlines for one stock or all holdings |
| `alert HAL below 4500` | Price alert (rings once) |
| `add HAL to My list` / `remove HAL` | Edit your lists |
| `paper buy HAL` | Simulated buy (asks to confirm) |
| `limit max_per_stock 80000` | Change a limit (asks to confirm) |
| `core 40` | Core + satellite target (asks to confirm) |
| `robot` | Robot overview |
| `robot risk 1.5` / `robot alert 15:45` | Robot risk cap / report time (asks to confirm) |
| `/help` | Everything the bot can do |
| `aaj kya karna hai`, `how are my holdings?` | Plain questions in English, Hindi or Hinglish |

- **Robot screens:**
  - **📂 Live:** open positions.
  - **✅ Sold:** sold trades with dates, net and reason. Use ◀ ▶ for older pages.
  - **📊 Strategies:** results and shadow results.
  - **📅 Today**, **📔 Diary**, **💸 Charges**, and **⚙️ Risk & alert**.
- **Confirming:** anything that changes data shows **✅ Confirm / ✖ Cancel**. The button works for 10 minutes.
- **Hindi:** the words are translated and the tables stay in English. If the AI takes more than 7 seconds, you get the English answer with a small note.
- **Muted alerts:** each alert about a stock comes once. To hear it again, tap **🔔 Allow again**, or open **🔔 Alerts → 🔕 Muted**.
- **Switching messages:** turn any built-in message on or off in **🔔 Alerts → 📨 Built-in messages** or under **Limits → Telegram**. "Robot live" (instant robot buys and sells) can be muted separately from the daily robot report.

## 10. Your own notifications

**Limits → Telegram → Your own notifications → + New notification**:

1. Pick a **check**, e.g. "holding down more than X%", "price crosses the 200-day average", "Nifty moves more than X%" or "news mentions a keyword".
2. Pick the **scope**: all holdings, some holdings (tick them), one stock, a list, or everything.
3. Pick **when**: during market hours (every 5 minutes), at the close, or at a time on chosen days.
4. Pick **repeat**: once a day per stock, once then off, or every N minutes.
5. **Test** sends it right away. **Save** turns it on.

Switch them on/off or delete them later on the same page, or from the bot (**🔔 Alerts → 🔔 Own notifications**).

## 11. Settings and limits

**⚙ Limits**:

- **Per mode:**
  - Capital, risk per trade, max per stock, max positions, max per sector, max open risk.
  - Pause after a drawdown of X%.
- **Telegram:** bots, messages, your own notifications, the chat bot, people, language, and the AI service. AI is optional: without it the bot uses keywords and English.
- **Holdings PIN:** change it.
- **Portal program:** shows the running version and any code error, plus a **Restart portal** button.

## 12. Troubleshooting

| Problem | What to do |
|---|---|
| Page says "Bad response from server" | The portal is restarting after an update (a few seconds). Refresh. The first scan after a restart can take 30–60 seconds. |
| My holdings is empty / "Zerodha not connected" | The daily Zerodha login ended. Tap the login link again. |
| "Sign in first" | The browser session ended. Sign in with the portal password. |
| No Telegram messages | Check **Limits → Telegram**: bot connected, the message switched on, not deleted, not muted. **History → Messages** shows "not sent" with the reason. |
| Bot answers in English though Hindi is on | The AI was slower than 7 seconds or is not set. That's normal, and the numbers are the same. |
| Bot doesn't answer | **Limits → Telegram → Chat with the bot**: is "Answer my messages" on? Is your chat in the people list? |
| A stock has no data | Yahoo has no data. The portal switches to the NSE, then the BSE, end-of-day file and shows a pop-up. |
| Robot did not buy | Read **📔 Diary → Daily notes**. Common reasons: the market filter is off, not enough cash, the price ran past the signal, negative news, or the day stop or pause. |
| Robot strategy switched off by itself | It lost more than −0.10R per trade after charges. It keeps trading as a shadow and comes back on when the shadow earns. |

## 13. Glossary

| Word | Meaning |
|---|---|
| **ATR** | Average true range: a stock's normal daily movement. Stops are set as a multiple of it. |
| **R** | Risk unit: entry minus stop. A trade's result in R makes trades of different sizes comparable. |
| **Market filter** | Nifty above its 50/200-day averages. When off, the rules hold off new buys. |
| **ORB** | Opening-range breakout: price leaving the first 15 minutes' range. |
| **GTT** | Good-till-triggered order in Kite: a stop that waits on Zerodha's side. |
| **Shadow** | A robot strategy that is off but still records the trades it would have taken, without money. |
| **Core + satellite** | Part of the money in a Nifty index fund (core), the rest in stocks picked by the rules (satellite). |
| **STCG / LTCG** | Short-term (under 12 months, 20%) and long-term (12.5% above ₹1.25 lakh a year) capital-gains tax. |
| **XIRR** | Yearly return that accounts for when money went in and out. |
