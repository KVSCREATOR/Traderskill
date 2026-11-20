"""Chat with your Tradeskill bot in Telegram: ask, and it answers from the portal's own data.

- Reads new messages by long polling (the NAS asks Telegram), so no port is opened and no public address is needed.
- Answers ONLY the chat set under Limits -> Telegram; every other chat is ignored.
- Commands (/today, /holdings, /stock HAL, /stops, /plan, /nifty, /vsnifty, /alerts, /messages, /lang) and
  plain words in English, Hindi or Hinglish. Words are matched first; when that fails and an AI service is set
  (ai.py), the AI only turns the question into one of these commands. Answers are built by portal code with
  exact numbers. With Hindi chosen, the AI translates the finished answer and the bot checks every number
  survived; otherwise the English answer is sent.
- Buttons can: mark stop GTTs done in Kite, tick Today items, switch notifications on/off. It never trades.
Owner's choices (20 Nov 2026): no PIN; Hindi answers by default; any AI provider via the settings box.
"""
import json
import re
import threading
import time

S = None    # server module
L = None    # longterm
T = None    # telegram
LG = None   # ledger
C = None    # custom notifications
R = None    # reports
AI = None   # ai connector

COMMANDS = [("today", "Today's checklist: exits, stops, limits"), ("holdings", "My holdings: value, today, best and worst"),
            ("stock", "One stock: /stock HAL"), ("stops", "Kite stop GTTs to set or raise"), ("plan", "What next: sells and buys"),
            ("nifty", "Nifty, VIX and the market filter"), ("vsnifty", "My return vs the Nifty"),
            ("alerts", "My own notifications (switch on/off)"), ("messages", "Built-in messages (switch on/off)"),
            ("lang", "Answer language: /lang hi or /lang en"), ("help", "What I can do")]
CMDS = {c for c, _ in COMMANDS}
WORDS = [  # plain words (English / Hindi / Hinglish) -> command; first match wins
    ("vsnifty", r"vs ?nifty|beat(ing)? (the )?nifty|my return|xirr|score"),
    ("stops", r"\bstops?\b|\bgtt|stop ?loss|स्टॉप"),
    ("plan", r"\bplan\b|what next|kya (karu|karun|kare)|sell|buy|बेच|खरीद|प्लान"),
    ("today", r"\btoday\b|checklist|\baaj\b|आज|to ?do"),
    ("holdings", r"holding|portfolio|\bp ?& ?l\b|\bpnl\b|profit|loss|munafa|nuksan|मेरा|पोर्टफोलियो|मुनाफ|नुकसान"),
    ("nifty", r"\bnifty\b|\bvix\b|market|bazaar|बाज़ार|बाजार|निफ्टी"),
    ("alerts", r"alert|notification|अलर्ट"),
    ("messages", r"messages|built.?in"),
    ("help", r"^(hi|hello|help|menu|start|namaste|नमस्ते)\b"),
]
_off = {"n": None}
_seen = {"today": []}
_sem = threading.BoundedSemaphore(2)
_status = {"started": None, "last_in": None, "last_error": None, "ignored": 0}


# ----------------------------------------------------------------- settings
def _tg():
    return S.load_state().get("telegram") or {}


def enabled():
    tg = _tg()
    return bool(tg.get("bot_on") and tg.get("chat_id") and T.token())


def lang():
    return _tg().get("bot_lang") or "hi"


def status():
    tg = _tg()
    return {"on": bool(tg.get("bot_on")), "lang": tg.get("bot_lang") or "hi", "chat": tg.get("name"), "connected": bool(tg.get("chat_id")),
            "running": bool(_status["started"]), "last_in": _status["last_in"], "last_error": _status["last_error"],
            "ignored": _status["ignored"], "ai": AI.status(), "commands": COMMANDS}


def set_settings(body):
    with S._state_lock:
        st = S.load_state()
        tg = st.setdefault("telegram", {})
        if "on" in body:
            tg["bot_on"] = bool(body["on"])
        if body.get("lang") in ("en", "hi"):
            tg["bot_lang"] = body["lang"]
        S.save_state(st)
    if body.get("on"):
        try:   # the menu shown when you type "/" in the chat
            T._call("setMyCommands", {"commands": json.dumps([{"command": c, "description": d} for c, d in COMMANDS])})
        except Exception:  # noqa: BLE001
            pass
    out = status()
    out["message"] = ("The bot now answers your messages." if out["on"] else "The bot no longer answers messages (alerts still come).") \
        if "on" in body else "Answer language: %s." % ("Hindi" if out["lang"] == "hi" else "English")
    return out


# ----------------------------------------------------------------- reading messages
def start():
    threading.Thread(target=_poll, name="tg-bot", daemon=True).start()


def _poll():
    _status["started"] = time.strftime("%Y-%m-%d %H:%M")
    while True:
        if not enabled():
            time.sleep(10)
            continue
        try:
            if _off["n"] is None:
                _off["n"] = _tg().get("bot_offset")
            params = {"timeout": 25, "allowed_updates": json.dumps(["message", "callback_query"])}
            if _off["n"]:
                params["offset"] = _off["n"]
            upd = T._call("getUpdates", params, timeout=40) or []
        except Exception as e:  # noqa: BLE001  (Telegram down, another reader, token changed)
            _status["last_error"] = "%s · %s" % (time.strftime("%H:%M"), str(e)[:150])
            time.sleep(30 if "onflict" in str(e) else 15)
            continue
        for u in upd:
            _off["n"] = u["update_id"] + 1
            threading.Thread(target=_handle_safe, args=(u,), daemon=True).start()
        if upd:
            with S._state_lock:
                st = S.load_state()
                st.setdefault("telegram", {})["bot_offset"] = _off["n"]
                S.save_state(st)


def _handle_safe(u):
    with _sem:
        try:
            handle(u)
        except Exception as e:  # noqa: BLE001
            _status["last_error"] = "%s · %s" % (time.strftime("%H:%M"), str(e)[:150])
            try:
                chat = ((u.get("message") or (u.get("callback_query") or {}).get("message") or {}).get("chat") or {}).get("id")
                if chat == _tg().get("chat_id"):
                    _send(chat, "Sorry, that failed: %s" % str(e)[:200])
            except Exception:  # noqa: BLE001
                pass


def handle(u):
    my_chat = _tg().get("chat_id")
    cq = u.get("callback_query")
    msg = u.get("message") or (cq or {}).get("message") or {}
    chat = (msg.get("chat") or {}).get("id")
    if not my_chat or chat != my_chat:   # only your chat; everyone else is ignored
        _status["ignored"] += 1
        return
    _status["last_in"] = S.now_ist().strftime("%d %b %H:%M")
    if cq:
        try:
            T._call("answerCallbackQuery", {"callback_query_id": cq["id"]})
        except Exception:  # noqa: BLE001
            pass
        return _button(chat, cq.get("data") or "")
    text = (msg.get("text") or "").strip()
    if not text:
        return _send(chat, "Send a question or a command, e.g. /today or /stock HAL.")
    cmd, arg, how = understand(text)
    answer, kb = run(cmd, arg)
    _reply(chat, answer, kb, how, text)


# ----------------------------------------------------------------- understanding a message
def _symbol_in(text):
    """An NSE symbol or a company name in the text. Your holdings match in any case; other symbols only when
    typed in CAPITALS (so words like "idea" or "bel" are not taken as stocks); a company name's first word only
    when no other company shares it."""
    held = set(C._holdings())
    for w in re.findall(r"[A-Za-z&-]{2,20}", text):
        u = w.upper()
        if u in held or (w.isupper() and u in S.NAMES):
            return u
    low = text.lower()
    firsts = {}
    for sym, name in S.NAMES.items():
        f = (name or "").lower().split()[0] if name else ""
        if len(f) >= 4:
            firsts.setdefault(f, []).append(sym)
    for f, syms in firsts.items():
        if len(syms) == 1 and re.search(r"\b%s\b" % re.escape(f), low):
            return syms[0]
    return None


def understand(text):
    """-> (command, argument, how it was understood)."""
    t = text.strip()
    if t.startswith("/"):
        parts = t[1:].split(None, 1)
        cmd = parts[0].split("@")[0].lower() if parts else "help"
        arg = parts[1].strip() if len(parts) > 1 else ""
        if cmd == "start":
            cmd = "help"
        return (cmd if cmd in CMDS else "help"), arg, "command"
    low = t.lower()
    m = re.match(r"^(lang|language|bhasha|भाषा)\s+(hindi|hi|english|en|हिंदी)", low)
    if m:
        return "lang", "hi" if m.group(2) in ("hindi", "hi", "हिंदी") else "en", "words"
    sym = _symbol_in(t)
    cmd = next((c for c, rx in WORDS if re.search(rx, low)), None)
    if sym and cmd in (None, "holdings", "plan", "today", "help"):   # "should I buy HAL", "how did TVSMOTOR do today"
        return "stock", sym, "words"
    if cmd:
        return cmd, "", "words"
    if AI.configured():
        try:
            return _ai_intent(t)
        except Exception as e:  # noqa: BLE001
            return "help", "", "AI failed (%s), showing the menu" % str(e)[:80]
    return "help", "", "not understood"


def _ai_intent(text):
    system = ("You route messages for a private Indian stock-portfolio assistant bot. Reply with ONLY a JSON object "
              '{"cmd": one of ' + json.dumps(sorted(CMDS)) + ', "symbol": NSE symbol in capitals or "", "lang": "hi" or "en" or ""}. '
              "today = daily checklist; holdings = my portfolio value, profit/loss, today's change; stock = one company "
              "(give its NSE symbol, e.g. Hindustan Aeronautics -> HAL, State Bank -> SBIN); stops = stop-loss GTT levels; "
              "plan = what to sell or buy next; nifty = market, index, VIX; vsnifty = my return compared with Nifty; "
              "alerts = my notifications; messages = built-in messages; lang = change answer language; help = anything else. "
              "The message may be English, Hindi or Hinglish.")
    out = AI.ask(system, text[:500], max_tokens=80)
    m = re.search(r"\{.*\}", out, re.S)
    j = json.loads(m.group(0)) if m else {}
    cmd = j.get("cmd") if j.get("cmd") in CMDS else "help"
    sym = S.clean_symbol(j.get("symbol") or "") if j.get("symbol") else ""
    if cmd == "lang":
        return "lang", j.get("lang") or "", "AI"
    if cmd == "stock" and not sym:
        cmd = "help"
    return cmd, sym, "AI"


# ----------------------------------------------------------------- answers (English, exact numbers from the portal)
def _rs(v):
    return ("−" if v < 0 else "") + "₹" + format(int(round(abs(v))), ",")


def _px(v):
    return "₹" + format(v, ",.2f") if v is not None else "–"


def _btn(*rows):
    return {"inline_keyboard": [[{"text": t, "callback_data": d[:64]} for t, d in row] for row in rows if row]}


MENU = _btn([("📋 Today", "cmd:today"), ("💼 Holdings", "cmd:holdings"), ("🛡 Stops", "cmd:stops")],
            [("🧭 Plan", "cmd:plan"), ("📈 Nifty", "cmd:nifty"), ("🏁 vs Nifty", "cmd:vsnifty")])


def run(cmd, arg=""):
    fn = {"help": a_help, "today": a_today, "holdings": a_holdings, "stock": a_stock, "stops": a_stops, "plan": a_plan,
          "nifty": a_nifty, "vsnifty": a_vsnifty, "alerts": a_alerts, "messages": a_messages, "lang": a_lang}.get(cmd, a_help)
    return fn(arg)


def a_help(_=""):
    return ("🤖 Ask me about your portfolio. Tap a button or type, e.g. \"how are my holdings?\", \"HAL\", \"aaj kya karna hai\".\n\n"
            + "\n".join("/%s · %s" % (c, d) for c, d in COMMANDS)
            + "\n\nRead-only: I never buy or sell. Rule results, not personal advice."), MENU


def a_today(_=""):
    t = LG.today("invest")
    items = [x for x in t["items"] if x["group"] in ("act", "watch", "tomorrow")]
    _seen["today"] = [x["id"] for x in items]
    icon = {"act": "🔴", "watch": "🟡", "tomorrow": "🟢"}
    lines = ["📋 Today · %d to act, %d to watch, %d for tomorrow" % (t["counts"]["act"], t["counts"]["watch"], t["counts"]["tomorrow"])]
    lines += ["%s %d. %s%s" % (icon[x["group"]], i + 1, x["text"], " ✓" if x.get("done") else "") for i, x in enumerate(items[:15])]
    if not items:
        lines.append("✅ Nothing to act on.")
    rows = [[("✓ %d" % (i + 1), "t:%d" % i) for i in range(k, min(k + 5, len(items[:15]))) if not items[i].get("done")] for k in range(0, len(items[:15]), 5)]
    return "\n".join(lines), _btn(*rows, [("🛡 Stops", "cmd:stops"), ("🧭 Plan", "cmd:plan")])


def a_holdings(_=""):
    hold = list(C._holdings().values())
    if not hold:
        return "No holdings snapshot yet: open My holdings once with Zerodha connected.", MENU
    tv = sum(h["value"] for h in hold)
    dp = sum(h["day_pnl"] or 0 for h in hold)
    pn = sum(h["pnl"] or 0 for h in hold)
    cost = sum((h["avg"] or 0) * h["qty"] for h in hold)
    hold.sort(key=lambda h: -(h["day_pnl"] or 0))
    lines = ["💼 My holdings · %d stocks · %s" % (len(hold), _rs(tv)),
             "Today %s (%+.2f%%) · Total %s (%+.1f%%)" % (_rs(dp), dp / (tv - dp) * 100 if tv - dp else 0, _rs(pn), pn / cost * 100 if cost else 0)]
    up = [h for h in hold if (h["day_pnl"] or 0) > 0][:4]
    dn = [h for h in hold[::-1] if (h["day_pnl"] or 0) < 0][:4]
    if up:
        lines.append("🟢 " + " · ".join("%s %s (%+.1f%%)" % (h["symbol"], _rs(h["day_pnl"]), h["day_pct"] or 0) for h in up))
    if dn:
        lines.append("🔴 " + " · ".join("%s %s (%+.1f%%)" % (h["symbol"], _rs(h["day_pnl"]), h["day_pct"] or 0) for h in dn))
    worst = sorted(hold, key=lambda h: h["pnl_pct"] if h["pnl_pct"] is not None else 0)[:3]
    lines.append("Biggest total losses: " + ", ".join("%s %+.1f%%" % (h["symbol"], h["pnl_pct"] or 0) for h in worst))
    lines.append("Prices: latest available (delayed); quantities from your last Zerodha snapshot.")
    return "\n".join(lines), _btn([("📋 Today", "cmd:today"), ("🛡 Stops", "cmd:stops"), ("🏁 vs Nifty", "cmd:vsnifty")])


def a_stock(arg=""):
    sym = S.clean_symbol(arg or "")
    if not sym:
        return "Which stock? Send e.g. /stock HAL or just HAL.", MENU
    p = L.analyze(sym, "invest")
    lines = ["📊 %s · %s" % (sym, p.get("name") or ""),
             "%s (%+.2f%% today) · score %s/100 · %s" % (_px(p.get("price")), p.get("change_pct") or 0, p.get("score"), p.get("verdict") or "")]
    if p.get("why"):
        lines.append(str(p["why"])[:300])
    pl = p.get("plan") or {}
    if pl.get("entry"):
        lines.append("Rule plan: entry %s · stop %s%s" % (_px(pl.get("entry")), _px(pl.get("stop")),
                                                        " · qty %s" % (p.get("size") or {}).get("qty") if (p.get("size") or {}).get("qty") else ""))
    h = C._holdings().get(sym)
    if h:
        lines.append("You hold %g @ %s · %s (%+.1f%%) · today %s" % (h["qty"], _px(h["avg"]), _rs(h["pnl"] or 0), h["pnl_pct"] or 0, _rs(h["day_pnl"] or 0)))
        if h.get("stop"):
            lines.append("Rule stop %s (%.1f%% below the price)" % (_px(h["stop"]), (1 - h["stop"] / h["price"]) * 100))
    lines.append("Investing rules · screening, not advice.")
    return "\n".join(lines), _btn([("💼 Holdings", "cmd:holdings"), ("🛡 Stops", "cmd:stops")])


def a_stops(_=""):
    s = LG.stops()
    todo = [x for x in s["rows"] if x["status"] in ("new", "raise", "qty")]
    hit = [x for x in s["rows"] if x["status"] == "hit"]
    lines = ["🛡 Kite stop GTTs · %d to set or change · %d OK" % (len(todo), s["counts"].get("ok", 0))]
    word = {"new": "SET", "raise": "RAISE", "qty": "QTY"}
    lines += ["%s %s: sell %g · trigger %s · limit %s%s" % (word[x["status"]], x["symbol"], x["qty"], _px(x["trigger"]), _px(x["limit"]),
                                                        " (was %s)" % _px(x["kite"]) if x["status"] == "raise" else "") for x in todo[:12]]
    if hit:
        lines.append("🔴 Exit fired (price at/below stop): " + ", ".join(x["symbol"] for x in hit))
    if not todo:
        lines.append("✅ Every stop is set.")
    rows = [[("✓ %s" % x["symbol"], "sd:%s" % x["symbol"]) for x in todo[k:k + 3]] for k in range(0, min(len(todo), 12), 3)]
    if len(todo) > 1:
        rows.append([("✓ All %d done in Kite" % len(todo), "sd:*")])
    return "\n".join(lines), _btn(*rows)


def a_plan(_=""):
    p = ((LG.report() or {}).get("next") or {}).get("plan")
    if not p or p.get("stale"):
        return "No plan yet: open My holdings once with Zerodha connected.", MENU
    lines = ["🧭 %s plan · Investing rules · stocks %d now (limit %d)" % (p["horizon"], p["before"]["holdings"], p["after"]["max"])]
    cb = p.get("core_buy")
    if cb and cb.get("amount"):
        lines.append("🔵 Nifty core first: buy about %s of %s (core → about %.0f%% of %d%%)" % (_rs(cb["amount"]), cb["fund"], cb.get("pct_after") or 0, cb["target"]))
    if p["sells"]:
        lines.append("🔴 Sell:")
        lines += ["  %s %s · %s" % ("all" if s["all"] else "%g" % s["qty"], s["symbol"], s["reason"]) for s in p["sells"][:12]]
    if p["buys"]:
        lines.append("🟢 Buy:")
        lines += ["  %d %s at %s · about %s" % (b["qty"], b["symbol"], _px(b["price"]), _rs(b["amount"])) for b in p["buys"]]
    if p.get("waiting"):
        lines.append("Next in line: " + ", ".join(w["symbol"] for w in p["waiting"]))
    lines.append("Rule results, not personal advice.")
    return "\n".join(lines), _btn([("📋 Today", "cmd:today"), ("💼 Holdings", "cmd:holdings")])


def a_nifty(_=""):
    _, by = R._quotes()
    lines = ["📈 Market"]
    for name in ("NIFTY 50", "BANK NIFTY", "INDIA VIX"):
        q = by.get(name)
        if q and q.get("price"):
            lines.append("%s %s (%+.2f%%)" % (name, format(q["price"], ",.2f"), q.get("pct") or 0))
    try:
        mkt = L.market()
        d = mkt.ind["d"][-1]
        lines.append("Investing market filter: %s" % ("ON, new buys allowed" if mkt.regime(d, "invest") else "OFF, rules hold off new buys"))
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(lines), MENU


def a_vsnifty(_=""):
    r = LG.vs_nifty()
    if not r.get("ok"):
        return r.get("message") or "Not enough records yet.", MENU
    lines = ["🏁 You vs Nifty · %s to %s (%d days)" % (r["from"], r["to"], r["days"]),
             "Your stocks: %s profit · %s a year" % (_rs(r["profit"]), "%+.1f%%" % r["xirr"] if r["xirr"] is not None else "–"),
             "Same money in Nifty 50: %s · %s a year" % (_rs(r["nifty_profit"]), "%+.1f%%" % r["nifty_xirr"] if r["nifty_xirr"] is not None else "–")]
    if r.get("short"):
        lines.append("Under a year of records: judge after 12 months.")
    return "\n".join(lines), MENU


def a_alerts(_=""):
    d = C.listing()
    if not d["rules"]:
        return "No own notifications yet. Add them on the portal: Limits → Telegram → + New notification.", MENU
    lines = ["🔔 My notifications (tap to switch)"]
    lines += ["%s %s" % ("🟢" if r["on"] else "⚪", r["name"]) for r in d["rules"][:20]]
    rows = [[("%s %s" % ("⏸" if r["on"] else "▶", r["name"][:20]), "cn:%s:%d" % (r["id"], 0 if r["on"] else 1))] for r in d["rules"][:20]]
    return "\n".join(lines), _btn(*rows)


def a_messages(_=""):
    st = T.status()
    gone = set(st.get("removed") or [])
    kinds = [(k, l) for k, l in st["kinds"] if k not in gone]
    lines = ["📨 Built-in messages (tap to switch)"] + ["%s %s" % ("🟢" if st["on"].get(k) else "⚪", l) for k, l in kinds]
    rows = [[("%s %s" % ("⏸" if st["on"].get(k) else "▶", l[:24]), "tg:%s:%d" % (k, 0 if st["on"].get(k) else 1))] for k, l in kinds]
    return "\n".join(lines), _btn(*rows)


def a_lang(arg=""):
    a = (arg or "").lower()
    if a not in ("hi", "en"):
        return "Answer language now: %s. Send /lang hi for Hindi or /lang en for English." % ("Hindi" if lang() == "hi" else "English"), None
    set_settings({"lang": a})
    note = "" if a == "en" or AI.configured() else " (Hindi needs an AI service set on the portal; until then answers stay English.)"
    return "Answer language: %s.%s" % ("Hindi" if a == "hi" else "English", note), MENU


# ----------------------------------------------------------------- buttons
def _button(chat, data):
    if data.startswith("cmd:"):
        answer, kb = run(data[4:])
    elif data.startswith("t:"):
        ids = _seen.get("today") or []
        i = int(data[2:]) if data[2:].isdigit() else -1
        if 0 <= i < len(ids):
            LG.today_done({"id": ids[i], "done": True})
        answer, kb = a_today()
        answer = "✓ Ticked item %d.\n\n%s" % (i + 1, answer)
    elif data.startswith("sd:"):
        sym = data[3:]
        if sym == "*":
            todo = [x["symbol"] for x in LG.stops()["rows"] if x["status"] in ("new", "raise", "qty")]
            res = LG.stops_done({"symbols": todo})
        else:
            res = LG.stops_done({"symbols": [sym]})
        answer, kb = a_stops()
        answer = "✓ %s\n\n%s" % (res.get("message"), answer)
    elif data.startswith("cn:"):
        _, rid, on = data.split(":")
        res = C.save({"action": "toggle", "id": rid, "on": on == "1"})
        answer, kb = a_alerts()
        answer = "✓ %s\n\n%s" % (res.get("message"), answer)
    elif data.startswith("tg:"):
        _, kind, on = data.split(":")
        T.set_on({kind: on == "1"})
        answer, kb = a_messages()
        answer = "✓ Switched %s.\n\n%s" % ("on" if on == "1" else "off", answer)
    else:
        answer, kb = a_help()
    _reply(chat, answer, kb, "button", data)


# ----------------------------------------------------------------- sending (with optional Hindi)
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text):
    return sorted(n.replace(",", "") for n in _NUM.findall(text))


def to_hindi(text):
    """AI translation; refused (English kept) when any number changed."""
    out = AI.ask("Translate the user's message into simple Hindi (Devanagari script). Keep every number, ₹ amount, %, "
                 "+/− sign, date, time, NSE stock symbol, emoji, slash command and line break exactly as written, using "
                 "Western digits 0-9. Do not add, remove or explain anything. Output only the translation.", text, max_tokens=1500)
    if not out or _numbers(out) != _numbers(text):
        raise ValueError("a number changed in translation")
    return out


def _reply(chat, text, kb, how, question):
    note = ""
    if lang() == "hi" and AI.configured():
        try:
            text = to_hindi(text)
        except Exception as e:  # noqa: BLE001
            note = "\n(Hindi skipped: %s)" % str(e)[:80]
    if how not in ("command", "words", "button", "AI"):
        note += "\n(%s)" % how
    _send(chat, text + note, kb)
    try:
        R.log("bot", "Q: %s\nA: %s" % (question[:200], text.split("\n")[0][:200]), "sent")
    except Exception:  # noqa: BLE001
        pass


def _send(chat, text, kb=None):
    params = {"chat_id": chat, "text": text[:4000], "disable_web_page_preview": "true"}
    if kb:
        params["reply_markup"] = json.dumps(kb)
    with T._send_lock:
        T._call("sendMessage", params)
