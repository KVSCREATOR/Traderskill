"""My scanner: your own named lists of stocks, scanned with the selected mode's rules.

- Lists live in data/state.json -> "mylists" (same lists in every mode, up to 20 lists of 50).
  Any NSE symbol can be added, not only the Nifty LargeMidcap 250.
- The News page and the Telegram buy-signal message use the union of the lists
  (settings.watchlist is kept in step), so there is one list to look after.
- /api/myscan adds what the full Scanner does not show: a status (Watching / Near trigger /
  Buy zone / Holding / Exit signal), distance to the trigger, a rule plan (entry, ATR stop,
  quantity, risk check), exit levels for paper and Zerodha holdings, an estimated results
  date and the sector limit. Paper only; nothing here places an order.
"""
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

S = None   # server module
L = None   # longterm module
K = None   # kite module

MAX_LISTS, MAX_PER_LIST = 20, 50
BUY = ("confirmed", "recent", "provisional")


def _data(st):
    d = st.get("mylists")
    if not isinstance(d, dict) or not d.get("lists"):
        seed = [s for s in (st.get("settings", {}).get("watchlist") or []) if isinstance(s, str)][:MAX_PER_LIST]
        d = {"lists": [{"id": "main", "name": "My list", "symbols": seed}], "notes": {}}
        st["mylists"] = d
    d.setdefault("notes", {})
    return d


def _sync_watchlist(st, d):
    seen = []
    for lst in d["lists"]:
        for s in lst["symbols"]:
            if s not in seen:
                seen.append(s)
    st["settings"]["watchlist"] = seen[:40]


def get_lists():
    st = S.load_state()
    d = _data(st)
    return {"lists": d["lists"], "notes": d["notes"], "max_per_list": MAX_PER_LIST}


def _find(d, lid):
    for lst in d["lists"]:
        if lst["id"] == lid:
            return lst
    raise S.ApiError(404, "That list no longer exists.")


def _check_symbol(sym):
    """A typo must not end up in a list: symbols outside the 250 need a price."""
    if sym in S.NAMES:
        return
    try:
        S.quote(sym)
    except Exception:  # noqa: BLE001
        raise S.ApiError(404, "No NSE price found for %s. Check the symbol (as on NSE, e.g. KALYANKJIL)." % sym)


def update(body):
    act = body.get("action")
    lid = str(body.get("list") or "main")
    syms = body.get("symbols") if isinstance(body.get("symbols"), list) else [body.get("symbol")] if body.get("symbol") else []
    syms = [S.clean_symbol(x) for x in syms if str(x or "").strip()]
    if act in ("add", "addmany"):
        for s in syms:
            if act == "add":
                _check_symbol(s)
    with S._state_lock:
        st = S.load_state()
        d = _data(st)
        msg = ""
        if act in ("add", "addmany"):
            lst = _find(d, lid)
            added = [s for s in syms if s not in lst["symbols"]]
            room = MAX_PER_LIST - len(lst["symbols"])
            if room <= 0 and added:
                raise S.ApiError(400, "%s already has %d stocks (the most). Remove some or make another list." % (lst["name"], MAX_PER_LIST))
            lst["symbols"] += added[:room]
            msg = "Added %d to %s%s." % (min(len(added), room), lst["name"],
                                         " (%d did not fit)" % (len(added) - room) if len(added) > room else "")
        elif act == "remove":
            lst = _find(d, lid)
            lst["symbols"] = [s for s in lst["symbols"] if s not in syms]
            msg = "Removed from %s." % lst["name"]
        elif act == "create":
            name = re.sub(r"\s+", " ", str(body.get("name") or "")).strip()[:30]
            if not name:
                raise S.ApiError(400, "Give the list a name.")
            if len(d["lists"]) >= MAX_LISTS:
                raise S.ApiError(400, "You already have %d lists (the most)." % MAX_LISTS)
            if any(x["name"].lower() == name.lower() for x in d["lists"]):
                raise S.ApiError(409, "There is already a list called %s." % name)
            new = {"id": "l%x" % int(time.time() * 1000), "name": name, "symbols": []}
            d["lists"].append(new)
            lid, msg = new["id"], "List %s made." % name
        elif act == "rename":
            lst = _find(d, lid)
            name = re.sub(r"\s+", " ", str(body.get("name") or "")).strip()[:30]
            if not name:
                raise S.ApiError(400, "Give the list a name.")
            lst["name"], msg = name, "Renamed to %s." % name
        elif act == "delete":
            if len(d["lists"]) <= 1:
                raise S.ApiError(400, "Keep at least one list.")
            lst = _find(d, lid)
            d["lists"] = [x for x in d["lists"] if x["id"] != lid]
            lid, msg = d["lists"][0]["id"], "List %s deleted." % lst["name"]
        elif act == "note":
            if len(syms) != 1:
                raise S.ApiError(400, "Note needs one symbol.")
            text = str(body.get("note") or "").strip()[:200]
            if text:
                d["notes"][syms[0]] = text
            else:
                d["notes"].pop(syms[0], None)
            msg = "Note saved."
        else:
            raise S.ApiError(400, "Unknown list action.")
        _sync_watchlist(st, d)
        S.save_state(st)
    return {"ok": True, "message": msg, "list": lid, "lists": d["lists"], "notes": d["notes"]}


# ----------------------------------------------------------------- scan
def _results_due(sym):
    try:
        q = S.earnings(sym).get("quarters") or []
        if not q:
            return None
        nxt = L.next_results(q[-1]["date"])
        days = (nxt - S.now_ist().date()).days
        return {"date": nxt.isoformat(), "days": days}
    except Exception:  # noqa: BLE001
        return None


def _rows_long(mode, syms, held):
    mkt = L.market()
    full = L.scan_long(mode)   # cached 10 min: needed for the strength percentile vs the 250
    key = "rs3" if mode == "swing" else "rs6"
    vals = sorted(r[key] for r in full["rows"] if r.get(key) is not None)
    vals12 = sorted(r["mom12"] for r in full["rows"] if r.get("mom12") is not None)
    with ThreadPoolExecutor(10) as ex:
        rows = list(ex.map(lambda s: L.scan_row(mode, s, mkt, extra=True), syms))
        dues = dict(zip(syms, ex.map(_results_due, syms)))
    pf = L.portfolio_long(mode)
    cfg, st = pf["settings"], S.load_state()
    rules = L.RULES[mode]
    pos_by = {p["symbol"]: p for p in pf["positions"]}
    zitems = {x["symbol"]: x for x in (held.get("items") or [])}
    ok, failed = [], []
    for r in rows:
        if "error" in r:
            failed.append(r)
            continue
        ind = r.pop("_ind")
        L.rank_row(mode, r, vals, vals12)
        sym, price = r["symbol"], r["price"]
        r["results"] = dues.get(sym)
        r["in_250"] = sym in S.NAMES
        # plan by the rules (same as the Predictor): buy now in the buy zone, else at the trigger
        live = r["status"] in BUY
        entry = price if live else (r["trigger"] or price)
        stop = L.stop_for(mode, entry, r.get("atr"))
        size = L.size_long(entry, stop, None, cfg)
        risk = L.risk_long(sym, size["qty"], entry, stop, mode, st)
        r["plan"] = {"entry": entry, "stop": stop, "risk_ps": entry - stop, "risk_pct": (entry - stop) / entry * 100,
                     "qty": size["qty"], "cost": size["cost"], "max_loss": size["max_loss"], "limited_by": size["limited_by"],
                     "checks": [c for c in risk["checks"] if c["name"] != "Market open"],
                     "at_trigger": not live}
        r["plan"]["verdict"] = "PASS" if all(c["ok"] for c in r["plan"]["checks"]) else "BLOCK"
        r["dist_trigger"] = (r["trigger"] / price - 1) * 100 if r["trigger"] and not live else None
        sector = r["industry"]
        r["sector_held"] = sum(1 for p in pf["positions"] if sector and p.get("sector") == sector and p["symbol"] != sym)
        r["sector_max"] = cfg["max_per_sector"]
        # holdings and exits
        p = pos_by.get(sym)
        if p:
            R = p["R"] or (p["entry"] - p["stop0"])
            r["paper"] = {"qty": p["qty"], "entry": p["entry"], "stop": p["stop"], "stop0": p["stop0"], "trailing": p.get("trailing"),
                          "held": p.get("held", 0), "hold": rules["hold"], "r_now": (price - p["entry"]) / R if R else None,
                          "be_level": p["entry"] + rules["be_at"] * R, "pnl": p.get("pnl"),
                          "below200": bool(mode == "invest" and r.get("sma200") and price < r["sma200"] * 0.97)}
        if sym in zitems:
            z = dict(zitems[sym])
            try:
                z.update(K._verdict(ind, mkt, mode))
            except Exception:  # noqa: BLE001
                pass
            r["zerodha"] = z
        if r.get("zerodha", {}).get("verdict") == "exit" or (p and r["paper"]["below200"]):
            r["state"] = "exit"
        elif p or sym in zitems:
            r["state"] = "holding"
        elif live:
            r["state"] = "buy"
        elif r["dist_trigger"] is not None and r["dist_trigger"] <= 3:
            r["state"] = "near"
        else:
            r["state"] = "watching"
        for k in ("atr", "sma50", "sma200"):
            r.pop(k, None)
        ok.append(r)
    cap = {"positions": len(pf["positions"]), "max_positions": cfg["max_positions"],
           "invested": sum(p["entry"] * p["qty"] for p in pf["positions"]), "capital": cfg["capital"],
           "cash": pf["cash"], "open_risk": pf["open_risk"], "max_open_risk": cfg["max_open_risk"],
           "drawdown": pf["drawdown"], "dd_pause": cfg["dd_pause_pct"]}
    return ok, failed, cap, full.get("regime")


def _rows_intraday(syms, held):
    with ThreadPoolExecutor(10) as ex:
        rows = list(ex.map(S.scan_one, syms))
    pf = S.portfolio()
    pos = {p["symbol"]: p for p in pf.get("positions", [])}
    zs = set(held.get("symbols") or [])
    ok, failed = [], []
    for r in rows:
        if "error" in r:
            failed.append(r)
            continue
        o = r.get("orb") or {}
        r["in_250"] = r["symbol"] in S.NAMES
        if r["symbol"] in pos:
            r["state"] = "holding"
            r["paper"] = pos[r["symbol"]]
        elif o.get("state") == "confirmed" and o.get("outcome") == "open":
            r["state"] = "buy"
        elif o.get("or_high") and r.get("price") and r["price"] >= o["or_high"] * 0.99:
            r["state"] = "near"
        else:
            r["state"] = "holding" if r["symbol"] in zs else "watching"
        r["dist_trigger"] = (o["or_high"] / r["price"] - 1) * 100 if o.get("or_high") and r.get("price") and r["state"] in ("near", "watching") else None
        ok.append(r)
    st = S.load_state()["settings"]
    cap = {"positions": len(pf.get("positions", [])), "max_positions": st.get("max_trades"), "cash": pf.get("cash"),
           "budget": st.get("budget"), "max_loss": st.get("max_loss")}
    return ok, failed, cap, None


def myscan(mode, q):
    src = q.get("source") or "list"
    st = S.load_state()
    d = _data(st)
    lst = None
    for x in d["lists"]:
        if x["id"] == (q.get("list") or d["lists"][0]["id"]):
            lst = x
    lst = lst or d["lists"][0]
    try:
        held = K.held()
    except Exception:  # noqa: BLE001
        held = {"connected": False, "symbols": []}
    hs = [s for s in held.get("symbols") or [] if re.fullmatch(r"[A-Z0-9&\-]{1,20}", s)]
    syms = list(lst["symbols"]) if src in ("list", "both") else []
    if src in ("holdings", "both"):
        syms += [s for s in hs if s not in syms]
    syms = syms[:120]
    t0 = time.time()
    if not syms:
        rows, failed, cap, regime = [], [], None, None
    elif mode == "intraday":
        rows, failed, cap, regime = _rows_intraday(syms, held)
    else:
        rows, failed, cap, regime = _rows_long(mode, syms, held)
    order = {"exit": 0, "buy": 1, "near": 2, "holding": 3, "watching": 4}
    rows.sort(key=lambda r: (order.get(r["state"], 9), -(r.get("rank") or 0), r["symbol"]))
    return {"mode": mode, "source": src, "list": lst["id"], "lists": d["lists"], "notes": d["notes"],
            "held_connected": bool(held.get("connected")), "held_count": len(hs),
            "rows": rows, "failed": failed, "capacity": cap, "regime": regime, "clock": S.market_clock(),
            "scanned_at": S.now_ist().strftime("%H:%M:%S"), "scanned_ts": int(time.time()), "secs": round(time.time() - t0, 1)}


def spark(sym):
    """Last ~6 months of daily closes with the 50 / 200-day averages, for the hover chart."""
    h = L.history(sym)
    ind = L.indicators(h["bars"])
    n = 130
    return {"symbol": sym, "d": ind["d"][-n:], "c": ind["c"][-n:],
            "sma50": ind["sma50"][-n:], "sma200": ind["sma200"][-n:]}
