"""Telegram notifications (send-only).

The bot token comes from TELEGRAM_BOT_TOKEN (tradeskill.env on the NAS) or, for a PC copy,
data/telegram_token.txt. It is never sent to the browser or written to git. The bot only SENDS
messages to the one chat that pressed Start; it does not read commands and cannot place orders.

A background watcher (started by server.py) keeps alerts, GTTs and paper exits running with no
browser open, and sends the after-close messages (signals, holdings, daily summary) at 15:45 IST.
"""
import hmac
import json
import os
import re
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
         ("weekly", "Sunday 10:00 weekly summary"), ("gtt", "GTT saved: details + Zerodha GTT link"), ("plan", "09:32 Day plan: market, your holdings, best setups"),
         ("close", "15:32 Market close summary"), ("eod", "15:35 Your holdings: today's gains and losses, rule actions"),
         ("zerodha", "Your real Zerodha buys and sells (seen within ~2 minutes)"), ("alert", "Price alerts ringing"),
         ("paper", "Paper trades: GTT fills, stops, targets, sells"),
         ("hindinews", "07:00 Overnight global market news in Hindi (20:00–07:00), every day"),
         ("exits", "10:00 Sell · Exit signal (rules) for your holdings, only when there is one"),
         ("whatnext", "12:00 What next: 3–6 month sell / buy plan"),
         ("roombuys", "13:00 Rule buy signals you have room for (trading days, only when there is one)"),
         ("loss10", "A holding is down 10% or more from your buy price"),
         ("trend", "Trend change on a holding (e.g. Uptrend → Weak → Sell), market hours"),
         ("lossnews", "A holding down 5%+ with mostly negative news"),
         ("custom", "Your own notifications (master switch for all of them)")]
R = None   # reports module (scheduled messages + history log)
C = None   # custom module (your own notifications)
LG = None  # ledger module (your holdings, for the quiet rule)
_send_lock = threading.Lock()


def _token_file():
    return os.path.join(S.DATA, "telegram_token.txt")


def token():
    """The bot set on the Limits page (data/telegram_token.txt) wins; otherwise TELEGRAM_BOT_TOKEN from tradeskill.env."""
    try:
        with open(_token_file(), encoding="utf-8") as f:
            t = f.read().strip()
    except OSError:
        t = ""
    return t or os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


def _cfg(st):
    c = st.get("telegram") or {}
    c.setdefault("on", {})
    for k, _ in KINDS:
        c["on"].setdefault(k, True)
    return c


def _call(method, params=None, timeout=20, tok=None):
    explicit = bool(tok)
    tok = tok or token()
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
            desc = "Telegram refused this bot token: copy it again from @BotFather." if explicit else "Telegram refused the bot token. Check TELEGRAM_BOT_TOKEN."
        elif "chat not found" in desc.lower():
            desc = "Telegram can't find that chat: open the bot, press Start (or add it to the group and send a message), then try again."
        raise S.ApiError(502, desc[:200])
    return j.get("result")


def status():
    c = _cfg(S.load_state())
    return {"token_set": bool(token()), "connected": bool(c.get("chat_id")), "name": c.get("name"),
            "on": c["on"], "kinds": KINDS, "last_error": c.get("last_error"), "last_sent": c.get("last_sent"),
            "removed": c.get("removed") or [], "bot": c.get("bot"), "bot_changed": c.get("bot_changed"),
            "token_tail": token()[-4:] if token() else None, "token_source": "page" if os.path.exists(_token_file()) else "env"}


# ----------------------------------------------------------------- change the bot from the Limits page
TOKEN_RE = re.compile(r"\d{5,}:[A-Za-z0-9_-]{30,}")
_pw_fail = {"n": 0, "until": 0.0}


def _check_pw(pw):
    """Changing the bot needs the portal password again: 5 wrong tries lock it for 15 minutes."""
    if time.time() < _pw_fail["until"]:
        raise S.ApiError(429, "Too many wrong passwords. Wait 15 minutes, then try again.")
    if not S.PASSWORD or not hmac.compare_digest(str(pw or "").encode(), S.PASSWORD.encode()):
        _pw_fail["n"] += 1
        if _pw_fail["n"] >= 5:
            _pw_fail.update(n=0, until=time.time() + 900)
        raise S.ApiError(403, "The portal password is not right.")
    _pw_fail["n"] = 0


def _tok_in(body):
    t = re.sub(r"\s+", "", str(body.get("token") or ""))
    if not TOKEN_RE.fullmatch(t):
        raise S.ApiError(400, "That doesn't look like a bot token. It looks like 123456789:AAH... and comes from @BotFather.")
    return t


def _chat_name(ch):
    return (ch.get("title") or ("%s %s" % (ch.get("first_name", ""), ch.get("last_name", ""))).strip() or ch.get("username") or str(ch.get("id")))


def find_chat(body):
    """Chats that pressed Start on (or wrote to) the new bot, newest last. Nothing is saved."""
    _check_pw(body.get("password"))
    t = _tok_in(body)
    me = _call("getMe", tok=t)
    upd = _call("getUpdates", {"limit": 100, "timeout": 0}, tok=t) or []
    seen = {}
    for u in upd:
        for key in ("message", "my_chat_member", "channel_post", "edited_message"):
            ch = (u.get(key) or {}).get("chat")
            if ch and ch.get("type") in ("private", "group", "supergroup", "channel"):
                seen[ch["id"]] = {"id": ch["id"], "name": _chat_name(ch), "type": ch["type"]}
    if not seen:
        raise S.ApiError(409, "No chat found yet. In Telegram open @%s and press Start (or add it to your group and send a message), then click Find again." % me.get("username"))
    return {"bot": me.get("username"), "chats": list(seen.values())[::-1]}


def change_bot(body):
    """Check the new bot and chat with Telegram (test message), then switch. If any check fails, nothing changes."""
    _check_pw(body.get("password"))
    t = _tok_in(body)
    try:
        chat = int(str(body.get("chat_id") or "").strip())
    except ValueError:
        raise S.ApiError(400, "Enter the chat ID (a number, e.g. 123456789, or -100... for a group), or click Find my chat ID.")
    me = _call("getMe", tok=t)
    ch = _call("getChat", {"chat_id": chat}, tok=t) or {}
    _call("sendMessage", {"chat_id": chat, "text": "Tradeskill now sends to this bot ✅ (@%s)\nYou will get the messages switched on under "
                                                  "Limits → Telegram. This bot only sends messages; it cannot buy or sell." % me.get("username")}, tok=t)
    os.makedirs(S.DATA, exist_ok=True)
    tmp = _token_file() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(t)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, _token_file())
    with S._state_lock:
        st = S.load_state()
        c = _cfg(st)
        c.update(chat_id=chat, name=_chat_name(ch) if ch else str(chat), bot=me.get("username"),
                 bot_changed=S.now_ist().strftime("%Y-%m-%d %H:%M"), last_error=None)
        st["telegram"] = c
        S.save_state(st)
    out = status()
    out["message"] = "Switched to @%s. A test message was sent to %s." % (me.get("username"), out["name"])
    return out


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


def remove(kind, restore=False):
    """Delete a built-in message for good (it never sends and leaves the table), or bring it back."""
    if kind not in dict(KINDS):
        raise S.ApiError(400, "Unknown message.")
    with S._state_lock:
        st = S.load_state()
        c = _cfg(st)
        rm = [k for k in (c.get("removed") or []) if k != kind]
        if not restore:
            rm.append(kind)
        c["removed"] = rm
        c["on"][kind] = bool(restore)
        st["telegram"] = c
        S.save_state(st)
    out = status()
    out["message"] = ("Restored and switched on: %s." if restore else "Deleted: %s. It will not send again; restore it from the Deleted list.") % dict(KINDS)[kind]
    return out


def test():
    c = _cfg(S.load_state())
    if not c.get("chat_id"):
        raise S.ApiError(409, "Connect Telegram first.")
    _post(c["chat_id"], "Test message from Tradeskill 👍  (%s IST)" % S.market_clock()["ist"])
    return {"ok": True}


def _post(chat_id, text, markup=None):
    with _send_lock:   # Telegram allows about 1 message per second per chat
        p = {"chat_id": chat_id, "text": text[:4000], "disable_web_page_preview": "true"}
        if markup:
            p["reply_markup"] = json.dumps(markup)
        _call("sendMessage", p)
        time.sleep(1.05)


# ----------------------------------------------------------------- "once, then quiet until you tap" (owner's choice, 20 Nov 2026)
QUIET_KINDS = {"stopalert", "loss10", "trend", "lossnews", "move", "exits", "roombuys", "custom"}
_SYM_RE = re.compile(r"\b[A-Z][A-Z0-9&-]{1,19}\b")


def _norm(line):
    """A line without numbers, times and signs: the same kind of message gives the same text every time."""
    return re.sub(r"[\d.,:%₹+−-]+", "", line).strip()[:60]


def _quiet(kind, text, st):
    """Drop lines about stocks you were already told about (until you tap Allow again).
    Returns (text to send or None, keys to mute after sending)."""
    q = (st.get("telegram") or {}).get("quiet") or {}
    names = set(S.NAMES)
    try:   # your holdings too (some are outside the 250, e.g. ETFs)
        with LG._lock:
            snaps = LG._load().get("snapshots") or {}
        names |= {r.get("symbol") for r in (snaps[sorted(snaps)[-1]].get("holdings") or [])} if snaps else set()
    except Exception:  # noqa: BLE001
        pass
    lines = text.split("\n")
    head = _norm(lines[0])
    keep, keys, stock_lines = [], [], 0
    for i, ln in enumerate(lines):
        syms = [w for w in _SYM_RE.findall(ln) if w in names] if i else []
        if syms:
            stock_lines += 1
            k = "%s|%s|%s" % (kind, head, syms[0])
            if k in q:
                continue
            keys.append(k)
        keep.append(ln)
    if stock_lines == 0:   # a message about the market, not stocks: the whole message is one item
        k = "%s|%s" % (kind, head)
        return (None, []) if k in q else (text, [k])
    if not keys:
        return None, []
    return "\n".join(keep), keys


def unquiet(keys=None):
    """Allow muted alerts again: the given keys, or all of them."""
    with S._state_lock:
        st = S.load_state()
        c = _cfg(st)
        q = c.get("quiet") or {}
        n = 0
        for k in (list(q) if keys is None else keys):
            if q.pop(k, None) is not None:
                n += 1
        c["quiet"] = q
        st["telegram"] = c
        S.save_state(st)
    return n


def notify(kind, text):
    """Send a message in the background if Telegram is connected and this kind is switched on.
    Alerts (QUIET_KINDS) say each thing once, then stay quiet until you tap "Allow again".
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
        if kind in (c.get("removed") or []):
            return log("not sent: deleted")
        if not c["on"].get(kind, True):
            return log("not sent: switched off")
        keys, markup = [], None
        if kind in QUIET_KINDS and not text.startswith("🧪"):
            body, keys = _quiet(kind, text, S.load_state())
            if body is None:
                return log("not sent: already told (quiet until you tap Allow again)")
            gid = "%x" % (abs(hash((kind, tuple(keys), time.time()))) % (1 << 40))
            body += "\n🔕 Won't repeat until you tap Allow again."
            markup = {"inline_keyboard": [[{"text": "🔔 Allow again", "callback_data": "uq:" + gid}]]}
            with S._state_lock:
                st = S.load_state()
                cc = _cfg(st)
                q = cc.setdefault("quiet", {})
                now = S.market_clock()["ist"]
                for k in keys:
                    q[k] = now
                g = cc.setdefault("quiet_groups", {})
                g[gid] = keys
                for old in list(g)[:-300]:
                    g.pop(old, None)
                st["telegram"] = cc
                S.save_state(st)
            send_text = body
        else:
            send_text = text
    except Exception:  # noqa: BLE001
        return log("not sent: error")

    def run():
        err = None
        try:
            _post(c["chat_id"], send_text, markup)
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
            try:
                if C:
                    C.tick()                                        # your own notifications (runs in the background)
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            pass
        time.sleep(30)


def start():
    threading.Thread(target=watcher, name="tradeskill-watcher", daemon=True).start()
    threading.Thread(target=tap_watcher, name="alert-taps", daemon=True).start()


# ----------------------------------------------------------------- the alert bot reads ONLY its own "Allow again" taps
def tap_watcher():
    """Button taps on alert messages (🔔 Allow again). Text messages to the alert bot are skipped: chat lives in the chat bot."""
    off = None
    while True:
        c = _cfg(S.load_state())
        if not token() or not c.get("chat_id"):
            time.sleep(15)
            continue
        try:
            if off is None:   # start after anything already waiting
                last = _call("getUpdates", {"offset": -1, "timeout": 0}) or []
                off = last[-1]["update_id"] + 1 if last else 0
            upd = _call("getUpdates", {"offset": off, "timeout": 25, "allowed_updates": json.dumps(["callback_query"])}, timeout=40) or []
        except Exception:  # noqa: BLE001
            time.sleep(20)
            continue
        for u in upd:
            off = u["update_id"] + 1
            cq = u.get("callback_query") or {}
            msg = cq.get("message") or {}
            data = cq.get("data") or ""
            if (msg.get("chat") or {}).get("id") != c.get("chat_id") or not data.startswith("uq:"):
                continue
            keys = (c.get("quiet_groups") or {}).get(data[3:]) or []
            n = unquiet(keys)
            try:
                _call("answerCallbackQuery", {"callback_query_id": cq["id"], "text": "Allowed again: %d" % n})
                _call("editMessageText", {"chat_id": msg["chat"]["id"], "message_id": msg["message_id"],
                                          "text": (msg.get("text") or "").replace("🔕 Won't repeat until you tap Allow again.", "")
                                          + "🔔 Allowed again: it will message you the next time this happens."})
            except Exception:  # noqa: BLE001
                pass
