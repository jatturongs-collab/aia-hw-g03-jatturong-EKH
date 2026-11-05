#!/usr/bin/env python3
"""
deepdive_viz.py - the sections of the deep dive that are mostly pictures (layout agreed with the owner, 10 Oct 2026):

  0  Overview          industry in brief + the company's hospitals: map, competitors nearby, table and one card each
  1  Position          the stock against the sector median (dumbbell), quarterly growth against the median, signal cards
  2  10 years          revenue, growth, gross profit, GPM, SG&A % and NPM from the Jitta factsheet, COVID years shaded
  3  (additions)       latest half-year vs the same half a year before with arrows; P&L by hospital (DBD filings)
  11 Valuation         P/E, EV/EBITDA, ROIC, yields, peers
  13 Open questions    pending questions + what to watch, in one place

Inputs beyond the data pack:
  <AI_ROOT>/data/Factsheet/factsheet_jitta_<T>.json      ten years (tier 2, compiled from filings)
  report/<T>_hospitals.json  blocks `sites`, `competitors`, `new_sites` (map and cards) and `dbd_pnl` (P&L by hospital)

Charts are inline SVG in the HTML only (Doc.raw); every chart has a table next to it, so the Markdown keeps the numbers.
Colours: the report's --s1..--s4 slots; green/red only for better/worse, always with an arrow or a word.
"""
import html as H
import json
import math
import os

COVID = (2020, 2022)
ARROW_UP = '<span class="vz-up">▲</span>'
ARROW_DN = '<span class="vz-dn">▼</span>'

CSS = """<style>
.vz-fig{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:12px 0}
.vz-fig h4{margin:0 0 4px;font-size:14px;color:var(--ink)}.vz-fig .vz-note{color:var(--muted);font-size:12px;margin:6px 0 0}
.vz-grid{display:grid;grid-template-columns:1fr;gap:12px}@media(min-width:880px){.vz-grid.c2{grid-template-columns:1fr 1fr}.vz-grid.c3{grid-template-columns:1fr 1fr 1fr}}
.vz-grid .vz-fig{margin:0}.vz-svg{width:100%;height:auto;display:block}.vz-svg text{font-size:11px;fill:var(--ink2)}.vz-svg .vz-ax{fill:var(--muted)}
.vz-svg .vz-gl{stroke:var(--line)}.vz-svg .vz-zero{stroke:var(--muted)}.vz-svg .vz-band{fill:var(--band)}.vz-svg .vz-lab{fill:var(--ink);font-weight:600}
.vz-svg .vz-halo{paint-order:stroke;stroke:var(--panel);stroke-width:4px;stroke-linejoin:round}
.vz-legend{display:flex;flex-wrap:wrap;gap:12px;font-size:12px;color:var(--ink2);margin:2px 0 6px}.vz-legend i{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:5px;vertical-align:-1px}
.vz-up,.vz-dngood{color:var(--good);font-weight:700}.vz-dn,.vz-upbad{color:var(--bad);font-weight:700}
.vz-cards{display:grid;grid-template-columns:1fr;gap:12px;margin:10px 0}@media(min-width:880px){.vz-cards{grid-template-columns:1fr 1fr}}
.vz-card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px}.vz-card h4{margin:0 0 2px;font-size:15px}
.vz-kpis{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0}.vz-kpi{background:var(--band);border-radius:8px;padding:5px 10px;min-width:92px}
.vz-kpi b{display:block;font-size:16px}.vz-kpi span{font-size:11.5px;color:var(--ink2)}.vz-card ul{margin:6px 0;padding-left:18px}.vz-card li{font-size:13.5px}
.vz-own{color:var(--red)}.vz-meter{height:8px;border-radius:4px;background:var(--line);overflow:hidden;margin:2px 0 6px}.vz-meter>div{height:100%;background:var(--s2)}
.vz-row{display:flex;justify-content:space-between;font-size:12px;color:var(--ink2)}#vz-map{height:440px;border-radius:10px;border:1px solid var(--line)}
.vz-sig{display:grid;grid-template-columns:1fr;gap:10px;margin:10px 0}@media(min-width:880px){.vz-sig{grid-template-columns:1fr 1fr}}
.vz-sig>div{background:var(--panel);border:1px solid var(--line);border-left:5px solid var(--muted);border-radius:8px;padding:10px 12px}
.vz-sig>div.better{border-left-color:var(--good)}.vz-sig>div.worse{border-left-color:var(--bad)}.vz-sig b{font-size:14px}.vz-sig p{margin:4px 0;font-size:13px}
.vz-sig .what{color:var(--ink2);font-size:12.5px}
</style>"""


def esc(s):
    return H.escape(str(s))


def _root(sdir):
    from snapshot import ai_root       # AI_ROOT only; snapshot stops the run if it is missing
    return ai_root(sdir)


def p1(v, d=1, sign=False):
    if v is None:
        return "–"
    return ("%+.*f%%" if sign else "%.*f%%") % (d, v * 100)


def n0(v):
    return "–" if v is None else "{:,.0f}".format(v)


def arrow(cur, prev, good_up=True):
    """Arrow shape = direction of the number; colour = good (green) or bad (red)."""
    if cur is None or prev is None or cur == prev:
        return ""
    if cur > prev:
        return ARROW_UP if good_up else '<span class="vz-upbad">▲</span>'
    return ARROW_DN if good_up else '<span class="vz-dngood">▼</span>'


# ------------------------------------------------------------------------------------------------ data
def load(sdir, ticker):
    """Ten years from the Jitta factsheet (tier 2). Returns {"jitta10": {...}} or {}."""
    p = os.path.join(_root(sdir), "data", "Factsheet", "factsheet_jitta_%s.json" % ticker)
    if not os.path.isfile(p):
        p2 = os.path.join(sdir, "factsheet", "factsheet_jitta_%s.json" % ticker)
        p = p2 if os.path.isfile(p2) else None
    if not p:
        return {}
    j = json.load(open(p, encoding="utf-8"))
    m = {x["metric"]: {int(k): v for k, v in (x.get("annual") or {}).items() if v is not None} for x in j.get("metrics", [])}
    R = m.get("total_revenue", {})
    if not R:
        return {}
    ys = sorted(R)[-10:]
    G, N, S = m.get("gross_profit", {}), m.get("net_profit", {}), m.get("selling_general_administrative_expenses", {})
    rows = []
    for y in ys:
        r = R.get(y)
        rows.append({"y": y, "rev": r, "rev_g": (r / R[y - 1] - 1) if r and R.get(y - 1) else None, "gp": G.get(y),
                     "gpm": G[y] / r if r and y in G else None, "sga_pct": S[y] / r if r and y in S else None,
                     "npm": N[y] / r if r and y in N else None, "np": N.get(y)})
    pre = [y for y in ys if 2017 <= y <= 2019]
    post = [y for y in ys if y >= ys[-1] - 2 and y > COVID[1]]
    def wavg(key, num, yy):
        rv = sum(R[y] for y in yy if R.get(y))
        return (sum(num[y] for y in yy if y in num) / rv) if rv and all(y in num for y in yy) else None
    def cagr(yy):
        return (R[yy[-1]] / R[yy[0]]) ** (1 / (len(yy) - 1)) - 1 if len(yy) > 1 and R.get(yy[0]) and R.get(yy[-1]) else None
    avg = {"pre": pre, "post": post,
           "rev_cagr": (cagr(pre), cagr(post)), "gpm": (wavg("gpm", G, pre), wavg("gpm", G, post)),
           "sga_pct": (wavg("sga", S, pre), wavg("sga", S, post)), "npm": (wavg("npm", N, pre), wavg("npm", N, post))}
    pcts = [v * 100 for r in rows for v in (r["rev_g"], r["gpm"], r["sga_pct"], r["npm"]) if v is not None]
    pcts += [v * 100 for pair in (avg["rev_cagr"], avg["gpm"], avg["sga_pct"], avg["npm"]) for v in pair if v is not None]
    return {"jitta10": {"rows": rows, "avg": avg, "src": os.path.relpath(p, _root(sdir)), "fetched": (j.get("fetch_timestamp") or "")[:10]},
            "viz_pcts": pcts}


# ------------------------------------------------------------------------------------------------ svg helpers
def _ticks(lo, hi, n=6):
    rng = (hi - lo) or 1
    for s in (0.5, 1, 2, 2.5, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 2500, 5000, 10000, 20000, 50000):
        if rng / s <= n:
            break
    g = math.ceil(lo / s) * s
    out = []
    while g <= hi + 1e-9:
        out.append(round(g, 6))
        g += s
    return out


def _fmt(v, unit):
    if unit == "%":
        return "%g%%" % v
    return "{:,.0f}".format(v)


def line_chart(title, labels, series, unit="%", band=None, clip=None, note="", height=300, colors=None):
    """series [(name, [v...])], values in display units (percent as 12.3). band = (i0, i1) indices shaded (COVID)."""
    W, Ht, L, R, T, B = 720, height, 48, 118, 14, 30
    pw, ph = W - L - R, Ht - T - B
    vals = [v for _, vs in series for v in vs if v is not None]
    if not vals:
        return ""
    lo, hi = min(vals + [0]), max(vals)
    if clip:
        lo, hi = max(lo, clip[0]), min(hi, clip[1])
    pad = (hi - lo) * 0.08 or 1
    lo, hi = lo - pad, hi + pad
    n = len(labels)
    X = lambda i: L + pw * (i + 0.5) / n
    Y = lambda v: T + ph - (min(max(v, lo), hi) - lo) / (hi - lo) * ph
    o = ['<svg class="vz-svg" viewBox="0 0 %d %d" role="img" aria-label="%s">' % (W, Ht, esc(title))]
    if band:
        x0, x1 = L + pw * band[0] / n, L + pw * (band[1] + 1) / n
        o.append('<rect class="vz-band" x="%.1f" y="%d" width="%.1f" height="%d"/><text class="vz-ax" x="%.1f" y="%d" text-anchor="middle">ช่วงโควิด</text>' % (
            x0, T, x1 - x0, ph, (x0 + x1) / 2, T + ph - 6))
    for g in _ticks(lo, hi):
        o.append('<line class="%s" x1="%d" x2="%d" y1="%.1f" y2="%.1f"/><text class="vz-ax" x="%d" y="%.1f" text-anchor="end">%s</text>' % (
            "vz-zero" if g == 0 else "vz-gl", L, L + pw, Y(g), Y(g), L - 6, Y(g) + 4, _fmt(g, unit)))
    for i, lb in enumerate(labels):
        o.append('<text class="vz-ax" x="%.1f" y="%d" text-anchor="middle">%s</text>' % (X(i), Ht - 10, esc(lb)))
    ends, clips = [], {}
    for si, (name, vs) in enumerate(series):
        col = (colors or [])[si] if colors and si < len(colors) else "var(--s%d)" % (si % 4 + 1)
        pts = [(X(i), Y(v), v, i) for i, v in enumerate(vs) if v is not None]
        o.append('<polyline fill="none" stroke="%s" stroke-width="2" points="%s"/>' % (col, " ".join("%.1f,%.1f" % (a, b) for a, b, _, _ in pts)))
        for a, b, v, i in pts:
            out = clip and (v < clip[0] or v > clip[1])
            o.append('<circle cx="%.1f" cy="%.1f" r="%s" fill="%s" stroke="var(--panel)" stroke-width="2"><title>%s %s: %s</title></circle>' % (
                a, b, "5" if out else "3.5", col, esc(name), esc(labels[i]), ("%.1f%%" % v) if unit == "%" else n0(v)))
            if out:
                clips.setdefault((i, v > hi), []).append((name, v))
        if pts:
            ends.append([pts[-1][1], si, name, pts[-1][2], col])
    for (i, top), lst in clips.items():
        lst.sort(key=lambda x: -x[1])
        for k, (name, v) in enumerate(lst):
            yy = (T + 14 + k * 13) if top else (T + ph - 20 - (len(lst) - 1 - k) * 13)
            o.append('<text class="vz-lab vz-halo" x="%.1f" y="%.1f">%s %+.0f%%</text>' % (X(i) + 8, yy, esc(name), v))
    ends.sort()
    for k in range(1, len(ends)):
        if ends[k][0] - ends[k - 1][0] < 13:
            ends[k][0] = ends[k - 1][0] + 13
    for yy, si, name, v, col in ends:
        o.append('<text x="%d" y="%.1f"><tspan fill="%s">●</tspan> <tspan class="vz-lab">%s</tspan> %s</text>' % (
            L + pw + 6, yy + 4, col, esc(name), ("%.1f%%" % v) if unit == "%" else n0(v)))
    o.append("</svg>")
    leg = "" if len(series) < 2 else '<div class="vz-legend">' + "".join(
        '<span><i style="background:%s"></i>%s</span>' % ((colors or [])[i] if colors and i < len(colors) else "var(--s%d)" % (i % 4 + 1), esc(nm))
        for i, (nm, _) in enumerate(series)) + "</div>"
    return '<div class="vz-fig"><h4>%s</h4>%s%s%s</div>' % (esc(title), leg, "".join(o), ('<p class="vz-note">%s</p>' % esc(note)) if note else "")


def small_multiple(title, labels, vals, unit="%", kind="line", band=None, avgs=None, color="var(--s1)"):
    """one measure over the years; avgs = [(i0, i1, value, label)] drawn as dashed segments (pre / post COVID averages)."""
    W, Ht, L, R, T, B = 340, 190, 42, 8, 22, 24
    pw, ph = W - L - R, Ht - T - B
    vv = [v for v in vals if v is not None]
    if not vv:
        return ""
    lo, hi = min(vv + ([0] if kind == "bar" else [])), max(vv + ([0] if kind == "bar" else []))
    if kind == "line":
        pad = (hi - lo) * 0.15 or 1
        lo, hi = lo - pad, hi + pad
    else:
        hi += (hi - lo) * 0.08 or 1
    n = len(labels)
    X = lambda i: L + pw * (i + 0.5) / n
    Y = lambda v: T + ph - (v - lo) / ((hi - lo) or 1) * ph
    o = ['<svg class="vz-svg" viewBox="0 0 %d %d" role="img" aria-label="%s">' % (W, Ht, esc(title))]
    if band:
        x0, x1 = L + pw * band[0] / n, L + pw * (band[1] + 1) / n
        o.append('<rect class="vz-band" x="%.1f" y="%d" width="%.1f" height="%d"/>' % (x0, T, x1 - x0, ph))
    for g in _ticks(lo, hi, 4):
        o.append('<line class="%s" x1="%d" x2="%d" y1="%.1f" y2="%.1f"/><text class="vz-ax" x="%d" y="%.1f" text-anchor="end">%s</text>' % (
            "vz-zero" if g == 0 else "vz-gl", L, L + pw, Y(g), Y(g), L - 4, Y(g) + 4, _fmt(g, unit)))
    for i, lb in enumerate(labels):
        if i % 2 == 0 or i == n - 1:
            o.append('<text class="vz-ax" x="%.1f" y="%d" text-anchor="middle">%s</text>' % (X(i), Ht - 8, esc(str(lb)[-2:])))
    if kind == "bar":
        bw = min(18, pw / n * 0.6)
        for i, v in enumerate(vals):
            if v is None:
                continue
            y0, y1 = (Y(v), Y(0)) if v >= 0 else (Y(0), Y(v))
            o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="3" fill="%s"><title>%s: %s</title></rect>' % (
                X(i) - bw / 2, y0, bw, max(0.5, y1 - y0), color, esc(labels[i]), _fmt(v, unit) if unit != "%" else "%.1f%%" % v))
    else:
        pts = [(X(i), Y(v), v, i) for i, v in enumerate(vals) if v is not None]
        o.append('<polyline fill="none" stroke="%s" stroke-width="2" points="%s"/>' % (color, " ".join("%.1f,%.1f" % (a, b) for a, b, _, _ in pts)))
        for a, b, v, i in pts:
            o.append('<circle cx="%.1f" cy="%.1f" r="3" fill="%s"><title>%s: %.1f%%</title></circle>' % (a, b, color, esc(labels[i]), v))
    for i0, i1, v, lab in avgs or []:
        if v is None:
            continue
        xa, xb = L + pw * i0 / n + 2, L + pw * (i1 + 1) / n - 2
        o.append('<line x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f" stroke="var(--ink2)" stroke-width="1.5" stroke-dasharray="4 3"/>'
                 '<text class="vz-lab vz-halo" x="%.1f" y="%.1f" text-anchor="middle">%s</text>' % (xa, xb, Y(v), Y(v), (xa + xb) / 2, Y(v) - 5, esc(lab)))
    last = next((v for v in reversed(vals) if v is not None), None)
    o.append("</svg>")
    head = '%s <span style="font-weight:400;color:var(--ink2)">— ล่าสุด %s</span>' % (esc(title), (_fmt(last, unit) if unit != "%" else "%.1f%%" % last) if last is not None else "–")
    return '<div class="vz-fig"><h4>%s</h4>%s</div>' % (head, "".join(o))


def dumbbell(title, rows, note=""):
    """rows [(label, stock, median, (q1, q3) or None, rank text)] in percent units."""
    W, rowh, L, R, T = 720, 46, 210, 70, 26
    Ht = T + rowh * len(rows) + 14
    vals = [v for r in rows for v in (r[1], r[2]) + tuple(r[3] or ()) if v is not None]
    lo, hi = min(vals + [0]), max(vals + [0])
    pad = (hi - lo) * 0.08 or 1
    lo, hi = lo - pad, hi + pad
    pw = W - L - R
    X = lambda v: L + (v - lo) / (hi - lo) * pw
    o = ['<svg class="vz-svg" viewBox="0 0 %d %d" role="img" aria-label="%s">' % (W, Ht, esc(title))]
    for g in _ticks(lo, hi):
        o.append('<line class="%s" x1="%.1f" x2="%.1f" y1="%d" y2="%d"/><text class="vz-ax" x="%.1f" y="16" text-anchor="middle">%g%%</text>' % (
            "vz-zero" if g == 0 else "vz-gl", X(g), X(g), T - 4, Ht - 8, X(g), g))
    for i, (lab, s, m, iqr, rk) in enumerate(rows):
        y = T + rowh * i + rowh / 2
        o.append('<text class="vz-lab" x="%d" y="%.1f" text-anchor="end">%s</text>' % (L - 10, y + 4, esc(lab)))
        if iqr:
            o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="14" rx="3" fill="var(--band)"><title>ครึ่งกลางของกลุ่ม %.1f%% ถึง %.1f%%</title></rect>' % (
                X(iqr[0]), y - 7, max(1, X(iqr[1]) - X(iqr[0])), iqr[0], iqr[1]))
        if s is not None and m is not None:
            col = "var(--good)" if s > m else "var(--bad)"
            o.append('<line x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f" stroke="%s" stroke-width="3"/>' % (X(m), X(s), y, y, col))
        if m is not None:
            o.append('<circle cx="%.1f" cy="%.1f" r="6" fill="var(--panel)" stroke="var(--ink2)" stroke-width="2"><title>median %.1f%%</title></circle>' % (X(m), y, m))
        if s is not None:
            o.append('<circle cx="%.1f" cy="%.1f" r="7" fill="var(--s1)" stroke="var(--panel)" stroke-width="2"><title>หุ้น %.1f%%</title></circle>' % (X(s), y, s))
            o.append('<text class="vz-lab vz-halo" x="%.1f" y="%.1f" text-anchor="middle">%+.1f%%</text>' % (X(s), y - 11, s))
        o.append('<text x="%d" y="%.1f">%s</text>' % (W - R + 8, y + 4, esc(rk)))
    o.append("</svg>")
    leg = ('<div class="vz-legend"><span><i style="background:var(--s1);border-radius:50%"></i>หุ้นตัวนี้</span>'
           '<span><i style="background:var(--panel);border:2px solid var(--ink2);border-radius:50%"></i>median ของกลุ่ม</span>'
           '<span><i style="background:var(--band)"></i>ครึ่งกลางของกลุ่ม (IQR)</span>'
           '<span><i style="background:var(--good)"></i>เส้นเขียว = เร็วกว่า median, แดง = ช้ากว่า</span></div>')
    return '<div class="vz-fig"><h4>%s</h4>%s%s%s</div>' % (esc(title), leg, "".join(o), ('<p class="vz-note">%s</p>' % esc(note)) if note else "")


def hbar_pairs(title, cats, a, b, la, lb, note=""):
    """two horizontal bars per category (share of revenue vs share of profit), percent units."""
    W, rowh, L = 720, 44, 120
    Ht = 28 + rowh * len(cats)
    mx = max([v for v in a + b if v is not None] + [1]) * 1.15
    sc = lambda v: (W - L - 60) * v / mx
    o = ['<svg class="vz-svg" viewBox="0 0 %d %d" role="img" aria-label="%s">' % (W, Ht, esc(title))]
    for i, c in enumerate(cats):
        y = 18 + i * rowh
        o.append('<text class="vz-lab" x="%d" y="%d" text-anchor="end">%s</text>' % (L - 8, y + 18, esc(c)))
        for j, (v, col, lab) in enumerate(((a[i], "var(--s1)", la), (b[i], "var(--s2)", lb))):
            if v is None:
                continue
            yy = y + j * 17
            o.append('<rect x="%d" y="%d" width="%.1f" height="13" rx="3" fill="%s"><title>%s %s: %.1f%%</title></rect><text x="%.1f" y="%d">%.0f%%</text>' % (
                L, yy, max(1, sc(v)), col, esc(c), esc(lab), v, L + sc(v) + 5, yy + 11, v))
    o.append("</svg>")
    leg = '<div class="vz-legend"><span><i style="background:var(--s1)"></i>%s</span><span><i style="background:var(--s2)"></i>%s</span></div>' % (esc(la), esc(lb))
    return '<div class="vz-fig"><h4>%s</h4>%s%s%s</div>' % (esc(title), leg, "".join(o), ('<p class="vz-note">%s</p>' % esc(note)) if note else "")


def yoy_panel(title, labels, vals, clip=60.0, note=""):
    """one hospital's YoY growth (% values) as labelled bars; shared scale ±clip, longer bars are cut and keep their true label."""
    W, Ht, L, R, T, B = 340, 210, 46, 8, 24, 24
    pw, ph = W - L - R, Ht - T - B
    vv = [v for v in vals if v is not None]
    if not vv:
        return ""
    lo, hi = -clip, clip
    n = len(labels)
    X = lambda i: L + pw * (i + 0.5) / n
    Y = lambda v: T + ph - (min(max(v, lo), hi) - lo) / (hi - lo) * ph
    o = ['<svg class="vz-svg" viewBox="0 0 %d %d" role="img" aria-label="%s">' % (W, Ht, esc(title))]
    for g in _ticks(lo, hi, 4):
        o.append('<line class="%s" x1="%d" x2="%d" y1="%.1f" y2="%.1f"/><text class="vz-ax" x="%d" y="%.1f" text-anchor="end">%g%%</text>' % (
            "vz-zero" if g == 0 else "vz-gl", L, L + pw, Y(g), Y(g), L - 4, Y(g) + 4, g))
    bw = min(26, pw / n * 0.62)
    for i, lb in enumerate(labels):
        o.append('<text class="vz-ax" x="%.1f" y="%d" text-anchor="middle">%s</text>' % (X(i), Ht - 8, esc(str(lb)[-2:])))
        v = vals[i]
        if v is None:
            continue
        y0, y1 = (Y(v), Y(0)) if v >= 0 else (Y(0), Y(v))
        col = "var(--good)" if v >= 0 else "var(--bad)"
        cut = abs(v) > clip
        o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="2" fill="%s"%s><title>%s: %+.1f%%</title></rect>' % (
            X(i) - bw / 2, y0, bw, max(0.5, y1 - y0), col, ' fill-opacity=".55"' if cut else "", esc(lb), v))
        if cut:   # zig-zag mark: the bar is longer than drawn
            yy = y0 + 6 if v > 0 else y1 - 6
            o.append('<path d="M%.1f %.1f l%.1f -3 l%.1f 6 l%.1f -3" stroke="var(--panel)" stroke-width="2" fill="none"/>' % (
                X(i) - bw / 2, yy, bw / 3, bw / 3, bw / 3))
        ty = (y0 - 4) if v >= 0 else (y1 + 12)
        if cut:
            ty = (T + 10) if v > 0 else (T + ph - 3)
        o.append('<text class="vz-lab vz-halo" x="%.1f" y="%.1f" text-anchor="middle" style="font-size:10.5px">%+.0f%%</text>' % (X(i), ty, v)
                 if abs(v) >= 10 else
                 '<text class="vz-lab vz-halo" x="%.1f" y="%.1f" text-anchor="middle" style="font-size:10.5px">%+.1f%%</text>' % (X(i), ty, v))
    o.append("</svg>")
    return '<div class="vz-fig"><h4>%s</h4>%s%s</div>' % (esc(title), "".join(o), ('<p class="vz-note">%s</p>' % esc(note)) if note else "")


def stack100(title, labels, series, note=""):
    """100% stacked columns: series [(name, [value per label])], segment labels = share of that column."""
    W, Ht, L, R, T, B = 720, 300, 40, 10, 10, 28
    pw, ph = W - L - R, Ht - T - B
    n = len(labels)
    tots = [sum((vs[i] or 0) for _, vs in series) for i in range(n)]
    X = lambda i: L + pw * (i + 0.5) / n
    bw = min(64, pw / n * 0.7)
    o = ['<svg class="vz-svg" viewBox="0 0 %d %d" role="img" aria-label="%s">' % (W, Ht, esc(title))]
    for g in (0, 25, 50, 75, 100):
        y = T + ph - g / 100 * ph
        o.append('<line class="vz-gl" x1="%d" x2="%d" y1="%.1f" y2="%.1f"/><text class="vz-ax" x="%d" y="%.1f" text-anchor="end">%d%%</text>' % (
            L, L + pw, y, y, L - 4, y + 4, g))
    for i, lb in enumerate(labels):
        o.append('<text class="vz-ax" x="%.1f" y="%d" text-anchor="middle">%s</text>' % (X(i), Ht - 8, esc(lb)))
        if not tots[i]:
            continue
        acc = 0.0
        for si, (name, vs) in enumerate(series):
            v = vs[i] or 0
            sh = v / tots[i]
            y1 = T + ph - acc * ph
            y0 = T + ph - (acc + sh) * ph
            col = "var(--s%d)" % (si % 4 + 1)
            o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s" stroke="var(--panel)" stroke-width="1"><title>%s %s: %.1f%% (%s ลบ.)</title></rect>' % (
                X(i) - bw / 2, y0, bw, max(0.5, y1 - y0), col, esc(name), esc(lb), sh * 100, n0(v)))
            if sh >= 0.045:
                o.append('<text x="%.1f" y="%.1f" text-anchor="middle" style="font-size:10.5px;fill:#fff;font-weight:600">%.0f%%</text>' % (
                    X(i), (y0 + y1) / 2 + 4, sh * 100))
            acc += sh
    o.append("</svg>")
    leg = '<div class="vz-legend">' + "".join('<span><i style="background:var(--s%d)"></i>%s</span>' % (k % 4 + 1, esc(nm)) for k, (nm, _) in enumerate(series)) + "</div>"
    return '<div class="vz-fig"><h4>%s</h4>%s%s%s</div>' % (esc(title), leg, "".join(o), ('<p class="vz-note">%s</p>' % esc(note)) if note else "")


def hospital_charts(d, names, keys, tb, what):
    """charts under the per-hospital tables (DX.render_hospitals): what = 'rev' (share + YoY) or 'np' (YoY)."""
    _css(d)
    ys = [str(r["year"]) for r in tb]
    short = lambda k: names[k].split(" (")[0]
    if what == "rev":
        d.raw(stack100("สัดส่วนรายได้รายโรงพยาบาล (% ของรวมก่อนตัดรายการระหว่างกัน)", ys,
                       [(short(k), [r["h"][k]["rev"] for r in tb]) for k in keys],
                       note="ตัวเลขในแท่ง = สัดส่วนรายได้ปีนั้น [คำนวณ]; ชี้เมาส์ดูล้านบาท"), "")
        g = [(short(k), [None if r["h"][k].get("rev_g") is None else r["h"][k]["rev_g"] * 100 for r in tb]) for k in keys]
        d.raw('<div class="vz-grid c2">%s</div><p class="src">รายได้โต YoY รายโรงพยาบาล: เขียว = โต, แดง = หด; ทุกช่องใช้สเกลเดียวกัน ±60%%, '
              'แท่งที่ยาวกว่านั้นถูกตัด (สีจาง มีรอยหยัก) แต่ตัวเลขเป็นค่าจริง [คำนวณ]</p>' % "".join(
                  yoy_panel("%s — รายได้โต YoY" % nm, ys, vs) for nm, vs in g), "")
    else:
        g = [(short(k), [None if r["h"][k].get("np_g") is None else r["h"][k]["np_g"] * 100 for r in tb]) for k in keys]
        d.raw('<div class="vz-grid c2">%s</div><p class="src">กำไรสุทธิ (ไม่รวมเงินปันผลรับจากบริษัทย่อย) โต YoY: สเกลเดียวกัน ±100%%, '
              'แท่งที่ยาวกว่านั้นถูกตัดแต่ตัวเลขเป็นค่าจริง; ฐานกำไรเล็กทำให้ %% แกว่งแรง [คำนวณ]</p>' % "".join(
                  yoy_panel("%s — กำไรสุทธิโต YoY" % nm, ys, vs, clip=100) for nm, vs in g), "")


# ------------------------------------------------------------------------------------------------ sections
def _css(d):
    if not getattr(d, "_vz_css", False):
        d.raw(CSS, "")
        d._vz_css = True


def _haversine(a, b, c, e):
    R = 6371
    p1_, p2_ = math.radians(a), math.radians(c)
    x = math.sin((p2_ - p1_) / 2) ** 2 + math.cos(p1_) * math.cos(p2_) * math.sin(math.radians(e - b) / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))


def render_overview(d, p, nar, narrative_items):
    """Section 0: the industry in brief, then the company's hospitals."""
    _css(d)
    s = p.get("sector") or {}
    T = p["ticker"]
    d.h(3, "0.1 ภาพอุตสาหกรรมโดยย่อ")
    if s and not s.get("missing"):
        rows = {r["key"]: r for r in s.get("rows", [])}
        pre, post, half = rows.get("pre") or {}, rows.get("post") or {}, rows.get("half") or {}
        f = s.get("fingerprint") or {}
        cn = f.get("count") or {}
        d.p("อุตสาหกรรมโรงพยาบาลเอกชนที่จดทะเบียนโตช้าลงมาก: บริษัทกลางกลุ่ม (median) ของ %d โรงพยาบาลโต %s ต่อปีก่อนโควิด เหลือ %s ต่อปีหลังโควิด "
            "และ %s จาก %s แห่ง ROE ลดลงเพราะเงินจากช่วงโควิดกลายเป็นทุนที่ยังไม่ได้ใช้ %s อยู่ในตำแหน่งตามตารางนี้ "
            "(รายละเอียดในข้อ 1 และไฟล์ `%s`)" % (s.get("core_n", 0), p1(pre.get("median")), p1(post.get("median")), cn.get("follows_cycle", "–"),
                                                  cn.get("n", "–"), T, os.path.basename(s.get("analysis") or "sector_analysis").replace(".md", ".html")))
        fs = f.get("stock") or {}
        fm = f.get("median") or {}
        tab = [["รายได้ CAGR หลังโควิด", "**%s**" % p1(post.get("stock"), sign=True), p1(post.get("median"), sign=True), "อันดับ %s จาก %s" % (post.get("rank") or "–", post.get("n") or "–")],
               ["รายได้ครึ่งปีล่าสุด YoY", "**%s**" % p1(half.get("stock"), sign=True), p1(half.get("median"), sign=True), "อันดับ %s จาก %s" % (half.get("rank") or "–", half.get("n") or "–")]]
        if fs:
            tab += [["อัตรากำไรสุทธิเฉลี่ย 3 ปีล่าสุด", "**%s**" % p1(fs.get("npm_post")), p1(fm.get("npm_post")), "ก่อนโควิด %s" % p1(fs.get("npm_pre"))],
                    ["ROE เฉลี่ย 3 ปีล่าสุด", "**%s**" % p1(fs.get("roe_post")), p1(fm.get("roe_post")), "ก่อนโควิด %s; ทุนโต %.2f เท่า กำไรโต %.2f เท่า" % (
                        p1(fs.get("roe_pre")), fs.get("equity_x") or 0, fs.get("np_x") or 0)],
                    ["เงินสดสุทธิต่อส่วนของผู้ถือหุ้น (ปลายปีล่าสุด)", "**%s**" % p1(fs.get("netcash_eq_post")), p1(fm.get("netcash_eq_post")), ""]]
        d.table(["ตัวชี้วัด (factsheet, tier 2)", T, "median กลุ่ม", "หมายเหตุ"], tab, align=["l", "r", "r", "l"])
        rel = "../../../data/sector/%s/%s" % (s.get("name") or "Hospital", os.path.basename(s.get("analysis") or "").replace(".md", ".html"))
        d.raw('<p class="src">ภาพอุตสาหกรรมฉบับเต็ม: <a href="%s">%s</a></p>' % (esc(rel), esc(os.path.basename(rel))), "")
    else:
        d.p("_ยังไม่มี `data/sector/Hospital/sector_trend.json` — รัน `script/sector/sector_trend.py`_")

    hb = p.get("hospitals") or {}
    sites = hb.get("sites") or {}
    names = hb.get("hospitals") or {}
    keys = [k for k in (hb.get("keys") or list(sites)) if k in sites] or list(sites)
    if not sites:
        d.h(3, "0.2 โรงพยาบาลของบริษัท")
        d.p("_ยังไม่ได้เก็บข้อมูลรายสาขา (บล็อก `sites` ใน `report/%s_hospitals.json`: ชื่อ ที่ตั้ง พิกัด ที่ดิน บทบาท พร้อม src) — "
            "Claude เติมได้ตอนทำ deepdive: ค้นพิกัดครั้งเดียว อ่าน One Report ข้อ 1.2 และทรัพย์สินที่ใช้ประกอบธุรกิจ_" % T)
        return
    tb = hb.get("table") or []
    last = tb[-1] if tb else None
    beds = hb.get("beds") or {}
    by = next((y for y in sorted(beds, reverse=True) if (beds[y].get("registered") or {})), None)
    capy = next((r for r in reversed(tb) if any((r["h"].get(k) or {}).get("cap") is not None for k in keys)), None)
    sso = (hb.get("sso") or {}).get("years") or {}
    sy = max(sso) if sso else None
    comps = hb.get("competitors") or []
    radius = hb.get("competitor_radius_km", 10)
    for k in keys:
        st = sites[k]
        st["_near"] = sorted([(c["name"], _haversine(st["lat"], st["lng"], c["lat"], c["lng"]), c.get("type", "")) for c in comps
                              if st.get("lat") and _haversine(st["lat"], st["lng"], c["lat"], c["lng"]) <= radius], key=lambda x: x[1])
    total_beds = (beds.get(by, {}).get("registered") or {}).get("total") if by else None
    d.h(3, "0.2 ที่ตั้งโรงพยาบาลและคู่แข่งรอบข้าง")
    d.p("%s มี %d โรงพยาบาล%s ปักคู่แข่งในรัศมี %d กม. (ระยะเส้นตรง) จากพิกัด Google Places — ไม่ครบทุกแห่ง และยังไม่มีจำนวนเตียงของคู่แข่ง" % (
        T, len(keys), (" %s เตียงจดทะเบียน (ปี %s)" % (n0(total_beds), by)) if total_beds else "", radius))
    pts = [dict(n=sites[k].get("name", names.get(k, k)), s=sites[k].get("short", names.get(k, k)), lat=sites[k]["lat"], lng=sites[k]["lng"], t="own",
                info="%s เตียง" % ((beds.get(by, {}).get("registered") or {}).get(k, "–") if by else "–")) for k in keys if sites[k].get("lat")]
    pts += [dict(n=x["name"], s=x["name"], lat=x["lat"], lng=x["lng"], t="new", info=x.get("note", "")) for x in hb.get("new_sites") or []]
    pts += [dict(n=c["name"], s=c["name"], lat=c["lat"], lng=c["lng"], t="pub" if str(c.get("type", "")).startswith("รัฐ") else "pvt", info=c.get("type", "")) for c in comps]
    js = ("(function(){if(!window.L){document.getElementById('vz-map').innerHTML='<p style=\"padding:12px\">แผนที่ต้องต่ออินเทอร์เน็ต — ดูตารางและลิงก์ Google Maps ด้านล่าง</p>';return;}"
          "var P=%s;var m=L.map('vz-map',{scrollWheelZoom:false});var col={own:'#2c4f8f',new:'#8a63c9',pvt:'#eb6834',pub:'#8a8984'};var b=[];"
          # Tile servers that refuse pages opened from disk (file://, no Referer): OpenStreetMap (403) and CARTO
          # (needs an API key since 2026). Esri World Street Map serves them without a key (checked 11 Oct 2569).
          "L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}',"
          "{maxZoom:19,attribution:'Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors'}).addTo(m);"
          "P.forEach(function(p){var c=L.circleMarker([p.lat,p.lng],{radius:p.t=='own'?10:(p.t=='new'?9:6),color:'#fff',weight:2,fillColor:col[p.t],fillOpacity:.95}).addTo(m);"
          "c.bindPopup('<b>'+p.n+'</b><br>'+p.info);if(p.t=='own'){c.bindTooltip(p.s,{permanent:true,direction:'right'});"
          "L.circle([p.lat,p.lng],{radius:%d,color:col.own,weight:1,fill:false,dashArray:'4 4'}).addTo(m);}b.push([p.lat,p.lng]);});"
          "m.fitBounds(b,{padding:[30,30]});})();") % (json.dumps(pts, ensure_ascii=False), radius * 1000)
    d.raw('<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css"><div id="vz-map"></div>'
          '<div class="vz-legend"><span><i style="background:#2c4f8f;border-radius:50%%"></i>%s</span><span><i style="background:#8a63c9;border-radius:50%%"></i>โครงการใหม่</span>'
          '<span><i style="background:#eb6834;border-radius:50%%"></i>เอกชนคู่แข่ง</span><span><i style="background:#8a8984;border-radius:50%%"></i>โรงพยาบาลรัฐ</span></div>'
          '<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script><script>%s</script>' % (esc(T), js), "")
    gm = lambda st: "https://www.google.com/maps/search/?api=1&query=%s%s" % (
        H.escape(st.get("name", "")).replace(" ", "+"), ("&query_place_id=" + st["place_id"]) if st.get("place_id") else "")
    d.table(["สาขา", "ที่ตั้ง", "คู่แข่งในรัศมี %d กม." % radius, "แผนที่"],
            [[sites[k].get("short", names.get(k, k)), sites[k].get("area", "–"),
              ", ".join("%s %.1f กม.%s" % (nm, km, "" if t == "เอกชน" else " (%s)" % t) for nm, km, t in sites[k]["_near"]) or "–",
              "[Google Maps](%s)" % gm(sites[k])] for k in keys], align=["l", "l", "l", "l"])
    if hb.get("geo_src"):
        d.p("_พิกัดและคู่แข่ง: %s_" % hb["geo_src"])

    d.h(3, "0.3 ตารางรายสาขา")
    rows, ra, rb = [], [], []
    for k in keys:
        h = (last["h"].get(k) or {}) if last else {}
        cap = (capy["h"].get(k) or {}).get("cap_share") if capy else None
        ins = ((sso.get(sy) or {}).get("insured") or {}).get(k) if sy else None
        quo = ((sso.get(sy) or {}).get("quota") or {}).get(k) if sy else None
        reg = (beds.get(by, {}).get("registered") or {}).get(k) if by else None
        op = (beds.get(by, {}).get("operating") or {}).get(k) if by else None
        rows.append([sites[k].get("short", names.get(k, k)), "%s / %s" % (reg if reg is not None else "–", op if op is not None else "–"),
                     n0(h.get("rev")), p1(h.get("rev_share")), n0(h.get("np")), p1(h.get("np_share")), p1(h.get("npm")), p1(h.get("rev_g"), sign=True),
                     p1(cap, 0), ("{:,} / {:,}".format(ins, quo) if ins and quo else ("ไม่รับ SSO" if sso and k not in ((sso.get(sy) or {}).get("insured") or {}) else "–")),
                     sites[k].get("land", "–")])
        ra.append((h.get("rev_share") or 0) * 100)
        rb.append((h.get("np_share") or 0) * 100)
    yl = last["year"] if last else "–"
    d.table(["สาขา", "เตียงจดทะเบียน / ให้บริการ (%s)" % (by or "–"), "รายได้ %s (ลบ.)" % yl, "% รายได้", "กำไร %s (ลบ.)" % yl, "% กำไร", "NPM", "รายได้โต",
             "%% รายได้ SSO (%s)" % (capy["year"] if capy else "–"), "ผู้ประกันตน / โควตา (%s)" % (sy or "–"), "ที่ดิน"], rows,
            align=["l", "r", "r", "r", "r", "r", "r", "r", "r", "l", "l"])
    d.p("_ที่มา: รายได้และกำไรรายสาขา (ไม่รวมเงินปันผลจากบริษัทย่อย) = %s; เตียง = %s; ที่ดิน = บล็อก `sites` (แต่ละสาขามี src ในการ์ด); สัดส่วนและอัตราเป็นค่าคำนวณ. "
        "OPD/IPD และไทย/ต่างชาติรายสาขา: บริษัทไม่เปิดเผย_" % ((last or {}).get("src") or "–", (beds.get(by) or {}).get("src", "–") if by else "–"))
    d.raw(hbar_pairs("สัดส่วนรายได้และกำไรรายสาขา ปี %s" % yl, [sites[k].get("short", names.get(k, k)) for k in keys], ra, rb, "รายได้", "กำไรสุทธิ"), "")

    d.h(3, "0.4 การ์ดรายสาขา")
    cards = []
    for k, rs, ns in zip(keys, ra, rb):
        st = sites[k]
        h = (last["h"].get(k) or {}) if last else {}
        cap = (capy["h"].get(k) or {}).get("cap_share") if capy else None
        reg = (beds.get(by, {}).get("registered") or {}).get(k) if by else None
        devs = "".join('<li>%s <span class="%s">[%s]</span></li>' % (esc(x.get("text", "")), "vz-own" if x.get("owner") else "src", esc(x.get("src", "")))
                       for x in st.get("dev") or [])
        cards.append('<div class="vz-card"><h4>%s</h4><div class="src">%s · %s · <a href="%s" target="_blank">Google Maps</a></div><div class="vz-kpis">'
                     '<div class="vz-kpi"><b>%s</b><span>เตียงจดทะเบียน</span></div><div class="vz-kpi"><b>%.0f%%</b><span>ของรายได้</span></div>'
                     '<div class="vz-kpi"><b>%.0f%%</b><span>ของกำไร</span></div><div class="vz-kpi"><b>%s</b><span>NPM</span></div><div class="vz-kpi"><b>%s</b><span>รายได้โต</span></div></div>'
                     '<div class="vz-row"><span>ผู้ป่วย: %s</span><span>SSO %s ของรายได้</span></div><div class="vz-meter"><div style="width:%.0f%%"></div></div>'
                     '<ul><li>ที่ดิน: %s <span class="src">[%s]</span></li><li>บทบาท: %s <span class="src">[%s]</span></li>%s</ul></div>' % (
                         esc(st.get("name", names.get(k, k))), esc(st.get("company", "")), esc(st.get("area", "")), gm(st), reg if reg is not None else "–",
                         rs, ns, p1(h.get("npm")), p1(h.get("rev_g"), sign=True), esc(st.get("payor", "–")), p1(cap, 0), (cap or 0) * 100,
                         esc(st.get("land", "–")), esc(st.get("land_src", "")), esc(st.get("role", "–")), esc(st.get("role_src", "")), devs))
    d.raw('<div class="vz-cards">%s</div><p class="src">ข้อความสีแดง = จากเจ้าของหรือแหล่งที่ 2 ยังไม่ได้ตรวจกับเอกสาร</p>' % "".join(cards),
          "\n".join("- **%s**: ที่ดิน %s [%s]; บทบาท %s [%s]%s" % (
              sites[k].get("name", k), sites[k].get("land", "–"), sites[k].get("land_src", ""), sites[k].get("role", "–"), sites[k].get("role_src", ""),
              "".join("; %s [%s]" % (x.get("text", ""), x.get("src", "")) for x in sites[k].get("dev") or [])) for k in keys) + "\n")


SIG_WHAT = {
    "acceleration": ("การเร่งหรือชะลอ", "เทียบการเติบโตครึ่งปีล่าสุดกับ CAGR หลังโควิดของตัวเองและกับ median — ครึ่งปีขยับก่อนงบทั้งปีหกเดือน"),
    "quarters": ("รายไตรมาสเทียบกลุ่ม", "นับว่ากี่ใน 4 ไตรมาสล่าสุดที่รายได้โตเร็วกว่า median และทิศของ 3 ไตรมาสล่าสุด — เห็นการเปลี่ยนทีละไตรมาส"),
    "margin": ("อัตรากำไรครึ่งปี", "อัตรากำไรสุทธิครึ่งปีล่าสุดเทียบช่วงเดียวกันปีก่อน (ใช้ครึ่งปีเพื่อไม่ให้รายการพิเศษไตรมาสเดียวตัดสิน)"),
    "rank_move": ("อันดับในกลุ่ม", "อันดับการเติบโตครึ่งปีล่าสุดเทียบอันดับหลังโควิด — อันดับที่ไต่ขึ้นแปลว่าเหตุเฉพาะบริษัท ไม่ใช่อุตสาหกรรม"),
}
VERD = {"better": "ดีขึ้น", "worse": "แย่ลง", "neutral": "ทรงตัว"}


def render_position(d, p, nar, narrative_items):
    """Section 1: where the stock stands and what moves first."""
    _css(d)
    s = p.get("sector") or {}
    if not s or s.get("missing"):
        d.p("_ยังไม่มีข้อมูลอุตสาหกรรม (`data/sector/Hospital/sector_trend.json`) — รัน `script/sector/sector_trend.py` ก่อน_")
        return
    T = p["ticker"]
    rows = s.get("rows") or []
    d.raw(dumbbell("การเติบโตของรายได้ต่อปี: %s เทียบ median ของ %d โรงพยาบาล" % (T, s.get("core_n", 0)),
                   [(r["label"], None if r.get("stock") is None else r["stock"] * 100, None if r.get("median") is None else r["median"] * 100,
                     (r["iqr"][0] * 100, r["iqr"][1] * 100) if r.get("iqr") else None, ("อันดับ %s/%s" % (r["rank"], r["n"])) if r.get("rank") else "")
                    for r in rows],
                   note="อ่าน: จุดน้ำเงินอยู่ขวาของวงกลม = โตเร็วกว่าบริษัทกลางกลุ่ม; แถบเทาคือครึ่งกลางของกลุ่ม ถ้าจุดอยู่นอกแถบ = ต่างจากกลุ่มชัดเจน"), "")
    d.table(["ช่วง", "ทั้งกลุ่ม", "median", "กลุ่มย่อย" + (" (%s)" % s["group"] if s.get("group") else ""), T, "อันดับ", "ห่าง median (จุด)"],
            [[r["label"], p1(r.get("sector"), sign=True), p1(r.get("median"), sign=True), p1(r.get("group"), sign=True), "**%s**" % p1(r.get("stock"), sign=True),
              ("%s / %s" % (r["rank"], r["n"])) if r.get("rank") else "–", "–" if r.get("gap") is None else "%+.1f" % (r["gap"] * 100)] for r in rows],
            align=["l", "r", "r", "r", "r", "r", "r"])
    d.p("_ที่มา: `sector_trend.json` (Jitta factsheet ที่รวบรวมจากงบ, tier 2) กลุ่มหลัก %d บริษัท ไม่รวมบริษัทที่รายได้เปลี่ยนจากการซื้อหรือขายกิจการ; "
        "ใช้ median เพราะบริษัทใหญ่สุดมีน้ำหนักมากในยอดรวม. ตัวเลขของบริษัทในข้ออื่นใช้งบของบริษัทเอง_" % s.get("core_n", 0))
    sv = (nar or {}).get("sector_view") or {}
    if sv.get("position"):
        d.p("**ทำไมอยู่ตรงนี้**")
        d.b.append(("nlist", narrative_items(sv["position"])))
    sig = s.get("signals") or []
    qsig = next((g for g in sig if g["id"] == "quarters"), None)
    if qsig:
        labs = ["%s/%s" % (x[0][-2:], str(int(x[0][:4]) + 543)[-2:]) for x in qsig["seq"]]
        d.raw(line_chart("รายได้รายไตรมาส YoY: %s เทียบ median กลุ่ม (%%)" % T, labs,
                         [(T, [None if x[1] is None else x[1] * 100 for x in qsig["seq"]]),
                          ("median", [None if x[2] is None else x[2] * 100 for x in qsig["seq"]])],
                         colors=["var(--s1)", "var(--muted)"], height=260,
                         note="อ่าน: เส้นน้ำเงินอยู่เหนือเส้นเทา = ไตรมาสนั้นโตเร็วกว่ากลุ่ม; ทิศของ 3 จุดล่าสุดบอกว่ากำลังเร่งหรือชะลอ"), "")
    if sig:
        cards = []
        for g in sig:
            lab, what = SIG_WHAT.get(g["id"], (g["id"], ""))
            cards.append('<div class="%s"><b>%s %s</b><p>%s</p><p class="what">วัดอะไร: %s</p></div>' % (
                g["verdict"], {"better": ARROW_UP, "worse": ARROW_DN}.get(g["verdict"], "●"), esc("%s — %s" % (lab, VERD.get(g["verdict"], g["verdict"]))),
                esc(g["text"]), esc(what)))
        d.raw('<div class="vz-sig">%s</div>' % "".join(cards), "")
        d.table(["สัญญาณ (คำนวณ)", "ทิศทาง", "รายละเอียด"],
                [[SIG_WHAT.get(g["id"], (g["id"],))[0], VERD.get(g["verdict"], g["verdict"]), g["text"]] for g in sig], align=["l", "l", "l"])
    f = s.get("fingerprint")
    if f and f.get("stock"):
        import deepdive_sector as DSEC
        c = f["stock"]
        y = lambda w: "–".join(str(int(x) + 543) for x in w.split("-"))
        d.p("**วงจรหลังโควิด: เงินพิเศษกลายเป็นทุน แล้วไปไหนต่อ** (เทียบ %s กับ %s ตัดปีโควิดออก)" % (y(f["pre"]), y(f["post"])))
        d.table(["ตัวชี้วัด", "%s ก่อน" % T, "%s หลัง" % T, "median ก่อน", "median หลัง"], DSEC._fp_rows(f), align=["l", "r", "r", "r", "r"])
        d.p("_ทั้งกลุ่ม %s จาก %s โรงพยาบาลเดินตามวงจร (ROE ลดเพราะทุนโตเร็วกว่ากำไร); %s %sตามวงจรนี้ ระยะตอนนี้: **%s**_" % (
            f["count"].get("follows_cycle"), f["count"].get("n"), T, "เป็นไป" if c.get("follows_cycle") else "ไม่เป็นไป",
            DSEC.STAGE.get(c.get("stage"), c.get("stage"))))
    if sv.get("leading"):
        d.p("**ตัวชี้นำจากเอกสาร (ขยับก่อนรายได้)**")
        d.b.append(("nlist", narrative_items(sv["leading"])))
    d.p("_สิ่งที่ต้องติดตามจากสัญญาณเหล่านี้รวมไว้ในข้อ 13_")


def _year_of(tag):
    """'2567-Q3' / '2566-05-01' / '2568→2569' / '2024Q3' / 'FY2024' -> BE year string."""
    import re as _re
    m = _re.match(r"(25\d\d)", str(tag))
    if m:
        return m.group(1)
    m = _re.match(r"\d+M(20\d\d)$", str(tag))
    if m:
        return str(int(m.group(1)) + 543)
    m = _re.match(r"(?:FY)?(20\d\d)", str(tag))
    return str(int(m.group(1)) + 543) if m else None


def render_year_events(d, p, nar, narrative_items):
    """Section 2.1: what happened each year — growth next to the events that explain it.
    Sources: data/sector/Hospital/payor_events.json (payor shocks), the one-offs in the assumptions file,
    the COVID window, and narrative `year_events` [{year, text, src, external?}] written from documents."""
    L, fys = p["lines"], list(p["fys"])
    try:
        import sso_pxq as SP
        sdir = p.get("stock_dir") or ""
        ev = SP.load_events(sdir) if sdir else {}
    except Exception:
        ev = {}
    t = p["ticker"]
    by = {}
    def add(y, text, kind):
        if y:
            by.setdefault(y, []).append((kind, text))
    for e in ev.get("events") or []:
        imp = (e.get("impacts") or {}).get(t)
        if not imp and e.get("payor") not in ("สปส.", "สปสช.", "บริษัทประกันชีวิต"):
            continue
        txt = e["text"]
        if imp:
            txt += " — ผลต่อ %s: %s" % (t, "; ".join("%s %s" % (k, ", ".join("%s %+.2f ลบ." % ({"revenue_mn": "รายได้", "np_mn": "กำไร"}.get(a, a), b)
                                                                           for a, b in v.items() if isinstance(b, (int, float))))
                                                 for k, v in imp.items()))
        add(_year_of(e.get("date")), "%s [%s]" % (txt, e.get("src", "")), "payor")
    payor_years = {y for y, v in by.items() if any(k == "payor" and "ผลต่อ %s" % t in tx for k, tx in v)}
    for o in p.get("one_offs") or []:
        y = _year_of(o.get("period"))
        if y in payor_years and "สปส" in (o.get("label") or ""):
            continue                     # already shown as the payor event with the company's figure
        add(y, "รายการพิเศษ %s: %s (หลังภาษี %+.2f ลบ.)" % (o.get("period", ""), o.get("label", ""), o.get("amount_after_tax") or 0), "one_off")
    for it in nar.get("year_events") or []:
        y = str(it.get("year", ""))
        txt = it.get("text", "")
        if it.get("src"):
            txt += " [%s]" % it["src"]
        if it.get("external"):
            txt = '<span style="color: #8B0000; font-weight: bold;">%s</span>' % txt
        add(y, txt, "doc")
    cols = fys + ([p["ytd"]] if p.get("ytd") in L else [])
    rows = []
    for x in cols:
        y = _year_of(x)
        ln = L.get(x, {})
        lab = "ปี %s" % y if x.startswith("FY") else ("%sM/%s" % (x.split("M")[0], y))
        cv = x.startswith("FY") and COVID[0] <= int(x[2:]) <= COVID[1]
        items = list(by.get(y, []))
        if x.startswith("FY") and int(x[2:]) == COVID[1] + 1:
            items.insert(0, ("covid", "ปีแรกหลังโควิด: ฐานปี %d สูงจากรายได้โรคระบาด — รายได้และกำไรที่ลดคือการกลับสู่ระดับปกติ ไม่ใช่ธุรกิจแย่ลง" % (COVID[1] + 543)))
        if cv:
            items.insert(0, ("covid", "ช่วงโควิด: รายได้และกำไรมีรายการจากโรคระบาด (ตรวจ/รักษา/Hospitel) — ไม่ใช่ฐานปกติ"))
        icon = {"payor": "🏛️", "one_off": "⚑", "doc": "•", "covid": "🦠"}
        rows.append([lab, p1(ln.get("rev_g"), sign=True), p1(ln.get("core_np_g"), sign=True), p1(ln.get("gpm")),
                     "<br>".join("%s %s" % (icon[k], tx) for k, tx in items) or "–"])
    d.h(3, "2.1 เหตุการณ์สำคัญรายปี — ตัวเลขข้างเหตุการณ์ที่อธิบายมัน")
    d.table(["ปี", "รายได้ YoY", "กำไรปกติ YoY", "GPM", "เหตุการณ์ (ที่มา)"], rows, align=["l", "r", "r", "r", "l"])
    d.p("_🏛️ = กติกา/อัตราจ่ายของ สปส. สปสช. บริษัทประกัน (data/sector/Hospital/payor_events.json); ⚑ = รายการพิเศษที่ตัดออกจากกำไรปกติ "
        "(assumptions); • = เหตุการณ์จากเอกสารบริษัท (narrative year_events); 🦠 = ช่วงโควิด %d–%d. อ่านการเติบโตของแต่ละปีคู่กับเหตุการณ์ในแถวเดียวกัน "
        "และปีก่อนหน้า (ฐาน) ก่อนสรุปว่าดีหรือแย่_" % (COVID[0] + 543, COVID[1] + 543))


def render_ten_years(d, p):
    """Section 2: ten years at a glance (Jitta)."""
    _css(d)
    j = p.get("jitta10")
    if not j:
        d.p("_ไม่มี Jitta factsheet ของหุ้นนี้ใน `data/Factsheet/` — รัน factsheet ก่อน_")
        return
    R = j["rows"]
    labs = [str(r["y"] + 543) for r in R]
    ys = [r["y"] for r in R]
    band = None
    ci = [i for i, y in enumerate(ys) if COVID[0] <= y <= COVID[1]]
    if ci:
        band = (ci[0], ci[-1])
    a = j["avg"]
    ip = [i for i, y in enumerate(ys) if y in a["pre"]]
    iq = [i for i, y in enumerate(ys) if y in a["post"]]
    def avs(key, scale=100):
        pr, po = a[key]
        out = []
        if ip and pr is not None:
            out.append((ip[0], ip[-1], pr * scale, "%.1f%%" % (pr * scale)))
        if iq and po is not None:
            out.append((iq[0], iq[-1], po * scale, "%.1f%%" % (po * scale)))
        return out
    pct = lambda k: [None if r[k] is None else r[k] * 100 for r in R]
    figs = [small_multiple("รายได้รวม (ล้านบาท)", labs, [r["rev"] for r in R], unit="", kind="bar", band=band),
            small_multiple("การเติบโตของรายได้ (%)", labs, pct("rev_g"), kind="bar", band=band, avgs=avs("rev_cagr"), color="var(--s3)"),
            small_multiple("กำไรขั้นต้น (ล้านบาท)", labs, [r["gp"] for r in R], unit="", kind="bar", band=band, color="var(--s2)"),
            small_multiple("อัตรากำไรขั้นต้น GPM (%)", labs, pct("gpm"), band=band, avgs=avs("gpm")),
            small_multiple("SG&A ต่อรายได้ (%)", labs, pct("sga_pct"), band=band, avgs=avs("sga_pct"), color="var(--s2)"),
            small_multiple("อัตรากำไรสุทธิ NPM (%)", labs, pct("npm"), band=band, avgs=avs("npm"), color="var(--s3)")]
    d.raw('<div class="vz-grid c3">%s</div><p class="src">เส้นประ = ค่าเฉลี่ยช่วงก่อนโควิด (%s) และ 3 ปีล่าสุด (%s); การเติบโตเฉลี่ย = CAGR ภายในช่วง; '
          'แถบเทา = ปีโควิด %d–%d; ที่มา: `%s` (Jitta, ดึงเมื่อ %s, tier 2) — รายได้รวมนับรายได้อื่น GPM จึงสูงกว่าในงบราว 1 จุด</p>' % (
              "".join(figs), "–".join(str(y + 543) for y in (a["pre"][:1] + a["pre"][-1:])), "–".join(str(y + 543) for y in (a["post"][:1] + a["post"][-1:])),
              COVID[0] + 543, COVID[1] + 543, esc(j["src"]), esc(j["fetched"])), "")
    rows = [["รายได้รวม (ลบ.)"] + [n0(r["rev"]) for r in R],
            ["การเติบโต"] + [p1(r["rev_g"], sign=True) for r in R],
            ["กำไรขั้นต้น (ลบ.)"] + [n0(r["gp"]) for r in R],
            ["GPM"] + [p1(r["gpm"]) for r in R],
            ["SG&A ต่อรายได้"] + [p1(r["sga_pct"]) for r in R],
            ["NPM"] + [p1(r["npm"]) for r in R]]
    d.table(["10 ปี (Jitta)"] + labs, rows)
    d.table(["ค่าเฉลี่ย", "ก่อนโควิด", "3 ปีล่าสุด", "เปลี่ยน"],
            [[lab, p1(a[k][0], sign=(k == "rev_cagr")), p1(a[k][1], sign=(k == "rev_cagr")),
              "%s %+.1f จุด" % (arrow(a[k][1], a[k][0], k != "sga_pct"), ((a[k][1] or 0) - (a[k][0] or 0)) * 100)
              if a[k][0] is not None and a[k][1] is not None else "–"]
             for k, lab in (("rev_cagr", "รายได้ CAGR"), ("gpm", "GPM"), ("sga_pct", "SG&A ต่อรายได้ (ลดลง = ดี)"), ("npm", "NPM"))], align=["l", "r", "r", "r"])


def render_mix_half(d, p):
    """Section 3 addition: the latest half-year against the same half a year before, with arrows on baht growth."""
    if not p.get("ytd") or not p.get("ytd_py"):
        return
    a, b = p["ytd_py"], p["ytd"]
    lab = lambda x: "%s/%d" % (x[:2], int(x[2:]) + 543)
    tabs = []
    for rows_src, title in ((p.get("mix_rows") or [], "ตามประเภทผู้ป่วย"), (p.get("nat_rows") or [], "ตามสัญชาติ")):
        rr = [r for r in rows_src if r["id"] != "elim" and (r["vals"].get(a) or r["vals"].get(b))]
        out = []
        for r in rr:
            va, vb = r["vals"].get(a), r["vals"].get(b)
            g = (vb / va - 1) if va and vb else None
            sig = ARROW_UP if g is not None and g > 0 else (ARROW_DN if g is not None and g < 0 else "–")
            sa, sb = r["share"].get(a), r["share"].get(b)
            out.append([r["label"], n0(va), n0(vb), "%s %s" % (p1(g, sign=True), sig if g is not None else ""),
                        p1(sa), p1(sb), ("%+.1f" % ((sb - sa) * 100)) if sa is not None and sb is not None else "–"])
        if out:
            tabs.append((title, out))
    if tabs:
        d.h(3, "3.1 ครึ่งปีล่าสุด %s เทียบ %s" % (lab(b), lab(a)))
        for title, out in tabs:
            d.table(["รายได้%s (ลบ.)" % title, lab(a), lab(b), "โต YoY", "สัดส่วน %s" % lab(a), "สัดส่วน %s" % lab(b), "จุด"], out,
                    align=["l", "r", "r", "r", "r", "r", "r"])
        d.p("_สัญญาณวัดจากรายได้เป็นบาทที่เพิ่มหรือลด (กติกาเจ้าของ 10 ต.ค. 2569): เพิ่ม = ▲ เขียว, ลด = ▼ แดง; ประกันสังคมที่เพิ่มนับเป็นบวก "
            "เพราะฐานลูกค้าโตและต่อยอดไปลูกค้าเงินสดได้; สัดส่วน % แสดงประกอบ; จุด = สัดส่วนที่เปลี่ยน (percentage points)_")


def render_hospital_pnl(d, p):
    """Section 3 addition: P&L by hospital from the subsidiaries' own filings (DBD)."""
    hb = p.get("hospitals") or {}
    db = hb.get("dbd_pnl")
    if not db:
        return
    _css(d)
    names = hb.get("hospitals") or {}
    sites = hb.get("sites") or {}
    keys = [k for k in (hb.get("keys") or []) if k in db["hospitals"]] or list(db["hospitals"])
    Y = db["years"]
    y1, y0 = Y[-1], Y[-2]
    yrs = hb.get("years") or {}
    def npx(k, y):
        v = ((yrs.get(y) or {}).get("np_ex_dividend") or {}).get(k)
        return v if v is not None else db["hospitals"][k]["np"].get(y)
    d.h(3, "3.2 งบกำไรขาดทุนรายโรงพยาบาล ปี %s (เทียบ %s)" % (y1, y0))
    rows = []
    for lab, f in (("รายได้ค่ารักษา", "rev_main"), ("ต้นทุน", "cogs"), ("กำไรขั้นต้น", "gp"), ("GPM", "gpm"), ("SG&A", "sga"), ("SG&A ต่อรายได้", "sga_pct"),
                   ("ดอกเบี้ยจ่าย", "interest"), ("กำไรสุทธิ*", "np"), ("NPM", "npm")):
        row = [lab]
        for k in keys:
            h = db["hospitals"][k]
            def val(y):
                rv = h["rev_main"].get(y)
                if f == "gpm":
                    return h["gp"].get(y) / rv if rv else None
                if f == "sga_pct":
                    return h["sga"].get(y) / rv if rv else None
                if f == "np":
                    return npx(k, y)
                if f == "npm":
                    n = npx(k, y)
                    return n / rv if rv and n is not None else None
                return h[f].get(y)
            c, pv = val(y1), val(y0)
            good_up = f not in ("cogs", "sga", "sga_pct", "interest")
            ar = arrow(c, pv, good_up)
            row.append(("%s %s" % (p1(c), ar)) if f in ("gpm", "sga_pct", "npm") else ("%s %s" % (n0(c) if c is None or abs(c) >= 10 else "%.1f" % c, ar)))
        rows.append(row)
    d.table(["ล้านบาท"] + [sites.get(k, {}).get("short") or names.get(k, k) for k in keys], rows, align=["l"] + ["r"] * len(keys),
            bold_rows=[2, 7])
    d.p("_ลูกศรบอกทิศทางเทียบปี %s (▲ เพิ่ม, ▼ ลด); สีบอกผล: เขียว = ดีขึ้น, แดง = แย่ลง (ต้นทุน SG&A ดอกเบี้ยที่เพิ่ม = ▲ แดง). *กำไรสุทธิไม่รวมเงินปันผลรับจากบริษัทย่อย. ที่มา: %s. %s_" % (y0, db.get("src", ""), db.get("note", "")))
    gl = [(sites.get(k, {}).get("short") or names.get(k, k), [None if not db["hospitals"][k]["rev_main"].get(y) or db["hospitals"][k]["gp"].get(y) is None else
                                                             db["hospitals"][k]["gp"][y] / db["hospitals"][k]["rev_main"][y] * 100 for y in Y]) for k in keys]
    d.raw(line_chart("GPM รายโรงพยาบาล %s–%s (%%)" % (Y[0], Y[-1]), Y, gl, height=260,
                     note="กำไรขั้นต้น = รายได้ค่ารักษา − ต้นทุน [คำนวณ] จากงบแต่ละนิติบุคคลที่ยื่นกรมพัฒนาธุรกิจการค้า"), "")
    d.table(["GPM"] + Y, [[nm] + [p1(None if v is None else v / 100) for v in vs] for nm, vs in gl])


def render_valuation(d, p):
    """Section 11: P/E, EV/EBITDA, ROIC — multiples only, no target price."""
    m = p.get("market") or {}
    v = (p.get("expect") or {}).get("valuation") or {}
    L, fys = p["lines"], p["fys"]
    fy = fys[-1]
    ln = L[fy]
    price, sh = m.get("price"), m.get("shares_mn")
    mcap = price * sh if price and sh else None
    nc = ln.get("net_cash")
    ev = mcap - nc if mcap is not None and nc is not None else None
    eb = ln.get("ebitda")
    rows = [["ราคา (บาท) ณ %s" % m.get("as_of", "–"), n0(price) if price and price >= 100 else ("%.2f" % price if price else "–"), m.get("source", "")],
            ["มูลค่าตลาด (ลบ.)", n0(mcap), "ราคา × %s ล้านหุ้น" % ("%.2f" % sh if sh else "–")],
            ["เงินสดสุทธิ ปี %s (ลบ.)" % (int(fy[2:]) + 543), n0(nc), "เงินสดและเงินลงทุนระยะสั้น − หนี้สินที่มีดอกเบี้ยและสัญญาเช่า"],
            ["EV (ลบ.)", n0(ev), "มูลค่าตลาด − เงินสดสุทธิ"],
            ["EBITDA ปี %s (ลบ.)" % (int(fy[2:]) + 543), n0(eb), "งบรวม"],
            ["**EV/EBITDA**", "**%s**" % ("%.1f เท่า" % (ev / eb) if ev is not None and eb else "–"), "[คำนวณ]"],
            ["**P/E กำไรปกติ TTM**", "**%s**" % ("%.1f เท่า" % v["pe"] if v.get("pe") else "–"), "กำไรปกติ 4 ไตรมาสล่าสุด"],
            ["P/E กำไรปีล่าสุด", "%.1f เท่า" % (mcap / ln["np_owners"]) if mcap and ln.get("np_owners") else "–", "กำไรสุทธิส่วนของบริษัทใหญ่ ปี %s" % (int(fy[2:]) + 543)],
            ["PEG (TTM / CAGR จากฐาน)", "%s / %s" % ("%.2f" % v["peg"] if v.get("peg") else "–", "%.2f" % v["peg_cagr3"] if v.get("peg_cagr3") else "–"), v.get("label", "")],
            ["Earnings yield / Dividend yield", "%s / %s" % (p1(v.get("earn_yield")), p1(v.get("yield"))), "DPS %s บาท" % m.get("dps_last_fy", "–")]]
    d.table(["มูลค่า", "ค่า", "หมายเหตุ"], rows, align=["l", "r", "l"])
    d.table(["ผลตอบแทนต่อเงินทุน"] + [str(int(x[2:]) + 543) for x in fys],
            [["ROIC"] + [p1(L[x].get("roic")) for x in fys], ["ROE"] + [p1(L[x].get("roe")) for x in fys],
             ["EBITDA margin"] + [p1(L[x].get("ebitda_m")) for x in fys]])
    pr = [r for r in p.get("peers") or [] if r.get("ticker") != p["ticker"] and (r.get("pe") or r.get("peg"))]
    if pr:
        d.table(["คู่แข่ง", "P/E TTM", "PEG", "ROE", "GPM"],
                [[r["ticker"], "%.1f" % r["pe"] if r.get("pe") else "–", "%.2f" % r["peg"] if r.get("peg") else "–", p1(r.get("roe")), p1(r.get("gpm"))] for r in pr],
                align=["l", "r", "r", "r", "r"])
    d.p("_ตามกฎของรายงาน: แสดง multiple เทียบกับผลตอบแทนและคู่แข่งเท่านั้น ไม่มีราคาเป้าหมายหรือคำแนะนำซื้อขาย; ราคาเป้าหมายของโบรกเกอร์ไม่นำมาใช้_")


def render_open_questions(d, p, nar):
    """Section 13: what the documents could not answer, and what to watch."""
    nar = nar or {}
    if nar.get("pending"):
        d.h(3, "13.1 คำถามที่ยังไม่มีคำตอบ")
        d.table(["#", "คำถาม", "ทำไมสำคัญ", "หาคำตอบได้จาก", "ตั้งเมื่อ"],
                [[str(i + 1), q.get("question", ""), q.get("why", ""), q.get("where", "–"), q.get("raised", "–")] for i, q in enumerate(nar["pending"])],
                align=["l", "l", "l", "l", "l"])
        d.p("_คำถามในตารางนี้คงอยู่ในรายงานฉบับถัดไปจนกว่าจะมีเอกสารมาปิด_")
    from render import item_text
    watch = []
    for src_lab, items in (("สัญญาณล่วงหน้า (ข้อ 1)", ((nar.get("sector_view") or {}).get("watch") or [])),
                           ("จุดชี้ชะตา (ข้อ 9)", ((nar.get("pivot") or {}).get("watch") or []))):
        for it in items:
            t, s, ext = item_text(it)
            watch.append([src_lab, t, s or "–"])
    if watch:
        d.h(3, "13.2 สิ่งที่ต้องติดตาม")
        d.table(["มาจาก", "ติดตามอะไร / จะเห็นที่ไหน", "แหล่งที่มา"], watch, align=["l", "l", "l"])
    if not nar.get("pending") and not watch:
        d.p("_ยังไม่มีคำถามค้างหรือรายการติดตาม — ต้องเขียน `pending` และ `sector_view.watch` ใน narrative_")
