---
name: thai-hospital-deepdive
description: Deep-dive analysis of a SET-listed Thai hospital or medical stock (VIH, BCH, BDMS, CHG, RJH, PR9 ...) in one skill - extract the filings into a 10-tab Excel model, build the quarterly snapshot data layer, then write the 5-6 year K. Pop-style deep-dive (five business phases, K. Pop checklist, downside/upside value range) as versioned Markdown + HTML + workbook, every number sourced. Thai hospitals on SET only.
---

# Thai Hospital Deep-Dive (SET only)

One skill that replaces the chain `thai-hospital-finance-sheet` -> `stock-snapshot` -> `stock-deepdive`. All scripts live in
one folder (`scripts/`), so the skill is self-contained. The three original skills are untouched.

Use it when the user asks for a deep-dive, long-term or strategic analysis, a quarterly snapshot, a finance sheet or
financial model, or "วิเคราะห์หุ้น / งบการเงิน / โมเดลการเงิน" for a **Thai hospital or medical stock listed on SET**. For any
other business or market, stop and say it is out of scope (the scripts raise `NotHospital`).

## Rule 0: AI_ROOT is never guessed

`AI_ROOT` is the one machine-wide setting. It is the folder that holds `data/` and `Thstock/`:

| Where | Value |
|---|---|
| Windows | `C:\ai` (a link to `G:\My Drive\00_AI_Project`) |
| WSL | `/mnt/c/ai` (a link to `/mnt/g/My Drive/00_AI_Project/`) |

- Every script reads `AI_ROOT` and nothing else. If it is unset, or the folder lacks `data/` or `Thstock/`, the script prints
  `STOP: ...` and exits. **When you see STOP, ask the user which folder to use; do not pick one and do not retry with a guess.**
- The stock folder must be `<AI_ROOT>/Thstock/<TICKER>`. A copy elsewhere (for example a project folder) is refused, because
  it would mix its own data with the master's sector, peer and factsheet data.
- Sector data: `<AI_ROOT>/data/sector/Hospital/` (`sector_trend.json`, `sector_analysis_*.md`, `payor_events.json`, papers).
  Ten-year factsheets: `<AI_ROOT>/data/Factsheet/`. Trusted forum authors: `<AI_ROOT>/etc/thaivi_trusted_authors.txt`.
- WSL: `~/.bashrc` must contain `export AI_ROOT=/mnt/c/ai`. A non-interactive `wsl -e bash -c` does not read it, so pass
  `AI_ROOT=/mnt/c/ai` in front of the command.

## Standing principles of the owner (apply in every report; never drop)

Full text: `references/analyst_playbook.md` §1c (the only copy). By name: (1) margin ladder, (2) read mix before volume,
(3) SSO is also a funnel. A principle changes only when a document shows otherwise: show that evidence in the report and
tell the owner; never change or ignore it silently. A later edit of this skill must keep this section.

## The K. Pop model in one paragraph

Five phases, one vocabulary everywhere: **Investment, Cost peak, Harvest, Late harvest, Saturation**. Margin squeeze,
cost-cut profit and flat profit are warning flags, not phases. Cost peak is confirmed by flat quarterly D&A and capital
commitments falling toward zero. Value is judged on normal profit (core business), with a margin of safety = low P/E on
normal profit and errors that cost only time; PEG near 1.0 is fair; the downside test asks what is left if the thesis
fails, the upside test is profit after operating leverage x a fair P/E (K. Pop looks for about 50-100%). Terms and
definitions: the project's `GLOSSARY.md` (if present) and `references/analyst_playbook.md`. CAPM and the 70-90% payout
scenarios are **analyst overlay**, labelled as such, not K. Pop rules.

## Design rule (why the numbers can be trusted)

A script computes every number; you write only the reasons, and each reason cites a source (`src`: file and line or page).
`check` rejects any number in the narrative that is not in the data pack, unless it carries a source or is declared
external. Beds, occupancy and management targets are never estimated: read them from the One Report, MD&A or Oppday with a
line reference, or say they were not disclosed. Checklist items of kind **owner** (`pop_owner`) are never answered by the skill.

## Workflow

Run from this skill's `scripts/` folder, with `S="$AI_ROOT/Thstock/<T>"` (Windows `py`, WSL `python3`; set `PYTHONUTF8=1`
on Windows).

| Stage | What | Command | Detail |
|---|---|---|---|
| 1. Extract + Excel model | 14 quarters of statements, MD&A mix, 10-tab formula workbook | `extract_financials.py`, `extract_mda.py`, `build_finance_sheet.py`, `check_workbook.py` | `references/workflow_finance_sheet.md` |
| 2. Quarterly snapshot | momentum, mix, incremental GPM, red flags, phase and cost-peak check | `snapshot.py data/check/render --stock-dir "$S" --ticker <T>` | `references/workflow_snapshot.md` |
| 3. Deep-dive | 5-6 year report, K. Pop checklist (14.1), value range (11.1-11.2), workbook | `deepdive.py data/check/render --stock-dir "$S" --ticker <T>` | `references/workflow_deepdive.md` |

Typical deep-dive run:

```bash
python3 deepdive.py data   --stock-dir "$S" --ticker VIH   # data pack + digest; read the ROOTS line and any INCOMPLETE INPUTS warning
# write report/VIH_deepdive_narrative.json  (references/deepdive_narrative_schema.md, example in assets/)
python3 deepdive.py check  --stock-dir "$S" --ticker VIH   # must end RESULT: CLEAN
python3 deepdive.py render --stock-dir "$S" --ticker VIH   # next free version; nothing is overwritten
```

Batch with no agent: `C:\ai\script\thai_hospital_deepdive\claude\run_thai_hospital_deepdive.py`.

Output goes to `<AI_ROOT>/Thstock/<T>/report/`: `<T>_DeepDive_Report_<BE>-v<N>.md/.html`, `<T>_Deepdive_<BE>_v<N>.xlsx`.
The master folder is the single home of reports; do not keep a second live copy elsewhere.

## Narrative and checklist rules

- Narrative schemas: `references/deepdive_narrative_schema.md`, `references/snapshot_narrative_schema.md`; worked examples in `assets/`.
- `pop_checklist`: `{"<id>": {"status": "pass|fail|unsure", "why": {"text": "...", "src": "..."}}}` for the document-based items
  (b1, b2, b3, b4, b6, c4, k3, t1). Auto items are computed by `deepdive_pop.py`. Owner items (b5, p3, t2, t3, t4, g1-g3) are
  left for the owner. Use `unsure` when the documents do not answer; never guess.
- Rules: `references/deepdive_rules.md` (phases, lenses), `references/analysis_rules.md`, `references/report_framework.md`.

## Files

- `scripts/deepdive.py`, `render_deepdive.py`, `deepdive_pop.py` (K. Pop checklist), `deepdive_val.py` (value range, end-state dividend),
  `deepdive_viz.py`, `deepdive_extra.py`, `deepdive_sector.py`, `deepdive_prerun.py`, `deepdive_workbook.py`: stage 3.
- `scripts/snapshot.py` (data layer and `AI_ROOT` guard), `render.py`, `quarter_docs.py`, `fs_notes.py`, `oppday_ops.py`, `sso_pxq.py`,
  `second_source.py`, `forum_posts.py`, `split_fb_posts.py`: stage 2.
- `scripts/extract_financials.py`, `extract_mda.py`, `build_finance_sheet.py`, `check_workbook.py`, `xlcalc.py`: stage 1.
- `references/`: playbook, rules, schemas, taxonomy, model spec, and the three `workflow_*.md` files with the full stage instructions.
- `assets/`: narrative and assumptions examples, note templates.
