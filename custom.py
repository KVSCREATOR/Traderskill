"""Your own Telegram notifications, built from ready-made blocks (Limits -> Telegram -> Your own notifications).

Each notification = WHAT to watch (a block from CATALOG) + WHICH stocks (scope) + WHEN to check +
HOW OFTEN it may ring + an optional note. Blocks are tested code; the form only combines them, so a
wrong setting can make a notification stay quiet but can never break the portal. A new kind of check
is added here as a new block.

Stored in state.json -> "custom_notes": {"rules": [...], "mem": {rule id: {...}}}.
Read-only facts and rule results, not personal advice.
"""
import math
import re
import secrets
import threading
import time
from datetime import date, timedelta

S = None    # server module
L = None    # longterm module
K = None    # kite module (Investing verdicts)
T = None    # telegram module (notify)
LG = None   # ledger module (holdings snapshot, lots, core list)
ML = None   # mylist module (My scanner lists, results dates)
R = None    # reports module (trading days)

MAX_RULES = 50
MIN_GAP = 1800          # "every time": at least 30 minutes between two messages for the same stock
MARKET_EVERY = 300      # market-hours checks every 5 minutes
_run_lock = threading.Lock()
_ind_cache = {}

P = lambda k, label, typ="num", default=None, unit="", options=None: {   # noqa: E731
    "k": k, "label": label, "type": typ, "default": default, "unit": unit, "options": options}
DIR3 = [["either", "Up or down"], ["up", "Up"], ["down", "Down"]]

# id, group, label, help, params, scope ("stocks" | "holdings" | "portfolio" | "none"), default when
CATALOG = [
    # --- My holdings
    ("h_profit_pct", "My holdings", "Profit reaches X%", "A holding's total profit vs your buy price reaches X% or more.",
     [P("x", "Profit at least", default=20, unit="%")], "holdings", "market"),
    ("h_profit_rs", "My holdings", "Profit reaches ₹X", "A holding's total profit in rupees reaches ₹X or more.",
     [P("x", "Profit at least", default=25000, unit="₹")], "holdings", "market"),
    ("h_loss_pct", "My holdings", "Down X% from your buy price", "A holding is X% or more below your average buy price.",
     [P("x", "Loss at least", default=10, unit="%")], "holdings", "market"),
    ("h_loss_rs", "My holdings", "Loss reaches ₹X", "A holding's total loss in rupees reaches ₹X or more.",
     [P("x", "Loss at least", default=10000, unit="₹")], "holdings", "market"),
    ("h_flip", "My holdings", "Turns from profit to loss (or back)", "A holding crosses your buy price.",
     [P("dir", "Direction", "sel", "either", options=[["either", "Either way"], ["to_loss", "Profit → loss"], ["to_profit", "Loss → profit"]])],
     "holdings", "market"),
    ("h_day_pct", "My holdings", "Moves X% today", "A holding's price moves X% or more today.",
     [P("x", "Move at least", default=4, unit="%"), P("dir", "Direction", "sel", "either", options=DIR3)], "holdings", "market"),
    ("h_day_rs", "My holdings", "Gains or loses ₹X today", "A holding gains or loses ₹X or more today (price move × your shares).",
     [P("x", "At least", default=5000, unit="₹"), P("dir", "Direction", "sel", "either", options=DIR3)], "holdings", "market"),
    ("h_from_peak", "My holdings", "Falls X% from its peak since you bought", "A holding closes X% or more below its highest close since you bought it (or the last 12 months when the buy date is not in your records): protects profits.",
     [P("x", "Fall at least", default=12, unit="%")], "holdings", "close"),
    ("h_weight", "My holdings", "Grows over X% of your portfolio", "A holding is worth more than X% of all your holdings together.",
     [P("x", "More than", default=15, unit="%")], "holdings", "close"),
    ("h_deal", "My holdings", "Bulk or block deal in your stock", "NSE reports a bulk or block deal (a big named buyer or seller) in the stock.",
     [P("side", "Side", "sel", "any", options=[["any", "Buy or sell"], ["BUY", "Buy"], ["SELL", "Sell"]])], "stocks", "close"),
    ("h_near_stop", "My holdings", "Near its stop", "A holding is within X% above its Investing rule stop.",
     [P("x", "Within", default=3, unit="%")], "holdings", "close"),
    ("h_long_soon", "My holdings", "Turns long-term soon", "Shares turn long-term (held 12 months) within X days: tax drops from 20% to 12.5%.",
     [P("x", "Within", default=15, unit="days")], "holdings", "close"),
    ("h_results_soon", "My holdings", "Results coming", "Quarterly results expected within X days (estimate): the price can gap.",
     [P("x", "Within", default=5, unit="days")], "holdings", "close"),
    # --- All holdings together
    ("p_day_rs", "All holdings", "Day profit or loss over ₹X", "All your holdings together gain or lose ₹X or more today.",
     [P("x", "At least", default=20000, unit="₹"), P("dir", "Direction", "sel", "down", options=DIR3)], "portfolio", "market"),
    ("p_drawdown", "All holdings", "Falls X% from its highest", "The total value of your holdings falls X% or more from the highest value seen.",
     [P("x", "Fall at least", default=8, unit="%")], "portfolio", "close"),
    ("p_over_cap", "All holdings", "A stock over your per-stock limit", "Any holding is worth more than your Investing per-stock limit (index funds skipped).",
     [], "portfolio", "close"),
    ("p_sector", "All holdings", "A sector over its limit", "A sector has more stocks than your limit or over 25% of the value.",
     [], "portfolio", "close"),
    # --- Price and % moves
    ("price_above", "Price and % moves", "Price at or above ₹X", "The price is at or above ₹X.",
     [P("x", "Price", default=None, unit="₹")], "stocks", "market"),
    ("price_below", "Price and % moves", "Price at or below ₹X", "The price is at or below ₹X.",
     [P("x", "Price", default=None, unit="₹")], "stocks", "market"),
    ("day_pct", "Price and % moves", "Up or down X% today", "The price moves X% or more today.",
     [P("x", "Move at least", default=5, unit="%"), P("dir", "Direction", "sel", "either", options=DIR3)], "stocks", "market"),
    ("from_dayhigh", "Price and % moves", "Falls X% from today's high", "The price is X% or more below today's high (a sharp fall during the day).",
     [P("x", "Fall at least", default=3, unit="%")], "stocks", "market"),
    ("gap_open", "Price and % moves", "Gap at the open", "The stock opens X% or more above or below yesterday's close (checked in the first hour).",
     [P("x", "Gap at least", default=2, unit="%"), P("dir", "Direction", "sel", "either", options=DIR3)], "stocks", "market"),
    # --- The market
    ("nifty_move", "The market", "Nifty 50 moves X% today", "The Nifty 50 is X% or more up or down today.",
     [P("x", "Move at least", default=1, unit="%"), P("dir", "Direction", "sel", "either", options=DIR3)], "none", "market"),
    ("nifty_level", "The market", "Nifty 50 above or below a level", "The Nifty 50 is at or above / at or below the level you set.",
     [P("x", "Level", default=None), P("dir", "When it is", "sel", "below", options=[["above", "At or above"], ["below", "At or below"]])], "none", "market"),
    ("vix", "The market", "India VIX above X", "India VIX (expected volatility) is above X: wider swings, stops hit more easily.",
     [P("x", "Above", default=18)], "none", "market"),
    # --- Chart signals (daily bars: today's price in market hours, the close after it)
    ("cross_ma", "Chart signals", "Crosses its 50 / 200-day average", "The price crosses its moving average since the day before.",
     [P("ma", "Average", "sel", "200", options=[["50", "50-day"], ["200", "200-day"]]),
      P("dir", "Direction", "sel", "down", options=[["up", "Crosses above"], ["down", "Crosses below"], ["either", "Either way"]])], "stocks", "close"),
    ("high52", "Chart signals", "New 52-week high or low", "The price makes a new 52-week high or low.",
     [P("dir", "Which", "sel", "high", options=[["high", "52-week high"], ["low", "52-week low"]])], "stocks", "close"),
    ("vol_spike", "Chart signals", "Volume X× normal", "Today's volume is X times the 50-day average or more.",
     [P("x", "At least", default=2, unit="×")], "stocks", "close"),
    ("rsi", "Chart signals", "RSI above or below X", "14-day RSI crosses above or below X (e.g. above 70 overbought, below 30 oversold).",
     [P("x", "Level", default=30), P("dir", "When RSI is", "sel", "below", options=[["below", "Below"], ["above", "Above"]])], "stocks", "close"),
    # --- Rule events
    ("verdict", "Rule events", "Investing verdict changes", "The Investing rules' verdict changes (Buy / Hold / Weak / Exit).",
     [P("to", "Changes to", "sel", "any", options=[["any", "Any change"], ["exit", "Exit"], ["weak", "Weak"], ["buy", "Buy"], ["hold", "Hold"]])],
     "stocks", "close"),
    # --- Scheduled and news
    ("summary", "Scheduled and news", "Summary at a set time", "A short report at the time and days you choose.",
     [P("what", "Report", "sel", "holdings", options=[["holdings", "My holdings: value, today, best and worst"],
                                                       ["stocks", "The chosen stocks: price and today's move"],
                                                       ["nifty", "Nifty 50: level, today, vs 50/200-day"]])], "stocks", "time"),
    ("news_kw", "Scheduled and news", "News headline with a keyword", "A new headline about the stocks that contains your word (empty = any new headline).",
     [P("kw", "Keyword", "text", "")], "stocks", "time"),
]
CAT = {c[0]: c for c in CATALOG}
WHEN = {"market": "Market hours, every 5 minutes", "close": "After the close (15:40)", "time": "At a set time"}
REPEAT = {"daily": "Once a day per stock", "once": "Once, then switch off", "every": "Every time (30 min apart)"}
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def catalog():
    return {"blocks": [{"id": c[0], "group": c[1], "label": c[2], "help": c[3], "params": c[4], "scope": c[5], "when": c[6]} for c in CATALOG],
            "when": WHEN, "repeat": REPEAT, "days": DAYS}


# ----------------------------------------------------------------- storage
def _data(st):
    d = st.get("custom_notes")
    if not isinstance(d, dict):
        d = {"rules": [], "mem": {}}
        st["custom_notes"] = d
    d.setdefault("rules", [])
    d.setdefault("mem", {})
    return d


def listing():
    st = S.load_state()
    d = _data(st)
    lists = [{"id": x["id"], "name": x["name"], "n": len(x["symbols"])} for x in ML.get_lists()["lists"]]
    snap = _snap()
    held = sorted(r["symbol"] for r in (snap or {}).get("holdings") or [] if r.get("symbol") and (r.get("qty") or 0) > 0)
    return {"rules": d["rules"], "catalog": catalog(), "lists": lists, "held": held,
            "master_on": (st.get("telegram") or {}).get("on", {}).get("custom", True)}


def _clean(body, old=None):
    what = body.get("what")
    if what not in CAT:
        raise S.ApiError(400, "Choose what to watch.")
    _, _, label, _, params, scope_kind, _ = CAT[what]
    name = str(body.get("name") or "").strip()[:60] or label
    vals = {}
    for p in params:
        v = (body.get("params") or {}).get(p["k"], p["default"])
        if p["type"] == "num":
            try:
                v = float(v)
            except (TypeError, ValueError):
                raise S.ApiError(400, "%s: enter a number." % p["label"])
            if not math.isfinite(v) or v < 0 or v > 1e9:
                raise S.ApiError(400, "%s: enter a number from 0 up." % p["label"])
        elif p["type"] == "sel":
            if v not in [o[0] for o in p["options"]]:
                raise S.ApiError(400, "%s: choose one of the options." % p["label"])
        else:
            v = str(v or "").strip()[:40]
        vals[p["k"]] = v
    scope = str(body.get("scope") or "")
    if scope.startswith("pick:"):   # some of my holdings, ticked one by one
        syms = [S.clean_symbol(x) for x in scope[5:].split(",") if x.strip()]
        syms = list(dict.fromkeys(s for s in syms if s))[:60]
        if not syms:
            raise S.ApiError(400, "Tick at least one of your holdings.")
        scope = "pick:" + ",".join(syms)
    if scope_kind == "none":
        scope = "none"
    elif scope_kind == "portfolio":
        scope = "holdings"
    elif scope_kind == "holdings":
        if not (scope == "holdings" or scope.startswith("stock:") or scope.startswith("pick:")):
            scope = "holdings"
    elif not (scope in ("holdings", "all") or scope.startswith(("list:", "stock:", "pick:"))):
        raise S.ApiError(400, "Choose which stocks to watch.")
    if scope.startswith("stock:"):
        sym = S.clean_symbol(scope[6:])
        if not sym:
            raise S.ApiError(400, "Enter an NSE symbol.")
        scope = "stock:" + sym
    when = body.get("when") if body.get("when") in WHEN else CAT[what][6]
    if what == "summary":
        when = "time"
    tm = str(body.get("time") or "16:00")
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", tm):
        raise S.ApiError(400, "Time must look like 16:00.")
    days = sorted({int(x) for x in (body.get("days") or [0, 1, 2, 3, 4]) if str(x).isdigit() and 0 <= int(x) <= 6}) or [0, 1, 2, 3, 4]
    repeat = body.get("repeat") if body.get("repeat") in REPEAT else "daily"
    return {"id": (old or {}).get("id") or secrets.token_hex(5), "name": name, "what": what, "params": vals, "scope": scope,
            "when": when, "time": tm, "days": days, "repeat": repeat, "note": str(body.get("note") or "").strip()[:200],
            "on": bool(body.get("on", True)), "created": (old or {}).get("created") or S.now_ist().strftime("%Y-%m-%d %H:%M"),
            "last": (old or {}).get("last")}


def save(body):
    act = body.get("action") or "save"
    with S._state_lock:
        st = S.load_state()
        d = _data(st)
        rid = body.get("id")
        old = next((r for r in d["rules"] if r["id"] == rid), None) if rid else None
        if act == "delete":
            if not old:
                raise S.ApiError(404, "That notification no longer exists.")
            d["rules"].remove(old)
            d["mem"].pop(rid, None)
            msg = "Deleted: %s." % old["name"]
        elif act == "toggle":
            if not old:
                raise S.ApiError(404, "That notification no longer exists.")
            old["on"] = bool(body.get("on"))
            msg = "%s: switched %s." % (old["name"], "on" if old["on"] else "off")
        else:
            r = _clean(body.get("rule") or {}, old)
            if old:
                d["rules"][d["rules"].index(old)] = r
                d["mem"].pop(r["id"], None)   # settings changed: start fresh
                msg = "Saved: %s." % r["name"]
            else:
                if len(d["rules"]) >= MAX_RULES:
                    raise S.ApiError(400, "Up to %d of your own notifications." % MAX_RULES)
                d["rules"].append(r)
                msg = "Added: %s. It checks %s." % (r["name"], _when_text(r).lower())
        S.save_state(st)
    return {"ok": True, "message": msg}


def _when_text(r):
    if r["when"] == "time":
        days = r.get("days") or []
        dtxt = "every day" if len(days) == 7 else "weekdays" if days == [0, 1, 2, 3, 4] else ", ".join(DAYS[i] for i in days)
        return "At %s, %s" % (r["time"], dtxt)
    return WHEN[r["when"]]


# ----------------------------------------------------------------- data
def _ind(sym):
    hit = _ind_cache.get(sym)
    if hit and time.time() - hit[0] < 240:
        return hit[1]
    try:
        bars = L.history(sym)["bars"]
        ind = L.indicators(bars) if len(bars) > 30 else None
    except Exception:  # noqa: BLE001
        ind = None
    _ind_cache[sym] = (time.time(), ind)
    return ind


def _snap():
    with LG._lock:
        d = LG._load()
    snaps = d.get("snapshots") or {}
    return snaps[sorted(snaps)[-1]] if snaps else None


def _holdings():
    """Your Zerodha holdings (quantity and buy price from the last snapshot) at today's prices."""
    snap = _snap()
    out = {}
    for r in (snap or {}).get("holdings") or []:
        sym, qty, avg = r.get("symbol"), r.get("qty") or 0, r.get("avg")
        if not sym or qty <= 0:
            continue
        ind = _ind(sym)
        price = ind["c"][-1] if ind else r.get("ltp")
        prev = ind["c"][-2] if ind and len(ind["c"]) > 1 else None   # last session's close (in market hours: today vs yesterday)
        if not price:
            continue
        out[sym] = {"symbol": sym, "qty": qty, "avg": avg, "price": price, "prev": prev, "value": qty * price,
                    "pnl": (price - avg) * qty if avg else None, "pnl_pct": (price / avg - 1) * 100 if avg else None,
                    "day_pct": (price / prev - 1) * 100 if prev else None, "day_pnl": (price - prev) * qty if prev else None,
                    "sector": r.get("sector") or S.UNIVERSE.get(sym, {}).get("industry") or "Other",
                    "stop": r.get("trail_stop") or r.get("rule_stop")}
    return out


def _symbols(scope, hold):
    if scope == "holdings":
        return list(hold)
    if scope == "all":
        return list(S.NAMES)
    if scope.startswith("stock:"):
        return [scope[6:]]
    if scope.startswith("pick:"):
        return [s for s in scope[5:].split(",") if s]
    if scope.startswith("list:"):
        for x in ML.get_lists()["lists"]:
            if x["id"] == scope[5:]:
                return list(x["symbols"])
    return []


def _rs(v):
    return ("−" if v < 0 else "") + "₹" + format(int(round(abs(v))), ",")


def _px(v):
    return "₹" + format(v, ",.2f")


def _today_pct(ind):
    if not ind or len(ind["c"]) < 2:
        return None
    return (ind["c"][-1] / ind["c"][-2] - 1) * 100


# ----------------------------------------------------------------- the checks: each returns [(key, text)]
def evaluate(r, mem):
    """What this notification would say right now. mem keeps what a check needs to remember (last verdict, peak)."""
    what, p = r["what"], r["params"]
    hold = _holdings()
    syms = _symbols(r["scope"], hold)
    x = p.get("x")
    hits = []

    def hd(sym):
        return hold.get(sym)

    def dir_ok(v, d):
        return v is not None and ((d == "up" and v >= 0) or (d == "down" and v <= 0) or d == "either")

    if what in ("h_profit_pct", "h_profit_rs", "h_loss_pct", "h_loss_rs", "h_flip", "h_day_pct", "h_day_rs", "h_near_stop"):
        for s in syms:
            h = hd(s)
            if not h:
                continue
            tail = "%g shares at %s · buy %s · %s (%+.1f%%)" % (h["qty"], _px(h["price"]), _px(h["avg"]) if h["avg"] else "?",
                                                         _rs(h["pnl"]) if h["pnl"] is not None else "?", h["pnl_pct"] or 0)
            if what == "h_profit_pct" and h["pnl_pct"] is not None and h["pnl_pct"] >= x:
                hits.append((s, "🟢 %s profit %+.1f%% (at least %g%%) · %s" % (s, h["pnl_pct"], x, tail)))
            elif what == "h_profit_rs" and h["pnl"] is not None and h["pnl"] >= x:
                hits.append((s, "🟢 %s profit %s (at least %s) · %s" % (s, _rs(h["pnl"]), _rs(x), tail)))
            elif what == "h_loss_pct" and h["pnl_pct"] is not None and h["pnl_pct"] <= -x:
                hits.append((s, "🔴 %s is %.1f%% below your buy price (limit %g%%) · %s" % (s, -h["pnl_pct"], x, tail)))
            elif what == "h_loss_rs" and h["pnl"] is not None and h["pnl"] <= -x:
                hits.append((s, "🔴 %s loss %s (limit %s) · %s" % (s, _rs(-h["pnl"]), _rs(x), tail)))
            elif what == "h_flip" and h["pnl"] is not None:
                now = "profit" if h["pnl"] >= 0 else "loss"
                was = mem.setdefault("side", {}).get(s)
                mem["side"][s] = now
                if was and was != now and (p["dir"] == "either" or p["dir"] == "to_" + now):
                    hits.append((s, "%s %s turned from %s to %s · %s" % ("🔴" if now == "loss" else "🟢", s, was, now, tail)))
            elif what == "h_day_pct" and h["day_pct"] is not None and abs(h["day_pct"]) >= x and dir_ok(h["day_pct"], p["dir"]):
                hits.append((s, "%s %s %+.1f%% today (at least %g%%) · day %s · %s" % ("🟢" if h["day_pct"] >= 0 else "🔴", s, h["day_pct"], x,
                                                                                     _rs(h["day_pnl"] or 0), tail)))
            elif what == "h_day_rs" and h["day_pnl"] is not None and abs(h["day_pnl"]) >= x and dir_ok(h["day_pnl"], p["dir"]):
                hits.append((s, "%s %s %s today (%+.1f%%, at least %s) · %s" % ("🟢" if h["day_pnl"] >= 0 else "🔴", s, _rs(h["day_pnl"]),
                                                                              h["day_pct"] or 0, _rs(x), tail)))
            elif what == "h_near_stop" and h["stop"] and h["price"] > h["stop"] and (h["price"] / h["stop"] - 1) * 100 <= x:
                hits.append((s, "🟡 %s is %.1f%% above its rule stop %s (within %g%%) · %s" % (s, (h["price"] / h["stop"] - 1) * 100,
                                                                                            _px(h["stop"]), x, tail)))
    elif what in ("h_from_peak", "h_weight"):
        if what == "h_from_peak":
            with LG._lock:
                d = LG._load()
            _, lots, _ = LG.compute(d)
        tv = sum(h["value"] for h in hold.values()) or 1
        for s in syms:
            h = hd(s)
            if not h:
                continue
            if what == "h_weight":
                w = h["value"] / tv * 100
                if w > x:
                    hits.append((s, "⚖ %s is %.1f%% of your holdings (%s of %s; limit %g%%)." % (s, w, _rs(h["value"]), _rs(tv), x)))
                continue
            ind = _ind(s)
            if not ind:
                continue
            dated = [l["date"] for l in lots.get(s) or [] if l.get("date")]
            since = min(dated) if dated else None
            k0 = ind["idx"].get(since) if since else None
            if k0 is None and since:
                k0 = next((i for i, dd in enumerate(ind["d"]) if dd >= since), None)
            if k0 is None:
                k0 = max(0, len(ind["c"]) - 252)
            closes = ind["c"][k0:]
            peak = max(closes)
            fall = (1 - h["price"] / peak) * 100 if peak else 0
            if fall >= x:
                at = ind["d"][k0 + closes.index(peak)]
                hits.append((s, "🔻 %s is %.1f%% below its peak close %s (%s)%s · limit %g%% · %g shares at %s · %s vs buy" % (
                    s, fall, _px(peak), at, "" if dated else ", last 12 months", x, h["qty"], _px(h["price"]),
                    _rs(h["pnl"]) if h["pnl"] is not None else "?")))
    elif what == "h_deal":
        seen = mem.setdefault("deals", {})
        want = set(syms)
        try:
            rows = S.deals()["rows"]
        except Exception:  # noqa: BLE001
            rows = []
        cutoff = (S.now_ist().date() - timedelta(days=5)).isoformat()
        for r_ in rows:
            if r_["symbol"] not in want or r_["date"] < cutoff or (p["side"] != "any" and r_["side"] != p["side"]):
                continue
            key = "%s|%s|%s|%s|%s" % (r_["date"], r_["kind"], r_["symbol"], r_["client"], r_["qty"])
            if key in seen:
                continue
            seen[key] = r_["date"]
            hits.append(("deal:" + key, "%s %s %s deal %s: %s %s %s shares at %s (%s)" % (
                "🟢" if r_["side"] == "BUY" else "🔴", r_["symbol"], r_["kind"], r_["date"], r_["client"], r_["side"].lower() + "s",
                format(int(r_["qty"]), ","), _px(r_["price"]), _rs(r_["value"]))))
        for k in [k for k, v in seen.items() if v < cutoff]:
            seen.pop(k)
    elif what in ("nifty_move", "nifty_level", "vix"):
        try:
            _, by = R._quotes()
        except Exception:  # noqa: BLE001
            by = {}
        n, v = by.get("NIFTY 50"), by.get("INDIA VIX")
        if what == "nifty_move" and n and n.get("pct") is not None and abs(n["pct"]) >= x and dir_ok(n["pct"], p["dir"]):
            hits.append(("nifty", "%s Nifty 50 %s, %+.2f%% today (alert at %g%%)." % ("🟢" if n["pct"] >= 0 else "🔴", format(n["price"], ",.2f"), n["pct"], x)))
        elif what == "nifty_level" and n and n.get("price") and x and ((p["dir"] == "above" and n["price"] >= x) or (p["dir"] == "below" and n["price"] <= x)):
            hits.append(("nifty", "%s Nifty 50 %s, %s your level %s (%+.2f%% today)." % ("🟢" if p["dir"] == "above" else "🔴", format(n["price"], ",.2f"),
                                                                                    "at or above" if p["dir"] == "above" else "at or below", format(x, ",.0f"), n.get("pct") or 0)))
        elif what == "vix" and v and v.get("price") and v["price"] > x:
            hits.append(("vix", "⚠️ India VIX %.2f, above %g (%+.1f%% today): expect wider swings." % (v["price"], x, v.get("pct") or 0)))
    elif what == "h_long_soon":
        with LG._lock:
            d = LG._load()
        _, lots, _ = LG.compute(d)
        today = S.now_ist().date()
        for s in syms:
            if s not in hold:
                continue
            for lot in lots.get(s) or []:
                lg, anniv = LG._is_long(lot["date"], today.isoformat())
                if lg is False:
                    days = (anniv + timedelta(days=1) - today).days
                    if 0 <= days <= x:
                        gain = (hold[s]["price"] - lot["price"]) * lot["qty"]
                        hits.append(("%s:%s" % (s, lot["date"]), "🗓 %s: %g shares (bought %s) turn long-term on %s, in %d days · gain %s. "
                                     "A sale before then is taxed 20%%, after it 12.5%%." % (s, lot["qty"], lot["date"],
                                                                                         (anniv + timedelta(days=1)).isoformat(), days, _rs(gain))))
    elif what == "h_results_soon":
        for s in syms:
            if s not in hold:
                continue
            due = ML._results_due(s)
            if due and 0 <= due["days"] <= x:
                hits.append(("%s:%s" % (s, due["date"]), "📅 %s: quarterly results expected around %s (in %d days, estimate). The price can gap." % (
                    s, due["date"], due["days"])))
    elif what in ("p_day_rs", "p_drawdown", "p_over_cap", "p_sector"):
        rows = list(hold.values())
        if not rows:
            return []
        tv = sum(h["value"] for h in rows)
        if what == "p_day_rs":
            dp = sum(h["day_pnl"] or 0 for h in rows)
            if abs(dp) >= x and dir_ok(dp, p["dir"]):
                best = max(rows, key=lambda h: h["day_pnl"] or 0)
                worst = min(rows, key=lambda h: h["day_pnl"] or 0)
                hits.append(("all", "%s All holdings %s today (%+.2f%% of %s) · best %s %s · worst %s %s" % (
                    "🟢" if dp >= 0 else "🔴", _rs(dp), dp / (tv - dp) * 100 if tv - dp else 0, _rs(tv),
                    best["symbol"], _rs(best["day_pnl"] or 0), worst["symbol"], _rs(worst["day_pnl"] or 0))))
        elif what == "p_drawdown":
            peak = max(mem.get("peak") or 0, tv)
            mem["peak"] = peak
            fall = (1 - tv / peak) * 100 if peak else 0
            if fall >= x:
                hits.append(("all", "🔴 Your holdings are worth %s, %.1f%% below their highest %s (limit %g%%)." % (_rs(tv), fall, _rs(peak), x)))
        elif what == "p_over_cap":
            cfg = L.settings_for("invest")
            core = LG.core_symbols()
            for h in rows:
                if h["symbol"] not in core and h["value"] > cfg["max_per_stock"]:
                    hits.append((h["symbol"], "⚖ %s is worth %s, over your %s per-stock limit by %s." % (
                        h["symbol"], _rs(h["value"]), _rs(cfg["max_per_stock"]), _rs(h["value"] - cfg["max_per_stock"]))))
        elif what == "p_sector":
            cfg = L.settings_for("invest")
            core = LG.core_symbols()
            secs = {}
            for h in rows:
                if h["symbol"] not in core and h["sector"] != "Other":
                    secs.setdefault(h["sector"], []).append(h)
            for sec, hs in secs.items():
                v = sum(h["value"] for h in hs)
                if len(hs) > cfg["max_per_sector"] or v / tv * 100 > 25:
                    hits.append((sec, "⚖ %s: %d stocks, %.0f%% of your holdings (limits: %d stocks, 25%%) · %s" % (
                        sec, len(hs), v / tv * 100, cfg["max_per_sector"], ", ".join(h["symbol"] for h in hs))))
    elif what in ("price_above", "price_below", "day_pct", "cross_ma", "high52", "vol_spike", "rsi", "from_dayhigh", "gap_open"):
        today = S.now_ist().date().isoformat()
        for s in syms[:260]:
            ind = _ind(s)
            if not ind or len(ind["c"]) < 2:
                continue
            c, c1 = ind["c"][-1], ind["c"][-2]
            dp = _today_pct(ind)
            base = "%s %s (%+.1f%% today)" % (s, _px(c), dp or 0)
            if what == "from_dayhigh":
                hi = ind["h"][-1]
                if ind["d"][-1] == today and hi and (1 - c / hi) * 100 >= x:
                    hits.append((s, "🔻 %s · %.1f%% below today's high %s" % (base, (1 - c / hi) * 100, _px(hi))))
                continue
            if what == "gap_open":
                o = ind["o"][-1]
                g = (o / c1 - 1) * 100 if o and c1 else None
                if ind["d"][-1] == today and g is not None and abs(g) >= x and dir_ok(g, p["dir"]):
                    hits.append((s, "%s %s opened %+.1f%% vs yesterday's close %s (at %s) · now %s (%+.1f%% today)" % (
                        "🟢" if g >= 0 else "🔴", s, g, _px(c1), _px(o), _px(c), dp or 0)))
                continue
            if what == "price_above" and x and c >= x:
                hits.append((s, "🟢 %s · at or above %s" % (base, _px(x))))
            elif what == "price_below" and x and c <= x:
                hits.append((s, "🔴 %s · at or below %s" % (base, _px(x))))
            elif what == "day_pct" and dp is not None and abs(dp) >= x and dir_ok(dp, p["dir"]):
                hits.append((s, "%s %s · moved at least %g%%" % ("🟢" if dp >= 0 else "🔴", base, x)))
            elif what == "cross_ma":
                key = "sma" + p["ma"]
                m, m1 = ind[key][-1], ind[key][-2]
                if m and m1:
                    up, down = c1 <= m1 and c > m, c1 >= m1 and c < m
                    if (up and p["dir"] in ("up", "either")) or (down and p["dir"] in ("down", "either")):
                        hits.append((s, "%s %s · crossed %s its %s-day average %s" % ("🟢" if up else "🔴", base, "above" if up else "below",
                                                                                     p["ma"], _px(m))))
            elif what == "high52":
                hi, lo = max(ind["h"][-253:-1]), min(ind["l"][-253:-1])
                if p["dir"] == "high" and c > hi:
                    hits.append((s, "🟢 %s · new 52-week high (old high %s)" % (base, _px(hi))))
                elif p["dir"] == "low" and c < lo:
                    hits.append((s, "🔴 %s · new 52-week low (old low %s)" % (base, _px(lo))))
            elif what == "vol_spike":
                va = ind["vavg50"][-2] or ind["vavg50"][-1]
                if va and ind["v"][-1] >= x * va:
                    hits.append((s, "📊 %s · volume %.1f× its 50-day average" % (base, ind["v"][-1] / va)))
            elif what == "rsi":
                rv, rv1 = ind["rsi"][-1], ind["rsi"][-2]
                if rv is not None and rv1 is not None:
                    if p["dir"] == "below" and rv < x <= rv1:
                        hits.append((s, "🔴 %s · RSI fell below %g (now %.0f)" % (base, x, rv)))
                    elif p["dir"] == "above" and rv > x >= rv1:
                        hits.append((s, "🟢 %s · RSI rose above %g (now %.0f)" % (base, x, rv)))
    elif what == "verdict":
        mkt = L.market()
        seen = mem.setdefault("verdict", {})
        names = {"buy": "Buy", "hold": "Hold", "weak": "Weak", "exit": "Exit"}
        for s in syms[:260]:
            ind = _ind(s)
            if not ind or len(ind["c"]) < 260:
                continue
            try:
                v = K._verdict(ind, mkt, "invest")
            except Exception:  # noqa: BLE001
                continue
            was, now = seen.get(s), v["verdict"]
            seen[s] = now
            if was and was != now and p["to"] in ("any", now):
                hits.append(("%s:%s" % (s, now), "%s %s: Investing verdict %s → %s (%s) · %s" % (
                    {"exit": "🔴", "weak": "🟡", "buy": "🟢", "hold": "⚪"}[now], s, names[was], names[now], v.get("why") or "",
                    _px(ind["c"][-1]))))
    elif what == "summary":
        if p["what"] == "holdings":
            rows = list(hold.values())
            if rows:
                tv = sum(h["value"] for h in rows)
                dp = sum(h["day_pnl"] or 0 for h in rows)
                pn = sum(h["pnl"] or 0 for h in rows)
                rows.sort(key=lambda h: -(h["day_pnl"] or 0))
                txt = ["📋 My holdings: %s · today %s · total %s" % (_rs(tv), _rs(dp), _rs(pn))]
                txt += ["  🟢 %s %s (%+.1f%%)" % (h["symbol"], _rs(h["day_pnl"] or 0), h["day_pct"] or 0) for h in rows[:3] if (h["day_pnl"] or 0) > 0]
                txt += ["  🔴 %s %s (%+.1f%%)" % (h["symbol"], _rs(h["day_pnl"] or 0), h["day_pct"] or 0) for h in rows[::-1][:3] if (h["day_pnl"] or 0) < 0]
                hits.append(("summary", "\n".join(txt)))
        elif p["what"] == "nifty":
            n = L.market().ind
            c, c1, m50, m200 = n["c"][-1], n["c"][-2], n["sma50"][-1], n["sma200"][-1]
            hits.append(("summary", "📈 Nifty 50 %s (%+.2f%% today) · %s its 50-day (%s) · %s its 200-day (%s)" % (
                format(c, ",.0f"), (c / c1 - 1) * 100, "above" if c > m50 else "below", format(m50, ",.0f"),
                "above" if c > m200 else "below", format(m200, ",.0f"))))
        else:
            lines = []
            for s in syms[:30]:
                ind = _ind(s)
                if ind:
                    lines.append("  %s %s (%+.1f%%)" % (s, _px(ind["c"][-1]), _today_pct(ind) or 0))
            if lines:
                hits.append(("summary", "📋 Your stocks:\n" + "\n".join(lines)))
    elif what == "news_kw":
        kw = (p.get("kw") or "").lower()
        seen = mem.setdefault("news", {})
        for s in syms[:25]:
            try:
                items = S.news(s).get("items") or []
            except Exception:  # noqa: BLE001
                continue
            for it in items[:8]:
                if kw and kw not in it["title"].lower():
                    continue
                if it["id"] in seen:
                    continue
                seen[it["id"]] = S.now_ist().date().isoformat()
                hits.append(("news:" + it["id"], "📰 %s: %s (%s)\n%s" % (s, it["title"], it.get("source") or "", it.get("link") or "")))
        for k in [k for k, v in seen.items() if v < (S.now_ist().date() - timedelta(days=10)).isoformat()]:
            seen.pop(k)
    return hits


# ----------------------------------------------------------------- when to check, and sending
def _due(r, last_run, now):
    m = now.hour * 60 + now.minute
    today = now.date().isoformat()
    if r["when"] == "time":
        hh, mm = map(int, r["time"].split(":"))
        at = hh * 60 + mm
        return now.weekday() in r.get("days", []) and at <= m < at + 30 and (last_run or "")[:10] != today
    if not R.is_trading_day():
        return False
    if r["when"] == "close":
        return m >= 940 and (last_run or "")[:10] != today
    return 555 <= m <= 930 and (not last_run or time.time() - (r.get("_last_ts") or 0) >= MARKET_EVERY)


def _send(r, hits, test=False):
    head = "%s🔔 %s" % ("🧪 Test · " if test else "", r["name"])
    body = "\n".join(h[1] for h in hits[:15])
    if len(hits) > 15:
        body += "\n…and %d more." % (len(hits) - 15)
    tail = ("\n📝 " + r["note"]) if r.get("note") else ""
    T.notify("custom", "%s\n%s%s" % (head, body, tail))


def run_rule(r, mem, now, test=False):
    """Check one notification; returns the lines it sent (or would send)."""
    hits = evaluate(r, mem)
    if test:
        return hits
    seen = mem.setdefault("rung", {})
    today = now.date().isoformat()
    fresh = []
    for key, text in hits:
        last = seen.get(key)
        if r["repeat"] == "daily" and last and last[:10] == today:
            continue
        if r["repeat"] == "every" and last and time.time() - float(last[11:] or 0) < MIN_GAP:
            continue
        fresh.append((key, text))
        seen[key] = "%s %s" % (today, time.time())
    for k in [k for k, v in seen.items() if v[:10] < (now.date() - timedelta(days=30)).isoformat()]:
        seen.pop(k)
    if fresh:
        _send(r, fresh)
    return fresh


def tick():
    """Called by the Telegram watcher every 30 s; does the work in the background, one run at a time."""
    if not _run_lock.acquire(blocking=False):
        return
    threading.Thread(target=_tick_bg, name="custom-notes", daemon=True).start()


_last_ts = {}


def _tick_bg():
    try:
        st = S.load_state()
        rules = [r for r in _data(st)["rules"] if r.get("on")]
        if not rules:
            return
        now = S.now_ist()
        updates = {}
        for r in rules:
            r["_last_ts"] = _last_ts.get(r["id"])
            if not _due(r, r.get("last"), now):
                continue
            mem = dict(_data(st)["mem"].get(r["id"]) or {})
            try:
                fresh = run_rule(r, mem, now)
            except Exception as e:  # noqa: BLE001
                fresh = None
                mem["error"] = str(e)[:200]
            else:
                mem.pop("error", None)
            _last_ts[r["id"]] = time.time()
            updates[r["id"]] = (mem, bool(fresh))
        if not updates:
            return
        with S._state_lock:
            st = S.load_state()
            d = _data(st)
            for r in d["rules"]:
                if r["id"] in updates:
                    mem, rang = updates[r["id"]]
                    d["mem"][r["id"]] = mem
                    r["last"] = now.strftime("%Y-%m-%d %H:%M")
                    if rang:
                        r["rang"] = now.strftime("%Y-%m-%d %H:%M")
                        if r["repeat"] == "once":
                            r["on"] = False
                    r["error"] = mem.get("error")
            S.save_state(st)
    finally:
        _run_lock.release()


def test(body):
    """Check a notification now (saved or not yet saved), ignoring its time and repeat, and send the result."""
    r = _clean(body.get("rule") or {}, None)
    hits = run_rule(r, {}, S.now_ist(), test=True)
    if hits:
        _send(r, hits, test=True)
        return {"ok": True, "lines": [h[1] for h in hits[:15]], "n": len(hits),
                "message": "%d match%s right now: sent to Telegram as a test." % (len(hits), "" if len(hits) == 1 else "es")}
    T.notify("custom", "🧪 Test · 🔔 %s\nNothing matches right now. It will message you when it does (%s)." % (r["name"], _when_text(r).lower()))
    note = " (changes like crossings, flips and verdicts need two checks in a row)" if r["what"] in ("h_flip", "verdict", "p_drawdown") else ""
    return {"ok": True, "lines": [], "n": 0, "message": "Nothing matches right now%s. A test message was sent to Telegram." % note}
