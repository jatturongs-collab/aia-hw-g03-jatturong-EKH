#!/usr/bin/env python3
"""
oppday_ops.py - read operating metrics from Opportunity Day slide PDFs by position. Script only, no tokens.

Why: the slide text survives in the PDF, but in the .md copy the numbers lose their labels (a column of
"74.50% 53.38% 81.42% ..."). On the page every word still has coordinates, so a value can be tied back to
the period label under it (x) and to the chart it sits in (y).

    python3 oppday_ops.py --stock-dir "<Thstock>/VIH" --ticker VIH
    python3 oppday_ops.py --stock-dir "<Thstock>/VIH" --ticker VIH --dump 2026_Q2     # show every chart found

Input : <stock>/set/oppday/oppday_<CE>_Q<q>_*.pdf
Output: <stock>/report/<T>_ops_metrics.json
  metrics   named series this script recognises by chart title (see KNOWN): for each period
            {"v": value, "src": "<file>:p<page>"}; newest deck first, older decks only where they agree
  charts    every chart / table with a period axis that was read, named or not (other hospitals show other
            things: foreign patients, centres, payors) - for the narrative to cite
  superseded older decks whose figures for a shared period differ from newer decks (the company restated the
            series: another bed base, visits vs persons); kept apart, never joined to "metrics"
  derived   computed here, not disclosed: the capacity each rate was computed on (beds = inpatient days /
            (occupancy x days in the period); OPD capacity per day likewise)
  base_checks a quarter whose implied capacity differs from both neighbours by more than 10% (a slide that used
            another year's bed count); replaced by an older deck's figure when that one fits, else kept and marked
  gaps      charts that failed the self-checks and were left out

Rules (same as the rest of the skill): a value is tied to exactly one period label or it is dropped; a rate
series is accepted only when every column has one; a "YoY" marker is recognised by arithmetic, not by guess.
Period keys match <T>_financials.json: FY2025, 6M2026, 2026Q2 (Christian era).
"""
import argparse
import calendar
import datetime as dt
import glob
import json
import os
import re
import sys

try:
    import pymupdf
except ImportError:                                   # older package name
    try:
        import fitz as pymupdf
    except ImportError:
        pymupdf = None

RE_PERIOD = re.compile(r"^(?:(Q[1-4]|[1-4]Q|3M|6M|9M|12M|H[12]|FY)\s*[/ ]?\s*)?((?:25|20)\d\d)$", re.I)
RE_NUM = re.compile(r"^\(?[-−–]?\d[\d,]*(?:\.\d+)?\)?%?$")
RE_UNIT = re.compile(r"หน\S*วย\s*:|^unit\s*:", re.I)
RE_SKIP = re.compile(r"^(yoy|qoq|cagr|%yoy|\+/\(-\)|\.)$", re.I)
_MARK = re.compile("[ัิ-ฺ็-๎​-‍]")

# chart title (folded) -> (key of the bar series, key of the rate series)
KNOWN = [
    (r"opd patients and utili|ผปวยนอกและอตราการใช", ("opd_visits", "opd_utilization_pct")),
    (r"ipd patients and occupancy|วนนอนผปวยในและอตราครองเตยง", ("ipd_days", "occupancy_pct")),
    (r"per billing\s*:\s*opd|ตอใบเสรจสาหรบผปวยนอก", ("per_bill_opd_baht", None)),
    (r"per billing\s*:\s*ipd|ตอใบเสรจสาหรบผปวยใน", ("per_bill_ipd_baht", None)),
    (r"total revenue and external", ("total_revenue_mn", None)),
]


def fold(s):
    """Lower-case, drop Thai marks and the stray ASCII letters legacy fonts leave inside Thai words."""
    s = _MARK.sub("", s.replace("ำ", "า"))
    s = re.sub(r"(?<=[฀-๿])[a-z](?=[฀-๿\s]|$)", "", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def period_key(text):
    m = RE_PERIOD.match(text.strip())
    if not m:
        return None
    pre, y = (m.group(1) or "FY").upper(), int(m.group(2))
    y = y - 543 if y > 2400 else y
    if not 2005 <= y <= 2040:
        return None
    if re.match(r"Q[1-4]$", pre):
        return "%dQ%s" % (y, pre[1])
    if re.match(r"[1-4]Q$", pre):
        return "%dQ%s" % (y, pre[0])
    if pre in ("FY", "12M"):
        return "FY%d" % y
    if pre == "3M":
        return "%dQ1" % y
    return "%s%d" % ("6M" if pre == "H1" else pre, y)


def kind_of(key):
    return "FY" if key.startswith("FY") else (key[:2] if key[1] == "M" else "Q" + key[-1])


def year_of(key):
    return int(re.search(r"\d{4}", key).group())


def to_num(t):
    neg = t.startswith("(") or t.lstrip("(")[:1] in "-−–"
    v = float(re.sub(r"[^\d.]", "", t))
    return -v if neg else v


def page_items(page):
    """Words joined into short runs: same block+line, split where the gap is wide (two axis labels in one line)."""
    runs, cur = [], None
    for x0, y0, x1, y1, w, b, ln, _ in page.get_text("words"):
        size = y1 - y0
        if cur and cur["k"] == (b, ln) and x0 - cur["x1"] < max(12, size * 0.9):
            cur["t"] += " " + w
            cur["x1"], cur["y1"] = x1, max(cur["y1"], y1)
        else:
            cur = {"k": (b, ln), "t": w, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "size": size}
            runs.append(cur)
    for r in runs:
        r["cx"], r["cy"] = (r["x0"] + r["x1"]) / 2, (r["y0"] + r["y1"]) / 2
        r["t"] = re.sub("[\u200b-\u200d\ufeff]", "", r["t"]).strip()      # zero-width marks around table cells
        t = r["t"]
        r["period"] = period_key(t)
        r["num"] = None if r["period"] else (to_num(t) if RE_NUM.match(t) and re.search(r"\d", t) else None)
        r["pct"] = t.endswith("%") or t.endswith("%)")
    return runs


def axis_rows(items):
    """Rows of period labels (>=2 at the same height), each split into charts where a period repeats."""
    per = sorted((i for i in items if i["period"]), key=lambda i: (round(i["cy"] / 8), i["cx"]))
    rows = []
    for i in per:
        if rows and abs(rows[-1][-1]["cy"] - i["cy"]) < 8:
            rows[-1].append(i)
        else:
            rows.append([i])
    out = []
    for row in rows:
        row.sort(key=lambda i: i["cx"])
        charts, cur, seen = [], [], set()
        for i in row:
            if i["period"] in seen:
                charts.append(cur)
                cur, seen = [], set()
            cur.append(i)
            seen.add(i["period"])
        charts.append(cur)
        out.append((sum(i["cy"] for i in row) / len(row), [c for c in charts if len(c) >= 2]))
    return [(y, cs) for y, cs in out if cs]


def stack(vals):
    """Bar labels in one column: one value, or a total with its parts (stacked bar)."""
    u = []
    for v, y in sorted(vals, key=lambda t: t[1]):           # top of page first
        if not any(abs(v - w) < 1e-9 for w, _ in u):
            u.append((v, y))
    if len(u) > 1:
        u = [t for t in u if t[0] != 0]                     # a "0" axis tick under the first bar
    if len(u) == 1:
        return {"v": u[0][0]}
    nums = [v for v, _ in u]
    top = max(nums)
    rest = [v for v in nums if v != top]
    if abs(sum(rest) - top) <= max(0.02, top * 0.0005):
        return {"v": top, "parts_top_down": [v for v, _ in u if v != top]}
    return {"ambiguous": nums}


def read_chart(labels, items, y_top, y_axis, x_lo, x_hi, page_h, split=False):
    cols = [l["cx"] for l in labels]
    gap = min(b - a for a, b in zip(cols, cols[1:]))
    tol = min(gap * 0.5, 70)
    lo, hi = max(x_lo, cols[0] - tol * 1.6), min(x_hi, cols[-1] + tol * 1.6)

    def column(i):
        d = [abs(i["cx"] - c) for c in cols]
        k = d.index(min(d))
        return k if d[k] <= tol else None

    above = [i for i in items if i["num"] is not None and y_top < i["cy"] < y_axis - 4]
    mode, body = "chart", above
    if sum(1 for i in above if column(i) is not None and not i["pct"]) < len(cols):
        mode = "table"
        body = [i for i in items if i["num"] is not None and y_axis + 4 < i["cy"] < page_h]
    res = {"mode": mode, "periods": [l["period"] for l in labels]}
    texts = [i for i in items if i["num"] is None and not i["period"] and not RE_SKIP.match(i["t"].strip())
             and re.search(r"[A-Za-z฀-๿]{3}", i["t"])]
    if mode == "table":
        rows = {}
        for i in body:
            k = column(i)
            if k is not None:
                rows.setdefault(round(i["cy"] / 6), {})[labels[k]["period"]] = i["num"]
        out = []
        for ry, vals in sorted(rows.items()):
            if len(vals) < len(cols):
                continue
            lab = [t for t in texts if abs(t["cy"] - ry * 6) < 9 and t["x1"] < cols[0]]
            if lab:
                out.append({"label": " ".join(t["t"] for t in sorted(lab, key=lambda t: t["x0"])), "values": vals})
        res["rows"] = out
        head = [t for t in texts if t["cy"] < y_axis - 12]
    else:
        bars, pcts = {}, {}
        for i in body:
            k = column(i)
            if k is None:
                continue
            (pcts if i["pct"] else bars).setdefault(k, []).append((i["num"], i["cy"]))
        if len(bars) < len(cols):
            return None, "bars for %d of %d periods" % (len(bars), len(cols))
        series = {k: stack(v) for k, v in bars.items()}
        if any("ambiguous" in s for s in series.values()):
            return None, "more than one unrelated bar label in a column"
        res["bars"] = {labels[k]["period"]: series[k] for k in sorted(series)}
        # a percent in a column is a YoY marker when it equals the growth of that column's bar on the same
        # kind of period one year earlier; what is left is a rate series, accepted only if every column has one
        by_p = {labels[k]["period"]: series[k]["v"] for k in series}
        rate, yoy = {}, {}
        for k, lst in pcts.items():
            p = labels[k]["period"]
            prev = next((q for q in by_p if kind_of(q) == kind_of(p) and year_of(q) == year_of(p) - 1), None)
            g = (by_p[p] / by_p[prev] - 1) * 100 if prev and by_p[prev] else None
            for v, _ in lst:
                if g is not None and abs(v - g) < 0.06:
                    yoy[p] = v
                else:
                    rate.setdefault(p, []).append(v)
        if yoy:
            res["yoy_pct"] = yoy
        if rate:
            if len(rate) == len(cols) and all(len(v) == 1 for v in rate.values()):
                res["rate_pct"] = {p: v[0] for p, v in rate.items()}
            else:
                res["unassigned_pct"] = rate
        top = min([i["cy"] for i in body if column(i) is not None] or [y_axis])
        head = [t for t in texts if t["cy"] < top + 6 and t["cy"] > y_top]
    head = [t for t in head if lo - 260 <= t["cx"] <= hi + 40]
    unit = next((t["t"] for t in texts if RE_UNIT.search(t["t"]) and y_top < t["cy"] < y_axis and lo - 260 <= t["cx"] <= hi), None)
    head = [t for t in head if not RE_UNIT.search(t["t"])]
    # several charts side by side: the chart's own title is the nearest line above it, not the page title
    head.sort(key=(lambda t: -t["cy"]) if split else (lambda t: (-round(t["size"]), t["cy"])))
    res["unit"] = unit
    res["titles"] = [t["t"] for t in head[:3]]
    return res, None


def read_pdf(path):
    doc = pymupdf.open(path)
    charts, gaps = [], []
    for pno, page in enumerate(doc, 1):
        items = page_items(page)
        rows = axis_rows(items)
        if not rows:
            continue
        w, h = page.rect.width, page.rect.height
        tx = [i for i in items if i["num"] is None and not i["period"] and re.search(r"[A-Za-z฀-๿]{4}", i["t"])]
        page_title = min(tx, key=lambda t: t["cy"])["t"] if tx else ""
        for r, (y_axis, cs) in enumerate(rows):
            y_top = rows[r - 1][0] + 6 if r else 0
            for c, labels in enumerate(cs):
                x_lo = (cs[c - 1][-1]["cx"] + labels[0]["cx"]) / 2 if c else 0
                x_hi = (labels[-1]["cx"] + cs[c + 1][0]["cx"]) / 2 if c + 1 < len(cs) else w
                sub = [i for i in items if x_lo <= i["cx"] <= x_hi]
                y_end = rows[r + 1][0] - 6 if r + 1 < len(rows) else h
                res, why = read_chart(labels, sub, y_top, y_axis, x_lo, x_hi, y_end, split=len(cs) > 1)
                src = "%s:p%d" % (os.path.basename(path), pno)
                if not res:
                    gaps.append({"src": src, "page_title": page_title, "why": why})
                    continue
                if res["mode"] == "table" and not res["rows"]:
                    continue
                res.update({"src": src, "page_title": page_title, "split": len(cs) > 1})
                charts.append(res)
    return charts, gaps


def name_of(ch):
    for t in ch["titles"] + [ch["page_title"]]:
        f = fold(t)
        for rx, keys in KNOWN:
            if re.search(rx, f):
                return keys
    return None


def deck_order(path):
    m = re.search(r"oppday_(\d{4})_Q(\d)", os.path.basename(path))
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def same(a, b, pct):
    """Equal apart from rounding (1,693.35 in one deck, 1,693 in the next)."""
    return abs(a - b) <= (0.011 if pct else max(0.5, abs(b) * 0.001))


def resolve(readings, pct):
    """Hospitals restate these series (bed base, visits vs persons, what a "bill" is). Start from the newest
    deck and walk back: an older deck adds its extra periods only if every period it shares with what is
    already accepted agrees; otherwise its figures follow another definition and are set aside, not mixed in."""
    acc, aside = {}, []
    for order, src, vals in sorted(readings, key=lambda r: r[0], reverse=True):
        shared = [p for p in vals if p in acc]
        bad = [p for p in shared if not same(vals[p], acc[p]["v"], pct)]
        if not acc or (shared and not bad):
            for p, v in vals.items():
                acc.setdefault(p, {"v": v, "src": src})
        else:
            ex = bad[0] if bad else None
            aside.append({"src": src, "why": "restated: %s was %s here, %s in %s" % (ex, vals[ex], acc[ex]["v"], acc[ex]["src"]) if ex
                          else "no period in common with newer decks, definition cannot be confirmed",
                          "values": vals})
    return acc, aside


def period_days(key):
    """Calendar days in a period key (2026Q2, 6M2026, 9M2026, FY2026)."""
    y = year_of(key)
    m = lambda a_, b_: sum(calendar.monthrange(y, i)[1] for i in range(a_, b_ + 1))
    if key.startswith("FY"):
        return m(1, 12)
    if key[1] == "M":
        return m(1, int(key[0]))
    q = int(key[-1])
    return m(3 * q - 2, 3 * q)


BASES = [("occupancy_pct", "ipd_days", "implied_beds"), ("opd_utilization_pct", "opd_visits", "implied_opd_capacity_per_day")]


def implied_base(volume, rate, per):
    """The capacity a rate was computed on: volume / (rate x days). For occupancy this is the bed count."""
    return volume / (rate / 100.0 * period_days(per)) if rate else None


def check_bases(metrics, superseded):
    """A rate is volume / capacity, so volume and rate give back the capacity the company used. Capacity moves in
    steps (a ward opens or closes); one quarter whose implied capacity differs from BOTH neighbours by more than
    10% while the neighbours agree is a slide error, not a step. If an older deck has a figure for that quarter
    whose capacity matches the neighbours, that figure is used instead and the swap is recorded."""
    derived, checks = {}, []
    for rate_k, vol_k, name in BASES:
        rate, vol = metrics.get(rate_k) or {}, metrics.get(vol_k) or {}
        qs = sorted(p for p in rate if p in vol and re.fullmatch(r"\d{4}Q[1-4]", p))
        base = {p: implied_base(vol[p]["v"], rate[p]["v"], p) for p in qs}
        def outliers():
            for i, p in enumerate(qs):
                nb = [base[q] for q in (qs[i - 1] if i else None, qs[i + 1] if i + 1 < len(qs) else None) if q]
                if len(nb) == 2 and abs(nb[0] / nb[1] - 1) <= 0.10 and all(abs(base[p] / n - 1) > 0.10 for n in nb):
                    yield p, nb

        # first replace every outlier that an older deck can correct (one fix can clear its neighbour), then
        # report what is still out of line
        done = set()
        while True:
            fixed = False
            for p, nb in list(outliers()):
                ref = sum(nb) / 2
                alt = next(({"v": a_["values"][p], "src": a_["src"]} for a_ in superseded.get(rate_k) or []
                            if a_["values"].get(p) and abs(implied_base(vol[p]["v"], a_["values"][p], p) / ref - 1) <= 0.03), None)
                if alt and p not in done:
                    checks.append({"metric": rate_k, "period": p, "slide": dict(rate[p]), "implied": round(base[p], 1),
                                   "neighbours": [round(n, 1) for n in nb], "used": alt,
                                   "action": "replaced: the newest deck's figure implies a capacity of %.0f, the quarters on both sides %.0f; "
                                             "an older deck's %s matches them" % (base[p], ref, alt["v"])})
                    rate[p] = dict(alt, note="chosen over %s (%s) by the capacity check" % (rate[p]["v"], rate[p]["src"]))
                    base[p] = implied_base(vol[p]["v"], alt["v"], p)
                    done.add(p)
                    fixed = True
                    break
            if not fixed:
                break
        for p, nb in outliers():
            checks.append({"metric": rate_k, "period": p, "slide": dict(rate[p]), "implied": round(base[p], 1),
                           "neighbours": [round(n, 1) for n in nb],
                           "action": "kept, but suspect: implied capacity %.0f against %.0f on both sides, and no other deck gives another figure" % (
                               base[p], sum(nb) / 2)})
        for p in sorted(rate):                                  # also the YTD and annual periods
            if p in vol and p not in base:
                base[p] = implied_base(vol[p]["v"], rate[p]["v"], p)
                y = year_of(p)
                n = 4 if p.startswith("FY") else int(p[0]) // 3
                part = [base[q] for q in ("%dQ%d" % (y, k) for k in range(1, n + 1)) if q in base]
                if len(part) == n and base[p] and not min(part) * 0.95 <= base[p] <= max(part) * 1.05:
                    checks.append({"metric": rate_k, "period": p, "slide": dict(rate[p]), "implied": round(base[p], 1),
                                   "neighbours": [round(x, 1) for x in part],
                                   "action": "kept, but suspect: implied capacity %.0f is outside its own quarters' %.0f-%.0f" % (
                                       base[p], min(part), max(part))})
        derived[name] = {p: {"v": round(v, 1), "calc": "%s / (%s x %d days)" % (vol_k, rate_k, period_days(p))}
                         for p, v in sorted(base.items()) if v}
    return derived, checks


def build(sdir, ticker, only=None):
    pdfs = sorted(glob.glob(os.path.join(sdir, "set", "oppday", "oppday_*.pdf")), key=deck_order)
    if only:
        pdfs = [p for p in pdfs if only in os.path.basename(p)]
    readings, charts, gaps, used = {}, [], [], []
    for p in pdfs:
        try:
            cs, gs = read_pdf(p)
        except Exception as e:                                  # a damaged PDF must not stop the others
            gaps.append({"src": os.path.basename(p), "why": "cannot read: %s" % e})
            continue
        used.append(os.path.basename(p))
        gaps += gs
        for ch in cs:
            keys = name_of(ch) if ch["mode"] == "chart" else None
            if keys and ch.get("split"):
                # a period shown twice on one axis (reported and "excluding ..." columns): not a clean series
                gaps.append({"src": ch["src"], "page_title": ch["page_title"], "why": "%s: a period appears twice on the axis (adjusted columns) - read by hand" % keys[0]})
                keys = None
            ch["metric"] = [k for k in keys if k] if keys else None
            charts.append(ch)
            if not keys:
                continue
            pairs = [(keys[0], {p_: b["v"] for p_, b in ch["bars"].items()})]
            if keys[1]:
                if "rate_pct" in ch:
                    pairs.append((keys[1], ch["rate_pct"]))
                else:
                    gaps.append({"src": ch["src"], "page_title": ch["page_title"], "why": "%s: not one rate per period" % keys[1]})
            for key, vals in pairs:
                readings.setdefault(key, []).append((deck_order(p), ch["src"], vals))
    metrics, superseded = {}, {}
    for key, rs in sorted(readings.items()):
        acc, aside = resolve(rs, key.endswith("_pct"))
        metrics[key] = dict(sorted(acc.items()))
        if aside:
            superseded[key] = aside
    derived, base_checks = check_bases(metrics, superseded)
    return {"ticker": ticker, "generated": dt.date.today().isoformat(), "sources": used,
            "note": "Read by position from Opportunity Day slides (tier 1). Period keys as in %s_financials.json. "
                    "'superseded' holds older decks whose figures differ from newer decks; do not join them to 'metrics'. "
                    "'derived' is computed here (capacity = volume / rate / days), not disclosed by the company." % ticker,
            "metrics": metrics, "derived": derived, "base_checks": base_checks, "superseded": superseded, "gaps": gaps, "charts": charts}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stock-dir", required=True)
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--dump", help="print every chart read from decks whose file name contains this text; write nothing")
    a = ap.parse_args()
    if pymupdf is None:
        sys.exit("needs PyMuPDF: pip install pymupdf")
    out = build(a.stock_dir, a.ticker, a.dump)
    if a.dump:
        for ch in out["charts"]:
            print(ch["src"], "|", ch["mode"], "|", ch["metric"], "|", ch["titles"][:2], "|", ch.get("unit"))
            for k in ("bars", "rate_pct", "yoy_pct", "unassigned_pct", "rows"):
                if ch.get(k):
                    print("    %s: %s" % (k, json.dumps(ch[k], ensure_ascii=False)))
        for g in out["gaps"]:
            print("GAP", g)
        return
    dst = os.path.join(a.stock_dir, "report", "%s_ops_metrics.json" % a.ticker)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    json.dump(out, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("%d decks, %d charts, %d named series, %d gaps -> %s" % (
        len(out["sources"]), len(out["charts"]), len(out["metrics"]), len(out["gaps"]), dst))
    for k, v in out["superseded"].items():
        for a_ in v:
            print("  set aside %-20s %s  (%s)" % (k, a_["src"], a_["why"]))
    for c in out["base_checks"]:
        print("  capacity check %s %s: %s" % (c["metric"], c["period"], c["action"]))
    for k, v in out["derived"].items():
        qs = [p for p in sorted(v) if "Q" in p][-6:]
        print("  %-28s %s" % (k, "  ".join("%s=%.0f" % (p, v[p]["v"]) for p in qs)))
    for k, v in out["metrics"].items():
        last = sorted(v)[-3:]
        print("  %-22s %3d periods   %s" % (k, len(v), "  ".join("%s=%s" % (p, v[p]["v"]) for p in last)))


if __name__ == "__main__":
    main()
