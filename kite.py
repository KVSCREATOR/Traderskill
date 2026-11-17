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
READ_TOOLS = {"portfolio": {"holdings", "positions", "profile", "margins"}}
_pending = {}   # state -> {"verifier", "at"}
_session = {"id": None, "token": None}


def _cb_url():
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


def callback(q):
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


# ----------------------------------------------------------------- holdings view
def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _login_needed(r):
    t = (r.get("error") or r.get("text") or "")
    m = re.search(r"https://kite\.zerodha\.com/connect/login\S+", t)
    return m.group(0).rstrip(").,") if m else (t if "login" in t.lower() else None)


def holdings():
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
    cfg = L.settings_for("invest", st)
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
               "sector": S.UNIVERSE.get(sym, {}).get("industry", ""), "flags": []}
        try:
            ind = L.indicators(L.history(sym)["bars"])
            i = len(ind["c"]) - 1
            c, s50, s200 = ind["c"][i], ind["sma50"][i], ind["sma200"][i]
            hh = max(ind["h"][-252:])
            row["trend"] = ("Strong up" if s50 and s200 and c > s50 > s200 else "Above 200-day" if s200 and c > s200
                            else "Below 200-day" if s200 else "–")
            row["from_high"] = (c / hh - 1) * 100
            row["vs_50"] = (c / s50 - 1) * 100 if s50 else None
            if s200 and c < s200 * 0.97:
                row["flags"].append("Closed well below the 200-day average (Investing rules would exit)")
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
    return {"connected": True, "rows": out, "total_value": tv, "total_cost": tc, "pnl": tv - tc,
            "pnl_pct": (tv / tc - 1) * 100 if tc else None, "day_pnl": sum(x["day_pnl"] or 0 for x in out),
            "sectors": sorted(([k_, v] for k_, v in secs.items()), key=lambda z: -z[1]), "warnings": warn,
            "connected_at": k.get("connected_at"), "clock": S.market_clock()}
