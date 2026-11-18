#!/usr/bin/env python3
"""Tradeskill Portal - local NSE purchase predictor.

Zero dependencies: Python 3.9+ standard library only.
Run:  python server.py   then open http://127.0.0.1:8765

Indian market only. Data: free delayed NSE quotes from Yahoo Finance, headlines
from Google News / Bing RSS, bulk and block deals from NSE's public files.
The broker is a built-in PAPER ledger. No real orders are ever sent anywhere.
"""
import csv
import hashlib
import hmac
import html
import secrets
import io
import json
import math
import os
import random
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(ROOT, "static")
DATA = os.path.join(ROOT, "data")
STATE_FILE = os.path.join(DATA, "state.json")
PORT = int(os.environ.get("PORT", "8765"))
# Running on a NAS / home server: HOST=0.0.0.0 accepts other devices on your network (then
# PORTAL_PASSWORD is required). PUBLIC_URL = the address you open it at, e.g.
# http://100.x.y.z:8765 (Tailscale) - used for the Zerodha login return address.
HOST = os.environ.get("HOST", "127.0.0.1")
PASSWORD = os.environ.get("PORTAL_PASSWORD", "")
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")
try:   # data/public_url.txt (one line) overrides it, so it can change without touching the password file
    with open(os.path.join(DATA, "public_url.txt"), encoding="utf-8") as _f:
        PUBLIC_URL = _f.read().strip().rstrip("/") or PUBLIC_URL
except OSError:
    pass
LOOPBACK = HOST in ("127.0.0.1", "localhost", "::1")
IST = timezone(timedelta(hours=5, minutes=30))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}

OPEN_M, OR_END_M, SQUARE_M, CLOSE_M = 555, 570, 915, 930  # 09:15 09:30 15:15 15:30

with open(os.path.join(ROOT, "nifty50.json"), encoding="utf-8") as _f:
    NIFTY = json.load(_f)  # Nifty 50: {"RELIANCE": "Reliance Industries", ...}
try:
    with open(os.path.join(ROOT, "nifty250.json"), encoding="utf-8") as _f:
        UNIVERSE = json.load(_f)  # Nifty LargeMidcap 250: {"SYMBOL": {"name":..., "industry":...}}
except (OSError, ValueError):
    UNIVERSE = {}
for _k, _v in NIFTY.items():
    UNIVERSE.setdefault(_k, {"name": _v, "industry": ""})
NAMES = {k: NIFTY.get(k) or v["name"] for k, v in UNIVERSE.items()}

CAUTION = ["fraud", "probe", "raid", "downgrade", "default", "resign", "penalty", "plunge",
           "slump", "crash", "tumble", "sink", "lawsuit", "investigation", "scam", "ban ",
           "fine ", "loss widens", "profit falls", "profit drops", "sebi notice", "recall"]


# Headline tone for the News page: green = positive, red = negative, plain = no clear impact.
# A word match, not a reading of the story. Phrases are matched before single words, and
# each matched piece of text counts once.
_NEUTRAL_PHRASES = [r"stop[- ]loss", r"profit[- ]and[- ]loss", r"p&l",
                    r"price,? news", r"share price today", r"stock price today", r"live updates?"]
_TONE_PHRASES = [  # (pattern, weight)
    (r"loss(es)? (narrows?|narrowed|shrinks?|halves)", 2), (r"turns? (profitable|around)", 2),
    (r"back (in|to) (the )?black", 2), (r"(net )?profit (rises?|rose|jumps?|surges?|soars?|climbs?|grows?|up|doubles?|beats?)", 2),
    (r"(revenue|sales|income|ebitda|margins?|earnings) (rises?|rose|jumps?|surges?|soars?|climbs?|grows?|up|improves?|beats?|expands?)", 2),
    (r"(beats?|tops?|surpass(es)?|exceeds?) (street |analyst |market )?(estimates?|expectations?|forecasts?)", 2),
    (r"(stocks?|shares?) to buy", 2), (r"top picks?", 2), (r"buy (rating|call|recommendation)", 2),
    (r"(rating|target) (raised|hiked|upped|increased)", 2), (r"(raises?|hikes?|ups) (its |the )?(target|rating|guidance|stake)", 2),
    (r"(record|all[- ]time|52[- ]week|lifetime|multi[- ]year|fresh|new) highs?", 2), (r"(near|closes near) (its )?(record |52[- ]week )?highs?", 1),
    (r"(bags?|wins?|secures?|receives?|bagged|won|secured|received) [^.;:]{0,40}?(orders?|contracts?|deals?|approvals?)", 2),
    (r"order (win|inflow|book (rises|grows|at record))", 2), (r"(bonus|stock split|buyback|special dividend)", 1),
    (r"call (contracts|options|writers?|buying)", 1), (r"fii(s)? (buy|add|raise)", 1),
    (r"loss(es)? (widens?|widened|deepens?|swells?)", -2), (r"(swings?|slips?|falls?|plunges?) (in)?to (a )?(net )?loss", -2),
    (r"(net )?profit (falls?|fell|drops?|dropped|declines?|declined|slumps?|plunges?|tumbles?|sinks?|down|halves|misses)", -2),
    (r"(revenue|sales|income|ebitda|margins?|earnings) (falls?|fell|drops?|declines?|slumps?|down|contracts?|shrinks?|misses|weakens?)", -2),
    (r"(miss(es)?|misses|missed|below|lags?) (street |analyst |market )?(estimates?|expectations?|forecasts?)", -2),
    (r"(stocks?|shares?) to (sell|avoid)", -2), (r"sell (rating|call|recommendation)", -2),
    (r"(rating|target) (cut|lowered|slashed|reduced)", -2), (r"(cuts?|lowers?|slashes?|trims?) (its |the )?(target|rating|guidance|stake|forecast)", -2),
    (r"(record|all[- ]time|52[- ]week|multi[- ]year|fresh|new) lows?", -2), (r"profit[- ]booking", -1),
    (r"put (contracts|options|buying|writers? exit)", -1), (r"puts? draw", -1), (r"fii(s)? (sell|cut|exit|dump)", -1),
    (r"stake sale", -1), (r"block deal", 0), (r"faces? pressure", -1), (r"under pressure", -1),
    (r"(up|gains?|higher|rises?|jumps?) (by )?(over |nearly |around |about )?\d", 1),
    (r"(down|lower|loses|falls?|drops?) (by )?(over |nearly |around |about )?\d", -1),
    (r"(trades?|trading|ends?|ended|closes?|closed|opens?|opened|settles?|settled|edges?) (sharply |marginally |slightly )?higher", 1),
    (r"(trades?|trading|ends?|ended|closes?|closed|opens?|opened|settles?|settled|edges?) (sharply |marginally |slightly )?lower", -1),
    (r"(workers?|employees?|staff|union)'? (go on )?strike|on strike", -2), (r"under fire|(major |massive )?fire (at|breaks)", -2),
    (r"steps? down", -1), (r"show[- ]cause", -2), (r"sebi (notice|order|probe|penalty|ban|action)", -2), (r"income tax (raid|notice|demand)", -2),
    (r"tax demand", -2), (r"gst (notice|demand)", -2), (r"pledged? shares", -1),
]
_TONE_WORDS = {
    1: ["gain", "gains", "gained", "rise", "rises", "rose", "rising", "climb", "climbs", "climbed", "advance", "advances",
        "rebound", "rebounds", "recovers", "recovery", "strong", "robust", "bullish", "positive", "upbeat",
        "shine", "shines", "outperform", "outperforms", "outperformed", "buying", "accumulate", "invest", "invests",
        "investment", "expansion", "expands", "expand", "launches", "approval", "approved", "dividend", "upgrade",
        "upgrades", "upgraded", "boost", "boosts", "boosted", "optimistic", "growth", "acquires", "wins", "milestone"],
    2: ["surge", "surges", "surged", "soar", "soars", "soared", "jump", "jumps", "jumped", "rally", "rallies", "rallied",
        "zoom", "zooms", "skyrocket", "skyrockets", "spurt", "spurts", "breakout", "multibagger"],
    -1: ["fall", "falls", "fell", "falling", "drop", "drops", "dropped", "decline", "declines", "declined",
         "dip", "dips", "dipped", "slip", "slips", "slipped", "slide", "slides", "weak", "weaker", "bearish",
         "negative", "pressure", "concern", "concerns", "worries", "worry", "caution", "cautious", "selling", "sell-off",
         "selloff", "underperform", "underperforms", "loss", "losses",
         "delay", "delayed", "warning", "warns", "headwinds", "outflow", "outflows", "volatile", "exit", "exits"],
    -2: ["plunge", "plunges", "plunged", "crash", "crashes", "crashed", "tumble", "tumbles", "tumbled", "slump", "slumps",
         "slumped", "sink", "sinks", "sank", "tank", "tanks", "tanked", "nosedive", "nosedives", "plummet", "plummets",
         "fraud", "scam", "probe", "raid", "raids", "penalty", "fined", "fine", "lawsuit", "ban", "banned", "resigns",
         "resignation", "quits", "default", "defaults", "investigation", "insolvency", "bankruptcy", "recall",
         "blaze", "accident", "shutdown", "suspended", "suspension", "downgrade", "downgrades", "downgraded", "rout",
         "bloodbath", "meltdown"],
}
_TONE_WORD_RE = [(w, re.compile(r"(?<![\w-])(?:" + "|".join(re.escape(x) for x in ws) + r")(?![\w-])"))
                 for w, ws in _TONE_WORDS.items()]
_TONE_PHRASE_RE = [(re.compile(p), w) for p, w in _TONE_PHRASES]
_NEUTRAL_RE = re.compile("|".join(_NEUTRAL_PHRASES))
_CLAUSE_RE = re.compile(r"\s*(?:;|:|\||—| - |\bwhile\b|\bbut\b|\bwhereas\b|\bhowever\b)\s*")


def _tone_score(text):
    """Score one piece of text; returns (score, matched words)."""
    t = " " + _NEUTRAL_RE.sub(" ", text) + " "
    score, hits = 0, []
    for rx, w in _TONE_PHRASE_RE:
        for m in rx.finditer(t):
            score += w
            if w:
                hits.append(m.group(0).strip())
        t = rx.sub(" ", t)
    for w, rx in _TONE_WORD_RE:
        for m in rx.finditer(t):
            score += w
            hits.append(m.group(0))
    return score, hits


def headline_tone(title, keys=()):
    """'pos', 'neg' or 'neu' for a headline about one stock.

    When the headline has several parts (split on ; : while but ...), the part that names
    the stock decides, if it has any tone words; otherwise the whole headline does.
    """
    low = title.lower()
    parts = [p for p in _CLAUSE_RE.split(low) if p.strip()]
    mine = [p for p in parts if any(k in p for k in keys)] if len(parts) > 1 else []
    score, hits = 0, []
    if mine:
        for p in mine:
            s, h = _tone_score(p)
            score, hits = score + s, hits + h
    if not hits:
        score, hits = _tone_score(low)
    tone = "pos" if score >= 1 else "neg" if score <= -1 else "neu"
    return tone, score, hits


class ApiError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code, self.msg = code, msg


# ----------------------------------------------------------------- state
_state_lock = threading.RLock()
DEFAULT_STATE = {
    "settings": {"budget": 25000, "max_loss": 500, "daily_loss": 1500, "max_trades": 3,
                 "entry_start": "09:30", "entry_end": "14:30",
                 "watchlist": ["RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS"]},
    "alerts": [],
    "paper": {"cash": 100000.0, "start_cash": 100000.0, "positions": [], "trades": []},
    "seen_news": [],
}


def load_state():
    with _state_lock:
        st = json.loads(json.dumps(DEFAULT_STATE))
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, encoding="utf-8") as f:
                    disk = json.load(f)
                for k, v in disk.items():
                    if isinstance(v, dict) and isinstance(st.get(k), dict):
                        st[k].update(v)
                    else:
                        st[k] = v
            except (ValueError, OSError):
                pass
        return st


def save_state(st):
    with _state_lock:
        os.makedirs(DATA, exist_ok=True)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, indent=1)
        os.replace(tmp, STATE_FILE)


# ----------------------------------------------------------------- fetch
_cache, _cache_lock = {}, threading.Lock()


def fetch(url, ttl=60, timeout=20, tries=2):
    now = time.time()
    with _cache_lock:
        hit = _cache.get(url)
        if hit and now - hit[0] < ttl:
            return hit[1]
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
            with _cache_lock:
                _cache[url] = (now, data)
            return data
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt + 1 < tries:
                time.sleep(0.8)
    if hit:
        return hit[1]  # stale is better than nothing
    raise last


def ysym(sym):
    return sym + ".NS"


def chart(sym, rng, interval, ttl=60):
    """Price bars. Yahoo Finance first; if Yahoo has no data for the scrip, daily bars
    fall back to NSE's end-of-day files, and if NSE has nothing either, to BSE's.
    Neither exchange publishes an open intraday feed."""
    try:
        meta, bars = yahoo_chart(sym, rng, interval, ttl)
        if bars or interval != "1d":
            return meta, bars
    except Exception:  # noqa: BLE001
        if interval != "1d":
            raise
    try:
        return eod_daily(sym, "nse")
    except ApiError:
        return eod_daily(sym, "bse")   # last resort: BSE's end-of-day file


def yahoo_chart(sym, rng, interval, ttl=60):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/%s?range=%s&interval=%s"
           "&includePrePost=false" % (urllib.parse.quote(ysym(sym), safe=""), rng, interval))
    res = json.loads(fetch(url, ttl))["chart"]["result"][0]
    meta, ts = res["meta"], res.get("timestamp") or []
    q = res["indicators"]["quote"][0]
    bars = []
    for i, t in enumerate(ts):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if o is None or h is None or l is None or c is None:
            continue
        bars.append({"t": t, "o": o, "h": h, "l": l, "c": c, "v": q["volume"][i] or 0})
    return meta, bars


# ----------------------------------------------------------------- exchange end-of-day fallbacks
_bhav, _bhav_lock = {}, threading.Lock()   # (source, "YYYY-MM-DD") -> {symbol: [o, h, l, c, v]}
BHAV_DAYS = 75
EOD_LABEL = {"nse": "NSE end-of-day file", "bse": "BSE end-of-day file"}


def _parse_nse(d):
    raw = fetch("https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_%s.csv"
                % d.strftime("%d%m%Y"), 3600, 30, tries=1).decode("utf-8", "replace")
    day = {}
    for row in csv.reader(io.StringIO(raw)):
        r = [x.strip() for x in row]
        if len(r) < 11 or r[1] not in ("EQ", "BE", "BZ"):
            continue
        try:
            day[r[0]] = [float(r[4]), float(r[5]), float(r[6]), float(r[8]), float(r[10])]
        except ValueError:
            continue
    return day


def _parse_bse(d):
    raw = fetch("https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_%s_F_0000.CSV"
                % d.strftime("%Y%m%d"), 3600, 30, tries=1).decode("utf-8", "replace")
    day = {}
    for r in csv.DictReader(io.StringIO(raw)):
        if (r.get("FinInstrmTp") or "").strip() != "STK":
            continue
        try:
            day[r["TckrSymb"].strip()] = [float(r["OpnPric"]), float(r["HghPric"]), float(r["LwPric"]),
                                          float(r["ClsPric"]), float(r["TtlTradgVol"] or 0)]
        except (KeyError, ValueError):
            continue
    return day


def _bhav_day(src, d):
    """One trading day's prices for every stock on an exchange, from its public bhavcopy file."""
    key = (src, d.isoformat())
    if key in _bhav:
        return _bhav[key]
    path = os.path.join(DATA, "bhav" if src == "nse" else "bhav_bse", key[1] + ".json")
    try:
        with open(path, encoding="utf-8") as f:
            _bhav[key] = json.load(f)
        return _bhav[key]
    except (OSError, ValueError):
        pass
    try:
        day = (_parse_nse if src == "nse" else _parse_bse)(d)
    except Exception:  # noqa: BLE001  (holiday, or today's file not published yet)
        day = {}
    _bhav[key] = day
    if day or (now_ist().date() - d).days > 3:   # remember holidays, but retry recent days
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(day, f)
    return day


def eod_daily(sym, src="nse"):
    with _bhav_lock:
        d, days = now_ist().date(), []
        while len(days) < 115:
            if d.weekday() < 5:
                days.append(d)
            d -= timedelta(days=1)
        with ThreadPoolExecutor(8) as ex:
            got = list(ex.map(lambda x: _bhav_day(src, x), days))
    bars = []
    for d, day in zip(days, got):
        r = day.get(sym) if day else None
        if r:
            ts = int(datetime(d.year, d.month, d.day, 15, 30, tzinfo=IST).timestamp())
            bars.append({"t": ts, "o": r[0], "h": r[1], "l": r[2], "c": r[3], "v": r[4]})
        if len(bars) >= BHAV_DAYS:
            break
    bars.reverse()
    if not bars:
        raise ApiError(404, "No price data for %s on Yahoo Finance, NSE or BSE." % sym)
    return {"regularMarketPrice": bars[-1]["c"], "previousClose": bars[-2]["c"] if len(bars) > 1 else None,
            "source": src, "asof": datetime.fromtimestamp(bars[-1]["t"], IST).date().isoformat()}, bars


def nse_daily(sym):
    return eod_daily(sym, "nse")


# ----------------------------------------------------------------- time
def now_ist():
    return datetime.now(IST)


def mins(d):
    return d.hour * 60 + d.minute


def hm(m):
    return "%02d:%02d" % (m // 60, m % 60)


def parse_hm(s, default):
    try:
        h, m = s.split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return default


def market_clock():
    n = now_ist()
    m = mins(n)
    weekday = n.weekday() < 5
    is_open = weekday and OPEN_M <= m < CLOSE_M
    if is_open:
        label = "Open"
    elif weekday and m < OPEN_M:
        label = "Pre-open"
    else:
        label = "Closed"
    return {"open": is_open, "label": label, "ist": n.strftime("%Y-%m-%d %H:%M:%S"),
            "date": n.date().isoformat(), "minute": m}


def sessions(bars):
    out = {}
    for b in bars:
        d = datetime.fromtimestamp(b["t"], IST)
        m = mins(d)
        if OPEN_M <= m < CLOSE_M:
            nb = dict(b)
            nb["m"] = m
            out.setdefault(d.date().isoformat(), []).append(nb)
    return out


# ----------------------------------------------------------------- indicators
def sma(vals, n):
    return sum(vals[-n:]) / n if len(vals) >= n else None


def rsi_series(closes, n=14):
    out = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    ag, al = gains / n, losses / n
    out[n] = 100 - 100 / (1 + ag / al) if al else 100.0
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (n - 1) + max(d, 0)) / n
        al = (al * (n - 1) + max(-d, 0)) / n
        out[i] = 100 - 100 / (1 + ag / al) if al else 100.0
    return out


def atr(bars, n=14):
    if len(bars) <= n:
        return None
    trs = []
    for i in range(1, len(bars)):
        pc = bars[i - 1]["c"]
        trs.append(max(bars[i]["h"] - bars[i]["l"], abs(bars[i]["h"] - pc), abs(bars[i]["l"] - pc)))
    return sum(trs[-n:]) / n


def daily_view(bars, live):
    """Chart setups on daily bars (trader-scanner / trader-nse-scanner rules)."""
    v = {"setups": [], "trend_up": False, "rsi": None, "rvol": None, "atr": None,
         "sma20": None, "sma50": None, "high20": None}
    if len(bars) < 30:
        return v
    c = [b["c"] for b in bars]
    h = [b["h"] for b in bars]
    l = [b["l"] for b in bars]
    vol = [b["v"] for b in bars]
    v["sma20"], v["sma50"] = sma(c, 20), sma(c, 50)
    v["atr"] = atr(bars)
    rs = rsi_series(c)
    v["rsi"] = rs[-1]
    v["high20"] = max(h[-21:-1])
    v["trend_up"] = bool(v["sma50"] and c[-1] > v["sma50"] and v["sma20"] > v["sma50"])
    i = -2 if live else -1  # last complete day for volume
    base = vol[i - 20:i]
    if base and sum(base) > 0:
        v["rvol"] = vol[i] / (sum(base) / len(base))

    if c[-1] > v["high20"]:
        v["setups"].append({"id": "breakout", "label": "20-day breakout",
                            "detail": "Close above the prior 20-day high of %.2f" % v["high20"]})
    elif c[-1] >= v["high20"] * 0.99:
        v["setups"].append({"id": "near", "label": "Near 20-day high",
                            "detail": "Within 1%% of the 20-day high %.2f" % v["high20"]})

    # bull flag: sharp pole, then a tight shallow pullback
    best = None
    for f in range(3, 9):
        top_i = len(c) - f - 1
        for k in range(5, 13):
            if top_i - k < 0:
                continue
            base_c, top = c[top_i - k], max(h[top_i - 2:top_i + 1])
            gain = top / base_c - 1
            if gain < 0.07:
                continue
            pole = top - base_c
            fh, fl = max(h[-f:]), min(l[-f:])
            if fh <= top * 1.01 and fl >= top - 0.5 * pole and (fh - fl) / top <= 0.06:
                if not best or gain > best[0]:
                    best = (gain, f, k)
    if best:
        v["setups"].append({"id": "flag", "label": "Bull flag",
                            "detail": "%.1f%% pole over %d days, %d-day tight flag"
                                      % (best[0] * 100, best[2], best[1])})

    recent = [x for x in rs[-4:-1] if x is not None]
    if recent and min(recent) < 32 and c[-1] > c[-2] and c[-1] > bars[-1]["o"]:
        v["setups"].append({"id": "bounce", "label": "Oversold bounce",
                            "detail": "RSI dipped to %.0f and price is turning up" % min(recent)})
    return v


# ----------------------------------------------------------------- ORB plan (entry + exit)
def orb_plan(sb, entry_cutoff, now_ts=None):
    """Opening-range breakout on one session of 5-minute bars.

    Opening range = 09:15-09:30. Entry = first completed 5-minute close above the
    range high. Stop = range midpoint. Target = entry + 2R.
    """
    orb = [b for b in sb if b["m"] < OR_END_M]
    rest = [b for b in sb if b["m"] >= OR_END_M]
    if not orb:
        return None
    hi, lo = max(b["h"] for b in orb), min(b["l"] for b in orb)
    mid = (hi + lo) / 2
    p = {"or_high": hi, "or_low": lo, "or_mid": mid, "or_complete": bool(rest),
         "state": "waiting", "entry": None, "stop": mid, "target": None, "risk": None,
         "entry_m": None, "outcome": None, "r": None, "exit_m": None}
    for i, b in enumerate(rest):
        if b["m"] > entry_cutoff:
            break
        if now_ts is not None and b["t"] + 300 > now_ts:
            break  # bar still forming: not a close yet
        if b["c"] > hi:
            entry = b["c"]
            risk = entry - mid
            target = entry + 2 * risk
            p.update(state="confirmed", entry=entry, risk=risk, target=target,
                     entry_m=min(b["m"] + 5, CLOSE_M), outcome="open")
            lastc = entry
            for a in rest[i + 1:]:
                if a["m"] >= SQUARE_M:
                    break
                lastc = a["c"]
                if a["l"] <= mid:
                    p.update(outcome="stop", r=-1.0, exit_m=a["m"])
                    break
                if a["h"] >= target:
                    p.update(outcome="target", r=2.0, exit_m=a["m"])
                    break
            if p["outcome"] == "open":
                p["r"] = (lastc - entry) / risk if risk > 0 else 0.0
            break
    return p


def monte_carlo(sess, entry, stop, target, steps, seed, cutoff=870, n=10000):
    """trader-timemachine: replay the plan n times by resampling real 5-minute bars."""
    # Prefer bars that followed a confirmed breakout in past sessions, so the replay
    # reflects how this stock behaves *after* the setup; fall back to every bar.
    pool, every = [], []
    for sb in sess.values():
        hp = orb_plan(sb, cutoff)
        for i in range(1, len(sb)):
            pc = sb[i - 1]["c"]
            if pc > 0:
                tup = (sb[i]["l"] / pc, sb[i]["h"] / pc, sb[i]["c"] / pc)
                every.append(tup)
                if hp and hp["state"] == "confirmed" and sb[i]["m"] >= hp["entry_m"]:
                    pool.append(tup)
    conditioned = len(pool) >= 300
    if not conditioned:
        pool = every
    risk = entry - stop
    if len(pool) < 200 or risk <= 0 or steps < 1:
        return None
    rnd = random.Random(seed)
    choice = rnd.choice
    wins = losses = 0
    r_sum = 0.0
    for _ in range(n):
        p = entry
        done = False
        for _s in range(steps):
            lo, hi, cl = choice(pool)
            if p * lo <= stop:
                losses += 1
                r_sum -= 1.0
                done = True
                break
            if p * hi >= target:
                wins += 1
                r_sum += (target - entry) / risk
                done = True
                break
            p *= cl
        if not done:
            r_sum += (p - entry) / risk
    return {"runs": n, "p_target": wins / n, "p_stop": losses / n,
            "p_timeout": (n - wins - losses) / n, "ev_r": r_sum / n,
            "steps": steps, "bars_sampled": len(pool), "days": len(sess), "conditioned": conditioned}


# ----------------------------------------------------------------- earnings (trader-analyst)
def earnings(sym):
    day = int(time.time() // 86400) * 86400 + 86400
    types = "quarterlyTotalRevenue,quarterlyNetIncome,quarterlyDilutedEPS,quarterlyOperatingIncome"
    url = ("https://query1.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/%s"
           "?type=%s&period1=%d&period2=%d"
           % (urllib.parse.quote(ysym(sym), safe=""), types, day - 3 * 366 * 86400, day))
    res = json.loads(fetch(url, 6 * 3600))["timeseries"]["result"]
    names = {"quarterlyTotalRevenue": "revenue", "quarterlyNetIncome": "net_income",
             "quarterlyDilutedEPS": "eps", "quarterlyOperatingIncome": "op_income"}
    q = {}
    for r in res:
        t = r["meta"]["type"][0]
        for x in r.get(t) or []:
            if x and x.get("reportedValue"):
                q.setdefault(x["asOfDate"], {})[names[t]] = x["reportedValue"]["raw"]
    if not q:
        raise ApiError(404, "No reported earnings found for %s" % sym)
    dates = sorted(q)
    rows = []
    for d in dates[-6:]:
        r = dict(q[d])
        r["date"] = d
        rev = r.get("revenue")
        r["net_margin"] = r["net_income"] / rev * 100 if rev and r.get("net_income") is not None else None
        r["op_margin"] = r["op_income"] / rev * 100 if rev and r.get("op_income") is not None else None
        rows.append(r)
    latest = rows[-1]
    ld = datetime.strptime(latest["date"], "%Y-%m-%d")
    base, basis = None, None
    for r in rows[:-1]:
        if abs((ld - datetime.strptime(r["date"], "%Y-%m-%d")).days - 365) <= 20:
            base, basis = r, "YoY"
    if base is None and len(rows) > 1:
        base = rows[-2]
        gap = (ld - datetime.strptime(base["date"], "%Y-%m-%d")).days
        basis = "QoQ" if 75 <= gap <= 110 else "vs quarter ending " + base["date"]

    def growth(k):
        if base and base.get(k) and latest.get(k) is not None:
            return (latest[k] - base[k]) / abs(base[k]) * 100
        return None

    cmp_ = None
    if base:
        cmp_ = {"basis": basis, "vs": base["date"], "revenue": growth("revenue"),
                "net_income": growth("net_income"), "eps": growth("eps"),
                "margin_delta": (latest["net_margin"] - base["net_margin"])
                if latest.get("net_margin") is not None and base.get("net_margin") is not None else None}
    return {"symbol": sym, "quarters": rows, "latest": latest, "compare": cmp_,
            "source": "Yahoo Finance reported fundamentals"}


# ----------------------------------------------------------------- news (trader-news)
def _rss(data, strip_source=False):
    items = []
    for it in ET.fromstring(data).iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        src = ""
        for ch in it:
            if ch.tag.lower().endswith("source"):
                src = (ch.text or "").strip()
        ts = 0
        try:
            ts = int(parsedate_to_datetime(it.findtext("pubDate")).timestamp())
        except (TypeError, ValueError):
            pass
        if strip_source and src and title.endswith(" - " + src):
            title = title[: -len(src) - 3]
        if title and link.startswith("http"):
            items.append({"title": title, "link": link, "source": src, "ts": ts})
    return items


def news(sym, name=None):
    name = name or NAMES.get(sym) or sym
    q = urllib.parse.quote("%s share" % name)
    items, source = [], None
    keys = {sym.lower(), name.lower(), name.split()[0].lower()}
    keys = [k for k in keys if len(k) >= 3]
    try:
        items = _rss(fetch("https://news.google.com/rss/search?q=%s%%20when:3d&hl=en-IN&gl=IN&ceid=IN:en" % q,
                           600), strip_source=True)
        source = "Google News"
    except Exception:  # noqa: BLE001
        items = _rss(fetch("https://www.bing.com/news/search?q=%s&format=rss&cc=IN" % q, 600))
        source = "Bing News"
    cutoff = time.time() - 3 * 86400
    items = sorted([i for i in items if i["ts"] >= cutoff and any(k in i["title"].lower() for k in keys)],
                   key=lambda i: -i["ts"])[:12]
    seen = set(load_state()["seen_news"])
    for i in items:
        i["id"] = hashlib.sha1((i["title"] + i["source"]).encode("utf-8")).hexdigest()[:16]
        i["new"] = i["id"] not in seen
        low = i["title"].lower() + " "
        i["caution"] = [w.strip() for w in CAUTION if w in low]
        i["tone"], i["tone_score"], i["tone_words"] = headline_tone(i["title"], keys)
    return {"symbol": sym, "name": name, "items": items, "source": source}


# ----------------------------------------------------------------- big deals (NSE bulk + block)
DEAL_FEEDS = (("bulk", "https://nsearchives.nseindia.com/content/equities/bulk.csv"),
              ("block", "https://nsearchives.nseindia.com/content/equities/block.csv"))


def deals(sym=None, days=90):
    """NSE bulk and block deals: named large buyers and sellers.

    NSE publishes only the latest trading day as a public file, so every fetch is
    merged into data/deals.json and the history builds up as the portal is used.
    """
    path = os.path.join(DATA, "deals.json")
    failed = []
    with _state_lock:
        store = {}
        try:
            with open(path, encoding="utf-8") as f:
                store = json.load(f)
        except (OSError, ValueError):
            pass
        before = len(store)
        for kind, url in DEAL_FEEDS:
            try:
                text = fetch(url, 900).decode("utf-8", "replace")
                for raw in csv.DictReader(io.StringIO(text)):
                    row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
                    try:
                        d = datetime.strptime(row["Date"], "%d-%b-%Y").date().isoformat()
                        qty = float(row["Quantity Traded"].replace(",", ""))
                        px = float(row["Trade Price / Wght. Avg. Price"].replace(",", ""))
                    except (KeyError, ValueError):
                        continue
                    side = row.get("Buy/Sell", "").upper()
                    rec = {"date": d, "kind": kind, "symbol": row.get("Symbol", ""), "name": row.get("Security Name", ""),
                           "client": row.get("Client Name", ""), "side": side, "qty": qty, "price": px, "value": qty * px}
                    store["|".join([d, kind, rec["symbol"], rec["client"], side, "%.0f" % qty, "%.2f" % px])] = rec
            except Exception:  # noqa: BLE001
                failed.append(kind)
        cutoff = (now_ist().date() - timedelta(days=days)).isoformat()
        store = {k: v for k, v in store.items() if v["date"] >= cutoff}
        if len(store) != before:
            os.makedirs(DATA, exist_ok=True)
            with open(path + ".tmp", "w", encoding="utf-8") as f:
                json.dump(store, f)
            os.replace(path + ".tmp", path)
    rows = sorted(store.values(), key=lambda r: (r["date"], r["value"]), reverse=True)
    for r in rows:
        r["nifty"] = r["symbol"] in NIFTY
    if sym:
        rows = [r for r in rows if r["symbol"] == sym]
    dates = sorted({r["date"] for r in store.values()})
    return {"rows": rows[:500], "symbol": sym, "failed": failed, "days_stored": len(dates),
            "from": dates[0] if dates else None, "to": dates[-1] if dates else None,
            "source": "NSE bulk and block deal files",
            "links": [
                {"label": "Insider trades (promoters, directors)", "url": "https://www.nseindia.com/companies-listing/corporate-filings-insider-trading"},
                {"label": "Promoter share pledges", "url": "https://www.nseindia.com/companies-listing/corporate-filings-pledged-data"},
                {"label": "FII / DII daily flows", "url": "https://www.nseindia.com/reports/fii-dii"},
                {"label": "Shareholding patterns", "url": "https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern"},
                {"label": "Bulk and block deal history", "url": "https://www.nseindia.com/report-detail/display-bulk-and-block-deals"}]}


# ----------------------------------------------------------------- budget + risk
def size_position(entry, stop, settings):
    """trader-budget: whole shares that fit both the budget and the max loss."""
    risk = entry - stop
    if risk <= 0 or entry <= 0:
        return {"qty": 0, "cost": 0, "max_loss": 0, "reward": 0, "limited_by": "invalid plan"}
    by_loss = math.floor(settings["max_loss"] / risk)
    by_budget = math.floor(settings["budget"] / entry)
    qty = max(0, min(by_loss, by_budget))
    return {"qty": qty, "cost": qty * entry, "max_loss": qty * risk, "reward": qty * risk * 2,
            "limited_by": "max loss" if by_loss <= by_budget else "budget"}


def risk_check(sym, qty, entry, stop, st):
    """trader-risk: PASS or BLOCK against the user's own limits."""
    s, paper = st["settings"], st["paper"]
    clk = market_clock()
    today = clk["date"]
    risk_amt = qty * (entry - stop)
    realised = sum(t["pnl"] for t in paper["trades"] if t.get("closed_date") == today)
    open_risk = sum(p["qty"] * max(p["entry"] - p["stop"], 0) for p in paper["positions"])
    worst_day = -min(realised, 0) + open_risk + risk_amt
    count = (sum(1 for p in paper["positions"] if p.get("opened_date") == today)
             + sum(1 for t in paper["trades"] if t.get("opened_date") == today))
    a, b = parse_hm(s["entry_start"], 570), parse_hm(s["entry_end"], 870)
    in_window = clk["open"] and a <= clk["minute"] <= b
    checks = [
        {"name": "Position size", "ok": qty >= 1,
         "detail": "%d shares" % qty if qty >= 1 else "Budget or max loss is too small for even 1 share"},
        {"name": "Max loss per trade", "ok": qty >= 1 and risk_amt <= s["max_loss"] + 0.01,
         "detail": "Risk Rs %.0f vs limit Rs %.0f" % (risk_amt, s["max_loss"])},
        {"name": "Daily loss limit", "ok": worst_day <= s["daily_loss"] + 0.01,
         "detail": "Worst case today Rs %.0f vs limit Rs %.0f" % (worst_day, s["daily_loss"])},
        {"name": "Trade count", "ok": count < s["max_trades"],
         "detail": "%d of %d trades used today" % (count, s["max_trades"])},
        {"name": "Entry window", "ok": in_window,
         "detail": ("Inside %s-%s IST" % (s["entry_start"], s["entry_end"])) if in_window
         else ("Market is %s; entries allowed %s-%s IST" % (clk["label"].lower(), s["entry_start"], s["entry_end"]))},
        {"name": "Cash available", "ok": qty * entry <= paper["cash"] + 0.01,
         "detail": "Needs Rs %.0f, paper cash Rs %.0f" % (qty * entry, paper["cash"])},
        {"name": "No duplicate position", "ok": all(p["symbol"] != sym for p in paper["positions"]),
         "detail": "Already holding %s" % sym if any(p["symbol"] == sym for p in paper["positions"])
         else "No open position in %s" % sym},
    ]
    return {"verdict": "PASS" if all(c["ok"] for c in checks) else "BLOCK", "checks": checks}


# ----------------------------------------------------------------- scanner
_scan_cache = {"t": 0, "data": None}
_scan_lock = threading.Lock()


def clean_symbol(s):
    s = (s or "").strip().upper()
    if s.endswith(".NS"):
        s = s[:-3]
    if not re.fullmatch(r"[A-Z0-9&\-]{1,20}", s):
        raise ApiError(400, "Enter an NSE symbol such as RELIANCE or TCS")
    return s


def session_context(sess):
    """Pick the session to analyse and say whether it is live."""
    clk = market_clock()
    if not sess:
        return None, [], False, clk
    day = list(sess)[-1]
    live = clk["open"] and day == clk["date"]
    return day, sess[day], live, clk


def scan_one(sym):
    try:
        dmeta, daily = chart(sym, "1y", "1d", 300)
        try:
            imeta, intra = chart(sym, "5d", "5m", 20)   # Scalping scan
        except Exception:  # noqa: BLE001
            imeta, intra = {}, []
        eod = dmeta.get("source") in EOD_LABEL
        if eod or not intra:
            imeta = {"regularMarketPrice": daily[-1]["c"], "previousClose": daily[-2]["c"] if len(daily) > 1 else None}
        sess = sessions(intra)
        day, sb, live, clk = session_context(sess)
        price = imeta.get("regularMarketPrice") or (daily[-1]["c"] if daily else None)
        prev = imeta.get("previousClose") or (daily[-2]["c"] if len(daily) > 1 else None)
        dv = daily_view(daily, live)
        cutoff = parse_hm(load_state()["settings"]["entry_end"], 870)
        plan = orb_plan(sb, cutoff, time.time() if live else None) if sb else None
        orb = {"state": "none"}
        if plan:
            orb = {"state": plan["state"], "or_high": plan["or_high"], "entry": plan["entry"],
                   "time": hm(plan["entry_m"]) if plan["entry_m"] else None, "outcome": plan["outcome"]}
        rank = 0
        ids = [s["id"] for s in dv["setups"]]
        rank += 30 if "breakout" in ids else 12 if "near" in ids else 0
        rank += 25 if "flag" in ids else 0
        rank += 20 if "bounce" in ids else 0
        rank += 25 if (plan and plan["state"] == "confirmed" and plan["outcome"] in ("open", "target")) else 0
        rank += 10 if dv["trend_up"] else 0
        rank += 10 if (dv["rvol"] or 0) >= 1.2 else 0
        return {"symbol": sym, "name": NAMES.get(sym, sym), "nifty50": sym in NIFTY,
                "industry": UNIVERSE.get(sym, {}).get("industry", ""), "price": price, "prev_close": prev,
                "change_pct": (price / prev - 1) * 100 if price and prev else None,
                "setups": dv["setups"], "trend_up": dv["trend_up"], "rsi": dv["rsi"], "rvol": dv["rvol"],
                "orb": orb, "rank": min(rank, 100), "session": day, "live": live,
                "source": EOD_LABEL[dmeta["source"]][:-5] if eod else "Yahoo"}
    except Exception as e:  # noqa: BLE001
        return {"symbol": sym, "name": NAMES.get(sym, sym), "error": str(e)[:120]}


def scan(refresh=False):
    with _scan_lock:
        if not refresh and _scan_cache["data"] and time.time() - _scan_cache["t"] < 180:
            return _scan_cache["data"]
        with ThreadPoolExecutor(12) as ex:
            rows = list(ex.map(scan_one, list(NAMES)))
        ok = sorted([r for r in rows if "error" not in r], key=lambda r: (-r["rank"], r["symbol"]))
        data = {"rows": ok, "failed": [r for r in rows if "error" in r], "clock": market_clock(),
                "scanned_at": now_ist().strftime("%H:%M:%S"), "universe": "Nifty LargeMidcap 250"}
        _scan_cache.update(t=time.time(), data=data)
        return data


# ----------------------------------------------------------------- predictor
def predict(sym):
    st = load_state()
    s = st["settings"]
    with ThreadPoolExecutor(4) as ex:
        f_daily = ex.submit(chart, sym, "1y", "1d", 300)
        f_intra = ex.submit(chart, sym, "60d", "5m", 60)
        f_earn = ex.submit(earnings, sym)
        try:
            dmeta, daily = f_daily.result()
        except Exception:  # noqa: BLE001
            raise ApiError(404, "No price data for %s on Yahoo Finance, NSE or BSE. Check the symbol." % sym)
        try:
            imeta, intra = f_intra.result()
        except Exception:  # noqa: BLE001
            imeta, intra = {}, []
        # Scalping speed: 60 days of bars are cached for a minute, but today's bars and the
        # price are re-read every few seconds and laid over them.
        try:
            fmeta, fresh = chart(sym, "1d", "5m", 8)
            if fresh:
                intra = [b for b in intra if b["t"] < fresh[0]["t"]] + fresh
                imeta = dict(imeta, **{k: v for k, v in fmeta.items() if k in ("regularMarketPrice", "regularMarketTime")})
        except Exception:  # noqa: BLE001
            pass
        eod = dmeta.get("source") in EOD_LABEL
        if eod or not intra:
            intra = []
            imeta = {"regularMarketPrice": daily[-1]["c"], "previousClose": daily[-2]["c"] if len(daily) > 1 else None}
        name = NAMES.get(sym) or re.sub(r"\s+(Limited|Ltd\.?)$", "", imeta.get("longName") or sym, flags=re.I)
        f_news = ex.submit(news, sym, name)
        try:
            earn = f_earn.result()
        except Exception:  # noqa: BLE001
            earn = None
        try:
            nws = f_news.result()
        except Exception:  # noqa: BLE001
            nws = None

    sess = sessions(intra)
    day, sb, live, clk = session_context(sess)
    price = imeta.get("regularMarketPrice") or (daily[-1]["c"] if daily else 0)
    prev = imeta.get("previousClose") or (daily[-2]["c"] if len(daily) > 1 else None)
    change = (price / prev - 1) * 100 if prev else None
    dv = daily_view(daily, live)
    cutoff = parse_hm(s["entry_end"], 870)
    plan = orb_plan(sb, cutoff, time.time() if live else None) if sb else None
    checks = []

    def add(cid, skill, title, status, pts, mx, detail):
        checks.append({"id": cid, "skill": skill, "title": title, "status": status,
                       "points": pts, "max": mx, "detail": detail})

    # 1 setup -------------------------------------------------------------
    ids = [x["id"] for x in dv["setups"]]
    pts = 15 if any(i in ids for i in ("breakout", "flag", "bounce")) else 8 if "near" in ids else 0
    pts += 5 if dv["trend_up"] else 0
    pts += 5 if (dv["rvol"] or 0) >= 1.2 else 0
    bits = [x["label"] for x in dv["setups"]] or ["No daily chart setup"]
    bits.append("uptrend (above 50-day average)" if dv["trend_up"] else "not in an uptrend")
    if dv["rvol"] is not None:
        bits.append("volume %.1fx its 20-day average" % dv["rvol"])
    add("setup", "scanner + nse-scanner", "Chart setup", "pass" if pts >= 15 else "warn" if pts >= 5 else "fail",
        pts, 25, "; ".join(bits) + ".")

    # 2 entry -------------------------------------------------------------
    entry_ok = False
    day_label = datetime.strptime(day, "%Y-%m-%d").strftime("%d %b") if day else "-"
    if not plan:
        add("entry", "entry", "Entry confirmation", "fail", 0, 15,
            "No 5-minute bars are available for this stock, so an intraday entry cannot be confirmed.")
    elif not live:
        if plan["state"] == "confirmed":
            res = {"target": "target hit at %s" % hm(plan["exit_m"] or 0), "stop": "stopped out at %s" % hm(plan["exit_m"] or 0),
                   "open": "held to square-off for %+.1fR" % (plan["r"] or 0)}[plan["outcome"]]
            d = "Market is closed. In the %s session the breakout confirmed at %s and %s." % (day_label, hm(plan["entry_m"]), res)
        else:
            d = "Market is closed. In the %s session price never closed above the opening range high." % day_label
        add("entry", "entry", "Entry confirmation", "fail", 0, 15, d + " Come back after 09:30 IST on a trading day.")
    elif not plan["or_complete"]:
        add("entry", "entry", "Entry confirmation", "warn", 0, 15, "Opening range (09:15-09:30) is still forming.")
    elif plan["state"] == "waiting":
        late = clk["minute"] > cutoff
        add("entry", "entry", "Entry confirmation", "fail" if late else "warn", 0 if late else 5, 15,
            ("Entry window has passed with no breakout." if late else
             "Waiting: no completed 5-minute close above the opening range high %.2f yet." % plan["or_high"]))
    elif plan["outcome"] != "open":
        add("entry", "entry", "Entry confirmation", "fail", 0, 15,
            "Breakout confirmed at %s but the trade has already %s. Do not chase."
            % (hm(plan["entry_m"]), "hit its target" if plan["outcome"] == "target" else "hit its stop"))
    else:
        ext = (price - plan["entry"]) / plan["risk"] if plan["risk"] else 9
        if ext <= 0.5 and price > plan["stop"]:
            entry_ok = True
            add("entry", "entry", "Entry confirmation", "pass", 15, 15,
                "Confirmed: 5-minute close above the opening range at %s. Price is %.1fR from the entry." % (hm(plan["entry_m"]), ext))
        else:
            add("entry", "entry", "Entry confirmation", "warn", 8, 15,
                "Confirmed at %s but price has already run %.1fR past the entry. Late entries carry worse odds." % (hm(plan["entry_m"]), ext))

    # trade plan numbers ---------------------------------------------------
    tp = None
    if plan and plan["or_complete"]:
        entry = plan["entry"] if plan["state"] == "confirmed" else plan["or_high"] + 0.05
        stop = plan["or_mid"]
        risk = entry - stop
        tp = {"entry": entry, "stop": stop, "target": entry + 2 * risk, "risk": risk,
              "risk_pct": risk / entry * 100 if entry else 0, "state": plan["state"],
              "or_high": plan["or_high"], "or_low": plan["or_low"], "outcome": plan["outcome"],
              "entry_time": hm(plan["entry_m"]) if plan["entry_m"] else None,
              "trigger": plan["state"] != "confirmed"}

    # 3 exit --------------------------------------------------------------
    exit_ok = False
    if not tp:
        add("exit", "exit", "Stop and target", "fail", 0, 10, "No opening range yet, so no stop or target can be set.")
    else:
        rp = tp["risk_pct"]
        if rp < 0.15:
            add("exit", "exit", "Stop and target", "fail", 0, 10,
                "Plan refused: the stop is only %.2f%% from entry, inside normal noise." % rp)
        elif rp > 2.5:
            add("exit", "exit", "Stop and target", "fail", 0, 10,
                "Plan refused: the stop is %.1f%% from entry, too wide for a day trade." % rp)
        elif dv["atr"] and 2 * tp["risk"] > 1.2 * dv["atr"]:
            exit_ok = True
            add("exit", "exit", "Stop and target", "warn", 6, 10,
                "Stop %.2f (range midpoint), target %.2f (2R). The target needs a move bigger than a typical day's range."
                % (tp["stop"], tp["target"]))
        else:
            exit_ok = True
            add("exit", "exit", "Stop and target", "pass", 10, 10,
                "Stop %.2f at the opening-range midpoint (%.2f%% risk), target %.2f at 2R." % (tp["stop"], rp, tp["target"]))

    # 4 odds --------------------------------------------------------------
    odds, hist = None, None
    if tp and tp["risk"] > 0:
        start_m = plan["entry_m"] if plan["state"] == "confirmed" else (max(clk["minute"], 575) if live else 575)
        steps = max(1, (SQUARE_M - start_m) // 5)
        seed = "%s|%s|%.2f|%.2f|%d" % (sym, day, tp["entry"], tp["stop"], steps)
        odds = monte_carlo({k: v for k, v in sess.items() if k != day}, tp["entry"], tp["stop"],
                           tp["target"], steps, seed, cutoff)
        w = l = t = n = 0
        rs = 0.0
        for d0, bars0 in sess.items():
            if d0 == day:
                continue
            hp = orb_plan(bars0, cutoff)
            if hp and hp["state"] == "confirmed":
                n += 1
                rs += hp["r"]
                w += hp["outcome"] == "target"
                l += hp["outcome"] == "stop"
                t += hp["outcome"] == "open"
        hist = {"sessions": len(sess) - 1, "trades": n, "wins": w, "losses": l, "timeouts": t,
                "avg_r": rs / n if n else None}
    if odds:
        ev = odds["ev_r"]
        past = hist["avg_r"] if hist and hist["trades"] >= 5 else None
        pts = int(round(12 * max(0.0, min(1.0, ev / 0.3)) + 8 * max(0.0, min(1.0, (past or 0) / 0.3))))
        d = ("Target first %.0f%%, stop first %.0f%%, neither %.0f%%: expected %+.2fR per trade."
             % (odds["p_target"] * 100, odds["p_stop"] * 100, odds["p_timeout"] * 100, ev))
        if past is not None:
            d += " The same plan on the last %d sessions triggered %d times and averaged %+.2fR." % (
                hist["sessions"], hist["trades"], past)
        add("odds", "timemachine", "Odds from 10,000 replays", "pass" if pts >= 12 else "warn" if pts >= 4 else "fail", pts, 20, d)
    else:
        add("odds", "timemachine", "Odds from 10,000 replays", "fail", 0, 20, "Not enough 5-minute history or no valid plan to replay.")

    # 5 size + 6 risk -----------------------------------------------------
    size, risk = None, None
    if tp:
        size = size_position(tp["entry"], tp["stop"], s)
        add("size", "budget", "Position size", "pass" if size["qty"] >= 1 else "fail", 5 if size["qty"] >= 1 else 0, 5,
            ("%d shares for Rs %s, risking Rs %s (limited by %s)."
             % (size["qty"], f"{size['cost']:,.0f}", f"{size['max_loss']:,.0f}", size["limited_by"]))
            if size["qty"] >= 1 else "Your budget or max loss does not cover a single share at this stop distance.")
        risk = risk_check(sym, size["qty"], tp["entry"], tp["stop"], st)
        fails = [c["name"] + ": " + c["detail"] for c in risk["checks"] if not c["ok"]]
        add("risk", "risk", "Risk limits", "pass" if risk["verdict"] == "PASS" else "fail",
            10 if risk["verdict"] == "PASS" else 0, 10,
            "PASS: all %d limits respected." % len(risk["checks"]) if not fails else "BLOCK. " + " | ".join(fails))
    else:
        add("size", "budget", "Position size", "fail", 0, 5, "Needs a trade plan first.")
        add("risk", "risk", "Risk limits", "fail", 0, 10, "Needs a trade plan first.")

    # 7 news --------------------------------------------------------------
    if nws is None:
        add("news", "news", "News check", "na", 0, 0, "Headlines unavailable right now; not counted in the score.")
    else:
        fresh = [i for i in nws["items"] if i["ts"] >= time.time() - 86400]
        flagged = [i for i in fresh if i["caution"]]
        bad_move = change is not None and change <= -2
        ok = not flagged and not bad_move
        d = "%d headline%s in the last 24h" % (len(fresh), "" if len(fresh) == 1 else "s")
        d += ", none with caution words" if not flagged else ", %d with caution words (%s)" % (
            len(flagged), ", ".join(sorted({w for i in flagged for w in i["caution"]})))
        if change is not None:
            d += ". Price is %+.2f%% from yesterday's close." % change
        add("news", "news", "News check", "pass" if ok else "warn", 5 if ok else 2, 5, d)

    # 8 earnings ----------------------------------------------------------
    if earn is None or not earn.get("compare"):
        add("earnings", "analyst", "Latest earnings", "na", 0, 0, "No reported quarterly figures found; not counted in the score.")
    elif (datetime.now() - datetime.strptime(earn["latest"]["date"], "%Y-%m-%d")).days > 200:
        add("earnings", "analyst", "Latest earnings", "na", 0, 0,
            "The newest quarter the free source has is %s, which is out of date; not counted in the score." % earn["latest"]["date"])
    else:
        c = earn["compare"]
        pts = (4 if (c["revenue"] or 0) > 0 else 0) + (4 if (c["net_income"] or 0) > 0 else 0) + \
              (2 if (c["margin_delta"] or 0) >= 0 else 0)

        def pc(v):
            return "n/a" if v is None else "%+.1f%%" % v
        add("earnings", "analyst", "Latest earnings", "pass" if pts >= 8 else "warn" if pts >= 4 else "fail", pts, 10,
            "Quarter ending %s, %s: revenue %s, net profit %s, net margin %s pts."
            % (earn["latest"]["date"], c["basis"], pc(c["revenue"]), pc(c["net_income"]),
               "n/a" if c["margin_delta"] is None else "%+.1f" % c["margin_delta"]))

    # 9 big deals ---------------------------------------------------------
    try:
        since = (now_ist().date() - timedelta(days=30)).isoformat()
        dl = [r for r in deals(sym)["rows"] if r["date"] >= since]
    except Exception:  # noqa: BLE001
        dl = None
    if not dl:
        add("deals", "big deals", "Bulk and block deals", "na", 0, 0,
            "No bulk or block deals on record for this stock in the last 30 days; not counted in the score."
            if dl is not None else "Deal files unavailable right now; not counted in the score.")
    else:
        buy = sum(r["value"] for r in dl if r["side"] == "BUY")
        sell = sum(r["value"] for r in dl if r["side"] == "SELL")
        net = buy - sell
        d = "%d deal%s in the last 30 days: bought Rs %.1f cr, sold Rs %.1f cr" % (
            len(dl), "" if len(dl) == 1 else "s", buy / 1e7, sell / 1e7)
        if abs(net) < 0.1 * (buy + sell):
            add("deals", "big deals", "Bulk and block deals", "na", 0, 0,
                d + ". Buying and selling roughly cancel out (often the same trader in and out), so it is not counted.")
        else:
            add("deals", "big deals", "Bulk and block deals", "pass" if net > 0 else "warn", 5 if net > 0 else 0, 5,
                d + ", net %s Rs %.1f cr." % ("buying" if net > 0 else "selling", abs(net) / 1e7))

    got, mx = sum(c["points"] for c in checks), sum(c["max"] for c in checks)
    score = int(round(100 * got / mx)) if mx else 0
    risk_pass = bool(risk and risk["verdict"] == "PASS")
    if score >= 70 and entry_ok and exit_ok and risk_pass:
        verdict, why = "qualifies", "Every gate is green: setup, confirmed entry, valid exits and risk limits."
    elif live and plan and plan["state"] == "waiting" and clk["minute"] <= cutoff and score >= 35:
        verdict, why = "wait", "The plan is ready but the entry has not triggered. Set an alert on the trigger price."
    elif not intra:
        verdict, why = "skip", ("Only end-of-day prices are available for this stock, so the entry, stop, target and "
                                "odds cannot be worked out. The score covers the daily chart, news and earnings only.")
    elif not live:
        verdict, why = "wait", "Market is closed. This is a replay of the last session; re-run it during market hours."
    elif score >= 55:
        verdict, why = "wait", "Some checks pass, but at least one gate (entry, exits or risk) is not green."
    else:
        verdict, why = "skip", "Too few checks pass for this to be a rule-based setup today."

    return {"symbol": sym, "name": name, "price": price, "prev_close": prev, "change_pct": change,
            "session": day, "live": live, "clock": clk, "intraday": bool(intra),
            "source": EOD_LABEL[dmeta["source"]] if eod else "Yahoo Finance", "asof": dmeta.get("asof"), "score": score, "points": got, "max_points": mx,
            "verdict": verdict, "why": why, "checks": checks, "plan": tp, "size": size, "risk": risk,
            "odds": odds, "history": hist, "daily": {k: dv[k] for k in ("rsi", "rvol", "atr", "sma20", "sma50", "high20", "trend_up")},
            "setups": dv["setups"], "bars": [{k: b[k] for k in ("m", "o", "h", "l", "c")} for b in sb],
            "news": nws, "earnings": earn, "settings": s}


# ----------------------------------------------------------------- quotes, alerts, paper broker
def quote(sym, ttl=30):
    meta, bars = chart(sym, "1d", "5m", ttl)
    return {"symbol": sym, "price": meta.get("regularMarketPrice"), "prev_close": meta.get("previousClose"),
            "bars": bars, "time": meta.get("regularMarketTime")}


def check_alerts():
    """trader-alerts: each alert rings once, then stays fired until re-armed."""
    with _state_lock:
        st = load_state()
        clk = market_clock()
        fired, quotes = [], {}
        for a in st["alerts"]:
            if a.get("fired_at"):
                continue
            hit, msg = False, ""
            if a["type"] == "clock":
                mark = {"open": OPEN_M, "preclose": SQUARE_M, "close": CLOSE_M}[a["level"]]
                label = {"open": "NSE market open (09:15 IST)", "preclose": "15 minutes to the close (15:15 IST)",
                         "close": "NSE market close (15:30 IST)"}[a["level"]]
                hit = now_ist().weekday() < 5 and mark <= clk["minute"] < mark + 10
                msg = label
            else:
                sym = a["symbol"]
                if sym not in quotes:
                    try:
                        quotes[sym] = quote(sym)
                    except Exception:  # noqa: BLE001
                        quotes[sym] = None
                q = quotes[sym]
                if not q or not q["price"]:
                    continue
                p, lvl = q["price"], float(a["level"])
                a["last"] = p
                if a["type"] == "above":
                    hit = p >= lvl
                    msg = "%s is at %.2f, at or above %.2f" % (sym, p, lvl)
                elif a["type"] == "below":
                    hit = p <= lvl
                    msg = "%s is at %.2f, at or below %.2f" % (sym, p, lvl)
                elif a["type"] in ("pct_up", "pct_down") and q["prev_close"]:
                    ch = (p / q["prev_close"] - 1) * 100
                    hit = ch >= lvl if a["type"] == "pct_up" else ch <= -lvl
                    msg = "%s has moved %+.2f%% from yesterday's close" % (sym, ch)
            if hit:
                a["fired_at"] = clk["ist"]
                a["message"] = (a.get("label") + ": " if a.get("label") else "") + msg
                fired.append(a)
                telegram.notify("alert", "🔔 " + a["message"])
        save_state(st)
        return {"alerts": st["alerts"], "fired": fired, "clock": clk}


def portfolio():
    """Mark the paper book to market and work the bracket exits."""
    with _state_lock:
        st = load_state()
        paper, clk = st["paper"], market_clock()
        keep = []
        for p in paper["positions"]:
            exit_px, reason, sq_px = None, None, None
            # 15:15 IST on the day the trade opened: nothing after this counts
            d = datetime.strptime(p["opened_date"], "%Y-%m-%d").replace(tzinfo=IST)
            sq_t = int((d + timedelta(minutes=SQUARE_M)).timestamp())
            try:
                q = quote(p["symbol"], 8)   # Scalping paper book
                last = q["price"] or p["entry"]
                for b in q["bars"]:
                    if b["t"] < p["opened"] or b["t"] >= sq_t:
                        continue
                    if b["l"] <= p["stop"]:
                        exit_px, reason = p["stop"], "stop"
                        break
                    if b["h"] >= p["target"]:
                        exit_px, reason = p["target"], "target"
                        break
                    sq_px = b["c"]   # close of the last bar before 15:15
            except Exception:  # noqa: BLE001
                last = p.get("last", p["entry"])
            if exit_px is None and (clk["date"] > p["opened_date"] or
                                    (clk["date"] == p["opened_date"] and clk["minute"] >= SQUARE_M)):
                exit_px, reason = (sq_px if sq_px is not None else last), "square-off"
            if exit_px is not None:
                _close(paper, p, exit_px, reason, clk)
            else:
                p["last"] = last
                p["pnl"] = (last - p["entry"]) * p["qty"]
                keep.append(p)
        paper["positions"] = keep
        # after the closes above, so sale proceeds are already back in cash
        equity = paper["cash"] + sum(p["last"] * p["qty"] for p in keep)
        save_state(st)
        today = clk["date"]
        return {"cash": paper["cash"], "equity": equity, "start_cash": paper["start_cash"],
                "positions": keep, "trades": paper["trades"][-50:][::-1],
                "day_pnl": sum(t["pnl"] for t in paper["trades"] if t.get("closed_date") == today)
                + sum(p["pnl"] for p in keep),
                "total_pnl": equity - paper["start_cash"], "clock": clk, "mode": "paper"}


def _close(paper, p, px, reason, clk):
    pnl = (px - p["entry"]) * p["qty"]
    telegram.notify("paper", "%s Paper Scalping: sold %d %s at %.2f (%s) · P&L %+.0f" % (
        "✅" if pnl >= 0 else "🔻", p["qty"], p["symbol"], px, reason, pnl))
    paper["cash"] += px * p["qty"]
    paper["trades"].append({"symbol": p["symbol"], "qty": p["qty"], "entry": p["entry"], "exit": px,
                            "stop": p["stop"], "target": p["target"], "pnl": pnl, "reason": reason,
                            "r": (px - p["entry"]) / (p["entry"] - p["stop"]) if p["entry"] > p["stop"] else 0,
                            "opened_date": p["opened_date"], "closed_date": clk["date"],
                            "closed_at": clk["ist"]})


def place_order(body):
    """trader-broker: paper only, needs a risk PASS and an explicit confirm."""
    sym = clean_symbol(body.get("symbol"))
    if body.get("confirm") is not True:
        raise ApiError(400, "Order not confirmed.")
    pr = predict(sym)
    tp = pr["plan"]
    if not tp:
        raise ApiError(409, "No trade plan for %s yet." % sym)
    with _state_lock:
        st = load_state()
        px = quote(sym, 8)["price"]   # Scalping paper fill
        if not px or px <= tp["stop"]:
            raise ApiError(409, "Price is at or below the stop; the plan is no longer valid.")
        if px >= tp["target"]:
            raise ApiError(409, "Price is already at the target; nothing left in this plan.")
        if tp["target"] - px < 1.5 * (px - tp["stop"]):
            raise ApiError(409, "Price has run too far past the entry: at %.2f the reward to the target "
                                "no longer covers 1.5x the risk to the stop. Do not chase." % px)
        size = size_position(px, tp["stop"], st["settings"])
        rc = risk_check(sym, size["qty"], px, tp["stop"], st)
        if rc["verdict"] != "PASS":
            raise ApiError(409, "Risk check BLOCK: " + "; ".join(
                c["name"] + " - " + c["detail"] for c in rc["checks"] if not c["ok"]))
        clk = market_clock()
        pos = {"id": hashlib.sha1(("%s%f" % (sym, time.time())).encode()).hexdigest()[:10], "symbol": sym,
               "qty": size["qty"], "entry": px, "stop": tp["stop"], "target": tp["target"],
               "opened": int(time.time()), "opened_date": clk["date"], "opened_at": clk["ist"], "last": px, "pnl": 0.0}
        st["paper"]["cash"] -= px * size["qty"]
        st["paper"]["positions"].append(pos)
        save_state(st)
        return {"ok": True, "position": pos, "risk": rc}


def close_position(body):
    with _state_lock:
        st = load_state()
        paper, clk = st["paper"], market_clock()
        for p in list(paper["positions"]):
            if p["id"] == body.get("id"):
                try:
                    px = quote(p["symbol"], 8)["price"] or p.get("last", p["entry"])
                except Exception:  # noqa: BLE001
                    px = p.get("last", p["entry"])
                _close(paper, p, px, "manual", clk)
                paper["positions"].remove(p)
                save_state(st)
                return {"ok": True}
        raise ApiError(404, "Position not found.")


# ----------------------------------------------------------------- http
INDICES = [("NIFTY 50", "^NSEI"), ("SENSEX", "^BSESN"), ("BANK NIFTY", "^NSEBANK"), ("FIN NIFTY", "NIFTY_FIN_SERVICE.NS"),
           ("NIFTY IT", "^CNXIT"), ("MIDCAP 100", "NIFTY_MIDCAP_100.NS"), ("SMALLCAP 100", "^CNXSC"),
           ("NIFTY AUTO", "^CNXAUTO"), ("NIFTY PHARMA", "^CNXPHARMA"), ("INDIA VIX", "^INDIAVIX")]


WORLD = [  # only markets that move the Nifty: US cues (futures trade during Indian hours), Asia, oil, rupee, dollar, US yields
    ("S&P 500 FUT", "ES=F"), ("NASDAQ FUT", "NQ=F"), ("DOW JONES", "^DJI"), ("NIKKEI", "^N225"), ("HANG SENG", "^HSI"),
    ("KOSPI", "^KS11"), ("BRENT CRUDE $", "BZ=F"), ("USD/INR", "INR=X"), ("DOLLAR INDEX", "DX-Y.NYB"),
    ("US 10Y YIELD %", "^TNX"), ("GOLD $", "GC=F")]


def indices():
    """Index levels for the scrolling strip (free Yahoo quotes, cached 60 s)."""
    def one(item):
        name, ys = item
        try:
            m = json.loads(fetch("https://query1.finance.yahoo.com/v8/finance/chart/%s?range=1d&interval=5m"
                                 % urllib.parse.quote(ys, safe=""), 60))["chart"]["result"][0]["meta"]
            px, prev = m.get("regularMarketPrice"), m.get("chartPreviousClose") or m.get("previousClose")
            return {"name": name, "price": px, "change": px - prev if px and prev else None,
                    "pct": (px / prev - 1) * 100 if px and prev else None}
        except Exception:  # noqa: BLE001
            return None
    stocks = [(k, k + ".NS") for k in sorted(NIFTY)]
    with ThreadPoolExecutor(16) as ex:
        rows = [r for r in ex.map(one, INDICES) if r and r["price"]]
        world = [r for r in ex.map(one, WORLD) if r and r["price"]]
        n50 = [r for r in ex.map(one, stocks) if r and r["price"]]
    return {"rows": rows, "nifty50": n50, "world": world, "clock": market_clock()}


def candles(sym, tf):
    """Chart candles at other timeframes: 3h (last ~1 year), 1w / 1m / 6m (up to 10 years)."""
    if tf == "3h":
        meta, bars = chart(sym, "1y", "60m", 300)
        groups = {}
        for b in bars:
            dt = datetime.fromtimestamp(b["t"], IST)
            blk = 0 if dt.hour * 60 + dt.minute < 735 else 1      # 09:15-12:15 and 12:15-15:30
            groups.setdefault((dt.date().isoformat(), blk), []).append(b)
        keys = sorted(groups)
        label = lambda k: "%s %s" % (k[0], "09:15-12:15" if k[1] == 0 else "12:15-15:30")  # noqa: E731
    else:
        rows = longterm.history(sym)["bars"]
        groups = {}
        for d, o, h, l, c, v in rows:
            y, m = int(d[:4]), int(d[5:7])
            if tf == "1w":
                iso = date.fromisoformat(d).isocalendar()
                k = (iso[0], iso[1])
            elif tf == "1m":
                k = (y, m)
            elif tf == "6m":
                k = (y, 1 if m <= 6 else 2)
            else:
                raise ApiError(400, "Unknown timeframe")
            groups.setdefault(k, []).append({"t": d, "o": o, "h": h, "l": l, "c": c, "v": v})
        keys = sorted(groups)
        label = None
    out = []
    for k in keys:
        g = groups[k]
        first = g[0]["t"]
        d = datetime.fromtimestamp(first, IST).date().isoformat() if isinstance(first, (int, float)) else first
        last = g[-1]["t"]
        de = datetime.fromtimestamp(last, IST).date().isoformat() if isinstance(last, (int, float)) else last
        out.append({"d": d, "de": de, "tl": label(k) if label else None, "o": g[0]["o"], "h": max(x["h"] for x in g),
                    "l": min(x["l"] for x in g), "c": g[-1]["c"], "v": sum(x["v"] or 0 for x in g)})
    cl = [b["c"] for b in out]
    vo = [b["v"] for b in out]
    for i, b in enumerate(out):
        b["s50"] = sum(cl[i - 49:i + 1]) / 50 if i >= 49 else None
        b["s200"] = sum(cl[i - 199:i + 1]) / 200 if i >= 199 else None
        b["va"] = sum(vo[i - 49:i + 1]) / 50 if i >= 49 else None
    try:
        longterm.add_overlays(out, "invest")
    except Exception:  # noqa: BLE001
        pass
    if tf == "3h":
        out = out[-500:]
    if out and out[0].get("rs"):
        b0 = out[0]["rs"]
        for b in out:
            if b.get("rs"):
                b["rs"] = b["rs"] / b0 * 100
    try:
        res = longterm.results_marks(earnings(sym))
    except Exception:  # noqa: BLE001
        res = []
    return {"symbol": sym, "tf": tf, "bars": out, "results": res}


def api(method, path, q, body):
    mode = q.get("mode") or (body or {}).get("mode") or "intraday"
    if mode not in longterm.LABEL:
        raise ApiError(400, "Unknown mode")
    long_mode = mode != "intraday"
    if path == "/api/status":
        st = load_state()
        return {"clock": market_clock(), "settings": st["settings"],
                "modes": {m: longterm.settings_for(m, st) for m in ("swing", "invest")}, "labels": longterm.LABEL,
                "universe": [{"symbol": k, "name": NAMES[k], "nifty50": k in NIFTY,
                              "industry": UNIVERSE[k].get("industry", "")} for k in sorted(NAMES)]}
    if path == "/api/settings" and method == "POST":
        with _state_lock:
            st = load_state()
            s = st["settings"]
            for k in ("budget", "max_loss", "daily_loss"):
                if k in body:
                    v = float(body[k])
                    if not 0 < v < 1e9:
                        raise ApiError(400, "%s must be a positive amount" % k)
                    s[k] = v
            if "max_trades" in body:
                s["max_trades"] = max(1, min(50, int(body["max_trades"])))
            for k in ("entry_start", "entry_end"):
                if k in body and re.fullmatch(r"\d\d:\d\d", str(body[k])):
                    s[k] = body[k]
            if "watchlist" in body:
                s["watchlist"] = [clean_symbol(x) for x in body["watchlist"] if str(x).strip()][:15]
            ms = body.get("mode_settings")
            if isinstance(ms, dict):
                for m, vals in ms.items():
                    if m not in longterm.DEFAULTS or not isinstance(vals, dict):
                        raise ApiError(400, "Unknown mode")
                    cur = s.setdefault("modes", {}).setdefault(m, {})
                    for k, v in vals.items():
                        if k not in longterm.DEFAULTS[m]:
                            continue
                        v = float(v)
                        if not 0 < v < 1e10:
                            raise ApiError(400, "%s must be positive" % k.replace("_", " "))
                        cur[k] = int(v) if k in ("max_positions", "max_per_sector") else v
            if "paper_cash" in body:
                v = float(body["paper_cash"])
                if not 0 < v < 1e10:
                    raise ApiError(400, "Paper cash must be positive")
                if long_mode:
                    save_state(st)
                    longterm.reset_paper(mode, v)
                    return {"settings": load_state()["settings"]}
                st["paper"] = {"cash": v, "start_cash": v, "positions": [], "trades": []}
            save_state(st)
            return {"settings": s}
    if path == "/api/scan":
        return longterm.scan_long(mode, q.get("refresh") == "1") if long_mode else scan(q.get("refresh") == "1")
    if path == "/api/predict":
        if long_mode:
            return longterm.analyze(clean_symbol(q.get("symbol")), mode)
        out = predict(clean_symbol(q.get("symbol")))
        out.update(mode="intraday", mode_label=longterm.LABEL["intraday"])
        return out
    if path == "/api/backtest":
        if not long_mode:
            raise ApiError(400, "The portfolio backtest is for Trading and Investing modes.")
        return longterm.portfolio_backtest(mode, q.get("refresh") == "1")
    if path == "/api/journal":
        if not long_mode:
            raise ApiError(400, "The forward test is for Trading and Investing modes.")
        return longterm.journal(mode)
    if path == "/api/notify_log":
        return reports.history(int(q.get("limit") or 500), q.get("kind") or None)
    if path == "/api/reports/run" and method == "POST":
        kind = body.get("kind")
        if kind not in reports.BUILDERS:
            raise ApiError(400, "Unknown report")
        text = reports.run(kind)
        return {"ok": text is not None, "text": text}
    if path == "/api/settings/holidays" and method == "POST":
        days = [d.strip() for d in str(body.get("holidays") or "").replace("\n", ",").split(",") if d.strip()]
        for d in days:
            if not re.fullmatch(r"\d{4}-\d\d-\d\d", d):
                raise ApiError(400, "Use dates like 2026-12-25, separated by commas.")
        with _state_lock:
            st = load_state()
            st["settings"]["holidays"] = sorted(set(days))
            save_state(st)
        return {"holidays": st["settings"]["holidays"]}
    if path == "/api/telegram":
        return telegram.status()
    if path == "/api/telegram/connect" and method == "POST":
        return telegram.connect()
    if path == "/api/telegram/test" and method == "POST":
        return telegram.test()
    if path == "/api/telegram/settings" and method == "POST":
        return telegram.set_on(body.get("on") or {})
    if path == "/api/telegram/disconnect" and method == "POST":
        return telegram.disconnect()
    if path == "/api/quote":
        sym = clean_symbol(q.get("symbol"))
        qt = quote(sym)
        if not qt["price"]:
            raise ApiError(404, "No price for %s" % sym)
        return {"symbol": sym, "price": qt["price"], "prev_close": qt["prev_close"], "live": market_clock()["open"],
                "pct": (qt["price"] / qt["prev_close"] - 1) * 100 if qt["prev_close"] else None}
    if path == "/api/candles":
        return candles(clean_symbol(q.get("symbol")), q.get("tf") or "1w")
    if path == "/api/indices":
        return indices()
    if path == "/api/earnings":
        return earnings(clean_symbol(q.get("symbol")))
    if path == "/api/news":
        st = load_state()
        if q.get("symbol"):
            syms = [clean_symbol(q["symbol"])]
        elif q.get("holdings") == "1":
            syms = [x for x in kite.held()["symbols"] if re.fullmatch(r"[A-Z0-9&\-]{1,20}", x)][:30]
        else:
            syms = st["settings"]["watchlist"]

        def one_news(sym):
            row = {"symbol": sym, "name": NAMES.get(sym, sym), "items": [], "error": None}
            try:
                row.update(news(sym))
            except Exception as e:  # noqa: BLE001
                row["error"] = "Headlines unavailable (%s)" % str(e)[:60]
            try:
                qt = quote(sym)
                row["price"] = qt["price"]
                row["change_pct"] = (qt["price"] / qt["prev_close"] - 1) * 100 if qt["prev_close"] else None
            except Exception:  # noqa: BLE001
                row["price"] = row["change_pct"] = None
            return row
        with ThreadPoolExecutor(8) as ex:
            out = list(ex.map(one_news, syms))
        return {"watch": out}
    if path == "/api/news/seen" and method == "POST":
        with _state_lock:
            st = load_state()
            st["seen_news"] = (st["seen_news"] + [str(i)[:16] for i in body.get("ids", [])])[-3000:]
            save_state(st)
        return {"ok": True}
    if path == "/api/deals":
        return deals(clean_symbol(q["symbol"]) if q.get("symbol") else None)
    if path == "/api/alerts" and method == "GET":
        return check_alerts()
    if path == "/api/alerts" and method == "POST":
        with _state_lock:
            st = load_state()
            made = []
            for a in body.get("alerts", []):
                t = a.get("type")
                if t == "clock":
                    if a.get("level") not in ("open", "preclose", "close"):
                        raise ApiError(400, "Unknown clock alert")
                    new = {"type": "clock", "symbol": None, "level": a["level"]}
                elif t in ("above", "below", "pct_up", "pct_down"):
                    lvl = float(a.get("level") or 0)
                    if lvl <= 0:
                        raise ApiError(400, "Alert level must be greater than zero")
                    new = {"type": t, "symbol": clean_symbol(a.get("symbol")), "level": lvl}
                else:
                    raise ApiError(400, "Unknown alert type")
                new["label"] = str(a.get("label") or "")[:40]
                new["id"] = hashlib.sha1(("%s%f%d" % (json.dumps(new), time.time(), len(made))).encode()).hexdigest()[:10]
                new["fired_at"] = None
                made.append(new)
            st["alerts"] = (st["alerts"] + made)[-100:]
            save_state(st)
        return {"ok": True, "created": len(made)}
    if path == "/api/alerts/delete" and method == "POST":
        with _state_lock:
            st = load_state()
            st["alerts"] = [a for a in st["alerts"] if a["id"] != body.get("id")]
            save_state(st)
        return {"ok": True}
    if path == "/api/alerts/rearm" and method == "POST":
        with _state_lock:
            st = load_state()
            for a in st["alerts"]:
                if a["id"] == body.get("id"):
                    a["fired_at"] = None
            save_state(st)
        return {"ok": True}
    if path == "/api/portfolio":
        try:
            gtt.check(mode)
        except Exception:  # noqa: BLE001
            pass
        return longterm.portfolio_long(mode) if long_mode else dict(portfolio(), mode="intraday")
    if path == "/api/orders" and method == "POST":
        if long_mode:
            return longterm.place_long(mode, clean_symbol(body.get("symbol")), body.get("confirm"))
        return place_order(body)
    if path == "/api/orders/close" and method == "POST":
        return longterm.close_long(mode, body.get("id")) if long_mode else close_position(body)
    if path == "/api/kite/connect" and method == "POST":
        return kite.connect_url()
    if path == "/api/kite/disconnect" and method == "POST":
        return kite.disconnect()
    if path == "/api/kite/holdings":
        return kite.holdings(mode)
    if path == "/api/kite/held":
        return kite.held()
    if path == "/api/kite/extras":
        return kite.extras()
    if path == "/api/gtt" and method == "GET":
        return gtt.listing(mode)
    if path == "/api/gtt" and method == "POST":
        return gtt.place(mode, body)
    if path == "/api/gtt/cancel" and method == "POST":
        return gtt.cancel(body.get("id"))
    raise ApiError(404, "Unknown endpoint")


import longterm  # noqa: E402  (Trading + Investing engines)
longterm.S = sys.modules[__name__]
import gtt  # noqa: E402  (paper GTT orders, all modes)
gtt.S, gtt.L = sys.modules[__name__], longterm
import kite  # noqa: E402  (read-only Zerodha link via the free Kite MCP server)
kite.S, kite.L = sys.modules[__name__], longterm
import telegram  # noqa: E402  (send-only notifications)
telegram.S, telegram.L, telegram.K, telegram.G = sys.modules[__name__], longterm, kite, gtt
import reports  # noqa: E402  (scheduled reports + notification history)
reports.S, reports.L, reports.K, reports.T = sys.modules[__name__], longterm, kite, telegram
telegram.R = reports

MIME = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8", ".svg": "image/svg+xml", ".json": "application/json"}


class Handler(BaseHTTPRequestHandler):
    server_version = "Tradeskill/1.0"

    def log_message(self, *a):  # quiet
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _local(self):
        if not LOOPBACK:
            return True   # network mode: protected by the password instead
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost", "[::1]")

    def _authed(self):
        if not PASSWORD:
            return True
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "ts_auth" and hmac.compare_digest(v, _auth_token()):
                return True
        return False

    def _login_page(self, msg=""):
        page = ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
                "<title>Tradeskill · sign in</title><body style='font:15px system-ui;background:#f3f4f7;display:grid;place-items:center;min-height:90vh;margin:0'>"
                "<form method=post action=/login style='background:#fff;padding:28px;border-radius:12px;box-shadow:0 4px 20px #0001;width:min(320px,90vw)'>"
                "<h2 style='margin:0 0 6px'>Tradeskill</h2><p style='color:#667085;margin:0 0 16px'>Enter the portal password.</p>"
                "<input type=password name=password autofocus required style='width:100%%;box-sizing:border-box;padding:10px;font-size:15px;border:1px solid #d0d5dd;border-radius:8px'>"
                "<p style='color:#d43a4c;min-height:1em'>%s</p><button style='width:100%%;padding:10px;border:0;border-radius:8px;background:#2f5bea;color:#fff;font-size:15px'>Sign in</button></form>"
                % html.escape(msg))
        self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")

    def _same_origin(self):
        origin = self.headers.get("Origin")
        if not origin:
            return True
        o = urllib.parse.urlparse(origin)
        if LOOPBACK:
            return o.hostname in ("127.0.0.1", "localhost")
        # behind DSM's HTTPS reverse proxy the Host header may lose its port: compare host names
        host = (self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or "").split(",")[0].strip()
        return (o.hostname or "") == host.rsplit(":", 1)[0].strip("[]")

    def _api(self, method, path, q, body):
        try:
            self._send(200, api(method, path, q, body or {}))
        except ApiError as e:
            self._send(e.code, {"error": e.msg})
        except Exception as e:  # noqa: BLE001
            self._send(500, {"error": "%s: %s" % (type(e).__name__, str(e)[:200])})

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if not self._local():
            return self._send(403, {"error": "local access only"})
        if u.path == "/login":
            return self._login_page()
        if not self._authed():
            if u.path.startswith("/api/"):
                return self._send(401, {"error": "Sign in first.", "login": True})
            self.send_response(302)
            self.send_header("Location", "/login")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        if u.path == "/api/kite/callback":   # Zerodha sends the browser back here after login
            try:
                page = kite.callback(dict(urllib.parse.parse_qsl(u.query)))
            except Exception as e:  # noqa: BLE001
                page = "<p>Zerodha login failed: %s</p>" % str(e)[:200].replace("<", "&lt;")
            return self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
        if u.path.startswith("/api/"):
            return self._api("GET", u.path, dict(urllib.parse.parse_qsl(u.query)), None)
        rel = "index.html" if u.path in ("/", "") else u.path.lstrip("/")
        full = os.path.normpath(os.path.join(STATIC, rel))
        if not full.startswith(STATIC) or not os.path.isfile(full):
            return self._send(404, b"Not found", "text/plain")
        with open(full, "rb") as f:
            self._send(200, f.read(), MIME.get(os.path.splitext(full)[1], "application/octet-stream"))

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if not self._local() or not self._same_origin():
            return self._send(403, {"error": "local access only"})
        if u.path == "/login" and PASSWORD:
            n = int(self.headers.get("Content-Length") or 0)
            pw = urllib.parse.parse_qs((self.rfile.read(min(n, 4096)) or b"").decode("utf-8", "replace")).get("password", [""])[0]
            if not hmac.compare_digest(pw.encode(), PASSWORD.encode()):
                time.sleep(1.5)   # slow down guessing
                return self._login_page("Wrong password.")
            self.send_response(302)
            self.send_header("Set-Cookie", "ts_auth=%s; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000" % _auth_token())
            self.send_header("Location", "/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        if not self._authed():
            return self._send(401, {"error": "Sign in first.", "login": True})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        except ValueError:
            return self._send(400, {"error": "Bad JSON"})
        self._api("POST", u.path, {}, body)


def _auth_token():
    """Cookie value: HMAC of the password with a random key kept in data/ (changes if the password changes)."""
    key_file = os.path.join(DATA, "auth.key")
    if not _AUTH["key"]:
        try:
            with open(key_file, "rb") as f:
                _AUTH["key"] = f.read()
        except OSError:
            os.makedirs(DATA, exist_ok=True)
            _AUTH["key"] = secrets.token_bytes(32)
            with open(key_file, "wb") as f:
                f.write(_AUTH["key"])
    return hmac.new(_AUTH["key"], PASSWORD.encode(), hashlib.sha256).hexdigest()


_AUTH = {"key": None}

if __name__ == "__main__":
    if not LOOPBACK and len(PASSWORD) < 8:
        sys.exit("Refusing to start: HOST=%s lets other devices in, so set PORTAL_PASSWORD (8+ characters)." % HOST)
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    telegram.start()   # background watcher: alerts, GTTs, paper exits, after-close messages
    print("Tradeskill Portal running at %s  (Ctrl+C to stop)" % (PUBLIC_URL or "http://%s:%d" % (HOST, PORT)))
    sys.stdout.flush()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
