> Detailed workflow of the former `stock-snapshot` skill, now one stage of `thai-hospital-deepdive`. Paths: `scripts/` and `references/` are this skill's own folders. AI_ROOT is never guessed (see SKILL.md).


# Stock Snapshot (4 quarters back, 4 quarters forward)

Writes `report/<T>_Snapshot_Report_Q<q>_<BE year>-v<N>.md` and a matching standalone `.html` dashboard for one
hospital stock. The report covers the latest quarter against the previous quarter, the same quarter last year and
the prior-year YTD, and gives a statistical view of the next four quarters.

Use it when the user asks for a snapshot, momentum report, ภาพรวมระยะสั้น, สรุปงบไตรมาสล่าสุด, or "stock-snapshot"
for a Thai hospital or medical stock (VIH, PR9, BCH, CHG, BDMS, SAFE...), or wants the snapshot refreshed after a new quarter.

**Scope: hospital and medical stocks only** (categories 1–5 in `hospital_taxonomy.md`). `snapshot.py` refuses any other
ticker. For another business, tell the user this skill does not cover it; a separate skill is planned for other sectors.
A medical ticker missing from the taxonomy can be admitted by setting `"category"` in its assumptions file.

## Why it is built this way (read once)

The Antigravity version wrote fluent reports with wrong numbers:

- "revenue" was total revenue, not hospital revenue
- selling expenses were shown as 0 when the filing had them
- ECL was a fixed 1.00 placeholder every quarter
- cash left out the short-term deposits, so it showed a fake −51% fall
- 6M results were compared with a full year
- occupancy, patient counts and payment rates were invented and then coloured red

So the rule here is the same as in `thai-hospital-finance-sheet`: **a script computes every number; you write only
the reasons, and each reason cites an MD&A or Oppday line.**

- The scripts reuse the finance-sheet extractor and its `Facts` definitions, so the snapshot and the Excel model can never disagree.
- The `check` step rejects any number in your narrative that is not in the data pack, unless it carries a source or is declared external.

## Standing principles of the owner (apply in every report; never drop)

The full text lives in ONE place: **`references/analyst_playbook.md` §1c** (the margin ladder). Read it
before writing any revenue-mix reason. A later edit of this skill must keep this section and that pointer. The three
principles, by name only: (1) margin ladder, (2) read mix before volume, (3) SSO is also a funnel. A principle changes
only when a document shows otherwise: show that evidence in the report and tell the owner; never change or ignore it
silently.

## Files

- `scripts/snapshot.py`: builds the data pack and has the `data`, `render`, `check` and `run` commands.
- `scripts/render.py`: writes the Markdown and HTML from the same blocks.
- `scripts/quarter_docs.py`: builds the per-quarter reading pack (MD&A, Oppday slides, transcript passages) — script only.
- `scripts/fs_notes.py`: reads the latest filing's notes with line sources — receivables aging and ECL allowance, cash-flow
  reconciling items, directors' and management pay, and an expenses-by-nature note if there is one.
- `scripts/oppday_ops.py`: reads operating metrics from the Oppday slide **PDFs** by position (period label under
  each value, chart above each axis) into `report/<T>_ops_metrics.json`: outpatient visits, OPD utilisation, inpatient
  days, occupancy, revenue per bill, plus every other chart or table with a period axis (payor, centre, ...). Needs
  PyMuPDF. `snapshot.py data` runs it when a PDF is newer than the file.
- `references/report_framework.md`: what belongs in the snapshot and what belongs in the deep dive, and the margin ladder.
- `references/snapshot_narrative_schema.md`: the narrative JSON you write, with a worked example.
- `references/analysis_rules.md`: interpretation rules (tiers, incremental GPM, cost rigidity, categories, seasonality).
- `references/analyst_playbook.md`: **the core lens of the narrative** — คุณ Pop's way of reading a hospital quarter
  (business phase, fixed costs, base effects, next-quarter bridge, tone). Read it before writing the narrative.
- `references/pop_casebook.md`: what his posts on other hospitals add. Read only the section that fits the stock:
  §1 SSO-heavy, §2 foreign-patient/high-end, §3 a new hospital or building, §4 a windfall unwinding, §5 checks on the
  statements, §6 demand drivers, §7 valuation and when a thesis fails.
- `assets/VIH_snapshot_narrative_example.json`: a complete narrative that passes `check`.

The scripts need the sibling skill `thai-hospital-finance-sheet`. They look for its `scripts/` next to this skill
(`../thai-hospital-finance-sheet/scripts`) and, failing that, at the master copy
`C:\ai\.agents\skills\thai-hospital-finance-sheet\scripts`
(WSL `/mnt/c/ai/.agents/skills/...`; the root can be changed with the `AI_ROOT` environment variable).

**The copy in the Claude account is this SKILL.md only, on purpose** (decided 7 Oct 2026): scripts, references and
assets exist in one place, the master folder `C:\ai\.agents\skills\stock-snapshot` on the user's computer, so the two
copies can never drift apart. When there is no `scripts/` folder next to this file, do this before step 1, and do not
rewrite any script from memory:

1. Take from the master folder: `scripts/*.py` (8 scripts: `snapshot.py`, `render.py`, `quarter_docs.py`, `fs_notes.py`,
   `oppday_ops.py`, `second_source.py`, `forum_posts.py`, `split_fb_posts.py`), `references/*` and `assets/*`; and the
   five scripts of `thai-hospital-finance-sheet/scripts/`. With a shell on the user's computer, run them there.
   Otherwise copy them into the working directory through the link to the user's computer, together with the stock's
   input files, and run them in the workspace.
2. Keep the layout `skills/stock-snapshot/scripts/` and `skills/thai-hospital-finance-sheet/scripts/` side by side, so
   the scripts find each other.
3. If the user's computer cannot be reached, stop and say so. Ask the user to open the chat in the desktop app on that
   computer; do not build the report another way.

`C:\ai` is a junction to `G:\My Drive\00_AI_Project`: the two paths are the same folder, not two copies. A session
usually has the `G:\My Drive\00_AI_Project` path connected; use whichever it can reach, and do not ask the user to
compare them.

Paths: stock folders are `C:\ai\Thstock\<T>` (WSL `/mnt/c/ai/Thstock/<T>`). Quote them.

## Workflow

### Step 1: Build the data pack and read the digest

```bash
S="/mnt/c/ai/Thstock/VIH"
python3 scripts/snapshot.py data --stock-dir "$S" --ticker VIH
```

- **What it runs first:**
  - If `report/<T>_financials.json` or `<T>_mda.json` is missing or older than `md/raw`, it runs the finance-sheet extractors itself.
  - `extract_mda.py` reads the MD&A revenue table. Only periods that reconcile to the statements within ±1 THB mn are kept.
- **What it prints:** a compact digest (~3k tokens). That digest is the only data you need to read.
  - the headline table: latest quarter vs QoQ and YoY, with tiers
  - revenue mix and nationality mix, plus record highs
  - incremental GPM, SG&A discipline and both profit bridges
  - Core PBT and Core PBT before ECL and one-offs, SG&A before ECL, and the selling-vs-admin split verdict
  - the ECL allowance by debtor group and receivable aging (from the notes), expenses by nature, dividend history and scenarios
  - YTD vs YTD, seasonality projections and the momentum score
  - red flags, checks and data gaps
  - the line ranges of the MD&A documents to read
- **What it writes:** `report/<T>_snapshot_data.json`.
- **If a CHECK fails:** stop and fix the data, the same way as in the finance sheet. Never write around it.

### Step 2: Read the quarter's reading pack (targeted)

The data step writes a reading pack for the quarter to `md/quarter/<BE>Q<q>/` and the digest lists it (`READ:` lines,
with token estimates). Read these files, not the combined files:

- `mda.md`: the quarter's MD&A (the English version when the company published one: about a third of the tokens)
- `oppday_slides.md`: the quarter's Oppday slides without disclaimer, agenda and ESG pages
- `oppday_qa.md`: only the transcript passages about revenue drivers, payors, prices, occupancy, costs, targets, capex
  and dividends; `[Lnnn]` is the line in the full transcript — open the full file only around a cited line when you
  need more context (`sed -n '<n-10>,<n+30>p' <transcript>`)

The pack holds only that quarter's documents, which also keeps a back-dated report free of hindsight. If the digest
prints `MD&A to read` line ranges instead, the quarter has no per-quarter MD&A file: read those lines of
`md/raw/combined_mda_all.md` (and re-run `fetch_set.py <T> --rebuild-md --ocr` if the MD&A is a scanned PDF).

Look for:

- why revenue changed (volume vs price, patient groups, payor mix)
- why costs and SG&A moved
- one-offs
- the working-capital and cash comments
- guidance and targets

If a topic you know is in the Oppday is missing from `oppday_qa.md`, add the term to `<stock>/md/oppday_keywords.txt`
(this stock) or `references/oppday_keywords.txt` (all stocks) and re-run `data` — then tell the user which term you added.

Cite as `quarter/2569Q2/mda.md:L120` or `quarter/2569Q2/oppday_qa.md:L141` (the transcript line number).

The Oppday files in the pack are the second source. **Before writing "the documents do
not explain" for a revenue line (OPD, IPD, SSO) or a margin move, search that quarter's Oppday** — it usually has the
reason and the volume/revenue-per-case figures (Q3/2567: IPD fell from the UC heart-surgery DRG payment, ~7,000 vs
8,400 billed, and stricter criteria — in Oppday, not the MD&A). Compare per-case figures with the same quarter only.

**Back-dated reports (`--quarter` earlier than the latest): no hindsight.** Use only documents released up to that
quarter's results (its MD&A, Oppday and earlier ones). Never write what happened later ("ต่อมาเกิดขึ้นจริง"), never
use a later MD&A to fill a gap, and treat later analyst notes as unavailable. The script already drops today's price and
later dividends from a back-dated pack.

**The reference analyst (คุณ Pop).** His way of reading is the method of this skill (playbook, casebook), so his notes
are read **first**, before any other outside source. The digest lists them under `REFERENCE ANALYST`:
`REFERENCE NOTE` files (`md/analyst_notes/pop_<BE>Q<q>.md`: his post for the quarter, the facts in it that the MD&A
lacks, errors already found) and `REFERENCE POST` lines (single Facebook posts). Use them to set the questions and
the order of the narrative, and record what he says in `pop_view`, each item with the result of checking it against
the filings (`confirmed`, `differs`, `not_in_filings`, `opinion`). **His figures never go into a table**: tier 1
still decides every number, and a difference is a row in `conflicts` with `second_src` in `md/analyst_notes/`.
Posts tagged `shared` or `news` are other people's material he re-posted: tier 2, not his view.

**Which notes the digest lists (file names matter).** `snapshot.py data` lists a note in `md/analyst_notes/` only when
its name carries the quarter as `<BE>Q<q>` (e.g. `pop_2569Q2.md`, `eaw_2569Q1_thaivi_deepdive.md`) and that quarter is
the report's quarter or the one before. A yearly or AGM note needs `_<BE year>_` in its name (`pop_2569_AGM.md`) and
is listed for the report's year and the year before. Any other file name is silently skipped. Only `.md` files are
read: a PDF, PPTX or video goes to `<stock>/etc/<source>/`, is condensed with `script/ingest/ingest_docs.py`, and
the summary is saved as a note. When the user says a note exists but the digest does not show it, check its name
first and tell the user how to rename it.

**More than one reference analyst.** A note whose first lines contain `- analyst: <name>` (e.g. `- analyst: คุณ Eaw`)
belongs to that analyst; a note without the line is คุณ Pop's. The digest names every analyst found
(`REFERENCE ANALYST (คุณ Pop, คุณ Eaw)`). Use each one's method the same way as คุณ Pop's, give every `pop_view`
row a `who`, and still check every figure against tier 1. `check` flags an analyst who has notes but no `pop_view` row.

`REFERENCE POST <date> [kind]` lines are single Facebook posts split by `scripts/split_fb_posts.py` (the user saves
a Facebook extraction such as `VIH_By_PoP.md`; run `python3 split_fb_posts.py <file.md> --stock-dir "$S"` once, and again
after each new extraction: it adds only new posts). The digest lists up to 12 posts written after this quarter's and
the previous quarter's results, `own` (his analysis) before `shared` (broker notes and articles he re-posted). Read
the `own` quarterly post first, then the ones on valuation, dividend, ownership and payor policy. In a back-dated
report, skip any post dated after that quarter's results + ~30 days (the date is in the line).

### Three tiers of sources

- **Tier 1 (trusted): what the company filed with SET/SEC** — financial statements, MD&A, Opportunity Day slides and
  transcript, 56-1, the SET factsheet. Every table and every figure in a plain narrative string comes from here.
- **Tier 2 (second source): `<stock>/md/second_source/`** — news, interviews, third-party presentations, video
  transcripts, broker notes. The user drops `.txt`/`.md` files there (or runs
  `python3 scripts/second_source.py --stock-dir "$S" --add <files>`). `snapshot.py data` builds
  `md/second_source/_pack/<name>.claims.md` (only the passages that state a figure or a key claim, with line numbers)
  and lists each as a `SECOND SOURCE` line. The owner's own records go here too: `visit_<YYYY-MM-DD>.md` (company visit) and
  `note_<YYYY-MM-DD>.md` (his note), listed with kind `visit` / `note` (templates in `assets/`). What management
  said on a visit is context and a lead to confirm in the next filing: external, never a table figure. Notes and posts in `md/analyst_notes/` belong to the reference analyst (above): read first, shown in their own section, figures still checked.

- **Tier 2, research papers: `<stock>/paper/` and `<AI_ROOT>/data/sector/Hospital/`** — broker papers on the stock and
  sector papers, turned into cards by `script/fetch_paper/paper_pack.py` (`_pack/INDEX.md`, `_pack/<name>.card.md`).
  The digest block `RESEARCH PAPERS` lists the cards that belong to this quarter: `BROKER PAPER` (dated from 15 days
  before the quarter ended to 135 days after), `SECTOR PAPER` (the last 12 months) and `INDUSTRY NOTES`.
  - **Read every card the digest lists before writing `outlook`, `risks` and `catalysts`.** They are where the industry
    picture comes from (tariffs and reimbursement rates, patient flows, competitors' openings, the sector's quarter).
  - Use what adds something as an external item: `{"text", "external": true, "src": "<card path>"}`. A figure that
    differs from the filings goes to `conflicts`. A broker's target price, rating or forecast is never carried over.
  - If nothing in them adds to the report, say why in `papers_note` (one sentence, shown in section 5). Citing none and
    leaving `papers_note` empty fails `check`.
  - `BROKER PAPER WITHOUT A DATE` lists cards that were not offered because they have no date. Tell the owner: one line
    per paper in `<stock>/paper/paper_dates.txt` (`<file name> = YYYY-MM-DD`) fixes it. Do not read them for a
    quarterly report.

- **Tier 3 (third source): `<stock>/md/third_source/`** — posts by other investors on a web board. The user's scrape
  of the ThaiVI thread sits in `<stock>/fetch_thaivi/<t>_posts_data.json` (older: `set/fetch_thaivi/`, `Thaivi_100P/`); `snapshot.py data` (or
  `python3 scripts/forum_posts.py --stock-dir "$S"`) turns it into `md/third_source/thaivi/<BE>Q<q>.md` (all posts
  written between that quarter's results and the next) and `<BE>Q<q>.top.md` (the short pack). The digest lists the
  packs for this quarter and the one before as `THIRD SOURCE` lines.

Rules for tier 3: it gives **leads and questions, never facts**. Read the `.top.md` last. For each point worth using,
look for it in tier 1 and cite tier 1. If tier 1 cannot confirm it, it may appear only as an investor's observation
(`"external": true`, `"src": "third_source/thaivi/<BE>Q<q>:<post id>"`), worded as such ("นักลงทุนในเว็บบอร์ดตั้ง
ข้อสังเกตว่า…"), and never with a number of its own. Put a forum claim in `conflicts` only when it is repeated by
several posters or would change the reading of the quarter. Ranking when sources disagree: tier 1 > tier 2 > tier 3.

Rules for tier 2:

1. Read the `.claims.md` files after the tier-1 reading pack, not before: form the view from tier 1 first.
2. A tier-2 figure never enters a table and never replaces a tier-1 figure. Use tier 2 for reasons, context and
   management colour that tier 1 lacks, as `{"text", "external": true, "src": "second_source/<stem>:L<n>"}`.
3. **Compare every checkable tier-2 claim with tier 1 and record the result in `conflicts`** (see
   `references/snapshot_narrative_schema.md`). A contradiction is reported, not hidden and not silently resolved: say what the
   second source claims, what the SET document shows, and the likely reason (different definition such as total vs
   owners' profit, a different date, long-term debt only vs all borrowings, rounding, or a plain error). Keep the
   tier-1 figure in the report. Also record claims that agree (`consistent`) for the two or three that matter most,
   and `unverifiable` for a material claim tier 1 cannot test.
4. Check the date of the source against the report quarter (no hindsight in a back-dated report; an old interview may
   be `outdated`, not wrong).
5. Auto-generated transcripts garble names and numbers ("19.8 8 ล้าน"). Do not quote a garbled figure; cite the line.

`LEAD` lines give two early signs of a phase change (D&A flat for N quarters; capital commitments from the notes,
current vs prior year-end) and `LOCATE` splits the YoY change in revenue and costs into parent and subsidiaries
(consolidated − separate). Use them in `angles` and when explaining a cost move.

`OPS` lines come from the Oppday slides (`<T>_ops_metrics.json`): for OPD and IPD, the YoY change in volume, in
revenue per bill, and the utilisation or occupancy rate. Use them to say whether revenue moved on **volume or on
price / case mix**, read through the margin ladder (playbook §1c). They raise flags of their own: `ops_<volume>` when
volume falls 10% or more YoY, `ops_<rate>` when a rate moves 5 points or more; each needs a sourced explanation like any
other flag. Before blaming demand for a lower rate, divide volume by the rate: the bed or capacity base may have
changed — the table shows that base as a `[คำนวณ]` row (beds = inpatient days ÷ occupancy ÷ days; OPD capacity per day
likewise; computed, not disclosed, so say so). An `OPS CHECK` line means one quarter's base does not fit the quarters on
both sides (a slide that used another year's bed count); the script takes an older deck's figure when that one fits and
says which. Companies restate these series; the script keeps only figures that agree with the newest deck and lists the
rest under `superseded` — never join the two. `charts` in the same file holds the other slides (revenue by payor, by
centre) with their page; cite them as `oppday_<CE>_Q<q>_<id>.pdf:p<n>`.

Text is often damaged in these files: dropped tone marks, `d`/`c`/`f`/`v` glyphs in place of Thai letters. Read through it.

### Step 3: Write the narrative JSON

Write `report/<T>_snapshot_narrative.json`, following `references/snapshot_narrative_schema.md` and the rules in `references/analysis_rules.md`. In short:

- **Answer the playbook's four questions first:** is the growth real (and is the base normal)? are fixed costs still flat?
  which business phase? what does it mean for next quarter, the dividend and the valuation? The digest's `PHASE`,
  `COST BAND`, `BASE` and `PRICE` lines are the script's answers; write `angles` (2–4 items), then `expectation` from the
  `EXPECT` lines (price = valuation + narrative; narrative = expectation − disappointment) and `peers_notes` from the
  `PEER` lines. Let `headline`,
  `summary` and `outlook` follow from them. Name the cause of an abnormal base from the documents or analyst notes.

- Explain **why**. The numbers are already in the tables, so do not restate every one.
- Every claim that uses a number not in the digest needs `"src": "MDA_Year2569_Q2:L4781-4795"`. A number from outside the company's documents needs `"external": true`; it is shown in dark red and listed in section 5.
- Write an entry in `explanations` for every red-flag id in the digest.
  - If the documents only partly explain it, say so and set `"status": "partial"`.
  - If nothing explains it, leave it out. The report then shows `🚩 Red Flag (Unexplained)`, which is the correct outcome.
- Respect the rule outcomes the digest already computed. Examples:
  - If incremental GPM is `low`, do not claim strong operating leverage.
  - If SG&A is `rigid`, do not praise cost discipline.
  - If selling is not reported separately, do not call it a cost saving.
  - If the split verdict is `genuine_saving`, do not call the selling/admin move a reclassification.
  - Never name the type of debtor behind an ECL charge unless a document does.
- A flag's "statement hint" in the digest is a fact from the filing, not an explanation. Cite the note lines it points to, and
  keep the flag `partial` until the MD&A or Oppday gives the reason.
- One-offs in the assumptions file should carry `amount_pretax` (or "<x> ลบ. ก่อนภาษี" in the label) so Core PBT before
  one-offs is right; add `"line": "other_income"` for a one-off booked outside GP/SG&A. If a company books ECL outside admin,
  set `"ecl_line"` in the assumptions file.
- Outlook: use the statistical seasonality table and the documents. Add no occupancy, bed or rate figures unless a document gives them.

### Step 4: Check, render, look

```bash
python3 scripts/snapshot.py check  --stock-dir "$S" --ticker VIH     # must end with RESULT: CLEAN ✅
python3 scripts/snapshot.py render --stock-dir "$S" --ticker VIH
```

- `check` lists each number it cannot match to the pack, a source or an external item. Fix each one: correct the number, add its `src`, or mark it `external`.
- `render` writes a new version and never overwrites an old one.
- Open the `.md` and skim sections 1 and 5 before delivering.

### Step 5: Deliver

Give the user the `.md` and `.html` paths and reply briefly:

1. the headline and momentum score
2. 3–4 bullets on *why* revenue, margin and profit moved
3. the unexplained red flags and data gaps, stated honestly
4. what to watch next quarter

## Batch / no-agent runs

`python3 scripts/snapshot.py run VIH PR9` (or `run -f input1.txt`, `--root <Thstock>`) builds the data and renders
each ticker. When no narrative file exists it writes a labelled automatic narrative from the numbers only; catalysts
and risks then say "ต้องอ่าน MD&A".

The user's runner `C:\ai\script\stock_snapshot\claude\run_stock_snapshot.py` wraps this command. Output goes to `Thstock/<T>/report`.

When the user later asks for a full snapshot of a stock that was run this way, do steps 2–4.

## Sections of the report

(Section 1 now also has two script boxes — มุมมองนักลงทุน and ราคา = มูลค่า + เรื่องเล่า — and section 2.9 is the peer table,
computed from each peer's own `report/<T>_financials.json`; peers without the file are listed as missing.)

1. **Executive summary:** headline, momentum score, summary bullets, flash table (Q py / Q pq / latest, YoY, QoQ, tier, incl. Core PBT
   and Core PBT before ECL and one-offs), charts.
2. **Operations:**
   - 2.1 revenue mix: OPD/IPD/SSO/eliminations, plus nationality for Category-1 hospitals
   - 2.2 incremental GPM and the share of the cost increase that is D&A
   - 2.3 SG&A, SG&A before ECL, the selling-vs-admin split verdict, 📉 cost record lows, the ECL allowance by debtor group and the receivable aging
   - 2.4 profit bridge, YoY and QoQ (it always closes)
   - 2.5 cash and cash flow
   - 2.6 YTD vs prior-year YTD (with Core PBT before ECL and one-offs)
   - 2.7 expenses by nature: YTD vs prior-year YTD from the filing (n/a with the reason when the interim statements do not
     disclose a bucket) plus the last two annual notes as % of revenue
   - 2.8 dividends: DPS/EPS/payout history, cash and net cash per share, DPS scenarios at +0/+5/+10 pt payout
3. **Outlook:** a statistical seasonality table with the method stated, plus document-based drivers, catalysts and risks.
4. **Takeaways:** the momentum-score components (a transparent rule table), takeaways and a watch-list.
5. **Red flags and verification:**
   - each flag, explained ✅, partly explained ⚠️ or unexplained 🚩
   - narrative-check issues
   - data gaps and restatements
   - external items in dark red
   - an appendix of source lines

## Updating for a new quarter

Refresh `md/raw` with the new filing and MD&A, then run `data`. The extractors re-run because the raw files are newer. Then write a new narrative (keep the old one for comparison under another name), `check`, and `render`.