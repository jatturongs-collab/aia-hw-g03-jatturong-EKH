"""
render_deepdive.py - Markdown + HTML for the stock-deepdive skill.  Uses the snapshot renderer's building blocks
(Doc, to_md, to_html, SVG charts) so both reports share one look.
"""
import os
import re
from datetime import datetime

import snapshot as S
from render import Doc, to_md, to_html, n2, p1, chg, pt, item_text, narrative_items, next_version, RED, _compress_checks
from deepdive import LINES_FY, RATIO
import deepdive_extra as DX
import deepdive_sector as DSEC
import deepdive_pop as DPOP
import deepdive_val as DVAL
import deepdive_viz as DV

LAB = dict(LINES_FY)


def sfy(per):
    """short label for chart axes: 68 / 6M69"""
    m = re.fullmatch(r"FY(\d{4})", per)
    if m:
        return str(int(m.group(1)) + 543)
    m = re.fullmatch(r"(\d+)M(\d{4})", per)
    return "%sM%s" % (m.group(1), str(int(m.group(2)) + 543)[-2:]) if m else per


def fmt(k, v):
    if v is None:
        return "–"
    if k in RATIO:
        return "%.2f" % v
    if k in ("gpm", "sga_pct", "ebit_m", "npm", "ebitda_m", "roe", "roa", "roic", "payout"):
        return p1(v)
    if k in ("eps", "dps"):
        return "%.2f" % v
    if k == "dso":
        return "%.0f" % v
    return n2(v)


def auto_narrative(p):
    fys, L, c = p["fys"], p["lines"], p["cagr"]
    a, b = fys[0], fys[-1]
    s = []
    if c.get("rev") is not None:
        s.append("รายได้โรงพยาบาล %s → %s ลบ. (%s–%s, CAGR %s); กำไรปกติ %s → %s ลบ. (CAGR %s)" % (
            n2(L[a]["rev"]), n2(L[b]["rev"]), S.be(a), S.be(b), p1(c["rev"]), n2(L[a].get("core_np")), n2(L[b].get("core_np")), p1(c.get("core_np"))))
    base = p["trend_base"]
    if L[b].get("gpm") is not None and L[base].get("gpm") is not None:
        s.append("GPM %s → %s (%s เทียบฐาน %s); ROE ล่าสุด %s, ROIC %s" % (p1(L[base]["gpm"]), p1(L[b]["gpm"]), pt(L[b]["gpm"] - L[base]["gpm"]),
                                                                      S.be(base), p1(L[b].get("roe")), p1(L[b].get("roic"))))
    s.append("วัฏจักรตามกฎตัวเลข: %s" % p["lifecycle"]["phase"])
    lp = p.get("lifecycle_pop") or {}
    if lp.get("phase"):
        s.append("ช่วงธุรกิจ (มุมนักลงทุน): %s — %s" % ((lp.get("shown") or lp["phase"]), lp.get("note") or ""))
    if L[b].get("net_cash") is not None:
        s.append("ฐานะการเงิน: เงินสดสุทธิ %s ลบ., D/E %s เท่า, payout %s" % (n2(L[b]["net_cash"]), fmt("de", L[b].get("de")), p1(L[b].get("payout"))))
    if p["ytd"]:
        y = L[p["ytd"]]
        s.append("ล่าสุด %s เทียบ %s: รายได้ %s, กำไรปกติ %s, GPM %s" % (S.be(p["ytd"]), S.be(p["ytd_py"]), chg(y.get("rev_g")), chg(y.get("core_np_g")),
                                                                         pt(y.get("gpm_chg"))))
    return {"_auto": True, "summary": s}


def build_doc(p, nar, problems):
    auto = not nar or nar.get("_auto")
    if auto:
        nar = auto_narrative(p)
    fys, L = p["fys"], p["lines"]
    cols = fys + ([p["ytd_py"], p["ytd"]] if p["ytd"] else [])
    d = Doc()
    name = p["company"].get("name_th") or p["company"].get("name_en") or p["ticker"]
    d.h(1, "🏛️ รายงานวิเคราะห์เชิงลึกหลายปี (Stock Deep-Dive) — %s" % p["ticker"])
    d.p("**%s** | %s" % (name, p["category_name"]))
    d.ul(["**ช่วงข้อมูล:** %s–%s (%d ปีบัญชี) + %s เทียบ %s" % (S.be(fys[0]), S.be(fys[-1]), len(fys), S.be(p["ytd"]) if p["ytd"] else "-",
                                                                 S.be(p["ytd_py"]) if p["ytd_py"] else "-"),
          "**สร้างเมื่อ:** %s" % datetime.now().strftime("%Y-%m-%d %H:%M"),
          "**ที่มาของตัวเลข:** งบการเงินที่ยื่น SET (`%s`, มีบรรทัดอ้างอิงทุกตัวเลข), โครงสร้างรายได้จาก MD&A (`%s`), รายการพิเศษจาก `%s`" % (
              os.path.basename(p["sources"]["financials"] or "-"), os.path.basename(p["sources"]["mda"] or "-"), os.path.basename(p["sources"]["assumptions"] or "-")),
          "**ปีโควิด:** %s–%s เป็นปีที่รายได้/กำไรผิดปกติจากโควิด — แนวโน้มและคะแนนใช้ฐาน %s" % (S.be("FY2020"), S.be("FY2022"), S.be(p["trend_base"])),
          "**บทวิเคราะห์เชิงคุณภาพ:** " + ("⚠️ อัตโนมัติจากตัวเลขเท่านั้น — ข้อมูลเตียง/อัตราครองเตียง/เป้าหมายผู้บริหาร/คู่แข่งเชิงคุณภาพ ต้องให้ Claude รัน skill `stock-deepdive`"
                                           if auto else "เขียนจาก One Report/MD&A/Oppday ทุกข้อที่มีตัวเลขนอกงบมีแหล่งอ้างอิง")])
    ok = all(c["ok"] for c in p["checks"])
    d.callout("tip" if ok else "warning", "การตรวจสอบความถูกต้อง: %s" % ("ผ่านทั้งหมด" if ok else "มีรายการไม่ผ่าน"),
              ["%s %s" % ("✅" if c["ok"] else "❌", c["label"]) for c in _compress_checks(p["checks"])])
    sc = p["scorecard"]
    args = (d, p, nar, L, fys, cols, sc)
    d.h(2, "🗺️ 0. Overview: อุตสาหกรรมและโรงพยาบาลของบริษัท")
    DV.render_overview(d, p, nar, narrative_items)
    d.h(2, "📍 1. ตำแหน่งในอุตสาหกรรมและสัญญาณล่วงหน้า")
    DV.render_position(d, p, nar, narrative_items)
    d.h(2, "📈 2. ผลงาน 10 ปี (Jitta factsheet)")
    DV.render_ten_years(d, p)
    DV.render_year_events(d, p, nar, narrative_items)
    _sec_mix(*args)
    _sec_capacity(*args)
    _sec_lifecycle(*args)
    _sec_moat(*args)
    _sec_roadmap(*args)
    _sec_macro(*args)
    _sec_exec(*args)
    _sec_financials(*args)
    d.h(2, "💰 11. การประเมินมูลค่า (P/E, EV/EBITDA, ROIC)")
    DV.render_valuation(d, p)
    DVAL.render(d, p)
    _sec_capital(*args)
    d.h(2, "❓ 13. คำถามที่ยังไม่มีคำตอบ และสิ่งที่ต้องติดตาม")
    DV.render_open_questions(d, p, nar)
    _sec_score(*args)
    _sec_pop(*args)
    _sec_verify(*args, problems=problems)
    return d


def _sec_exec(d, p, nar, L, fys, cols, sc):
    d.h(2, "🧭 9. บทสรุปผู้บริหาร")
    if nar.get("headline"):
        d.p("**%s**" % nar["headline"])
    lp = p.get("lifecycle_pop") or {}
    d.p("**คะแนนคุณภาพทางการเงิน: %s / 10** (กฎโปร่งใส ดูข้อ 14) | **วัฏจักรตามกฎตัวเลข:** %s | **ช่วงธุรกิจ (กำไรโต ÷ รายได้โต):** %s" % (
        sc["score"], p["lifecycle"]["phase"], (lp.get("shown") or lp.get("phase", "–"))))
    ex = p.get("expect") or {}
    v = ex.get("valuation")
    xl = []
    if v:
        xl.append("**มูลค่า:** P/E กำไรปกติ TTM %s เท่า, กำไรปกติ TTM โต %s (CAGR จากฐาน %s) → PEG %s (%s) — %s" % (
            n2(v["pe"], 1), chg(v.get("np_g")), p1(v.get("np_cagr3")), n2(v.get("peg")), n2(v.get("peg_cagr3")), v["label"]))
    if lp.get("phase"):
        xl.append("**เรื่องเล่า:** ช่วง%s — %s" % ((lp.get("shown") or lp["phase"]), lp.get("note") or "ดูตาราง 5.1"))
    if xl or nar.get("expectation"):
        d.h(3, "ราคา = มูลค่า + เรื่องเล่า (เรื่องเล่า = ความคาดหวัง − ความผิดหวัง)")
        d.ul(xl)
        d.b.append(("nlist", narrative_items(nar.get("expectation"))))
    d.b.append(("nlist", narrative_items(nar.get("summary"))))
    popv = [it for it in nar.get("pop_view") or [] if isinstance(it, dict) and it.get("text")]
    if popv:
        PVL = {"confirmed": "✅ ตรงกับเอกสารบริษัท", "differs": "⚠️ ต่างจากเอกสารบริษัท (ดูตารางเทียบแหล่งข้อมูล ข้อ 15)",
               "not_in_filings": "ไม่มีในเอกสารบริษัท ยังตรวจไม่ได้", "opinion": "ความเห็น/การตีความ"}
        an = p.get("analyst_notes")
        names = S.analyst_names(an, popv)
        if names == [S.DEFAULT_ANALYST]:
            d.h(3, "มุมมองของคุณ Pop (นักวิเคราะห์อ้างอิง)")
            d.p("_รายงานนี้ใช้วิธีอ่านของคุณ Pop เป็นหลักในการตั้งประเด็นและลำดับการวิเคราะห์ ตัวเลขในตารางทุกตัวยังมาจากเอกสารที่บริษัทยื่นต่อ ตลท. "
                "ตัวเลขจากบันทึกและโพสต์ของเขาถูกตรวจกับเอกสารและระบุผลไว้ท้ายแต่ละข้อ_")
            d.table(["ประเด็นที่คุณ Pop ชี้", "ผลการตรวจกับเอกสารบริษัท", "ที่มา"],
                    [[it["text"], PVL.get(it.get("verdict"), it.get("verdict", "")), "<small>%s</small>" % it.get("src", "")] for it in popv],
                    align=["l", "l", "l"])
        else:
            d.h(3, "มุมมองของนักวิเคราะห์อ้างอิง (%s)" % ", ".join(names))
            d.p("_รายงานนี้ใช้วิธีอ่านของนักวิเคราะห์อ้างอิงเป็นหลักในการตั้งประเด็นและลำดับการวิเคราะห์ ตัวเลขในตารางทุกตัวยังมาจากเอกสารที่บริษัทยื่นต่อ ตลท. "
                "ตัวเลขจากบันทึก โพสต์ และการบรรยายของแต่ละท่านถูกตรวจกับเอกสารและระบุผลไว้ท้ายแต่ละข้อ_")
            d.table(["นักวิเคราะห์", "ประเด็นที่ชี้", "ผลการตรวจกับเอกสารบริษัท", "ที่มา"],
                    [[S.row_analyst(it, an), it["text"], PVL.get(it.get("verdict"), it.get("verdict", "")), "<small>%s</small>" % it.get("src", "")]
                     for it in popv], align=["l", "l", "l", "l"])
    pv = nar.get("pivot") or {}
    if pv:
        # the one point that is both the largest risk and the largest opportunity of this stock (not the generic risk list)
        d.h(3, "จุดชี้ชะตาของหุ้นตัวนี้: %s" % item_text(pv.get("title", ""))[0])
        for lab, key in (("ถ้าไม่สำเร็จ", "if_fails"), ("ถ้าสำเร็จ", "if_works"), ("สัญญาณที่จะบอกผล และเอกสารที่จะเห็น", "watch")):
            if pv.get(key):
                d.p("**%s**" % lab)
                d.b.append(("nlist", narrative_items(pv[key])))
    if nar.get("pending"):
        d.p("_มีคำถามที่เอกสารยังตอบไม่ได้ %d ข้อ — ดูข้อ 13_" % len(nar["pending"]))

def _sec_financials(d, p, nar, L, fys, cols, sc):
    # 1 ------------------------------------------------------------------
    d.h(2, "📊 10. การเปลี่ยนแปลงทางการเงินรอบ %d ปีจากงบ (Multi-Year Financial Transformation, ใช้อ้างอิง)" % len(fys))
    rows, bold = [], []
    show = ["rev", "total_rev", "gp", "gpm", "sga", "sga_pct", "ebit", "ebit_m", "np_owners", "npm", "one_off", "core_np", "da", "ebitda", "ebitda_m",
            "cash_total", "net_cash", "liab", "tot_equity", "de", "roe", "roic", "dso", "cfo", "capex", "capex_da", "fcf", "cfo_ebitda", "eps", "dps", "payout"]
    for k in show:
        vals = [L.get(c, {}).get(k) for c in cols]
        if all(v is None for v in vals):
            continue
        rows.append([LAB[k]] + [fmt(k, v) for v in vals])
        if k in ("rev", "gp", "np_owners", "core_np"):
            bold.append(len(rows) - 1)
        if k in ("rev", "gp", "core_np"):
            rows.append(["&nbsp;&nbsp;% เติบโต YoY"] + [chg(L.get(c, {}).get(k + "_g")) if c != p["ytd_py"] else "–" for c in cols])
    head = ["รายการ (ล้านบาท)"] + [S.be(c) for c in cols]
    d.table(head, rows, bold_rows=bold)
    d.p("_%s เทียบกับ %s (ช่วงเดียวกัน) ไม่เทียบกับทั้งปี; ROE/ROIC ของงวดสะสมเป็นตัวเลขปรับเต็มปี; DPS จาก Jitta/SET (พื้นเหลืองในโมเดล)_" % (
        S.be(p["ytd"]) if p["ytd"] else "-", S.be(p["ytd_py"]) if p["ytd_py"] else "-"))
    c = p["cagr"]
    d.p("**CAGR %d ปี (%s–%s):** รายได้ %s, กำไรขั้นต้น %s, EBITDA %s, กำไรปกติ %s, ส่วนของผู้ถือหุ้น %s | **CAGR %d ปีจากฐาน %s:** รายได้ %s, กำไรปกติ %s, ค่าเสื่อม %s" % (
        p["n_years"], S.be(fys[0]), S.be(fys[-1]), p1(c.get("rev")), p1(c.get("gp")), p1(c.get("ebitda")), p1(c.get("core_np")), p1(c.get("tot_equity")),
        p["trend_years"], S.be(p["trend_base"]), p1(p["cagr3"].get("rev")), p1(p["cagr3"].get("core_np")), p1(p["cagr3"].get("da"))))
    d.chart({"type": "bars", "title": "รายได้โรงพยาบาลรายปี (ล้านบาท)", "series": [{"name": "รายได้", "vals": [(sfy(x), L[x].get("rev")) for x in fys]}]})
    d.chart({"type": "bars", "title": "กำไรปกติรายปี (ล้านบาท)", "series": [{"name": "กำไรปกติ", "vals": [(sfy(x), L[x].get("core_np")) for x in fys]}]})
    d.chart({"type": "lines", "title": "มาร์จิ้นและผลตอบแทน (%)", "pct": True, "series": [
        {"name": "GPM", "vals": [(sfy(x), L[x].get("gpm")) for x in fys]},
        {"name": "ROE", "vals": [(sfy(x), L[x].get("roe")) for x in fys]},
        {"name": "ROIC", "vals": [(sfy(x), L[x].get("roic")) for x in fys]}]})
    d.b.append(("nlist", narrative_items(nar.get("transformation"))))

def _sec_mix(d, p, nar, L, fys, cols, sc):
    # 2 ------------------------------------------------------------------
    d.h(2, "🧩 3. โครงสร้างรายได้และต้นทุน")
    for rows_src, title in ((p["mix_rows"], "รายได้ตามประเภทผู้ป่วย (ล้านบาท, % ของรวม)"), (p["nat_rows"], "รายได้ตามสัญชาติ (ล้านบาท, % ของรวม)")):
        if not rows_src:
            continue
        mc = [x for x in cols if any(r["vals"].get(x) for r in rows_src)]
        rows = [[r["label"]] + [("%s<br><sub>%s</sub>" % (DV.n0(r["vals"][x] * (-1 if r["id"] == "elim" else 1)), p1(r["share"].get(x))) if r["share"].get(x) is not None
                                 else DV.n0(r["vals"][x] * (-1 if r["id"] == "elim" else 1))) if r["vals"].get(x) else "–" for x in mc] for r in rows_src]
        d.table([title] + [S.be(x) for x in mc], rows)
    src_rows = p["mix_rows"] or p["nat_rows"]
    stack = [r for r in src_rows if r["id"] != "elim"]
    if stack:
        tots = {}
        for x in fys:     # same base as the % column of the table: total after eliminations
            t = sum((r["vals"].get(x) or 0) * (-1 if r["id"] == "elim" else 1) for r in src_rows)
            if t:
                tots[sfy(x)] = t
        d.chart({"type": "stack", "title": "โครงสร้างรายได้รายปี (ล้านบาท, % ของรวม)", "pct_total": tots,
                 "note": "% ในแท่ง = สัดส่วนต่อรายได้จากกิจการโรงพยาบาลของปีนั้น เหมือนคอลัมน์ % ในตาราง; ส่วนที่เล็กเกินไปดูได้จากการชี้เมาส์",
                 "series": [{"name": r["label"], "vals": [(sfy(x), r["vals"].get(x)) for x in fys]} for r in stack]})
    if p["nature"]:
        rows = [[r["label"]] + ["%s (%s)" % (n2(r["vals"].get(x)), p1(r["share"].get(x))) if r["vals"].get(x) is not None else "–" for x in fys] for r in p["nature"]]
        d.table(["ค่าใช้จ่ายตามลักษณะ (ล้านบาท, % ของรายได้ รพ.)"] + [S.be(x) for x in fys], rows)
    DV.render_mix_half(d, p)
    DV.render_hospital_pnl(d, p)
    DX.render_hospitals(d, p)
    d.b.append(("nlist", narrative_items(nar.get("mix_notes"))))

def _sec_capacity(d, p, nar, L, fys, cols, sc):
    # 3 ------------------------------------------------------------------
    d.h(2, "🛏️ 4. ศักยภาพรองรับและอัตราครองเตียง (Capacity & Utilisation)")
    cap = nar.get("capacity") or {}
    if cap.get("rows"):
        rows = []
        for r in cap["rows"]:
            cells = [r.get("hospital", ""), r.get("location", "–"), str(r.get("beds_registered", "–")), str(r.get("beds_operating", "–")),
                     str(r.get("opd_rooms", "–")), str(r.get("occupancy", "ไม่เปิดเผย")), r.get("role", ""), r.get("src", "–")]
            if r.get("external"):
                cells = ['<span style="color:%s;font-weight:bold">%s</span>' % (RED, x) for x in cells]
            rows.append(cells)
        d.table(["โรงพยาบาล", "ที่ตั้ง", "เตียงจดทะเบียน", "เตียงให้บริการ", "ห้องตรวจ OPD", "อัตราครองเตียง", "บทบาท", "แหล่งที่มา"], rows,
                align=["l", "l", "r", "r", "r", "r", "l", "l"])
    if cap.get("history"):
        rows = [[h.get("year", ""), str(h.get("beds", "–")), str(h.get("occupancy", "ไม่เปิดเผย")), str(h.get("patient_days", "–")), h.get("note", ""), h.get("src", "–")]
                for h in cap["history"]]
        d.table(["ปี", "เตียง", "อัตราครองเตียง", "วันนอน", "หมายเหตุ", "แหล่งที่มา"], rows, align=["l", "r", "r", "r", "l", "l"])
    if not cap.get("rows") and not cap.get("history"):
        d.p("ไม่มีข้อมูลเตียงหรืออัตราครองเตียงที่อ้างอิงเอกสารได้ในรายงานนี้ — **ไม่ประมาณการเอง** (ให้ Claude อ่าน One Report/Oppday ตามบรรทัดที่ `deepdive.py data` แสดง)")
    DX.render_ops(d, p)
    DX.render_sso(d, p)
    d.b.append(("nlist", narrative_items(cap.get("notes"))))

def _sec_lifecycle(d, p, nar, L, fys, cols, sc):
    # 4 ------------------------------------------------------------------
    d.h(2, "💡 5. วัฏจักรธุรกิจและ operating leverage (Lifecycle)")
    lc = p["lifecycle"]
    d.table(["ตัวชี้วัดวัฏจักร", "ค่า"], [
        ["Capex / ค่าเสื่อม เฉลี่ย 2 ปีล่าสุด", "%.2f เท่า" % lc["capex_da_avg_2y"] if lc["capex_da_avg_2y"] is not None else "–"],
        ["GPM เปลี่ยนแปลงจากฐาน %s" % S.be(lc["base"]), pt(lc["gpm_trend_3y"])],
        ["CAGR ค่าเสื่อม − CAGR รายได้", pt(lc["da_minus_rev_cagr3"])],
        ["CAGR กำไรปกติ − CAGR รายได้", pt(lc["corenp_minus_rev_cagr3"])],
        ["GPM งวดสะสมล่าสุดเทียบปีก่อน", pt(lc["ytd_gpm_chg"])],
        ["**ผลตามกฎ**", "**%s**" % lc["phase"]]], align=["l", "r"])
    d.p("_กฎ: %s_" % lc["rule"])
    lp = p.get("lifecycle_pop") or {}
    if lp.get("rows"):
        d.h(3, "5.1 ช่วงธุรกิจจาก Operating Leverage (กำไรโตกี่เท่าของรายได้)")
        rows = [[S.be(r["fy"]) + (" (โควิด)" if r["covid"] else ""), chg(r["rev_g"]), chg(r["pbt_g"]), n2(r["mult"], 1), p1(r["incr_gpm"]), p1(r["gpm"]),
                 chg(r.get("sga_g")), "**%s**" % (r.get("shown") or r["phase"])] for r in lp["rows"]]
        d.table(["ปี", "รายได้โต", "Core PBT โต (ก่อน ECL/รายการพิเศษ)", "กำไรโต ÷ รายได้โต (เท่า)", "GP ส่วนเพิ่ม/รายได้ส่วนเพิ่ม", "GPM เฉลี่ย",
                 "SG&A โต", "ช่วง"], rows, align=["l"] + ["r"] * 6 + ["l"])
        d.p("_ช่วงเก็บเกี่ยว: ต้นทุนคงที่ไม่เพิ่ม รายได้ส่วนเพิ่มมีแต่ต้นทุนผันแปร กำไรโต ≥ 2 เท่าของรายได้ "
            "และ GP ส่วนเพิ่มสูงกว่า GPM เฉลี่ย | ปลายช่วงเก็บเกี่ยว: กำไรโตใกล้เคียงรายได้ (0.8–2 เท่า) — การเติบโตชะลอ ตลาดมัก de-rate P/E | "
            "กำไรโต < 0.8 เท่า: ระยะลงทุน ถ้า Capex ≥ 1.5 เท่าของค่าเสื่อม, ไม่เช่นนั้นเป็นสัญญาณเตือน «มาร์จิ้นถูกกด» (ไม่ใช่ช่วง) | อิ่มตัว: รายได้ไม่โต กำไรโตไม่เกิน ±5%% และ Capex < 1.2 เท่า | จุดต้นทุนพีค ไม่ตัดสินรายปี: ต้องยืนยันด้วยค่าเสื่อมรายไตรมาสและภาระผูกพันฯ (ดู snapshot). "
            "สรุปล่าสุด: **%s** — %s_" % ((lp.get("shown") or lp["phase"]), lp.get("note") or ""))
    lnar = nar.get("lifecycle") or {}
    if lnar.get("phase"):
        t, src, ext = item_text(lnar["phase"])
        d.p("**มุมมองจากเอกสาร:** %s%s" % (t, " [%s]" % src if src else ""))
    d.b.append(("nlist", narrative_items(lnar.get("reasoning"))))
    for cs in nar.get("case_studies") or []:
        d.h(3, cs.get("title", "กรณีศึกษา"))
        d.b.append(("nlist", narrative_items(cs.get("items"))))

def _sec_moat(d, p, nar, L, fys, cols, sc):
    # 5 ------------------------------------------------------------------
    d.h(2, "🏰 6. ทีมแพทย์ ป้อมปราการ และคู่แข่ง")
    d.b.append(("nlist", narrative_items(nar.get("moats"))))
    if nar.get("team"):
        d.h(3, "ทีมแพทย์และการหาแพทย์ (สิ่งที่ตึกใหม่ซื้อไม่ได้)")
        d.b.append(("nlist", narrative_items(nar["team"])))
    if len(p["peers"]) > 1:
        vv = (p.get("expect") or {}).get("valuation") or {}
        rows = [[("**%s**" % r["ticker"]) if r["ticker"] == p["ticker"] else r["ticker"], str(r.get("category") or "–"), S.be(r["fy"]), n2(r.get("rev"), 0),
                 p1(r.get("cagr")), p1(r.get("gpm")), p1(r.get("npm")), p1(r.get("roe")), fmt("de", r.get("de")), n2(r.get("net_cash"), 0),
                 p1(r.get("sso_share")), p1(r.get("foreign_share")),
                 n2(vv.get("pe") if r["ticker"] == p["ticker"] else r.get("pe"), 1), n2(vv.get("peg") if r["ticker"] == p["ticker"] else r.get("peg"))] for r in p["peers"]]
        d.table(["หุ้น", "กลุ่ม", "ปี", "รายได้ รพ.", "CAGR (ฐานหลังโควิด)", "GPM", "NPM", "ROE", "D/E", "เงินสดสุทธิ", "สัดส่วน SSO", "สัดส่วนต่างชาติ",
                 "P/E TTM", "PEG"], rows, align=["l", "l", "l"] + ["r"] * 11)
        d.p("_ตัวเลขคู่แข่งคำนวณจากงบการเงินของแต่ละบริษัทในโฟลเดอร์ Thstock (ไฟล์ `<T>_financials.json`) ด้วยนิยามเดียวกัน — คู่แข่งที่ยังไม่มีไฟล์ไม่แสดง_")
    else:
        d.p("ยังไม่มีงบคู่แข่งในโฟลเดอร์ Thstock (ต้องมี `report/<T>_financials.json`) — รัน `run_finance_sheet.py <peer>` ก่อนเพื่อเปรียบเทียบด้วยตัวเลขจริง")
    d.b.append(("nlist", narrative_items(nar.get("peers_notes"))))

def _sec_capital(d, p, nar, L, fys, cols, sc):
    # 6 ------------------------------------------------------------------
    d.h(2, "🎯 12. การจัดสรรเงินทุนและเป้าหมายผู้บริหารเทียบผลจริง")
    rows = [[LAB[k]] + [fmt(k, L[x].get(k)) for x in fys] for k in ("cfo", "capex", "capex_da", "fcf", "dps", "payout", "net_cash", "roic")]
    d.table(["การจัดสรรเงินทุน"] + [S.be(x) for x in fys], rows)
    d.b.append(("nlist", narrative_items(nar.get("management"))))
    if nar.get("guidance"):
        rows = []
        for g in nar["guidance"]:
            rows.append([g.get("guidance", ""), g.get("when", ""), g.get("actual", ""), g.get("status", ""), g.get("src", "–")])
        d.table(["เป้าหมาย/คำแถลงผู้บริหาร", "เมื่อ", "ผลจริง (จากงบ)", "สถานะ", "แหล่งที่มา"], rows, align=["l", "l", "l", "l", "l"])
    else:
        d.p("_ยังไม่มีตารางเป้าหมายเทียบผลจริง (ต้องอ่าน MD&A/Oppday) — ไฟล์ oppday_guidance_tracker.md เดิมของ AGY ไม่ใช้เป็นแหล่งข้อมูลเพราะเป็นข้อความถอดเสียงที่ยังไม่สรุป_")

def _sec_macro(d, p, nar, L, fys, cols, sc):
    # 7, 8 ---------------------------------------------------------------
    d.h(2, "🌍 8. ปัจจัยมหภาค: ปัจจัยหนุนและแรงต้าน")
    d.p("**ลมหนุน (Tailwinds)**")
    d.b.append(("nlist", narrative_items(nar.get("tailwinds")) or [("txt", "_ต้องอ่านเอกสาร — ไม่มีในโหมดอัตโนมัติ_", None)]))
    d.p("**ลมต้าน (Headwinds)**")
    d.b.append(("nlist", narrative_items(nar.get("headwinds")) or [("txt", "_ต้องอ่านเอกสาร — ไม่มีในโหมดอัตโนมัติ_", None)]))

def _sec_roadmap(d, p, nar, L, fys, cols, sc):
    d.h(2, "🏗️ 7. Roadmap และ S-curve ใหม่")
    DX.render_project(d, p)
    d.b.append(("nlist", narrative_items(nar.get("roadmap")) or [("txt", "_ต้องอ่านเอกสาร — ไม่มีในโหมดอัตโนมัติ_", None)]))

def _sec_score(d, p, nar, L, fys, cols, sc):
    # 9 ------------------------------------------------------------------
    d.h(2, "🏆 14. Scorecard และข้อสรุป")
    rows = [[c2["name"], str(c2["score"]), c2["why"]] for c2 in sc["components"]]
    rows.append(["**คะแนนคุณภาพทางการเงินเฉลี่ย**", "**%s**" % sc["score"], ""])
    d.table(["องค์ประกอบ (กฎโปร่งใส)", "คะแนน /10", "ข้อมูล"], rows, align=["l", "r", "l"])
    snar = nar.get("scorecard") or {}
    extra = []
    if snar.get("posture"):
        extra.append("**Strategic posture:** %s" % item_text(snar["posture"])[0])
    if snar.get("moat_rating") is not None:
        extra.append("**Moat rating (ดุลยพินิจ):** %s / 10 — %s" % (snar["moat_rating"], item_text(snar.get("moat_why", ""))[0]))
    if snar.get("capital_allocation_view"):
        extra.append("**Capital allocation:** %s" % item_text(snar["capital_allocation_view"])[0])
    d.ul(extra)
    d.b.append(("nlist", narrative_items(nar.get("verdict"))))

def _sec_pop(d, p, nar, L, fys, cols, sc):
    # 14.1 K. Pop checklist: auto items computed, document items from the narrative, owner items never answered by the skill
    d.h(3, "14.1 เช็กลิสต์ของ K. Pop (เรียงตามลำดับที่เขาใช้ ตกข้อต้นๆ ไม่ต้องไปข้อหลัง)")
    groups = DPOP.evaluate(p, nar)
    rows, n = [], {"auto": 0, "doc": 0, "owner": 0, "open": 0}
    for g, items in groups:
        for r in items:
            n[r["kind"]] += 1
            n["open"] += r["status"] == "open"
            ev = r["text"] + (" [%s]" % r["src"] if r["src"] else "")
            rows.append([g, r["icon"], r["q"], ev])
    d.table(["กลุ่ม", "", "คำถาม", "หลักฐาน / คำตอบ"], rows, align=["l", "l", "l", "l"])
    d.p("_✅ ผ่าน ❌ ไม่ผ่าน ℹ️ ข้อมูลประกอบ (สคริปต์คำนวณ) | ❓ ไม่แน่ใจ ⬜ ยังไม่ได้ประเมินจากเอกสาร (ดู `pop_checklist` ใน narrative) | "
        "👤 เป็นการตัดสินใจของเจ้าของพอร์ต: สคริปต์แสดงตัวเลขข้างคำถามแต่ไม่ตอบแทน เพราะไม่ใช่คำแนะนำการลงทุน. "
        "ข้อ %d ข้อคำนวณจากข้อมูล, %d ข้อต้องอ่านเอกสาร (ยังเปิดอยู่ %d), %d ข้อเป็นของเจ้าของพอร์ต_" % (n["auto"], n["doc"], n["open"], n["owner"]))


def _sec_verify(d, p, nar, L, fys, cols, sc, problems=()):
    # 10 -----------------------------------------------------------------
    d.h(2, "⚠️ 15. การตรวจสอบ: red flags, แหล่งที่มา และรายการนอกเอกสารทางการ")
    expl = nar.get("explanations") or {}
    fl = []
    for f in p["flags"]:
        e = expl.get(f["id"])
        if e:
            t, src, ext = item_text(e)
            partial = isinstance(e, dict) and e.get("status") == "partial"
            fl.append("%s %s — %s%s" % ("⚠️ อธิบายได้บางส่วน:" if partial or not src else "✅", f["text"], t, " [%s]" % src if src else ""))
        else:
            fl.append("🚩 **Red Flag (Unexplained):** %s" % f["text"])
    if fl:
        d.p("**การเปลี่ยนแปลงปีล่าสุดที่เกิน ±15% หรือโครงสร้างต้นทุนเปลี่ยน ≥1 pt (ต้องมีคำอธิบายจากเอกสาร):**")
        d.ul(fl)
    if problems:
        d.callout("warning", "ประเด็นจากการตรวจบทวิเคราะห์ (%d)" % len(problems), problems[:25])
    ext_items = list(nar.get("external") or [])
    if ext_items:
        rows = [[str(i + 1), '<span style="color:%s;font-weight:bold">%s</span>' % (RED, e.get("item", "")), e.get("value", ""), e.get("source", ""), e.get("status", "")]
                for i, e in enumerate(ext_items)]
        d.table(["#", "รายการ/สมมติฐาน", "ค่า", "แหล่งที่มา", "สถานะ"], rows, align=["l", "l", "r", "l", "l"])
    else:
        d.p("ไม่มีตัวเลขหรือสมมติฐานจากนอกเอกสารทางการในรายงานนี้")
    cfs = [c for c in nar.get("conflicts") or [] if isinstance(c, dict)]
    if cfs:
        VL = {"conflict": "⚠️ ขัดแย้ง", "definition": "ต่างนิยาม", "outdated": "ข้อมูลเก่ากว่า", "consistent": "✅ สอดคล้อง", "unverifiable": "ตรวจสอบไม่ได้"}
        d.h(3, "ข้อมูลจากนักวิเคราะห์อ้างอิงและแหล่งที่ 2–3 เทียบกับเอกสารที่ยื่นต่อ ตลท. (แหล่งที่ 1)")
        d.p("_เมื่อขัดกัน รายงานยึดเอกสารที่บริษัทยื่นต่อ ตลท. และแสดงความต่างไว้ที่นี่ ไม่เฉลี่ยตัวเลข_")
        tier = lambda c: ("แหล่งที่ 3 (เว็บบอร์ด)" if "third_source" in str(c.get("second_src", "")) else
                          "%s (นักวิเคราะห์อ้างอิง)" % S.row_analyst(c, p.get("analyst_notes"))
                          if "analyst_notes" in str(c.get("second_src", "")) else "แหล่งที่ 2")
        rows = [[VL.get(c.get("verdict", "conflict"), c.get("verdict", "")), "%s<br><small>%s</small>" % (c.get("topic", ""), tier(c)),
                 '<span style="color:%s">%s</span><br><small>%s</small>' % (RED, c.get("second", ""), c.get("second_src", "")),
                 "%s<br><small>%s</small>" % (c.get("primary", ""), c.get("primary_src", "")), c.get("note", "")] for c in cfs]
        d.table(["ผล", "ประเด็น", "แหล่งภายนอกกล่าวว่า", "เอกสาร ตลท. (แหล่งที่ 1)", "ข้อสังเกต"], rows, align=["l", "l", "l", "l", "l"])
    if p["one_offs"]:
        d.p("**รายการพิเศษที่ปรับกำไรปกติ:**")
        d.ul(["%s: %+.2f ลบ. — %s" % (S.be(o["period"]), o["amount_after_tax"], o.get("label", "")) for o in p["one_offs"]])
    src = p["sources"].get("fact_src") or {}
    rows = [[k, src["%s|%s" % (k, fys[-1])]] for k in ("rev_hosp", "cogs", "np_owners", "cf_da", "cash", "st_invest", "cfo", "capex_ppe", "dps")
            if "%s|%s" % (k, fys[-1]) in src]
    if rows:
        d.h(3, "ภาคผนวก: บรรทัดอ้างอิงของตัวเลขหลัก %s" % S.be(fys[-1]))
        d.table(["รายการ", "แหล่งที่มา"], rows, align=["l", "l"])

def write(p, nar, outdir, problems=(), version=None):
    d = build_doc(p, nar, list(problems))
    last = p["ytd"] or p["fys"][-1]
    be_year = int(last[-4:]) + 543
    stem = "%s_DeepDive_Report_%d" % (p["ticker"], be_year)
    v = int(version) if version else next_version(outdir, stem)
    md_p = os.path.join(outdir, "%s-v%d.md" % (stem, v))
    html_p = os.path.join(outdir, "%s-v%d.html" % (stem, v))
    open(md_p, "w", encoding="utf-8").write(to_md(d))
    open(html_p, "w", encoding="utf-8").write(to_html(d, "%s Deep-Dive %d" % (p["ticker"], be_year)))
    return md_p, html_p
