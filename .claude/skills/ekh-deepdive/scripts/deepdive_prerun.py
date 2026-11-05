#!/usr/bin/env python3
"""
deepdive_prerun.py - run BEFORE asking Claude for a deep dive. No AI, no network, no tokens.

For each ticker it
  1. checks what is ready (financials, MD&A mix, assumptions, hospitals.json, narrative, factsheets, source text)
     and flags problems (files of another ticker in the folder, duplicate source files, scaffold-only assumptions);
  2. runs the deterministic data layer (`deepdive.py data`) so the numbers pack + digest already exist;
  3. greps the tier-1/2 source text for each topic Claude must write about (beds, branches, mix, SSO, guidance,
     capex, land, dividend policy, team, competitors, juristic ids) and writes file:line evidence;
  4. estimates the Claude work left and the token budget.

Output per ticker:  report/<T>_deepdive_prerun.md  (+ .json)
Claude then reads ONLY that file plus the lines it points to, instead of whole One Reports / MD&A dumps.

Usage (WSL, venv):
  python3 deepdive_prerun.py RJH BH NTV EKH RPH --root "/mnt/c/ai/Thstock"
  python3 deepdive_prerun.py -f tickers.txt --no-data          # evidence + readiness only
"""
import argparse, glob, hashlib, json, os, re, subprocess, sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import deepdive as DD  # noqa: E402  (also puts stock-snapshot/scripts on sys.path)
S = DD.S

SECRET = re.compile(r"cookie|token|secret|credential|password|passwd|login_debug|\.env$|session|apikey|api_key|(^|[_\-.])key([_\-.]|$)", re.I)
HOSPITAL_TICKERS = "AHC BCH BDMS BH CHG EKH KDH LPH NEW NTV PHG PR9 PYT RAM RJH RPH SKR SVH THG VIBHA VIH WPH CMR M-CHAI".split()

TOPICS = [
    ("beds", "เตียง / อัตราครองเตียง / ห้องตรวจ (ข้อ 0, 4)",
     r"เตียง|อัตราการครองเตียง|อัตราครองเตียง|occupan|ห้องตรวจ|\bbeds?\b"),
    ("branches", "โรงพยาบาลในเครือ / ที่ตั้ง (ข้อ 0)",
     r"บริษัทย่อย|โรงพยาบาลในเครือ|สาขา|ตั้งอยู่|เลขที่.*(ถนน|ถ\.)|subsidiar"),
    ("juristic", "เลขทะเบียนนิติบุคคล (ใช้ดึงงบ DBD ข้อ 3.2)",
     r"ทะเบียนนิติบุคคล|เลขทะเบียน|registration no|\b0\d{12}\b"),
    ("mix", "รายได้ OPD/IPD/ประกันสังคม/ชำระเอง/ต่างชาติ (ข้อ 3)",
     r"ผู้ป่วยนอก|ผู้ป่วยใน|\bOPD\b|\bIPD\b|ประกันสังคม|ชำระเงินเอง|เงินสด|ต่างชาติ|international|คู่สัญญา|ประกันสุขภาพ"),
    ("sso", "ผู้ประกันตน / โควตา / อัตราเหมาจ่าย (ข้อ 1, 3)",
     r"ผู้ประกันตน|โควต้า|โควตา|เหมาจ่าย|capitation|AdjRW|RW\b"),
    ("guidance", "เป้าหมาย / guidance ผู้บริหาร (ข้อ 12)",
     r"เป้าหมาย|ตั้งเป้า|คาดว่า.*(ปี|เติบโต)|guidance|target|แนวโน้ม"),
    ("capex", "โครงการลงทุน / อาคารใหม่ / S-curve (ข้อ 7, 12)",
     r"แผนการลงทุน|งบลงทุน|capex|โครงการ|อาคารใหม่|ก่อสร้าง|เปิดให้บริการ|EIA"),
    ("land", "ที่ดิน / สิทธิการเช่า (ข้อ 0)",
     r"ไร่|ตารางวา|ตร\.?ว\.|สิทธิการเช่า|เช่าที่ดิน|ที่ดิน"),
    ("dividend", "นโยบายเงินปันผล (ข้อ 12)",
     r"นโยบายการจ่ายเงินปันผล|เงินปันผล|dividend policy|payout"),
    ("team", "ผู้บริหาร / ทีม (ข้อ 6)",
     r"กรรมการผู้จัดการ|ประธานเจ้าหน้าที่บริหาร|\bCEO\b|\bCFO\b|ผู้อำนวยการโรงพยาบาล|ผู้ถือหุ้นรายใหญ่"),
    ("competitors", "คู่แข่ง / ภาวะการแข่งขัน (ข้อ 0, 6)",
     r"คู่แข่ง|การแข่งขัน|competit|ส่วนแบ่งตลาด|market share"),
]


def _tok(chars):          # Thai-heavy text: ~2 characters per token
    return int(chars / 2)


def source_files(sdir):
    """tier-1/2 text the deep dive reads (same set as deepdive.candidates + top-level .txt), secrets skipped."""
    fs = (glob.glob(os.path.join(sdir, "md", "raw", "*.md")) + glob.glob(os.path.join(sdir, "PDF", "*.txt")) +
          glob.glob(os.path.join(sdir, "md", "*.md")) + glob.glob(os.path.join(sdir, "*.md")) + glob.glob(os.path.join(sdir, "*.txt")))
    return sorted(f for f in set(fs) if not SECRET.search(os.path.basename(f)))


def classify(name):
    n = name.lower()
    if re.search(r"one_?report|annual_report|56-1|e1n|one\b", n):
        return "One Report (tier 1)"
    if re.search(r"mda|md&a|nws", n):
        return "MD&A (tier 1)"
    if re.search(r"oppday|presentation|agm|progress|plan|jump", n):
        return "Company presentation (tier 1/2)"
    if re.search(r"financial|fs\d", n):
        return "Statements (tier 1, already parsed)"
    if re.search(r"factsheet|jitta", n):
        return "Factsheet (tier 2)"
    if re.search(r"company report|earnings|sector report|tp ?thb|maintain|buy|hold|by-asps|paper|thaivi", n):
        return "Broker / forum (tier 3 lead only)"
    return "Other"


def readiness(sdir, t):
    rep = os.path.join(sdir, "report")
    def f(n):
        return os.path.join(rep, n % t)
    chk, gaps = [], []
    def add(label, ok, note=""):
        chk.append({"item": label, "ok": bool(ok), "note": note})
    add("financials.json (งบจาก filing)", os.path.isfile(f("%s_financials.json")))
    mda = S.load_json(f("%s_mda.json")) if os.path.isfile(f("%s_mda.json")) else {}
    add("mda.json (สัดส่วนรายได้จาก MD&A)", bool(mda), "%d bytes" % os.path.getsize(f("%s_mda.json")) if mda else "")
    asm = S.load_json(f("%s_assumptions.json")) if os.path.isfile(f("%s_assumptions.json")) else {}
    real_asm = bool(asm.get("revenue_mix")) or len(json.dumps(asm)) > 2500
    add("assumptions.json มี revenue_mix / one-offs จริง", real_asm, "scaffold เท่านั้น" if asm and not real_asm else "")
    hj = S.load_json(f("%s_hospitals.json")) if os.path.isfile(f("%s_hospitals.json")) else {}
    add("hospitals.json (รายสาขา)", bool(hj))
    add("hospitals.json: sites (พิกัด/ที่ดิน, ข้อ 0)", bool(hj.get("sites")))
    add("hospitals.json: dbd_pnl (งบรายนิติบุคคล, ข้อ 3.2)", bool(hj.get("dbd_pnl")))
    nar = f("%s_deepdive_narrative.json")
    add("deepdive_narrative.json", os.path.isfile(nar), "%d KB" % (os.path.getsize(nar) // 1024) if os.path.isfile(nar) else "")
    if os.path.isfile(nar):
        n = S.load_json(nar)
        add("narrative: sector_view (ข้อ 1)", bool(n.get("sector_view")))
        add("narrative: expectation/valuation", bool(n.get("expectation")))
    root = S.ai_root(sdir)
    jit = glob.glob(os.path.join(root, "data", "Factsheet", "factsheet_jitta_%s.json" % t))
    add("Jitta factsheet 10 ปี (ข้อ 2)", jit, "" if jit else "data/Factsheet/factsheet_jitta_%s.json" % t)
    add("SET factsheet (ราคา/หุ้น)", [x for d in ("set/factsheet", "factsheet", "md/factsheets")   # same places as snapshot.py
                                       for x in glob.glob(os.path.join(sdir, d, "factsheet_set_%s.json" % t))])
    add("md/raw combined_*_all.md", glob.glob(os.path.join(sdir, "md", "raw", "combined_*_all.md")))
    for c in chk:
        if not c["ok"]:
            gaps.append(c["item"])
    return chk, gaps


def contamination(sdir, t):
    """Files that look like another ticker's (e.g. a PR9 readme copied into NTV)."""
    out = []
    others = [x for x in HOSPITAL_TICKERS if x != t]
    for p in os.listdir(sdir):
        if SECRET.search(p):
            continue
        m = re.match(r"^(?:readme_|thaivi-100p-)?([A-Z0-9\-]{2,6})(?:__|_|-| )", p, re.I)
        if m and m.group(1).upper() in others:
            out.append(p)
    codes = sorted({m.group(1) for d in glob.glob(os.path.join(sdir, "FS_*")) for m in [re.search(r"_(\d{4})FIN", d)] if m})
    if len(codes) > 1:
        out.append("FS_ folders carry more than one company code: %s" % ", ".join(codes))
    return out


def _context(path, line, before):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            ls = fh.readlines()
    except OSError:
        return ""
    return " / ".join(x.strip() for x in ls[max(0, line - 1 - before):line] if x.strip())


def duplicates(files):
    seen, dup = {}, []
    for f in files:
        try:
            h = hashlib.md5(open(f, "rb").read()).hexdigest()
        except OSError:
            continue
        if h in seen:
            dup.append((os.path.basename(f), os.path.basename(seen[h])))
        else:
            seen[h] = f
    return dup


def run_data(t, sdir, root):
    cmd = [sys.executable, os.path.join(HERE, "deepdive.py"), "data", "--ticker", t, "--stock-dir", sdir] + (["--root", root] if root else [])
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout + r.stderr)[-1500:]


def estimate(gaps, ev_chars, has_nar):
    """Effective-token budget for the Claude part (instructions re-read each step, reading, writing, checking)."""
    base = 300_000                                   # instructions + context re-read across ~30-40 steps
    read = _tok(ev_chars) * 4 + 120_000              # evidence pack + the source lines it points to, re-read
    write = (60_000 if has_nar else 160_000) * 5 // 4  # narrative JSON output (output weighted 5x, partly cached)
    extra = 0
    if any("sites" in g for g in gaps):
        extra += 150_000                             # Google Places look-ups + coordinates
    if any("dbd_pnl" in g for g in gaps):
        extra += 250_000                             # DBD DataWarehouse per subsidiary (browser)
    if any("revenue_mix" in g for g in gaps):
        extra += 150_000                             # MD&A revenue mix into assumptions
    lo = base + read + write + extra
    return int(lo * 0.8), int(lo * 1.4)


def prerun(t, sdir, root, do_data=True, per_topic=25):
    rep = os.path.join(sdir, "report")
    os.makedirs(rep, exist_ok=True)
    chk, gaps = readiness(sdir, t)
    files = source_files(sdir)
    inv = []
    for f in files:
        sz = os.path.getsize(f)
        k = classify(os.path.basename(f))
        inv.append({"file": os.path.relpath(f, sdir), "kind": k, "kb": sz // 1024,
                    "tokens_if_read_whole": 0 if k.startswith("Statements") else _tok(sz)})
    tier3 = [x for x in inv if x["kind"].startswith("Broker")]
    data_out = ""
    if do_data:
        rc, data_out = run_data(t, sdir, root)
        if rc:
            gaps.append("deepdive.py data failed (rc=%d)" % rc)
    tier12 = [f for f in files if not classify(os.path.basename(f)).startswith("Broker")]
    ev = {}
    for key, label, rx in TOPICS:
        hits = DD.candidates(sdir, rx, per_topic, files=tier12)
        if key == "juristic":                        # a bare id is useless without the company name above it
            for h in hits:
                h["text"] = _context(os.path.join(sdir, h["file"]), h["line"], 2)[:240]
        ev[key] = {"label": label, "hits": hits}
    ev_chars = sum(len(h["text"]) + 40 for v in ev.values() for h in v["hits"])
    has_nar = os.path.isfile(os.path.join(rep, "%s_deepdive_narrative.json" % t))
    lo, hi = estimate(gaps, ev_chars, has_nar)
    whole = sum(x["tokens_if_read_whole"] for x in inv)
    res = {"ticker": t, "generated": datetime.now().isoformat(timespec="seconds"), "readiness": chk, "gaps": gaps,
           "contamination": contamination(sdir, t), "duplicates": duplicates(files), "inventory": inv,
           "evidence": ev, "estimate_effective_tokens": [lo, hi], "tokens_if_reading_all_sources": whole,
           "mode": "refresh" if has_nar else "new"}
    json.dump(res, open(os.path.join(rep, "%s_deepdive_prerun.json" % t), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    L = ["# %s — deep dive pre-run (%s)" % (t, res["generated"]), "",
         "_ไฟล์นี้สร้างด้วยสคริปต์ ไม่มี AI. ให้ Claude อ่านไฟล์นี้ก่อน แล้วเปิดเฉพาะบรรทัดที่ชี้ ไม่ต้องอ่านเอกสารทั้งเล่ม_", "",
         "**โหมด:** %s · **งบ token (ประมาณ, effective):** %s–%s · ถ้าอ่านเอกสารทั้งหมดตรง ๆ: ~%s tokens" % (
             "refresh (มี narrative แล้ว)" if has_nar else "ทำใหม่ทั้งฉบับ", "{:,}".format(lo), "{:,}".format(hi), "{:,}".format(whole)), "",
         "## 1. ความพร้อม", "", "| รายการ | พร้อม | หมายเหตุ |", "| :--- | :---: | :--- |"]
    L += ["| %s | %s | %s |" % (c["item"], "✅" if c["ok"] else "❌", c["note"]) for c in chk]
    if res["contamination"]:
        L += ["", "**⚠ ไฟล์ที่น่าจะเป็นของหุ้นตัวอื่น (ตรวจก่อนใช้):**"] + ["- %s" % x for x in res["contamination"]]
    if res["duplicates"]:
        L += ["", "**ไฟล์ซ้ำ (เนื้อหาเหมือนกัน — อ่านแค่ไฟล์เดียว):**"] + ["- %s = %s" % d for d in res["duplicates"][:30]]
    L += ["", "## 2. เอกสารต้นทาง", "", "| ไฟล์ | ประเภท | KB |", "| :--- | :--- | ---: |"]
    L += ["| %s | %s | %d |" % (x["file"], x["kind"], x["kb"]) for x in sorted(inv, key=lambda x: (x["kind"], x["file"]))]
    if tier3:
        L += ["", "_ไฟล์ broker/forum เป็น tier 3: ใช้เป็นเบาะแสเท่านั้น ไม่ถูกนำมาค้นในข้อ 3_"]
    L += ["", "## 3. หลักฐานรายหัวข้อ (file:line — เปิดอ่านรอบ ๆ บรรทัดนี้)", ""]
    for key, v in ev.items():
        L += ["### %s" % v["label"], ""]
        if not v["hits"]:
            L += ["- (ไม่พบ — ต้องหาเอกสารเพิ่มหรือถามบริษัท)", ""]
            continue
        L += ["- `%s:%d` %s" % (h["file"], h["line"], h["text"].replace("|", "/")) for h in v["hits"]] + [""]
    L += ["## 4. สิ่งที่ Claude ต้องทำ", ""]
    todo = []
    if any("revenue_mix" in g for g in gaps):
        todo.append("เติม revenue_mix ใน assumptions.json จาก MD&A (หัวข้อ mix ด้านบน) แล้ว build finance sheet ใหม่")
    if any("hospitals.json" in g for g in gaps):
        todo.append("สร้าง report/%s_hospitals.json: รายชื่อ รพ./เตียง (หัวข้อ beds, branches)" % t)
    if any("sites" in g for g in gaps):
        todo.append("เติม sites (พิกัด Google Places, ที่ดิน, payor) + competitors รัศมี 10 กม.")
    if any("dbd_pnl" in g for g in gaps):
        todo.append("ดึงงบรายนิติบุคคลจาก DBD DataWarehouse ด้วยเลขทะเบียน (หัวข้อ juristic)")
    todo.append("เขียน/อัปเดต report/%s_deepdive_narrative.json (sector_view, expectation, capacity, roadmap, macro, scorecard)" % t)
    todo.append("render → check ต้อง CLEAN")
    L += ["%d. %s" % (i + 1, x) for i, x in enumerate(todo)]
    if data_out:
        L += ["", "## 5. ผลรัน deepdive.py data (ท้าย log)", "", "```", data_out.strip()[-1200:], "```"]
    out = os.path.join(rep, "%s_deepdive_prerun.md" % t)
    open(out, "w", encoding="utf-8").write("\n".join(L) + "\n")
    return res, out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tickers", nargs="*")
    ap.add_argument("-f", "--file")
    ap.add_argument("--root", help="Thstock folder (default: same search as deepdive.py)")
    ap.add_argument("--no-data", action="store_true", help="skip running deepdive.py data")
    ap.add_argument("--per-topic", type=int, default=15)
    a = ap.parse_args()
    ts = [x.upper() for x in a.tickers]
    if a.file:
        for ln in open(a.file, encoding="utf-8"):
            ts += [x.upper() for x in re.split(r"[,\s]+", ln.split("#")[0].strip()) if x]
    root = S.find_root(a.root)
    if not root:
        sys.exit("Thstock root not found; pass --root")
    rows = []
    for t in dict.fromkeys(ts):
        sdir = os.path.join(root, t)
        if not os.path.isdir(sdir):
            rows.append((t, "folder missing", "", ""))
            continue
        print("━━━ %s ━━━" % t)
        res, out = prerun(t, sdir, a.root, not a.no_data, a.per_topic)
        lo, hi = res["estimate_effective_tokens"]
        print("   → %s" % out)
        rows.append((t, res["mode"], "%.1f–%.1fM" % (lo / 1e6, hi / 1e6), "; ".join(res["gaps"][:4]) + (" …" if len(res["gaps"]) > 4 else "")))
    print("\n━━━ Summary ━━━")
    for r in rows:
        print(" %-6s %-8s %-11s %s" % r)
    tot = sum(float(r[2].split("–")[1][:-1]) for r in rows if r[2])
    print(" total (upper bound) ≈ %.1fM effective tokens" % tot)


if __name__ == "__main__":
    main()
