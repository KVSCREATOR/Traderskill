"""Full history of the portal: your actions, paper orders, GTTs, alerts and every message.

data/activity_log.jsonl is append-only (never trimmed): it records what YOU do in the portal
(alerts added / deleted, settings, Zerodha / Telegram connect, paper resets, restarts...).
Orders and GTTs come from the paper accounts and GTT list themselves (their full records),
and messages from data/notify_log.jsonl, so nothing is shown twice.
"""
import json
import os
import threading

S = None   # server
L = None   # longterm
R = None   # reports

_lock = threading.Lock()
MODE = {"intraday": "Scalping", "swing": "Trading", "invest": "Investing"}


def _path():
    return os.path.join(S.DATA, "activity_log.jsonl")


def add(cat, title, detail="", mode=None, status="done"):
    rec = {"ts": S.market_clock()["ist"], "cat": cat, "title": title, "detail": detail, "mode": mode, "status": status}
    with _lock:
        os.makedirs(S.DATA, exist_ok=True)
        with open(_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _rs(v, dec=2):
    try:
        return S.telegram._rs(v, dec)
    except Exception:  # noqa: BLE001
        return str(v)


def log_post(path, body, result, mode):
    """Called after every successful POST from the browser. Orders / GTTs are not logged here
    (their own records are complete); everything else you do is."""
    b = body or {}
    m = MODE.get(mode, mode)
    try:
        if path == "/api/alerts":
            for a in b.get("alerts") or ([b] if b.get("symbol") else []):
                add("alert", "Alert added: %s %s %s" % (a.get("symbol", ""), a.get("type", ""), a.get("level", "")), a.get("label", ""), None)
        elif path == "/api/alerts/delete":
            add("alert", "Alert deleted", "id %s" % b.get("id", ""))
        elif path == "/api/alerts/rearm":
            add("alert", "Alert re-armed", "id %s" % b.get("id", ""))
        elif path == "/api/settings":
            keys = [k for k in b.keys() if k not in ("mode", "confirm")]
            add("action", "Settings saved (%s)" % m, ", ".join(keys)[:300], mode)
        elif path == "/api/kite/disconnect":
            add("action", "Zerodha disconnected")
        elif path == "/api/kite/connect":
            add("action", "Zerodha login started")
        elif path == "/api/telegram/settings":
            on = b.get("on") or {}
            add("action", "Telegram messages changed", ", ".join("%s %s" % (k, "on" if v else "off") for k, v in on.items())[:300])
        elif path in ("/api/telegram/connect", "/api/telegram/disconnect"):
            add("action", "Telegram " + path.rsplit("/", 1)[1] + "ed")
        elif path == "/api/ledger/pin/set":
            add("action", "My holdings PIN set (with the portal password)")
        elif path == "/api/ledger/pin/change":
            add("action", "My holdings PIN changed")
        elif path == "/api/ledger/import":
            add("action", "Zerodha tradebook imported", (result or {}).get("message", "")[:200])
        elif path == "/api/ledger/pnl":
            add("action", "Zerodha P&L statement imported", (result or {}).get("message", "")[:200])
        elif path == "/api/ledger/manual":
            add("action", "My holdings record: trade %s by hand" % ("deleted" if b.get("action") == "delete" else "added"), (result or {}).get("message", "")[:200])
        elif path == "/api/admin/restart":
            add("action", "Portal restarted from Limits")
        elif path == "/api/reports/run":
            add("action", "Report run now: %s" % b.get("kind", ""))
    except Exception:  # noqa: BLE001
        pass


def _actions():
    try:
        with open(_path(), encoding="utf-8") as f:
            return [json.loads(x) for x in f if x.strip()]
    except OSError:
        return []


def _orders(st):
    out = []
    books = [("intraday", st.get("paper") or {}), ("swing", st.get("paper_swing") or {}), ("invest", st.get("paper_invest") or {})]
    for mode, book in books:
        for t in book.get("trades") or []:
            ts = t.get("closed_at") or t.get("closed_date") or ""
            out.append({"ts": ts, "cat": "order", "mode": mode, "status": "win" if (t.get("pnl") or 0) > 0 else "loss",
                        "title": "Paper sell: %s %s %s" % (t.get("qty"), t.get("symbol"), "at " + _rs(t.get("exit"))),
                        "detail": "Bought %s on %s · %s · P&L %s%s" % (
                            _rs(t.get("entry")), t.get("opened_date", ""), t.get("reason", ""), _rs(t.get("pnl"), 0),
                            (" · %+.2fR" % t["r"]) if isinstance(t.get("r"), (int, float)) else "")})
            out.append({"ts": t.get("opened_at") or t.get("opened_date") or "", "cat": "order", "mode": mode,
                        "status": "done", "title": "Paper buy: %s %s at %s" % (t.get("qty"), t.get("symbol"), _rs(t.get("entry"))),
                        "detail": "Closed later: %s" % (t.get("reason") or "")})
        for p in book.get("positions") or []:
            out.append({"ts": p.get("opened_at") or p.get("opened_date") or "", "cat": "order", "mode": mode, "status": "open",
                        "title": "Paper buy: %s %s at %s" % (p.get("qty"), p.get("symbol"), _rs(p.get("entry"))),
                        "detail": "Still open · stop %s%s" % (_rs(p.get("stop")), (" · " + p["setup"]) if p.get("setup") else "")})
    return out


def _gtts(st):
    out = []
    for o in st.get("gtt") or []:
        way = "rises to" if o.get("direction") == "above" else "falls to"
        qty = ("%s × " % o["qty"]) if o.get("qty") else ""
        out.append({"ts": o.get("created_at", ""), "cat": "gtt", "mode": o.get("mode"), "status": o.get("status", ""),
                    "title": "GTT set: buy %s%s when price %s %s" % (qty, o.get("symbol"), way, _rs(o.get("trigger"))),
                    "detail": "Stop %s%s · now %s%s" % (_rs(o["stop"]) if o.get("stop") else "by the rules",
                                                       (" · target " + _rs(o["target"])) if o.get("target") else "",
                                                       o.get("status", ""), (" · " + o["note"]) if o.get("note") else "")})
        if o.get("status") not in ("active", None) and o.get("closed_at"):
            out.append({"ts": o["closed_at"], "cat": "gtt", "mode": o.get("mode"), "status": o["status"],
                        "title": "GTT %s: %s" % (o["status"], o.get("symbol")), "detail": o.get("note") or ""})
    return out


def _messages():
    try:
        rows = R.history(100000)["rows"]
    except Exception:  # noqa: BLE001
        rows = []
    return [{"ts": r["ts"], "cat": "message", "kind": r["kind"], "status": r["status"], "mid": r.get("mid"),
             "title": (r["text"].split("\n")[0])[:160], "detail": r["text"], "error": r.get("error")} for r in rows]


def history():
    st = S.load_state()
    rows = _actions() + _orders(st) + _gtts(st) + _messages()
    for r in rows:
        r.setdefault("cat", "action")
        r["mode_label"] = MODE.get(r.get("mode") or "", "")
    rows.sort(key=lambda r: r.get("ts") or "", reverse=True)
    counts = {}
    for r in rows:
        counts[r["cat"]] = counts.get(r["cat"], 0) + 1
    return {"rows": rows, "counts": counts, "total": len(rows)}
