#!/usr/bin/env python3
"""
quarter_docs.py - build the per-quarter reading pack for the snapshot narrative (script only, no tokens).

For quarter X it writes <stock>/md/quarter/<BE>Q<q>/:
  mda.md            the quarter's MD&A (English version first when the company published one - fewer tokens)
  oppday_slides.md  the quarter's Opportunity Day slides, without disclaimer / agenda / ESG pages
  oppday_qa.md      only the transcript passages that talk about revenue drivers, prices, payors, occupancy,
                    costs, targets, capex, dividends ... each with its line number in the full transcript
  README.md         what is in the folder, sizes and token estimates
Only documents of quarter X are used, so a back-dated report cannot see later documents.
"""
import glob, json, os, re

KEYWORDS = [
    # revenue drivers / payors
    "รายได้", "ผู้ป่วยนอก", "ผู้ป่วยใน", "OPD", "IPD", "ประกันสังคม", "สปส", "ผู้ประกันตน", "บัตรทอง", "สปสช", "เหมาจ่าย",
    "RW", "DRG", "ต่างชาติ", "ต่างด้าว", "ประกันสุขภาพ", "ประกันชีวิต", "copay", "โคเพย์", "คู่สัญญา", "เงินสด",
    "เคส", "ราย", "ต่อหัว", "ต่อครั้ง", "ต่อวัน", "ครองเตียง", "occupancy", "เตียง", "โรคระบาด", "ไข้หวัด", "RSV",
    "หัวใจ", "cath", "แคท", "ผ่าตัด", "ศูนย์", "excellent", "ตรวจสุขภาพ",
    # price, cost, margin
    "ราคา", "ขึ้นราคา", "ปรับราคา", "ต้นทุน", "ค่าแพทย์", "ค่าแรง", "เงินเดือน", "โบนัส", "มาร์จิ้น", "margin", "กำไรขั้นต้น",
    "ค่าใช้จ่าย", "หนี้สงสัยจะสูญ", "ECL", "ลูกหนี้", "สำรอง", "คดี",
    # outlook, capex, capital
    "เป้า", "target", "guidance", "คาดว่า", "ปีหน้า", "ไตรมาส", "เติบโต", "โรงพยาบาลใหม่", "เปิด", "ลงทุน", "capex",
    "ปันผล", "dividend", "ซื้อหุ้นคืน", "M&A", "ซื้อกิจการ", "วอร์แรนท์", "warrant",
]
# topics an analyst would not want to miss: weight 3 (other keywords weigh 1; very common words 0.5)
PRIORITY = {"ปรับราคา", "ขึ้นราคา", "ครองเตียง", "occupancy", "เป้า", "target", "guidance", "DRG", "RW", "โรงพยาบาลใหม่",
            "ปันผล", "dividend", "M&A", "ซื้อกิจการ", "สปสช", "บัตรทอง", "ECL", "หนี้สงสัยจะสูญ", "คดี", "copay", "โคเพย์",
            "ต่างด้าว", "ผู้ประกันตน", "เหมาจ่าย", "ซื้อหุ้นคืน", "ค่าแพทย์"}
COMMON = {"รายได้", "ไตรมาส", "ราย", "เคส", "ศูนย์", "เปิด", "เติบโต", "ค่าใช้จ่าย", "คาดว่า", "ต้นทุน"}
NUM = re.compile(r"\d[\d,.]*\s*(%|เปอร์เซ็นต์|ล้าน|บาท|ราย|เตียง|เท่า)")
DROP_PAGE = re.compile(r"disclaimer|ข้อสงวนสิทธิ|agenda|วาระ|สารบัญ|ESG|ความยั่งยืน|sustainab|CSR|Q\s*&\s*A\s*$|thank you|ขอบคุณ", re.I)
TS = re.compile(r"^\[\d{2}:\d{2}:\d{2}\]\s*")


def tokens_est(text):
    thai = len(re.findall(r"[฀-๿]", text))
    return int(thai * 0.77 + (len(text) - thai) * 0.27)


def _find(sdir, rel):
    p = os.path.join(sdir, rel) if rel else None
    return p if p and os.path.isfile(p) else None


def sources(sdir, q_last):
    """-> dict mda / slides / transcript (paths or None) for CE quarter q_last (e.g. 2026Q2)."""
    ce, qn = int(q_last[:4]), int(q_last[-1])
    be = ce + 543
    key = "%dQ%d" % (be, qn)
    idx = {}
    try:
        idx = (json.load(open(os.path.join(sdir, "md", "index.json"), encoding="utf-8")).get("quarters") or {}).get(key) or {}
    except (OSError, ValueError):
        pass

    def f(v):
        return _find(sdir, v.get("file") if isinstance(v, dict) else v) if v else None
    mda_en = f(idx.get("mda_en")) or _find(sdir, "md/mda/MDA_%d_Q%d_en.md" % (be, qn))
    mda_th = f(idx.get("mda_th")) or _find(sdir, "md/mda/MDA_%d_Q%d.md" % (be, qn))
    if mda_en and os.path.getsize(mda_en) < 3000:
        mda_en = None
    slides = f(idx.get("oppday_slides")) or next(iter(sorted(glob.glob(os.path.join(sdir, "set", "oppday", "oppday_%d_Q%d_*.md" % (ce, qn))))), None)
    trans = f(idx.get("oppday_transcript")) or next(iter(sorted(glob.glob(os.path.join(sdir, "set", "oppday_t", "oppday_%d_Q%d_*.md" % (ce, qn))))), None)
    return {"mda": mda_en or mda_th, "mda_lang": "en" if mda_en else ("th" if mda_th else None), "mda_th": mda_th,
            "slides": slides, "transcript": trans, "key": key}


def clean_slides(text):
    pages = re.split(r"(?=<!-- page \d+ -->)", text)
    keep = []
    for pg in pages:
        body = re.sub(r"<!-- page \d+ -->", "", pg).strip()
        if not body:
            continue
        head = " ".join(body.splitlines()[:3])
        if DROP_PAGE.search(head) and not NUM.search(body):
            continue
        if len(body) < 40:
            continue
        keep.append(pg.strip())
    return "\n\n".join(keep)


HERE = os.path.dirname(os.path.abspath(__file__))


def load_keywords(sdir=None):
    """Built-in list + user files: <skill>/references/oppday_keywords.txt (all stocks) and
    <stock>/md/oppday_keywords.txt (this stock). One term per line; 'term | 3' sets the weight; '#' = comment."""
    weights = {k: (3 if k in PRIORITY else 0.5 if k in COMMON else 1) for k in KEYWORDS}
    for p in [os.path.join(HERE, "..", "references", "oppday_keywords.txt")] + ([os.path.join(sdir, "md", "oppday_keywords.txt")] if sdir else []):
        if not os.path.isfile(p):
            continue
        for ln in open(p, encoding="utf-8"):
            ln = ln.split("#")[0].strip()
            if not ln:
                continue
            term, _, w = ln.partition("|")
            term = term.strip()
            try:
                weights[term] = float(w) if w.strip() else 3.0     # a term the user added is a priority by default
            except ValueError:
                weights[term] = 3.0
    return weights


def qa_passages(lines, max_chars=14000, block=4, weights=None):
    """Score 4-line blocks of a transcript by distinct keywords + figures; keep the best, in order."""
    weights = weights or load_keywords()
    kws = [(k, re.compile(re.escape(k), re.I)) for k in weights]
    blocks = []
    for i in range(0, len(lines), block):
        chunk = lines[i:i + block]
        txt = " ".join(TS.sub("", x).strip() for x in chunk)
        hits = {k for k, rx in kws if rx.search(txt)}
        score = sum(weights[k] for k in hits) + (2 if NUM.search(txt) else 0)
        ts = next((m.group(0).strip() for x in chunk for m in [re.match(r"^\[\d{2}:\d{2}:\d{2}\]", x)] if m), "")
        blocks.append({"i": i, "txt": txt, "score": score, "ts": ts})
    ranked = sorted(blocks, key=lambda b: -b["score"])
    chosen, size = set(), 0
    for b in ranked:
        if b["score"] < 3 or size > max_chars:
            break
        chosen.add(b["i"])
        size += len(b["txt"])
    out, last = [], None
    for b in blocks:
        if b["i"] in chosen:
            if last is not None and b["i"] != last + block:
                out.append("…")
            out.append("[L%d %s] %s" % (b["i"] + 1, b["ts"], b["txt"]))
            last = b["i"]
    return "\n".join(out)


def build(sdir, q_last, force=False):
    src = sources(sdir, q_last)
    outd = os.path.join(sdir, "md", "quarter", src["key"])
    os.makedirs(outd, exist_ok=True)
    made = []

    def write(name, text, origin, note=""):
        p = os.path.join(outd, name)
        hdr = "<!-- source: %s%s -->\n" % (os.path.relpath(origin, sdir) if origin else "-", (" | " + note) if note else "")
        open(p, "w", encoding="utf-8").write(hdr + text.strip() + "\n")
        made.append({"file": os.path.relpath(p, sdir), "chars": len(text), "tokens_est": tokens_est(text), "source": origin and os.path.relpath(origin, sdir)})

    if src["mda"]:
        write("mda.md", open(src["mda"], encoding="utf-8", errors="replace").read(), src["mda"],
              "English MD&A (Thai: %s)" % os.path.relpath(src["mda_th"], sdir) if src["mda_lang"] == "en" and src["mda_th"] else "")
    if src["slides"]:
        write("oppday_slides.md", clean_slides(open(src["slides"], encoding="utf-8", errors="replace").read()), src["slides"],
              "disclaimer/agenda/ESG pages removed")
    if src["transcript"]:
        lines = open(src["transcript"], encoding="utf-8", errors="replace").read().splitlines()
        write("oppday_qa.md", qa_passages(lines, weights=load_keywords(sdir)), src["transcript"],
              "keyword passages only; [Lnnn] = line in the full transcript - open it there for more context")
    full = sum(os.path.getsize(p) for p in (src["mda_th"], src["slides"], src["transcript"]) if p)
    readme = ["# Reading pack %s" % src["key"], "", "| file | chars | tokens (est.) | source |", "|---|---:|---:|---|"]
    readme += ["| %s | %d | %d | %s |" % (m["file"], m["chars"], m["tokens_est"], m["source"]) for m in made]
    readme += ["", "Full documents: %.0f KB. Missing: %s" % (full / 1024, ", ".join(k for k in ("mda", "slides", "transcript") if not src[k]) or "none")]
    open(os.path.join(outd, "README.md"), "w", encoding="utf-8").write("\n".join(readme) + "\n")
    return {"dir": os.path.relpath(outd, sdir), "files": made, "missing": [k for k in ("mda", "slides", "transcript") if not src[k]],
            "full_bytes": full}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stock-dir", required=True)
    ap.add_argument("--quarter", required=True, help="CE quarter, e.g. 2026Q2")
    a = ap.parse_args()
    print(json.dumps(build(a.stock_dir, a.quarter), ensure_ascii=False, indent=1))
