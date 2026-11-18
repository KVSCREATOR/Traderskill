"""Paper GTT (Good Till Triggered) orders for all three modes.

Set a buy while the market is closed: "buy when the price reaches X". The order rests until
a later bar touches the trigger, then the paper broker buys at the trigger (or at the open,
if the price gaps through it), sized and risk-checked with the same rules as a normal order.

- Trading / Investing: checked on daily bars from the next session on; the stop is set by the
  mode's ATR rule from the fill price; the order stays valid for up to 1 year (as with a broker GTT).
- Scalping: checked on 5-minute bars inside your entry window, valid for one session only;
  the stop and target are the ones you set, and the position is squared off at 15:15 as usual.

Paper only. No real order is ever sent.
"""
import hashlib
import math
import time
from datetime import date, datetime, timedelta

S = None   # server module
L = None   # longterm module

VALID_DAYS = 365


def _new_id(sym):
    return hashlib.sha1(("gtt%s%f" % (sym, time.time())).encode()).hexdigest()[:10]


def _orders(st):
    return st.setdefault("gtt", [])


def place(mode, body):
    if body.get("confirm") is not True:
        raise S.ApiError(400, "GTT not confirmed.")
    sym = S.clean_symbol(body.get("symbol"))
    try:
        trigger = float(body.get("trigger"))
    except (TypeError, ValueError):
        raise S.ApiError(400, "Enter a trigger price.")
    if trigger <= 0:
        raise S.ApiError(400, "The trigger price must be above zero.")
    stop = body.get("stop")
    target = body.get("target")
    stop = float(stop) if stop not in (None, "") else None
    target = float(target) if target not in (None, "") else None
    qty = body.get("qty")
    try:
        qty = int(qty) if qty not in (None, "") else None
    except (TypeError, ValueError):
        raise S.ApiError(400, "Quantity must be a whole number of shares.")
    if qty is not None and qty < 1:
        raise S.ApiError(400, "Quantity must be at least 1 share (or leave it blank to size by your limits).")
    if mode == "intraday":
        if stop is None or target is None:
            raise S.ApiError(400, "Scalping GTTs need a stop and a target.")
        if not stop < trigger < target:
            raise S.ApiError(400, "Need stop < trigger < target.")
    elif stop is not None and stop >= trigger:
        raise S.ApiError(400, "The stop must be below the trigger.")
    try:
        last = S.quote(sym)["price"]
    except Exception:  # noqa: BLE001
        last = None
    clk = S.market_clock()
    now = S.now_ist()
    order = {"id": _new_id(sym), "mode": mode, "symbol": sym, "trigger": round(trigger, 2),
             "direction": "above" if last is None or trigger >= last else "below", "price_at_set": last,
             "stop": stop, "target": target, "qty": qty, "created": int(time.time()), "created_date": clk["date"],
             "created_at": clk["ist"], "status": "active", "note": "",
             "expires": (now + timedelta(days=VALID_DAYS)).date().isoformat() if mode != "intraday" else None,
             "session": None}
    with S._state_lock:
        st = S.load_state()
        orders = _orders(st)
        if any(o["status"] == "active" and o["mode"] == mode and o["symbol"] == sym for o in orders):
            raise S.ApiError(409, "There is already an active GTT for %s in this mode. Cancel it first." % sym)
        orders.append(order)
        S.save_state(st)
    try:   # confirmation on Telegram, with Zerodha's GTT page to set the same order for real yourself
        mlabel = {"intraday": "Scalping", "swing": "Trading", "invest": "Investing"}.get(mode, mode)
        S.telegram.notify("gtt", "\n".join([
            "🎯 GTT saved (paper, %s): BUY %s %s when the price %s %s" % (
                mlabel, ("%d ×" % qty) if qty else "(sized at the fill)", sym,
                "rises to" if order["direction"] == "above" else "falls to", S.telegram._rs(trigger, 2)),
            "Stop %s%s · valid %s" % (S.telegram._rs(stop, 2) if stop else "by the rules",
                                     (" · target " + S.telegram._rs(target, 2)) if target else "",
                                     "this session" if mode == "intraday" else "1 year"),
            "To place the same GTT in your real account, open Zerodha (sign in if asked) → GTT:",
            "https://kite.zerodha.com/orders/gtt",
            "The portal itself never places real orders."]))
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "order": order}


def cancel(oid):
    with S._state_lock:
        st = S.load_state()
        for o in _orders(st):
            if o["id"] == oid and o["status"] == "active":
                o["status"], o["note"] = "cancelled", "Cancelled by you"
                o["closed_at"] = S.market_clock()["ist"]
                S.save_state(st)
                return {"ok": True}
    raise S.ApiError(404, "Active GTT not found.")


def _hit(o, b_o, b_h, b_l):
    """Fill price if this bar touches the trigger, else None."""
    t = o["trigger"]
    if o["direction"] == "above" and b_h >= t:
        return max(b_o, t)
    if o["direction"] == "below" and b_l <= t:
        return min(b_o, t)
    return None


def _check_long(st, o, clk):
    mode = o["mode"]
    if o["expires"] and clk["date"] > o["expires"]:
        o["status"], o["note"] = "expired", "Not triggered within a year"
        return
    ind = L.indicators(L.history(o["symbol"])["bars"])
    n = len(ind["d"])
    for k in range(1, n):
        if ind["d"][k] <= o["created_date"]:
            continue
        if o["direction"] == "above":
            # the rules' breakout: a DAILY CLOSE at or above the trigger, bought at the NEXT open
            # (exactly how the backtest trades), and not if that open has run too far
            if ind["c"][k] < o["trigger"] or (clk["open"] and ind["d"][k] == clk["date"]):
                continue
            if k + 1 >= n:
                o["note"] = "Closed above %.2f on %s; buys at the next open" % (o["trigger"], ind["d"][k])
                return
            j, fill, atr_i = k + 1, ind["o"][k + 1], k
            if fill > ind["c"][k] * (1 + L.RULES[mode]["max_ext"]):
                o.update(status="rejected", triggered_date=ind["d"][j],
                         note="Opened %.2f on %s, more than %.0f%% above the signal close: the rules do not chase" % (
                             fill, ind["d"][j], L.RULES[mode]["max_ext"] * 100))
                return
        else:
            fill = _hit(o, ind["o"][k], ind["h"][k], ind["l"][k])   # dip buy: a price order, fills on touch
            if fill is None:
                continue
            j, atr_i = k, k - 1
        day = ind["d"][j]
        cfg = L.settings_for(mode, st)
        stop = o["stop"] if o["stop"] is not None else L.stop_for(mode, fill, ind["atr"][atr_i])
        if fill <= stop:
            o.update(status="rejected", note="Opened at or below the stop on %s" % day, triggered_date=day)
            return
        target = L.target_for(mode, fill, stop)
        size = L.size_long(fill, stop, target, cfg)
        if o.get("qty"):
            size["qty"] = int(o["qty"])
        rc = L.risk_long(o["symbol"], size["qty"], fill, stop, mode, st)
        bad = [c for c in rc["checks"] if not c["ok"] and c["name"] != "Market open"]
        if bad:
            o.update(status="rejected", triggered_date=day,
                     note="Triggered %s but risk check BLOCK: %s" % (day, "; ".join(c["name"] + " - " + c["detail"] for c in bad)))
            return
        paper = L._paper(st, mode)
        hold = L.RULES[mode]["hold"]
        until = (date.fromisoformat(day) + timedelta(days=math.ceil(hold * 365 / 248))).isoformat()
        pos = {"id": "%s%d" % (o["symbol"][:6], int(time.time() * 1000) % 10 ** 8), "symbol": o["symbol"], "qty": size["qty"],
               "entry": fill, "stop": stop, "stop0": stop, "R": fill - stop, "target": target, "opened_date": day,
               "opened_at": day + " (GTT)", "sector": S.UNIVERSE.get(o["symbol"], {}).get("industry", ""),
               "setup": "GTT %s %.2f" % ("above" if o["direction"] == "above" else "below", o["trigger"]),
               "last": fill, "pnl": 0.0, "held": 0, "hold_until": until}
        paper["cash"] -= fill * size["qty"] * (1 + L.COST_SIDE)
        paper["positions"].append(pos)
        o.update(status="triggered", triggered_date=day, fill=fill, qty=size["qty"], stop_used=stop,
                 note="Bought %d at %.2f on %s" % (size["qty"], fill, day))
        return


def _check_intraday(st, o, clk):
    s = st["settings"]
    a, b = S.parse_hm(s["entry_start"], 570), S.parse_hm(s["entry_end"], 870)
    q = S.quote(o["symbol"])
    for bar in q["bars"]:
        if bar["t"] < o["created"]:
            continue
        d = datetime.fromtimestamp(bar["t"], S.IST)
        day, m = d.date().isoformat(), S.mins(d)
        if o["session"] is None:
            o["session"] = day
        if day != o["session"] or m < a or m > b:
            continue
        if o["direction"] == "above":
            # the opening-range rule: a completed 5-minute bar must CLOSE at or above the trigger
            if bar["c"] < o["trigger"] or bar["t"] + 300 > time.time():
                continue
            fill = bar["c"]
        else:
            fill = _hit(o, bar["o"], bar["h"], bar["l"])
            if fill is None:
                continue
        if fill <= o["stop"] or fill >= o["target"]:
            o.update(status="rejected", note="Gapped past the stop or target at %s" % S.hm(m), triggered_date=day)
            return
        size = S.size_position(fill, o["stop"], s)
        if o.get("qty"):
            size["qty"] = int(o["qty"])
        rc = S.risk_check(o["symbol"], size["qty"], fill, o["stop"], st)
        bad = [c for c in rc["checks"] if not c["ok"] and c["name"] != "Entry window"]
        if bad:
            o.update(status="rejected", triggered_date=day,
                     note="Triggered %s but risk check BLOCK: %s" % (S.hm(m), "; ".join(c["name"] + " - " + c["detail"] for c in bad)))
            return
        pos = {"id": S.hashlib.sha1(("%s%f" % (o["symbol"], time.time())).encode()).hexdigest()[:10], "symbol": o["symbol"],
               "qty": size["qty"], "entry": fill, "stop": o["stop"], "target": o["target"], "opened": bar["t"],
               "opened_date": day, "opened_at": "%s %s (GTT)" % (day, S.hm(m)), "last": fill, "pnl": 0.0}
        st["paper"]["cash"] -= fill * size["qty"]
        st["paper"]["positions"].append(pos)
        o.update(status="triggered", triggered_date=day, fill=fill, qty=size["qty"],
                 note="Bought %d at %.2f at %s" % (size["qty"], fill, S.hm(m)))
        return
    # one session only: expire once that session's entry window has passed
    sess = o["session"]
    if sess and (clk["date"] > sess or (clk["date"] == sess and clk["minute"] > b)):
        o["status"], o["note"] = "expired", "Not triggered in the %s session" % sess


def check(mode=None):
    """Work every active GTT (of one mode, or all). Safe to call often."""
    with S._state_lock:
        st = S.load_state()
        clk = S.market_clock()
        changed = False
        for o in _orders(st):
            if o["status"] != "active" or (mode and o["mode"] != mode):
                continue
            before = dict(o)
            try:
                (_check_intraday if o["mode"] == "intraday" else _check_long)(st, o, clk)
            except Exception:  # noqa: BLE001  (no data right now: try again next time)
                pass
            if o != before:
                o.setdefault("closed_at", clk["ist"] if o["status"] != "active" else None)
                changed = True
                if before["status"] == "active" and o["status"] != "active":
                    try:
                        msg = ("bought %s %s at %.2f" % (o.get("qty"), o["symbol"], o["fill"])) if o["status"] == "triggered" and o.get("fill")                             else "%s %s · %s" % (o["symbol"], o["status"], o.get("note") or "")
                        S.telegram.notify("paper", "%s Paper GTT (%s): %s" % ("🟢" if o["status"] == "triggered" else "⚪",
                                                                             S.longterm.LABEL.get(o["mode"], o["mode"]), msg))
                    except Exception:  # noqa: BLE001
                        pass
        if changed:
            S.save_state(st)
        return st


def listing(mode):
    st = check(mode)
    orders = [o for o in _orders(st) if o["mode"] == mode]
    orders.sort(key=lambda o: (o["status"] != "active", -o["created"]))
    return {"mode": mode, "orders": orders[:100], "clock": S.market_clock()}
