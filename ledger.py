"""My holdings: a permanent record of your real Zerodha account, financial year by financial year.

Where the data comes from (read-only, nothing is ever sent to Zerodha):
- Tradebook CSV from Zerodha Console (Reports -> Tradebook) that you upload once: every past buy and
  sell with its date. Duplicates are skipped (trade_id), so uploading overlapping files is safe.
- While Zerodha is connected the portal saves a snapshot (holdings, funds, today's buys and sells
  from positions) when you open My holdings and every trading day after the close. These stay in
  data/ledger.json when Zerodha is disconnected, so the last record is always there.
- Trades you add by hand (bonus shares, a transfer in, a missing day).

What it works out: lots per stock (first in, first out), same-day buy + sell = intraday, realised
profit split into short-term (held 12 months or less), long-term and intraday, an estimate of
capital-gains tax, days until each lot turns long-term, sector split, funds history and the rule
results for what to keep, sell or buy. Estimates only; Zerodha Console's Tax P&L is the official one.

The page is behind a 4-digit PIN (hashed with PBKDF2, never stored in plain text). Five wrong PINs
lock it until the portal password is entered.
"""
import csv
import hashlib
import io
import json
import os
import re
import secrets
import threading
import time
from datetime import date, datetime, timedelta

S = None   # server module
L = None   # longterm module
K = None   # kite module

_lock = threading.Lock()
_tokens = {}            # unlock token -> expiry time
_last = {"at": 0}       # last snapshot from a page open
TOKEN_SECS = 30 * 60    # one unlock covers refreshes on the page for 30 minutes
MAX_FAILS = 5
PIN_LEN = 4
DELIVERY_SIDE = 0.0012  # STT 0.1% + exchange / SEBI / stamp / GST, per side (same as the rules' costs)
DP_FEE = 15.93          # Zerodha DP charge per stock per sell day (incl. GST)
INTRADAY_COST = 0.0006  # brokerage + STT + exchange + GST + stamp, of turnover (approx.)
CESS = 0.04


def _path():
    return os.path.join(S.DATA, "ledger.json")


def _load():
    try:
        with open(_path(), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    d.setdefault("trades", {})       # id -> trade
    d.setdefault("snapshots", {})    # date -> snapshot (last one of that day)
    d.setdefault("imports", [])      # tradebook uploads: {at, file, from, to, added, skipped}
    return d


def _save(d):
    tmp = _path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, separators=(",", ":"))
    os.replace(tmp, _path())


# ----------------------------------------------------------------- PIN
def _hash(pin, salt):
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), 200000).hex()


def _pin_state(st):
    return st.get("holdings_pin") or {}


def pin_status():
    p = _pin_state(S.load_state())
    return {"set": bool(p.get("hash")), "locked": bool(p.get("locked")), "length": PIN_LEN,
            "password_needed": bool(S.PASSWORD), "tries_left": max(0, MAX_FAILS - int(p.get("fails") or 0))}


def _check_password(pw):
    if not S.PASSWORD:
        return True
    import hmac
    ok = hmac.compare_digest(str(pw or "").encode(), S.PASSWORD.encode())
    if not ok:
        time.sleep(1.5)
    return ok


def _valid_pin(pin):
    pin = str(pin or "")
    if not re.fullmatch(r"\d{%d}" % PIN_LEN, pin):
        raise S.ApiError(400, "The PIN must be exactly %d digits." % PIN_LEN)
    if len(set(pin)) == 1 or pin in ("1234", "4321", "0123", "9876"):
        raise S.ApiError(400, "Pick a PIN that is harder to guess than %s." % pin)
    return pin


def _store_pin(pin):
    salt = secrets.token_hex(16)
    with S._state_lock:
        st = S.load_state()
        st["holdings_pin"] = {"salt": salt, "hash": _hash(pin, salt), "fails": 0, "locked": False,
                              "changed": S.market_clock()["ist"]}
        S.save_state(st)
    _tokens.clear()   # every open page has to unlock again


def pin_set(body):
    """First PIN, or a new one after a lock / a forgotten PIN: needs the portal password."""
    if not _check_password(body.get("password")):
        raise S.ApiError(403, "Wrong portal password.")
    _store_pin(_valid_pin(body.get("pin")))
    return {"ok": True, "message": "PIN saved. Use it to open My holdings."}


def pin_change(body):
    p = _pin_state(S.load_state())
    if not p.get("hash"):
        raise S.ApiError(400, "No PIN set yet.")
    if p.get("locked"):
        raise S.ApiError(423, "The PIN is locked after %d wrong tries. Reset it with the portal password." % MAX_FAILS)
    if _hash(str(body.get("old") or ""), p["salt"]) != p["hash"]:
        _fail()
        raise S.ApiError(403, "The current PIN is wrong.")
    _store_pin(_valid_pin(body.get("pin")))
    return {"ok": True, "message": "PIN changed."}


def _fail():
    with S._state_lock:
        st = S.load_state()
        p = st.setdefault("holdings_pin", {})
        p["fails"] = int(p.get("fails") or 0) + 1
        if p["fails"] >= MAX_FAILS:
            p["locked"] = True
        S.save_state(st)
        return p


def unlock(body):
    p = _pin_state(S.load_state())
    if not p.get("hash"):
        raise S.ApiError(400, "Set a PIN first.")
    if p.get("locked"):
        raise S.ApiError(423, "Locked after %d wrong PINs. Reset the PIN with the portal password." % MAX_FAILS)
    if _hash(str(body.get("pin") or ""), p["salt"]) != p["hash"]:
        time.sleep(0.8)
        p = _fail()
        left = MAX_FAILS - p["fails"]
        raise S.ApiError(403, "Wrong PIN. %s" % ("%d tr%s left." % (left, "y" if left == 1 else "ies") if left > 0 else "Now locked: reset it with the portal password."))
    with S._state_lock:
        st = S.load_state()
        st["holdings_pin"]["fails"] = 0
        S.save_state(st)
    tok = secrets.token_urlsafe(24)
    now = time.time()
    for k in [k for k, v in _tokens.items() if v < now]:
        _tokens.pop(k, None)
    _tokens[tok] = now + TOKEN_SECS
    return {"ok": True, "token": tok, "valid_secs": TOKEN_SECS}


def require(token):
    """Raise unless the request carries a valid unlock token (the page then shows the PIN pad)."""
    if not _pin_state(S.load_state()).get("hash"):
        raise S.ApiError(401, "PIN needed")
    exp = _tokens.get(token or "")
    if not exp or exp < time.time():
        raise S.ApiError(401, "PIN needed")


# ----------------------------------------------------------------- recording
def fy_of(d):
    d = d if isinstance(d, date) else date.fromisoformat(str(d)[:10])
    y = d.year if d.month >= 4 else d.year - 1
    return "%d-%02d" % (y, (y + 1) % 100)


def _fy_range(fy):
    y = int(fy[:4])
    return date(y, 4, 1), date(y + 1, 3, 31)


def snapshot(reason="page"):
    """Save holdings, funds and today's buys / sells from Zerodha. Quiet no-op if not connected."""
    st = S.load_state()
    if not K._kite(st).get("token"):
        return {"saved": False, "why": "Zerodha is not connected"}
    if reason == "page" and time.time() - _last["at"] < 120:   # several reloads in a row: one Zerodha read
        return {"saved": False, "why": "saved %d s ago" % (time.time() - _last["at"])}
    _last["at"] = time.time()
    h = K.holdings("invest")
    if not h.get("connected") or h.get("kite_login") or h.get("error"):
        return {"saved": False, "why": h.get("message") or h.get("error") or "Zerodha login needed"}
    today = S.now_ist().date().isoformat()
    funds = None
    try:
        m = K.call("portfolio", {"mode": "margins"}).get("data") or {}
        eq = m.get("equity") or {}
        av = eq.get("available") or {}
        funds = {"net": K._num(eq.get("net")), "cash": K._num(av.get("live_balance") or av.get("cash")),
                 "opening": K._num(av.get("opening_balance")), "used": K._num((eq.get("utilised") or {}).get("debits"))}
    except Exception:  # noqa: BLE001
        pass
    day_trades = []
    try:
        for p in K._rows(K.call("portfolio", {"mode": "positions"})):
            if (p.get("exchange") or "") not in ("NSE", "BSE"):
                continue
            sym = (p.get("tradingsymbol") or "").upper()
            prod = p.get("product") or ""
            for side in ("buy", "sell"):
                q = K._num(p.get("day_%s_quantity" % side)) or 0
                px = K._num(p.get("day_%s_price" % side))
                if q and px:
                    day_trades.append({"id": "auto|%s|%s|%s|%s" % (today, sym, side, prod), "date": today, "time": "",
                                       "symbol": sym, "side": side, "qty": q, "price": px, "product": prod,
                                       "exchange": p.get("exchange"), "source": "zerodha"})
    except Exception:  # noqa: BLE001
        pass
    snap = {"at": S.market_clock()["ist"], "reason": reason, "funds": funds,
            "total_value": h.get("total_value"), "total_cost": h.get("total_cost"),
            "holdings": [{k: r.get(k) for k in ("symbol", "exchange", "qty", "avg", "ltp", "value", "cost", "pnl", "pnl_pct",
                                                 "day_pct", "day_pnl", "sector", "trend", "verdict", "why", "rule_stop", "flags")}
                         for r in h["rows"]],
            "fit": {"buys": (h.get("fit") or {}).get("buys") or [], "regime": (h.get("fit") or {}).get("regime")}}
    with _lock:
        d = _load()
        d["snapshots"][today] = snap
        for t in day_trades:
            d["trades"][t["id"]] = t
        _save(d)
    return {"saved": True, "at": snap["at"], "day_trades": len(day_trades)}


def _norm_date(s):
    s = str(s or "").strip()[:19]
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%d-%b-%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s if "%H" in fmt else s[:11].strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def import_tradebook(body):
    text = str(body.get("csv") or "")
    if not text.strip():
        raise S.ApiError(400, "The file is empty.")
    if len(text) > 15_000_000:
        raise S.ApiError(400, "File too big (15 MB max). Export a shorter date range.")
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    # Console files can start with a few title lines: find the header row
    hi = next((i for i, r in enumerate(rows[:30]) if {"symbol", "trade_type", "quantity", "price"} <=
               {re.sub(r"[^a-z]+", "_", c.strip().lower()).strip("_") for c in r}), None)
    if hi is None:
        raise S.ApiError(400, "This does not look like a Zerodha tradebook: need columns Symbol, Trade Date, Trade Type, Quantity, Price.")
    cols = [re.sub(r"[^a-z]+", "_", c.strip().lower()).strip("_") for c in rows[hi]]
    added, skipped, bad, dates = 0, 0, 0, []
    with _lock:
        d = _load()
        for r in rows[hi + 1:]:
            if not any(x.strip() for x in r):
                continue
            x = dict(zip(cols, [c.strip() for c in r]))
            seg = (x.get("segment") or "EQ").upper()
            if seg not in ("EQ", "") or (x.get("exchange") or "NSE").upper() not in ("NSE", "BSE"):
                skipped += 1
                continue
            day = _norm_date(x.get("trade_date") or x.get("order_execution_time"))
            side = (x.get("trade_type") or "").lower()
            try:
                qty, px = float(x.get("quantity") or 0), float(x.get("price") or 0)
            except ValueError:
                bad += 1
                continue
            sym = re.sub(r"-(EQ|BE|BZ|SM|ST)$", "", (x.get("symbol") or "").upper())
            if not day or side not in ("buy", "sell") or qty <= 0 or px < 0 or not sym:
                bad += 1
                continue
            tid = x.get("trade_id") or "%s|%s|%s|%g|%g|%s" % (day, sym, side, qty, px, x.get("order_execution_time", ""))
            key = "tb|%s|%s" % (x.get("exchange", ""), tid)
            if key in d["trades"]:
                skipped += 1
                continue
            d["trades"][key] = {"id": key, "date": day, "time": (x.get("order_execution_time") or "")[11:19],
                                "symbol": sym, "side": side, "qty": qty, "price": px, "product": "",
                                "exchange": x.get("exchange") or "", "source": "tradebook", "order_id": x.get("order_id", "")}
            added += 1
            dates.append(day)
        if not dates and not skipped:
            raise S.ApiError(400, "No equity trades found in the file (%d rows could not be read)." % bad)
        if dates:
            d["imports"].append({"at": S.market_clock()["ist"], "file": str(body.get("name") or "")[:80],
                                 "from": min(dates), "to": max(dates), "added": added, "skipped": skipped, "bad": bad})
        _save(d)
    return {"ok": True, "added": added, "skipped": skipped, "bad": bad,
            "message": "Imported %d trades%s%s." % (added, " (%d already there or not equity, skipped)" % skipped if skipped else "",
                                                   ", %d rows unreadable" % bad if bad else "")}


def manual(body):
    act = body.get("action")
    with _lock:
        d = _load()
        if act == "delete":
            tid = str(body.get("id") or "")
            if not tid.startswith("man|") or tid not in d["trades"]:
                raise S.ApiError(400, "Only trades you added by hand can be deleted here.")
            d["trades"].pop(tid)
            _save(d)
            return {"ok": True, "message": "Trade deleted."}
        day = _norm_date(body.get("date"))
        side = str(body.get("side") or "").lower()
        sym = S.clean_symbol(body.get("symbol"))
        try:
            qty, px = float(body.get("qty")), float(body.get("price"))
        except (TypeError, ValueError):
            raise S.ApiError(400, "Enter a quantity and a price (0 for bonus shares).")
        if not day or side not in ("buy", "sell") or qty <= 0 or px < 0:
            raise S.ApiError(400, "Need a date, buy or sell, quantity above 0 and a price of 0 or more.")
        tid = "man|%s|%d" % (day, int(time.time() * 1000))
        d["trades"][tid] = {"id": tid, "date": day, "time": "", "symbol": sym, "side": side, "qty": qty, "price": px,
                            "product": "", "exchange": "", "source": "manual", "note": str(body.get("note") or "")[:80]}
        _save(d)
    return {"ok": True, "message": "Added: %s %g %s at %.2f on %s." % (side, qty, sym, px, day)}


# ----------------------------------------------------------------- working it out
def _active_trades(d):
    """Tradebook wins over the auto-recorded day totals for the dates it covers."""
    covered = [(i["from"], i["to"]) for i in d["imports"]]
    out = []
    for t in d["trades"].values():
        if t["source"] == "zerodha" and any(a <= t["date"] <= b for a, b in covered):
            continue
        out.append(t)
    out.sort(key=lambda t: (t["date"], t.get("time") or "", 0 if t["side"] == "buy" else 1))
    return out


def _rates(fy):
    y = int(fy[:4])
    if y >= 2024:
        return 0.20, 0.125, 125000.0
    return 0.15, 0.10, 100000.0


def _is_long(buy_day, sell_day):
    """Long-term = held for more than 12 months (sold after the same date next year)."""
    if not buy_day:
        return None
    b = date.fromisoformat(buy_day)
    try:
        anniv = b.replace(year=b.year + 1)
    except ValueError:   # 29 Feb
        anniv = b.replace(year=b.year + 1, day=28)
    return date.fromisoformat(sell_day) > anniv, anniv


def compute(d):
    trades = _active_trades(d)
    lots = {}          # symbol -> [ {date, qty, price, source} ]
    realised = []      # {date, symbol, kind: intraday|short|long|unknown, qty, buy, sell, pnl, buy_date}
    by_day = {}
    for t in trades:
        by_day.setdefault((t["date"], t["symbol"]), []).append(t)
    for (day, sym), ts in sorted(by_day.items()):
        bq = sum(t["qty"] for t in ts if t["side"] == "buy")
        bv = sum(t["qty"] * t["price"] for t in ts if t["side"] == "buy")
        sq = sum(t["qty"] for t in ts if t["side"] == "sell")
        sv = sum(t["qty"] * t["price"] for t in ts if t["side"] == "sell")
        m = min(bq, sq)
        if m > 0:   # same-day buy and sell of the same stock: intraday (speculative) for tax
            ab, as_ = bv / bq, sv / sq
            realised.append({"date": day, "symbol": sym, "kind": "intraday", "qty": m, "buy": ab, "sell": as_,
                             "pnl": m * (as_ - ab), "buy_date": day, "turnover": m * (ab + as_)})
        if bq > m:
            lots.setdefault(sym, []).append({"date": day, "qty": bq - m, "price": bv / bq})
        left = sq - m
        if left > 0:
            as_ = sv / sq
            q = lots.get(sym, [])
            while left > 1e-9 and q:
                lot = q[0]
                take = min(left, lot["qty"])
                lg, _ = _is_long(lot["date"], day)
                realised.append({"date": day, "symbol": sym, "kind": "long" if lg else "short", "qty": take,
                                 "buy": lot["price"], "sell": as_, "pnl": take * (as_ - lot["price"]), "buy_date": lot["date"],
                                 "turnover": take * (lot["price"] + as_)})
                lot["qty"] -= take
                left -= take
                if lot["qty"] <= 1e-9:
                    q.pop(0)
            if left > 1e-9:   # sold shares bought before your records start
                realised.append({"date": day, "symbol": sym, "kind": "unknown", "qty": left, "buy": None, "sell": as_,
                                 "pnl": None, "buy_date": None, "turnover": left * as_})
    return trades, lots, realised


def _tax(fy, realised, extra=None):
    st_r, lt_r, exempt = _rates(fy)
    rows = [r for r in realised if r["pnl"] is not None and fy_of(r["date"]) == fy] + (extra or [])
    stg = sum(r["pnl"] for r in rows if r["kind"] == "short")
    ltg = sum(r["pnl"] for r in rows if r["kind"] == "long")
    intra = sum(r["pnl"] for r in rows if r["kind"] == "intraday")
    # set-off: a short-term loss can reduce long-term gains; a long-term loss only long-term gains
    st_net, lt_net = stg, ltg
    if st_net < 0 and lt_net > 0:
        use = min(-st_net, lt_net)
        lt_net -= use
        st_net += use
    st_tax = max(st_net, 0) * st_r
    lt_taxable = max(lt_net - exempt, 0)
    lt_tax = lt_taxable * lt_r
    return {"short_gain": stg, "long_gain": ltg, "intraday": intra, "short_after_setoff": st_net, "long_after_setoff": lt_net,
            "long_exempt": exempt, "long_taxable": lt_taxable, "st_rate": st_r, "lt_rate": lt_r,
            "st_tax": st_tax, "lt_tax": lt_tax, "cess": (st_tax + lt_tax) * CESS, "total_tax": (st_tax + lt_tax) * (1 + CESS),
            "carry_short_loss": min(st_net, 0), "carry_long_loss": min(lt_net, 0)}


def report(fy=None):
    with _lock:
        d = _load()
    trades, lots, realised = compute(d)
    today = S.now_ist().date()
    fy = fy or fy_of(today)
    if not re.fullmatch(r"\d{4}-\d{2}", fy):
        raise S.ApiError(400, "Unknown financial year")
    f0, f1 = _fy_range(fy)
    snaps = d["snapshots"]
    last_day = max(snaps) if snaps else None
    snap = snaps.get(last_day) if last_day else None
    connected = False
    try:
        connected = bool(K.held().get("connected"))
    except Exception:  # noqa: BLE001
        pass
    held = {h["symbol"]: h for h in (snap or {}).get("holdings", [])}
    cfg = L.settings_for("invest")
    # ---- open lots, matched to what Zerodha shows now
    holdings = []
    for sym in sorted(set(lots) | set(held)):
        ls = [l for l in lots.get(sym, []) if l["qty"] > 1e-9]
        lq = sum(l["qty"] for l in ls)
        h = held.get(sym)
        zq = (h or {}).get("qty")
        if not h and lq <= 1e-9:
            continue
        ltp = (h or {}).get("ltp")
        if ltp is None and ls:
            try:
                ltp = L.history(sym)["bars"][-1][4]
            except Exception:  # noqa: BLE001
                ltp = None
        lot_rows = []
        for l in ls:
            lg, anniv = _is_long(l["date"], today.isoformat())
            lot_rows.append({"date": l["date"], "qty": l["qty"], "price": l["price"], "long": lg,
                             "long_from": (anniv + timedelta(days=1)).isoformat(), "days_to_long": max(0, (anniv + timedelta(days=1) - today).days),
                             "days_held": (today - date.fromisoformat(l["date"])).days,
                             "gain": (ltp - l["price"]) * l["qty"] if ltp is not None else None})
        if h and zq is not None and zq - lq > 1e-6:   # shares the records cannot date (bought before the tradebook)
            lot_rows.insert(0, {"date": None, "qty": zq - lq, "price": h.get("avg"), "long": None, "long_from": None,
                                "days_to_long": None, "days_held": None,
                                "gain": (ltp - h["avg"]) * (zq - lq) if ltp is not None and h.get("avg") is not None else None})
        qty = zq if zq is not None else lq
        cost = sum((l["price"] or 0) * l["qty"] for l in lot_rows)
        mismatch = None
        if h and abs((zq or 0) - lq) > 1e-6:
            mismatch = ("%g shares have no buy date in your records: upload a tradebook that goes back further." % (zq - lq)) if zq > lq else \
                       ("Records show %g more than Zerodha: a sale is missing (upload the tradebook for the missing dates)." % (lq - zq))
        elif not h and lq > 1e-9 and snap:
            mismatch = "Not in your latest Zerodha holdings (as of %s): a sale may be missing." % snap["at"]
        nxt = min((l for l in lot_rows if l["long"] is False), key=lambda l: l["days_to_long"], default=None)
        holdings.append({
            "symbol": sym, "sector": (h or {}).get("sector") or S.UNIVERSE.get(sym, {}).get("industry", "") or "Other",
            "qty": qty, "avg": (h or {}).get("avg") or (cost / lq if lq else None), "ltp": ltp,
            "value": (ltp or 0) * qty, "cost": (h or {}).get("cost") or cost,
            "pnl": ((ltp or 0) * qty - ((h or {}).get("cost") or cost)) if ltp is not None else None,
            "day_pnl": (h or {}).get("day_pnl"), "day_pct": (h or {}).get("day_pct"),
            "verdict": (h or {}).get("verdict"), "why": (h or {}).get("why"), "rule_stop": (h or {}).get("rule_stop"),
            "trend": (h or {}).get("trend"), "lots": lot_rows, "mismatch": mismatch, "in_zerodha": bool(h),
            "counted": bool(h) or not snap,   # no Zerodha snapshot yet: count what the tradebook says you hold
            "first_buy": min((l["date"] for l in lot_rows if l["date"]), default=None),
            "short_qty": sum(l["qty"] for l in lot_rows if l["long"] is False),
            "long_qty": sum(l["qty"] for l in lot_rows if l["long"]),
            "unknown_qty": sum(l["qty"] for l in lot_rows if l["long"] is None),
            "next_long": {"date": nxt["long_from"], "days": nxt["days_to_long"], "qty": nxt["qty"]} if nxt else None,
            "unreal_short": sum(l["gain"] or 0 for l in lot_rows if l["long"] is False),
            "unreal_long": sum(l["gain"] or 0 for l in lot_rows if l["long"]),
        })
    holdings.sort(key=lambda x: -(x["value"] or 0))
    # ---- this financial year: trades, per stock, monthly
    in_fy = lambda day: f0.isoformat() <= day <= f1.isoformat()  # noqa: E731
    fy_trades = [t for t in trades if in_fy(t["date"])]
    fy_real = [r for r in realised if in_fy(r["date"])]
    per = {}
    for t in fy_trades:
        p = per.setdefault(t["symbol"], {"symbol": t["symbol"], "buy_qty": 0, "buy_value": 0.0, "sell_qty": 0, "sell_value": 0.0,
                                         "first": t["date"], "last": t["date"], "intraday": 0.0, "short": 0.0, "long": 0.0, "unknown_qty": 0})
        p["%s_qty" % t["side"]] += t["qty"]
        p["%s_value" % t["side"]] += t["qty"] * t["price"]
        p["last"] = t["date"]
    for r in fy_real:
        p = per.get(r["symbol"])
        if not p:
            continue
        if r["pnl"] is None:
            p["unknown_qty"] += r["qty"]
        else:
            p[r["kind"]] += r["pnl"]
    hq = {h["symbol"]: h["qty"] for h in holdings}
    for p in per.values():
        p["remaining"] = hq.get(p["symbol"], 0)
        p["realised"] = p["intraday"] + p["short"] + p["long"]
        p["avg_buy"] = p["buy_value"] / p["buy_qty"] if p["buy_qty"] else None
        p["avg_sell"] = p["sell_value"] / p["sell_qty"] if p["sell_qty"] else None
        p["sector"] = S.UNIVERSE.get(p["symbol"], {}).get("industry", "") or "Other"
    months = {}
    for t in fy_trades:
        m = months.setdefault(t["date"][:7], {"month": t["date"][:7], "buys": 0, "buy_value": 0.0, "sells": 0, "sell_value": 0.0, "realised": 0.0})
        m["buys" if t["side"] == "buy" else "sells"] += 1
        m["%s_value" % t["side"]] += t["qty"] * t["price"]
    for r in fy_real:
        if r["pnl"] is not None:
            months.setdefault(r["date"][:7], {"month": r["date"][:7], "buys": 0, "buy_value": 0.0, "sells": 0, "sell_value": 0.0, "realised": 0.0})["realised"] += r["pnl"]
    # ---- charges (estimate) and tax
    deliv_turn = sum(t["qty"] * t["price"] for t in fy_trades) - sum(r["turnover"] for r in fy_real if r["kind"] == "intraday")
    intra_turn = sum(r["turnover"] for r in fy_real if r["kind"] == "intraday")
    sell_days = len({(t["date"], t["symbol"]) for t in fy_trades if t["side"] == "sell"})
    charges = {"delivery": max(deliv_turn, 0) * DELIVERY_SIDE + sell_days * DP_FEE, "intraday": intra_turn * INTRADAY_COST}
    charges["total"] = charges["delivery"] + charges["intraday"]
    tax = _tax(fy, realised)
    # if everything open were sold today (adds to the current FY only)
    if fy == fy_of(today):
        extra = []
        for h in holdings:
            for l in h["lots"]:
                if l["gain"] is not None and l["long"] is not None:
                    extra.append({"date": today.isoformat(), "kind": "long" if l["long"] else "short", "pnl": l["gain"]})
        tax["if_sold_today"] = _tax(fy, realised, extra)["total_tax"] - tax["total_tax"]
    # ---- sectors
    tv = sum(h["value"] or 0 for h in holdings if h["counted"]) or 1
    secs = {}
    for h in holdings:
        if not h["counted"]:
            continue
        s_ = secs.setdefault(h["sector"], {"sector": h["sector"], "value": 0.0, "cost": 0.0, "stocks": [], "realised": 0.0})
        s_["value"] += h["value"] or 0
        s_["cost"] += h["cost"] or 0
        s_["stocks"].append(h["symbol"])
    for p in per.values():
        secs.setdefault(p["sector"], {"sector": p["sector"], "value": 0.0, "cost": 0.0, "stocks": [], "realised": 0.0})["realised"] += p["realised"]
    for s_ in secs.values():
        s_["pct"] = s_["value"] / tv * 100
        s_["pnl"] = s_["value"] - s_["cost"]
        s_["over"] = s_["sector"] != "Other" and (len(s_["stocks"]) > cfg["max_per_sector"] or s_["pct"] > 25)
    # ---- what next: rule results, your limits, tax timing (not personal advice)
    nxt = {"exit": [], "weak": [], "keep": [], "buy_more": [], "unknown": [], "limits": [], "tax": [], "buys": [], "cash": None, "slots": None}
    for h in holdings:
        if not h["counted"]:
            continue
        item = {"symbol": h["symbol"], "why": h["why"], "rule_stop": h["rule_stop"], "pnl": h["pnl"], "value": h["value"],
                "next_long": h["next_long"]}
        nxt[{"exit": "exit", "weak": "weak", "buy": "buy_more", "hold": "keep"}.get(h["verdict"], "unknown")].append(item)
        if (h["value"] or 0) > cfg["max_per_stock"]:
            nxt["limits"].append("%s is %s, over your ₹%s per-stock limit" % (h["symbol"], _rs(h["value"]), format(int(cfg["max_per_stock"]), ",")))
        nl = h["next_long"]
        if h["verdict"] in ("exit", "weak") and nl and nl["days"] <= 60 and (h["unreal_short"] or 0) > 0:
            nxt["tax"].append("%s: %g shares turn long-term on %s (%d days). A sale before then is taxed %d%%, after it %.1f%% (above the ₹1.25 lakh exemption)." % (
                h["symbol"], nl["qty"], nl["date"], nl["days"], _rates(fy)[0] * 100, _rates(fy)[1] * 100))
    n_held = sum(1 for h in holdings if h["counted"])
    if n_held > cfg["max_positions"]:
        nxt["limits"].append("%d stocks held vs your limit of %d" % (n_held, cfg["max_positions"]))
    for s_ in secs.values():
        if s_["over"]:
            nxt["limits"].append("%s: %d stock%s, %.0f%% of the value (limits: %d stocks, 25%%)" % (
                s_["sector"], len(s_["stocks"]), "" if len(s_["stocks"]) == 1 else "s", s_["pct"], cfg["max_per_sector"]))
    if tax["short_gain"] > 0:
        losers = sorted((h for h in holdings if h["counted"] and (h["unreal_short"] or 0) < 0), key=lambda h: h["unreal_short"])
        if losers:
            nxt["tax"].append("Short-term gains booked this year: %s. Holdings with short-term losses that would offset them if sold: %s." % (
                _rs(tax["short_gain"]), ", ".join("%s %s" % (h["symbol"], _rs(h["unreal_short"])) for h in losers[:5])))
    if snap:
        nxt["buys"] = snap.get("fit", {}).get("buys") or []
        nxt["regime"] = snap.get("fit", {}).get("regime")
        nxt["cash"] = (snap.get("funds") or {}).get("net")
    nxt["slots"] = max(0, cfg["max_positions"] - n_held)
    nxt["per_stock"] = cfg["max_per_stock"]
    funds_hist = [{"date": k, "at": v["at"], **(v.get("funds") or {}), "value": v.get("total_value"), "cost": v.get("total_cost")}
                  for k, v in sorted(snaps.items())]
    fys = sorted({fy_of(t["date"]) for t in trades} | {fy_of(k) for k in snaps} | {fy_of(today)}, reverse=True)
    totals = {"buy_value": sum(p["buy_value"] for p in per.values()), "sell_value": sum(p["sell_value"] for p in per.values()),
              "buys": sum(1 for t in fy_trades if t["side"] == "buy"), "sells": sum(1 for t in fy_trades if t["side"] == "sell"),
              "buy_qty": sum(p["buy_qty"] for p in per.values()), "sell_qty": sum(p["sell_qty"] for p in per.values()),
              "realised": sum(r["pnl"] for r in fy_real if r["pnl"] is not None),
              "unknown_sells": sum(r["qty"] for r in fy_real if r["pnl"] is None),
              "value": sum(h["value"] or 0 for h in holdings if h["counted"]),
              "cost": sum(h["cost"] or 0 for h in holdings if h["counted"]),
              "unreal_short": sum(h["unreal_short"] for h in holdings), "unreal_long": sum(h["unreal_long"] for h in holdings)}
    totals["unrealised"] = totals["value"] - totals["cost"]
    return {"fy": fy, "fys": fys, "fy_from": f0.isoformat(), "fy_to": f1.isoformat(), "connected": connected, "totals": totals,
            "snapshot_at": snap["at"] if snap else None, "funds": (snap or {}).get("funds"),
            "holdings": holdings, "per_stock": sorted(per.values(), key=lambda p: -(p["buy_value"] + p["sell_value"])),
            "trades": [dict(t, value=t["qty"] * t["price"]) for t in reversed(fy_trades)],
            "realised": list(reversed(fy_real)), "months": [months[k] for k in sorted(months)],
            "tax": tax, "charges": charges, "sectors": sorted(secs.values(), key=lambda s_: -s_["value"]),
            "next": nxt, "funds_history": funds_hist[-400:], "imports": d["imports"][-20:],
            "records": {"trades": len(d["trades"]), "snapshots": len(snaps), "first_trade": trades[0]["date"] if trades else None},
            "settings": {"max_positions": cfg["max_positions"], "max_per_stock": cfg["max_per_stock"], "max_per_sector": cfg["max_per_sector"]},
            "clock": S.market_clock()}


def _rs(v):
    return ("−" if v < 0 else "") + "₹" + format(int(round(abs(v))), ",")


def csv_export(fy):
    r = report(fy)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["date", "time", "symbol", "side", "qty", "price", "value", "source"])
    for t in r["trades"]:
        w.writerow([t["date"], t.get("time", ""), t["symbol"], t["side"], t["qty"], "%.2f" % t["price"], "%.2f" % t["value"], t["source"]])
    w.writerow([])
    w.writerow(["sell date", "symbol", "type", "qty", "buy date", "buy price", "sell price", "profit"])
    for x in r["realised"]:
        w.writerow([x["date"], x["symbol"], x["kind"], x["qty"], x["buy_date"] or "", "%.2f" % x["buy"] if x["buy"] is not None else "",
                    "%.2f" % x["sell"], "%.2f" % x["pnl"] if x["pnl"] is not None else ""])
    return {"name": "zerodha-record-%s.csv" % fy, "csv": out.getvalue()}


def daily():
    """Watcher hook after the close: one snapshot per trading day while Zerodha is connected."""
    try:
        return snapshot("daily")
    except Exception as e:  # noqa: BLE001
        return {"saved": False, "why": str(e)[:120]}
