#!/usr/bin/env python3
"""
deepdive.py - data layer + checks for the stock-deepdive skill (5-6 year strategic report, Thai hospitals).

Numbers come from the statement facts of the thai-hospital-finance-sheet skill (<T>_financials.json), the MD&A
revenue mix (<T>_mda.json) and the curated assumptions file - the same definitions as the Excel model and the
snapshot.  Branch beds / occupancy / guidance are NOT computed: the agent reads them from the One Report, MD&A or
Oppday text, and every such row must carry a source.  To help, `data` prints the file:line candidates to read.

Sub-commands
  data    report/<T>_deepdive_data.json + a compact digest
  render  report/<T>_DeepDive_Report_<BE year>-v<N>.md + .html (uses <T>_deepdive_narrative.json if present)
  check   verify a narrative: numbers must be in the pack, sourced, or declared external; capacity rows need src
  run     data + render for tickers (batch / no agent)
"""
import argparse, glob, json, os, re, sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
SNAP_DIR = HERE            # this skill ships the snapshot data layer in the same scripts/ folder
sys.path.insert(0, SNAP_DIR)
sys.path.insert(0, HERE)
import snapshot as S  # noqa: E402
import deepdive_extra as DX  # noqa: E402
import deepdive_sector as DSEC  # noqa: E402
import deepdive_pop as DPOP  # noqa: E402
import deepdive_val as DVAL  # noqa: E402
import deepdive_viz as DV  # noqa: E402

LINES_FY = [
    ("rev", "รายได้จากกิจการโรงพยาบาล"), ("total_rev", "รายได้รวม"), ("gp", "กำไรขั้นต้น"), ("gpm", "อัตรากำไรขั้นต้น (GPM)"),
    ("sga", "SG&A"), ("sga_pct", "% SG&A ต่อรายได้"), ("ebit", "EBIT (รวมรายได้อื่น)"), ("ebit_m", "EBIT Margin"),
    ("np_owners", "กำไรสุทธิส่วนของบริษัทใหญ่"), ("npm", "อัตรากำไรสุทธิ (NPM)"), ("one_off", "รายการพิเศษหลังภาษี"),
    ("core_np", "กำไรปกติ (Core)"), ("da", "ค่าเสื่อมราคาและค่าตัดจำหน่าย"), ("ebitda", "EBITDA"), ("ebitda_m", "EBITDA Margin"),
    ("cash_total", "เงินสด + เงินลงทุนระยะสั้น"), ("debt_lease", "หนี้มีดอกเบี้ย + สัญญาเช่า"), ("net_cash", "เงินสดสุทธิ"),
    ("liab", "หนี้สินรวม"), ("tot_equity", "ส่วนของผู้ถือหุ้นรวม"), ("de", "หนี้สินรวม/ทุน (D/E, เท่า)"),
    ("roe", "ROE (กำไรบริษัทใหญ่ / ทุนเฉลี่ย)"), ("roa", "ROA (กำไรสุทธิ / สินทรัพย์เฉลี่ย)"),
    ("roic", "ROIC (EBIT×(1−ETR) / (ทุน+หนี้+สัญญาเช่า−เงินสด))"), ("dso", "ระยะเวลาเก็บหนี้ (วัน)"),
    ("cfo", "กระแสเงินสดจากการดำเนินงาน"), ("capex", "รายจ่ายลงทุน (Capex)"), ("capex_da", "Capex / ค่าเสื่อม (เท่า)"),
    ("fcf", "กระแสเงินสดอิสระ (FCF)"), ("cfo_ebitda", "CFO / EBITDA (เท่า)"), ("eps", "EPS (บาท)"), ("dps", "เงินปันผลต่อหุ้น (บาท)"),
    ("payout", "อัตราการจ่ายปันผล (DPS/EPS)"),
]
PCTK = {"gpm", "sga_pct", "ebit_m", "npm", "ebitda_m", "roe", "roa", "roic", "payout", "etr", "g", "cagr", "share", "rev_g",
        "gp_g", "np_g", "da_g", "gpm_chg", "yoy", "pct", "nat_share", "sso_share", "foreign_share",
        "pbt_g", "incr_gpm", "sga_g", "earn_yield", "np_cagr3", "yield"}
RATIO = {"de", "capex_da", "cfo_ebitda"}
NATURE = [("exp_staff", "ค่าใช้จ่ายพนักงาน"), ("exp_doctor", "ค่าธรรมเนียมแพทย์"), ("exp_medicine", "ยาและเวชภัณฑ์ใช้ไป"),
          ("exp_da", "ค่าเสื่อมราคาและค่าตัดจำหน่าย"), ("exp_referral", "ค่ารักษาพยาบาลส่งต่อ")]


def fy_lines(fx, per, prev=None, ann=1.0, oo=None):
    oo_pre, oo_sga = (oo or (None, None))
    L = S.period_lines(fx, per, ann=ann, oo_pre=oo_pre, oo_sga=oo_sga)
    g = fx.get
    L["dps"] = g("dps", per)
    L["de"] = L["liab"] / L["tot_equity"] if L.get("liab") is not None and L.get("tot_equity") else None
    eq0 = prev.get("equity") if prev else None
    L["roe"] = (L["np_owners"] * ann / ((L["equity"] + eq0) / 2 if eq0 else L["equity"])) if L.get("np_owners") is not None and L.get("equity") else None
    a0 = prev.get("assets") if prev else None
    L["roa"] = (L["np"] * ann / ((L["assets"] + a0) / 2 if a0 else L["assets"])) if L.get("np") is not None and L.get("assets") else None
    ic = (L["tot_equity"] or 0) + (L.get("debt_lease") or 0) - (L.get("cash_total") or 0) if L.get("tot_equity") else None
    L["roic"] = L["ebit"] * (1 - (L["etr"] or 0)) * ann / ic if L.get("ebit") is not None and ic and ic > 0 else None
    L["capex_da"] = L["capex"] / L["da"] if L.get("capex") is not None and L.get("da") else None
    L["cfo_ebitda"] = L["cfo"] / L["ebitda"] if L.get("cfo") is not None and L.get("ebitda") else None
    if L.get("dps") and L.get("eps") and L["eps"] > 0:
        L["payout"] = L["dps"] / L["eps"]
    else:
        sh = g("shares_out", per)
        L["payout"] = L["dps"] * sh / L["np_owners"] if L.get("dps") and sh and L.get("np_owners") and L["np_owners"] > 0 else None
    L["dso"] = L["recv"] / (L["rev"] * ann) * 365 if L.get("recv") is not None and L.get("rev") else None
    for k, _ in NATURE:
        v = g(k, per)
        L[k] = abs(v) if v is not None else None
    return L


def cagr(a, b, n):
    if a is None or b is None or a <= 0 or b <= 0 or n <= 0:
        return None
    return (b / a) ** (1 / n) - 1


def candidates(sdir, patterns, limit=30, files=None):
    """file:line hits for the agent to read (beds, occupancy, targets...)."""
    files = files or (glob.glob(os.path.join(sdir, "md", "raw", "*.md")) + glob.glob(os.path.join(sdir, "PDF", "*.txt")) +
                      glob.glob(os.path.join(sdir, "md", "*.md")) + glob.glob(os.path.join(sdir, "*.md")))
    try:
        from extract_mda import fold
    except ImportError:
        fold = lambda x: x
    rx = re.compile(fold(patterns), re.I)
    hits = []
    for f in sorted(set(files)):
        # statements are covered by the extractor; AGY-generated digests are not primary sources
        if re.search(r"(financial|fs\d)_all\.md$|finance_summary\.md$|finance_sheet_v\d+\.md$|guidance_tracker\.md$|MANIFEST\.md$", f):
            continue
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                doc = ""
                for i, ln in enumerate(fh, 1):
                    if ln.startswith("# DOCUMENT:"):
                        doc = ln.split(":", 1)[1].strip()[:40]
                    s = ln.replace("\u200c", "").strip()
                    if len(s) < 400 and re.search(r"\d", s) and rx.search(fold(s)):
                        hits.append({"file": os.path.relpath(f, sdir), "line": i, "doc": doc, "text": s[:160]})
        except OSError:
            pass
    # newest documents first (MD&A/OneReport years appear in doc names)
    def yr(h):
        m = re.search(r"(25\d\d|20\d\d)", h["doc"] + h["file"])
        return int(m.group(1)) if m else 0
    good = re.compile(fold(r"ครองเตียง|occupan|โรงพยาบาล|รพ\.|hospital|ห้องตรวจ|เป้า|target|guidance"), re.I)
    bad = re.compile(fold(r"โรงแรม|hotel|hospitel|residence|ESG|คาร์บอน"), re.I)
    for h in hits:
        t = fold(h["text"])
        h["score"] = (2 if good.search(t) else 0) - (3 if bad.search(t) else 0)
    hits.sort(key=lambda h: (-h["score"], -yr(h), h["file"], h["line"]))
    return hits[:limit]


def reference_notes(sdir, q_last, max_posts=25):
    """The reference analyst's own material for a multi-year report (<stock>/md/analyst_notes).

    notes   every *.md note in the folder; a note tagged with a quarter later than q_last is left out
    posts   his own Facebook posts (fb/index.json, kind "own"), newest first, dated no later than 135 days after the
            last quarter in the report. Undated posts and later posts are left out, so a back-dated deep dive never
            reads something written after its own date.
    Posts he only shared (kind shared / news) are other people's material: counted here, read as tier 2.
    """
    d = os.path.join(sdir, "md", "analyst_notes")
    out = {"notes": [], "posts": [], "more": 0, "shared": 0, "undated": 0, "index": None}
    if not os.path.isdir(d):
        return out
    y, q = S.qsplit(q_last)
    last_tag = "%dQ%d" % (y + 543, q)
    end = datetime(y, q * 3, 30 if q in (2, 3) else 31)
    hi = (end + timedelta(days=135)).strftime("%Y-%m-%d")
    for f in sorted(os.listdir(d)):
        if not f.endswith(".md"):
            continue
        m = re.search(r"(\d{4})Q([1-4])", f)
        if m and m.group(0) > last_tag:
            continue
        out["notes"].append({"file": os.path.join(d, f), "period": m.group(0) if m else None,
                             "who": S.note_analyst(os.path.join(d, f))})
    idx = os.path.join(d, "fb", "index.json")
    if os.path.isfile(idx):
        try:
            allp = S.load_json(idx)
        except Exception:
            allp = []
        out["index"] = idx
        own = [e for e in allp if e.get("kind") == "own" and e.get("chars", 0) >= 150]
        out["shared"] = sum(1 for e in allp if e.get("kind") != "own")
        out["undated"] = sum(1 for e in own if not e.get("date"))
        sel = sorted((e for e in own if e.get("date") and e["date"] <= hi), key=lambda e: e["date"], reverse=True)
        out["more"] = max(0, len(sel) - max_posts)
        out["posts"] = [{"file": os.path.join(d, "fb", e["file"]), "date": e["date"], "period": e.get("quarter_hint"),
                         "title": (e.get("title") or "")[:70], "chars": e.get("chars")} for e in sel[:max_posts]]
    return out


def build_pack(sdir, ticker, rebuild=False, quiet=False, peers=None, root=None):
    fin_p, mda_p = S.ensure_inputs(sdir, ticker, rebuild, quiet)
    fin = S.load_json(fin_p)
    asm_p = os.path.join(sdir, "report", "%s_assumptions.json" % ticker)
    asm = S.load_json(asm_p)
    mda = S.load_json(mda_p)
    mix = {"quarterly": {}, "annual": {}}
    for sect in ("quarterly", "annual"):
        mix[sect].update((mda.get("revenue_mix") or {}).get(sect) or {})
        mix[sect].update(((asm.get("revenue_mix") or {}).get(sect)) or {})
    asm2 = dict(asm)
    asm2["revenue_mix"] = {"source": "MD&A", **mix}
    fx = S.F(fin, asm2)
    _oo = S.one_off_pretax(asm)
    OO = (_oo[0], _oo[2])

    years = sorted(y for y in fin.get("years", []) if fx.get("rev_hosp", "FY%d" % y) is not None)
    if not years:
        raise RuntimeError("no annual hospital revenue in %s" % fin_p)
    years = years[-6:]
    L = {}
    prev = None
    for y in [years[0] - 1] + years:
        per = "FY%d" % y
        if fx.get("rev_hosp", per) is None and y != years[0] - 1:
            continue
        L[per] = fy_lines(fx, per, prev, oo=OO)
        prev = L[per]
    L.pop("FY%d" % (years[0] - 1), None)
    fys = ["FY%d" % y for y in years]
    # growth
    for i, per in enumerate(fys[1:], 1):
        p0 = L[fys[i - 1]]
        for k in ("rev", "gp", "np_owners", "core_np", "da", "ebitda", "sga", "capex", "cfo"):
            L[per][k + "_g"] = S.pct(L[per].get(k), p0.get(k))
        L[per]["gpm_chg"] = (L[per]["gpm"] - p0["gpm"]) if L[per].get("gpm") is not None and p0.get("gpm") is not None else None
        dr = (L[per].get("rev") or 0) - (p0.get("rev") or 0)
        L[per]["incr_gpm"] = ((L[per]["gp"] - p0["gp"]) / dr) if L[per].get("gp") is not None and p0.get("gp") is not None and abs(dr) > 0.01 * (p0.get("rev") or 1) else None

    # latest YTD vs prior YTD
    quarters = sorted(q for q in fin.get("quarters", []) if fx.get("rev_hosp", q) is not None)
    q_last = quarters[-1]
    y, qn = S.qsplit(q_last)
    ytd = ytd_py = None
    if qn < 4:
        ytd, ytd_py = "%dM%d" % (3 * qn, y), "%dM%d" % (3 * qn, y - 1)
        for p, pv in ((ytd, "FY%d" % (y - 1)), (ytd_py, "FY%d" % (y - 2))):
            L[p] = fy_lines(fx, p, L.get(pv), ann=4 / qn, oo=OO)
            qq = ["%sQ%d" % (p[-4:], k) for k in range(1, qn + 1)]
            ql = {q: S.period_lines(fx, q, oo_pre=OO[0], oo_sga=OO[1]) for q in qq}
            for k in S.FLOW_LINES:
                if L[p].get(k) is None and all(ql[q].get(k) is not None for q in qq):
                    L[p][k] = sum(ql[q][k] for q in qq)
            if L[p].get("gp") is not None and L[p].get("rev"):
                L[p]["gpm"] = L[p]["gp"] / L[p]["rev"]
        for k in ("rev", "gp", "np_owners", "core_np", "da", "ebitda", "sga", "capex", "cfo"):
            L[ytd][k + "_g"] = S.pct(L[ytd].get(k), L[ytd_py].get(k))
        L[ytd]["gpm_chg"] = (L[ytd]["gpm"] - L[ytd_py]["gpm"]) if L[ytd].get("gpm") is not None and L[ytd_py].get("gpm") is not None else None

    n = len(fys) - 1
    cagrs = {k: cagr(L[fys[0]].get(k), L[fys[-1]].get(k), n) for k in ("rev", "gp", "np_owners", "core_np", "ebitda", "tot_equity", "da")}
    # Trend base: 3 years back, but never a COVID-distorted year (CE 2020-2022 = BE 2563-2565) when a later one exists
    base_i = max(0, len(fys) - 4)
    while base_i < len(fys) - 2 and int(fys[base_i][2:]) <= 2022:
        base_i += 1
    base = fys[base_i]
    n3 = len(fys) - 1 - base_i
    cagr3 = {k: cagr(L[base].get(k), L[fys[-1]].get(k), n3) for k in ("rev", "gp", "np_owners", "core_np", "ebitda", "da")}

    # nature (% of hospital revenue)
    nature = []
    for k, lab in NATURE:
        vals = {p: L[p].get(k) for p in fys}
        if any(v is not None for v in vals.values()):
            nature.append({"id": k, "label": lab, "vals": vals,
                           "share": {p: (vals[p] / L[p]["rev"]) if vals[p] is not None and L[p].get("rev") else None for p in fys}})

    # annual mix
    cat = asm.get("category")
    if not cat and S.FS_DIR:
        import build_finance_sheet as BF
        cat = BF.HOSPITAL_CATEGORY.get(ticker, 3)
    cat = cat or 3
    has_sso = asm.get("has_sso", cat == 2)
    mix_rows = []
    keys = ([("opd", "ผู้ป่วยนอก (OPD)"), ("ipd", "ผู้ป่วยใน (IPD)"), ("cash", "ผู้ป่วยทั่วไป/คู่สัญญา (ไม่แยก OPD/IPD)")]
            + ([("sso", "ประกันสังคม (SSO)"), ("gov", "โครงการรัฐอื่น (บัตรทอง/สปสช./ข้าราชการ)")] if has_sso else [])
            + [("other", "รายได้อื่นจากกิจการ (เช่น โควิด-19)"), ("misc", "บริการอื่น"), ("elim", "หักรายการระหว่างกัน")])
    cols = fys + ([ytd, ytd_py] if ytd else [])
    for k, lab in keys:
        vals = {p: (mix["annual"].get(p) or {}).get(k) for p in cols}
        if any(v for v in vals.values()):
            mix_rows.append({"id": k, "label": lab, "vals": vals})
    natsrc = (asm.get("nationality_mix") or mda.get("nationality") or {}).get("annual") or {}
    nat_rows = []
    for k, lab in (("thai", "ผู้ป่วยชาวไทย"), ("foreign", "ผู้ป่วยต่างชาติ")):
        vals = {p: (natsrc.get(p) or {}).get(k) for p in cols}
        if any(v for v in vals.values()):
            nat_rows.append({"id": k, "label": lab, "vals": vals})
    for rows in (mix_rows, nat_rows):
        for r in rows:
            r["share"] = {}
            for p in cols:
                tot = sum((x["vals"].get(p) or 0) * (-1 if x["id"] == "elim" else 1) for x in rows)
                r["share"][p] = r["vals"][p] / tot if r["vals"].get(p) and tot and r["id"] != "elim" else None

    # lifecycle (rule-based evidence)
    last2 = fys[-2:]
    cd = [L[p].get("capex_da") for p in last2 if L[p].get("capex_da") is not None]
    cd_avg = sum(cd) / len(cd) if cd else None
    gpm_trend = (L[fys[-1]]["gpm"] - L[base]["gpm"]) if L[fys[-1]].get("gpm") is not None and L[base].get("gpm") is not None else None
    da_vs_rev = (cagr3.get("da") - cagr3.get("rev")) if cagr3.get("da") is not None and cagr3.get("rev") is not None else None
    np_vs_rev = (cagr3.get("core_np") - cagr3.get("rev")) if cagr3.get("core_np") is not None and cagr3.get("rev") is not None else None
    ytd_d = L[ytd].get("gpm_chg") if ytd else None
    if cd_avg is None or gpm_trend is None:
        phase, why = "ไม่พอข้อมูล", []
    elif cd_avg >= 1.5 and ((da_vs_rev or 0) > 0 or gpm_trend < 0):
        phase = S.PH_INVEST + " — ลงทุนหนัก ค่าเสื่อมกดมาร์จิ้น"
    elif cd_avg >= 1.2 and gpm_trend >= 0:
        if da_vs_rev is not None and da_vs_rev <= 0:
            phase = S.PH_PEAK + " — ค่าเสื่อมโตไม่เร็วกว่ารายได้แล้ว มาร์จิ้นเริ่มดีขึ้น (ยืนยันด้วยค่าเสื่อมรายไตรมาสและภาระผูกพันในหมายเหตุงบ — ดู snapshot)"
        else:
            phase = S.PH_INVEST + " — ลงทุนต่อเนื่อง ค่าเสื่อมยังโตเร็วกว่ารายได้ แต่มาร์จิ้นเริ่มดีขึ้น"
    elif cd_avg < 1.2 and gpm_trend >= 0 and (np_vs_rev or 0) > 0:
        phase = S.PH_HARVEST + " — ลงทุนต่ำกว่าค่าเสื่อม มาร์จิ้นและกำไรโตเร็วกว่ารายได้"
    elif cd_avg < 1.2 and gpm_trend < 0:
        phase = S.PH_LATE + " — ลงทุนต่ำ แต่มาร์จิ้นเริ่มลดลง (ถ้าเริ่มโครงการใหม่ = เริ่มระยะลงทุนรอบใหม่)"
    elif (cd_avg < S.SAT_CAPEX_DA and gpm_trend >= 0 and (np_vs_rev or 0) <= 0
          and cagr3.get("rev") is not None and cagr3.get("core_np") is not None
          and cagr3["rev"] < S.SAT_GROWTH and cagr3["core_np"] < S.SAT_GROWTH):
        phase = S.PH_SAT + " — รายได้และกำไรปกติแทบไม่โต ลงทุนต่ำกว่าค่าเสื่อม"
    else:
        phase = "Transition (สัญญาณผสม)"
    lifecycle = {"phase": phase, "capex_da_avg_2y": cd_avg, "gpm_trend_3y": gpm_trend, "da_minus_rev_cagr3": da_vs_rev,
                 "corenp_minus_rev_cagr3": np_vs_rev, "ytd_gpm_chg": ytd_d,
                 "base": base, "rule": "ฐานแนวโน้ม = %s (ไม่ใช้ปีโควิด 2563–2565 เป็นฐาน); " % S.be(base) + "Capex/D&A เฉลี่ย 2 ปี ≥1.5 และ (ค่าเสื่อมโตเร็วกว่ารายได้ หรือ GPM ลดลง) = Investment; ≥1.2 และ GPM ดีขึ้น = Cost peak ถ้าค่าเสื่อมโตไม่เร็วกว่ารายได้ ไม่เช่นนั้น Investment; "
                         "<1.2, GPM ดีขึ้น และกำไรปกติโตเร็วกว่ารายได้ = Harvest; <1.2 แต่ GPM ลด = Late harvest; "
                         "<1.2 และรายได้/กำไรปกติโต < %.0f%% ต่อปี = Saturation" % (S.SAT_GROWTH * 100)}

    # operating-leverage phase by year (คุณ Pop's lens): profit growth ÷ revenue growth and the margin on extra revenue
    lev_rows = []
    for i, per in enumerate(fys[1:], 1):
        p0, p1_ = L[fys[i - 1]], L[per]
        pk = "core_pbt_x" if p1_.get("core_pbt_x") is not None and p0.get("core_pbt_x") is not None else "core_pbt"
        rg, pg = S.pct(p1_.get("rev"), p0.get("rev")), S.pct(p1_.get(pk), p0.get(pk))
        mult = pg / rg if rg is not None and pg is not None and rg > 0.005 else None
        inc, gpm_ = p1_.get("incr_gpm"), p1_.get("gpm")
        fl = ""        # a warning sign, not a phase (GLOSSARY.md). Cost peak is not decided per year: it needs quarterly D&A + commitments
        if rg is None or pg is None:
            ph = "–"
        elif rg <= 0.005:
            if pg > 0.05:
                ph, fl = S.PH_NONE, S.FLAG_COSTCUT
            elif abs(pg) <= 0.05 and (p1_.get("capex_da") or 0) < S.SAT_CAPEX_DA:
                ph = S.PH_SAT
            else:
                ph, fl = S.PH_NONE, S.FLAG_FLAT
        elif mult >= 2 and (inc is None or (gpm_ is not None and inc > gpm_)):
            ph = S.PH_HARVEST
        elif mult >= 0.8:
            ph = S.PH_LATE
        elif (p1_.get("capex_da") or 0) >= 1.5:
            ph = S.PH_INVEST
        else:
            ph, fl = S.PH_NONE, S.FLAG_SQUEEZE
        lev_rows.append({"fy": per, "rev_g": rg, "pbt_g": pg, "pbt_key": pk, "mult": mult, "incr_gpm": inc, "gpm": gpm_,
                         "sga_g": p1_.get("sga_g"), "phase": ph, "flag": fl, "shown": ph + (" — " + fl if fl else ""), "covid": int(per[2:]) <= 2022})
    post = [r for r in lev_rows if not r["covid"]] or lev_rows
    last2 = [r["phase"] for r in post[-2:]]
    pop_phase = post[-1]["phase"] if post else "–"
    pop_flag = post[-1]["flag"] if post else ""
    if len(last2) == 2 and last2[0] == S.PH_HARVEST and last2[1] == S.PH_LATE:
        pop_note = "leverage เริ่มอ่อนลง: จากระยะเก็บเกี่ยวไปสู่ช่วงท้าย — ความคาดหวังลด เสี่ยง P/E ถูกปรับลด"
    elif len(last2) == 2 and last2[1] == S.PH_HARVEST:
        pop_note = "ต้นทุนคงที่ยังไม่เพิ่ม กำไรโตเร็วกว่ารายได้หลายเท่า — ช่วงที่ดีที่สุดของหุ้นเติบโต"
    elif pop_phase == S.PH_INVEST:
        pop_note = "ลงทุนหนักและต้นทุนโตตามรายได้ (โครงการใหม่ยัง Ramp-up) — ติดตามอัตราการครองเตียงและจุดคุ้มทุน"
    elif pop_phase == S.PH_SAT:
        pop_note = "รายได้และกำไรนิ่ง ลงทุนต่ำ — เป็นหุ้นปันผลเว้นแต่จะเริ่มลงทุนรอบใหม่"
    elif pop_flag == S.FLAG_SQUEEZE:
        pop_note = "รายได้โตแต่ต้นทุนโตเร็วกว่า ทั้งที่ไม่ได้ลงทุนหนัก — หาสาเหตุจากเอกสาร (ค่าแพทย์/ค่าแรง, อัตรา สปส./บัตรทอง, ส่วนผสมผู้ป่วย)"
    elif pop_flag == S.FLAG_COSTCUT:
        pop_note = "กำไรมาจากการลดต้นทุน ไม่ใช่การเติบโต — ทำซ้ำได้จำกัด"
    else:
        pop_note = ""
    lifecycle_pop = {"rows": lev_rows, "phase": pop_phase, "flag": pop_flag, "shown": pop_phase + (" — " + pop_flag if pop_flag else ""), "note": pop_note}

    # quality scorecard (transparent)
    last = L[fys[-1]]
    comp = []

    def sc(name, val, pts, why):
        comp.append({"name": name, "value": val, "score": pts, "why": why})
    roe = last.get("roe")
    if roe is not None:
        sc("ผลตอบแทน (ROE ปีล่าสุด)", roe, 10 if roe >= 0.20 else 8 if roe >= 0.15 else 6 if roe >= 0.10 else 4 if roe >= 0.05 else 2, "%.1f%%" % (roe * 100))
    g3 = cagr3.get("rev")
    if g3 is not None:
        sc("การเติบโต (Revenue CAGR %d ปี จาก%s)" % (n3, S.be(base)), g3, 9 if g3 > 0.10 else 7 if g3 > 0.05 else 5 if g3 >= 0 else 2, "%.1f%%" % (g3 * 100))
    if last.get("de") is not None:
        de, nc = last["de"], last.get("net_cash") or 0
        sc("ฐานะการเงิน (D/E, เงินสดสุทธิ)", de, 10 if nc > 0 and de < 0.3 else 8 if nc > 0 else 6 if de < 1 else 3, "D/E %.2f เท่า, เงินสดสุทธิ %s ลบ." % (de, "{:,.0f}".format(nc)))
    cc = [L[p].get("cfo_ebitda") for p in fys[-3:] if L[p].get("cfo_ebitda") is not None]
    if cc:
        a = sum(cc) / len(cc)
        sc("คุณภาพกระแสเงินสด (CFO/EBITDA เฉลี่ย 3 ปี)", a, 9 if a >= 0.85 else 7 if a >= 0.75 else 5 if a >= 0.6 else 3, "%.2f เท่า" % a)
    ro = last.get("roic")
    if ro is not None:
        po = last.get("payout")
        pts = 9 if ro >= 0.15 else 7 if ro >= 0.10 else 5 if ro >= 0.06 else 3
        sc("การจัดสรรเงินทุน (ROIC, payout)", ro, min(10, pts + (1 if po and 0.4 <= po <= 0.9 else 0)),
           "ROIC %.1f%%%s" % (ro * 100, (", payout %.0f%%" % (po * 100)) if po else ""))
    gt = gpm_trend
    if gt is not None:
        sc("แนวโน้มมาร์จิ้น (GPM %d ปี จาก%s)" % (n3, S.be(base)), gt, 9 if gt > 0.02 else 7 if gt > 0 else 5 if gt > -0.02 else 3, "%+.1f pt" % (gt * 100))
    score = round(sum(c["score"] for c in comp) / len(comp), 1) if comp else None

    # flags: FY last vs prior > 15%
    flags = []
    p1, p0 = fys[-1], fys[-2] if len(fys) > 1 else None
    if p0:
        for k in ("rev", "gp", "sga", "np_owners", "core_np", "da", "capex", "recv", "cash_total", "cfo"):
            c = S.pct(L[p1].get(k), L[p0].get(k))
            if c is not None and abs(c) > 0.15 and abs((L[p1].get(k) or 0) - (L[p0].get(k) or 0)) >= 5:
                lab = dict(LINES_FY).get(k) or dict(S.LINE_DEFS).get(k, k)
                flags.append({"id": "fy_%s" % k, "change": c, "text": "%s %s %+.1f%% (%s → %s ลบ.)" % (
                    lab, S.be(p1), c * 100, "{:,.2f}".format(L[p0][k]), "{:,.2f}".format(L[p1][k]))})
    for r in nature:
        a, b = r["share"].get(p1), r["share"].get(p0) if p0 else None
        if a is not None and b is not None and abs(a - b) >= 0.01:
            flags.append({"id": "nature_%s" % r["id"], "change": a - b, "text": "%s/รายได้ %s %.1f%% เทียบ %.1f%% (%+.1f pt)" % (
                r["label"], S.be(p1), a * 100, b * 100, (a - b) * 100)})

    # peers (real data only: other stocks' financials.json under the same root)
    peer_rows = []
    root = root or S.peers_root(sdir)
    if S.FS_DIR:
        import build_finance_sheet as BF
        cands = peers if peers is not None else [t for t in BF.HOSPITAL_CATEGORY if t != ticker]
        for t in cands:
            pd = os.path.join(root, t)
            fp = os.path.join(pd, "report", "%s_financials.json" % t)
            if not os.path.isfile(fp):
                continue
            try:
                pf = S.load_json(fp)
                pfx = S.F(pf, {})
                py_ = sorted(y2 for y2 in pf.get("years", []) if pfx.get("rev_hosp", "FY%d" % y2) is not None)
                if not py_:
                    continue
                prv = fy_lines(pfx, "FY%d" % (py_[-1] - 1)) if len(py_) > 1 else None
                pl = fy_lines(pfx, "FY%d" % py_[-1], prv)
                cand = [y2 for y2 in py_[-4:-1] if y2 >= 2023] or py_[-4:-1]
                by = cand[0] if cand else None
                p3 = fy_lines(pfx, "FY%d" % by) if by else None
                pn = py_[-1] - by if by else 0
                pm = S.load_json(os.path.join(pd, "report", "%s_mda.json" % t))
                am = ((pm.get("revenue_mix") or {}).get("annual") or {}).get("FY%d" % py_[-1]) or {}
                nm = ((pm.get("nationality") or {}).get("annual") or {}).get("FY%d" % py_[-1]) or {}
                peer_rows.append({"ticker": t, "category": BF.HOSPITAL_CATEGORY.get(t), "fy": "FY%d" % py_[-1], "rev": pl.get("rev"),
                                  "cagr": cagr(p3.get("rev"), pl.get("rev"), pn) if p3 else None, "cagr_base": "FY%d" % by if by else None, "gpm": pl.get("gpm"), "npm": pl.get("npm"),
                                  "roe": pl.get("roe"), "de": pl.get("de"), "net_cash": pl.get("net_cash"),
                                  "sso_share": (am.get("sso") / pl["rev"]) if am.get("sso") and pl.get("rev") else None,
                                  "foreign_share": (nm.get("foreign") / pl["rev"]) if nm.get("foreign") and pl.get("rev") else None,
                                  "src": os.path.relpath(fp, root)})
            except Exception as e:  # a broken peer file must not stop the report
                peer_rows.append({"ticker": t, "error": str(e)})
    selfrow = {"ticker": ticker, "category": cat, "fy": fys[-1], "rev": last.get("rev"), "cagr": cagr3.get("rev"), "cagr_base": base, "gpm": last.get("gpm"),
               "npm": last.get("npm"), "roe": last.get("roe"), "de": last.get("de"), "net_cash": last.get("net_cash"),
               "sso_share": next(((r["vals"].get(fys[-1]) or 0) / last["rev"] for r in mix_rows if r["id"] == "sso" and last.get("rev")), None),
               "foreign_share": next(((r["vals"].get(fys[-1]) or 0) / last["rev"] for r in nat_rows if r["id"] == "foreign" and last.get("rev")), None),
               "src": "this report"}

    # candidates for the agent (capacity, occupancy, targets)
    cap = candidates(sdir, r"เตียง|อัตราการครองเตียง|อัตราครองเตียง|occupan|ห้องตรวจ|\bbeds?\b", 30)
    tgt = candidates(sdir, r"เป้าหมาย|ตั้งเป้า|คาดว่า.*(ปี|เติบโต)|guidance|target|แผนการลงทุน|งบลงทุน|capex", 30)

    checks = []
    for per in fys:
        a_, l_, e_ = L[per].get("assets"), L[per].get("liab"), L[per].get("tot_equity")
        if None not in (a_, l_, e_):
            checks.append({"label": "สมการงบดุล A = L + E (%s)" % S.be(per), "ok": abs(a_ - l_ - e_) < 0.5, "detail": "%.2f" % (a_ - l_ - e_)})
    for per in fys + [x for x in (ytd, ytd_py) if x]:
        st = ((mda.get("recon") or {}).get(per) or {}).get("status") or {}
        if st and any(r["vals"].get(per) for r in mix_rows + nat_rows):
            checks.append({"label": "โครงสร้างรายได้ MD&A = รายได้ในงบ ±1 ลบ. (%s)" % S.be(per),
                           "ok": all(v in ("PASS", "NO_REPORTED") for v in st.values()), "detail": str(st)})
    mk = dict(asm.get("market") or {}) or S.set_factsheet_price(sdir, ticker)
    # price = valuation + narrative (expectation − disappointment)
    ql = {}

    def QL(q):
        if q not in ql:
            ql[q] = S.period_lines(fx, q, oo_pre=OO[0], oo_sga=OO[1])
        return ql[q]
    np1, np0 = S._ttm(QL, q_last, "core_np"), S._ttm(QL, S.qadd(q_last, -4), "core_np")
    mk_now = S.price_near(sdir, ticker, q_last, asm)
    val = S.valuation_view(mk_now.get("price"), mk_now.get("shares_mn"), np1, np0, mk_now.get("dps_last_fy")) if mk_now else None
    if val and cagr3.get("core_np"):
        val["np_cagr3"] = cagr3["core_np"]
        val["peg_cagr3"] = val["pe"] / (cagr3["core_np"] * 100) if cagr3["core_np"] > 0 else None
    qpeers = {r["ticker"]: r for r in S.peer_rows(root, ticker, cat, q_last, peers)} if S.FS_DIR else {}
    for r in peer_rows:
        qp = qpeers.get(r.get("ticker")) or {}
        r.update({k: qp.get(k) for k in ("pe", "peg", "np_g", "mult")})
    expect = {"valuation": val, "phase": pop_phase, "note": pop_note}
    comp_name = asm.get("company") or {}
    extra = DX.load(sdir, ticker, fys, ytd, ytd_py)       # by-hospital table, project file, Oppday operating metrics (all optional)
    sec = DSEC.load(sdir, ticker)                          # section 7: sector trend and the stock's position (data/sector/...)
    extra["extra_pcts"] = (extra.get("extra_pcts") or []) + sec.pop("sector_pcts", [])
    vz = DV.load(sdir, ticker)                             # section 2: ten years from the Jitta factsheet
    extra["extra_pcts"] = (extra.get("extra_pcts") or []) + vz.pop("viz_pcts", [])
    extra.update(vz)
    extra.update(sec)
    pack = dict(extra, **{
        "roots": {"ai_root": S.ai_root(sdir), "peers_root": root},
        "papers": S.papers(sdir, q_last),
        "analyst_notes": reference_notes(sdir, q_last),
        "ticker": ticker, "stock_dir": os.path.abspath(sdir), "generated": datetime.now().isoformat(timespec="seconds"),
        "company": {"name_th": comp_name.get("name_th"), "name_en": comp_name.get("name_en")},
        "category": cat, "category_name": S.CATEGORY_NAMES.get(cat, str(cat)), "has_sso": has_sso,
        "fys": fys, "trend_base": base, "trend_years": n3, "ytd": ytd, "ytd_py": ytd_py, "q_last": q_last, "lines": L, "cagr": cagrs, "cagr3": cagr3, "n_years": n,
        "nature": nature, "mix_rows": mix_rows, "nat_rows": nat_rows, "lifecycle": lifecycle, "lifecycle_pop": lifecycle_pop, "expect": expect,
        "scorecard": {"score": score, "components": comp}, "flags": flags, "checks": checks,
        "peers": [selfrow] + [p for p in peer_rows if "error" not in p], "peer_errors": [p for p in peer_rows if "error" in p],
        "one_offs": asm.get("one_offs") or [], "market": mk,
        "cap_candidates": cap, "target_candidates": tgt,
        "sources": {"financials": fin_p, "mda": mda_p, "assumptions": asm_p if os.path.isfile(asm_p) else None,
                    "fact_src": {k: v for k, v in fx.src.items() if k.split("|")[1] in fys + [p for p in (ytd, ytd_py) if p]}},
        "val_assumptions": asm.get("valuation") or {},
    })
    pack["val_block"] = DVAL.compute(pack)
    return pack


# ------------------------------------------------------------------------------------------ digest
def f2(v, pctv=False, d=2):
    return S.f2(v, pctv, d)


def digest(p):
    out = []
    w = out.append
    fys, L = p["fys"], p["lines"]
    cols = fys + ([p["ytd_py"], p["ytd"]] if p["ytd"] else [])
    w("%s %s | %s | FY %s–%s + %s vs %s" % (p["ticker"], p["company"].get("name_th") or "", p["category_name"], S.be(fys[0]), S.be(fys[-1]),
                                          S.be(p["ytd"]) if p["ytd"] else "-", S.be(p["ytd_py"]) if p["ytd_py"] else "-"))
    rt, s_ = p.get("roots") or {}, p.get("sector") or {}
    w("ROOTS: data root=%s | peers root=%s (%d peers) | sector data=%s" % (
        rt.get("ai_root") or "NOT FOUND", rt.get("peers_root"), len(p.get("peers") or []), ("MISSING " + str(s_.get("missing"))) if s_.get("missing") else "ok"))
    if not rt.get("ai_root") or s_.get("missing") or not p.get("peers"):
        w("  ⚠ INCOMPLETE INPUTS: set AI_ROOT to the folder that holds data/ and Thstock/ (WSL: /mnt/c/ai), or run on the master copy. "
          "Sector and peer numbers cannot be sourced until this is fixed.")
    an = p.get("analyst_notes") or {}
    if an.get("notes") or an.get("posts"):
        names = S.analyst_names(an)
        w("\nREFERENCE ANALYST (%s) — READ FIRST. His way of reading sets the questions and the order of this report; write "
          "what he says in `pop_view`. His figures are still checked against the filings: a difference goes to `conflicts`. "
          "Read the notes, then the posts from the newest back until nothing new comes up." % ", ".join(names))
        if len(names) > 1:
            w("  More than one reference analyst: give every `pop_view` row a `who` (%s) and write at least one row for each."
              % " / ".join(names))
        for n in an.get("notes") or []:
            tag = "" if (n.get("who") or S.DEFAULT_ANALYST) == S.DEFAULT_ANALYST else " [%s]" % n["who"]
            w("  REFERENCE NOTE%s%s: %s" % (" %s" % n["period"] if n.get("period") else "", tag, n["file"]))
        for n in an.get("posts") or []:
            w("  REFERENCE POST %s [%s, %s chars] %s — %s" % (n["date"], n.get("period") or "-", n.get("chars"), n.get("title"), n["file"]))
        tail = []
        if an.get("more"):
            tail.append("%d older own posts" % an["more"])
        if an.get("undated"):
            tail.append("%d undated own posts (not used: no date, no way to rule out hindsight)" % an["undated"])
        if an.get("shared"):
            tail.append("%d posts he only shared (other people's material: tier 2, not his view)" % an["shared"])
        if tail:
            w("  ALSO in %s: %s" % (an.get("index"), "; ".join(tail)))
    w("\n%-12s " % "THB mn" + " ".join("%10s" % S.be(c)[-8:] for c in cols))
    for k, lab in LINES_FY:
        vals = []
        for c in cols:
            v = L.get(c, {}).get(k)
            vals.append(f2(v, k in PCTK) if k not in RATIO else ("%.2f" % v if v is not None else "·"))
        w("%-12s " % k + " ".join("%10s" % x for x in vals))
    w("growth YoY (rev/gp/core_np): " + "; ".join("%s %s/%s/%s" % (S.be(c), f2(L[c].get("rev_g"), True), f2(L[c].get("gp_g"), True),
                                                                   f2(L[c].get("core_np_g"), True)) for c in cols if L.get(c, {}).get("rev_g") is not None))
    w("CAGR %d-year: " % p["n_years"] + "; ".join("%s %s" % (k, f2(v, True)) for k, v in p["cagr"].items()) +
      " | %d-year from %s: " % (p["trend_years"], S.be(p["trend_base"])) + "; ".join("%s %s" % (k, f2(v, True)) for k, v in p["cagr3"].items()))
    for r in p["nature"]:
        w("NATURE %-14s " % r["id"] + " ".join("%s %s (%s)" % (S.be(c)[-4:], f2(r["vals"].get(c)), f2(r["share"].get(c), True)) for c in fys))
    for r in p["mix_rows"] + p["nat_rows"]:
        w("MIX %-8s " % r["id"] + " ".join("%s %s (%s)" % (S.be(c)[-7:], f2(r["vals"].get(c)), f2(r["share"].get(c), True)) for c in cols if r["vals"].get(c)))
    lc = p["lifecycle"]
    w("LIFECYCLE rule → %s | capex/D&A 2y %.2f | GPM since base %+.2fpt | D&A−rev CAGR %s | coreNP−rev CAGR %s" % (
        lc["phase"], lc["capex_da_avg_2y"] or 0, (lc["gpm_trend_3y"] or 0) * 100, f2(lc["da_minus_rev_cagr3"], True), f2(lc["corenp_minus_rev_cagr3"], True)))
    lp = p.get("lifecycle_pop") or {}
    w("OPERATING LEVERAGE by year (profit growth ÷ revenue growth): " + "; ".join("%s rev %s %s %s x%s incrGPM %s → %s%s" % (
        S.be(r["fy"]), f2(r["rev_g"], True), r["pbt_key"], f2(r["pbt_g"], True), f2(r["mult"], d=1), f2(r["incr_gpm"], True), r["phase"],
        " (COVID)" if r["covid"] else "") for r in lp.get("rows") or []))
    w("PHASE (investor lens): %s — %s" % (lp.get("shown") or lp.get("phase"), lp.get("note")))
    v = (p.get("expect") or {}).get("valuation")
    if v:
        w("VALUATION: P/E core TTM %.1f, core NP TTM growth %s, PEG %s; CAGR from base %s → PEG %s | %s" % (
            v["pe"], f2(v.get("np_g"), True), f2(v.get("peg")), f2(v.get("np_cagr3"), True), f2(v.get("peg_cagr3")), v["label"]))
    sc = p["scorecard"]
    w("QUALITY SCORE %s/10: " % sc["score"] + "; ".join("%s %d (%s)" % (c["name"], c["score"], c["why"]) for c in sc["components"]))
    vb = p.get("val_block") or {}
    if vb.get("ok"):
        w("VAL SCENARIOS: " + "; ".join("%s %.2f บ. (%+.1f%%)" % (x["name"], x["value"], x["chg"] * 100) for x in vb["scenarios"]) +
          ("; end-state div %s" % ", ".join("%.0f%%→%.2f" % (e["payout"] * 100, e["value"]) for e in vb.get("end_state") or [])))
    w("PEERS (from their own financials.json): " + "; ".join("%s cat%s %s rev %s GPM %s ROE %s D/E %s P/E %s PEG %s" % (
        r["ticker"], r.get("category"), S.be(r["fy"]), f2(r.get("rev"), d=0), f2(r.get("gpm"), True), f2(r.get("roe"), True),
        ("%.2f" % r["de"]) if r.get("de") is not None else "·", f2(r.get("pe"), d=1), f2(r.get("peg"))) for r in p["peers"]))
    for x in DSEC.digest_lines(p):
        w(x)
    w("FLAGS needing a sourced explanation:")
    for fl in p["flags"]:
        w("  %s: %s" % (fl["id"], fl["text"]))
    if p["one_offs"]:
        w("ONE-OFFS: " + "; ".join("%s %+.2f %s" % (o["period"], o["amount_after_tax"], o.get("label", "")[:60]) for o in p["one_offs"]))
    w("CAPACITY candidates (read around these lines; beds/occupancy must be sourced):")
    for h in p["cap_candidates"][:20]:
        w("  %s:%d [%s] %s" % (h["file"], h["line"], h["doc"], h["text"][:110]))
    w("TARGET/GUIDANCE candidates:")
    for h in p["target_candidates"][:20]:
        w("  %s:%d [%s] %s" % (h["file"], h["line"], h["doc"], h["text"][:110]))
    pp = p.get("papers") or {}
    if pp.get("stock_index") or pp.get("sector_index") or pp.get("industry_notes"):
        w("\nRESEARCH PAPERS (tier 2 — cross-check and industry picture only, always external; target prices and ratings are never used):")
        if pp.get("stock_index"):
            w("  BROKER PAPERS on this stock: %d cards, read the index first -> %s" % (pp.get("stock_total", 0), pp["stock_index"]))
        if pp.get("sector_index"):
            w("  SECTOR PAPERS -> %s" % pp["sector_index"])
        if pp.get("industry_notes"):
            w("  INDUSTRY NOTES (dated summary) -> %s" % pp["industry_notes"])
    return "\n".join(out)


# ------------------------------------------------------------------------------------------ check
def pack_numbers(p):
    amounts, pcts = set(), set()

    def add(t, x):
        for d in (0, 1, 2):
            t.add((d, round(abs(x), d)))

    def walk(o, key=""):
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, k)
        elif isinstance(o, list):
            for v in o:
                walk(v, key)
        elif isinstance(o, (int, float)) and not isinstance(o, bool):
            if key in PCTK or key.endswith("_g") or key.endswith("_chg") or key in ("gpm_trend_3y", "da_minus_rev_cagr3", "corenp_minus_rev_cagr3",
                                                                                     "ytd_gpm_chg", "incr_gpm") or key.startswith("exp_") and False:
                add(pcts, o * 100)
            else:
                add(amounts, o)
    walk({k: v for k, v in p.items() if k not in ("sources", "cap_candidates", "target_candidates")})
    for r in p["nature"] + p["mix_rows"] + p["nat_rows"]:
        for v in (r.get("share") or {}).values():
            if v is not None:
                add(pcts, v * 100)
    for v in p.get("extra_pcts") or []:                 # shares, margins and growth the by-hospital / ops tables derive
        add(pcts, v)
    for k in ("cagr", "cagr3"):
        for v in p[k].values():
            if v is not None:
                add(pcts, v * 100)
    for c in p["scorecard"]["components"]:
        if c["value"] is not None and c["name"].startswith(("ผลตอบแทน", "การเติบโต", "การจัดสรร", "แนวโน้ม")):
            add(pcts, c["value"] * 100)
    for r in p["peers"]:
        for k in ("cagr", "gpm", "npm", "roe", "sso_share", "foreign_share"):
            if r.get(k) is not None:
                add(pcts, r[k] * 100)
    return amounts, pcts


def check_narrative(p, nar):
    amounts, pcts = pack_numbers(p)
    years = set()
    for c in list(p["lines"]) + [p["q_last"]]:
        m = re.search(r"(\d{4})", c)
        if m:
            yy = int(m.group(1))
            years |= {yy, yy + 543, yy - 1, yy + 542, yy + 1, yy + 544, yy + 2, yy + 545, yy + 3, yy + 546}
    problems = []

    def ok(tok):
        t = tok.replace(",", "").replace("−", "-").strip()
        is_pct = t.endswith("%")
        t = t.rstrip("%").strip()
        try:
            v = abs(float(t))
        except ValueError:
            return True
        dec = len(t.split(".")[1]) if "." in t else 0
        if not is_pct and dec == 0 and (v in years or v <= 12):
            return True
        return (dec, round(v, dec)) in (pcts if is_pct else amounts)

    def visit(item, path):
        if isinstance(item, dict) and "text" in item:
            if item.get("src") or item.get("external"):
                return
            item = item["text"]
        if isinstance(item, str):
            txt = re.sub(r"\[[^\]]*\]", "", item)
            txt = re.sub(r"(Q[1-4]|[1-4]Q|[69]M|12M)[/ ]?\d{2,4}", "", txt)
            for tok in S.NUM_RE.findall(txt):
                if not ok(tok):
                    problems.append("%s: '%s' not in data pack — add \"src\" or mark external" % (path, tok.strip()))
        elif isinstance(item, list):
            for i, x in enumerate(item):
                visit(x, "%s[%d]" % (path, i))
        elif isinstance(item, dict):
            for k, x in item.items():
                if k in ("external", "src"):
                    continue
                visit(x, "%s.%s" % (path, k))
    visit({k: v for k, v in nar.items() if k not in ("external", "capacity", "guidance", "pending", "conflicts")}, "narrative")
    visit((nar.get("capacity") or {}).get("notes") or [], "narrative.capacity.notes")
    capn = nar.get("capacity") or {}
    for i, r in enumerate((capn.get("rows") or []) + (capn.get("history") or [])):
        if not r.get("src") and not r.get("external"):
            problems.append("capacity row %d (%s) has no src — beds/occupancy must come from a document" % (i, r.get("hospital") or r.get("year")))
    pv = nar.get("pivot")
    if pv and not (pv.get("title") and pv.get("if_fails") and pv.get("if_works")):
        problems.append("pivot needs title, if_fails and if_works — the make-or-break point is argued on both sides")
    for i, q in enumerate(nar.get("pending") or []):
        if not (isinstance(q, dict) and q.get("question") and q.get("why")):
            problems.append("pending[%d] needs question and why" % i)
    for i, g in enumerate(nar.get("guidance") or []):
        if not g.get("src"):
            problems.append("guidance row %d has no src (where/when management said it)" % i)
    # section 7: the stock's place in the sector and the leading indicators (the owner's alpha question)
    sv = nar.get("sector_view") or {}
    if sv and (p.get("sector") or {}).get("missing"):
        problems.append("sector data not found (%s): the narrative has a sector_view but its numbers cannot be sourced. Set AI_ROOT to the "
                        "folder that holds data/ and Thstock/ (WSL: /mnt/c/ai) or run script/sector/sector_trend.py" % p["sector"]["missing"])
    if (p.get("sector") or {}).get("rows") and not nar.get("_auto") and not sv.get("position"):
        problems.append("the digest has SECTOR & POSITION but the narrative has no `sector_view.position` (where the stock "
                        "stands against the median and why)")
    for i, it in enumerate(sv.get("leading") or []):
        if not (isinstance(it, dict) and (it.get("src") or it.get("external"))):
            problems.append("sector_view.leading[%d] needs a src (a leading indicator must be found in a document)" % i)
    problems.extend(DPOP.problems(p, nar))      # K. Pop checklist answers (section 14.1)
    # the reference analyst: his view has its own block; his figures are still checked against the filings
    PV = ("confirmed", "differs", "not_in_filings", "opinion")
    cfs = [c for c in nar.get("conflicts") or [] if isinstance(c, dict)]
    for i, it in enumerate(nar.get("pop_view") or []):
        if not isinstance(it, dict) or not it.get("text"):
            problems.append("pop_view[%d] must be an object with text, src and verdict" % i)
            continue
        if "analyst_notes" not in str(it.get("src", "")):
            problems.append("pop_view[%d].src must point into md/analyst_notes/<file> (his own note or post)" % i)
        if it.get("verdict") not in PV:
            problems.append("pop_view[%d].verdict must be one of %s" % (i, ", ".join(PV)))
        if it.get("verdict") == "differs" and not any("analyst_notes" in str(c.get("second_src", "")) for c in cfs):
            problems.append("pop_view[%d] says the filings differ: add the row to `conflicts` with second_src in md/analyst_notes/" % i)
    an = p.get("analyst_notes") or {}
    if (an.get("notes") or an.get("posts")) and not nar.get("pop_view") and not nar.get("_auto"):
        problems.append("the stock has reference-analyst notes (digest: REFERENCE ANALYST) but the narrative has no `pop_view`")
    elif nar.get("pop_view") and not nar.get("_auto"):
        for x in S.analyst_gaps(an, nar.get("pop_view")):
            problems.append("reference analyst %s has notes in the digest but no row in `pop_view` (set `who` on the rows)" % x)
    for i, c in enumerate(nar.get("conflicts") or []):
        miss = [k for k in ("topic", "second", "second_src", "primary", "primary_src") if not (isinstance(c, dict) and c.get(k))]
        if miss:
            problems.append("conflicts[%d] is missing %s" % (i, ", ".join(miss)))
        elif not re.search(r"second_source|third_source|analyst_notes|paper/_pack|data/sector|\.card\.md", c["second_src"]):
            problems.append("conflicts[%d].second_src must point into second_source/, third_source/, analyst_notes/ or a paper card" % i)

    def tier(item, path):
        if isinstance(item, list):
            for i, x in enumerate(item):
                tier(x, "%s[%d]" % (path, i))
        elif isinstance(item, dict):
            if (re.search(r"second_source|third_source|paper/_pack|data/sector|\.card\.md", str(item.get("src", ""))) and not item.get("external")
                    and not path.startswith("narrative.conflicts")):
                problems.append("%s cites a second/third source but is not marked \"external\": true" % path)
            for k, x in item.items():
                tier(x, "%s.%s" % (path, k))
    tier(nar, "narrative")
    expl = nar.get("explanations") or {}
    for fid in sorted({f["id"] for f in p["flags"]} - set(expl)):
        problems.append("flag '%s' has no explanation (shown as 🚩 Unexplained)" % fid)
    for fid, e in expl.items():
        if isinstance(e, dict) and not e.get("src"):
            problems.append("explanation '%s' has no src" % fid)
    return problems


# ------------------------------------------------------------------------------------------ CLI
def sdir_for(a):
    if a.stock_dir:
        return S.check_stock_dir(a.stock_dir)
    root = S.find_root(a.root)
    if not root:
        raise RuntimeError("Thstock root not found; pass --stock-dir")
    return os.path.join(root, a.ticker)


def cmd_data(a):
    sd = sdir_for(a)
    p = build_pack(sd, a.ticker, a.rebuild, peers=a.peers.split(",") if a.peers else None)
    out = os.path.join(sd, "report", "%s_deepdive_data.json" % a.ticker)
    json.dump(p, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    print(digest(p))
    print("\n-> %s\nnarrative file: %s" % (out, os.path.join(sd, "report", "%s_deepdive_narrative.json" % a.ticker)))
    return 0


def cmd_check(a):
    sd = sdir_for(a)
    p = S.load_json(os.path.join(sd, "report", "%s_deepdive_data.json" % a.ticker)) or build_pack(sd, a.ticker)
    nar = S.load_json(a.narrative or os.path.join(sd, "report", "%s_deepdive_narrative.json" % a.ticker))
    if not nar:
        print("no narrative file")
        return 2
    probs = check_narrative(p, nar)
    for x in probs:
        print("  ⚠", x)
    print("RESULT: %s (%d issue%s)" % ("CLEAN ✅" if not probs else "REVIEW", len(probs), "" if len(probs) == 1 else "s"))
    return 0 if not probs else 1


def cmd_render(a):
    import render_deepdive as R
    sd = sdir_for(a)
    p = build_pack(sd, a.ticker, a.rebuild, quiet=True, peers=a.peers.split(",") if getattr(a, "peers", None) else None)
    json.dump(p, open(os.path.join(sd, "report", "%s_deepdive_data.json" % a.ticker), "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    nar_p = a.narrative or os.path.join(sd, "report", "%s_deepdive_narrative.json" % a.ticker)
    nar = {} if a.auto else S.load_json(nar_p)
    probs = check_narrative(p, nar) if nar else []
    md, html = R.write(p, nar, os.path.join(sd, "report"), probs, a.version)
    print("✅ %s\n✅ %s%s" % (md, html, "" if nar else "   (automatic narrative — no %s)" % os.path.basename(nar_p)))
    if probs:
        print("⚠ %d narrative issue(s) — listed in section 10" % len(probs))
    return 0


def cmd_run(a):
    tickers = [t.upper() for t in a.tickers]
    if a.file:
        for ln in open(a.file, encoding="utf-8"):
            ln = ln.split("#")[0].strip()
            tickers += [t.upper() for t in re.split(r"[,\s]+", ln) if t]
    root = S.find_root(a.root)
    res = []
    for t in dict.fromkeys(tickers):
        print("━━━ %s ━━━" % t)
        try:
            cmd_render(argparse.Namespace(stock_dir=os.path.join(root, t) if root else None, ticker=t, rebuild=a.rebuild, narrative=None,
                                          auto=a.auto, version=None, root=a.root, peers=None))
            res.append((t, "OK"))
        except Exception as e:
            print("   ❌ %s" % e)
            res.append((t, "ERROR: %s" % e))
    print("━━━ Summary ━━━")
    for t, s in res:
        print(" %-8s %s" % (t, s))
    return 0 if all(s == "OK" for _, s in res) else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("data", "render", "check"):
        s = sub.add_parser(name)
        s.add_argument("--stock-dir")
        s.add_argument("--ticker", required=True)
        s.add_argument("--root")
        s.add_argument("--rebuild", action="store_true")
        s.add_argument("--peers", help="comma-separated peer tickers (default: every hospital with report/<T>_financials.json)")
        s.add_argument("--narrative")
        s.add_argument("--auto", action="store_true")
        s.add_argument("--version")
    s = sub.add_parser("run")
    s.add_argument("tickers", nargs="*")
    s.add_argument("-f", "--file")
    s.add_argument("--root")
    s.add_argument("--rebuild", action="store_true")
    s.add_argument("--auto", action="store_true")
    a = ap.parse_args()
    if getattr(a, "ticker", None):
        a.ticker = a.ticker.upper()
    return {"data": cmd_data, "render": cmd_render, "check": cmd_check, "run": cmd_run}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
