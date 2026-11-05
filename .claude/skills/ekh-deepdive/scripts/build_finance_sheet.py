#!/usr/bin/env python3
"""
build_finance_sheet.py — 10-tab Thai-hospital financial model (xlsx) + Markdown companion.

Inputs
  1. <TICKER>_financials.json   from extract_financials.py  (facts with provenance)
  2. <TICKER>_assumptions.json  written by the agent (market data, revenue mix, one-offs,
                                executive summary text, valuation + project assumptions)
     -> scaffold one with:  build_finance_sheet.py init --financials ... --set-factsheet ...

Outputs (never overwrites; auto-increments):
  report/<TICKER>_finance_model_v<N>.xlsx
  report/<TICKER>_finance_model_v<N>.md

Tabs
  0 หน้าปก (Cover & Summary)       KPIs, executive summary, profit bridge, TOC, checks  [NEW]
  1 งบรวม (Consolidated)           quarterly hierarchy P&L / BS / ratios / CF + TTM
  2 งบเฉพาะกิจการ (Separate)        same layout, company-only statements
  3 งบบริษัทย่อย (Subsidiaries)     Consolidated − Separate + dividend-adjusted contribution
  4 โครงสร้างรายได้ (Revenue)       OPD / IPD / SSO quarterly mix (from MD&A)
  5 วิเคราะห์<project> (Sensitivity) expansion-project 2-D sensitivity (live formulas)
  6 งบรวมรายปี (Consolidated)       6 filed fiscal years (asm annual_years)  + interim YTD
  7 โครงสร้างรายได้ (Annual)        annual revenue mix
  8 ค่าใช้จ่ายตามลักษณะ (Nature)     expenses by nature (annual notes)
  9 ประเมินมูลค่า (Valuation)        valuation matrix + 3 sensitivity grids          [NEW]

Every number in the workbook is either (a) a blue input traced to a filing / Jitta / MD&A
source, or (b) a black formula.  Nothing is estimated by fixed ratios.
"""
import argparse, datetime, glob, json, os, re, sys

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.formatting.rule import CellIsRule, ColorScaleRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xlcalc import Workbook as CalcWB, XLError, num2col  # noqa: E402

# =============================================================================
# Styling
# =============================================================================
FONT = "Segoe UI"
NAVY, SUBTOTAL, SECTION, SECTION_TXT = "2F5496", "E2EFDA", "D9E1F2", "1F4E79"
ZEBRA, FALLBACK_FILL, CHECK_FILL, NOTE_GREY = "F7F9FC", "FFF2CC", "FCE4D6", "7F7F7F"
BLUE, BLACK, GREEN = "0000FF", "000000", "008000"
FMT = {
    "num": '#,##0.00;(#,##0.00);"-"', "pct": '0.0%;(0.0%);"-"', "x": '0.00"x";(0.00"x");"-"',
    "eps": '0.000;(0.000);"-"', "days": '#,##0;(#,##0);"-"', "int": '#,##0;(#,##0);"-"',
    "thb": '#,##0.00', "check": '0.00;(0.00);"0.00"', "text": "@", "pct2": '0.00%',
}
thin = Side(style="thin", color="BFBFBF")
BORDER_BOTTOM = Border(bottom=thin)
BORDER_TOTAL = Border(top=Side(style="thin", color="000000"), bottom=Side(style="double", color="000000"))
BORDER_SUB = Border(top=Side(style="thin", color="7F7F7F"))


def fnt(bold=False, color=BLACK, size=10, italic=False):
    return Font(name=FONT, bold=bold, color=color, size=size, italic=italic)


def fill(c):
    return PatternFill("solid", start_color=c, end_color=c)


def qs(name):
    return "'" + name.replace("'", "''") + "'"


def th_q(per):
    m = re.fullmatch(r"(\d{4})Q(\d)", per)
    return f"Q{m.group(2)}/{int(m.group(1)) + 543}" if m else per


def th_p(per):
    if per.startswith("FY"):
        return f"ปี {int(per[2:]) + 543}"
    m = re.fullmatch(r"(\d)M(\d{4})", per)
    if m:
        return f"{m.group(1)}M/{int(m.group(2)) + 543}"
    return th_q(per)


# =============================================================================
# Facts access (with virtual keys and sign normalisation)
# =============================================================================
class Facts:
    def __init__(self, fin, asm):
        self.f = dict(fin["facts"])
        self.rank = {}
        # manual facts from the agent (must carry a source)
        for k, v in (asm.get("manual_facts") or {}).items():
            self.f[k] = {"v": v["v"], "src": "MANUAL: " + v.get("src", "?")}
        # revenue mix from MD&A / 56-1
        mix = asm.get("revenue_mix") or {}
        msrc = mix.get("source", "MD&A")
        for bucket in ("quarterly", "annual"):
            for per, d in (mix.get(bucket) or {}).items():
                for k in ("opd", "ipd", "sso", "elim", "other", "cash", "gov", "misc"):
                    if d.get(k) is not None:
                        self.f[f"C|mix_{k}|{per}"] = {"v": float(d[k]), "src": f"{msrc} ({per})"}
        # one-offs are entered per quarter (after tax, consolidated) and rolled up into FY and YTD columns
        for o in asm.get("one_offs") or []:
            per = o["period"]
            amt = float(o["amount_after_tax"])
            targets = [per]
            m = re.fullmatch(r"(\d{4})Q(\d)", per)
            if m:
                y, q = int(m.group(1)), int(m.group(2))
                targets += [f"FY{y}"] + [f"{3 * k}M{y}" for k in (2, 3) if q <= k]
            for t in targets:
                k = f"C|one_off|{t}"
                prev = self.f.get(k, {"v": 0.0, "src": ""})
                self.f[k] = {"v": prev["v"] + amt, "src": (prev["src"] + "; " if prev["src"] else "") + o.get("label", "one-off")}

    def raw(self, ent, key, per):
        x = self.f.get(f"{ent}|{key}|{per}")
        return (x["v"], x["src"]) if x else (None, None)

    def get(self, ent, key, per):
        r = self.raw
        if key in ("rev_hosp", "cogs"):
            v, s = r(ent, key, per)
            extras = ("rev_other_ops", "rev_sales") if key == "rev_hosp" else ("cogs_other_ops", "cogs_sales")
            xs = [r(ent, x, per)[0] for x in extras]
            ov = None if all(x is None for x in xs) else sum(abs(x) if key == "cogs" else x for x in xs if x is not None)
            if ov is not None:        # services / food & beverage run alongside the hospital: count them as operating revenue and cost
                v = (abs(v) if v is not None else 0.0) + abs(ov) if key == "cogs" else (v or 0.0) + ov
                s = "%s + %s" % (s or "", "other operating / sale revenue" if key == "rev_hosp" else "other operating / sale cost")
            if v is None:
                return None, None
            return (abs(v) if key == "cogs" else v), s
        if key in ("cogs", "selling", "admin", "cf_da"):
            v, s = r(ent, key, per)
            if v is None and key == "admin" and r(ent, "selling", per)[0] is None:
                v, s = r(ent, "sga", per)           # one combined "distribution costs and administrative expenses" line
                s = s and "combined selling+admin line (%s)" % s
            return (abs(v), s) if v is not None else (None, None)
        if key == "fin":
            v, s = r(ent, "fin_cost", per)
            return (abs(v), s) if v is not None else (None, None)
        if key == "tax":
            pbt, s1 = r(ent, "pbt", per); np_, s2 = r(ent, "np", per)
            if pbt is not None and np_ is not None:
                return pbt - np_, f"PBT − NP ({s1})"
            v, s = r(ent, "tax", per)
            return (abs(v), s) if v is not None else (None, None)
        if key == "oth_inc":
            tr, s = r(ent, "total_rev", per); rh, _ = self.get(ent, "rev_hosp", per); dv, _ = r(ent, "dividend_income", per)
            if tr is not None and rh is not None:
                return tr - rh - (dv or 0.0), f"Total revenues − operating revenue − dividend ({s})"
            oi, s = r(ent, "other_income", per); ii, _ = r(ent, "interest_income", per)
            if oi is None and ii is None:
                return None, None
            return (oi or 0) + (ii or 0), s
        if key == "nci":
            v, s = r(ent, "np_nci", per)
            if v is not None:
                return v, s
            np_, s = r(ent, "np", per); no, _ = r(ent, "np_owners", per)
            if np_ is not None and no is not None:
                return np_ - no, "NP − NP owners"
            return (0.0, "no NCI line") if np_ is not None else (None, None)
        if key in ("debt", "lease", "capex"):
            parts = {"debt": ["st_debt", "lt_debt_cur", "lt_debt", "debentures"], "lease": ["lease_cur", "lease_lt"],
                     "capex": ["capex_ppe", "capex_payable", "capex_intang"]}[key]
            vals = [r(ent, p, per) for p in parts]
            if all(v is None for v, _ in vals):
                anchor = r(ent, "total_assets" if key != "capex" else "cfo", per)[0]
                return (0.0, "no line item in filing") if anchor is not None else (None, None)
            tot = sum(v for v, _ in vals if v is not None)
            src = next(s for v, s in vals if v is not None)
            return (abs(tot) if key == "capex" else tot), src
        if key == "divp":
            v, s = r(ent, "div_paid", per)
            if v is None:
                return (0.0, "no dividend line") if r(ent, "cfo", per)[0] is not None else (None, None)
            return abs(v), s
        if key == "div_inc":
            v, s = r(ent, "dividend_income", per)
            if v is None and r(ent, "rev_hosp", per)[0] is not None:
                return 0.0, "no dividend line"
            return v, s
        if key == "assoc":
            return r(ent, "share_assoc", per)
        return r(ent, key, per)


# =============================================================================
# Workbook model: writes openpyxl + mirrors cells for evaluation
# =============================================================================
class Col:
    def __init__(self, letter, per, label, ann=4, kind="q", bs_per=None, py=None, pp=None):
        self.letter, self.per, self.label, self.ann, self.kind = letter, per, label, ann, kind
        self.bs_per = bs_per or per
        self.py, self.pp = py, pp


class Model:
    def __init__(self):
        self.wb = Workbook()
        self.wb.remove(self.wb.active)
        self.cells = {}
        self.tabs = {}

    def sheet(self, key, name):
        assert len(name) <= 31, name
        ws = self.wb.create_sheet(name)
        ws.sheet_view.showGridLines = False
        self.cells[name] = {}
        t = Tab(self, key, ws)
        self.tabs[key] = t
        return t


class Tab:
    def __init__(self, model, key, ws):
        self.m, self.key, self.ws, self.name = model, key, ws, ws.title
        self.rowmap, self.rows, self.cols = {}, [], []
        self.r = 1

    # low-level put
    def put(self, addr, value, font=None, fill_=None, fmt=None, align=None, border=None, comment=None):
        c = self.ws[addr]
        c.value = value
        self.m.cells[self.name][addr] = value
        c.font = font or fnt()
        if fill_:
            c.fill = fill(fill_)
        if fmt:
            c.number_format = FMT.get(fmt, fmt)
        if align:
            c.alignment = align
        if border:
            c.border = border
        if comment:
            c.comment = Comment(comment[:500], "model")
        return c

    def ref(self, rid, col_letter, other=None):
        t = self.m.tabs[other] if other else self
        return f"{col_letter}{t.rowmap[rid]}" if not other else f"{qs(t.name)}!{col_letter}{t.rowmap[rid]}"

    def title(self, title, subtitle, note=None, width_a=54):
        self.put("A1", title, fnt(True, SECTION_TXT, 14))
        self.put("A2", subtitle, fnt(True, "595959", 11))
        self.put("A3", note or "หน่วย: ล้านบาท (THB mn) ยกเว้นที่ระบุ | ตัวเลขสีน้ำเงิน = ข้อมูลนำเข้าจากงบ/แหล่งอ้างอิง, สีดำ = สูตร, สีเขียว = ลิงก์ข้ามชีต, พื้นเหลือง = ข้อมูลสำรอง (Jitta/Manual)",
                 fnt(False, NOTE_GREY, 9, True))
        self.ws.column_dimensions["A"].width = width_a
        self.r = 5

    def header(self, cols, first="รายการ (ล้านบาท)", src_col=True):
        self.cols = cols
        r = self.r
        self.put(f"A{r}", first, fnt(True, "FFFFFF", 10), NAVY, align=Alignment(vertical="center"))
        for c in cols:
            self.put(f"{c.letter}{r}", c.label, fnt(True, "FFFFFF", 10), NAVY, align=Alignment(horizontal="center"))
            self.ws.column_dimensions[c.letter].width = 12.5
        if src_col:
            sc = num2col(max(ord(c.letter[-1]) - 64 for c in cols) + 1) if all(len(c.letter) == 1 for c in cols) else None
            self.src_letter = sc
            if sc:
                self.put(f"{sc}{r}", "แหล่งข้อมูล / หมายเหตุ", fnt(True, "FFFFFF", 10), NAVY)
                self.ws.column_dimensions[sc].width = 48
        self.ws.freeze_panes = f"B{r + 1}"
        self.r += 1

    def section(self, text, ncols=None):
        r = self.r
        last = ncols or (len(self.cols) + 2)
        for i in range(1, last + 1):
            self.put(f"{num2col(i)}{r}", text if i == 1 else None, fnt(True, SECTION_TXT, 10), SECTION)
        self.r += 1

    # ------------------------------------------------------------------
    def render(self, tpl, col):
        """[id] same col, [id@py] prior-year col, [id@pp] prior period, [TAB:id] other tab same col, {ann}."""
        missing = False

        def rep(m):
            nonlocal missing
            other, rid, shift = m.group(1), m.group(2), m.group(3)
            letter = col.letter
            if shift == "py":
                letter = col.py
            elif shift == "pp":
                letter = col.pp
            if letter is None:
                missing = True
                return "0"
            t = self.m.tabs[other] if other else self
            if rid not in t.rowmap:
                raise KeyError(f"{rid} not in {t.name}")
            a = f"{letter}{t.rowmap[rid]}"
            return f"{qs(t.name)}!{a}" if other else a

        out = re.sub(r"\[(?:([A-Z_]+):)?([a-z0-9_]+)(?:@(py|pp))?\]", rep, tpl)
        out = out.replace("{ann}", str(col.ann))
        return None if missing else "=" + out

    def add_row(self, spec, facts=None, ent=None):
        """spec keys: id, label, kind(in|f|link|sub|txt), key, fmt, lvl, style, f, ttm, guard, bs, note, q_only."""
        r = self.r
        rid = spec["id"]
        self.rowmap[rid] = r
        self.rows.append((rid, r, spec))
        style = spec.get("style")
        lvl = spec.get("lvl", 0)
        bold = style in ("sub", "total", "check")
        lab_font = fnt(bold, BLACK if style != "ratio" else "404040", 10, italic=(style in ("ratio", "growth")))
        zeb = ZEBRA if (len(self.rows) % 2 == 0 and style not in ("sub", "total", "check")) else None
        rowfill = SUBTOTAL if style in ("sub", "total") else (CHECK_FILL if style == "check" else zeb)
        self.put(f"A{r}", spec["label"], lab_font, rowfill, align=Alignment(indent=lvl))
        fmt = spec.get("fmt", "num")
        border = BORDER_TOTAL if style == "total" else (BORDER_SUB if style == "sub" else None)
        srcs = set()
        for c in self.cols:
            addr = f"{c.letter}{r}"
            val, font, cm, cf = None, fnt(bold, BLACK), None, rowfill
            kind = spec["kind"]
            if spec.get("q_only") and c.kind != "q":
                pass
            elif c.kind == "ttm" and kind == "in":
                mode = spec.get("ttm", "sum")
                qcols = [x for x in self.cols if x.kind == "q"]
                if mode == "sum" and len(qcols) >= 4 and spec["id"] in OPTIONAL_ROWS:
                    val = f"=SUM({qcols[-4].letter}{r}:{qcols[-1].letter}{r})"
                elif mode == "sum" and len(qcols) >= 4:
                    val = f"=IF(COUNT({qcols[-4].letter}{r}:{qcols[-1].letter}{r})=4,SUM({qcols[-4].letter}{r}:{qcols[-1].letter}{r}),\"\")"
                elif mode == "last":
                    val = f"={qcols[-1].letter}{r}"
            elif c.kind == "ttm" and kind in ("f", "link") and spec.get("ttm") == "none":
                pass
            elif kind == "in":
                per = c.bs_per if spec.get("bs") else c.per
                v, s = facts.get(ent, spec["key"], per)
                if v is not None:
                    val = round(v, 6)
                    font = fnt(bold, BLUE)
                    if s and ("Jitta" in s or "MANUAL" in s):
                        cf = FALLBACK_FILL
                        cm = s
                    elif s and s.startswith("derived"):
                        cm = s
                    if s:
                        srcs.add(s.split(":")[0].split(" (")[0])
            elif kind in ("f", "link"):
                tpl = spec["f"]
                if isinstance(tpl, dict):
                    tpl = tpl.get(c.kind, tpl.get("q"))
                val = self.render(tpl, c) if tpl else None
                if val and spec.get("guard"):
                    g = spec["guard"]
                    gl = [g] if isinstance(g, str) else g
                    cond = ",".join(f"[{x}]=\"\"" for x in gl)
                    gexpr = self.render(f"OR({cond})", c)[1:]
                    val = f"=IF({gexpr},\"\",{val[1:]})"
                if kind == "link" or (val and "!" in val and spec.get("green", True)):
                    font = fnt(bold, GREEN)
            self.put(addr, val, font, cf, fmt, Alignment(horizontal="right"), border, cm)
        if getattr(self, "src_letter", None):
            note = spec.get("note") or ("; ".join(sorted(srcs))[:120] if srcs else "")
            if note:
                self.put(f"{self.src_letter}{r}", note, fnt(False, NOTE_GREY, 8, True))
        self.r += 1
        return r

    def blank(self, n=1):
        self.r += n

    def text(self, t, col="A", font=None, fill_=None, merge_to=None, height=None, wrap=True):
        r = self.r
        self.put(f"{col}{r}", t, font or fnt(), fill_, align=Alignment(wrap_text=wrap, vertical="top"))
        if merge_to:
            self.ws.merge_cells(f"{col}{r}:{merge_to}{r}")
        if height:
            self.ws.row_dimensions[r].height = height
        self.r += 1
        return r


# Rows that may legitimately be empty (no line item in the filing) -> treated as 0 in arithmetic
OPTIONAL_ROWS = {"fin_inc", "assoc", "one_off", "div_inc", "ecl", "eq_nci", "debt", "lease", "nci", "st_inv", "fin", "other", "elim", "sso"}

# =============================================================================
# Row specifications
# =============================================================================
def statement_rows(has_sso=True):
    g = lambda rid, lab, shift="py": {"id": f"{rid}_{shift}", "label": lab, "kind": "f", "fmt": "pct", "lvl": 2,
                                       "style": "growth", "f": f"IFERROR([{rid}]/[{rid}@{shift}]-1,\"\")", "ttm": "none",
                                       **({"q_only": True} if shift == "pp" else {})}
    return [
        ("section", "ส่วนที่ 1: งบกำไรขาดทุน (Income Statement)"),
        {"id": "rev_hosp", "label": "รายได้จากกิจการโรงพยาบาล (Hospital Revenue)", "kind": "in", "key": "rev_hosp", "lvl": 0},
        g("rev_hosp", "% เติบโต YoY"),
        g("rev_hosp", "% เติบโต QoQ", "pp"),
        {"id": "div_inc", "label": "รายได้เงินปันผล (Dividend Income)", "kind": "in", "key": "div_inc", "lvl": 1},
        {"id": "oth_inc", "label": "รายได้อื่น รวมดอกเบี้ยรับ (Other Income)", "kind": "in", "key": "oth_inc", "lvl": 1},
        {"id": "total_rev", "label": "รายได้รวม (Total Revenues)", "kind": "f", "style": "sub", "guard": "rev_hosp",
         "f": "[rev_hosp]+[div_inc]+[oth_inc]"},
        {"id": "cogs", "label": "หัก ต้นทุนกิจการโรงพยาบาล (Cost of Hospital Operations)", "kind": "in", "key": "cogs", "lvl": 1},
        {"id": "gp", "label": "กำไรขั้นต้น (Gross Profit)", "kind": "f", "style": "sub", "guard": "rev_hosp", "f": "[rev_hosp]-[cogs]"},
        {"id": "gpm", "label": "อัตรากำไรขั้นต้น (GPM %)", "kind": "f", "fmt": "pct", "lvl": 2, "style": "ratio",
         "f": "IFERROR([gp]/[rev_hosp],\"\")"},
        g("gp", "% เติบโตกำไรขั้นต้น YoY"),
        {"id": "selling", "label": "ค่าใช้จ่ายในการขาย (Selling - SG)", "kind": "in", "key": "selling", "lvl": 1},
        {"id": "sg_pct", "label": "% ค่าใช้จ่ายในการขายต่อรายได้ (% SG to Sales)", "kind": "f", "fmt": "pct", "lvl": 2,
         "style": "ratio", "f": "IFERROR([selling]/[rev_hosp],\"\")"},
        {"id": "admin", "label": "ค่าใช้จ่ายในการบริหาร (Administrative - SA)", "kind": "in", "key": "admin", "lvl": 1},
        {"id": "sa_pct", "label": "% ค่าใช้จ่ายในการบริหารต่อรายได้ (% SA to Sales)", "kind": "f", "fmt": "pct", "lvl": 2,
         "style": "ratio", "f": "IFERROR([admin]/[rev_hosp],\"\")"},
        {"id": "sga", "label": "รวมค่าใช้จ่าย SG&A", "kind": "f", "style": "sub", "guard": "rev_hosp", "f": "N([selling])+N([admin])"},
        {"id": "sga_pct", "label": "% SG&A ต่อรายได้โรงพยาบาล", "kind": "f", "fmt": "pct", "lvl": 2, "style": "ratio",
         "f": "IFERROR([sga]/[rev_hosp],\"\")"},
        {"id": "ebit", "label": "กำไรจากการดำเนินงาน (EBIT / Operating Profit)", "kind": "f", "style": "total", "guard": "rev_hosp",
         "f": "[total_rev]-[cogs]-[sga]"},
        {"id": "ebit_m", "label": "อัตรากำไรจากการดำเนินงาน (EBIT Margin %)", "kind": "f", "fmt": "pct", "lvl": 2, "style": "ratio",
         "f": "IFERROR([ebit]/[total_rev],\"\")"},
        g("ebit", "% เติบโต EBIT YoY"),
        {"id": "assoc", "label": "ส่วนแบ่งกำไรจากเงินลงทุน (Share of Associates)", "kind": "in", "key": "assoc", "lvl": 1},
        {"id": "fin_inc", "label": "บวก รายได้ทางการเงิน (Finance Income)", "kind": "in", "key": "fin_inc", "lvl": 1},
        {"id": "fin", "label": "หัก ต้นทุนทางการเงิน (Finance Costs)", "kind": "in", "key": "fin", "lvl": 1},
        {"id": "pbt", "label": "กำไรก่อนภาษีเงินได้ (PBT)", "kind": "f", "style": "sub", "guard": "rev_hosp", "f": "[ebit]+[assoc]+[fin_inc]-[fin]"},
        {"id": "tax", "label": "หัก ภาษีเงินได้ (Income Tax)", "kind": "in", "key": "tax", "lvl": 1},
        {"id": "etr", "label": "อัตราภาษีที่แท้จริง (Effective Tax Rate %)", "kind": "f", "fmt": "pct", "lvl": 2, "style": "ratio",
         "f": "IFERROR([tax]/[pbt],\"\")"},
        {"id": "np", "label": "กำไรสุทธิสำหรับงวด (Net Profit)", "kind": "f", "style": "total", "guard": "rev_hosp", "f": "[pbt]-[tax]"},
        {"id": "nci", "label": "หัก ส่วนของผู้มีส่วนได้เสียที่ไม่มีอำนาจควบคุม (NCI)", "kind": "in", "key": "nci", "lvl": 1},
        {"id": "np_owners", "label": "กำไรสุทธิส่วนของผู้ถือหุ้นบริษัทใหญ่ (NP to Owners)", "kind": "f", "style": "total",
         "guard": "rev_hosp", "f": "[np]-[nci]"},
        {"id": "npm", "label": "อัตรากำไรสุทธิ (NPM % ของรายได้รวม)", "kind": "f", "fmt": "pct", "lvl": 2, "style": "ratio",
         "f": "IFERROR([np]/[total_rev],\"\")"},
        g("np_owners", "% เติบโตกำไรสุทธิ YoY"),
        g("np_owners", "% เติบโตกำไรสุทธิ QoQ", "pp"),
        {"id": "one_off", "label": "รายการพิเศษหลังภาษี (One-off, after tax)", "kind": "in", "key": "one_off", "lvl": 1},
        {"id": "core_np", "label": "กำไรปกติ (Core Profit)", "kind": "f", "style": "sub", "guard": "rev_hosp", "f": "[np_owners]-[one_off]"},
        {"id": "eps", "label": "กำไรต่อหุ้นขั้นพื้นฐาน (EPS, บาท)", "kind": "in", "key": "eps", "fmt": "eps", "lvl": 1},
        ("section", "ข้อมูลประกอบ (Memo: EBITDA & Credit Loss)"),
        {"id": "da", "label": "ค่าเสื่อมราคาและค่าตัดจำหน่าย (D&A)", "kind": "in", "key": "cf_da", "lvl": 1},
        {"id": "ebitda", "label": "EBITDA", "kind": "f", "style": "sub", "guard": ["da", "rev_hosp"], "f": "[ebit]+[da]"},
        {"id": "ebitda_m", "label": "EBITDA Margin % (ของรายได้รวม)", "kind": "f", "fmt": "pct", "lvl": 2, "style": "ratio",
         "f": "IFERROR([ebitda]/[total_rev],\"\")"},
        {"id": "ecl", "label": "ผลขาดทุนด้านเครดิตที่คาดว่าจะเกิด (ECL, กลับรายการ)", "kind": "in", "key": "cf_ecl", "lvl": 1},
        {"id": "ecl_pct", "label": "% ECL ต่อรายได้โรงพยาบาล", "kind": "f", "fmt": "pct", "lvl": 2, "style": "ratio",
         "f": "IFERROR([ecl]/[rev_hosp],\"\")"},
        ("section", "ส่วนที่ 2: งบแสดงฐานะการเงิน (Balance Sheet)"),
        {"id": "cash", "label": "เงินสดและรายการเทียบเท่าเงินสด", "kind": "in", "key": "cash", "bs": True, "ttm": "last", "lvl": 1},
        {"id": "st_inv", "label": "เงินลงทุนระยะสั้น / สินทรัพย์ทางการเงินหมุนเวียน", "kind": "in", "key": "st_invest", "bs": True, "ttm": "last", "lvl": 1},
        {"id": "cash_total", "label": "รวมเงินสดและเงินลงทุนระยะสั้น", "kind": "f", "style": "sub", "guard": "cash", "f": "[cash]+[st_inv]"},
        {"id": "recv", "label": "ลูกหนี้การค้าและลูกหนี้อื่น", "kind": "in", "key": "receivables", "bs": True, "ttm": "last", "lvl": 1},
        {"id": "inv", "label": "ยาและเวชภัณฑ์คงเหลือ (Inventories)", "kind": "in", "key": "inventory", "bs": True, "ttm": "last", "lvl": 1},
        {"id": "total_ca", "label": "รวมสินทรัพย์หมุนเวียน", "kind": "in", "key": "total_ca", "bs": True, "ttm": "last", "lvl": 1},
        {"id": "ppe", "label": "ที่ดิน อาคารและอุปกรณ์ สุทธิ (PPE)", "kind": "in", "key": "ppe", "bs": True, "ttm": "last", "lvl": 1},
        {"id": "total_assets", "label": "สินทรัพย์รวม (Total Assets)", "kind": "in", "key": "total_assets", "bs": True, "ttm": "last",
         "style": "sub"},
        {"id": "payables", "label": "เจ้าหนี้การค้าและเจ้าหนี้อื่น", "kind": "in", "key": "payables", "bs": True, "ttm": "last", "lvl": 1},
        {"id": "debt", "label": "เงินกู้ยืมและหุ้นกู้ (Interest-bearing Debt)", "kind": "in", "key": "debt", "bs": True, "ttm": "last", "lvl": 1},
        {"id": "lease", "label": "หนี้สินตามสัญญาเช่า (Lease Liabilities)", "kind": "in", "key": "lease", "bs": True, "ttm": "last", "lvl": 1},
        {"id": "total_liab", "label": "หนี้สินรวม (Total Liabilities)", "kind": "in", "key": "total_liab", "bs": True, "ttm": "last",
         "style": "sub"},
        {"id": "eq_owners", "label": "ส่วนของผู้ถือหุ้นบริษัทใหญ่", "kind": "in", "key": "equity_owners", "bs": True, "ttm": "last", "lvl": 1},
        {"id": "eq_nci", "label": "ส่วนได้เสียที่ไม่มีอำนาจควบคุม (NCI)", "kind": "in", "key": "equity_nci", "bs": True, "ttm": "last", "lvl": 1},
        {"id": "total_equity", "label": "ส่วนของผู้ถือหุ้นรวม (Total Equity)", "kind": "in", "key": "total_equity", "bs": True, "ttm": "last",
         "style": "sub"},
        {"id": "bal_check", "label": "ตรวจสอบสมการงบดุล A − (L + E) = 0.00", "kind": "f", "fmt": "check", "style": "check",
         "f": "IF(OR([total_assets]=\"\",[total_liab]=\"\",[total_equity]=\"\"),\"n/a\",ROUND([total_assets]-[total_liab]-[total_equity],2))"},
        {"id": "net_cash", "label": "เงินสดสุทธิ (Net Cash = เงินสด+ลงทุน − หนี้ − สัญญาเช่า)", "kind": "f", "style": "sub",
         "guard": "cash", "f": "[cash_total]-[debt]-[lease]"},
        {"id": "de", "label": "หนี้สินรวมต่อทุน (D/E, เท่า)", "kind": "f", "fmt": "x", "lvl": 2, "style": "ratio",
         "f": "IFERROR([total_liab]/[total_equity],\"\")"},
        {"id": "ibde", "label": "หนี้ที่มีภาระดอกเบี้ยต่อทุน (IBD/E, เท่า)", "kind": "f", "fmt": "x", "lvl": 2, "style": "ratio",
         "f": "IFERROR(([debt]+[lease])/[total_equity],\"\")"},
        ("section", "ส่วนที่ 3: อัตราผลตอบแทนและประสิทธิภาพ (Returns & Efficiency)"),
        {"id": "roa", "label": "ROA (%, annualised)", "kind": "f", "fmt": "pct", "lvl": 1, "style": "ratio",
         "f": "IFERROR([np]*{ann}/[total_assets],\"\")"},
        {"id": "roe", "label": "ROE (%, annualised, ส่วนของบริษัทใหญ่)", "kind": "f", "fmt": "pct", "lvl": 1, "style": "ratio",
         "f": "IFERROR([np_owners]*{ann}/[eq_owners],\"\")"},
        {"id": "roic", "label": "ROIC (%, EBIT×(1−ETR) / (Equity+Debt+Lease−Cash))", "kind": "f", "fmt": "pct", "lvl": 1, "style": "ratio",
         "f": "IFERROR([ebit]*(1-[etr])*{ann}/([total_equity]+[debt]+[lease]-[cash_total]),\"\")"},
        {"id": "dso", "label": "ระยะเวลาเก็บหนี้ (DSO, วัน)", "kind": "f", "fmt": "days", "lvl": 1, "style": "ratio",
         "f": "IFERROR([recv]/([rev_hosp]*{ann})*365,\"\")"},
        {"id": "dio", "label": "ระยะเวลายาคงคลัง (DIO, วัน)", "kind": "f", "fmt": "days", "lvl": 1, "style": "ratio",
         "f": "IFERROR([inv]/([cogs]*{ann})*365,\"\")"},
        ("section", "ส่วนที่ 4: กระแสเงินสด (Cash Flow — single period)"),
        {"id": "cfo", "label": "เงินสดสุทธิจากการดำเนินงาน (CFO)", "kind": "in", "key": "cfo", "lvl": 1},
        {"id": "capex", "label": "หัก รายจ่ายลงทุน (CAPEX: PPE + เจ้าหนี้ค่าสินทรัพย์ + Intangibles)", "kind": "in", "key": "capex", "lvl": 1},
        {"id": "fcf", "label": "กระแสเงินสดอิสระ (FCF = CFO − CAPEX)", "kind": "f", "style": "sub", "guard": "cfo", "f": "[cfo]-[capex]"},
        {"id": "divp", "label": "เงินปันผลจ่าย (Dividends Paid)", "kind": "in", "key": "divp", "lvl": 1},
        {"id": "cash_conv", "label": "คุณภาพกำไร CFO / Net Profit (เท่า)", "kind": "f", "fmt": "x", "lvl": 2, "style": "ratio",
         "f": "IFERROR([cfo]/[np],\"\")"},
        ("section", "ส่วนที่ 5: กระทบยอดกับงบการเงิน (Tie-out to Reported Figures)"),
        {"id": "rep_op", "label": "งบฯ: กำไรจากการดำเนินงาน (Reported Operating Profit)", "kind": "in", "key": "op_profit", "lvl": 1},
        {"id": "chk_ebit", "label": "ตรวจสอบ EBIT − Reported = 0.00", "kind": "f", "fmt": "check", "style": "check",
         "f": "IF(OR([rep_op]=\"\",[ebit]=\"\"),\"n/a\",ROUND([ebit]-[rep_op],2))"},
        {"id": "rep_np", "label": "งบฯ: กำไรสุทธิส่วนของบริษัทใหญ่ (Reported NP to Owners)", "kind": "in", "key": "np_owners", "lvl": 1},
        {"id": "chk_np", "label": "ตรวจสอบ NP Owners − Reported = 0.00", "kind": "f", "fmt": "check", "style": "check",
         "f": "IF(OR([rep_np]=\"\",[np_owners]=\"\"),\"n/a\",ROUND([np_owners]-[rep_np],2))"},
    ]


def build_statement_tab(model, key, name, title, subtitle, cols, facts, ent, has_sso, extra=None):
    t = model.sheet(key, name)
    t.title(title, subtitle)
    t.header(cols)
    for spec in statement_rows(has_sso):
        if isinstance(spec, tuple):
            t.section(spec[1])
            continue
        t.add_row(spec, facts, ent)
    if extra:
        extra(t)
    return t


def build_subs_tab(model, cols, subtitle):
    name = "งบบริษัทย่อย (Subsidiaries)"
    t = model.sheet("SUB", name)
    t.title("งบบริษัทย่อยและรายการตัดบัญชี (Subsidiaries & Eliminations = Consolidated − Separate)", subtitle,
            "สูตรไดนามิก: ทุกช่องข้อมูล = งบรวม − งบเฉพาะกิจการ | ข้อควรระวัง: งบเฉพาะกิจการรวม 'เงินปันผลรับจากบริษัทย่อย' "
            "จึงต้องดูแถวปรับปรุงด้านล่างเพื่อวัดกำไรที่แท้จริงของบริษัทย่อย")
    t.header(cols)
    for spec in statement_rows():
        if isinstance(spec, tuple):
            t.section(spec[1]); continue
        s = dict(spec)
        if s["kind"] == "in":
            s["kind"] = "f"
            if s["id"] in OPTIONAL_ROWS:
                s["f"] = f"N([C:{s['id']}])-N([S:{s['id']}])"
            else:
                s["f"] = f"IF(OR([C:{s['id']}]=\"\",[S:{s['id']}]=\"\"),\"\",[C:{s['id']}]-[S:{s['id']}])"
            if s.get("ttm") == "last" or s["id"] == "eps":
                pass
            s["note"] = "สูตร: งบรวม − งบเฉพาะกิจการ"
            if s["id"] in ("eps", "rep_op", "rep_np"):
                s["f"] = "\"\"" if s["id"] == "eps" else s["f"]
        t.add_row(s)
    t.section("ส่วนที่ 6: การวิเคราะห์สัดส่วนกำไร (Dividend-adjusted Contribution)")
    rows = [
        {"id": "sep_div_sub", "label": "เงินปันผลรับจากบริษัทย่อยในงบเฉพาะกิจการ (Intra-group dividend)", "kind": "f", "lvl": 1,
         "f": "IF(OR([C:div_inc]=\"\",[S:div_inc]=\"\"),\"\",[S:div_inc]-[C:div_inc])", "ttm": "sum_f"},
        {"id": "sep_np_adj", "label": "กำไรสุทธิบริษัทแม่ ไม่รวมปันผลจากบริษัทย่อย (Parent NP ex-dividend)", "kind": "f", "style": "sub",
         "f": "IF(OR([S:np]=\"\",[sep_div_sub]=\"\"),\"\",[S:np]-[sep_div_sub])"},
        {"id": "sub_np_adj", "label": "กำไรสุทธิบริษัทย่อย+ตัดบัญชี ปรับปรุงแล้ว (Subsidiaries NP, adjusted)", "kind": "f", "style": "sub",
         "f": "IF(OR([C:np]=\"\",[sep_np_adj]=\"\"),\"\",[C:np]-[sep_np_adj])"},
        {"id": "sub_np_share", "label": "สัดส่วนกำไรจากบริษัทย่อย (% ของกำไรรวม)", "kind": "f", "fmt": "pct", "lvl": 2, "style": "ratio",
         "f": "IFERROR([sub_np_adj]/[C:np],\"\")"},
        {"id": "sub_rev_share", "label": "สัดส่วนรายได้จากบริษัทย่อย (% ของรายได้โรงพยาบาลรวม)", "kind": "f", "fmt": "pct", "lvl": 2,
         "style": "ratio", "f": "IFERROR(([C:rev_hosp]-[S:rev_hosp])/[C:rev_hosp],\"\")"},
        {"id": "sub_npm_adj", "label": "อัตรากำไรสุทธิบริษัทย่อย ปรับปรุงแล้ว (%)", "kind": "f", "fmt": "pct", "lvl": 2, "style": "ratio",
         "f": "IFERROR([sub_np_adj]/([C:rev_hosp]-[S:rev_hosp]),\"\")"},
        {"id": "sep_npm_adj", "label": "อัตรากำไรสุทธิบริษัทแม่ ไม่รวมปันผล (%)", "kind": "f", "fmt": "pct", "lvl": 2, "style": "ratio",
         "f": "IFERROR([sep_np_adj]/[S:rev_hosp],\"\")"},
    ]
    for s in rows:
        if s.get("ttm") == "sum_f":
            s = dict(s); s["ttm"] = None
        t.add_row(s)
    return t


def build_mix_tab(model, key, name, title, cols, facts, rev_link_tab, has_sso, source_note):
    t = model.sheet(key, name)
    t.title(title, source_note)
    t.header(cols)
    g = lambda rid, lab: {"id": f"{rid}_py", "label": lab, "kind": "f", "fmt": "pct", "lvl": 2, "style": "growth",
                          "f": f"IFERROR([{rid}]/[{rid}@py]-1,\"\")", "ttm": "none"}
    rows = [
        ("section", "รายได้จำแนกตามประเภทผู้ป่วย (Revenue by Payor / Patient Type)"),
        {"id": "opd", "label": "ผู้ป่วยนอกทั่วไป (OPD - Non-Capitation)", "kind": "in", "key": "mix_opd", "lvl": 1},
        g("opd", "% เติบโต OPD YoY"),
        {"id": "ipd", "label": "ผู้ป่วยในทั่วไป (IPD - Non-Capitation)", "kind": "in", "key": "mix_ipd", "lvl": 1},
        g("ipd", "% เติบโต IPD YoY"),
        {"id": "noncap", "label": "รวมผู้ป่วยทั่วไป (Non-Capitation: เงินสด/ประกัน)", "kind": "f", "style": "sub", "guard": "opd",
         "f": "[opd]+[ipd]"},
        g("noncap", "% เติบโตผู้ป่วยทั่วไป YoY"),
        {"id": "sso", "label": "ประกันสังคม (SSO Capitation + High-cost)" if has_sso else "ประกันสังคม (ไม่มีบริการ — Non-SSO)",
         "kind": "in", "key": "mix_sso", "lvl": 1},
        g("sso", "% เติบโตประกันสังคม YoY"),
        {"id": "other", "label": "รายได้อื่นจากกิจการ (Other hospital revenue)", "kind": "in", "key": "mix_other", "lvl": 1},
        {"id": "gross", "label": "รวมรายได้จากการให้บริการ (ก่อนตัดรายการระหว่างกัน)", "kind": "f", "style": "sub", "guard": "opd",
         "f": "[noncap]+[sso]+[other]"},
        {"id": "elim", "label": "หัก รายการระหว่างกัน (Eliminations)", "kind": "in", "key": "mix_elim", "lvl": 1},
        {"id": "hosp", "label": "รายได้จากกิจการโรงพยาบาลสุทธิ", "kind": "f", "style": "total", "guard": "opd", "f": "[gross]-[elim]"},
        g("hosp", "% เติบโตรายได้โรงพยาบาล YoY"),
        {"id": "rep", "label": "งบฯ: รายได้จากกิจการโรงพยาบาล (Reported)", "kind": "link", "f": f"[{rev_link_tab}:rev_hosp]", "lvl": 1},
        {"id": "chk", "label": "ตรวจสอบ Mix − Reported (≈ 0; ต่างได้จากการปัดเศษ MD&A)", "kind": "f", "fmt": "check", "style": "check",
         "f": "IF(OR([opd]=\"\",[rep]=\"\"),\"n/a\",ROUND([hosp]-[rep],2))"},
        ("section", "สัดส่วนรายได้ (Revenue Mix % of Gross Service Revenue)"),
        {"id": "opd_pct", "label": "สัดส่วน OPD (%)", "kind": "f", "fmt": "pct", "lvl": 1, "style": "ratio", "f": "IFERROR([opd]/[gross],\"\")"},
        {"id": "ipd_pct", "label": "สัดส่วน IPD (%)", "kind": "f", "fmt": "pct", "lvl": 1, "style": "ratio", "f": "IFERROR([ipd]/[gross],\"\")"},
        {"id": "noncap_pct", "label": "สัดส่วนผู้ป่วยทั่วไป Non-Cap (%)", "kind": "f", "fmt": "pct", "lvl": 1, "style": "ratio",
         "f": "IFERROR([noncap]/[gross],\"\")"},
        {"id": "sso_pct", "label": "สัดส่วนประกันสังคม Capitation (%)", "kind": "f", "fmt": "pct", "lvl": 1, "style": "ratio",
         "f": "IFERROR([sso]/[gross],\"\")"},
    ]
    for s in rows:
        if isinstance(s, tuple):
            t.section(s[1]); continue
        t.add_row(s, facts, "C")
    return t


def build_nature_tab(model, cols, facts, subtitle):
    t = model.sheet("NAT", "ค่าใช้จ่ายตามลักษณะ (Nature)")
    t.title("ค่าใช้จ่ายตามลักษณะ (Expenses by Nature) — หมายเหตุประกอบงบการเงินประจำปี", subtitle,
            "ที่มา: หมายเหตุประกอบงบ 'ค่าใช้จ่ายตามลักษณะ' (งบรวม) | งวดระหว่างกาลไม่เปิดเผยจะเว้นว่าง (ไม่ประมาณการ)")
    t.header(cols)
    pct = lambda rid, lab: {"id": f"{rid}_pct", "label": lab, "kind": "f", "fmt": "pct", "lvl": 2, "style": "ratio",
                            "guard": rid, "f": f"IFERROR([{rid}]/[base],\"\")"}
    rows = [
        {"id": "base", "label": "ฐานรายได้จากกิจการโรงพยาบาล", "kind": "link", "f": "[A:rev_hosp]", "style": "sub"},
        {"id": "opex_total", "label": "ต้นทุน + SG&A ตามงบกำไรขาดทุน", "kind": "link", "f": "IFERROR([A:cogs]+[A:sga],\"\")", "lvl": 1},
        ("section", "ค่าใช้จ่ายหลัก 5 หมวด (Key cost buckets)"),
        {"id": "staff", "label": "1. เงินเดือน ค่าแรง และผลประโยชน์พนักงาน", "kind": "in", "key": "exp_staff", "lvl": 1}, pct("staff", "% ต่อรายได้"),
        {"id": "doctor", "label": "2. ค่าธรรมเนียมแพทย์ (Doctor Fees)", "kind": "in", "key": "exp_doctor", "lvl": 1}, pct("doctor", "% ต่อรายได้"),
        {"id": "med", "label": "3. ยา เวชภัณฑ์ และวัสดุสิ้นเปลืองใช้ไป", "kind": "in", "key": "exp_medicine", "lvl": 1}, pct("med", "% ต่อรายได้"),
        {"id": "dep", "label": "4. ค่าเสื่อมราคาและค่าตัดจำหน่าย", "kind": "in", "key": "exp_da", "lvl": 1}, pct("dep", "% ต่อรายได้"),
        {"id": "ref", "label": "5. ค่ารักษาพยาบาลส่งต่อ (Referral)", "kind": "in", "key": "exp_referral", "lvl": 1}, pct("ref", "% ต่อรายได้"),
        {"id": "sum5", "label": "รวมค่าใช้จ่ายหลัก 5 หมวด", "kind": "f", "style": "sub", "guard": "staff",
         "f": "[staff]+[doctor]+[med]+[dep]+[ref]"},
        pct("sum5", "% รวม 5 หมวดต่อรายได้"),
        {"id": "other", "label": "6. ค่าใช้จ่ายดำเนินงานอื่น (คำนวณ = ต้นทุน+SG&A − 5 หมวด)", "kind": "f", "lvl": 1, "guard": "staff",
         "f": "[opex_total]-[sum5]"},
        pct("other", "% ต่อรายได้"),
        {"id": "total", "label": "รวมต้นทุนและค่าใช้จ่ายดำเนินงาน", "kind": "f", "style": "total", "guard": "staff", "f": "[sum5]+[other]"},
        pct("total", "% ต้นทุนรวมต่อรายได้"),
        {"id": "staff_doc_py", "label": "% เติบโตค่าบุคลากร (พนักงาน+แพทย์) YoY", "kind": "f", "fmt": "pct", "lvl": 2, "style": "growth",
         "f": "IFERROR(([staff]+[doctor])/([staff@py]+[doctor@py])-1,\"\")"},
    ]
    for s in rows:
        if isinstance(s, tuple):
            t.section(s[1]); continue
        t.add_row(s, facts, "C")
    return t


# =============================================================================
# Project sensitivity
# =============================================================================
def build_project_tab(model, asm, name):
    p = asm.get("project") or {}
    t = model.sheet("PRJ", name)
    t.title(f"แบบจำลองความอ่อนไหวโครงการ: {p.get('name', 'โครงการขยาย (ยังไม่ระบุ)')}",
            "Project Sensitivity — กำไรสุทธิโครงการ และ ROE กลุ่ม ตามอัตราครองเตียง × รายได้ต่อวันนอน",
            "สูตรทั้งหมดคำนวณสด: แก้ตัวเลขสีน้ำเงินแล้วตารางจะเปลี่ยนทันที | ที่มาของสมมติฐาน: " + p.get("source", "agent/ผู้ใช้"), width_a=48)
    ws = t.ws
    for c in "BCDEFGHIJK":
        ws.column_dimensions[c].width = 13
    if not p:
        t.text("⚠ ไม่มีโครงการขยายที่ระบุใน assumptions.json (key: project) — ชีตนี้เว้นไว้", font=fnt(True, "C00000"))
        return t
    t.section("สมมติฐานโครงการ (Inputs)", 3)
    inputs = [
        ("beds", "จำนวนเตียงที่เปิดให้บริการ (เตียง)", p.get("beds", 200), "int"),
        ("capex", "เงินลงทุนรวม (ล้านบาท)", p.get("capex", 0), "num"),
        ("land", "มูลค่าที่ดิน (ไม่คิดค่าเสื่อม, ล้านบาท)", p.get("land_value", 0), "num"),
        ("years", "อายุการคิดค่าเสื่อม (ปี)", p.get("dep_years", 20), "int"),
        ("fixed", "ค่าใช้จ่ายคงที่ต่อปี (Fixed OPEX, ล้านบาท)", p.get("fixed_opex", 0), "num"),
        ("vcr", "ต้นทุนผันแปรต่อรายได้ (Variable cost %)", p.get("variable_cost_ratio", 0.45), "pct"),
        ("tax", "อัตราภาษี (%)", p.get("tax_rate", 0.20), "pct"),
    ]
    for rid, lab, v, f in inputs:
        r = t.r; t.rowmap[rid] = r
        t.put(f"A{r}", lab); t.put(f"B{r}", v, fnt(False, BLUE), fmt=f, align=Alignment(horizontal="right")); t.r += 1
    r = t.r; t.rowmap["base_np"] = r
    t.put(f"A{r}", "ฐานกำไรสุทธิกลุ่ม TTM (ลิงก์งบรวม)")
    t.put(f"B{r}", "=" + model.tabs["C"].ref("np_owners", model.ttm_letter, "C"), fnt(False, GREEN), fmt="num"); t.r += 1
    r = t.r; t.rowmap["base_eq"] = r
    t.put(f"A{r}", "ฐานส่วนของผู้ถือหุ้นบริษัทใหญ่ล่าสุด (ลิงก์งบรวม)")
    t.put(f"B{r}", "=" + model.tabs["C"].ref("eq_owners", model.last_q_letter, "C"), fnt(False, GREEN), fmt="num"); t.r += 1
    t.section("ค่าที่คำนวณ (Derived)", 3)
    for rid, lab, f, fm in [("dep", "ค่าเสื่อมราคาต่อปี = (ลงทุน − ที่ดิน) / อายุ", "=(B{capex}-B{land})/B{years}", "num"),
                            ("beddays", "จำนวนวันนอนสูงสุดต่อปี = เตียง × 365", "=B{beds}*365", "int"),
                            ("fixed_all", "ต้นทุนคงที่รวมค่าเสื่อม (ล้านบาท/ปี)", "=B{fixed}+B{dep}", "num")]:
        r = t.r; t.rowmap[rid] = r
        t.put(f"A{r}", lab); t.put(f"B{r}", f.format(**t.rowmap), fmt=fm); t.r += 1
    occ = p.get("occupancy", [0.2, 0.3, 0.4, 0.5, 0.6, 0.7])
    rpb = p.get("rev_per_bed_day", [8000, 10000, 12000, 14000, 16000, 18000])
    R = t.rowmap

    def grid(title, cell_formula, fmt_):
        t.blank(); t.section(title, len(rpb) + 1)
        hr = t.r
        t.put(f"A{hr}", "อัตราครองเตียง ↓ \\ รายได้ต่อวันนอน (บาท) →", fnt(True, "FFFFFF"), NAVY)
        for j, v in enumerate(rpb):
            t.put(f"{num2col(j + 2)}{hr}", v, fnt(True, BLUE), "DDEBF7", "#,##0", Alignment(horizontal="center"))
        t.r += 1
        first = t.r
        for i, o in enumerate(occ):
            rr = t.r
            t.put(f"A{rr}", o, fnt(True, BLUE), "DDEBF7", "0%", Alignment(horizontal="center"))
            for j in range(len(rpb)):
                cl = num2col(j + 2)
                t.put(f"{cl}{rr}", cell_formula(f"$A{rr}", f"{cl}${hr}"), fmt=fmt_, align=Alignment(horizontal="right"))
            t.r += 1
        rng = f"B{first}:{num2col(len(rpb) + 1)}{t.r - 1}"
        ws.conditional_formatting.add(rng, ColorScaleRule(start_type="min", start_color="F8696B", mid_type="percentile",
                                                          mid_value=50, mid_color="FFEB84", end_type="max", end_color="63BE7B"))
        return hr, first

    ebt = lambda o, rp: f"($B${R['beddays']}*{o}*{rp}/1000000*(1-$B${R['vcr']})-$B${R['fixed_all']})"
    np_ = lambda o, rp: f"=IF({ebt(o, rp)}>0,{ebt(o, rp)}*(1-$B${R['tax']}),{ebt(o, rp)})"
    hr1, f1 = grid("ตารางที่ 1: กำไรสุทธิของโครงการต่อปี (ล้านบาท) — ขาดทุนไม่ได้รับเครดิตภาษี", np_, "num")
    t.rowmap["grid1_hdr"], t.rowmap["grid1_first"] = hr1, f1
    roe = lambda o, rp: f"=IFERROR(($B${R['base_np']}+{np_(o, rp)[1:]})/$B${R['base_eq']},\"\")"
    hr2, f2 = grid("ตารางที่ 2: ROE ของกลุ่มหลังรวมโครงการ (%)", roe, "pct")
    t.rowmap["grid2_hdr"], t.rowmap["grid2_first"] = hr2, f2
    t.blank(); t.section("จุดคุ้มทุน (Break-even occupancy ที่ EBT = 0)", len(rpb) + 1)
    r = t.r; t.rowmap["be"] = r
    t.put(f"A{r}", "อัตราครองเตียงคุ้มทุน (%)", fnt(True))
    for j in range(len(rpb)):
        cl = num2col(j + 2)
        t.put(f"{cl}{r}", f"=IFERROR($B${R['fixed_all']}/($B${R['beddays']}*{cl}${hr1}/1000000*(1-$B${R['vcr']})),\"\")", fnt(True), fmt="pct")
    t.r += 1
    model.project_meta = {"occ": occ, "rpb": rpb}
    return t


# =============================================================================
# Valuation tab
# =============================================================================
def build_valuation_tab(model, asm):
    v = asm.get("valuation") or {}
    mk = asm.get("market") or {}
    t = model.sheet("VAL", "ประเมินมูลค่า (Valuation)")
    t.title("ตารางประเมินมูลค่าหุ้น (Valuation Matrix) และการวิเคราะห์ความอ่อนไหว (Sensitivity Analysis)",
            f"ราคาอ้างอิง ณ {mk.get('as_of', '?')} | แหล่งราคา: {mk.get('source', '?')}",
            "ช่องสีน้ำเงิน = สมมติฐานที่แก้ได้ | ทุกมูลค่าคำนวณด้วยสูตร | เหตุผลของสมมติฐานอยู่ในคอลัมน์ C (ถัดจากตัวเลข)", width_a=50)
    ws = t.ws
    for c, w in zip("BCDEFGHIJK", [14, 13, 13, 13, 13, 13, 13, 11, 13, 13]):
        ws.column_dimensions[c].width = w
    C = model.tabs["C"]
    TT, LQ = model.ttm_letter, model.last_q_letter
    notes = v.get("notes", {})

    def row(rid, label, value, fmt_="num", kind="in", note=None, bold=False):
        r = t.r; t.rowmap[rid] = r
        color = BLUE if kind == "in" else (GREEN if kind == "link" else BLACK)
        t.put(f"A{r}", label, fnt(bold))
        is_default = kind == "in" and isinstance(note, str) and note.startswith("DEFAULT")
        t.put(f"B{r}", value, fnt(bold, color), FALLBACK_FILL if is_default else None, fmt_, Alignment(horizontal="right"))
        if note:
            t.put(f"C{r}", note, fnt(False, NOTE_GREY, 8, True))   # overflows into empty D:K
        t.r += 1
        return r

    def dflt(key, default):
        if key in v:
            return v[key], notes.get(key)
        return default, f"DEFAULT — agent ควรกำหนดค่าเองพร้อมเหตุผล (ค่าเริ่มต้น {default})"

    t.section("1) ข้อมูลตลาดและฐานตัวเลข (Market & Base Data)", 5)
    row("price", "ราคาหุ้นอ้างอิง (บาท)", mk.get("price"), "thb", note=mk.get("source"))
    row("shares", "จำนวนหุ้น (ล้านหุ้น)", mk.get("shares_mn"), "num", note=mk.get("shares_note", "หุ้นจดทะเบียนใน SET"))
    R = t.rowmap
    row("mcap", "มูลค่าตลาด (Market Cap, ล้านบาท)", f"=B{R['price']}*B{R['shares']}", "num", "f")
    row("ttm_rev", "รายได้โรงพยาบาล TTM (ล้านบาท)", "=" + C.ref("rev_hosp", TT, "C"), "num", "link")
    row("ttm_np", "กำไรสุทธิบริษัทใหญ่ TTM (ล้านบาท)", "=" + C.ref("np_owners", TT, "C"), "num", "link")
    row("ttm_core", "กำไรปกติ TTM (Core, ล้านบาท)", "=" + C.ref("core_np", TT, "C"), "num", "link")
    row("eps_ttm", "EPS TTM (บาท) = กำไรปกติ TTM / หุ้น", f"=IFERROR(B{R['ttm_core']}/B{R['shares']},\"\")", "eps", "f")
    row("bvps", "มูลค่าทางบัญชีต่อหุ้น BVPS (บาท)", f"=IFERROR({C.ref('eq_owners', LQ, 'C')}/B{R['shares']},\"\")", "eps", "f")
    row("ttm_ebitda", "EBITDA TTM (ล้านบาท)", "=" + C.ref("ebitda", TT, "C"), "num", "link")
    row("ttm_fcf", "FCF TTM (ล้านบาท)", "=" + C.ref("fcf", TT, "C"), "num", "link")
    row("net_cash", "เงินสดสุทธิล่าสุด (Net Cash, ล้านบาท)", "=" + C.ref("net_cash", LQ, "C"), "num", "link")
    row("roe_ttm", "ROE TTM (%)", "=" + C.ref("roe", TT, "C"), "pct", "link")
    row("dps_last", "เงินปันผลต่อหุ้นปีล่าสุด (บาท)", mk.get("dps_last_fy"), "eps", note=mk.get("dps_note"))

    t.section("2) สมมติฐานการประเมินมูลค่า (Assumptions)", 5)
    rf, n = dflt("rf", 0.025); row("rf", "อัตราผลตอบแทนพันธบัตร 10 ปี (Rf)", rf, "pct2", note=n)
    beta, n = dflt("beta", 0.8); row("beta", "Beta", beta, "num", note=n)
    erp, n = dflt("erp", 0.08); row("erp", "ส่วนชดเชยความเสี่ยงตลาด (ERP)", erp, "pct2", note=n)
    row("ke", "ต้นทุนส่วนของผู้ถือหุ้น Ke = Rf + β × ERP", f"=B{R['rf']}+B{R['beta']}*B{R['erp']}", "pct2", "f", bold=True)
    g, n = dflt("g", 0.03); row("g", "อัตราเติบโตระยะยาว (Terminal g)", g, "pct2", note=n)
    po, n = dflt("payout", 0.6); row("payout", "อัตราการจ่ายปันผล (Payout)", po, "pct", note=n)
    fy1 = v.get("forecast", {}).get("fy1", {})
    row("fy1_label", "ปีประมาณการ FY1", fy1.get("label", "FY1E"), "text", note=fy1.get("note"))
    npf = fy1.get("np")
    row("fy1_np", "ประมาณการกำไรปกติ FY1 (ล้านบาท)", npf if npf is not None else f"=B{R['ttm_core']}", "num",
        "in" if npf is not None else "f", note=fy1.get("rationale") or "DEFAULT — ใช้กำไรปกติ TTM (agent ควรใส่ประมาณการพร้อมเหตุผล)")
    row("eps1", "EPS FY1 (บาท)", f"=IFERROR(B{R['fy1_np']}/B{R['shares']},\"\")", "eps", "f")
    row("dps1", "DPS FY1 (บาท) = EPS × Payout", f"=IFERROR(B{R['eps1']}*B{R['payout']},\"\")", "eps", "f")
    row("eps_g", "การเติบโต EPS FY1 เทียบ TTM (%)", f"=IFERROR(B{R['eps1']}/B{R['eps_ttm']}-1,\"\")", "pct", "f")

    # ---------------- valuation matrix ----------------
    t.blank(); t.section("3) ตารางประเมินมูลค่าหุ้น (Valuation Matrix)", 11)
    hr = t.r
    heads = ["วิธีประเมิน (Method)", "ฐานตัวเลข", "สมมติฐาน ต่ำ", "สมมติฐาน กลาง", "สมมติฐาน สูง", "มูลค่า ต่ำ", "มูลค่า กลาง",
             "มูลค่า สูง", "น้ำหนัก", "ถ่วงน้ำหนัก", "Upside (กลาง)"]
    for i, h in enumerate(heads):
        t.put(f"{num2col(i + 1)}{hr}", h, fnt(True, "FFFFFF"), NAVY, align=Alignment(horizontal="center", wrap_text=True))
    ws.row_dimensions[hr].height = 30
    t.r += 1
    methods = [
        ("pe", "P/E × EPS FY1 (เท่า)", f"=B{R['eps1']}", v.get("pe", [12, 15, 18]), "x", "{m}*{b}"),
        ("pbv", "P/BV × BVPS (เท่า)", f"=B{R['bvps']}", v.get("pbv", [1.2, 1.5, 1.8]), "x", "{m}*{b}"),
        ("ev", "EV/EBITDA TTM + เงินสดสุทธิ (เท่า)", f"=B{R['ttm_ebitda']}", v.get("ev_ebitda", [7, 8.5, 10]), "x",
         f"({{m}}*{{b}}+$B${R['net_cash']})/$B${R['shares']}"),
        ("ddm", "DDM (Gordon): DPS FY1 / (Ke − g)  [สมมติฐาน = g]", f"=B{R['dps1']}", v.get("ddm_g", [0.02, 0.03, 0.04]), "pct2",
         f"IF($B${R['ke']}<={{m}},\"n/a\",{{b}}/($B${R['ke']}-{{m}}))"),
        ("dcf", "DCF อย่างง่าย: FCF TTM×(1+g)/(Ke−g) + เงินสดสุทธิ  [สมมติฐาน = g]", f"=B{R['ttm_fcf']}", v.get("dcf_g", [0.02, 0.03, 0.04]),
         "pct2", f"IF($B${R['ke']}<={{m}},\"n/a\",({{b}}*(1+{{m}})/($B${R['ke']}-{{m}})+$B${R['net_cash']})/$B${R['shares']})"),
    ]
    weights = v.get("weights", {"pe": 0.4, "pbv": 0.1, "ev": 0.15, "ddm": 0.2, "dcf": 0.15})
    first = t.r
    for mid, lab, basis, mults, mfmt, ftpl in methods:
        r = t.r; t.rowmap[f"m_{mid}"] = r
        t.put(f"A{r}", lab)
        t.put(f"B{r}", basis, fnt(False, BLACK), fmt="eps" if mid != "ev" and mid != "dcf" else "num", align=Alignment(horizontal="right"))
        for j, mv in enumerate(mults):
            t.put(f"{num2col(3 + j)}{r}", mv, fnt(False, BLUE), fmt=mfmt, align=Alignment(horizontal="right"))
        for j in range(3):
            mcell = f"{num2col(3 + j)}{r}"
            f = ftpl.format(m=mcell, b=f"$B{r}")
            t.put(f"{num2col(6 + j)}{r}", f"=IFERROR({f},\"n/a\")", fmt="thb", align=Alignment(horizontal="right"))
        t.put(f"I{r}", weights.get(mid, 0), fnt(False, BLUE), fmt="0%", align=Alignment(horizontal="right"))
        t.put(f"J{r}", f"=IF(ISNUMBER(G{r}),G{r}*I{r},0)", fmt="thb", align=Alignment(horizontal="right"))
        t.put(f"K{r}", f"=IFERROR(G{r}/$B${R['price']}-1,\"\")", fmt="pct", align=Alignment(horizontal="right"))
        t.r += 1
    last = t.r - 1
    r = t.r; t.rowmap["fair"] = r
    t.put(f"A{r}", "มูลค่าเหมาะสมถ่วงน้ำหนัก (Weighted Fair Value, บาท)", fnt(True), SUBTOTAL)
    for c in "BCDEFGH":
        t.put(f"{c}{r}", None, fill_=SUBTOTAL)
    t.put(f"I{r}", f"=SUM(I{first}:I{last})", fnt(True), SUBTOTAL, "0%")
    t.put(f"J{r}", f"=IFERROR(SUM(J{first}:J{last})/SUMIFW,\"\")".replace("SUMIFW", f"I{r}"), fnt(True), SUBTOTAL, "thb")
    t.put(f"K{r}", f"=IFERROR(J{r}/$B${R['price']}-1,\"\")", fnt(True), SUBTOTAL, "pct")
    t.r += 1
    ws.conditional_formatting.add(f"K{first}:K{r}", CellIsRule(operator="greaterThan", formula=["0.15"], font=Font(color="00B050", bold=True)))
    ws.conditional_formatting.add(f"K{first}:K{r}", CellIsRule(operator="lessThan", formula=["0"], font=Font(color="C00000", bold=True)))
    t.blank()
    row("fair_v", "มูลค่าเหมาะสม (บาท/หุ้น)", f"=J{R['fair']}", "thb", "f", bold=True)
    row("upside", "ส่วนต่างจากราคาปัจจุบัน (Upside / Downside)", f"=IFERROR(B{R['fair_v']}/B{R['price']}-1,\"\")", "pct", "f", bold=True)
    row("mos", "ส่วนเผื่อความปลอดภัย (Margin of Safety = 1 − ราคา/มูลค่า)", f"=IFERROR(1-B{R['price']}/B{R['fair_v']},\"\")", "pct", "f")
    row("pe_ttm", "P/E ปัจจุบัน (TTM core, เท่า)", f"=IFERROR(B{R['price']}/B{R['eps_ttm']},\"\")", "x", "f")
    row("pe_fy1", "P/E ปัจจุบัน (FY1, เท่า)", f"=IFERROR(B{R['price']}/B{R['eps1']},\"\")", "x", "f")
    row("pbv_now", "P/BV ปัจจุบัน (เท่า)", f"=IFERROR(B{R['price']}/B{R['bvps']},\"\")", "x", "f")
    row("ev_now", "EV/EBITDA ปัจจุบัน (เท่า)", f"=IFERROR((B{R['mcap']}-B{R['net_cash']})/B{R['ttm_ebitda']},\"\")", "x", "f")
    row("yield_last", "อัตราผลตอบแทนปันผลย้อนหลัง (Trailing Yield)", f"=IFERROR(B{R['dps_last']}/B{R['price']},\"\")", "pct2", "f")
    row("yield_fy1", "อัตราผลตอบแทนปันผลคาดการณ์ (FY1 Yield)", f"=IFERROR(B{R['dps1']}/B{R['price']},\"\")", "pct2", "f")
    row("verdict", "สรุปสัญญาณ (Signal)",
        f"=IF(B{R['upside']}=\"\",\"n/a\",IF(B{R['upside']}>0.15,\"น่าสะสม (Upside > 15%)\",IF(B{R['upside']}>=0,\"ถือ / เก็งกำไรจำกัด (0–15%)\",\"แพงกว่ามูลค่า (Downside)\")))",
        "text", "f", bold=True)

    # ---------------- sensitivity grids ----------------
    def grid(title, rows_vals, cols_vals, rfmt, cfmt, cell, corner):
        t.blank(); t.section(title, len(cols_vals) + 1)
        hr_ = t.r
        t.put(f"A{hr_}", corner, fnt(True, "FFFFFF"), NAVY)
        for j, cv in enumerate(cols_vals):
            t.put(f"{num2col(j + 2)}{hr_}", cv, fnt(True, BLUE), "DDEBF7", cfmt, Alignment(horizontal="center"))
        t.r += 1
        f0 = t.r
        for rv in rows_vals:
            rr = t.r
            t.put(f"A{rr}", rv, fnt(True, BLUE), "DDEBF7", rfmt, Alignment(horizontal="center"))
            for j in range(len(cols_vals)):
                cl = num2col(j + 2)
                t.put(f"{cl}{rr}", "=" + cell(f"$A{rr}", f"{cl}${hr_}"), fmt="thb", align=Alignment(horizontal="right"))
            t.r += 1
        rng = f"B{f0}:{num2col(len(cols_vals) + 1)}{t.r - 1}"
        price = f"$B${R['price']}"
        ws.conditional_formatting.add(rng, CellIsRule(operator="greaterThanOrEqual", formula=[f"{price}*1.15"], fill=fill("C6EFCE")))
        ws.conditional_formatting.add(rng, CellIsRule(operator="lessThan", formula=[price], fill=fill("FFC7CE")))
        t.text("เขียว = มูลค่า ≥ ราคา +15% | แดง = มูลค่าต่ำกว่าราคาปัจจุบัน", font=fnt(False, NOTE_GREY, 8, True), wrap=False)
        return hr_, f0

    sens = v.get("sensitivity", {})
    pe_rows = sens.get("pe", [10, 12, 14, 16, 18, 20])
    g_cols = sens.get("eps_growth", [-0.10, -0.05, 0.0, 0.05, 0.10, 0.15, 0.20])
    hA, fA = grid("4) Sensitivity A: มูลค่าหุ้นตาม P/E (แถว) × การเติบโต EPS จากฐาน TTM (คอลัมน์)", pe_rows, g_cols, '0.0"x"', "+0%;-0%;0%",
                  lambda rr, cc: f"IFERROR({rr}*$B${R['eps_ttm']}*(1+{cc}),\"\")", "P/E ↓ \\ EPS growth →")
    ke_rows = sens.get("ke", [0.08, 0.09, 0.10, 0.11, 0.12])
    gg_cols = sens.get("g", [0.0, 0.01, 0.02, 0.03, 0.04])
    hB, fB = grid("5) Sensitivity B: มูลค่าตาม DDM — Ke (แถว) × Terminal g (คอลัมน์)", ke_rows, gg_cols, "0.0%", "0.0%",
                  lambda rr, cc: f"IF({rr}<={cc},\"n/a\",$B${R['dps1']}*(1+{cc})/({rr}-{cc}))", "Ke ↓ \\ g →")
    roe_rows = sens.get("roe", [0.08, 0.10, 0.12, 0.14, 0.16])
    hC, fC = grid("6) Sensitivity C: Justified P/BV = (ROE − g)/(Ke − g) → มูลค่า = BVPS × P/BV — ROE (แถว) × Ke (คอลัมน์)",
                  roe_rows, ke_rows, "0.0%", "0.0%",
                  lambda rr, cc: f"IF({cc}<=$B${R['g']},\"n/a\",$B${R['bvps']}*({rr}-$B${R['g']})/({cc}-$B${R['g']}))", "ROE ↓ \\ Ke →")
    model.sens_meta = {"A": (hA, fA, pe_rows, g_cols), "B": (hB, fB, ke_rows, gg_cols), "C": (hC, fC, roe_rows, ke_rows)}
    return t


# =============================================================================
# Cover tab
# =============================================================================
TOC = [
    ("COVER", "หน้าปกและบทสรุปผู้บริหาร: KPI, สาเหตุการเปลี่ยนแปลง Margin/กำไร, สะพานกำไร, ผลตรวจสอบ"),
    ("C", "งบรวมรายไตรมาส: กำไรขาดทุน → ฐานะการเงิน → อัตราส่วน → กระแสเงินสด → กระทบยอด + TTM"),
    ("S", "งบเฉพาะกิจการ (บริษัทแม่) รายไตรมาส ในโครงสร้างเดียวกัน"),
    ("SUB", "บริษัทย่อย = งบรวม − งบเฉพาะกิจการ พร้อมปรับปรุงเงินปันผลระหว่างกัน"),
    ("REV", "โครงสร้างรายได้รายไตรมาส OPD / IPD / ประกันสังคม และการกระทบยอดกับงบ"),
    ("PRJ", "แบบจำลองความอ่อนไหวโครงการขยาย: กำไรโครงการ, ROE กลุ่ม, จุดคุ้มทุน"),
    ("A", "งบรวมรายปี (6 ปีที่มีงบ ปรับได้ด้วย annual_years) + งวดสะสมระหว่างปีเทียบปีก่อน"),
    ("AREV", "โครงสร้างรายได้รายปี"),
    ("NAT", "ค่าใช้จ่ายตามลักษณะ (พนักงาน แพทย์ ยา ค่าเสื่อม ส่งต่อ)"),
    ("VAL", "ตารางประเมินมูลค่า 5 วิธี + Sensitivity 3 ตาราง"),
]


def build_cover(model, asm, fin, meta):
    t = model.tabs["COVER"]
    ws = t.ws
    for c, w in zip("ABCD", [50, 18, 18, 70]):
        ws.column_dimensions[c].width = w
    C, V = model.tabs["C"], model.tabs["VAL"]
    TT, LQ = model.ttm_letter, model.last_q_letter
    comp = asm.get("company", {})
    t.put("A1", f"{comp.get('name_en', meta['ticker'])} (SET: {meta['ticker']})", fnt(True, SECTION_TXT, 16))
    ws.merge_cells("A1:D1")
    t.put("A2", f"{comp.get('name_th', '')} | Master Financial Model & Executive Summary | "
                f"รายไตรมาส {meta['q_first']}–{meta['q_last']} ({meta['nq']} ไตรมาส) และรายปี {meta['y_first']}–{meta['y_last']}",
          fnt(True, "595959", 11))
    ws.merge_cells("A2:D2")
    t.put("A3", f"กลุ่มโรงพยาบาล: {meta['category']} | ข้อมูลงบถึง {meta['q_last']} | จัดทำ {meta['generated']} | ไฟล์ {meta['file']}",
          fnt(False, NOTE_GREY, 9, True))
    ws.merge_cells("A3:D3")
    t.r = 5

    def sec(txt):
        t.section(txt, 4)

    def hdr(*cols):
        r = t.r
        for i, h in enumerate(cols):
            t.put(f"{num2col(i + 1)}{r}", h, fnt(True, "FFFFFF"), NAVY)
        t.r += 1

    sec("EXECUTIVE SUMMARY KPIs (ตัวชี้วัดหลัก)")
    hdr("ตัวชี้วัด", "ค่า", "", "ความหมาย / ที่มา")
    R = V.rowmap
    kpis = [
        ("มูลค่าตลาด (Market Cap, ล้านบาท)", f"={qs(V.name)}!B{R['mcap']}", "num", "ราคา × จำนวนหุ้น (ชีตประเมินมูลค่า)"),
        ("รายได้โรงพยาบาล TTM (ล้านบาท)", "=" + C.ref("rev_hosp", TT, "C"), "num", "ผลรวม 4 ไตรมาสล่าสุด"),
        (f"อัตรากำไรขั้นต้นไตรมาสล่าสุด ({meta['q_last']})", "=" + C.ref("gpm", LQ, "C"), "pct", "กำไรขั้นต้น / รายได้โรงพยาบาล"),
        (f"อัตรากำไรสุทธิไตรมาสล่าสุด ({meta['q_last']})", "=" + C.ref("npm", LQ, "C"), "pct", "กำไรสุทธิ / รายได้รวม"),
        ("EBITDA Margin TTM", "=" + C.ref("ebitda_m", TT, "C"), "pct", "EBITDA / รายได้รวม"),
        ("เงินสดสุทธิ (Net Cash, ล้านบาท)", "=" + C.ref("net_cash", LQ, "C"), "num", "เงินสด+เงินลงทุนระยะสั้น − หนี้ − หนี้สินสัญญาเช่า"),
        ("ROE TTM", "=" + C.ref("roe", TT, "C"), "pct", "กำไรสุทธิบริษัทใหญ่ TTM / ส่วนของผู้ถือหุ้นล่าสุด"),
        ("ROIC TTM", "=" + C.ref("roic", TT, "C"), "pct", "EBIT หลังภาษี / เงินทุนดำเนินงาน"),
        ("P/E TTM (เท่า)", f"={qs(V.name)}!B{R['pe_ttm']}", "x", "ราคา / EPS กำไรปกติ TTM"),
        ("P/BV (เท่า)", f"={qs(V.name)}!B{R['pbv_now']}", "x", "ราคา / BVPS"),
        ("อัตราผลตอบแทนปันผลย้อนหลัง", f"={qs(V.name)}!B{R['yield_last']}", "pct2", "DPS ปีล่าสุด / ราคา"),
        ("มูลค่าเหมาะสมถ่วงน้ำหนัก (บาท)", f"={qs(V.name)}!B{R['fair_v']}", "thb", "ถ่วงน้ำหนัก 5 วิธี (ชีตประเมินมูลค่า)"),
        ("Upside / Downside", f"={qs(V.name)}!B{R['upside']}", "pct", "มูลค่าเหมาะสม / ราคา − 1"),
        ("สัญญาณ", f"={qs(V.name)}!B{R['verdict']}", "text", "เกณฑ์: >15% น่าสะสม, 0–15% ถือ, <0% แพง"),
    ]
    model.cover_kpi_rows = []
    for lab, f, fm, note in kpis:
        r = t.r
        t.put(f"A{r}", lab, fnt(True))
        t.put(f"B{r}", f, fnt(True, GREEN), fmt=fm, align=Alignment(horizontal="right"))
        t.put(f"D{r}", note, fnt(False, NOTE_GREY, 9, True))
        model.cover_kpi_rows.append((lab, f"B{r}", fm))
        t.r += 1

    t.blank()
    sec("1) บทสรุปผู้บริหาร (Executive Summary — สาเหตุการเปลี่ยนแปลงของ Margin และกำไร)")
    es = dict(asm.get("executive_summary") or {})
    if isinstance(es.get("valuation_view"), list):       # tolerate a list of sentences
        es["valuation_view"] = " ".join(es["valuation_view"])
    if not es:
        t.text("⚠ ยังไม่ได้เขียนบทสรุปเชิงคุณภาพ — agent ต้องเติม executive_summary ใน assumptions.json แล้ว build ใหม่",
               font=fnt(True, "C00000"), merge_to="D")
    else:
        t.text(es.get("headline", ""), font=fnt(True, SECTION_TXT, 12), merge_to="D", height=36)
        for key, lab in [("margin_drivers", "ปัจจัยที่ทำให้ Margin เปลี่ยน"), ("profit_drivers", "ปัจจัยที่ทำให้กำไรเปลี่ยน"),
                         ("segment_notes", "บริษัทแม่ vs บริษัทย่อย / โครงสร้างรายได้"), ("balance_sheet", "ฐานะการเงินและกระแสเงินสด"),
                         ("risks", "ความเสี่ยงที่ต้องติดตาม"), ("catalysts", "ปัจจัยบวก / สิ่งที่ต้องติดตาม")]:
            items = es.get(key) or []
            if not items:
                continue
            t.text(lab, font=fnt(True, BLACK, 10), fill_=SECTION, merge_to="D")
            for it in items:
                t.text("• " + it, merge_to="D", height=max(18, 15 * (1 + len(it) // 120)))
        if es.get("valuation_view"):
            t.text("มุมมองด้านมูลค่า", font=fnt(True, BLACK, 10), fill_=SECTION, merge_to="D")
            t.text(es["valuation_view"], merge_to="D", height=max(30, 15 * (1 + len(es["valuation_view"]) // 120)))

    # ---- profit bridge
    t.blank()
    sec("2) สะพานกำไร (Profit Bridge) — อธิบายการเปลี่ยนแปลงกำไรสุทธิบริษัทใหญ่ด้วยตัวเลข")
    cq = [c for c in C.cols if c.kind == "q"]
    last = cq[-1]
    py, pp = last.py, last.pp
    hdr("รายการ (ล้านบาท)", f"YoY vs {th_q(cq[-5].per) if len(cq) >= 5 else '-'}", f"QoQ vs {th_q(cq[-2].per)}", "คำอธิบาย")
    x = lambda rid, col: f"{qs(C.name)}!{col}{C.rowmap[rid]}"

    def bridge(fn):
        return [fn(py), fn(pp)]
    items = [
        ("กำไรสุทธิบริษัทใหญ่ งวดเปรียบเทียบ", lambda b: f"={x('np_owners', b)}", "ฐานเริ่มต้น"),
        ("ผลจากรายได้ (Volume effect = ΔRevenue × GPM เดิม)",
         lambda b: f"=({x('rev_hosp', last.letter)}-{x('rev_hosp', b)})*{x('gpm', b)}", "รายได้โตขึ้นที่ margin เดิม"),
        ("ผลจาก Margin (Margin effect = ΔGPM × Revenue ใหม่)",
         lambda b: f"=({x('gpm', last.letter)}-{x('gpm', b)})*{x('rev_hosp', last.letter)}", "ประสิทธิภาพต้นทุน/ส่วนผสมรายได้/ราคา"),
        ("รายได้อื่นและเงินปันผล (Δ)", lambda b: f"=({x('div_inc', last.letter)}+{x('oth_inc', last.letter)})-({x('div_inc', b)}+{x('oth_inc', b)})", ""),
        ("ค่าใช้จ่าย SG&A (Δ, ลบ = ใช้จ่ายเพิ่ม)", lambda b: f"=-({x('sga', last.letter)}-{x('sga', b)})", ""),
        ("ส่วนแบ่งกำไร/รายได้-ต้นทุนทางการเงิน (Δ)", lambda b: f"=({x('assoc', last.letter)}-{x('assoc', b)})+({x('fin_inc', last.letter)}-{x('fin_inc', b)})-({x('fin', last.letter)}-{x('fin', b)})", ""),
        ("ภาษีเงินได้ (Δ, ลบ = ภาษีเพิ่ม)", lambda b: f"=-({x('tax', last.letter)}-{x('tax', b)})", ""),
        ("ส่วนได้เสียที่ไม่มีอำนาจควบคุม (Δ)", lambda b: f"=-({x('nci', last.letter)}-{x('nci', b)})", ""),
    ]
    first = t.r
    for lab, fn, note in items:
        r = t.r
        t.put(f"A{r}", lab, fnt(r == first))
        for j, b in enumerate([py, pp]):
            t.put(f"{'BC'[j]}{r}", fn(b) if b else None, fnt(r == first, GREEN if r == first else BLACK), fmt="num",
                  align=Alignment(horizontal="right"))
        t.put(f"D{r}", note, fnt(False, NOTE_GREY, 9, True))
        t.r += 1
    r = t.r; t.rowmap["bridge_end"] = r
    t.put(f"A{r}", f"กำไรสุทธิบริษัทใหญ่ {th_q(last.per)} (ผลรวมสะพาน)", fnt(True), SUBTOTAL)
    for j in range(2):
        cl = "BC"[j]
        t.put(f"{cl}{r}", f"=SUM({cl}{first}:{cl}{r - 1})", fnt(True), SUBTOTAL, "num", Alignment(horizontal="right"))
    t.put(f"D{r}", None, fill_=SUBTOTAL)
    t.r += 1
    r = t.r
    t.put(f"A{r}", "ตรวจสอบ: ผลรวมสะพาน − กำไรจริง = 0.00", fnt(True), CHECK_FILL)
    for j in range(2):
        cl = "BC"[j]
        t.put(f"{cl}{r}", f"=ROUND({cl}{r - 1}-{x('np_owners', last.letter)},2)", fnt(True), CHECK_FILL, "check", Alignment(horizontal="right"))
    model.bridge_rows = (first, r)
    t.r += 1

    # ---- TOC
    t.blank()
    sec("สารบัญและการนำทาง (Table of Contents & Navigation)")
    hdr("ชื่อชีต (Tab)", "", "", "คำอธิบาย / ลิงก์")
    for k, desc in TOC:
        tab = model.tabs.get(k)
        if not tab:
            continue
        r = t.r
        c = t.put(f"A{r}", tab.name, fnt(True, "0563C1"))
        c.hyperlink = f"#{qs(tab.name)}!A1"
        t.put(f"D{r}", desc + "  → ไปยังชีต", fnt(False, BLACK, 9))
        ws.cell(row=r, column=4).hyperlink = f"#{qs(tab.name)}!A1"
        t.r += 1

    # ---- checks
    t.blank()
    sec("การตรวจสอบความถูกต้องของแบบจำลอง (Integrity Checks)")
    hdr("การตรวจสอบ", "ผล", "", "เกณฑ์")
    checks = []
    for tk, rid, lab in [("C", "bal_check", "งบรวม: สมการงบดุล A = L + E ทุกไตรมาส"), ("S", "bal_check", "งบเฉพาะกิจการ: สมการงบดุล"),
                         ("A", "bal_check", "งบรวมรายปี: สมการงบดุล"), ("C", "chk_ebit", "งบรวม: EBIT ตรงกับกำไรจากการดำเนินงานในงบ"),
                         ("C", "chk_np", "งบรวม: กำไรสุทธิตรงกับงบ"), ("S", "chk_np", "งบเฉพาะกิจการ: กำไรสุทธิตรงกับงบ"),
                         ("A", "chk_np", "รายปี: กำไรสุทธิตรงกับงบ")]:
        tab = model.tabs[tk]
        qc = [c for c in tab.cols if c.kind != "ttm"]
        rng = f"{qs(tab.name)}!{qc[0].letter}{tab.rowmap[rid]}:{qc[-1].letter}{tab.rowmap[rid]}"
        checks.append((lab, f"=IF(SUMSQ({rng})<0.0001,\"✅ PASS\",\"❌ FAIL\")", "ทุกงวดต้อง = 0.00 (n/a = ข้อมูลไม่ครบ ไม่นับ)"))
    for tk in ("REV", "AREV"):
        tab = model.tabs.get(tk)
        if tab and "chk" in tab.rowmap:
            qc = [c for c in tab.cols if c.kind != "ttm"]
            rng = f"{qs(tab.name)}!{qc[0].letter}{tab.rowmap['chk']}:{qc[-1].letter}{tab.rowmap['chk']}"
            checks.append((f"{tab.name}: Mix รวมเท่ากับรายได้ในงบ (±1 ล้านบาท)",
                           f"=IF(AND(MAX({rng})<=1,MIN({rng})>=-1),\"✅ PASS\",\"❌ FAIL\")", "|ผลต่าง| ≤ 1 ล้านบาท"))
    checks.append(("สะพานกำไรปิดยอด", f"=IF(SUMSQ(B{r}:C{r})<0.0001,\"✅ PASS\",\"❌ FAIL\")", "= 0.00"))
    model.cover_checks = []
    for lab, f, crit in checks:
        rr = t.r
        t.put(f"A{rr}", lab)
        t.put(f"B{rr}", f, fnt(True), align=Alignment(horizontal="center"))
        t.put(f"D{rr}", crit, fnt(False, NOTE_GREY, 9, True))
        model.cover_checks.append((lab, f"B{rr}"))
        t.r += 1

    # ---- legend + provenance
    t.blank()
    sec("สัญลักษณ์สีและแหล่งข้อมูล (Colour Legend & Data Provenance)")
    for txt, color, fl in [("ตัวเลขสีน้ำเงิน = ข้อมูลนำเข้า (จากงบการเงิน/MD&A/สมมติฐาน)", BLUE, None),
                           ("ตัวเลขสีดำ = สูตรคำนวณภายในชีต", BLACK, None), ("ตัวเลขสีเขียว = ลิงก์ข้ามชีต", GREEN, None),
                           ("พื้นเหลือง = ข้อมูลสำรองจาก Jitta / ป้อนเอง (Manual) หรือค่าเริ่มต้นที่ยังไม่ได้ยืนยัน", BLACK, FALLBACK_FILL),
                           ("พื้นส้มอ่อน = แถวตรวจสอบ (ต้องเป็น 0.00)", BLACK, CHECK_FILL),
                           ("พื้นเขียวอ่อน = ยอดรวมย่อย / ตัวเลขสำคัญ", BLACK, SUBTOTAL)]:
        t.text(txt, font=fnt(False, color), fill_=fl, merge_to="D", wrap=False)
    t.text("ไฟล์ต้นทาง: " + " | ".join(os.path.basename(s) for s in fin.get("source_files", [])), font=fnt(False, NOTE_GREY, 9, True), merge_to="D")
    t.text(f"ข้อมูลงบการเงินที่สกัดได้ {len(fin['facts'])} รายการ | ข้อสังเกตจากการสกัด {len(fin.get('flags', []))} รายการ "
           f"| ช่องที่ขาดข้อมูลใน {meta['nq']} ไตรมาสล่าสุด: {meta['gaps']}", font=fnt(False, NOTE_GREY, 9, True), merge_to="D")
    ws.freeze_panes = "A5"
    return t


# =============================================================================
# Markdown companion
# =============================================================================
def fmt_md(v, f):
    if isinstance(v, XLError):
        return v.code
    if v is None or v == "":
        return "–"
    if isinstance(v, str):
        return v
    if isinstance(v, bool):
        return str(v)
    if f in ("pct",):
        return f"{v * 100:.1f}%"
    if f == "pct2":
        return f"{v * 100:.2f}%"
    if f == "x":
        return f"{v:.2f}x"
    if f == "eps":
        return f"{v:.3f}"
    if f in ("days", "int"):
        return f"{v:,.0f}"
    if f == "check":
        return f"{v:.2f}"
    if abs(v) < 0.005:
        return "0.00" if f != "num" else "-"
    return f"{v:,.2f}"


def md_tab_table(model, calc, key, row_ids=None, split=7, skip_styles=()):
    t = model.tabs[key]
    out = []
    cols = t.cols
    qcols = [c for c in cols if c.kind == "q"]
    other = [c for c in cols if c.kind != "q"]
    chunks = [qcols[i:i + split] for i in range(0, len(qcols), split)] if len(qcols) > split + 1 else [qcols]
    if other:
        chunks[-1] = chunks[-1] + other
    for ch in chunks:
        if len(chunks) > 1:
            out.append(f"\n**{t.name} — {ch[0].label} ถึง {ch[-1].label}**\n")
        out.append("| รายการ (ล้านบาท) | " + " | ".join(c.label for c in ch) + " |")
        out.append("| :--- | " + " | ".join("---:" for _ in ch) + " |")
        for rid, r, spec in t.rows:
            if row_ids and rid not in row_ids:
                continue
            if spec.get("style") in skip_styles:
                continue
            vals = [fmt_md(calc.get(t.name, f"{c.letter}{r}"), spec.get("fmt", "num")) for c in ch]
            if all(v == "–" for v in vals):
                continue
            lab = ("&nbsp;&nbsp;" * spec.get("lvl", 0)) + spec["label"]
            if spec.get("style") in ("sub", "total", "check"):
                lab = f"**{lab}**"
                vals = [f"**{v}**" if v != "–" else v for v in vals]
            out.append(f"| {lab} | " + " | ".join(vals) + " |")
    return "\n".join(out)


def md_grid(model, calc, sheet_key, hdr_row, first_row, rows_vals, cols_vals, rfmt, cfmt, cellfmt, corner):
    t = model.tabs[sheet_key]
    out = [f"| {corner} | " + " | ".join(fmt_md(c, cfmt) for c in cols_vals) + " |",
           "| :---: | " + " | ".join("---:" for _ in cols_vals) + " |"]
    for i, rv in enumerate(rows_vals):
        r = first_row + i
        vals = [fmt_md(calc.get(t.name, f"{num2col(j + 2)}{r}"), cellfmt) for j in range(len(cols_vals))]
        out.append(f"| **{fmt_md(rv, rfmt)}** | " + " | ".join(vals) + " |")
    return "\n".join(out)


def build_markdown(model, calc, asm, fin, meta, path):
    V = model.tabs["VAL"]
    cov = model.tabs["COVER"]
    es = dict(asm.get("executive_summary") or {})
    if isinstance(es.get("valuation_view"), list):
        es["valuation_view"] = " ".join(es["valuation_view"])
    comp = asm.get("company", {})
    L = []
    L.append(f"# {comp.get('name_th', meta['ticker'])} ({meta['ticker']}) — Master Financial Model & Executive Summary")
    L.append(f"**{comp.get('name_en', '')} | SET: {meta['ticker']} | กลุ่ม: {meta['category']}**\n")
    L.append(f"* ไฟล์ Excel คู่กัน: `{meta['file']}` (10 ชีต, สูตรคำนวณสด)")
    L.append(f"* ช่วงข้อมูล: รายไตรมาส {meta['q_first']}–{meta['q_last']} | รายปี {meta['y_first']}–{meta['y_last']} + งวดสะสมล่าสุด")
    L.append(f"* จัดทำ: {meta['generated']} | หน่วย: ล้านบาท ยกเว้นที่ระบุ\n")
    L.append("---\n")
    # ---------------- 1 Executive summary
    L.append("## 1. บทสรุปผู้บริหาร (Executive Summary)\n")
    if es.get("headline"):
        L.append(f"> **{es['headline']}**\n")
    L.append("### ตัวชี้วัดหลัก (KPIs)\n")
    L.append("| ตัวชี้วัด | ค่า |\n| :--- | ---: |")
    for lab, addr, fm in model.cover_kpi_rows:
        L.append(f"| {lab} | {fmt_md(calc.get(cov.name, addr), fm)} |")
    L.append("")
    for key, lab in [("margin_drivers", "สาเหตุการเปลี่ยนแปลงของ Margin"), ("profit_drivers", "สาเหตุการเปลี่ยนแปลงของกำไร"),
                     ("segment_notes", "บริษัทแม่ vs บริษัทย่อย / โครงสร้างรายได้"), ("balance_sheet", "ฐานะการเงินและกระแสเงินสด"),
                     ("risks", "ความเสี่ยงที่ต้องติดตาม"), ("catalysts", "ปัจจัยบวก / สิ่งที่ต้องติดตาม")]:
        if es.get(key):
            L.append(f"### {lab}\n")
            L += [f"- {x}" for x in es[key]]
            L.append("")
    if not es:
        L.append("> ⚠ ยังไม่มีบทสรุปเชิงคุณภาพ (executive_summary ว่าง)\n")
    b0, b1 = model.bridge_rows
    L.append("### สะพานกำไร (Profit Bridge)\n")
    L.append(f"| รายการ (ล้านบาท) | {cov.ws['B' + str(b0 - 1)].value} | {cov.ws['C' + str(b0 - 1)].value} |\n| :--- | ---: | ---: |")
    for r in range(b0, b1 + 1):
        lab = cov.ws[f"A{r}"].value
        L.append(f"| {lab} | {fmt_md(calc.get(cov.name, f'B{r}'), 'num')} | {fmt_md(calc.get(cov.name, f'C{r}'), 'num')} |")
    if es.get("valuation_view"):
        L.append(f"\n### มุมมองด้านมูลค่า\n\n{es['valuation_view']}\n")
    L.append("\n---\n")
    # ---------------- 2 Financial tables
    L.append("## 2. โครงสร้างตารางทางการเงินตามลำดับชั้น (Hierarchical Financial Statements)\n")
    L.append("### 2.1 งบรวมรายไตรมาส (Consolidated)\n")
    L.append(md_tab_table(model, calc, "C"))
    L.append("\n### 2.2 งบเฉพาะกิจการ vs บริษัทย่อย (Parent vs Subsidiaries)\n")
    keep = ["rev_hosp", "gp", "gpm", "div_inc", "ebit", "np", "npm", "total_assets", "total_equity", "bal_check", "chk_np"]
    L.append("**งบเฉพาะกิจการ (Separate)**\n")
    L.append(md_tab_table(model, calc, "S", keep))
    L.append("\n**บริษัทย่อย + รายการตัดบัญชี (Consolidated − Separate) และการปรับปรุงเงินปันผล**\n")
    L.append(md_tab_table(model, calc, "SUB", ["rev_hosp", "gp", "gpm", "np", "sep_div_sub", "sep_np_adj", "sub_np_adj",
                                               "sub_np_share", "sub_rev_share", "sub_npm_adj", "sep_npm_adj"]))
    L.append("\n### 2.3 โครงสร้างรายได้รายไตรมาส (Revenue Mix)\n")
    L.append(md_tab_table(model, calc, "REV"))
    L.append("\n### 2.4 งบรวมรายปี (Annual Consolidated)\n")
    L.append(md_tab_table(model, calc, "A", split=99))
    L.append("\n### 2.5 โครงสร้างรายได้รายปี\n")
    L.append(md_tab_table(model, calc, "AREV", split=99))
    L.append("\n### 2.6 ค่าใช้จ่ายตามลักษณะ (Expenses by Nature)\n")
    L.append(md_tab_table(model, calc, "NAT", split=99))
    L.append("\n---\n")
    # ---------------- 3 Valuation
    L.append("## 3. ตารางประเมินมูลค่าหุ้น (Valuation Matrix) และ Sensitivity Analysis\n")
    R = V.rowmap
    L.append("### 3.1 ฐานตัวเลขและสมมติฐาน\n")
    L.append("| รายการ | ค่า | หมายเหตุ |\n| :--- | ---: | :--- |")
    for rid, fm in [("price", "thb"), ("shares", "num"), ("mcap", "num"), ("ttm_np", "num"), ("ttm_core", "num"), ("eps_ttm", "eps"),
                    ("bvps", "eps"), ("ttm_ebitda", "num"), ("ttm_fcf", "num"), ("net_cash", "num"), ("roe_ttm", "pct"),
                    ("dps_last", "eps"), ("rf", "pct2"), ("beta", "num"), ("erp", "pct2"), ("ke", "pct2"), ("g", "pct2"),
                    ("payout", "pct"), ("fy1_np", "num"), ("eps1", "eps"), ("dps1", "eps"), ("eps_g", "pct")]:
        r = R[rid]
        note = V.ws[f"C{r}"].value or ""
        L.append(f"| {V.ws[f'A{r}'].value} | {fmt_md(calc.get(V.name, f'B{r}'), fm)} | {note} |")
    L.append("\n### 3.2 Valuation Matrix\n")
    L.append("| วิธี | ฐาน | สมมติฐาน (ต่ำ/กลาง/สูง) | มูลค่า ต่ำ | มูลค่า กลาง | มูลค่า สูง | น้ำหนัก | Upside (กลาง) |")
    L.append("| :--- | ---: | :---: | ---: | ---: | ---: | ---: | ---: |")
    for mid, mf in [("pe", "x"), ("pbv", "x"), ("ev", "x"), ("ddm", "pct2"), ("dcf", "pct2")]:
        r = R[f"m_{mid}"]
        g_ = lambda c, f="thb": fmt_md(calc.get(V.name, f"{c}{r}"), f)
        L.append(f"| {V.ws[f'A{r}'].value} | {g_('B', 'num')} | {g_('C', mf)} / {g_('D', mf)} / {g_('E', mf)} | {g_('F')} | **{g_('G')}** | "
                 f"{g_('H')} | {fmt_md(calc.get(V.name, f'I{r}'), 'pct')} | {g_('K', 'pct')} |")
    fr = R["fair"]
    L.append(f"| **มูลค่าเหมาะสมถ่วงน้ำหนัก** | | | | **{fmt_md(calc.get(V.name, 'J%d' % fr), 'thb')}** | | "
             f"{fmt_md(calc.get(V.name, 'I%d' % fr), 'pct')} | **{fmt_md(calc.get(V.name, 'K%d' % fr), 'pct')}** |")
    L.append("")
    L.append("| ตัวชี้วัดราคา | ค่า |\n| :--- | ---: |")
    for rid, fm in [("fair_v", "thb"), ("upside", "pct"), ("mos", "pct"), ("pe_ttm", "x"), ("pe_fy1", "x"), ("pbv_now", "x"),
                    ("ev_now", "x"), ("yield_last", "pct2"), ("yield_fy1", "pct2"), ("verdict", "text")]:
        L.append(f"| {V.ws[f'A{R[rid]}'].value} | {fmt_md(calc.get(V.name, f'B{R[rid]}'), fm)} |")
    sm = model.sens_meta
    hA, fA, a_r, a_c = sm["A"]
    price_txt = fmt_md(calc.get(V.name, "B%d" % R["price"]), "thb")
    L.append(f"\n### 3.3 Sensitivity A — มูลค่าหุ้น (บาท) ตาม P/E × การเติบโต EPS (ราคาปัจจุบัน {price_txt})\n")
    L.append(md_grid(model, calc, "VAL", hA, fA, a_r, a_c, "x", "pct", "thb", "P/E \\ EPS growth"))
    hB, fB, b_r, b_c = sm["B"]
    L.append("\n### 3.4 Sensitivity B — DDM มูลค่า (บาท): Ke × g\n")
    L.append(md_grid(model, calc, "VAL", hB, fB, b_r, b_c, "pct", "pct", "thb", "Ke \\ g"))
    hC, fC, c_r, c_c = sm["C"]
    L.append("\n### 3.5 Sensitivity C — Justified P/BV มูลค่า (บาท): ROE × Ke\n")
    L.append(md_grid(model, calc, "VAL", hC, fC, c_r, c_c, "pct", "pct", "thb", "ROE \\ Ke"))
    P = model.tabs.get("PRJ")
    if P is not None and "grid1_first" in P.rowmap:
        pm = model.project_meta
        pj = asm.get("project", {})
        L.append(f"\n### 3.6 Project Sensitivity — {pj.get('name', '')}\n")
        L.append(f"สมมติฐาน: {pj.get('beds')} เตียง, ลงทุน {pj.get('capex'):,} ล้านบาท (ที่ดิน {pj.get('land_value', 0):,}), "
                 f"ค่าเสื่อม {pj.get('dep_years')} ปี, Fixed OPEX {pj.get('fixed_opex')} ล้านบาท/ปี, "
                 f"ต้นทุนผันแปร {pj.get('variable_cost_ratio', 0) * 100:.0f}% ของรายได้ | ที่มา: {pj.get('source', '-')}\n")
        L.append("**กำไรสุทธิโครงการต่อปี (ล้านบาท)**\n")
        L.append(md_grid(model, calc, "PRJ", P.rowmap["grid1_hdr"], P.rowmap["grid1_first"], pm["occ"], pm["rpb"], "pct", "int", "num",
                         "Occupancy \\ บาท/วันนอน"))
        L.append("\n**ROE กลุ่มหลังรวมโครงการ**\n")
        L.append(md_grid(model, calc, "PRJ", P.rowmap["grid2_hdr"], P.rowmap["grid2_first"], pm["occ"], pm["rpb"], "pct", "int", "pct",
                         "Occupancy \\ บาท/วันนอน"))
        be = P.rowmap["be"]
        L.append("\n| บาท/วันนอน | " + " | ".join(f"{x:,}" for x in pm["rpb"]) + " |\n| :--- | " + " | ".join("---:" for _ in pm["rpb"]) + " |")
        L.append("| **Occupancy คุ้มทุน** | " + " | ".join(fmt_md(calc.get(P.name, f"{num2col(j + 2)}{be}"), "pct") for j in range(len(pm["rpb"]))) + " |")
    L.append("\n---\n")
    # ---------------- 4 QA
    L.append("## 4. การตรวจสอบคุณภาพแบบจำลองและแหล่งข้อมูล (QA & Provenance)\n")
    L.append("| การตรวจสอบ | ผล |\n| :--- | :---: |")
    for lab, addr in model.cover_checks:
        L.append(f"| {lab} | {fmt_md(calc.get(cov.name, addr), 'text')} |")
    L.append("")
    L.append(f"- ไฟล์ต้นทาง: {', '.join('`' + os.path.basename(s) + '`' for s in fin.get('source_files', []))}")
    L.append("- ตัวเลขทุกช่องมาจากงบการเงินที่ยื่นต่อ SET/ก.ล.ต. (สีน้ำเงิน); Q4 = งบทั้งปี − งบ 9 เดือน; กระแสเงินสดรายไตรมาส = ผลต่างงบสะสม")
    L.append("- ช่องพื้นเหลือง = ข้อมูลสำรองจาก Jitta หรือป้อนเอง (Manual) — ตรวจสอบกับเอกสารต้นฉบับก่อนใช้ตัดสินใจ")
    L.append(f"- ช่องว่างข้อมูลในไตรมาสที่แสดง: {meta['gaps']}")
    if fin.get("flags"):
        L.append("- ข้อสังเกตจากการสกัดข้อมูล (อาจเป็นการปรับปรุงงบย้อนหลัง):")
        L += [f"  - {f}" for f in fin["flags"][:15]]
    if meta.get("warnings"):
        L.append("- ⚠ คำเตือนจากการสร้างแบบจำลอง:")
        L += [f"  - {w}" for w in meta["warnings"]]
    open(path, "w", encoding="utf-8").write("\n".join(L) + "\n")


# =============================================================================
# Orchestration
# =============================================================================
CATEGORY = {1: "Category 1: Foreigner & Medical Tourism (Non-SSO)", 2: "Category 2: Social Security (SSO) Powerhouse",
            3: "Category 3: Thai Cash & Private Insurance (Non-SSO)", 4: "Category 4: Aesthetics & Elective Surgery (Non-SSO)",
            5: "Category 5: Specialized Biotech & Fertility (Non-SSO)"}


# Default customer-segment category per ticker (references/hospital_taxonomy.md); unknown -> 3
HOSPITAL_CATEGORY = {t: 1 for t in ("BH", "BDMS", "WPH", "PR9")}
HOSPITAL_CATEGORY.update({t: 2 for t in ("BCH", "CHG", "RJH", "SKR", "LPH", "VIH", "PHG")})
HOSPITAL_CATEGORY.update({t: 3 for t in ("NTV", "RPH", "RAM", "THG", "AHC", "CMR", "PRINC", "EKH", "KDH", "M-CHAI", "NEW", "NKT", "VIBHA")})
HOSPITAL_CATEGORY.update({t: 4 for t in ("MASTER", "KLINIQ", "TRP")})
HOSPITAL_CATEGORY.update({t: 5 for t in ("SAFE", "MEDEZE", "BKGI")})


def next_version(outdir, ticker, force=None):
    os.makedirs(outdir, exist_ok=True)
    if force:
        return int(force)
    vs = [int(m.group(1)) for f in os.listdir(outdir) for m in [re.match(rf"{ticker}_finance_model_v(\d+)\.(xlsx|md)$", f)] if m]
    return max(vs, default=0) + 1


def build(fin, asm, outdir, nq=14, version=None):
    ticker = fin["ticker"]
    facts = Facts(fin, asm)
    cat = int(asm.get("category", 3))
    has_sso = cat == 2 or bool(asm.get("has_sso"))
    warnings = []
    # ---------------- columns
    allq = [q for q in fin["quarters"] if facts.get("C", "rev_hosp", q)[0] is not None]
    quarters = allq[-nq:]
    qcols = []
    for i, q in enumerate(quarters):
        L = num2col(i + 2)
        qcols.append(Col(L, q, th_q(q), 4, "q", py=num2col(i - 2) if i >= 4 else None, pp=num2col(i + 1) if i >= 1 else None))
    ttm_letter = num2col(len(quarters) + 2)
    qcols_ttm = qcols + [Col(ttm_letter, "TTM", "TTM", 1, "ttm")]
    ly, lqn = int(quarters[-1][:4]), int(quarters[-1][-1])
    # annual columns: every fiscal year with a filed statement (annual FS or a later year's comparative column), up to
    # asm["annual_years"] (default 6); a year known only from Jitta is shown only inside the last 5. Years stay
    # consecutive, because each column's YoY formula points at the column to its left.
    n_ann = int(asm.get("annual_years", 6))
    last_fy = ly if lqn == 4 else ly - 1
    have = {y for y in fin["years"] if facts.get("C", "np_owners", f"FY{y}")[0] is not None and y <= last_fy}
    filed = {y for y in have if "jitta" not in str(facts.get("C", "np_owners", f"FY{y}")[1] or "").lower()}
    top = max(have) if have else last_fy
    fys = []
    y = top
    while y in have and len(fys) < n_ann and (y in filed or y > top - 5):
        fys.insert(0, y)
        y -= 1
    acols = []
    for i, y in enumerate(fys):
        acols.append(Col(num2col(i + 2), f"FY{y}", f"ปี {y + 543}", 1, "q", py=num2col(i + 1) if i >= 1 else None))
    if lqn != 4:
        m = 3 * lqn
        ip = f"{ly}Q1" if lqn == 1 else f"{m}M{ly}"
        ipp = f"{ly - 1}Q1" if lqn == 1 else f"{m}M{ly - 1}"
        n = len(acols)
        acols.append(Col(num2col(n + 2), ipp, f"{m}M/{ly - 1 + 543}", 12 / m, "i", bs_per=f"{ly - 1}Q{lqn}"))
        acols.append(Col(num2col(n + 3), ip, f"{m}M/{ly + 543}", 12 / m, "i", bs_per=f"{ly}Q{lqn}", py=num2col(n + 2)))
    for c in acols:
        if c.kind == "q":
            c.bs_per = c.per
    # ---------------- model
    model = Model()
    model.ttm_letter, model.last_q_letter = ttm_letter, qcols[-1].letter
    comp = asm.get("company", {})
    cover = model.sheet("COVER", "หน้าปก (Cover & Summary)")
    sub = f"{comp.get('name_th', ticker)} ({ticker}) | {th_q(quarters[0])} – {th_q(quarters[-1])} ({len(quarters)} ไตรมาส) + TTM"
    build_statement_tab(model, "C", "งบรวม (Consolidated)", "งบการเงินรวม (Consolidated Financial Statements) — รายไตรมาส", sub,
                        qcols_ttm, facts, "C", has_sso)
    build_statement_tab(model, "S", "งบเฉพาะกิจการ (Separate)", "งบการเงินเฉพาะกิจการ (Separate / Parent Company) — รายไตรมาส", sub,
                        qcols_ttm, facts, "S", has_sso)
    build_subs_tab(model, qcols_ttm, sub)
    mix_src = (asm.get("revenue_mix") or {}).get("source", "ยังไม่ระบุแหล่ง — agent ต้องกรอกจาก MD&A/56-1")
    build_mix_tab(model, "REV", "โครงสร้างรายได้ (Revenue)", "โครงสร้างรายได้รายไตรมาส (Quarterly Revenue Mix)", qcols_ttm, facts, "C",
                  has_sso, "ที่มา: " + mix_src)
    pj = asm.get("project") or {}
    pname = f"วิเคราะห์{pj.get('short_name', 'โครงการ')} (Sensitivity)"
    if len(pname) > 31:
        pname = "วิเคราะห์โครงการ (Sensitivity)"
    # annual tab before project (project links to C only)
    asub = f"{comp.get('name_th', ticker)} ({ticker}) | " + " / ".join(c.label for c in acols)
    tA = build_statement_tab(model, "A", "งบรวมรายปี (Consolidated)", f"งบการเงินรวมรายปี {len(fys)} ปี + งวดสะสมล่าสุด (Annual Consolidated)", asub,
                             acols, facts, "C", has_sso,
                             extra=lambda t: [t.section("เงินปันผล (Dividend)"),
                                              t.add_row({"id": "dps", "label": "เงินปันผลต่อหุ้น (DPS, บาท) — ปีที่จ่ายจากผลประกอบการ", "kind": "in",
                                                         "key": "dps", "fmt": "eps", "lvl": 1}, facts, "C"),
                                              t.add_row({"id": "payout", "label": "อัตราการจ่ายปันผล (Payout % ของ EPS)", "kind": "f", "fmt": "pct",
                                                         "lvl": 2, "style": "ratio", "f": "IFERROR([dps]/[eps],\"\")"})])
    build_project_tab(model, asm, pname)
    build_mix_tab(model, "AREV", "โครงสร้างรายได้ (Annual)", "โครงสร้างรายได้รายปี (Annual Revenue Mix)", acols, facts, "A", has_sso,
                  "ที่มา: " + mix_src)
    build_nature_tab(model, acols, facts, asub)
    build_valuation_tab(model, asm)
    # order tabs
    order = ["COVER", "C", "S", "SUB", "REV", "PRJ", "A", "AREV", "NAT", "VAL"]
    model.wb._sheets = [model.tabs[k].ws for k in order]
    # gaps
    core = ["rev_hosp", "cogs", "selling", "admin", "np_owners", "total_assets", "total_liab", "total_equity", "cash", "cfo"]
    # a filing that never shows a separate selling line (admin only, or one combined SG&A line) is not a gap
    no_sell = {e for e in "CS" if all(facts.get(e, "selling", q)[0] is None for q in quarters)}
    gaps = [f"{e}:{k}@{th_q(q)}" for e in "CS" for k in core for q in quarters
            if facts.get(e, k, q)[0] is None and not (k == "selling" and e in no_sell)]
    if all(facts.get("S", "rev_hosp", q)[0] is None for q in quarters):
        warnings.append("ไม่มีงบเฉพาะกิจการในไฟล์ (บริษัทไม่มีบริษัทย่อยหรือไม่ได้แยกงบ) — ชีตงบเฉพาะกิจการ/บริษัทย่อยจะว่าง")
    if not asm.get("executive_summary"):
        warnings.append("executive_summary ว่าง — Cover ยังไม่มีบทวิเคราะห์เชิงคุณภาพ")
    if not asm.get("revenue_mix"):
        warnings.append("revenue_mix ว่าง — ชีตโครงสร้างรายได้จะไม่มีตัวเลข")
    for k in ("rf", "beta", "erp", "g", "payout"):
        if k not in (asm.get("valuation") or {}):
            warnings.append(f"valuation.{k} ใช้ค่าเริ่มต้น (พื้นเหลือง) — ควรกำหนดพร้อมเหตุผล")
    ver = next_version(outdir, ticker, version)
    fname = f"{ticker}_finance_model_v{ver}"
    meta = {"ticker": ticker, "q_first": th_q(quarters[0]), "q_last": th_q(quarters[-1]), "nq": len(quarters),
            "y_first": acols[0].label, "y_last": acols[-1].label, "category": CATEGORY.get(cat, str(cat)),
            "generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "file": fname + ".xlsx",
            "gaps": (f"{len(gaps)} ช่อง — " + ", ".join(gaps[:12]) + (" ..." if len(gaps) > 12 else "")) if gaps else "ไม่มี",
            "warnings": warnings}
    build_cover(model, asm, fin, meta)
    for ws in model.wb.worksheets:
        ws.sheet_properties.tabColor = {"หน้าปก (Cover & Summary)": "1F4E79", "ประเมินมูลค่า (Valuation)": "C00000"}.get(ws.title, "2F5496")
    xlsx = os.path.join(outdir, fname + ".xlsx")
    model.wb.save(xlsx)
    calc = CalcWB(model.cells)
    # evaluate every formula once so errors surface
    errors = []
    for sh, cells in model.cells.items():
        for addr, v in cells.items():
            if isinstance(v, str) and v.startswith("="):
                val = calc.get(sh, addr)
                if isinstance(val, XLError) and val.code != "n/a":
                    errors.append(f"{sh}!{addr} {val.code} {v[:80]}")
    md = os.path.join(outdir, fname + ".md")
    build_markdown(model, calc, asm, fin, meta, md)
    return xlsx, md, errors, meta, model, calc


def init_assumptions(fin, set_path, out):
    """Scaffold an assumptions file with market data pulled from the SET factsheet; the agent fills the rest."""
    mk = {}
    comp = {}
    if set_path and os.path.exists(set_path):
        d = json.load(open(set_path, encoding="utf-8")).get("data", {})
        ts = (d.get("trading_stat") or [{}])[0]
        ov = d.get("overview") or {}
        mk = {"price": ts.get("close"), "shares_mn": round((ts.get("listedShare") or 0) / 1e6, 3),
              "as_of": (ts.get("date") or "")[:10], "source": f"SET factsheet trading_stat {ts.get('date', '')[:10]}",
              "dps_last_fy": None, "shares_note": "listedShare จาก SET"}
        ca = d.get("corporate_action_historical") or d.get("corporate_action") or []
        yr = {}
        for a in ca:
            if a.get("caType") == "XD" and a.get("dividend") and a.get("endOperation"):
                y = a["endOperation"][:4]
                yr[y] = yr.get(y, 0) + a["dividend"]
        # last COMPLETE fiscal year = latest year that already has a dividend covering up to December
        complete = {a["endOperation"][:4] for a in ca if a.get("caType") == "XD" and a.get("dividend")
                    and (a.get("endOperation") or "")[5:7] == "12"}
        if yr:
            last = max(complete) if complete else max(yr)
            mk["dps_last_fy"] = round(yr[last], 4)
            mk["dps_note"] = f"รวมปันผลจากผลประกอบการปี {int(last) + 543} (SET corporate actions)"
        comp = {"name_th": ov.get("name", ""), "name_en": ""}
    tpl = {
        "company": comp, "category": 3, "has_sso": False,
        "market": mk,
        "revenue_mix": {"source": "", "quarterly": {}, "annual": {}},
        "one_offs": [],
        "manual_facts": {},
        "executive_summary": {},
        "valuation": {"notes": {}, "forecast": {"fy1": {"label": "", "np": None, "rationale": ""}}},
        "project": {},
    }
    json.dump(tpl, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"✅ scaffold written: {out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd")
    b = sp.add_parser("build")
    b.add_argument("--financials", "-f", required=True)
    b.add_argument("--assumptions", "-a", required=True)
    b.add_argument("--output-dir", "-o", required=True)
    b.add_argument("--quarters", "-q", type=int, default=14)
    b.add_argument("--version", "-v")
    i = sp.add_parser("init")
    i.add_argument("--financials", "-f", required=True)
    i.add_argument("--set-factsheet")
    i.add_argument("--out", required=True)
    a = ap.parse_args()
    if a.cmd == "init":
        init_assumptions(json.load(open(a.financials, encoding="utf-8")), a.set_factsheet, a.out)
        return
    if a.cmd != "build":
        ap.print_help(); return
    fin = json.load(open(a.financials, encoding="utf-8"))
    asm = json.load(open(a.assumptions, encoding="utf-8"))
    xlsx, md, errors, meta, model, calc = build(fin, asm, a.output_dir, a.quarters, a.version)
    print(f"✅ {xlsx}\n✅ {md}")
    cov = model.tabs["COVER"]
    for lab, addr in model.cover_checks:
        print(f"   {calc.get(cov.name, addr)}  {lab}")
    for w in meta["warnings"]:
        print("   ⚠", w)
    if errors:
        print(f"   ❌ {len(errors)} formula errors:")
        for e in errors[:20]:
            print("     ", e)
    print(f"   gaps: {meta['gaps'][:300]}")


if __name__ == "__main__":
    main()
