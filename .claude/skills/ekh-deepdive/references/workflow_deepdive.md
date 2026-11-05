> Detailed workflow of the former `stock-deepdive` skill, now one stage of `thai-hospital-deepdive`. Paths: `scripts/` and `references/` are this skill's own folders. AI_ROOT is never guessed (see SKILL.md).


# Stock Deep-Dive (5–6 years)

Writes `report/<T>_DeepDive_Report_<BE year>-v<N>.md` and a standalone `.html` for one hospital stock. It covers
every fiscal year in the filings (up to 6), plus the latest YTD compared with the prior-year YTD.

Use it when the user asks for a deep-dive, long-term or strategic analysis, วิเคราะห์เชิงลึก, วัฏจักรธุรกิจ, moat, or
"stock-deepdive" for a Thai hospital stock. For a quarter-focused view use `stock-snapshot`. For the Excel model and
valuation use `thai-hospital-finance-sheet`.

## Why it is built this way (read once)

The Antigravity version had a fine structure, but the numbers were unreliable:

- It printed invented occupancy ranges for each branch and for five years ("72–78%").
- It showed ROIC and payout as 0% every year.
- It compared a 6-month total with a full year and called it −51% growth.
- It excluded short-term deposits from cash.
- Its guidance tracker was raw transcript text, with every item marked "In-Line".

Here the script computes every financial number with the finance-sheet definitions. **Beds, occupancy and management targets are never estimated.** They come from the One Report, MD&A or Oppday with a line reference, or the report says they were not disclosed.

## Standing principles of the owner (apply in every report; never drop)

The full text lives in ONE place: **`references/analyst_playbook.md` §1c** (the margin ladder). Read it
before writing any revenue-mix reason. A later edit of this skill must keep this section and that pointer. The three
principles, by name only: (1) margin ladder, (2) read mix before volume, (3) SSO is also a funnel. A principle changes
only when a document shows otherwise: show that evidence in the report and tell the owner; never change or ignore it
silently.

## Files

- `scripts/deepdive.py`: builds the data pack and has the `data`, `render`, `check` and `run` commands.
- `scripts/render_deepdive.py`: writes the Markdown and HTML (it reuses the snapshot renderer).
- `scripts/deepdive_extra.py`: loads the optional `<T>_hospitals.json`, `<T>_project.json` and `<T>_ops_metrics.json` and renders their tables (by hospital, operations, new project).
- `scripts/deepdive_workbook.py`: writes the **Deepdive workbook** — the finance model with the analysis on top.
- `scripts/deepdive_sector.py`: reads `<AI_ROOT>/data/sector/Hospital/sector_trend.json` and builds section 7.1–7.2 (the stock's rank vs the sector median and the early signals), its digest block and the workbook sheet `อุตสาหกรรม`.
- `references/deepdive_narrative_schema.md`: the narrative JSON you write, section by section.
- `references/deepdive_rules.md`: the COVID base-year rule, lifecycle rules, scorecard, peers and what never to estimate.
- `assets/VIH_deepdive_narrative_example.json`: a complete narrative that passes `check`.

It needs the sibling skills `stock-snapshot` (its data layer and renderer) and `thai-hospital-finance-sheet` (its extractors), in the same `skills` folder:

- master: `C:\ai\.agents\skills\`
- WSL: `/mnt/c/ai/.agents/skills/` (the root can be changed with the `AI_ROOT` environment variable)

**The copy in the Claude account is this SKILL.md only, on purpose** (decided 7 Oct 2026): scripts, references and
assets exist in one place, the master folder `C:\ai\.agents\skills\stock-deepdive` on the user's computer, so the two
copies can never drift apart. When there is no `scripts/` folder next to this file, do this before step 1, and do not
rewrite any script from memory:

1. Take from the master `skills` folder: this skill's `scripts/*.py` (5 scripts: `deepdive.py`, `render_deepdive.py`,
   `deepdive_extra.py`, `deepdive_workbook.py`, `deepdive_sector.py`), the sector file
   `data/sector/Hospital/sector_trend.json`, `references/*` and `assets/*`; all of `stock-snapshot/scripts/` and
   `stock-snapshot/references/`; and the five scripts of `thai-hospital-finance-sheet/scripts/`. With a shell on the
   user's computer, run them there. Otherwise copy them into the working directory through the link to the user's
   computer, together with the stock's input files, and run them in the workspace.
2. Keep the three folders side by side (`skills/stock-deepdive/scripts/`, `skills/stock-snapshot/scripts/`,
   `skills/thai-hospital-finance-sheet/scripts/`), so the scripts find each other.
3. If the user's computer cannot be reached, stop and say so. Ask the user to open the chat in the desktop app on that
   computer; do not build the report another way.

`C:\ai` is a junction to `G:\My Drive\00_AI_Project`: the two paths are the same folder, not two copies. A session
usually has the `G:\My Drive\00_AI_Project` path connected; use whichever it can reach, and do not ask the user to
compare them.

Stock folders are `C:\ai\Thstock\<T>` (WSL `/mnt/c/ai/Thstock/<T>`). Reports go to `<T>/report`.

## Workflow

### Step 1: Data pack and digest

```bash
S="/mnt/c/ai/Thstock/VIH"
python3 scripts/deepdive.py data --stock-dir "$S" --ticker VIH
```

This re-runs the extractors if `md/raw` is newer than the JSON files. The digest (~4k tokens) shows:

- every fiscal year and the YTD pair for about 30 lines
- growth, full-period CAGR and CAGR from the post-COVID base year
- expenses by nature as a share of revenue
- annual revenue mix and nationality mix
- the lifecycle rule result and the quality scorecard
- peers, computed from their own `report/<T>_financials.json`
- red flags
- **file:line candidates** for beds and occupancy, and for targets and guidance

Peers appear only when their finance sheet has been run. `run_finance_sheet.py BCH CHG RJH` makes Category-2 peers available.

### Step 2: Read the sources (targeted)

**Start with the reference analyst (คุณ Pop).** When the digest has a `REFERENCE ANALYST` block, read his notes and his own
posts first (`<stock>/md/analyst_notes/`, newest first, until nothing new comes up). His reading sets the questions and
the order of the report (decided 6 Oct 2026: his *method* is level 1). Then read the company's documents to answer those
questions. His figures are not level 1: each one is checked against the filings.

Read only around the candidate lines, plus the latest annual (Q4) MD&A and the latest quarter's MD&A:

- **Capacity:** the One Report text in `PDF/*.txt`, section 1.2 on the business. Use the most recent year available, and say which year it is.
- **Guidance:** MD&A pages on the earnings call and targets (e.g. JUMP+), and Oppday transcripts if they are in `md/raw`.
- **Explanations:** the annual MD&A, for why revenue, costs, SG&A and cash changed in the latest year.

`md/oppday_guidance_tracker.md` and `md/finance_summary.md` were generated by AGY. They are not sources.

### Step 2b: Update the finance model and the two fact files (the deep dive is built on them)

1. **Finance model first.** Update `report/<T>_assumptions.json` (market data, one-offs, the `project` block) and rebuild
   with `thai-hospital-finance-sheet` until `check_workbook.py` says CLEAN. The deep dive analyses from this model.
2. **`report/<T>_hospitals.json`** (groups with several hospitals): revenue, capitation, net profit and beds **per
   hospital and year**, each year with its `src`. Sources: the annual report / One Report table "รายได้แยกตามโรงพยาบาล"
   and the AGM minutes (`set/agm`). Rules:
   - The parent hospital's profit in an annual report includes dividends from subsidiaries. Store the figure excluding
     them and say so in `np_basis` (separate net profit − dividend income).
   - The sum of the hospitals must equal group revenue before eliminations; the workbook shows the difference.
   - When the company gives only a growth rate, the computed value is allowed but must be labelled as computed, and the
     missing table goes into `pending`.
   - File names of annual reports can be one year ahead of the report year. Check the cover.
3. **`report/<T>_project.json`** (a new hospital or other large project): `approved`, `revised`, `funding`, `phasing`,
   `competitors_20km`, `ifa` (NPV, IRR, payback, FCFF by year, sensitivity), `management_statements`, `timeline` (what
   management said and when), each block with `src`. The shareholder-meeting minutes for the asset acquisition and the
   IFA report are the sources. IFA figures are **the proposer's base case, not results**: always labelled so, and never
   used as the floor of the risk case.

Both files are optional; a stock without them gets a report without those tables. Copy the layout from
`Thstock/VIH/report/VIH_hospitals.json` and `VIH_project.json`.

### Step 3: Write `report/<T>_deepdive_narrative.json`

Follow `references/deepdive_narrative_schema.md`. Key rules:

- Every number not in the digest needs a `src`. Anything from outside the company's documents needs `"external": true` (dark red, listed in section 10).
- Every capacity row and every guidance row needs a `src`. Occupancy is "ไม่เปิดเผย" unless a document states it.
- Give each red-flag id an explanation. Use `"status": "partial"` when the documents only partly explain it; leave it out when nothing explains it.
- **Reference analyst:** write `pop_view` (3–8 rows `{"text", "src", "verdict"}`): the points he makes about this stock
  over the years, in his order. `src` points into `md/analyst_notes/`; `verdict` is `confirmed`, `differs`,
  `not_in_filings` or `opinion`. A `differs` row needs a matching row in `conflicts`. Own posts only: what he merely
  shared is tier 2. `check` reports a stock that has his notes but no `pop_view`.
- **Source tiers:** SET filings and company documents are tier 1 and decide every figure. Files in `<stock>/md/second_source/`
  (news, interviews, transcripts), broker and sector papers, and posts he only shared are tier 2: context only, marked
  external. Forum posts are tier 3: leads only. Where a lower tier or the reference analyst contradicts tier 1, keep
  tier 1 and record both sides in `conflicts` (shown in section 10); never average.
- **Situation-specific rules:** `stock-snapshot/references/pop_casebook.md` — read the section that fits the stock (SSO-heavy,
  foreign-patient, a new hospital ramping, a windfall unwinding, when a thesis fails). The stock's own dated facts from
  his posts are in `<stock>/md/analyst_notes/company_facts.md` (leads: verify before use).
- **Division of work with the snapshot:** `stock-snapshot/references/report_framework.md`. Quarterly detail stays in the
  snapshot; here the same data answers the long questions. Occupancy and volume come from `report/<T>_ops_metrics.json`
  (read from Oppday PDFs by `stock-snapshot/scripts/oppday_ops.py`; use `metrics`, never `superseded`): read occupancy
  as distance from break-even and from full, and pair it with room to expand. Revenue by subsidiary hospital comes from
  the annual report. Read every revenue split through the margin ladder and the SSO funnel (the standing principles above).
- **Make-or-break point, open questions, industry:** write `pivot` (one stock-specific point, both sides sized), `pending`
  (what the documents could not answer) and `team`; take the industry picture from
  `<AI_ROOT>/data/sector/Hospital/industry_notes.md` and broker cards in `<folder>/_pack/INDEX.md`
  (`script/fetch_paper/paper_pack.py`). See `references/deepdive_rules.md` and `deepdive_narrative_schema.md`.
- **Sector position and early signals:** digest block `SECTOR & POSITION`. Write `sector_view` (position vs the median and why; leading indicators from documents, each with `src`; what to watch). `check` fails without `sector_view.position` when the block exists. Rules: `deepdive_rules.md` → Sector and the stock's position.
- **Shape of the argument:** casebook §10 gives the order of his own long-form deep dive (industry → feared threat tested
  against history → branches and land → record over 3 and 10 years → new S-curve sized against an analogue → peer table →
  risks), plus occupancy as distance from break-even and from full, and growth read in baht (ΔNP / Δrevenue).
- **Core lens (from `references/analyst_playbook.md`):** the business phase by operating leverage (4.1, digest
  `OPERATING LEVERAGE` / `PHASE`) and price = valuation + narrative (`VALUATION`, write `expectation`).
- Lifecycle: start from the rule result. You may argue for a different phase, but only with documentary evidence such as a new hospital under construction or a big capex plan.
- Scorecard: the quality score is computed. You add the posture, a moat rating with its reason, and a capital-allocation view.

### Step 4: Check, render, look

```bash
python3 scripts/deepdive.py check  --stock-dir "$S" --ticker VIH   # RESULT: CLEAN ✅
python3 scripts/deepdive.py render --stock-dir "$S" --ticker VIH
```

The version number continues after existing reports, so the new one never overwrites an old one. Open the `.md` and skim the executive summary, section 3 and section 10.

### Step 4b: The Deepdive workbook (the main deliverable)

```bash
python3 scripts/deepdive_workbook.py --stock-dir "$S" --ticker VIH
python3 ../thai-hospital-finance-sheet/scripts/check_workbook.py "$S/report/VIH_Deepdive_<year>_v<N>.xlsx"   # CLEAN ✅
```

It opens the newest `<T>_finance_model_v<N>.xlsx`, keeps all its sheets and formulas, and adds four sheets:
`Deepdive (บทวิเคราะห์)` in front (headline, make-or-break point, summary, expectation, team, headwinds and tailwinds,
guidance, open questions, external items — taken from the checked narrative), `รายโรงพยาบาล (By hospital)` (inputs in
blue; sums, shares, margins and growth as formulas), `ปฏิบัติการ (Operations)` and `โครงการใหม่ (Project)`. Output:
`report/<T>_Deepdive_<BE year>_v<N>.xlsx`. Run it only after `check` is CLEAN, so the text on top matches the model.

### Step 5: Deliver

Give the paths and reply with:

1. the headline
2. the lifecycle phase and quality score
3. the 3–4 most important long-term findings
4. what could not be verified (capacity year, missing peers, unexplained flags)

## Batch / no-agent runs

`python3 scripts/deepdive.py run VIH PR9` (or `-f input1.txt`, `--root <Thstock>`) writes each report with an automatic narrative built from the numbers only. The capacity, guidance, macro and roadmap sections then say "ต้องอ่านเอกสาร".

The user's runner `C:\ai\script\stock_deepdive\claude\run_stock_deepdive.py` wraps this command.

## Report sections

- **0. Executive summary**
- **1. Multi-year financial table:** fiscal years + YTD vs prior YTD, CAGR, charts
- **2. Structure:** revenue mix and nationality mix, expenses by nature as % of revenue
- **3. Capacity and utilisation:** sourced rows only
- **4. Lifecycle:** capex-rule phase, 4.1 operating-leverage phase by year, the documents' view, case studies
- **5. Moats and peers:** the peer table from filings
- **6. Capital allocation:** the table, plus guidance vs actual results
- **7. Industry, position and macro:** 7.1 sector CAGR windows and the stock's rank vs the core median; 7.2 computed early signals plus `sector_view.leading` / `watch`; 7.3 tailwinds and headwinds. Data: `<AI_ROOT>/data/sector/Hospital/sector_trend.json` (re-run `python3 script/sector/sector_trend.py` when a new quarter is in); the workbook gets a sheet `อุตสาหกรรม`
- **8. Roadmap**
- **9. Scorecard:** transparent quality score, plus posture and moat
- **10. Verification:** red flags, check issues, external items, one-offs, source-line appendix
