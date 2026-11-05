# Narrative JSON (`report/<T>_snapshot_narrative.json`)

You write this file. The scripts compute and draw every table; the narrative adds *reasons*.
Everything is Thai, and every key is optional. A section you leave empty shows nothing, or "ต้องอ่าน MD&A" for catalysts and risks.

## Item format

An item can take three forms:

- **A plain string:** use it when every number in it comes from the digest.
- **A sourced object:** `{"text": "...", "src": "MDA_Year2569_Q2:L4781-4795"}`. Use it when the text quotes a document or a number that is not in the digest. For `src`, use the MD&A document name and line numbers from `combined_mda_all.md`. You can also cite an Oppday file with lines, or a financial-statement line from the digest's source appendix.
- **An external object:** `{"text": "...", "external": true, "src": "news/analyst ..."}`. Use it for anything that is not from the company's own documents. It is shown in dark red (#8B0000) and listed again in section 5.

## Keys

| key | shown in | content |
|---|---|---|
| `headline` | top of section 1 | one line: what happened and the main reason |
| `summary` | section 1 bullets | 3–5 items: revenue driver, margin driver, profit bridge reading, main weakness |
| `angles` | investor-angle box in section 1 | 2–4 items in คุณ Pop's framing: which business phase and why (fixed costs flat → harvest), whether this quarter's and next quarter's YoY base is abnormal (epidemic year, SSO/UC rate cuts, one-offs) and what that implies for next quarter's growth, and the price/volume sensitivity (e.g. a price rise of X% ≈ Y% of profit). Base the phase and base verdicts on the digest's PHASE / BASE lines; name the cause of an abnormal base from the MD&A, Oppday or analyst notes |
| `pop_view` | table "มุมมองของคุณ Pop (นักวิเคราะห์อ้างอิง)" in section 1 | 2–6 objects `{"text", "src", "verdict"}`: what he points to this quarter, in his order. `src` = `md/analyst_notes/<file>`; `verdict` = `confirmed` (the filings say the same), `differs` (also add a `conflicts` row), `not_in_filings` (cannot be checked yet) or `opinion` (a reading, not a fact). Own posts only, not what he re-posted. Leave the key out when there is no note for the quarter |
| `expectation` | box "ราคา = มูลค่า + เรื่องเล่า" in section 1 | 2–3 items: what the P/E/PEG already expects, whether the quarter beat or missed the trend (digest `EXPECT`), whether the story (phase) is strengthening or fading, and what could disappoint or surprise next. No target price, no buy/sell |
| `peers_notes` | 2.9 peer table | 1–3 items: how the stock compares with its group this quarter (growth, leverage, DSO, P/E) and why, from the `PEER` lines |
| `revenue`, `mix_notes` | 2.1 | why OPD/IPD/SSO, or Thai/foreign, moved (volume, intensity, payor, country) |
| `op_leverage` | 2.2 | why incremental GPM is what it is (fixed-cost absorption, D&A from new capacity, mix) |
| `sga` | 2.3 | SG&A causes, normalisation (one-offs), ECL context |
| `cash` | 2.5 | cash vs deposits, receivables/DSO (use the aging table in 2.3), capex |
| `nature` | 2.7 | what the disclosed nature items say (D&A vs revenue, management pay, ECL); say plainly which buckets the interim statements do not disclose |
| `dividend` | 2.8 | payout trend and cash per share; any DPS figure is a scenario from the table, never a forecast |
| `explanations` | section 5 | `{"<flag id>": {"text", "src", "status": "partial"?}}`, one per red-flag id in the digest |
| `outlook` | 3.1 table | `{"2026Q3": {"text", "src"?}, ...}` — keys are CE quarters from the seasonality table |
| `catalysts`, `risks` | 3.2 / 3.3 | document-based items; `external` for anything else |
| `takeaways`, `watchlist` | section 4 | 2–4 items each |
| `conflicts` | warning box under the headline + table in section 5 | second-source claims compared with SET documents: `{"verdict", "topic", "second", "second_src", "primary", "primary_src", "note"}`. `verdict` = `conflict` (shown in the warning box), `definition` (same fact, different measure), `outdated`, `consistent`, `unverifiable`. `second_src` = `second_source/<file stem>:L<n>` or, for a forum post, `third_source/thaivi/<BE>Q<q>:<post id>` |
| `papers_note` | one line in section 5 | a sentence saying why none of the research-paper cards the digest listed is used. Needed only when no item cites a card (`src` = `paper/_pack/<name>.card.md`, `data/sector/...` or `industry_notes.md`) |
| `external` | section 5 table | optional explicit rows `{"item", "value", "source", "status"}` |

## What `check` enforces

- Every number in a plain string must exist in the data pack at the precision written (`9.2%` matches 9.2; `9.48%` does not).
- Amounts and percents are checked separately.
- Years, quarter numbers and small counts (≤ 12) are allowed.
- Text inside `[...]` is skipped, so `[คำนวณ: ...]` formulas may restate their inputs.
- Numbers in sourced or external items are not checked, but the source must exist.
- An item whose `src` points into `second_source/` must be `"external": true`. Each `conflicts` row needs all of topic, second, second_src, primary, primary_src.
- Every red flag needs an explanation, and every explanation needs a `src`.
  Flags named `ops_...` come from the Oppday slides (volume −10% YoY or more; a rate moving 5 points or more) and are explained the same way.
- A flag's grey "ข้อมูลจากงบ" hint (ECL note, selling-vs-admin split, receivable aging) is computed from the statements. It helps you
  write the explanation but is not one: a flag stays ⚠️ partial until a document (MD&A, Oppday, a note) gives the reason.

The check is a guard, not a proof. It can miss a number that happens to equal a pack value, so still write only what the documents support.

## Example

`assets/VIH_snapshot_narrative_example.json` is a complete VIH Q2/2569 narrative that passes `check`. Use it as a model for tone and length. Don't copy its content.

## More than one reference analyst

A stock may carry notes from more than one reference analyst (RJH: คุณ Pop and คุณ Eaw).

- A note file in `md/analyst_notes/` names its author on a line `- analyst: คุณ Eaw` within its first 12 lines. A file
  without that line, and every post under `fb/`, belongs to คุณ Pop.
- The digest then lists the names and marks each note. Give every `pop_view` row a `who` (the name as the digest prints
  it) and write at least one row for each analyst; `check` reports an analyst who has notes but no row.
- A `conflicts` row may carry `who` too. The report then shows a column "นักวิเคราะห์" and the heading names all of them.
- A talk where several people speak (a recorded Q&A) is the analyst's own view only for the parts he says himself.
  Passages whose speaker the transcript does not name stay tier 2 (`second_source/...`), not `pop_view`.
- Date the note: put the period in the file name (`eaw_2569Q1_...md`) so a back-dated report leaves it out.
