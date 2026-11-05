#!/usr/bin/env python3
"""
check_workbook.py — independent verification of a built model.

1. Recalculates the .xlsx in LibreOffice (headless) and compares every formula cell with the
   builder's own evaluator (xlcalc).  Any difference > 0.005 is reported.
2. Scans for Excel errors (#REF!, #DIV/0!, #VALUE!, #NAME?).
3. Prints the Cover integrity-check results.

Usage:  python3 check_workbook.py report/VIH_finance_model_v3.xlsx
Exit code 0 = clean, 1 = problems found.  LibreOffice missing -> step 1 is skipped with a warning.
"""
import os, shutil, subprocess, sys, tempfile
from openpyxl import load_workbook
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xlcalc import Workbook as CalcWB, XLError


def main(path):
    wb = load_workbook(path)                      # formulas
    cells = {ws.title: {c.coordinate: c.value for row in ws.iter_rows() for c in row if c.value is not None} for ws in wb}
    calc = CalcWB(cells)
    problems = []
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    lo = None
    if soffice:
        tmp = tempfile.mkdtemp()
        subprocess.run([soffice, "--headless", "--calc", "--convert-to", "xlsx", "--outdir", tmp, path],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
        out = os.path.join(tmp, os.path.basename(path))
        if os.path.exists(out):
            lo = load_workbook(out, data_only=True)
    else:
        print("⚠ LibreOffice not found — skipping cross-engine recalculation (install: sudo apt install libreoffice-calc)")
    n = 0
    for sh, cs in cells.items():
        for addr, v in cs.items():
            if not (isinstance(v, str) and v.startswith("=")):
                continue
            n += 1
            mine = calc.get(sh, addr)
            if isinstance(mine, XLError):
                problems.append(f"{sh}!{addr} evaluator error {mine.code}: {v[:90]}")
                continue
            if lo is not None:
                theirs = lo[sh][addr].value
                if isinstance(theirs, str) and theirs.startswith("#"):
                    problems.append(f"{sh}!{addr} LibreOffice error {theirs}: {v[:90]}")
                elif isinstance(mine, (int, float)) and not isinstance(mine, bool):
                    if not isinstance(theirs, (int, float)) or abs(float(theirs) - mine) > 0.005:
                        problems.append(f"{sh}!{addr} mismatch: evaluator {mine!r} vs LibreOffice {theirs!r}")
                elif (mine or "") != (theirs or "") and not (isinstance(mine, bool) and theirs == mine):
                    problems.append(f"{sh}!{addr} mismatch: evaluator {mine!r} vs LibreOffice {theirs!r}")
    # The model's Cover is the first sheet, but the Deepdive workbook puts its analysis sheet in front.
    cover = next((ws for ws in wb.worksheets if "Cover" in ws.title), wb.worksheets[0])
    n_checks = 0
    print(f"Checked {n} formulas in {len(cells)} sheets" + (" (cross-checked with LibreOffice)" if lo else ""))
    for row in cover.iter_rows():
        for c in row:
            if isinstance(c.value, str) and "PASS" in c.value and c.value.startswith("=IF"):
                n_checks += 1
                res = calc.get(cover.title, c.coordinate)
                print(f"  {res}  {cover.cell(row=c.row, column=1).value}")
                if "FAIL" in str(res):
                    problems.append(f"Integrity check failed: {cover.cell(row=c.row, column=1).value}")
    if not n_checks:
        problems.append(f"No integrity checks found on sheet '{cover.title}': the model's checks were not run")
    for p in problems[:40]:
        print("  ❌", p)
    print("RESULT:", "CLEAN ✅" if not problems else f"{len(problems)} problem(s) ❌")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
