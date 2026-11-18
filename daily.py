"""Daily Telegram routine around the NAS power schedule (on 07:00-15:45 and 17:00-23:55).

- Start greeting on a REAL start (NAS power-on / Docker start), not on code reloads.
- Morning plan at the first start after 06:00 on a trading day: national + global headlines,
  global cues, one Bullish / Bearish / Mixed reading with its own track record. 08:45 update
  only if the reading flipped or important new headlines arrived.
- Zerodha: one-tap phone login link right after the morning start, then every 30 minutes
  until you sign in (last at 15:30, trading days only); again if the login drops later.
- First sign-in of the day: value, P&L, funds, every holding (one line) and mutual funds,
  plus your own limits (per stock, number of stocks, per sector).
- During market hours: a holding falls through its rule stop (once per stock per day);
  NIFTY moves 1.5% or India VIX goes above 20 (once each per day).
- Evening start: today's close in one line and estimated results dates for your holdings.
- Sunday ~10:00: weekly summary.

Everything reports what the portal's tested rules and the data say. It is not personal advice,
and the reading of news and cues is not a forecast.
"""
import hashlib
import hmac
import json
import os
import threading
import time
import urllib.parse
from datetime import date, timedelta

S = None   # server
L = None   # longterm
K = None   # kite
T = None   # telegram
R = None   # reports

NOTE = "Rule results and data, not personal advice."
NEWS_QUERIES = [   # (query, label)
    ("Sensex Nifty stock market today", "India"), ("RBI rupee India economy", "India"),
    ("Wall Street stocks Fed", "Global"), ("crude oil prices", "Global"), ("Asian markets stocks", "Global"),
]


# ----------------------------------------------------------------- small helpers
def _now():
    return S.now_ist()


def _min():
    n = _now()
    return n.hour * 60 + n.minute


def _today():
    return _now().date().isoformat()


def _tg(st):
    return st.setdefault("telegram", {})


def _flag(name, value=None):
    """Read (value None) or set a per-day flag in state.telegram.daily."""
    with S._state_lock:
        st = S.load_state()
        d = _tg(st).setdefault("daily", {})
        if value is None:
            return d.get(name)
        d[name] = value
        S.save_state(st)
        return value


def _once_today(name):
    """True the first time it is called on a day (and records it)."""
    with S._state_lock:
        st = S.load_state()
        d = _tg(st).setdefault("daily", {})
        if d.get(name) == _today():
            return False
        d[name] = _today()
        S.save_state(st)
        return True


def greeting(m=None):
    m = _min() if m is None else m
    if 300 <= m < 720:
        return "🌅 Good morning"
    if 720 <= m < 1020:
        return "🌞 Good afternoon"
    if 1020 <= m < 1260:
        return "🌆 Good evening"
    return "🌙 Good night"


def _send(kind, text):
    T.notify(kind, text)


# ----------------------------------------------------------------- one-tap Zerodha login link
def _sig(day):
    key = S._auth_token().encode()
    return hmac.new(key, ("kite-go-" + day).encode(), hashlib.sha256).hexdigest()[:24]


def login_link():
    base = S.PUBLIC_URL or "http://127.0.0.1:%d" % S.PORT
    return "%s/kite/go?t=%s" % (base, _sig(_today()))


def portal_link():
    return S.PUBLIC_URL or "http://127.0.0.1:%d" % S.PORT


def link_ok(t):
    """The link works on the day it was sent (and the morning after, for a late tap)."""
    days = [_today(), (_now().date() - timedelta(days=1)).isoformat()]
    return bool(t) and any(hmac.compare_digest(t, _sig(d)) for d in days)


def connected():
    try:
        return bool(K.held().get("connected"))
    except Exception:  # noqa: BLE001
        return False


# ----------------------------------------------------------------- news reading
def headlines(limit_each=4):
    out, seen = [], set()
    for q, label in NEWS_QUERIES:
        try:
            url = "https://news.google.com/rss/search?q=%s%%20when:1d&hl=en-IN&gl=IN&ceid=IN:en" % urllib.parse.quote(q)
            items = S._rss(S.fetch(url, 900), strip_source=True)
        except Exception:  # noqa: BLE001
            continue
        items = sorted([i for i in items if i["ts"] >= time.time() - 86400], key=lambda i: -i["ts"])
        n = 0
        for i in items:
            key = i["title"].lower()[:60]
            if key in seen:
                continue
            seen.add(key)
            tone, score, words = S.headline_tone(i["title"])
            out.append({"title": i["title"], "source": i.get("source", ""), "label": label, "tone": tone,
                        "score": score, "id": hashlib.sha1(i["title"].encode()).hexdigest()[:12]})
            n += 1
            if n >= limit_each:
                break
    return out


def reading():
    """Combine overnight cues (as before) with headline tone. Returns dict."""
    d, by = R._quotes()
    cue, lines = 0.0, []
    for name, w in R.CUES:
        r = by.get(name)
        if r and r["pct"] is not None:
            cue += w * r["pct"]
            lines.append("%s %s %s" % (R.arrow(r["pct"]), name, R.pct(r["pct"])))
    nifty, vix = by.get("NIFTY 50"), by.get("INDIA VIX")
    if nifty and nifty["pct"] is not None:
        cue += 0.3 * nifty["pct"]
    news = headlines()
    pos = sum(1 for h in news if h["tone"] == "pos")
    neg = sum(1 for h in news if h["tone"] == "neg")
    news_score = (pos - neg) / max(len(news), 1)          # -1 .. +1
    score = cue + 0.6 * news_score
    tone = "Bullish" if score > 0.35 else "Bearish" if score < -0.35 else "Mixed"
    return {"score": score, "cue": cue, "news_score": news_score, "pos": pos, "neg": neg, "tone": tone,
            "cue_lines": lines, "news": news, "nifty": nifty, "vix": vix}


def _track_line():
    calls = (_tg(S.load_state()).get("outlook_calls") or [])
    judged = [c for c in calls if c.get("right") is not None][-20:]
    if not judged:
        return "Track record: building up (needs a few trading days)."
    return "Track record: right %d of the last %d mornings." % (sum(c["right"] for c in judged), len(judged))


def _tone_for_track(t):
    return {"Bullish": "Positive", "Bearish": "Negative"}.get(t, "Mixed / flat")


def morning_plan(update=False):
    r = reading()
    icon = {"Bullish": "🟢", "Bearish": "🔴"}.get(r["tone"], "🟡")
    head = "🔄 08:45 update" if update else "📰 Morning plan"
    msg = ["%s · %s" % (head, _now().strftime("%a %d %b")),
           "%s Reading for today: %s (score %+.2f: cues %+.2f, news %d positive / %d negative)" % (
               icon, r["tone"], r["score"], r["cue"], r["pos"], r["neg"])]
    n, v = r["nifty"], r["vix"]
    msg.append("Yesterday: NIFTY 50 %s %s · VIX %s" % (R.pts(n["price"]) if n else "–", R.pct(n and n["pct"]),
                                                     "%.2f" % v["price"] if v else "–"))
    msg.append("\nGlobal cues:")
    msg += ["  " + x for x in r["cue_lines"]]
    for label in ("India", "Global"):
        hs = [h for h in r["news"] if h["label"] == label][:5]
        if hs:
            msg.append("\n%s news:" % label)
            msg += ["  %s %s" % ({"pos": "🟢", "neg": "🔴"}.get(h["tone"], "⚪"), h["title"][:140]) for h in hs]
    if v and v["price"] and v["price"] > 20:
        msg.append("\n⚠️ India VIX above 20: expect wider swings; the rules size smaller trades.")
    if not update:
        res = results_soon(days=1)
        if res:
            msg.append("\n📅 Results expected about today/tomorrow (estimate): " + ", ".join(res))
        msg.append("\nToday's routine: Zerodha login reminder now, final plan at 09:32 after the opening.")
    msg += [_track_line(), "🌐 Portal: %s" % portal_link(), "A reading of news and overnight cues, not a forecast. " + NOTE]
    R._save_call(_tone_for_track(r["tone"]), r["score"])
    _flag("morning_reading", {"day": _today(), "tone": r["tone"], "ids": [h["id"] for h in r["news"]]})
    return "\n".join(msg), r


def morning_update():
    """08:45: send only if the reading flipped or important new headlines arrived."""
    prev = _flag("morning_reading") or {}
    if prev.get("day") != _today():
        return None
    r = reading()
    new = [h for h in r["news"] if h["id"] not in set(prev.get("ids") or []) and h["tone"] != "neu"]
    flipped = r["tone"] != prev.get("tone")
    if not flipped and len(new) < 2:
        return None
    text, _ = morning_plan(update=True)
    why = ("reading changed %s → %s" % (prev.get("tone"), r["tone"])) if flipped else "%d important new headlines" % len(new)
    return text.replace("🔄 08:45 update", "🔄 08:45 update (%s)" % why, 1)


# ----------------------------------------------------------------- results dates (estimated)
def next_results(sym):
    try:
        q = (S.earnings(sym) or {}).get("quarters") or []
    except Exception:  # noqa: BLE001
        return None
    if not q:
        return None
    qe = date.fromisoformat(q[-1]["date"])
    m = qe.month + 3
    nq = date(qe.year + (m > 12), (m - 1) % 12 + 1, 1)
    nq = (nq.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)   # next quarter end
    nxt = nq + timedelta(days=60 if nq.month == 3 else 45)                              # filing deadline
    while nxt < _now().date() - timedelta(days=10):
        nxt += timedelta(days=91)
    return nxt


def _held_syms():
    h = K.held()
    if h.get("connected") and h.get("symbols"):
        return h["symbols"]
    last = (_tg(S.load_state()).get("last_holdings") or {}).get("rows") or []
    return [r["symbol"] for r in last]


def results_soon(days=1):
    out, today = [], _now().date()
    for sym in _held_syms():
        d = next_results(sym)
        # the deadline is the latest day; most companies report in the 2 weeks before it
        if d and today <= d <= today + timedelta(days=14) and (d - today).days <= 14:
            if (d - today).days <= days or d.weekday() >= 5:
                out.append("%s (by %s)" % (sym, d.strftime("%d %b")))
    return out


# ----------------------------------------------------------------- start greeting
def on_start():
    """Called once per REAL start (not code reloads), ~20 s after the server comes up."""
    time.sleep(20)
    started = _now().strftime("%H:%M")
    # after a NAS power-on the network / Telegram may need a minute: wait (up to 10 min) so the greeting is not lost
    for _ in range(40):
        try:
            if T._call("getMe", timeout=10):
                break
        except Exception:  # noqa: BLE001
            pass
        time.sleep(15)
    m = _min()
    trading = R.is_trading_day()
    try:
        import urllib.request
        urllib.request.urlopen("http://127.0.0.1:%d/login" % S.PORT, timeout=10)
        web = "✅"
    except Exception:  # noqa: BLE001
        web = "⚠️"
    lines = ["%s! Your NAS and Tradeskill are live (started %s IST)." % (greeting(m), started),
             "Checks: portal %s · Telegram ✅ · Zerodha %s" % (web, "✅ signed in" if connected() else "🔑 needs login"),
             "🌐 Open the portal: %s" % portal_link()]
    if not trading:
        lines.append("Market closed today (weekend or NSE holiday).")
    if m >= 1020:   # evening start
        try:
            d, by = R._quotes()
            n = by.get("NIFTY 50")
            if n:
                lines.append("Today NIFTY 50 %s %s %s." % (R.pts(n["price"]), R.arrow(n["pct"]), R.pct(n["pct"])))
        except Exception:  # noqa: BLE001
            pass
        res = results_soon(days=1)
        if res:
            lines.append("📅 Results expected soon (estimate): " + ", ".join(res))
    _send("hello", "\n".join(lines))
    if trading and 360 <= m < 560 and _once_today("morning_sent"):
        try:
            text, _ = morning_plan()
            _send("morning", text)
        except Exception as e:  # noqa: BLE001
            R.log("morning", "Morning plan could not be built: %s" % str(e)[:200], "error")
    if trading and 420 <= m <= 930:
        login_reminder(force=True)


# ----------------------------------------------------------------- Zerodha reminders + first sign-in
def login_reminder(force=False):
    if not R.is_trading_day():
        return
    m = _min()
    if not (420 <= m <= 930) or connected():
        return
    last = _flag("login_last") or {}
    if not force and last.get("day") == _today() and time.time() - last.get("at", 0) < 29.5 * 60:
        return
    later = bool(_flag("signin_sent") == _today())
    msg = ["🔑 %s Zerodha login needed%s." % ("Again:" if later else "", " (it ended during the day)" if later else ""),
           "Tap to sign in (one step, opens Zerodha's login on your phone):", login_link(),
           "🌐 Portal: %s" % portal_link(),
           "Keep Tailscale on. Reminders every 30 min until you sign in; last at 15:30."]
    _flag("login_last", {"day": _today(), "at": time.time()})
    _send("login", "\n".join(msg))


def _fit_lines(h):
    cfg = L.settings_for("invest")
    out = []
    live = [r for r in h["rows"] if r.get("qty")]
    if len(live) > cfg["max_positions"]:
        out.append("%d holdings vs your limit of %d" % (len(live), cfg["max_positions"]))
    over = [r["symbol"] for r in h["rows"] if r["value"] > cfg["max_per_stock"]]
    if over:
        out.append("%d over the %s per-stock cap" % (len(over), R.rs(cfg["max_per_stock"])))
    for z in (h.get("fit") or {}).get("sectors") or []:
        if z.get("over"):
            out.append("%s %.0f%% (%d stocks)" % (z["sector"], z["pct"], z["stocks"]))
    return out


def signin_summary():
    """After the day's first Zerodha login: everything in one message."""
    text = signin_text()
    if text:
        _send("signin", text)


def login_text():
    return "\n".join(["🔑 Zerodha login (tap to sign in, Tailscale on):", login_link(), "🌐 Portal: %s" % portal_link(),
                      "Reminders every 30 min from 07:00 until you sign in; last at 15:30 (trading days)."])


def signin_text():
    h = K.holdings("invest")
    if not h.get("connected") or "rows" not in h:
        return None
    try:
        x = K.extras()
    except Exception:  # noqa: BLE001
        x = {"mfs": [], "funds": None, "positions": []}
    icon = {"exit": "🔴", "weak": "🟠", "buy": "🟢", "hold": "⚪"}
    f = x.get("funds") or {}
    mfv = sum(m["value"] for m in x["mfs"])
    mfc = sum(m["cost"] for m in x["mfs"])
    msg = ["✅ Zerodha connected · %s" % _now().strftime("%a %d %b %H:%M"),
           "Stocks: value %s · invested %s · P&L %s (%+.1f%%) · today %s" % (
               R.rs(h["total_value"]), R.rs(h["total_cost"]), R.signed(h["pnl"]), h["pnl_pct"] or 0, R.signed(h["day_pnl"])),
           "Funds available: %s" % (R.rs(f.get("net")) if f.get("net") is not None else "–")]
    if x["mfs"]:
        msg.append("Mutual funds: value %s · P&L %s" % (R.rs(mfv), R.signed(mfv - mfc)))
    rows = [r for r in h["rows"] if r.get("qty")]   # Zerodha keeps sold-out stocks with 0 shares for a while
    msg.append("\nHoldings (%d) · rule verdict:" % len(rows))
    for r in sorted(rows, key=lambda r: -r["value"]):
        msg.append("%s %s %g × %s = %s · %s%s" % (icon.get(r.get("verdict"), "⚪"), r["symbol"], r["qty"], R.rs(r["ltp"], 2),
                                                  R.rs(r["value"]), R.signed(r["pnl"]),
                                                  " (%+.1f%%)" % r["pnl_pct"] if r.get("pnl_pct") is not None else ""))
    if x["mfs"]:
        msg.append("\nMutual funds (%d):" % len(x["mfs"]))
        msg += ["• %s · %s · %s" % (m["fund"][:38], R.rs(m["value"]), R.signed(m["pnl"])) for m in x["mfs"]]
    fit = _fit_lines(h)
    if fit:
        msg.append("\n⚠️ Your own limits: " + "; ".join(fit))
    msg.append(NOTE)
    msg.insert(len(msg) - 1, "🌐 Portal: %s" % portal_link())
    R._save_holdings(h["rows"])
    return "\n".join(msg)


def after_login():
    """Called from the Zerodha callback. First login of the day -> full summary."""
    if _once_today("signin_sent"):
        threading.Thread(target=signin_summary, daemon=True).start()


# ----------------------------------------------------------------- 09:32 final plan additions
def month_stats():
    out = []
    try:
        n = L.history("^NSEI", index=True)["bars"]
        if len(n) > 22:
            ch = (n[-1][4] / n[-22][4] - 1) * 100
            hi = max(b[2] for b in n[-22:])
            lo = min(b[3] for b in n[-22:])
            out.append("NIFTY 50 last month: %+.1f%% (range %s – %s)" % (ch, R.pts(lo), R.pts(hi)))
    except Exception:  # noqa: BLE001
        pass
    moves = []
    for sym in _held_syms():
        try:
            b = L.history(sym)["bars"]
            if len(b) > 22:
                moves.append((sym, (b[-1][4] / b[-22][4] - 1) * 100))
        except Exception:  # noqa: BLE001
            pass
    if moves:
        moves.sort(key=lambda z: -z[1])
        up = sum(1 for _, v in moves if v > 0)
        out.append("Your holdings last month: %d up, %d down" % (up, len(moves) - up))
        out.append("  Best: " + ", ".join("%s %+.1f%%" % z for z in moves[:3]))
        out.append("  Worst: " + ", ".join("%s %+.1f%%" % z for z in moves[-3:][::-1]))
    for mode in ("swing", "invest"):
        try:
            j = L.journal(mode)
            if j["signals"]:
                out.append("Forward test %s: %d signals, %d closed%s" % (
                    L.LABEL[mode], j["signals"], j["closed"],
                    ", average %+.2fR" % j["avg_r_closed"] if j.get("avg_r_closed") is not None else ""))
        except Exception:  # noqa: BLE001
            pass
    return out


def plan_extra():
    """Lines appended to the 09:32 plan: news reading, last month, Scalping setups."""
    msg = []
    prev = _flag("morning_reading") or {}
    if prev.get("day") == _today():
        msg.append("Morning reading was %s." % prev.get("tone"))
    ms = month_stats()
    if ms:
        msg.append("\n📊 Last month:")
        msg += ms
    try:
        d = S.scan()
        orb = [r for r in d["rows"] if r.get("orb", {}).get("state") == "confirmed" and r["orb"].get("outcome") == "open"]
        orb.sort(key=lambda r: -r.get("rank", 0))
        if orb:
            msg.append("\nScalping (opening-range breakouts so far, rules):")
            msg += ["  %s at %s (rank %d)" % (r["symbol"], R.rs(r["price"], 2), r.get("rank", 0)) for r in orb[:5]]
    except Exception:  # noqa: BLE001
        pass
    return msg


# ----------------------------------------------------------------- market-hours watches
def stop_watch():
    """A holding trades below its Investing rule stop: once per stock per day."""
    if not R.is_trading_day() or not (555 <= _min() <= 930):
        return
    mkt = L.market()
    hit = []
    done = set((_flag("stop_alerts") or {}).get(_today(), []))
    for sym in _held_syms():
        if sym in done:
            continue
        try:
            ind = L.indicators(L.history(sym)["bars"])
            v = K._verdict(ind, mkt, "invest")
            px = ind["c"][-1]
            if v.get("rule_stop") and px < v["rule_stop"]:
                hit.append((sym, px, v["rule_stop"]))
        except Exception:  # noqa: BLE001
            pass
    if hit:
        with S._state_lock:
            st = S.load_state()
            d = _tg(st).setdefault("daily", {})
            d["stop_alerts"] = {_today(): sorted(done | {h[0] for h in hit})}
            S.save_state(st)
        _send("stopalert", "🔴 Below the rule stop (Investing rules):\n" + "\n".join(
            "  %s at %s · rule stop %s" % (s, R.rs(p, 2), R.rs(rs_, 2)) for s, p, rs_ in hit) + "\n" + NOTE)


def move_watch():
    if not R.is_trading_day() or not (560 <= _min() <= 930):
        return
    d, by = R._quotes()
    n, v = by.get("NIFTY 50"), by.get("INDIA VIX")
    if n and n["pct"] is not None and abs(n["pct"]) >= 1.5 and _once_today("move_nifty"):
        _send("move", "%s Big market move: NIFTY 50 %s %s %s. The rules hold off new buys if the trend breaks." % (
            "🚀" if n["pct"] > 0 else "⚠️", R.pts(n["price"]), R.arrow(n["pct"]), R.pct(n["pct"])))
    if v and v["price"] and v["price"] > 20 and _once_today("move_vix"):
        _send("move", "⚠️ India VIX %.2f (above 20): wider swings today; the rules size smaller trades." % v["price"])


# ----------------------------------------------------------------- Sunday weekly summary
def weekly():
    msg = ["🗓️ Weekly summary · week to %s" % _now().strftime("%d %b")]
    try:
        n = L.history("^NSEI", index=True)["bars"]
        if len(n) > 6:
            msg.append("NIFTY 50 this week: %+.1f%%" % ((n[-1][4] / n[-6][4] - 1) * 100))
    except Exception:  # noqa: BLE001
        pass
    rows = (_tg(S.load_state()).get("last_holdings") or {}).get("rows") or []
    moves, pnl = [], 0.0
    for r in rows:
        try:
            b = L.history(r["symbol"])["bars"]
            if len(b) > 6:
                ch = b[-1][4] - b[-6][4]
                moves.append((r["symbol"], (b[-1][4] / b[-6][4] - 1) * 100))
                pnl += ch * (r.get("qty") or 0)
        except Exception:  # noqa: BLE001
            pass
    if moves:
        moves.sort(key=lambda z: -z[1])
        if any(r.get("qty") for r in rows):
            msg.append("Your holdings this week: about %s" % R.signed(pnl))
        msg.append("Best: " + ", ".join("%s %+.1f%%" % z for z in moves[:3]))
        msg.append("Worst: " + ", ".join("%s %+.1f%%" % z for z in moves[-3:][::-1]))
    for mode in ("swing", "invest"):
        try:
            j = L.journal(mode)
            msg.append("Forward test %s: %d signals, %d closed, %d open%s" % (
                L.LABEL[mode], j["signals"], j["closed"], j["open"],
                ", average %+.2fR vs backtest %+.2fR" % (j["avg_r_closed"], j["expected_r"]) if j.get("avg_r_closed") is not None else ""))
        except Exception:  # noqa: BLE001
            pass
    res = results_soon(days=7)
    if res:
        msg.append("📅 Results due in the next weeks (estimate): " + ", ".join(res))
    msg.append(NOTE)
    return "\n".join(msg)


# ----------------------------------------------------------------- one-shot live test of every message
def test_all():
    """Send every message type once, marked TEST (triggered by data/test_notifications.flag)."""
    tag = "🧪 TEST · "

    def send(kind, text):
        if text:
            _send(kind, tag + text)

    m = _min()
    send("hello", "%s! Your NAS and Tradeskill are live (started %s IST).\nChecks: portal ✅ · Telegram ✅ · Zerodha %s" % (
        greeting(m), _now().strftime("%H:%M"), "✅ signed in" if connected() else "🔑 needs login"))
    jobs = [("morning", lambda: morning_plan()[0]),
            ("update", lambda: morning_update() or "08:45 update: nothing changed since the morning plan, so normally no message."),
            ("login", lambda: "\n".join(["🔑 Zerodha login needed.", "Tap to sign in (one step, opens Zerodha's login on your phone):",
                                         login_link(), "Works on your home Wi-Fi (or Tailscale). Reminders every 30 min until you sign in; last at 15:30."])),
            ("plan", lambda: R.plan()), ("weekly", weekly)]
    for kind, fn in jobs:
        try:
            send(kind, fn())
        except Exception as e:  # noqa: BLE001
            send(kind, "%s could not be built: %s" % (kind, str(e)[:150]))
    try:   # sign-in summary, stop and market-move checks as they stand right now
        out = []
        orig = globals()["_send"]
        globals()["_send"] = lambda k, t: out.append((k, t))
        try:
            signin_summary()
        finally:
            globals()["_send"] = orig
        for k, t in out:
            send(k, t)
        mkt, hits = L.market(), []
        for sym in _held_syms():
            try:
                ind = L.indicators(L.history(sym)["bars"])
                v = K._verdict(ind, mkt, "invest")
                if v.get("rule_stop") and ind["c"][-1] < v["rule_stop"]:
                    hits.append("  %s at %s · rule stop %s" % (sym, R.rs(ind["c"][-1], 2), R.rs(v["rule_stop"], 2)))
            except Exception:  # noqa: BLE001
                pass
        send("stopalert", ("🔴 Below the rule stop (Investing rules):\n" + "\n".join(hits)) if hits else "Rule-stop alert: no holding is below its rule stop right now.")
        d, by = R._quotes()
        n, v = by.get("NIFTY 50"), by.get("INDIA VIX")
        send("move", "Market-move check: NIFTY 50 %s (alert at ±1.5%%) · India VIX %s (alert above 20)." % (
            R.pct(n and n["pct"]), "%.2f" % v["price"] if v else "–"))
    except Exception as e:  # noqa: BLE001
        send("signin", "Test part failed: %s" % str(e)[:150])
    send("hello", "Test finished: every message type above was sent once. Normal schedule continues.")


# ----------------------------------------------------------------- watcher hook (every 30 s)
_last = {"stop": 0, "move": 0}


def tick():
    flag = os.path.join(S.DATA, "test_notifications.flag")
    if os.path.exists(flag):
        try:
            os.remove(flag)
        except OSError:
            pass
        threading.Thread(target=test_all, name="notify-test", daemon=True).start()
    flag = os.path.join(S.DATA, "send_login_link.flag")   # one-shot: send a fresh Zerodha login link now
    if os.path.exists(flag):
        try:
            os.remove(flag)
        except OSError:
            pass
        _send("login", "\n".join(["🔑 Zerodha login (tap to sign in, Tailscale on):", login_link(),
                                   "🌐 Open the portal: %s" % portal_link(), "Tip: pin this message for quick access."]))
    m = _min()
    for job in (lambda: login_reminder(),):
        try:
            job()
        except Exception:  # noqa: BLE001
            pass
    # morning plan if the server was already on at 06:00 (no fresh start)
    if 360 <= m < 560 and R.is_trading_day() and _flag("morning_sent") != _today():
        if _once_today("morning_sent"):
            try:
                text, _ = morning_plan()
                _send("morning", text)
            except Exception as e:  # noqa: BLE001
                R.log("morning", "Morning plan could not be built: %s" % str(e)[:200], "error")
    if 525 <= m < 545 and R.is_trading_day() and _once_today("update_checked"):
        try:
            t = morning_update()
            if t:
                _send("update", t)
        except Exception:  # noqa: BLE001
            pass
    if time.time() - _last["stop"] > 300:
        _last["stop"] = time.time()
        for job in (stop_watch, move_watch):
            try:
                job()
            except Exception:  # noqa: BLE001
                pass
    if _now().weekday() == 6 and 600 <= m < 660 and _once_today("weekly"):
        try:
            _send("weekly", weekly())
        except Exception:  # noqa: BLE001
            pass
