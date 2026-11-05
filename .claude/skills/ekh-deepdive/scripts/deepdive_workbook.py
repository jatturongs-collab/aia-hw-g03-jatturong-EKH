#!/usr/bin/env python3
"""
deepdive_workbook.py - one file for the deep dive: the finance model with the analysis on top.

    python3 deepdive_workbook.py --stock-dir "<Thstock>/VIH" --ticker VIH

Takes the newest report/<T>_finance_model_v<N>.xlsx (build or refresh it first with thai-hospital-finance-sheet),
keeps every sheet and formula, and adds
    Deepdive (บทวิเคราะห์)     first sheet: headline, the make-or-break point, summary, what the price expects,
                               verdict, open questions, and a table of contents linked to every sheet
    รายโรงพยาบาล (By hospital) revenue, net profit, capitation share and beds by hospital (report/<T>_hospitals.json)
    ปฏิบัติการ (Operations)     volume, utilisation, revenue per bill from Oppday slides (report/<T>_ops_metrics.json)
    โครงการใหม่ (Project)       the project file: size, funding, IFA projection, timeline (report/<T>_project.json)
and writes report/<T>_Deepdive_<BE year>_v<N>.xlsx. The text comes from report/<T>_deepdive_narrative.json, so run
`deepdive.py check` first: this script copies the narrative, it does not check it.
Sums, shares, margins and growth on the added sheets are live formulas; blue = transcribed input with its source.
"""
import argparse
import datetime as dt
import glob
import json
import os
import re

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter as L

NAVY, BAND, SUB, BLUE, RED = "2F5496", "D9E1F2", "E2EFDA", "0000FF", "8B0000"
FONT = "Segoe UI"
THIN = Side(style="thin", color="BFBFBF")
H_ORDER = ["omnoi", "nongkhaem", "samutsakhon", "yaekfaichai"]


def load(sdir, name):
    p = os.path.join(sdir, "report", name)
    return json.load(open(p, encoding="utf-8")) if os.path.isfile(p) else None


def txt(item):
    """narrative item -> (text, source, external)"""
    if isinstance(item, dict):
        return item.get("text", ""), item.get("src", ""), bool(item.get("external"))
    return str(item), "", False


class Sheet:
    def __init__(self, wb, title, widths, index=None, tab=NAVY):
        self.ws = wb.create_sheet(title[:31], index)
        self.ws.sheet_view.showGridLines = False
        self.ws.sheet_properties.tabColor = tab
        for i, w in enumerate(widths, 1):
            self.ws.column_dimensions[L(i)].width = w
        self.r, self.ncol = 1, len(widths)

    def cell(self, c, v, bold=False, size=10, color="000000", fill=None, fmt=None, wrap=False, align=None, italic=False, border=False):
        x = self.ws.cell(self.r, c, v)
        x.font = Font(name=FONT, size=size, bold=bold, color=color, italic=italic)
        if fill:
            x.fill = PatternFill("solid", fgColor=fill)
        if fmt:
            x.number_format = fmt
        x.alignment = Alignment(wrap_text=wrap, vertical="top", horizontal=align)
        if border:
            x.border = Border(top=THIN, bottom=THIN, left=THIN, right=THIN)
        return x

    def title(self, t, sub=None):
        self.cell(1, t, bold=True, size=14)
        self.r += 1
        if sub:
            self.cell(1, sub, size=9, italic=True, color="595959")
            self.r += 1
        self.r += 1

    def band(self, t):
        for c in range(1, self.ncol + 1):
            self.cell(c, t if c == 1 else None, bold=True, fill=BAND)
        self.r += 1

    def header(self, cols):
        for c, v in enumerate(cols, 1):
            self.cell(c, v, bold=True, color="FFFFFF", fill=NAVY, align="center" if c > 1 else None, wrap=True, border=True)
        self.r += 1

    def row(self, vals, fmt="#,##0.00", bold=False, fill=None, inputs=False, wrap=False):
        for c, v in enumerate(vals, 1):
            num = isinstance(v, (int, float)) or (isinstance(v, str) and v.startswith("="))
            self.cell(c, v, bold=bold or c == 1 and bold, fill=fill, fmt=fmt if num and c > 1 else None, wrap=wrap or c == 1,
                      color=BLUE if inputs and isinstance(v, (int, float)) and c > 1 else "000000", align="right" if num and c > 1 else None, border=True)
        self.r += 1

    def para(self, t, src="", external=False, bullet="• ", height=None):
        """A wrapped paragraph merged across the sheet; the source goes underneath in grey."""
        s = bullet + t + (("  [%s]" % src) if src else "")
        self.ws.merge_cells(start_row=self.r, start_column=1, end_row=self.r, end_column=self.ncol)
        self.cell(1, s, wrap=True, color=RED if external else "000000")
        width = sum(self.ws.column_dimensions[L(i)].width for i in range(1, self.ncol + 1))
        self.ws.row_dimensions[self.r].height = height or max(15, 15 * (1 + int(len(s) * 1.25 / width)))
        self.r += 1

    def gap(self, n=1):
        self.r += n


def by_hospital(wb, hosp):
    names = hosp.get("hospitals") or {}
    keys = [k for k in H_ORDER if k in names] or list(names)
    ys = sorted(hosp.get("years") or {})
    if not ys:                                  # only the `sso` block / beds: no revenue-by-hospital tables to build
        s = Sheet(wb, "รายโรงพยาบาล (By hospital)", [46] + [15] * 8 + [60])
        s.title("ข้อมูลรายโรงพยาบาล", "เอกสารบริษัทไม่เปิดเผยรายได้และกำไรรายโรงพยาบาล — แสดงเฉพาะข้อมูลประกันสังคมและเตียงที่มีที่มา")
        sso = hosp.get("sso") or {}
        if sso.get("years"):
            sso_section(s, sso, names)
        sso_tables(s, sso)
        if hosp.get("note"):
            s.para(hosp["note"], bullet="")
        s.ws.freeze_panes = "B5"
        return
    s = Sheet(wb, "รายโรงพยาบาล (By hospital)", [46] + [13] * len(ys) + [60])
    s.title("รายได้และกำไรรายโรงพยาบาล", "ล้านบาท | ตัวเลขสีน้ำเงิน = คัดจากเอกสารตามที่มาในคอลัมน์ขวา | ผลรวม สัดส่วน อัตรากำไร และการเติบโต = สูตร")
    col = lambda i: L(i + 2)
    # revenue
    s.band("1) รายได้จากการให้บริการ รายโรงพยาบาล")
    s.header(["โรงพยาบาล"] + ["ปี %s" % y for y in ys] + ["ที่มา"])
    rev_rows = {}
    for k in keys:
        rev_rows[k] = s.r
        s.row([names[k]] + [hosp["years"][y]["revenue"].get(k) for y in ys] + [hosp["years"][ys[-1]].get("revenue_calc", "") if k != "omnoi" else "งบเฉพาะกิจการ / รายงานประจำปี"], inputs=True)
    tot = s.r
    s.row(["รวมก่อนตัดรายการระหว่างกัน"] + ["=SUM(%s%d:%s%d)" % (col(i), rev_rows[keys[0]], col(i), rev_rows[keys[-1]]) for i in range(len(ys))], bold=True, fill=SUB)
    grp = s.r
    s.row(["รายได้กลุ่มตามงบรวม"] + [hosp["years"][y].get("revenue_group") for y in ys] + ["งบการเงินรวม"], inputs=True)
    s.row(["รายการระหว่างกัน (รวม − งบรวม)"] + ["=%s%d-%s%d" % (col(i), tot, col(i), grp) for i in range(len(ys))])
    s.gap()
    s.header(["สัดส่วนรายได้"] + ["ปี %s" % y for y in ys])
    for k in keys:
        s.row([names[k]] + ["=IFERROR(%s%d/%s%d,\"\")" % (col(i), rev_rows[k], col(i), tot) for i in range(len(ys))], fmt="0.0%")
    s.gap()
    s.header(["รายได้โต YoY"] + ["ปี %s" % y for y in ys])
    for k in keys:
        s.row([names[k]] + [""] + ["=IFERROR(%s%d/%s%d-1,\"\")" % (col(i), rev_rows[k], col(i - 1), rev_rows[k]) for i in range(1, len(ys))], fmt="0.0%")
    s.gap()
    # net profit
    s.band("2) กำไรสุทธิรายโรงพยาบาล ไม่รวมเงินปันผลรับจากบริษัทย่อย")
    s.header(["โรงพยาบาล"] + ["ปี %s" % y for y in ys] + ["ที่มา / หมายเหตุ"])
    np_rows = {}
    for k in keys:
        np_rows[k] = s.r
        s.row([names[k]] + [(hosp["years"][y].get("np_ex_dividend") or {}).get(k) for y in ys] +
              ["อ้อมน้อย ปี 2563–2565 = กำไรงบเฉพาะกิจการ − เงินปันผลรับ (คำนวณ); ปี 2566–2568 ตามที่บริษัทรายงานต่อที่ประชุมผู้ถือหุ้น" if k == "omnoi" else ""], inputs=True)
    ntot = s.r
    s.row(["รวมสี่โรงพยาบาล"] + ["=IF(COUNT(%s%d:%s%d)=0,\"\",SUM(%s%d:%s%d))" % (col(i), np_rows[keys[0]], col(i), np_rows[keys[-1]], col(i), np_rows[keys[0]], col(i), np_rows[keys[-1]])
                                    for i in range(len(ys))], bold=True, fill=SUB)
    s.row(["กำไรสุทธิกลุ่มตามงบรวม"] + [hosp["years"][y].get("np_group") for y in ys] + ["งบการเงินรวม (ส่วนต่าง = โรงเรียนอาชีวศึกษา บริษัทย่อยอื่น และการปัดเศษ)"], inputs=True)
    s.gap()
    s.header(["อัตรากำไรสุทธิ"] + ["ปี %s" % y for y in ys])
    for k in keys:
        s.row([names[k]] + ["=IFERROR(%s%d/%s%d,\"\")" % (col(i), np_rows[k], col(i), rev_rows[k]) for i in range(len(ys))], fmt="0.0%")
    s.gap()
    s.header(["สัดส่วนกำไร"] + ["ปี %s" % y for y in ys])
    for k in keys:
        s.row([names[k]] + ["=IFERROR(%s%d/%s%d,\"\")" % (col(i), np_rows[k], col(i), ntot) for i in range(len(ys))], fmt="0.0%")
    s.gap()
    # capitation
    cy = [y for y in ys if hosp["years"][y].get("capitation")]
    if cy:
        s.band("3) รายได้ Capitation (ประกันสังคม) รายโรงพยาบาล")
        s.header(["โรงพยาบาล"] + ["ปี %s" % y for y in ys])
        cap_rows = {}
        for k in keys:
            cap_rows[k] = s.r
            s.row([names[k]] + [(hosp["years"][y].get("capitation") or {}).get(k) for y in ys], inputs=True)
        s.gap()
        s.header(["สัดส่วน Capitation ต่อรายได้ของโรงพยาบาล"] + ["ปี %s" % y for y in ys])
        for k in keys:
            s.row([names[k]] + ["=IF(%s%d=\"\",\"\",IFERROR(%s%d/%s%d,\"\"))" % (col(i), cap_rows[k], col(i), cap_rows[k], col(i), rev_rows[k]) for i in range(len(ys))], fmt="0.0%")
        s.gap()
    beds = hosp.get("beds")
    if beds:
        by = sorted(beds)
        s.band("4) เตียงจดทะเบียน / เตียงให้บริการจริง")
        s.header(["โรงพยาบาล"] + [("ปี %s" % y) if y.isdigit() else y for y in by])
        for k in keys + ["total"]:
            s.row(["รวม" if k == "total" else names[k]] + ["%s / %s" % ((beds[y].get("registered") or {}).get(k, "–"), (beds[y].get("operating") or {}).get(k, "–")) for y in by],
                  bold=k == "total", fill=SUB if k == "total" else None)
        s.gap()
    sso = hosp.get("sso") or {}
    if sso.get("years"):
        sso_section(s, sso, names)
    sso_tables(s, sso)
    s.band("ที่มา")
    for y in ys:
        s.para("ปี %s: %s" % (y, hosp["years"][y].get("src", "")), bullet="")
    for y in sorted(beds or {}):
        s.para("เตียง %s: %s" % (y, beds[y]["src"]), bullet="")
    if hosp.get("note"):
        s.para(hosp["note"], bullet="")
    s.ws.freeze_panes = "B5"


def sso_tables(s, sso):
    """Free tables of the `sso` block (group series from Oppday, official provincial statistics): values as given."""
    for t in sso.get("tables") or []:
        if not t.get("rows"):
            continue
        tier2 = str(t.get("tier", 1)) != "1"
        s.band(t.get("title", "ประกันสังคม") + (" — แหล่งที่ 2 (ไม่ใช่เอกสารบริษัท)" if tier2 else ""))
        s.header(list(t.get("cols") or []))
        bold = set(t.get("bold") or [])
        for i, r in enumerate(t["rows"]):
            allint = all(isinstance(v, int) or v in (None, "") for v in r[1:])
            s.row(list(r), fmt="#,##0" if allint else "#,##0.00", bold=i in bold, fill=SUB if i in bold else None, inputs=True)
        s.para("ที่มา: %s%s" % (t.get("src", ""), (" | " + t["note"]) if t.get("note") else ""), bullet="")
        s.gap()
    if not sso.get("years"):
        for pt in sso.get("points") or []:
            s.para("%s: %s" % (pt.get("when", ""), pt.get("text", "")), src=pt.get("src", ""))
        if sso.get("note"):
            s.para(sso["note"], bullet="")


def sso_section(s, sso, names):
    """Insured persons against the SSO quota: what is used, what is left (formulas)."""
    sy = sorted(sso["years"])
    hk = sso.get("hospitals") or []
    col = lambda i: L(i + 2)
    Y = sso["years"]
    s.band("5) ผู้ประกันตนในระบบประกันสังคม เทียบโควตา: รับอยู่เท่าไร รับได้สูงสุดเท่าไร เหลือเท่าไร")
    s.header(["ราย (คน)"] + ["ปี %s" % y for y in sy] + ["ที่มา / หมายเหตุ"])
    q_rows, i_rows = {}, {}
    for k in hk:
        q_rows[k] = s.r
        s.row(["โควตา (รับได้สูงสุด) — %s" % names[k]] + [(Y[y].get("quota") or {}).get(k) for y in sy] +
              ["บริษัทแจ้งโควตารายโรงพยาบาลเฉพาะบางปี"], fmt="#,##0", inputs=True)
    qt = s.r
    s.row(["โควตารวม"] + [Y[y].get("quota_total") for y in sy] + ["ตามที่บริษัทแจ้งต่อที่ประชุมผู้ถือหุ้น"], fmt="#,##0", inputs=True, bold=True)
    for k in hk:
        i_rows[k] = s.r
        s.row(["ผู้ประกันตน — %s" % names[k]] + [(Y[y].get("insured") or {}).get(k) for y in sy] +
              ["ไม่เปิดเผยรายโรงพยาบาลในปีที่เว้นว่าง"], fmt="#,##0", inputs=True)
    it = s.r
    vals = []
    for i, y in enumerate(sy):
        if Y[y].get("insured"):
            vals.append("=SUM(%s%d:%s%d)" % (col(i), i_rows[hk[0]], col(i), i_rows[hk[-1]]))
        elif Y[y].get("sso_revenue_mn") and Y[y].get("revenue_per_insured"):
            vals.append("=ROUND(%s*1000000/%s,0)" % (Y[y]["sso_revenue_mn"], Y[y]["revenue_per_insured"]))
        else:
            vals.append(None)
    s.row(["ผู้ประกันตนรวม"] + vals + ["ปีที่ไม่มีตัวเลขรายโรงพยาบาล = [คำนวณ] รายได้ประกันสังคม ÷ รายได้ต่อราย"], fmt="#,##0", bold=True, fill=SUB)
    left = s.r
    s.row(["เหลือที่ยังรับได้ รวม (โควตา − ผู้ประกันตน)"] + ["=IF(OR(%s%d=\"\",%s%d=\"\"),\"\",%s%d-%s%d)" % (col(i), qt, col(i), it, col(i), qt, col(i), it) for i in range(len(sy))], fmt="#,##0", bold=True)
    s.row(["อัตราใช้โควตา รวม"] + ["=IF(OR(%s%d=\"\",%s%d=\"\"),\"\",%s%d/%s%d)" % (col(i), qt, col(i), it, col(i), it, col(i), qt) for i in range(len(sy))], fmt="0.0%")
    for k in hk:
        s.row(["เหลือที่ยังรับได้ — %s" % names[k]] + ["=IF(OR(%s%d=\"\",%s%d=\"\"),\"\",%s%d-%s%d)" % (col(i), q_rows[k], col(i), i_rows[k], col(i), q_rows[k], col(i), i_rows[k]) for i in range(len(sy))],
              fmt="#,##0")
    s.gap()
    s.header(["การเติบโตและรายได้ต่อราย"] + ["ปี %s" % y for y in sy] + ["ที่มา / หมายเหตุ"])
    for k in hk:
        s.row(["ผู้ประกันตนโต YoY — %s" % names[k]] + [""] + ["=IF(OR(%s%d=\"\",%s%d=\"\"),\"\",%s%d/%s%d-1)" % (col(i), i_rows[k], col(i - 1), i_rows[k], col(i), i_rows[k], col(i - 1), i_rows[k]) for i in range(1, len(sy))], fmt="0.0%")
    s.row(["ผู้ประกันตนโต YoY — รวม"] + [""] + ["=IF(OR(%s%d=\"\",%s%d=\"\"),\"\",%s%d/%s%d-1)" % (col(i), it, col(i - 1), it, col(i), it, col(i - 1), it) for i in range(1, len(sy))], fmt="0.0%")
    s.row(["โควตาโต YoY — รวม"] + [""] + ["=IF(OR(%s%d=\"\",%s%d=\"\"),\"\",%s%d/%s%d-1)" % (col(i), qt, col(i - 1), qt, col(i), qt, col(i - 1), qt) for i in range(1, len(sy))], fmt="0.0%")
    rp = s.r
    s.row(["รายได้ประกันสังคมต่อผู้ประกันตน (บาท/ปี)"] + [Y[y].get("revenue_per_insured") for y in sy] + ["ตามที่บริษัทแจ้ง"], inputs=True)
    s.row(["รายได้ที่เพิ่มได้ถ้าเติมเต็มโควตา (ล้านบาท/ปี) [คำนวณ]"] + ["=IF(OR(%s%d=\"\",%s%d=\"\"),\"\",%s%d*%s%d/1000000)" % (col(i), left, col(i), rp, col(i), left, col(i), rp) for i in range(len(sy))] +
          ["เพดานทางทฤษฎี = เหลือที่ยังรับได้ × รายได้ต่อราย; ไม่ใช่ประมาณการ"])
    s.gap()
    s.para("อ่านอย่างไร: โควตาคือเพดานที่ สปส. อนุญาต แต่ผู้ประกันตนเป็นผู้เลือกโรงพยาบาลเอง ถ้าอัตราใช้โควตาต่ำกว่า 100% และลดลง คอขวดไม่ได้อยู่ที่โควตา ให้ดูต่อว่า (1) โรงพยาบาลใดยังโต (2) บริษัทตั้งใจเร่งหรือไม่ (3) ผู้ป่วยนอกเต็มหรือยัง — แผ่น ปฏิบัติการ", bullet="")
    for pt in sso.get("points") or []:
        s.para("%s: %s" % (pt.get("when", ""), pt.get("text", "")), src=pt.get("src", ""))
    for y in sy:
        s.para("ประกันสังคม ปี %s: %s%s" % (y, Y[y].get("src", ""), (" | " + Y[y]["insured_note"]) if Y[y].get("insured_note") else ""), bullet="")
    if sso.get("note"):
        s.para(sso["note"], bullet="")
    s.gap()


def be(per):
    if per.startswith("FY"):
        return "ปี %d" % (int(per[2:]) + 543)
    if per[1] == "M":
        return "%s/%d" % (per[:2], int(per[2:]) + 543)
    return "Q%s/%d" % (per[-1], int(per[:4]) + 543)


def operations(wb, ops):
    m, dv = ops["metrics"], ops.get("derived") or {}
    allp = set()
    for ser in m.values():
        allp |= set(ser)
    fy = sorted(p for p in allp if p.startswith("FY"))
    qs = sorted(p for p in allp if re.fullmatch(r"\d{4}Q[1-4]", p))[-10:]
    rows = [("opd_visits", "ผู้ป่วยนอก (ครั้ง)", "#,##0"), ("opd_utilization_pct", "อัตราการใช้บริการ OPD (%)", "0.00"),
            ("implied_opd_capacity_per_day", "กำลังรับ OPD ต่อวันที่ใช้คำนวณอัตรา [คำนวณ]", "#,##0"),
            ("per_bill_opd_baht", "รายได้ต่อใบเสร็จ OPD (บาท)", "#,##0"), ("ipd_days", "วันนอนผู้ป่วยใน (วัน)", "#,##0"),
            ("occupancy_pct", "อัตราครองเตียง (%)", "0.00"), ("implied_beds", "ฐานเตียงที่ใช้คำนวณอัตรา [คำนวณ]", "#,##0"),
            ("per_bill_ipd_baht", "รายได้ต่อใบเสร็จ IPD (บาท)", "#,##0")]
    s = Sheet(wb, "ปฏิบัติการ (Operations)", [46] + [12] * max(len(fy), len(qs)))
    s.title("ปริมาณ อัตราการใช้ และรายได้ต่อใบเสร็จ (จากสไลด์ Opportunity Day)",
            "อ่านจากตำแหน่งบนสไลด์ด้วยสคริปต์ oppday_ops.py | แถว [คำนวณ] = ปริมาณ ÷ อัตรา ÷ จำนวนวัน คือฐานที่บริษัทใช้ ไม่ใช่ตัวเลขที่บริษัทเปิดเผย")
    for label, pers in (("รายปี", fy), ("รายไตรมาส (10 ไตรมาสล่าสุด)", qs)):
        s.band(label)
        s.header(["ตัวชี้วัด"] + [be(p) for p in pers])
        for key, lab, f in rows:
            ser = m.get(key) or dv.get(key) or {}
            if any(p in ser for p in pers):
                s.row([lab] + [ser[p]["v"] if p in ser else None for p in pers], fmt=f, inputs=key in m)
        s.gap()
    for c in ops.get("base_checks") or []:
        s.para("ตรวจฐานของอัตรา %s %s: %s" % (c["metric"], be(c["period"]), c["action"]), bullet="")
    srcs = sorted({v["src"].split(":")[0] for ser in m.values() for v in ser.values() if v.get("src")})
    s.para("ที่มา: " + ", ".join(srcs), bullet="")
    s.ws.freeze_panes = "B5"


def project(wb, pj):
    s = Sheet(wb, "โครงการใหม่ (Project)", [34, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16], tab="C00000")
    a, r, f, ph, ifa = pj.get("approved") or {}, pj.get("revised") or {}, pj.get("funding") or {}, pj.get("phasing") or {}, pj.get("ifa") or {}
    s.title(pj.get("name", "โครงการลงทุน"), "ข้อเท็จจริงจากรายงานการประชุมผู้ถือหุ้น | ประมาณการ IFA = กรณีฐานของผู้เสนอโครงการ ไม่ใช่ผลประกอบการ")
    s.band("ข้อมูลโครงการ")
    facts = [("ที่ตั้ง", "%s (%s)" % (a.get("location", ""), a.get("land_area", "")), a.get("src")),
             ("มูลค่าโครงการที่อนุมัติ (ล้านบาท)", a.get("value_max"), a.get("src")), ("  ที่ดิน", a.get("land"), a.get("src")),
             ("  ก่อสร้าง (ไม่เกิน)", a.get("construction_max"), a.get("src")), ("มูลค่าฉบับปรับปรุง (ล้านบาท)", r.get("value_max"), r.get("src")),
             ("ผู้ดำเนินโครงการ", r.get("vehicle"), r.get("src")), ("จำนวนเตียง", a.get("beds"), a.get("src")),
             ("ตลาดเป้าหมาย", a.get("positioning"), a.get("src")), ("ศูนย์ที่เน้น", a.get("focus"), a.get("src")),
             ("เพิ่มทุน RO ไม่เกิน (ล้านบาท)", f.get("ro_max"), f.get("src")), ("เงินกู้ไม่ต่ำกว่า (ล้านบาท)", f.get("loan_min_with_ro"), f.get("src")),
             ("เงินกู้หากไม่มี RO (ล้านบาท)", f.get("loan_min_without_ro"), f.get("src")), ("EPS dilution (%)", f.get("eps_dilution_pct"), f.get("src")),
             ("จำนวนเฟส / เตียงเฟสแรก / ปีจนเปิดครบ", "%s / %s / %s" % (ph.get("phases"), ph.get("first_phase_beds"), ph.get("years_to_full")), ph.get("src")),
             ("โรงพยาบาลเอกชนในรัศมี 20 กม.", ", ".join(pj.get("competitors_20km") or []), a.get("src")), ("ราคาและการบริหาร", pj.get("pricing"), "")]
    for lab, v, src in facts:
        if v in (None, ""):
            continue
        s.cell(1, lab, bold=True, border=True, wrap=True)
        if isinstance(v, (int, float)):
            s.cell(2, v, color=BLUE, fmt="#,##0.00", border=True, align="right")
            s.ws.merge_cells(start_row=s.r, start_column=3, end_row=s.r, end_column=9)
            s.cell(3, src or "", size=9, color="595959", wrap=True)
        else:
            s.ws.merge_cells(start_row=s.r, start_column=2, end_row=s.r, end_column=9)
            s.cell(2, "%s%s" % (v, ("  [%s]" % src) if src else ""), wrap=True)
            s.ws.row_dimensions[s.r].height = max(15, 15 * (1 + len(str(v)) // 95))
        s.r += 1
    s.gap()
    if ifa:
        s.band("ประมาณการของที่ปรึกษาทางการเงินอิสระ (%s)" % ifa.get("adviser", ""))
        for lab, v, fmt in (("NPV (ล้านบาท)", ifa.get("npv"), "#,##0.00"), ("IRR (%)", ifa.get("irr_pct"), "0.00"), ("คืนทุน (ปี นับจากเปิดให้บริการ)", ifa.get("payback_years_from_opening"), "0")):
            s.row([lab, v], fmt=fmt, inputs=True)
        sens = ifa.get("sensitivity") or {}
        for lab, k, fmt in (("NPV ตามจำนวนผู้ป่วย: ต่ำ / สูง", "npv_by_patients", "#,##0.00"), ("NPV ตามต้นทุน: ต่ำ / สูง", "npv_by_cost", "#,##0.00"),
                            ("IRR ตามจำนวนผู้ป่วย: ต่ำ / สูง (%)", "irr_by_patients_pct", "0.00"), ("IRR ตามต้นทุน: ต่ำ / สูง (%)", "irr_by_cost_pct", "0.00")):
            if sens.get(k):
                s.row([lab] + list(sens[k]), fmt=fmt, inputs=True)
        s.gap()
        fc = ifa.get("fcff") or {}
        if fc:
            ys = sorted(fc)
            s.header(["FCFF ของโครงการ (ล้านบาท)"] + ["ปี %s" % y for y in ys])
            fr = s.r
            s.row(["FCFF ตามประมาณการ IFA"] + [fc[y] for y in ys], inputs=True)
            s.row(["FCFF สะสม"] + ["=SUM($B%d:%s%d)" % (fr, L(i + 2), fr) for i in range(len(ys))], bold=True, fill=SUB)
            s.gap()
            s.para("ประมาณการนี้จัดทำเมื่อปี 2567 โดยสมมติว่าลงทุนหนักในปี 2568–2569 และ FCFF เป็นบวกตั้งแต่ปี 2571 — เมื่อโครงการเลื่อน ลำดับปีทั้งหมดเลื่อนตาม", bullet="")
        s.para("ที่มา: %s" % ifa.get("src", ""), bullet="")
        s.gap()
    if pj.get("timeline"):
        s.band("กำหนดการตามที่ผู้บริหารแจ้งในแต่ละครั้ง")
        for t in pj["timeline"]:
            s.para("%s — %s" % (t["said"], t["plan"]), src=t["src"], bullet="")
    for ms in pj.get("management_statements") or []:
        s.para("%s: %s" % (ms.get("who", ""), ms["text"]), src=ms.get("src", ""), bullet="")


def front(wb, nar, ticker, model_name, sheets):
    s = Sheet(wb, "Deepdive (บทวิเคราะห์)", [30, 22, 22, 22, 22, 30], index=0, tab="C00000")
    s.title("%s — Deep Dive" % ticker, "บทวิเคราะห์อยู่บนแบบจำลองการเงิน %s | จัดทำ %s | ตัวอักษรสีแดงเข้ม = ข้อมูลนอกเอกสารที่ยื่นต่อ ตลท. | ไม่มีราคาเป้าหมาย ไม่ใช่คำแนะนำการลงทุน" % (
        model_name, dt.date.today().isoformat()))
    if nar.get("headline"):
        s.ws.merge_cells(start_row=s.r, start_column=1, end_row=s.r, end_column=6)
        s.cell(1, nar["headline"], bold=True, size=12, wrap=True)
        s.ws.row_dimensions[s.r].height = 36
        s.r += 2

    def block(title, items):
        if not items:
            return
        s.band(title)
        for it in items:
            t, src, ext = txt(it)
            s.para(t, src, ext)
        s.gap()
    pv = nar.get("pivot") or {}
    if pv:
        s.band("จุดชี้ชะตา: %s" % txt(pv.get("title", ""))[0])
        for lab, key in (("ถ้าไม่สำเร็จ", "if_fails"), ("ถ้าสำเร็จ", "if_works"), ("สัญญาณที่จะบอกผล", "watch")):
            if pv.get(key):
                s.cell(1, lab, bold=True, fill=SUB)
                s.r += 1
                for it in pv[key]:
                    t, src, ext = txt(it)
                    s.para(t, src, ext)
        s.gap()
    block("สรุป", nar.get("summary"))
    popv = [it for it in nar.get("pop_view") or [] if isinstance(it, dict) and it.get("text")]
    if popv:
        PVL = {"confirmed": "ตรงกับเอกสารบริษัท", "differs": "ต่างจากเอกสารบริษัท", "not_in_filings": "ไม่มีในเอกสารบริษัท ยังตรวจไม่ได้",
               "opinion": "ความเห็น/การตีความ"}
        _who = lambda it: str(it.get("who") or "คุณ Pop").strip()
        _names = sorted({_who(it) for it in popv}, key=lambda x: (x != "คุณ Pop", x))
        _multi = _names != ["คุณ Pop"]
        s.band("มุมมองของ%s (นักวิเคราะห์อ้างอิง) — ตัวเลขยังตรวจกับเอกสารบริษัททุกข้อ" % (", ".join(_names)))
        s.header(["ประเด็นที่นักวิเคราะห์ชี้" if _multi else "ประเด็นที่คุณ Pop ชี้", "", "", "ผลการตรวจกับเอกสารบริษัท", "", "ที่มา"])
        for it in popv:
            r0 = s.r
            _t = ("[%s] %s" % (_who(it), it["text"])) if _multi else it["text"]
            s.row([_t, "", "", PVL.get(it.get("verdict"), it.get("verdict", "")), "", it.get("src", "")], wrap=True)
            s.ws.merge_cells(start_row=r0, start_column=1, end_row=r0, end_column=3)
            s.ws.merge_cells(start_row=r0, start_column=4, end_row=r0, end_column=5)
            s.ws.row_dimensions[r0].height = 62
        s.gap()
    block("ราคา = มูลค่า + เรื่องเล่า: ราคานี้คาดหวังอะไร", nar.get("expectation"))
    lc = nar.get("lifecycle") or {}
    block("ช่วงของธุรกิจ", ([lc["phase"]] if lc.get("phase") else []) + list(lc.get("reasoning") or []))
    block("ทีมแพทย์และการหาแพทย์", nar.get("team"))
    block("ลมต้าน", nar.get("headwinds"))
    block("ลมหนุน", nar.get("tailwinds"))
    block("ข้อสรุป", nar.get("verdict"))
    if nar.get("guidance"):
        s.band("เป้าหมายและคำแถลงของผู้บริหาร เทียบผลจริง")
        s.header(["เป้าหมาย", "แจ้งเมื่อ", "ผลจริง", "สถานะ", "", "แหล่งที่มา"])
        for g in nar["guidance"]:
            s.row([g.get("guidance", ""), g.get("when", ""), g.get("actual", ""), g.get("status", ""), "", g.get("src", "")], wrap=True)
            s.ws.row_dimensions[s.r - 1].height = 45
        s.gap()
    if nar.get("pending"):
        s.band("คำถามที่ยังตอบไม่ได้ (ต้องติดตาม) — ไม่เดาเติม คงไว้จนกว่าจะมีเอกสารมาปิด")
        s.header(["คำถาม", "ทำไมสำคัญ", "", "หาคำตอบได้จาก", "", "ตั้งเมื่อ"])
        for q in nar["pending"]:
            r0 = s.r
            s.row([q.get("question", ""), q.get("why", ""), "", q.get("where", ""), "", q.get("raised", "")], wrap=True)
            s.ws.merge_cells(start_row=r0, start_column=2, end_row=r0, end_column=3)
            s.ws.merge_cells(start_row=r0, start_column=4, end_row=r0, end_column=5)
            s.ws.row_dimensions[r0].height = 62
        s.gap()
    s.band("สารบัญ (คลิกเพื่อไปยังชีต)")
    for name, what in sheets:
        c = s.cell(1, name, color="0563C1")
        c.hyperlink = "#'%s'!A1" % name
        s.ws.merge_cells(start_row=s.r, start_column=2, end_row=s.r, end_column=6)
        s.cell(2, what, size=9, color="595959")
        s.r += 1
    s.ws.freeze_panes = "A4"


def build(sdir, ticker, model=None, out=None):
    rep = os.path.join(sdir, "report")
    if not model:
        ms = glob.glob(os.path.join(rep, "%s_finance_model_v*.xlsx" % ticker))
        if not ms:
            raise SystemExit("no %s_finance_model_v*.xlsx in %s - build the finance model first" % (ticker, rep))
        model = max(ms, key=lambda p: int(re.search(r"_v(\d+)\.xlsx$", p).group(1)))
    nar = load(sdir, "%s_deepdive_narrative.json" % ticker) or {}
    hosp, ops, pj = load(sdir, "%s_hospitals.json" % ticker), load(sdir, "%s_ops_metrics.json" % ticker), load(sdir, "%s_project.json" % ticker)
    wb = load_workbook(model)
    toc = [(ws.title, "แบบจำลองการเงิน (จากงบที่ยื่นต่อ ตลท.)") for ws in wb.worksheets]
    added = []
    if hosp:
        by_hospital(wb, hosp)
        added.append(("รายโรงพยาบาล (By hospital)", "รายได้ กำไร Capitation และเตียง รายโรงพยาบาล"))
    if ops and ops.get("metrics"):
        operations(wb, ops)
        added.append(("ปฏิบัติการ (Operations)", "ปริมาณ อัตราการใช้ รายได้ต่อใบเสร็จ จาก Oppday"))
    if pj:
        project(wb, pj)
        added.append(("โครงการใหม่ (Project)", "ขนาดโครงการ แหล่งเงิน ประมาณการ IFA กำหนดการ"))
    try:                                                    # section 7: sector position and early signals
        import deepdive_sector as DSEC
        sec = DSEC.load(sdir, ticker).get("sector")
        if sec and sec.get("rows") and DSEC.workbook(wb, sec, ticker, (Font(name=FONT, size=10, bold=True, color="FFFFFF"), PatternFill("solid", fgColor=NAVY), Font(name=FONT, size=10))):
            added.append(("อุตสาหกรรม", "ตำแหน่งของหุ้นในอุตสาหกรรมและสัญญาณล่วงหน้า (factsheet)"))
    except Exception as e:
        print("sector sheet skipped:", e)
    front(wb, nar, ticker, os.path.basename(model), added + toc)
    if not out:
        m = re.search(r"\d{4}Q\d", json.dumps((load(sdir, "%s_deepdive_data.json" % ticker) or {}).get("q_last", "")))
        year = (int(m.group()[:4]) + 543) if m else dt.date.today().year + 543
        n = 1 + max([int(re.search(r"_v(\d+)\.xlsx$", p).group(1)) for p in glob.glob(os.path.join(rep, "%s_Deepdive_%d_v*.xlsx" % (ticker, year)))] or [0])
        out = os.path.join(rep, "%s_Deepdive_%d_v%d.xlsx" % (ticker, year, n))
    wb.save(out)
    return out, model


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--stock-dir", required=True)
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--model", help="finance model xlsx (default: newest report/<T>_finance_model_v<N>.xlsx)")
    ap.add_argument("--out")
    a = ap.parse_args()
    out, model = build(a.stock_dir, a.ticker, a.model, a.out)
    print("✅ %s  (on %s)" % (out, os.path.basename(model)))


if __name__ == "__main__":
    main()
