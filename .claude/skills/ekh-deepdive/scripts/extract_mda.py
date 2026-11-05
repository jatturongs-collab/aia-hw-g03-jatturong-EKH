#!/usr/bin/env python3
"""
extract_mda.py - pull the hospital revenue mix out of the MD&A text (md/raw/combined_mda_all.md).

What it reads, per MD&A document ("# DOCUMENT: MDA_Year2569_Q2.pdf"):
  * revenue by patient type   : OPD, IPD, SSO (capitation), inter-company eliminations, non-capitation subtotal
  * revenue by nationality    : Thai, foreign                      (Category-1 hospitals such as PR9, BCH)
  * hospital revenue / other income / total revenue rows (used for the self-check)

Each value keeps its provenance ("MDA_Year2569_Q2:L4689 current").  Current-period columns win over the
prior-year comparative column of a later document.  Q4 is taken from the Q4 MD&A when it shows a
3-month column; otherwise Q4 = FY - 9M and is marked "derived".

Every period is reconciled:  OPD + IPD + SSO - elim  (or Thai + foreign)  must equal the hospital revenue
reported in the financial statements (<T>_financials.json, C|rev_hosp) within +/-1 THB mn.  Periods that
do not reconcile are reported and are NOT written into the assumptions file.

Usage
  python3 extract_mda.py --stock-dir "$S" --ticker VIH -f "$S/report/VIH_financials.json" -o "$S/report/VIH_mda.json"
  # also merge into the finance-sheet assumptions (fills only periods that are missing there):
  python3 extract_mda.py ... --merge-assumptions "$S/report/VIH_assumptions.json"

Output JSON
  {"ticker", "generated", "source", "periods": {"2026Q2": {"opd": {"v":..,"src":..}, ...}},
   "recon": {"2026Q2": {"calc":.., "reported":.., "diff":.., "status": "PASS|FAIL|NO_REPORTED"}},
   "revenue_mix": {<finance-sheet schema: quarterly/annual with opd/ipd/sso/elim>},
   "nationality": {"quarterly": {"2026Q2": {"thai":.., "foreign":..}}, "annual": {...}},
   "flags": [...]}
"""
import argparse, json, os, re, sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    from extract_financials import thai_fold
except Exception:  # standalone fallback
    _M = re.compile("[ัิ-ื็-์๎-​-‍�]")

    def thai_fold(s):
        return _M.sub("", s.replace("ํา", "ำ"))


def fold(s):
    s = thai_fold(s.replace("‌", ""))
    # legacy-font damage leaves single ASCII letters inside Thai words (ผู้ปdวย, ทั่cไป) - drop them
    s = re.sub(r"(?<=[฀-๿])[a-z](?=[฀-๿\s]|$)", "", s)
    s = re.sub(r"(?<=[ก-ฮ])\s+(?=ำ)", "", s)      # "จ ำนวน" -> "จำนวน"
    s = s.replace("ำ", "า")          # PDF damage writes า as ำ (รำยได้จำก): fold both to า
    s = re.sub(r"(?<=[฀-๿])[\u00c0-\u00ff](?=[฀-๿]|$)", "", s)   # legacy-font glyphs (ทัÉวไป)
    return re.sub(r"\s+", " ", s).strip()


def P(*pats):
    return [re.compile(fold(p), re.I) for p in pats]


# Row labels.  Order matters: first match wins.  Patterns are folded like the text.
ROWS = [
    ("opd",     P(r"\(OPD\)", r"ผู้ป่วยนอก", r"^OPD\b")),
    ("ipd",     P(r"\(IPD\)", r"ผู้ป่วยใน(?!โครงการ)", r"^IPD\b")),
    ("gov_total", P(r"สวัสดิการภาครัฐ", r"^รวม.*ภาครัฐ")),
    ("sso",     P(r"ประกันสังคม", r"\bSSO\b", r"social security")),
    ("gov",     P(r"สปสช", r"บัตรทอง", r"หลักประกันสุขภาพ", r"ข้าราชการ", r"ภาครัฐอื่น", r"\bUCS?\b", r"universal coverage")),
    ("elim",    P(r"รายการระหว่างกัน", r"eliminat")),
    ("noncap_total", P(r"^รวม.*(ทั่วไป|เงินสด)")),
    ("contract", P(r"คู่สัญญา", r"contract")),
    ("noncap",  P(r"ลูกค้าทั่วไป", r"ผู้ป่วยทั่วไป", r"non-?capitation", r"ผู้ป่วยเงินสด", r"ชำระเงินเอง")),
    ("misc",    P(r"ตรวจสุขภาพเคลื่อนที่", r"โรงพยาบาลเคลื่อนที่", r"ฉายแสง", r"รังสีรักษา")),
    ("thai",    P(r"(คนไข้|ลูกค้า|ผู้ป่วย|ผู้รับบริการ)\s*(ชาว)?\s*(คน)?ไทย", r"^thai (patients?|customers?)")),
    ("foreign", P(r"ต่างชาติ", r"ต่างประเทศ", r"^(foreign|international) (patients?|customers?)")),
    ("hosp",    P(r"^รายได้จากกิจการโรงพยาบาล$", r"^รายได้จากการประกอบกิจการโรงพยาบาล$",
                  r"^รายได้ค่ารักษาพยาบาล$", r"^(revenue|revenues) from hospital operations?$")),
    ("other",   P(r"^รายได้อื่น", r"^รายได้ค่าเช่า", r"^other income")),
    ("total",   P(r"^รายได้รวม$", r"^รวมรายได้$", r"^total revenues?$")),
]

RE_DOC = re.compile(r"^# DOCUMENT:\s*MDA_Year(\d{4})_Q([1-4])", re.I)
RE_NUM = re.compile(r"^\(?[+-]?[\d,]+(\.\d+)?\)?%?\)?$")
RE_YTD = re.compile(fold(r"หกเดือน|เก้าเดือน|สิบสองเดือน|ประจำปี|ทั้งปี|สำหรับปี|ปีสิ้นสุด|\b(6|9|12)\s?M\b|งวด\s*(6|9|12)\s*เดือน"), re.I)
RE_PCT_COLS = re.compile(fold(r"ล้านบาท\s*ร้อยละ\s*ล้านบาท\s*ร้อยละ"))
RE_QTR = re.compile(fold(r"สามเดือน|\bQ[1-4]\b|ไตรมาส|3\s?M\b"), re.I)


def num_token(tok):
    """-> (kind, value) kind: 'v' plain value, 'p' percent/change, None not a number"""
    t = tok.strip().replace(" ", "")
    if not t or not RE_NUM.match(t):
        return None, None
    if "%" in t or t[0] in "+-" or (t.startswith("(") and t.endswith("%)")):
        return "p", None
    neg = t.startswith("(")
    t = t.strip("()").replace(",", "")
    try:
        v = float(t)
    except ValueError:
        return None, None
    return "v", -v if neg else v


def classify(label):
    f = fold(label)
    if not f or len(f) > 70:
        return None
    for key, pats in ROWS:
        if any(p.search(f) for p in pats):
            return key
    return None


def split_docs(lines):
    docs, cur = [], None
    for i, ln in enumerate(lines):
        m = RE_DOC.match(ln.strip())
        if m:
            cur = {"be": int(m.group(1)), "q": int(m.group(2)), "start": i, "name": ln.split(":", 1)[1].strip()}
            docs.append(cur)
        elif ln.startswith("# DOCUMENT:"):
            cur = None
            docs.append({"be": None, "start": i})
    for a, b in zip(docs, docs[1:] + [{"start": len(lines)}]):
        a["end"] = b["start"]
    return [d for d in docs if d.get("be")]


def parse_doc(lines, d):
    """Return list of rows: (key, [values], ctx, line_no, label)."""
    rows, header, ctx, i = [], [], "", d["start"]
    while i < d["end"]:
        raw = lines[i].replace("‌", "").strip()
        key = classify(raw) if raw and num_token(raw)[0] is None else None
        if key:
            vals, pcts, j = [], 0, i + 1
            while j < d["end"]:
                t = lines[j].replace("‌", "").strip()
                if not t:
                    j += 1
                    continue
                toks = t.split()
                kinds = [num_token(x) for x in toks]
                if all(k for k, _ in kinds):
                    for k, v in kinds:
                        if k == "v":
                            vals.append(v)
                        else:
                            pcts += 1
                    j += 1
                    continue
                break
            if len(vals) >= 2:
                h = " ".join(header[-40:])
                if RE_YTD.search(h) or RE_QTR.search(h) or re.search(fold("ล้านบาท|หน่วย"), h):
                    ctx = h            # a new table header; otherwise keep the current table's context
                rows.append((key, vals, ctx, i + 1, raw))
                header = []
                i = j
                continue
        if raw and num_token(raw)[0] is None:
            header.append(fold(raw))
        i += 1
    return rows


RE_PROSE_NUM = re.compile("(" + "|".join(fold(w) for w in ("จำนวน", "เท่ากับ", "อยู่ที่", "รวม")) + r")\s*([\d,]+\.\d+|[\d,]{3,})\s*" + fold("ล้านบาท"))
# a period marker counts only when it names a reporting period ("สำหรับไตรมาส 2 ปี 2569", "หกเดือนแรกของปี 2568"),
# not a passing mention ("ในช่วงไตรมาสก่อน")
RE_CTX_Q = re.compile(fold(r"(สำหรับ\s*(ไตรมาส|งวดสามเดือน|งวด\s*3\s*เดือน))|((ไตรมาส(ที่)?\s*[1-4]|สามเดือน|งวด\s*3\s*เดือน)[^0-9]{0,12}(ปี\s*)?25\d\d)"))
RE_CTX_Y = re.compile(fold(r"(สำหรับ\s*(งวด|ปี))|((หกเดือน|งวด\s*6\s*เดือน|ครึ่งปี|เก้าเดือน|งวด\s*9\s*เดือน|ทั้งปี)[^0-9]{0,15}(ปี\s*)?25\d\d)|ครึ่งปีแรก|หกเดือนแรก|เก้าเดือนแรก"))


def parse_prose(lines, d):
    """MD&A that give the mix only in sentences ("รายได้จากผู้ป่วยนอก เท่ากับ 1,031.5 ล้านบาท ...").
    Returns (period, key, value, src, rank) for the CURRENT period only; comparatives come from last year's document."""
    be, q = d["be"], d["q"]
    ce = be - 543
    out = []
    ctx_kind = None
    for i in range(d["start"], d["end"]):
        f = fold(lines[i].replace("‌", ""))
        if not f:
            continue
        mq, my = list(RE_CTX_Q.finditer(f)), list(RE_CTX_Y.finditer(f))
        # a quarter marker for another quarter ("ในช่วงไตรมาสที่ 1" inside the Q2 MD&A) is a passing mention
        mq = [x for x in mq if not re.search(r"[1-4]", x.group(0)[:20]) or re.search(r"(?<!\d)%d(?!\d)" % q, x.group(0)[:20])]
        pos = 0
        for m in RE_PROSE_NUM.finditer(f):
            seg = f[pos:m.start()][-70:]
            # the period stated closest before the number on this line, else the latest seen above
            lq = max([x.start() for x in mq if x.start() < m.start()] or [-1])
            ly = max([x.start() for x in my if x.start() < m.start()] or [-1])
            kind = ("Y" if ly > lq else "Q") if max(lq, ly) >= 0 else ctx_kind
            pos = m.end()
            key = classify(seg.split(fold("ล้านบาท"))[-1])
            if not key or key in ("hosp", "total", "other") or kind is None:
                continue
            v = float(m.group(2).replace(",", ""))
            per = ce_q(be, q) if kind == "Q" or q == 1 else ("FY%d" % ce if q == 4 else "%dM%d" % (3 * q, ce))
            out.append((per, key, v, "%s:L%d prose" % (d["name"].replace(".pdf", ""), i + 1), 0 if per[4:5] == "Q" else 1))
        if mq or my:
            last = max([("Q", x.start()) for x in mq] + [("Y", x.start()) for x in my], key=lambda t: t[1])
            ctx_kind = last[0]
    return out


def ce_q(be, q):
    return f"{be - 543}Q{q}"


def assign(rows, d):
    """Map rows to periods.  Returns list of (period, key, value, src, rank).  rank 0=current 3M, 1=current YTD, 2=comparative"""
    be, q = d["be"], d["q"]
    ce = be - 543
    ytd_name = "FY%d" % ce if q == 4 else "%dM%d" % (3 * q, ce)
    ytd_prev = "FY%d" % (ce - 1) if q == 4 else "%dM%d" % (3 * q, ce - 1)
    out = []
    for key, vals, ctx, ln, label in rows:
        src = "%s:L%d" % (d["name"].replace(".pdf", ""), ln)
        has_ytd = bool(RE_YTD.search(ctx))
        has_qtr = bool(RE_QTR.search(ctx))
        v = vals
        if RE_PCT_COLS.search(ctx) and len(v) >= 4:
            v = v[0::2]          # "ล้านบาท | ร้อยละ | ล้านบาท | ร้อยละ" tables: drop the share-of-revenue columns
        if len(v) >= 6 and abs(v[0] - v[1] - v[2]) < 0.05 and abs(v[3] - v[4] - v[5]) < 0.05:  # cur, pri, chg, ...
            v = [v[0], v[1], v[3], v[4]]
        elif len(v) >= 3 and abs(v[0] - v[1] - v[2]) < 0.05:
            v = [v[0], v[1]] + v[3:]
        if q == 1:
            has_ytd = False
        if len(v) >= 4 and (has_ytd or q == 4) and not (q == 1):
            # quarter columns then YTD columns (VIH style) - unless the only context is YTD
            if has_qtr or not has_ytd:
                out += [(ce_q(be, q), key, v[0], src + " current", 0), (ce_q(be - 1, q), key, v[1], src + " comparative", 2),
                        (ytd_name, key, v[2], src + " YTD current", 1), (ytd_prev, key, v[3], src + " YTD comparative", 3)]
            else:
                out += [(ytd_name, key, v[0], src + " YTD current", 1), (ytd_prev, key, v[1], src + " YTD comparative", 3)]
        elif has_ytd and not has_qtr and q != 1:
            out += [(ytd_name, key, v[0], src + " YTD current", 1), (ytd_prev, key, v[1], src + " YTD comparative", 3)]
        else:
            out += [(ce_q(be, q), key, v[0], src + " current", 0), (ce_q(be - 1, q), key, v[1], src + " comparative", 2)]
    return out


KEYS_TYPE = ["opd", "ipd", "sso", "gov", "gov_total", "elim", "noncap", "noncap_total", "contract", "misc"]
KEYS_NAT = ["thai", "foreign"]


def build(stock_dir, fin_path=None, mda_path=None):
    mda_path = mda_path or os.path.join(stock_dir, "md", "raw", "combined_mda_all.md")
    lines = open(mda_path, encoding="utf-8", errors="replace").read().splitlines()
    docs = split_docs(lines)
    best = {}   # (period,key) -> (rank, value, src)
    flags = []
    for d in docs:
        rows = parse_doc(lines, d)
        items = assign(rows, d)
        if not any(k in ("opd", "sso", "noncap", "noncap_total") and r <= 1 for _, k, _, _, r in items):
            items = items + parse_prose(lines, d)
        seen = set()
        for per, key, val, src, rank in items:
            if key == "elim":
                val = abs(val)
            if (per, key, rank) in seen:      # first table in the document wins (later ones are often % tables)
                continue
            seen.add((per, key, rank))
            cur = best.get((per, key))
            if cur is not None and rank >= 2 and cur[0] <= 1 and abs(cur[1] - val) > 0.6:
                flags.append("RESTATED LATER %s %s: original %.2f (%s) -> %.2f in %s (original kept)" % (per, key, cur[1], cur[2], val, src))
            if cur is None or rank < cur[0]:
                if cur and abs(cur[1] - val) > 0.6 and rank <= 1:
                    flags.append("RESTATED? %s %s: %.2f (%s) vs %.2f (%s)" % (per, key, cur[1], cur[2], val, src))
                best[(per, key)] = (rank, val, src)
    periods = {}
    for (per, key), (rank, val, src) in best.items():
        periods.setdefault(per, {})[key] = {"v": round(val, 4), "src": src}

    # Guards against an annual column read as a quarter: Q4 == FY, or a quarter far above its neighbours
    for per in [p for p in periods if "Q" in p]:
        y, q = int(per[:4]), int(per[-1])
        for key in list(periods[per]):
            v = periods[per][key]["v"]
            fy = periods.get("FY%d" % y, {}).get(key)
            if q == 4 and fy and abs(fy["v"] - v) < 0.05:
                flags.append("DROPPED %s %s = FY value %.2f (annual column, not Q4)" % (per, key, v))
                del periods[per][key]
                continue
            nb = [periods.get(k, {}).get(key, {}).get("v") for k in _neighbours(y, q)]
            nb = sorted(x for x in nb if x)
            if len(nb) >= 2 and v > 2.5 * nb[len(nb) // 2] and key not in ("elim", "other"):
                flags.append("DROPPED %s %s = %.2f (>2.5x neighbouring quarters, likely a YTD column)" % (per, key, v))
                del periods[per][key]

    # Q4 = FY - 9M when no 3-month Q4 column
    for per in list(periods):
        if per.startswith("FY"):
            y = int(per[2:])
            q4, m9 = "%dQ4" % y, "9M%d" % y
            for key in KEYS_TYPE + KEYS_NAT + ["hosp", "other", "total"]:
                if key in periods[per] and key not in periods.get(q4, {}):
                    base = periods.get(m9, {}).get(key)
                    if base is None and all(key in periods.get("%dQ%d" % (y, k), {}) for k in (1, 2, 3)):
                        base = {"v": sum(periods["%dQ%d" % (y, k)][key]["v"] for k in (1, 2, 3)), "src": "Q1+Q2+Q3"}
                    if base is not None and periods[per][key]["v"] - base["v"] >= 0:
                        periods.setdefault(q4, {})[key] = {"v": round(periods[per][key]["v"] - base["v"], 4),
                                                           "src": "derived =FY%d-9M%d" % (y, y)}

    reported = {}
    if fin_path and os.path.isfile(fin_path):
        facts = json.load(open(fin_path, encoding="utf-8"))["facts"]
        for k, f in facts.items():
            ent, key, per = k.split("|")
            if ent == "C" and key == "rev_hosp":
                reported[per] = f["v"]

    recon, mix_q, mix_a, nat_q, nat_a = {}, {}, {}, {}, {}
    for per in sorted(periods, key=_sort_key):
        p = periods[per]
        g = lambda k: p[k]["v"] if k in p else None
        rep = reported.get(per, g("hosp"))
        rep_src = "financials" if per in reported else ("MD&A" if g("hosp") is not None else None)
        res = {"reported": rep, "reported_src": rep_src}
        calc, how = None, None
        extra = (g("sso") or 0) + (g("gov") or 0) + (g("misc") or 0) - (g("elim") or 0)
        gov_part = (g("sso") or 0) + (g("gov") or 0)
        if g("gov_total") is not None and g("gov") is None and g("sso") is not None:
            gov_part = g("gov_total")          # sub-total given, other-government line missing
            extra = gov_part + (g("misc") or 0) - (g("elim") or 0)
        cands = []
        if g("opd") is not None and g("ipd") is not None:
            cands.append(("opd+ipd", g("opd") + g("ipd")))
        if g("noncap_total") is not None:
            cands.append(("cash total", g("noncap_total")))
        if g("noncap") is not None and g("contract") is not None:
            cands.append(("general+contract", g("noncap") + g("contract")))
        if g("noncap") is not None:
            cands.append(("general", g("noncap")))
        if (g("sso") is not None or g("gov_total") is not None) and cands:
            tol = max(1.0, 0.0025 * abs(rep)) if rep is not None else None
            for name, cash in cands:          # first variant that reconciles wins (OPD+IPD preferred), else the closest
                c = cash + extra
                if rep is not None and abs(c - rep) <= tol:
                    calc, how, cash_v = c, name, cash
                    break
                if calc is None or (rep is not None and abs(c - rep) < abs(calc - rep)):
                    calc, how, cash_v = c, name, cash
        elif cands:
            calc, how, cash_v = cands[0][1] + (g("misc") or 0) - (g("elim") or 0), cands[0][0], cands[0][1]
        res["calc_how"] = how
        nat = None
        if g("thai") is not None and g("foreign") is not None:
            nat = g("thai") + g("foreign")
        res["calc_type"] = calc
        res["calc_nat"] = nat
        st = []
        for name, c in (("type", calc), ("nat", nat)):
            if c is None:
                continue
            if rep is None:
                st.append((name, "NO_REPORTED"))
            else:
                # ±1 THB mn, or ±0.25% for large groups whose MD&A rounds each line to 0.1 mn
                st.append((name, "PASS" if abs(c - rep) <= max(1.0, 0.0025 * abs(rep)) else "FAIL"))
        res["status"] = dict(st)
        recon[per] = res
        ok_type = res["status"].get("type") in ("PASS", "NO_REPORTED") and calc is not None
        ok_nat = res["status"].get("nat") in ("PASS", "NO_REPORTED") and nat is not None
        tgt_mix = mix_q if "Q" in per else mix_a
        tgt_nat = nat_q if "Q" in per else nat_a
        if ok_type:
            m = {"sso": g("sso") or (gov_part if g("gov") is None and g("gov_total") is not None and g("sso") is None else 0.0),
                 "elim": g("elim") or 0.0}
            if how == "opd+ipd":
                m.update({"opd": g("opd"), "ipd": g("ipd")})
            else:
                m["cash"] = cash_v                 # cash / general / contract patients (no OPD-IPD split published)
            gv = (g("gov") if g("gov") is not None else (g("gov_total") - g("sso") if g("gov_total") is not None and g("sso") is not None else None))
            if gv:
                m["gov"] = gv
            if g("misc"):
                m["misc"] = g("misc")
            tgt_mix[per] = m
        if ok_nat:
            tgt_nat[per] = {"thai": g("thai"), "foreign": g("foreign")}
        for name, s in res["status"].items():
            if s == "FAIL":
                c = calc if name == "type" else nat
                flags.append("RECON FAIL %s (%s): mix %.2f vs reported %.2f (diff %.2f) - not used" % (per, name, c, rep, c - rep))
    return {"periods": periods, "recon": recon, "flags": flags,
            "revenue_mix": {"source": "MD&A 'โครงสร้างรายได้' (extract_mda.py; reconciled ±1 ลบ. to งบการเงิน)",
                            "quarterly": mix_q, "annual": mix_a},
            "nationality": {"source": "MD&A รายได้ตามสัญชาติ (extract_mda.py)", "quarterly": nat_q, "annual": nat_a},
            "source": mda_path}


def _neighbours(y, q):
    out = []
    for d in (-2, -1, 1, 2):
        n = (y * 4 + q - 1) + d
        out.append("%dQ%d" % (n // 4, n % 4 + 1))
    return out


def _sort_key(p):
    m = re.match(r"(\d{4})Q(\d)", p)
    if m:
        return (int(m.group(1)), int(m.group(2)), "")
    m = re.match(r"(\d+)M(\d{4})", p)
    if m:
        return (int(m.group(2)), int(m.group(1)) // 3, "Y")
    m = re.match(r"FY(\d{4})", p)
    return (int(m.group(1)), 4, "Z") if m else (0, 0, p)


def merge_into_assumptions(res, path, overwrite=False):
    a = json.load(open(path, encoding="utf-8")) if os.path.isfile(path) else {}
    rm = a.setdefault("revenue_mix", {})
    rm.setdefault("quarterly", {})
    rm.setdefault("annual", {})
    added = 0
    for sect in ("quarterly", "annual"):
        for per, v in res["revenue_mix"][sect].items():
            if overwrite or per not in rm[sect] or not rm[sect][per]:
                rm[sect][per] = v
                added += 1
    if added and not rm.get("source"):
        rm["source"] = res["revenue_mix"]["source"]
    elif added and "extract_mda" not in rm.get("source", ""):
        rm["source"] = rm["source"] + " + extract_mda.py (auto, reconciled)"
    if res["nationality"]["quarterly"] or res["nationality"]["annual"]:
        a["nationality_mix"] = res["nationality"]
    json.dump(a, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return added


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stock-dir", required=True)
    ap.add_argument("--ticker", required=True)
    ap.add_argument("-f", "--financials", help="<T>_financials.json for the reconciliation")
    ap.add_argument("--mda", help="MD&A file (default md/raw/combined_mda_all.md)")
    ap.add_argument("-o", "--out")
    ap.add_argument("--merge-assumptions", help="fill missing revenue_mix periods in this assumptions JSON")
    ap.add_argument("--overwrite", action="store_true", help="with --merge-assumptions: replace existing periods too")
    ap.add_argument("-q", "--quiet", action="store_true")
    a = ap.parse_args()
    mda = a.mda or os.path.join(a.stock_dir, "md", "raw", "combined_mda_all.md")
    if not os.path.isfile(mda):
        print("no MD&A file: %s" % mda)
        return 2
    res = build(a.stock_dir, a.financials, mda)
    res.update({"ticker": a.ticker, "generated": datetime.now().isoformat(timespec="seconds")})
    out = a.out or os.path.join(a.stock_dir, "report", "%s_mda.json" % a.ticker)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(res, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if not a.quiet:
        print("period    OPD      IPD      SSO     elim   | Thai   foreign | reported  type  nat   (cash/gov in the JSON)")
        for per in sorted(res["recon"], key=_sort_key):
            p, r = res["periods"][per], res["recon"][per]
            f = lambda k: ("%8.2f" % p[k]["v"]) if k in p else "       ·"
            rep = ("%9.2f" % r["reported"]) if r["reported"] is not None else "        ·"
            print("%-8s %s %s %s %s | %s %s | %s  %-5s %-5s" % (per, f("opd"), f("ipd"), f("sso"), f("elim"), f("thai"), f("foreign"),
                                                              rep, r["status"].get("type", "-")[:5], r["status"].get("nat", "-")[:5]))
        for fl in res["flags"]:
            print("  ⚠", fl)
        print("-> %s  (%d quarters + %d years usable for revenue_mix, %d for nationality)" % (
            out, len(res["revenue_mix"]["quarterly"]), len(res["revenue_mix"]["annual"]),
            len(res["nationality"]["quarterly"]) + len(res["nationality"]["annual"])))
    if a.merge_assumptions:
        n = merge_into_assumptions(res, a.merge_assumptions, a.overwrite)
        print("merged %d revenue_mix periods into %s" % (n, a.merge_assumptions))
    return 0


if __name__ == "__main__":
    sys.exit(main())
