"""AI Robot: a self-running PAPER trader (owner's 1-month test, started 20 Nov 2026).

Separate on purpose so it can be removed without touching anything else:
  - its own data file  data/robot.json   (nothing in state.json)
  - its own thread      start() from server main, guarded
  - its own page        static/robot.js (adds itself to the menu)
To remove: delete robot.py + static/robot.js + the <script> line + the guarded lines in server.py.

What it does (never a real order, Zerodha is never touched):
  09:15-15:28  every strategy checked about every 3 min (owner 20 Nov 2026: no fixed buy/sell time)
               4 daily-chart swing strategies (Short swing, Dip buy, Bullish candle, 52-week high), all
               backtested positive after charges in 2017-22 AND 2022-26; completed-day signals any time
               while the price is within 3% of the signal close, today's forming signal from 15:10
  scalps       ORB and afternoon momentum: OFF by default (lost after charges in the 60-day tests)
  15:35        diary: per-strategy notes + scorecard (best performer, what suits the doubling goal)
  alert time   day report + AI review on Telegram (numbers checked)
Diary: data/robot_diary.jsonl, kept 5 years, deletable by hand on the page.
The robot decides its own size: each strategy earns or loses its share by its own results
after all charges (STT, brokerage, exchange, SEBI, stamp, GST, DP, slippage); it trades smaller
in a drawdown, stops for the day after -3%, pauses after -15% from the peak.
A small learning model (logistic regression, pure Python) is trained on every candidate it saw;
it is only allowed to filter trades after it beats chance on days it was not trained on.
"""
import json
import math
import os
import random
import re
import threading
import time
from datetime import datetime

S = None   # server module
L = None   # longterm module
T = None   # telegram module
AI = None  # ai module

START_CAPITAL = 150000.0
TARGET_X = 2.0
SLIP = 0.0003            # 0.03% slippage each side (buy fills higher, sell lower)
MIS_MARGIN = 0.20        # intraday needs 20% margin (5x, like Zerodha MIS)
DAY_STOP = 0.03          # no new entries after -3% on the day
PAUSE_DD = 0.15          # no new entries for 5 trading days after -15% from the peak
MAX_SCALPS_DAY = 6
MAX_SWING = 10           # owner 20 Nov 2026: more strategies -> more slots (was 5)
SWING_CAP = 0.20         # one swing <= 20% of the money (was 25% with 5 slots)
BASE_RISK = 1.5          # % of equity per trade before the strategy factor (was 1.0); still capped by risk_cap
MAX_PER_SECTOR = 2
SCALP_EXIT_M = 900       # 15:00
DAY_FROM_M, DAY_TO_M = 555, 928   # owner: check every strategy all session, 09:15-15:28
FORMING_M = 910          # from 15:10 a daily signal forming today counts (close to how it was tested)
MAX_EXT = 0.03           # buy a daily signal only within 3% above its signal-day close (as tested)
DIARY_YEARS = 5          # owner: keep the diary 5 years; entries can be deleted by hand on the page
# expect = average R per trade after all charges in the 20 Nov 2026 study (2017-22 / 2022-26 halves)
STRATS = {
    "swing": {"label": "Short swing (Trading v2 rules)", "kind": "delivery", "prior": 1.0, "expect": 0.30,
              "why": "Base breakout / pullback in an uptrend, stop 2 ATR, trail 3 ATR, break-even after +2R. Backtest 2017-2026: +0.14R / +0.40R per trade after costs."},
    "dip": {"label": "Dip buy in an uptrend", "kind": "delivery", "prior": 1.0, "expect": 0.35,
            "why": "Stock in an uptrend (above rising 50-day, 50 above 200) falls 3 days in a row or RSI(2) under 10; same stop and trail as Short swing. Backtest: +0.27R / +0.43R per trade after costs."},
    "candle": {"label": "Bullish candle at the average", "kind": "delivery", "prior": 1.0, "expect": 0.27,
               "why": "Bullish engulfing or hammer after touching the 20/50-day average in an uptrend, stronger than Nifty; same stop and trail. Backtest: +0.28R / +0.25R per trade after costs."},
    "high52": {"label": "52-week-high breakout", "kind": "delivery", "prior": 1.0, "expect": 0.29,
               "why": "Closes above its 52-week high on 1.5x volume, near the day's high, in an uptrend, stronger than Nifty; same stop and trail. Backtest: +0.13R / +0.45R per trade after costs."},
    "orb": {"label": "Morning breakout scalp (ORB)", "kind": "intraday", "prior": 0.5, "expect": -0.15, "default_off": True,
            "why": "9:15-9:30 range breakout, stop 1 ATR, target 2R. Lost money after charges in the 60-day studies (19-20 Nov), so it is OFF; switch on only to watch it."},
    "pm": {"label": "Afternoon momentum scalp (experiment)", "kind": "intraday", "prior": 0.25, "expect": -0.12, "default_off": True,
           "why": "14:30 stocks at the day's high on strong volume. Tested 20 Nov on 60 days: -0.14R / -0.10R per trade after charges, so it is OFF."},
}
NEW_DAILY = ("high52", "dip", "candle")   # order tried per stock (one signal per stock per day)
_lock = threading.Lock()
_mem = {"last_scan": 0, "busy": False}


# ----------------------------------------------------------------- storage
def _path():
    return os.path.join(S.DATA, "robot.json")


def _fresh(capital=START_CAPITAL):
    return {"on": True, "capital": capital, "cash": capital, "started": None, "positions": [], "trades": [],
            "equity": [], "peak": capital, "pause_until": None, "day": {}, "samples": [], "log": [],
            "strat_on": {k: not v.get("default_off") for k, v in STRATS.items()}, "risk_cap": 2.0, "model": None, "sent": {},
            "version": 2, "alert_at": "15:32"}   # owner: robot trading alert after the close (time editable on the page)


def load():
    try:
        with open(_path(), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = _fresh()
    if not d.get("version"):
        d["version"] = 1
    base = _fresh(d.get("capital") or START_CAPITAL)
    for k, v in base.items():
        d.setdefault(k, v)
    for k, v in STRATS.items():
        d["strat_on"].setdefault(k, not v.get("default_off"))
    return d


def migrate():
    """v1 -> v2 (20 Nov 2026): 3 new daily strategies, both scalps off (they lost after charges), diary to its own file."""
    with _lock:
        d = load()
        if d["version"] >= 2:
            return
        for e in d.get("log") or []:
            _diary_append(dict(e, id=_eid(), strat=None))
        d["log"] = []
        d["strat_on"]["orb"] = d["strat_on"]["pm"] = False
        d["version"] = 2
        _say(d, "Upgrade: 3 new daily-chart strategies added (Dip buy, Bullish candle at the average, 52-week-high breakout), "
                "both scalps switched OFF (they lost money after charges in the 60-day tests), up to %d swings at %d%% each, "
                "base risk %.1f%% per trade, every strategy checked all session." % (MAX_SWING, SWING_CAP * 100, BASE_RISK), "info")
        save(d)


def save(d):
    d["log"] = []   # the diary lives in robot_diary.jsonl (5 years)
    d["samples"] = d["samples"][-4000:]
    d["sent"] = dict(list(d["sent"].items())[-60:])
    os.makedirs(S.DATA, exist_ok=True)
    tmp = _path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, _path())


# ----------------------------------------------------------------- diary (own file, kept DIARY_YEARS, deletable on the page)
_dlock = threading.Lock()
_dcache = {"mtime": None, "rows": []}


def _dpath():
    return os.path.join(S.DATA, "robot_diary.jsonl")


def _eid():
    return "%x%03x" % (time.time_ns(), random.randrange(4096))


def _diary_append(e):
    os.makedirs(S.DATA, exist_ok=True)
    with _dlock:
        with open(_dpath(), "a", encoding="utf-8") as f:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
        _dcache["mtime"] = None


def _say(d, text, kind="info", strat=None):
    """One diary line. kind: buy, sell, loss, skip, score, ai, info, error. strat: strategy id or None."""
    _diary_append({"id": _eid(), "at": S.now_ist().strftime("%Y-%m-%d %H:%M"), "kind": kind, "strat": strat, "text": text})


def _diary_all():
    with _dlock:
        try:
            mt = os.path.getmtime(_dpath())
        except OSError:
            return []
        if _dcache["mtime"] != mt:
            rows = []
            with open(_dpath(), encoding="utf-8") as f:
                for line in f:
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        continue
            _dcache.update(mtime=mt, rows=rows)
        return _dcache["rows"]


def _diary_match(e, flt):
    if flt.get("strat"):
        if flt["strat"] == "general" and e.get("strat"):
            return False
        if flt["strat"] != "general" and e.get("strat") != flt["strat"]:
            return False
    if flt.get("kind") and e.get("kind") not in flt["kind"].split(","):
        return False
    if flt.get("from") and e["at"][:10] < flt["from"]:
        return False
    if flt.get("to") and e["at"][:10] > flt["to"]:
        return False
    if flt.get("q") and flt["q"].lower() not in e.get("text", "").lower():
        return False
    return True


def _diary_flt(body):
    flt = {k: str(body.get(k) or "").strip() for k in ("strat", "kind", "from", "to", "q")}
    for k in ("from", "to"):
        if flt[k] and not re.fullmatch(r"\d{4}-\d\d-\d\d", flt[k]):
            raise S.ApiError(400, "Dates as YYYY-MM-DD.")
    return flt


def diary(body=None):
    body = body or {}
    flt = _diary_flt(body)
    rows = [e for e in _diary_all() if _diary_match(e, flt)]
    limit = max(1, min(int(body.get("limit") or 150), 2000))
    return {"items": rows[::-1][:limit], "total": len(rows), "all": len(_diary_all()), "oldest": (_diary_all() or [{}])[0].get("at")}


def _diary_rewrite(keep_fn):
    with _dlock:
        rows = []
        try:
            with open(_dpath(), encoding="utf-8") as f:
                for line in f:
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        continue
        except OSError:
            return 0
        kept = [e for e in rows if keep_fn(e)]
        tmp = _dpath() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(json.dumps(e, ensure_ascii=False) + "\n" for e in kept)
        os.replace(tmp, _dpath())
        _dcache["mtime"] = None
        return len(rows) - len(kept)


def diary_delete(body):
    """Owner deletes by hand: given ids, or every entry matching the filter (one day, a date range, one strategy...)."""
    ids = body.get("ids")
    if ids:
        ids = set(str(i) for i in ids)
        return _diary_rewrite(lambda e: e.get("id") not in ids)
    flt = _diary_flt(body)
    return _diary_rewrite(lambda e: not _diary_match(e, flt))


def diary_prune():
    from datetime import timedelta
    cut = (S.now_ist() - timedelta(days=round(365.25 * DIARY_YEARS))).strftime("%Y-%m-%d")
    rows = _diary_all()
    if rows and rows[0]["at"][:10] < cut:
        _diary_rewrite(lambda e: e["at"][:10] >= cut)


# ----------------------------------------------------------------- charges (Zerodha, Nov 2026)
def charges(kind, buy_val, sell_val):
    """Every charge on one round trip. intraday = MIS equity, delivery = CNC equity."""
    turnover = buy_val + sell_val
    txn = 0.0000297 * turnover          # NSE transaction charge
    sebi = 0.000001 * turnover          # SEBI ₹10 per crore
    if kind == "intraday":
        brok = min(20.0, 0.0003 * buy_val) + min(20.0, 0.0003 * sell_val)
        stt = 0.00025 * sell_val
        stamp = 0.00003 * buy_val
        dp = 0.0
    else:
        brok = 0.0
        stt = 0.001 * turnover
        stamp = 0.00015 * buy_val
        dp = 15.93                      # depository charge per sell (₹13.5 + GST)
    gst = 0.18 * (brok + txn + sebi)
    parts = {"brokerage": brok, "stt": stt, "exchange": txn, "sebi": sebi, "stamp": stamp, "gst": gst, "dp": dp}
    parts = {k: round(v, 2) for k, v in parts.items()}
    parts["total"] = round(sum(parts.values()), 2)
    return parts


# ----------------------------------------------------------------- money
def _mark(d, prices=None):
    prices = prices or {}
    val = 0.0
    for p in d["positions"]:
        px = prices.get(p["symbol"]) or p.get("last") or p["entry"]
        if p["kind"] == "intraday":
            val += p["margin"] + (px - p["entry"]) * p["qty"]
        else:
            val += px * p["qty"]
    return d["cash"] + val


def equity(d):
    return _mark(d)


def _strat_stats(d, k, last=20):
    tr = [t for t in d["trades"] if t["strat"] == k]
    recent = tr[-last:]
    n = len(tr)
    avg_r = sum(t["r"] for t in recent) / len(recent) if recent else None
    return {"n": n, "won": sum(1 for t in tr if t["net"] > 0), "net": round(sum(t["net"] for t in tr), 2),
            "charges": round(sum(t["charges"]["total"] for t in tr), 2), "avg_r": avg_r}


def strat_factor(d, k):
    """How much of the normal size this strategy has earned: by its own results after charges."""
    st = _strat_stats(d, k)
    if st["n"] < 15:
        return STRATS[k]["prior"], "learning (%d of 15 trades)" % st["n"]
    a = st["avg_r"] or 0
    if a >= 0.2:
        return 1.5, "proven: %+.2fR per trade (last 20)" % a
    if a >= 0.0:
        return 1.0, "break-even or a little better: %+.2fR" % a
    if a >= -0.15:
        return 0.5, "slightly losing: %+.2fR, half size" % a
    return 0.25, "losing: %+.2fR, probe size only" % a


def risk_pct(d, k, vix=None):
    """Risk per trade as % of equity: the robot's own decision."""
    eq = equity(d)
    dd = 1 - eq / max(d["peak"], 1)
    f, why = strat_factor(d, k)
    base = BASE_RISK * f
    notes = [why]
    if dd > 0.10:
        base *= 0.5
        notes.append("down %.0f%% from the peak: half size" % (dd * 100))
    elif dd > 0.05:
        base *= 0.75
        notes.append("down %.0f%% from the peak: 3/4 size" % (dd * 100))
    elif eq > d["capital"] * 1.15 and f >= 1.0:
        base *= 1.25
        notes.append("ahead >15%%: a little bigger")
    if vix and vix > 22:
        base *= 0.5
        notes.append("India VIX %.1f: half size" % vix)
    return min(base, d.get("risk_cap") or 2.0), notes


# ----------------------------------------------------------------- learning model (logistic regression)
FEATS = ("orb", "swing", "pm", "minute", "gap", "rvol", "or_atr", "risk_pct", "nifty", "vix", "news", "chg")


def _x(f):
    s = f.get("strat")
    v = [1.0 if s == "orb" else 0.0, 1.0 if STRATS.get(s, {}).get("kind") == "delivery" else 0.0, 1.0 if s == "pm" else 0.0,
         ((f.get("minute") or 600) - 600) / 300.0, (f.get("gap") or 0) / 2.0, min(f.get("rvol") or 1, 5) - 1,
         (f.get("or_atr") or 0.7) - 0.7, (f.get("risk_pct") or 1) - 1, (f.get("nifty") or 0) / 1.0,
         ((f.get("vix") or 14) - 14) / 5.0, (f.get("news") or 0) / 2.0, (f.get("chg") or 0) / 2.0]
    return v


def _fit(rows, epochs=300, lr=0.1, l2=0.01):
    w = [0.0] * (len(FEATS) + 1)
    for _ in range(epochs):
        g = [0.0] * len(w)
        for x, y in rows:
            z = w[0] + sum(a * b for a, b in zip(w[1:], x))
            p = 1 / (1 + math.exp(-max(-30, min(30, z))))
            e = p - y
            g[0] += e
            for i, a in enumerate(x):
                g[i + 1] += e * a
        n = len(rows)
        w = [w[0] - lr * g[0] / n] + [wi - lr * (gi / n + l2 * wi) for wi, gi in zip(w[1:], g[1:])]
    return w


def _prob(w, x):
    z = w[0] + sum(a * b for a, b in zip(w[1:], x))
    return 1 / (1 + math.exp(-max(-30, min(30, z))))


def _auc(pairs):
    pos = [p for p, y in pairs if y]
    neg = [p for p, y in pairs if not y]
    if not pos or not neg:
        return None
    win = sum((1.0 if a > b else 0.5 if a == b else 0.0) for a in pos for b in neg)
    return win / (len(pos) * len(neg))


def train(d):
    """Walk-forward: train on the older 70% of days, judge on the newest 30% it never saw."""
    rows = [s for s in d["samples"] if s.get("y") is not None]
    if len(rows) < 80:
        d["model"] = {"ready": False, "n": len(rows), "why": "needs 80 finished samples, has %d" % len(rows)}
        return d["model"]
    rows.sort(key=lambda s: s["day"])
    cut = int(len(rows) * 0.7)
    tr, te = rows[:cut], rows[cut:]
    w = _fit([(_x(s), s["y"]) for s in tr])
    auc = _auc([(_prob(w, _x(s)), s["y"]) for s in te])
    useful = auc is not None and auc >= 0.56 and len(te) >= 25
    w_all = _fit([(_x(s), s["y"]) for s in rows]) if useful else w
    d["model"] = {"ready": useful, "n": len(rows), "auc": round(auc, 3) if auc else None, "w": w_all,
                  "base": round(sum(s["y"] for s in rows) / len(rows), 3), "trained": S.now_ist().strftime("%Y-%m-%d"),
                  "why": ("beats chance on unseen days (AUC %.2f): it may skip weak trades" % auc) if useful
                  else ("not better than chance on unseen days yet (AUC %s): watching only" % ("%.2f" % auc if auc else "–"))}
    return d["model"]


def model_p(d, f):
    m = d.get("model") or {}
    return _prob(m["w"], _x(f)) if m.get("w") else None


# ----------------------------------------------------------------- market mood
def mood():
    out = {"nifty": None, "vix": None}
    for key, ys in (("nifty", "^NSEI"), ("vix", "^INDIAVIX")):
        try:
            m = S.yahoo_chart(ys, "1d", "5m", 120)[0]
            px, prev = m.get("regularMarketPrice"), m.get("chartPreviousClose") or m.get("previousClose")
            out[key] = ((px / prev - 1) * 100 if px and prev else None) if key == "nifty" else px
        except Exception:  # noqa: BLE001
            pass
    return out


def news_score(sym):
    """+1 per positive, -1 per negative headline of the last day (0 if none)."""
    try:
        cutoff = time.time() - 86400
        its = [i for i in S.news(sym)["items"] if i["ts"] >= cutoff]
        return sum(1 if i["tone"] == "pos" else -1 if i["tone"] == "neg" else 0 for i in its)
    except Exception:  # noqa: BLE001
        return 0


# ----------------------------------------------------------------- trading
def _day(d, today):
    if d["day"].get("date") != today:
        d["day"] = {"date": today, "start_eq": equity(d), "scalps": 0, "orb_done": [], "pm_done": False,
                    "swing_done": [], "closed15": False, "after": False, "report": False}
    return d["day"]


def _can_enter(d, today):
    day = _day(d, today)
    eq = equity(d)
    if d.get("pause_until") and today < d["pause_until"]:
        return False, "paused after a 15%% fall until %s" % d["pause_until"]
    if eq <= day["start_eq"] * (1 - DAY_STOP):
        return False, "day stop: down 3% today"
    return True, ""


def _open(d, strat, sym, price, stop, target, feats, why, sector=""):
    k = STRATS[strat]["kind"]
    fill = price * (1 + SLIP)
    rp, notes = risk_pct(d, strat, feats.get("vix"))
    eq = equity(d)
    risk_amt = eq * rp / 100
    per = fill - stop
    if per <= 0:
        return None
    qty = int(risk_amt // per)
    need = (fill * qty * (MIS_MARGIN if k == "intraday" else 1))
    if k == "delivery":
        qty = min(qty, int((eq * SWING_CAP) // fill))  # one swing <= 20% of the money
        need = fill * qty
    if need > d["cash"]:
        qty = int(d["cash"] // (fill * (MIS_MARGIN if k == "intraday" else 1)))
        need = fill * qty * (MIS_MARGIN if k == "intraday" else 1)
    if k == "intraday":
        qty = min(qty, int((2 * eq) // fill))          # one scalp <= 2x the money (40% margin)
        need = fill * qty * MIS_MARGIN
    if qty < 1:
        return None
    pos = {"t_open": time.time(), "id": "%s-%s-%d" % (strat, sym, int(time.time())), "strat": strat, "kind": k, "symbol": sym, "sector": sector,
           "qty": qty, "entry": round(fill, 2), "stop": round(stop, 2), "stop0": round(stop, 2), "R": round(per, 4),
           "target": round(target, 2) if target else None, "opened": S.now_ist().strftime("%Y-%m-%d %H:%M"),
           "margin": round(need, 2), "risk_pct": round(rp, 2), "why": why, "size_why": notes, "feats": feats,
           "last": fill, "maxc": fill, "bars": 0}
    d["cash"] -= need
    d["positions"].append(pos)
    _say(d, "BUY %d %s @ ₹%.2f · %s · stop ₹%.2f%s · risk %.2f%% (%s)" % (
        qty, sym, fill, STRATS[strat]["label"], stop, " · target ₹%.2f" % target if target else "", rp, "; ".join(notes)), "buy", strat)
    return pos


def _close(d, p, price, reason):
    fill = price * (1 - SLIP)
    bv, sv = p["entry"] * p["qty"], fill * p["qty"]
    ch = charges(p["kind"], bv, sv)
    gross = sv - bv
    net = gross - ch["total"]
    if p["kind"] == "intraday":
        d["cash"] += p["margin"] + gross - ch["total"]
    else:
        d["cash"] += sv - ch["total"]
    r = net / (p["R"] * p["qty"]) if p["R"] else 0
    t = {"id": p["id"], "strat": p["strat"], "kind": p["kind"], "symbol": p["symbol"], "qty": p["qty"], "entry": p["entry"],
         "exit": round(fill, 2), "opened": p["opened"], "closed": S.now_ist().strftime("%Y-%m-%d %H:%M"), "reason": reason,
         "gross": round(gross, 2), "charges": ch, "net": round(net, 2), "r": round(r, 3), "why": p["why"], "risk_pct": p["risk_pct"]}
    d["trades"].append(t)
    d["positions"] = [x for x in d["positions"] if x["id"] != p["id"]]
    for s in d["samples"]:
        if s.get("pid") == p["id"]:
            s["y"] = 1 if net > 0 else 0
            s["r"] = round(r, 3)
    _say(d, "SELL %d %s @ ₹%.2f · %s · net %s₹%.0f (charges ₹%.0f) · %+.2fR" % (
        p["qty"], p["symbol"], fill, reason, "+" if net >= 0 else "−", abs(net), ch["total"], r), "sell" if net >= 0 else "loss", p["strat"])
    return t


def _sample(d, f, pid=None, taken=False, skip=None):
    s = dict(f, day=S.now_ist().strftime("%Y-%m-%d"), pid=pid, taken=taken, skip=skip, y=None)
    d["samples"].append(s)
    return s


def _recent_exit(d, sym, days=5):
    from datetime import timedelta
    cut = (S.now_ist() - timedelta(days=days)).strftime("%Y-%m-%d")
    return any(t["symbol"] == sym and t["closed"][:10] >= cut for t in d["trades"])


def _price(sym):
    q = S.quote(sym, 20)
    return q.get("price"), q.get("bars") or []


def manage(d, clk):
    """Stops, targets, the 15:00 close for scalps; intraday stop check for swings."""
    m = clk["minute"]
    for p in list(d["positions"]):
        try:
            px, bars = _price(p["symbol"])
        except Exception:  # noqa: BLE001
            continue
        if not px:
            continue
        p["last"] = px
        if p["kind"] == "intraday":
            after = [b for b in bars if b["t"] >= p.get("t_open", 0)]   # only bars after the entry
            lo = min([b["l"] for b in after] + [px])
            hi = max([b["h"] for b in after] + [px])
            if lo <= p["stop"]:
                _close(d, p, min(px, p["stop"]), "stop hit")
            elif p.get("target") and hi >= p["target"]:
                _close(d, p, max(px, p["target"]) if px >= p["target"] else p["target"], "target hit")
            elif m >= SCALP_EXIT_M:
                _close(d, p, px, "15:00 close (scalps never stay overnight)")
        elif px <= p["stop"]:
            _close(d, p, px, "trailing stop" if p["stop"] > p["stop0"] else "stop hit")


def _atr_daily(sym):
    _, daily = S.chart(sym, "1y", "1d", 300)
    return S.atr(daily[:-1] if daily else daily), daily


def orb_entries(d, clk, md):
    if not d["strat_on"].get("orb"):
        return
    day = _day(d, clk["date"])
    rows = S.scan()["rows"]
    for r in rows:
        if day["scalps"] >= MAX_SCALPS_DAY:
            break
        o = r.get("orb") or {}
        sym = r["symbol"]
        if o.get("state") != "confirmed" or o.get("outcome") != "open" or sym in day["orb_done"] or not r.get("live"):
            continue
        if any(p["symbol"] == sym for p in d["positions"]):
            continue
        day["orb_done"].append(sym)
        f = {"strat": "orb", "symbol": sym, "minute": clk["minute"], "gap": None, "rvol": r.get("rvol"), "or_atr": o.get("or_atr"),
             "risk_pct": o.get("risk_pct"), "nifty": md["nifty"], "vix": md["vix"], "chg": r.get("change_pct")}
        skip = None
        if not o.get("or_atr") or not (0.5 <= o["or_atr"] <= 1.0):
            skip = "range not 0.5-1 x ATR"
        elif (o.get("risk_pct") or 0) < 0.4:
            skip = "stop too tight for charges"
        price = r.get("price")
        if not skip and (not price or not o.get("entry") or price > o["entry"] * 1.005):
            skip = "price already ran past the entry"
        if not skip:
            f["news"] = news_score(sym)
            if f["news"] <= -2:
                skip = "negative news today"
        p = model_p(d, f)
        f["p"] = round(p, 3) if p is not None else None
        if not skip and (d.get("model") or {}).get("ready") and p is not None and p < 0.35:
            skip = "learning model: low win chance (%.0f%%)" % (p * 100)
        if skip:
            _sample(d, f, skip=skip)
            continue
        ok, why = _can_enter(d, clk["date"])
        if not ok:
            _sample(d, f, skip=why)
            continue
        try:
            a, _ = _atr_daily(sym)
        except Exception:  # noqa: BLE001
            continue
        if not a:
            continue
        stop = price - 1.0 * a
        pos = _open(d, "orb", sym, price, stop, price + 2 * (price - stop), f,
                    "ORB breakout at %s, range %.2f x ATR" % (o.get("time") or "", o["or_atr"]), r.get("industry", ""))
        _sample(d, f, pid=pos["id"] if pos else None, taken=bool(pos), skip=None if pos else "no money for even 1 share")
        if pos:
            day["scalps"] += 1


def pm_entries(d, clk, md):
    if not d["strat_on"].get("pm"):
        return
    day = _day(d, clk["date"])
    day["pm_done"] = True
    rows = [r for r in S.scan()["rows"] if r.get("live")]
    picks = 0
    for r in rows:
        if picks >= 2 or day["scalps"] >= MAX_SCALPS_DAY:
            break
        sym = r["symbol"]
        if any(p["symbol"] == sym for p in d["positions"]):
            continue
        try:
            px, bars = _price(sym)
        except Exception:  # noqa: BLE001
            continue
        tb = [b for b in bars if datetime.fromtimestamp(b["t"], S.IST).date().isoformat() == clk["date"]] if bars else []
        if not px or len(tb) < 30:
            continue
        hi = max(b["h"] for b in tb)
        if not ((r.get("change_pct") or 0) > 1 and px >= hi * 0.997 and (r.get("rvol") or 0) >= 1.2 and r.get("trend_up")):
            continue
        f = {"strat": "pm", "symbol": sym, "minute": clk["minute"], "rvol": r.get("rvol"), "nifty": md["nifty"],
             "vix": md["vix"], "chg": r.get("change_pct"), "news": news_score(sym)}
        p = model_p(d, f)
        f["p"] = round(p, 3) if p is not None else None
        ok, why = _can_enter(d, clk["date"])
        if not ok or f["news"] <= -2:
            _sample(d, f, skip=why or "negative news today")
            continue
        try:
            a, _ = _atr_daily(sym)
        except Exception:  # noqa: BLE001
            continue
        if not a:
            continue
        stop = px - 0.5 * a
        pos = _open(d, "pm", sym, px, stop, px + 1.5 * (px - stop), f, "At the day's high at %s on %.1fx volume" % (S.hm(clk["minute"]), r.get("rvol") or 0), r.get("industry", ""))
        _sample(d, f, pid=pos["id"] if pos else None, taken=bool(pos))
        if pos:
            day["scalps"] += 1
            picks += 1


def swing_entries(d, clk, md):
    if not d["strat_on"].get("swing"):
        return
    day = _day(d, clk["date"])
    data = L.scan_long("swing")
    if not data.get("regime"):
        if "regime" not in day:
            day["regime"] = False
            _say(d, "Market filter is off (Nifty below its 50/200-day averages), so no new swing buys today (all daily strategies wait).")
        return
    held = [p for p in d["positions"] if p["kind"] == "delivery"]
    ok_status = ("confirmed", "recent") + (("provisional",) if clk["minute"] >= FORMING_M else ())   # forming signal only near the close
    for r in data["rows"]:
        if len(held) >= MAX_SWING:
            break
        sym = r["symbol"]
        if r.get("status") not in ok_status or sym in day["swing_done"] or any(p["symbol"] == sym for p in d["positions"]):
            continue
        if _recent_exit(d, sym):
            continue
        day["swing_done"].append(sym)
        sec = r.get("industry") or ""
        if sec and sum(1 for p in held if p.get("sector") == sec) >= MAX_PER_SECTOR:
            continue
        f = {"strat": "swing", "symbol": sym, "minute": clk["minute"], "nifty": md["nifty"], "vix": md["vix"],
             "chg": r.get("change_pct"), "rvol": None, "news": news_score(sym)}
        p = model_p(d, f)
        f["p"] = round(p, 3) if p is not None else None
        if f["news"] <= -2:
            _sample(d, f, skip="negative news today")
            continue
        ok, why = _can_enter(d, clk["date"])
        if not ok:
            _sample(d, f, skip=why)
            continue
        try:
            px, _ = _price(sym)
            ind = L.indicators(L.history(sym)["bars"])
        except Exception:  # noqa: BLE001
            continue
        sd = ind["idx"].get(r.get("setup_day"))
        a = ind["atr"][sd if sd is not None else -1]
        if not px:
            continue
        stop = L.stop_for("swing", px, a)
        pos = _open(d, "swing", sym, px, stop, None, f, "%s (%s)" % (r.get("setup") or "Trading signal", r.get("setup_day") or ""), sec)
        _sample(d, f, pid=pos["id"] if pos else None, taken=bool(pos))
        if pos:
            held.append(pos)


# ----------------------------------------------------------------- new daily-chart strategies (20 Nov 2026 study)
def _uptrend(ind, i):
    c, s50, s200 = ind["c"][i], ind["sma50"][i], ind["sma200"][i]
    old = ind["sma50"][i - 10] if i >= 10 else None
    return bool(s50 and s200 and old and c > s50 > s200 and s50 > old)


def _stronger(ind, i, mkt, n=63):
    own = L.ret(ind, i, n)
    bench = mkt.ret(ind["d"][i], n)
    return own is not None and (bench is None or own > bench)


def daily_signal(k, ind, i, mkt):
    """Signal of strategy k on the close of bar i: a short reason, or None. Same rules as the 20 Nov backtest."""
    if i < 210:
        return None
    o, h, l, c, v = ind["o"], ind["h"], ind["l"], ind["c"], ind["v"]
    if k == "high52":
        hh, va, rg = ind["hh252"][i], ind["vavg50"][i], h[i] - l[i]
        if _uptrend(ind, i) and hh and va and c[i] > hh and v[i] >= 1.5 * va and rg > 0 and c[i] >= h[i] - 0.3 * rg and _stronger(ind, i, mkt):
            return "closed above the 52-week high %.2f on %.1fx volume" % (hh, v[i] / va)
    elif k == "dip":
        s50, s200 = ind["sma50"][i], ind["sma200"][i]
        r2 = ind.get("rsi2")
        if r2 is None:
            r2 = ind["rsi2"] = S.rsi_series(c, 2)
        if s50 and s200 and c[i] > s200 and s50 > s200 and r2[i] is not None and r2[i] < 10:
            return "sharp 2-day dip in an uptrend (RSI-2 %.0f)" % r2[i]
        if _uptrend(ind, i) and c[i] < c[i - 1] < c[i - 2] < c[i - 3]:
            return "3 down days in a row, still above the 50-day average"
    elif k == "candle":
        if not (_uptrend(ind, i) and _stronger(ind, i, mkt)):
            return None
        s20, s50 = ind["sma20"][i], ind["sma50"][i]
        low3 = min(l[i - 2:i + 1])
        if not (low3 <= s20 * 1.01 or low3 <= s50 * 1.01) or c[i] <= s20 * 0.99:
            return None
        if c[i] > o[i] and c[i - 1] < o[i - 1] and c[i] >= o[i - 1] and o[i] <= c[i - 1]:
            return "bullish engulfing candle at the %s-day average" % ("20" if low3 <= s20 * 1.01 else "50")
        rg = h[i] - l[i]
        if rg > 0 and (min(o[i], c[i]) - l[i]) >= 0.6 * rg and c[i] >= h[i] - 0.25 * rg and c[i] > c[i - 1]:
            return "hammer candle at the %s-day average" % ("20" if low3 <= s20 * 1.01 else "50")
    return None


def _scan_one(sym, mkt, today, forming):
    try:
        ind = L.indicators(L.history(sym)["bars"])
    except Exception:  # noqa: BLE001
        return []
    n = len(ind["c"])
    if forming:
        if ind["d"][-1] != today:
            return []
        i = n - 1
    else:
        i = n - 2 if ind["d"][-1] == today else n - 1
    if i < 210 or L.signal("swing", ind, i, mkt):   # Trading v2 signals belong to Short swing
        return []
    for k in NEW_DAILY:
        why = daily_signal(k, ind, i, mkt)
        if why:
            r3, b3 = L.ret(ind, i, 63), mkt.ret(ind["d"][i], 63)
            return [{"strat": k, "symbol": sym, "why": why, "day": ind["d"][i], "close": ind["c"][i], "atr": ind["atr"][i],
                     "rs": (r3 - b3) if r3 is not None and b3 is not None else 0, "forming": forming,
                     "sector": S.UNIVERSE.get(sym, {}).get("industry", "")}]
    return []


def scan_daily(clk):
    """Candidates of the new daily strategies. Completed-day signals once a day; from 15:10 also today's forming bar
    (every 5 min). Runs OUTSIDE the robot lock: it reads ~250 histories."""
    from concurrent.futures import ThreadPoolExecutor
    today, m = clk["date"], clk["minute"]
    c = _mem.setdefault("daily", {})
    if c.get("date") != today:
        c.clear()
        c["date"] = today
    jobs = []
    if "done" not in c:
        jobs.append(False)
    if m >= FORMING_M and time.time() - c.get("form_at", 0) > 290:
        jobs.append(True)
    if not jobs:
        return
    mkt = L.market()
    for forming in jobs:
        with ThreadPoolExecutor(8) as ex:
            rows = [r for rs in ex.map(lambda s: _scan_one(s, mkt, today, forming), list(S.NAMES)) for r in rs]
        rows.sort(key=lambda r: -r["rs"])
        if forming:
            c["forming"], c["form_at"] = rows, time.time()
        else:
            c["done"] = rows


def daily_entries(d, clk, md):
    on = [k for k in NEW_DAILY if d["strat_on"].get(k)]
    c = _mem.get("daily") or {}
    if not on or c.get("date") != clk["date"]:
        return
    day = _day(d, clk["date"])
    day.setdefault("daily_done", [])
    data = L.scan_long("swing")
    if not data.get("regime"):
        if "regime" not in day:
            day["regime"] = False
            _say(d, "Market filter is off (Nifty below its 50/200-day averages), so no new swing buys today (all daily strategies wait).")
        return
    held = [p for p in d["positions"] if p["kind"] == "delivery"]
    cands = (c.get("done") or []) + (c.get("forming") or [] if clk["minute"] >= FORMING_M else [])
    for r in cands:
        if len(held) >= MAX_SWING:
            break
        k, sym = r["strat"], r["symbol"]
        if k not in on or sym in day["daily_done"] or any(p["symbol"] == sym for p in d["positions"]) or _recent_exit(d, sym):
            continue
        try:
            px, _ = _price(sym)
        except Exception:  # noqa: BLE001
            continue
        if not px or not r.get("atr"):
            continue
        stop = L.stop_for("swing", px, r["atr"])
        if px > r["close"] * (1 + MAX_EXT):
            continue   # ran too far above the signal close; it may come back later in the day
        day["daily_done"].append(sym)
        f = {"strat": k, "symbol": sym, "minute": clk["minute"], "nifty": md["nifty"], "vix": md["vix"],
             "chg": (px / r["close"] - 1) * 100, "rvol": None, "news": news_score(sym)}
        pm = model_p(d, f)
        f["p"] = round(pm, 3) if pm is not None else None
        sec = r.get("sector") or ""
        skip = None
        if px <= stop:
            skip = "price already below the stop"
        elif f["news"] <= -2:
            skip = "negative news today"
        elif sec and sum(1 for p in held if p.get("sector") == sec) >= MAX_PER_SECTOR:
            skip = "already 2 swings in %s" % sec
        else:
            ok, why = _can_enter(d, clk["date"])
            skip = None if ok else why
        if skip:
            _sample(d, f, skip=skip)
            continue
        pos = _open(d, k, sym, px, stop, None, f, "%s (%s%s)" % (r["why"], r["day"], ", forming" if r["forming"] else ""), sec)
        _sample(d, f, pid=pos["id"] if pos else None, taken=bool(pos), skip=None if pos else "no money for even 1 share")
        if pos:
            held.append(pos)


# ----------------------------------------------------------------- diary: daily strategy notes + scorecard
def skip_notes(d, today):
    """One diary line per strategy: what it looked at today and why it did not buy."""
    for k in STRATS:
        ss = [x for x in d["samples"] if x.get("day") == today and x.get("strat") == k]
        if not ss:
            continue
        taken = sum(1 for x in ss if x.get("taken"))
        why = {}
        for x in ss:
            if not x.get("taken"):
                why[x.get("skip") or "not bought"] = why.get(x.get("skip") or "not bought", 0) + 1
        _say(d, "%s today: %d signal(s), bought %d%s" % (STRATS[k]["label"], len(ss), taken,
             (" · skipped: " + ", ".join("%s ×%d" % (w, n) for w, n in sorted(why.items(), key=lambda z: -z[1]))) if why else ""), "skip", k)


def scorecard(d):
    """Per-strategy results after charges + plain verdicts: best performer and what suits the owner's doubling goal."""
    rows = []
    for k, v in STRATS.items():
        tr = [t for t in d["trades"] if t["strat"] == k]
        n = len(tr)
        avg = sum(t["r"] for t in tr) / n if n else None
        net = sum(t["net"] for t in tr)
        days = [max(1, (datetime.strptime(t["closed"][:10], "%Y-%m-%d") - datetime.strptime(t["opened"][:10], "%Y-%m-%d")).days) for t in tr]
        if not n:
            verdict = "no trades yet" + ("" if d["strat_on"].get(k) else " (switched off)")
        elif n < 15:
            verdict = "too early to judge (%d of 15 trades)" % n
        elif avg >= max(0.2, v["expect"] * 0.6):
            verdict = "GOOD FOR YOU: earning as tested, helps the doubling goal"
        elif avg >= 0:
            verdict = "small profit, below its backtest (%+.2fR expected)" % v["expect"]
        else:
            verdict = "COSTING YOU MONEY: the robot has cut its size; consider switching it off"
        rows.append({"id": k, "label": v["label"], "on": d["strat_on"].get(k, False), "n": n, "won": sum(1 for t in tr if t["net"] > 0),
                     "net": round(net, 2), "avg_r": round(avg, 3) if avg is not None else None, "expect": v["expect"],
                     "avg_days": round(sum(days) / n, 1) if n else None, "verdict": verdict})
    judged = [r for r in rows if r["n"] >= 15]
    best = max(judged, key=lambda r: r["avg_r"]) if judged else None
    top_net = max((r for r in rows if r["n"]), key=lambda r: r["net"], default=None)
    if best:
        summary = "Best so far: %s, %+.2fR per trade over %d trades (net ₹%s)." % (best["label"], best["avg_r"], best["n"], _n(best["net"]))
    elif top_net:
        summary = "Most money so far: %s (net %s₹%s), but no strategy has 15 trades yet, so none is proven." % (
            top_net["label"], "+" if top_net["net"] >= 0 else "−", _n(abs(top_net["net"])))
    else:
        summary = "No closed trades yet."
    return {"rows": rows, "best": best["id"] if best else None, "summary": summary}


def score_note(d):
    sc = scorecard(d)
    parts = ["%s: %d trades, won %s, net %s₹%s, %s · %s" % (
        r["label"], r["n"], ("%d%%" % round(r["won"] / r["n"] * 100)) if r["n"] else "–", "+" if r["net"] >= 0 else "−", _n(abs(r["net"])),
        ("%+.2fR/trade" % r["avg_r"]) if r["avg_r"] is not None else "–", r["verdict"]) for r in sc["rows"] if r["n"] or r["on"]]
    _say(d, "📊 Strategy scorecard · " + sc["summary"] + " | " + " | ".join(parts), "score")


def swing_update(d, clk):
    """Trading v2 rules on every completed daily bar since the last one seen (catches up after a NAS restart)."""
    why = {"stop": "stop hit", "trail": "trailing stop", "time": "time limit", "target": "target"}
    for p in [x for x in d["positions"] if x["kind"] == "delivery"]:
        try:
            ind = L.indicators(L.history(p["symbol"])["bars"])
        except Exception:  # noqa: BLE001
            continue
        n = len(ind["c"])
        last_done = n - 2 if (clk["open"] and ind["d"][-1] == clk["date"]) else n - 1
        seen = p.get("seen") or p["opened"][:10]
        for j in range(n):
            if ind["d"][j] <= seen or j > last_done:
                continue
            p.setdefault("maxc", p["entry"])
            p.setdefault("bars", 0)
            old = p["stop"]
            ex = L.step("swing", ind, j, p)
            p["seen"] = ind["d"][j]
            p["last"] = ind["c"][j]
            if ex:
                _close(d, p, ex[0], why.get(ex[1], ex[1]) + " (%s)" % ind["d"][j])
                break
            if p["stop"] > old:
                _say(d, "%s: stop raised to ₹%.2f (trail)" % (p["symbol"], p["stop"]), "info", p["strat"])


def scalp_catch_up(d, clk):
    """Scalps never stay overnight: if the robot was not running at 15:00 (NAS off), square off at the 15:20 price, like Zerodha."""
    for p in [x for x in d["positions"] if x["kind"] == "intraday"]:
        day = p["opened"][:10]
        if day == clk["date"] and clk["minute"] < 930:
            continue
        px = None
        try:
            _, bars = S.chart(p["symbol"], "5d", "5m", 60)
            sb = S.sessions(bars).get(day) or []
            done = [b for b in sb if b["m"] <= 920]
            px = done[-1]["c"] if done else None
        except Exception:  # noqa: BLE001
            pass
        _close(d, p, px or p.get("last") or p["entry"], "auto square-off at 15:20 (robot was not running at 15:00)")


def label_skipped(d, clk):
    """End of day: what each skipped ORB would have done (the scanner's own simulation), so the model learns from skips too."""
    try:
        rows = {r["symbol"]: r for r in S.scan(refresh=True)["rows"]}
    except Exception:  # noqa: BLE001
        return
    for s in d["samples"]:
        if s["day"] == clk["date"] and s["strat"] == "orb" and not s.get("taken") and s.get("y") is None:
            o = (rows.get(s["symbol"]) or {}).get("orb") or {}
            if o.get("outcome") in ("target", "stop"):
                s["y"] = 1 if o["outcome"] == "target" else 0
            elif o.get("outcome") == "open":
                s["y"] = 0   # no target by the close: after charges a flat scalp is a small loss


# ----------------------------------------------------------------- reports
def day_summary(d, today):
    tr = [t for t in d["trades"] if t["closed"].startswith(today)]
    eq = equity(d)
    day = d["day"] if d["day"].get("date") == today else {"start_eq": eq}
    lines = ["🤖 AI Robot · paper · %s" % today,
             "Money ₹%s (start ₹%s, goal ₹%s) · today %s₹%s" % (_n(eq), _n(d["capital"]), _n(d["capital"] * TARGET_X),
                                                              "+" if eq >= day["start_eq"] else "−", _n(abs(eq - day["start_eq"])))]
    if tr:
        lines.append("Closed today: %d trades (%d won, %d lost), charges ₹%s" % (
            len(tr), sum(1 for t in tr if t["net"] > 0), sum(1 for t in tr if t["net"] <= 0), _n(sum(t["charges"]["total"] for t in tr))))
    for t in tr:
        lines.append("  %s %s %s: %s₹%s after ₹%s charges (%s)" % ("✅" if t["net"] > 0 else "❌", STRATS[t["strat"]]["label"].split(" (")[0],
                                                                t["symbol"], "+" if t["net"] >= 0 else "−", _n(abs(t["net"])), _n(t["charges"]["total"]), t["reason"]))
    op = d["positions"]
    if op:
        lines.append("Open: " + ", ".join("%s %s" % (p["symbol"], "swing" if p["kind"] == "delivery" else "scalp") for p in op))
    if not tr and not op:
        lines.append("No trades today: nothing passed the robot's checks.")
    return "\n".join(lines), tr


def alert_text(d, today, test=False):
    """Robot trading alert: today's buys, closed trades, open trades, money made or lost, wealth now."""
    eq = equity(d)
    day = d["day"] if d["day"].get("date") == today else {"start_eq": eq}
    opened = [p for p in d["positions"] if p["opened"].startswith(today)] + [t for t in d["trades"] if t["opened"].startswith(today)]
    closed = [t for t in d["trades"] if t["closed"].startswith(today)]
    booked = sum(t["net"] for t in closed)
    unreal = sum(((p.get("last") or p["entry"]) - p["entry"]) * p["qty"] for p in d["positions"])
    dchg, tot = eq - day["start_eq"], eq - d["capital"]
    sg = lambda v: ("+" if v >= 0 else "−") + "₹" + _n(abs(v))
    typ = lambda x: "scalp" if x["kind"] == "intraday" else "swing"
    out = ["🤖 ROBOT TRADING ALERT%s · %s" % (" (test)" if test else "", S.now_ist().strftime("%a %d %b %H:%M")),
           "Paper money only, no real orders.", "",
           "💰 Wealth now: ₹%s (start ₹%s · goal ₹%s)" % (_n(eq), _n(d["capital"]), _n(d["capital"] * TARGET_X)),
           "%s today: %s (%+.2f%%) · since start: %s (%+.2f%%)" % ("📈 Earned" if dchg >= 0 else "📉 Lost", sg(dchg),
                                                                  dchg / max(day["start_eq"], 1) * 100, sg(tot), tot / d["capital"] * 100),
           "Booked today %s · open trades %s" % (sg(booked), sg(unreal)), "",
           "🛒 Bought today: %d" % len(opened)]
    out += ["  %s %d @ ₹%.2f · capital ₹%s · %s" % (x["symbol"], x["qty"], x["entry"], _n(x["entry"] * x["qty"]), typ(x)) for x in opened]
    out += ["", "✅ Closed today: %d (won %d, lost %d) · charges ₹%s" % (
        len(closed), sum(1 for t in closed if t["net"] > 0), sum(1 for t in closed if t["net"] <= 0), _n(sum(t["charges"]["total"] for t in closed)))]
    out += ["  %s %s %d · capital ₹%s · ₹%.2f → ₹%.2f · %s · %s" % ("✅" if t["net"] > 0 else "❌", t["symbol"], t["qty"], _n(t["entry"] * t["qty"]), t["entry"], t["exit"], sg(t["net"]), t["reason"])
            for t in closed]
    out += ["", "📂 Open now: %d · capital in use ₹%s · free cash ₹%s" % (
        len(d["positions"]), _n(sum(p["entry"] * p["qty"] for p in d["positions"])), _n(d["cash"]))]
    for p in d["positions"]:
        last = p.get("last") or p["entry"]
        pl = (last - p["entry"]) * p["qty"]
        out.append("  %s %d · capital ₹%s · ₹%.2f → ₹%.2f · %s (%+.1f%%) · stop ₹%.2f · %s" % (
            p["symbol"], p["qty"], _n(p["entry"] * p["qty"]), p["entry"], last, sg(pl), (last / p["entry"] - 1) * 100, p["stop"], typ(p)))
    return "\n".join(out)


def _alert_m(d):
    try:
        h, mm = (d.get("alert_at") or "15:32").split(":")
        return int(h) * 60 + int(mm)
    except ValueError:
        return 932


def _n(v):
    """Indian grouping: 150915 -> 1,50,915."""
    n = int(round(v))
    t = str(abs(n))
    if len(t) > 3:
        t = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", t[:-3]) + "," + t[-3:]
    return ("-" if n < 0 else "") + t


def _numbers(t):
    return set(re.findall(r"\d[\d,]*\.?\d*", t))


def ai_review(d, facts):
    if not AI or not AI.configured():
        return None
    nums = _numbers(facts)
    try:
        return AI.ask("You review one day of a PAPER trading robot for its owner. Write 3-5 short bullet lines in simple English: "
                      "what worked, what did not, one pattern worth watching. Start lines with • (no numbered lists). Use ONLY numbers that appear in the facts; "
                      "never invent a number. No advice to trade real money.", facts, max_tokens=350,
                      check=lambda o: _numbers(o) <= nums)
    except Exception:  # noqa: BLE001
        return None


def _send(text):
    try:
        T.notify("robot", text)
    except Exception:  # noqa: BLE001
        pass


# ----------------------------------------------------------------- the loop
def _trading_day(clk):
    try:
        import reports
        return S.now_ist().weekday() < 5 and clk["date"] not in reports.holidays()
    except Exception:  # noqa: BLE001
        return S.now_ist().weekday() < 5


def tick():
    clk = S.market_clock()
    if not _trading_day(clk):
        return
    m = clk["minute"]
    if clk["open"] and DAY_FROM_M <= m <= DAY_TO_M and time.time() - _mem["last_scan"] > 170:
        son = load()["strat_on"]
        try:
            if (575 <= m <= 630 and son.get("orb")) or (870 <= m <= 885 and son.get("pm")):
                S.scan()
            L.scan_long("swing")
            scan_daily(clk)                           # new daily strategies, warmed outside the lock
        except Exception:  # noqa: BLE001
            pass
    with _lock:
        d = load()
        if not d["on"]:
            return
        day = _day(d, clk["date"])
        changed = False
        if any(p["kind"] == "intraday" and (p["opened"][:10] < clk["date"] or m >= 930) for p in d["positions"]):
            scalp_catch_up(d, clk)
            changed = True
        if not day.get("swing_am") and m >= 556:
            day["swing_am"] = True
            swing_update(d, clk)                     # days missed while the NAS was off
            changed = True
        if clk["open"]:
            if d["positions"]:
                manage(d, clk)
                changed = True
            md = None
            if DAY_FROM_M <= m <= DAY_TO_M and time.time() - _mem["last_scan"] > 170:
                _mem["last_scan"] = time.time()   # owner: every strategy checked all session (about every 3 min)
                md = mood()
                if 575 <= m <= 630:          # 09:35-10:30 (ORB is defined on the opening range; OFF by default)
                    orb_entries(d, clk, md)
                if 870 <= m <= 885 and not day["pm_done"]:
                    pm_entries(d, clk, md)
                swing_entries(d, clk, md)
                daily_entries(d, clk, md)
                changed = True
                if 575 <= m <= 600 and not d["sent"].get(clk["date"] + "a") and day["scalps"]:
                    d["sent"][clk["date"] + "a"] = 1
                    _send("🤖 Robot trading alert · 09:35 · bought (paper):\n" + "\n".join(
                        "  %s %d @ ₹%.2f · stop ₹%.2f · %s" % (p["symbol"], p["qty"], p["entry"], p["stop"], STRATS[p["strat"]]["label"])
                        for p in d["positions"] if p["opened"].startswith(clk["date"])))
            if m >= SCALP_EXIT_M and not day["closed15"]:
                day["closed15"] = True
                manage(d, clk)
                closed = [t for t in d["trades"] if t["closed"].startswith(clk["date"]) and t["kind"] == "intraday"]
                if closed:
                    _send("🤖 Robot trading alert · 15:00 · scalps closed: " + ", ".join(
                        "%s %s₹%s" % (t["symbol"], "+" if t["net"] >= 0 else "−", _n(abs(t["net"]))) for t in closed))
                changed = True
        if m >= 935 and not day["after"]:            # 15:35
            day["after"] = True
            swing_update(d, clk)
            label_skipped(d, clk)
            eq = equity(d)
            d["peak"] = max(d["peak"], eq)
            if eq < d["peak"] * (1 - PAUSE_DD) and not d.get("pause_until"):
                from datetime import timedelta
                d["pause_until"] = (S.now_ist() + timedelta(days=7)).strftime("%Y-%m-%d")
                _say(d, "Down 15%% from the peak: new entries paused until %s." % d["pause_until"], "loss")
            elif d.get("pause_until") and clk["date"] >= d["pause_until"]:
                d["pause_until"] = None
            d["equity"] = [e for e in d["equity"] if e["date"] != clk["date"]] + [{"date": clk["date"], "equity": round(eq, 2)}]
            train(d)
            skip_notes(d, clk["date"])                # diary: per-strategy notes + scorecard, kept DIARY_YEARS
            score_note(d)
            diary_prune()
            changed = True
        if m >= _alert_m(d) and not day["report"]:   # robot trading alert (default 15:32, after the close)
            day["report"] = True
            text = alert_text(d, clk["date"])
            tr = [t for t in d["trades"] if t["closed"].startswith(clk["date"])]
            review = ai_review(d, text) if tr else None
            _send(text + ("\n\n🧠 AI review:\n" + review if review else ""))
            if review:
                _say(d, "AI review: " + review.replace("\n", " "), "ai")
            changed = True
        if changed:
            save(d)


def _loop():
    time.sleep(20)
    while True:
        try:
            tick()
        except Exception as e:  # noqa: BLE001
            try:
                with _lock:
                    d = load()
                    _say(d, "Robot error (it keeps running): %s" % str(e)[:150], "error")
                    save(d)
            except Exception:  # noqa: BLE001
                pass
        time.sleep(30)


def start():
    try:
        migrate()
    except Exception:  # noqa: BLE001
        pass
    threading.Thread(target=_loop, name="ai-robot", daemon=True).start()


# ----------------------------------------------------------------- page API
def status():
    d = load()
    eq = equity(d)
    days = len(d["equity"])
    first = d["equity"][0]["equity"] if d["equity"] else d["capital"]
    gain = eq / d["capital"] - 1
    tr = d["trades"]
    ch_tot = {}
    for t in tr:
        for k, v in t["charges"].items():
            ch_tot[k] = round(ch_tot.get(k, 0) + v, 2)
    net_intra = sum(t["net"] for t in tr if t["kind"] == "intraday")
    net_deliv = sum(t["net"] for t in tr if t["kind"] == "delivery")
    tax = {"intraday": round(max(net_intra, 0) * 0.30, 2), "swing": round(max(net_deliv, 0) * 0.20, 2)}
    pace = None
    if days >= 5 and eq > 0 and first > 0:
        per_day = (eq / first) ** (1 / days) - 1
        pace = {"per_day_pct": round(per_day * 100, 3),
                "days_to_double": round(math.log(TARGET_X * d["capital"] / eq) / math.log(1 + per_day)) if per_day > 0 and eq < TARGET_X * d["capital"] else None}
    return {"on": d["on"], "capital": d["capital"], "cash": round(d["cash"], 2), "equity": round(eq, 2), "peak": round(d["peak"], 2),
            "goal": d["capital"] * TARGET_X, "gain_pct": round(gain * 100, 2), "started": d["started"], "pause_until": d["pause_until"],
            "positions": d["positions"], "trades": tr[-200:][::-1], "curve": d["equity"], "diary": diary({"limit": 150}),
            "scorecard": scorecard(d), "limits": {"max_swing": MAX_SWING, "swing_cap": SWING_CAP * 100, "base_risk": BASE_RISK, "diary_years": DIARY_YEARS},
            "strategies": [dict(id=k, label=v["label"], why=v["why"], kind=v["kind"], on=d["strat_on"].get(k, True),
                                factor=strat_factor(d, k)[0], factor_why=strat_factor(d, k)[1], **_strat_stats(d, k)) for k, v in STRATS.items()],
            "charges": ch_tot, "tax_est": tax, "pace": pace, "risk_cap": d.get("risk_cap"), "alert_at": d.get("alert_at") or "15:32",
            "model": {k: v for k, v in (d.get("model") or {"ready": False, "n": 0, "why": "not trained yet"}).items() if k != "w"},
            "samples": len(d["samples"]), "clock": S.market_clock(), "ai": bool(AI and AI.configured())}


def act(body, check_pw):
    a = body.get("action")
    if a == "diary":                     # read only: filtered diary
        return {"diary": diary(body)}
    if a == "diary_delete":              # owner deletes by hand (confirm on the page, no password: owner 20 Nov 2026)
        n = diary_delete(body)
        out = {"diary": diary(body if not body.get("ids") else {k: body.get(k) for k in ("strat", "kind", "from", "to", "q", "limit")})}
        out["message"] = "Deleted %d diary entr%s." % (n, "y" if n == 1 else "ies")
        return out
    with _lock:
        d = load()
        if a == "on":
            d["on"] = True
            d["started"] = d["started"] or S.now_ist().strftime("%Y-%m-%d %H:%M")
            _say(d, "Robot switched ON by you.")
            msg = "Robot is ON. It trades paper money by itself from the next market minute."
        elif a == "off":
            d["on"] = False
            _say(d, "Robot switched OFF by you (open positions kept, not managed until ON).")
            msg = "Robot is OFF. Open positions stay as they are until you switch it on or close them."
        elif a == "strat":
            k = body.get("id")
            if k not in STRATS:
                raise S.ApiError(400, "Unknown strategy.")
            d["strat_on"][k] = bool(body.get("on"))
            _say(d, "%s switched %s by you." % (STRATS[k]["label"], "on" if d["strat_on"][k] else "off"), "info", k)
            msg = "%s %s." % (STRATS[k]["label"], "on" if d["strat_on"][k] else "off")
        elif a == "risk_cap":
            v = float(body.get("value") or 2)
            if not 0.25 <= v <= 3:
                raise S.ApiError(400, "Pick a cap between 0.25% and 3%.")
            d["risk_cap"] = v
            msg = "The robot will never risk more than %.2f%% of its money on one trade." % v
        elif a == "close_all":
            check_pw(body.get("password"))
            n = 0
            for p in list(d["positions"]):
                try:
                    px, _ = _price(p["symbol"])
                except Exception:  # noqa: BLE001
                    px = None
                _close(d, p, px or p.get("last") or p["entry"], "closed by you")
                n += 1
            msg = "Closed %d position(s) at the latest price." % n
        elif a == "reset":
            check_pw(body.get("password"))
            cap = float(body.get("capital") or START_CAPITAL)
            if not 10000 <= cap <= 10000000:
                raise S.ApiError(400, "Capital between ₹10,000 and ₹1 crore.")
            d = _fresh(cap)
            _say(d, "Robot reset by you: fresh paper account ₹%s." % _n(cap))
            msg = "Reset: fresh paper account with ₹%s. The robot keeps running." % _n(cap)
        elif a == "alert_at":
            v = str(body.get("value") or "").strip()
            if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
                raise S.ApiError(400, "Enter the time as HH:MM, e.g. 15:32.")
            d["alert_at"] = v
            msg = "Robot trading alert will come at %s on trading days." % v
        elif a == "alert_test":
            _send(alert_text(d, S.now_ist().strftime("%Y-%m-%d"), test=True))
            msg = "Test robot trading alert sent to Telegram."
        elif a == "train":
            m = train(d)
            msg = "Model: " + m["why"]
        else:
            raise S.ApiError(400, "Unknown action.")
        save(d)
    out = status()
    out["message"] = msg
    return out
