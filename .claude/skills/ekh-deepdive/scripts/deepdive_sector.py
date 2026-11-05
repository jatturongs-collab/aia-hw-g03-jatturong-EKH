#!/usr/bin/env python3
"""
deepdive_sector.py - section 7 of the deep dive: the sector and where this stock stands in it.

Reads  <AI_ROOT>/data/sector/<Sector>/sector_trend.json   (script/sector/sector_trend.py, from the factsheets)
       <AI_ROOT>/data/sector/<Sector>/sector_analysis_*.md (the dated reading of the sector: why, and what next)

load() adds p["sector"]:
  windows     sector total, ex-largest company, median company, the stock's group and the stock itself, per window
              (pre-COVID trend, from the pre-COVID year, post-COVID, latest half-year)
  rank        the stock's place among the core panel in each window (1 = fastest) and its percentile
  signals     early signs computed from the quarterly series, which move before the annual numbers:
                acceleration   latest half-year growth vs the stock's own post-COVID CAGR, and vs the sector median
                quarters       the last six quarters of revenue YoY, stock vs sector median, and the direction
                margin         net margin of the latest half-year vs the same half a year earlier
                rank_move      rank in the latest half-year vs rank over the post-COVID years
              each signal carries a verdict: better / worse / neutral
  analysis    the newest sector_analysis_*.md, to read for the reasons and the outlook

The numbers are the factsheet compilation (tier 2 for one company; the company's own tables in sections 1-6 use its
filings). The narrative adds `sector_view` (see references/narrative_schema.md): where the stock stands and why, and
the leading indicators Claude found in the documents (SSO insured counts, new beds, Oppday volumes, guidance changes,
policy decisions), each with a source.
"""
import glob
import json
import os
import statistics as st

DEFAULT_SECTOR = "Hospital"


def _root(sdir):
    from snapshot import ai_root       # AI_ROOT only; snapshot stops the run if it is missing
    return ai_root(sdir)


def _rank(vals, t):
    """1 = highest. vals: {ticker: value}."""
    xs = sorted([(v, k) for k, v in vals.items() if v is not None], reverse=True)
    for i, (_, k) in enumerate(xs, 1):
        if k == t:
            return i, len(xs)
    return None, len(xs)


def load(sdir, ticker, sector=DEFAULT_SECTOR):
    base = os.path.join(_root(sdir), "data", "sector", sector)
    p = os.path.join(base, "sector_trend.json")
    if not os.path.isfile(p):
        return {"sector": {"missing": p}}
    j = json.load(open(p, encoding="utf-8"))
    first, last = j["first_year"], j["last_year"]
    W = [("pre", "%d-2019" % first, "ก่อนโควิด %d–%d" % (first + 543, 2019 + 543)),
         ("since19", "2019-%d" % last, "จากปีก่อนโควิด %d–%d" % (2019 + 543, last + 543)),
         ("post", "2023-%d" % last, "หลังโควิด %d–%d" % (2023 + 543, last + 543))]
    core = j["core"].get("members") or j["core"]["tickers"]
    comp = j.get("companies", {})
    group = next((g for g, b in j.get("groups", {}).items() if ticker in b["tickers"]), None)
    status = "core" if ticker in core else ("structure" if ticker in j.get("structure_changes", {}) else
                                             ("non_core" if ticker in j.get("non_core", []) else "short_history"))
    rows, pcts, ranks = [], [], {}
    for key, w, lab in W:
        stock = (comp.get(ticker) or {}).get("cagr", {}).get(w)
        r, n = _rank(dict({t: comp[t]["cagr"].get(w) for t in core if t in comp}, **({ticker: stock} if stock is not None else {})), ticker)
        ranks[key] = (r, n)
        row = {"key": key, "label": lab, "sector": j["core"]["cagr"].get(w, {}).get("rev"),
               "median": j.get("core_median_cagr", {}).get(w), "iqr": j.get("core_iqr_cagr", {}).get(w),
               "group": (j["groups"][group]["median_cagr"].get(w) if group else None), "stock": stock, "rank": r, "n": n}
        rows.append(row)
    hy = j.get("half_year") or {}
    hyc = dict(hy.get("by_company") or [])
    q = j.get("quarterly") or {}
    qs = q.get("quarters") or []
    qc = (q.get("companies") or {}).get(ticker) or {}
    stock_h = hyc.get(ticker)
    if stock_h is None and qc and len(qs) >= 2:                       # not in the core panel: from its own quarters
        stock_h = None
    rh, nh = _rank(hyc, ticker) if ticker in hyc else (None, len(hyc))
    ranks["half"] = (rh, nh)
    rows.append({"key": "half", "label": "ครึ่งปีล่าสุด %s เทียบ %s" % (_half_label(hy.get("period", "")), _half_label(hy.get("vs", ""))),
                 "sector": hy.get("total"), "median": hy.get("median"), "iqr": None,
                 "group": (st.median([hyc[t] for t in j["groups"][group]["tickers"] if t in hyc]) if group and any(
                     t in hyc for t in j["groups"][group]["tickers"]) else None),
                 "stock": stock_h, "rank": rh, "n": nh})
    for r in rows:
        pcts += [v * 100 for v in (r["sector"], r["median"], r["group"], r["stock"]) if v is not None]
        if r.get("iqr"):
            pcts += [v * 100 for v in r["iqr"]]
        if r["stock"] is not None and r["median"] is not None:
            r["gap"] = r["stock"] - r["median"]
            pcts.append(r["gap"] * 100)

    # ---- early signals
    sig = []
    post = next(r for r in rows if r["key"] == "post")
    if stock_h is not None and post["stock"] is not None:
        acc = stock_h - post["stock"]
        vs_med = stock_h - (hy.get("median") or 0)
        verdict = "better" if acc > 0.02 and vs_med > 0 else ("worse" if acc < -0.02 and vs_med < 0 else "neutral")
        sig.append({"id": "acceleration", "verdict": verdict,
                    "text": "รายได้ครึ่งปีล่าสุดโต %s เทียบ CAGR หลังโควิดของตัวเอง %s (%s จุด) และเทียบ median กลุ่ม %s (%s จุด)" % (
                        _p(stock_h), _p(post["stock"]), _pp(acc), _p(hy.get("median")), _pp(vs_med))})
        pcts += [stock_h * 100, post["stock"] * 100, acc * 100, vs_med * 100]
    yo = qc.get("rev_yoy") or {}
    med = q.get("core_median_rev_yoy") or {}
    if len(yo) >= 4:
        seq = [(k, yo.get(k), med.get(k)) for k in qs]
        last3 = [v for k, v, m in seq[-3:] if v is not None]
        beat = sum(1 for k, v, m in seq[-4:] if v is not None and m is not None and v > m)
        trend = "ขึ้น" if len(last3) == 3 and last3[2] > last3[0] + 0.01 else ("ลง" if len(last3) == 3 and last3[2] < last3[0] - 0.01 else "ทรง")
        verdict = "better" if beat >= 3 and trend != "ลง" else ("worse" if beat <= 1 and trend != "ขึ้น" else "neutral")
        sig.append({"id": "quarters", "verdict": verdict, "seq": seq,
                    "text": "รายได้ YoY รายไตรมาสแนวโน้ม%s; ชนะ median กลุ่ม %d ใน 4 ไตรมาสล่าสุด" % (trend, beat)})
        pcts += [v * 100 for k, v, m in seq if v is not None] + [m * 100 for k, v, m in seq if m is not None]
    if qc.get("npm_half") is not None and qc.get("npm_half_py") is not None:
        dm = qc["npm_half"] - qc["npm_half_py"]
        sig.append({"id": "margin", "verdict": "better" if dm > 0.01 else ("worse" if dm < -0.01 else "neutral"),
                    "text": "อัตรากำไรสุทธิครึ่งปีล่าสุด %s เทียบช่วงเดียวกันปีก่อน %s (%s จุด; รวมรายการพิเศษ ตรวจกับกำไรปกติในข้อ 1)" % (
                        _p(qc["npm_half"]), _p(qc["npm_half_py"]), _pp(dm))})
        pcts += [qc["npm_half"] * 100, qc["npm_half_py"] * 100, dm * 100]
    if ranks.get("post", (None,))[0] and rh:
        rp, n1 = ranks["post"]
        up = rh < rp and (rp - rh >= 2 or rh <= 3)
        down = rh > rp and (rh - rp >= 2 or rh > nh - 3)
        sig.append({"id": "rank_move", "verdict": "better" if up else ("worse" if down else "neutral"),
                    "text": "อันดับการเติบโตในกลุ่ม: หลังโควิด %d จาก %d → ครึ่งปีล่าสุด %d จาก %d" % (rp, n1, rh, nh)})
    # ---- COVID-cycle fingerprint (owner, 10 Oct 2026): normal years before COVID vs the last three, 2020-2022 left out
    fp = j.get("fingerprint") or {}
    fc = (fp.get("companies") or {}).get(ticker) or (fp.get("all") or {}).get(ticker)
    fpo = None
    if fp.get("companies"):
        fpo = {"pre": fp["pre"], "post": fp["post"], "stock": fc, "median": fp.get("median") or {}, "count": fp.get("count") or {}}
        for c in (fc or {}, fpo["median"]):
            for k, v in c.items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    pct_like = k.startswith(("rev_cagr", "gpm_", "npm_", "roe_", "netcash_eq", "payout_"))
                    pcts.append(v * 100 if pct_like else v)
    an = sorted(glob.glob(os.path.join(base, "sector_analysis_*.md")))
    out = {"sector": {"name": sector, "file": p, "analysis": an[-1] if an else None, "first": first, "last": last,
                      "status": status, "group": group, "rows": rows, "signals": sig, "core_n": len(core), "fingerprint": fpo,
                      "largest": "BDMS" if "BDMS" in core else None, "source": j.get("source"),
                      "notes_file": os.path.join(base, "industry_notes.md") if os.path.isfile(os.path.join(base, "industry_notes.md")) else None}}
    return dict(out, sector_pcts=pcts)


def _half_label(per):
    """2026Q1+2026Q2 -> 1H/2569; 2025Q3+2025Q4 -> 2H/2568; other pairs -> Q1-Q2/2569 style."""
    try:
        a, b = per.split("+")
        y = int(b[:4]) + 543
        if a[-1] == "1" and b[-1] == "2":
            return "1H/%d" % y
        if a[-1] == "3" and b[-1] == "4":
            return "2H/%d" % y
        return "Q%s–Q%s/%d" % (a[-1], b[-1], y)
    except Exception:
        return per


def _p(v, d=1):
    return "–" if v is None else "%+.*f%%" % (d, v * 100)


def _pp(v):
    return "–" if v is None else "%+.1f" % (v * 100)


VERD = {"better": "🟢 ดีขึ้น", "worse": "🔴 แย่ลง", "neutral": "⚪ ทรงตัว"}

STAGE = {"spending_now": "กำลังลงทุนขยาย capacity (capex/ค่าเสื่อมปีล่าสุดสูง)",
         "spent": "ลงทุนขยายไปแล้วในช่วงหลังโควิด ตอนนี้อยู่ช่วงเร่งใช้ capacity ใหม่",
         "cash_pile": "เก็บเงินสดไว้ ยังไม่ได้ใช้ขยาย (ROE ถูกกดด้วยเงินสด)",
         "paying_out": "คืนเงินให้ผู้ถือหุ้นมากขึ้น (payout เพิ่ม)",
         "other": "ไม่เข้าแบบใดชัดเจน"}

FP_ROWS = [  # key, label, kind (pct = percent, x = multiple, pair = pre/post pair)
    ("rev_cagr", "รายได้ CAGR ในช่วง", "pct"),
    ("npm", "อัตรากำไรสุทธิ", "pct"),
    ("roe", "ROE เฉลี่ย", "pct"),
    ("netcash_eq", "เงินสดสุทธิต่อส่วนของผู้ถือหุ้น (ปลายช่วง)", "pct"),
    ("de", "หนี้สินรวมต่อส่วนของผู้ถือหุ้น (ปลายช่วง)", "x"),
    ("payout", "อัตราการจ่ายปันผลเฉลี่ย", "pct"),
    ("capex_da", "capex ต่อค่าเสื่อม [คำนวณ]", "x"),
]


def _fx(v):
    return "–" if v is None else "%.2f เท่า" % v


def _fp_rows(f):
    c, m = f.get("stock") or {}, f.get("median") or {}
    out = []
    for k, lab, kind in FP_ROWS:
        fmt = (lambda v: "–" if v is None else "%.1f%%" % (v * 100)) if kind == "pct" else _fx
        out.append([lab, fmt(c.get(k + "_pre")), fmt(c.get(k + "_post")), fmt(m.get(k + "_pre")), fmt(m.get(k + "_post"))])
    out.append(["ส่วนของผู้ถือหุ้นเฉลี่ย หลัง ÷ ก่อน", "", _fx(c.get("equity_x")), "", _fx(m.get("equity_x"))])
    out.append(["กำไรสุทธิรวม หลัง ÷ ก่อน", "", _fx(c.get("np_x")), "", _fx(m.get("np_x"))])
    out.append(["capex ต่อค่าเสื่อม ปีล่าสุด [คำนวณ]", "", _fx(c.get("capex_da_last")), "", _fx(m.get("capex_da_last"))])
    return out


def digest_lines(p):
    s = p.get("sector") or {}
    if not s or s.get("missing"):
        return ["SECTOR: no sector_trend.json (%s) — run script/sector/sector_trend.py first" % (s or {}).get("missing")]
    out = ["\nSECTOR & POSITION (factsheet compilation, core panel %d companies; the stock's own tables use its filings):" % s["core_n"]]
    out.append("  status: %s%s" % (s["status"], (" | group: %s" % s["group"]) if s.get("group") else ""))
    for r in s["rows"]:
        out.append("  %-34s sector %7s | median %7s | group %7s | %s %7s | rank %s/%s | gap vs median %s" % (
            r["label"], _p(r["sector"]), _p(r["median"]), _p(r["group"]), p["ticker"], _p(r["stock"]),
            r["rank"] or "–", r["n"], _pp(r.get("gap"))))
    for g in s["signals"]:
        out.append("  SIGNAL %-12s %-8s %s" % (g["id"], g["verdict"], g["text"]))
    f = s.get("fingerprint")
    if f:
        cn = f["count"]
        out.append("  COVID-CYCLE FINGERPRINT %s vs %s (2020-2022 left out): followed the cycle (ROE down, equity grew faster than profit) %s of %s hospitals" % (
            f["pre"], f["post"], cn.get("follows_cycle"), cn.get("n")))
        if f.get("stock"):
            c = f["stock"]
            out.append("    %s: stage %s | follows cycle %s | flags %s" % (p["ticker"], c.get("stage"), c.get("follows_cycle"),
                       ", ".join(k for k, v in (c.get("flags") or {}).items() if v) or "none"))
        for r in _fp_rows(f):
            out.append("    %-44s %s pre %-10s post %-10s | median pre %-10s post %s" % (r[0], p["ticker"], r[1], r[2], r[3], r[4]))
    out.append("  READ the sector reading -> %s (why the sector slowed, drivers 1-3 / 3-5 / 5-10 years, what makes alpha)" % s.get("analysis"))
    out.append("  WRITE `sector_view` (narrative_schema.md): position (where and why, vs median), leading indicators found in "
               "the documents with src (SSO insured in the catchment, new beds or branches, Oppday volume, guidance, policy), "
               "and what would show the turn first. Lead with signals that move before revenue.")
    return out


def render(d, p, nar, narrative_items):
    s = p.get("sector") or {}
    if not s or s.get("missing"):
        d.p("_ยังไม่มีข้อมูลอุตสาหกรรม (`data/sector/Hospital/sector_trend.json`) — รัน `script/sector/sector_trend.py` ก่อน_")
        return
    d.h(3, "7.1 ตำแหน่งของ %s ในอุตสาหกรรม (การเติบโตของรายได้ต่อปี)" % p["ticker"])
    rows = []
    for r in s["rows"]:
        iqr = ("%s ถึง %s" % (_p(r["iqr"][0]), _p(r["iqr"][1]))) if r.get("iqr") else "–"
        rows.append([r["label"], _p(r["sector"]), _p(r["median"]), iqr, _p(r["group"]), "**%s**" % _p(r["stock"]),
                     ("%s / %s" % (r["rank"], r["n"])) if r["rank"] else "–", _pp(r.get("gap"))])
    d.table(["ช่วง", "ทั้งกลุ่ม", "median บริษัท", "ครึ่งกลาง (IQR)", "กลุ่มย่อย" + (" (%s)" % s["group"] if s.get("group") else ""),
             p["ticker"], "อันดับ", "ห่าง median (จุด)"], rows, align=["l", "r", "r", "l", "r", "r", "r", "r"])
    note = {"core": "", "structure": " %s อยู่นอกกลุ่มหลักเพราะรายได้เปลี่ยนจากการรวม/แยกบริษัทย่อย จัดอันดับเพื่ออ้างอิงเท่านั้น" % p["ticker"],
            "non_core": " %s ไม่ใช่โรงพยาบาล (คลินิก/แล็บ) จึงไม่อยู่ในกลุ่มหลัก" % p["ticker"],
            "short_history": " %s มีข้อมูลไม่ครบ 10 ปี จึงจัดอันดับได้เฉพาะช่วงที่มีข้อมูล" % p["ticker"]}[s["status"]]
    d.p("_ที่มา: `%s` (factsheet ที่รวบรวมจากงบ, รายได้รวม) กลุ่มหลัก %d บริษัท ไม่รวมบริษัทที่รายได้เปลี่ยนจากการซื้อหรือขายกิจการ; "
        "%s มีน้ำหนักมากในยอดรวม จึงใช้ median เป็นตัวแทนบริษัททั่วไป.%s ตัวเลขของ %s ในข้อ 1–6 มาจากงบของบริษัทเอง_" % (
            os.path.basename(s["file"]), s["core_n"], s.get("largest") or "บริษัทใหญ่สุด", note, p["ticker"]))
    sv = (nar or {}).get("sector_view") or {}
    if sv.get("position"):
        d.b.append(("nlist", narrative_items(sv["position"])))

    f = s.get("fingerprint")
    if f and f.get("stock"):
        cn, c = f["count"], f["stock"]
        y = lambda w: "–".join(str(int(x) + 543) for x in w.split("-"))
        d.p("**วงจรหลังโควิด: เงินพิเศษกลายเป็นทุน แล้วไปไหนต่อ** (เทียบ %s กับ %s ตัดปีโควิด %s–%s ออก)" % (
            y(f["pre"]), y(f["post"]), 2020 + 543, 2022 + 543))
        d.table(["ตัวชี้วัด", "%s ก่อน" % p["ticker"], "%s หลัง" % p["ticker"], "median ก่อน", "median หลัง"], _fp_rows(f),
                align=["l", "r", "r", "r", "r"])
        d.p("_ทั้งกลุ่ม: %s จาก %s โรงพยาบาลเดินตามวงจร (ROE ลดและทุนโตเร็วกว่ากำไร). %s %sตามวงจรนี้; ระยะตอนนี้: **%s**. "
            "ทุน/กำไร = ค่าเฉลี่ยช่วงหลังหารช่วงก่อน; capex = ที่ดินอาคารอุปกรณ์สุทธิที่เพิ่ม + ค่าเสื่อม (คำนวณ, สัญญาเช่าและการขายสินทรัพย์ทำให้คลาดได้); "
            "ที่มา factsheet ชุดเดียวกัน_" % (cn.get("follows_cycle"), cn.get("n"), p["ticker"],
                                              "เป็นไป" if c.get("follows_cycle") else "ไม่เป็นไป", STAGE.get(c.get("stage"), c.get("stage"))))

    d.h(3, "7.2 สัญญาณล่วงหน้า (เห็นก่อนตัวเลขรายปี)")
    d.p("_ผลตอบแทนส่วนเกินมาจากการเห็นการเปลี่ยนก่อนตลาด ตัวชี้วัดด้านล่างขยับก่อนงบปี: "
        "การเติบโตรายไตรมาสเทียบกลุ่ม อัตรากำไรครึ่งปีล่าสุดเทียบปีก่อน และอันดับที่เลื่อน ส่วน \"ตัวชี้นำจากเอกสาร\" คือสิ่งที่ขยับก่อนรายได้_")
    if s["signals"]:
        d.table(["สัญญาณ (คำนวณ)", "ทิศทาง", "รายละเอียด"],
                [[{"acceleration": "การเร่ง/ชะลอ", "quarters": "รายไตรมาสเทียบกลุ่ม", "margin": "อัตรากำไรครึ่งปี", "rank_move": "อันดับในกลุ่ม"}.get(g["id"], g["id"]),
                  VERD[g["verdict"]], g["text"]] for g in s["signals"]], align=["l", "l", "l"])
        qsig = next((g for g in s["signals"] if g["id"] == "quarters"), None)
        if qsig:
            d.table(["ไตรมาส"] + [x[0][-2:] + "/" + str(int(x[0][:4]) + 543) for x in qsig["seq"]],
                    [[p["ticker"] + " รายได้ YoY"] + [_p(x[1]) for x in qsig["seq"]],
                     ["median กลุ่มหลัก"] + [_p(x[2]) for x in qsig["seq"]]])
    if sv.get("leading"):
        d.p("**ตัวชี้นำจากเอกสาร (ขยับก่อนรายได้)**")
        d.b.append(("nlist", narrative_items(sv["leading"])))
    if sv.get("watch"):
        d.p("**จะรู้ก่อนคนอื่นได้จากอะไร (ติดตามที่ไหน เมื่อไร)**")
        d.b.append(("nlist", narrative_items(sv["watch"])))
    if s.get("analysis"):
        d.p("_ภาพรวมอุตสาหกรรม ทำไมชะลอ และ driver ระยะสั้น/กลาง/ยาว: `%s`_" % os.path.basename(s["analysis"]))


def workbook(wb, s, ticker, styles):
    """Sheet 'อุตสาหกรรม': the 7.1 table and the quarterly signals. styles = (hdr_font, hdr_fill, body_font)."""
    if not s or s.get("missing"):
        return None
    hf, hfill, bf = styles
    ws = wb.create_sheet("อุตสาหกรรม")
    ws.append(["ตำแหน่งในอุตสาหกรรม (factsheet, กลุ่มหลัก %d บริษัท)" % s["core_n"]])
    ws.append(["ช่วง", "ทั้งกลุ่ม", "median", "กลุ่มย่อย", ticker, "อันดับ", "จาก", "ห่าง median"])
    for c in ws[2]:
        c.font, c.fill = hf, hfill
    for r in s["rows"]:
        ws.append([r["label"], r["sector"], r["median"], r["group"], r["stock"], r["rank"], r["n"], r.get("gap")])
    for row in ws.iter_rows(min_row=3, max_row=ws.max_row, min_col=2, max_col=5):
        for c in row:
            c.number_format = "0.0%"
    for row in ws.iter_rows(min_row=3, max_row=ws.max_row, min_col=8, max_col=8):
        for c in row:
            c.number_format = "0.0%"
    ws.append([])
    ws.append(["สัญญาณ", "ทิศทาง", "รายละเอียด"])
    for c in ws[ws.max_row]:
        c.font, c.fill = hf, hfill
    for g in s["signals"]:
        ws.append([g["id"], g["verdict"], g["text"]])
    f = s.get("fingerprint")
    if f and f.get("stock"):
        ws.append([])
        ws.append(["วงจรหลังโควิด %s vs %s" % (f["pre"], f["post"]), ticker + " ก่อน", ticker + " หลัง", "median ก่อน", "median หลัง"])
        for c in ws[ws.max_row]:
            c.font, c.fill = hf, hfill
        for r in _fp_rows(f):
            ws.append(r)
        ws.append(["ระยะตอนนี้", STAGE.get(f["stock"].get("stage"), "")])
    ws.column_dimensions["A"].width = 38
    ws.column_dimensions["C"].width = 14
    for col in "BDEFGH":
        ws.column_dimensions[col].width = 12
    return ws.title
