"""
fs_notes.py - read the few interim-note items the snapshot needs straight from the filing text, with line sources.

The finance-sheet extractor reads the face statements.  The snapshot also needs, for the latest quarter:
  * the receivables note: aging buckets and the ECL allowance per group (trade vs other/accrued SSO income),
    so an ECL jump can be traced to a group of debtors instead of guessed;
  * the cash-flow reconciling items that are "expenses by nature" proxies in a condensed interim statement
    (D&A, ECL, bad debt written off, inventory write-down, employee-benefit provision) for YTD current and prior;
  * directors' and management's benefits for YTD current and prior;
  * an expenses-by-nature note, if the interim statements happen to include one (condensed ones usually do not).

Source files (first that has the period wins):
  md/raw/combined_financial_all.md   blocks "# PERIOD: <yyyymm>_..."   (SEC filing, Thai or English)
  md/raw/combined_fs2_all.md         blocks "# QUARTER / FOLDER: `FS2_Year<BE>_Q<q>`"

Every value is in THB million and carries "file:Lnnn".  Anything not found is simply absent: never estimated.
"""
import os
import re

MONTH_EN = {1: "March", 2: "June", 3: "September", 4: "December"}
MONTH_TH = {1: "มีนาคม", 2: "มิถุนายน", 3: "กันยายน", 4: "ธันวาคม"}
DAY = {1: 31, 2: 30, 3: 30, 4: 31}
YTD_WORD_EN = {1: "three-month", 2: "six-month", 3: "nine-month"}
YTD_WORD_TH = {1: "สามเดือน", 2: "หกเดือน", 3: "เก้าเดือน"}

BUCKETS = [  # key, label TH, regex
    ("not_due", "ยังไม่ถึงกำหนดชำระ", r"ยังไม่ถึงกำหนด|not yet due"),
    ("lt3", "ค้างไม่เกิน 3 เดือน", r"ไม่เกิน\s*3\s*เดือน|up to 3 months|not over 3 months|less than 3 months"),
    ("m3_6", "ค้าง 3–6 เดือน", r"^3\s*-\s*6|3\s*-\s*6\s*(เดือน|months)"),
    ("m6_12", "ค้าง 6–12 เดือน", r"^6\s*-\s*12|6\s*-\s*12\s*(เดือน|months)"),
    ("gt12", "ค้างเกิน 12 เดือน", r"มากกว่า\s*12\s*เดือน|over 12 months|more than 12 months"),
]

CF_ITEMS = [  # key, label TH, regex on the (joined) row label
    ("da", "ค่าเสื่อมราคาและค่าตัดจำหน่าย", r"^ค่าเสื่อมราคาและค่าตัดจำหน่าย|^depreciation and amorti[sz]ation"),
    ("ecl", "ผลขาดทุนด้านเครดิตที่คาดว่าจะเกิดขึ้น (ECL)", r"ผลขาดทุนด้านเครดิตที่คาดว่าจะเกิดขึ้น|expected credit loss"),
    ("bad_debt", "หนี้สูญตัดจำหน่าย", r"หนี้สูญ|bad debt"),
    ("inv_writedown", "ปรับลดมูลค่ายาและเวชภัณฑ์", r"ปรับลดมูลค่า.*(ยา|วัสดุ)|net realisable|net realizable"),
    ("emp_provision", "ประมาณการผลประโยชน์พนักงาน (หลังออกจากงาน)", r"ผลประโยชน์พนักงาน|provision for employee benefits"),
    ("share_advance", "เงินรับล่วงหน้าค่าหุ้น (ใบสำคัญแสดงสิทธิ)", r"เงินรับล่วงหน้าค่าหุ้น|advance received from share subscription"),
]

NATURE_ITEMS = [
    ("staff", "เงินเดือน ค่าจ้าง และผลประโยชน์พนักงาน", r"เงินเดือน|salar(y|ies)|employee benefits"),
    ("da", "ค่าเสื่อมราคาและค่าตัดจำหน่าย", r"ค่าเสื่อม|depreciation"),
    ("doctor", "ค่าธรรมเนียมแพทย์", r"ค่าธรรมเนียมแพทย์|ค่าแพทย์|doctor"),
    ("referral", "ค่ารักษาพยาบาลผู้ป่วยส่งต่อ", r"ส่งต่อ|refer"),
    ("medicine", "ยา เวชภัณฑ์และวัสดุสิ้นเปลืองใช้ไป", r"^ยา|medicine|medical supplies"),
]


def _num(cell):
    c = cell.strip().replace(",", "").replace(" ", "")
    if c in ("", "-", "–"):
        return None if c == "" else 0.0
    neg = c.startswith("(") and c.endswith(")")
    c = c.strip("()")
    try:
        v = float(c)
    except ValueError:
        return None
    return -v if neg else v


def _cells(line):
    parts = line.strip().strip("|").split("|")
    return [p.strip() for p in parts]


def _nums(cells, skip_note=False):
    vals = [_num(c) for c in cells[1:]]
    vals = [v for v in vals if v is not None]
    if skip_note and len(vals) >= 3 and float(vals[0]).is_integer() and 0 < vals[0] < 50:
        vals = vals[1:]
    return vals


def _unit(text):
    t = text.lower()
    if "พันบาท" in text or "thousand baht" in t:
        return 1000.0
    if "ล้านบาท" in text or "million baht" in t:
        return 1.0
    if "(บาท)" in text or "unit: baht" in t:
        return 1e6
    return None


# ------------------------------------------------------------------------------------------ locate the filing
def _blocks(path, marker):
    if not os.path.isfile(path):
        return []
    lines = open(path, encoding="utf-8", errors="replace").read().split("\n")
    starts = [i for i, ln in enumerate(lines) if ln.startswith(marker)]
    return [(lines, s, (starts[k + 1] if k + 1 < len(starts) else len(lines))) for k, s in enumerate(starts)]


def find_block(sdir, quarter):
    """-> (lines, start, end, file_label) of the interim filing whose period ends at <quarter> (e.g. 2026Q2)."""
    y, q = int(quarter[:4]), int(quarter[-1])
    raw = os.path.join(sdir, "md", "raw")
    en = "%d %s %d" % (DAY[q], MONTH_EN[q], y)
    th = "%d %s %d" % (DAY[q], MONTH_TH[q], y + 543)
    pat = re.compile(r"(ended|สิ้นสุดวันที่)\s*(%s|%s)" % (re.escape(en), re.escape(th)))
    if q == 4:   # audited annual statements: "as at 31 December 2025 ... for the year then ended"
        pat = re.compile(r"(as at|ณ วันที่)\s*(%s|%s).{0,400}?(for the year|สำหรับปี)" % (re.escape(en), re.escape(th)))
    hit = None
    for lines, s, e in _blocks(os.path.join(raw, "combined_financial_all.md"), "# PERIOD:"):
        head = re.sub(r"\s+", " ", " ".join(lines[s:min(e, s + 60)]))
        if pat.search(head):
            hit = (lines, s, e, "%s" % lines[s].split(":", 1)[1].strip())
    if hit:
        return hit
    tag = "FS2_Year%d_Q%d" % (y + 543, q)
    for lines, s, e in _blocks(os.path.join(raw, "combined_fs2_all.md"), "# QUARTER / FOLDER:"):
        if tag in lines[s]:
            hit = (lines, s, e, tag)
    return hit


def _section(lines, s, e, head_re):
    """Line range of a numbered note whose title matches head_re (until the next numbered note)."""
    st = None
    for i in range(s, e):
        t = lines[i].strip()
        if st is None:
            if re.match(r"^\d+\s*\.\s*", t) and re.search(head_re, t, re.I):
                st = i
        elif re.match(r"^\d+\s*\.\s*\S", t) and not re.match(r"^\d+\.\d", t) and i > st + 2:
            return st, i
    return (st, e) if st is not None else (None, None)


# ------------------------------------------------------------------------------------------ parsers
def parse_receivables(lines, s, e, label):
    a, b = _section(lines, s, e, r"ลูกหนี้การค้า|trade (and other )?(current )?receivables")
    if a is None:
        return None
    unit = 1000.0
    groups, cur = {}, None
    sso = None
    total = None
    for i in range(a, b):
        ln = lines[i]
        if not ln.startswith("|"):
            continue
        u = _unit(ln)
        if u:
            unit = u
        c = _cells(ln)
        name = re.sub(r"\s+", " ", c[0]) if c else ""
        low = name.lower()
        vals = _nums(c)
        if not vals:
            if re.search(r"ลูกหนี้การค้า|trade receivables", low) and re.search(r"ไม่เกี่ยวข้อง|unrelated", low):
                cur = "trade_unrelated"
            elif re.search(r"ลูกหนี้การค้า|trade receivables", low) and re.search(r"เกี่ยวข้อง|related", low):
                cur = "trade_related"
            elif re.search(r"ลูกหนี้หมุนเวียนอื่น|other (current )?receivables", low) and re.search(r"ไม่เกี่ยวข้อง|unrelated", low):
                cur = "other_unrelated"
            elif re.search(r"ลูกหนี้หมุนเวียนอื่น|other (current )?receivables", low) and re.search(r"เกี่ยวข้อง|related", low):
                cur = "other_related"
            continue
        if len(vals) < 2:
            continue
        src = "%s:L%d" % (label, i + 1)
        pair = (vals[0] / unit, vals[1] / unit)
        if cur:
            g = groups.setdefault(cur, {"aging": {}, "allowance": None, "src": {}})
            for k, _, rx in BUCKETS:
                if re.search(rx, low, re.I):
                    g["aging"][k] = pair
                    g["src"][k] = src
                    break
            if re.search(r"ค่าเผื่อ|allowance", low):
                g["allowance"] = (abs(pair[0]), abs(pair[1]))
                g["src"]["allowance"] = src
        if re.search(r"(ประกันสังคม|social security).*(ค้างรับ|accrued)|(ค้างรับ|accrued).*(ประกันสังคม|social security)", low):
            sso = {"cur": pair[0], "prior": pair[1], "src": src}
        if re.search(r"^(รวม)?ลูกหนี้การค้าและลูกหนี้หมุนเวียนอื่น\s*-\s*สุทธิ|^total trade and other (current )?receivables\s*-?\s*net", low):
            total = {"cur": pair[0], "prior": pair[1], "src": src}
    def nonzero(g):
        vals = [x for pr in g["aging"].values() for x in pr] + list(g["allowance"] or ())
        return any(abs(x) > 1e-9 for x in vals)
    groups = {k: v for k, v in groups.items() if nonzero(v)}
    if not groups:
        return None
    return {"groups": groups, "sso_accrued": sso, "total_net": total, "file": label, "lines": [a + 1, b]}


def parse_cashflow(lines, s, e, label):
    """YTD current / prior (consolidated) for the reconciling items in CF_ITEMS."""
    st = None
    for i in range(s, e):
        if re.search(r"\|\s*(งบกระแสเงินสด|cash flow statements?|statements? of cash flows?)\s*\|", lines[i], re.I):
            st = i
            break
    if st is None:
        return {}
    out, prev = {}, ""
    unit = 1000.0
    for i in range(st, e):
        ln = lines[i]
        if ln.startswith("## Sheet") and i > st + 5 and not re.search(r"cash|กระแสเงินสด", ln, re.I):
            break
        if not ln.startswith("|"):
            continue
        u = _unit(ln)
        if u:
            unit = u
        c = _cells(ln)
        name = re.sub(r"\s+", " ", c[0]) if c else ""
        vals = _nums(c, skip_note=True)
        if not vals:
            prev = name
            continue
        full = (prev + name) if prev and not re.search(r"^(ค่า|กำไร|ขาดทุน|เงิน|รายได้|ดอกเบี้ย|ประมาณ|[A-Z])", name) else name
        prev = ""
        if len(vals) < 2:
            continue
        for k, _, rx in CF_ITEMS:
            if k not in out and re.search(rx, full, re.I):
                out[k] = {"cur": vals[0] / unit, "prior": vals[1] / unit, "src": "%s:L%d" % (label, i + 1)}
                break
    return out


def _ytd_table(lines, a, b, qn):
    """Yield (row_label, vals, lineno) for the rows of the YTD table inside lines[a:b]."""
    words = (YTD_WORD_EN[qn], YTD_WORD_TH[qn]) if qn in YTD_WORD_EN else ("year", "ปี")
    active, unit = (qn == 4), 1000.0
    for i in range(a, b):
        ln = lines[i]
        u = _unit(ln)
        if u:
            unit = u
        if re.search(r"(three|six|nine)-month|สามเดือน|หกเดือน|เก้าเดือน|for the years? ended|สำหรับปี", ln, re.I):
            active = any(w in ln for w in words) or (qn == 4 and not re.search(r"(three|six|nine)-month|สามเดือน|หกเดือน|เก้าเดือน", ln))
            continue
        if active and ln.startswith("|"):
            c = _cells(ln)
            vals = _nums(c)
            if len(vals) >= 2:
                yield re.sub(r"\s+", " ", c[0]), [v / unit for v in vals], i + 1


def parse_mgmt_comp(lines, s, e, label, qn):
    for i in range(s, e):
        if re.search(r"ค่าตอบแทนกรรมการและผู้บริหาร|directors and management.s benefits", lines[i], re.I):
            end = min(e, i + 40)
            for name, vals, ln in _ytd_table(lines, i, end, qn):
                if re.match(r"^(รวม|total)$", name.strip(), re.I):
                    return {"cur": vals[0], "prior": vals[1], "src": "%s:L%d" % (label, ln)}
    return None


def parse_nature(lines, s, e, label, qn):
    a, b = _section(lines, s, e, r"ค่าใช้จ่ายตามลักษณะ|expenses by nature")
    if a is None:
        return None
    out = {}
    for name, vals, ln in _ytd_table(lines, a, b, qn):
        for k, _, rx in NATURE_ITEMS:
            if k not in out and re.search(rx, name, re.I):
                out[k] = {"cur": vals[0], "prior": vals[1], "src": "%s:L%d" % (label, ln)}
                break
    return out or None


RE_COMMIT = re.compile(r"(ภาระผูกพัน\S{0,12}\s*รายจ่ายฝ่ายทุน|capital (expenditure )?commitments?)", re.I)


def parse_commitments(lines, s, e, label):
    """Capital-expenditure commitments note (Pop's leading indicator of the investment phase): totals for the
    consolidated and separate statements, current date and prior year-end. Only read from a 4-number table."""
    for i in range(s, e):
        if not RE_COMMIT.search(lines[i]) or lines[i].lstrip().startswith("|"):
            continue
        unit, rows = None, []
        for j in range(i, min(e, i + 30)):
            t = lines[j]
            unit = unit or _unit(t)
            if t.lstrip().startswith("|"):
                c = _cells(t)
                v = _nums(c)
                if len(v) == 4 and c[0] and not re.search(r"\d{4}", c[0]):
                    rows.append((c[0], v, j + 1))
            elif rows and t.strip() and not t.lstrip().startswith("|"):
                break
        if rows and unit:
            tot = [sum(r[1][k] for r in rows) / unit for k in range(4)]
            return {"cons": tot[0], "cons_prior": tot[1], "sep": tot[2], "sep_prior": tot[3],
                    "items": [{"label": r[0], "cons": r[1][0] / unit, "cons_prior": r[1][1] / unit} for r in rows],
                    "src": "%s:L%d" % (label, rows[0][2])}
    return None


def read_notes(sdir, quarter):
    blk = find_block(sdir, quarter)
    if not blk:
        return {"found": False, "quarter": quarter}
    lines, s, e, label = blk
    qn = int(quarter[-1])
    return {"found": True, "quarter": quarter, "file": label,
            "receivables": parse_receivables(lines, s, e, label),
            "cashflow": parse_cashflow(lines, s, e, label),
            "mgmt_comp": parse_mgmt_comp(lines, s, e, label, qn),
            "nature": parse_nature(lines, s, e, label, qn),
            "commitments": parse_commitments(lines, s, e, label)}


if __name__ == "__main__":
    import json
    import sys
    print(json.dumps(read_notes(sys.argv[1], sys.argv[2]), ensure_ascii=False, indent=1))
