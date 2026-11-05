#!/usr/bin/env python3
"""
forum_posts.py - turn a scraped web-board thread (ThaiVI "100 คน 100 หุ้น") into THIRD-TIER Markdown. Script only.

Source tiers
  tier 1  SET/SEC filings, MD&A, Oppday, factsheet            -> every figure
  tier 2  md/second_source/  news, interviews, transcripts    -> context, always external
  tier 3  md/third_source/   forum posts by other investors   -> leads and questions only; anonymous, unedited,
          often opinion or rumour. Never a figure, never a stated fact. A claim worth using must be confirmed in
          tier 1 (then cite tier 1), or shown as "นักลงทุนในเว็บบอร์ดตั้งข้อสังเกตว่า…" marked external.

    python3 forum_posts.py --stock-dir "<Thstock>/RJH"
    python3 forum_posts.py --stock-dir "<Thstock>/RJH" --json "<Thstock>/RJH/Thaivi_100P/rjh_posts_data.json"

Input : <stock>/fetch_thaivi/*_posts_data.json (older locations: <stock>/set/fetch_thaivi, <stock>/Thaivi_100P)  ({"posts": [{id, author, date, likes, content, page, url}, ...]})
Output: <stock>/md/third_source/thaivi/
          <BE>Q<q>.md      every kept post written after quarter q's results and before the next quarter's
                           (the quarter the thread was discussing), oldest first, one "###" block per post
          <BE>Q<q>.top.md  the reading pack for that quarter: the posts most worth reading (likes, figures,
                           key topics), capped at ~12,000 characters, each cut to 1,500
          index.json       per quarter: posts, characters, token estimate, top authors
          README.md        what this folder is and how it may be used
          trusted/<name>.md every post of one trusted author, oldest first, with its quarter
Noise is dropped: posts under 60 characters (20 for trusted authors), pure quotes, thanks, "+1".

Trusted authors (14 Oct 2026): names the owner follows. Read from --trusted, --trusted-file, the shared list
<AI_ROOT>/etc/thaivi_trusted_authors.txt (found as <stock-dir>/../../etc/) and <stock>/0_readme/trusted_authors.txt
(one name per line, # = comment, case ignored). Their best posts go first in <BE>Q<q>.top.md, marked ⭐, in their
own budget of ~8,000 characters (others keep ~12,000); the rest are listed at the end and are all in trusted/<name>.md.
They are still tier 3.
Post id / link: fetch_thaivi.py JSON has page, post_num and base_url (no id/url), so id = "#<post_num>" and
url = base_url&start=(page-1)*<posts per page>.
"""
import argparse
import datetime as dt
import glob
import json
import os
import re

import quarter_docs as QD

TH_MON = {"ม.ค.": 1, "ก.พ.": 2, "มี.ค.": 3, "เม.ย.": 4, "พ.ค.": 5, "มิ.ย.": 6, "ก.ค.": 7, "ส.ค.": 8, "ก.ย.": 9,
          "ต.ค.": 10, "พ.ย.": 11, "ธ.ค.": 12}
RE_DATE = re.compile(r"(\S+\.)\s+(\d{1,2}),\s+(\d{4})\s+(\d{1,2}):(\d{2})\s*(am|pm)", re.I)
NOISE = re.compile(r"^(ขอบคุณ|thanks?|thank you|\+1|ตามด้วย|ปักหมุด|มาตาม|ขอตาม)[\s\S]{0,40}$", re.I)
README = """# Third source — forum posts (tier 3)

Posts by other investors on a public web board, split by the quarter they were discussing. They are **leads and
questions**, not facts: authors are anonymous, numbers are often from memory, and opinions are mixed with rumour.

- Never copy a figure from here into a report. Check it in the filings, MD&A or Oppday and cite those.
- A point that tier 1 cannot confirm may appear only as an investor's observation, marked external, with the post
  reference (`third_source/thaivi/<BE>Q<q>:<post id>`).
- Where a post contradicts the filings, record it in the narrative's `conflicts` list only if the claim is widely
  repeated or would change the reading of the quarter.
- Use `<BE>Q<q>.top.md` (the short pack). Open `<BE>Q<q>.md` only to read a thread around a post.
- ⭐ marks a trusted author (owner's list, `etc/thaivi_trusted_authors.txt`). Their posts are always in the top pack
  and also collected per author in `trusted/<name>.md`. Trusted means worth reading first; it is still tier 3, so a
  figure must still be confirmed in tier 1. First-hand notes (company visit, Opp Day, IR call) are the most useful.
- Cite a post as `[TVI #<post_num>, YYYY-MM-DD, author]`; the link under each heading opens the page that holds it.
"""


def parse_date(s):
    m = RE_DATE.search(s or "")
    if not m or m.group(1) not in TH_MON:
        return None
    h = int(m.group(4)) % 12 + (12 if m.group(6).lower() == "pm" else 0)
    try:
        return dt.datetime(int(m.group(3)), TH_MON[m.group(1)], int(m.group(2)), h, int(m.group(5)))
    except ValueError:
        return None


def quarter_of(d):
    """Latest quarter whose results were public on date d (≈45 days after quarter end, 60 for Q4)."""
    for y in (d.year, d.year - 1):
        for q, (m, day) in ((4, (12, 31)), (3, (9, 30)), (2, (6, 30)), (1, (3, 31))):
            if dt.datetime(y, m, day) + dt.timedelta(days=(60 if q == 4 else 45) - 5) <= d:
                return "%dQ%d" % (y + 543, q)
    return None


def to_int(x):
    try:
        return int(str(x).strip() or 0)
    except ValueError:
        return 0


def load_trusted(sdir, names=None, files=None):
    """{lower-case name: name} from --trusted names, --trusted-file files, the shared etc list and the stock's own list."""
    out = {}
    for n in names or []:
        if n.strip():
            out[n.strip().lower()] = n.strip()
    cands = list(files or []) + [os.path.join(os.environ.get("AI_ROOT", ""), "etc", "thaivi_trusted_authors.txt"),
                                 os.path.join(sdir, "0_readme", "trusted_authors.txt")]
    for f in cands:
        if f and os.path.isfile(f):
            for line in open(f, encoding="utf-8-sig"):
                n = line.split("#", 1)[0].strip()
                if n:
                    out[n.lower()] = n
    return out


def build(sdir, src=None, trusted=None):
    trusted = trusted or {}
    if not src:
        c = []
        for sub in (("fetch_thaivi",), ("set", "fetch_thaivi"), ("Thaivi_100P",)):     # newest location first
            c = sorted(glob.glob(os.path.join(sdir, *(sub + ("*_posts_data.json",)))))
            if c:
                break
        if not c:
            return []
        src = c[-1]
    data = json.load(open(src, encoding="utf-8"))
    out = os.path.join(sdir, "md", "third_source", "thaivi")
    os.makedirs(out, exist_ok=True)
    base = data.get("base_url") or ""
    pages = {}
    for p in data.get("posts") or []:
        pages[str(p.get("page"))] = pages.get(str(p.get("page")), 0) + 1
    per_page = max(pages.values()) if pages else 30           # full pages hold the board's page size

    def pid(p):
        return p.get("id") or ("#%s" % p["post_num"] if p.get("post_num") not in (None, "") else "")

    def purl(p):
        if p.get("url"):
            return p["url"]
        try:
            return "%s&start=%d" % (base, (int(p.get("page")) - 1) * per_page) if base else ""
        except (TypeError, ValueError):
            return base
    weights = QD.load_keywords(sdir)
    kws = [(k, re.compile(re.escape(k), re.I)) for k in weights]
    by_q = {}
    for p in data.get("posts") or []:
        txt = (p.get("content") or "").strip()
        d = parse_date(p.get("date"))
        star = (p.get("author") or "").strip().lower() in trusted
        if not d or len(txt) < (20 if star else 60) or NOISE.match(txt):
            continue
        q = quarter_of(d)
        if not q:
            continue
        hits = {k for k, rx in kws if rx.search(txt)}
        score = sum(weights[k] for k in hits) + (3 if QD.NUM.search(txt) else 0) + 2 * to_int(p.get("likes")) + min(len(txt), 3000) / 600.0
        by_q.setdefault(q, []).append({"d": d, "id": pid(p), "author": p.get("author"), "likes": to_int(p.get("likes")),
                                       "url": purl(p), "txt": txt, "score": score, "star": star, "q": q})
    index = []
    for q in sorted(by_q):
        posts = sorted(by_q[q], key=lambda x: x["d"])
        head = "<!-- THIRD SOURCE (tier 3): forum posts, %s %s. Leads and questions only — never a figure or a stated fact. -->\n" % (
            data.get("stock", ""), q)

        def block(x, cut=None):
            t = x["txt"] if not cut or len(x["txt"]) <= cut else x["txt"][:cut].rstrip() + " …[ตัด]"
            return "### %s%s · %s · 👍%d · %s\n%s\n\n%s\n" % ("⭐ " if x["star"] else "", x["d"].strftime("%Y-%m-%d %H:%M"),
                                                          x["author"], x["likes"], x["id"], x["url"] or "", t)
        open(os.path.join(out, q + ".md"), "w", encoding="utf-8").write(head + "\n".join(block(x) for x in posts))
        top, ssize = [], 0                             # trusted authors first, own budget ~8,000 chars
        for x in sorted((x for x in posts if x["star"]), key=lambda x: -x["score"]):
            if ssize > 8000:
                break
            top.append(x)
            ssize += min(len(x["txt"]), 1500)
        left = {}
        for x in posts:
            if x["star"] and x not in top:
                left[x["author"]] = left.get(x["author"], 0) + 1
        size = 0
        for x in sorted((x for x in posts if not x["star"]), key=lambda x: -x["score"]):
            if size > 12000 or x["score"] < 4:
                break
            top.append(x)
            size += min(len(x["txt"]), 1500)
        top.sort(key=lambda x: x["d"])
        body = head + "\n".join(block(x, 1500) for x in top)
        if left:
            body += "\n---\n⭐ not in this pack (read trusted/<name>.md, quarter %s): %s\n" % (
                q, ", ".join("%s %d" % (a, n) for a, n in sorted(left.items(), key=lambda t: -t[1])))
        open(os.path.join(out, q + ".top.md"), "w", encoding="utf-8").write(body)
        auth = {}
        for x in posts:
            auth[x["author"]] = auth.get(x["author"], 0) + 1
        index.append({"quarter": q, "posts": len(posts), "chars": sum(len(x["txt"]) for x in posts),
                      "first": posts[0]["d"].strftime("%Y-%m-%d"), "last": posts[-1]["d"].strftime("%Y-%m-%d"),
                      "top_file": os.path.relpath(os.path.join(out, q + ".top.md"), sdir), "top_posts": len(top), "trusted_posts": sum(1 for x in posts if x["star"]),
                      "trusted_in_top": sum(1 for x in top if x["star"]),
                      "top_tokens_est": QD.tokens_est(body),
                      "authors": sorted(auth, key=lambda a: -auth[a])[:5]})
    # one file per trusted author, every quarter, oldest first
    tr = {}
    for q in by_q:
        for x in by_q[q]:
            if x["star"]:
                tr.setdefault(trusted[x["author"].strip().lower()], []).append(x)
    tinfo = {}
    if tr:
        tdir = os.path.join(out, "trusted")
        os.makedirs(tdir, exist_ok=True)
        for name, xs in sorted(tr.items()):
            xs.sort(key=lambda x: x["d"])
            fn = os.path.join(tdir, re.sub(r'[\\/:*?"<>|\s]+', "_", name) + ".md")
            body = ("<!-- THIRD SOURCE (tier 3), trusted author %s, %s: %d posts. Worth reading first; still confirm every figure in tier 1. -->\n"
                    % (name, data.get("stock", ""), len(xs)))
            body += "\n".join("### %s · %s · 👍%d · %s\n%s\n\n%s\n" % (x["q"], x["d"].strftime("%Y-%m-%d %H:%M"), x["likes"], x["id"],
                                                                     x["url"] or "", x["txt"]) for x in xs)
            open(fn, "w", encoding="utf-8").write(body)
            tinfo[name] = {"posts": len(xs), "file": os.path.relpath(fn, sdir), "tokens_est": QD.tokens_est(body),
                           "first": xs[0]["d"].strftime("%Y-%m-%d"), "last": xs[-1]["d"].strftime("%Y-%m-%d")}
    json.dump({"source": os.path.relpath(src, sdir), "topic": data.get("title"), "trusted": tinfo, "quarters": index},
              open(os.path.join(out, "index.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    open(os.path.join(out, "README.md"), "w", encoding="utf-8").write(README)
    return index


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stock-dir", required=True)
    ap.add_argument("--json", help="posts JSON (default: <stock>/Thaivi_100P/*_posts_data.json)")
    ap.add_argument("--trusted", nargs="*", default=[], help="trusted ThaiVI author names (added to the list files)")
    ap.add_argument("--trusted-file", action="append", default=[], help="file with one trusted author per line")
    a = ap.parse_args()
    trusted = load_trusted(a.stock_dir, a.trusted, a.trusted_file)
    if trusted:
        print("trusted authors: %d (%s)" % (len(trusted), ", ".join(sorted(trusted.values()))))
    idx = build(a.stock_dir, a.json, trusted)
    print("%d quarters -> %s" % (len(idx), os.path.join(a.stock_dir, "md", "third_source", "thaivi")))
    for e in idx[-6:]:
        print("  %s  %3d posts (%s..%s)  top pack %d posts (⭐%d) ~%d tokens" % (e["quarter"], e["posts"], e["first"], e["last"], e["top_posts"],
                                                                              e["trusted_posts"], e["top_tokens_est"]))


if __name__ == "__main__":
    main()
