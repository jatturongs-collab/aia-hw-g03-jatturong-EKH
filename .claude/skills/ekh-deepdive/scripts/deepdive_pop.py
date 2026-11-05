"""K. Pop checklist (section 14.1): his tests in the order he applies them (The K. Pop Way §14).

Three kinds of item, so that a script never invents a judgement:
  auto   computed from the data pack (and the snapshot pack for quarterly D&A and commitments); status = pass / fail / info.
  doc    needs a reading of the company's documents: taken from narrative["pop_checklist"][id] = {"status", "why", "src"};
         "open" until the narrative answers it.
  owner  a decision that belongs to the portfolio owner (buy today? sell plan? sizing). The skill shows the numbers beside
         the question and NEVER answers it: it is not investment advice. narrative["pop_owner"][id] = {"answer", "note"}.

Group order is the order he applies them: a stock that fails an early group does not reach the later ones.
"""
import json
import os
import statistics as st

STATUS = ("pass", "fail", "unsure")            # what a narrative answer to a `doc` item may say
ICON = {"pass": "✅", "fail": "❌", "info": "ℹ️", "unsure": "❓", "open": "⬜", "owner": "👤"}

# (id, kind, question)
ITEMS = [
    ("ธุรกิจ", [
        ("b1", "doc", "ลูกค้าเป็นผู้บริโภค จำนวนมากและไม่กระจุกตัวหรือไม่"),
        ("b2", "doc", "ลูกค้าซื้อซ้ำ และคนเดิมจ่ายมากขึ้นตามเวลาหรือไม่"),
        ("b3", "doc", "ขึ้นราคาได้ทันเงินเฟ้อหรือไม่"),
        ("b4", "doc", "มีหลายสาขา และยังมีที่ให้โตจากฐานต่ำหรือไม่"),
        ("b5", "owner", "ตรวจสอบเองได้ (ไปดู โทร เป็นลูกค้า) หรือไม่"),
        ("b6", "doc", "เป็นธุรกิจที่ไม่ใช่ของตามกระแส (fashion) หรือไม่"),
    ]),
    ("คู่แข่ง", [
        ("c1", "auto", "รายได้โตเร็วกว่าอุตสาหกรรมหรือไม่"),
        ("c2", "auto", "อัตรากำไรขั้นต้นยังทรงตัวหรือดีขึ้นหรือไม่"),
        ("c3", "auto", "งบของคู่แข่งบอกอะไร (เทียบ GPM กับมัธยฐานกลุ่ม)"),
        ("c4", "doc", "ระบุที่มาของความได้เปรียบได้หรือไม่ (ต้นทุน แบรนด์ ทุน หรือการบริหาร)"),
    ]),
    ("วัฏจักรต้นทุน", [
        ("k1", "auto", "ค่าเสื่อมราคารายไตรมาสหยุดเพิ่มแล้วหรือไม่"),
        ("k2", "auto", "ภาระผูกพันรายจ่ายฝ่ายทุนในหมายเหตุลดลงใกล้ศูนย์หรือไม่"),
        ("k3", "doc", "อยู่ที่หรือเพิ่งผ่านจุดคุ้มทุนของกำลังการผลิตใหม่ล่าสุดหรือไม่"),
        ("k4", "auto", "รายได้เพิ่มทุก 100 บาท ตกถึงกำไรเท่าไร"),
    ]),
    ("ราคา", [
        ("p1", "auto", "PE บนกำไรปกติ (ตัดรายการพิเศษ) เท่าไร"),
        ("p2", "auto", "ถ้าการเติบโตไม่มา PE และปันผลจำกัดความเสียหายได้หรือไม่"),
        ("p3", "owner", "ถ้าการเติบโตมา กำไรและ PE ระดับไหนให้ผลตอบแทน 50–100%"),
        ("p4", "auto", "PEG ต่ำกว่า 1 หรือไม่"),
        ("p5", "auto", "กำไรกลายเป็นเงินปันผลสดหรือไม่"),
    ]),
    ("จังหวะและแผน", [
        ("t1", "doc", "มีเหตุชั่วคราวที่ทำให้ผลไตรมาสถัดไปดูแย่หรือไม่"),
        ("t2", "owner", "เขียนไว้แล้วหรือยังว่าคาดหวังอะไรในแต่ละไตรมาส"),
        ("t3", "owner", "เขียนแผนขายไว้ก่อนเกิดเหตุการณ์แล้วหรือยัง"),
        ("t4", "owner", "ถ้าไม่มีหุ้นอยู่เลย วันนี้จะซื้อที่ราคานี้หรือไม่"),
    ]),
    ("พอร์ต", [
        ("g1", "owner", "ไม่ใช้มาร์จิ้นใช่หรือไม่"),
        ("g2", "owner", "ถ้าหุ้นตัวนี้ผิดพลาด พอร์ตอยู่รอดได้หรือไม่"),
        ("g3", "owner", "ครอบครัวถือต่อได้หรือไม่ถ้าไม่มีผม"),
    ]),
]


def _pct(x, d=1):
    return "–" if x is None else "%.*f%%" % (d, x * 100)


def _snapshot_angles(p):
    """The quarterly signals live in the snapshot pack (angles). Returns {} when it has not been built."""
    f = os.path.join(p.get("stock_dir") or "", "report", "%s_snapshot_data.json" % p.get("ticker"))
    try:
        return (json.load(open(f, encoding="utf-8")).get("angles") or {})
    except (OSError, ValueError):
        return {}


def _auto(p, iid):
    """-> (status, evidence) for an auto item. status in pass / fail / info."""
    L, fys = p["lines"], p["fys"]
    last = L[fys[-1]]
    v = (p.get("expect") or {}).get("valuation") or {}
    lc = p.get("lifecycle") or {}
    if iid == "c1":
        rows = (p.get("sector") or {}).get("rows") or []
        r = next((x for x in rows if x["key"] == "post"), None) or (rows[-1] if rows else None)
        if not r or r.get("gap") is None:
            return "info", "ไม่มีข้อมูลอุตสาหกรรม (รัน sector_trend.py / ตั้ง AI_ROOT)"
        return ("pass" if r["gap"] > 0 else "fail"), "%s: หุ้น %s เทียบมัธยฐานกลุ่ม %s (ส่วนต่าง %+.1f pt, อันดับ %s/%s)" % (
            r["label"], _pct(r["stock"]), _pct(r["median"]), r["gap"] * 100, r["rank"], r["n"])
    if iid == "c2":
        g = lc.get("gpm_trend_3y")
        if g is None:
            return "info", "ไม่พอข้อมูล"
        return ("pass" if g >= 0 else "fail"), "GPM เปลี่ยน %+.2f pt จากฐานปี %s" % (g * 100, lc.get("base"))
    if iid == "c3":
        allp = [x for x in p.get("peers") or [] if x.get("ticker") != p["ticker"] and x.get("gpm") is not None]
        peers = [x for x in allp if x.get("category") == p.get("category")]      # same business model only (clinic chains run 50% GPM)
        me = last.get("gpm")
        if len(peers) < 3 or me is None:
            return "info", "คู่แข่งหมวดเดียวกันในตารางเทียบกลุ่มไม่พอ (ต้องรัน finance sheet ของคู่แข่งก่อน)"
        med = st.median(x["gpm"] for x in peers)
        return ("pass" if me >= med else "fail"), "GPM %s เทียบมัธยฐานกลุ่มหมวดเดียวกัน %s (%d บริษัท: %s)" % (
            _pct(me), _pct(med), len(peers), ", ".join(x["ticker"] for x in peers))
    if iid in ("k1", "k2"):
        an = _snapshot_angles(p)
        if iid == "k1":
            t = an.get("da_trend")
            if not t:
                return "info", "ยังไม่มีสัญญาณรายไตรมาส (รัน snapshot.py data ก่อน)"
            return ("pass" if t["quarters_flat"] >= 4 else "fail"), t["text"]
        cm = an.get("commit")
        if not cm:
            return "info", "ไม่พบหมายเหตุภาระผูกพันรายจ่ายฝ่ายทุนในงบล่าสุด"
        down = cm.get("cons_prior") and (cm["cons"] - cm["cons_prior"]) / cm["cons_prior"] < -0.3
        return ("pass" if down else "fail"), cm["text"]
    if iid == "k4":
        inc = last.get("incr_gpm")
        if inc is None:
            return "info", "ไม่พอข้อมูล"
        return "info", "GP ส่วนเพิ่ม %.1f บาทต่อรายได้เพิ่ม 100 บาท (GPM เฉลี่ย %s) — ก่อนหักค่าขายและบริหาร" % (inc * 100, _pct(last.get("gpm")))
    if iid == "p1":
        if v.get("pe") is None:
            return "info", "ไม่มีราคาตลาด"
        return "info", "P/E กำไรปกติ TTM %.1f เท่า (earning yield %s)" % (v["pe"], _pct(v.get("earn_yield")))
    if iid == "p2":
        if v.get("pe") is None:
            return "info", "ไม่มีราคาตลาด"
        return "info", "P/E %.1f เท่า + ปันผลตอบแทน %s — ตัวเลขประกอบการตัดสินใจของเจ้าของพอร์ต ไม่ใช่คำตอบ" % (v["pe"], _pct(v.get("yield")))
    if iid == "p4":
        if v.get("peg") is None:
            return "info", "ไม่มี PEG"
        return ("pass" if v["peg"] < 1 else "fail"), "PEG %.2f (จากกำไรโต TTM %s); จากฐานปี %s: %.2f" % (
            v["peg"], _pct(v.get("np_g")), lc.get("base"), v.get("peg_cagr3") or float("nan"))
    if iid == "p5":
        po, dps = last.get("payout"), last.get("dps")
        if po is None:
            return "info", "ไม่มีข้อมูลปันผล"
        return ("pass" if po >= 0.4 else "fail"), "ปันผล %.2f บาท/หุ้น คิดเป็น %s ของกำไร (ปีล่าสุด); เงินสดสุทธิ %.0f ลบ." % (
            dps or 0, _pct(po), last.get("net_cash") or 0)
    return "info", ""


def evaluate(p, nar):
    """-> list of (group, [row dict]) ; row = {id, kind, q, status, icon, text, src}"""
    pc = (nar or {}).get("pop_checklist") or {}
    po = (nar or {}).get("pop_owner") or {}
    out = []
    for g, items in ITEMS:
        rows = []
        for iid, kind, q in items:
            src = ""
            if kind == "auto":
                status, text = _auto(p, iid)
            elif kind == "doc":
                a = pc.get(iid) or {}
                status = a.get("status") if a.get("status") in STATUS else "open"
                w_ = a.get("why")
                text = (w_.get("text") if isinstance(w_, dict) else w_) or "ยังไม่ได้ประเมินจากเอกสาร"
                src = (w_.get("src") if isinstance(w_, dict) else None) or a.get("src") or ""
            else:
                a = po.get(iid) or {}
                status = "owner"
                text = a.get("note") or a.get("answer") or "รอเจ้าของพอร์ตตอบเอง"
            rows.append({"id": iid, "kind": kind, "q": q, "status": status, "icon": ICON.get(status, "⬜"), "text": text, "src": src})
        out.append((g, rows))
    return out


def problems(p, nar):
    """Rules for `check`: the narrative may answer doc items (with a src) and owner items; it may not invent ids."""
    errs = []
    known_doc = {i for _, its in ITEMS for i, k, _ in its if k == "doc"}
    known_owner = {i for _, its in ITEMS for i, k, _ in its if k == "owner"}
    for iid, a in ((nar or {}).get("pop_checklist") or {}).items():
        if iid not in known_doc:
            errs.append("pop_checklist.%s: not a document-based item (valid: %s)" % (iid, ", ".join(sorted(known_doc))))
            continue
        if not isinstance(a, dict) or a.get("status") not in STATUS:
            errs.append("pop_checklist.%s: status must be one of %s" % (iid, "/".join(STATUS)))
        else:
            w_ = a.get("why")
            txt, src = (w_.get("text"), w_.get("src") or a.get("src")) if isinstance(w_, dict) else (w_, a.get("src"))
            ext = a.get("external") or (isinstance(w_, dict) and w_.get("external"))
            if not (txt and (src or ext)):
                errs.append("pop_checklist.%s needs `why` as {\"text\", \"src\"} (or external: true)" % iid)
    for iid in ((nar or {}).get("pop_owner") or {}):
        if iid not in known_owner:
            errs.append("pop_owner.%s: not an owner item (valid: %s)" % (iid, ", ".join(sorted(known_owner))))
    return errs
