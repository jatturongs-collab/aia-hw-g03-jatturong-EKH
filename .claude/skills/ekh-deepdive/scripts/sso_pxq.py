"""
sso_pxq.py - Social-security (SSO) revenue split into Q (insured persons) x P (revenue per insured person).

Why: a hospital's SSO revenue can grow with flat or falling headcount when revenue per insured person rises
(higher capitation / AdjRW rates from the SSO office, more complex cases billed above the capitation, or
back-payments).  Reading P and Q separately tells which one moved; the cause still needs a document.

Inputs (no new files):
  report/<T>_hospitals.json  -> "sso": {"years": {"2568": {"insured": {...}, "quota": {...}, "quota_total",
                                 "revenue_per_insured" (stated), "src"}}}
  SSO revenue by fiscal year / YTD from the same revenue-mix dict the snapshot uses (assumptions first, then MD&A).

Used by snapshot.py (section 2.1) and can be imported by the deep dive.
"""
import json
import os
import re


def _bep(p):          # "6M2026" -> "6M/2569"
    m = re.fullmatch(r"(\d+)M(\d{4})", p or "")
    return "%sM/%d" % (m.group(1), int(m.group(2)) + 543) if m else p


def _be(fy):           # "FY2025" -> "2568"
    return str(int(fy[2:]) + 543)


def _ce(be):           # "2568" -> 2025
    return int(be) - 543


def _g(a, b):
    return (a / b - 1) if a is not None and b not in (None, 0) else None


def load_events(sdir):
    """data/sector/Hospital/payor_events.json (shared record of SSO/NHSO/insurer rule changes)."""
    from snapshot import ai_root
    root = ai_root(sdir)
    p = os.path.join(root, "data", "sector", "Hospital", "payor_events.json")
    try:
        return json.load(open(p, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


REFERRAL = re.compile(r"^\|\s*(ค่ารักษาพยาบาลส่งต่อ|ค่ารักษาส่งต่อ|ค่าส่งต่อผู้ป่วย)\s*\|")


def referral_by_year(sdir):
    """consolidated referral cost (ค่ารักษาพยาบาลส่งต่อ, expenses by nature) per fiscal year, THB mn, from the
    audited annual statements md/raw/combined_fs3_all.md (first number of the row = consolidated, current year)."""
    p = os.path.join(sdir, "md", "raw", "combined_fs3_all.md")
    out = {}
    try:
        lines = open(p, encoding="utf-8", errors="replace").read().splitlines()
    except OSError:
        return out
    yr, unit = None, 1e-3
    for i, ln in enumerate(lines):
        m = re.search(r"#\s*ANNUAL.*?(25\d\d)", ln)
        if m:
            yr, unit = m.group(1), 1e-3
            continue
        if "หน่วย" in ln and "บาท" in ln:
            unit = 1e-3 if "พันบาท" in ln else (1.0 if "ล้านบาท" in ln else 1e-6)
        if yr and yr not in out and REFERRAL.match(ln):
            nums = [c.strip().replace(",", "") for c in ln.strip().strip("|").split("|")[1:]]
            nums = [float(c) for c in nums if re.fullmatch(r"-?\d+(\.\d+)?", c)]
            if nums:
                out[yr] = {"mn": nums[0] * unit, "src": "combined_fs3_all.md:%d (งบปี %s ค่าใช้จ่ายตามลักษณะ งบรวม)" % (i + 1, yr)}
    return out


def build(sdir, ticker, mixval, ytd=None, ytd_py=None, gpm=None):
    """mixval(period, key) -> value in THB mn (the snapshot's accessor).  gpm = {period: group GPM} for context.
    Returns None when the stock has no `sso` block."""
    p = os.path.join(sdir, "report", "%s_hospitals.json" % ticker)
    if not os.path.isfile(p):
        return None
    try:
        sso = (json.load(open(p, encoding="utf-8")) or {}).get("sso") or {}
    except ValueError:
        return None
    yrs = sso.get("years") or {}
    if not yrs:
        return None
    rows, flags = [], []
    for be in sorted(yrs, key=int):
        y = yrs[be] or {}
        ins = y.get("insured") or {}
        q = sum(v for v in ins.values() if v) if ins else None
        fy = "FY%d" % _ce(be)
        rev = mixval(fy, "sso")
        rev_src = "รายได้ประกันสังคมตามโครงสร้างรายได้ MD&A %s" % fy
        if rev is None and y.get("sso_revenue_mn") is not None:
            rev, rev_src = y["sso_revenue_mn"], "hospitals.json sso_revenue_mn"
        p_calc = rev * 1e6 / q if rev is not None and q else None
        p_stated = y.get("revenue_per_insured")
        if p_calc and p_stated and abs(p_calc / p_stated - 1) > 0.005:
            flags.append("ปี %s รายได้ต่อผู้ประกันตนที่บริษัทแจ้ง %s บาท ต่างจากค่าคำนวณ %s บาท (%+.1f%%) — รายได้ SSO ที่ใช้ในสองแหล่งไม่เท่ากัน"
                         % (be, "{:,.0f}".format(p_stated), "{:,.0f}".format(p_calc), (p_calc / p_stated - 1) * 100))
        quota = y.get("quota_total")
        rows.append({"year": be, "fy": fy, "insured": q, "quota": quota, "util": (q / quota) if q and quota else None,
                     "rev": rev, "p": p_calc, "p_stated": p_stated, "src": y.get("src", ""), "rev_src": rev_src,
                     "gpm": (gpm or {}).get(fy)})
    for a, b in zip(rows, rows[1:]):
        b["q_g"], b["p_g"], b["rev_g"] = _g(b["insured"], a["insured"]), _g(b["p"], a["p"]), _g(b["rev"], a["rev"])
        if None not in (a["insured"], b["insured"], a["p"], b["p"]):
            b["q_eff"] = (b["insured"] - a["insured"]) * a["p"] / 1e6          # THB mn from headcount
            b["p_eff"] = (b["p"] - a["p"]) * b["insured"] / 1e6                # THB mn from revenue per head
        if a.get("gpm") is not None and b.get("gpm") is not None:
            b["gpm_pt"] = (b["gpm"] - a["gpm"]) * 100

    ev = load_events(sdir)
    cy = ((ev.get("company_year") or {}).get(ticker) or {})
    ref = referral_by_year(sdir)
    for r in rows:
        adj = (cy.get(r["year"]) or {}).get("sso_revenue_cut_mn")
        if adj and r["rev"] is not None:
            r["cut"] = adj
            r["cut_src"] = (cy[r["year"]] or {}).get("src", "")
            r["rev_ex"] = r["rev"] - adj                 # add the retroactive cut back
            r["p_ex"] = r["rev_ex"] * 1e6 / r["insured"] if r["insured"] else None
        if r["year"] in ref:
            r["referral"] = ref[r["year"]]["mn"]
            r["referral_src"] = ref[r["year"]]["src"]
            r["referral_to_sso"] = r["referral"] / r["rev"] if r["rev"] else None
    for a, b in zip(rows, rows[1:]):
        pa, pb = a.get("p_ex") or a["p"], b.get("p_ex") or b["p"]
        if (a.get("p_ex") or b.get("p_ex")) and pa and pb:
            b["p_g_ex"] = pb / pa - 1                     # growth with every year's retroactive cut added back
        if a.get("referral") and b.get("referral"):
            b["referral_g"] = b["referral"] / a["referral"] - 1

    out = {"rows": rows, "flags": flags, "note": sso.get("note", ""), "read": [],
           "events": [e for e in ev.get("events") or [] if ticker in (e.get("impacts") or {}) or e.get("payor") in ("สปส.", "สปสช.")]}
    if ytd and ytd_py:
        r1, r0 = mixval(ytd, "sso"), mixval(ytd_py, "sso")
        last = next((r for r in reversed(rows) if r["insured"]), None)
        out["ytd"] = {"ytd": ytd, "ytd_py": ytd_py, "rev": r1, "rev_py": r0, "rev_g": _g(r1, r0),
                      "q_last_year": last["year"] if last else None, "q_last": last["insured"] if last else None}

    # mechanical reading: which of P or Q moved (cause is NOT inferred here)
    for n, r in enumerate(rows):
        if n == 0 or r.get("q_g") is None or r.get("p_g") is None:
            continue
        lead = "รายได้ต่อหัว (P)" if abs(r["p_g"]) > abs(r["q_g"]) else "จำนวนผู้ประกันตน (Q)"
        t = ("ปี %s: ผู้ประกันตน %+.1f%% · รายได้ต่อหัว %+.1f%% → รายได้ SSO %+.1f%% (จาก Q %+.1f ลบ., จาก P %+.1f ลบ.) — ตัวขับหลักคือ%s"
             % (r["year"], r["q_g"] * 100, r["p_g"] * 100, (r["rev_g"] or 0) * 100, r.get("q_eff", 0), r.get("p_eff", 0), lead))
        prev = rows[n - 1]
        if prev.get("p_g") is not None and prev["p_g"] < 0 and r["p_g"] > 0 and n >= 2 and rows[n - 2].get("p"):
            t += ("; ฐานปี %s ต่ำ (P %+.1f%%) — เทียบ 2 ปีกับปี %s P ยัง %+.1f%%"
                  % (prev["year"], prev["p_g"] * 100, rows[n - 2]["year"], (r["p"] / rows[n - 2]["p"] - 1) * 100))
        if r.get("p_g_ex") is not None and abs(r["p_g_ex"] - r["p_g"]) > 0.005:
            t += "; บวกคืนรายการ สปส. ตัดย้อนหลังแล้ว P %+.1f%%" % (r["p_g_ex"] * 100)
        out["read"].append(t)
    for r in rows:
        if r.get("cut"):
            out["read"].append("ปี %s: สปส. ตัดรายได้ย้อนหลัง %.2f ลบ. (อัตรา AdjRW > 2 จาก 12,000 เหลือ 7,200–8,000 บาทต่อ RW) — ฐานต่ำ; "
                               "รายได้ SSO ไม่รวมรายการนี้ %.2f ลบ., P %s บาท [ที่มา: %s]" % (
                                   r["year"], -r["cut"], r["rev_ex"], "{:,.0f}".format(r["p_ex"]) if r.get("p_ex") else "–", r.get("cut_src", "")))
    rr = [r for r in rows if r.get("referral") is not None]
    if len(rr) >= 2:
        out["read"].append("ค่ารักษาพยาบาลส่งต่อ (งบรวม): " + " → ".join(
            "ปี %s %.1f ลบ. (%.0f%% ของรายได้ SSO)" % (r["year"], r["referral"], (r["referral_to_sso"] or 0) * 100) for r in rr)
            + " — โรงพยาบาลหลักในระบบประกันสังคมจ่ายค่ารักษาเมื่อส่งผู้ป่วยไปที่อื่น ค่าส่งต่อที่ลดลงขณะรายได้ SSO โตจึงชี้ว่าส่งต่อน้อยลง "
              "(รักษาเองได้มากขึ้นหรือคุมการส่งต่อ) — เหตุผลต้องยืนยันจาก MD&A/Oppday; ค่าส่งต่ออาจรวมผู้ป่วยสิทธิอื่นด้วย")
    y = out.get("ytd")
    if y and y.get("rev_g") is not None:
        out["read"].append("%s รายได้ SSO %+.1f%% YoY (%s → %s ลบ.); ผู้ประกันตนรายครึ่งปียังไม่เปิดเผย — ถ้า Q ยังใกล้ปี %s (%s ราย) "
                           "การเติบโตนี้มาจาก P เกือบทั้งหมด" % (
                               _bep(y["ytd"]), y["rev_g"] * 100, "{:,.2f}".format(y["rev_py"]), "{:,.2f}".format(y["rev"]), y["q_last_year"],
                               "{:,.0f}".format(y["q_last"]) if y["q_last"] else "–"))
    out["drivers"] = [
        "อัตราที่ สปส. จ่าย: อัตราเหมาจ่ายรายหัว/ค่าน้ำหนักสัมพัทธ์ (AdjRW) สำหรับโรคเรื้อรังและผู้ป่วยในที่ปรับขึ้น — ตรวจประกาศ สปส. และ MD&A",
        "ความซับซ้อนของผู้ป่วย (case mix): ผู้ป่วย SSO โรคซับซ้อนที่เบิกได้นอกเหนือเหมาจ่ายเพิ่มขึ้น สะท้อนแพทย์เฉพาะทาง/ศูนย์รักษา — ตรวจ AdjRW ต่อราย, จำนวนแพทย์, ศูนย์ใหม่ใน Oppday",
        "รายการย้อนหลัง/ครั้งเดียว: เงินจ่ายเพิ่มหรือปรับลดย้อนหลังจาก สปส. ทำให้ P กระโดดชั่วคราว — ตรวจหมายเหตุงบและ one-offs",
    ]
    return out
