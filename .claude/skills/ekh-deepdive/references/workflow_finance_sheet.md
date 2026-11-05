> Detailed workflow of the former `thai-hospital-finance-sheet` skill, now one stage of `thai-hospital-deepdive`. Paths: `scripts/` and `references/` are this skill's own folders. AI_ROOT is never guessed (see SKILL.md).


# Thai Hospital Finance Sheet (10-tab model + Markdown)

Produces `report/<TICKER>_finance_model_v<N>.xlsx` and a matching `.md` for one hospital stock. The output
always follows the user's required format:

1. **Executive Summary** (Thai, qualitative): *why* margins and profit changed, backed by a numeric profit bridge
2. **Hierarchical financial tables**: P&L → Balance sheet → Returns → Cash flow → Tie-out
3. **Valuation Matrix + Sensitivity Analysis**

## Why this skill exists (read once)

It replaces the Antigravity `finance_sheet` skill. That skill produced nice-looking sheets, but many
numbers were **invented by fixed ratios**: Separate = 85% of Consolidated, tax = 20% of EBIT, finance cost =
0.7% of liabilities, ECL = 1.0 every quarter, and expenses by nature as % of cost. It also forced
Equity = Assets − Liabilities, so its "Balance Check = 0.00" could never fail. For VIH the real Separate revenue is ~38% of the
group, not 85%, so its Subsidiaries tab was wrong by a factor of ~2.5.

The rule here: **a number is either extracted from a filing (with its source line) or it is left blank and
reported as a gap.** Judgement goes only into clearly labelled inputs: revenue mix, one-offs, forecasts,
valuation and project assumptions, and the narrative. Each carries a written source or rationale.

## Tabs produced

| # | Sheet | What it holds |
|---|---|---|
| 0 | `หน้าปก (Cover & Summary)` **NEW** | Title, 14 KPIs (links), executive summary, profit bridge YoY/QoQ, TOC with hyperlinks, integrity checks, colour legend, data gaps |
| 1 | `งบรวม (Consolidated)` | 14 quarters + TTM. Full hierarchy and tie-out to reported EBIT/NP |
| 2 | `งบเฉพาะกิจการ (Separate)` | Same layout from the company-only statements (real numbers) |
| 3 | `งบบริษัทย่อย (Subsidiaries)` | `=Consolidated − Separate` formulas + **dividend-adjusted** contribution rows |
| 4 | `โครงสร้างรายได้ (Revenue)` | OPD / IPD / SSO / eliminations from MD&A; must reconcile to reported revenue |
| 5 | `วิเคราะห์<project> (Sensitivity)` | Expansion project: project NP and group ROE grids, break-even occupancy (live formulas) |
| 6 | `งบรวมรายปี (Consolidated)` | 6 fiscal years + interim YTD **vs prior-year YTD** (not vs full year) + DPS/payout |
| 7 | `โครงสร้างรายได้ (Annual)` | Annual revenue mix |
| 8 | `ค่าใช้จ่ายตามลักษณะ (Nature)` | Expenses-by-nature note (annual); "other" = total cost − 5 buckets |
| 9 | `ประเมินมูลค่า (Valuation)` **NEW** | Market data, CAPM, 5-method valuation matrix with weights, price metrics, 3 sensitivity grids |

Full row-by-row spec: `references/model_spec.md`.

## Workflow

Scripts live in `scripts/` next to this file, with `references/` and `assets/` beside them.

**The copy in the Claude account is this SKILL.md only, on purpose** (decided 7 Oct 2026): scripts, references and
assets exist in one place, the master folder on the user's computer, so the two copies can never drift apart. When
there is no `scripts/` folder next to this file, do this before step 1, and do not rewrite any script from memory:

1. Take `scripts/*.py`, `references/*.md` and `assets/*` from the master folder (5 scripts: `extract_financials.py`,
   `extract_mda.py`, `build_finance_sheet.py`, `check_workbook.py`, `xlcalc.py`). With a shell on the user's computer,
   run them there. Otherwise copy them into the working directory through the link to the user's computer, together
   with the stock's input files, and run them in the workspace.
2. If the user's computer cannot be reached, stop and say so. Ask the user to open the chat in the desktop app on
   that computer; do not build the model another way.

Master location of this skill on the user's computer:
`C:\ai\.agents\skills\thai-hospital-finance-sheet` (WSL
`/mnt/c/ai/.agents/skills/thai-hospital-finance-sheet`; the root can be changed with the `AI_ROOT` environment variable).
`C:\ai` is a junction to `G:\My Drive\00_AI_Project`: the two paths are the same folder, not two copies. A session
usually has the `G:\My Drive\00_AI_Project` path connected; use whichever of the two it can reach, and do not ask the
user to compare them. Sibling skills: `stock-snapshot` and
`stock-deepdive` in the same folder. They reuse this skill's extractors (`extract_financials.py`, `extract_mda.py`) and the
`Facts` definitions in `build_finance_sheet.py`, so a change here changes them too. After editing a label or a definition,
re-run a snapshot for VIH and PR9 as a regression check.

The scripts need Python 3.8+ and `openpyxl`. If `import openpyxl`
fails, use `pip install openpyxl` or set `PYTHONPATH=<stock_dir>/pylib`; VIH ships a copy there.
LibreOffice is optional. It is used only for the cross-check in step 4.

Paths: the user's stock folders are `C:\ai\Thstock\<TICKER>` (= `G:\My Drive\00_AI_Project\Thstock\<TICKER>`) on Windows. In WSL they are
`/mnt/c/ai/Thstock/<TICKER>`. Quote paths,
because they contain a space.

### Step 1: Extract statements (deterministic)

```bash
S="/mnt/c/ai/Thstock/VIH"
python3 scripts/extract_financials.py --stock-dir "$S" --ticker VIH -o "$S/report/VIH_financials.json"
```

- Inputs found automatically with `--stock-dir`:
  - `md/raw/combined_financial_all.md`: quarterly and annual SEC/SET filings, English or Thai
  - `md/raw/combined_fs2_all.md`: latest interim filings
  - `md/raw/combined_fs3_all.md`: audited annual statements (`# ANNUAL / FOLDER` blocks). This is what gives the 6 fiscal
    years of the annual tab and the expenses-by-nature notes. Each annual file also carries the year before as its
    comparative column (FY2564 gives FY2563 too), so 5 annual files cover 6 years. Years filed in a statement are shown
    first; a year known only from Jitta is used only inside the last 5 years. Set `"annual_years"` in the assumptions
    file for more or fewer years (consecutive years only, because each column's YoY formula uses the column to its left).
    An annual folder downloaded by hand (`set/fs3/FS3_Year<BE>_Annual/` with `.XLS`/`.DOC`) is converted by
    `fetch_set.py <T> --rebuild-md`.
  - The Jitta factsheet (`set/factsheet/factsheet_jitta_<T>.json`, then the older `factsheet/` and `md/factsheets/`),
    used only as a fallback for older consolidated totals and shown yellow.
- If a stock has no `combined_fs3_all.md`, pass the One Report text with `--files ... "$S"/PDF/E_ONE_REPORT_*_Y<year>.txt`
  (it costs more tokens and time). The parser also copes with PDF text that drops Thai tone marks.
- Read the printed coverage grid and flags:
  - `■` means found; `·` means missing.
  - `CONFLICT` / `RESTATED?` means two sources disagree. The original current-period figure is kept; mention it in the report.
  - `AMBIGUOUS ROW` means a column layout couldn't be resolved. Check that line in the filing.
- If a hospital uses different wording and a core line is missing, run with `--dump-labels`. Add the label as
  a synonym in `LABELS` inside `extract_financials.py`. Never type numbers into the model to paper over it.

### Step 2: Scaffold and fill the assumptions file (judgement, with sources)

```bash
python3 scripts/build_finance_sheet.py init -f "$S/report/VIH_financials.json" \
   --set-factsheet "$S/set/factsheet/factsheet_set_VIH.json" --out "$S/report/VIH_assumptions.json"
```

The SET and Jitta factsheets are in `<stock>/set/factsheet/` (written by `script/factsheet/fetch_factsheet_set.py`). If
that folder is not there yet, use the older locations `<stock>/factsheet/` or `<stock>/md/factsheets/`; take the file
with the newest trading date. When an assumptions file already exists, check its `market` block against the newest
factsheet and update price, date and shares before building.

The scaffold pre-fills price, listed shares and last-year DPS from the SET factsheet. Fill in the rest
following `references/assumptions_guide.md`, which has the schema, rules and a worked VIH example
(`assets/VIH_assumptions_example.json`). In short:

- **company / category**: category from `references/hospital_taxonomy.md`. SSO rows appear only for Category 2.
- **revenue_mix**: OPD, IPD, SSO and eliminations per quarter and year from `md/raw/combined_mda_all.md`
  (table "โครงสร้างรายได้"). Run the extractor first; it fills every period that reconciles:
  ```bash
  python3 scripts/extract_mda.py --stock-dir "$S" --ticker VIH -f "$S/report/VIH_financials.json" \
     -o "$S/report/VIH_mda.json" --merge-assumptions "$S/report/VIH_assumptions.json"
  ```
  - It only adds periods that are missing, unless you pass `--overwrite`.
  - It also stores the Thai/foreign split (`nationality_mix`) for Category-1 hospitals.
  - It prints a grid with PASS/FAIL per period, plus `RESTATED LATER` notes when a later MD&A reclassified OPD/IPD.
  - Transcribe by hand only the periods it could not read, e.g. very old MD&A that are image-only.
  - The Revenue tab must reconcile to reported revenue within ±1 THB mn. A FAIL there means a transcription error. Fix it; don't ignore it.
- **one_offs**: after-tax, per quarter, only items management or the auditor names, with the source in the
  label. Examples: SSO retroactive rate cuts, provision reversals, asset sales. They drive Core Profit and
  roll up into FY and YTD automatically.
- **valuation**: rf (look up the current Thai 10-year yield), beta, ERP, g, payout, FY1 forecast with
  rationale, multiple ranges and weights. Put a one-line justification for each in `valuation.notes`. Any value left
  out falls back to a yellow DEFAULT cell, and the build warns about it.
- **project**: only a disclosed expansion, or one the user supplies. Say where the numbers came from.
- **manual_facts**: last resort for a figure the parser cannot reach. Each needs a `src`, and it is shown yellow.

### Step 3: Build, read the numbers, then write the executive summary

```bash
python3 scripts/build_finance_sheet.py build -f "$S/report/VIH_financials.json" \
   -a "$S/report/VIH_assumptions.json" -o "$S/report"
```

Build first with `executive_summary` empty. Open the generated `.md` and read:

- the profit bridge (volume effect, margin effect, other income, SG&A, tax)
- GPM, SG&A% and ETR trends
- the dividend-adjusted subsidiary contribution
- DSO, ECL, net cash and FCF
- the valuation matrix

Then read the latest MD&A for the *reasons*. Write `executive_summary` (Thai) as described in
`references/exec_summary_guide.md`. Every claim should cite a number that appears in the model, and each
margin or profit statement should say *why* (payor mix, price/RW rates, volume, cost growth vs revenue,
one-offs). Rebuild. Each build writes a new version and never overwrites an old one. Delete
superseded drafts only if the user wants that.

### Step 4: Verify

```bash
python3 scripts/check_workbook.py "$S/report/VIH_finance_model_v<N>.xlsx"
```

The check requires `RESULT: CLEAN ✅`. It confirms:

- every integrity check PASSes (balance sheet A = L + E using *reported* equity, EBIT and NP tie to the filing, revenue mix ties, profit bridge closes)
- there are no formula errors
- LibreOffice values equal the builder's own evaluator

Also spot-check three numbers in the xlsx against the filing lines named in the cell comments or source column.
If a check FAILs, find the cause in the data. Never "fix" a check by editing its formula.

### Step 5: Deliver

Give the user the `.xlsx` and `.md` paths. Reply in the required format, briefly:

1. 3–5 bullet executive summary (margin and profit drivers, with numbers)
2. One line on what the tables contain, with any gaps or restatement flags
3. Fair value, upside and signal, plus the one or two assumptions that move it most (from the sensitivity grids)

## Batch / manual runs (no agent)

The user has a standalone runner at `C:\ai\script\finance_sheet\claude\run_finance_sheet.py`
(WSL `/mnt/c/ai/script/finance_sheet/claude`). It runs `python3 run_finance_sheet.py PR9`, several
tickers, or `-f input1.txt`, and executes steps 1–4 for each ticker. Output goes to `Thstock/<TICKER>/report`.

- It reuses `<T>_assumptions.json` when present.
- Step "2b" runs `extract_mda.py` and adds the reconciled revenue-mix periods that are missing, so the Revenue tabs are filled without an agent.
- Otherwise it scaffolds one with category-based default multiples and writes an automatic, number-only executive
  summary labelled `[สรุปอัตโนมัติจากตัวเลข]`.

When the user asks for a full analysis of a stock already run this way, do steps 2–3 properly:

- Replace the automatic summary and the defaults in the existing assumptions file (revenue mix, one-offs, valuation
  notes, FY1 forecast, a real summary from MD&A).
- Rebuild.

The runner imports the engine from the master `scripts/` folder when it exists, so there is one copy to maintain. Its local copies are only a fallback.

Companies without subsidiaries (e.g. PR9) file only consolidated-style statements. The Separate and Subsidiaries
tabs stay empty and the build warns about it; that is expected. Finance income below operating profit is its own P&L
row.

## Updating for a new quarter

Refresh `md/raw` with the new filing, re-run step 1 (the 14-quarter window rolls forward by itself), add the
new quarter's revenue mix and any one-offs, update market data and the FY1 forecast, rewrite the executive
summary, rebuild, and verify.

## Formatting conventions (built in; don't restyle by hand)

- Navy `#2F5496` headers, `#E2EFDA` subtotals, `#D9E1F2` section bands, Segoe UI, hidden gridlines, frozen panes at B6
- Blue font = input, black = formula, green = cross-sheet link, yellow fill = Jitta/manual/default, orange fill = check row
- `#,##0.00` for amounts, `0.0%` for ratios, `-` for zero; sheet names ≤ 31 characters
- Thai labels with English in brackets; periods in Buddhist-era years (Q2/2569)