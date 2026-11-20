"""Chat with your Tradeskill bot in Telegram: see and control the portal from the chat.

- Reads new messages by long polling (the NAS asks Telegram): no open port, no public address.
- Answers ONLY the chat set under Limits -> Telegram; every other chat is ignored. Messages sent before the
  bot was switched on are skipped (no burst of old replies).
- A permanent menu at the bottom of the chat; buttons under answers update the SAME message in place.
- See: today, holdings, a stock, stops, plan, market, news, vs Nifty, tax, core split, sectors, results,
  long-term dates, limits, lists, signals, scanner, paper account, reports on demand, Zerodha login link.
- Control (all through the portal's own API, the same checks as the website): mark stops done, tick Today,
  core target, limits (with confirm), price alerts, own notifications, built-in messages, muted alerts,
  My scanner lists, paper buy / close / GTT cancel (simulated money only, with confirm), answer language,
  rules for stock answers, restart the portal (with confirm). It NEVER places a real order in Zerodha.
- Words in English / Hindi / Hinglish are matched first; when that fails and an AI service is set (ai.py),
  the AI only turns the question into a command. Answers are built by portal code with exact numbers; for
  Hindi the AI translates the finished answer and the bot checks every number survived.
Owner's choices (20 Nov 2026): no PIN; Hindi by default; any AI provider; alerts once then quiet until tapped.
"""
import json
import os
import re
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor

S = None    # server module
L = None    # longterm
T = None    # telegram
LG = None   # ledger
C = None    # custom notifications
R = None    # reports
AI = None   # ai connector
ML = None   # mylist
G = None    # gtt (paper GTT orders)
D = None    # daily (login link)
H = None    # history (action log)

COMMANDS = [("menu", "Show the menu"), ("today", "Today's checklist"), ("holdings", "My holdings"), ("stock", "One stock: /stock HAL"),
            ("stops", "Kite stop GTTs"), ("plan", "What next: sells and buys"), ("nifty", "Market: Nifty, VIX, filter"),
            ("news", "News for my holdings (or /news HAL)"), ("alerts", "Alerts and notifications"), ("scanner", "Lists, signals, scanner"),
            ("paper", "Paper trading"), ("tax", "Tax and tax-free gains"), ("reports", "Reports on demand"),
            ("settings", "Settings, Zerodha login, portal"), ("vsnifty", "My return vs the Nifty"), ("lang", "Language: /lang hi or /lang en"),
            ("help", "What I can do")]
CMDS = {c for c, _ in COMMANDS} | {"more", "core", "sectors", "results", "longterm", "limits", "lists", "signals", "top", "quiet",
                                   "pricealerts", "notes", "messages", "login", "status", "gtts", "rules", "restart", "holdmenu"}
BOTTOM = [["📋 Today", "💼 Holdings", "🛡 Stops"], ["🧭 Plan", "📈 Market", "📰 News"], ["🔔 Alerts", "📊 Scanner", "☰ More"]]
BOTTOM_CMD = {"📋 Today": "today", "💼 Holdings": "holdings", "🛡 Stops": "stops", "🧭 Plan": "plan", "📈 Market": "nifty",
              "📰 News": "news", "🔔 Alerts": "alerts", "📊 Scanner": "scanner", "☰ More": "more"}
WORDS = [  # plain words (English / Hindi / Hinglish) -> command; first match wins
    ("vsnifty", r"vs ?nifty|beat(ing)? (the )?nifty|my return|xirr|score"),
    ("stops", r"\bstops?\b|\bgtt|stop ?loss|स्टॉप"),
    ("tax", r"\btax\b|harvest|ltcg|stcg|टैक्स"),
    ("news", r"\bnews\b|khabar|खबर|headline"),
    ("paper", r"\bpaper\b"),
    ("reports", r"\breports?\b|summary|outlook"),
    ("settings", r"setting|login|zerodha|restart|link"),
    ("scanner", r"scanner|signal|my ?list|watch ?list|breakout"),
    ("plan", r"\bplan\b|what next|kya (karu|karun|kare)|sell|buy|बेच|खरीद|प्लान"),
    ("today", r"\btoday\b|checklist|\baaj\b|आज|to ?do"),
    ("holdings", r"holding|portfolio|\bp ?& ?l\b|\bpnl\b|profit|loss|munafa|nuksan|मेरा|पोर्टफोलियो|मुनाफ|नुकसान"),
    ("nifty", r"\bnifty\b|\bvix\b|market|bazaar|बाज़ार|बाजार|निफ्टी"),
    ("alerts", r"alert|notification|अलर्ट|quiet|mute"),
    ("help", r"^(hi|hello|help|menu|start|namaste|नमस्ते)\b"),
]
_off = {"n": None}
_seen = {"today": []}
_pending = {}                 # confirm tokens -> (text, function, made)
_sem = threading.BoundedSemaphore(2)
_lock_send = threading.Lock()
_ctx = threading.local()
_ctx.role = "full"


def _remember(chat, text):
    """Chats that wrote to the bot but are not allowed (last 20), to add them from the Limits page."""
    if not chat.get("id"):
        return
    name = (chat.get("title") or ("%s %s" % (chat.get("first_name", ""), chat.get("last_name", ""))).strip() or chat.get("username") or str(chat["id"]))
    with S._state_lock:
        st = S.load_state()
        cb = st.setdefault("chatbot", {})
        seen = [x for x in cb.get("seen") or [] if x["id"] != chat["id"]]
        seen.append({"id": chat["id"], "name": name, "text": text, "at": S.now_ist().strftime("%d %b %H:%M")})
        cb["seen"] = seen[-20:]
        S.save_state(st)
_status = {"started": None, "last_in": None, "last_error": None, "ignored": 0, "skipped_old": 0}


# ----------------------------------------------------------------- settings (the chat bot is a SEPARATE bot from the alert bot)
_lock = threading.Lock()


def _token_file():
    return os.path.join(S.DATA, "chatbot_token.txt")


def token():
    try:
        with open(_token_file(), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _call(method, params=None, timeout=20):
    """Telegram API with the CHAT bot's own token (alerts use the other bot)."""
    tok = token()
    if not tok:
        raise S.ApiError(409, "No chat bot set yet (Limits -> Telegram -> Chat bot).")
    return T._call(method, params, timeout, tok=tok)


def _tg():
    return S.load_state().get("telegram") or {}


def _cb():
    return S.load_state().get("chatbot") or {}


def people():
    """Who may use the chat bot. Default: you (the alert bot's chat), with full control."""
    ppl = _cb().get("people") or []
    if not ppl and _tg().get("chat_id"):
        ppl = [{"id": _tg()["chat_id"], "name": _tg().get("name") or "Me", "role": "full", "owner": True}]
    return ppl


def _person(chat):
    return next((x for x in people() if x["id"] == chat), None)


def enabled():
    return bool(_cb().get("on") and token() and people())


def lang():
    return _cb().get("lang") or "hi"


def rules():
    return _cb().get("rules") or "invest"


def status():
    cb = _cb()
    return {"on": bool(cb.get("on")), "lang": cb.get("lang") or "hi", "token_set": bool(token()), "token_tail": token()[-4:] if token() else None,
            "bot": cb.get("bot"), "people": people(), "seen": (cb.get("seen") or [])[-10:][::-1],
            "running": bool(_status["started"]), "last_in": _status["last_in"], "last_error": _status["last_error"],
            "ignored": _status["ignored"], "skipped_old": _status["skipped_old"], "muted": len(_tg().get("quiet") or {}),
            "ai": AI.status(), "commands": COMMANDS, "alert_bot": _tg().get("bot")}


def _set(**kw):
    with S._state_lock:
        st = S.load_state()
        cb = st.setdefault("chatbot", {})
        cb.update(kw)
        S.save_state(st)


def set_settings(body):
    turning_on = bool(body.get("on")) and not _cb().get("on")
    if turning_on and not token():
        raise S.ApiError(409, "Set up the chat bot first (its token), then switch it on.")
    upd = {}
    if "on" in body:
        upd["on"] = bool(body["on"])
    if body.get("lang") in ("en", "hi"):
        upd["lang"] = body["lang"]
    if turning_on:
        upd["since"] = int(time.time())   # older messages waiting in Telegram are skipped
        upd["offset"] = _latest_offset()
        _off["n"] = upd["offset"]
    _set(**upd)
    if turning_on:
        try:
            _call("setMyCommands", {"commands": json.dumps([{"command": c, "description": d} for c, d in COMMANDS])})
        except Exception:  # noqa: BLE001
            pass
        _retire_alert_bot_menu()
        for x in people():
            try:
                _send(x["id"], "🤖 Tradeskill chat bot is on. Use the menu below, or type a question (e.g. \"HAL\", \"aaj kya karna hai\")."
                      + ("" if x.get("role") == "full" else "\nYou have view-only access."), _bottom())
            except Exception:  # noqa: BLE001
                pass
    out = status()
    out["message"] = ("The chat bot now answers; the menu was sent to it." if out["on"] else
                      "The chat bot no longer answers messages (alerts still come from the alert bot).") if "on" in body else \
        "Answer language: %s." % ("Hindi" if out["lang"] == "hi" else "English")
    return out


def _retire_alert_bot_menu():
    """The alert bot used to carry the menu: remove its command list and bottom keyboard (once)."""
    if _cb().get("alert_menu_removed"):
        return
    try:
        T._call("deleteMyCommands", {})
        if _tg().get("chat_id"):
            T._call("sendMessage", {"chat_id": _tg()["chat_id"], "text": "ℹ️ This bot now only sends alerts. Chat and control moved to @%s." % (_cb().get("bot") or "your chat bot"),
                                    "reply_markup": json.dumps({"remove_keyboard": True})})
        _set(alert_menu_removed=True)
    except Exception:  # noqa: BLE001
        pass


def _latest_offset():
    """The offset just after the newest waiting message, so nothing old gets answered."""
    try:
        upd = _call("getUpdates", {"offset": -1, "timeout": 0}) or []
        return upd[-1]["update_id"] + 1 if upd else None
    except Exception:  # noqa: BLE001
        return None


def set_token(body):
    """Check a NEW bot for chat (Telegram getMe + a test message to you), then save its token. Portal password needed."""
    T._check_pw(body.get("password"))
    t = T._tok_in(body)
    if t == T.token():
        raise S.ApiError(400, "That is your alert bot. Create a second bot in @BotFather for chat, so alerts and chat stay apart.")
    me = T._call("getMe", tok=t)
    owner = people()[0]["id"] if people() else _tg().get("chat_id")
    if not owner:
        raise S.ApiError(409, "Connect the alert bot first (it knows your chat ID).")
    try:
        T._call("sendMessage", {"chat_id": owner, "text": "✅ This is your Tradeskill chat bot (@%s). Switch it on under Limits → Telegram → Chat bot." % me.get("username")}, tok=t)
    except S.ApiError as e:
        raise S.ApiError(409, "Open @%s in Telegram and press Start first, then try again. (%s)" % (me.get("username"), str(e)[:80]))
    os.makedirs(S.DATA, exist_ok=True)
    tmp = _token_file() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(t)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, _token_file())
    _set(bot=me.get("username"), offset=None, since=int(time.time()))
    _off["n"] = None
    out = status()
    out["message"] = "Chat bot set: @%s. A test message was sent to you there. Now switch it on." % me.get("username")
    return out


def set_people(body):
    """Add / remove a person or change their access (full control or view only). Adding needs the portal password."""
    act = body.get("action")
    with _lock:
        ppl = people()
        try:
            cid = int(str(body.get("id") or "").strip())
        except ValueError:
            raise S.ApiError(400, "Chat ID must be a number (pick from 'People who messaged the bot', or ask them to send /myid).")
        cur = next((x for x in ppl if x["id"] == cid), None)
        if act == "add":
            T._check_pw(body.get("password"))
            if cur:
                raise S.ApiError(400, "Already allowed.")
            seen = next((x for x in _cb().get("seen") or [] if x["id"] == cid), {})
            ppl.append({"id": cid, "name": str(body.get("name") or seen.get("name") or cid)[:40], "role": "view" if body.get("role") == "view" else "full"})
            msg = "Added %s (%s)." % (ppl[-1]["name"], "view only" if ppl[-1]["role"] == "view" else "full control")
        elif act == "role":
            if not cur:
                raise S.ApiError(404, "Not in the list.")
            if cur.get("owner"):
                raise S.ApiError(400, "You (the owner) always have full control.")
            cur["role"] = "view" if body.get("role") == "view" else "full"
            msg = "%s now has %s." % (cur["name"], "view-only access" if cur["role"] == "view" else "full control")
        elif act == "remove":
            if not cur:
                raise S.ApiError(404, "Not in the list.")
            if cur.get("owner"):
                raise S.ApiError(400, "You (the owner) can't be removed.")
            ppl.remove(cur)
            msg = "Removed %s." % cur["name"]
        else:
            raise S.ApiError(400, "Unknown action.")
        _set(people=ppl)
    out = status()
    out["message"] = msg
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
                _off["n"] = _cb().get("offset")
            params = {"timeout": 25, "allowed_updates": json.dumps(["message", "callback_query"])}
            if _off["n"]:
                params["offset"] = _off["n"]
            upd = _call("getUpdates", params, timeout=40) or []
        except Exception as e:  # noqa: BLE001  (Telegram down, another reader, token changed)
            _status["last_error"] = "%s · %s" % (time.strftime("%H:%M"), str(e)[:150])
            time.sleep(30 if "onflict" in str(e) else 15)
            continue
        for u in upd:
            _off["n"] = u["update_id"] + 1
            threading.Thread(target=_handle_safe, args=(u,), daemon=True).start()
        if upd:
            _set(offset=_off["n"])


def _handle_safe(u):
    with _sem:
        try:
            handle(u)
        except Exception as e:  # noqa: BLE001
            _status["last_error"] = "%s · %s" % (time.strftime("%H:%M"), str(e)[:150])
            try:
                chat = ((u.get("message") or (u.get("callback_query") or {}).get("message") or {}).get("chat") or {}).get("id")
                if _person(chat):
                    _send(chat, "Sorry, that failed: %s" % str(e)[:200])
            except Exception:  # noqa: BLE001
                pass


def handle(u):
    cb = _cb()
    cq = u.get("callback_query")
    msg = u.get("message") or (cq or {}).get("message") or {}
    chat = (msg.get("chat") or {}).get("id")
    who = _person(chat)
    if not who:   # not in your people list: ignored, but remembered so you can add them on the Limits page
        _status["ignored"] += 1
        _remember(msg.get("chat") or {}, (msg.get("text") or "")[:60])
        if (msg.get("text") or "").strip().lower() in ("/myid", "/start", "myid"):
            try:
                _send(chat, "This is a private bot. Your chat ID is %s: send it to the owner if you should have access." % chat)
            except Exception:  # noqa: BLE001
                pass
        return
    _ctx.role = who.get("role") or "full"
    if not cq and (msg.get("date") or 0) < (cb.get("since") or 0) - 5:   # written before the bot was switched on
        _status["skipped_old"] += 1
        return
    _status["last_in"] = S.now_ist().strftime("%d %b %H:%M")
    if cq:
        try:
            _call("answerCallbackQuery", {"callback_query_id": cq["id"]})
        except Exception:  # noqa: BLE001
            pass
        return _button(chat, msg.get("message_id"), cq.get("data") or "")
    text = (msg.get("text") or "").strip()
    if not text:
        return _send(chat, "Send a question or tap the menu below.", _bottom())
    if text in BOTTOM_CMD:
        cmd, arg, how = BOTTOM_CMD[text], "", "button"
    else:
        cmd, arg, how = understand(text)
    if cmd in ("menu", "help"):
        a, _ = a_help()
        return _reply(chat, None, a, _bottom(), how, text)
    answer, kb = run(cmd, arg)
    _reply(chat, None, answer, kb, how, text)


# ----------------------------------------------------------------- understanding a message
def _held():
    try:
        return set(C._holdings())
    except Exception:  # noqa: BLE001
        return set()


def _symbol_in(text):
    """An NSE symbol or a company name in the text. Your holdings match in any case; other symbols only when
    typed in CAPITALS (so words like "idea" are not taken as stocks); a company name's first word only when no
    other company shares it."""
    held = _held()
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


ACTIONS = [  # typed actions: (regex, command)
    (r"^alert\s+([A-Za-z0-9&-]+)\s+(above|below|>|<|upar|niche)\s+₹?([\d.,]+)$", "addalert"),
    (r"^(add|remove|hatao|jodo)\s+([A-Za-z0-9&-]+)(?:\s+(?:to|from|in|se|me)\s+(.+))?$", "listedit"),
    (r"^paper\s+buy\s+([A-Za-z0-9&-]+)$", "paperbuy"),
    (r"^limit\s+([a-z_ ]+?)\s+₹?([\d.,]+)$", "setlimit"),
    (r"^core\s+(\d{1,3})\s*%?$", "setcore"),
    (r"^news\s+([A-Za-z0-9&-]+)$", "news"),
]


def understand(text):
    """-> (command, argument, how it was understood)."""
    t = text.strip()
    if t.startswith("/"):
        parts = t[1:].split(None, 1)
        cmd = parts[0].split("@")[0].lower() if parts else "help"
        arg = parts[1].strip() if len(parts) > 1 else ""
        if cmd == "start":
            cmd = "menu"
        return (cmd if cmd in CMDS else "help"), arg, "command"
    low = t.lower()
    for rx, cmd in ACTIONS:
        m = re.match(rx, low, re.I)
        if m:
            return cmd, m.groups(), "words"
    m = re.match(r"^(lang|language|bhasha|भाषा)\s+(hindi|hi|english|en|हिंदी)", low)
    if m:
        return "lang", "hi" if m.group(2) in ("hindi", "hi", "हिंदी") else "en", "words"
    sym = _symbol_in(t)
    cmd = next((c for c, rx in WORDS if re.search(rx, low)), None)
    if sym and cmd in (None, "holdings", "plan", "today", "help"):   # "should I buy HAL", "how did TVSMOTOR do today"
        return "stock", sym, "words"
    if sym and cmd == "news":
        return "news", sym, "words"
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
              "plan = what to sell or buy next; nifty = market, index, VIX; news = headlines (symbol optional); "
              "vsnifty = my return compared with Nifty; tax = capital gains tax; scanner = buy signals and my watch lists; "
              "paper = simulated trading account; reports = summaries; settings = Zerodha login, language, portal; "
              "alerts = my notifications; lang = change answer language; help = anything else. "
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


# ----------------------------------------------------------------- helpers
def _rs(v):
    return ("−" if v < 0 else "") + "₹" + format(int(round(abs(v))), ",")


def _px(v):
    return "₹" + format(v, ",.2f") if v is not None else "–"


def _btn(*rows):
    return {"inline_keyboard": [[{"text": t[:40], "callback_data": d[:64]} for t, d in row] for row in rows if row]}


def _bottom():
    return {"keyboard": [[{"text": t} for t in row] for row in BOTTOM], "resize_keyboard": True, "is_persistent": True}


def _back(*extra):
    return list(extra) + [[("☰ Menu", "cmd:more")]]


def _api(method, path, body=None, mode="invest"):
    """The portal's own API, so the bot gets exactly the same checks as the website."""
    return S.api(method, path, {"mode": mode}, dict(body or {}, mode=mode))


def _log(title, detail=""):
    try:
        H.add("action", "From the bot: " + title, detail[:300])
    except Exception:  # noqa: BLE001
        pass


def _confirm(text, fn):
    """Ask before doing something that changes your data; the button works for 10 minutes."""
    for k in [k for k, v in _pending.items() if time.time() - v[2] > 600]:
        _pending.pop(k, None)
    tok = secrets.token_hex(4)
    _pending[tok] = (text, fn, time.time())
    return "❓ " + text, _btn([("✅ Confirm", "cf:" + tok), ("✖ Cancel", "cx:" + tok)])


MENU = _btn([("📋 Today", "cmd:today"), ("💼 Holdings", "cmd:holdings"), ("🛡 Stops", "cmd:stops")],
            [("🧭 Plan", "cmd:plan"), ("📈 Market", "cmd:nifty"), ("📰 News", "cmd:news")],
            [("☰ More", "cmd:more")])


VIEW_BLOCK_CMD = {"addalert", "listedit", "paperbuy", "setlimit", "setcore", "restart", "login"}
VIEW_BLOCK_BTN = {"lr", "la", "t", "sd", "cn", "cd", "pd", "tg", "uq", "uk", "ct", "pc", "gc", "pb", "cf", "ru", "lg"}
VIEW_ONLY = "👁 You have view-only access: ask the owner to change this."


def _view_only():
    return getattr(_ctx, "role", "full") == "view"


def run(cmd, arg=""):
    if _view_only() and cmd in VIEW_BLOCK_CMD:
        return VIEW_ONLY, MENU
    fn = {"help": a_help, "menu": a_help, "more": a_more, "holdmenu": a_holdmenu, "today": a_today, "holdings": a_holdings, "stock": a_stock,
          "stops": a_stops, "plan": a_plan, "nifty": a_nifty, "vsnifty": a_vsnifty, "news": a_news, "tax": a_tax,
          "core": a_core, "sectors": a_sectors, "results": a_results, "longterm": a_longterm, "limits": a_limits,
          "alerts": a_alerts, "notes": a_notes, "pricealerts": a_pricealerts, "messages": a_messages, "quiet": a_quiet,
          "scanner": a_scanner, "lists": a_lists, "signals": a_signals, "top": a_top, "paper": a_paper, "gtts": a_gtts,
          "reports": a_reports, "settings": a_settings, "login": a_login, "status": a_settings, "rules": a_rules,
          "lang": a_lang, "restart": a_restart, "addalert": x_addalert, "listedit": x_listedit, "paperbuy": x_paperbuy,
          "setlimit": x_setlimit, "setcore": x_setcore}.get(cmd, a_help)
    return fn(arg)


# ----------------------------------------------------------------- menus
def a_help(_=""):
    return ("🤖 Tradeskill bot. Tap the menu below, or type:\n"
            "• a stock: HAL · news HAL · paper buy HAL\n"
            "• alert HAL below 4500 · add HAL to My list · remove HAL\n"
            "• limit max_per_stock 80000 · core 50\n"
            "• questions: \"how are my holdings?\", \"aaj kya karna hai\"\n\n"
            + "\n".join("/%s · %s" % (c, d) for c, d in COMMANDS)
            + "\n\nNever places real orders. Rule results, not personal advice."), MENU


def a_more(_=""):
    return "☰ More · pick a section", _btn(
        [("💼 Holdings & tax", "cmd:holdmenu"), ("🔔 Alerts", "cmd:alerts")],
        [("📊 Lists & scanner", "cmd:scanner"), ("🧾 Paper trading", "cmd:paper")],
        [("📑 Reports", "cmd:reports"), ("⚙️ Settings & portal", "cmd:settings")],
        [("📋 Today", "cmd:today"), ("💼 Holdings", "cmd:holdings")])


def a_holdmenu(_=""):
    return "💼 Holdings & tax", _btn(
        [("💼 Holdings", "cmd:holdings"), ("🛡 Stops", "cmd:stops"), ("🧭 Plan", "cmd:plan")],
        [("🏁 vs Nifty", "cmd:vsnifty"), ("💰 Tax", "cmd:tax"), ("🥧 Core split", "cmd:core")],
        [("🏭 Sectors", "cmd:sectors"), ("📅 Results", "cmd:results"), ("🗓 Long-term", "cmd:longterm")],
        [("⚖ Limits", "cmd:limits"), ("☰ Menu", "cmd:more")])


# ----------------------------------------------------------------- holdings & tax
def a_today(_=""):
    t = LG.today("invest")
    items = [x for x in t["items"] if x["group"] in ("act", "watch", "tomorrow")]
    _seen["today"] = [x["id"] for x in items]
    icon = {"act": "🔴", "watch": "🟡", "tomorrow": "🟢"}
    lines = ["📋 Today · %d to act, %d to watch, %d for tomorrow" % (t["counts"]["act"], t["counts"]["watch"], t["counts"]["tomorrow"])]
    lines += ["%s %d. %s%s" % (icon[x["group"]], i + 1, x["text"], " ✓" if x.get("done") else "") for i, x in enumerate(items[:15])]
    if not items:
        lines.append("✅ Nothing to act on.")
    shown = items[:15]
    rows = [[("✓ %d" % (i + 1), "t:%d" % i) for i in range(k, min(k + 5, len(shown))) if not shown[i].get("done")] for k in range(0, len(shown), 5)]
    return "\n".join(lines), _btn(*rows, [("🔄 Refresh", "cmd:today"), ("🛡 Stops", "cmd:stops"), ("☰ Menu", "cmd:more")])


def a_holdings(_=""):
    hold = list(C._holdings().values())
    if not hold:
        return "No holdings snapshot yet: open My holdings once with Zerodha connected (/login).", MENU
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
    lines.append("Tap a stock for details. Prices delayed; quantities from your last Zerodha snapshot.")
    syms = sorted(h["symbol"] for h in hold)
    rows = [[(s, "st:" + s) for s in syms[k:k + 4]] for k in range(0, min(len(syms), 20), 4)]
    return "\n".join(lines), _btn(*rows, [("🔄 Refresh", "cmd:holdings"), ("🛡 Stops", "cmd:stops"), ("☰ Menu", "cmd:holdmenu")])


def a_stock(arg=""):
    sym = S.clean_symbol(arg if isinstance(arg, str) else (arg[0] if arg else ""))
    if not sym:
        return "Which stock? Send e.g. /stock HAL or just HAL.", MENU
    mode = rules()
    p = L.analyze(sym, mode)
    lines = ["📊 %s · %s" % (sym, p.get("name") or ""),
             "%s (%+.2f%% today) · score %s/100 · %s" % (_px(p.get("price")), p.get("change_pct") or 0, p.get("score"), p.get("verdict") or ""),
             "Rules: %s" % ("Investing" if mode == "invest" else "Trading")]
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
    lines.append("Screening, not advice.")
    return "\n".join(lines), _btn([("📰 News", "nw:" + sym), ("🔔 Alert…", "al:" + sym), ("➕ My list", "la:" + sym)],
                                  [("🧾 Paper buy…", "pb:" + sym), ("🔄 Refresh", "st:" + sym), ("☰ Menu", "cmd:more")])


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
    return "\n".join(lines), _btn(*rows, [("🔄 Refresh", "cmd:stops"), ("☰ Menu", "cmd:holdmenu")])


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
    return "\n".join(lines), _btn([("🔄 Refresh", "cmd:plan"), ("📋 Today", "cmd:today"), ("☰ Menu", "cmd:holdmenu")])


def a_vsnifty(_=""):
    r = LG.vs_nifty()
    if not r.get("ok"):
        return r.get("message") or "Not enough records yet.", MENU
    lines = ["🏁 You vs Nifty · %s to %s (%d days)" % (r["from"], r["to"], r["days"]),
             "Your stocks: %s profit · %s a year" % (_rs(r["profit"]), "%+.1f%%" % r["xirr"] if r["xirr"] is not None else "–"),
             "Same money in Nifty 50: %s · %s a year" % (_rs(r["nifty_profit"]), "%+.1f%%" % r["nifty_xirr"] if r["nifty_xirr"] is not None else "–")]
    if r.get("short"):
        lines.append("Under a year of records: judge after 12 months.")
    return "\n".join(lines), _btn(*_back())


def a_tax(_=""):
    rep = LG.report()
    tx = rep.get("tax") or {}
    lines = ["💰 Tax estimate · FY %s" % rep.get("fy"),
             "Short-term gains %s · long-term gains %s" % (_rs(tx.get("short_gain") or 0), _rs(tx.get("long_gain") or 0)),
             "Estimated tax %s (incl. cess)" % _rs(tx.get("total_tax") or 0)]
    if tx.get("if_sold_today") is not None:
        lines.append(("Extra tax if all sold today: %s" if tx["if_sold_today"] >= 0 else "Tax saved if all sold today: %s") % _rs(abs(tx["if_sold_today"])))
    hv = tx.get("harvest")
    if hv:
        lines.append("\nTax-free long-term gains left before %s: %s" % (hv["fy_end"], _rs(hv["room"])))
        if hv["picks"]:
            lines += ["  Sell %g %s, buy back next trading day · books %s%s" % (p["qty"], p["symbol"], _rs(p["gain"]), " (from %s)" % p["sell_from"] if p["sell_from"] else "")
                      for p in hv["picks"][:6]]
            lines.append("Saves about %s tax · charges about %s" % (_rs(hv["saved"]), _rs(hv["charges"])))
        if hv.get("maybe"):
            lines.append("Not dated in your records: " + ", ".join(m["symbol"] for m in hv["maybe"][:8]))
    lines.append("Estimate from your records, not tax advice.")
    return "\n".join(lines), _btn([("🗓 Long-term soon", "cmd:longterm"), ("☰ Menu", "cmd:holdmenu")])


def a_core(_=""):
    c = (LG.report() or {}).get("core") or {}
    lines = ["🥧 Core + satellite · target %d%% in Nifty funds" % (c.get("target") or 0),
             "Core (index funds) %s · stocks %s" % (_rs(c.get("core_value") or 0), _rs(c.get("sat_value") or 0)),
             "Now %s in the core" % ("%.0f%%" % c["actual"] if c.get("actual") is not None else "–")]
    if c.get("move"):
        lines.append("%s about %s to reach the target%s" % ("Move into the index fund" if c["move"] > 0 else "Move from the index fund into stocks",
                                                        _rs(abs(c["move"])), " · rebalance due" if c.get("due") else ""))
    lines.append("Change the target with a button, or type: core 40")
    return "\n".join(lines), _btn([("25%", "ct:25"), ("40%", "ct:40"), ("50%", "ct:50"), ("60%", "ct:60"), ("75%", "ct:75")],
                                  [("☰ Menu", "cmd:holdmenu")])


def x_setcore(arg):
    t = int(arg[0] if isinstance(arg, (tuple, list)) else arg)
    return _confirm("Set the Nifty core target to %d%%?" % t, lambda: _set_core(t))


def _set_core(t):
    c = (LG.report() or {}).get("core") or {}
    r = LG.core_set({"target": t, "symbols": c.get("symbols") or [], "count_mf": c.get("count_mf", True)})
    _log("core target %d%%" % t)
    return r["message"]


def a_sectors(_=""):
    secs = (LG.report() or {}).get("sectors") or []
    lines = ["🏭 Sectors"] + ["%s %s: %d stock%s, %.0f%% · %s" % ("⚠️" if s.get("over") else "•", s["sector"], len(s["stocks"]), "" if len(s["stocks"]) == 1 else "s",
                                                               s.get("pct") or 0, ", ".join(s["stocks"][:5])) for s in secs if s.get("stocks")][:15]
    return "\n".join(lines), _btn(*_back())


def a_results(_=""):
    held = sorted(_held())
    with ThreadPoolExecutor(6) as ex:
        dues = dict(zip(held, ex.map(ML._results_due, held)))
    rows = sorted(((s, d) for s, d in dues.items() if d and -2 <= d["days"] <= 45), key=lambda x: x[1]["days"])
    lines = ["📅 Results expected (estimates)"] + ["%s around %s (in %d days)" % (s, d["date"], d["days"]) for s, d in rows]
    if not rows:
        lines.append("None in the next 45 days.")
    return "\n".join(lines), _btn(*_back())


def a_longterm(_=""):
    hv = ((LG.report() or {}).get("holdings")) or []
    rows = []
    for h in hv:
        for l in h.get("lots") or []:
            if l.get("long") is False and l.get("days_to_long") is not None and l["days_to_long"] <= 90:
                rows.append((l["days_to_long"], h["symbol"], l))
    rows.sort(key=lambda x: x[0])
    lines = ["🗓 Turning long-term (tax 20% → 12.5%) within 90 days"] + [
        "%s: %g shares on %s (in %d days)%s" % (s, l["qty"], l["long_from"], d, " · gain %s" % _rs(l["gain"]) if l.get("gain") is not None else "")
        for d, s, l in rows[:15]]
    if not rows:
        lines.append("None in the next 90 days (records start with your imported tradebook).")
    return "\n".join(lines), _btn(*_back())


LIMIT_KEYS = {"capital": "capital", "risk": "risk_per_trade", "risk_per_trade": "risk_per_trade", "max_per_stock": "max_per_stock",
              "per_stock": "max_per_stock", "max_positions": "max_positions", "stocks": "max_positions", "max_per_sector": "max_per_sector",
              "sector": "max_per_sector", "max_open_risk": "max_open_risk", "open_risk": "max_open_risk", "dd_pause_pct": "dd_pause_pct", "pause": "dd_pause_pct"}


def a_limits(_=""):
    cfg = L.settings_for("invest")
    lines = ["⚖ Your limits (Investing, also used for Trading)",
             "capital %s · risk_per_trade %s · max_per_stock %s" % (_rs(cfg["capital"]), _rs(cfg["risk_per_trade"]), _rs(cfg["max_per_stock"])),
             "max_positions %d · max_per_sector %d · max_open_risk %s · dd_pause_pct %g%%" % (cfg["max_positions"], cfg["max_per_sector"], _rs(cfg["max_open_risk"]), cfg["dd_pause_pct"]),
             "Change: type e.g. limit max_per_stock 80000 (asks to confirm)."]
    return "\n".join(lines), _btn(*_back())


def x_setlimit(arg):
    name, val = arg[0].strip().replace(" ", "_"), float(arg[1].replace(",", ""))
    key = LIMIT_KEYS.get(name)
    if not key:
        return "Unknown limit. Use one of: " + ", ".join(sorted(set(LIMIT_KEYS.values()))), None
    return _confirm("Set %s to %s for Investing and Trading?" % (key, ("%g" % val)), lambda: _set_limit(key, val))


def _set_limit(key, val):
    for m in ("invest", "swing"):
        _api("POST", "/api/settings", {"mode_settings": {m: {key: val}}}, mode=m)
    _log("limit %s = %g" % (key, val))
    return "Saved: %s = %g (Investing and Trading)." % (key, val)


# ----------------------------------------------------------------- market & news
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
    return "\n".join(lines), _btn([("🔄 Refresh", "cmd:nifty"), ("📰 News", "cmd:news"), ("☰ Menu", "cmd:more")])


TONE = {"pos": "🟢", "neg": "🔴"}


def a_news(arg=""):
    sym = S.clean_symbol(arg if isinstance(arg, str) else (arg[0] if arg else ""))
    syms = [sym] if sym else sorted(_held())[:14]
    if not syms:
        return "No holdings yet. Try: news HAL", MENU
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(lambda s: (s, (S.news(s) or {}).get("items") or []) if True else None, syms))
    lines = ["📰 News · %s" % (sym or "my holdings (3 days)")]
    for s, items in res:
        if not items:
            continue
        top = items[:4 if sym else 1]
        neg = sum(1 for i in items if i.get("tone") == "neg")
        pos = sum(1 for i in items if i.get("tone") == "pos")
        if not sym:
            lines.append("%s (%d: %d🟢 %d🔴): %s %s" % (s, len(items), pos, neg, TONE.get(top[0].get("tone"), "⚪"), top[0]["title"][:110]))
        else:
            lines += ["%s %s (%s)" % (TONE.get(i.get("tone"), "⚪"), i["title"][:140], i.get("source") or "") for i in top]
    if len(lines) == 1:
        lines.append("No headlines in the last 3 days.")
    return "\n".join(lines), _btn([("🇮🇳 Hindi overnight news", "rp:hindinews")], [("🔄 Refresh", "nw:" + (sym or "")), ("☰ Menu", "cmd:more")])


# ----------------------------------------------------------------- alerts & notifications
def a_alerts(_=""):
    st = S.load_state()
    n_own = len(((st.get("custom_notes") or {}).get("rules")) or [])
    n_px = len([a for a in st.get("alerts") or [] if not a.get("fired_at")])
    n_q = len(((st.get("telegram") or {}).get("quiet")) or {})
    return ("🔔 Alerts\nOwn notifications: %d · price alerts waiting: %d · muted alerts: %d\n"
            "Add a price alert: type alert HAL below 4500 (or above)." % (n_own, n_px, n_q)), _btn(
        [("🔔 Own notifications", "cmd:notes"), ("💲 Price alerts", "cmd:pricealerts")],
        [("📨 Built-in messages", "cmd:messages"), ("🔕 Muted (%d)" % n_q, "cmd:quiet")], [("☰ Menu", "cmd:more")])


def a_notes(_=""):
    d = C.listing()
    if not d["rules"]:
        return "No own notifications yet. Add them on the portal: Limits → Telegram → + New notification.", _btn([("◀ Alerts", "cmd:alerts")])
    lines = ["🔔 Own notifications (⏸/▶ to switch, 🗑 to delete)"] + ["%s %s" % ("🟢" if r["on"] else "⚪", r["name"]) for r in d["rules"][:20]]
    rows = [[("%s %s" % ("⏸" if r["on"] else "▶", r["name"][:22]), "cn:%s:%d" % (r["id"], 0 if r["on"] else 1)), ("🗑", "cd:%s" % r["id"])] for r in d["rules"][:20]]
    return "\n".join(lines), _btn(*rows, [("◀ Alerts", "cmd:alerts")])


def a_pricealerts(_=""):
    al = S.load_state().get("alerts") or []
    lines = ["💲 Price alerts (🗑 to delete)"]
    rows = []
    for a in al[-20:]:
        if a.get("type") == "clock":
            txt = "clock %s" % a.get("level")
        else:
            txt = "%s %s %s%s" % (a.get("symbol"), a.get("type"), a.get("level"), " · rang" if a.get("fired_at") else "")
        lines.append(("✅ " if a.get("fired_at") else "⏳ ") + txt + (" (%s)" % a["label"] if a.get("label") else ""))
        rows.append([("🗑 " + txt[:30], "pd:" + a["id"])])
    if len(lines) == 1:
        lines.append("None. Type: alert HAL below 4500")
    return "\n".join(lines), _btn(*rows, [("◀ Alerts", "cmd:alerts")])


def x_addalert(arg):
    sym, how, lvl = S.clean_symbol(arg[0]), arg[1], float(arg[2].replace(",", ""))
    t = "above" if how in ("above", ">", "upar") else "below"
    _api("POST", "/api/alerts", {"alerts": [{"type": t, "symbol": sym, "level": lvl, "label": "from bot"}]})
    _log("price alert %s %s %g" % (sym, t, lvl))
    return "✅ Alert set: %s %s %s. It rings once (Telegram 'Price alerts ringing' must be on)." % (sym, t, _px(lvl)), _btn([("💲 Price alerts", "cmd:pricealerts")])


def a_messages(_=""):
    st = T.status()
    gone = set(st.get("removed") or [])
    kinds = [(k, l) for k, l in st["kinds"] if k not in gone]
    lines = ["📨 Built-in messages (tap to switch)"] + ["%s %s" % ("🟢" if st["on"].get(k) else "⚪", l) for k, l in kinds]
    rows = [[("%s %s" % ("⏸" if st["on"].get(k) else "▶", l[:30]), "tg:%s:%d" % (k, 0 if st["on"].get(k) else 1))] for k, l in kinds]
    return "\n".join(lines), _btn(*rows, [("◀ Alerts", "cmd:alerts")])


def a_quiet(_=""):
    q = (_tg().get("quiet")) or {}
    lines = ["🔕 Muted alerts: told once, quiet until you allow them again"]
    items = sorted(q.items(), key=lambda kv: kv[1], reverse=True)[:20]
    rows = []
    for i, (k, when) in enumerate(items):
        kind, *rest = k.split("|")
        label = "%s · %s" % (kind, rest[-1] if rest else "")
        lines.append("• %s (since %s)" % (label, str(when)[5:16]))
        rows.append([("🔔 Allow " + label[:28], "uk:%d" % i)])
    _seen["quiet"] = [k for k, _ in items]
    if not items:
        lines.append("Nothing muted.")
    else:
        rows.append([("🔔 Allow all", "uk:*")])
    return "\n".join(lines), _btn(*rows, [("◀ Alerts", "cmd:alerts")])


# ----------------------------------------------------------------- lists & scanner
def a_scanner(_=""):
    lists = ML.get_lists()["lists"]
    return ("📊 Lists & scanner\nLists: %s\nType: add HAL (to the first list) · add HAL to <list> · remove HAL" %
            ", ".join("%s (%d)" % (x["name"], len(x["symbols"])) for x in lists)), _btn(
        [("🟢 Buy signals with room", "cmd:signals"), ("🏆 Top scanner picks", "cmd:top")],
        *[[("📋 %s" % x["name"][:24], "ls:%s" % x["id"])] for x in lists[:8]], [("☰ Menu", "cmd:more")])


def a_lists(arg=""):
    lists = ML.get_lists()["lists"]
    lid = arg if isinstance(arg, str) and arg else (lists[0]["id"] if lists else "main")
    d = ML.myscan("invest", {"list": lid, "source": "list"})
    icon = {"exit": "🔴", "buy": "🟢", "near": "🟡", "holding": "💼", "watching": "⚪"}
    name = next((x["name"] for x in lists if x["id"] == lid), lid)
    lines = ["📋 %s · Investing rules" % name] + ["%s %s %s%s%s" % (icon.get(r.get("state"), "⚪"), r["symbol"], _px(r.get("price")),
                                                                 " · %s" % r["setup"] if r.get("setup") else "",
                                                                 " · %.1f%% to trigger" % r["dist_trigger"] if r.get("dist_trigger") is not None else "")
                                                for r in d["rows"][:25]]
    if not d["rows"]:
        lines.append("Empty. Type: add HAL to %s" % name)
    rows = [[("➖ %s" % r["symbol"], "lr:%s:%s" % (lid, r["symbol"])) for r in d["rows"][k:k + 4]] for k in range(0, min(len(d["rows"]), 16), 4)]
    return "\n".join(lines), _btn(*rows, [("🔄 Refresh", "ls:" + lid), ("◀ Scanner", "cmd:scanner")])


def x_listedit(arg):
    act, sym, lname = arg[0].lower(), S.clean_symbol(arg[1]), (arg[2] or "").strip() if len(arg) > 2 else ""
    lists = ML.get_lists()["lists"]
    lst = next((x for x in lists if x["name"].lower() == lname.lower()), None) if lname else (lists[0] if lists else None)
    if not lst:
        return "No list called %r. Lists: %s" % (lname, ", ".join(x["name"] for x in lists)), None
    add = act in ("add", "jodo")
    ML.update({"action": "add" if add else "remove", "list": lst["id"], "symbol": sym})
    _log("list %s %s %s" % (lst["name"], "add" if add else "remove", sym))
    return "✅ %s %s %s." % ("Added" if add else "Removed", sym, ("to " if add else "from ") + lst["name"]), _btn([("📋 %s" % lst["name"][:24], "ls:" + lst["id"])])


def a_signals(_=""):
    txt = R.roombuys() if hasattr(R, "roombuys") else None
    return (txt or "🟢 No rule buy signal you have room for right now."), _btn([("🏆 Top scanner picks", "cmd:top"), ("◀ Scanner", "cmd:scanner")])


def a_top(_=""):
    d = L.scan_long("invest")
    rows = [r for r in d["rows"] if r.get("status") in ("confirmed", "recent", "provisional")][:12]
    lines = ["🏆 Investing signals now (top by strength)"] + ["%s · %s · %s%s" % (r["symbol"], r.get("setup") or "", _px(r.get("price")),
                                                                                 " · rank %s" % r["rank"] if r.get("rank") is not None else "") for r in rows]
    if not rows:
        lines.append("No active signal.")
    return "\n".join(lines), _btn(*[[(r["symbol"], "st:" + r["symbol"]) for r in rows[k:k + 4]] for k in range(0, len(rows), 4)], [("◀ Scanner", "cmd:scanner")])


# ----------------------------------------------------------------- paper trading (simulated money only)
def a_paper(_=""):
    p = L.portfolio_long("invest")
    lines = ["🧾 Paper account · Investing (simulated money)",
             "Equity %s · cash %s · total P&L %s · drawdown %.1f%%" % (_rs(p["equity"]), _rs(p["cash"]), _rs(p["total_pnl"]), p.get("drawdown") or 0)]
    for x in p["positions"][:12]:
        last = x.get("last") or x["entry"]
        lines.append("• %s %g @ %s → %s (%+.1f%%) · stop %s" % (x["symbol"], x["qty"], _px(x["entry"]), _px(last), (last / x["entry"] - 1) * 100, _px(x["stop"])))
    if not p["positions"]:
        lines.append("No open paper positions. Type: paper buy HAL")
    rows = [[("✖ Close %s" % x["symbol"], "pc:%s" % x["id"])] for x in p["positions"][:8] if x.get("id")]
    return "\n".join(lines), _btn(*rows, [("⏳ Paper GTTs", "cmd:gtts"), ("🔄 Refresh", "cmd:paper"), ("☰ Menu", "cmd:more")])


def a_gtts(_=""):
    d = G.listing("invest")
    act = [o for o in d["orders"] if o.get("status") == "active"][:15]
    lines = ["⏳ Paper GTTs · Investing"] + ["%s buy at %s%s" % (o["symbol"], _px(o.get("trigger")), " · stop %s" % _px(o["stop"]) if o.get("stop") else "") for o in act]
    if not act:
        lines.append("None active. Set them on the portal (Predictor / My scanner → GTT).")
    return "\n".join(lines), _btn(*[[("✖ Cancel %s" % o["symbol"], "gc:%s" % o["id"])] for o in act[:8]], [("◀ Paper", "cmd:paper")])


def x_paperbuy(arg):
    sym = S.clean_symbol(arg[0] if isinstance(arg, (tuple, list)) else arg)
    p = L.analyze(sym, "invest")
    pl, sz = p.get("plan") or {}, p.get("size") or {}
    txt = "Paper buy %s (simulated): %s%s · stop %s · qty %s · verdict %s" % (
        sym, "buy above %s" % _px(pl.get("trigger")) if pl.get("trigger") else "at about %s" % _px(pl.get("entry") or p.get("price")),
        "", _px(pl.get("stop")), sz.get("qty") or "?", p.get("verdict") or "")
    return _confirm(txt + "?", lambda: _paper_buy(sym))


def _paper_buy(sym):
    r = _api("POST", "/api/orders", {"symbol": sym, "confirm": True})
    _log("paper buy %s" % sym)
    pos = (r or {}).get("position") or {}
    return "✅ Paper order done: %s %s" % (sym, ("%s shares at %s" % (pos.get("qty"), _px(pos.get("entry")))) if pos else (r.get("message") if isinstance(r, dict) else ""))


# ----------------------------------------------------------------- reports, settings, portal
REPORTS = [("morning", "🌅 Morning plan"), ("plan", "📋 Day plan"), ("exits", "🔴 Exit signals"), ("whatnext", "🧭 What next"),
           ("roombuys", "🟢 Buy signals"), ("close", "🔔 Market close"), ("eod", "💼 Holdings today"), ("weekly", "📆 Weekly"),
           ("hindinews", "🇮🇳 Hindi news")]


def a_reports(_=""):
    return "📑 Reports on demand · built now from live data, sent only here", _btn(
        *[[(l, "rp:" + k) for k, l in REPORTS[i:i + 3]] for i in range(0, len(REPORTS), 3)], [("☰ Menu", "cmd:more")])


def a_report(kind):
    fn = R.BUILDERS.get(kind)
    if not fn:
        return "Unknown report.", None
    txt = fn()
    return (txt or "Nothing to report right now."), _btn([("📑 Reports", "cmd:reports"), ("☰ Menu", "cmd:more")])


def a_settings(_=""):
    st = S.load_state()
    tg = st.get("telegram") or {}
    snaps = {}
    try:
        with LG._lock:
            snaps = LG._load().get("snapshots") or {}
    except Exception:  # noqa: BLE001
        pass
    last = snaps[sorted(snaps)[-1]].get("at") if snaps else None
    code = {}
    try:
        code = S.code_status() or {}
    except Exception:  # noqa: BLE001
        pass
    lines = ["⚙️ Settings & portal",
             "Zerodha: %s" % ("token saved" if (st.get("kite") or {}).get("token") else "not connected") + (" · last holdings snapshot %s" % last if last else ""),
             "Answer language: %s · stock answers by %s rules" % ("Hindi" if lang() == "hi" else "English", "Investing" if rules() == "invest" else "Trading"),
             "AI service: %s" % ("%s · %s" % (AI.status()["providers"][AI.cfg()["provider"]]["label"], AI.cfg()["model"]) if AI.configured() else "not set (keywords only)"),
             "Portal: running%s" % (" since %s" % code.get("started") if code.get("started") else ""),
             "Telegram: %d muted alerts · %d other chats ignored" % (len(tg.get("quiet") or {}), _status["ignored"])]
    return "\n".join(lines), _btn(
        [("🔑 Zerodha login link", "cmd:login"), ("🌐 Portal link", "pl:")],
        [("🇮🇳 Hindi" if lang() == "en" else "🇬🇧 English", "lg:" + ("hi" if lang() == "en" else "en")),
         ("Rules: %s" % ("Trading" if rules() == "invest" else "Investing"), "ru:" + ("swing" if rules() == "invest" else "invest"))],
        [("⚖ Limits", "cmd:limits"), ("🔄 Restart portal…", "cmd:restart")], [("☰ Menu", "cmd:more")])


def a_login(_=""):
    return ("🔑 Zerodha login (tap, Tailscale on if you're away from home):\n%s\nAfter signing in, holdings and the snapshot refresh." % D.login_link()), _btn([("◀ Settings", "cmd:settings")])


def a_rules(arg=""):
    return a_settings()


def a_lang(arg=""):
    a = (arg or "").lower() if isinstance(arg, str) else ""
    if a not in ("hi", "en"):
        return "Answer language now: %s. Send /lang hi or /lang en." % ("Hindi" if lang() == "hi" else "English"), \
            _btn([("🇮🇳 Hindi", "lg:hi"), ("🇬🇧 English", "lg:en")])
    _set(lang=a)
    note = "" if a == "en" or AI.configured() else " (Hindi needs an AI service set on the portal; until then answers stay English.)"
    return "Answer language: %s.%s" % ("Hindi" if a == "hi" else "English", note), MENU


def a_restart(_=""):
    return _confirm("Restart the portal now? (about 10 seconds; alerts pause briefly)", _restart)


def _restart():
    err = S._code_ok()
    if err:
        return "Not restarted: a code file has an error. " + err
    _log("portal restart")
    threading.Timer(2.0, lambda: S.restart_now("Telegram bot")).start()
    return "🔄 Restarting in a few seconds."


# ----------------------------------------------------------------- buttons
def _button(chat, mid, data):
    head, _, rest = data.partition(":")
    note = ""
    if _view_only() and (head in VIEW_BLOCK_BTN or data in ("cmd:restart", "cmd:login")):
        return _reply(chat, mid, VIEW_ONLY, _btn([("☰ Menu", "cmd:more")]), "button", data)
    if head == "cmd":
        answer, kb = a_holdmenu() if rest == "holdmenu" else run(rest)
    elif head == "st":
        answer, kb = a_stock(rest)
    elif head == "nw":
        answer, kb = a_news(rest)
    elif head == "rp":
        answer, kb = a_report(rest)
    elif head == "ls":
        answer, kb = a_lists(rest)
    elif head == "lr":
        lid, sym = rest.split(":", 1)
        ML.update({"action": "remove", "list": lid, "symbol": sym})
        _log("list remove %s" % sym)
        answer, kb = a_lists(lid)
        note = "✓ Removed %s." % sym
    elif head == "la":
        lists = ML.get_lists()["lists"]
        ML.update({"action": "add", "list": lists[0]["id"], "symbol": rest})
        _log("list add %s" % rest)
        answer, kb = a_stock(rest)
        note = "✓ Added %s to %s." % (rest, lists[0]["name"])
    elif head == "al":
        answer, kb = ("🔔 Type the alert, e.g.\nalert %s below 4500\nalert %s above 5200" % (rest, rest)), _btn([("◀ %s" % rest, "st:" + rest)])
    elif head == "pb":
        answer, kb = x_paperbuy([rest])
    elif head == "t":
        ids = _seen.get("today") or []
        i = int(rest) if rest.isdigit() else -1
        if 0 <= i < len(ids):
            LG.today_done({"id": ids[i], "done": True})
        answer, kb = a_today()
        note = "✓ Ticked item %d." % (i + 1)
    elif head == "sd":
        todo = [x["symbol"] for x in LG.stops()["rows"] if x["status"] in ("new", "raise", "qty")] if rest == "*" else [rest]
        note = "✓ " + LG.stops_done({"symbols": todo}).get("message", "")
        answer, kb = a_stops()
    elif head == "cn":
        rid, on = rest.split(":")
        note = "✓ " + C.save({"action": "toggle", "id": rid, "on": on == "1"}).get("message", "")
        answer, kb = a_notes()
    elif head == "cd":
        r = next((x for x in C.listing()["rules"] if x["id"] == rest), None)
        answer, kb = _confirm("Delete the notification \"%s\" for good?" % (r["name"] if r else rest),
                              lambda: C.save({"action": "delete", "id": rest}).get("message"))
    elif head == "pd":
        _api("POST", "/api/alerts/delete", {"id": rest})
        _log("price alert deleted")
        answer, kb = a_pricealerts()
        note = "✓ Price alert deleted."
    elif head == "tg":
        kind, on = rest.split(":")
        T.set_on({kind: on == "1"})
        answer, kb = a_messages()
        note = "✓ Switched %s." % ("on" if on == "1" else "off")
    elif head in ("uq", "uk"):
        if head == "uq":
            keys = (_tg().get("quiet_groups") or {}).get(rest) or []
        elif rest == "*":
            keys = None
        else:
            lst = _seen.get("quiet") or []
            keys = [lst[int(rest)]] if rest.isdigit() and int(rest) < len(lst) else []
        n = T.unquiet(keys)
        note = "🔔 Allowed again: %d alert%s. They'll message you the next time they happen." % (n, "" if n == 1 else "s")
        answer, kb = a_quiet() if head == "uk" else (note, _btn([("🔕 Muted list", "cmd:quiet")]))
        if head == "uq":
            note = ""
    elif head == "ct":
        answer, kb = x_setcore(rest)
    elif head == "pc":
        answer, kb = _confirm("Close the paper position now (simulated)?", lambda: (L.close_long("invest", rest), _log("paper close"), "✅ Paper position closed.")[-1])
    elif head == "gc":
        answer, kb = _confirm("Cancel this paper GTT?", lambda: (G.cancel(rest), _log("paper GTT cancelled"), "✅ Paper GTT cancelled.")[-1])
    elif head == "lg":
        answer, kb = a_lang(rest)
    elif head == "ru":
        _set(rules=rest if rest in ("invest", "swing") else "invest")
        answer, kb = a_settings()
        note = "✓ Stock answers now use the %s rules." % ("Trading" if rest == "swing" else "Investing")
    elif head == "pl":
        answer, kb = "🌐 Portal: %s" % D.portal_link(), _btn([("◀ Settings", "cmd:settings")])
    elif head == "cf":
        item = _pending.pop(rest, None)
        if not item:
            answer, kb = "This confirmation expired (10 minutes). Please ask again.", MENU
        else:
            answer, kb = str(item[1]() or "Done."), _btn([("☰ Menu", "cmd:more")])
    elif head == "cx":
        _pending.pop(rest, None)
        answer, kb = "Cancelled. Nothing was changed.", _btn([("☰ Menu", "cmd:more")])
    else:
        answer, kb = a_help()
    if note:
        answer = note + "\n\n" + answer
    _reply(chat, mid, answer, kb, "button", data)


# ----------------------------------------------------------------- sending (in place, optional Hindi)
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text):
    return sorted(n.replace(",", "") for n in _NUM.findall(text))


def to_hindi(text):
    """AI translation; refused (English kept) when any number changed."""
    out = AI.ask("Translate the user's message into simple Hindi (Devanagari script). Keep every number, ₹ amount, %, "
                 "+/− sign, date, time, NSE stock symbol, emoji, slash command, web link and line break exactly as written, "
                 "using Western digits 0-9. Do not add, remove or explain anything. Output only the translation.", text, max_tokens=1500)
    if not out or _numbers(out) != _numbers(text):
        raise ValueError("a number changed in translation")
    return out


def _reply(chat, mid, text, kb, how, question):
    note = ""
    if lang() == "hi" and AI.configured():
        try:
            text = to_hindi(text)
        except Exception as e:  # noqa: BLE001
            note = "\n(Hindi skipped: %s)" % str(e)[:80]
    if how not in ("command", "words", "button", "AI"):
        note += "\n(%s)" % how
    full = text + note
    if mid and (kb is None or "inline_keyboard" in kb):   # a button press: update that message in place
        try:
            params = {"chat_id": chat, "message_id": mid, "text": full[:4000], "disable_web_page_preview": "true"}
            if kb:
                params["reply_markup"] = json.dumps(kb)
            with _lock_send:
                _call("editMessageText", params)
        except Exception as e:  # noqa: BLE001
            if "not modified" not in str(e):
                _send(chat, full, kb)
    else:
        _send(chat, full, kb)
    try:
        R.log("bot", "Q: %s\nA: %s" % (str(question)[:200], text.split("\n")[0][:200]), "sent")
    except Exception:  # noqa: BLE001
        pass


def _send(chat, text, kb=None):
    params = {"chat_id": chat, "text": text[:4000], "disable_web_page_preview": "true"}
    if kb:
        params["reply_markup"] = json.dumps(kb)
    with _lock_send:
        _call("sendMessage", params)
