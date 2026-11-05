"""deepdive_val.py - computed valuation block (Pop's downside / upside test + end-state dividend value).

Every number is computed here from the data pack and the assumptions file (`valuation` key); the narrative never
types them.  This is a scenario range, NOT a target price (the report rule: no target price, no buy/sell advice).

Pop's method (GLOSSARY: downside test, upside test, margin of safety):
  downside  = normal EPS (TTM) after a profit shock x the lowest P/E in sight          (what is left if the thesis fails)
  base      = FY1 forecast EPS x today's P/E                                          (no re-rating)
  upside    = FY1 forecast EPS x same-category peer median P/E                        (profit after operating leverage)
  end-state = DPS at the harvest-phase payout / (cost of equity - g)                   (value of the dividend stream)
The cost of equity (CAPM = rf + beta x ERP) is the analyst overlay, not a K. Pop rule, and is labelled so.
"""
from statistics import median

OVERLAY = "ส่วนเสริมของนักวิเคราะห์"


def compute(p):
    v = (p.get("expect") or {}).get("valuation") or {}
    m = p.get("market") or {}
    a = p.get("val_assumptions") or {}
    price, sh, pe = m.get("price"), m.get("shares_mn"), v.get("pe")
    if not (price and sh and pe):
        return {"ok": False, "why": "ไม่มีราคา จำนวนหุ้น หรือ P/E ในชุดข้อมูล"}
    eps_ttm = price / pe                                   # normal (core) EPS, trailing four quarters
    problems = []
    peers = [r["pe"] for r in p.get("peers") or []
             if r.get("pe") and r.get("category") == p.get("category") and r.get("ticker") != p["ticker"]]
    if len(peers) < 3:
        problems.append("คู่แข่งหมวดเดียวกันที่มี P/E น้อยกว่า 3 ราย (%d) จึงไม่คำนวณกรณีบน" % len(peers))
    pe_lo = min([pe] + peers) if peers else pe
    pe_med = median(peers) if len(peers) >= 3 else None
    fc = ((a.get("forecast") or {}).get("fy1") or {})
    eps_fy1 = fc["np"] / sh if fc.get("np") else None
    shock = min((a.get("sensitivity") or {}).get("eps_growth") or [-0.10])
    dps = m.get("dps_last_fy")
    dy = dps / price if dps else 0.0

    def row(name, eps, mult, basis):
        if eps is None or mult is None:
            return None
        val = eps * mult
        return {"name": name, "eps": eps, "pe": mult, "value": val, "chg": val / price - 1, "basis": basis}

    sc = [row("กรณีลบ (Downside)", eps_ttm * (1 + shock), pe_lo,
              "EPS กำไรปกติ TTM %+.0f%% x P/E ต่ำสุดที่เห็น (ตัวเราหรือคู่แข่งหมวดเดียวกัน)" % (shock * 100)),
          row("กรณีฐาน (ไม่ปรับ P/E)", eps_fy1, pe,
              "EPS ประมาณการปีหน้า (FY1) x P/E ปัจจุบัน"),
          row("กรณีบวก (Upside)", eps_fy1, pe_med,
              "EPS ประมาณการปีหน้า (FY1) x P/E มัธยฐานคู่แข่งหมวดเดียวกัน (%d ราย)" % len(peers))]
    sc = [s for s in sc if s]
    for s in sc:
        s["total"] = s["chg"] + dy                         # one year of dividend at last year's DPS, held flat

    out = {"ok": True, "price": price, "eps_ttm": eps_ttm, "eps_fy1": eps_fy1, "pe_now": pe, "pe_low": pe_lo, "pe_med": pe_med,
           "n_peers": len(peers), "shock": shock, "dps": dps, "yield": dy, "scenarios": sc, "problems": problems,
           "fy1_label": fc.get("label")}
    if sc and sc[0]["total"] is not None and sc[2:] and sc[2]["total"]:
        pass

    # end-state dividend value: dividend stream of a harvested, mature business, discounted at CAPM cost of equity
    rf, beta, erp, g = (a.get(k) for k in ("rf", "beta", "erp", "g"))
    if None not in (rf, beta, erp, g) and eps_fy1:
        ke = rf + beta * erp
        out["ke"], out["g"] = ke, g
        if ke > g:
            es = []
            pays = [("ปันผลตามปีล่าสุด", a.get("payout"))] + [("สถานการณ์จ่ายสูง", x) for x in (0.7, 0.9)]
            for nm, po in pays:
                if po:
                    d_ = eps_fy1 * po
                    es.append({"name": nm, "payout": po, "dps": d_, "value": d_ / (ke - g), "chg": d_ / (ke - g) / price - 1})
            out["end_state"] = es
        else:
            problems.append("Ke ไม่มากกว่า g จึงไม่คำนวณมูลค่าปันผลปลายทาง")
    return out


def render(d, p):
    """Section 11.1: scenario table. Uses deepdive_viz writer `d` (d.h / d.table / d.p)."""
    b = p.get("val_block") or {}
    d.h(3, "11.1 ช่วงมูลค่าตามกรณี (ทดสอบด้านลบ/ด้านบวก)")
    if not b.get("ok"):
        d.p("_ไม่คำนวณ: %s_" % b.get("why", "ข้อมูลไม่พอ"))
        return
    f2 = lambda x: "–" if x is None else "%.2f" % x
    pc = lambda x: "–" if x is None else "%+.1f%%" % (x * 100)
    d.table(["กรณี", "EPS (บาท)", "P/E (เท่า)", "มูลค่า/หุ้น (บาท)", "เทียบราคา", "รวมปันผล 1 ปี", "ที่มา"],
            [[s["name"], f2(s["eps"]), "%.1f" % s["pe"], f2(s["value"]), pc(s["chg"]), pc(s["total"]), s["basis"]] for s in b["scenarios"]],
            align=["l", "r", "r", "r", "r", "r", "l"])
    d.p("_ราคา %s บาท; ปันผลปีล่าสุด %s บาท (%s) ถือคงที่; ค่าทั้งหมด [คำนวณ] จากชุดข้อมูลและไฟล์สมมติฐาน ไม่ใช่ราคาเป้าหมาย%s_" % (
        f2(b["price"]), f2(b.get("dps")), "%.1f%%" % (b["yield"] * 100),
        ("; EPS ปีหน้ามาจากประมาณการของผู้วิเคราะห์ใน assumptions (%s)" % b["fy1_label"]) if b.get("fy1_label") else ""))
    up = next((x for x in b["scenarios"] if x["name"].startswith("กรณีบวก")), None)
    dn = next((x for x in b["scenarios"] if x["name"].startswith("กรณีลบ")), None)
    if up and dn:
        d.p("อัตราส่วนผลได้ด้านบวกต่อด้านลบ **%.1f เท่า** (รวมปันผล %+.1f%% ต่อ %+.1f%%). K. Pop มองหาด้านบวกราว 50–100%% จากตัวเลขนี้ด้านบวก %s เกณฑ์ขั้นต่ำ 50%%" % (
            up["total"] / abs(dn["total"]) if dn["total"] < 0 else float("nan"), up["total"] * 100, dn["total"] * 100,
            "**ถึง**" if up["total"] >= 0.5 else "**ยังไม่ถึง**"))
    es = b.get("end_state")
    if es:
        d.h(3, "11.2 มูลค่าปันผลปลายทาง — %s" % OVERLAY)
        d.table(["สถานการณ์", "จ่ายปันผล", "DPS (บาท)", "มูลค่า/หุ้น (บาท)", "เทียบราคา"],
                [[e["name"], "%.0f%%" % (e["payout"] * 100), f2(e["dps"]), f2(e["value"]), pc(e["chg"])] for e in es],
                align=["l", "r", "r", "r", "r"])
        d.p("_มูลค่า = DPS ÷ (Ke − g); Ke จาก CAPM = %.2f%%, g = %.1f%% [คำนวณ]. CAPM เป็นส่วนเสริมของนักวิเคราะห์ ไม่ใช่วิธีของ K. Pop; "
            "กรณีจ่าย 70–90%% เป็นสถานการณ์สมมติ ไม่ใช่นโยบายบริษัท_" % (b["ke"] * 100, b["g"] * 100))
    for x in b.get("problems") or []:
        d.p("⚠ " + x)
