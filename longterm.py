"""Trading (swing, 2-3 months) and Investing (6-12 months) engines.

Daily bars only. Wired into server.py, which sets `S` to its own module so this file
can reuse fetch, earnings, news, deals, state and the price-source fallbacks.
"""
import bisect
import json
import math
import os
import threading
import time
import urllib.parse
import urllib.request
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

S = None  # the server module, set by server.py

LABEL = {"intraday": "Scalping", "swing": "Trading", "invest": "Investing"}
DEFAULTS = {
    "swing": {"capital": 200000, "risk_per_trade": 2500, "max_per_stock": 25000, "max_positions": 10,
              "max_open_risk": 25000, "max_per_sector": 2, "dd_pause_pct": 10},
    "invest": {"capital": 200000, "risk_per_trade": 2500, "max_per_stock": 25000, "max_positions": 10,
               "max_open_risk": 25000, "max_per_sector": 2, "dd_pause_pct": 15},
}
RULES = {
    # Trading rules v2 (Nov 2026): no fixed target, only buy within 10% of the 52-week high,
    # stop to break-even only after +2R. Chosen because it improved results in both 2017-22
    # and 2022-26 and nearby settings gave similar results (see CLAUDE.md).
    "swing": {"hold": 60, "stop_atr": 2.0, "min_risk": 0.04, "max_risk": 0.12, "target_r": None,
              "trail_atr": 3.0, "max_ext": 0.05, "rs_days": 63, "recent": 5, "be_at": 2.0,
              "setups": ("breakout", "pullback"), "vol_x": 1.5, "base_depth": 0.25, "base_len": 40,
              "rs_margin": 0.0, "near_high": 0.10},
    "invest": {"hold": 250, "stop_atr": 3.0, "min_risk": 0.08, "max_risk": 0.20, "target_r": None,
               "trail_atr": 5.0, "max_ext": 0.08, "rs_days": 126, "recent": 10, "be_at": 1.0},
}
PAUSE_DAYS = {"swing": 20, "invest": 40}   # trading days new buys stop after a drawdown breach
COST_SIDE = 0.0012  # STT 0.1% + stamp/exchange/GST, per side, delivery
DP_FEE = 16.0        # depository charge per sell
HIST_RANGE = "10y"


def settings_for(mode, st=None):
    st = st or S.load_state()
    out = dict(DEFAULTS[mode])
    out.update((st["settings"].get("modes") or {}).get(mode) or {})
    return out


def costs(value_buy, value_sell):
    return COST_SIDE * (value_buy + value_sell) + DP_FEE


# ----------------------------------------------------------------- daily history
_hist, _hist_lock = {}, threading.Lock()
_sym_locks = {}


def _hist_path(sym):
    safe = sym.replace("&", "_and_").replace("^", "idx_")
    return os.path.join(S.DATA, "hist", safe + ".json")


def _yahoo_daily(ysym, rng, ttl=None):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/%s?range=%s&interval=1d&includePrePost=false"
           % (urllib.parse.quote(ysym, safe=""), rng))
    if ttl:  # short ranges go through the shared cache
        raw = S.fetch(url, ttl)
    else:    # 10-year pulls bypass it so the memory cache does not hold big blobs
        raw, last = None, None
        for attempt in range(2):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=S.UA), timeout=30) as r:
                    raw = r.read()
                break
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(0.8)
        if raw is None:
            raise last
    res = json.loads(raw)["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    out = {}
    for i, t in enumerate(res.get("timestamp") or []):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if None in (o, h, l, c) or c <= 0:
            continue
        d = datetime.fromtimestamp(t, S.IST).date().isoformat()
        out[d] = (d, o, h, l, c, q["volume"][i] or 0)
    return [out[k] for k in sorted(out)]


def history(sym, index=False):
    """About 10 years of daily bars [(date, o, h, l, c, v)], plus the source used.

    The long history is downloaded once a day and kept in data/hist; the last month is
    refreshed every few minutes so today's bar stays current.
    """
    today = S.now_ist().date().isoformat()
    with _hist_lock:
        lock = _sym_locks.setdefault(sym, threading.Lock())
    with lock:
        hit = _hist.get(sym)
        if hit and hit["day"] == today and time.time() - hit["at"] < 300:
            return hit
        ys = sym if index else S.ysym(sym)
        base, src = None, "yahoo"
        path = _hist_path(sym)
        if hit and hit["day"] == today:
            base = hit["bars"]
        else:
            try:
                with open(path, encoding="utf-8") as f:
                    disk = json.load(f)
                if disk.get("day") == today:
                    base = [tuple(b) for b in disk["bars"]]
            except (OSError, ValueError):
                disk = None
            if base is None:
                try:
                    base = _yahoo_daily(ys, HIST_RANGE)
                    if base:
                        os.makedirs(os.path.dirname(path), exist_ok=True)
                        with open(path, "w", encoding="utf-8") as f:
                            json.dump({"day": today, "bars": base}, f)
                except Exception:  # noqa: BLE001
                    base = [tuple(b) for b in disk["bars"]] if disk else None
        if base:
            try:
                recent = _yahoo_daily(ys, "1mo", ttl=300)
                merged = {b[0]: b for b in base}
                merged.update({b[0]: b for b in recent})
                base = [merged[k] for k in sorted(merged)]
            except Exception:  # noqa: BLE001
                pass
        if not base and not index:
            meta, bars = S.chart(sym, "1y", "1d", 300)   # NSE / BSE end-of-day fallback
            src = meta.get("source", "yahoo")
            base = [(datetime.fromtimestamp(b["t"], S.IST).date().isoformat(), b["o"], b["h"], b["l"], b["c"], b["v"])
                    for b in bars]
        if not base:
            raise S.ApiError(404, "No daily price history for %s." % sym)
        # A one-day move this large is almost always a demerger, split or bonus the data
        # source did not adjust for. Start the history after it so it cannot fake a stop.
        cut = 0
        for k in range(1, len(base)):
            g = base[k][1] / base[k - 1][4] - 1 if base[k - 1][4] else 0
            if g < -0.35 or g > 0.6:
                cut = k
        if cut:
            base = base[cut:]
        ent = {"day": today, "at": time.time(), "bars": base, "source": src, "cut": base[0][0] if cut else None}
        _hist[sym] = ent
        return ent


# ----------------------------------------------------------------- indicators
def _sma(a, n):
    out, s = [None] * len(a), 0.0
    for i, v in enumerate(a):
        s += v
        if i >= n:
            s -= a[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def _roll_max_prior(a, n):
    """Highest value of the n bars *before* each bar."""
    out, dq = [None] * len(a), deque()
    for i in range(len(a)):
        if i >= n:
            out[i] = a[dq[0]]
        while dq and a[dq[-1]] <= a[i]:
            dq.pop()
        dq.append(i)
        while dq[0] <= i - n:
            dq.popleft()
    return out


def _roll_min_prior(a, n):
    return [None if v is None else -v for v in _roll_max_prior([-x for x in a], n)]


def indicators(bars):
    d = [b[0] for b in bars]
    o = [b[1] for b in bars]
    h = [b[2] for b in bars]
    l = [b[3] for b in bars]
    c = [b[4] for b in bars]
    v = [float(b[5] or 0) for b in bars]
    tr = [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]
    return {"d": d, "o": o, "h": h, "l": l, "c": c, "v": v, "idx": {x: i for i, x in enumerate(d)},
            "sma20": _sma(c, 20), "sma50": _sma(c, 50), "sma200": _sma(c, 200), "vavg50": _sma(v, 50),
            "atr": _sma(tr, 14), "hh40": _roll_max_prior(h, 40), "ll40": _roll_min_prior(l, 40),
            "hh252": _roll_max_prior(h, 252), "rsi": S.rsi_series(c)}


def ret(ind, i, n):
    return ind["c"][i] / ind["c"][i - n] - 1 if i >= n and ind["c"][i - n] else None


class Market:
    """Nifty 50 index: trend filter and the benchmark for relative strength."""

    def __init__(self):
        self.ind = indicators(history("^NSEI", index=True)["bars"])

    def at(self, day):
        """Index position on or before a date."""
        i = self.ind["idx"].get(day)
        if i is None:
            ds = self.ind["d"]
            lo, hi = 0, len(ds) - 1
            while lo <= hi:
                mid = (lo + hi) // 2
                if ds[mid] <= day:
                    lo = mid + 1
                else:
                    hi = mid - 1
            i = hi if hi >= 0 else None
        return i

    def regime(self, day, mode):
        i = self.at(day)
        if i is None:
            return False
        n = self.ind
        c, s50, s200 = n["c"][i], n["sma50"][i], n["sma200"][i]
        if s200 is None:
            return True
        return c > s200 and (mode == "invest" or (s50 is not None and c > s50))

    def ret(self, day, n):
        i = self.at(day)
        return ret(self.ind, i, n) if i is not None else None


# ----------------------------------------------------------------- setups
def signal(mode, ind, i, mkt):
    """Setup on the close of bar i, or None. Returns (id, label, detail)."""
    if i < (252 if mode == "invest" else 205):
        return None
    c, h, l = ind["c"], ind["h"], ind["l"]
    s20, s50, s200, va = ind["sma20"][i], ind["sma50"][i], ind["sma200"][i], ind["vavg50"][i]
    if None in (s20, s50, s200) or not va:
        return None
    vol_x = ind["v"][i] / va if va else 0
    bench = mkt.ret(ind["d"][i], RULES[mode]["rs_days"]) if mkt else None
    own = ret(ind, i, RULES[mode]["rs_days"])
    if mode == "swing":
        p = RULES["swing"]
        rs_ok = own is not None and (bench is None or own > bench + p["rs_margin"])
        trend = c[i] > s50 > s200 and ind["sma50"][i - 10] is not None and s50 > ind["sma50"][i - 10]
        if not (trend and rs_ok):
            return None
        if p["near_high"] and ind["hh252"][i] and c[i] < ind["hh252"][i] * (1 - p["near_high"]):
            return None
        hh, ll = _base(ind, i, p["base_len"])
        if "breakout" in p["setups"] and hh and c[i] > hh and (hh - ll) / hh <= p["base_depth"] and vol_x >= p["vol_x"]:
            return ("breakout", "Base breakout",
                    "Closed above the %d-week high %.2f on %.1fx volume; base %.0f%% deep" % (p["base_len"] // 5, hh, vol_x, (hh - ll) / hh * 100))
        touched = min(l[i - 3:i + 1]) <= s20 * 1.015 or min(l[i - 3:i + 1]) <= s50 * 1.015
        r = ind["rsi"][i]
        if "pullback" in p["setups"] and touched and c[i] > h[i - 1] and c[i] > s50 and r is not None and 40 <= r <= 65:
            return ("pullback", "Pullback buy", "Dipped to the 20/50-day average and closed above yesterday's high")
        return None
    # invest
    rs_ok = own is not None and (bench is None or own > bench)
    s200_old = ind["sma200"][i - 20]
    trend = c[i] > s200 and s200_old is not None and s200 > s200_old and s50 > s200
    if not (trend and rs_ok):
        return None
    hh = ind["hh252"][i]
    if hh and c[i] > hh and vol_x >= 1.3:
        return ("high52", "52-week high breakout", "Closed above the 52-week high %.2f on %.1fx volume" % (hh, vol_x))
    if hh and min(l[i - 9:i + 1]) <= s50 * 1.02 and c[i] > s50 and c[i] > h[i - 1] and c[i] >= hh * 0.75:
        return ("pullback50", "Pullback to 50-day", "Long uptrend; bounced off the 50-day average")
    return None


def _base(ind, i, n):
    """Highest high and lowest low of the n bars before bar i."""
    if n == 40:
        return ind["hh40"][i], ind["ll40"][i]
    if i < n:
        return None, None
    return max(ind["h"][i - n:i]), min(ind["l"][i - n:i])


def stop_for(mode, entry, atr_v):
    r = RULES[mode]
    dist = r["stop_atr"] * (atr_v or entry * 0.03)
    dist = min(max(dist, entry * r["min_risk"]), entry * r["max_risk"])
    return entry - dist


def target_for(mode, entry, stop):
    tr = RULES[mode]["target_r"]
    return entry + tr * (entry - stop) if tr else None


def step(mode, ind, j, pos, forming=False):
    """Work one daily bar for an open position. Returns (exit_price, reason) or None.

    pos keys: entry, stop, R, target, maxc, bars (bars held so far).
    """
    r = RULES[mode]
    o, h, l, c = ind["o"][j], ind["h"][j], ind["l"][j], ind["c"][j]
    if o <= pos["stop"]:
        return o, "stop"
    if l <= pos["stop"]:
        return pos["stop"], ("trail" if pos["stop"] > pos["stop0"] else "stop")
    if pos.get("target") and h >= pos["target"]:
        return max(o, pos["target"]), "target"
    if forming:
        return None
    pos["bars"] += 1
    if mode == "invest" and ind["sma200"][j] and c < ind["sma200"][j] * 0.97:
        return c, "trend broken"
    if pos["bars"] >= r["hold"]:
        return c, "time"
    pos["maxc"] = max(pos["maxc"], c)
    if pos["maxc"] >= pos["entry"] + r["be_at"] * pos["R"]:
        pos["stop"] = max(pos["stop"], pos["entry"])
        a = ind["atr"][j]
        if a:
            pos["stop"] = max(pos["stop"], pos["maxc"] - r["trail_atr"] * a)
    return None


# ----------------------------------------------------------------- backtests
def stock_backtest(mode, ind, mkt, upto=None):
    """Rules on one stock, one trade at a time, no capital limits. Results in R after costs."""
    n = len(ind["c"]) if upto is None else upto
    trades, i = [], 0
    while i < n - 1:
        sig = signal(mode, ind, i, mkt)
        if not sig or not mkt.regime(ind["d"][i], mode):
            i += 1
            continue
        j = i + 1
        entry = ind["o"][j]
        if entry > ind["c"][i] * (1 + RULES[mode]["max_ext"]):
            i += 1
            continue
        stop = stop_for(mode, entry, ind["atr"][i])
        R = entry - stop
        pos = {"entry": entry, "stop": stop, "stop0": stop, "R": R, "target": target_for(mode, entry, stop),
               "maxc": entry, "bars": 0}
        out, k = None, j
        while k < n:
            out = step(mode, ind, k, pos)
            if out:
                break
            k += 1
        if not out:
            break  # still open at the end of the data
        px, why = out
        cost_r = (COST_SIDE * (entry + px)) / R
        trades.append({"in": ind["d"][j], "out": ind["d"][k], "entry": entry, "exit": px, "why": why,
                       "r": (px - entry) / R - cost_r, "pct": (px / entry - 1) * 100 - COST_SIDE * 200,
                       "days": k - j + 1, "setup": sig[1]})
        i = k + 1
    wins = [t for t in trades if t["r"] > 0]
    nt = len(trades)
    return {"trades": nt, "wins": len(wins), "win_rate": len(wins) / nt if nt else None,
            "avg_r": sum(t["r"] for t in trades) / nt if nt else None,
            "avg_win_pct": sum(t["pct"] for t in wins) / len(wins) if wins else None,
            "avg_loss_pct": (sum(t["pct"] for t in trades if t["r"] <= 0) / (nt - len(wins))) if nt > len(wins) else None,
            "avg_days": sum(t["days"] for t in trades) / nt if nt else None,
            "years": round(len(ind["c"]) / 248, 1), "recent": trades[-8:][::-1], "_all": trades}


_bt_cache, _bt_lock = {}, threading.Lock()


def load_universe():
    syms = list(S.NAMES)
    with ThreadPoolExecutor(12) as ex:
        res = list(ex.map(lambda s: _safe_hist(s), syms))
    return {s: r for s, r in zip(syms, res) if r}


def _safe_hist(sym):
    try:
        h = history(sym)
        return h if len(h["bars"]) > 260 and h["source"] == "yahoo" else None
    except Exception:  # noqa: BLE001
        return None


def portfolio_backtest(mode, refresh=False):
    """The full rule set on all 250 stocks with the owner's capital and limits."""
    with _bt_lock:
        hit = _bt_cache.get(mode)
        if hit and not refresh and time.time() - hit["at"] < 6 * 3600:
            return hit["data"]
        t0 = time.time()
        cfg = settings_for(mode)
        rules = RULES[mode]
        mkt = Market()
        uni = load_universe()
        inds = {s: indicators(h["bars"]) for s, h in uni.items()}
        clk = S.market_clock()
        days = [d for d in mkt.ind["d"] if not (clk["open"] and d == clk["date"])]   # completed days only
        warm = 260 if mode == "swing" else 300
        days = days[warm:]
        sigs = {}   # date -> [(rs, sym, i, setup)]
        for s, ind in inds.items():
            for i in range(len(ind["c"]) - 1):
                sg = signal(mode, ind, i, mkt)
                if sg:
                    sigs.setdefault(ind["d"][i], []).append((ret(ind, i, rules["rs_days"]) or 0, s, i, sg[1]))
        cash = float(cfg["capital"])
        pos, trades, curve, pending = {}, [], [], []
        peak, max_dd, invested_sum = cash, 0.0, 0.0
        top, pause_left, pauses = cash, 0, 0
        for day in days:
            # 1. fills at today's open for yesterday's signals
            for rs, s, i, setup in pending:
                ind = inds[s]
                j = ind["idx"].get(day)
                if j is None or j != i + 1 or s in pos or len(pos) >= cfg["max_positions"]:
                    continue
                sector = S.UNIVERSE.get(s, {}).get("industry", "")
                if sector and sum(1 for p in pos.values() if p["sector"] == sector) >= cfg["max_per_sector"]:
                    continue
                entry = ind["o"][j]
                if entry > ind["c"][i] * (1 + rules["max_ext"]):
                    continue
                stop = stop_for(mode, entry, ind["atr"][i])
                R = entry - stop
                open_risk = sum(p["qty"] * max(p["entry"] - p["stop"], 0) for p in pos.values())
                qty = min(math.floor(cfg["risk_per_trade"] / R), math.floor(cfg["max_per_stock"] / entry),
                          math.floor(cash / (entry * (1 + COST_SIDE))))
                if qty < 1 or open_risk + qty * R > cfg["max_open_risk"]:
                    continue
                cash -= qty * entry * (1 + COST_SIDE)
                pos[s] = {"qty": qty, "entry": entry, "stop": stop, "stop0": stop, "R": R, "maxc": entry, "bars": 0,
                          "target": target_for(mode, entry, stop), "in": day, "sector": sector, "setup": setup}
            pending = []
            # 2. work open positions on today's bar
            for s in list(pos):
                ind, p = inds[s], pos[s]
                j = ind["idx"].get(day)
                if j is None:
                    continue
                out = step(mode, ind, j, p)
                if out:
                    px, why = out
                    gross = (px - p["entry"]) * p["qty"]
                    fee = costs(p["entry"] * p["qty"], px * p["qty"])
                    cash += px * p["qty"] * (1 - COST_SIDE) - DP_FEE
                    held = (date.fromisoformat(day) - date.fromisoformat(p["in"])).days
                    trades.append({"symbol": s, "in": p["in"], "out": day, "entry": p["entry"], "exit": px, "qty": p["qty"],
                                   "pnl": gross - fee, "r": (gross - fee) / (p["R"] * p["qty"]), "why": why,
                                   "held": held, "setup": p["setup"]})
                    del pos[s]
            # 3. mark to market
            value = 0.0
            for s, p in pos.items():
                ind = inds[s]
                j = ind["idx"].get(day)
                last = ind["c"][j] if j is not None else p.get("last", p["entry"])
                p["last"] = last
                value += last * p["qty"]
            equity = cash + value
            invested_sum += value / equity if equity else 0
            peak = max(peak, equity)
            top = max(top, equity)
            max_dd = max(max_dd, (top - equity) / top)
            curve.append((day, equity))
            # 4. tonight's signals become tomorrow's orders, if the market filter allows.
            # A drawdown beyond the limit pauses new buys for a cooling-off period, then
            # the peak resets so the account can trade again.
            if pause_left == 0 and equity < peak * (1 - cfg["dd_pause_pct"] / 100):
                pause_left = PAUSE_DAYS[mode]
                pauses += 1
            if pause_left:
                pause_left -= 1
                if pause_left == 0:
                    peak = equity
            if mkt.regime(day, mode) and not pause_left:
                pending = sorted(sigs.get(day, []), reverse=True)
        data = _summarise(mode, cfg, trades, curve, max_dd, invested_sum, pos, len(uni), time.time() - t0)
        data["pauses"] = pauses
        try:
            data["bench"] = benchmark(curve, float(cfg["capital"]), mkt)
            y = max(len(curve) / 248, 0.01)
            data["cagr_after_tax"] = (((data["start"] + data["after_tax"]) / data["start"]) ** (1 / y) - 1) * 100
        except Exception as e:  # noqa: BLE001  (the comparison must never break the backtest)
            data["bench"] = {"error": str(e)[:150]}
        _bt_cache[mode] = {"at": time.time(), "data": data}
        return data


NIFTY_DIV = 0.013   # Nifty 50 dividend yield, about 1.2-1.4% a year: the price index leaves it out


def _xirr(flows):
    """Yearly return from dated cash flows [(date, amount)], invested amounts negative."""
    d0 = flows[0][0]
    f = lambda r: sum(a / (1 + r) ** ((d - d0).days / 365.0) for d, a in flows)  # noqa: E731
    lo, hi = -0.99, 5.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if f(mid) > 0:
            lo = mid
        else:
            hi = mid
    return mid * 100


def benchmark(curve, start, mkt):
    """The same money in the Nifty 50 over the same days: all at once, and as a monthly SIP.
    Bought like an index ETF (NIFTYBEES): delivery costs on buy and sell, LTCG 12.5% above
    Rs 1.25 lakh when sold at the end (held > 12 months)."""
    if not curve:
        return None
    n = mkt.ind
    px = []
    for d, _ in curve:
        i = mkt.at(d)
        px.append(n["c"][i] if i is not None else None)
    if px[0] is None:
        return None
    days = [d for d, _ in curve]
    years = max(len(curve) / 248, 0.01)

    def path(with_div):
        units = start * (1 - COST_SIDE) / px[0]
        vals = []
        for k, p in enumerate(px):
            g = (1 + NIFTY_DIV) ** (k / 248) if with_div else 1.0
            vals.append(units * (p or px[k - 1]) * g)
        return vals
    out = {}
    for key, wd in (("price", False), ("with_div", True)):
        v = path(wd)
        peak, dd = v[0], 0.0
        for x in v:
            peak = max(peak, x)
            dd = max(dd, (peak - x) / peak)
        final = v[-1] * (1 - COST_SIDE) - DP_FEE
        gain = final - start
        tax = 0.125 * max(gain - 125000, 0) if len(curve) > 248 else 0.20 * max(gain, 0)
        yearly, prev = [], v[0]
        for i, d in enumerate(days):
            if i == len(days) - 1 or days[i + 1][:4] != d[:4]:
                yearly.append({"year": d[:4], "ret": (v[i] / prev - 1) * 100})
                prev = v[i]
        out[key] = {"final": final, "cagr": ((final / start) ** (1 / years) - 1) * 100, "max_dd": dd * 100,
                    "tax_est": tax, "after_tax": gain - tax,
                    "cagr_after_tax": (((final - tax) / start) ** (1 / years) - 1) * 100, "yearly": yearly}
    # monthly SIP: the same total spread over the months, first trading day of each month
    months = []
    for k, d in enumerate(days):
        if k == 0 or d[:7] != days[k - 1][:7]:
            months.append(k)
    amt = start / len(months)
    units, flows, lots = 0.0, [], []
    for k in months:
        u = amt * (1 - COST_SIDE) / px[k]
        units += u
        lots.append((days[k], u, amt))
        flows.append((date.fromisoformat(days[k]), -amt))
    final = units * px[-1] * (1 - COST_SIDE) - DP_FEE
    end = date.fromisoformat(days[-1])
    st_gain = sum(u * px[-1] - a for d, u, a in lots if (end - date.fromisoformat(d)).days <= 365)
    lt_gain = sum(u * px[-1] - a for d, u, a in lots if (end - date.fromisoformat(d)).days > 365)
    tax = 0.20 * max(st_gain, 0) + 0.125 * max(lt_gain - 125000, 0)
    flows.append((end, final))
    out["sip"] = {"monthly": amt, "months": len(months), "invested": start, "final": final, "xirr": _xirr(flows),
                  "tax_est": tax, "after_tax": final - start - tax}
    step_n = max(1, len(curve) // 260)
    pv = path(False)
    out["curve"] = [[days[k], round(pv[k])] for k in range(0, len(days), step_n)] + [[days[-1], round(pv[-1])]]
    return out


def _summarise(mode, cfg, trades, curve, max_dd, invested_sum, pos, n_stocks, secs):
    start = float(cfg["capital"])
    final = curve[-1][1] if curve else start
    years = max(len(curve) / 248, 0.01)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    nt = len(trades)
    # tax: per Indian financial year (April-March), STCG 20% under 12 months, LTCG 12.5% above Rs 1.25 lakh
    fy = {}
    for t in trades:
        d = date.fromisoformat(t["out"])
        y = d.year if d.month >= 4 else d.year - 1
        k = "lt" if t["held"] >= 365 else "st"
        fy.setdefault(y, {"st": 0.0, "lt": 0.0})[k] += t["pnl"]
    tax = sum(0.20 * max(v["st"], 0) + 0.125 * max(v["lt"] - 125000, 0) for v in fy.values())
    yearly, prev = [], start
    for i, (d, eq) in enumerate(curve):
        if i == len(curve) - 1 or curve[i + 1][0][:4] != d[:4]:
            yearly.append({"year": d[:4], "ret": (eq / prev - 1) * 100})
            prev = eq
    step_n = max(1, len(curve) // 260)
    return {"mode": mode, "label": LABEL[mode], "settings": cfg, "from": curve[0][0] if curve else None,
            "to": curve[-1][0] if curve else None, "years": round(years, 1), "stocks": n_stocks,
            "start": start, "final": final, "total_pct": (final / start - 1) * 100,
            "cagr": ((final / start) ** (1 / years) - 1) * 100 if final > 0 else None,
            "max_dd": max_dd * 100, "trades": nt, "win_rate": len(wins) / nt * 100 if nt else None,
            "avg_win": sum(t["pnl"] for t in wins) / len(wins) if wins else None,
            "avg_loss": sum(t["pnl"] for t in losses) / len(losses) if losses else None,
            "avg_r": sum(t["r"] for t in trades) / nt if nt else None,
            "expectancy": sum(t["pnl"] for t in trades) / nt if nt else None,
            "profit_factor": (sum(t["pnl"] for t in wins) / -sum(t["pnl"] for t in losses)) if losses and sum(t["pnl"] for t in losses) else None,
            "avg_held": sum(t["held"] for t in trades) / nt if nt else None,
            "exposure": invested_sum / len(curve) * 100 if curve else 0,
            "tax_est": tax, "after_tax": final - start - tax,
            "yearly": yearly, "curve": [[d, round(e)] for d, e in curve[::step_n]] + ([[curve[-1][0], round(curve[-1][1])]] if curve else []),
            "exits": {k: sum(1 for t in trades if t["why"] == k) for k in ("target", "trail", "stop", "time", "trend broken")},
            "recent": sorted(trades, key=lambda t: t["out"], reverse=True)[:25], "open": len(pos), "secs": round(secs, 1)}


# ----------------------------------------------------------------- live analysis
WEIGHTS = {
    "swing": {"trend": 15, "setup": 15, "entry": 10, "odds": 20, "earnings": 15, "regime": 10, "exit": 10, "news": 5},
    "invest": {"trend": 20, "setup": 10, "entry": 5, "odds": 15, "earnings": 25, "regime": 10, "exit": 10, "news": 5},
}
_mkt = {"at": 0, "m": None}


def market():
    if not _mkt["m"] or time.time() - _mkt["at"] > 300:
        _mkt.update(m=Market(), at=time.time())
    return _mkt["m"]


def _forming(ind):
    clk = S.market_clock()
    return clk["open"] and ind["d"][-1] == clk["date"]


def state_at(mode, ind, mkt):
    """What the rules say about the latest bar: active setup, entry status and trigger."""
    rules = RULES[mode]
    n = len(ind["c"])
    forming = _forming(ind)
    last_done = n - 2 if forming else n - 1
    out = {"forming": forming, "setup": None, "setup_day": None, "status": "none", "trigger": None}
    if forming:
        sg = signal(mode, ind, n - 1, mkt)
        if sg:
            out.update(setup=sg, setup_day=ind["d"][n - 1], status="provisional")
            return out
    for i in range(last_done, max(last_done - rules["recent"], 0), -1):
        sg = signal(mode, ind, i, mkt)
        if sg:
            price = ind["c"][-1]
            ok = price <= ind["c"][i] * (1 + rules["max_ext"]) and price > stop_for(mode, ind["c"][i], ind["atr"][i])
            out.update(setup=sg, setup_day=ind["d"][i], status=("confirmed" if i == last_done else "recent") if ok else "missed",
                       signal_close=ind["c"][i])
            return out
    i = last_done
    if mode == "swing" and ind["hh40"][i]:
        out["trigger"] = ind["hh40"][i] * 1.002
    elif mode == "invest" and ind["hh252"][i]:
        out["trigger"] = ind["hh252"][i] * 1.002
    return out


def analyze(sym, mode):
    st = S.load_state()
    cfg = settings_for(mode, st)
    rules = RULES[mode]
    with ThreadPoolExecutor(4) as ex:
        f_h = ex.submit(history, sym)
        f_m = ex.submit(market)
        f_e = ex.submit(S.earnings, sym)
        try:
            h = f_h.result()
        except Exception:  # noqa: BLE001
            raise S.ApiError(404, "No price data for %s on Yahoo Finance, NSE or BSE. Check the symbol." % sym)
        name = S.NAMES.get(sym, sym)
        f_n = ex.submit(S.news, sym, name)
        mkt = f_m.result()
        try:
            earn = f_e.result()
        except Exception:  # noqa: BLE001
            earn = None
        try:
            nws = f_n.result()
        except Exception:  # noqa: BLE001
            nws = None
    ind = indicators(h["bars"])
    n, i = len(ind["c"]), len(ind["c"]) - 1
    clk = S.market_clock()
    price, prev = ind["c"][i], ind["c"][i - 1] if i else None
    stt = state_at(mode, ind, mkt)
    W = WEIGHTS[mode]
    checks = []

    def add(cid, skill, title, status, pts, mx, detail):
        checks.append({"id": cid, "skill": skill, "title": title, "status": status, "points": pts, "max": mx, "detail": detail})

    short = len(ind["c"]) < 260
    # trend + relative strength (nse-scanner)
    s50, s200 = ind["sma50"][i], ind["sma200"][i]
    rs_n = rules["rs_days"]
    own, bench = ret(ind, i, rs_n), mkt.ret(ind["d"][i], rs_n)
    own3, bench3 = ret(ind, i, 63), mkt.ret(ind["d"][i], 63)
    rs = (own - bench) * 100 if own is not None and bench is not None else None
    up_long = s200 is not None and price > s200 and (ind["sma200"][i - 20] or 0) < s200
    up_mid = s50 is not None and s200 is not None and price > s50 > s200
    pts = (W["trend"] * 0.3 if up_long else 0) + (W["trend"] * 0.3 if up_mid else 0) + \
        (W["trend"] * 0.4 * max(0.0, min(1.0, (rs or 0) / 15 + 0.5)) if rs is not None and rs > 0 else 0)
    pts = int(round(pts))
    add("trend", "nse-scanner", "Trend and relative strength", "pass" if pts >= W["trend"] * 0.7 else "warn" if pts >= W["trend"] * 0.3 else "fail",
        pts, W["trend"], "%s; %s. %d-month return %s vs Nifty %s (%s)." % (
            "above a rising 200-day average" if up_long else "not above a rising 200-day average",
            "50-day above 200-day" if up_mid else "50-day not above 200-day",
            rs_n // 21, "n/a" if own is None else "%+.1f%%" % (own * 100), "n/a" if bench is None else "%+.1f%%" % (bench * 100),
            "outperforming" if (rs or 0) > 0 else "lagging"))
    # setup (scanner)
    sg = stt["setup"]
    if sg and stt["status"] in ("confirmed", "provisional", "recent"):
        add("setup", "scanner", "Chart setup", "pass", W["setup"], W["setup"], "%s on %s: %s." % (sg[1], stt["setup_day"], sg[2]))
    elif sg:
        add("setup", "scanner", "Chart setup", "warn", W["setup"] // 3, W["setup"],
            "%s on %s, but price has since moved away; wait for the next setup." % (sg[1], stt["setup_day"]))
    else:
        add("setup", "scanner", "Chart setup", "fail", 0, W["setup"],
            "No %s setup in the last %d sessions." % ("trading" if mode == "swing" else "investing", rules["recent"]))
    # entry
    entry_ok = False
    if stt["status"] == "confirmed":
        entry_ok = True
        add("entry", "entry", "Entry confirmation", "pass", W["entry"], W["entry"], "Confirmed on the %s daily close. Buy zone: up to %.2f." % (stt["setup_day"], stt["signal_close"] * (1 + rules["max_ext"])))
    elif stt["status"] == "recent":
        entry_ok = True
        add("entry", "entry", "Entry confirmation", "pass", int(W["entry"] * 0.7), W["entry"],
            "Signal on %s and price is still inside the buy zone (up to %.2f)." % (stt["setup_day"], stt["signal_close"] * (1 + rules["max_ext"])))
    elif stt["status"] == "provisional":
        add("entry", "entry", "Entry confirmation", "warn", W["entry"] // 2, W["entry"],
            "Today's bar shows a setup, but it is only confirmed by the 15:30 close.")
    elif stt["status"] == "missed":
        add("entry", "entry", "Entry confirmation", "fail", 0, W["entry"], "Price has run more than %.0f%% past the signal close. Do not chase." % (rules["max_ext"] * 100))
    elif rules.get("near_high") and price < max(ind["h"][-252:]) * (1 - rules["near_high"]):
        add("entry", "entry", "Entry confirmation", "fail", 0, W["entry"],
            "More than %.0f%% below its 52-week high (%.2f). The rules only buy stocks trading near their highs." % (
                rules["near_high"] * 100, max(ind["h"][-252:])))
    else:
        add("entry", "entry", "Entry confirmation", "warn" if stt["trigger"] and (up_mid or up_long) else "fail", 0, W["entry"],
            ("Waiting: buy only on a daily close above %.2f with strong volume." % stt["trigger"]) if stt["trigger"] else "No entry trigger yet.")
    # plan
    entry = price if entry_ok or stt["status"] == "provisional" else (stt["trigger"] or price)
    # same as the backtest: the stop uses the daily range (ATR) of the signal day
    sig_i = ind["idx"].get(stt["setup_day"]) if stt["setup_day"] and stt["status"] in ("confirmed", "recent", "provisional") else None
    a = ind["atr"][sig_i] if sig_i is not None and ind["atr"][sig_i] else ind["atr"][i - 1 if stt["forming"] else i]
    stop = stop_for(mode, entry, a)
    R = entry - stop
    target = target_for(mode, entry, stop)
    raw = rules["stop_atr"] * (a or 0)
    plan = {"entry": entry, "stop": stop, "target": target, "risk": R, "risk_pct": R / entry * 100, "trigger": not entry_ok,
            "state": stt["status"], "setup": sg[1] if sg else None, "hold_days": rules["hold"],
            "hold_until": (S.now_ist().date() + timedelta(days=int(rules["hold"] * 1.45))).isoformat()}
    clamp = "wide" if raw > entry * rules["max_risk"] else "tight" if raw < entry * rules["min_risk"] else None
    add("exit", "exit", "Stop and exit plan", "warn" if clamp == "wide" else "pass", W["exit"] // 2 if clamp == "wide" else W["exit"], W["exit"],
        "Stop %.2f (%.1f%% below entry, %.0fx the daily range%s). %s Exit by %d trading days at the latest." % (
            stop, R / entry * 100, rules["stop_atr"], ", capped: this stock swings a lot" if clamp == "wide" else "",
            ("Target %.2f (%.1fR); after +%gR the stop moves to break-even, then trails." % (target, rules["target_r"], rules["be_at"])) if target
            else "No fixed target, so winners can run: after +%gR the stop moves to break-even, then trails %g× the daily range below the best close%s." % (
                rules["be_at"], rules["trail_atr"], "; also exits on a close well below the 200-day average" if mode == "invest" else ""),
            rules["hold"]))
    # odds = backtest of the same rules on this stock
    bt = stock_backtest(mode, ind, mkt) if not short else None
    if bt and bt["trades"] >= 4:
        ar = bt["avg_r"]
        p = int(round(W["odds"] * max(0.0, min(1.0, (ar + 0.1) / 0.6))))
        add("odds", "timemachine", "Backtest on this stock", "pass" if ar >= 0.2 else "warn" if ar > 0 else "fail", p, W["odds"],
            "%d trades in %.0f years with these rules: %.0f%% won, average %+.2fR after costs, wins %+.1f%% / losses %+.1f%%, held %.0f days on average." % (
                bt["trades"], bt["years"], bt["win_rate"] * 100, ar, bt["avg_win_pct"] or 0, bt["avg_loss_pct"] or 0, bt["avg_days"] or 0))
    else:
        add("odds", "timemachine", "Backtest on this stock", "warn", W["odds"] // 4, W["odds"],
            "Too few past signals on this stock to judge (%s)." % ("short price history" if short else "%d trades" % (bt["trades"] if bt else 0)))
    # market regime
    reg = mkt.regime(ind["d"][i], mode)
    add("regime", "market", "Market filter (Nifty 50)", "pass" if reg else "fail", W["regime"] if reg else 0, W["regime"],
        "Nifty is %s, so new %s are %s." % ("above its 50- and 200-day averages" if reg and mode == "swing" else "above its 200-day average" if reg else "below its key averages",
                                           "trades" if mode == "swing" else "investments", "allowed" if reg else "not advised"))
    # earnings (analyst): growth over several quarters + next results estimate
    add_earn(checks, mode, earn, W["earnings"])
    # news + big deals
    if nws is None:
        add("news", "news", "News check", "na", 0, 0, "Headlines unavailable right now; not counted.")
    else:
        flagged = [x for x in nws["items"] if x["caution"]]
        add("news", "news", "News check (3 days)", "pass" if not flagged else "warn", W["news"] if not flagged else 1, W["news"],
            "%d headlines, %s." % (len(nws["items"]), "none with caution words" if not flagged else "%d with caution words (%s)" % (
                len(flagged), ", ".join(sorted({w for x in flagged for w in x["caution"]})))))
    try:
        since = (S.now_ist().date() - timedelta(days=60)).isoformat()
        dl = [r for r in S.deals(sym)["rows"] if r["date"] >= since]
        buy = sum(r["value"] for r in dl if r["side"] == "BUY")
        sell = sum(r["value"] for r in dl if r["side"] == "SELL")
        if dl and abs(buy - sell) >= 0.1 * (buy + sell):
            add("deals", "big deals", "Bulk and block deals (60 days)", "pass" if buy > sell else "warn", 5 if buy > sell else 0, 5,
                "Bought Rs %.1f cr, sold Rs %.1f cr." % (buy / 1e7, sell / 1e7))
        else:
            add("deals", "big deals", "Bulk and block deals (60 days)", "na", 0, 0, "No one-sided bulk or block deals on record; not counted.")
    except Exception:  # noqa: BLE001
        add("deals", "big deals", "Bulk and block deals", "na", 0, 0, "Deal files unavailable; not counted.")
    # size + risk
    size = size_long(entry, stop, target, cfg)
    risk = risk_long(sym, size["qty"], entry, stop, mode, st)
    add("size", "budget", "Position size", "pass" if size["qty"] >= 1 else "fail", 0, 0,
        ("%d shares for Rs %s, risking Rs %s (limited by %s)." % (size["qty"], f"{size['cost']:,.0f}", f"{size['max_loss']:,.0f}", size["limited_by"]))
        if size["qty"] >= 1 else "Your limits do not allow even one share at this price and stop.")
    add("risk", "risk", "Risk limits", "pass" if risk["verdict"] == "PASS" else "fail", 0, 0,
        "PASS: all %d limits respected." % len(risk["checks"]) if risk["verdict"] == "PASS"
        else "BLOCK. " + " | ".join(c["name"] + ": " + c["detail"] for c in risk["checks"] if not c["ok"]))
    got, mx = sum(c["points"] for c in checks), sum(c["max"] for c in checks)
    score = int(round(100 * got / mx)) if mx else 0
    if short:
        verdict, why = "skip", "Less than a year of prices is available, so the long-term rules cannot be checked."
    elif score >= 65 and entry_ok and reg and risk["verdict"] == "PASS":
        verdict, why = "qualifies", "Setup confirmed, trend and market agree, and the plan fits your limits."
    elif not reg:
        verdict, why = "wait", "The Nifty is in a downtrend; the rules hold off new buys until it recovers."
    elif score >= 45 and (up_mid or up_long):
        verdict, why = "wait", "Strong stock but no confirmed entry right now. Set an alert on the trigger price."
    else:
        verdict, why = "skip", "Too few checks pass for this to be a rule-based %s." % ("trade" if mode == "swing" else "investment")
    # Trading looks at ~8 months, Investing at ~13 months so the 52-week high is on screen
    start = max(0, n - (160 if mode == "swing" else 270))
    bars = [{"d": ind["d"][k], "o": ind["o"][k], "h": ind["h"][k], "l": ind["l"][k], "c": ind["c"][k], "v": ind["v"][k],
             "va": ind["vavg50"][k], "s20": ind["sma20"][k], "s50": ind["sma50"][k], "s200": ind["sma200"][k]} for k in range(n)]
    try:
        add_overlays(bars, mode)   # on the full history so the RSI and trailing line are warmed up
    except Exception:  # noqa: BLE001
        pass
    bars = bars[start:]
    if bars and bars[0].get("rs"):
        b0 = bars[0]["rs"]
        for b in bars:
            if b.get("rs"):
                b["rs"] = b["rs"] / b0 * 100
    # the level a breakout must close above (40-day high for Trading, 52-week high for Investing)
    lvl_i = i - 1 if stt["forming"] else i
    level = ind["hh40"][lvl_i] if mode == "swing" else ind["hh252"][lvl_i]
    plan["level"] = level
    plan["level_label"] = "40-day high" if mode == "swing" else "52-week high"
    plan["signal_day"] = stt["setup_day"] if sg else None
    plan["vol_x"] = 1.5 if mode == "swing" else 1.3
    src = {"yahoo": "Yahoo Finance", "nse": "NSE end-of-day file", "bse": "BSE end-of-day file"}.get(h["source"], "Yahoo Finance")
    return {"mode": mode, "mode_label": LABEL[mode], "symbol": sym, "name": name, "price": price, "prev_close": prev,
            "change_pct": (price / prev - 1) * 100 if prev else None, "session": ind["d"][i], "live": stt["forming"],
            "clock": clk, "intraday": True, "source": src, "asof": ind["d"][i], "score": score, "points": got,
            "max_points": mx, "verdict": verdict, "why": why, "checks": checks, "plan": plan, "size": size, "risk": risk,
            "backtest": bt, "setups": [{"id": sg[0], "label": sg[1], "detail": sg[2]}] if sg else [],
            "trend": {"rs": rs, "own": own, "bench": bench, "own3": own3, "bench3": bench3, "up_long": up_long, "up_mid": up_mid,
                      "sma50": s50, "sma200": s200, "high52": max(ind["h"][-252:]), "low52": min(ind["l"][-252:]),
                      "atr": a, "rsi": ind["rsi"][i], "regime": reg},
            "daily_bars": bars, "results": results_marks(earn), "news": nws, "earnings": earn, "settings": cfg}


def add_earn(checks, mode, earn, mx):
    if not earn or not earn.get("quarters"):
        checks.append({"id": "earnings", "skill": "analyst", "title": "Earnings trend", "status": "na", "points": 0, "max": 0,
                       "detail": "No reported quarterly figures found; not counted."})
        return
    q = earn["quarters"]
    latest = q[-1]
    if (datetime.now() - datetime.strptime(latest["date"], "%Y-%m-%d")).days > 200:
        checks.append({"id": "earnings", "skill": "analyst", "title": "Earnings trend", "status": "na", "points": 0, "max": 0,
                       "detail": "Newest quarter available is %s, which is out of date; not counted." % latest["date"]})
        return
    c = earn.get("compare") or {}
    rev_up = sum(1 for a, b in zip(q, q[1:]) if a.get("revenue") and b.get("revenue") and b["revenue"] > a["revenue"])
    pr_up = sum(1 for a, b in zip(q, q[1:]) if a.get("net_income") is not None and b.get("net_income") is not None and b["net_income"] > a["net_income"])
    steps = max(1, len(q) - 1)
    score = 0.3 * ((c.get("revenue") or 0) > 0) + 0.3 * ((c.get("net_income") or 0) > 0) + \
        0.2 * (rev_up / steps) + 0.1 * (pr_up / steps) + 0.1 * ((c.get("margin_delta") or 0) >= 0)
    pts = int(round(mx * score))
    nxt = next_results(latest["date"])
    hold_end = S.now_ist().date() + timedelta(days=int(RULES[mode]["hold"] * 1.45))
    pc = lambda v: "n/a" if v is None else "%+.1f%%" % v  # noqa: E731
    d = "Latest quarter %s (%s): revenue %s, net profit %s. Revenue rose in %d of the last %d quarters, profit in %d." % (
        latest["date"], c.get("basis", "n/a"), pc(c.get("revenue")), pc(c.get("net_income")), rev_up, steps, pr_up)
    if nxt <= hold_end:
        d += " Next results expected by about %s, inside your holding period: expect a price swing around that date." % nxt.strftime("%d %b %Y")
    checks.append({"id": "earnings", "skill": "analyst", "title": "Earnings trend", "status": "pass" if score >= 0.7 else "warn" if score >= 0.4 else "fail",
                   "points": pts, "max": mx, "detail": d})


def next_results(quarter_end):
    """Latest results 'by about' date for the quarter after `quarter_end` (YYYY-MM-DD):
    45 days after the quarter ends, 60 after March (year-end results take longer)."""
    qe = date.fromisoformat(quarter_end)
    nxt_q = date(qe.year + (qe.month + 3 > 12), (qe.month + 3 - 1) % 12 + 1, 28)
    nxt_q = (nxt_q.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    return nxt_q + timedelta(days=60 if nxt_q.month == 3 else 45)


def size_long(entry, stop, target, cfg):
    R = entry - stop
    if R <= 0 or entry <= 0:
        return {"qty": 0, "cost": 0, "max_loss": 0, "reward": 0, "limited_by": "invalid plan", "costs": 0}
    by_risk = math.floor(cfg["risk_per_trade"] / R)
    by_cap = math.floor(cfg["max_per_stock"] / entry)
    qty = max(0, min(by_risk, by_cap))
    fee = costs(qty * entry, qty * (target or entry))
    gain = qty * ((target or entry) - entry) - fee
    return {"qty": qty, "cost": qty * entry, "max_loss": qty * R + costs(qty * entry, qty * stop), "reward": gain if target else None,
            "reward_after_tax": gain * 0.8 if target and gain > 0 else None, "limited_by": "risk per trade" if by_risk <= by_cap else "max per stock",
            "by_risk": by_risk, "by_cap": by_cap, "costs": fee}


def _paper(st, mode):
    key = "paper_" + mode
    cap = float(settings_for(mode, st)["capital"])
    if key not in st:
        st[key] = {"cash": cap, "start_cash": cap, "peak": cap, "positions": [], "trades": []}
    return st[key]


def risk_long(sym, qty, entry, stop, mode, st):
    cfg, paper = settings_for(mode, st), _paper(st, mode)
    clk = S.market_clock()
    R = entry - stop
    pos = paper["positions"]
    open_risk = sum(p["qty"] * max(p["entry"] - p["stop"], 0) for p in pos)
    sector = S.UNIVERSE.get(sym, {}).get("industry", "")
    same = sum(1 for p in pos if p.get("sector") and p.get("sector") == sector)
    equity = paper["cash"] + sum(p.get("last", p["entry"]) * p["qty"] for p in pos)
    peak = max(paper.get("peak", equity), equity)
    dd = (peak - equity) / peak * 100 if peak else 0
    checks = [
        {"name": "Position size", "ok": qty >= 1, "detail": "%d shares" % qty if qty >= 1 else "Not even one share fits your limits"},
        {"name": "Risk per trade", "ok": qty >= 1 and qty * R <= cfg["risk_per_trade"] + 0.01, "detail": "Risk Rs %.0f vs limit Rs %.0f" % (qty * R, cfg["risk_per_trade"])},
        {"name": "Max per stock", "ok": qty * entry <= cfg["max_per_stock"] + 0.01, "detail": "Rs %.0f vs limit Rs %.0f" % (qty * entry, cfg["max_per_stock"])},
        {"name": "Open positions", "ok": len(pos) < cfg["max_positions"], "detail": "%d of %d held" % (len(pos), cfg["max_positions"])},
        {"name": "Total open risk", "ok": open_risk + qty * R <= cfg["max_open_risk"] + 0.01,
         "detail": "Rs %.0f after this trade vs limit Rs %.0f" % (open_risk + qty * R, cfg["max_open_risk"])},
        {"name": "Sector limit", "ok": not sector or same < cfg["max_per_sector"],
         "detail": "%d of %d in %s" % (same, cfg["max_per_sector"], sector or "this sector")},
        {"name": "Drawdown pause", "ok": dd < cfg["dd_pause_pct"], "detail": "Account %.1f%% below its peak vs pause at %.0f%%" % (dd, cfg["dd_pause_pct"])},
        {"name": "Cash available", "ok": qty * entry * (1 + COST_SIDE) <= paper["cash"] + 0.01,
         "detail": "Needs Rs %.0f, paper cash Rs %.0f" % (qty * entry * (1 + COST_SIDE), paper["cash"])},
        {"name": "Market open", "ok": clk["open"], "detail": "Paper fills need a live price" if not clk["open"] else "Open"},
        {"name": "No duplicate position", "ok": all(p["symbol"] != sym for p in pos),
         "detail": "Already holding %s" % sym if any(p["symbol"] == sym for p in pos) else "Not held"},
    ]
    return {"verdict": "PASS" if all(c["ok"] for c in checks) else "BLOCK", "checks": checks}


# ----------------------------------------------------------------- scanner
_scan, _scan_lock = {}, threading.Lock()


def scan_row(mode, sym, mkt, extra=False):
    """One scanner row. extra=True also returns the ATR and averages My scanner needs."""
    try:
        h = history(sym)
        ind = indicators(h["bars"])
        i = len(ind["c"]) - 1
        stt = state_at(mode, ind, mkt)
        c = ind["c"][i]
        r3, r6 = ret(ind, i, 63), ret(ind, i, 126)
        b3, b6 = mkt.ret(ind["d"][i], 63), mkt.ret(ind["d"][i], 126)
        s50, s200 = ind["sma50"][i], ind["sma200"][i]
        hi = max(ind["h"][-252:])
        row = {"symbol": sym, "name": S.NAMES.get(sym, sym), "nifty50": sym in S.NIFTY,
               "industry": S.UNIVERSE.get(sym, {}).get("industry", ""), "price": c,
               "change_pct": (c / ind["c"][i - 1] - 1) * 100 if i else None,
               "rs3": (r3 - b3) * 100 if r3 is not None and b3 is not None else None,
               "rs6": (r6 - b6) * 100 if r6 is not None and b6 is not None else None,
               "from_high": (c / hi - 1) * 100, "up_mid": bool(s50 and s200 and c > s50 > s200),
               "up_long": bool(s200 and c > s200 and (ind["sma200"][i - 20] or 0) < s200),
               "setup": stt["setup"][1] if stt["setup"] else None, "setup_detail": stt["setup"][2] if stt["setup"] else "",
               "setup_day": stt["setup_day"], "status": stt["status"], "trigger": stt["trigger"],
               "source": {"nse": "NSE end-of-day", "bse": "BSE end-of-day"}.get(h["source"], "Yahoo")}
        if mode == "invest":
            try:
                e = S.earnings(sym)
                cmp_ = e.get("compare") or {}
                row["rev_g"], row["profit_g"], row["basis"] = cmp_.get("revenue"), cmp_.get("net_income"), cmp_.get("basis")
            except Exception:  # noqa: BLE001
                row["rev_g"] = row["profit_g"] = row["basis"] = None
        if extra:
            # ATR of the signal day when there is one (as the backtest), else of the last completed day
            sd = ind["idx"].get(stt["setup_day"]) if stt["setup_day"] and stt["status"] in ("confirmed", "recent", "provisional") else None
            row["_ind"] = ind
            row["atr"] = ind["atr"][sd if sd is not None else (i - 1 if stt["forming"] and i else i)]
            row["sma50"], row["sma200"] = s50, s200
        return row
    except Exception as e:  # noqa: BLE001
        return {"symbol": sym, "name": S.NAMES.get(sym, sym), "error": str(e)[:120]}


def rank_row(mode, r, vals):
    """Strength percentile vs the 250 (vals = their sorted 3m / 6m values) and the 0-100 rank."""
    key = "rs3" if mode == "swing" else "rs6"
    if r[key] is None or not vals:
        pctl = 0
    else:
        pctl = bisect.bisect_left(vals, r[key]) / max(1, len(vals) - 1)
    pctl = min(1.0, pctl)
    r["rs_pct"] = round(pctl * 100)
    live = r["status"] in ("confirmed", "recent", "provisional")
    if mode == "swing":
        rank = (35 if live else 0) + (20 if r["up_mid"] else 0) + 25 * pctl + (10 if r["from_high"] > -10 else 0) + (10 if r["up_long"] else 0)
    else:
        rank = (15 if live else 0) + (20 if r["up_long"] else 0) + 25 * pctl + (10 if r["from_high"] > -15 else 0) + \
            (15 if (r.get("rev_g") or 0) > 0 else 0) + (15 if (r.get("profit_g") or 0) > 0 else 0)
    r["rank"] = int(min(100, round(rank)))


def scan_long(mode, refresh=False):
    with _scan_lock:
        hit = _scan.get(mode)
        if hit and not refresh and time.time() - hit["at"] < 600:
            return hit["data"]
        mkt = market()
        with ThreadPoolExecutor(12) as ex:
            rows = list(ex.map(lambda s: scan_row(mode, s, mkt), list(S.NAMES)))
        ok = [r for r in rows if "error" not in r]
        key = "rs3" if mode == "swing" else "rs6"
        vals = sorted(r[key] for r in ok if r[key] is not None)
        for r in ok:
            rank_row(mode, r, vals)
        ok.sort(key=lambda r: (-r["rank"], r["symbol"]))
        data = {"mode": mode, "rows": ok, "failed": [r for r in rows if "error" in r], "clock": S.market_clock(),
                "scanned_at": S.now_ist().strftime("%H:%M:%S"), "universe": "Nifty LargeMidcap 250",
                "regime": mkt.regime(mkt.ind["d"][-1], mode)}
        _scan[mode] = {"at": time.time(), "data": data}
        try:
            log_signals(mode, ok, data["regime"])
        except Exception:  # noqa: BLE001  (the journal must never break the scanner)
            pass
        return data


# ----------------------------------------------------------------- forward-test journal
# Every completed-day signal the scanner sees is logged once, with the date it was logged.
# Its result is simulated from the first open AFTER that date, with the same stop / trail /
# time rules, so nothing known after the log date can leak in. Over months this shows
# whether the rules work on days the backtest never saw.
RULES_VERSION = {"swing": "Trading v2", "invest": "Investing v1"}
# average result per signal in the all-stocks backtest (Nov 2017 - Nov 2026, after costs)
EXPECTED_R = {"swing": 0.29, "invest": 0.56}


def log_signals(mode, rows, regime):
    today = S.now_ist().date().isoformat()
    new = [r for r in rows if r.get("status") in ("confirmed", "recent") and r.get("setup_day")]
    if not new:
        return
    with S._state_lock:
        st = S.load_state()
        j = st.setdefault("journal", {}).setdefault(mode, [])
        seen = {(e["symbol"], e["day"]) for e in j}
        for r in new:
            if (r["symbol"], r["setup_day"]) in seen:
                continue
            j.append({"symbol": r["symbol"], "day": r["setup_day"], "logged": today, "setup": r["setup"],
                      "rank": r.get("rank"), "rs_pct": r.get("rs_pct"), "price": r["price"],
                      "regime": bool(regime), "rules": RULES_VERSION[mode]})
        S.save_state(st)


def _journal_outcome(mode, e):
    """Simulate one logged signal from the first open after its log date."""
    h = history(e["symbol"])
    ind = indicators(h["bars"])
    n = len(ind["c"]) - (1 if _forming(ind) else 0)   # completed bars only
    sig_i = ind["idx"].get(e["day"])
    j = next((k for k in range(n) if ind["d"][k] > e["logged"]), None)
    if j is None or sig_i is None:
        return {"status": "waiting", "note": "Buys at the next open"}
    entry = ind["o"][j]
    stop = stop_for(mode, entry, ind["atr"][sig_i])
    R = entry - stop
    pos = {"entry": entry, "stop": stop, "stop0": stop, "R": R, "target": target_for(mode, entry, stop),
           "maxc": entry, "bars": 0}
    for k in range(j, n):
        out = step(mode, ind, k, pos)
        if out:
            px, why = out
            r = (px - entry) / R - COST_SIDE * (entry + px) / R
            return {"status": "closed", "entry_day": ind["d"][j], "entry": entry, "stop0": stop, "exit": px,
                    "exit_day": ind["d"][k], "why": why, "r": r, "pct": (px / entry - 1) * 100, "days": k - j + 1}
    last = ind["c"][n - 1]
    return {"status": "open", "entry_day": ind["d"][j], "entry": entry, "stop0": stop, "stop": pos["stop"],
            "last": last, "r": (last - entry) / R - COST_SIDE * (entry + last) / R, "pct": (last / entry - 1) * 100,
            "days": n - j}


def journal(mode):
    st = S.load_state()
    entries = list((st.get("journal") or {}).get(mode) or [])

    def one(e):
        try:
            return dict(e, **_journal_outcome(mode, e))
        except Exception as ex:  # noqa: BLE001
            return dict(e, status="error", note=str(ex)[:100])

    with ThreadPoolExecutor(8) as ex:
        rows = list(ex.map(one, entries))
    rows.sort(key=lambda r: (r["day"], r["symbol"]), reverse=True)
    closed = [r for r in rows if r["status"] == "closed"]
    live = [r for r in rows if r["status"] in ("closed", "open")]
    wins = [r for r in closed if r["r"] > 0]

    def avg(a):
        return sum(x["r"] for x in a) / len(a) if a else None
    # does a higher scanner rank go with better results? (needs many closed trades to mean anything)
    by_rank = None
    ranked = sorted((r for r in closed if r.get("rank") is not None), key=lambda r: r["rank"])
    if len(ranked) >= 10:
        half = len(ranked) // 2
        by_rank = {"low": avg(ranked[:half]), "high": avg(ranked[half:]), "split": ranked[half]["rank"]}
    return {"mode": mode, "label": LABEL[mode], "rules": RULES_VERSION[mode], "expected_r": EXPECTED_R[mode],
            "since": min((r["logged"] for r in rows), default=None), "signals": len(rows), "closed": len(closed),
            "open": len(live) - len(closed), "win_rate": len(wins) / len(closed) * 100 if closed else None,
            "avg_r_closed": avg(closed), "avg_r_all": avg(live), "by_rank": by_rank, "rows": rows}


# ----------------------------------------------------------------- paper account (positions held for weeks)
def portfolio_long(mode):
    with S._state_lock:
        st = S.load_state()
        paper, clk = _paper(st, mode), S.market_clock()
        keep, closed_now = [], []
        for p in paper["positions"]:
            try:
                ind = indicators(history(p["symbol"])["bars"])
            except Exception:  # noqa: BLE001
                keep.append(p)
                continue
            # replay every daily bar since the buy day from the original plan, so the
            # trailing stop is always worked out the same way
            pos = {"entry": p["entry"], "stop": p["stop0"], "stop0": p["stop0"], "R": p["R"], "target": p.get("target"),
                   "maxc": p["entry"], "bars": 0}
            out = None
            for j in range(len(ind["d"])):
                if ind["d"][j] <= p["opened_date"]:
                    continue
                forming = clk["open"] and ind["d"][j] == clk["date"]
                out = step(mode, ind, j, pos, forming=forming)
                if out:
                    out = (out[0], out[1], ind["d"][j])
                    break
            last = ind["c"][-1]
            if out:
                _close_long(paper, p, out[0], out[1], out[2], clk, mode)
                closed_now.append(p["symbol"])
            else:
                p.update(stop=pos["stop"], last=last, held=pos["bars"], pnl=(last - p["entry"]) * p["qty"],
                         trailing=pos["stop"] > p["stop0"])
                keep.append(p)
        paper["positions"] = keep
        equity = paper["cash"] + sum(p["last"] * p["qty"] for p in keep)
        paper["peak"] = max(paper.get("peak", equity), equity)
        S.save_state(st)
        cfg = settings_for(mode, st)
        return {"mode": mode, "mode_label": LABEL[mode], "cash": paper["cash"], "equity": equity, "start_cash": paper["start_cash"],
                "positions": keep, "trades": paper["trades"][-50:][::-1], "closed_now": closed_now,
                "open_risk": sum(p["qty"] * max(p["entry"] - p["stop"], 0) for p in keep),
                "drawdown": (paper["peak"] - equity) / paper["peak"] * 100 if paper["peak"] else 0,
                "total_pnl": equity - paper["start_cash"], "realised": sum(t["pnl"] for t in paper["trades"]),
                "settings": cfg, "clock": clk}


def _close_long(paper, p, px, why, day, clk, mode=None):
    gross = (px - p["entry"]) * p["qty"]
    fee = costs(p["entry"] * p["qty"], px * p["qty"])
    try:
        S.telegram.notify("paper", "%s Paper %s: sold %d %s at %.2f (%s) · P&L after costs %+.0f" % (
            "✅" if gross - fee >= 0 else "🔻", LABEL.get(mode, "Trading/Investing"), p["qty"], p["symbol"], px, why, gross - fee))
    except Exception:  # noqa: BLE001
        pass
    paper["cash"] += px * p["qty"] * (1 - COST_SIDE) - DP_FEE
    held = (date.fromisoformat(day) - date.fromisoformat(p["opened_date"])).days
    paper["trades"].append({"symbol": p["symbol"], "qty": p["qty"], "entry": p["entry"], "exit": px, "stop0": p["stop0"],
                            "pnl": gross - fee, "costs": fee, "reason": why, "r": (gross - fee) / (p["R"] * p["qty"]),
                            "opened_date": p["opened_date"], "closed_date": day, "closed_at": clk["ist"], "held_days": held,
                            "tax_type": "LTCG" if held >= 365 else "STCG"})


def place_long(mode, sym, confirm):
    if confirm is not True:
        raise S.ApiError(400, "Order not confirmed.")
    a = analyze(sym, mode)
    pl = a["plan"]
    if pl["trigger"]:
        raise S.ApiError(409, "No confirmed entry for %s right now. Wait for the trigger." % sym)
    with S._state_lock:
        st = S.load_state()
        cfg = settings_for(mode, st)
        px = S.quote(sym)["price"] or a["price"]
        stop = pl["stop"]
        if px <= stop:
            raise S.ApiError(409, "Price is at or below the stop; the plan is no longer valid.")
        size = size_long(px, stop, pl["target"], cfg)
        rc = risk_long(sym, size["qty"], px, stop, mode, st)
        if rc["verdict"] != "PASS":
            raise S.ApiError(409, "Risk check BLOCK: " + "; ".join(c["name"] + " - " + c["detail"] for c in rc["checks"] if not c["ok"]))
        paper, clk = _paper(st, mode), S.market_clock()
        pos = {"id": "%s%d" % (sym[:6], int(time.time() * 1000) % 10 ** 8), "symbol": sym, "qty": size["qty"], "entry": px,
               "stop": stop, "stop0": stop, "R": px - stop, "target": pl["target"], "opened_date": clk["date"], "opened_at": clk["ist"],
               "sector": S.UNIVERSE.get(sym, {}).get("industry", ""), "setup": pl["setup"], "last": px, "pnl": 0.0, "held": 0,
               "hold_until": pl["hold_until"]}
        paper["cash"] -= px * size["qty"] * (1 + COST_SIDE)
        paper["positions"].append(pos)
        S.save_state(st)
        return {"ok": True, "position": pos, "risk": rc}


def close_long(mode, pid):
    with S._state_lock:
        st = S.load_state()
        paper, clk = _paper(st, mode), S.market_clock()
        for p in list(paper["positions"]):
            if p["id"] == pid:
                try:
                    px = S.quote(p["symbol"])["price"] or p.get("last", p["entry"])
                except Exception:  # noqa: BLE001
                    px = p.get("last", p["entry"])
                _close_long(paper, p, px, "manual", clk["date"], clk, mode)
                paper["positions"].remove(p)
                S.save_state(st)
                return {"ok": True}
        raise S.ApiError(404, "Position not found.")


def reset_paper(mode, cash):
    with S._state_lock:
        st = S.load_state()
        st["paper_" + mode] = {"cash": cash, "start_cash": cash, "peak": cash, "positions": [], "trades": []}
        S.save_state(st)


# ----------------------------------------------------------------- chart indicators
def add_overlays(rows, mode="invest"):
    """Add RSI(14), the rules' trailing-stop line and relative strength vs the Nifty to
    chart candles (dicts with o/h/l/c and d = start date, optional de = end date)."""
    if not rows:
        return rows
    c = [r["c"] for r in rows]
    rsi = S.rsi_series(c)
    tr = [rows[0]["h"] - rows[0]["l"]] + [max(rows[k]["h"] - rows[k]["l"], abs(rows[k]["h"] - c[k - 1]), abs(rows[k]["l"] - c[k - 1]))
                                          for k in range(1, len(rows))]
    mult, look = RULES[mode]["trail_atr"], 60
    try:
        nif = Market()
    except Exception:  # noqa: BLE001
        nif = None
    base = None
    for k, r in enumerate(rows):
        r["rsi"] = rsi[k]
        if k >= 13:
            a = sum(tr[k - 13:k + 1]) / 14
            r["trail"] = max(c[max(0, k - look + 1):k + 1]) - mult * a
        if nif:
            j = nif.at(r.get("de") or r["d"])
            if j is not None:
                ratio = c[k] / nif.ind["c"][j]
                base = base or ratio
                r["rs"] = ratio / base * 100
    return rows


def results_marks(earn):
    """Approximate results dates (quarter end + 45 days, + 60 for March) with profit growth."""
    out = []
    q = (earn or {}).get("quarters") or []
    for a, b in zip([None] + q[:-1], q):
        qe = date.fromisoformat(b["date"])
        d = qe + timedelta(days=60 if qe.month == 3 else 45)
        g = None
        if a and a.get("net_income") and b.get("net_income") is not None:
            g = (b["net_income"] - a["net_income"]) / abs(a["net_income"]) * 100
        out.append({"d": d.isoformat(), "q": b["date"], "growth": g})
    return out
