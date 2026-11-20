"""Telegram message formatting (owner 20 Nov 2026: "messages should be proper and in tabular format").

Message builders stay plain Python strings. Inside them, table()/kv() add a fixed-width block between two
invisible markers. telegram._call() turns every message into Telegram HTML with render(): first line bold,
tables in a <pre> box (columns stay straight on a phone), everything else escaped. If Telegram ever refuses
the HTML, it is sent again as plain() text, so a message is never lost.
Tables are kept in English when the bot answers in Hindi (split()/join()), so no number or column can change.
No emoji inside tables: they are double width and break the columns.
"""
import html
import re

T0, T1 = "\x0e", "\x0f"            # start / end of a table block (never in normal text)
WIDTH = 34                         # characters that fit a phone screen in Telegram's fixed-width box
_TBL = re.compile(T0 + "(.*?)(?:" + T1 + "|$)", re.S)
_NUMLIKE = re.compile(r"^[+\-−]?[₹]?[+\-−]?[\d,.]+[%x×RkKLCr]*$|^[–-]$")


def _cut(s, n):
    return s if len(s) <= n else (s[:max(n - 1, 0)] + "…" if n > 1 else s[:n])


def table(rows, head=None, align=None, width=WIDTH, shrink=None):
    """Fixed-width table. rows: lists of cells. align: string of 'l'/'r' per column (default: numbers right).
    When too wide, the `shrink` column (default: the widest text column) is cut with '…'."""
    rows = [["" if c is None else str(c) for c in r] for r in rows if r is not None]
    allr = ([list(map(str, head))] if head else []) + rows
    if not allr:
        return ""
    n = max(len(r) for r in allr)
    allr = [r + [""] * (n - len(r)) for r in allr]
    if align is None:
        align = "".join("r" if i and all(_NUMLIKE.match(r[i].strip()) or not r[i].strip() for r in allr[1 if head else 0:]) else "l"
                        for i in range(n))
    w = [max(len(r[i]) for r in allr) for i in range(n)]
    total = sum(w) + (n - 1)
    if total > width:
        if shrink is None:
            text_cols = [i for i in range(n) if align[i] == "l"] or [0]
            shrink = max(text_cols, key=lambda i: w[i])
        w[shrink] = max(3, w[shrink] - (total - width))
    out = []
    for k, r in enumerate(allr):
        cells = []
        for i, c in enumerate(r):
            c = _cut(c, w[i])
            cells.append(c.rjust(w[i]) if align[i] == "r" else c.ljust(w[i]))
        out.append(" ".join(cells).rstrip())
        if head and k == 0:
            out.append("-" * min(sum(w) + n - 1, width))
    return T0 + "\n".join(out) + T1


def kv(pairs, width=WIDTH):
    """Two-column 'label  value' table, values right-aligned."""
    return table([[a, b] for a, b in pairs if a is not None], align="lr", width=width, shrink=0)


def has_table(text):
    return T0 in (text or "")


def plain(text):
    """Text without markers (logs, fallback when Telegram refuses HTML)."""
    return (text or "").replace(T0, "").replace(T1, "")


def render(text):
    """Telegram HTML: first line bold, tables in <pre>, the rest escaped."""
    text = text or ""
    out, pos = [], 0
    for m in _TBL.finditer(text):
        out.append(("t", text[pos:m.start()]))
        out.append(("p", m.group(1)))
        pos = m.end()
    out.append(("t", text[pos:]))
    html_parts, first = [], True
    for kind, s in out:
        if kind == "p":
            html_parts.append("<pre>%s</pre>" % html.escape(s.strip("\n"), quote=False))
            first = False
            continue
        s = s.replace(T1, "")
        if first and s.strip():
            head, sep, rest = s.lstrip("\n").partition("\n")
            html_parts.append("<b>%s</b>%s%s" % (html.escape(head, quote=False), sep, html.escape(rest, quote=False)))
            first = False
        else:
            html_parts.append(html.escape(s, quote=False))
    return "".join(html_parts).replace("\n<pre>", "<pre>").replace("</pre>\n", "</pre>")


def split(text):
    """Take the tables out (for translation): text with [[T1]].. placeholders, and the tables."""
    tabs = []

    def keep(m):
        tabs.append(m.group(0))
        return "\n[[T%d]]\n" % len(tabs)
    return _TBL.sub(keep, text or ""), tabs


def join(text, tabs):
    for i, t in enumerate(tabs, 1):
        text = re.sub(r"\n*\[\[\s*T\s*%d\s*\]\]\n*" % i, lambda _m, t=t: "\n" + t + "\n", text)
    return text


def rs(v, dec=0):
    """₹ with Indian grouping: 150168 -> ₹1,50,168; negatives with a real minus sign."""
    if v is None:
        return "–"
    n = round(abs(v), dec)
    whole = int(n)
    t = str(whole)
    if len(t) > 3:
        t = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", t[:-3]) + "," + t[-3:]
    if dec:
        t += ("%.*f" % (dec, n - whole))[1:]
    return ("−" if v < 0 and n else "") + "₹" + t


def sg(v, dec=0):
    """Signed rupees: +₹1,234 / −₹567."""
    if v is None:
        return "–"
    return ("+" if v >= 0 else "") + rs(v, dec) if v >= 0 else rs(v, dec)


def pc(v, dec=1):
    return "–" if v is None else ("%+.*f%%" % (dec, v)).replace("-", "−")


def px(v):
    """Price: two decimals under ₹1,000, none above (keeps tables narrow)."""
    if v is None:
        return "–"
    return rs(v, 2) if abs(v) < 1000 else rs(v, 0)
