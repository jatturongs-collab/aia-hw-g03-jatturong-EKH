#!/usr/bin/env python3
"""
extract_financials.py — pull real statement figures out of SET filing text dumps.

Reads the markdown conversions of SEC/SET financial-statement filings
(e.g. md/raw/combined_financial_all.md, md/raw/combined_fs2_all.md) and writes
one JSON dataset in which EVERY number carries its provenance.

Why this exists: the earlier Antigravity generator filled gaps with ratios
(Separate = 85% of Consolidated, tax = 20% of EBIT, ECL = 1.0 ...).  Those
numbers look plausible but are wrong (VIH Separate revenue is ~38% of group,
not 85%).  This extractor only records what the filing says; anything it
cannot find stays missing and is reported, never invented.

Usage
-----
  python3 extract_financials.py --stock-dir "/mnt/c/ai/Thstock/VIH" --ticker VIH
  python3 extract_financials.py --files a.md b.md --ticker VIH -o VIH_financials.json
  python3 extract_financials.py --stock-dir ... --dump-labels      # show unmapped row labels

Output (JSON)
-------------
  {
    "ticker": "VIH", "unit": "THB million",
    "facts": { "<entity>|<key>|<period>": {"v": 753.193, "src": "202608_...:L9930 (3M current)"} },
    "quarters": ["2023Q1", ...], "years": [2022, ...],
    "flags": ["..."]
  }
  entity  : C = consolidated, S = separate (company only)
  period  : 2026Q2 (single quarter flow or quarter-end balance),
            FY2025 (full year flow or Dec balance), 6M2026 / 9M2025 (cumulative YTD)
"""
import argparse, glob, json, os, re, sys
from collections import defaultdict
from datetime import datetime

# Above-line vowels and tone marks are frequently dropped or replaced by legacy-font private-use glyphs
# in PDF text (e.g. 'รายไดเงินปนผล' for 'รายได้เงินปันผล').  Folding removes them from BOTH the text and
# the label patterns, so matching is insensitive to that damage.
THAI_MARKS = re.compile("[\u0e31\u0e34-\u0e37\u0e47-\u0e4c\u0e4e\uf700-\uf71f\u200b-\u200d\ufffd]")


def thai_fold(s):
    s = s.replace("\u0e4d\u0e32", "\u0e33")
    return THAI_MARKS.sub("", s)


# ---------------------------------------------------------------------------
# Label dictionary (English + Thai).  Keys are canonical line items.
# Each entry: key -> (statement, [regex, ...]).  Regexes are matched against the
# row label after whitespace normalisation, case-insensitive, anchored at start.
# Add synonyms here when a new company uses different wording (run --dump-labels).
# ---------------------------------------------------------------------------
LABELS = {
    # ---------------- Income statement ----------------
    "rev_hosp":      ("IS", [r"revenues? from hospital operations?", r"revenues? from medical (services|treatment)", r"medical services? revenues?",
                             r"hospital (operating )?revenues?", r"revenues? from rendering of services",
                             r"รายได้จากกิจการโรงพยาบาล", r"รายได้จากการประกอบกิจการโรงพยาบาล", r"รายได้ค่ารักษาพยาบาล", r"รายได้จากการให้บริการทางการแพทย์",
                             r"รายได้จากการรักษาพยาบาล"]),
    "rev_other_ops": ("IS", [r"revenues? from services$", r"food and beverage revenues?", r"revenues? from food and beverage"]),
    "cogs_other_ops": ("IS", [r"cost of services$", r"cost of food and beverages?"]),
    "rev_sales":     ("IS", [r"revenues? from sales", r"sales of goods", r"รายได้จากการขาย"]),
    "dividend_income": ("IS", [r"dividend income", r"รายได้เงินปันผล"]),
    "interest_income": ("IS", [r"interest income", r"รายได้ดอกเบี้ย", r"ดอกเบี้ยรับ"]),
    "other_income":  ("IS", [r"other income", r"รายได้อื่น"]),
    "total_rev":     ("IS", [r"total revenues?$", r"รวมรายได้$"]),
    "cogs":          ("IS", [r"cost of hospital operations?", r"cost of (medical )?services", r"cost of rendering",
                             r"cost of (medical|hospital)", r"ต้นทุนกิจการโรงพยาบาล", r"ต้นทุนในการประกอบกิจการโรงพยาบาล",
                             r"ต้นทุนการประกอบกิจการโรงพยาบาล", r"ต้นทุนการให้บริการ",
                             r"ต้นทุนค่ารักษาพยาบาล", r"ต้นทุนการรักษาพยาบาล"]),
    "cogs_sales":    ("IS", [r"cost of sales", r"ต้นทุนขาย"]),
    "selling":       ("IS", [r"selling expenses?", r"selling and distribution", r"distribution costs?\b(?! and admin)",
                             r"ค่าใช้จ่ายในการขาย$"]),
    "admin":         ("IS", [r"administrative expenses?", r"ค่าใช้จ่ายในการบริหาร$"]),
    "sga":           ("IS", [r"selling and administrative expenses", r"distribution costs? and administrative e[xs]*penses", r"services? and administrative expenses",
                             r"ค่าใช้จ่ายในการขายและบริหาร", r"ค่าใช้จ่ายในการขายและค่าใช้จ่ายในการบริหาร"]),
    "total_exp":     ("IS", [r"total expenses$", r"รวมค่าใช้จ่าย$"]),
    "op_profit":     ("IS", [r"operating profit", r"profit from operating activities$", r"profit from operations?( activities)?$",
                             r"กำไรจากการดำเนินงาน$", r"กำไร \(ขาดทุน\) จากการดำเนินงาน"]),
    "share_assoc":   ("IS", [r"share of (profit|loss|income)", r"ส่วนแบ่งกำไร", r"ส่วนแบ่ง(ผล)?กำไร"]),
    "fin_inc":       ("IS", [r"finance income", r"รายได้ทางการเงิน", r"ดอกเบี้ยรับและรายได้ทางการเงิน"]),
    "fin_cost":      ("IS", [r"finance costs?$", r"financial costs?$", r"interest expenses?$", r"ต้นทุนทางการเงิน$"]),
    "pbt":           ("IS", [r"profit (\(loss\) )?before income tax", r"profit before tax", r"กำไรก่อนค่าใช้จ่ายภาษีเงินได้",
                             r"กำไรก่อนภาษีเงินได้", r"กำไร \(ขาดทุน\) ก่อนค่าใช้จ่ายภาษี"]),
    "tax":           ("IS", [r"income tax expenses?", r"tax expenses?$", r"ค่าใช้จ่ายภาษีเงินได้", r"\(ค่าใช้จ่าย\) รายได้ภาษีเงินได้"]),
    "np":            ("IS", [r"profit (\(loss\) )?for the (period|year)$", r"กำไรสำหรับ(งวด|ปี)$", r"กำไร \(ขาดทุน\) สำหรับ(งวด|ปี)$"]),
    "np_owners":     ("IS", [r"equity holders of (the )?(company|parent)", r"owners of (the )?(company|parent)",
                             r"ส่วนที่เป็นของผู้ถือหุ้นของ(บริษัทฯ|บริษัทใหญ่|บริษัท)"]),
    "np_nci":        ("IS", [r"non-controlling interests?", r"ส่วนที่เป็นของผู้มีส่วนได้เสียที่ไม่มีอำนาจควบคุม"]),
    "eps":           ("IS", [r"basic earnings per share", r"กำไรต่อหุ้นขั้นพื้นฐาน"]),
    # ---------------- Balance sheet ----------------
    "cash":          ("BS", [r"cash and cash equivalents$", r"เงินสดและรายการเทียบเท่าเงินสด$"]),
    "st_invest":     ("BS", [r"other current financial assets", r"short-term investments?", r"current investments?",
                             r"สินทรัพย์ทางการเงินหมุนเวียนอื่น", r"เงินลงทุนระยะสั้น", r"เงินลงทุนชั่วคราว"]),
    "receivables":   ("BS", [r"trade and other (current )?receivables", r"trade accounts receivable", r"ลูกหนี้การค้าและลูกหนี้",
                             r"ลูกหนี้การค้า"]),
    "accrued_inc":   ("BS", [r"accrued (?!dividend|interest)[a-z ]*(income|revenues?)", r"รายได้ค้างรับ", r"รายได้ค่ารักษาพยาบาลค้างรับ"]),
    "inventory":     ("BS", [r"medicines? and (medical )?supplies", r"inventories", r"ยาและเวชภัณฑ์", r"ยา เวชภัณฑ์",
                             r"สินค้าคงเหลือ"]),
    "total_ca":      ("BS", [r"total current assets", r"รวมสินทรัพย์หมุนเวียน"]),
    "ppe":           ("BS", [r"property, plant and equipment", r"ที่ดิน อาคารและอุปกรณ์", r"ที่ดิน อาคาร และอุปกรณ์"]),
    "rou":           ("BS", [r"right-of-use assets?", r"สินทรัพย์สิทธิการใช้"]),
    "total_assets":  ("BS", [r"total assets$", r"รวมสินทรัพย์$"]),
    "payables":      ("BS", [r"trade and other (current )?payables", r"trade accounts payable", r"เจ้าหนี้การค้าและเจ้าหนี้",
                             r"เจ้าหนี้การค้า"]),
    "st_debt":       ("BS", [r"bank overdrafts?", r"short-term loans?\b(?! (to|and|from related|to related))", r"short-term borrowings?", r"เงินเบิกเกินบัญชี", r"เงินกู้ยืมระยะสั้น"]),
    "lt_debt_cur":   ("BS", [r"current portion of long-term (loans?|borrowings?)", r"ส่วนของเงินกู้ยืมระยะยาวที่ถึงกำหนด"]),
    "lease_cur":     ("BS", [r"current portion of lease liabilit", r"ส่วนของหนี้สินตามสัญญาเช่าที่ถึงกำหนด"]),
    "lt_debt":       ("BS", [r"long-term loans?,? net of current", r"long-term (loans?|borrowings?)( from financial institutions?)?(,? net)?$", r"เงินกู้ยืมระยะยาว"]),
    "debentures":    ("BS", [r"debentures", r"หุ้นกู้"]),
    "lease_lt":      ("BS", [r"lease liabilities,? net of current", r"lease liabilities$", r"หนี้สินตามสัญญาเช่า\s*-?\s*สุทธิ"]),
    "total_cl":      ("BS", [r"total current liabilities", r"รวมหนี้สินหมุนเวียน"]),
    "total_liab":    ("BS", [r"total liabilities$", r"รวมหนี้สิน$"]),
    "equity_owners": ("BS", [r"(total )?equity attributable to (the )?owners", r"total equity attributable to (the )?owners", r"equity attributable to equity holders",
                             r"ส่วนของผู้ถือหุ้นของ(บริษัทฯ|บริษัทใหญ่|บริษัท)"]),
    "equity_nci":    ("BS", [r"non-controlling interests?", r"ส่วนของผู้มีส่วนได้เสียที่ไม่มีอำนาจควบคุม"]),
    "total_equity":  ("BS", [r"total (shareholders'? )?equity$", r"รวมส่วนของผู้ถือหุ้น$"]),
    "total_le":      ("BS", [r"total liabilities and (shareholders'? )?equity", r"รวมหนี้สินและส่วนของผู้ถือหุ้น"]),
    # ---------------- Cash flow (cumulative YTD) ----------------
    "cf_da":         ("CF", [r"depreciation and amorti[sz]ation", r"ค่าเสื่อมราคาและค่าตัดจำหน่าย", r"ค่าเสื่อมราคา"]),
    "cf_ecl":        ("CF", [r"(allowance for )?expected credit loss", r"(reversal of )?allowance for expected credit loss", r"bad debts? and doubtful", r"\(reversal of\) (bad debts? and )?expected credit loss",
                             r"reversal of expected credit loss", r"(reversal of )?bad debts? and expected credit loss",
                             r"ค่าเผื่อผลขาดทุนด้านเครดิต", r"\(กลับรายการ\)\s*ผลขาดทุนด้านเครดิต", r"ผลขาดทุนด้านเครดิตที่คาดว่าจะเกิดขึ้น",
                             r"หนี้สงสัยจะสูญ"]),
    "cfo":           ("CF", [r"net cash (flows? )?(from|provided by|used in|from \(used in\)) operating", r"เงินสดสุทธิ.*กิจกรรมดำเนินงาน"]),
    "capex_ppe":     ("CF", [r"acquisitions? of (buildings? improvements? and )?(property, plant and )?equipment",
                             r"purchases? of (property|equipment|buildings)", r"ซื้อ.*(อาคาร|อุปกรณ์)",
                             r"เงินสดจ่ายเพื่อ(ซื้อ|ลงทุนใน).*(อาคาร|อุปกรณ์)",
                             r"acquisitions? of fixed assets$", r"purchases? of fixed assets$", r"ซื้อสินทรัพย์ถาวร$",
                             r"cash paid (for|to) (the )?(purchases?|acquisitions?) of\s*(property|equipment|fixed|buildings?)"]),
    "capex_payable": ("CF", [r"cash paid for payables? (of|from) (buildings|property|equipment)", r"จ่ายชำระเจ้าหนี้.*(อาคาร|อุปกรณ์)",
                             r"จ่ายชำระหนี้ค่าซื้อสินทรัพย์ถาวร$"]),
    "capex_intang":  ("CF", [r"acquisitions? of intangible", r"purchases? of intangible", r"cash paid (for|to) (the )?(purchases?|acquisitions?) of intangible", r"ซื้อสินทรัพย์ไม่มีตัวตน"]),
    "cfi":           ("CF", [r"net cash .*investing", r"เงินสดสุทธิ.*กิจกรรมลงทุน"]),
    "div_paid":      ("CF", [r"dividends? paid$", r"cash paid for dividends?$", r"dividends? paid to (the )?(owners|equity holders) of the (parent|company)", r"dividends? paid to (the )?(company'?s? )?shareholders", r"เงินปันผลจ่าย$",
                             r"จ่ายเงินปันผล$", r"จ่ายเงินปันผลให้(แก่)?ผู้ถือหุ้นของบริษัท"]),
    "cff":           ("CF", [r"net cash .*financing", r"เงินสดสุทธิ.*กิจกรรมจัดหาเงิน"]),
    # ---------------- Note: expenses by nature ----------------
    "exp_staff":     ("NAT", [r"salaries", r"employee benefit", r"staff costs?", r"เงินเดือน", r"ค่าใช้จ่ายผลประโยชน์พนักงาน"]),
    "exp_da":        ("NAT", [r"depreciation", r"ค่าเสื่อมราคา"]),
    "exp_doctor":    ("NAT", [r"doctor'?s? fees?", r"ค่าธรรมเนียมแพทย์", r"ค่าตอบแทนแพทย์", r"ค่าแพทย์"]),
    "exp_referral":  ("NAT", [r"medical treatment expenses? for referred", r"referr", r"ค่ารักษาพยาบาลส่งต่อ", r"ค่าส่งต่อ"]),
    "exp_medicine":  ("NAT", [r"medicines?,? medical supplies", r"medicine and supplies used", r"ยา เวชภัณฑ์", r"ยาและเวชภัณฑ์",
                             r"วัตถุดิบและวัสดุสิ้นเปลืองใช้ไป"]),
}
# Keys whose values should be summed when the same label pattern appears more than once in one statement
SUM_KEYS = set()
# Keys that are per-share (not scaled by unit)
PER_SHARE = {"eps"}
# Thai statements put the NCI label on two lines ("...ไม่มีอำนาจควบคุม" / "ของบริษัทย่อย | 312"),
# so a mapped label with no numbers leaves a "pending" key for the next unmapped numeric row.

EN_MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july",
                                          "august", "september", "october", "november", "december"], 1)}
TH_MONTHS = {m: i for i, m in enumerate(["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน", "กรกฎาคม",
                                          "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"], 1)}
DUR_WORD = {"three": 3, "six": 6, "nine": 9, "สาม": 3, "หก": 6, "เกา": 9}   # Thai keys in folded form

RE_TITLE = {  # matched against folded text
    "BS": re.compile(thai_fold(r"statements? of financial position|balance sheets?|งบ(แสดง)?ฐานะการเงิน"), re.I),
    "IS": re.compile(thai_fold(r"statements? of (comprehensive )?income|income statements?|statements? of profit or loss|งบกำไรขาดทุน"), re.I),
    "CF": re.compile(thai_fold(r"cash flows? statements?|statements? of cash flows?|งบกระแสเงินสด"), re.I),
    "EQ": re.compile(thai_fold(r"changes in (shareholders'? )?equity|งบการเปลี่ยนแปลงส่วนของผู้ถือหุ้น"), re.I),
}
RE_PERIOD_EN = re.compile(r"for\s+the\s+(three|six|nine)[- ]months?(?:[- ]periods?)?\s+ended\s+(\d{1,2})\s+(\w+)\s+(\d{4})", re.I)
RE_YEAR_EN = re.compile(r"for the years? ended (\d{1,2}) (\w+) (\d{4})", re.I)
RE_PERIOD_TH = re.compile(thai_fold(r"สำหรับ\s*งวด\s*(สาม|หก|เก้า)\s*เดือน\s*สิ้นสุด\s*วันที่\s*(\d{1,2})\s*(\S+)\s*(\d{4})"))
RE_YEAR_TH = re.compile(thai_fold(r"สำหรับ\s*ปี\s*สิ้นสุด\s*วันที่\s*(\d{1,2})\s*(\S+)\s*(\d{4})"))
RE_DATE_EN = re.compile(r"(?<!\d)(\d{1,2}) (january|february|march|april|may|june|july|august|september|october|november|december) (\d{4})", re.I)
RE_DATE_TH = re.compile(r"(?<!\d)(\d{1,2})\s*(" + "|".join(sorted({thai_fold(m) for m in TH_MONTHS}, key=len, reverse=True)) + r")\s*(\d{4})")
RE_NATURE = re.compile(thai_fold(r"^\s*\d+\.?\s*(expenses by nature|ค่าใช้จ่ายตามลักษณะ)"), re.I)
RE_NOTE_HEAD = re.compile(r"^\s*\d+\.\s*\S")
RE_NOTES_START = re.compile(thai_fold(r"^\s*1\.?\s*(ข้อมูลทั่วไป|general information|corporate information)"), re.I)
RE_US_DATE = re.compile(r"\b(january|february|march|april|may|june|july|august|september|october|november|december) (\d{1,2}),? (\d{4})", re.I)
RE_MONTH_ONLY = re.compile(r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\b(?!\s*\d)", re.I)
RE_DUR_ONLY_EN = re.compile(r"(three|six|nine)[- ]months?(?:[- ]periods?)?\s+ended", re.I)
RE_YEAR_ONLY_EN = re.compile(r"years? ended", re.I)
RE_DUR_ONLY_TH = re.compile(thai_fold(r"งวด\s*(สาม|หก|เก้า)\s*เดือน"))
RE_YEAR_ONLY_TH = re.compile(thai_fold(r"สำหรับ\s*ปี\s*สิ้นสุด"))
RE_DAYMON_EN = re.compile(r"(\d{1,2}) (january|february|march|april|may|june|july|august|september|october|november|december)\b(?!\s*\d{4})", re.I)
RE_FILING = re.compile(r"^# (PERIOD|QUARTER / FOLDER|ANNUAL / FOLDER|DOCUMENT):\s*`?([^`]+)`?")


def ce_year(y):
    y = int(y)
    return y - 543 if y > 2400 else y


TH_MONTHS_F = {}


def month_of(name):
    n = name.strip().lower()
    if not TH_MONTHS_F:
        TH_MONTHS_F.update({thai_fold(k): v for k, v in TH_MONTHS.items()})
    return EN_MONTHS.get(n) or TH_MONTHS.get(name.strip()) or TH_MONTHS_F.get(thai_fold(name.strip()))


def parse_num(cell):
    if re.fullmatch(r"\s*\d{1,3}(\s*,\s*\d{1,2})+\s*", cell):
        return None           # note references such as "5, 20" (a thousands group always has 3 digits)
    c = cell.strip().replace(",", "").replace("‌", "").replace(" ", "")
    if c in ("", "-", "–"):
        return None
    neg = c.startswith("(") and c.endswith(")")
    c = c.strip("()")
    try:
        v = float(c)
    except ValueError:
        return None
    return -v if neg else v


def norm_label(s):
    s = s.replace("‌", "").replace("ํา", "ำ")
    s = re.sub(r"\s+", " ", s).strip(" :-")
    return s


_FOLDED = {}


def match_key(label, stmt):
    lab = thai_fold(label)
    for key, (st, pats) in LABELS.items():
        if st != stmt:
            continue
        for p in pats:
            fp = _FOLDED.get(p)
            if fp is None:
                fp = _FOLDED[p] = re.compile(thai_fold(p), re.I)
            if fp.match(lab):
                return key
    return None


def period_key(dur, year, month):
    """dur in months (0 = balance), year CE, month -> canonical period string."""
    if dur == 0:
        return f"{year}Q{(month - 1) // 3 + 1}" if month != 12 else f"FY{year}"
    if dur == 12:
        return f"FY{year}"
    if dur == 3:
        return f"{year}Q{(month - 1) // 3 + 1}"
    return f"{dur}M{year}"


class Extractor:
    def __init__(self):
        self.facts = {}            # key -> {"v","src","rank"}
        self.flags = []
        self.unmapped = defaultdict(int)

    def put(self, fkey, v, src, rank):
        """rank 0 = current-period column of original filing, 1 = comparative column."""
        old = self.facts.get(fkey)
        if old is None or rank < old["rank"]:
            if old is not None and old["v"] and abs(old["v"] - v) > max(0.5, abs(old["v"]) * 0.005):
                self.flags.append(f"RESTATED? {fkey}: {old['v']:.2f} ({old['src']}) vs {v:.2f} ({src})")
            self.facts[fkey] = {"v": v, "src": src, "rank": rank}
        elif old is not None and rank == old["rank"] and abs(old["v"] - v) > max(0.5, abs(old["v"]) * 0.005):
            self.flags.append(f"CONFLICT {fkey}: kept {old['v']:.2f} ({old['src']}), saw {v:.2f} ({src})")
        elif old is not None and rank > old["rank"] and abs(old["v"] - v) > max(0.5, abs(old["v"]) * 0.005):
            self.flags.append(f"RESTATED? {fkey}: original {old['v']:.2f} ({old['src']}) vs comparative {v:.2f} ({src})")

    def run_file(self, path):
        lines = open(path, encoding="utf-8", errors="ignore").read().split("\n")
        # A stock folder can hold another company's filings (a mis-filed download): SEC folder names carry the filer code
        # (FS_202608_0808FIN...). When several codes are present, keep the code whose filings show hospital revenue.
        # Older filings have no code in the folder name (FS_202102_21013888). Once another filer is known to be in this file,
        # an uncoded filing with no hospital revenue is treated as that company's too; otherwise it slips past the code check.
        codes, cur, hosp = {}, None, set()
        uncoded, block = {}, None
        for raw in lines:
            mf = RE_FILING.match(raw)
            if mf:
                mc = re.search(r"_(\d{4})FIN", mf.group(2))
                cur = mc.group(1) if mc else None
                block = mf.group(2).strip()
                if cur:
                    codes[cur] = codes.get(cur, 0) + 1
                else:
                    uncoded.setdefault(block, False)
            elif re.search(r"hospital operation|medical service|กิจการโรงพยาบาล|ค่ารักษาพยาบาล", raw, re.I):
                if cur:
                    hosp.add(cur)
                elif block in uncoded:
                    uncoded[block] = True
        skip_codes = set(codes) - hosp if len(codes) > 1 and hosp else set()
        skip_blocks = {b for b, has_hosp in uncoded.items() if not has_hosp} if skip_codes else set()
        if skip_codes:
            self.flags.append("OTHER COMPANY filings skipped in %s: codes %s and %d uncoded filings (no hospital revenue) — move those set/fs folders out"
                              % (os.path.basename(path), ", ".join(sorted(skip_codes)), len(skip_blocks)))
        skipping = False
        filing = os.path.basename(path)
        stmt = None; dur = None; end = None; prior_end = None
        scale = 1 / 1000.0
        in_notes = False
        nature = None          # dict when parsing the expenses-by-nature table
        seen_in_stmt = set()
        pending = None
        filing_end = None      # (dur, y, m) of the widest IS period in this filing
        hdr = {"dur": None, "months": []}   # period header split over several table rows (Excel-converted filings)
        for i, raw in enumerate(lines):
            ln = i + 1
            mf = RE_FILING.match(raw)
            if mf:
                mc = re.search(r"_(\d{4})FIN", mf.group(2))
                skipping = bool(mc and mc.group(1) in skip_codes) or (not mc and mf.group(2).strip() in skip_blocks)
                filing = mf.group(2).strip()
                scale = 1 / 1000.0       # a new filing starts at the default; never carry a unit over from the previous one
                stmt = None; in_notes = False; nature = None; filing_end = None
                continue
            if skipping:
                continue
            if raw.startswith("## FILE:") or raw.startswith("# NOTES"):
                in_notes = ("NOTES" in raw.upper())
                stmt = None; nature = None
                continue
            if raw.startswith("## Sheet:"):
                # a new sheet starts with no period: it must state its own ("PL 12m" must not inherit "PL 3m")
                stmt = None; in_notes = False; nature = None; hdr = {"dur": None, "months": []}
                dur = None; end = None; prior_end = None; seen_in_stmt = set()
                continue
            is_table = raw.strip().startswith("|")
            if is_table:
                cells = raw.split("|")[1:-1]
                if cells and not cells[0].strip():
                    # nested label ("|  | Owners of parent |  | 112,846 |"): move the first text cell to the label column
                    for k, c in enumerate(cells):
                        if c.strip():
                            if parse_num(c) is None and k < 4:
                                cells = [c] + cells[k + 1:]
                            break
            else:
                # plain PDF text: "label  1,234  (567)  -  890"  -> label + trailing numeric tokens
                toks = raw.replace("\t", " ").split()
                j = len(toks)
                while j > 0 and re.fullmatch(r"\(?-?[\d,]+(\.\d+)?\)?|-|–", toks[j - 1]):
                    j -= 1
                nums_txt = ["0" if t in ("-", "–") else t for t in toks[j:]]
                cells = [" ".join(toks[:j])] + nums_txt
            text = thai_fold(" ".join(c.strip() for c in cells if c.strip()))
            # US-style dates ("JUNE 30, 2026") -> "30 JUNE 2026"
            text = RE_US_DATE.sub(lambda mm: "%s %s %s" % (mm.group(2), mm.group(1), mm.group(3)), text)

            if not in_notes and RE_NOTES_START.match(thai_fold(raw.strip().lstrip("|").strip())):
                in_notes, stmt = True, None      # notes begin: stop reading statement rows (note tables repeat labels)
            # ---------- expenses by nature (note table; works for markdown tables and plain PDF text) ----------
            if RE_NATURE.match(thai_fold(raw.strip())):
                nature = {"start": ln}
                continue
            if nature is not None:
                if ln - nature["start"] > 40 or (RE_NOTE_HEAD.match(raw) and not is_table):
                    nature = None
                else:
                    lowt = text.lower()
                    if "thousand baht" in lowt or thai_fold("พันบาท") in text:
                        scale = 1 / 1000.0
                    elif re.search(r"\(unit\s*:\s*baht\)|\(in baht\)|^unit\s*:\s*baht$", lowt.strip()) or re.search(thai_fold(r"\(หน่วย\s*:\s*บาท\)"), text):
                        scale = 1 / 1_000_000.0
                    label = norm_label(cells[0]) if cells else ""
                    nums = [parse_num(c) for c in cells[1:]]
                    nums = [x for x in nums if x is not None]
                    if len(nums) == 5 and float(nums[0]).is_integer() and 0 < nums[0] < 60:
                        nums = nums[1:]
                    if len(nums) == 3 and float(nums[0]).is_integer() and 0 < nums[0] < 60:
                        nums = nums[1:]
                    if len(nums) in (2, 4) and label and filing_end:
                        key = match_key(label, "NAT")
                        if key:
                            d, y, m = filing_end
                            p_cur, p_pri = period_key(d, y, m), period_key(d, y - 1, m)
                            src = f"{filing}:L{ln} (note: expenses by nature)"
                            self.put(f"C|{key}|{p_cur}", nums[0] * scale, src, 0)
                            self.put(f"C|{key}|{p_pri}", nums[1] * scale, src + " comparative", 1)
                            if len(nums) == 4:        # 2-column notes = company without separate statements
                                self.put(f"S|{key}|{p_cur}", nums[2] * scale, src, 0)
                                self.put(f"S|{key}|{p_pri}", nums[3] * scale, src + " comparative", 1)
                    continue
            if in_notes:
                continue

            # ---------- statement titles / period lines ----------
            low = text.lower()
            for st, rx in RE_TITLE.items():
                if rx.search(text) and len(text) < 160:
                    new_stmt = None if st == "EQ" else st
                    if new_stmt != stmt:
                        seen_in_stmt = set()
                    stmt = new_stmt
                    pending = None
                    hdr = {"dur": None, "months": []}
                    if st == "BS":
                        dur = 0
                    break
            if "thousand baht" in low or thai_fold("พันบาท") in text:
                scale = 1 / 1000.0
            elif "million baht" in low or thai_fold("ล้านบาท") in text:
                scale = 1.0
            elif re.search(r"\(unit\s*:\s*baht\)|\(in baht\)|^unit\s*:\s*baht$", low.strip()) or re.search(thai_fold(r"\(หน่วย\s*:\s*บาท\)"), text) \
                    or any(re.sub(r"\s+", "", c).lower() in ("(บาท)", thai_fold("(บาท)"), "บาท", thai_fold("บาท"), "หน่วย:บาท", "baht", "unit:baht", "(unit:baht)")
                           for c in cells):     # SKR prints a bare "บาท" cell above the columns (statements in baht)
                scale = 1 / 1_000_000.0
            m = RE_PERIOD_EN.search(text) or RE_PERIOD_TH.search(text)
            if m and stmt in ("IS", "CF"):
                d = DUR_WORD[m.group(1).lower() if m.group(1).isascii() else m.group(1)]
                newend = (ce_year(m.group(4)), month_of(m.group(3)))
                if (d, newend) != (dur, end):
                    seen_in_stmt = set()
                dur, end = d, newend
                if stmt == "IS" and (filing_end is None or d > filing_end[0]):
                    filing_end = (d, end[0], end[1])
                continue
            m = RE_YEAR_EN.search(text) or RE_YEAR_TH.search(text)
            if m and stmt in ("IS", "CF"):
                newend = (ce_year(m.group(3)), month_of(m.group(2)))
                if (12, newend) != (dur, end):
                    seen_in_stmt = set()
                dur, end = 12, newend
                if stmt == "IS":
                    filing_end = (12, end[0], end[1])
                continue
            # ---------- split headers: "Three-month period ended" / "30 June" / "2026 | 2025" on separate rows ----------
            if stmt in ("IS", "CF", "BS"):
                md = RE_DUR_ONLY_EN.search(text) or RE_DUR_ONLY_TH.search(text)
                if md and stmt != "BS":
                    w = md.group(1)
                    hdr["dur"] = DUR_WORD[w.lower() if w.isascii() else w]
                    continue
                if (RE_YEAR_ONLY_EN.search(text) or RE_YEAR_ONLY_TH.search(text)) and stmt != "BS" and len(text) < 120:
                    hdr["dur"] = 12
                    continue
                dm = RE_DAYMON_EN.findall(text)
                if not dm:
                    dm = [(a, b) for a, b in re.findall(r"(\d{1,2})\s*(" + "|".join(sorted({thai_fold(x) for x in TH_MONTHS}, key=len, reverse=True)) + r")(?!\s*\d{4})", text)]
                if not dm and len(text) < 120 and not re.search(r"\d", text):
                    mo = RE_MONTH_ONLY.findall(text)
                    dm = [("", x) for x in mo] if mo else []
                if dm and not RE_DATE_EN.search(text) and not RE_DATE_TH.search(text) and len(text) < 120:
                    hdr["months"] = [month_of(b) for _, b in dm]
                    continue
                cl = [c.strip() for c in cells if c.strip()]
                yrs = [c for c in cl if re.fullmatch(r"(19|20|25|26)\d{2}", c)]
                other = [c for c in cl if c not in yrs]
                if hdr["months"] and len(yrs) >= 2 and len(other) <= 2 and all(len(c) <= 12 and parse_num(c) is None for c in other):
                    ys = [ce_year(c) for c in yrs]
                    mo = hdr["months"]
                    if stmt == "BS":
                        end = (ys[0], mo[0]); prior_end = (ys[1], mo[1] if len(mo) > 1 else mo[0])
                        dur = 0
                    elif hdr["dur"]:
                        newend = (ys[0], mo[0])
                        if (hdr["dur"], newend) != (dur, end):
                            seen_in_stmt = set()
                        dur, end = hdr["dur"], newend
                        if stmt == "IS" and (filing_end is None or dur > filing_end[0]):
                            filing_end = (dur, end[0], end[1])
                    continue
            if stmt == "BS":
                dates = RE_DATE_EN.findall(text) or RE_DATE_TH.findall(text)
                if len(dates) >= 2:
                    (d1, m1, y1), (d2, m2, y2) = dates[0], dates[1]
                    end, prior_end = (ce_year(y1), month_of(m1)), (ce_year(y2), month_of(m2))
                    continue
                if len(dates) == 1 and re.match(r"(as at|ณ\s*วนท)", text.lower()):
                    d1, m1, y1 = dates[0]
                    end = (ce_year(y1), month_of(m1)); prior_end = (end[0] - 1, 12)
                    if end[1] == 12:
                        prior_end = (end[0] - 1, 12)
                    continue
            if stmt is None or end is None:
                continue
            if not is_table and len(cells) < 2 and not (cells and cells[0] and match_key(norm_label(cells[0]), stmt)):
                continue

            # ---------- data rows ----------
            label = norm_label(cells[0]) if cells else ""
            nums_all = [parse_num(c) for c in cells[1:]]
            nums = [x for x in nums_all if x is not None]
            key = match_key(label, stmt) if label else None
            if key and not nums:
                pending = key
                continue
            if not nums:
                continue
            if key is None and pending and not (label and match_key(label, stmt)):
                key = pending
            pending = None
            if key is None:
                if label and len(nums) >= 2:
                    self.unmapped[(stmt, label)] += 1
                continue
            # column assignment: [note?] C_cur C_pri S_cur S_pri
            if len(nums) >= 5:
                first = nums[0]
                nz = [x for x in nums if x != 0]
                if len(nums) > 5 and len(nz) != 4:
                    continue          # wide tables (changes in equity, PPE roll-forward) are not face statements
                if 0 < abs(first) < 60 and abs(first * 10 - round(first * 10)) < 1e-6:
                    nums = nums[1:5]                       # leading note number (5, 5.1, 15.2 ...)
                elif len(nz) == 4:
                    nums = nz                              # stray zero cells from the PDF/Excel conversion
                elif len(nums) == 5 and nums[1] == nums[3]:
                    nums = [nums[0], nums[2], nums[3], nums[4]]   # conversion artefact: separate value duplicated
                elif key in PER_SHARE:
                    nums = nums[1:5]
                else:
                    if len(nums) == 5:
                        self.flags.append(f"AMBIGUOUS ROW skipped {filing}:L{ln} {label}: {nums}")
                    continue
            elif len(nums) == 3:
                first = nums[0]
                if 0 < first < 60 and abs(first * 10 - round(first * 10)) < 1e-6:
                    nums = nums[1:]
                else:
                    continue
            if len(nums) not in (2, 4):
                continue
            tag = (stmt, key, dur, end)
            if tag in seen_in_stmt and key not in SUM_KEYS:
                continue          # first occurrence wins (e.g. profit vs comprehensive-income attribution)
            seen_in_stmt.add(tag)
            sc = 1.0 if key in PER_SHARE else scale
            src = f"{filing}:L{ln}"
            if stmt == "BS":
                p_cur = period_key(0, *end)
                p_pri = period_key(0, *prior_end) if prior_end else None
            else:
                p_cur = period_key(dur, *end)
                p_pri = period_key(dur, end[0] - 1, end[1])
                if stmt == "CF" and dur == 3:
                    p_cur, p_pri = f"3M{end[0]}" if end[1] == 3 else p_cur, (f"3M{end[0]-1}" if end[1] == 3 else p_pri)
                if stmt == "CF" and dur == 3 and end[1] != 3:
                    continue      # 3-month cash flows beyond Q1 are unusual; skip to avoid clashes
            ents = ["C", "S"] if len(nums) == 4 else ["C"]
            vals = [(nums[0], nums[1])] if len(nums) == 2 else [(nums[0], nums[1]), (nums[2], nums[3])]
            for ent, (vc, vp) in zip(ents, vals):
                for pc, pp in ([(p_cur, p_pri)] + ([(p_cur.replace("FY", "") + "Q4" if p_cur.startswith("FY") else None,
                                                     p_pri.replace("FY", "") + "Q4" if p_pri and p_pri.startswith("FY") else None)]
                                                   if stmt == "BS" else [])):
                    if pc:
                        self.put(f"{ent}|{key}|{pc}", vc * sc, f"{src} current", 0)
                    if pp:
                        self.put(f"{ent}|{key}|{pp}", vp * sc, f"{src} comparative", 1)

    # ------------------------------------------------------------------
    def fill_owner_profit(self):
        """Companies without subsidiaries/NCI show no profit attribution: NP to owners = profit for the period."""
        for fk, f in list(self.facts.items()):
            ent, key, per = fk.split("|")
            if key != "np":
                continue
            ok = f"{ent}|np_owners|{per}"
            if ok not in self.facts and f"{ent}|np_nci|{per}" not in self.facts:
                self.facts[ok] = {"v": f["v"], "src": f"profit for the period (no NCI line) {f['src']}", "rank": f["rank"]}

    def derive_quarters(self):
        """Turn cumulative YTD figures into single-quarter figures (flows only)."""
        flow_keys = [k for k, (st, _) in LABELS.items() if st in ("IS", "CF")]
        years = set()
        for fk in self.facts:
            p = fk.split("|")[2]
            mm = re.search(r"(\d{4})", p)
            if mm:
                years.add(int(mm.group(1)))
        for ent in ("C", "S"):
            for key in flow_keys:
                if key in PER_SHARE:
                    for y in sorted(years):
                        fy, n9 = self.facts.get(f"{ent}|{key}|FY{y}"), self.facts.get(f"{ent}|{key}|9M{y}")
                        if fy and n9 and f"{ent}|{key}|{y}Q4" not in self.facts:
                            self.facts[f"{ent}|{key}|{y}Q4"] = {"v": fy["v"] - n9["v"], "rank": 2,
                                                                 "src": f"derived =FY{y}-9M{y} (approx: share count changes)"}
                    continue
                st = LABELS[key][0]
                for y in sorted(years):
                    g = lambda p: self.facts.get(f"{ent}|{key}|{p}")
                    cum = {3: g(f"3M{y}") if st == "CF" else g(f"{y}Q1"), 6: g(f"6M{y}"), 9: g(f"9M{y}"), 12: g(f"FY{y}")}
                    if st == "CF" and cum[3]:
                        self._derive(ent, key, f"{y}Q1", cum[3]["v"], f"=3M{y} ({cum[3]['src']})")
                    # Q2
                    if not g(f"{y}Q2") and cum[6] and cum[3]:
                        self._derive(ent, key, f"{y}Q2", cum[6]["v"] - cum[3]["v"], f"=6M{y}-3M{y}")
                    # Q3
                    if not g(f"{y}Q3") and cum[9] and cum[6]:
                        self._derive(ent, key, f"{y}Q3", cum[9]["v"] - cum[6]["v"], f"=9M{y}-6M{y}")
                    # Q4 always derived from FY - 9M
                    if not g(f"{y}Q4") and cum[12] and cum[9]:
                        self._derive(ent, key, f"{y}Q4", cum[12]["v"] - cum[9]["v"], f"=FY{y}-9M{y}")
                    # build missing cumulative figures from quarters (helps later checks)
                    if st == "IS" and not cum[6] and g(f"{y}Q1") and g(f"{y}Q2"):
                        self._derive(ent, key, f"6M{y}", g(f"{y}Q1")["v"] + g(f"{y}Q2")["v"], f"=Q1+Q2 {y}")

    def _derive(self, ent, key, period, v, how):
        fk = f"{ent}|{key}|{period}"
        if fk not in self.facts:
            self.facts[fk] = {"v": v, "src": f"derived {how}", "rank": 2}

    # ------------------------------------------------------------------
    def jitta_fallback(self, jitta_path):
        """Fill consolidated gaps (older periods) from Jitta; tagged so the sheet can colour them."""
        if not jitta_path or not os.path.exists(jitta_path):
            return
        j = json.load(open(jitta_path, encoding="utf-8"))
        mp = {"total_assets": "total_assets", "total_liab": "total_liabilities", "equity_owners": "shareholder_equity",
              "ppe": "property_plant_equipment_net", "np_owners": "net_profit", "cfo": "cash_from_op_activities",
              "cf_da": "depreciation", "dps": "dividend_per_share", "shares_out": "common_shares_out"}
        # NB: Jitta working-capital lines (receivables/payables/current assets) use narrower definitions than
        # the filings, so they are deliberately NOT used as fallbacks - a gap is better than a mismatched series.
        metrics = {m["metric"]: m for m in j.get("metrics", [])}
        for key, jm in mp.items():
            m = metrics.get(jm)
            if not m:
                continue
            for q, v in (m.get("quarterly") or {}).items():
                if v is None:
                    continue
                fk = f"C|{key}|{q}"
                if fk not in self.facts:
                    self.facts[fk] = {"v": float(v), "src": f"Jitta {jm} {q}", "rank": 3}
            for y, v in (m.get("annual") or {}).items():
                if v is None:
                    continue
                fk = f"C|{key}|FY{y}"
                if fk not in self.facts:
                    self.facts[fk] = {"v": float(v), "src": f"Jitta {jm} FY{y}", "rank": 3}
        # Jitta 'total_revenue' = hospital revenue + other income; keep separately so it is never mistaken for rev_hosp
        m = metrics.get("total_revenue")
        if m:
            for y, v in (m.get("annual") or {}).items():
                fk = f"C|total_rev|FY{y}"
                if fk not in self.facts and v is not None:
                    self.facts[fk] = {"v": float(v), "src": f"Jitta total_revenue FY{y}", "rank": 3}
        m = metrics.get("gross_profit")
        if m:
            for y, v in (m.get("annual") or {}).items():
                fk = f"C|gp_jitta|FY{y}"
                if v is not None:
                    self.facts[fk] = {"v": float(v), "src": f"Jitta gross_profit FY{y}", "rank": 3}

    def validate(self):
        """Internal ties that should hold in any filing; failures are reported, not fixed."""
        for fk, f in list(self.facts.items()):
            ent, key, p = fk.split("|")
            if key == "total_assets":
                le = self.facts.get(f"{ent}|total_le|{p}")
                if le and abs(le["v"] - f["v"]) > 0.01:
                    self.flags.append(f"BS TIE FAIL {ent} {p}: assets {f['v']:.3f} vs L+E {le['v']:.3f}")
                tl, te = self.facts.get(f"{ent}|total_liab|{p}"), self.facts.get(f"{ent}|total_equity|{p}")
                if tl and te and abs(f["v"] - tl["v"] - te["v"]) > 0.01:
                    self.flags.append(f"BS TIE FAIL {ent} {p}: assets {f['v']:.3f} vs liab+equity {tl['v']+te['v']:.3f}")
            if key == "np" and re.match(r"\d{4}Q\d", p):
                pbt, tax = self.facts.get(f"{ent}|pbt|{p}"), self.facts.get(f"{ent}|tax|{p}")
                if pbt and tax and abs(pbt["v"] + tax["v"] - f["v"]) > 0.01 and abs(pbt["v"] - tax["v"] - f["v"]) > 0.01:
                    self.flags.append(f"P&L TIE FAIL {ent} {p}: PBT {pbt['v']:.3f} tax {tax['v']:.3f} NP {f['v']:.3f}")


def find_default_files(stock_dir):
    cands = []
    for pat in ["md/raw/combined_financial_all.md", "md/raw/combined_fs2_all.md",
                "md/combined_financial_all.md", "md/FINANCIAL_STATEMENTS.txt", "md/raw/combined_fs*_all.md"]:
        cands += glob.glob(os.path.join(stock_dir, pat))
    seen, out = set(), []
    for c in cands:
        if c not in seen:
            seen.add(c); out.append(c)
    return out


def find_jitta(stock_dir, ticker):
    for pat in [f"set/factsheet/factsheet_jitta_{ticker}.json", f"factsheet/factsheet_jitta_{ticker}.json", f"md/factsheets/factsheet_jitta_{ticker}.json",
                f"md/raw/_cache_factsheet_jitta_{ticker}.json", f"factsheet/factsheet_jitta_{ticker.lower()}.json"]:
        p = os.path.join(stock_dir, pat)
        if os.path.exists(p):
            return p
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stock-dir", "-d")
    ap.add_argument("--ticker", "-t", required=True)
    ap.add_argument("--files", nargs="*")
    ap.add_argument("--jitta")
    ap.add_argument("--output", "-o")
    ap.add_argument("--dump-labels", action="store_true", help="print unmapped statement labels and exit")
    ap.add_argument("--all-flags", action="store_true", help="also print flags for periods outside the model window")
    a = ap.parse_args()
    files = a.files or (find_default_files(a.stock_dir) if a.stock_dir else [])
    if not files:
        sys.exit("No statement files found. Pass --files or --stock-dir containing md/raw/combined_financial_all.md")
    ex = Extractor()
    for f in files:
        print(f"  reading {f}")
        ex.run_file(f)
    if a.dump_labels:
        for (st, lab), n in sorted(ex.unmapped.items(), key=lambda x: -x[1])[:150]:
            print(f"{st}\t{n}\t{lab}")
        return
    ex.fill_owner_profit()
    ex.derive_quarters()
    ex.jitta_fallback(a.jitta or (find_jitta(a.stock_dir, a.ticker.upper()) if a.stock_dir else None))
    ex.validate()
    quarters = sorted({fk.split("|")[2] for fk in ex.facts if re.fullmatch(r"\d{4}Q[1-4]", fk.split("|")[2])})
    years = sorted({int(fk.split("|")[2][2:]) for fk in ex.facts if fk.split("|")[2].startswith("FY")})
    out = {
        "ticker": a.ticker.upper(), "unit": "THB million (EPS in THB)",
        "generated": datetime.now().isoformat(timespec="seconds"),
        "source_files": files,
        "quarters": quarters, "years": years,
        "facts": {k: {"v": round(v["v"], 6), "src": v["src"]} for k, v in sorted(ex.facts.items())},
        "flags": sorted(set(ex.flags)),
    }
    outp = a.output or os.path.join(a.stock_dir or ".", "report", f"{a.ticker.upper()}_financials.json")
    os.makedirs(os.path.dirname(os.path.abspath(outp)), exist_ok=True)
    json.dump(out, open(outp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # coverage summary so the agent sees gaps immediately
    core = ["rev_hosp", "cogs", "selling", "admin", "op_profit", "fin_cost", "tax", "np", "np_owners",
            "cash", "total_assets", "total_liab", "total_equity", "cf_da", "cfo"]
    print(f"\n✅ wrote {outp}  ({len(out['facts'])} facts, {len(out['flags'])} flags)")
    print("coverage (last 14 quarters)  C = consolidated, S = separate:")
    for ent in ("C", "S"):
        for k in core:
            row = "".join("■" if f"{ent}|{k}|{q}" in ex.facts else "·" for q in quarters[-14:])
            print(f"  {ent} {k:<13} {row}")
    # v2 (16/10/2569): print only flags for the periods the model uses (last 14 quarters, last 6 fiscal years).
    # Older filings added by hand (e.g. set/fs/FS_2018..2020_hand) produce hundreds of RESTATED/CONFLICT lines
    # for years the model never shows. They stay in the JSON "flags"; --all-flags prints them.
    q_from = quarters[-14:][0] if quarters else "0000Q1"
    y_from = min(int(q_from[:4]), (years[-1] - 5) if years else 0)

    def flag_year(fl):
        m = re.search(r"[| ](?:FY|[69]M)?((?:19|20)\d\d)(?:Q[1-4])?\b", fl)
        if m:
            return int(m.group(1))
        m = re.search(r"FS[23]?_Year(25\d\d)", fl)                 # filing named in Buddhist-era years
        if m:
            return int(m.group(1)) - 543
        m = re.search(r"\b((?:19|20)\d\d)(?:0[1-9]|1[0-2])_", fl)   # SEC folder FS_<YYYYMM>_...
        return int(m.group(1)) if m else None

    def in_window(fl):
        y = flag_year(fl)
        if y is None:
            return True
        m = re.search(r"((?:19|20)\d\d)Q([1-4])", fl)
        if m and not fl.startswith("AMBIGUOUS"):
            return (m.group(1) + "Q" + m.group(2)) >= q_from
        return y >= y_from

    shown = out["flags"] if a.all_flags else [fl for fl in out["flags"] if in_window(fl)]
    for fl in shown[:40 if a.all_flags else 25]:
        print("  ⚠", fl)
    if len(shown) > (40 if a.all_flags else 25):
        print(f"  … {len(shown) - (40 if a.all_flags else 25)} more flags in the model window (see JSON 'flags')")
    hidden = len(out["flags"]) - len(shown)
    if hidden:
        print(f"  ({hidden} flags for periods before {q_from} / FY{y_from} hidden — outside the model window; "
              f"kept in the JSON 'flags'. --all-flags prints them.)")


if __name__ == "__main__":
    main()
