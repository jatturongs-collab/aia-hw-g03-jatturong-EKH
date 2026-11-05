#!/usr/bin/env python3
"""
deepdive_extra.py - optional data blocks for the deep dive that do not come from the statements:

  report/<T>_hospitals.json   revenue, capitation / non-capitation, net profit and beds BY HOSPITAL, transcribed
                              from annual reports and AGM minutes with a source per year (see the VIH file for the shape)
  report/<T>_project.json     the make-or-break project: approved size, funding, phasing, the IFA's projection,
                              and the timeline as management restated it at each meeting
  report/<T>_ops_metrics.json volume, utilisation and revenue per bill read from Oppday slides (stock-snapshot/oppday_ops.py)

load() puts them in the data pack (so the narrative may quote their numbers) and lists every percentage the tables
derive. The render_* functions draw the tables. Everything is optional: a stock without a file gets no table.
"""
import json
import os

H_ORDER = ["omnoi", "nongkhaem", "samutsakhon", "yaekfaichai"]


def _load(sdir, name):
    p = os.path.join(sdir, "report", name)
    return json.load(open(p, encoding="utf-8")) if os.path.isfile(p) else None


def _be(per):
    """FY2025 -> ปี 2568, 6M2026 -> 6M/2569, 2026Q2 -> Q2/2569"""
    if per.startswith("FY"):
        return "ปี %d" % (int(per[2:]) + 543)
    if per[1] == "M":
        return "%s/%d" % (per[:2], int(per[2:]) + 543)
    return "Q%s/%d" % (per[-1], int(per[:4]) + 543)


def load(sdir, ticker, fys, ytd=None, ytd_py=None):
    out, pcts = {}, []
    hosp = _load(sdir, "%s_hospitals.json" % ticker)
    if hosp:
        keys = [k for k in H_ORDER if k in hosp.get("hospitals", {})] or list(hosp.get("hospitals", {}))
        table = []
        hosp.setdefault("years", {})
        for y in sorted(hosp["years"]):
            yr = hosp["years"][y]
            rev = yr.get("revenue") or {}
            tot = sum(rev.get(k) or 0 for k in keys)
            npx = yr.get("np_ex_dividend") or {}
            nps = sum(npx.get(k) or 0 for k in keys)
            row = {"year": y, "src": yr.get("src"), "h": {}}
            for k in keys:
                r, n, c = rev.get(k), npx.get(k), (yr.get("capitation") or {}).get(k)
                e = {"rev": r, "np": n, "cap": c,
                     "rev_share": r / tot if r and tot else None, "np_share": n / nps if n is not None and nps else None,
                     "npm": n / r if n is not None and r else None, "cap_share": c / r if c is not None and r else None}
                row["h"][k] = e
                pcts += [v * 100 for v in (e["rev_share"], e["np_share"], e["npm"], e["cap_share"]) if v is not None]
            row.update(rev_sum=round(tot, 2), np_sum=round(nps, 2) if npx else None, rev_group=yr.get("revenue_group"), np_group=yr.get("np_group"),
                       intercompany=yr.get("intercompany"))
            table.append(row)
        for a, b in zip(table, table[1:]):                       # growth by hospital
            for k in keys:
                r0, r1 = a["h"][k]["rev"], b["h"][k]["rev"]
                if r0 and r1:
                    b["h"][k]["rev_g"] = r1 / r0 - 1
                    pcts.append((r1 / r0 - 1) * 100)
        out["hospitals"] = dict(hosp, keys=keys, table=table)
    proj = _load(sdir, "%s_project.json" % ticker)
    if proj:
        out["project"] = proj
        ifa = proj.get("ifa") or {}
        pcts += [v for v in [ifa.get("irr_pct")] + list((ifa.get("sensitivity") or {}).get("irr_by_patients_pct") or []) +
                 list((ifa.get("sensitivity") or {}).get("irr_by_cost_pct") or []) + [(proj.get("funding") or {}).get("eps_dilution_pct")] if v is not None]
    ops = _load(sdir, "%s_ops_metrics.json" % ticker)
    if ops and ops.get("metrics"):
        m, dv = ops["metrics"], ops.get("derived") or {}
        pers = [p for p in fys if any(p in s for s in m.values())]
        for p in (ytd_py, ytd):
            if p and any(p in s for s in m.values()):
                pers.append(p)
        rows = []
        for key, label, rate in (("opd_visits", "ผู้ป่วยนอก (ครั้ง)", False), ("opd_utilization_pct", "อัตราการใช้บริการ OPD", True),
                                 ("per_bill_opd_baht", "รายได้ต่อใบเสร็จ OPD (บาท)", False), ("ipd_days", "วันนอนผู้ป่วยใน (วัน)", False),
                                 ("occupancy_pct", "อัตราครองเตียง", True), ("implied_beds", "ฐานเตียงที่ใช้คำนวณอัตรา [คำนวณ]", False),
                                 ("per_bill_ipd_baht", "รายได้ต่อใบเสร็จ IPD (บาท)", False)):
            ser = m.get(key) or dv.get(key) or {}
            vals = {p: ser[p]["v"] for p in pers if p in ser}
            if not vals:
                continue
            rows.append({"id": key, "label": label, "rate": rate, "ops_vals": vals, "derived": key in dv,
                         "src": sorted({ser[p]["src"] for p in vals if ser[p].get("src")})})
            if rate:
                pcts += list(vals.values())
            ordered = [vals[p] for p in pers if p in vals and p.startswith("FY")]
            for a, b in zip(ordered, ordered[1:]):
                pcts.append((b - a) if rate else (b / a - 1) * 100)
            if ytd in vals and ytd_py in vals:
                pcts.append((vals[ytd] - vals[ytd_py]) if rate else (vals[ytd] / vals[ytd_py] - 1) * 100)
        out["ops"] = {"periods": pers, "rows": rows, "base_checks": ops.get("base_checks") or [],
                      "restated": sorted(ops.get("superseded") or {})}
    out["extra_pcts"] = pcts
    return out


# ------------------------------------------------------------------------------------------------- rendering
def _n(v, d=2):
    return "–" if v is None else "{:,.{}f}".format(v, d)


def _p(v, d=1):
    return "–" if v is None else "%.*f%%" % (d, v * 100)


def render_hospitals(d, p):
    hb = p.get("hospitals")
    if not hb or not hb.get("table"):          # a file with only the `sso` block (no revenue by hospital) has nothing to show here
        return
    names, keys, tb = hb["hospitals"], hb["keys"], hb["table"]
    ys = [r["year"] for r in tb]
    d.h(3, "รายได้และกำไรรายโรงพยาบาล (จากรายงานประจำปีและรายงานการประชุมผู้ถือหุ้น)")
    rows = []
    for k in keys:
        rows.append(["**%s** — รายได้" % names[k]] + [_n(r["h"][k]["rev"]) for r in tb])
        rows.append(["  สัดส่วนรายได้"] + [_p(r["h"][k]["rev_share"]) for r in tb])
        rows.append(["  รายได้โต YoY"] + [_p(r["h"][k].get("rev_g")) for r in tb])
    rows.append(["รวมก่อนตัดรายการระหว่างกัน"] + [_n(r["rev_sum"]) for r in tb])
    rows.append(["รายการระหว่างกัน"] + [_n(r["intercompany"]) for r in tb])
    rows.append(["**รายได้กลุ่มตามงบรวม**"] + [_n(r["rev_group"]) for r in tb])
    d.table(["รายได้ (ล้านบาท)"] + ["ปี %s" % y for y in ys], rows, bold_rows=[len(rows) - 1])
    for k in keys:                               # net profit growth (needs both years, base > 0)
        prev = None
        for r in tb:
            v = r["h"][k].get("np")
            r["h"][k]["np_g"] = (v / prev - 1) if v is not None and prev not in (None, 0) and prev > 0 else None
            prev = v
    import deepdive_viz as DV
    DV.hospital_charts(d, names, keys, tb, "rev")
    rows = []
    for k in keys:
        rows.append(["**%s** — กำไรสุทธิ" % names[k]] + [_n(r["h"][k]["np"]) for r in tb])
        rows.append(["  อัตรากำไรสุทธิ"] + [_p(r["h"][k]["npm"]) for r in tb])
        rows.append(["  สัดส่วนกำไร"] + [_p(r["h"][k]["np_share"]) for r in tb])
        rows.append(["  กำไรสุทธิโต YoY"] + [_p(r["h"][k].get("np_g")) for r in tb])
    rows.append(["รวมสี่โรงพยาบาล"] + [_n(r["np_sum"]) for r in tb])
    rows.append(["**กำไรสุทธิกลุ่มตามงบรวม**"] + [_n(r["np_group"]) for r in tb])
    d.table(["กำไรสุทธิ ไม่รวมเงินปันผลรับจากบริษัทย่อย (ล้านบาท)"] + ["ปี %s" % y for y in ys], rows, bold_rows=[len(rows) - 1])
    DV.hospital_charts(d, names, keys, tb, "np")
    capy = [r for r in tb if any(r["h"][k]["cap"] is not None for k in keys)]
    if capy:
        rows = [["%s" % names[k]] + [_p(r["h"][k]["cap_share"]) for r in capy] for k in keys]
        d.table(["สัดส่วนรายได้ Capitation ต่อรายได้ของโรงพยาบาล"] + ["ปี %s" % r["year"] for r in capy], rows)
    d.p("_ที่มา: %s. กำไรของอ้อมน้อย (บริษัทแม่) ในรายงานประจำปีรวมเงินปันผลรับจากบริษัทย่อย ตารางนี้จึงใช้กำไรไม่รวมเงินปันผล: "
        "ปี 2563–2565 คำนวณจากงบเฉพาะกิจการ (กำไรสุทธิ − เงินปันผลรับ) ปี 2566–2568 ตามที่บริษัทรายงานต่อที่ประชุมผู้ถือหุ้น. "
        "สัดส่วน อัตรากำไร และการเติบโตเป็นค่าคำนวณ; ช่องว่าง (–) = เอกสารไม่เปิดเผย_" % "; ".join(
            "ปี %s: %s" % (r["year"], r["src"]) for r in tb if r.get("src")))
    beds = hb.get("beds")
    if beds:
        ys2 = sorted(beds)
        rows = []
        for k in keys + ["total"]:
            lab = "**รวม**" if k == "total" else names[k]
            rows.append([lab] + ["%s / %s" % ((beds[y].get("registered") or {}).get(k, "–"), (beds[y].get("operating") or {}).get(k, "–")) for y in ys2])
        d.table(["เตียงจดทะเบียน / เตียงให้บริการจริง"] + [("ปี %s" % y) if y.isdigit() else y for y in ys2], rows, bold_rows=[len(rows) - 1])
        d.p("_ที่มา: %s_" % "; ".join("%s: %s" % (y, beds[y]["src"]) for y in ys2))


def render_sso(d, p):
    """Section 3: insured persons against the SSO quota, by hospital (from <T>_hospitals.json, block `sso`)."""
    hb = p.get("hospitals") or {}
    sso = hb.get("sso") or {}
    Y = sso.get("years") or {}
    if Y:
        _sso_quota(d, hb, sso, Y)
    _sso_tables(d, sso)
    if not Y:
        pts = sso.get("points") or []
        if pts:
            d.ul(["**%s:** %s <small>[%s]</small>" % (pt.get("when", ""), pt.get("text", ""), pt.get("src", "")) for pt in pts])
        if sso.get("note"):
            d.p("_%s_" % sso["note"])


def _fmt_cell(v):
    if v is None or v == "":
        return "–"
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, int):
        return "{:,}".format(v)
    if isinstance(v, float):
        t = "{:,.2f}".format(v)
        return t[:-1] if t.endswith("0") else t          # 214.00 -> 214.0, 273.49 stays
    return str(v)


def _sso_tables(d, sso):
    """Free tables of the `sso` block (`tables`): group series from Oppday slides (tier 1) or official provincial
    statistics (tier 2). Each table carries its tier, source and note; nothing is computed here."""
    for t in sso.get("tables") or []:
        if not t.get("rows"):
            continue
        tier2 = str(t.get("tier", 1)) != "1"
        d.h(3, t.get("title", "ประกันสังคม") + (" — แหล่งที่ 2 (ไม่ใช่เอกสารบริษัท)" if tier2 else ""))
        d.table(t.get("cols") or [], [[r[0]] + [_fmt_cell(v) for v in r[1:]] for r in t["rows"]], bold_rows=t.get("bold") or [])
        tail = "_ที่มา: %s%s_" % (t.get("src", "–"), (". " + t["note"]) if t.get("note") else "")
        d.p(tail)


def _sso_quota(d, hb, sso, Y):
    names, hk, ys = hb.get("hospitals") or {}, sso.get("hospitals") or [], sorted(Y)
    num = lambda v: "–" if v is None else "{:,.0f}".format(v)

    def q(y, k):
        return (Y[y].get("quota") or {}).get(k)

    def ins(y, k):
        return (Y[y].get("insured") or {}).get(k)

    def tot_ins(y):
        v = [ins(y, k) for k in hk]
        if v and all(a is not None for a in v):
            return sum(v), False
        if Y[y].get("sso_revenue_mn") and Y[y].get("revenue_per_insured"):
            return round(Y[y]["sso_revenue_mn"] * 1e6 / Y[y]["revenue_per_insured"]), True      # computed, labelled below
        return None, False

    d.h(3, "ผู้ประกันตนในระบบประกันสังคม เทียบโควตา รายโรงพยาบาล: รับอยู่เท่าไร รับได้สูงสุดเท่าไร เหลือเท่าไร")
    rows, bold = [], []
    for k in hk:
        nm = names.get(k, k)
        rows.append(["**%s** — โควตา (รับได้สูงสุด)" % nm] + [num(q(y, k)) for y in ys])
        rows.append(["  ผู้ประกันตน"] + [num(ins(y, k)) for y in ys])
        rows.append(["  ผู้ประกันตนโต YoY"] + ["–"] + [_p(ins(b, k) / ins(a, k) - 1) if ins(a, k) and ins(b, k) else "–" for a, b in zip(ys, ys[1:])])
        rows.append(["  อัตราใช้โควตา"] + [_p(ins(y, k) / q(y, k)) if ins(y, k) and q(y, k) else "–" for y in ys])
        rows.append(["  เหลือที่ยังรับได้"] + [num(q(y, k) - ins(y, k)) if ins(y, k) is not None and q(y, k) else "–" for y in ys])
    T = {y: tot_ins(y) for y in ys}
    computed = any(c for _, c in T.values())
    bold.append(len(rows))
    rows.append(["**รวม** — โควตา"] + [num(Y[y].get("quota_total")) for y in ys])
    bold.append(len(rows))
    rows.append(["**รวม** — ผู้ประกันตน"] + [(num(T[y][0]) + (" [คำนวณ]" if T[y][1] else "")) for y in ys])
    rows.append(["  ผู้ประกันตนโต YoY"] + ["–"] + [_p(T[b][0] / T[a][0] - 1) if T[a][0] and T[b][0] else "–" for a, b in zip(ys, ys[1:])])
    rows.append(["  อัตราใช้โควตา"] + [_p(T[y][0] / Y[y]["quota_total"]) if T[y][0] and Y[y].get("quota_total") else "–" for y in ys])
    bold.append(len(rows))
    rows.append(["**เหลือที่ยังรับได้ รวม**"] + [num(Y[y]["quota_total"] - T[y][0]) if T[y][0] is not None and Y[y].get("quota_total") else "–" for y in ys])
    rows.append(["รายได้ประกันสังคมต่อผู้ประกันตน (บาท/ปี)"] + [_n(Y[y].get("revenue_per_insured")) for y in ys])
    rows.append(["รายได้ที่เพิ่มได้ถ้าเติมเต็มโควตา (ล้านบาท/ปี) [คำนวณ]"] + [
        _n((Y[y]["quota_total"] - T[y][0]) * Y[y]["revenue_per_insured"] / 1e6) if T[y][0] is not None and Y[y].get("quota_total") and Y[y].get("revenue_per_insured") else "–"
        for y in ys])
    d.table(["ราย (คน)"] + ["ปี %s" % y for y in ys], rows, bold_rows=bold)
    d.p("_อ่านอย่างไร: โควตาคือเพดานที่ สปส. อนุญาต แต่ผู้ประกันตนเป็นผู้เลือกโรงพยาบาลเอง ถ้าอัตราใช้โควตาต่ำกว่า 100%% และไม่เพิ่ม "
        "คอขวดไม่ได้อยู่ที่โควตา. แถวสุดท้ายเป็นเพดานทางทฤษฎี (เหลือที่ยังรับได้ × รายได้ต่อราย) ไม่ใช่ประมาณการ. อัตรา การเติบโต "
        "และส่วนที่เหลือเป็นค่าคำนวณจากตัวเลขที่บริษัทแจ้ง%s_" % ("; ผู้ประกันตนรวมที่มีป้าย [คำนวณ] = รายได้ประกันสังคม ÷ รายได้ต่อราย" if computed else ""))
    pts = sso.get("points") or []
    if pts:
        d.ul(["**%s:** %s <small>[%s]</small>" % (pt.get("when", ""), pt.get("text", ""), pt.get("src", "")) for pt in pts])
    d.p("_ที่มา: %s%s_" % ("; ".join("ปี %s: %s" % (y, Y[y].get("src", "–")) for y in ys), (". " + sso["note"]) if sso.get("note") else ""))
    for y in ys:
        if Y[y].get("insured_note"):
            d.p("_หมายเหตุปี %s: %s_" % (y, Y[y]["insured_note"]))


def render_ops(d, p):
    ops = p.get("ops")
    if not ops or not ops["rows"]:
        return
    pers = ops["periods"]
    d.h(3, "ปริมาณ อัตราการใช้ และรายได้ต่อใบเสร็จ (จากสไลด์ Oppday)")
    rows = []
    for r in ops["rows"]:
        f = (lambda v: "–" if v is None else ("%.2f%%" % v if r["rate"] else "{:,.0f}".format(v)))
        rows.append([r["label"]] + [f(r["ops_vals"].get(x)) for x in pers])
    d.table(["ตัวชี้วัด"] + [_be(x) for x in pers], rows)
    note = "_ที่มา: สไลด์ Opportunity Day อ่านจากตำแหน่งบนหน้าด้วยสคริปต์ (`%s_ops_metrics.json`); แถว [คำนวณ] = วันนอน ÷ (อัตราครองเตียง × จำนวนวันในงวด) " \
           "คือฐานที่บริษัทใช้คำนวณอัตรา ไม่ใช่จำนวนเตียงที่บริษัทเปิดเผย" % p["ticker"]
    if ops.get("restated"):
        note += "; สไลด์รุ่นก่อนใช้ตัวเลขคนละชุดสำหรับบางงวด จึงใช้เฉพาะชุดที่ตรงกับสไลด์ล่าสุด"
    d.p(note + "_")


def render_project(d, p):
    pj = p.get("project")
    if not pj:
        return
    a, r, f, ph, ifa = pj.get("approved") or {}, pj.get("revised") or {}, pj.get("funding") or {}, pj.get("phasing") or {}, pj.get("ifa") or {}
    d.h(3, pj.get("name", "โครงการลงทุน"))
    rows = [["ที่ตั้ง", "%s (%s)" % (a.get("location", "–"), a.get("land_area", "–")), a.get("src", "")],
            ["มูลค่าโครงการที่อนุมัติ", "ไม่เกิน %s ลบ. (ที่ดิน %s + ก่อสร้างไม่เกิน %s)" % (_n(a.get("value_max")), _n(a.get("land")), _n(a.get("construction_max"))), a.get("src", "")],
            ["ขนาดและตลาด", "%s เตียง — %s; เน้น %s" % (a.get("beds", "–"), a.get("positioning", ""), a.get("focus", "")), a.get("src", "")]]
    if r:
        rows.append(["ฉบับปรับปรุง", "ไม่เกิน %s ลบ. โดย%s (ทุนจดทะเบียน %s ลบ.)" % (_n(r.get("value_max")), r.get("vehicle", ""), _n(r.get("registered_capital"), 0)), r.get("src", "")])
    if f:
        rows.append(["แหล่งเงินทุน", "เพิ่มทุน (RO) ไม่เกิน %s ลบ. + กู้ไม่ต่ำกว่า %s ลบ.; หากไม่มี RO กู้ไม่ต่ำกว่า %s ลบ.; EPS dilution ราว %s%%" % (
            _n(f.get("ro_max")), _n(f.get("loan_min_with_ro")), _n(f.get("loan_min_without_ro")), f.get("eps_dilution_pct")), f.get("src", "")])
    if ph:
        rows.append(["การเปิดเป็นเฟส", "%s เฟส เฟสแรกราว %s เตียง ใช้ราว %s ปีจึงเปิดครบ" % (ph.get("phases"), ph.get("first_phase_beds"), ph.get("years_to_full")), ph.get("src", "")])
    if pj.get("competitors_20km"):
        rows.append(["โรงพยาบาลเอกชนในรัศมี 20 กม.", ", ".join(pj["competitors_20km"]), a.get("src", "")])
    if pj.get("pricing"):
        rows.append(["ราคาและการบริหาร", pj["pricing"], ""])
    d.table(["หัวข้อ", "รายละเอียด", "แหล่งที่มา"], rows, align=["l", "l", "l"])
    if ifa:
        s = ifa.get("sensitivity") or {}
        d.p("**ประมาณการของที่ปรึกษาทางการเงินอิสระ (%s) — กรณีฐานของผู้เสนอโครงการ ไม่ใช่ผลประกอบการ:** NPV %s ลบ., IRR %s%%, คืนทุน %s ปีนับจากเปิดให้บริการ. "
            "ความอ่อนไหว: NPV %s–%s ลบ. ตามจำนวนผู้ป่วย และ %s–%s ลบ. ตามต้นทุน; IRR %s%%–%s%% ตามจำนวนผู้ป่วย" % (
                ifa.get("adviser", ""), _n(ifa.get("npv")), ifa.get("irr_pct"), ifa.get("payback_years_from_opening"),
                _n((s.get("npv_by_patients") or [None, None])[0]), _n((s.get("npv_by_patients") or [None, None])[1]),
                _n((s.get("npv_by_cost") or [None, None])[0]), _n((s.get("npv_by_cost") or [None, None])[1]),
                (s.get("irr_by_patients_pct") or [None, None])[0], (s.get("irr_by_patients_pct") or [None, None])[1]))
        fc = ifa.get("fcff") or {}
        if fc:
            ys = sorted(fc)
            d.table(["FCFF ของโครงการตามประมาณการ IFA (ล้านบาท)"] + ["ปี %s" % y for y in ys], [["FCFF"] + [_n(fc[y]) for y in ys]])
        d.p("_ที่มา: %s_" % ifa.get("src", ""))
    if pj.get("timeline"):
        d.table(["แจ้งเมื่อ", "กำหนดการที่ผู้บริหารแจ้ง", "แหล่งที่มา"], [[t["said"], t["plan"], t["src"]] for t in pj["timeline"]], align=["l", "l", "l"])
