"""Scheduled Telegram reports (trading days only) and the notification history log.

08:45 morning outlook (global cues -> likely opening tone, with its own hit rate)
09:32 day plan (opening, market filter, holdings by the rules, best rule setups)
15:32 market close summary (indices, Nifty 50 breadth, gainers/losers, sectors, world)
15:35 holdings summary (today's gains and losses, rule actions, rule breaches, buy signals)

Everything here reports what the portal's tested rules and the data say. It is not personal
advice, and the outlook is a reading of overnight cues, not a forecast.
"""
import json
import os
import threading
import time
from datetime import date, timedelta

S = None   # server module
L = None   # longterm
K = None   # kite
T = None   # telegram

SCHEDULE = [("plan", 572), ("close", 932), ("eod", 935)]   # morning plan + 08:45 update now live in daily.py
D = None   # daily module   # minutes after midnight IST
NOTE = "Rule results and data, not personal advice."
_log_lock = threading.Lock()


# ----------------------------------------------------------------- history log
def _log_path():
    return os.path.join(S.DATA, "notify_log.jsonl")


def log(kind, text, status, error=None):
    rec = {"ts": S.market_clock()["ist"], "kind": kind, "text": text, "status": status, "error": error}
    with _log_lock:
        os.makedirs(S.DATA, exist_ok=True)
        with open(_log_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def history(limit=500, kind=None):
    try:
        with open(_log_path(), encoding="utf-8") as f:
            rows = [json.loads(x) for x in f if x.strip()]
    except OSError:
        rows = []
    if kind:
        rows = [r for r in rows if r["kind"] == kind]
    return {"rows": rows[::-1][:limit], "total": len(rows)}


# ----------------------------------------------------------------- trading-day checks
def holidays():
    return set((S.load_state()["settings"].get("holidays") or []))


def is_trading_day(check_traded=False):
    now = S.now_ist()
    d = now.date().isoformat()
    if now.weekday() >= 5 or d in holidays():
        return False
    if check_traded:   # after 09:15: did the Nifty actually trade today?
        try:
            bars = L.history("^NSEI", index=True)["bars"]
            return bars[-1][0] == d
        except Exception:  # noqa: BLE001
            return True
    return True


# ----------------------------------------------------------------- helpers
def rs(v, dec=0):
    return T._rs(v, dec)


def signed(v, dec=0):
    return ("+" if v >= 0 else "") + rs(v, dec) if v is not None else "–"


def pts(v):
    """Index level in points (Indian grouping, no rupee sign)."""
    return "–" if v is None else rs(v, 2).replace("₹", "")


def pct(v):
    return "–" if v is None else "%+.2f%%" % v


def arrow(v):
    return "▲" if (v or 0) >= 0 else "▼"


def _quotes():
    d = S.indices()
    by = {r["name"]: r for r in d["rows"] + d["world"]}
    return d, by


def _zerodha():
    """Holdings by the Investing rules, or None if the Zerodha login has expired."""
    try:
        h = K.holdings("invest")
        if h.get("connected") and "rows" in h:
            return h
    except Exception:  # noqa: BLE001
        pass
    return None


def _reconnect_line():
    try:
        return "🔑 Zerodha login has expired (it ends every morning). One-tap login: %s" % D.login_link()
    except Exception:  # noqa: BLE001
        url = (S.PUBLIC_URL or "http://127.0.0.1:%d" % S.PORT) + "/#/holdings"
        return "🔑 Zerodha login has expired (it ends every morning). Reconnect: %s" % url


def _setups(mode, n=5, only=None):
    try:
        d = L.scan_long(mode)
    except Exception:  # noqa: BLE001
        return [], None
    rows = [r for r in d["rows"] if r["status"] in ("confirmed", "recent") and (only is None or r["symbol"] in only)]
    return rows[:n], d.get("regime")


# ----------------------------------------------------------------- 08:45 morning outlook
CUES = [("S&P 500 FUT", 2.0), ("NASDAQ FUT", 1.0), ("NIKKEI", 0.6), ("HANG SENG", 0.5), ("KOSPI", 0.5),
        ("BRENT CRUDE $", -0.6), ("USD/INR", -1.5), ("DOLLAR INDEX", -0.5), ("US 10Y YIELD %", -0.3)]


def morning():
    d, by = _quotes()
    score, lines = 0.0, []
    for name, w in CUES:
        r = by.get(name)
        if r and r["pct"] is not None:
            score += w * r["pct"]
            lines.append("%s %s %s" % (arrow(r["pct"]), name, pct(r["pct"])))
    nifty, vix = by.get("NIFTY 50"), by.get("INDIA VIX")
    if nifty and nifty["pct"] is not None:
        score += 0.3 * nifty["pct"]
    tone = "Positive" if score > 0.3 else "Negative" if score < -0.3 else "Mixed / flat"
    icon = {"Positive": "🟢", "Negative": "🔴"}.get(tone, "🟡")
    st = S.load_state()
    calls = (st.get("telegram") or {}).get("outlook_calls") or []
    judged = [c for c in calls if c.get("right") is not None][-20:]
    hit = ("Outlook hit rate: %d of the last %d calls right." % (sum(c["right"] for c in judged), len(judged))) if judged \
        else "Outlook hit rate: building up (needs a few days)."
    _save_call(tone, score)
    msg = ["🌅 Morning outlook · %s" % S.now_ist().strftime("%a %d %b"),
           "%s Likely opening tone: %s (cue score %+.2f)" % (icon, tone, score),
           "Yesterday: NIFTY 50 %s %s · VIX %s" % (pts(nifty["price"]) if nifty else "–", pct(nifty and nifty["pct"]),
                                                   "%.2f" % vix["price"] if vix else "–"),
           "Global cues:"] + ["  " + x for x in lines]
    if vix and vix["price"] and vix["price"] > 20:
        msg.append("⚠️ India VIX above 20: expect wider swings; size positions smaller.")
    if not _zerodha():
        msg.append(_reconnect_line())
    msg += [hit, "A reading of overnight cues, not a forecast."]
    return "\n".join(msg)


def _save_call(tone, score):
    with S._state_lock:
        st = S.load_state()
        tg = st.setdefault("telegram", {})
        calls = tg.get("outlook_calls") or []
        day = S.now_ist().date().isoformat()
        calls = [c for c in calls if c["day"] != day] + [{"day": day, "tone": tone, "score": round(score, 3), "right": None}]
        tg["outlook_calls"] = calls[-60:]
        S.save_state(st)


def _judge_call(nifty_pct):
    """At 09:32: was the outlook's direction right? (Mixed counts as right within ±0.25%.)"""
    with S._state_lock:
        st = S.load_state()
        tg = st.setdefault("telegram", {})
        day = S.now_ist().date().isoformat()
        for c in tg.get("outlook_calls") or []:
            if c["day"] == day and c.get("right") is None and nifty_pct is not None:
                c["right"] = (c["tone"] == "Positive" and nifty_pct > 0) or (c["tone"] == "Negative" and nifty_pct < 0) \
                    or (c["tone"].startswith("Mixed") and abs(nifty_pct) <= 0.25)
                c["nifty_0930"] = round(nifty_pct, 2)
                S.save_state(st)
                return c
    return None


# ----------------------------------------------------------------- 09:32 day plan
def plan():
    d, by = _quotes()
    nifty = by.get("NIFTY 50")
    c = _judge_call(nifty and nifty["pct"])
    msg = ["📋 Day plan · %s 09:32" % S.now_ist().strftime("%a %d %b")]
    if nifty:
        msg.append("NIFTY 50 %s %s %s%s" % (pts(nifty["price"]), arrow(nifty["pct"]), pct(nifty["pct"]),
                                            (" · outlook was %s (%s)" % (c["tone"], "right" if c["right"] else "wrong")) if c else ""))
    for name in ("BANK NIFTY", "INDIA VIX"):
        r = by.get(name)
        if r:
            msg.append("%s %s %s" % (name, pts(r["price"]), pct(r["pct"])))
    for mode in ("swing", "invest"):
        try:
            mk = L.market()
            ok = mk.regime(mk.ind["d"][-1], mode)
            msg.append("%s market filter: %s" % (L.LABEL[mode], "buys allowed ✅" if ok else "hold off new buys ⛔"))
        except Exception:  # noqa: BLE001
            pass
    h = _zerodha()
    if h:
        msg.append("\nYour holdings (%d) by the Investing rules:" % len(h["rows"]))
        msg += _rule_actions(h)
    else:
        msg.append("\n" + _reconnect_line())
        last = ((S.load_state().get("telegram") or {}).get("last_holdings") or {})
        if last.get("rows"):
            msg.append("Last known (%s): %s" % (last["day"], ", ".join("%s %s" % (r["symbol"], r["verdict"]) for r in last["rows"]
                                                                       if r["verdict"] in ("exit", "weak"))[:600] or "no Exit/Weak"))
    for mode in ("invest", "swing"):
        rows, _ = _setups(mode, 5)
        if rows:
            msg.append("\nTop %s setups in a buy zone (rules):" % L.LABEL[mode])
            msg += ["  %s · %s at %s (rank %d)" % (r["symbol"], r["setup"], rs(r["price"], 2), r["rank"]) for r in rows]
    try:
        msg += D.plan_extra()   # morning reading, last month, Scalping breakouts
    except Exception:  # noqa: BLE001
        pass
    msg.append(NOTE)
    return "\n".join(msg)


def _rule_actions(h):
    out = []
    groups = {"exit": [], "weak": [], "buy": [], "hold": []}
    for r in h["rows"]:
        groups.setdefault(r.get("verdict") or "hold", []).append(r)
    for key, icon, label in (("exit", "🔴", "Exit signal (below rule stop)"), ("weak", "🟠", "Weak (trend turned down)"),
                             ("buy", "🟢", "Buy signal (entry rules fire now)")):
        if groups.get(key):
            out.append("%s %s: %s" % (icon, label, ", ".join(
                "%s%s" % (r["symbol"], (" stop " + rs(r["rule_stop"], 2)) if r.get("rule_stop") else "") for r in groups[key])))
    out.append("⚪ Hold: %d stocks" % len(groups.get("hold", [])))
    return out


# ----------------------------------------------------------------- 15:32 market close
def close():
    d, by = _quotes()
    n50 = sorted([r for r in d["nifty50"] if r["pct"] is not None], key=lambda r: -r["pct"])
    up = sum(1 for r in n50 if r["pct"] > 0)
    msg = ["🔔 Market close · %s" % S.now_ist().strftime("%a %d %b")]
    for r in d["rows"]:
        msg.append("%s %s %s %s" % (arrow(r["pct"]), r["name"], pts(r["price"]), pct(r["pct"])))
    if n50:
        msg.append("\nNifty 50 breadth: %d up, %d down" % (up, len(n50) - up))
        msg.append("Top gainers: " + ", ".join("%s %s" % (r["name"], pct(r["pct"])) for r in n50[:5]))
        msg.append("Top losers: " + ", ".join("%s %s" % (r["name"], pct(r["pct"])) for r in n50[-5:][::-1]))
    w = [r for r in d["world"] if r["name"] in ("S&P 500 FUT", "NIKKEI", "HANG SENG", "BRENT CRUDE $", "USD/INR")]
    if w:
        msg.append("\nWorld now: " + " · ".join("%s %s" % (r["name"], pct(r["pct"])) for r in w))
    msg.append("Closing prices settle after NSE's closing session (about 15:40); small differences are normal.")
    return "\n".join(msg)


# ----------------------------------------------------------------- 15:35 holdings summary
def eod():
    msg = ["💼 Your holdings today · %s" % S.now_ist().strftime("%a %d %b")]
    h = _zerodha()
    held = []
    if not h:
        msg.append(_reconnect_line())
        msg.append("Holdings summary needs today's Zerodha login.")
    else:
        rows = h["rows"]
        held = [r["symbol"] for r in rows]
        gain = [r for r in rows if (r.get("day_pnl") or 0) > 0]
        loss = [r for r in rows if (r.get("day_pnl") or 0) < 0]
        msg.append("Value %s · today %s · total %s (%+.1f%%)" % (rs(h["total_value"]), signed(h["day_pnl"]),
                                                                 signed(h["pnl"]), h["pnl_pct"] or 0))
        msg.append("Gained today: %s on %d stocks · Lost today: %s on %d stocks" % (
            signed(sum(r["day_pnl"] for r in gain)), len(gain), signed(sum(r["day_pnl"] for r in loss)), len(loss)))
        gain.sort(key=lambda r: -r["day_pnl"])
        loss.sort(key=lambda r: r["day_pnl"])
        if gain:
            msg.append("🟢 Best: " + ", ".join("%s %s (%s)" % (r["symbol"], signed(r["day_pnl"]), pct(r["day_pct"])) for r in gain[:5]))
        if loss:
            msg.append("🔴 Worst: " + ", ".join("%s %s (%s)" % (r["symbol"], signed(r["day_pnl"]), pct(r["day_pct"])) for r in loss[:5]))
        msg.append("\nWhat the Investing rules say for tomorrow:")
        msg += _rule_actions(h)
        cfg = L.settings_for("invest")
        breach = []
        if len(rows) > cfg["max_positions"]:
            breach.append("%d holdings vs your limit of %d" % (len(rows), cfg["max_positions"]))
        over = [r["symbol"] for r in rows if r["value"] > cfg["max_per_stock"]]
        if over:
            breach.append("%d over your %s per-stock cap: %s" % (len(over), rs(cfg["max_per_stock"]), ", ".join(over[:8])))
        if breach:
            msg.append("\n⚠️ Your own limits: " + "; ".join(breach))
        _save_holdings(rows)
    for mode in ("invest", "swing"):
        mine, regime = _setups(mode, 10, only=set(held) | set(S.load_state()["settings"].get("watchlist") or []))
        top, _ = _setups(mode, 3)
        if mine or top:
            msg.append("\n%s buy signals (rules%s):" % (L.LABEL[mode], "" if regime else "; market filter says hold off"))
            msg += ["  %s · %s at %s%s" % (r["symbol"], r["setup"], rs(r["price"], 2), " (you hold it)" if r["symbol"] in held else " (watchlist)")
                    for r in mine]
            msg += ["  %s · %s (top ranked overall)" % (r["symbol"], r["setup"]) for r in top if r not in mine]
    msg.append(NOTE)
    return "\n".join(msg)


def _save_holdings(rows):
    with S._state_lock:
        st = S.load_state()
        tg = st.setdefault("telegram", {})
        tg["last_holdings"] = {"day": S.now_ist().date().isoformat(),
                               "rows": [{"symbol": r["symbol"], "verdict": r.get("verdict") or "hold", "qty": r.get("qty")} for r in rows]}
        S.save_state(st)


BUILDERS = {"morning": lambda: D.morning_plan()[0],
            "update": lambda: D.morning_update() or "08:45 update: nothing changed since the morning plan (normally not sent).",
            "login": lambda: D.login_text(), "signin": lambda: D.signin_text() or "Zerodha is not connected: no sign-in summary.",
            "plan": plan, "close": close, "eod": eod, "weekly": lambda: D.weekly()}


def run(kind):
    """Build one report, log it, and send it if Telegram is on for this kind."""
    try:
        text = BUILDERS[kind]()
    except Exception as e:  # noqa: BLE001
        log(kind, "Report could not be built: %s" % str(e)[:200], "error", str(e)[:200])
        return None
    T.notify(kind, text)
    return text


def due():
    """Called by the watcher every 30 s: start any report whose time has come today."""
    now = S.now_ist()
    m = now.hour * 60 + now.minute
    today = now.date().isoformat()
    st = S.load_state()
    sent = (st.get("telegram") or {}).get("sched") or {}
    for kind, at in SCHEDULE:
        if at <= m < at + 20 and sent.get(kind) != today:
            if not is_trading_day(check_traded=at >= 570):
                _mark(kind, today)
                continue
            _mark(kind, today)
            threading.Thread(target=run, args=(kind,), daemon=True).start()


def _mark(kind, day):
    with S._state_lock:
        st = S.load_state()
        tg = st.setdefault("telegram", {})
        tg.setdefault("sched", {})[kind] = day
        S.save_state(st)
