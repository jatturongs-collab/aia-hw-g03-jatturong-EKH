#!/usr/bin/env python3
"""
snapshot.py - data layer + checks for the stock-snapshot skill (Thai listed hospital / medical stocks ONLY).

Other businesses are refused on purpose: the rules (SSO, ECL, incremental GPM, seasonality) are hospital rules.

Every number in the snapshot comes from here.  The data pack is computed from the statement facts
extracted by the thai-hospital-finance-sheet skill (<T>_financials.json, with source lines), the MD&A
revenue mix (<T>_mda.json, reconciled to the statements) and the curated assumptions file
(<T>_assumptions.json: one-offs, category, market price).  Nothing is estimated with fixed ratios.

Sub-commands
  data    build report/<T>_snapshot_data.json and print a compact digest (what the agent reads)
  render  write report/<T>_Snapshot_Report_Q<q>_<BE>-v<N>.md + .html   (uses <T>_snapshot_narrative.json if present,
          otherwise an automatic rule-based narrative clearly labelled as such)
  check   verify a narrative file: every number must exist in the data pack, or carry a source, or be listed
          as an external/unverified item
  run     data + render for one or more tickers (batch / no agent), e.g.  run VIH PR9   or  run -f input1.txt

Typical agent flow
  python3 snapshot.py data   --stock-dir "$S" --ticker VIH           # read the digest
  (read the latest MD&A for reasons, write report/VIH_snapshot_narrative.json)
  python3 snapshot.py check  --stock-dir "$S" --ticker VIH
  python3 snapshot.py render --stock-dir "$S" --ticker VIH
"""
import argparse, glob, json, os, re, statistics, sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
def _require_ai_root():
    """AI_ROOT is the ONE machine-wide setting: the folder that holds data/ and Thstock/ (Windows C:\ai, WSL /mnt/c/ai).
    It is never guessed. If it is missing or wrong the run stops with a message; the agent must then ask the user."""
    env = os.environ.get("AI_ROOT")
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        return env or ""
    why = None
    if not env:
        why = "the environment variable AI_ROOT is not set"
    elif not os.path.isdir(os.path.join(env, "data")) or not os.path.isdir(os.path.join(env, "Thstock")):
        why = "AI_ROOT=%r does not hold both data/ and Thstock/" % env
    if why:
        sys.exit("STOP: %s.\nDo NOT guess a folder. Ask the user which folder holds data/ and Thstock/ "
                 "(normally C:\\ai on Windows, /mnt/c/ai in WSL), set AI_ROOT to it, then run again." % why)
    return env


AI_ROOT = _require_ai_root()
FS_CANDIDATES = [HERE]            # this skill ships the finance-sheet extractors in the same scripts/ folder
FS_DIR = next((os.path.abspath(d) for d in FS_CANDIDATES if os.path.isfile(os.path.join(d, "build_finance_sheet.py"))), None)
if FS_DIR:
    sys.path.insert(0, FS_DIR)
sys.path.insert(0, HERE)
try:
    import fs_notes as FN
except ImportError:          # pragma: no cover
    FN = None

ROOT_CANDIDATES = [os.path.join(AI_ROOT, "Thstock")] if AI_ROOT else []

CATEGORY_NAMES = {
    1: "Category 1: รพ.พรีเมียม/ผู้ป่วยต่างชาติ (Non-SSO)",
    2: "Category 2: รพ.ที่มีประกันสังคมเป็นฐาน (SSO)",
    3: "Category 3: รพ.เอกชนทั่วไป/ภูมิภาค",
    4: "Category 4: คลินิก/ความงาม/เฉพาะทาง",
    5: "Category 5: ธุรกิจสนับสนุน/อุปกรณ์การแพทย์",
}
# tickers of categories 4-5 (the finance-sheet table covers 1-3); see hospital_taxonomy.md
EXTRA_CATEGORY = {t: 4 for t in ("MASTER", "KLINIQ", "TRP")}
EXTRA_CATEGORY.update({t: 5 for t in ("SAFE", "MEDEZE", "BKGI")})


class NotHospital(RuntimeError):
    pass


def hospital_category(ticker, asm):
    """Category 1-5 from the assumptions file or the hospital taxonomy; refuse anything else."""
    cat = asm.get("category")
    if not cat and FS_DIR:
        import build_finance_sheet as BF
        cat = BF.HOSPITAL_CATEGORY.get(ticker)
    cat = cat or EXTRA_CATEGORY.get(ticker)
    if cat not in CATEGORY_NAMES:
        raise NotHospital("%s is not in the Thai hospital/medical taxonomy. stock-snapshot is for hospital and medical stocks only; "
                          "if %s is one, set \"category\" (1-5) in report/%s_assumptions.json (see hospital_taxonomy.md). "
                          "Use a different skill for other businesses." % (ticker, ticker, ticker))
    return cat


# ------------------------------------------------------------------------------------------ periods
def qsplit(p):
    return int(p[:4]), int(p[-1])


def qadd(p, n):
    y, q = qsplit(p)
    k = y * 4 + (q - 1) + n
    return "%dQ%d" % (k // 4, k % 4 + 1)


def be(p):
    m = re.fullmatch(r"(\d{4})Q(\d)", p)
    if m:
        return "Q%s/%d" % (m.group(2), int(m.group(1)) + 543)
    m = re.fullmatch(r"(\d+)M(\d{4})", p)
    if m:
        return "%sM/%d" % (m.group(1), int(m.group(2)) + 543)
    m = re.fullmatch(r"FY(\d{4})", p)
    if m:
        return "ปี %d" % (int(m.group(1)) + 543)
    m = re.fullmatch(r"TTM(\d{4}Q\d)", p)
    return ("TTM ถึง " + be(m.group(1))) if m else p


def pct(a, b):
    """% change; None when the base is zero/negative-to-positive (a sign flip makes % meaningless)."""
    if a is None or b is None or abs(b) < 1e-6 or a * b < 0:
        return None
    return (a / b - 1) * (1 if b > 0 else -1)


NO_PCT = {"divp", "ecl", "one_off", "fin_net"}   # shown as absolute change only


def tier(ch):
    """3-tier YoY framework: T1 <=3%, T2 3-10%, T3 >10% (absolute change)."""
    if ch is None:
        return None
    a = abs(ch) * 100
    return 1 if a <= 3 else (2 if a <= 10 else 3)


# ------------------------------------------------------------------------------------------ inputs
def find_root(explicit=None):
    """Thstock folder: --root if given and it exists, else <AI_ROOT>/Thstock. No other guess."""
    if explicit:
        if os.path.isdir(explicit):
            return explicit
        sys.exit("STOP: --root %r is not a folder. Ask the user for the right Thstock folder." % explicit)
    return ROOT_CANDIDATES[0] if ROOT_CANDIDATES and os.path.isdir(ROOT_CANDIDATES[0]) else None


def ai_root(sdir=None):
    """The data root (holds data/, Thstock/, etc/): AI_ROOT, nothing else. `sdir` is accepted for old callers."""
    return AI_ROOT or None


def same_place(a, b):
    n = lambda x: os.path.normcase(os.path.realpath(os.path.abspath(x)))
    return n(a) == n(b)


def check_stock_dir(sdir):
    """The stock folder must be <AI_ROOT>/Thstock/<T>. A copy elsewhere would mix its own data with the master's sector,
    peer and factsheet data, so stop and ask instead of guessing."""
    if not AI_ROOT:
        return sdir
    home = os.path.join(AI_ROOT, "Thstock")
    if not same_place(os.path.dirname(os.path.abspath(sdir)), home):
        sys.exit("STOP: stock folder %r is not under %r. The skill reads sector, peer and factsheet data from AI_ROOT; a copy "
                 "elsewhere would mix the two. Ask the user: run on the master folder, or change AI_ROOT." % (sdir, home))
    return sdir


def peers_root(sdir=None):
    """The folder that holds the OTHER stocks' folders: <AI_ROOT>/Thstock."""
    return os.path.join(AI_ROOT, "Thstock") if AI_ROOT else os.path.dirname(os.path.abspath(sdir))


def ensure_inputs(sdir, ticker, rebuild=False, quiet=False):
    """Make sure report/<T>_financials.json and <T>_mda.json exist (runs the finance-sheet extractors)."""
    rep = os.path.join(sdir, "report")
    os.makedirs(rep, exist_ok=True)
    fin = os.path.join(rep, "%s_financials.json" % ticker)
    raw = glob.glob(os.path.join(sdir, "md", "raw", "combined_*_all.md"))
    newest_raw = max((os.path.getmtime(f) for f in raw), default=0)
    if rebuild or not os.path.isfile(fin) or os.path.getmtime(fin) < newest_raw:
        if not FS_DIR:
            raise RuntimeError("thai-hospital-finance-sheet scripts not found and %s missing" % fin)
        import extract_financials as EX
        ex = EX.Extractor()
        for f in EX.find_default_files(sdir):
            ex.run_file(f)
        ex.derive_quarters()
        ex.jitta_fallback(EX.find_jitta(sdir, ticker))
        ex.validate()
        quarters = sorted({k.split("|")[2] for k in ex.facts if re.fullmatch(r"\d{4}Q[1-4]", k.split("|")[2])})
        years = sorted({int(k.split("|")[2][2:]) for k in ex.facts if k.split("|")[2].startswith("FY")})
        data = {"ticker": ticker, "unit": "THB million (EPS in THB)", "generated": datetime.now().isoformat(timespec="seconds"),
                "source_files": EX.find_default_files(sdir), "quarters": quarters, "years": years,
                "facts": {k: {"v": round(v["v"], 6), "src": v["src"]} for k, v in sorted(ex.facts.items())},
                "flags": sorted(set(ex.flags))}
        json.dump(data, open(fin, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        if not quiet:
            print("   extracted statements -> %s" % os.path.basename(fin))
    mda = os.path.join(rep, "%s_mda.json" % ticker)
    mda_src = os.path.join(sdir, "md", "raw", "combined_mda_all.md")
    if os.path.isfile(mda_src) and (rebuild or not os.path.isfile(mda) or os.path.getmtime(mda) < max(os.path.getmtime(mda_src), os.path.getmtime(fin))):
        if FS_DIR and os.path.isfile(os.path.join(FS_DIR, "extract_mda.py")):
            import extract_mda as MDA
            res = MDA.build(sdir, fin, mda_src)
            res.update({"ticker": ticker, "generated": datetime.now().isoformat(timespec="seconds")})
            json.dump(res, open(mda, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            if not quiet:
                print("   extracted MD&A revenue mix -> %s" % os.path.basename(mda))
    # operating metrics from the Opportunity Day slide PDFs (read by position; optional)
    pdfs = glob.glob(os.path.join(sdir, "set", "oppday", "oppday_*.pdf"))
    ops = os.path.join(rep, "%s_ops_metrics.json" % ticker)
    if pdfs and (rebuild or not os.path.isfile(ops) or os.path.getmtime(ops) < max(os.path.getmtime(f) for f in pdfs)):
        try:
            import oppday_ops as OPS
            if OPS.pymupdf is not None:
                json.dump(OPS.build(sdir, ticker), open(ops, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
                if not quiet:
                    print("   read Oppday operating metrics -> %s" % os.path.basename(ops))
        except Exception as e:                       # never block the report on the optional file
            if not quiet:
                print("   Oppday operating metrics skipped (%s)" % e)
    return fin, (mda if os.path.isfile(mda) else None)


def load_json(p):
    return json.load(open(p, encoding="utf-8")) if p and os.path.isfile(p) else {}


def set_factsheet_price(sdir, ticker):
    best = {}
    for pat in ["set/factsheet/factsheet_set_%s.json", "factsheet/factsheet_set_%s.json", "md/factsheets/factsheet_set_%s.json"]:
        p = os.path.join(sdir, pat % ticker)
        if os.path.isfile(p):
            d = load_json(p).get("data", {})
            ts = d.get("trading_stat") or {}
            if isinstance(ts, list):     # the SET API lists the latest year first: take the newest date, whatever the order
                ts = max(ts, key=lambda x: str(x.get("date", ""))) if ts else {}
            if ts.get("close") and str(ts.get("date", ""))[:10] > best.get("as_of", ""):
                best = {"price": ts.get("close"), "as_of": str(ts.get("date", ""))[:10],
                        "shares_mn": round((ts.get("listedShare") or 0) / 1e6, 3) or None, "source": "SET factsheet trading_stat"}
    return best


# ------------------------------------------------------------------------------------------ facts
class F:
    """Thin wrapper over the finance-sheet Facts class, so definitions match the Excel model exactly."""

    def __init__(self, fin, asm):
        self.src = {}
        if FS_DIR:
            import build_finance_sheet as BF
            self.facts = BF.Facts(fin, asm)
        else:
            self.facts = None
            self.f = fin["facts"]

    def get(self, key, per, ent="C"):
        if self.facts:
            v, s = self.facts.get(ent, key, per)
        else:
            x = self.f.get("%s|%s|%s" % (ent, key, per))
            v, s = (x["v"], x["src"]) if x else (None, None)
            if v is not None and key in ("cogs", "selling", "admin", "cf_da", "fin_cost"):
                v = abs(v)
        if v is not None:
            self.src["%s|%s" % (key, per)] = s
        return v


LINE_DEFS = [
    # id, label (Thai / English), formatter
    ("rev", "รายได้จากกิจการโรงพยาบาล (Hospital Revenue)"),
    ("oth", "รายได้อื่น + เงินปันผลรับ (Other Income)"),
    ("total_rev", "รายได้รวม (Total Revenue)"),
    ("cogs", "ต้นทุนกิจการโรงพยาบาล (COGS)"),
    ("gp", "กำไรขั้นต้น (Gross Profit)"),
    ("gpm", "อัตรากำไรขั้นต้น (GPM %)"),
    ("selling", "ค่าใช้จ่ายในการขาย (Selling)"),
    ("admin", "ค่าใช้จ่ายในการบริหาร (Admin)"),
    ("sga", "รวม SG&A"),
    ("sg_pct", "% ค่าใช้จ่ายขายต่อรายได้ (% SG)"),
    ("sa_pct", "% ค่าใช้จ่ายบริหารต่อรายได้ (% SA)"),
    ("sga_pct", "% SG&A ต่อรายได้"),
    ("core_op", "กำไรจากการดำเนินงานหลัก (GP − SG&A, ไม่รวมรายได้อื่น)"),
    ("core_pbt", "กำไรก่อนภาษีธุรกิจรพ. (Core PBT: ไม่รวมรายได้อื่น/ดอกเบี้ย/เงินปันผล)"),
    ("core_pbt_x", "Core PBT ก่อน ECL และรายการพิเศษ (ก่อนภาษี)"),
    ("admin_x", "ค่าใช้จ่ายบริหารก่อน ECL และรายการพิเศษ"),
    ("sga_x", "รวม SG&A ก่อน ECL และรายการพิเศษ"),
    ("ebit", "กำไรจากการดำเนินงาน (EBIT, รวมรายได้อื่น)"),
    ("ebit_m", "EBIT Margin % (ของรายได้รวม)"),
    ("fin_net", "รายได้(ต้นทุน)ทางการเงินสุทธิ + ส่วนแบ่งกำไร"),
    ("pbt", "กำไรก่อนภาษี (PBT)"),
    ("tax", "ภาษีเงินได้ (Tax)"),
    ("etr", "อัตราภาษีที่แท้จริง (ETR %)"),
    ("np_owners", "กำไรสุทธิส่วนของบริษัทใหญ่ (NP)"),
    ("npm", "อัตรากำไรสุทธิ (NPM %, ของรายได้รวม)"),
    ("one_off", "รายการพิเศษหลังภาษี (One-off)"),
    ("core_np", "กำไรปกติ (Core Profit)"),
    ("eps", "EPS (บาท)"),
    ("da", "ค่าเสื่อมราคาและค่าตัดจำหน่าย (D&A)"),
    ("ebitda", "EBITDA"),
    ("ebitda_m", "EBITDA Margin %"),
    ("ecl", "ผลขาดทุนด้านเครดิต ECL (งบกระแสเงินสด)"),
    ("ecl_pct", "% ECL ต่อรายได้"),
    ("cash_total", "เงินสด + เงินลงทุนระยะสั้น"),
    ("debt_lease", "หนี้ที่มีดอกเบี้ย + หนี้สินตามสัญญาเช่า"),
    ("net_cash", "เงินสดสุทธิ (Net Cash)"),
    ("recv", "ลูกหนี้การค้าและลูกหนี้อื่น"),
    ("dso", "ระยะเวลาเก็บหนี้ (DSO, วัน)"),
    ("equity", "ส่วนของผู้ถือหุ้นบริษัทใหญ่"),
    ("cfo", "กระแสเงินสดจากการดำเนินงาน (CFO)"),
    ("capex", "รายจ่ายลงทุน (Capex)"),
    ("fcf", "กระแสเงินสดอิสระ (FCF = CFO − Capex)"),
    ("divp", "เงินปันผลจ่าย (งบกระแสเงินสด)"),
]
PCT_LINES = {"gpm", "sg_pct", "sa_pct", "sga_pct", "ebit_m", "etr", "npm", "ebitda_m", "ecl_pct"}
FLOW_LINES = {"rev", "oth", "total_rev", "cogs", "gp", "selling", "admin", "sga", "core_op", "core_pbt", "core_pbt_x",
              "admin_x", "sga_x", "oo_pre", "ebit", "fin_net", "pbt", "tax",
              "np_owners", "one_off", "core_np", "eps", "da", "ebitda", "ecl", "cfo", "capex", "fcf", "divp"}


def period_lines(fx, per, ann=4, oo_pre=None, ecl_line="admin", oo_sga=None):
    g = fx.get
    L = {}
    L["rev"] = rev = g("rev_hosp", per)
    div, oth = g("div_inc", per), g("oth_inc", per)
    L["oth"] = (div or 0) + (oth or 0) if (div is not None or oth is not None) else None
    L["total_rev"] = rev + (L["oth"] or 0) if rev is not None else None
    L["cogs"] = cogs = g("cogs", per)
    L["gp"] = gp = rev - cogs if rev is not None and cogs is not None else None
    L["gpm"] = gp / rev if gp is not None and rev else None
    sel, adm = g("selling", per), g("admin", per)
    L["selling"], L["admin"] = sel, adm
    L["sga"] = sga = (sel or 0) + (adm or 0) if (sel is not None or adm is not None) else None
    L["sg_pct"] = sel / rev if sel is not None and rev else None
    L["sa_pct"] = adm / rev if adm is not None and rev else None
    L["sga_pct"] = sga / rev if sga is not None and rev else None
    L["core_op"] = gp - sga if gp is not None and sga is not None else None
    L["ebit"] = ebit = L["total_rev"] - cogs - sga if None not in (L["total_rev"], cogs, sga) else None
    L["ebit_m"] = ebit / L["total_rev"] if ebit is not None and L["total_rev"] else None
    fi, fc, asc = g("fin_inc", per), g("fin", per), g("assoc", per)
    L["fin_net"] = (fi or 0) - (fc or 0) + (asc or 0)
    L["pbt"] = pbt = g("pbt", per)
    L["tax"] = tax = g("tax", per)
    L["etr"] = tax / pbt if tax is not None and pbt else None
    npo = g("np_owners", per)
    if (npo is None or str(fx.src.get("np_owners|%s" % per, "")).startswith("Jitta")) and g("np", per) is not None \
            and not str(fx.src.get("np|%s" % per, "")).startswith("Jitta"):
        # companies without NCI report only "profit for the period"; prefer the filing over the Jitta fallback
        npo = g("np", per) - (g("nci", per) or 0.0)
        fx.src["np_owners|%s" % per] = "NP − NCI (%s)" % fx.src.get("np|%s" % per)
    L["np_owners"] = npo
    L["npm"] = g("np", per) / L["total_rev"] if g("np", per) is not None and L["total_rev"] else None
    oo = g("one_off", per)
    L["one_off"] = oo or 0.0
    L["core_np"] = npo - (oo or 0) if npo is not None else None
    L["eps"] = g("eps", per)
    L["da"] = da = g("cf_da", per)
    ecl0 = g("cf_ecl", per)
    # Core PBT (Pop-style): hospital operations only = GP − SG&A − finance cost (no other/interest/dividend income, no associates)
    fcst = g("fin", per)
    L["core_pbt"] = L["core_op"] - (fcst or 0) if L["core_op"] is not None else None
    L["oo_pre"] = (oo_pre or {}).get(per, 0.0)
    L["core_pbt_x"] = (L["core_pbt"] + ecl0 - L["oo_pre"]) if L["core_pbt"] is not None and ecl0 is not None else None
    in_admin = ecl_line == "admin"
    # before ECL and before one-offs booked in SG&A (a provision reversal lowers SG&A: add it back)
    oos = (oo_sga or {}).get(per, 0.0)
    L["admin_x"] = (adm - ecl0 + oos) if adm is not None and ecl0 is not None and in_admin else (adm + oos if adm is not None and not in_admin else None)
    L["sga_x"] = (sga - ecl0 + oos) if sga is not None and ecl0 is not None and ecl_line in ("admin", "selling") else None
    L["ebitda"] = ebit + da if ebit is not None and da is not None else None
    L["ebitda_m"] = L["ebitda"] / L["total_rev"] if L["ebitda"] is not None and L["total_rev"] else None
    L["ecl"] = ecl = g("cf_ecl", per)
    L["ecl_pct"] = ecl / rev if ecl is not None and rev else None
    cash, sti = g("cash", per), g("st_invest", per)
    L["cash_total"] = (cash or 0) + (sti or 0) if cash is not None else None
    debt, lease = g("debt", per), g("lease", per)
    L["debt_lease"] = (debt or 0) + (lease or 0) if (debt is not None or lease is not None) else None
    L["net_cash"] = L["cash_total"] - (L["debt_lease"] or 0) if L["cash_total"] is not None else None
    L["recv"] = recv = g("receivables", per)
    L["dso"] = recv / (rev * ann) * 365 if recv is not None and rev else None
    L["equity"] = g("equity_owners", per)
    L["cfo"] = cfo = g("cfo", per)
    L["capex"] = capex = g("capex", per)
    L["fcf"] = cfo - capex if cfo is not None and capex is not None else None
    L["divp"] = g("divp", per)
    L["nci"] = g("nci", per)
    L["div_inc"] = div
    L["assets"] = g("total_assets", per)
    L["liab"] = g("total_liab", per)
    L["tot_equity"] = g("total_equity", per)
    L["np"] = g("np", per)
    return L


# ------------------------------------------------------------------------------------------ helpers
OO_PRE_RE = re.compile(r"([−\-+]?\d[\d,]*(?:\.\d+)?)\s*ลบ\.\s*ก่อนภาษี")


def one_off_pretax(asm):
    """Pre-tax one-offs per period (quarters, rolled into YTD and FY), for Core PBT ex-one-offs.

    Taken from "amount_pretax" when given, otherwise from the label's "<x> ลบ. ก่อนภาษี" (the sign follows the
    after-tax amount).  One-offs booked outside GP/SG&A (e.g. a gain in other income: "line": "other_income") are
    already outside Core PBT and are skipped.  Never grossed up with an assumed tax rate.

    A one-off that mixes lines can list its parts, as the MD&A states them:
      "pretax_items": [{"amount": 13.07, "line": "admin"}, {"amount": 2.77, "line": "other_income"}]
    Parts booked in admin/selling/sga are also added back to "SG&A before ECL" so a provision reversal in the
    base period does not look like cost growth.  Returns (core_pretax, gaps, sga_pretax)."""
    out, gaps, sga_out = {}, [], {}

    def targets_of(per):
        m = re.fullmatch(r"(\d{4})Q(\d)", per)
        t = [per]
        if m:
            y, q = int(m.group(1)), int(m.group(2))
            t += ["FY%d" % y] + ["%dM%d" % (3 * k, y) for k in (2, 3) if q <= k]
        return t
    for o in asm.get("one_offs") or []:
        per = o.get("period", "")
        if o.get("pretax_items"):
            for it in o["pretax_items"]:
                line = it.get("line", "")
                if line in ("other_income", "oth", "finance", "associate"):
                    continue
                for t in targets_of(per):
                    out[t] = out.get(t, 0.0) + float(it["amount"])
                    if line in ("admin", "selling", "sga"):
                        sga_out[t] = sga_out.get(t, 0.0) + float(it["amount"])
            continue
        if o.get("line") in ("other_income", "oth", "finance", "associate"):
            continue
        v = o.get("amount_pretax")
        if v is None:
            m = OO_PRE_RE.search(o.get("label", ""))
            if m:
                v = abs(float(m.group(1).replace(",", "").replace("−", "-")))
                v = v if float(o.get("amount_after_tax", 0)) >= 0 else -v
        if v is None:
            gaps.append("รายการพิเศษ %s ไม่มียอดก่อนภาษี (amount_pretax) — Core PBT ก่อนรายการพิเศษไม่ได้ปรับรายการนี้" % per)
            continue
        for t in targets_of(per):
            out[t] = out.get(t, 0.0) + float(v)
            if o.get("line") in ("admin", "selling", "sga"):
                sga_out[t] = sga_out.get(t, 0.0) + float(v)
    return out, gaps, sga_out


def ecl_attribution(notes, q_last, ecl_ytd):
    """Where the ECL allowance moved (receivables note), for the ECL red flag."""
    rc = (notes or {}).get("receivables")
    if not rc:
        return None
    y = int(q_last[:4])
    names = {"trade_unrelated": "ลูกหนี้การค้า (บุคคลภายนอก)", "trade_related": "ลูกหนี้การค้า (กิจการเกี่ยวข้อง)",
             "other_unrelated": "ลูกหนี้อื่น/รายได้ค้างรับ (บุคคลภายนอก)", "other_related": "ลูกหนี้อื่น (กิจการเกี่ยวข้อง)"}
    rows, parts, total_d = [], [], 0.0
    for k, gdat in rc["groups"].items():
        al = gdat.get("allowance")
        if al:
            d = al[0] - al[1]
            total_d += d
            rows.append({"group": k, "label": names.get(k, k), "cur": al[0], "prior": al[1], "delta": d, "src": gdat["src"].get("allowance")})
            if abs(d) >= 0.05:
                parts.append("%s %+.2f" % (names.get(k, k), d))
    aging = []
    tu = rc["groups"].get("trade_unrelated") or next(iter(rc["groups"].values()))
    od = lambda i: sum(tu["aging"].get(b, (0, 0))[i] for b in ("m3_6", "m6_12", "gt12"))
    over3 = (od(0), od(1)) if tu["aging"] else None
    for b, lab, _ in FN.BUCKETS:
        if b in tu["aging"]:
            c, p_ = tu["aging"][b]
            aging.append({"bucket": b, "label": lab, "cur": c, "prior": p_, "delta": c - p_, "src": tu["src"].get(b)})
    txt = "ค่าเผื่อ ECL ในหมายเหตุลูกหนี้เปลี่ยนแปลง %+.2f ลบ. จากสิ้นปี %d (%s)" % (total_d, y - 1 + 543, "; ".join(parts) or "ไม่เปลี่ยน")
    if ecl_ytd is not None:
        txt += " เทียบ ECL ในงบกระแสเงินสด YTD %.2f ลบ." % ecl_ytd
    aging_txt = None
    if over3:
        aging_txt = "ลูกหนี้การค้าค้างชำระเกิน 3 เดือน %.2f → %.2f ลบ. (สิ้นปี %d → %s)" % (over3[1], over3[0], y - 1 + 543, be(q_last))
        txt += "; " + aging_txt
    sso = rc.get("sso_accrued")
    if sso:
        txt += "; รายได้ประกันสังคมค้างรับ %.2f → %.2f ลบ." % (sso["prior"], sso["cur"])
    return {"rows": rows, "aging": aging, "over3": over3, "sso_accrued": sso, "total_delta": total_d, "ecl_ytd": ecl_ytd,
            "recon_diff": (total_d - ecl_ytd) if ecl_ytd is not None else None, "prior_label": "31 ธ.ค. %d" % (y - 1 + 543),
            "text": txt, "aging_text": aging_txt, "file": rc.get("file"), "lines": rc.get("lines")}


NATURE_KEYS = [("staff", "เงินเดือน ค่าจ้าง และผลประโยชน์พนักงาน"), ("da", "ค่าเสื่อมราคาและค่าตัดจำหน่าย"),
               ("doctor", "ค่าธรรมเนียมแพทย์"), ("referral", "ค่ารักษาพยาบาลผู้ป่วยส่งต่อ"),
               ("medicine", "ยา เวชภัณฑ์และวัสดุสิ้นเปลืองใช้ไป")]


def nature_block(fx, notes, lines, ytd, ytd_py, fy_list):
    """Expenses by nature: annual note (last two FY) + YTD from the interim note if any, else statement proxies."""
    annual = []
    for fy in fy_list:
        rev = fx.get("rev_hosp", fy)
        row = {"fy": fy, "rev": rev, "items": {}}
        for k, _ in NATURE_KEYS:
            v = fx.get("exp_" + k, fy)
            if v is not None:
                row["items"][k] = {"v": abs(v), "pct_rev": abs(v) / rev if rev else None}
        tot = [fx.get(k, fy) for k in ("cogs", "selling", "admin")]
        row["total_cost"] = sum(tot) if all(t is not None for t in tot) else None
        if row["items"]:
            annual.append(row)
    nat = (notes or {}).get("nature") or {}
    cf = (notes or {}).get("cashflow") or {}
    ytd_rows = []
    for k, lab in NATURE_KEYS:
        if k in nat:
            ytd_rows.append({"id": k, "label": lab, "cur": nat[k]["cur"], "prior": nat[k]["prior"], "src": nat[k]["src"], "kind": "note"})
        elif k == "da" and cf.get("da"):
            ytd_rows.append({"id": k, "label": lab, "cur": cf["da"]["cur"], "prior": cf["da"]["prior"], "src": cf["da"]["src"], "kind": "cashflow"})
        else:
            ytd_rows.append({"id": k, "label": lab, "cur": None, "prior": None, "src": None, "kind": "not_disclosed"})
        if k == "staff":
            mc = (notes or {}).get("mgmt_comp")
            if mc:
                ytd_rows.append({"id": "mgmt_comp", "label": "ในนั้น: ค่าตอบแทนกรรมการและผู้บริหาร", "cur": mc["cur"], "prior": mc["prior"],
                                 "src": mc["src"], "kind": "note", "sub": True})
            if cf.get("emp_provision"):
                e = cf["emp_provision"]
                ytd_rows.append({"id": "emp_provision", "label": "ในนั้น: ประมาณการผลประโยชน์พนักงานหลังออกจากงาน", "cur": e["cur"],
                                 "prior": e["prior"], "src": e["src"], "kind": "cashflow", "sub": True})
    for k, lab in (("ecl", "ผลขาดทุนด้านเครดิต (ECL)"), ("bad_debt", "หนี้สูญตัดจำหน่าย"), ("inv_writedown", "ปรับลดมูลค่ายาและเวชภัณฑ์")):
        if cf.get(k):
            ytd_rows.append({"id": k, "label": lab, "cur": cf[k]["cur"], "prior": cf[k]["prior"], "src": cf[k]["src"], "kind": "cashflow"})
    tc = lambda p: (sum(lines[p][k] for k in ("cogs", "selling", "admin")) if p in lines and all(lines[p].get(k) is not None for k in ("cogs", "selling", "admin")) else None)
    ytd_rows.append({"id": "total_cost", "label": "รวมต้นทุน + ค่าใช้จ่ายขาย + บริหาร (ตามงบ)", "cur": tc(ytd), "prior": tc(ytd_py), "src": "งบกำไรขาดทุน", "kind": "pl", "bold": True})
    for r in ytd_rows:
        r["yoy"] = pct(r["cur"], r["prior"]) if r["cur"] is not None and r["prior"] is not None and r["id"] not in ("ecl", "bad_debt", "inv_writedown") else None
        if r["cur"] is not None and r.get("prior") is not None:
            r["delta"] = r["cur"] - r["prior"]
    note_avail = bool(nat)
    reason = None if note_avail else (
        "งบการเงินระหว่างกาลแบบย่อ (TAS 34) ของงวดนี้ไม่มีหมายเหตุค่าใช้จ่ายตามลักษณะ — หมวดเงินเดือน/ค่าแพทย์/ค่ายา/ค่าส่งต่อจึงไม่มีตัวเลข %s "
        "(ไม่ประมาณเอง); แสดงรายการที่งบเปิดเผย และตัวเลขปีเต็มเป็นฐานอ้างอิง" % be(ytd) if (notes or {}).get("found") else
        "ไม่พบงบการเงินระหว่างกาลฉบับเต็มใน md/raw")
    return {"ytd": ytd, "ytd_py": ytd_py, "rows": ytd_rows, "annual": annual, "note_available": note_avail, "reason": reason}


def dividend_block(fx, lines, market, notes, season, q_last, ytd, fy_py):
    y = int(q_last[:4])
    hist = []
    last_fy = y if q_last.endswith("Q4") else y - 1          # FY y's DPS is declared with the Q4 results: no look-ahead
    for fy in ["FY%d" % k for k in range(y - 4, last_fy + 1)]:
        dps, eps, npo = fx.get("dps", fy), fx.get("eps", fy), fx.get("np_owners", fy)
        if dps is None and eps is None:
            continue
        hist.append({"fy": fy, "dps": dps, "eps": eps, "np_owners": npo, "payout": dps / eps if dps and eps else None})
    sh = (market or {}).get("shares_mn")
    L = lines.get(q_last, {})
    out = {"history": hist, "shares_mn": sh, "shares_note": (market or {}).get("shares_note"),
           "cash_total": L.get("cash_total"), "net_cash": L.get("net_cash"),
           "cash_ps": L["cash_total"] / sh if sh and L.get("cash_total") is not None else None,
           "net_cash_ps": L["net_cash"] / sh if sh and L.get("net_cash") is not None else None,
           "price": (market or {}).get("price")}
    if out["cash_ps"] and out["price"]:
        out["cash_to_price"] = out["cash_ps"] / out["price"]
    sa = ((notes or {}).get("cashflow") or {}).get("share_advance")
    if sa and sa["cur"]:
        out["share_advance"] = sa
    # mechanical FY core-profit estimate: YTD actual + the seasonality table's remaining quarters of this year
    rem = [s_ for s_ in season if s_["q"][:4] == str(y)]
    ytd_np = lines.get(ytd, {}).get("core_np")
    fy_np_py = lines.get(fy_py, {}).get("core_np") if fy_py in lines else None
    if ytd_np is not None and rem and all(s_.get("core_np_proj") is not None for s_ in rem):
        est = ytd_np + sum(s_["core_np_proj"] for s_ in rem)
        out["fy_core_np_est"] = est
        out["fy_core_np_py"] = fy_np_py
        out["fy_growth_est"] = pct(est, fy_np_py) if fy_np_py else None
        last = next((h["payout"] for h in reversed(hist) if h.get("payout")), None)
        if last and sh:
            sc = []
            for dp in (0.0, 0.05, 0.10):
                po = last + dp
                dps = est * po / sh
                sc.append({"payout": po, "dps": dps, "yield": dps / out["price"] if out["price"] else None,
                           "dps_growth": pct(dps, hist[-1]["dps"]) if hist and hist[-1].get("dps") else None})
            out["scenarios"] = sc
            out["method"] = ("กำไรปกติปีคาด = %s จริง + ค่าประมาณเชิงสถิติไตรมาสที่เหลือ (ตาราง 3.1); DPS = กำไรคาด × Payout ÷ %.2f ล้านหุ้น "
                             "— ค่าประมาณเชิงกลไก ไม่ใช่ประมาณการหรือนโยบายของบริษัท" % (be(ytd), sh))
    return out


# ------------------------------------------------------------------------------------------ build
def build_pack(sdir, ticker, quarter=None, rebuild=False, quiet=False, _expect=True):
    fin_p, mda_p = ensure_inputs(sdir, ticker, rebuild, quiet)
    fin = load_json(fin_p)
    asm_p = os.path.join(sdir, "report", "%s_assumptions.json" % ticker)
    asm = load_json(asm_p)
    mda = load_json(mda_p)
    # MD&A mix: assumptions (curated) first, then extracted periods that reconcile
    mix = {"quarterly": {}, "annual": {}}
    for sect in ("quarterly", "annual"):
        mix[sect].update((mda.get("revenue_mix") or {}).get(sect) or {})
        mix[sect].update(((asm.get("revenue_mix") or {}).get(sect)) or {})
    asm2 = dict(asm)
    asm2["revenue_mix"] = {"source": (asm.get("revenue_mix") or {}).get("source") or (mda.get("revenue_mix") or {}).get("source", "MD&A"),
                           **mix}
    fx = F(fin, asm2)
    cat = hospital_category(ticker, asm)          # refuses non-hospital stocks before any work
    ecl_line = asm.get("ecl_line", "admin")       # where the ECL charge sits in the P&L (TH hospitals: admin)
    oo_pre, oo_gaps, oo_sga = one_off_pretax(asm)

    quarters = sorted(q for q in fin.get("quarters", []) if fx.get("rev_hosp", q) is not None)
    if not quarters:
        raise RuntimeError("no quarterly hospital revenue in %s" % fin_p)
    q_last = quarter or quarters[-1]
    if q_last not in quarters:
        raise RuntimeError("quarter %s not available (latest %s)" % (q_last, quarters[-1]))
    qs_all = [q for q in quarters if q <= q_last]
    lines = {q: period_lines(fx, q, oo_pre=oo_pre, ecl_line=ecl_line, oo_sga=oo_sga) for q in qs_all}
    window = [qadd(q_last, -k) for k in range(3, -1, -1)]          # last 4 quarters
    ext = [qadd(q_last, -k) for k in range(7, -1, -1)]              # 8 quarters (YoY base for the window)

    y, qn = qsplit(q_last)
    ytd = "%dM%d" % (3 * qn, y) if qn < 4 else "FY%d" % y
    ytd_py = "%dM%d" % (3 * qn, y - 1) if qn < 4 else "FY%d" % (y - 1)
    for p in (ytd, ytd_py):
        lines[p] = period_lines(fx, p, ann=4 / qn, oo_pre=oo_pre, ecl_line=ecl_line, oo_sga=oo_sga)
        # fill YTD flows the filing did not state from the quarters (e.g. derived Q4 of a Q4 YTD)
        yy = int(p[-4:])
        qq = ["%dQ%d" % (yy, k) for k in range(1, qn + 1)]
        for k in FLOW_LINES:
            if lines[p].get(k) is None and all(lines.get(q, {}).get(k) is not None for q in qq):
                lines[p][k] = sum(lines[q][k] for q in qq)
        L = lines[p]
        if L.get("gp") is not None and L.get("rev"):
            L["gpm"] = L["gp"] / L["rev"]

    # TTM (sum of 4 quarters) for flows
    def ttm(end):
        qq = [qadd(end, -k) for k in range(4)]
        if not all(q in lines for q in qq):
            return None
        out = {}
        for k in FLOW_LINES:
            vals = [lines[q].get(k) for q in qq]
            out[k] = sum(vals) if all(v is not None for v in vals) else None
        for k in ("cash_total", "net_cash", "recv", "equity", "debt_lease"):
            out[k] = lines[end].get(k)
        r = out.get("rev")
        out["gpm"] = out["gp"] / r if out.get("gp") is not None and r else None
        out["sga_pct"] = out["sga"] / r if out.get("sga") is not None and r else None
        out["npm"] = None
        out["dso"] = out["recv"] / r * 365 if out.get("recv") is not None and r else None
        return out
    ttm_now, ttm_py = ttm(q_last), ttm(qadd(q_last, -4))

    has_sso = asm.get("has_sso", cat == 2)

    # ---------------------------------------------------------------- headline table
    def g(q, k):
        return lines.get(q, {}).get(k)
    q_pq, q_py = qadd(q_last, -1), qadd(q_last, -4)
    headline = []
    for k, lab in LINE_DEFS:
        cur, pq, py = g(q_last, k), g(q_pq, k), g(q_py, k)
        row = {"id": k, "label": lab, "cur": cur, "pq": pq, "py": py, "is_pct": k in PCT_LINES}
        if k in PCT_LINES or k == "dso":
            row["yoy_pt"] = (cur - py) if cur is not None and py is not None else None
            row["qoq_pt"] = (cur - pq) if cur is not None and pq is not None else None
        elif k in NO_PCT:
            row["yoy_abs"] = (cur - py) if cur is not None and py is not None else None
            row["qoq_abs"] = (cur - pq) if cur is not None and pq is not None else None
        else:
            row["yoy"] = pct(cur, py)
            row["qoq"] = pct(cur, pq)
            row["tier"] = tier(row["yoy"])
        headline.append(row)

    # ---------------------------------------------------------------- mix
    periods = mda.get("periods") or {}

    def mixval(per, key):
        src = mix["quarterly"] if "Q" in per else mix["annual"]
        if per in src and src[per].get(key) is not None:
            return src[per][key]
        return None

    def natval(per, key):
        nq = (asm.get("nationality_mix") or mda.get("nationality") or {})
        src = nq.get("quarterly" if "Q" in per else "annual") or {}
        return (src.get(per) or {}).get(key)

    mix_rows = []
    mix_keys = [("opd", "ผู้ป่วยนอก (OPD)"), ("ipd", "ผู้ป่วยใน (IPD)"),
                ("cash", "ผู้ป่วยทั่วไป/คู่สัญญา (MD&A ไม่แยก OPD/IPD)")]
    if has_sso:
        mix_keys += [("sso", "ประกันสังคม (SSO)"), ("gov", "โครงการรัฐอื่น (บัตรทอง/สปสช./ข้าราชการ)")]
    mix_keys += [("misc", "บริการอื่น (ตรวจสุขภาพเคลื่อนที่/ฉายแสง)"), ("elim", "หักรายการระหว่างกัน")]
    mix_cols = ext
    for k, lab in mix_keys:
        vals = {q: mixval(q, k) for q in mix_cols}
        if k in ("elim", "cash", "gov", "misc", "opd", "ipd") and not any(vals.values()):
            continue
        mix_rows.append({"id": k, "label": lab, "vals": vals})
    nat_rows = []
    for k, lab in (("thai", "ผู้ป่วยชาวไทย"), ("foreign", "ผู้ป่วยต่างชาติ")):
        vals = {q: natval(q, k) for q in mix_cols}
        if any(v is not None for v in vals.values()):
            nat_rows.append({"id": k, "label": lab, "vals": vals})
    mix_recon = {q: (mda.get("recon") or {}).get(q, {}).get("status", {}) for q in mix_cols}
    # SSO revenue = Q (insured persons, hospitals.json `sso`) x P (revenue per insured person)
    sso_pxq = None
    if has_sso:
        import sso_pxq as SP
        def _gpm_fy(fy):
            try:
                return period_lines(fx, fy, ann=1.0, oo_pre=oo_pre, ecl_line=ecl_line, oo_sga=oo_sga).get("gpm")
            except Exception:
                return None
        sso_pxq = SP.build(sdir, ticker, mixval, ytd, ytd_py,
                           gpm={"FY%d" % y: _gpm_fy("FY%d" % y) for y in range(int(q_last[:4]) - 6, int(q_last[:4]) + 1)})
    # records (highest in the available history)
    records = []
    for k in (["sso"] if has_sso else []) + ["opd", "ipd", "foreign"]:
        hist = {}
        for q in qs_all:
            v = mixval(q, k) if k != "foreign" else natval(q, k)
            if v:
                hist[q] = v
        if q_last in hist and len(hist) >= 6 and hist[q_last] >= max(hist.values()) - 1e-9:
            first = min(hist)
            records.append({"id": k, "value": hist[q_last], "since": first, "n": len(hist),
                            "text": "%s %.2f ลบ. สูงสุดในข้อมูลที่มี %d ไตรมาส (ตั้งแต่ %s)" % (dict(mix_keys + [("foreign", "ผู้ป่วยต่างชาติ")]).get(k, k), hist[q_last], len(hist), be(first))})
    for k in ("rev", "gp", "gpm", "core_np"):
        hist = {q: g(q, k) for q in qs_all if g(q, k) is not None}
        if q_last in hist and len(hist) >= 6 and hist[q_last] >= max(hist.values()) - 1e-9:
            records.append({"id": k, "value": hist[q_last], "since": min(hist), "n": len(hist),
                            "text": ("%s %.1f%% สูงสุดในข้อมูลที่มี %d ไตรมาส (ตั้งแต่ %s)" % (dict(LINE_DEFS)[k], hist[q_last] * 100, len(hist), be(min(hist))))
                            if k in PCT_LINES else
                            ("%s %.2f ลบ. สูงสุดในข้อมูลที่มี %d ไตรมาส (ตั้งแต่ %s)" % (dict(LINE_DEFS)[k], hist[q_last], len(hist), be(min(hist))))})

    for k in ("selling", "sg_pct", "sa_pct", "sga_pct", "sga_x"):
        hist = {q: g(q, k) for q in qs_all if g(q, k) is not None and g(q, k) > 0}
        if q_last in hist and len(hist) >= 6 and hist[q_last] <= min(hist.values()) + 1e-9:
            val = ("%.1f%%" % (hist[q_last] * 100)) if k in PCT_LINES else ("%.2f ลบ." % hist[q_last])
            prev_low = min(v for q, v in hist.items() if q != q_last)
            records.append({"id": k, "kind": "low", "value": hist[q_last], "since": min(hist), "n": len(hist), "prev_low": prev_low,
                            "text": "%s %s ต่ำสุดในข้อมูลที่มี %d ไตรมาส (ตั้งแต่ %s; ต่ำสุดเดิม %s)" % (
                                dict(LINE_DEFS)[k], val, len(hist), be(min(hist)),
                                ("%.1f%%" % (prev_low * 100)) if k in PCT_LINES else "%.2f" % prev_low)})

    # ---------------------------------------------------------------- operating leverage
    def incr(q, base):
        r1, r0, g1, g0 = g(q, "rev"), g(base, "rev"), g(q, "gp"), g(base, "gp")
        if None in (r1, r0, g1, g0):
            return None
        dr, dg = r1 - r0, g1 - g0
        out = {"d_rev": dr, "d_gp": dg, "base": base, "gpm_avg": g1 / r1 if r1 else None,
               "d_cogs": g(q, "cogs") - g(base, "cogs"), "d_da": (g(q, "da") - g(base, "da")) if g(q, "da") is not None and g(base, "da") is not None else None}
        if abs(dr) < 0.01 * r0:
            out.update({"igpm": None, "class": "insignificant",
                        "text": "รายได้เปลี่ยนน้อยกว่า 1%% (%.2f ลบ.) จึงไม่ใช้ Incremental GPM ตีความ" % dr})
            return out
        ig = dg / dr
        out["igpm"] = ig
        if dr > 0:
            if dg < 0:
                c, t = "negative", "Negative operating leverage: รายได้เพิ่ม %.2f ลบ. แต่กำไรขั้นต้นลดลง %.2f ลบ. ต้องหาสาเหตุ (ค่าเสื่อม/อัตราครองเตียง/ส่วนผสมผู้ป่วย)" % (dr, -dg)
            elif ig > 0.40:
                c, t = "strong", "Operating leverage แข็งแรง: กำไรขั้นต้นส่วนเพิ่ม %.1f%% ของรายได้ส่วนเพิ่ม (สูงกว่า GPM เฉลี่ย %.1f%%)" % (ig * 100, out["gpm_avg"] * 100)
            elif ig >= 0.20:
                c, t = "normal", "Incremental GPM %.1f%% อยู่ในช่วงปกติของโรงพยาบาล (20–40%%)" % (ig * 100)
            elif ig >= 0.15:
                c, t = "moderate", "Incremental GPM %.1f%% ค่อนข้างต่ำ รายได้ส่วนเพิ่มมีต้นทุนผันแปรสูง" % (ig * 100)
            else:
                c, t = "low", ("Incremental GPM ต่ำ (%.1f%%): ห้ามสรุปว่ามี Operating Leverage สูง — สะท้อนต้นทุนผันแปร"
                               "หรือต้นทุนคงที่ของบริการ/สาขาใหม่ที่ยัง Ramp-up" % (ig * 100))
        else:
            if dg >= 0:
                c, t = "resilient", "รายได้ลดลง %.2f ลบ. แต่กำไรขั้นต้นไม่ลด (+%.2f) — คุมต้นทุนได้ดีหรือส่วนผสมผู้ป่วยดีขึ้น" % (-dr, dg)
            else:
                c, t = "decremental", "รายได้ลดลง %.2f ลบ. กำไรขั้นต้นลดลง %.2f ลบ. (Decremental margin %.1f%% — ต้นทุนคงที่ลดตามไม่ทัน)" % (-dr, -dg, ig * 100)
        out.update({"class": c, "text": t})
        if out["d_da"] is not None and out["d_cogs"]:
            out["da_share_of_dcogs"] = out["d_da"] / out["d_cogs"] if abs(out["d_cogs"]) > 0.01 else None
        return out
    oplev = {"yoy": incr(q_last, q_py), "qoq": incr(q_last, q_pq)}
    if oplev["qoq"]:
        mg, ng = None, 0
        vals = [g(q, "gpm") - g(qadd(q, -1), "gpm") for q in qs_all
                if q != q_last and qsplit(q)[1] == qsplit(q_last)[1] and qadd(q, -1) in lines
                and g(q, "gpm") is not None and g(qadd(q, -1), "gpm") is not None]
        if len(vals) >= 2:
            mg, ng = statistics.median(vals), len(vals)
            d_now = g(q_last, "gpm") - g(q_pq, "gpm")
            oplev["qoq"]["seasonal_gpm_pt"] = mg
            oplev["qoq"]["text"] += " | GPM QoQ %+.2f pt เทียบฤดูกาลปกติของไตรมาสนี้ %+.2f pt (%d ปี)%s" % (
                d_now * 100, mg * 100, ng, " — อยู่ในรูปแบบฤดูกาล" if d_now >= mg - 0.005 else " — แย่กว่าฤดูกาลปกติ")
    oplev["history"] = {q: (incr(q, qadd(q, -4)) or {}).get("igpm") for q in window}

    # ---------------------------------------------------------------- SG&A discipline
    def sga_view(q, base):
        r1, r0, s1, s0 = g(q, "rev"), g(base, "rev"), g(q, "sga"), g(base, "sga")
        if None in (r1, r0, s1, s0):
            return None
        rg, sg = pct(r1, r0), pct(s1, s0)
        p1, p0 = s1 / r1, s0 / r0
        if rg < 0 and p1 > p0:
            c, t = "rigid", ("Cost rigidity: รายได้ลดลง %.1f%% แต่ SG&A/รายได้เพิ่มจาก %.1f%% เป็น %.1f%% — ห้ามเรียกว่าคุมค่าใช้จ่ายมีวินัย"
                             % (rg * 100, p0 * 100, p1 * 100))
        elif sg is not None and sg < rg:
            c, t = "discipline", "SG&A โต %.1f%% ช้ากว่ารายได้ (%.1f%%) — สัดส่วนต่อรายได้ลดจาก %.1f%% เป็น %.1f%%" % (sg * 100, rg * 100, p0 * 100, p1 * 100)
        else:
            c, t = "rising", "SG&A โต %.1f%% เร็วกว่ารายได้ (%.1f%%) — สัดส่วนต่อรายได้เพิ่มจาก %.1f%% เป็น %.1f%%" % (sg * 100, rg * 100, p0 * 100, p1 * 100)
        return {"rev_g": rg, "sga_g": sg, "pct0": p0, "pct1": p1, "class": c, "text": t}
    def seasonal_qoq(k, pt=False):
        """This quarter's usual QoQ move of line k (median of the same quarter-of-year in earlier years)."""
        vals = []
        for q in qs_all:
            if q != q_last and qsplit(q)[1] == qsplit(q_last)[1] and qadd(q, -1) in lines:
                a, b = g(q, k), g(qadd(q, -1), k)
                if a is not None and b is not None:
                    v = (a - b) if pt else pct(a, b)
                    if v is not None:
                        vals.append(v)
        return (statistics.median(vals), len(vals)) if vals else (None, 0)

    sga_qoq = sga_view(q_last, q_pq)
    if sga_qoq:
        # v3: Q4 admin (bonus, year-end provisions) and Q1 revenue dips are seasonal — judge QoQ against the usual move
        med_s, n_s = seasonal_qoq("sga_x")
        med_r, _ = seasonal_qoq("rev")
        cur_s = pct(g(q_last, "sga_x"), g(q_pq, "sga_x"))
        if med_s is not None and cur_s is not None and n_s >= 2:
            sga_qoq["seasonal_median"] = med_s
            sga_qoq["seasonal_n"] = n_s
            if cur_s <= med_s + 0.03:
                sga_qoq["class"] = "seasonal"
                sga_qoq["text"] = ("QoQ ตามฤดูกาล: SG&A ก่อน ECL/รายการพิเศษ %+.1f%% เทียบค่ามัธยฐานของไตรมาสเดียวกันในอดีต %+.1f%% (%d ปี); "
                                   "รายได้ %+.1f%% (ปกติ %+.1f%%) — ไม่ใช่ cost rigidity ให้อ่าน YoY เป็นหลัก"
                                   % (cur_s * 100, med_s * 100, n_s, (sga_qoq["rev_g"] or 0) * 100, (med_r or 0) * 100))
            else:
                sga_qoq["text"] += " | SG&A ก่อน ECL/รายการพิเศษ %+.1f%% สูงกว่าฤดูกาลปกติ %+.1f%% (%d ปี)" % (cur_s * 100, med_s * 100, n_s)
    selling_reported = any((g(q, "selling") or 0) > 0 for q in window)
    sga = {"yoy": sga_view(q_last, q_py), "qoq": sga_qoq, "selling_reported": selling_reported,
           "selling_note": None if selling_reported else
           "งบไม่ได้แยกค่าใช้จ่ายในการขาย (รวมอยู่ในค่าใช้จ่ายบริหาร) — Admin = SG&A ทั้งหมด ไม่ใช่ผลของการลดค่าการตลาด"}
    def sga_x_view(q, base):
        r1, r0, s1, s0 = g(q, "rev"), g(base, "rev"), g(q, "sga_x"), g(base, "sga_x")
        if None in (r1, r0, s1, s0):
            return None
        rg, sg = pct(r1, r0), pct(s1, s0)
        if sg is None:
            return None
        word = "ช้ากว่า" if sg < rg else "เร็วกว่า"
        return {"rev_g": rg, "sga_g": sg, "pct0": s0 / r0, "pct1": s1 / r1,
                "text": "SG&A ก่อน ECL %s → %s ลบ. (%+.1f%%) %sรายได้ (%+.1f%%)" % (f2(s0), f2(s1), sg * 100, word, rg * 100)}

    def split_view(q, base):
        """Selling and admin moving in opposite directions: real saving or reclassification?"""
        sl1, sl0, ad1, ad0 = g(q, "selling"), g(base, "selling"), g(q, "admin"), g(base, "admin")
        if None in (sl1, sl0, ad1, ad0) or not sl0 or not ad0:
            return None
        sg, ag = pct(sl1, sl0), pct(ad1, ad0)
        if sg is None or ag is None or sg * ag >= 0 or max(abs(sg), abs(ag)) <= 0.10:
            return None
        rg = pct(g(q, "rev"), g(base, "rev")) or 0.0
        ax1, ax0 = g(q, "admin_x"), g(base, "admin_x")
        axg = pct(ax1, ax0) if None not in (ax1, ax0) else None
        d_sel, d_ax = sl1 - sl0, ((ax1 - ax0) if axg is not None else None)
        oo_note = ""
        if abs(g(q, "oo_pre") or 0) > 0.01 or abs(g(base, "oo_pre") or 0) > 0.01:
            oo_note = " (รายการพิเศษก่อนภาษี %s %+.2f / %s %+.2f ลบ.; ส่วนที่ระบุ line admin/selling ถูกปรับออกแล้ว)" % (
                be(q), g(q, "oo_pre") or 0, be(base), g(base, "oo_pre") or 0)
        out = {"sell_g": sg, "admin_g": ag, "admin_x_g": axg, "rev_g": rg, "d_sell": d_sel, "d_admin_x": d_ax,
               "d_ecl": (g(q, "ecl") or 0) - (g(base, "ecl") or 0)}
        if axg is None:
            out.update({"class": "unknown", "text": "ขายกับบริหารสวนทางกัน แต่ไม่มี ECL ให้แยกดู — ต้องอ่าน MD&A/หมายเหตุก่อนสรุป"})
        elif axg <= rg + 0.03 and d_sel < 0:
            out.update({"class": "genuine_saving",
                        "text": "ค่าใช้จ่ายขาย %+.1f%% เป็นการลดจริง: ค่าใช้จ่ายบริหารก่อน ECL และรายการพิเศษ %+.1f%% (รายได้ %+.1f%%); "
                                "ส่วนต่างกับค่าใช้จ่ายบริหารตามงบ (%+.1f%%) มาจาก ECL (Δ%+.2f ลบ.) และรายการพิเศษในงวดใดงวดหนึ่ง"
                                % (sg * 100, axg * 100, rg * 100, ag * 100, out["d_ecl"])})
        elif d_sel < 0 < d_ax and abs(d_ax + d_sel) <= 0.3 * abs(d_sel):
            out.update({"class": "reclass",
                        "text": "สงสัยการจัดประเภทใหม่: ค่าใช้จ่ายขายลด %.2f ลบ. ขณะบริหารก่อน ECL เพิ่ม %.2f ลบ. ใกล้เคียงกัน (MD&A ต้องยืนยัน)" % (-d_sel, d_ax)})
        else:
            out.update({"class": "mixed",
                        "text": "ค่าใช้จ่ายขาย %+.1f%%, บริหาร %+.1f%% (ก่อน ECL %+.1f%%) — ไม่ใช่การย้ายบรรทัดล้วน ต้องหาสาเหตุฝั่งบริหาร" % (sg * 100, ag * 100, axg * 100)})
        out["text"] += oo_note
        return out
    sga["yoy_x"], sga["qoq_x"] = sga_x_view(q_last, q_py), sga_x_view(q_last, q_pq)
    long_q = [q for q in qs_all if q > qadd(q_last, -12)]
    lv = [(q, g(q, "admin_x"), g(q, "rev")) for q in long_q if g(q, "admin_x") is not None and g(q, "rev")]
    if len(lv) >= 8:
        a_vals = [a for _, a, _ in lv]
        r0 = statistics.mean(r for _, _, r in lv[:4])
        r1 = statistics.mean(r for _, _, r in lv[-4:])
        a0 = statistics.mean(a for _, a, _ in lv[:4])
        a1 = statistics.mean(a for _, a, _ in lv[-4:])
        sga["long_run"] = {"n": len(lv), "from": lv[0][0], "to": lv[-1][0], "admin_min": min(a_vals), "admin_max": max(a_vals),
                           "admin_median": statistics.median(a_vals), "rev_g": pct(r1, r0), "admin_g": pct(a1, a0),
                           "text": "%d ไตรมาส (%s–%s): ค่าใช้จ่ายบริหารก่อน ECL/รายการพิเศษ อยู่ในช่วง %.1f–%.1f ลบ. (มัธยฐาน %.1f); "
                                   "เฉลี่ย 4 ไตรมาสล่าสุดเทียบ 4 ไตรมาสแรก: บริหาร %+.1f%% ขณะรายได้ %+.1f%%"
                                   % (len(lv), be(lv[0][0]), be(lv[-1][0]), min(a_vals), max(a_vals), statistics.median(a_vals),
                                      (pct(a1, a0) or 0) * 100, (pct(r1, r0) or 0) * 100)}
    sga["split_yoy"], sga["split_qoq"] = split_view(q_last, q_py), split_view(q_last, q_pq)
    sga["ecl_line"] = ecl_line
    ecl_rows = {q: {"ecl": g(q, "ecl"), "admin": g(q, "admin"), "ecl_pct": g(q, "ecl_pct")} for q in ext}

    # ---------------------------------------------------------------- interim notes (receivables/ECL, nature proxies, mgmt pay)
    notes = FN.read_notes(sdir, q_last) if FN else {"found": False}
    ecl_attrib = ecl_attribution(notes, q_last, lines.get(ytd, {}).get("ecl"))

    # ---------------------------------------------------------------- profit bridge
    def bridge(q, base):
        need = ["rev", "gpm", "oth", "sga", "fin_net", "tax", "np_owners"]
        if any(g(q, k) is None or g(base, k) is None for k in need):
            return None
        vol = (g(q, "rev") - g(base, "rev")) * g(base, "gpm")
        mar = g(q, "rev") * (g(q, "gpm") - g(base, "gpm"))
        items = [("ปริมาณ/รายได้ (Volume: ΔRev × GPM เดิม)", vol),
                 ("อัตรากำไรขั้นต้น (Margin: Rev × ΔGPM)", mar),
                 ("รายได้อื่น + เงินปันผลรับ", g(q, "oth") - g(base, "oth")),
                 ("SG&A (เพิ่ม = ลบ)", -(g(q, "sga") - g(base, "sga"))),
                 ("การเงินสุทธิ + ส่วนแบ่งกำไร", g(q, "fin_net") - g(base, "fin_net")),
                 ("ภาษี (เพิ่ม = ลบ)", -(g(q, "tax") - g(base, "tax"))),
                 ("ส่วนได้เสียที่ไม่มีอำนาจควบคุม", -((g(q, "nci") or 0) - (g(base, "nci") or 0)))]
        total = g(q, "np_owners") - g(base, "np_owners")
        resid = total - sum(v for _, v in items)
        if abs(resid) > 0.05:
            items.append(("อื่นๆ/ปัดเศษ (Residual)", resid))
        return {"base": base, "np0": g(base, "np_owners"), "np1": g(q, "np_owners"), "items": items, "total": total,
                "closes": abs(total - sum(v for _, v in items)) < 0.01}
    bridges = {"yoy": bridge(q_last, q_py), "qoq": bridge(q_last, q_pq)}

    # ---------------------------------------------------------------- YTD / TTM
    ytd_rows = []
    for k in ("rev", "gp", "gpm", "sga", "sga_x", "core_pbt", "core_pbt_x", "ebit", "np_owners", "core_np", "da", "ebitda", "cfo", "capex", "fcf"):
        a, b = lines[ytd].get(k), lines[ytd_py].get(k)
        r = {"id": k, "label": dict(LINE_DEFS)[k], "cur": a, "py": b, "is_pct": k in PCT_LINES}
        if k in PCT_LINES:
            r["yoy_pt"] = (a - b) if a is not None and b is not None else None
        else:
            r["yoy"] = pct(a, b)
        ytd_rows.append(r)

    # ---------------------------------------------------------------- seasonality (statistical, from history)
    hist_q = [q for q in qs_all if g(q, "rev") is not None]
    season = []
    growth_basis = None
    yt = pct(lines[ytd].get("rev"), lines[ytd_py].get("rev"))
    tt = pct(ttm_now["rev"], ttm_py["rev"]) if ttm_now and ttm_py else None
    growth_basis = yt if yt is not None else tt
    np_basis = pct(lines[ytd].get("core_np"), lines[ytd_py].get("core_np"))
    for k in range(1, 5):
        f = qadd(q_last, k)
        fq = qsplit(f)[1]
        qoq_hist, np_qoq_hist = [], []
        for q in hist_q:
            if qsplit(q)[1] == fq and qadd(q, -1) in lines:
                c = pct(g(q, "rev"), g(qadd(q, -1), "rev"))
                if c is not None:
                    qoq_hist.append((q, c))
                c2 = pct(g(q, "core_np"), g(qadd(q, -1), "core_np"))
                if c2 is not None and g(qadd(q, -1), "core_np") and g(qadd(q, -1), "core_np") > 0:
                    np_qoq_hist.append((q, c2))
        base = qadd(f, -4)
        rv = g(base, "rev")
        proj = rv * (1 + growth_basis) if rv is not None and growth_basis is not None else None
        cnp = g(base, "core_np")
        proj_np = cnp * (1 + np_basis) if cnp is not None and np_basis is not None and cnp > 0 else None
        season.append({"q": f, "same_q_last_year": base, "rev_base": rv, "core_np_base": cnp,
                       "rev_proj": proj, "core_np_proj": proj_np,
                       "qoq_hist": qoq_hist[-4:], "qoq_median": statistics.median([c for _, c in qoq_hist[-4:]]) if qoq_hist else None,
                       "np_qoq_hist": np_qoq_hist[-4:],
                       "np_qoq_median": statistics.median([c for _, c in np_qoq_hist[-4:]]) if np_qoq_hist else None})
    season_meta = {"rev_growth_basis": growth_basis, "rev_growth_basis_label": ("YTD %s vs %s" % (be(ytd), be(ytd_py))) if yt is not None else "TTM YoY",
                   "np_growth_basis": np_basis,
                   "method": "ฐาน = ไตรมาสเดียวกันของปีก่อน × (1 + อัตราเติบโต YTD ล่าสุด); รูปแบบ QoQ = ค่ามัธยฐานของไตรมาสเดียวกันในอดีต"}

    # ---------------------------------------------------------------- momentum score (transparent)
    comp = []

    def add(name, pts, why, value=None):
        comp.append({"name": name, "points": pts, "why": why, "value": value})
    rv_y = pct(g(q_last, "rev"), g(q_py, "rev"))
    if rv_y is not None:
        add("รายได้ YoY", 1.5 if rv_y > 0.10 else 1.0 if rv_y > 0.04 else 0.5 if rv_y >= 0 else -1.0, "%+.1f%%" % (rv_y * 100))
    gp_y = pct(g(q_last, "gp"), g(q_py, "gp"))
    if gp_y is not None and rv_y is not None:
        d_gpm = (g(q_last, "gpm") - g(q_py, "gpm")) * 100
        add("อัตรากำไรขั้นต้น YoY", 1.0 if d_gpm > 0.5 else (-1.5 if d_gpm < -1.0 else (-0.5 if d_gpm < -0.5 else 0.0)), "GPM %+.2f pt" % d_gpm)
    cn_y = pct(g(q_last, "core_np"), g(q_py, "core_np"))
    if cn_y is not None:
        add("กำไรปกติ YoY", 1.5 if cn_y > 0.10 else 0.5 if cn_y >= 0 else (-0.5 if cn_y > -0.10 else -1.5), "%+.1f%%" % (cn_y * 100))
    s = next((x for x in season if False), None)
    hist_same = [pct(g(q, "core_np"), g(qadd(q, -1), "core_np")) for q in hist_q
                 if qsplit(q)[1] == qn and q != q_last and qadd(q, -1) in lines and (g(qadd(q, -1), "core_np") or 0) > 0]
    hist_same = [x for x in hist_same if x is not None]
    cn_q = pct(g(q_last, "core_np"), g(q_pq, "core_np"))
    if cn_q is not None and hist_same:
        med = statistics.median(hist_same)
        add("กำไรปกติ QoQ เทียบฤดูกาลปกติ", 0.5 if cn_q >= med else -0.5, "QoQ %+.1f%% vs ค่ามัธยฐาน %s ในอดีต %+.1f%%" % (cn_q * 100, "Q%d" % qn, med * 100))
    if ttm_now and ttm_now.get("cfo") is not None and ttm_now.get("ebitda"):
        cc = ttm_now["cfo"] / ttm_now["ebitda"]
        add("CFO/EBITDA (TTM)", 0.5 if cc >= 0.8 else (-0.5 if cc < 0.6 else 0.0), "%.2f เท่า" % cc, round(cc, 2))
    d_dso = (g(q_last, "dso") - g(q_py, "dso")) if g(q_last, "dso") is not None and g(q_py, "dso") is not None else None
    if d_dso is not None:
        add("DSO YoY", -0.5 if d_dso > 10 else (0.5 if d_dso < -10 else 0.0), "%+.1f วัน" % d_dso)
    score = max(0.0, min(10.0, 5.0 + sum(c["points"] for c in comp)))
    label = ("Strong" if score >= 7.5 else "Positive" if score >= 6 else "Neutral" if score >= 4.5 else "Weak" if score >= 3 else "Negative")

    # ---------------------------------------------------------------- red flags (>10% YoY on key lines need a sourced explanation)
    flags = []
    e1, e0 = g(q_last, "ecl"), g(q_py, "ecl")
    if e1 is not None and e0 is not None and abs(e1 - e0) >= max(2.0, 0.003 * (g(q_last, "rev") or 0)):
        flags.append({"id": "ecl_change", "line": "ECL", "change": None, "cur": e1, "py": e0,
                      "text": "ECL %s %.2f ลบ. เทียบ %.2f ลบ. ใน %s (Δ%+.2f ลบ.)" % (be(q_last), e1, e0, be(q_py), e1 - e0)})
    for k in ("rev", "gp", "sga", "admin", "selling", "core_pbt", "ebit", "np_owners", "core_np", "da", "recv", "cash_total", "oth"):
        c = pct(g(q_last, k), g(q_py, k))
        if k == "oth" and abs((g(q_last, k) or 0) - (g(q_py, k) or 0)) < max(3.0, 0.03 * abs(g(q_last, "core_pbt") or 0)):
            continue          # v3: other income is outside core analysis; flag it only when material
        if c is not None and abs(c) > 0.10 and abs((g(q_last, k) or 0) - (g(q_py, k) or 0)) >= 1.0:
            flags.append({"id": "yoy_%s" % k, "line": dict(LINE_DEFS)[k], "change": c, "cur": g(q_last, k), "py": g(q_py, k),
                          "text": "%s %s %+.1f%% YoY (%.2f → %.2f ลบ.)" % (dict(LINE_DEFS)[k], be(q_last), c * 100, g(q_py, k), g(q_last, k))})
    for m in mix_rows + nat_rows:
        a, b = m["vals"].get(q_last), m["vals"].get(q_py)
        c = pct(a, b)
        if c is not None and abs(c) > 0.10 and m["id"] != "elim":
            flags.append({"id": "yoy_mix_%s" % m["id"], "line": m["label"], "change": c, "cur": a, "py": b,
                          "text": "%s %s %+.1f%% YoY (%.2f → %.2f ลบ.)" % (m["label"], be(q_last), c * 100, b, a)})
    ops = ops_view(sdir, ticker, q_last, q_py, ext)
    if ops:
        flags += ops.pop("flags")
    # facts from the statements that help (they are not explanations: the narrative still needs a document source)
    for fl in flags:
        if fl["id"] == "ecl_change" and ecl_attrib:
            fl["hint"] = ecl_attrib["text"]
        if fl["id"] in ("yoy_admin", "yoy_selling") and sga.get("split_yoy"):
            fl["hint"] = sga["split_yoy"]["text"]
        if fl["id"] in ("yoy_admin", "yoy_selling"):
            # v3 (Pop): judge a cost line by its % of revenue against its own recent band, not only YoY
            kp = "sa_pct" if fl["id"] == "yoy_admin" else "sg_pct"
            band = [g(q, kp) for q in qs_all if q < q_last and q > qadd(q_last, -13) and g(q, kp) is not None]
            cur_p = g(q_last, kp)
            if len(band) >= 6 and cur_p is not None:
                lo, hi = min(band), max(band)
                where = "อยู่ในกรอบ" if lo - 0.00005 <= cur_p <= hi + 0.00005 else ("ต่ำกว่ากรอบ" if cur_p < lo else "สูงกว่ากรอบ")
                txt = "%s %.2f%% ของรายได้ %s %d ไตรมาสก่อนหน้า (%.2f–%.2f%%)" % (dict(LINE_DEFS)[kp].split(" (")[0], cur_p * 100, where, len(band), lo * 100, hi * 100)
                fl["band"] = {"lo": lo, "hi": hi, "cur": cur_p, "where": where}
                fl["hint"] = (fl.get("hint", "") + " | " if fl.get("hint") else "") + txt
        if fl["id"] == "yoy_recv" and ecl_attrib and ecl_attrib.get("aging_text"):
            fl["hint"] = ecl_attrib["aging_text"]
    if oplev["yoy"] and oplev["yoy"].get("class") == "negative":
        flags.append({"id": "neg_oplev", "line": "Incremental GPM", "change": None, "text": oplev["yoy"]["text"]})
    if sga["yoy"] and sga["yoy"]["class"] == "rigid":
        flags.append({"id": "cost_rigidity", "line": "SG&A", "change": None, "text": sga["yoy"]["text"]})

    # ---------------------------------------------------------------- integrity checks + gaps
    checks = []
    a, l_, e = g(q_last, "assets"), g(q_last, "liab"), g(q_last, "tot_equity")
    if None not in (a, l_, e):
        checks.append(("สมการงบดุล A = L + E (%s, ส่วนของผู้ถือหุ้นตามงบ)" % be(q_last), abs(a - l_ - e) < 0.5, "%.2f" % (a - l_ - e)))
    for q in ext:
        st = mix_recon.get(q) or {}
        if st:
            ok = all(v in ("PASS", "NO_REPORTED") for v in st.values())
            checks.append(("โครงสร้างรายได้ MD&A = รายได้ในงบ ±1 ลบ. (%s)" % be(q), ok, ",".join("%s:%s" % kv for kv in st.items())))
    for key in ("yoy", "qoq"):
        b = bridges[key]
        if b:
            checks.append(("สะพานกำไร %s ปิดยอด" % key.upper(), b["closes"], "%.2f" % b["total"]))
    # quarters derived from cumulative statements must be YTD(this year) − YTD(earlier, SAME year)
    bad = []
    for q in window:
        for k in ("cf_da", "cf_ecl", "cfo", "capex_ppe", "div_paid"):
            sname = str(fx.src.get("%s|%s" % (k, q)) or "")
            m = re.search(r"derived\s*=\s*(\d+)M(\d{4})\s*-\s*(\d+)M(\d{4})", sname)
            if m and not (m.group(2) == m.group(4) == q[:4] and int(m.group(1)) - int(m.group(3)) == 3 and int(m.group(1)) == 3 * qsplit(q)[1]):
                bad.append("%s %s (%s)" % (k, be(q), sname))
    for k in ("ecl", "da", "cfo"):
        qq = ["%dQ%d" % (y, j) for j in range(1, qn + 1)]
        if qn > 1 and lines[ytd].get(k) is not None and all(g(x, k) is not None for x in qq):
            diff = sum(g(x, k) for x in qq) - lines[ytd][k]
            if abs(diff) > 0.05:
                bad.append("%s: ผลรวมไตรมาส %s ≠ %s (%.2f)" % (k, "+".join(be(x) for x in qq), be(ytd), diff))
    checks.append(("ไตรมาสที่คำนวณจากงบสะสม = YTD ปีนี้ − YTD ก่อนหน้าของปีเดียวกัน (ECL, D&A, CFO)", not bad, "; ".join(bad) or "ok"))
    gaps = []
    for q in ext:
        for k in ("rev", "gp", "sga", "np_owners", "da", "cash_total", "cfo"):
            if g(q, k) is None:
                gaps.append("%s: ไม่มี %s" % (be(q), dict(LINE_DEFS)[k]))
        if not any(m["vals"].get(q) is not None for m in mix_rows):
            gaps.append("%s: ไม่มีโครงสร้างรายได้ OPD/IPD จาก MD&A" % be(q))
    gaps += oo_gaps
    sso_seen = any((v or {}).get("sso") for v in (mix.get("quarterly") or {}).values())
    if sso_seen and cat != 2:
        gaps.append("MD&A มีรายได้ประกันสังคม (SSO) แต่ %s อยู่กลุ่ม %s ในตาราง taxonomy — ตรวจ category (hospital_taxonomy.md)" % (ticker, cat))
    elif cat == 2 and mix.get("quarterly") and not sso_seen:
        gaps.append("%s อยู่กลุ่ม 2 (SSO) แต่ MD&A ไม่มีบรรทัดรายได้ประกันสังคม — ตรวจ category (hospital_taxonomy.md)" % ticker)
    if not notes.get("found"):
        gaps.append("%s: ไม่พบงบการเงินระหว่างกาลฉบับเต็ม (หมายเหตุ) ใน md/raw — ไม่มีตารางอายุลูกหนี้/ค่าใช้จ่ายตามลักษณะ" % be(q_last))
    for fl in (mda.get("flags") or []):
        if fl.startswith("RESTATED") or fl.startswith("RECON FAIL"):
            per = fl.split()[2]
            if per in window:
                gaps.append("MD&A: " + fl)

    # ---------------------------------------------------------------- market
    mk = dict(asm.get("market") or {}) or set_factsheet_price(sdir, ticker)
    if mk.get("as_of"):
        # back-test guard: a price long after the quarter's release would mix today's valuation into an old report
        try:
            d_as = datetime.strptime(str(mk["as_of"])[:10], "%Y-%m-%d")
            d_end = datetime(y, 3 * qn, 28)
            if not -120 <= (d_as - d_end).days <= 150:
                gaps.append("ราคาหุ้นในไฟล์ factsheet (%s) ไม่ใช่ช่วงประกาศงบ %s — ไม่แสดง P/E, P/BV, yield" % (mk["as_of"], be(q_last)))
                mk = {"shares_mn": mk.get("shares_mn"),
                      "shares_note": "จำนวนหุ้น ณ %s (อาจต่างจากตอนประกาศงบ %s)" % (mk["as_of"], be(q_last))} if mk.get("shares_mn") else {}
        except ValueError:
            pass
    market = {}
    if mk.get("price"):
        sh = mk.get("shares_mn") or (g(q_last, "equity") and None)
        market = {"price": mk["price"], "as_of": mk.get("as_of"), "shares_mn": sh, "source": mk.get("source")}
        if sh and ttm_now and ttm_now.get("np_owners"):
            market["pe_ttm"] = mk["price"] * sh / ttm_now["np_owners"]
            if ttm_now.get("core_np"):
                market["pe_core_ttm"] = mk["price"] * sh / ttm_now["core_np"]
        if sh and g(q_last, "equity"):
            market["pbv"] = mk["price"] * sh / g(q_last, "equity")
        if sh and g(q_last, "net_cash") is not None:
            market["net_cash_ps"] = g(q_last, "net_cash") / sh
        if mk.get("dps_last_fy"):
            market["yield"] = mk["dps_last_fy"] / mk["price"]

    fy_py = "FY%d" % (y - 1)
    if fy_py not in lines:
        lines[fy_py] = period_lines(fx, fy_py, oo_pre=oo_pre, ecl_line=ecl_line, oo_sga=oo_sga)
    nature = nature_block(fx, notes, lines, ytd, ytd_py, ["FY%d" % (y - 2), fy_py])
    dividend = dividend_block(fx, lines, {**mk, **market}, notes, season, q_last, ytd, fy_py)
    if market and mk.get("shares_note"):
        market["shares_note"] = mk["shares_note"]

    # ---------------------------------------------------------------- expectation (price = valuation + narrative)
    angles = investor_angles(lines, qs_all, q_last, asm.get("one_offs") or [])
    angles.update(lead_indicators(lines, q_last, notes, fx, q_py))
    expect = {}
    np_ttm = ttm_now.get("core_np") if ttm_now else None
    np_ttm_py = ttm_py.get("core_np") if ttm_py else None
    if market.get("price") and market.get("shares_mn"):
        expect["valuation"] = valuation_view(market["price"], market["shares_mn"], np_ttm, np_ttm_py, mk.get("dps_last_fy"),
                                            market.get("net_cash_ps"))
    if _expect and qadd(q_last, -1) in quarters:
        try:
            import contextlib, io
            with contextlib.redirect_stdout(io.StringIO()):
                prev = build_pack(sdir, ticker, qadd(q_last, -1), quiet=True, _expect=False)
            sp = next((x for x in prev.get("season") or [] if x["q"] == q_last), None)
            if sp and sp.get("rev_proj") and sp.get("core_np_proj"):
                ar, an_ = g(q_last, "rev"), g(q_last, "core_np")
                expect["surprise"] = {"rev_proj": sp["rev_proj"], "np_proj": sp["core_np_proj"], "rev": ar, "np": an_,
                                      "rev_s": pct(ar, sp["rev_proj"]), "np_s": pct(an_, sp["core_np_proj"])}
        except Exception:
            pass
    ph = (angles or {}).get("phase") or {}
    tr = [float(re.search(r"([\d.]+) เท่า", x).group(1)) for x in ph.get("trail") or [] if re.search(r"([\d.]+) เท่า", x)]
    if len(tr) >= 3:
        expect["leverage_trend"] = "เร่งขึ้น" if tr[-1] > tr[0] * 1.15 else ("อ่อนลง" if tr[-1] < tr[0] * 0.85 else "ทรงตัว")
    root = peers_root(sdir)
    peers = peer_rows(root, ticker, cat, q_last, asm.get("peers")) if _expect else []
    ok = [r for r in peers if r.get("rev") is not None]
    if ok:
        def med(k):
            xs = [r[k] for r in ok if r.get(k) is not None]
            return statistics.median(xs) if len(xs) >= (3 if k in ("pe", "peg") else 1) else None   # no "median" of one or two P/Es
        expect["peer_median"] = {k: med(k) for k in ("rev_yoy", "gpm", "sga_pct", "pbt_yoy", "mult", "dso", "pe", "peg")}
    lines_out = []
    v = expect.get("valuation")
    if v:
        lines_out.append("มูลค่า: P/E กำไรปกติ TTM %.1f เท่า สำหรับกำไรปกติที่โต %s → PEG %s — %s" % (
            v["pe"], ("%+.1f%%" % (v["np_g"] * 100)) if v.get("np_g") is not None else "–", ("%.2f" % v["peg"]) if v.get("peg") else "–", v["label"]))
        if v.get("ex_cash_pe"):
            lines_out.append("มูลค่าไม่รวมเงินสด: ราคาหักเงินสดสุทธิ %.2f บาท/หุ้น (%.0f%% ของราคา) → P/E เฉพาะธุรกิจโรงพยาบาล %.1f เท่า" % (
                v["net_cash_ps"], v["net_cash_ps"] / market["price"] * 100, v["ex_cash_pe"]))
    su = expect.get("surprise")
    if su:
        tag = lambda x: "เหนือความคาดหมาย" if x > 0.03 else ("ต่ำกว่าความคาดหมาย" if x < -0.03 else "ตามคาด")
        lines_out.append("ความคาดหวัง vs ผลจริง: ค่าประมาณเชิงสถิติ ณ %s คาด %s รายได้ %.2f / กำไรปกติ %.2f ลบ.; จริง %.2f / %.2f ลบ. → รายได้ %s (%+.1f%%), กำไร %s (%+.1f%%)" % (
            be(qadd(q_last, -1)), be(q_last), su["rev_proj"], su["np_proj"], su["rev"] or 0, su["np"] or 0,
            tag(su["rev_s"] or 0), (su["rev_s"] or 0) * 100, tag(su["np_s"] or 0), (su["np_s"] or 0) * 100))
    if expect.get("leverage_trend"):
        lines_out.append("เรื่องเล่า (ช่วงธุรกิจ): %s — operating leverage %s (%s)%s" % (
            ph.get("phase") + ((" — " + ph["flag"]) if ph.get("flag") else ""), expect["leverage_trend"], ", ".join(ph.get("trail") or []),
            " → ถ้าอ่อนลงต่อเนื่องจะเข้าสู่ปลายช่วงเก็บเกี่ยว: ความคาดหวังลด เสี่ยง P/E ถูกปรับลด" if expect["leverage_trend"] == "อ่อนลง" else ""))
    pm = expect.get("peer_median")
    if pm:
        lines_out.append("เทียบกลุ่ม (มัธยฐาน %d บริษัท): รายได้ YoY %s, Core PBT YoY %s, กำไรโต/รายได้โต %s เท่า%s" % (
            len(ok), ("%+.1f%%" % (pm["rev_yoy"] * 100)) if pm.get("rev_yoy") is not None else "–",
            ("%+.1f%%" % (pm["pbt_yoy"] * 100)) if pm.get("pbt_yoy") is not None else "–",
            ("%.1f" % pm["mult"]) if pm.get("mult") is not None else "–",
            "".join([(", P/E %.1f เท่า (%d บริษัท)" % (pm["pe"], sum(1 for r in ok if r.get("pe")))) if pm.get("pe") else "",
                     (", PEG %.2f" % pm["peg"]) if pm.get("peg") else ""])))
    expect["lines"] = lines_out

    comp_name = asm.get("company") or {}
    pack = {
        "ticker": ticker, "generated": datetime.now().isoformat(timespec="seconds"),
        "company": {"name_th": comp_name.get("name_th"), "name_en": comp_name.get("name_en")},
        "category": cat, "category_name": CATEGORY_NAMES.get(cat, str(cat)), "has_sso": has_sso,
        "q_last": q_last, "q_last_be": be(q_last), "q_pq": q_pq, "q_py": q_py, "window": window, "ext": ext,
        "ytd": ytd, "ytd_py": ytd_py,
        "lines": {q: lines[q] for q in ext + [ytd, ytd_py, fy_py] if q in lines},
        "hist_rev": {q: g(q, "rev") for q in qs_all},
        "hist_core_np": {q: g(q, "core_np") for q in qs_all},
        "ttm": ttm_now, "ttm_py": ttm_py,
        "headline": headline, "mix_rows": mix_rows, "nat_rows": nat_rows, "mix_recon": mix_recon, "records": records, "sso_pxq": sso_pxq,
        "oplev": oplev, "sga": sga, "ecl_rows": ecl_rows, "ecl_attrib": ecl_attrib, "bridges": bridges, "ytd_rows": ytd_rows,
        "nature": nature, "dividend": dividend, "notes_file": notes.get("file"),
        "season": season, "season_meta": season_meta,
        "momentum": {"score": score, "label": label, "components": comp},
        "flags": flags, "checks": [{"label": c[0], "ok": c[1], "detail": c[2]} for c in checks], "gaps": gaps,
        "one_offs": [o for o in (asm.get("one_offs") or []) if o.get("period") in ext],
        "market": market,
        "sources": {"financials": fin_p, "mda": mda_p, "assumptions": asm_p if os.path.isfile(asm_p) else None,
                    "mix_source": asm2["revenue_mix"]["source"],
                    "fact_src": {k: v for k, v in fx.src.items() if k.split("|")[1] in ext + [ytd, ytd_py]}},
        "mda_docs": latest_mda_docs(sdir, q_last),
        "reading_pack": reading_pack(sdir, q_last),
        "analyst_notes": analyst_notes(sdir, q_last),
        "second_sources": second_sources(sdir),
        "third_sources": third_sources(sdir, q_last),
        "papers": papers(sdir, q_last),
        "angles": angles, "expect": expect, "peers": peers, "ops": ops,
    }
    return pack



OPS_ROWS = [("opd_visits", "ผู้ป่วยนอก (ครั้ง)", False), ("opd_utilization_pct", "อัตราการใช้บริการ OPD (%)", True),
            ("implied_opd_capacity_per_day", "กำลังรับ OPD ต่อวันที่ใช้คำนวณ (ครั้ง) [คำนวณ]", False),
            ("per_bill_opd_baht", "รายได้ต่อใบเสร็จ OPD (บาท)", False),
            ("ipd_days", "วันนอนผู้ป่วยใน (วัน)", False), ("occupancy_pct", "อัตราครองเตียง (%)", True),
            ("implied_beds", "ฐานเตียงที่ใช้คำนวณ (เตียง) [คำนวณ]", False),
            ("per_bill_ipd_baht", "รายได้ต่อใบเสร็จ IPD (บาท)", False)]


def ops_view(sdir, ticker, q_last, q_py, ext):
    """Volume, utilisation and revenue per bill from the Oppday slides (report/<T>_ops_metrics.json).
    Answers whether the quarter's revenue moved on volume or on price, and how full the hospital is."""
    f = os.path.join(sdir, "report", "%s_ops_metrics.json" % ticker)
    if not os.path.isfile(f):
        return None
    o = load_json(f)
    m = o.get("metrics") or {}
    dv = o.get("derived") or {}                      # capacity behind each rate: volume / (rate x days), computed
    rows = []
    for key, label, rate in OPS_ROWS:
        ser = m.get(key) or dv.get(key) or {}
        cur, py = (ser.get(q_last) or {}).get("v"), (ser.get(q_py) or {}).get("v")
        if cur is None:
            continue
        r = {"id": key, "label": label, "rate": rate, "ops_vals": {q: ser[q]["v"] for q in ext if q in ser},
             "ops_cur": cur, "ops_py": py, "src": ser[q_last].get("src") or "คำนวณ: " + ser[q_last]["calc"],
             "derived": key in dv}
        if py is not None:
            r["ops_pt" if rate else "ops_g"] = (cur - py) if rate else pct(cur, py)
        rows.append(r)
    if not rows:
        return None
    by = {r["id"]: r for r in rows}
    read, flags = [], []
    for side, vol, bill, util in (("OPD", "opd_visits", "per_bill_opd_baht", "opd_utilization_pct"),
                                  ("IPD", "ipd_days", "per_bill_ipd_baht", "occupancy_pct")):
        v, b, u = by.get(vol), by.get(bill), by.get(util)
        bits = []
        if v and v.get("ops_g") is not None:
            bits.append("ปริมาณ %+.1f%% YoY" % (v["ops_g"] * 100))
        if b and b.get("ops_g") is not None:
            bits.append("รายได้ต่อใบเสร็จ %+.1f%% YoY" % (b["ops_g"] * 100))
        if u:
            bits.append("%s %.2f%%%s" % ("อัตราครองเตียง" if side == "IPD" else "อัตราการใช้บริการ", u["ops_cur"],
                                         (" (%+.2f จุด YoY)" % u["ops_pt"]) if u.get("ops_pt") is not None else ""))
        c = by.get("implied_beds" if side == "IPD" else "implied_opd_capacity_per_day")
        if c and c.get("ops_py"):
            bits.append("ฐานที่ใช้คำนวณอัตรา %s → %s %s (%+.1f%%) [คำนวณ: ปริมาณ ÷ อัตรา ÷ จำนวนวัน]" % (
                "{:,.0f}".format(c["ops_py"]), "{:,.0f}".format(c["ops_cur"]), "เตียง" if side == "IPD" else "ครั้งต่อวัน", c["ops_g"] * 100))
        if bits:
            read.append("%s: %s" % (side, ", ".join(bits)))
        if v and v.get("ops_g") is not None and v["ops_g"] <= -0.10:
            flags.append({"id": "ops_%s" % vol, "line": v["label"], "change": v["ops_g"], "cur": v["ops_cur"], "py": v["ops_py"],
                          "text": "%s %s %+.1f%% YoY (%s → %s) [%s]" % (v["label"], be(q_last), v["ops_g"] * 100,
                                                                         "{:,.0f}".format(v["ops_py"]), "{:,.0f}".format(v["ops_cur"]), v["src"])})
        if u and u.get("ops_pt") is not None and abs(u["ops_pt"]) >= 5:
            flags.append({"id": "ops_%s" % util, "line": u["label"], "change": None, "cur": u["ops_cur"], "py": u["ops_py"],
                          "text": "%s %s %.2f%% เทียบ %.2f%% ใน %s (%+.2f จุด) [%s]" % (u["label"], be(q_last), u["ops_cur"], u["ops_py"],
                                                                                 be(q_py), u["ops_pt"], u["src"])})
    restated = sorted({k for k in (o.get("superseded") or {}) if k in by})
    notes = ["%s %s: สไลด์ล่าสุดแสดง %s%% ซึ่งให้ฐาน %s ต่างจากไตรมาสข้างเคียง (%s) — %s" % (
        dict((k, l) for k, l, _ in OPS_ROWS).get(c["metric"], c["metric"]), be(c["period"]) if "Q" in c["period"] else c["period"],
        c["slide"]["v"], "{:,.0f}".format(c["implied"]), ", ".join("{:,.0f}".format(n) for n in c["neighbours"]),
        ("ใช้ %s%% จาก %s แทน" % (c["used"]["v"], c["used"]["src"])) if c.get("used") else "ยังใช้ตัวเลขนี้ แต่ควรตรวจกับบริษัท")
        for c in o.get("base_checks") or [] if c["period"] in ext or "Q" not in c["period"] and str(int(q_last[:4]) - 1) in c["period"]]
    return {"rows": rows, "read": read, "flags": flags, "restated": restated, "base_notes": notes,
            "source": "Oppday slides (%s)" % ", ".join(sorted({r["src"] for r in rows if not r["derived"]}))}


# ------------------------------------------------------------------------------------------ investor angles (from คุณ Pop's posts)
# Canonical business-phase names = GLOSSARY.md (decided 2026-11-04). The ONLY phase vocabulary of snapshot, deepdive and
# every report. "Margin squeeze" and "cost-cut profit" are warning FLAGS, never phases; re-investment is a new Investment.
PH_INVEST = "ระยะลงทุน (Investment)"
PH_PEAK = "จุดต้นทุนพีค (Cost peak)"
PH_HARVEST = "ระยะเก็บเกี่ยว (Harvest)"
PH_LATE = "ระยะเก็บเกี่ยวช่วงท้าย (Late harvest)"
PH_SAT = "ระยะอิ่มตัว (Saturation)"
PH_NONE = "ยังไม่ระบุช่วง"
FLAG_SQUEEZE = "สัญญาณเตือน: มาร์จิ้นถูกกด"
FLAG_COSTCUT = "สัญญาณเตือน: กำไรโตจากลดต้นทุน ไม่ใช่การเติบโต"
FLAG_FLAT = "สัญญาณเตือน: รายได้ไม่โต"
SAT_CAPEX_DA = 1.2         # Saturation needs capex below 1.2x D&A (same cut-off as the Harvest rule)
SAT_GROWTH = 0.02          # ...and revenue and core-profit growth both under 2% a year (NEW threshold, tune with the owner)


def lead_indicators(lines, q_last, notes, fx, q_py):
    """Pop's early signs of a phase change, read from the statements rather than the P&L headline:
    D&A that has stopped rising and capital commitments running down = the investment phase is ending;
    commitments rising again = a new project has started. Plus where a change sits: parent or subsidiaries."""
    out = {}
    g = lambda q, k: (lines.get(q) or {}).get(k)
    qs = [qadd(q_last, -j) for j in range(8)]
    da = [(q, g(q, "da")) for q in qs if g(q, "da") is not None]
    if len(da) >= 5:
        cur = da[0][1]
        n = 1
        while n < len(da) and abs(da[n][1] / cur - 1) <= 0.05:
            n += 1
        yo = pct(cur, g(q_py, "da"))
        if n >= 4:
            t = "ค่าเสื่อมราคาทรงตัว %.1f–%.1f ลบ. มา %d ไตรมาส (ต้นทุนคงที่จากสินทรัพย์ไม่เพิ่มแล้ว)" % (
                min(v for _, v in da[:n]), max(v for _, v in da[:n]), n)
        elif yo is not None and yo > 0.08:
            t = "ค่าเสื่อมราคายังเพิ่ม %+.1f%% YoY (%.1f ลบ.) — ต้นทุนคงที่จากสินทรัพย์ใหม่ยังเข้ามา" % (yo * 100, cur)
        else:
            t = "ค่าเสื่อมราคา %.1f ลบ. (%s YoY)" % (cur, ("%+.1f%%" % (yo * 100)) if yo is not None else "–")
        out["da_trend"] = {"quarters_flat": n, "yoy": yo, "text": t}
    cm = (notes or {}).get("commitments")
    if cm:
        d = cm["cons"] - cm["cons_prior"]
        tag = ("เพิ่มขึ้น — อาจเริ่มโครงการลงทุนรอบใหม่" if cm["cons_prior"] and d / cm["cons_prior"] > 0.5 and d > 20 else
               "ลดลง — งานลงทุนที่ค้างอยู่กำลังหมด" if cm["cons_prior"] and d / cm["cons_prior"] < -0.3 else "ใกล้เคียงเดิม")
        out["commit"] = dict(cm, text="ภาระผูกพันรายจ่ายฝ่ายทุน งบรวม %.1f ลบ. (สิ้นปีก่อน %.1f) เฉพาะกิจการ %.1f (%.1f): %s [%s]" % (
            cm["cons"], cm["cons_prior"], cm["sep"], cm["sep_prior"], tag, cm["src"]))
    # Cost peak (GLOSSARY.md): both signals together confirm it; one alone is only a lead.
    dt, cm2 = out.get("da_trend"), out.get("commit")
    if dt or cm2:
        flat = bool(dt and dt["quarters_flat"] >= 4)
        down = bool(cm2 and cm2.get("cons_prior") and (cm2["cons"] - cm2["cons_prior"]) / cm2["cons_prior"] < -0.3)
        verdict = "ยืนยัน" if flat and down else ("บางส่วน" if flat or down else "ยังไม่ใช่")
        out["cost_peak"] = {"da_flat": flat, "commit_down": down, "verdict": verdict,
                            "text": "จุดต้นทุนพีค (Cost peak): %s — ค่าเสื่อมราคารายไตรมาส%s; ภาระผูกพันรายจ่ายฝ่ายทุน%s" % (
                                verdict, "ทรงตัว ≥ 4 ไตรมาสแล้ว" if flat else "ยังไม่ทรงตัว/ไม่พอข้อมูล",
                                "ลดลงมากกว่า 30%" if down else "ยังไม่ลดลงชัด/ไม่พบในหมายเหตุ")}
    # where does the YoY change sit: parent (separate statements) or subsidiaries (consolidated − separate)?
    rows = []
    for k, fk, lab in (("rev", "rev_hosp", "รายได้"), ("cogs", "cogs", "ต้นทุน"), ("selling", "selling", "ค่าใช้จ่ายขาย"), ("admin", "admin", "ค่าใช้จ่ายบริหาร")):
        c1, c0 = g(q_last, k), g(q_py, k)
        try:
            s1, s0 = fx.get(fk, q_last, "S"), fx.get(fk, q_py, "S")
        except Exception:
            s1 = s0 = None
        if None in (c1, c0, s1, s0):
            continue
        rows.append({"id": k, "label": lab, "cons": c1 - c0, "parent": s1 - s0, "subs": (c1 - s1) - (c0 - s0)})
    if rows:
        out["locate"] = {"rows": rows, "text": "; ".join("%s Δ YoY %+.1f = บริษัทแม่ %+.1f + บริษัทย่อย %+.1f" % (
            r["label"], r["cons"], r["parent"], r["subs"]) for r in rows)}
    return out


def investor_angles(lines, qs_all, q_last, one_offs):
    """Script-computed versions of the questions an experienced hospital investor asks every quarter:
    which business phase (investment / harvest / late harvest), how flat the fixed costs have been,
    whether the YoY base is abnormal (and what next quarter's base looks like), and price sensitivity."""
    g = lambda q, k: (lines.get(q) or {}).get(k)
    out = {}
    # ---- 1. business phase from TTM operating leverage
    def ttm(end, k):
        qq = [qadd(end, -j) for j in range(4)]
        vals = [g(q, k) for q in qq]
        return sum(vals) if all(v is not None for v in vals) else None
    pk = "core_pbt_x" if ttm(q_last, "core_pbt_x") is not None and ttm(qadd(q_last, -4), "core_pbt_x") is not None else "core_pbt"
    r1, r0 = ttm(q_last, "rev"), ttm(qadd(q_last, -4), "rev")
    p1_, p0 = ttm(q_last, pk), ttm(qadd(q_last, -4), pk)
    gp1, gp0 = ttm(q_last, "gp"), ttm(qadd(q_last, -4), "gp")
    if None not in (r1, r0, p1_, p0, gp1, gp0) and r0 and p0 > 0:
        rg, pg = r1 / r0 - 1, p1_ / p0 - 1
        inc = (gp1 - gp0) / (r1 - r0) if abs(r1 - r0) > 0.01 * r0 else None
        gpm = gp1 / r1
        mult = pg / rg if rg > 0.005 else None
        trail = []
        for k in range(3, -1, -1):
            q = qadd(q_last, -k)
            a, b = g(q, "rev"), g(qadd(q, -4), "rev")
            c, d = g(q, pk), g(qadd(q, -4), pk)
            if None not in (a, b, c, d) and b and d and d > 0 and a / b - 1 > 0.005:
                trail.append("%s %.1f เท่า" % (be(q), (c / d - 1) / (a / b - 1)))
        cx, da_ = ttm(q_last, "capex"), ttm(q_last, "da")
        cd = cx / da_ if cx is not None and da_ else None          # capex ÷ D&A: is the company building?
        flag = ""      # a warning sign, NOT a phase (GLOSSARY.md): the phase stays PH_NONE until the cause is found
        if rg <= 0.005:
            if pg > 0.05:
                phase, flag, why = PH_NONE, FLAG_COSTCUT, "กำไรมาจากการลดต้นทุน ไม่ใช่การเติบโต — ถามว่าลดต่อได้อีกแค่ไหน (ทำซ้ำไม่ได้ตลอด)"
            elif abs(pg) <= 0.05 and (cd is None or cd < SAT_CAPEX_DA):
                phase, why = PH_SAT, "รายได้และกำไรนิ่ง ลงทุนต่ำกว่าค่าเสื่อม — กำลังการผลิตน่าจะเต็ม เป็นหุ้นปันผลเว้นแต่จะเริ่มลงทุนรอบใหม่"
            else:
                phase, flag, why = PH_NONE, FLAG_FLAT, "Operating leverage ทำงานกลับด้าน (ขากลับของ Economies of Scale) — ดูว่าต้นทุนคงที่ปรับลดตามได้หรือไม่"
        elif mult is not None and mult >= 2 and (inc is None or inc > gpm):
            phase, why = PH_HARVEST, "รายได้ส่วนเพิ่มมีแต่ต้นทุนผันแปร ต้นทุนคงที่ไม่เพิ่ม กำไรจึงโตเร็วกว่ารายได้ — อัตรากำไรสุทธิมีแนวโน้มดีขึ้นต่อ"
        elif mult is not None and mult >= 0.8:
            phase, why = PH_LATE, "กำไรโตใกล้เคียงรายได้ ไม่เร่งแล้ว — ระวัง P/E ถูกปรับลด (de-rate) เมื่อการเติบโตชะลอ"
        elif cd is not None and cd >= 1.5:
            phase, why = PH_INVEST, "ลงทุนหนัก (Capex %.1f เท่าของค่าเสื่อม) ต้นทุนของสาขา/บริการใหม่มาก่อนรายได้ — กำไรยังไม่โตตาม" % cd
        else:
            phase, flag, why = PH_NONE, FLAG_SQUEEZE, "รายได้โตแต่ต้นทุนโตเร็วกว่า ทั้งที่ไม่ได้ลงทุนหนัก%s — หาสาเหตุ (ค่าแพทย์/ค่าแรง, ราคา สปส./บัตรทอง, ส่วนผสมผู้ป่วย)" % (
                (" (Capex %.1f เท่าของค่าเสื่อม)" % cd) if cd is not None else "")
        shown = phase + (" — " + flag if flag else "")
        margin = p1_ / r1
        out["phase"] = {"phase": phase, "flag": flag, "capex_da": cd, "rev_g": rg, "pbt_g": pg, "mult": mult, "incr_gpm": inc, "gpm": gpm, "pbt_key": pk,
                        "margin": margin, "trail": trail,
                        "text": "%s: รายได้ TTM %+.1f%%, %s TTM %+.1f%%%s; GP ส่วนเพิ่ม %s ของรายได้ส่วนเพิ่ม เทียบ GPM เฉลี่ย %.1f%%; %s%s" % (
                            shown, rg * 100, "Core PBT ก่อน ECL/รายการพิเศษ" if pk == "core_pbt_x" else "Core PBT", pg * 100,
                            (" (กำไรโต %.1f เท่าของรายได้)" % mult) if mult is not None else "",
                            ("%.1f%%" % (inc * 100)) if inc is not None else "–", gpm * 100, why,
                            (" | รายไตรมาส: " + ", ".join(trail)) if trail else "")}
        # price sensitivity: a price rise has (almost) no cost attached, so it drops to profit
        out["price"] = {"pct_per_1pct": r1 * 0.01 / p1_, "margin": margin,
                        "text": "ขึ้นราคา 1%% ≈ +%.2f ลบ./ปี ≈ +%.1f%% ของ Core PBT (Core PBT margin TTM %.1f%% — ยิ่งใกล้จุดคุ้มทุน ยิ่งไวต่อราคา/ปริมาณ)" % (
                            r1 * 0.01, r1 * 0.01 / p1_ * 100, margin * 100)}
    # ---- 2. how long each fixed cost has stayed in a narrow band (Q4 bonus quarters skipped, not counted)
    bands = []
    for k, lab in (("selling", "ค่าใช้จ่ายขาย"), ("admin_x", "ค่าใช้จ่ายบริหาร (ก่อน ECL/รายการพิเศษ)"), ("admin", "ค่าใช้จ่ายบริหาร")):
        if k == "admin" and any(b["id"] == "admin_x" for b in bands):
            continue
        v0 = g(q_last, k)
        if v0 is None or v0 <= 0:
            continue
        lo = hi = v0
        n, skipped, q = 1, [], q_last
        while True:
            q = qadd(q, -1)
            v = g(q, k)
            if v is None or q not in lines:
                break
            nlo, nhi = min(lo, v), max(hi, v)
            if nhi / nlo <= 1.12:
                lo, hi, n = nlo, nhi, n + 1
                continue
            if q.endswith("Q4") and v > hi and not skipped:
                skipped.append(q)
                continue
            break
        if n >= 3:
            bands.append({"id": k, "n": n, "lo": lo, "hi": hi, "skipped": skipped,
                          "text": "%s ทรงตัว %.1f–%.1f ลบ. มา %d ไตรมาส%s" % (
                              lab, lo, hi, n, (" (ไม่นับ %s ที่สูงกว่าปกติ — Q4 มักมีโบนัส/ตั้งสำรองสิ้นปี)" % ", ".join(be(x) for x in skipped)) if skipped else "")})
    out["cost_bands"] = bands
    # ---- 3. is the YoY base normal?  seasonal share of the base quarter in its own year, 2-year growth, base one-offs
    def share(q):
        y = q[:4]
        qq = ["%sQ%d" % (y, j) for j in range(1, 5)]
        vals = [g(x, "rev") for x in qq]
        return g(q, "rev") / sum(vals) if all(v is not None for v in vals) else None

    def base_view(q_cur, label):
        qb = qadd(q_cur, -4)
        sh = share(qb)
        others = [share("%dQ%s" % (y, q_cur[-1])) for y in range(int(qs_all[0][:4]), int(q_cur[:4]))]
        others = [x for x in others if x is not None and not str(qb).startswith(str(x))]
        hist = [share("%dQ%s" % (y, q_cur[-1])) for y in range(int(qs_all[0][:4]), int(qb[:4]))]
        hist = [x for x in hist if x is not None]
        oo = [o for o in one_offs if o.get("period") == qb]
        bits = []
        # seasonal tell: did the base quarter move QoQ unlike the same quarter in other years? (e.g. Q4/2566 above Q3/2566)
        def qoq(q):
            a, b = g(q, "rev"), g(qadd(q, -1), "rev")
            return a / b - 1 if a is not None and b else None
        qb_qoq = qoq(qb)
        other_qoq = [qoq("%dQ%s" % (y, qb[-1])) for y in range(int(qs_all[0][:4]), int(q_cur[:4]) + 1)]
        other_qoq = [x for y, x in zip(range(int(qs_all[0][:4]), int(q_cur[:4]) + 1), other_qoq)
                     if x is not None and "%dQ%s" % (y, qb[-1]) not in (qb, q_cur)]
        if qb_qoq is not None and other_qoq:
            mq = statistics.median(other_qoq)
            if abs(qb_qoq - mq) > 0.05:
                bits.append("%s: %s เปลี่ยน QoQ %+.1f%% ขณะที่ไตรมาสเดียวกันปีอื่นเปลี่ยน %+.1f%% (มัธยฐาน)" % (
                    "ฐานสูงผิดปกติ" if qb_qoq > mq else "ฐานต่ำผิดปกติ", be(qb), qb_qoq * 100, mq * 100))
        if sh is not None and hist:
            med = statistics.median(hist)
            tag = "ฐานสูงผิดปกติ" if sh - med > 0.01 else ("ฐานต่ำผิดปกติ" if med - sh > 0.01 else "ฐานปกติ")
            if tag != "ฐานปกติ" or not bits:
                bits.append("%s: %s มีสัดส่วน %.1f%% ของรายได้ทั้งปี %d เทียบปกติ %.1f%%" % (tag, be(qb), sh * 100, int(qb[:4]) + 543, med * 100))
        for o in oo:
            bits.append("ฐานมีรายการพิเศษ %+.2f ลบ. หลังภาษี (%s)" % (o["amount_after_tax"], o.get("label", "")))
        if not bits:
            return None
        return {"q": q_cur, "base": qb, "text": "%s %s เทียบ %s — " % (label, be(q_cur), be(qb)) + "; ".join(bits)}
    b_now = base_view(q_last, "ไตรมาสนี้")
    q2 = qadd(q_last, -8)
    if g(q_last, "rev") and g(q2, "rev"):
        two = g(q_last, "rev") / g(q2, "rev") - 1
        t2 = "รายได้เทียบ 2 ปีก่อน (%s) %+.1f%% (เฉลี่ย %+.1f%%/ปี) — ใช้ตัดผลของฐานที่ผิดปกติ" % (be(q2), two * 100, ((1 + two) ** 0.5 - 1) * 100)
        b_now = dict(b_now or {"q": q_last, "base": qadd(q_last, -4), "text": "ไตรมาสนี้ %s เทียบ %s" % (be(q_last), be(qadd(q_last, -4)))})
        b_now["two_year"] = two
        b_now["text"] += " | " + t2
    out["base_now"] = b_now
    out["base_next"] = base_view(qadd(q_last, 1), "ไตรมาสหน้า")
    return out


# ------------------------------------------------------------------------------------------ valuation, expectation, peers
# Price = valuation + narrative; narrative = expectation − disappointment (คุณ Pop).  The script supplies the measurable
# parts: what the market pays (P/E) for what growth (PEG), how results compared with what the trend implied, and whether
# operating leverage (the harvest story) is strengthening or fading.
def stock_dir(root, t):
    """Case-insensitive stock folder (the Thstock tree has 'lph', 'nkt', 'princ')."""
    p = os.path.join(root, t)
    if os.path.isdir(p):
        return p
    for d in os.listdir(root) if os.path.isdir(root) else []:
        if d.lower() == t.lower():
            return os.path.join(root, d)
    return None


def price_near(sdir, ticker, q_last, asm=None, max_days=150):
    mk = dict((asm or {}).get("market") or {}) or set_factsheet_price(sdir, ticker)
    if not mk.get("price") or not mk.get("as_of"):
        return {}
    try:
        d_as = datetime.strptime(str(mk["as_of"])[:10], "%Y-%m-%d")
    except ValueError:
        return {}
    y, qn = qsplit(q_last)
    if not -120 <= (d_as - datetime(y, 3 * qn, 28)).days <= max_days:
        return {}
    return mk


def valuation_view(price, shares, np_ttm, np_ttm_py, dps=None, net_cash_ps=None):
    if not (price and shares and np_ttm and np_ttm > 0):
        return None
    pe = price * shares / np_ttm
    # ex-cash P/E (Pop): strip the net cash per share from the price, so the multiple is on the hospital business only
    ex_pe = (price - net_cash_ps) / (np_ttm / shares) if net_cash_ps and net_cash_ps > 0 and price > net_cash_ps else None
    g = np_ttm / np_ttm_py - 1 if np_ttm_py and np_ttm_py > 0 else None
    peg = pe / (g * 100) if g and g > 0 else None
    if peg is None:
        lab = "กำไรไม่โต — P/E สะท้อนความคาดหวังว่าจะฟื้น"
    elif peg < 0.7:
        lab = "ตลาดคาดหวังต่ำ (PEG < 0.7) — ถ้าการเติบโตยังต่อได้ มีโอกาส re-rate"
    elif peg <= 1.5:
        lab = "ราคาสะท้อนการเติบโตพอสมควร (PEG 0.7–1.5)"
    else:
        lab = "ตลาดคาดหวังสูง (PEG > 1.5) — ถ้าผิดหวังเสี่ยงถูก de-rate"
    return {"pe": pe, "np_g": g, "peg": peg, "earn_yield": 1 / pe, "yield": (dps / price) if dps and price else None, "label": lab,
            "ex_cash_pe": ex_pe, "net_cash_ps": net_cash_ps if net_cash_ps and net_cash_ps > 0 else None}


def _ttm(lines_fn, end, k):
    vals = [lines_fn(qadd(end, -j)).get(k) for j in range(4)]
    return sum(vals) if all(v is not None for v in vals) else None


def peer_rows(root, ticker, cat, q_last, peers=None):
    """Same-quarter metrics for other hospitals from their own report/<T>_financials.json (script only)."""
    out = []
    if not root or not FS_DIR:
        return out
    import build_finance_sheet as BF
    cands = peers or [t for t, c in BF.HOSPITAL_CATEGORY.items() if c == cat and t != ticker]
    for t in cands:
        pd = stock_dir(root, t)
        fp = pd and os.path.join(pd, "report", "%s_financials.json" % t)
        if not fp or not os.path.isfile(fp):
            out.append({"ticker": t, "missing": True})
            continue
        try:
            pf = load_json(fp)
            pasm = load_json(os.path.join(pd, "report", "%s_assumptions.json" % t))
            pfx = F(pf, pasm)
            oo_pre, _, oo_sga = one_off_pretax(pasm)
            cache = {}

            def L(q):
                if q not in cache:
                    cache[q] = period_lines(pfx, q, oo_pre=oo_pre, oo_sga=oo_sga)
                return cache[q]
            q = q_last if L(q_last).get("rev") is not None else None
            if q is None:
                out.append({"ticker": t, "not_reported": True})
                continue
            cur, py = L(q), L(qadd(q, -4))
            pk = "core_pbt_x" if None not in (_ttm(L, q, "core_pbt_x"), _ttm(L, qadd(q, -4), "core_pbt_x")) else "core_pbt"
            r1, r0 = _ttm(L, q, "rev"), _ttm(L, qadd(q, -4), "rev")
            p1_, p0 = _ttm(L, q, pk), _ttm(L, qadd(q, -4), pk)
            n1, n0 = _ttm(L, q, "core_np"), _ttm(L, qadd(q, -4), "core_np")
            acc = pfx.get("accrued_inc", q)
            recv = (cur.get("recv") or 0) + (acc or 0) if cur.get("recv") is not None else None
            mult = ((p1_ / p0 - 1) / (r1 / r0 - 1)) if None not in (r1, r0, p1_, p0) and p0 > 0 and r1 / r0 - 1 > 0.005 else None
            row = {"ticker": t, "q": q, "rev": cur.get("rev"), "rev_yoy": pct(cur.get("rev"), py.get("rev")),
                   "gpm": cur.get("gpm"), "gpm_yoy_pt": (cur["gpm"] - py["gpm"]) if cur.get("gpm") is not None and py.get("gpm") is not None else None,
                   "sga_pct": cur.get("sga_pct"), "pbt_yoy": pct(cur.get(pk), py.get(pk)), "pbt_key": pk,
                   "core_pbt_margin": (cur.get(pk) / cur["rev"]) if cur.get(pk) is not None and cur.get("rev") else None,
                   "mult": mult, "dso": recv / (cur["rev"] * 4) * 365 if recv and cur.get("rev") else None,
                   "sso_share": ((((load_json(os.path.join(pd, "report", "%s_mda.json" % t)).get("revenue_mix") or {}).get("quarterly") or {})
                                  .get(q) or {}).get("sso") or 0) / cur["rev"] or None if cur.get("rev") else None,
                   "src": os.path.relpath(fp, root)}
            mk = price_near(pd, t, q, pasm)
            v = valuation_view(mk.get("price"), mk.get("shares_mn"), n1, n0) if mk else None
            if v:
                row.update({"pe": v["pe"], "peg": v["peg"], "np_g": v["np_g"]})
            out.append(row)
        except Exception as e:      # a broken peer file must not stop the report
            out.append({"ticker": t, "error": str(e)[:120]})
    return out

def reading_pack(sdir, q_last):
    """Per-quarter MD&A + Oppday slides + transcript passages in md/quarter/<BE>Q<q>/ (quarter_docs.py)."""
    try:
        import quarter_docs as QD
        r = QD.build(sdir, q_last)
        r["root"] = sdir
        return r
    except Exception as e:           # never let the reading pack stop the report
        return {"error": str(e)[:200], "files": []}


def second_sources(sdir):
    """Tier-2 material in md/second_source/ (news, interviews, third-party presentations): build the claims pack
    and list it. Tier 1 = SET/SEC filings, MD&A, Oppday. A tier-2 figure never replaces a tier-1 figure."""
    if not os.path.isdir(os.path.join(sdir, "md", "second_source")):
        return []
    try:
        import second_source as SS
        return SS.build(sdir)
    except Exception as e:
        return [{"file": "?", "error": str(e)}]


def third_sources(sdir, q_last):
    """Tier-3 material: forum posts by other investors (ThaiVI thread scraped into <stock>/Thaivi_100P). Built into
    md/third_source/thaivi/<BE>Q<q>.top.md; only the packs for this quarter and the one before are listed."""
    if not any(glob.glob(os.path.join(sdir, *(sub + ("*_posts_data.json",))))
               for sub in (("fetch_thaivi",), ("set", "fetch_thaivi"), ("Thaivi_100P",))):
        return []
    try:
        import forum_posts as FP
        idx = FP.build(sdir)
    except Exception as e:
        return [{"error": str(e)}]
    want = ["%dQ%d" % (int(q[:4]) + 543, int(q[-1])) for q in (q_last, qadd(q_last, -1))]
    return [e for e in idx if e["quarter"] in want]


def _paper_index(folder):
    p = os.path.join(folder, "_pack", "index.json")
    if not os.path.isfile(p):
        return []
    try:
        return [e for e in load_json(p) if e.get("status") == "ok" and e.get("card")]
    except Exception:
        return []


def papers(sdir, q_last, sector="Hospital", max_stock=10, max_sector=5):
    """Tier-2 research papers already turned into cards by script/fetch_paper/paper_pack.py.

    stock   <stock>/paper/_pack/: papers dated from 15 days before the quarter ended to 135 days after it (previews,
            result notes, the reviews before the next quarter's results). Dated papers only, so a back-dated
            report never sees a later one.
    sector  <AI_ROOT>/data/sector/<sector>/_pack/: the newest papers of the 12 months up to the same end date.
    """
    y, q = qsplit(q_last)
    end = datetime(y, q * 3, 30 if q in (2, 3) else 31)
    lo = (end - __import__("datetime").timedelta(days=15)).strftime("%Y-%m-%d")
    hi = (end + __import__("datetime").timedelta(days=135)).strftime("%Y-%m-%d")
    lo12 = (end - __import__("datetime").timedelta(days=365)).strftime("%Y-%m-%d")
    out = {"stock": [], "sector": [], "stock_index": None, "sector_index": None, "stock_total": 0}
    folder = os.path.join(sdir, "paper")
    idx = _paper_index(folder)
    if idx:
        out["stock_index"] = os.path.join(folder, "_pack", "INDEX.md")
        out["stock_total"] = len(idx)
        sel = sorted((e for e in idx if e.get("date") and lo <= e["date"] <= hi), key=lambda e: e["date"], reverse=True)
        out["stock"] = [dict(e, path=os.path.join(folder, e["card"])) for e in sel[:max_stock]]
        out["stock_more"] = max(0, len(sel) - max_stock)
        out["stock_undated"] = [e.get("file") or e["card"] for e in idx if not e.get("date")]
    sfolder = os.path.join(AI_ROOT, "data", "sector", sector)
    sidx = _paper_index(sfolder)
    if sidx:
        out["sector_index"] = os.path.join(sfolder, "_pack", "INDEX.md")
        sel = sorted((e for e in sidx if e.get("date") and lo12 <= e["date"] <= hi), key=lambda e: e["date"], reverse=True)
        out["sector"] = [dict(e, path=os.path.join(sfolder, e["card"])) for e in sel[:max_sector]]
    notes = os.path.join(sfolder, "industry_notes.md")
    out["industry_notes"] = notes if os.path.isfile(notes) else None
    return out


DEFAULT_ANALYST = "คุณ Pop"


def note_analyst(path):
    """Who wrote a reference note: a line `analyst: <name>` in the first 12 lines of the file, otherwise คุณ Pop.
    Lets a stock carry notes of more than one reference analyst (for example คุณ Eaw for RJH)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for _ in range(12):
                m = re.match(r"\s*(?:[-*]\s*)?analyst\s*:\s*(.+?)\s*$", fh.readline(), re.I)
                if m:
                    return m.group(1).strip()
    except OSError:
        pass
    return DEFAULT_ANALYST


def note_list(an):
    """Notes and posts of the pack as one list (snapshot keeps a list, the deep dive a dict of notes and posts)."""
    if isinstance(an, dict):
        return list(an.get("notes") or []) + list(an.get("posts") or [])
    return list(an or [])


def row_analyst(row, an=None):
    """Analyst of a `pop_view` or `conflicts` row: its `who`, else the author of the note file named in its source."""
    if isinstance(row, dict) and row.get("who"):
        return str(row["who"]).strip()
    src = str((row or {}).get("src") or (row or {}).get("second_src") or "") if isinstance(row, dict) else ""
    for n in note_list(an):
        if n.get("who") and os.path.basename(n.get("file", "")) and os.path.basename(n["file"]) in src:
            return n["who"]
    return DEFAULT_ANALYST


def analyst_names(an, rows=None):
    """Distinct reference analysts, คุณ Pop first: from the notes offered and from the rows written."""
    names = [n.get("who") or DEFAULT_ANALYST for n in note_list(an)] + [row_analyst(r, an) for r in rows or [] if isinstance(r, dict)]
    out = []
    for x in sorted(set(names), key=lambda x: (x != DEFAULT_ANALYST, x)):
        out.append(x)
    return out


def analyst_gaps(an, rows):
    """Analysts whose notes were offered but who have no row in `pop_view`."""
    have = {row_analyst(r, an) for r in rows or [] if isinstance(r, dict)}
    return [x for x in analyst_names(an) if x not in have]


def analyst_notes(sdir, q_last):
    """External analyst notes saved for this stock (md/analyst_notes/*<BE>Q<q>*.md): the latest quarter and the one before."""
    d = os.path.join(sdir, "md", "analyst_notes")
    if not os.path.isdir(d):
        return []
    want = {"%dQ%d" % (int(q[:4]) + 543, int(q[-1])) for q in (q_last, qadd(q_last, -1))}
    out = []
    for f in sorted(os.listdir(d)):
        m = re.search(r"(\d{4})Q([1-4])", f)
        if f.endswith(".md") and m and m.group(0) in want:
            out.append({"file": os.path.join(d, f), "period": m.group(0), "who": note_analyst(os.path.join(d, f))})
        elif f.endswith(".md") and not m:
            y = re.search(r"_(\d{4})_", f)        # look-backs / AGM notes: pop_2568_AGM.md
            if y and int(y.group(1)) in (int(q_last[:4]) + 543, int(q_last[:4]) + 542):
                out.append({"file": os.path.join(d, f), "period": y.group(1), "who": note_analyst(os.path.join(d, f))})
    # Facebook posts split by split_fb_posts.py: posts written after this quarter's results (and after the previous
    # quarter's), Pop's own analysis first. Dated, so a back-dated report can drop anything after its as-of date.
    idx = os.path.join(d, "fb", "index.json")
    if os.path.isfile(idx):
        try:
            posts = [e for e in load_json(idx) if e.get("quarter_hint") in want and e.get("chars", 0) >= 150]
        except Exception:
            posts = []
        rank = {"own": 0, "shared": 1, "news": 2}
        posts.sort(key=lambda e: (e.get("quarter_hint") != max(want), rank.get(e.get("kind"), 3), e.get("date") or ""))
        for e in posts[:12]:
            out.append({"file": os.path.join(d, "fb", e["file"]), "period": e["quarter_hint"], "date": e.get("date"),
                        "kind": e.get("kind"), "title": e.get("title", "")[:70], "chars": e.get("chars"), "who": DEFAULT_ANALYST})
    return out


def latest_mda_docs(sdir, q_last):
    """Line ranges of the MD&A documents for the latest quarter and the one before (for targeted reading)."""
    p = os.path.join(sdir, "md", "raw", "combined_mda_all.md")
    if not os.path.isfile(p):
        return []
    starts = []
    with open(p, encoding="utf-8", errors="replace") as fh:
        for i, ln in enumerate(fh, 1):
            if ln.startswith("# DOCUMENT:"):
                starts.append((i, ln.split(":", 1)[1].strip()))
        n = i
    out = []
    for k, (i, name) in enumerate(starts):
        m = re.search(r"Year(\d{4})_Q(\d)", name)
        if not m:
            continue
        per = "%dQ%s" % (int(m.group(1)) - 543, m.group(2))
        end = starts[k + 1][0] - 1 if k + 1 < len(starts) else n
        if per in (q_last, qadd(q_last, -1), qadd(q_last, -4)):
            out.append({"period": per, "doc": name, "file": p, "lines": [i, end]})
    return out


# ------------------------------------------------------------------------------------------ digest
def f2(v, pctv=False, d=2):
    if v is None:
        return "·"
    return ("%.1f%%" % (v * 100)) if pctv else ("{:,.%df}" % d).format(v)


def digest(p):
    L = []
    w = L.append
    w("%s %s  | %s | latest %s (QoQ %s, YoY %s) | YTD %s vs %s" % (p["ticker"], p["company"].get("name_th") or "", p["category_name"],
                                                                   p["q_last_be"], be(p["q_pq"]), be(p["q_py"]), be(p["ytd"]), be(p["ytd_py"])))
    w("\nHEADLINE (THB mn)            %10s %10s %10s   YoY     QoQ   tier" % (be(p["q_py"]), be(p["q_pq"]), p["q_last_be"]))
    for r in p["headline"]:
        if r["is_pct"] or r["id"] == "dso":
            ch = "%+.2fpt %+.2fpt" % ((r.get("yoy_pt") or 0) * (100 if r["is_pct"] else 1), (r.get("qoq_pt") or 0) * (100 if r["is_pct"] else 1)) if r.get("yoy_pt") is not None else ""
            w("  %-28s %10s %10s %10s   %s" % (r["id"], f2(r["py"], r["is_pct"]), f2(r["pq"], r["is_pct"]), f2(r["cur"], r["is_pct"]), ch))
        elif "yoy_abs" in r:
            w("  %-28s %10s %10s %10s  Δ%+.2f Δ%+.2f" % (r["id"], f2(r["py"]), f2(r["pq"]), f2(r["cur"]), r["yoy_abs"] or 0, r["qoq_abs"] or 0))
        else:
            w("  %-28s %10s %10s %10s  %6s %6s   %s" % (r["id"], f2(r["py"]), f2(r["pq"]), f2(r["cur"]), f2(r.get("yoy"), True), f2(r.get("qoq"), True),
                                                     ("T%d" % r["tier"]) if r.get("tier") else ""))
    w("\nREVENUE MIX (MD&A, reconciled)  " + " ".join("%9s" % be(q) for q in p["ext"]))
    for m in p["mix_rows"] + p["nat_rows"]:
        w("  %-30s " % m["id"] + " ".join("%9s" % f2(m["vals"].get(q)) for q in p["ext"]))
    for r in p["records"]:
        w("  RECORD: " + r["text"])
    for k in ("yoy", "qoq"):
        o = p["oplev"].get(k)
        if o:
            w("OPLEV %s: %s" % (k, o["text"]) + (" | ΔD&A/ΔCOGS %.0f%%" % (o["da_share_of_dcogs"] * 100) if o.get("da_share_of_dcogs") is not None else ""))
    for k in ("yoy", "qoq"):
        s = p["sga"].get(k)
        if s:
            w("SG&A %s: %s" % (k, s["text"]))
    if p["sga"]["selling_note"]:
        w("SELLING: " + p["sga"]["selling_note"])
    if p["sga"].get("long_run"):
        w("SG&A LONG RUN: " + p["sga"]["long_run"]["text"])
    for k in ("yoy_x", "qoq_x", "split_yoy", "split_qoq"):
        s = p["sga"].get(k)
        if s:
            w("SG&A %s: %s" % (k, s["text"]))
    if p.get("ecl_attrib"):
        w("ECL NOTE: " + p["ecl_attrib"]["text"])
    nt = p.get("nature") or {}
    if nt:
        w("NATURE %s vs %s: " % (be(nt["ytd"]), be(nt["ytd_py"])) + ("; ".join(
            "%s %s→%s" % (r["id"], f2(r["prior"]), f2(r["cur"])) for r in nt["rows"] if r["cur"] is not None) or "-") +
          ("" if nt["note_available"] else " | " + (nt["reason"] or "")))
    dv = p.get("dividend") or {}
    if dv.get("history"):
        w("DIVIDEND: " + "; ".join("%s DPS %s EPS %s payout %s" % (be(h["fy"]), f2(h["dps"]), f2(h["eps"], d=3), f2(h["payout"], True)) for h in dv["history"]) +
          " | cash/share %s, net cash/share %s (%s mn shares)" % (f2(dv.get("cash_ps")), f2(dv.get("net_cash_ps")), f2(dv.get("shares_mn"))))
        for sc in dv.get("scenarios") or []:
            w("  scenario payout %s -> DPS %s (yield %s)" % (f2(sc["payout"], True), f2(sc["dps"], d=3), f2(sc["yield"], True)))
    for k in ("yoy", "qoq"):
        b = p["bridges"].get(k)
        if b:
            w("BRIDGE %s %.2f → %.2f: " % (k, b["np0"], b["np1"]) + "; ".join("%s %+.2f" % (n.split(" (")[0], v) for n, v in b["items"]))
    w("YTD %s vs %s: " % (be(p["ytd"]), be(p["ytd_py"])) + "; ".join(
        "%s %s (%s)" % (r["id"], f2(r["cur"], r["is_pct"]), ("%+.2fpt" % (r["yoy_pt"] * 100)) if r["is_pct"] and r.get("yoy_pt") is not None else f2(r.get("yoy"), True))
        for r in p["ytd_rows"]))
    w("SEASONALITY basis %s %s; " % (p["season_meta"]["rev_growth_basis_label"], f2(p["season_meta"]["rev_growth_basis"], True)) + "; ".join(
        "%s rev≈%s (QoQ med %s) coreNP≈%s" % (be(s["q"]), f2(s["rev_proj"]), f2(s["qoq_median"], True), f2(s["core_np_proj"])) for s in p["season"]))
    w("MOMENTUM %.1f/10 %s: " % (p["momentum"]["score"], p["momentum"]["label"]) + "; ".join("%s %+.1f (%s)" % (c["name"], c["points"], c["why"]) for c in p["momentum"]["components"]))
    w("RED FLAGS needing a sourced explanation (id: text):")
    for fl in p["flags"]:
        w("  %s: %s" % (fl["id"], fl["text"]) + ("\n      statement hint (not an explanation): " + fl["hint"] if fl.get("hint") else ""))
    w("CHECKS: " + "; ".join("%s %s" % ("PASS" if c["ok"] else "FAIL", c["label"]) for c in p["checks"]))
    if p["gaps"]:
        w("GAPS: " + "; ".join(p["gaps"][:12]))
    if p["one_offs"]:
        w("ONE-OFFS: " + "; ".join("%s %+.2f %s" % (o["period"], o["amount_after_tax"], o.get("label", "")) for o in p["one_offs"]))
    if p["market"]:
        m = p["market"]
        w("MARKET: price %s (%s) P/E TTM %s P/BV %s yield %s" % (m.get("price"), m.get("as_of"), f2(m.get("pe_ttm")), f2(m.get("pbv")), f2(m.get("yield"), True)))
    rp = p.get("reading_pack") or {}
    for f in rp.get("files") or []:
        w("READ: %s (~%d tokens, from %s)" % (os.path.join(rp["root"], f["file"]), f["tokens_est"], f["source"]))
    if rp.get("files"):
        w("  (reading pack of %s; full documents %.0f KB — open them only at the [Lnnn] lines cited in oppday_qa.md)" % (
            p["q_last_be"], rp.get("full_bytes", 0) / 1024))
    for d in (p["mda_docs"] if not any(f["file"].endswith("mda.md") for f in rp.get("files") or []) else []):
        w("MD&A to read: %s lines %d-%d of %s" % (d["doc"], d["lines"][0], d["lines"][1], d["file"]))
    for x in (p.get("expect") or {}).get("lines") or []:
        w("EXPECT: " + x)
    for r in p.get("peers") or []:
        if r.get("rev") is not None:
            w("PEER %s %s: rev %s YoY %s | SSO %s | GPM %s (%s) | SG&A %s | %s YoY %s | x%s | DSO %s | P/E %s PEG %s" % (
                r["ticker"], be(r["q"]), f2(r["rev"]), f2(r["rev_yoy"], True), f2(r.get("sso_share"), True), f2(r["gpm"], True),
                ("%+.2fpt" % (r["gpm_yoy_pt"] * 100)) if r.get("gpm_yoy_pt") is not None else "·", f2(r["sga_pct"], True),
                r["pbt_key"], f2(r["pbt_yoy"], True), f2(r.get("mult"), d=1), f2(r.get("dso"), d=0), f2(r.get("pe"), d=1), f2(r.get("peg"))))
        else:
            w("PEER %s: %s" % (r["ticker"], "no report/%s_financials.json (run the finance-sheet extractor)" % r["ticker"] if r.get("missing")
                                else "not reported for this quarter" if r.get("not_reported") else r.get("error")))
    an = p.get("angles") or {}
    if an.get("phase"):
        w("PHASE: " + an["phase"]["text"])
    for b in an.get("cost_bands") or []:
        w("COST BAND: " + b["text"])
    for k in ("base_now", "base_next"):
        if an.get(k):
            w("BASE: " + an[k]["text"])
    if an.get("price"):
        w("PRICE: " + an["price"]["text"])
    for t in (p.get("ops") or {}).get("read") or []:
        w("OPS (Oppday: ปริมาณ vs ราคา): " + t)
    for t in (p.get("ops") or {}).get("base_notes") or []:
        w("OPS CHECK (ฐานของอัตราไม่เข้ากับงวดข้างเคียง): " + t)
    for k in ("da_trend", "commit", "cost_peak"):
        if an.get(k):
            w("LEAD: " + an[k]["text"])
    if an.get("locate"):
        w("LOCATE (งบรวม − งบเฉพาะกิจการ): " + an["locate"]["text"])
    notes = p.get("analyst_notes") or []
    if notes:
        names = analyst_names(notes)
        w("REFERENCE ANALYST (%s) — READ FIRST. His reading sets the questions and the order of the narrative; write what "
          "he says in `pop_view`. His figures are still checked against the filings: a difference goes to `conflicts`. "
          "Posts tagged shared/news are other people's material he re-posted: tier 2, not his view." % ", ".join(names))
        if len(names) > 1:
            w("  More than one reference analyst: give every `pop_view` row a `who` (%s) and write at least one row for each."
              % " / ".join(names))
    for n in notes:
        tag = "" if (n.get("who") or DEFAULT_ANALYST) == DEFAULT_ANALYST else " [%s]" % n["who"]
        if n.get("date"):
            w("  REFERENCE POST %s [%s, %s chars] %s — %s" % (n["date"], n.get("kind"), n.get("chars"), n.get("title"), n["file"]))
        else:
            w("  REFERENCE NOTE%s: %s" % (tag, n["file"]))
    pp = p.get("papers") or {}
    if pp.get("stock") or pp.get("sector") or pp.get("stock_index"):
        w("RESEARCH PAPERS (tier 2 — cross-check and context only, always external; a broker's target price, rating or "
          "forecast is never carried into the report; a figure that differs from the filings -> `conflicts`):")
        for e in pp.get("stock") or []:
            w("  BROKER PAPER %s %s [%s, %s chars] %s -> %s" % (e.get("date"), e.get("broker") or "?", e.get("kind"), e.get("card_chars"),
                                                             (e.get("title") or "")[:60], e["path"]))
        if pp.get("stock_index") and not pp.get("stock"):
            w("  BROKER PAPER: none dated in this quarter's window (%d cards in all) -> %s" % (pp.get("stock_total", 0), pp["stock_index"]))
        elif pp.get("stock_more"):
            w("  BROKER PAPER: %d more in the window -> %s" % (pp["stock_more"], pp["stock_index"]))
        if pp.get("stock_undated"):
            w("  BROKER PAPER WITHOUT A DATE (%d, not offered: no date, no way to rule out hindsight; tell the owner to add them to "
              "paper/paper_dates.txt): %s" % (len(pp["stock_undated"]), ", ".join(pp["stock_undated"][:8])))
        if pp.get("stock") or pp.get("sector"):
            w("  USE: read every card listed above before writing `outlook`, `risks` and `catalysts`. Either cite at least one "
              "(external item, src = the card path) or say in `papers_note` why none adds anything. A silent skip fails `check`.")
        for e in pp.get("sector") or []:
            w("  SECTOR PAPER %s %s [%s chars] %s -> %s" % (e.get("date"), e.get("broker") or "?", e.get("card_chars"),
                                                         (e.get("title") or "")[:60], e["path"]))
        if pp.get("industry_notes"):
            w("  INDUSTRY NOTES (dated summary of the sector papers) -> %s" % pp["industry_notes"])
    for e in p.get("second_sources") or []:
        if e.get("error"):
            w("SECOND SOURCE: could not build pack (%s)" % e["error"])
        else:
            w("SECOND SOURCE (tier 2 — context only, always external; contradiction with the pack/MD&A/Oppday -> `conflicts`): "
              "%s [%s, %s, ~%s tokens] -> %s" % (e["file"], e["kind"], e.get("date") or (e.get("mtime", "") + " file date"),
                                                 e["claims_tokens_est"], e["claims"]))
    for e in p.get("third_sources") or []:
        if e.get("error"):
            w("THIRD SOURCE: could not build pack (%s)" % e["error"])
        else:
            w("THIRD SOURCE (tier 3 — forum posts by other investors: leads and questions only, never a figure or a fact): "
              "%s %d posts %s..%s [~%s tokens] -> %s" % (e["quarter"], e["posts"], e["first"], e["last"], e["top_tokens_est"], e["top_file"]))
    return "\n".join(L)


# ------------------------------------------------------------------------------------------ narrative check
NUM_RE = re.compile(r"(?<![\w.])[-+−]?\d[\d,]*(?:\.\d+)?\s*%?")


PCT_KEYS = PCT_LINES | {"yoy", "qoq", "yoy_pt", "qoq_pt", "igpm", "gpm_avg", "rev_g", "sga_g", "pct0", "pct1", "change", "qoq_median",
                        "np_qoq_median", "rev_growth_basis", "np_growth_basis", "da_share_of_dcogs", "yield", "gpm",
                        "payout", "pct_rev", "dps_growth", "fy_growth_est", "cash_to_price", "sell_g", "admin_g", "admin_x_g",
            "pbt_g", "incr_gpm", "margin", "pct_per_1pct", "two_year",
            "np_g", "earn_yield", "rev_s", "np_s", "rev_yoy", "pbt_yoy", "gpm_yoy_pt", "core_pbt_margin", "sso_share"}


def pack_numbers(p):
    """Numbers a narrative may quote: (amounts, percents), each as rounded values at 0/1/2 decimals."""
    amounts, pcts = set(), set()

    def add(target, x):
        for d in (0, 1, 2):
            target.add((d, round(abs(x), d)))

    def walk(o, key=""):
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, k)
        elif isinstance(o, (list, tuple)):
            if len(o) == 2 and isinstance(o[0], str) and isinstance(o[1], (int, float)):   # bridge items
                add(amounts, o[1])
                return
            for v in o:
                walk(v, key)
        elif isinstance(o, (int, float)) and not isinstance(o, bool):
            if key in PCT_KEYS:
                add(pcts, o * 100)
            else:
                add(amounts, o)
    walk({k: v for k, v in p.items() if k not in ("sources", "mda_docs")})
    # growth and margin figures the report derives on the fly
    L = p["lines"]
    for q in L:
        for k, v in L[q].items():
            if isinstance(v, (int, float)) and k in PCT_LINES:
                add(pcts, v * 100)
    for q in L:
        for base in (qadd(q, -1), qadd(q, -4)) if "Q" in q else ():
            if base in L:
                for k, v in L[q].items():
                    b0 = L[base].get(k)
                    c = pct(v, b0) if isinstance(v, (int, float)) and isinstance(b0, (int, float)) else None
                    if c is not None:
                        add(pcts, c * 100)
                    if isinstance(v, (int, float)) and isinstance(b0, (int, float)):
                        add(amounts, v - b0)
                        if k in PCT_LINES:
                            add(pcts, (v - b0) * 100)
    for r in (p.get("ops") or {}).get("rows") or []:
        vals = [r["ops_cur"]] + list(r["ops_vals"].values())
        for v in vals:
            add(pcts if r["rate"] else amounts, v)
        if r.get("ops_pt") is not None:
            add(pcts, r["ops_pt"])
        if r.get("ops_g") is not None:
            add(pcts, r["ops_g"] * 100)
            add(amounts, r["ops_cur"] - r["ops_py"])
    for m in p.get("mix_rows", []) + p.get("nat_rows", []):
        vals = m["vals"]
        for q, v in vals.items():
            for base in (qadd(q, -1), qadd(q, -4)):
                c = pct(v, vals.get(base))
                if c is not None:
                    add(pcts, c * 100)
                if v is not None and vals.get(base) is not None:
                    add(amounts, v - vals[base])
            tot = sum((r["vals"].get(q) or 0) * (-1 if r["id"] == "elim" else 1) for r in p.get("mix_rows", []) + p.get("nat_rows", [])
                      if r in (p.get("mix_rows", []) if m in p.get("mix_rows", []) else p.get("nat_rows", [])))
            if v and tot:
                add(pcts, v / tot * 100)
    return amounts, pcts


def check_narrative(p, nar):
    """Returns list of problems: numbers that are neither in the pack nor sourced nor declared external."""
    amounts, pcts = pack_numbers(p)
    years = set()
    for q in list(p["lines"]) + p["window"] + [s["q"] for s in p["season"]] + list(p.get("hist_rev") or {}):
        m = re.search(r"(\d{4})", q)
        if m:
            years |= {int(m.group(1)), int(m.group(1)) + 543}
    problems = []

    def ok_num(tok):
        t = tok.replace(",", "").replace("−", "-").strip()
        is_pct = t.endswith("%")
        t = t.rstrip("%").strip()
        try:
            v = abs(float(t))
        except ValueError:
            return True
        dec = len(t.split(".")[1]) if "." in t else 0
        if not is_pct and dec == 0 and (v in years or v <= 12):    # years, quarter numbers, counts
            return True
        pool = pcts if is_pct else amounts
        if (dec, round(v, dec)) in pool:
            return True
        if is_pct and dec == 0 and any((1, x) in pcts for x in (round(v - 0.5, 1), round(v + 0.4, 1))):
            return True
        return False

    def visit(item, path):
        if isinstance(item, dict) and "text" in item:
            if item.get("src") or item.get("external"):
                return
            item = item["text"]
        if isinstance(item, str):
            txt = re.sub(r"\[[^\]]*\]", "", item)     # [คำนวณ: ...] formulas may restate inputs
            txt = re.sub(r"(Q[1-4]|[1-4]Q|[69]M|12M)[/ ]?\d{2,4}", "", txt)
            for tok in NUM_RE.findall(txt):
                if not ok_num(tok):
                    problems.append("%s: '%s' not in data pack — add \"src\" (MD&A/Oppday line) or list it under external" % (path, tok.strip()))
        elif isinstance(item, list):
            for i, x in enumerate(item):
                visit(x, "%s[%d]" % (path, i))
        elif isinstance(item, dict):
            for k, x in item.items():
                if k in ("external", "src"):
                    continue
                visit(x, "%s.%s" % (path, k))
    visit({k: v for k, v in nar.items() if k not in ("external", "conflicts")}, "narrative")
    PV = ("confirmed", "differs", "not_in_filings", "opinion")
    for i, it in enumerate(nar.get("pop_view") or []):
        if not isinstance(it, dict) or not it.get("text"):
            problems.append("pop_view[%d] must be an object with text, src and verdict" % i)
            continue
        if "analyst_notes" not in str(it.get("src", "")):
            problems.append("pop_view[%d].src must point into md/analyst_notes/<file> (his own note or post)" % i)
        if it.get("verdict") not in PV:
            problems.append("pop_view[%d].verdict must be one of %s" % (i, ", ".join(PV)))
        if it.get("verdict") == "differs" and not any("analyst_notes" in str(c.get("second_src", "")) for c in nar.get("conflicts") or [] if isinstance(c, dict)):
            problems.append("pop_view[%d] says the filings differ: add the row to `conflicts` with second_src in md/analyst_notes/" % i)
    if (nar.get("pop_view") or len(analyst_names(p.get("analyst_notes"))) > 1) and not nar.get("_auto"):
        for x in analyst_gaps(p.get("analyst_notes"), nar.get("pop_view")):
            problems.append("reference analyst %s has notes in the digest but no row in `pop_view` (set `who` on the rows)" % x)
    pp = p.get("papers") or {}
    offered = [e["path"] for e in (pp.get("stock") or []) + (pp.get("sector") or [])]
    if offered and not nar.get("_auto"):
        blob = json.dumps(nar, ensure_ascii=False)
        if not re.search(r"paper/_pack|data/sector|\.card\.md|industry_notes", blob) and not str(nar.get("papers_note") or "").strip():
            problems.append("the digest offered %d research paper card(s) (RESEARCH PAPERS) but the narrative cites none: cite one as an "
                            "external item with src = the card path, or set `papers_note` to the reason none is used" % len(offered))
    fl_ids = {f["id"] for f in p["flags"]}
    expl = nar.get("explanations") or {}
    for fid in sorted(fl_ids - set(expl)):
        problems.append("red flag '%s' has no explanation (it will be shown as 🚩 Unexplained)" % fid)
    for fid, e in expl.items():
        if isinstance(e, dict) and not e.get("src"):
            problems.append("explanation '%s' has no src (MD&A/Oppday line)" % fid)
    # second-source discipline: anything citing md/second_source must be marked external; a conflict needs both sides
    def walk(item, path):
        if isinstance(item, list):
            for i, x in enumerate(item):
                walk(x, "%s[%d]" % (path, i))
        elif isinstance(item, dict):
            if re.search(r"second_source|third_source|paper/_pack|data/sector|\.card\.md", str(item.get("src", ""))) and not item.get("external") and not path.startswith("narrative.conflicts"):
                problems.append("%s cites a second/third source but is not marked \"external\": true" % path)
            for k, x in item.items():
                walk(x, "%s.%s" % (path, k))
    walk(nar, "narrative")
    for i, c in enumerate(nar.get("conflicts") or []):
        miss = [k for k in ("topic", "second", "second_src", "primary", "primary_src") if not (isinstance(c, dict) and c.get(k))]
        if miss:
            problems.append("conflicts[%d] is missing %s" % (i, ", ".join(miss)))
        elif not re.search(r"second_source|third_source|analyst_notes|paper/_pack|data/sector|\.card\.md", c["second_src"]):
            problems.append("conflicts[%d].second_src must point into second_source/<file>:L<n>, third_source/thaivi/<BE>Q<q>:<post id> "
                            "analyst_notes/<file> (the reference analyst) or a paper card (paper/_pack/<name>.card.md)" % i)
    return problems


# ------------------------------------------------------------------------------------------ CLI
def stock_dir_for(args):
    if args.stock_dir:
        return check_stock_dir(args.stock_dir)
    root = find_root(getattr(args, "root", None))
    if not root:
        raise RuntimeError("Thstock root not found; pass --stock-dir")
    return os.path.join(root, args.ticker)


def cmd_data(a):
    sdir = stock_dir_for(a)
    p = build_pack(sdir, a.ticker, a.quarter, a.rebuild)
    out = os.path.join(sdir, "report", "%s_snapshot_data.json" % a.ticker)
    json.dump(p, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    print(digest(p))
    print("\n-> %s" % out)
    nar = os.path.join(sdir, "report", "%s_snapshot_narrative.json" % a.ticker)
    print("narrative file: %s (%s)" % (nar, "exists" if os.path.isfile(nar) else "not yet written"))
    return 0


def cmd_check(a):
    sdir = stock_dir_for(a)
    dp = os.path.join(sdir, "report", "%s_snapshot_data.json" % a.ticker)
    p = load_json(dp) or build_pack(sdir, a.ticker, a.quarter)
    nar_p = a.narrative or os.path.join(sdir, "report", "%s_snapshot_narrative.json" % a.ticker)
    nar = load_json(nar_p)
    if not nar:
        print("no narrative at %s" % nar_p)
        return 2
    probs = check_narrative(p, nar)
    for x in probs:
        print("  ⚠", x)
    print("RESULT: %s (%d issue%s)" % ("CLEAN ✅" if not probs else "REVIEW", len(probs), "" if len(probs) == 1 else "s"))
    return 0 if not probs else 1


def cmd_render(a):
    import render
    sdir = stock_dir_for(a)
    p = build_pack(sdir, a.ticker, a.quarter, a.rebuild, quiet=True)
    json.dump(p, open(os.path.join(sdir, "report", "%s_snapshot_data.json" % a.ticker), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1, default=str)
    nar_p = a.narrative or os.path.join(sdir, "report", "%s_snapshot_narrative.json" % a.ticker)
    nar = load_json(nar_p) if not a.auto else {}
    probs = check_narrative(p, nar) if nar else []
    md, html = render.write(p, nar, os.path.join(sdir, "report"), problems=probs, version=a.version)
    print("✅ %s\n✅ %s%s" % (md, html, "" if nar else "   (automatic narrative — no %s)" % os.path.basename(nar_p)))
    if probs:
        print("⚠ %d narrative issue(s) — listed in the report's verification section" % len(probs))
    return 0


def cmd_run(a):
    tickers = [t.upper() for t in a.tickers]
    if a.file:
        for ln in open(a.file, encoding="utf-8"):
            ln = ln.split("#")[0].strip()
            tickers += [t.upper() for t in re.split(r"[,\s]+", ln) if t]
    root = find_root(a.root)
    res = []
    for t in dict.fromkeys(tickers):
        print("━━━ %s ━━━" % t)
        try:
            ns = argparse.Namespace(stock_dir=os.path.join(root, t) if root else None, ticker=t, quarter=None, rebuild=a.rebuild,
                                    narrative=None, auto=a.auto, version=None, root=a.root)
            cmd_render(ns)
            res.append((t, "OK"))
        except Exception as e:
            print("   ❌ %s" % e)
            res.append((t, "ERROR: %s" % e))
    print("━━━ Summary ━━━")
    for t, s in res:
        print(" %-8s %s" % (t, s))
    return 0 if all(s == "OK" for _, s in res) else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("data", "render", "check"):
        s = sub.add_parser(name)
        s.add_argument("--stock-dir")
        s.add_argument("--ticker", required=True)
        s.add_argument("--root")
        s.add_argument("--quarter", help="analyse this quarter instead of the latest (e.g. 2026Q1)")
        s.add_argument("--rebuild", action="store_true", help="re-extract financials/MD&A even if up to date")
        s.add_argument("--narrative", help="narrative JSON (default report/<T>_snapshot_narrative.json)")
        s.add_argument("--auto", action="store_true", help="render: ignore any narrative file, use the automatic one")
        s.add_argument("--version", help="render: force version number")
    s = sub.add_parser("run")
    s.add_argument("tickers", nargs="*")
    s.add_argument("-f", "--file")
    s.add_argument("--root")
    s.add_argument("--rebuild", action="store_true")
    s.add_argument("--auto", action="store_true")
    a = ap.parse_args()
    a.ticker = getattr(a, "ticker", None) and a.ticker.upper()
    return {"data": cmd_data, "render": cmd_render, "check": cmd_check, "run": cmd_run}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
