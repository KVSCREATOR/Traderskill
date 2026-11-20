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
import math
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
    mfs = []
    try:   # Coin mutual funds: index funds can count as the "core" of the account
        for m in K._rows(K.call("mutual_funds", {"mode": "holdings"})):
            q, avg, nav = K._num(m.get("quantity")) or 0, K._num(m.get("average_price")) or 0, K._num(m.get("last_price")) or 0
            if q:
                mfs.append({"fund": m.get("fund") or m.get("tradingsymbol") or "", "units": q, "value": q * nav, "cost": q * avg})
    except Exception:  # noqa: BLE001
        mfs = None
    snap = {"at": S.market_clock()["ist"], "reason": reason, "funds": funds, "mfs": mfs,
            "total_value": h.get("total_value"), "total_cost": h.get("total_cost"),
            "holdings": [{k: r.get(k) for k in ("symbol", "exchange", "qty", "avg", "ltp", "value", "cost", "pnl", "pnl_pct",
                                                 "day_pct", "day_pnl", "sector", "trend", "verdict", "why", "rule_stop", "flags",
                                                 "verdict_t", "why_t", "trail_stop", "floor200", "asset", "hmode", "verdict_i")}
                         for r in h["rows"]],
            "fit": {"buys": (h.get("fit") or {}).get("buys") or [], "regime": (h.get("fit") or {}).get("regime")},
            "fit_t": {"buys": (h.get("fit_t") or {}).get("buys") or [], "regime": (h.get("fit_t") or {}).get("regime")}}
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
    added, skipped, dup, bad, dates = 0, 0, 0, 0, []
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
                dup += 1
                continue
            d["trades"][key] = {"id": key, "date": day, "time": (x.get("order_execution_time") or "")[11:19],
                                "symbol": sym, "side": side, "qty": qty, "price": px, "product": "",
                                "exchange": x.get("exchange") or "", "source": "tradebook", "order_id": x.get("order_id", "")}
            added += 1
            dates.append(day)
        if not dates and not skipped and not dup:
            raise S.ApiError(400, "No equity trades found in the file (%d rows could not be read)." % bad)
        if dates:
            d["imports"].append({"at": S.market_clock()["ist"], "file": str(body.get("name") or "")[:80],
                                 "from": min(dates), "to": max(dates), "added": added, "skipped": skipped + dup, "bad": bad})
        _save(d)
    extra = [x for x in ("%d not equity" % skipped if skipped else "", "%d rows unreadable" % bad if bad else "") if x]
    if not added and dup:
        msg = "Nothing new: all %d trades in this file are already in your record%s." % (dup, " (" + ", ".join(extra) + ")" if extra else "")
    else:
        msg = "Imported %d new trade%s%s." % (added, "" if added == 1 else "s",
                                             " (" + ", ".join(([("%d already in your record" % dup)] if dup else []) + extra) + ")" if dup or extra else "")
    return {"ok": True, "added": added, "skipped": skipped, "duplicates": dup, "bad": bad, "message": msg}


def _xlsx_sheets(raw):
    """{sheet name: [[cell text, ...], ...]} from an .xlsx, standard library only."""
    import zipfile
    import xml.etree.ElementTree as ET
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    rel_ns = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    z = zipfile.ZipFile(io.BytesIO(raw))
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
            shared.append("".join(t.text or "" for t in si.iter("{%s}t" % ns["m"])))
    rels = {}
    try:
        for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")):
            rels[r.get("Id")] = r.get("Target").lstrip("/").replace("xl/", "")
    except KeyError:
        pass
    out = {}
    for sh in ET.fromstring(z.read("xl/workbook.xml")).find("m:sheets", ns):
        path = "xl/" + rels.get(sh.get(rel_ns), "worksheets/sheet1.xml")
        rows = []
        for row in ET.fromstring(z.read(path)).iter("{%s}row" % ns["m"]):
            cells = {}
            for c in row.findall("m:c", ns):
                ref = re.match(r"([A-Z]+)", c.get("r") or "A")
                col = 0
                for ch in ref.group(1):
                    col = col * 26 + ord(ch) - 64
                v = c.find("m:v", ns)
                t = c.get("t")
                if t == "s" and v is not None:
                    val = shared[int(v.text)]
                elif t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter("{%s}t" % ns["m"]))
                else:
                    val = v.text if v is not None else ""
                cells[col - 1] = (val or "").strip()
            if cells:
                rows.append([cells.get(i, "") for i in range(max(cells) + 1)])
        out[sh.get("name")] = rows
    return out


def _num(x):
    try:
        return float(str(x).replace(",", "").replace("₹", "").strip())
    except (TypeError, ValueError):
        return None


def import_pnl(body):
    """Zerodha Console -> Reports -> P&L (Equity), Excel or CSV: Zerodha's own realised P&L per stock,
    open quantity / value, and the real charges and other debits and credits."""
    import base64
    name = str(body.get("name") or "")[:80]
    try:
        raw = base64.b64decode(body.get("b64") or "")
    except ValueError:
        raise S.ApiError(400, "Could not read the file.")
    if len(raw) > 15_000_000:
        raise S.ApiError(400, "File too big (15 MB max).")
    if raw[:2] == b"PK":
        try:
            sheets = _xlsx_sheets(raw)
        except Exception:  # noqa: BLE001
            raise S.ApiError(400, "Could not open this Excel file. Save it again as .xlsx or download the CSV.")
    else:
        sheets = {"Equity": list(csv.reader(io.StringIO(raw.decode("utf-8-sig", "replace"))))}
    norm = lambda s: re.sub(r"[^a-z]+", "_", str(s).lower()).strip("_")  # noqa: E731
    eq = None
    for nm, rows in sheets.items():
        for i, r in enumerate(rows[:60]):
            cols = [norm(c) for c in r]
            if "symbol" in cols and any(c.startswith("realized_p_l") or c.startswith("realised_p_l") for c in cols):
                eq = (nm, i, cols)
                break
        if eq:
            break
    if not eq:
        raise S.ApiError(400, "This does not look like a Zerodha P&L statement: need columns Symbol and Realized P&L.")
    nm, hi, cols = eq
    rows = sheets[nm]
    text = " ".join(" ".join(r) for r in rows[:hi])
    dts = re.findall(r"(\d{4}-\d{2}-\d{2})", text)
    p_from, p_to = (dts[0], dts[1]) if len(dts) >= 2 else (None, None)
    summary = {}
    for r in rows[:hi]:   # label / amount pairs above the table (Charges, Net Realized P&L, ...)
        cells = [c for c in r if c != ""]
        if len(cells) >= 2 and _num(cells[-1]) is not None and _num(cells[0]) is None:
            summary[cells[0].strip()[:60]] = _num(cells[-1])
    stocks = {}
    for r in rows[hi + 1:]:
        x = dict(zip(cols, r))
        sym = (x.get("symbol") or "").strip().upper()
        if not sym:
            if stocks:
                break
            continue
        g = lambda *ks: next((_num(x[k]) for k in ks if k in x and _num(x[k]) is not None), None)  # noqa: E731
        stocks[sym] = {"isin": x.get("isin", ""), "qty": g("quantity"), "buy_value": g("buy_value"), "sell_value": g("sell_value"),
                       "realised": g("realized_p_l", "realised_p_l"), "realised_pct": g("realized_p_l_pct", "realised_p_l_pct"),
                       "prev_close": g("previous_closing_price"), "open_qty": g("open_quantity"), "open_value": g("open_value"),
                       "unrealised": g("unrealized_p_l", "unrealised_p_l")}
    if not stocks:
        raise S.ApiError(400, "No stock rows found under the header.")
    other = []
    for snm, srows in sheets.items():   # 'Other Debits and Credits' sheet
        if snm == nm or not srows:
            continue
        h = next((i for i, r in enumerate(srows[:40]) if any(norm(c) in ("particulars", "description", "narration") for c in r)), None)
        if h is None:
            continue
        oc = [norm(c) for c in srows[h]]
        for r in srows[h + 1:]:
            x = dict(zip(oc, r))
            if not any(r):
                continue
            desc = x.get("particulars") or x.get("description") or x.get("narration") or ""
            amt = _num(x.get("amount"))
            if amt is None:
                dr, cr = _num(x.get("debit")) or 0, _num(x.get("credit")) or 0
                amt = cr - dr
            if desc and amt is not None:
                other.append({"date": _norm_date(x.get("posting_date") or x.get("date") or ""), "what": desc[:120], "amount": amt})
    fy = fy_of(p_to or p_from or S.now_ist().date())
    with _lock:
        d = _load()
        d.setdefault("pnl", {})[fy] = {"at": S.market_clock()["ist"], "file": name, "from": p_from, "to": p_to,
                                       "stocks": stocks, "summary": summary, "other": other}
        _save(d)
    return {"ok": True, "fy": fy, "message": "Zerodha P&L for FY %s saved: %d stocks%s%s." % (
        fy, len(stocks), ", %d summary lines" % len(summary) if summary else "", ", %d other debits/credits" % len(other) if other else "")}


CORE_DEFAULT = ["NIFTYBEES", "SETFNIF50", "NIFTYIETF", "UTINIFTETF", "HDFCNIFTY", "BSLNIFTY", "AXISNIFTY",
                "NIFTY1", "LICNETFN50", "MOM50", "NIFTYETF"]
INDEX_MF = re.compile(r"nifty ?50\b|sensex", re.I)   # core = Nifty 50 / Sensex index funds only (not midcap, Next 50, sector or consumption index funds)


def _core_cfg(d):
    c = d.get("core") or {}
    return {"target": c.get("target", 50), "symbols": c.get("symbols") or list(CORE_DEFAULT), "count_mf": c.get("count_mf", True)}


def core_symbols():
    """Index funds you count as core (NIFTYBEES etc.): they are not stocks, so the per-stock cap,
    the stock-count limit and the plan's sells leave them alone."""
    with _lock:
        return set(_core_cfg(_load())["symbols"])


def core_set(body):
    """Your target split: share in Nifty index funds (core) vs stocks run by the rules (satellite)."""
    try:
        t = int(body.get("target"))
    except (TypeError, ValueError):
        raise S.ApiError(400, "Target must be a whole number from 0 to 100.")
    if not 0 <= t <= 100:
        raise S.ApiError(400, "Target must be from 0 to 100.")
    syms = [S.clean_symbol(x) for x in (body.get("symbols") or []) if str(x).strip()][:30]
    with _lock:
        d = _load()
        d["core"] = {"target": t, "symbols": syms or list(CORE_DEFAULT), "count_mf": bool(body.get("count_mf", True))}
        _save(d)
    return {"ok": True, "message": "Target saved: %d%% in index funds, %d%% in stocks." % (t, 100 - t)}


def _core_view(d, snap, holdings, today):
    cfg = _core_cfg(d)
    core_set_ = set(cfg["symbols"])
    core, sat = [], []
    for h in holdings:
        if not h.get("counted"):
            continue
        (core if h["symbol"] in core_set_ else sat).append({"name": h["symbol"], "value": h["value"] or 0, "kind": "ETF" if h["symbol"] in core_set_ else "stock"})
    other_mf = []
    for m in ((snap or {}).get("mfs") or []):
        item = {"name": m["fund"], "value": m["value"], "kind": "mutual fund"}
        (core if cfg["count_mf"] and INDEX_MF.search(m["fund"] or "") else other_mf).append(item)
    cv, sv = sum(x["value"] for x in core), sum(x["value"] for x in sat)
    tot = cv + sv
    actual = cv / tot * 100 if tot else None
    move = tot * cfg["target"] / 100 - cv if tot else 0
    off = abs(actual - cfg["target"]) if actual is not None else 0
    due = tot > 0 and (today.month == 4 or off > 10)
    return {"target": cfg["target"], "symbols": cfg["symbols"], "count_mf": cfg["count_mf"], "core": sorted(core, key=lambda x: -x["value"]),
            "satellite": sorted(sat, key=lambda x: -x["value"]), "other_mf": other_mf, "core_value": cv, "sat_value": sv, "total": tot,
            "actual": actual, "move": move, "off": off, "due": due, "april": today.month == 4,
            "mf_known": (snap or {}).get("mfs") is not None}


# ----------------------------------------------------------------- Today: the 15-minute daily checklist
def today(mode=None):
    """Everything worth a look after the close, in one list: act / watch / for tomorrow / info.
    Rule results and facts from your own records, not personal advice."""
    mode = "invest"   # real stocks follow the Investing rules (owner's choice, 20 Nov 2026), whatever mode the page is in
    lbl = L.LABEL[mode]
    rep = report()
    now = S.now_ist()
    day = now.date().isoformat()
    items = []

    def add(iid, group, text, link=None, level="watch"):
        items.append({"id": iid, "group": group, "text": text, "link": link, "level": level})

    # Zerodha + market
    if not rep["connected"]:
        add("connect", "act", "Zerodha is not connected: sign in once so today's holdings and funds are recorded%s." % (
            " (last record %s)" % rep["snapshot_at"] if rep["snapshot_at"] else ""), "#/holdings", "act")
    try:
        mkt = L.market()
        n = mkt.ind
        i = len(n["c"]) - 1
        chg = (n["c"][i] / n["c"][i - 1] - 1) * 100
        on = mkt.regime(n["d"][i], mode)
        add("market", "info", "Nifty %s %.0f (%+.2f%% on %s). Market filter for the %s rules: %s." % (
            "closed at" if not S.market_clock()["open"] else "at", n["c"][i], chg, n["d"][i], lbl,
            "ON, new buys allowed" if on else "OFF, the rules hold off new buys"), None, "info")
    except Exception:  # noqa: BLE001
        on = None
    nx = rep["next"]
    for x in nx["exit"]:
        add("exit:" + x["symbol"], "act", "%s: exit rule fired (%s)%s." % (x["symbol"], x.get("why") or "rule exit",
            " · rule stop %s" % _rs(x["rule_stop"]) if x.get("rule_stop") else ""), "#/predictor/" + x["symbol"], "act")
    for x in nx["weak"]:
        add("weak:" + x["symbol"], "watch", "%s: weak trend (%s)." % (x["symbol"], x.get("why") or "below its averages"), "#/predictor/" + x["symbol"])
    for t in nx["limits"]:
        add("limit:" + t[:40], "watch", "Your limit: " + t + ".")
    hv = (rep.get("tax") or {}).get("harvest")   # Feb-Mar: book long-term gains tax-free before 31 March
    if hv and now.month in (2, 3) and hv["used"] >= 5000:
        add("harvest:" + hv["fy_end"], "act" if now.month == 3 else "watch",
            "Tax-free gains: book about %s of long-term gains before %s (sell, buy back next trading day): saves about %s tax. %s." % (
                _rs(hv["used"]), hv["fy_end"], _rs(hv["saved"]), ", ".join("%s %g" % (p["symbol"], p["qty"]) for p in hv["picks"][:5])),
            "#/holdings/tax", "act" if now.month == 3 else "watch")
    try:   # Kite stop-loss GTTs to set or raise
        stp = stops()
        todo = [x for x in stp["rows"] if x["status"] in ("new", "raise", "qty")]
        if todo:
            add("stops:%s:%d" % (day, len(todo)), "act", "Kite stop-loss GTTs: %d to set or change (%s)." % (
                len(todo), ", ".join(x["symbol"] for x in todo[:6]) + (" …" if len(todo) > 6 else "")), "#/holdings/stops", "act")
    except Exception:  # noqa: BLE001
        pass
    # rebalance
    c = rep["core"]
    if c["total"] and abs(c["move"]) >= max(2000, c["total"] * 0.02):
        txt = "Core + satellite: index funds %.0f%% vs your target %d%%. %s about %s." % (
            c["actual"], c["target"], "Move into the index fund" if c["move"] > 0 else "Move from the index fund into stocks", _rs(abs(c["move"])))
        if c["due"]:
            add("rebal", "act", txt + (" April rebalance." if c["april"] else " More than 10 points off."), "#/holdings", "act")
        elif c["off"] > 5:
            add("rebal", "info", txt + " Not due yet (April, or more than 10 points off).", None, "info")
    # tax timing: lots turning long-term within 30 days
    for h in rep["holdings"]:
        if not h.get("counted"):
            continue
        nl = h.get("next_long")
        if nl and nl["days"] <= 30 and (h.get("unreal_short") or 0) > 0:
            add("lt:%s:%s" % (h["symbol"], nl["date"]), "watch", "%s: %g shares turn long-term on %s (%d days). A sale before then is taxed 20%%, after it 12.5%%." % (
                h["symbol"], nl["qty"], nl["date"], nl["days"]), "#/holdings")
    for t in nx["tax"]:
        if "turn long-term" not in t:
            add("tax:" + t[:40], "info", t, None, "info")
    # results within the next 7 days (estimated from the last reported quarter)
    held = [h["symbol"] for h in rep["holdings"] if h.get("counted")][:40]
    try:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(8) as ex:
            dues = dict(zip(held, ex.map(S.mylist._results_due, held)))
    except Exception:  # noqa: BLE001
        dues = {}
    for sym, r in dues.items():
        if r and 0 <= r["days"] <= 7:
            add("res:%s:%s" % (sym, r["date"]), "watch", "%s: quarterly results expected by about %s (estimate): the price can gap." % (sym, r["date"]), "#/earnings/" + sym)
    # paper accounts
    for m in ("swing", "invest"):
        try:
            pf = L.portfolio_long(m)
        except Exception:  # noqa: BLE001
            continue
        for sym in pf.get("closed_now") or []:
            add("pclosed:%s:%s:%s" % (m, sym, day), "info", "Paper %s: %s was sold by the rules today." % (L.LABEL[m], sym), "#/broker", "info")
        for p in pf["positions"]:
            last, stop = p.get("last") or p["entry"], p["stop"]
            if stop and last and (last / stop - 1) * 100 <= 3:
                add("pnear:%s:%s" % (m, p["symbol"]), "watch", "Paper %s: %s is within %.1f%% of its stop %s." % (
                    L.LABEL[m], p["symbol"], (last / stop - 1) * 100, _rs(stop)), "#/broker")
    # GTTs
    try:
        g = S.gtt.listing(mode)["orders"]
        act_g = [o for o in g if o["status"] == "active"]
        trig = [o for o in g if o["status"] == "triggered" and o.get("triggered_date") == day]
        for o in trig:
            add("gtt:%s:%s" % (o["symbol"], day), "info", "Paper GTT bought %s today." % o["symbol"], "#/broker", "info")
        if act_g:
            add("gtts", "info", "%d paper GTT%s waiting (%s mode): %s." % (len(act_g), "" if len(act_g) == 1 else "s", lbl,
                ", ".join("%s at %s" % (o["symbol"], _rs(o["trigger"])) for o in act_g[:6])), "#/broker", "info")
        waiting = {o["symbol"] for o in act_g}
    except Exception:  # noqa: BLE001
        waiting = set()
    # for tomorrow: rule buy signals with room, and your list's stocks near their trigger
    try:
        scan = L.scan_long(mode)
        holds = {h["symbol"] for h in rep["holdings"] if h.get("counted")}
        full = {s_["sector"] for s_ in rep["sectors"] if s_.get("over")}
        if nx["slots"] and scan.get("regime"):
            best = [r for r in scan["rows"] if r.get("status") in ("confirmed", "recent") and (r.get("rs_pct") or 0) >= 50
                    and r["symbol"] not in holds and (r.get("industry") or "Other") not in full]
            best.sort(key=lambda r: -(r.get("rs3" if mode == "swing" else "rs6") or -999))
            for r in best[:4]:
                add("buy:%s:%s" % (r["symbol"], r.get("setup_day")), "tomorrow", "%s (%s): %s rules buy signal, %s, price %s. %d free place%s." % (
                    r["symbol"], r.get("industry") or "", lbl, r.get("setup") or "", _rs(r["price"]), nx["slots"], "" if nx["slots"] == 1 else "s"),
                    "#/predictor/" + r["symbol"])
        watch = set(S.load_state()["settings"].get("watchlist") or [])
        for r in scan["rows"]:
            if r["symbol"] in watch and r.get("trigger") and r.get("price") and r["symbol"] not in waiting \
                    and r.get("status") not in ("confirmed", "recent", "provisional"):
                dist = (r["trigger"] / r["price"] - 1) * 100
                if 0 < dist <= 3:
                    add("near:%s:%s" % (r["symbol"], day), "tomorrow", "%s (your list) is %.1f%% below its breakout level %s: you could set a paper GTT there." % (
                        r["symbol"], dist, _rs(r["trigger"])), "#/myscan")
    except Exception:  # noqa: BLE001
        pass
    with _lock:
        d = _load()
        done = set((d.get("today_done") or {}).get(day) or [])
    order = {"act": 0, "watch": 1, "tomorrow": 2, "info": 3}
    items.sort(key=lambda x: order.get(x["group"], 9))
    for x in items:
        x["done"] = x["id"] in done
    return {"date": day, "mode": mode, "mode_label": lbl, "items": items, "at": S.market_clock()["ist"],
            "counts": {g: sum(1 for x in items if x["group"] == g) for g in order},
            "done": sum(1 for x in items if x["done"]), "snapshot_at": rep["snapshot_at"], "connected": rep["connected"]}


def today_done(body):
    iid = str(body.get("id") or "")[:120]
    day = S.now_ist().date().isoformat()
    with _lock:
        d = _load()
        td = d.setdefault("today_done", {})
        cur = set(td.get(day) or [])
        (cur.add if body.get("done") else cur.discard)(iid)
        td[day] = sorted(cur)
        for k in sorted(td)[:-30]:   # keep a month of ticks
            td.pop(k, None)
        _save(d)
    return {"ok": True}


# ----------------------------------------------------------------- You vs the Nifty: the honest scoreboard
def _close_on(sym, day):
    """Closing price on or before a date, from the daily history (None if the stock has no history)."""
    try:
        bars = L.history(sym)["bars"]
    except Exception:  # noqa: BLE001
        return None
    px = None
    for b in bars:
        if b[0] > day:
            break
        px = b[4]
    return px


def vs_nifty():
    """Your stocks' real return compared with the same money in the Nifty 50 on the same days.

    Start: the day before your records begin. The shares you already held then count as money put in
    that day (valued at that day's close). After that every buy is money in and every sell money out,
    the same rupees on the same dates for both. End: your holdings' value in the last snapshot.
    The Nifty side buys and sells Nifty 50 at each day's close (price index). Dividends are left out on
    both sides, and so are charges and stocks with no price history (listed)."""
    with _lock:
        d = _load()
    trades, _, _ = compute(d)
    snaps = d["snapshots"]
    if not trades or not snaps:
        return {"ok": False, "message": "Needs your Zerodha tradebook (Import & add) and one holdings snapshot (open Live holdings once)."}
    snap_day = sorted(snaps)[-1]
    snap = snaps[snap_day]
    end = (snap.get("at") or snap_day)[:10]
    start = trades[0]["date"]
    t0 = (date.fromisoformat(start) - timedelta(days=1)).isoformat()
    now_q = {r["symbol"]: r.get("qty") or 0 for r in snap.get("holdings") or []}
    now_v = {r["symbol"]: r.get("value") or 0 for r in snap.get("holdings") or []}
    net = {}
    for t in trades:
        net[t["symbol"]] = net.get(t["symbol"], 0) + (t["qty"] if t["side"] == "buy" else -t["qty"])
    start_q = {s: now_q.get(s, 0) - net.get(s, 0) for s in set(now_q) | set(net)}
    excluded, open_v, open_n = [], 0.0, 0
    for s, q in start_q.items():
        if q > 1e-6:
            px = _close_on(s, t0)
            if not px:
                excluded.append(s)
                continue
            open_v += q * px
            open_n += 1
    bad = set(excluded)
    flows = {}
    if open_v:
        flows[t0] = -open_v
    put_in = taken_out = 0.0
    for t in trades:
        if t["symbol"] in bad:
            continue
        a = t["qty"] * t["price"] * (-1 if t["side"] == "buy" else 1)
        flows[t["date"]] = flows.get(t["date"], 0.0) + a
        if a < 0:
            put_in -= a
        else:
            taken_out += a
    value = sum(v for s, v in now_v.items() if s not in bad)
    mkt = L.market()
    nc = mkt.ind["c"]
    units = 0.0
    for day, a in sorted(flows.items()):
        i = mkt.at(day)
        units -= a / nc[i]
    i_end = mkt.at(end)
    nifty_value = units * nc[i_end]
    fl = [(date.fromisoformat(k), v) for k, v in sorted(flows.items())]
    e = date.fromisoformat(end)
    days = (e - date.fromisoformat(t0)).days
    you_x = L._xirr(fl + [(e, value)]) if fl and days > 0 else None
    nif_x = L._xirr(fl + [(e, nifty_value)]) if fl and days > 0 and nifty_value > 0 else None
    paid = -sum(fl_[1] for fl_ in fl)   # net money in (positive) or out
    return {"ok": True, "from": t0, "to": end, "days": days, "open_value": open_v, "open_stocks": open_n,
            "put_in": put_in, "taken_out": taken_out, "value": value, "nifty_value": nifty_value,
            "profit": value - paid, "nifty_profit": nifty_value - paid, "xirr": you_x, "nifty_xirr": nif_x,
            "nifty_from": nc[mkt.at(t0)], "nifty_to": nc[i_end], "excluded": sorted(excluded), "short": days < 365,
            "nifty_units_negative": units < 0}


# ----------------------------------------------------------------- Stops: one Kite stop-loss GTT per real holding
STOP_STEP = 0.02    # ask you to raise a Kite GTT only when the rule stop is 2% or more above the one you set
LIMIT_GAP = 0.02    # the GTT's sell limit sits 2% under the trigger, so a small gap down still fills
TICK = 0.05         # a multiple of every NSE tick size, so Kite accepts the price
STOP_ORDER = {"hit": 0, "new": 1, "raise": 2, "qty": 3, "ok": 4, "none": 5}


def _tick_down(x):
    return round(math.floor(x / TICK + 1e-9) * TICK, 2)


def stops():
    """The Investing rules' trailing stop for every real holding, as a Kite GTT to set once and raise now and then.

    Trigger = highest close of the last 60 sessions minus 5 x ATR (what the backtest sells on when the day's
    low touches it), rounded down to 0.05 and never lowered (the backtest ratchets it up only). The 200-day rule
    (close more than 3% under the 200-day average) is judged on the close, so it stays in the evening list,
    not in a GTT. Index funds in your core list get no stop. Status: hit (price at or under the stop: the exit
    rule has fired), new (no GTT recorded yet), raise (stop is 2%+ above the GTT you set), qty (your quantity
    changed), ok. Not personal advice: you place any GTT yourself in Kite."""
    with _lock:
        d = _load()
        snaps = d["snapshots"]
        if not snaps:
            return {"rows": [], "as_of": None, "counts": {}, "todo": 0}
        day = sorted(snaps)[-1]
        snap = snaps[day]
        core = set(_core_cfg(d)["symbols"])
        book = d.setdefault("stops", {})
        rows, held = [], set()
        for r in snap.get("holdings") or []:
            sym, qty, ltp = r.get("symbol"), r.get("qty") or 0, r.get("ltp")
            if not sym or qty <= 0 or sym in core:
                continue
            held.add(sym)
            rule = r.get("trail_stop") if "trail_stop" in r else r.get("rule_stop")   # older snapshots: rule stop
            b = book.setdefault(sym, {})
            today_trig = _tick_down(rule) if rule else None
            if today_trig:
                b["high"] = max(b.get("high") or 0, today_trig)
            trig, kite = b.get("high"), b.get("kite")
            if not trig:
                status = "none"
            elif ltp and ltp <= trig:
                status = "hit"
            elif not kite:
                status = "new"
            elif trig >= kite * (1 + STOP_STEP):
                status = "raise"
            elif b.get("kite_qty") != qty:
                status = "qty"
            else:
                status = "ok"
            rows.append({"symbol": sym, "qty": qty, "ltp": ltp, "trigger": trig, "limit": _tick_down(trig * (1 - LIMIT_GAP)) if trig else None,
                         "today": today_trig, "away_pct": (ltp / trig - 1) * 100 if ltp and trig else None,
                         "kite": kite, "kite_qty": b.get("kite_qty"), "kite_at": b.get("kite_at"), "status": status,
                         "floor200": r.get("floor200"), "verdict": r.get("verdict"), "value": r.get("value")})
        for sym in [s for s in book if s not in held]:   # sold: forget its stop
            book.pop(sym)
        _save(d)
    rows.sort(key=lambda x: (STOP_ORDER[x["status"]], -(x["value"] or 0)))
    counts = {k: sum(1 for x in rows if x["status"] == k) for k in STOP_ORDER}
    return {"rows": rows, "as_of": snap.get("at"), "counts": counts, "todo": counts["new"] + counts["raise"] + counts["qty"],
            "step_pct": STOP_STEP * 100, "limit_gap_pct": LIMIT_GAP * 100}


def stops_done(body):
    """You set (or raised) these GTTs in Kite: remember the trigger and quantity, so only real changes come back."""
    syms = body.get("symbols")
    with _lock:
        d = _load()
        snaps = d["snapshots"]
        snap = snaps[sorted(snaps)[-1]] if snaps else {}
        qty = {r.get("symbol"): r.get("qty") for r in snap.get("holdings") or []}
        book = d.setdefault("stops", {})
        day = S.now_ist().date().isoformat()
        n = 0
        for sym in (syms if isinstance(syms, list) else list(book)):
            b = book.get(sym)
            if not b or not b.get("high"):
                continue
            if body.get("undo"):
                b.pop("kite", None), b.pop("kite_qty", None), b.pop("kite_at", None)
            else:
                b["kite"], b["kite_qty"], b["kite_at"] = b["high"], qty.get(sym), day
            n += 1
        _save(d)
    return {"ok": True, "message": ("Marked %d as not set in Kite." if body.get("undo") else "Saved: %d GTT stop%s set in Kite.") % (
        n, "" if n == 1 or body.get("undo") else "s")}


def stop_lines(limit=10):
    """Short version for the 15:35 Telegram message: only the GTTs to set or change."""
    s = stops()
    todo = [x for x in s["rows"] if x["status"] in ("new", "raise", "qty")]
    if not todo:
        return ["🛡 Kite stop GTTs: nothing to change."] if s["rows"] else []
    word = {"new": "set", "raise": "raise to", "qty": "change qty"}
    out = ["🛡 Kite stop GTTs to set or change (%d):" % len(todo)]
    out += ["  %s: %s sell %g · trigger %s · limit %s%s" % (x["symbol"], word[x["status"]], x["qty"], _rs2(x["trigger"]), _rs2(x["limit"]),
            " (was %s)" % _rs2(x["kite"]) if x["status"] == "raise" else "") for x in todo[:limit]]
    if len(todo) > limit:
        out.append("  …and %d more: portal → My holdings → Stops." % (len(todo) - limit))
    return out


def _rs2(v):
    return "₹" + format(v, ",.2f")


def today_lines(mode="invest", limit=8):
    """Short version for the 15:35 Telegram message."""
    t = today(mode)
    pick = [x for x in t["items"] if x["group"] in ("act", "watch", "tomorrow")][:limit]
    if not pick:
        return ["✅ Today's checklist: nothing to act on."]
    icon = {"act": "🔴", "watch": "🟡", "tomorrow": "🟢"}
    out = ["✅ Today's checklist (%d to act, %d to watch, %d for tomorrow):" % (t["counts"]["act"], t["counts"]["watch"], t["counts"]["tomorrow"])]
    out += ["%s %s" % (icon[x["group"]], x["text"]) for x in pick]
    more = sum(t["counts"][g] for g in ("act", "watch", "tomorrow")) - len(pick)
    if more > 0:
        out.append("…and %d more: portal → My holdings → Today." % more)
    return out


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


def _harvest(tax, holdings, today):
    """Long-term gains you can still book tax-free this financial year (the Rs 1.25 lakh exemption).

    Sell a long-term lot with a gain and buy it back on the NEXT trading day (same-day buy and sell
    counts as intraday): the gain uses up the exemption instead of being taxed later, and the new
    buy price is higher. Lots with the biggest gain per share go first, so you sell as few shares as
    possible. Lots that turn long-term before 31 March count too (sell on or after that date). Shares
    with no buy date in your records (bought before the tradebook) are listed separately."""
    st_r, lt_r, exempt = _rates(fy_of(today))
    room = max(0.0, exempt - max(tax["long_after_setoff"], 0))
    fy_end = date(today.year if today.month <= 3 else today.year + 1, 3, 31)
    cands, maybe = [], []
    for h in holdings:
        if not h.get("counted"):
            continue
        for l in h["lots"]:
            if not l.get("gain") or l["gain"] <= 0 or l["qty"] <= 0:
                continue
            per = l["gain"] / l["qty"]
            if l["long"] is None:
                maybe.append({"symbol": h["symbol"], "qty": l["qty"], "gain": l["gain"], "avg": l["price"]})
            elif l["long"] or date.fromisoformat(l["long_from"]) <= fy_end:
                cands.append((per, h["symbol"], l))
    cands.sort(key=lambda x: -x[0])
    left, picks = room, []
    for per, sym, l in cands:
        q = min(l["qty"], math.floor(left / per)) if per else 0
        if q < 1:
            continue
        price = (l["price"] or 0) + per
        picks.append({"symbol": sym, "qty": q, "gain": q * per, "price": price, "bought": l["date"],
                      "sell_from": None if l["long"] else l["long_from"], "lot_qty": l["qty"]})
        left -= q * per
    used = room - left
    charges = sum(p["qty"] * p["price"] for p in picks) * DELIVERY_SIDE * 2 + DP_FEE * len(picks)
    return {"fy_end": fy_end.isoformat(), "exempt": exempt, "booked": max(tax["long_after_setoff"], 0), "room": room,
            "picks": picks, "used": used, "saved": used * lt_r * (1 + CESS), "charges": charges, "lt_rate": lt_r,
            "maybe": sorted(maybe, key=lambda m: -m["gain"])[:10], "maybe_gain": sum(m["gain"] for m in maybe)}


def report(fy=None, d_from=None, d_to=None):
    with _lock:
        d = _load()
    trades, lots, realised = compute(d)
    today = S.now_ist().date()
    fy = fy or fy_of(today)
    if not re.fullmatch(r"\d{4}-\d{2}", fy):
        raise S.ApiError(400, "Unknown financial year")
    f0, f1 = _fy_range(fy)
    custom = False
    a, b = _norm_date(d_from) if d_from else None, _norm_date(d_to) if d_to else None
    if a or b:   # a month or any date range instead of the whole financial year
        a, b = a or "2000-01-01", b or today.isoformat()
        if a > b:
            a, b = b, a
        f0, f1, custom = date.fromisoformat(a), date.fromisoformat(b), True
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
    core_syms = set(_core_cfg(d)["symbols"])   # index funds: outside the stock limits
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
    zp = None if custom else (d.get("pnl") or {}).get(fy)   # Zerodha's statement covers a whole year only
    if zp:   # Zerodha's own P&L statement for this year: add stocks it has that the tradebook does not
        for sym, z in zp["stocks"].items():
            if sym not in per and ((z.get("buy_value") or 0) or (z.get("sell_value") or 0) or (z.get("realised") or 0)):
                per[sym] = {"symbol": sym, "buy_qty": 0, "buy_value": 0.0, "sell_qty": 0, "sell_value": 0.0, "first": "", "last": "",
                            "intraday": 0.0, "short": 0.0, "long": 0.0, "unknown_qty": 0, "only_zerodha": True}
    for p in per.values():
        z = (zp or {}).get("stocks", {}).get(p["symbol"]) if zp else None
        p["z_realised"] = z.get("realised") if z else None
        p["z_buy_value"] = z.get("buy_value") if z else None
        p["z_sell_value"] = z.get("sell_value") if z else None
        p["remaining"] = hq.get(p["symbol"], 0)
        p["realised"] = p["intraday"] + p["short"] + p["long"]
        p["avg_buy"] = p["buy_value"] / p["buy_qty"] if p["buy_qty"] else None
        p["avg_sell"] = p["sell_value"] / p["sell_qty"] if p["sell_qty"] else None
        p["sector"] = S.UNIVERSE.get(p["symbol"], {}).get("industry", "") or "Other"
    months = {}   # every month on record, not only the selected period
    for t in trades:
        m = months.setdefault(t["date"][:7], {"month": t["date"][:7], "buys": 0, "buy_value": 0.0, "sells": 0, "sell_value": 0.0, "realised": 0.0})
        m["buys" if t["side"] == "buy" else "sells"] += 1
        m["%s_value" % t["side"]] += t["qty"] * t["price"]
    for r in realised:
        if r["pnl"] is not None:
            months.setdefault(r["date"][:7], {"month": r["date"][:7], "buys": 0, "buy_value": 0.0, "sells": 0, "sell_value": 0.0, "realised": 0.0})["realised"] += r["pnl"]
    # ---- charges (estimate) and tax
    deliv_turn = sum(t["qty"] * t["price"] for t in fy_trades) - sum(r["turnover"] for r in fy_real if r["kind"] == "intraday")
    intra_turn = sum(r["turnover"] for r in fy_real if r["kind"] == "intraday")
    sell_days = len({(t["date"], t["symbol"]) for t in fy_trades if t["side"] == "sell"})
    charges = {"delivery": max(deliv_turn, 0) * DELIVERY_SIDE + sell_days * DP_FEE, "intraday": intra_turn * INTRADAY_COST}
    charges["total"] = charges["delivery"] + charges["intraday"]
    if zp:
        ch = next((v for k, v in zp["summary"].items() if re.fullmatch(r"(total )?charges", k.strip().lower())), None)
        if ch is not None:
            charges["zerodha"] = abs(ch)
    tax = _tax(fy, realised)
    # if everything open were sold today (adds to the current FY only)
    if fy == fy_of(today):
        extra = []
        for h in holdings:
            for l in h["lots"]:
                if l["gain"] is not None and l["long"] is not None:
                    extra.append({"date": today.isoformat(), "kind": "long" if l["long"] else "short", "pnl": l["gain"]})
        tax["if_sold_today"] = _tax(fy, realised, extra)["total_tax"] - tax["total_tax"]
        try:
            tax["harvest"] = _harvest(tax, holdings, today)
        except Exception:  # noqa: BLE001
            tax["harvest"] = None
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
        if (h["value"] or 0) > cfg["max_per_stock"] and h["symbol"] not in core_syms:
            nxt["limits"].append("%s is %s, over your ₹%s per-stock limit" % (h["symbol"], _rs(h["value"]), format(int(cfg["max_per_stock"]), ",")))
        nl = h["next_long"]
        if h["verdict"] in ("exit", "weak") and nl and nl["days"] <= 60 and (h["unreal_short"] or 0) > 0:
            nxt["tax"].append("%s: %g shares turn long-term on %s (%d days). A sale before then is taxed %d%%, after it %.1f%% (above the ₹1.25 lakh exemption)." % (
                h["symbol"], nl["qty"], nl["date"], nl["days"], _rates(fy)[0] * 100, _rates(fy)[1] * 100))
    n_held = sum(1 for h in holdings if h["counted"] and h["symbol"] not in core_syms)
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
    core_v = _core_view(d, snap, holdings, today)
    nxt["plan"] = _plan(snap, cfg, core_syms, core_v)   # your Investing limits, Investing verdicts and buys; sells fill the Nifty core first
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
    pnl_info = None
    if zp:
        pnl_info = {k: zp.get(k) for k in ("at", "file", "from", "to", "summary", "other")}
        pnl_info["realised"] = sum(z.get("realised") or 0 for z in zp["stocks"].values())
        pnl_info["other_total"] = sum(o["amount"] for o in zp.get("other") or [])
        pnl_info["differ"] = [p["symbol"] for p in per.values() if p.get("z_realised") is not None and not p.get("only_zerodha")
                              and abs(p["z_realised"] - p["realised"]) > max(50, abs(p["z_realised"]) * 0.02)]
    return {"fy": fy, "fys": fys, "fy_from": f0.isoformat(), "fy_to": f1.isoformat(), "connected": connected, "totals": totals, "pnl": pnl_info,
            "range": {"from": f0.isoformat(), "to": f1.isoformat(), "custom": custom},
            "core": core_v,
            "snapshot_at": snap["at"] if snap else None, "funds": (snap or {}).get("funds"),
            "holdings": holdings, "per_stock": sorted(per.values(), key=lambda p: -(p["buy_value"] + p["sell_value"])),
            "trades": [dict(t, value=t["qty"] * t["price"]) for t in reversed(fy_trades)],
            "realised": list(reversed(fy_real)), "months": [months[k] for k in sorted(months)],
            "tax": tax, "charges": charges, "sectors": sorted(secs.values(), key=lambda s_: -s_["value"]),
            "next": nxt, "funds_history": funds_hist[-400:], "imports": d["imports"][-20:],
            "records": {"trades": len(d["trades"]), "snapshots": len(snaps), "first_trade": trades[0]["date"] if trades else None},
            "settings": {"max_positions": cfg["max_positions"], "max_per_stock": cfg["max_per_stock"], "max_per_sector": cfg["max_per_sector"]},
            "clock": S.market_clock()}


PLAN_HORIZON = "6–12 months"


def _plan(snap, cfg, core=(), core_v=None):
    """One rebalance plan from your last snapshot: what to sell and what to buy, sector by sector.

    Sells, in order: rule exit fired; over the per-stock limit (trim the excess); sector over its
    limit (weakest first); more stocks than your limit (weakest first). Weak trends are sold only
    when a limit forces it. Buys: the Best-odds Investing signals (confirmed, top-half strength,
    market filter on) in sectors with room after the sells, strongest 6-month strength first,
    one per free slot, sized to the per-stock limit and your cash. Mechanical rule results, not advice.
    Index funds in your core list are left alone: not sold, not counted as stocks; their value still
    counts in the total that sector shares are measured against.
    Nifty core first: money from the sells (and your free cash) goes into a Nifty 50 index fund until the
    core reaches your target share (core_v from _core_view); only what is left buys new stocks.
    """
    if not snap or not snap.get("holdings"):
        return None
    cap, maxn, maxs = cfg["max_per_stock"], cfg["max_positions"], cfg["max_per_sector"]
    if not any(r.get("verdict") for r in snap["holdings"]):   # snapshot without rule verdicts
        return {"horizon": PLAN_HORIZON, "as_of": snap.get("at"), "stale": True, "before": {}, "after": {}, "sells": [], "keeps": [],
                "buys": [], "free_slots": 0, "cash": None,
                "notes": ["Open My holdings while Zerodha is connected once to take a fresh snapshot, then the plan appears."]}
    act = {r["symbol"]: dict(r) for r in snap["holdings"] if (r.get("value") or 0) > 0}   # Investing verdicts (owner's choice, 20 Nov 2026)
    core_held = sorted(s for s in act if s in core)
    core_value = sum(act.pop(s)["value"] for s in core_held)
    others = [act.pop(s) for s in [s for s, r in act.items() if r.get("asset") == "other"]]   # ETFs / gold / silver
    other_value = sum(r["value"] for r in others)   # counted in the total, never in the stock limits
    before = {"holdings": len(act), "value": sum(r["value"] for r in act.values()), "max": maxn,
              "core": core_held, "core_value": core_value}
    sells = []

    def sec(r):
        return r.get("sector") or "Other"

    def total():
        return core_value + other_value + sum(r["value"] for r in act.values()) or 1

    def weakest(rs):   # weak trend first, then the biggest loss first (keep the winners)
        return sorted(rs, key=lambda r: (0 if r.get("verdict") == "weak" else 1, r.get("pnl_pct") or 0))

    def sell_all(r, reason):
        sells.append({"symbol": r["symbol"], "sector": sec(r), "qty": r.get("qty") or 0, "value": r["value"],
                      "pnl_pct": r.get("pnl_pct"), "verdict": r.get("verdict"), "reason": reason, "all": True})
        act.pop(r["symbol"], None)

    def rlab(r):
        return "Trading" if r.get("hmode") == "swing" else "Investing"

    for r in others:
        if r.get("verdict") == "exit":
            sells.append({"symbol": r["symbol"], "sector": "Other asset", "qty": r.get("qty") or 0, "value": r["value"],
                          "pnl_pct": r.get("pnl_pct"), "verdict": "exit", "reason": "ETF / other asset: trailing stop broken", "all": True})
            other_value -= r["value"]
    for r in list(act.values()):
        if r.get("verdict") == "exit":
            sell_all(r, "%s rules: exit fired (%s)" % (rlab(r), r.get("why") or "stop broken"))
    big = [r["symbol"] for r in act.values() if r["value"] > cap]   # winners are kept: the limit only blocks new buys
    while True:   # sector over its stock count or 25% of the value: sell its weakest, one at a time
        T, by = total(), {}
        for r in act.values():
            if sec(r) != "Other":
                by.setdefault(sec(r), []).append(r)
        bad = next(((s, rs) for s, rs in by.items()
                    if len(rs) > maxs or sum(x["value"] for x in rs) / T * 100 > 25), None)
        if not bad:
            break
        w = weakest(bad[1])[0]
        sell_all(w, "%s is over its sector limit (its weakest: %s)" % (bad[0], w.get("verdict") or "–"))
    while len(act) > maxn:   # more stocks than your limit
        sell_all(weakest(list(act.values()))[0], "over your %d-stock limit" % maxn)

    # swap: a holding whose Trading trend has turned weak makes room for a Best-odds buy signal
    fit = snap.get("fit") or {}   # Investing Best-odds buys
    regime = fit.get("regime")
    cash = (snap.get("funds") or {}).get("net")
    cands = [b for b in (fit.get("buys") or []) if regime and b.get("price") and b["symbol"] not in act]
    weak = weakest([r for r in act.values() if r.get("verdict") == "weak"])
    for r in weak[:max(0, min(len(weak), len(cands) - (maxn - len(act))))]:
        sell_all(r, "weak trend: swap for a stronger buy signal")

    free = maxn - len(act)
    T = total()
    sec_n, sec_v = {}, {}
    for r in act.values():
        sec_n[sec(r)] = sec_n.get(sec(r), 0) + 1
        sec_v[sec(r)] = sec_v.get(sec(r), 0) + r["value"]
    proceeds = sum(s["value"] for s in sells)
    cash_after = None if cash is None else cash + proceeds   # cash plus what the sells bring in
    buys, notes = [], []
    core_buy = None
    if core_v and core_v.get("total") and (core_v.get("move") or 0) > 0:   # fill the Nifty core first
        need = core_v["move"]
        avail = cash_after if cash_after is not None else proceeds
        amt = max(0.0, min(need, avail or 0))
        held = [s for s in (core_v.get("symbols") or []) if s in core_held] or ["NIFTYBEES"]
        cv_after = core_v["core_value"] + amt
        core_buy = {"amount": amt, "need": need, "short": need - amt, "fund": held[0], "target": core_v["target"],
                    "pct_now": core_v.get("actual"), "core_after": cv_after, "pct_after": None}
        if cash_after is not None:
            cash_after -= amt
        if amt and core_buy["short"] > 1000:
            notes.append("The Nifty core is still %s short of your %d%% target after this: later sells and new cash go there first." % (
                _rs(core_buy["short"]), core_v["target"]))
    if not regime:
        notes.append("Market filter is off: the Investing rules hold off new buys.")
    for b in (fit.get("buys") or []) if regime else []:
        if len(buys) >= free:
            break
        s, price = b.get("sector") or "Other", b.get("price")
        if b["symbol"] in act or not price:
            continue
        if s != "Other" and (sec_n.get(s, 0) >= maxs or sec_v.get(s, 0) / (T or 1) * 100 >= 25):
            continue
        budget = cap if cash_after is None else min(cap, cash_after / max(free, 1))
        qty = int(budget // price)
        if qty < 1:
            continue
        buys.append({"symbol": b["symbol"], "name": b.get("name"), "sector": s, "setup": b.get("setup"), "rs6": b.get("rs6"),
                     "price": price, "qty": qty, "amount": qty * price})
        sec_n[s] = sec_n.get(s, 0) + 1
        sec_v[s] = sec_v.get(s, 0) + qty * price
        T += qty * price
    if core_buy:   # core share once every sell, trim and buy is done
        sat_after = sum(r["value"] for r in act.values()) + sum(b["amount"] for b in buys)
        tot_after = core_buy["core_after"] + sat_after
        core_buy["pct_after"] = core_buy["core_after"] / tot_after * 100 if tot_after else None
    bought = {b["symbol"] for b in buys}
    waiting = [{"symbol": b["symbol"], "sector": b.get("sector") or "Other", "setup": b.get("setup"), "rs6": b.get("rs6"),
                "price": b.get("price")} for b in cands if b["symbol"] not in bought][:6]
    if not free and waiting:
        notes.append("Every place is taken after the sells (limit %d stocks), so the buy signals wait until a place frees up." % maxn)
    if free > len(buys):
        notes.append("%d free slot%s not filled: no Best-odds buy fits the sector and cash limits." % (
            free - len(buys), "" if free - len(buys) == 1 else "s"))
    big = [x for x in big if x in act]
    if big:
        notes.append("Over your %s per-stock limit, kept (winners are not trimmed), no more buys: %s." % (_rs(cap), ", ".join(big)))
    if others:
        notes.append("Other assets (ETFs, gold, silver: %s) are outside the stock limits; sold only when their trailing stop breaks." % ", ".join(r["symbol"] for r in others))
    if core_held:
        notes.append("Index funds (%s, %s) are your core: not counted in the %d-stock or per-stock limits and not sold by this plan." % (
            ", ".join(core_held), _rs(core_value), maxn))
    if not sells and not buys:
        notes.append("Nothing to change: holdings are within your limits and there is no buy signal with room.")
    return {"horizon": PLAN_HORIZON, "as_of": snap.get("at"), "before": before,
            "sells": sells, "keeps": [{"symbol": r["symbol"], "verdict": r.get("verdict"), "pnl_pct": r.get("pnl_pct"), "sector": sec(r)}
                                      for r in act.values()],
            "buys": buys, "free_slots": free, "after": {"holdings": len(act) + len(buys), "max": maxn},
            "waiting": waiting, "cash": cash, "cash_after": cash_after, "per_stock": cap, "core_buy": core_buy, "notes": notes + [
                "Each stock is judged by its own tag (Investing by default, or Trading); limits from your Investing settings. "
                "Investing rules (holds 6–12 months), backtested Dec 2017–Nov 2026 (~10.7%/yr, 38% of trades won, worst fall −34%, losing years too). "
                "Not a promise of profit and not personal advice."]}


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
