"""
render.py - turn a snapshot data pack (+ optional agent narrative) into the Markdown report and a standalone
HTML dashboard.  Both come from one list of blocks, so they always show the same numbers.

Narrative items may be plain strings or {"text": ..., "src": "MDA_Year2569_Q2:L4758"} or
{"text": ..., "external": true}.  External/unverified items are shown in dark red (#8B0000) and listed again
in section 5.
"""
import html as H
import os
import re
from datetime import datetime

from snapshot import be, qadd, pct, LINE_DEFS, PCT_LINES
import snapshot as S

RED = "#8B0000"
LAB = dict(LINE_DEFS)


# ------------------------------------------------------------------------------------------ formatting
def n2(v, d=2):
    if v is None:
        return "–"
    s = ("{:,.%df}" % d).format(abs(v))
    return "(%s)" % s if v < 0 else s


def p1(v):
    return "–" if v is None else "%.1f%%" % (v * 100)


def pct_(a, b):
    if a is None or b is None or abs(b) < 1e-6 or a * b < 0:
        return None
    return (a / b - 1) * (1 if b > 0 else -1)


def chg(v):
    return "–" if v is None else "%+.1f%%" % (v * 100)


def pt(v):
    return "–" if v is None else "%+.2f pt" % (v * 100)


def sbe(q):
    """short BE label for chart axes: Q3/68"""
    return "Q%s/%s" % (q[-1], str(int(q[:4]) + 543)[-2:])


def tier_s(t):
    return {1: "T1 ≤3%", 2: "T2 3–10%", 3: "T3 >10%"}.get(t, "")


def item_text(it):
    """-> (text, src, external)"""
    if isinstance(it, dict):
        return it.get("text", ""), it.get("src"), bool(it.get("external"))
    return str(it), None, False


# ------------------------------------------------------------------------------------------ blocks
class Doc:
    def __init__(self):
        self.b = []

    def h(self, lvl, text):
        self.b.append(("h", lvl, text))

    def p(self, text):
        self.b.append(("p", text))

    def ul(self, items):
        items = [i for i in items if i]
        if items:
            self.b.append(("ul", items))

    def table(self, head, rows, align=None, bold_rows=()):
        self.b.append(("table", head, rows, align or (["l"] + ["r"] * (len(head) - 1)), set(bold_rows)))

    def callout(self, kind, title, lines):
        self.b.append(("callout", kind, title, lines))

    def chart(self, spec):
        self.b.append(("chart", spec))

    def hr(self):
        self.b.append(("hr",))

    def raw(self, html, md=""):
        """HTML written as is (charts, maps, cards) and its Markdown stand-in (often empty when a table follows)."""
        self.b.append(("raw", html, md))


def narrative_items(items):
    out = []
    for it in items or []:
        t, src, ext = item_text(it)
        if not t:
            continue
        out.append(("ext", t, src) if ext else ("src", t, src) if src else ("txt", t, None))
    return out


# ------------------------------------------------------------------------------------------ auto narrative
def auto_narrative(p):
    """Rule-based commentary from the numbers only (no MD&A reasons).  Clearly labelled in the report."""
    g = lambda q, k: p["lines"].get(q, {}).get(k)
    q, py, pq = p["q_last"], p["q_py"], p["q_pq"]
    s = []
    rv, gp, cn = pct(g(q, "rev"), g(py, "rev")), pct(g(q, "gp"), g(py, "gp")), pct(g(q, "core_np"), g(py, "core_np"))
    if rv is not None:
        s.append("รายได้โรงพยาบาล %s %s ลบ. %s YoY [คำนวณ: (%s − %s) / %s] และ %s QoQ" % (
            be(q), n2(g(q, "rev")), chg(rv), n2(g(q, "rev")), n2(g(py, "rev")), n2(g(py, "rev")), chg(pct(g(q, "rev"), g(pq, "rev")))))
    if gp is not None:
        s.append("กำไรขั้นต้น %s ลบ. %s YoY; GPM %s เทียบ %s ปีก่อน (%s)" % (n2(g(q, "gp")), chg(gp), p1(g(q, "gpm")), p1(g(py, "gpm")),
                                                                     pt(g(q, "gpm") - g(py, "gpm"))))
    if cn is not None:
        s.append("กำไรปกติ %s ลบ. %s YoY, %s QoQ" % (n2(g(q, "core_np")), chg(cn), chg(pct(g(q, "core_np"), g(pq, "core_np")))))
    b = p["bridges"].get("yoy")
    if b:
        top = sorted(b["items"], key=lambda x: -abs(x[1]))[:2]
        s.append("ปัจจัยหลักของกำไรที่เปลี่ยน YoY (%+.2f ลบ.): %s" % (b["total"], "; ".join("%s %+.2f ลบ." % (n.split(" (")[0], v) for n, v in top)))
    cx = pct(g(q, "core_pbt_x"), g(py, "core_pbt_x"))
    if cx is not None:
        s.append("Core PBT ก่อน ECL และรายการพิเศษ %s ลบ. %s YoY (ไม่รวมรายได้อื่น/ดอกเบี้ย/เงินปันผล)" % (n2(g(q, "core_pbt_x")), chg(cx)))
    if p["sga"].get("split_yoy"):
        s.append(p["sga"]["split_yoy"]["text"])
    for r in p["records"]:
        s.append(("📉 " if r.get("kind") == "low" else "🏆 ") + r["text"])
    return {"_auto": True, "summary": s, "headline": None}


# ------------------------------------------------------------------------------------------ document
def build_doc(p, nar, problems):
    auto = not nar or nar.get("_auto")
    if auto:
        nar = auto_narrative(p)
    g = lambda q, k: p["lines"].get(q, {}).get(k)
    q, py, pq, W = p["q_last"], p["q_py"], p["q_pq"], p["window"]
    d = Doc()
    name = p["company"].get("name_th") or p["company"].get("name_en") or p["ticker"]
    d.h(1, "⚡ รายงานสรุปภาพรวมและโมเมนตัมระยะสั้น หุ้นโรงพยาบาล (Hospital Stock Snapshot) — %s" % p["ticker"])
    d.p("**%s** | %s" % (name, p["category_name"]))
    meta = ["**ไตรมาสล่าสุด:** %s (QoQ เทียบ %s, YoY เทียบ %s; สะสม %s เทียบ %s)" % (p["q_last_be"], be(pq), be(py), be(p["ytd"]), be(p["ytd_py"])),
            "**ขอบเขต:** ย้อนหลัง 4 ไตรมาส (%s–%s) และมองไปข้างหน้า 4 ไตรมาส" % (be(W[0]), be(W[-1])),
            "**สร้างเมื่อ:** %s" % datetime.now().strftime("%Y-%m-%d %H:%M"),
            "**ที่มาของตัวเลข:** งบการเงินที่ยื่น SET (`%s`, ทุกตัวเลขมีบรรทัดอ้างอิง), โครงสร้างรายได้จาก MD&A (`%s`, กระทบยอดกับงบ ±1 ลบ.), "
            "รายการพิเศษ/ราคาตลาดจาก `%s`" % (os.path.basename(p["sources"]["financials"] or "-"), os.path.basename(p["sources"]["mda"] or "-"),
                                          os.path.basename(p["sources"]["assumptions"] or "-")),
            "**บทวิเคราะห์เชิงคุณภาพ:** " + ("⚠️ อัตโนมัติจากตัวเลขเท่านั้น (ยังไม่ได้อ่าน MD&A หาสาเหตุ) — ให้ Claude รัน skill `stock-snapshot` เพื่อเติมเหตุผล"
                                             if auto else "เขียนจาก MD&A/เอกสารบริษัท ทุกข้อที่มีตัวเลขนอกงบมีแหล่งอ้างอิง")]
    d.ul(meta)
    ok = all(c["ok"] for c in p["checks"])
    d.callout("tip" if ok else "warning", "การตรวจสอบความถูกต้อง (Integrity checks): %s" % ("ผ่านทั้งหมด" if ok else "มีรายการไม่ผ่าน"),
              ["%s %s" % ("✅" if c["ok"] else "❌", c["label"]) for c in _compress_checks(p["checks"])])

    # ---------------------------------------------------------------- 1. executive
    m = p["momentum"]
    d.h(2, "📌 1. สรุปผู้บริหาร (Executive Flash Summary)")
    if nar.get("headline"):
        d.p("**%s**" % nar["headline"])
    _cf = [c for c in nar.get("conflicts") or [] if isinstance(c, dict) and c.get("verdict", "conflict") == "conflict"]
    if _cf:
        d.callout("warning", "แหล่งข้อมูลชุดที่ 2 (ข่าว/บทสัมภาษณ์/คลิป) ขัดกับเอกสารที่ยื่นต่อ ตลท. %d ประเด็น — รายงานนี้ใช้ตัวเลขจากเอกสาร ตลท. (ดูข้อ 5)" % len(_cf),
                  ["%s: แหล่งที่ 2 ว่า \"%s\" แต่เอกสาร ตลท. คือ %s" % (c["topic"], c["second"], c["primary"]) for c in _cf])
    d.p("**คะแนนโมเมนตัมระยะสั้น: %.1f / 10 (%s)** — คำนวณจากกฎที่โปร่งใส (ดูข้อ 4)" % (m["score"], m["label"]))
    d.b.append(("nlist", narrative_items(nar.get("summary"))))
    rows, bold = [], []
    for r in p["headline"]:
        if r["id"] not in ("rev", "gp", "gpm", "sg_pct", "sa_pct", "sga", "sga_x", "sga_pct", "core_op", "core_pbt", "core_pbt_x", "ebit",
                           "np_owners", "one_off", "core_np", "da", "ebitda", "ebitda_m", "ecl", "cash_total", "net_cash", "dso", "cfo"):
            continue
        if r["is_pct"]:
            rows.append([r["label"], p1(r["py"]), p1(r["pq"]), p1(r["cur"]), pt(r.get("yoy_pt")), pt(r.get("qoq_pt")), ""])
        elif r["id"] == "dso":
            rows.append([r["label"], n2(r["py"], 1), n2(r["pq"], 1), n2(r["cur"], 1),
                         "%+.1f วัน" % r["yoy_pt"] if r.get("yoy_pt") is not None else "–", "%+.1f วัน" % r["qoq_pt"] if r.get("qoq_pt") is not None else "–", ""])
        elif r["cur"] is None and r["py"] is None and r["pq"] is None:
            continue
        elif "yoy_abs" in r:
            rows.append([r["label"], n2(r["py"]), n2(r["pq"]), n2(r["cur"]),
                         "Δ %s" % n2(r["yoy_abs"]) if r["yoy_abs"] is not None else "–", "Δ %s" % n2(r["qoq_abs"]) if r["qoq_abs"] is not None else "–", ""])
        else:
            rows.append([r["label"], n2(r["py"]), n2(r["pq"]), n2(r["cur"]), chg(r.get("yoy")), chg(r.get("qoq")), tier_s(r.get("tier"))])
        if r["id"] in ("rev", "gp", "core_pbt_x", "ebit", "core_np", "np_owners"):
            bold.append(len(rows) - 1)
    d.table(["ตัวชี้วัด (ล้านบาท)", be(py), be(pq), be(q), "YoY", "QoQ", "ระดับ YoY"], rows, bold_rows=bold)
    d.p("_ระดับ YoY: T1 = เปลี่ยน ≤3% (ต้องอธิบายปัจจัยหักล้าง), T2 = 3–10% (ต้องระบุสาเหตุหลัก), T3 = >10% (ต้องมีหลักฐานจากเอกสาร มิฉะนั้นเป็น 🚩)_")
    d.p("_Core PBT = กำไรขั้นต้น − SG&A − ต้นทุนทางการเงิน (ตัดรายได้อื่น ดอกเบี้ยรับ เงินปันผลรับ และภาษีที่ผันผวนรายไตรมาสออก); "
        "ก่อน ECL = บวกกลับ ECL จากงบกระแสเงินสดทั้งสองงวด (การโอนกลับ ECL ในงวดเปรียบเทียบจะถูกหักออก); ก่อนรายการพิเศษ = หักรายการพิเศษก่อนภาษีจาก assumptions. "
        "SG&A ก่อน ECL ใช้สมมติฐานว่า ECL บันทึกใน%s_" % ("ค่าใช้จ่ายบริหาร" if p["sga"].get("ecl_line", "admin") == "admin" else p["sga"].get("ecl_line")))
    an = p.get("angles") or {}
    items = []
    if an.get("phase"):
        items.append("**ช่วงของธุรกิจ — " + an["phase"]["text"].replace(": ", ":** ", 1))
    for b in an.get("cost_bands") or []:
        items.append("**ต้นทุนคงที่:** " + b["text"])
    for k in ("base_now", "base_next"):
        if an.get(k):
            items.append("**ฐานเปรียบเทียบ:** " + an[k]["text"])
    if an.get("price"):
        items.append("**ความไวต่อราคา:** " + an["price"]["text"])
    for k in ("da_trend", "commit", "cost_peak"):
        if an.get(k):
            items.append("**สัญญาณนำของช่วงลงทุน:** " + an[k]["text"])
    if an.get("locate"):
        items.append("**การเปลี่ยนแปลงอยู่ที่ใคร (งบรวม − งบเฉพาะกิจการ = บริษัทย่อย):** " + an["locate"]["text"])
    if items:
        d.h(3, "มุมมองนักลงทุน: ช่วงธุรกิจ ต้นทุนคงที่ ฐานเปรียบเทียบ (คำนวณด้วยสคริปต์)")
        d.ul(items)
        d.b.append(("nlist", narrative_items(nar.get("angles"))))
    pv = [it for it in nar.get("pop_view") or [] if isinstance(it, dict) and it.get("text")]
    if pv:
        PVL = {"confirmed": "✅ ตรงกับเอกสารบริษัท", "differs": "⚠️ ต่างจากเอกสารบริษัท (ดูตารางเทียบแหล่งข้อมูล)",
               "not_in_filings": "ไม่มีในเอกสารบริษัท ยังตรวจไม่ได้", "opinion": "ความเห็น/การตีความ"}
        an = p.get("analyst_notes")
        names = S.analyst_names(None, pv) if not an else S.analyst_names(an, pv)
        if names == [S.DEFAULT_ANALYST]:
            d.h(3, "มุมมองของคุณ Pop (นักวิเคราะห์อ้างอิง)")
            d.p("_รายงานนี้ใช้วิธีอ่านของคุณ Pop เป็นหลักในการตั้งประเด็น ตัวเลขในตารางทุกตัวยังมาจากเอกสารที่บริษัทยื่นต่อ ตลท. "
                "ตัวเลขจากโพสต์ถูกตรวจกับเอกสารและระบุผลไว้ท้ายแต่ละข้อ_")
            d.table(["ประเด็นที่คุณ Pop ชี้", "ผลการตรวจกับเอกสารบริษัท", "ที่มา"],
                    [[it["text"], PVL.get(it.get("verdict"), it.get("verdict", "")), "<small>%s</small>" % it.get("src", "")] for it in pv],
                    align=["l", "l", "l"])
        else:
            d.h(3, "มุมมองของนักวิเคราะห์อ้างอิง (%s)" % ", ".join(names))
            d.p("_รายงานนี้ใช้วิธีอ่านของนักวิเคราะห์อ้างอิงเป็นหลักในการตั้งประเด็น ตัวเลขในตารางทุกตัวยังมาจากเอกสารที่บริษัทยื่นต่อ ตลท. "
                "ตัวเลขจากบันทึก โพสต์ และการบรรยายของแต่ละท่านถูกตรวจกับเอกสารและระบุผลไว้ท้ายแต่ละข้อ_")
            d.table(["นักวิเคราะห์", "ประเด็นที่ชี้", "ผลการตรวจกับเอกสารบริษัท", "ที่มา"],
                    [[S.row_analyst(it, an), it["text"], PVL.get(it.get("verdict"), it.get("verdict", "")), "<small>%s</small>" % it.get("src", "")]
                     for it in pv], align=["l", "l", "l", "l"])
    ex = p.get("expect") or {}
    if ex.get("lines") or nar.get("expectation"):
        d.h(3, "ราคา = มูลค่า + เรื่องเล่า (เรื่องเล่า = ความคาดหวัง − ความผิดหวัง)")
        d.ul(ex.get("lines") or [])
        d.b.append(("nlist", narrative_items(nar.get("expectation"))))
    d.chart({"type": "bars", "title": "รายได้โรงพยาบาลรายไตรมาส (ล้านบาท)", "series": [
        {"name": "รายได้", "vals": [(sbe(x), g(x, "rev")) for x in p["ext"]]}]})
    d.chart({"type": "bars", "title": "กำไรปกติรายไตรมาส (ล้านบาท)", "series": [
        {"name": "กำไรปกติ", "vals": [(sbe(x), g(x, "core_np")) for x in p["ext"]]}]})
    d.chart({"type": "lines", "title": "อัตรากำไร (% ของรายได้)", "pct": True, "series": [
        {"name": "GPM", "vals": [(sbe(x), g(x, "gpm")) for x in p["ext"]]},
        {"name": "SG&A/รายได้", "vals": [(sbe(x), g(x, "sga_pct")) for x in p["ext"]]},
        {"name": "EBITDA margin", "vals": [(sbe(x), g(x, "ebitda_m")) for x in p["ext"]]}]})

    # ---------------------------------------------------------------- 2. operations
    d.h(2, "🔍 2. เจาะลึกการดำเนินงาน 4 ไตรมาสล่าสุด (Operational Review)")
    d.h(3, "2.1 โครงสร้างรายได้ (Revenue Mix ตาม MD&A)")
    charts = []
    if p["mix_rows"]:
        _mix_table(d, p, p["mix_rows"], "โครงสร้างรายได้ตามประเภทผู้ป่วย (ล้านบาท)")
        stack = [r for r in p["mix_rows"] if r["id"] != "elim"]
        charts.append({"type": "stack", "title": "รายได้ตามประเภทผู้ป่วย (ล้านบาท, % ของรายได้โรงพยาบาล)",
                       "pct_total": _mix_totals(p, p["mix_rows"]),
                       "note": "% = สัดส่วนต่อรายได้จากกิจการโรงพยาบาล (หลังหักรายการระหว่างกัน) เหมือนคอลัมน์สัดส่วนในตาราง จึงรวมกันเกิน 100% เล็กน้อย",
                       "series": [{"name": r["label"], "vals": [(sbe(x), r["vals"].get(x)) for x in p["ext"]]} for r in stack]})
    else:
        d.p("ไม่มีตารางโครงสร้างรายได้ OPD/IPD ที่กระทบยอดได้จาก MD&A สำหรับช่วงนี้")
    if p["nat_rows"]:
        _mix_table(d, p, p["nat_rows"], "รายได้ตามสัญชาติผู้ป่วย (ล้านบาท)")
        charts.append({"type": "stack", "title": "รายได้ตามสัญชาติผู้ป่วย (ล้านบาท, % ของรายได้)",
                       "pct_total": _mix_totals(p, p["nat_rows"]),
                       "series": [{"name": r["label"], "vals": [(sbe(x), r["vals"].get(x)) for x in p["ext"]]} for r in p["nat_rows"]]})
    for c in charts:
        d.chart(c)
    ops = p.get("ops")
    if ops:
        qs = [q for q in p["ext"][-5:]]
        rows = []
        for r in ops["rows"]:
            f = (lambda v: "–" if v is None else ("%.2f%%" % v if r["rate"] else "{:,.0f}".format(v)))
            ch = ("%+.2f จุด" % r["ops_pt"]) if r.get("ops_pt") is not None else (chg(r.get("ops_g")) if r.get("ops_g") is not None else "–")
            rows.append([r["label"]] + [f(r["ops_vals"].get(q)) for q in qs] + [ch])
        d.h(3, "ปริมาณ อัตราการใช้ และรายได้ต่อใบเสร็จ (จากสไลด์ Oppday)")
        d.table(["ตัวชี้วัด"] + [be(q) for q in qs] + ["YoY"], rows)
        d.ul(["**ปริมาณหรือราคา — " + t.replace(": ", ":** ", 1) for t in ops["read"]])
        if ops.get("base_notes"):
            d.ul(["**ตรวจฐานของอัตรา:** " + t for t in ops["base_notes"]])
        note = "_ที่มา: %s อ่านจากตำแหน่งบนสไลด์ด้วยสคริปต์; แถว [คำนวณ] = ปริมาณ ÷ อัตรา ÷ จำนวนวันในไตรมาส บริษัทไม่ได้เปิดเผยโดยตรง" % ops["source"]
        if ops.get("restated"):
            note += "; บริษัทเคยปรับนิยามของชุดข้อมูลนี้ในสไลด์รุ่นก่อน จึงใช้เฉพาะตัวเลขที่ตรงกับสไลด์ล่าสุด"
        d.p(note + "_")
    sp = p.get("sso_pxq")
    if sp and sp.get("rows"):
        d.h(3, "ประกันสังคม: รายได้ = จำนวนผู้ประกันตน (Q) × รายได้ต่อผู้ประกันตน (P)")
        fm = lambda v, f="{:,.0f}": "–" if v is None else f.format(v)
        gp = lambda v: "–" if v is None else "%+.1f%%" % (v * 100)
        rows = []
        for r in sp["rows"]:
            rows.append(["ปี %s" % r["year"], fm(r["insured"]), gp(r.get("q_g")), fm(r["p"]), fm(r.get("p_stated")), gp(r.get("p_g")), fm(r["rev"], "{:,.2f}"), gp(r.get("rev_g")),
                         ("%+.1f / %+.1f" % (r["q_eff"], r["p_eff"])) if r.get("q_eff") is not None else "–",
                         "–" if r.get("util") is None else "%.0f%%" % (r["util"] * 100),
                         "–" if r.get("gpm") is None else ("%.1f%%" % (r["gpm"] * 100) + ((" (%+.1f จุด)" % r["gpm_pt"]) if r.get("gpm_pt") is not None else ""))])
        y = sp.get("ytd")
        if y and y.get("rev") is not None:
            rows.append(["%s" % be(y["ytd"]), "ยังไม่เปิดเผย", "–", "–", "–", "–", fm(y["rev"], "{:,.2f}"), gp(y.get("rev_g")), "–", "–", "–"])
        d.table(["ปี", "ผู้ประกันตน (Q)", "Q YoY", "P คำนวณ (บาท/ราย)", "P บริษัทแจ้ง", "P YoY", "รายได้ SSO (ลบ.)", "รายได้ YoY",
                 "ส่วนเพิ่มจาก Q / P (ลบ.)", "ใช้โควตา", "GPM กลุ่ม"], rows,
                align=["l", "r", "r", "r", "r", "r", "r", "r", "r", "r", "r"])
        lab = [r["year"] for r in sp["rows"]]
        base = next((r for r in sp["rows"] if r["insured"] and r["p"]), None)
        if base:
            d.chart({"type": "lines", "title": "ดัชนี Q และ P (ปี %s = 100)" % base["year"],
                     "note": "เส้นที่ชันกว่าคือตัวขับรายได้ SSO; P = รายได้ประกันสังคม ÷ ผู้ประกันตน [คำนวณ]",
                     "series": [{"name": "ผู้ประกันตน (Q)", "vals": [(x["year"], x["insured"] / base["insured"] * 100 if x["insured"] else None) for x in sp["rows"]]},
                                {"name": "รายได้ต่อผู้ประกันตน (P)", "vals": [(x["year"], x["p"] / base["p"] * 100 if x["p"] else None) for x in sp["rows"]]}]})
        xr = [r for r in sp["rows"] if r.get("rev_ex") is not None or r.get("referral") is not None]
        if xr:
            d.table(["ปี", "รายได้ SSO ไม่รวมรายการตัดย้อนหลัง (ลบ.)", "P ไม่รวมรายการ (บาท)", "P YoY ไม่รวมรายการ",
                     "ค่ารักษาพยาบาลส่งต่อ (ลบ.)", "ค่าส่งต่อ YoY", "ค่าส่งต่อ ÷ รายได้ SSO"],
                    [["ปี %s" % r["year"], fm(r.get("rev_ex", r["rev"]), "{:,.2f}"), fm(r.get("p_ex", r["p"])),
                      gp(r.get("p_g_ex", r.get("p_g"))), fm(r.get("referral"), "{:,.1f}"), gp(r.get("referral_g")),
                      "–" if r.get("referral_to_sso") is None else "%.1f%%" % (r["referral_to_sso"] * 100)] for r in sp["rows"]],
                    align=["l", "r", "r", "r", "r", "r", "r"])
        if sp.get("events"):
            d.p("**เหตุการณ์ผู้จ่ายเงินที่กระทบฐาน (บันทึกใน data/sector/Hospital/payor_events.json):**")
            d.ul(["%s — %s [%s]" % (e["date"], e["text"], e.get("src", "")) for e in sp["events"]])
        d.ul(["**P × Q — " + t.split(": ", 1)[0] + ":** " + t.split(": ", 1)[-1] if ": " in t[:12] else "**P × Q:** " + t for t in sp["read"]])
        d.p("**ทำไม P เปลี่ยนได้ (ต้องมีเอกสารยืนยันก่อนสรุป):**")
        d.ul(sp["drivers"])
        for f in sp.get("flags") or []:
            d.p("⚠ " + f)
        d.p("_ที่มา: ผู้ประกันตนและโควตา %s; รายได้ SSO ตามโครงสร้างรายได้ MD&A; P, YoY, ส่วนเพิ่ม (Q: ΔQ×P ปีก่อน, P: ΔP×Q ปีนี้) และ GPM กลุ่มเป็นค่าคำนวณ. "
            "GPM เป็นของทั้งกลุ่ม ไม่ใช่ของผู้ป่วย SSO — บริษัทไม่เปิดเผยกำไรตามประเภทผู้ป่วย_" % (sp["rows"][-1].get("src", "") or "hospitals.json"))
    for r in p["records"]:
        if r.get("kind") != "low":
            d.p("🏆 **%s**" % r["text"])
    if not p["has_sso"]:
        d.p("_%s — ไม่มีรายได้ประกันสังคม จึงไม่แสดงแถว SSO_" % p["category_name"])
    d.b.append(("nlist", narrative_items(nar.get("revenue")) + narrative_items(nar.get("mix_notes"))))

    d.h(3, "2.2 โครงสร้างต้นทุนและ Operating Leverage (Incremental GPM)")
    ol = []
    for key, lab in (("yoy", "YoY"), ("qoq", "QoQ")):
        o = p["oplev"].get(key)
        if not o:
            continue
        if o.get("igpm") is not None:
            ol.append("**%s:** Incremental GPM %.1f%% [คำนวณ: ΔGP / ΔRev = %s / %s เทียบ %s] — %s" % (
                lab, o["igpm"] * 100, n2(o["d_gp"]), n2(o["d_rev"]), be(o["base"]), o["text"]))
        else:
            ol.append("**%s:** %s" % (lab, o["text"]))
        if o.get("da_share_of_dcogs") is not None and o["d_cogs"] > 0:
            ol.append("&nbsp;&nbsp;ค่าเสื่อมราคาเพิ่ม %s ลบ. คิดเป็น %.0f%% ของต้นทุนที่เพิ่ม %s ลบ. [คำนวณ: ΔD&A / ΔCOGS]" % (
                n2(o["d_da"]), o["da_share_of_dcogs"] * 100, n2(o["d_cogs"])))
    d.ul(ol)
    hist = p["oplev"].get("history") or {}
    if any(v is not None for v in hist.values()):
        d.table(["Incremental GPM (YoY)"] + [be(x) for x in W], [["ΔGP/ΔRev เทียบไตรมาสเดียวกันปีก่อน"] + [p1(hist.get(x)) for x in W]])
    d.p("_รายได้โรงพยาบาลมีฤดูกาล และต้นทุนคงที่ต่อไตรมาสใกล้เคียงกัน จึงตีความ GPM และ Incremental GPM แบบ YoY เป็นหลัก; ค่า QoQ ใช้ประกอบเท่านั้น_")
    d.p("_เกณฑ์: >40% = Operating leverage แข็งแรง; 20–40% = ปกติของโรงพยาบาล; <15% = ห้ามสรุปว่ามี operating leverage สูง; "
        "ติดลบขณะที่รายได้โต = ต้องหาสาเหตุ (ค่าเสื่อมจากการลงทุน, อัตราครองเตียง, ผู้ป่วยกลุ่มมาร์จิ้นสูงลดลง, ส่วนผสม OPD/IPD)_")
    d.b.append(("nlist", narrative_items(nar.get("op_leverage"))))

    d.h(3, "2.3 วินัยค่าใช้จ่าย SG&A และผลขาดทุนด้านเครดิต (ECL)")
    rows = []
    for k in ("selling", "sg_pct", "admin", "sa_pct", "sga", "sga_pct", "ecl", "ecl_pct", "admin_x", "sga_x"):
        vals = [g(x, k) for x in W]
        rows.append([LAB[k]] + [p1(v) if k in PCT_LINES else n2(v) for v in vals])
    d.table(["ค่าใช้จ่าย (ล้านบาท)"] + [be(x) for x in W], rows)
    sl = []
    for key, lab in (("yoy", "YoY"), ("qoq", "QoQ")):
        s = p["sga"].get(key)
        if s:
            sl.append("**%s:** %s" % (lab, s["text"]))
    for key, lab in (("yoy_x", "YoY ก่อน ECL"), ("qoq_x", "QoQ ก่อน ECL")):
        s = p["sga"].get(key)
        if s:
            sl.append("**%s:** %s" % (lab, s["text"]))
    for key, lab in (("split_yoy", "ขาย vs บริหาร YoY"), ("split_qoq", "ขาย vs บริหาร QoQ")):
        s = p["sga"].get(key)
        if s:
            sl.append("**%s:** %s" % (lab, s["text"]))
    if p["sga"].get("long_run"):
        sl.append("**ระดับระยะยาว:** " + p["sga"]["long_run"]["text"])
    if p["sga"].get("selling_note"):
        sl.append(p["sga"]["selling_note"])
    for r in p["records"]:
        if r.get("kind") == "low":
            sl.append("📉 **%s**" % r["text"])
    d.ul(sl)
    ea = p.get("ecl_attrib")
    if ea:
        rows = [[r["label"], n2(r["prior"]), n2(r["cur"]), "%+.2f" % r["delta"]] for r in ea["rows"]]
        rows.append(["**รวมค่าเผื่อ ECL**", "**%s**" % n2(sum(r["prior"] for r in ea["rows"])), "**%s**" % n2(sum(r["cur"] for r in ea["rows"])),
                     "**%+.2f**" % ea["total_delta"]])
        if ea.get("ecl_ytd") is not None:
            rows.append(["ECL ในงบกระแสเงินสด %s" % be(p["ytd"]), "", n2(ea["ecl_ytd"]), ""])
        d.table(["ค่าเผื่อผลขาดทุนด้านเครดิต (หมายเหตุลูกหนี้, ล้านบาท)", ea["prior_label"], p["q_last_be"], "เปลี่ยนแปลง"], rows)
        if ea.get("aging"):
            rows = [[a["label"], n2(a["prior"]), n2(a["cur"]), "%+.2f" % a["delta"]] for a in ea["aging"]]
            if ea.get("over3"):
                rows.append(["**รวมค้างชำระเกิน 3 เดือน**", "**%s**" % n2(ea["over3"][1]), "**%s**" % n2(ea["over3"][0]),
                             "**%+.2f**" % (ea["over3"][0] - ea["over3"][1])])
            if ea.get("sso_accrued"):
                so = ea["sso_accrued"]
                rows.append(["รายได้ประกันสังคมค้างรับ", n2(so["prior"]), n2(so["cur"]), "%+.2f" % (so["cur"] - so["prior"])])
            d.table(["อายุลูกหนี้การค้า (บุคคลภายนอก, ล้านบาท)", ea["prior_label"], p["q_last_be"], "เปลี่ยนแปลง"], rows)
        d.p("<sub>ที่มา: หมายเหตุลูกหนี้การค้าและลูกหนี้หมุนเวียนอื่น, %s บรรทัด %s–%s (หน่วยในงบ พันบาท แปลงเป็นล้านบาท)</sub>" % (
            ea.get("file") or "-", (ea.get("lines") or ["?", "?"])[0], (ea.get("lines") or ["?", "?"])[1]))
    d.b.append(("nlist", narrative_items(nar.get("sga"))))

    d.h(3, "2.4 สะพานกำไรสุทธิ (Profit Bridge)")
    for key, lab in (("yoy", "YoY"), ("qoq", "QoQ")):
        b = p["bridges"].get(key)
        if not b:
            continue
        rows = [["กำไรสุทธิ %s" % be(b["base"]), n2(b["np0"])]] + [[n, "%+.2f" % v] for n, v in b["items"]] + [["กำไรสุทธิ %s" % be(q), n2(b["np1"])]]
        d.table(["สะพานกำไร %s (ล้านบาท)" % lab, "จำนวน"], rows, bold_rows=(0, len(rows) - 1))

    d.h(3, "2.5 เงินสด งบดุล และกระแสเงินสด")
    rows = []
    for k in ("cash_total", "debt_lease", "net_cash", "recv", "dso", "cfo", "capex", "fcf", "divp"):
        rows.append([LAB[k]] + [n2(g(x, k), 1 if k == "dso" else 2) for x in W])
    d.table(["รายการ (ล้านบาท)"] + [be(x) for x in W], rows)
    mk = p.get("market") or {}
    if mk.get("price"):
        d.p("ราคา %s บาท (%s): P/E TTM %s เท่า, P/BV %s เท่า, เงินสดสุทธิ %s บาท/หุ้น, ปันผลปีล่าสุด %s" % (
            mk["price"], mk.get("as_of") or "", n2(mk.get("pe_ttm")), n2(mk.get("pbv")), n2(mk.get("net_cash_ps")), p1(mk.get("yield"))))
    d.b.append(("nlist", narrative_items(nar.get("cash"))))

    d.h(3, "2.6 ผลงานสะสม %s เทียบ %s (YTD vs YTD ปีก่อน)" % (be(p["ytd"]), be(p["ytd_py"])))
    rows = []
    for r in p["ytd_rows"]:
        rows.append([r["label"], p1(r["py"]) if r["is_pct"] else n2(r["py"]), p1(r["cur"]) if r["is_pct"] else n2(r["cur"]),
                     pt(r.get("yoy_pt")) if r["is_pct"] else chg(r.get("yoy"))])
    d.table(["รายการ", be(p["ytd_py"]), be(p["ytd"]), "เปลี่ยนแปลง"], rows)
    if p["one_offs"]:
        d.ul(["รายการพิเศษหลังภาษี %s: %+.2f ลบ. — %s" % (be(o["period"]), o["amount_after_tax"], o.get("label", "")) for o in p["one_offs"]])

    nt = p.get("nature") or {}
    if nt:
        d.h(3, "2.7 ค่าใช้จ่ายตามลักษณะ (Expenses by Nature) — %s เทียบ %s" % (be(nt["ytd"]), be(nt["ytd_py"])))
        if nt.get("reason"):
            d.p("_%s_" % nt["reason"])
        rows, bold = [], []
        kinds = {"note": "หมายเหตุ", "cashflow": "งบกระแสเงินสด", "pl": "งบกำไรขาดทุน", "not_disclosed": "ไม่เปิดเผยในงบระหว่างกาล"}
        for r in nt["rows"]:
            lab = ("&nbsp;&nbsp;" + r["label"]) if r.get("sub") else r["label"]
            if r["cur"] is None and r["prior"] is None:
                rows.append([lab, "n/a", "n/a", "–", kinds.get(r["kind"], "")])
            else:
                ch = chg(r["yoy"]) if r.get("yoy") is not None else ("Δ %+.2f" % r["delta"] if r.get("delta") is not None else "–")
                rows.append([lab, n2(r["prior"]), n2(r["cur"]), ch, "%s %s" % (kinds.get(r["kind"], ""), ("[%s]" % r["src"]) if r.get("src") and r["kind"] != "pl" else "")])
            if r.get("bold"):
                bold.append(len(rows) - 1)
        d.table(["ค่าใช้จ่ายตามลักษณะ (งบรวม, ล้านบาท)", be(nt["ytd_py"]), be(nt["ytd"]), "เปลี่ยนแปลง", "ที่มา"], rows,
                align=["l", "r", "r", "r", "l"], bold_rows=bold)
        if nt.get("annual"):
            fys = nt["annual"]
            head = ["หมวด (หมายเหตุงบปี)"]
            for a in fys:
                head += [be(a["fy"]), "% รายได้"]
            rows = []
            for k, lab in (("staff", "เงินเดือนและผลประโยชน์พนักงาน"), ("da", "ค่าเสื่อมราคาและค่าตัดจำหน่าย"), ("doctor", "ค่าธรรมเนียมแพทย์"),
                           ("referral", "ค่ารักษาผู้ป่วยส่งต่อ"), ("medicine", "ยาและเวชภัณฑ์ใช้ไป")):
                row = [lab]
                for a in fys:
                    it = a["items"].get(k)
                    row += [n2(it["v"]) if it else "–", p1(it["pct_rev"]) if it else "–"]
                rows.append(row)
            row = ["**อื่น ๆ (รวมต้นทุน+ขาย+บริหาร − 5 หมวด)**"]
            for a in fys:
                if a.get("total_cost") is not None and len(a["items"]) == 5:
                    oth = a["total_cost"] - sum(it["v"] for it in a["items"].values())
                    row += [n2(oth), p1(oth / a["rev"]) if a["rev"] else "–"]
                else:
                    row += ["–", "–"]
            rows.append(row)
            d.table(head, rows, align=["l"] + ["r"] * (len(head) - 1))
            d.p("_ตัวเลขปีเต็มจากหมายเหตุค่าใช้จ่ายตามลักษณะในงบการเงินประจำปี (ใช้เป็นฐานสัดส่วน ไม่ใช่ค่าประมาณของงวดสะสม)_")
        d.b.append(("nlist", narrative_items(nar.get("nature"))))

    dv = p.get("dividend") or {}
    if dv.get("history"):
        d.h(3, "2.8 เงินปันผล อัตราการจ่าย และเงินสดต่อหุ้น")
        rows = [[be(h["fy"]), n2(h["dps"]), n2(h["eps"], 3), p1(h["payout"]), n2(h["np_owners"])] for h in dv["history"]]
        d.table(["ปีผลประกอบการ", "DPS (บาท)", "EPS (บาท)", "Payout", "กำไรสุทธิ (ลบ.)"], rows)
        items = []
        if dv.get("cash_ps") is not None:
            items.append("เงินสด + เงินลงทุนระยะสั้น %s ลบ. = %s บาท/หุ้น%s; เงินสดสุทธิ %s บาท/หุ้น (จำนวนหุ้น %s ล้านหุ้น%s)" % (
                n2(dv["cash_total"]), n2(dv["cash_ps"]), (" (%s ของราคา %s บาท)" % (p1(dv["cash_to_price"]), dv["price"])) if dv.get("cash_to_price") else "",
                n2(dv["net_cash_ps"]), n2(dv["shares_mn"]), ("; " + dv["shares_note"]) if dv.get("shares_note") else ""))
        if dv.get("share_advance"):
            sa = dv["share_advance"]
            items.append("เงินรับล่วงหน้าค่าหุ้นจากการใช้สิทธิ %s ลบ. ใน %s [%s] — จำนวนหุ้นจะเพิ่ม ใช้หุ้นหลังแปลงสภาพเมื่อคิดต่อหุ้น" % (
                n2(sa["cur"]), be(p["ytd"]), sa["src"]))
        d.ul(items)
        if dv.get("scenarios"):
            rows = [[p1(sc["payout"]), n2(sc["dps"], 3), chg(sc.get("dps_growth")), p1(sc["yield"])] for sc in dv["scenarios"]]
            d.table(["Payout (สมมติ)", "DPS ปีนี้ (บาท)", "เทียบ DPS ปีก่อน", "Yield ที่ราคาปัจจุบัน"], rows)
            d.p("_กำไรปกติทั้งปีคาด %s ลบ. (%s เทียบปีก่อน %s ลบ.). %s_" % (
                n2(dv["fy_core_np_est"]), chg(dv.get("fy_growth_est")), n2(dv.get("fy_core_np_py")), dv["method"]))
        d.b.append(("nlist", narrative_items(nar.get("dividend"))))

    pr = [r for r in (p.get("peers") or []) if r.get("rev") is not None]
    if pr:
        d.h(3, "2.9 เทียบกลุ่มเดียวกัน (%s, %s) — คำนวณจากงบของแต่ละบริษัท" % (p.get("category_name", ""), be(q)))
        me = {"ticker": "**%s**" % p["ticker"], "q": q}
        L0, Lp = p["lines"].get(q, {}), p["lines"].get(p["q_py"], {})
        ph = ((p.get("angles") or {}).get("phase") or {})
        v = (ex.get("valuation") or {})
        sso_me = next(((r["vals"].get(q) or 0) / L0["rev"] for r in p["mix_rows"] if r["id"] == "sso" and L0.get("rev") and r["vals"].get(q)), None)
        rows = [["**%s**" % p["ticker"], n2(L0.get("rev")), chg(pct_(L0.get("rev"), Lp.get("rev"))), p1(sso_me), p1(L0.get("gpm")),
                 pt((L0["gpm"] - Lp["gpm"]) if L0.get("gpm") is not None and Lp.get("gpm") is not None else None), p1(L0.get("sga_pct")),
                 chg(pct_(L0.get("core_pbt_x") if L0.get("core_pbt_x") is not None else L0.get("core_pbt"),
                          Lp.get("core_pbt_x") if L0.get("core_pbt_x") is not None else Lp.get("core_pbt"))),
                 n2(ph.get("mult"), 1), n2(L0.get("dso"), 0), n2(v.get("pe"), 1), n2(v.get("peg"))]]
        for r in pr:
            rows.append([r["ticker"], n2(r["rev"]), chg(r.get("rev_yoy")), p1(r.get("sso_share")), p1(r.get("gpm")), pt(r.get("gpm_yoy_pt")), p1(r.get("sga_pct")),
                         chg(r.get("pbt_yoy")), n2(r.get("mult"), 1), n2(r.get("dso"), 0), n2(r.get("pe"), 1), n2(r.get("peg"))])
        d.table(["บริษัท", "รายได้ (ลบ.)", "รายได้ YoY", "สัดส่วน SSO", "GPM", "GPM YoY", "SG&A/รายได้", "Core PBT YoY", "กำไรโต/รายได้โต (TTM, เท่า)",
                 "DSO (วัน)", "P/E TTM", "PEG"], rows, align=["l"] + ["r"] * 11)
        miss = [r["ticker"] for r in (p.get("peers") or []) if r.get("missing") or r.get("not_reported") or r.get("error")]
        d.p("_Core PBT = GP − SG&A − ต้นทุนทางการเงิน (ก่อน ECL/รายการพิเศษเมื่อมีข้อมูล); DSO ของบริษัทอื่นรวมรายได้ค้างรับที่แยกบรรทัด; "
            "P/E ใช้ราคาจาก factsheet ที่ไม่ห่างจากงวดเกิน 150 วัน%s_" % ((" | ยังไม่มีข้อมูล: " + ", ".join(miss)) if miss else ""))
        d.b.append(("nlist", narrative_items(nar.get("peers_notes"))))

    # ---------------------------------------------------------------- 3. outlook
    d.h(2, "🔮 3. แนวโน้ม 4 ไตรมาสข้างหน้า (Outlook)")
    sm = p["season_meta"]
    d.h(3, "3.1 ฤดูกาลและค่าประมาณเชิงกลไก (Statistical, ไม่ใช่ Guidance)")
    rows = []
    out = nar.get("outlook") or {}
    for s in p["season"]:
        t, src, ext = item_text(out.get(s["q"]) or out.get(be(s["q"])) or "")
        if src:
            t = "%s <sub>[%s]</sub>" % (t, src)
        if ext:
            t = '<span style="color:%s;font-weight:bold">%s</span>' % (RED, t)
        rows.append([be(s["q"]) + "F", n2(s["rev_base"]), n2(s["rev_proj"]), chg(s["qoq_median"]), n2(s["core_np_proj"]), t or "–"])
    d.table(["ไตรมาส", "รายได้ไตรมาสเดียวกันปีก่อน", "ค่าประมาณรายได้", "QoQ มัธยฐานในอดีต", "ค่าประมาณกำไรปกติ", "ปัจจัยจากเอกสาร"], rows,
            align=["l", "r", "r", "r", "r", "l"])
    d.p("_วิธีคำนวณ: %s; อัตราเติบโตที่ใช้ = %s %s (รายได้), %s (กำไรปกติ). เป็นค่าประมาณเชิงสถิติ ไม่ใช่ประมาณการของบริษัท_" % (
        sm["method"], sm["rev_growth_basis_label"], chg(sm["rev_growth_basis"]), chg(sm["np_growth_basis"])))
    d.h(3, "3.2 ปัจจัยบวกระยะสั้น (Catalysts)")
    d.b.append(("nlist", narrative_items(nar.get("catalysts")) or [("txt", "_ต้องอ่าน MD&A/Opportunity Day — ไม่มีในโหมดอัตโนมัติ_", None)]))
    d.h(3, "3.3 ความเสี่ยงระยะสั้น (Risks)")
    d.b.append(("nlist", narrative_items(nar.get("risks")) or [("txt", "_ต้องอ่าน MD&A/Opportunity Day — ไม่มีในโหมดอัตโนมัติ_", None)]))

    # ---------------------------------------------------------------- 4. takeaways
    d.h(2, "🎯 4. ข้อสรุปและสิ่งที่ต้องติดตาม (Actionable Takeaways)")
    rows = [[c["name"], "%+.1f" % c["points"], c["why"]] for c in m["components"]]
    rows.append(["**คะแนนรวม (เริ่มที่ 5.0)**", "**%.1f**" % m["score"], "**%s**" % m["label"]])
    d.table(["องค์ประกอบคะแนนโมเมนตัม", "คะแนน", "ข้อมูล"], rows, align=["l", "r", "l"])
    d.b.append(("nlist", narrative_items(nar.get("takeaways"))))
    if nar.get("watchlist"):
        d.p("**ประเด็นต้องติดตามใน %s:**" % be(qadd(q, 1)))
        d.b.append(("nlist", narrative_items(nar.get("watchlist"))))

    # ---------------------------------------------------------------- 5. flags & verification
    d.h(2, "⚠️ 5. Red Flags, ข้อมูลที่ขาด และรายการนอกเอกสารทางการ")
    expl = nar.get("explanations") or {}
    fl = []
    for f in p["flags"]:
        e = expl.get(f["id"])
        if e:
            t, src, ext = item_text(e)
            partial = isinstance(e, dict) and e.get("status") == "partial"
            icon = "⚠️ อธิบายได้บางส่วน:" if partial or not src else "✅"
            fl.append("%s %s — %s%s" % (icon, f["text"], t, " [%s]" % src if src else " (ไม่มีแหล่งอ้างอิง)"))
        else:
            fl.append("🚩 **Red Flag (Unexplained):** %s — ยังไม่มีคำอธิบายจากเอกสาร" % f["text"])
        if f.get("hint"):
            fl[-1] += " <sub>ข้อมูลจากงบ: %s</sub>" % f["hint"]
    if fl:
        d.p("**การเปลี่ยนแปลงที่เกิน ±10% YoY หรือสัญญาณผิดปกติ (ต้องมีคำอธิบายจากเอกสาร):**")
        d.ul(fl)
    if problems:
        d.callout("warning", "ตัวเลขในบทวิเคราะห์ที่ตรวจสอบกับชุดข้อมูลไม่ได้ (%d รายการ)" % len(problems), problems[:25])
    if p["gaps"]:
        d.p("**ข้อมูลที่ขาด/ข้อสังเกตจากการดึงข้อมูล:**")
        d.ul(p["gaps"][:20])
    ext_items = list(nar.get("external") or [])
    for sect in ("summary", "revenue", "mix_notes", "op_leverage", "sga", "cash", "nature", "dividend", "catalysts", "risks", "takeaways", "watchlist"):
        for it in nar.get(sect) or []:
            t, src, ext = item_text(it)
            if ext and not any(isinstance(e, dict) and e.get("item") == t for e in ext_items):
                ext_items.append({"item": t, "value": "", "source": src or "–", "status": "ยังไม่ยืนยันจากเอกสารทางการ"})
    if ext_items:
        rows = [[str(i + 1), '<span style="color:%s;font-weight:bold">%s</span>' % (RED, e.get("item", "")), e.get("value", ""), e.get("source", ""),
                 e.get("status", "")] for i, e in enumerate(ext_items)]
        d.table(["#", "รายการ/สมมติฐาน", "ค่า", "แหล่งที่มา", "สถานะ"], rows, align=["l", "l", "r", "l", "l"])
    else:
        d.p("ไม่มีตัวเลขหรือสมมติฐานจากนอกเอกสารทางการในรายงานนี้")

    pp = p.get("papers") or {}
    n_off = len(pp.get("stock") or []) + len(pp.get("sector") or [])
    if n_off or pp.get("stock_undated"):
        line = "**บทวิเคราะห์ภายนอก (แหล่งที่ 2):** มีบทวิเคราะห์ในช่วงของไตรมาสนี้ %d ฉบับ (รายหุ้น %d, รายอุตสาหกรรม %d)" % (
            n_off, len(pp.get("stock") or []), len(pp.get("sector") or []))
        if pp.get("stock_undated"):
            line += " | อีก %d ฉบับไม่มีวันที่จึงไม่ได้นำมาใช้" % len(pp["stock_undated"])
        if str(nar.get("papers_note") or "").strip():
            line += " — %s" % str(nar["papers_note"]).strip()
        d.p(line)
    cfs = [c for c in nar.get("conflicts") or [] if isinstance(c, dict)]
    if cfs:
        VL = {"conflict": "⚠️ ขัดแย้ง", "definition": "ต่างนิยาม", "outdated": "ข้อมูลเก่ากว่า", "consistent": "✅ สอดคล้อง", "unverifiable": "ตรวจสอบไม่ได้"}
        d.h(3, "ข้อมูลจากแหล่งที่ 2 และ 3 เทียบกับเอกสารที่ยื่นต่อ ตลท. (แหล่งที่ 1)")
        d.p("_แหล่งที่ 1 = งบการเงิน, MD&A, Oppday, factsheet ของ ตลท. (ใช้ในทุกตาราง). แหล่งที่ 2 = ข่าว บทสัมภาษณ์ คลิป บทวิเคราะห์ภายนอก "
            "(ใช้เป็นบริบทเท่านั้น). แหล่งที่ 3 = ความเห็นนักลงทุนในเว็บบอร์ด (ใช้เป็นประเด็นให้ตรวจสอบเท่านั้น). เมื่อขัดกัน รายงานยึดแหล่งที่ 1 และแสดงความต่างไว้ที่นี่_")
        tier = lambda c: ("แหล่งที่ 3 (เว็บบอร์ด)" if "third_source" in str(c.get("second_src", "")) else
                          "%s (นักวิเคราะห์อ้างอิง)" % S.row_analyst(c, p.get("analyst_notes"))
                          if "analyst_notes" in str(c.get("second_src", "")) else "แหล่งที่ 2")
        rows = [[VL.get(c.get("verdict", "conflict"), c.get("verdict", "")), "%s<br><small>%s</small>" % (c.get("topic", ""), tier(c)),
                 '<span style="color:%s">%s</span><br><small>%s</small>' % (RED, c.get("second", ""), c.get("second_src", "")),
                 "%s<br><small>%s</small>" % (c.get("primary", ""), c.get("primary_src", "")), c.get("note", "")] for c in cfs]
        d.table(["ผล", "ประเด็น", "แหล่งที่ 2/3 กล่าวว่า", "เอกสาร ตลท. (แหล่งที่ 1)", "ข้อสังเกต"], rows, align=["l", "l", "l", "l", "l"])
    elif p.get("second_sources"):
        d.p("_มีแหล่งข้อมูลชุดที่ 2 จำนวน %d ไฟล์ — ยังไม่ได้บันทึกผลการเทียบกับเอกสาร ตลท. ใน `conflicts`_" % len(p["second_sources"]))

    d.h(3, "ภาคผนวก: บรรทัดอ้างอิงของตัวเลขหลัก %s" % p["q_last_be"])
    src = p["sources"].get("fact_src") or {}
    rows = []
    for k in ("rev_hosp", "cogs", "selling", "admin", "np_owners", "cf_da", "cf_ecl", "cash", "st_invest", "receivables", "cfo"):
        s = src.get("%s|%s" % (k, q))
        if s:
            rows.append([k, s])
    if rows:
        d.table(["รายการ", "แหล่งที่มา (ไฟล์:บรรทัด)"], rows, align=["l", "l"])
    return d


def _compress_checks(checks):
    mix = [c for c in checks if c["label"].startswith("โครงสร้างรายได้")]
    other = [c for c in checks if not c["label"].startswith("โครงสร้างรายได้")]
    if mix:
        okn = sum(1 for c in mix if c["ok"])
        other.append({"label": "โครงสร้างรายได้ MD&A = รายได้ในงบ ±1 ลบ. (%d/%d งวด)" % (okn, len(mix)), "ok": okn == len(mix)})
    return other


def _mix_totals(p, rows_src):
    """{short quarter label: total} with the same definition as the table's share column (elims subtracted)."""
    out = {}
    for x in p["ext"]:
        t = sum(r["vals"].get(x) or 0 for r in rows_src if r["id"] != "elim") - sum(r["vals"].get(x) or 0 for r in rows_src if r["id"] == "elim")
        if t:
            out[sbe(x)] = t
    return out


def _mix_table(d, p, rows_src, title):
    W, q, py, pq = p["window"], p["q_last"], p["q_py"], p["q_pq"]
    tot = {x: sum(r["vals"].get(x) or 0 for r in rows_src if r["id"] != "elim") - sum(r["vals"].get(x) or 0 for r in rows_src if r["id"] == "elim")
           for x in p["ext"]}
    rows = []
    for r in rows_src:
        v = r["vals"]
        sign = -1 if r["id"] == "elim" else 1
        share = (v.get(q) / tot[q]) if v.get(q) is not None and tot.get(q) and r["id"] != "elim" else None
        rows.append([r["label"]] + [n2(sign * v[x]) if v.get(x) is not None else "–" for x in W] +
                    [p1(share), chg(pct(v.get(q), v.get(pq))), chg(pct(v.get(q), v.get(py)))])
    rows.append(["**รวม (กระทบยอดกับงบ)**"] + ["**%s**" % n2(tot[x]) if tot.get(x) else "–" for x in W] + ["100%", chg(pct(tot.get(q), tot.get(pq))), chg(pct(tot.get(q), tot.get(py)))])
    d.table([title] + [be(x) for x in W] + ["สัดส่วน %s" % be(q), "QoQ", "YoY"], rows)


# ------------------------------------------------------------------------------------------ markdown
def to_md(d):
    out = []
    for b in d.b:
        k = b[0]
        if k == "h":
            out.append("\n" + "#" * b[1] + " " + b[2] + "\n")
        elif k == "p":
            out.append(b[1] + "\n")
        elif k == "ul":
            out.append("\n".join("- " + i for i in b[1]) + "\n")
        elif k == "nlist":
            if b[1]:
                out.append("\n".join("- " + _md_item(i) for i in b[1]) + "\n")
        elif k == "table":
            head, rows, align, bold = b[1], b[2], b[3], b[4]
            out.append("| " + " | ".join(head) + " |")
            out.append("| " + " | ".join(":---" if a == "l" else "---:" for a in align) + " |")
            for i, r in enumerate(rows):
                cells = [("**%s**" % c if i in bold and c and not str(c).startswith("**") else str(c)) for c in r]
                out.append("| " + " | ".join(c.replace("|", "/") for c in cells) + " |")
            out.append("")
        elif k == "callout":
            out.append("> [!%s]\n> **%s**\n" % ("TIP" if b[1] == "tip" else "WARNING", b[2]) + "\n".join("> - " + x for x in b[3]) + "\n")
        elif k == "chart":
            pass
        elif k == "hr":
            out.append("---\n")
        elif k == "raw":
            if b[2]:
                out.append(b[2])
    return "\n".join(out)


def _md_item(i):
    kind, t, src = i
    if kind == "ext":
        return '<span style="color: %s; font-weight: bold;">%s</span>%s' % (RED, t, " [%s]" % src if src else "")
    if kind == "src":
        return "%s [%s]" % (t, src)
    return t


# ------------------------------------------------------------------------------------------ html
CSS = """
:root{--surface:#fcfcfb;--panel:#ffffff;--ink:#0b0b0b;--ink2:#52514e;--muted:#8a8984;--line:#e4e3de;--head:#2F5496;--head-ink:#fff;
--band:#eef2fa;--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#8a63c9;--good:#0ca30c;--bad:#d03b3b;--red:#8B0000;--tip:#e9f6ec;--warn:#fdf1e7}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--surface:#1a1a19;--panel:#222220;--ink:#fff;--ink2:#c3c2b7;--muted:#8f8e86;
--line:#3a3a36;--head:#2c4f8f;--band:#26303f;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#a083d9;--red:#ff8a80;--tip:#1f3326;--warn:#3a2a1c}}
:root[data-theme="dark"]{--surface:#1a1a19;--panel:#222220;--ink:#fff;--ink2:#c3c2b7;--muted:#8f8e86;--line:#3a3a36;--head:#2c4f8f;--band:#26303f;
--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#a083d9;--red:#ff8a80;--tip:#1f3326;--warn:#3a2a1c}
*{box-sizing:border-box}body{margin:0;background:var(--surface);color:var(--ink);font:15px/1.6 "Segoe UI","Sarabun",system-ui,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 64px}h1{font-size:24px;line-height:1.3;margin:8px 0 4px}
h2{font-size:19px;margin:36px 0 10px;padding-bottom:6px;border-bottom:2px solid var(--head)}h3{font-size:16px;margin:24px 0 8px;color:var(--ink2)}
p,li{color:var(--ink)}ul{padding-left:20px}.tw{overflow-x:auto;margin:10px 0 16px;border:1px solid var(--line);border-radius:8px;background:var(--panel)}
table{border-collapse:collapse;width:100%;font-size:13.5px;font-variant-numeric:tabular-nums}th{background:var(--head);color:var(--head-ink);font-weight:600;
padding:7px 10px;white-space:nowrap}td{padding:6px 10px;border-top:1px solid var(--line);white-space:nowrap}td.l,th.l{text-align:left;white-space:normal;min-width:110px;overflow-wrap:anywhere}td.l:first-child{min-width:140px}td.w,th.w{white-space:normal;min-width:90px;overflow-wrap:anywhere}table.wide{font-size:12px}table.wide th,table.wide td{padding:5px 6px}table.wide td.l{min-width:90px}table.wide td.w,table.wide th.w{min-width:64px}
td.r,th.r{text-align:right}tr.b td{font-weight:700;background:var(--band)}.callout{border-radius:8px;padding:10px 14px;margin:12px 0}
.callout.tip{background:var(--tip)}.callout.warning{background:var(--warn)}.callout ul{margin:4px 0}.charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px;margin:14px 0;justify-items:start}
.chart{max-width:560px;width:100%;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:10px 12px}.chart h4{margin:0 0 6px;font-size:13.5px;color:var(--ink2);font-weight:600}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:12.5px;color:var(--ink2);margin-top:4px}.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px}
svg text{fill:var(--ink2);font-size:11px}svg .grid{stroke:var(--line)}svg .hit:hover+.mark,svg g.m:hover .mark{opacity:.75}.ext{color:var(--red);font-weight:700}
sub{color:var(--muted)}.src{color:var(--muted);font-size:12px}
"""
SERIES = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)"]


def _inline(t):
    t = H.escape(t, quote=False)
    t = t.replace("&lt;sub&gt;", "<sub>").replace("&lt;/sub&gt;", "</sub>").replace("&lt;br&gt;", "<br>")
    t = re.sub(r"&lt;span style=&quot;color:\s*#8B0000[^&]*?&quot;&gt;(.*?)&lt;/span&gt;", r'<span class="ext">\1</span>', t)
    t = re.sub(r'&lt;span style="color:\s*#8B0000[^"]*"&gt;(.*?)&lt;/span&gt;', r'<span class="ext">\1</span>', t)
    t = re.sub(r'&lt;span class="(vz-[a-z]+)"&gt;(.*?)&lt;/span&gt;', r'<span class="\1">\2</span>', t)
    links = []
    def _lk(m):
        links.append('<a href="%s" target="_blank" rel="noopener">%s</a>' % (m.group(2).replace('"', "%22"), m.group(1)))
        return "\x00%d\x00" % (len(links) - 1)
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", _lk, t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<![\w*])_(.+?)_(?![\w*])", r"<i>\1</i>", t)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub("\x00(\\d+)\x00", lambda m: links[int(m.group(1))], t)
    return t.replace("&amp;nbsp;", "&nbsp;")


def _svg_chart(spec):
    ser = [s for s in spec["series"] if any(v is not None for _, v in s["vals"])]
    if not ser:
        return ""
    labels = [l for l, _ in ser[0]["vals"]]
    n = len(labels)
    Wd, Ht, L, R, T, B = (540 if spec.get("pct_total") else 420), 230, 46, 10, 12, 30
    pw, ph = Wd - L - R, Ht - T - B
    if spec["type"] == "stack":
        tops = [sum((s["vals"][i][1] or 0) for s in ser) for i in range(n)]
        vmax, vmin = max(tops) or 1, 0
    else:
        allv = [v for s in ser for _, v in s["vals"] if v is not None]
        vmax, vmin = max(allv), min(0, min(allv)) if spec["type"] == "bars" else min(allv)
        if spec["type"] == "lines":
            pad = (vmax - vmin) * 0.15 or abs(vmax) * 0.1 or 1
            vmin, vmax = max(0, vmin - pad), vmax + pad
    span = (vmax - vmin) or 1
    y = lambda v: T + ph - (v - vmin) / span * ph
    fmt = (lambda v: "%.0f%%" % (v * 100)) if spec.get("pct") else (lambda v: "{:,.0f}".format(v))
    out = ['<svg viewBox="0 0 %d %d" width="100%%" role="img" aria-label="%s">' % (Wd, Ht, H.escape(spec["title"]))]
    for k in range(5):
        v = vmin + span * k / 4
        out.append('<line class="grid" x1="%d" x2="%d" y1="%.1f" y2="%.1f"/><text x="%d" y="%.1f" text-anchor="end">%s</text>' % (
            L, Wd - R, y(v), y(v), L - 6, y(v) + 4, fmt(v)))
    bw = pw / n
    for i, lab in enumerate(labels):
        out.append('<text x="%.1f" y="%d" text-anchor="middle">%s</text>' % (L + bw * (i + .5), Ht - 12, H.escape(lab)))
    if spec["type"] in ("bars", "stack"):
        w = min(44, bw * 0.72) if spec.get("pct_total") else min(34, bw * 0.6)
        for i in range(n):
            x = L + bw * (i + .5) - w / 2
            base = vmin
            for si, s in enumerate(ser):
                v = s["vals"][i][1]
                if v is None:
                    continue
                y0 = y(base + v) if spec["type"] == "stack" else y(max(v, 0))
                y1 = y(base) if spec["type"] == "stack" else y(min(v, 0))
                h = max(0.5, y1 - y0 - (2 if spec["type"] == "stack" and si < len(ser) - 1 else 0))
                tot = (spec.get("pct_total") or {}).get(labels[i])
                share = v / tot if tot else None
                tip = "%s — %s: %s%s" % (labels[i], s["name"], fmt(v), (" (%.1f%%)" % (share * 100)) if share is not None else "")
                col = SERIES[si % len(SERIES)]
                out.append('<g class="m"><title>%s</title><rect class="mark" x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="3" fill="%s"/></g>' % (
                    H.escape(tip), x, y0, w, h, col))
                if share is not None and h >= 13:
                    out.append('<text x="%.1f" y="%.1f" text-anchor="middle" dominant-baseline="central" '
                               'style="fill:#fff;font-size:10px;font-weight:600;pointer-events:none">%.1f%%</text>' % (
                                   x + w / 2, y0 + h / 2, share * 100))
                if spec["type"] == "stack":
                    base += v
        if spec["type"] == "bars" and len(ser) == 1:
            i = n - 1
            v = ser[0]["vals"][i][1]
            if v is not None:
                out.append('<text x="%.1f" y="%.1f" text-anchor="middle" style="fill:var(--ink);font-weight:600">%s</text>' % (
                    L + bw * (i + .5), y(max(v, 0)) - 4, fmt(v)))
    else:
        for si, s in enumerate(ser):
            pts = [(L + bw * (i + .5), y(v), v) for i, (_, v) in enumerate(s["vals"]) if v is not None]
            col = SERIES[si % len(SERIES)]
            out.append('<polyline fill="none" stroke="%s" stroke-width="2" points="%s"/>' % (col, " ".join("%.1f,%.1f" % (a, b) for a, b, _ in pts)))
            for (a, b, v), (lab, _) in zip(pts, [sv for sv in s["vals"] if sv[1] is not None]):
                out.append('<g class="m"><title>%s — %s: %s</title><circle class="mark" cx="%.1f" cy="%.1f" r="4" fill="%s" stroke="var(--panel)" stroke-width="2"/></g>' % (
                    H.escape(lab), H.escape(s["name"]), fmt(v), a, b, col))
            if pts:
                a, b, v = pts[-1]
                out.append('<text x="%.1f" y="%.1f" text-anchor="end" style="fill:var(--ink)">%s</text>' % (a, b - 8, fmt(v)))
    out.append("</svg>")
    leg = ""
    if len(ser) > 1:
        leg = '<div class="legend">' + "".join('<span><i style="background:%s"></i>%s</span>' % (SERIES[i % len(SERIES)], H.escape(s["name"])) for i, s in enumerate(ser)) + "</div>"
    note = '<div class="src">%s</div>' % H.escape(spec["note"]) if spec.get("note") else ""
    return '<div class="chart"><h4>%s</h4>%s%s%s</div>' % (H.escape(spec["title"]), "".join(out), leg, note)


def to_html(d, title):
    out = ['<!doctype html><html lang="th"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
           "<title>%s</title><style>%s</style></head><body><main>" % (H.escape(title), CSS)]
    charts = []

    def flush():
        if charts:
            out.append('<div class="charts">' + "".join(charts) + "</div>")
            charts.clear()
    for b in d.b:
        k = b[0]
        if k == "chart":
            charts.append(_svg_chart(b[1]))
            continue
        flush()
        if k == "h":
            out.append("<h%d>%s</h%d>" % (b[1], _inline(b[2]), b[1]))
        elif k == "p":
            out.append("<p>%s</p>" % _inline(b[1]))
        elif k == "ul":
            out.append("<ul>" + "".join("<li>%s</li>" % _inline(i) for i in b[1]) + "</ul>")
        elif k == "nlist":
            if b[1]:
                out.append("<ul>" + "".join("<li>%s</li>" % _html_item(i) for i in b[1]) + "</ul>")
        elif k == "table":
            head, rows, align, bold = b[1], b[2], b[3], b[4]
            def _cls(a, c, lim):     # long text in a number column wraps instead of widening the table
                return a + (" w" if a != "l" and len(re.sub(r"<[^>]+>|\*\*", "", str(c))) > lim else "")
            t = ['<div class="tw"><table%s><thead><tr>' % (' class="wide"' if len(head) > 9 else "") + "".join('<th class="%s">%s</th>' % (_cls(a, h, 14), _inline(h)) for h, a in zip(head, align)) + "</tr></thead><tbody>"]
            for i, r in enumerate(rows):
                isb = i in bold or str(r[0]).startswith("**")
                t.append('<tr%s>' % (' class="b"' if isb else "") + "".join('<td class="%s">%s</td>' % (_cls(a, c, 18), _inline(str(c).replace("**", "") if isb else str(c)))
                                                                       for c, a in zip(r, align)) + "</tr>")
            t.append("</tbody></table></div>")
            out.append("".join(t))
        elif k == "callout":
            out.append('<div class="callout %s"><b>%s</b><ul>%s</ul></div>' % (b[1], _inline(b[2]), "".join("<li>%s</li>" % _inline(x) for x in b[3])))
        elif k == "hr":
            out.append("<hr>")
        elif k == "raw":
            out.append(b[1])
    flush()
    out.append("</main></body></html>")
    return "".join(out)


def _html_item(i):
    kind, t, src = i
    s = _inline(t)
    if kind == "ext":
        s = '<span class="ext">%s</span>' % s
    if src:
        s += ' <span class="src">[%s]</span>' % H.escape(src)
    return s


# ------------------------------------------------------------------------------------------ write
def next_version(outdir, stem):
    vs = [int(m.group(1)) for f in os.listdir(outdir) for m in [re.match(re.escape(stem) + r"-v(\d+)\.(md|html)$", f)] if m]
    return max(vs, default=0) + 1


def write(p, nar, outdir, problems=(), version=None):
    d = build_doc(p, nar, list(problems))
    y, q = int(p["q_last"][:4]), p["q_last"][-1]
    stem = "%s_Snapshot_Report_Q%s_%d" % (p["ticker"], q, y + 543)
    v = int(version) if version else next_version(outdir, stem)
    md_p = os.path.join(outdir, "%s-v%d.md" % (stem, v))
    html_p = os.path.join(outdir, "%s-v%d.html" % (stem, v))
    open(md_p, "w", encoding="utf-8").write(to_md(d))
    open(html_p, "w", encoding="utf-8").write(to_html(d, "%s Snapshot %s" % (p["ticker"], p["q_last_be"])))
    return md_p, html_p
