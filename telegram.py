"""Telegram notifications (send-only).

The bot token comes from TELEGRAM_BOT_TOKEN (tradeskill.env on the NAS) or, for a PC copy,
data/telegram_token.txt. It is never sent to the browser or written to git. The bot only SENDS
messages to the one chat that pressed Start; it does not read commands and cannot place orders.

A background watcher (started by server.py) keeps alerts, GTTs and paper exits running with no
browser open, and sends the after-close messages (signals, holdings, daily summary) at 15:45 IST.
"""
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

S = None   # server module
L = None   # longterm module
K = None   # kite module
G = None   # gtt module

D = None   # daily module
KINDS = [("hello", "Greeting when the NAS / portal starts"), ("morning", "Morning plan: news + global cues (first start after 06:00)"),
         ("update", "08:45 update, only if the morning reading changed"), ("login", "Zerodha login reminders (every 30 min until signed in)"),
         ("signin", "First Zerodha login of the day: holdings, funds, mutual funds, limits"),
         ("stopalert", "A holding falls below its rule stop"), ("move", "Big market move: NIFTY ±1.5% or VIX above 20"),
         ("weekly", "Sunday 10:00 weekly summary"), ("plan", "09:32 Day plan: market, your holdings, best setups"),
         ("close", "15:32 Market close summary"), ("eod", "15:35 Your holdings: today's gains and losses, rule actions"),
         ("zerodha", "Your real Zerodha buys and sells (seen within ~2 minutes)"), ("alert", "Price alerts ringing"),
         ("paper", "Paper trades: GTT fills, stops, targets, sells")]
R = None   # reports module (scheduled messages + history log)
_send_lock = threading.Lock()


def token():
    t = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not t:
        try:
            with open(os.path.join(S.DATA, "telegram_token.txt"), encoding="utf-8") as f:
                t = f.read().strip()
        except OSError:
            t = ""
    return t


def _cfg(st):
    c = st.get("telegram") or {}
    c.setdefault("on", {})
    for k, _ in KINDS:
        c["on"].setdefault(k, True)
    return c


def _call(method, params=None, timeout=20):
    tok = token()
    if not tok:
        raise S.ApiError(400, "No bot token yet. Add TELEGRAM_BOT_TOKEN to tradeskill.env and rebuild.")
    url = "https://api.telegram.org/bot%s/%s" % (tok, method)
    data = urllib.parse.urlencode(params or {}).encode() if params else None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=timeout) as r:
            j = json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            j = json.loads(e.read())
        except ValueError:
            j = {"ok": False, "description": "HTTP %s" % e.code}
    except Exception as e:  # noqa: BLE001
        raise S.ApiError(502, "Telegram not reachable: %s" % str(e)[:80])
    if not j.get("ok"):
        desc = j.get("description") or "error"
        if "Unauthorized" in desc:
            desc = "Telegram refused the bot token. Check TELEGRAM_BOT_TOKEN."
        raise S.ApiError(502, desc[:200])
    return j.get("result")


def status():
    c = _cfg(S.load_state())
    return {"token_set": bool(token()), "connected": bool(c.get("chat_id")), "name": c.get("name"),
            "on": c["on"], "kinds": KINDS, "last_error": c.get("last_error"), "last_sent": c.get("last_sent")}


def connect():
    """Find the chat that pressed Start on the bot, save it, and send a test message."""
    upd = _call("getUpdates", {"limit": 50, "timeout": 0}) or []
    chats = [u.get("message", {}).get("chat") or u.get("my_chat_member", {}).get("chat") for u in upd]
    chats = [c for c in chats if c and c.get("type") == "private"]
    if not chats:
        raise S.ApiError(409, "No chat found. Open your bot in Telegram, press Start (or send any message), then click Connect again.")
    chat = chats[-1]
    with S._state_lock:
        st = S.load_state()
        c = _cfg(st)
        c.update(chat_id=chat["id"], name=(chat.get("first_name", "") + " " + chat.get("last_name", "")).strip()
                 or chat.get("username") or "you", last_error=None)
        st["telegram"] = c
        S.save_state(st)
    _post(chat["id"], "Tradeskill connected ✅\nYou will get the messages you switch on under Limits → Telegram. "
                      "This bot only sends messages; it cannot buy or sell.")
    return status()


def disconnect():
    with S._state_lock:
        st = S.load_state()
        c = _cfg(st)
        c.pop("chat_id", None)
        c.pop("name", None)
        st["telegram"] = c
        S.save_state(st)
    return status()


def set_on(on):
    with S._state_lock:
        st = S.load_state()
        c = _cfg(st)
        for k, _ in KINDS:
            if k in on:
                c["on"][k] = bool(on[k])
        st["telegram"] = c
        S.save_state(st)
    return status()


def test():
    c = _cfg(S.load_state())
    if not c.get("chat_id"):
        raise S.ApiError(409, "Connect Telegram first.")
    _post(c["chat_id"], "Test message from Tradeskill 👍  (%s IST)" % S.market_clock()["ist"])
    return {"ok": True}


def _post(chat_id, text):
    with _send_lock:   # Telegram allows about 1 message per second per chat
        _call("sendMessage", {"chat_id": chat_id, "text": text[:4000], "disable_web_page_preview": "true"})
        time.sleep(1.05)


def notify(kind, text):
    """Send a message in the background if Telegram is connected and this kind is switched on.
    Never raises and never slows the caller."""
    def log(status, err=None):
        try:
            R.log(kind, text, status, err)
        except Exception:  # noqa: BLE001
            pass
    try:
        if not token():
            return log("not sent: no bot token")
        c = _cfg(S.load_state())
        if not c.get("chat_id"):
            return log("not sent: Telegram not connected")
        if not c["on"].get(kind, True):
            return log("not sent: switched off")
    except Exception:  # noqa: BLE001
        return log("not sent: error")

    def run():
        err = None
        try:
            _post(c["chat_id"], text)
        except Exception as e:  # noqa: BLE001
            err = getattr(e, "msg", None) or str(e)[:150]
        log("failed" if err else "sent", err)
        try:
            with S._state_lock:
                st = S.load_state()
                cc = _cfg(st)
                cc["last_error"] = err
                if not err:
                    cc["last_sent"] = S.market_clock()["ist"]
                st["telegram"] = cc
                S.save_state(st)
        except Exception:  # noqa: BLE001
            pass
    threading.Thread(target=run, daemon=True).start()


# ----------------------------------------------------------------- after-close messages
def _rs(v, dec=2):
    """Indian digit grouping: ₹12,47,627.50"""
    if v is None:
        return "–"
    neg, v = v < 0, abs(v)
    whole, frac = ("%.*f" % (dec, v)).split(".") if dec else ("%.0f" % v, "")
    head, tail = whole[:-3], whole[-3:]
    while len(head) > 2:
        tail = head[-2:] + "," + tail
        head = head[:-2]
    s = (head + "," + tail) if head else tail
    return ("-" if neg else "") + "₹" + s + ("." + frac if frac else "")


def after_close():
    """Buy signals, holdings at Exit/Weak and the daily summary (once per trading day)."""
    st = S.load_state()
    on = _cfg(st)["on"]
    watch = list(st["settings"].get("watchlist") or [])
    held = []
    try:
        held = K.held()["symbols"]
    except Exception:  # noqa: BLE001
        pass
    mine = set(watch) | set(held)
    sig_lines = []
    if on.get("signals"):
        for mode in ("swing", "invest"):
            try:
                d = L.scan_long(mode, refresh=True)
            except Exception:  # noqa: BLE001
                continue
            if not d.get("regime"):
                sig_lines.append("%s: market filter says hold off new buys." % L.LABEL[mode])
            for r in d["rows"]:
                if r["status"] in ("confirmed", "recent") and r["symbol"] in mine:
                    sig_lines.append("%s · %s %s at %s (%s%s)" % (L.LABEL[mode], r["symbol"], r["setup"], _rs(r["price"]),
                                                                "you hold it" if r["symbol"] in held else "watchlist",
                                                                ", rank %d" % r["rank"]))
            n = sum(1 for r in d["rows"] if r["status"] in ("confirmed", "recent"))
            sig_lines.append("%s: %d of 250 stocks in a buy zone today." % (L.LABEL[mode], n))
        notify("signals", "📈 Buy signals after today's close\n" + "\n".join(sig_lines))
    hold_lines = []
    if on.get("holdings") and held:
        try:
            h = K.holdings("invest")
            for r in h.get("rows", []):
                if r.get("verdict") in ("exit", "weak"):
                    hold_lines.append("%s %s · %s%s" % ("🔴" if r["verdict"] == "exit" else "🟠", r["symbol"],
                                                       "Exit signal" if r["verdict"] == "exit" else "Weak",
                                                       (" · rule stop " + _rs(r.get("rule_stop"))) if r.get("rule_stop") else ""))
        except Exception:  # noqa: BLE001
            hold_lines.append("Could not read Zerodha holdings (log in again on My holdings).")
        if hold_lines:
            notify("holdings", "📋 Your Zerodha holdings (Investing rules)\n" + "\n".join(hold_lines))
    if on.get("summary"):
        lines = ["🗓 Tradeskill · %s" % S.market_clock()["date"]]
        try:
            for r in S.indices()["rows"][:3]:
                lines.append("%s %s (%+.2f%%)" % (r["name"], "{:,.2f}".format(r["price"]), r["pct"] or 0))
        except Exception:  # noqa: BLE001
            pass
        for mode in ("swing", "invest"):
            try:
                p = L.portfolio_long(mode)
                lines.append("Paper %s: %d holdings, equity %s (%s%s since start)" % (
                    L.LABEL[mode], len(p["positions"]), _rs(p["equity"], 0), "+" if p["total_pnl"] >= 0 else "", _rs(p["total_pnl"], 0)))
            except Exception:  # noqa: BLE001
                pass
        if held:
            try:
                h = K.holdings("invest")
                lines.append("Zerodha: value %s, today %s%s, total %s%s (%+.1f%%)" % (
                    _rs(h["total_value"], 0), "+" if h["day_pnl"] >= 0 else "", _rs(h["day_pnl"], 0),
                    "+" if h["pnl"] >= 0 else "", _rs(h["pnl"], 0), h["pnl_pct"] or 0))
            except Exception:  # noqa: BLE001
                pass
        lines.append("Signals for your stocks: %d · holdings at Exit/Weak: %d" % (
            sum(1 for x in sig_lines if "you hold it" in x or "watchlist" in x), len(hold_lines)))
        notify("summary", "\n".join(lines))


# ----------------------------------------------------------------- your real Zerodha trades
def zerodha_trades():
    """Compare today's bought / sold quantities in Zerodha positions with the last look and
    report the difference. Read-only: uses the same positions read as My holdings.
    The first look of the day only records, so a restart does not repeat earlier trades."""
    st = S.load_state()
    c = _cfg(st)
    if not c.get("chat_id") or not c["on"].get("zerodha", True):
        return
    if not (st.get("kite") or {}).get("token"):
        return
    rows = K._rows(K.call("portfolio", {"mode": "positions"}))
    if not rows and "data" not in K.call("portfolio", {"mode": "positions"}):
        return
    today = S.market_clock()["date"]
    snap = {}
    for r in rows:
        key = "%s|%s|%s" % (r.get("tradingsymbol"), r.get("exchange"), r.get("product"))
        snap[key] = [K._num(r.get("day_buy_quantity")) or 0, K._num(r.get("day_sell_quantity")) or 0,
                     K._num(r.get("day_buy_price")) or 0, K._num(r.get("day_sell_price")) or 0,
                     K._num(r.get("day_buy_value")) or 0, K._num(r.get("day_sell_value")) or 0]
    prev = c.get("zsnap") or {}
    if prev.get("day") == today:
        old = prev.get("rows") or {}
        for key, (bq, sq, bp, sp, bv, sv) in snap.items():
            ob = old.get(key, [0, 0, 0, 0, 0, 0])
            sym, exch, prod = key.split("|")
            if bq > ob[0]:
                q = bq - ob[0]
                px = (bv - ob[4]) / q if bv > ob[4] else bp
                notify("zerodha", "🟢 Zerodha BUY: %g %s at %s (%s, %s) · today's total bought %g" % (q, sym, _rs(px), prod, exch, bq))
            if sq > ob[1]:
                q = sq - ob[1]
                px = (sv - ob[5]) / q if sv > ob[5] else sp
                notify("zerodha", "🔴 Zerodha SELL: %g %s at %s (%s, %s) · today's total sold %g" % (q, sym, _rs(px), prod, exch, sq))
    with S._state_lock:
        st = S.load_state()
        cc = _cfg(st)
        cc["zsnap"] = {"day": today, "rows": snap}
        st["telegram"] = cc
        S.save_state(st)


# ----------------------------------------------------------------- background watcher
def watcher():
    """Runs for the life of the server. Each job is wrapped so one failure never stops the rest."""
    last_paper = last_z = 0
    while True:
        try:
            clk = S.market_clock()
            weekday = S.now_ist().weekday() < 5
            if weekday and 540 <= clk["minute"] <= 945:            # 09:00-15:45
                for job in (S.check_alerts, G.check):
                    try:
                        job()
                    except Exception:  # noqa: BLE001
                        pass
                if clk["minute"] >= 555 and time.time() - last_z > 110:   # your Zerodha trades, every ~2 minutes
                    last_z = time.time()
                    try:
                        zerodha_trades()
                    except Exception:  # noqa: BLE001
                        pass
                if time.time() - last_paper > 300:                 # paper books every 5 minutes
                    last_paper = time.time()
                    for job in (S.portfolio, lambda: L.portfolio_long("swing"), lambda: L.portfolio_long("invest")):
                        try:
                            job()
                        except Exception:  # noqa: BLE001
                            pass
            try:
                D.tick()                                            # reminders, morning plan, watches, weekly
            except Exception:  # noqa: BLE001
                pass
            try:
                R.due()                                             # 08:45 / 09:32 / 15:32 / 15:35 reports
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            pass
        time.sleep(30)


def start():
    threading.Thread(target=watcher, name="tradeskill-watcher", daemon=True).start()
