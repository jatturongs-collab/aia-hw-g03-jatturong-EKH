#!/usr/bin/env python3
"""Split a Facebook extraction report (e.g. VIH_By_PoP.md) into one file per post plus an index.

    python3 split_fb_posts.py <report.md> --stock-dir "<Thstock>/VIH"

Writes <stock>/md/analyst_notes/fb/<YYYY-MM-DD>_p<NN>.md (undated posts: undated_p<NN>.md) and
<stock>/md/analyst_notes/fb/index.json. Re-running with a newer extraction only adds posts that are not there yet
(same link), so the folder can grow over time. snapshot.py lists the posts that belong to the report's quarter.

Each post is tagged:
  kind = own       Pop's own analysis (quarterly read, thesis, valuation)
         shared    a broker note / article / other author he re-posted (useful, but not his angle)
         news      short news or event (big lot, shareholder change, invitation)
The tag is a heuristic from the text; it only decides the order in which notes are listed.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re

RE_POST = re.compile(r"\n## 📌 โพสต์ที่ (\d+) \| (.*)")
RE_DATE = re.compile(r"วันที่/เวลา:\*\*\s*(.*)")
RE_LINK = re.compile(r"ลิงก์โพสต์:\*\*\s*\[([^\]]+)\]")
SHARED = re.compile(r"(Analyst Note|บล\.|Small-Cap|FYNNCORP|#Matketeer|MarketeerOnline|KS :|ข้อมูลโดย|ThaiVI|Watchlist|"
                    r"สมัครเลย|คอร์ส|เรียนเชิญ|#chrizano|หนังสือ)", re.I)
NOT_HIS = re.compile(r"(วิตามินหุ้น|Stock Vitamins|By สมาคมนักลงทุน|MrStock|เทรนด์ลงทุน|DAOL|Krungsri|หลักทรัพย์กสิกร|"
                     r"\(.{2,12} TB, (Not Rated|BUY|HOLD|SELL|Outperform|Neutral)|Analyst Note|ราคาเป้าหมาย|ราคาพื้นฐาน|"
                     r"แนะนำ [\"“]?(ซื้อ|ถือ|ขาย)|ผู้สื่อข่าวรายงาน|เปิดเผยว่า)", re.I)
OWN = re.compile(r"(ตัดรายได้อื่น|กำไรก่อนภาษี|จ\.บ\.|#สรุป|ผมคิดว่า|ความคิดเห็นส่วนตัว|เดาๆ|Pay Out|Phase|phase)")


def parse_date(s):
    s = (s or "").strip()
    for fmt in ("%A, %B %d, %Y at %I:%M %p", "%A, %B %d, %Y"):
        try:
            return dt.datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def clean(body):
    lines = [ln.lstrip(">").replace("⁣", "").strip() for ln in body.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def be_quarter(d):
    """The latest quarter whose results were already public on date d (released ~45 days after quarter end,
    Q4 ~60 days). Only a hint for which quarter a post talks about."""
    if not d:
        return None
    for y in (d.year, d.year - 1):
        for q, (m, day) in ((4, (12, 31)), (3, (9, 30)), (2, (6, 30)), (1, (3, 31))):
            if dt.datetime(y, m, day) + dt.timedelta(days=60 if q == 4 else 45) - dt.timedelta(days=5) <= d:
                return "%dQ%d" % (y + 543, q)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("report")
    ap.add_argument("--stock-dir", required=True)
    a = ap.parse_args()
    txt = open(a.report, encoding="utf-8").read()
    out_dir = os.path.join(a.stock_dir, "md", "analyst_notes", "fb")
    os.makedirs(out_dir, exist_ok=True)
    idx_p = os.path.join(out_dir, "index.json")
    index = json.load(open(idx_p, encoding="utf-8")) if os.path.isfile(idx_p) else []
    seen = {e.get("link") for e in index}

    def sig(body):        # same text re-extracted under another link (photo link vs post link) is the same post
        return hashlib.md5(re.sub(r"\s+", "", body).encode("utf-8")).hexdigest()
    sigs = set()
    for e in index:
        if not e.get("sig"):
            fp = os.path.join(out_dir, e["file"])
            if os.path.isfile(fp):
                e["sig"] = sig(open(fp, encoding="utf-8").read().split("\n\n", 2)[-1].strip())
        sigs.add(e.get("sig"))
    parts = RE_POST.split(txt)
    added = 0
    for i in range(1, len(parts), 3):
        n, author, rest = int(parts[i]), parts[i + 1].strip(), parts[i + 2]
        dm, lm = RE_DATE.search(rest), RE_LINK.search(rest)
        link = lm.group(1) if lm else None
        if link and link in seen:
            continue
        d = parse_date(dm.group(1) if dm else "")
        body = rest.split("### เนื้อหา:", 1)[1] if "### เนื้อหา:" in rest else ""
        body = clean(body.split("### 🖼️", 1)[0].split("\n---", 1)[0])
        if not body or sig(body) in sigs or ("(โพสต์รูปภาพ" in body and len(body) < 80):
            continue
        sigs.add(sig(body))
        first = next((ln for ln in body.splitlines() if not ln.startswith("#")), body.splitlines()[0])
        own_hits, shared_hits = len(OWN.findall(body)), len(SHARED.findall(body))
        if NOT_HIS.search(body):          # broker notes, meeting notes, other pages: not his analysis
            shared_hits += 4
        kind = "shared" if shared_hits > own_hits else ("own" if own_hits or len(body) > 600 else "news")
        stem = ("%s_p%02d" % (d.strftime("%Y-%m-%d"), n)) if d else "undated_p%02d" % n
        fn = stem + ".md"
        with open(os.path.join(out_dir, fn), "w", encoding="utf-8") as fh:
            fh.write("# %s — %s\n\n- date: %s\n- link: %s\n- kind: %s\n- quarter_hint: %s\n\n%s\n" % (
                author, first[:80], d.strftime("%Y-%m-%d %H:%M") if d else "unknown", link, kind, be_quarter(d), body))
        index.append({"file": fn, "date": d.strftime("%Y-%m-%d") if d else None, "author": author, "kind": kind,
                      "quarter_hint": be_quarter(d), "chars": len(body), "sig": sig(body), "title": first[:120], "link": link})
        added += 1
    index.sort(key=lambda e: e.get("date") or "0000")
    json.dump(index, open(idx_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    kinds = {}
    for e in index:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    print("added %d posts, index has %d (%s) -> %s" % (added, len(index), kinds, out_dir))


if __name__ == "__main__":
    main()
