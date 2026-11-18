"""Read-only link to your Zerodha account through Zerodha's free hosted Kite MCP server.

Flow (OAuth 2.1 with PKCE, no API key or secret, no paid Kite Connect plan):
  1. "Connect Zerodha" registers this portal once as a public client at mcp.kite.trade
     (redirect back to http://127.0.0.1:<port>/api/kite/callback) and opens Zerodha's login.
  2. You sign in on Zerodha's own page. This portal never sees your password or 2FA code.
  3. The callback swaps the one-time code for an access token, kept only in data/state.json.
  4. Holdings / positions / profile are read by calling the MCP server's READ tools.

Only the tools in READ_TOOLS can ever be called. Order tools are refused in code, so this
link can never place, change or cancel a real order.
"""
import base64
import html
import hashlib
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

S = None   # server module
L = None   # longterm module

BASE = "https://mcp.kite.trade"
MCP_URL = BASE + "/mcp"
# tool -> the only modes this portal may use (all read-only). Anything else is refused.
READ_TOOLS = {"portfolio": {"holdings", "positions", "profile", "margins"}, "mutual_funds": {"holdings"}}
_pending = {}   # state -> {"verifier", "at"}
_session = {"id": None, "token": None}


def _cb_url():
    if S.PUBLIC_URL:   # NAS / home server: Zerodha must send the browser back to that address
        return S.PUBLIC_URL + "/api/kite/callback"
    return "http://127.0.0.1:%d/api/kite/callback" % S.PORT


def _http(url, data=None, headers=None, form=False, timeout=30):
    h = {"User-Agent": "Tradeskill-local/1.0", "Accept": "application/json, text/event-stream"}
    h.update(headers or {})
    body = None
    if data is not None:
        if form:
            body = urllib.parse.urlencode(data).encode()
            h["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            body = json.dumps(data).encode()
            h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=h, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode("utf-8", "replace")


def _kite(st):
    return st.setdefault("kite", {})


# ----------------------------------------------------------------- login
def connect_url():
    """Register once (if needed) and return Zerodha's login URL."""
    with S._state_lock:
        st = S.load_state()
        k = _kite(st)
        if k.get("client_id") and k.get("redirect") != _cb_url():
            k.pop("client_id", None)   # port changed: register again
        if not k.get("client_id"):
            code, _, body = _http(BASE + "/register", {
                "client_name": "Tradeskill portal (local, read-only)", "redirect_uris": [_cb_url()],
                "grant_types": ["authorization_code"], "response_types": ["code"],
                "token_endpoint_auth_method": "none"})
            if code >= 300:
                raise S.ApiError(502, "Kite MCP refused to register this portal (%d): %s" % (code, body[:200]))
            k["client_id"] = json.loads(body)["client_id"]
            k["redirect"] = _cb_url()
            S.save_state(st)
        client_id = k["client_id"]
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    _pending[state] = {"verifier": verifier, "at": time.time()}
    q = {"response_type": "code", "client_id": client_id, "redirect_uri": _cb_url(), "code_challenge": challenge,
         "code_challenge_method": "S256", "state": state, "scope": "default", "resource": MCP_URL}
    return {"url": BASE + "/authorize?" + urllib.parse.urlencode(q)}


D = None   # daily module


def callback(q, signed_in=True):
    """Finish the login. Returns an HTML page that sends you back to the portal."""
    state, code = q.get("state"), q.get("code")
    p = _pending.pop(state or "", None)
    if q.get("error"):
        return _page("Zerodha login was cancelled or failed: %s" % (q.get("error_description") or q["error"]), False)
    if not p or not code or time.time() - p["at"] > 900:
        return _page("This login link has expired. Click Connect Zerodha again.", False)
    with S._state_lock:
        st = S.load_state()
        k = _kite(st)
        status, _, body = _http(BASE + "/token", {
            "grant_type": "authorization_code", "code": code, "redirect_uri": _cb_url(),
            "client_id": k.get("client_id", ""), "code_verifier": p["verifier"], "resource": MCP_URL}, form=True)
        if status >= 300:
            return _page("Zerodha did not accept the login (%d). Try Connect Zerodha again." % status, False)
        tok = json.loads(body)
        k["token"] = tok["access_token"]
        k["refresh"] = tok.get("refresh_token")
        k["expires"] = time.time() + float(tok.get("expires_in") or 6 * 3600)
        k["connected_at"] = S.market_clock()["ist"]
        S.save_state(st)
    _session.update(id=None, token=None)
    _held.update(at=0, data=None)
    try:
        D.after_login()   # first login of the day -> holdings + funds on Telegram
    except Exception:  # noqa: BLE001
        pass
    if not signed_in:   # came from the phone link: no portal session needed, just confirm
        return ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
                "<body style='font:17px system-ui;padding:40px;text-align:center'><h2>✅ Zerodha connected</h2>"
                "<p>Read-only. Your holdings summary is on its way to Telegram. You can close this page.</p>")
    return _page("Zerodha connected (read-only). Loading your holdings…", True)


def _page(msg, ok):
    return ("<!doctype html><meta charset=utf-8><title>Zerodha</title><body style='font:15px system-ui;padding:40px'>"
            "<p>%s</p><script>setTimeout(()=>location.href='/#/holdings',%d)</script>" % (html.escape(msg), 800 if ok else 4000))


def disconnect():
    with S._state_lock:
        st = S.load_state()
        for key in ("token", "refresh", "expires", "connected_at"):
            _kite(st).pop(key, None)
        S.save_state(st)
    _session.update(id=None, token=None)
    _held.update(at=0, data=None)
    return {"ok": True}


# ----------------------------------------------------------------- MCP calls (read tools only)
def _rpc(token, method, params=None, rid=1):
    h = {"Authorization": "Bearer " + token, "MCP-Protocol-Version": "2025-03-26"}
    if _session["id"] and _session["token"] == token:
        h["Mcp-Session-Id"] = _session["id"]
    msg = {"jsonrpc": "2.0", "method": method}
    if rid is not None:
        msg["id"] = rid
    if params is not None:
        msg["params"] = params
    code, hdr, body = _http(MCP_URL, msg, h, timeout=45)
    sid = next((v for k_, v in hdr.items() if k_.lower() == "mcp-session-id"), None)
    if sid:
        _session.update(id=sid, token=token)
    if code == 401:
        _held.update(at=time.time(), data={"connected": False, "symbols": []})
        raise S.ApiError(401, "Zerodha login has expired. Click Connect Zerodha.")
    if code >= 300:
        raise S.ApiError(502, "Kite MCP error %d: %s" % (code, body[:200]))
    if rid is None or not body.strip():
        return None
    # answer may be plain JSON or a server-sent-events stream
    if body.lstrip().startswith("{"):
        out = json.loads(body)
    else:
        out = None
        for line in body.splitlines():
            if line.startswith("data:"):
                try:
                    j = json.loads(line[5:].strip())
                except ValueError:
                    continue
                if j.get("id") == rid:
                    out = j
        if out is None:
            raise S.ApiError(502, "Kite MCP sent an answer this portal could not read.")
    if "error" in out:
        raise S.ApiError(502, "Kite MCP: %s" % out["error"].get("message", out["error"]))
    return out.get("result")


def _ensure_session(token):
    if _session["id"] and _session["token"] == token:
        return
    _session.update(id=None, token=None)
    _rpc(token, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                               "clientInfo": {"name": "tradeskill-portal", "version": "1.0"}})
    _rpc(token, "notifications/initialized", rid=None)


def call(tool, args=None):
    if tool not in READ_TOOLS or (args or {}).get("mode") not in READ_TOOLS[tool]:
        raise S.ApiError(403, "Blocked: this portal only reads your Zerodha account.")
    st = S.load_state()
    k = _kite(st)
    token = k.get("token")
    if not token:
        raise S.ApiError(401, "Not connected. Click Connect Zerodha.")
    for attempt in range(2):
        _ensure_session(token)
        try:
            res = _rpc(token, "tools/call", {"name": tool, "arguments": args or {}}, rid=int(time.time() * 1000) % 10 ** 9)
            break
        except S.ApiError as e:
            if attempt == 0 and e.code == 502 and "session" in e.msg.lower():
                _session.update(id=None, token=None)
                continue
            raise
    texts = [c.get("text", "") for c in (res or {}).get("content", []) if c.get("type") == "text"]
    text = "\n".join(texts)
    if res and res.get("isError"):
        return {"error": text}
    try:
        return {"data": json.loads(text)}
    except ValueError:
        return {"text": text}


# ----------------------------------------------------------------- sector fit
SECTOR_MAX_PCT = 25.0   # flag a sector above a quarter of the portfolio


def _sector_fit(rows, total, cfg):
    """Sector balance from your limits plus the tested stock rules.

    - Too much in one sector: more than SECTOR_MAX_PCT of the value, or more stocks than
      your 'max per sector' limit.
    - Trim first: holdings in those sectors whose rules say Exit / Weak, weakest first.
    - Sector mood: from the Investing scan of all 250 stocks - share in a long uptrend and
      average 6-month strength vs the Nifty. NOTE: a sector-strength filter did not improve
      the backtest (tested Nov 2026), so mood is shown for information only.
    - Rule buy signals: 'Best odds' Investing signals (confirmed, top-half strength, market
      filter on) in sectors you are not over the limit in and do not already hold.
    """
    scan = L.scan_long("invest")
    per = {}
    for r in scan["rows"]:
        sec = r.get("industry") or "Other"
        a = per.setdefault(sec, {"n": 0, "up": 0, "rs": []})
        a["n"] += 1
        a["up"] += 1 if r.get("up_long") else 0
        if r.get("rs6") is not None:
            a["rs"].append(r["rs6"])
    held = {}
    for h in rows:
        sec = h["sector"] or "Other"
        g = held.setdefault(sec, {"value": 0.0, "stocks": []})
        g["value"] += h["value"]
        g["stocks"].append(h)
    order = {"exit": 0, "weak": 1, "hold": 2, "buy": 3}
    sectors = []
    for sec in sorted(set(per) | set(held)):
        a, g = per.get(sec), held.get(sec, {"value": 0.0, "stocks": []})
        pct = g["value"] / total * 100 if total else 0
        mood_up = a["up"] / a["n"] * 100 if a and a["n"] else None
        mood_rs = sum(a["rs"]) / len(a["rs"]) if a and a["rs"] else None
        over = sec != "Other" and (pct > SECTOR_MAX_PCT or len(g["stocks"]) > cfg["max_per_sector"])
        mood = None if mood_up is None else ("Strong" if mood_up >= 60 and (mood_rs or 0) > 0 else
                                              "Weak" if mood_up < 40 or (mood_rs or 0) < -5 else "Mixed")
        trim = sorted((x for x in g["stocks"] if x.get("verdict") in ("exit", "weak")),
                      key=lambda x: (order.get(x.get("verdict"), 9), x.get("pnl_pct") or 0))
        sectors.append({"sector": sec, "value": g["value"], "pct": pct, "stocks": len(g["stocks"]),
                        "over": over, "mood": mood, "uptrend_pct": mood_up, "rs6": mood_rs,
                        "exits": [x["symbol"] for x in g["stocks"] if x.get("verdict") == "exit"],
                        "trim": [{"symbol": x["symbol"], "verdict": x["verdict"], "why": x.get("why")} for x in trim[:3]] if over else []})
    sectors.sort(key=lambda z: -z["value"])
    held_syms = {h["symbol"] for h in rows}
    over_secs = {z["sector"] for z in sectors if z["over"] or (z["sector"] != "Other" and z["stocks"] >= cfg["max_per_sector"])}
    buys = [r for r in scan["rows"] if scan.get("regime") and r.get("status") in ("confirmed", "recent")
            and (r.get("rs_pct") or 0) >= 50 and r["symbol"] not in held_syms and (r.get("industry") or "Other") not in over_secs]
    buys.sort(key=lambda r: -(r.get("rs6") or -999))
    return {"sectors": sectors, "limit_pct": SECTOR_MAX_PCT, "max_per_sector": cfg["max_per_sector"], "regime": bool(scan.get("regime")),
            "buys": [{"symbol": r["symbol"], "name": r["name"], "sector": r.get("industry"), "setup": r.get("setup"),
                      "rs6": r.get("rs6"), "price": r.get("price")} for r in buys[:6]]}


# ----------------------------------------------------------------- holdings view
def _verdict(ind, mkt, mode="invest"):
    """What the Investing rules (backtested Nov 2017 - Nov 2026) say about a stock you already hold.

    Exit signal: the rules' own exit fired (close more than 3% below the 200-day average, or
    below the trailing stop = highest close of the last 60 sessions minus 5 x ATR).
    Weak: still above both exits but the trend is not up (below the 50-day or 200-day falling).
    Buy signal: the entry rules fire now (52-week-high breakout or pullback to the 50-day).
    Hold: uptrend intact, above the rule stop.
    """
    i = len(ind["c"]) - 1
    c, s50, s200, atr = ind["c"][i], ind["sma50"][i], ind["sma200"][i], ind["atr"][i]
    r = L.RULES[mode]
    trail = max(ind["c"][max(0, i - 59):i + 1]) - r["trail_atr"] * atr if atr else None
    floor200 = s200 * 0.97 if s200 and mode == "invest" else None   # the 200-day exit is an Investing rule only
    stop = max(x for x in (trail, floor200) if x is not None) if (trail or floor200) else None
    s200_old = ind["sma200"][i - 20] if i >= 20 else None
    out = {"rule_stop": stop, "to_stop": (c / stop - 1) * 100 if stop else None}
    if floor200 and c < floor200:
        return dict(out, verdict="exit", why="Closed more than 3% below the 200-day average")
    if trail and c < trail:
        return dict(out, verdict="exit", why="Below the trailing stop (60-day high close minus %g ATR)" % r["trail_atr"])
    sig = L.state_at(mode, ind, mkt)
    if sig["status"] in ("confirmed", "recent", "provisional"):
        return dict(out, verdict="buy", why="Entry rule active: " + (sig["setup"][1] if sig["setup"] else ""))
    if (s50 and c < s50) or (s200 and s200_old and s200 < s200_old):
        return dict(out, verdict="weak", why="Below the 50-day average" if s50 and c < s50 else "200-day average is falling")
    return dict(out, verdict="hold", why="Uptrend intact, above the rule stop")


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _login_needed(r):
    t = (r.get("error") or r.get("text") or "")
    m = re.search(r"https://kite\.zerodha\.com/connect/login\S+", t)
    return m.group(0).rstrip(").,") if m else (t if "login" in t.lower() else None)


def holdings(mode="invest"):
    st = S.load_state()
    k = _kite(st)
    if not k.get("token"):
        return {"connected": False}
    r = call("portfolio", {"mode": "holdings", "type": "full", "limit": 500})
    need = _login_needed(r) if "data" not in r else None
    if need:
        url = need if need.startswith("https://") else None
        if not url:
            raise S.ApiError(401, "Zerodha login has expired. Click Connect Zerodha.")
        return {"connected": True, "kite_login": url, "message": "Zerodha asks you to log in to Kite once more for this session."}
    rows = r.get("data")
    if isinstance(rows, dict):
        rows = rows.get("data") or rows.get("holdings") or []
    if not isinstance(rows, list):
        return {"connected": True, "error": (r.get("error") or r.get("text") or "Unexpected answer")[:300]}
    rmode = mode if mode in ("swing", "invest") else "invest"   # Scalping is same-day: judge holdings by Investing rules
    cfg = L.settings_for(rmode, st)
    mkt = L.market()
    out = []
    for h in rows:
        sym = (h.get("tradingsymbol") or h.get("symbol") or "").upper()
        qty = (_num(h.get("quantity")) or 0) + (_num(h.get("t1_quantity")) or 0)
        avg, ltp = _num(h.get("average_price")), _num(h.get("last_price"))
        close = _num(h.get("close_price"))
        value, cost = (ltp or 0) * qty, (avg or 0) * qty
        row = {"symbol": sym, "exchange": h.get("exchange"), "qty": qty, "avg": avg, "ltp": ltp, "value": value,
               "cost": cost, "pnl": value - cost, "pnl_pct": (value / cost - 1) * 100 if cost else None,
               "day_pct": (ltp / close - 1) * 100 if ltp and close else _num(h.get("day_change_percentage")),
               "day_pnl": (ltp - close) * qty if ltp and close else None,
               "sector": S.UNIVERSE.get(sym, {}).get("industry", ""), "flags": [],
               "detail": {"exchange": h.get("exchange"), "isin": h.get("isin"), "product": h.get("product"),
                          "settled_qty": _num(h.get("quantity")), "t1_qty": _num(h.get("t1_quantity")),
                          "realised_qty": _num(h.get("realised_quantity")), "opening_qty": _num(h.get("opening_quantity")),
                          "used_qty": _num(h.get("used_quantity")), "authorised_qty": _num(h.get("authorised_quantity")),
                          "authorised_date": h.get("authorised_date"), "collateral_qty": _num(h.get("collateral_quantity")),
                          "collateral_type": h.get("collateral_type"), "close": close,
                          "day_change": _num(h.get("day_change")), "day_change_pct": _num(h.get("day_change_percentage")),
                          "zerodha_pnl": _num(h.get("pnl")), "discrepancy": bool(h.get("discrepancy")),
                          "mtf": {k_: v_ for k_, v_ in (h.get("mtf") or {}).items() if _num(v_)} or None}}
        try:
            ind = L.indicators(L.history(sym)["bars"])
            i = len(ind["c"]) - 1
            c, s50, s200 = ind["c"][i], ind["sma50"][i], ind["sma200"][i]
            hh = max(ind["h"][-252:])
            row["trend"] = ("Strong up" if s50 and s200 and c > s50 > s200 else "Above 200-day" if s200 and c > s200
                            else "Below 200-day" if s200 else "–")
            row["from_high"] = (c / hh - 1) * 100
            row["vs_50"] = (c / s50 - 1) * 100 if s50 else None
            row.update(_verdict(ind, mkt, rmode))
        except Exception:  # noqa: BLE001
            row["trend"] = "–"
        if value > cfg["max_per_stock"]:
            row["flags"].append("Over your ₹%s per-stock cap" % format(int(cfg["max_per_stock"]), ","))
        out.append(row)
    out.sort(key=lambda x: -x["value"])
    tv, tc = sum(x["value"] for x in out), sum(x["cost"] for x in out)
    secs = {}
    for x in out:
        secs[x["sector"] or "Other"] = secs.get(x["sector"] or "Other", 0) + x["value"]
    warn = []
    if len(out) > cfg["max_positions"]:
        warn.append("%d holdings vs your limit of %d" % (len(out), cfg["max_positions"]))
    try:
        fit = _sector_fit(out, tv, cfg)
    except Exception as e:  # noqa: BLE001
        fit = {"error": str(e)[:150]}
    return {"connected": True, "rules_mode": rmode, "rules_label": L.LABEL[rmode], "fit": fit, "rows": out, "total_value": tv, "total_cost": tc, "pnl": tv - tc,
            "pnl_pct": (tv / tc - 1) * 100 if tc else None, "day_pnl": sum(x["day_pnl"] or 0 for x in out),
            "sectors": sorted(([k_, v] for k_, v in secs.items()), key=lambda z: -z[1]), "warnings": warn,
            "connected_at": k.get("connected_at"), "clock": S.market_clock()}


# ----------------------------------------------------------------- light helpers for other pages
_held = {"at": 0, "data": None}


def held():
    """Symbols you hold (cached 5 min). Never raises: other pages just hide the extras."""
    d = _held["data"]
    # re-check every 2 min while connected, every 30 s while not, so an expired login hides the extras quickly
    if d and time.time() - _held["at"] < (120 if d["connected"] else 30):
        return d
    out = {"connected": False, "symbols": []}
    try:
        if _kite(S.load_state()).get("token"):
            r = call("portfolio", {"mode": "holdings", "type": "full", "limit": 500})
            rows = r.get("data")
            if isinstance(rows, dict):
                rows = rows.get("data") or []
            if isinstance(rows, list):
                syms, items = [], []
                for h in rows:
                    sym = (h.get("tradingsymbol") or h.get("symbol") or "").upper()
                    qty = (_num(h.get("quantity")) or 0) + (_num(h.get("t1_quantity")) or 0)
                    if not sym or sym in syms or not qty:   # skip sold-out rows (0 shares)
                        continue
                    syms.append(sym)
                    avg, ltp, close = _num(h.get("average_price")), _num(h.get("last_price")), _num(h.get("close_price"))
                    items.append({"symbol": sym, "qty": qty, "ltp": ltp,
                                  "day_pct": (ltp / close - 1) * 100 if ltp and close else _num(h.get("day_change_percentage")),
                                  "pnl_pct": (ltp / avg - 1) * 100 if ltp and avg else None})
                out = {"connected": True, "symbols": syms, "items": items}
    except Exception:  # noqa: BLE001
        pass
    _held.update(at=time.time(), data=out)
    return out


def _rows(r):
    d = r.get("data")
    if isinstance(d, dict):
        d = d.get("data") if "data" in d else d.get("net", d)
    return d if isinstance(d, list) else []


def extras():
    """Positions, mutual funds and funds (all read-only)."""
    out = {"positions": [], "mfs": [], "funds": None, "margins": {}, "profile": None, "errors": []}
    try:
        for p in _rows(call("portfolio", {"mode": "positions"})):
            qty = _num(p.get("quantity")) or 0
            if not qty and not _num(p.get("pnl")):
                continue
            out["positions"].append({"symbol": p.get("tradingsymbol"), "product": p.get("product"), "qty": qty,
                                     "avg": _num(p.get("average_price")), "ltp": _num(p.get("last_price")),
                                     "pnl": _num(p.get("pnl")) or 0, "exchange": p.get("exchange"),
                                     "overnight_qty": _num(p.get("overnight_quantity")), "day_buy": _num(p.get("day_buy_quantity")),
                                     "day_sell": _num(p.get("day_sell_quantity")), "realised": _num(p.get("realised"))})
    except Exception as e:  # noqa: BLE001
        out["errors"].append("Positions: %s" % str(e)[:100])
    try:
        for m in _rows(call("mutual_funds", {"mode": "holdings"})):
            q, avg, ltp = _num(m.get("quantity")) or 0, _num(m.get("average_price")) or 0, _num(m.get("last_price")) or 0
            out["mfs"].append({"fund": m.get("fund") or m.get("tradingsymbol"), "units": q, "avg": avg, "nav": ltp,
                               "nav_date": m.get("last_price_date"), "value": q * ltp, "cost": q * avg, "pnl": q * (ltp - avg),
                               "pnl_pct": (ltp / avg - 1) * 100 if avg else None})
        out["mfs"].sort(key=lambda x: -x["value"])
    except Exception as e:  # noqa: BLE001
        out["errors"].append("Mutual funds: %s" % str(e)[:100])
    try:
        m = call("portfolio", {"mode": "margins"}).get("data") or {}
        eq = m.get("equity") or {}
        av = eq.get("available") or {}
        out["funds"] = {"net": _num(eq.get("net")), "cash": _num(av.get("live_balance") or av.get("cash")),
                        "used": _num((eq.get("utilised") or {}).get("debits"))}
        for seg in ("equity", "commodity"):
            s_ = m.get(seg) or {}
            if s_:
                out["margins"][seg] = {"enabled": s_.get("enabled"), "net": _num(s_.get("net")),
                                       "available": {k_: _num(v_) for k_, v_ in (s_.get("available") or {}).items() if _num(v_) is not None},
                                       "utilised": {k_: _num(v_) for k_, v_ in (s_.get("utilised") or {}).items() if _num(v_) is not None}}
    except Exception as e:  # noqa: BLE001
        out["errors"].append("Funds: %s" % str(e)[:100])
    try:   # profile: name, client ID and segments only (no e-mail, no photo)
        p = call("portfolio", {"mode": "profile"}).get("data") or {}
        lst = lambda v: ", ".join(v) if isinstance(v, list) else (v or "")  # noqa: E731
        out["profile"] = {"name": p.get("user_name"), "user_id": p.get("user_id"), "broker": p.get("broker"),
                          "type": p.get("user_type"), "exchanges": lst(p.get("exchanges")), "products": lst(p.get("products")),
                          "demat_consent": (p.get("meta") or {}).get("demat_consent")}
    except Exception as e:  # noqa: BLE001
        out["errors"].append("Profile: %s" % str(e)[:100])
    return out
