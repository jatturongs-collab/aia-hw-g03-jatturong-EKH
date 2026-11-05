#!/usr/bin/env python3
"""
second_source.py - prepare SECOND-TIER sources (news, interviews, third-party presentations, video transcripts)
for the snapshot / deep-dive narrative. Script only, no tokens.

Source tiers
  tier 1  what the company filed with SET/SEC: financial statements, MD&A, Opportunity Day slides and transcript,
          56-1 One Report, the SET factsheet. Every table figure comes from here.
  tier 2  everything in <stock>/md/second_source/: news, interviews, an investor's presentation, a YouTube transcript,
          and the owner's own records: visit_<YYYY-MM-DD>.md (company visit: what management said to the owner) and
          note_<YYYY-MM-DD>.md (the owner's note). Named person, but no document others can check, so tier 2.
          It may add context or reasons, always shown as external. It never replaces a tier-1 figure. Where it
          contradicts tier 1, the narrative lists the contradiction under `conflicts` and the report flags it.

    python3 second_source.py --stock-dir "<Thstock>/RJH"            # build / refresh the reading pack
    python3 second_source.py --stock-dir "<Thstock>/RJH" --add file1.txt file2.md   # copy files in, then build

For every file in md/second_source/ (txt, md) it writes md/second_source/_pack/<name>.claims.md: only the passages
that state a figure or talk about a key topic, each with a line reference into a re-wrapped copy
(<name>.lines.txt, one sentence-sized line per row, so "second_source/<name>:L123" can be cited and checked).
index.json lists the files with size, kind and the date found in the file name or text.
"""
import argparse
import datetime as dt
import json
import os
import re
import shutil

import quarter_docs as QD

RE_DATE = re.compile(r"(20\d{2}|25\d{2})[-_.]?(0[1-9]|1[0-2])[-_.]?([0-2]\d|3[01])")
SPLIT = re.compile(r"(?<=ครับ)\s+|(?<=นะคะ)\s+|(?<=ค่ะ)\s+|(?<=[.!?])\s+(?=\D)|\n+")
# The owner's own records come first: decided by the file name (visit_<date>.md, note_<date>.md).
KIND = [("visit", re.compile(r"^visit[_-]|company ?visit|เยี่ยมชมกิจการ", re.I)),
        ("note", re.compile(r"^note[_-]", re.I)),
        ("transcript", re.compile(r"transcript|คลิป|youtube|ถอดเทป", re.I)),
        ("interview", re.compile(r"สัมภาษณ์|interview|money ?talk", re.I)),
        ("broker", re.compile(r"บล\.|Analyst Note|ราคาเป้าหมาย|TB,", re.I)),
        ("news", re.compile(r"ข่าว|news|ผู้สื่อข่าว|เปิดเผยว่า", re.I))]
# words that make a passage a checkable claim about the company
CLAIM = re.compile(r"รายได้|กำไร|ขาดทุน|มาร์จิ้น|margin|GPM|NPM|EBITDA|เตียง|ผู้ประกันตน|ครองเตียง|occupancy|ปันผล|หนี้|"
                   r"เงินสด|ลงทุน|capex|P/?E|ราคา|ต้นทุน|ค่าเสื่อม|เป้า|target|เปิด|สาขา|ถือหุ้น|ส่วนแบ่ง|เติบโต|โต", re.I)


def wrap(text, width=220):
    """Sentence-sized lines: transcripts often arrive as one very long line."""
    out = []
    for part in SPLIT.split(text):
        part = re.sub(r"\s+", " ", part).strip()
        while len(part) > width:
            cut = part.rfind(" ", 0, width)
            cut = cut if cut > width * 0.5 else width
            out.append(part[:cut].strip())
            part = part[cut:].strip()
        if part:
            out.append(part)
    return out


def file_date(name, text):
    m = RE_DATE.search(name) or RE_DATE.search(text[:600])
    if not m:
        return None
    y = int(m.group(1))
    y = y - 543 if y > 2400 else y
    try:
        return dt.date(y, int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None


def build(sdir, max_chars=16000):
    d = os.path.join(sdir, "md", "second_source")
    if not os.path.isdir(d):
        return []
    pack = os.path.join(d, "_pack")
    os.makedirs(pack, exist_ok=True)
    weights = QD.load_keywords(sdir)
    index = []
    for f in sorted(os.listdir(d)):
        p = os.path.join(d, f)
        if not os.path.isfile(p) or not f.lower().endswith((".txt", ".md")):
            continue
        text = open(p, encoding="utf-8", errors="replace").read()
        stem = os.path.splitext(f)[0]
        lines = wrap(text)
        open(os.path.join(pack, stem + ".lines.txt"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
        # passages: keyword-weighted blocks (same scorer as the Oppday pack) restricted to ones that carry a claim
        body = QD.qa_passages(lines, max_chars=max_chars, block=3, weights=weights)
        kept = [ln for ln in body.split("\n") if ln == "…" or (CLAIM.search(ln) and QD.NUM.search(ln)) or len(ln) < 4]
        claims = "\n".join(kept)
        kind = next((k for k, rx in KIND if rx.search(f) or rx.search(text[:1500])), "other")
        hdr = ("<!-- SECOND SOURCE (tier 2): %s | kind=%s | not from SET filings. Use as context only, always external.\n"
               "     A figure here never replaces a statement figure. If it contradicts the data pack, MD&A or Oppday,\n"
               "     list it under `conflicts` in the narrative. Cite as second_source/%s:L<n> (lines in _pack/%s.lines.txt). -->\n"
               % (f, kind, stem, stem))
        out = os.path.join(pack, stem + ".claims.md")
        open(out, "w", encoding="utf-8").write(hdr + claims + "\n")
        index.append({"file": f, "kind": kind, "date": file_date(f, text), "chars": len(text), "lines": len(lines),
                      "claims": os.path.relpath(out, sdir), "claims_chars": len(claims),
                      "claims_tokens_est": QD.tokens_est(claims),
                      "mtime": dt.datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d")})
    json.dump(index, open(os.path.join(pack, "index.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return index


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stock-dir", required=True)
    ap.add_argument("--add", nargs="*", help="files to copy into md/second_source/ first")
    a = ap.parse_args()
    d = os.path.join(a.stock_dir, "md", "second_source")
    os.makedirs(d, exist_ok=True)
    for f in a.add or []:
        shutil.copy(f, os.path.join(d, os.path.basename(f)))
    for e in build(a.stock_dir):
        print("%-40s %-10s %s  %6d chars -> %s (%d chars, ~%d tokens)" % (
            e["file"][:40], e["kind"], e["date"] or e["mtime"] + "*", e["chars"], e["claims"], e["claims_chars"], e["claims_tokens_est"]))


if __name__ == "__main__":
    main()
