# Deep-dive narrative JSON (`report/<T>_deepdive_narrative.json`)

Items use the same format as in the snapshot:

- **Plain string:** every number in it must be in the digest.
- **Sourced:** `{"text", "src"}`.
- **External:** `{"text", "external": true, "src"?}`. Shown in dark red and listed in section 10.

| key | section | content |
|---|---|---|
| `headline` | 0 | one line on the multi-year story |
| `summary` | 0 | 4–6 items |
| `transformation` | 1 | what changed structurally: returns, margins, cash |
| `mix_notes` | 2 | revenue mix and cost-structure reasons |
| `capacity.rows` | 3 | `{"hospital", "location", "beds_registered", "beds_operating", "opd_rooms", "occupancy", "role", "src"}`; **src is required** |
| `capacity.history` | 3 | `{"year", "beds", "occupancy", "patient_days", "note", "src"}`; **src is required** |
| `capacity.notes` | 3 | the document's date, what is not disclosed |
| `expectation` | 0 (box "ราคา = มูลค่า + เรื่องเล่า") | 2–3 items: what P/E/PEG already expects, is the harvest story intact or fading, what could disappoint or surprise |
| `pop_view` | 0 (table "มุมมองของคุณ Pop (นักวิเคราะห์อ้างอิง)", after the summary) | 3–8 objects `{"text", "src", "verdict"}`: what the reference analyst says about this stock, in his order. `src` = `md/analyst_notes/<file>`; `verdict` = `confirmed` (the filings say the same), `differs` (also add a `conflicts` row), `not_in_filings` (cannot be checked yet) or `opinion` (a reading, not a fact). Own notes and posts only. Leave the key out only when the digest has no `REFERENCE ANALYST` block |
| `conflicts` | 10 (table) | claims of the reference analyst or of tier 2–3 compared with SET documents: `{"verdict", "topic", "second", "second_src", "primary", "primary_src", "note"}`; `verdict` = `conflict`, `definition`, `outdated`, `consistent`, `unverifiable`. Same format as the snapshot. Its numbers are not number-checked; both sources are required instead |
| `pivot` | 0 (box "จุดชี้ชะตา") | `{"title", "if_fails": [items], "if_works": [items], "watch": [items]}` — the **one** point specific to this stock that is both its largest risk and its largest opportunity (VIH: the new hospital). Size both sides in baht where a document allows; `watch` = the signs and the document that will show each. Not the generic risk list. If present it needs title, if_fails and if_works |
| `team` | 5 | items on the medical team and doctor pipeline; usually tier 2, so mark `external` with `src` |
| `pending` | 0 (count) and 10 (table) | `[{"question", "why", "where", "raised"}]` — what the documents could not answer; never fill the gap with a guess. Carry every open item into the next deep dive. Needs question and why |
| `lifecycle.phase` | 4 | item: agree with or argue against the rule result, with evidence |
| `lifecycle.reasoning` | 4 | items; reconcile the capex rule with the operating-leverage phase (4.1) |
| `case_studies` | 4 | `[{"title", "items": [...]}]` |
| `moats`, `peers_notes` | 5 | items |
| `management` | 6 | capital allocation, dividend policy |
| `guidance` | 6 | `[{"guidance", "when", "actual", "status", "src"}]`; `actual` quotes pack numbers; **src is required** |
| `sector_view.position` | 7.1 | 2–4 items: where the stock stands against the core median in each window of the digest's `SECTOR & POSITION` block (pre-COVID, since 2019, post-COVID, latest half-year) and **why** (its own drivers, not the sector's). Required whenever the digest has that block |
| `sector_view.leading` | 7.2 | items: leading indicators found in documents that show a turn before the reported numbers do (SSO insured counts by hospital, new beds or wards opening, Oppday volume/occupancy, guidance raised or cut, insurer or payor changes, new supply in the catchment). **Each needs a `src`**; tier 2–3 also `external` |
| `sector_view.watch` | 7.2 | items: what to watch next and which document will show it first; a figure derived here is labelled [คำนวณ] |
| `tailwinds`, `headwinds` | 7.3 | items |
| `roadmap` | 8 | items; projects only from documents |
| `scorecard` | 9 | `{"posture", "moat_rating" (0–10), "moat_why", "capital_allocation_view"}` |
| `verdict` | 9 | 2–3 items |
| `pop_checklist` | 14.1 | `{"<id>": {"status": "pass"/"fail"/"unsure", "why": {"text", "src"}}}` for the **document** items only: b1 b2 b3 b4 b6 (business), c4 (advantage), k3 (break-even), t1 (temporary reason). `src` is required. Unanswered items show ⬜ and are not an error |
| `pop_owner` | 14.1 | `{"<id>": {"answer", "note"}}` for the **owner** items (b5, p3, t2, t3, t4, g1–g3). **Write only what the owner told you; never answer for them** (not investment advice). Unanswered items show 👤 |
| `explanations` | 10 | `{"<flag id>": {"text", "src", "status": "partial"?}}` |
| `external` | 10 | optional explicit rows `{"item", "value", "source", "status"}` |

`check` enforces six things:

- the number rules, on everything except `capacity.rows`, `capacity.history` and `guidance`, which must carry a `src` instead
- a `src` on every capacity and guidance row
- an explanation for every flag
- `pop_view`: present when the stock has reference-analyst notes; each row has `src` in `md/analyst_notes/` and a valid `verdict`; `differs` has its `conflicts` row
- `sector_view`: `position` present when the digest has `SECTOR & POSITION`; every `leading` item has a `src`
- source tiers: an item whose `src` is a second/third source or a paper card is `"external": true`; each `conflicts` row has topic, second, second_src, primary, primary_src

See `assets/VIH_deepdive_narrative_example.json`.

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


## `report/<T>_hospitals.json`: block `sso` when the company gives no quota per hospital

`sso.years` (quota and insured per hospital, the VIH layout) is optional. A company that discloses other series can use
`sso.tables`: a list of `{"title", "tier" (1 = company document, 2 = outside the company), "cols": [...],
"rows": [[label, v1, v2, ...], ...], "bold": [row numbers], "src", "note"}`. Section 3 prints each table as given, with
its source line; a tier-2 table is labelled "แหล่งที่ 2 (ไม่ใช่เอกสารบริษัท)". Nothing is computed from these tables, so
put a computed row in only with "[คำนวณ]" in its label. `"years": {}` is allowed when the company does not publish
revenue by hospital. Official provincial statistics (insured persons by hospital) go in as tier 2, with the extract
saved under `md/second_source/` so the page of every figure can be found again.


## `year_events`: what happened each year (section 2.1)

Section 2.1 puts each fiscal year's revenue and normal-profit growth next to the events that explain them. Three
sources fill it automatically: payor rule changes with the company's own impact (`data/sector/Hospital/payor_events.json`),
the one-offs in the assumptions file, and the COVID window plus the first year after it. Add what only documents
show in `year_events`:

```json
"year_events": [
  {"year": "2567", "text": "ลงทุนในบริษัท วัฒนาเวชวิวัฒน์ จำกัด (ถือ 100%) เดือนพฤศจิกายน 2567", "src": "งบการเงินปี 2568 หมายเหตุเงินลงทุนในบริษัทย่อย"},
  {"year": "2569", "text": "...", "src": "MD&A Q2/2569", "external": false}
]
```

- `year` is the Buddhist-era year; the YTD row shows the current year's items.
- One event per item, with its number and `src`. Outside the company's documents: `"external": true` (shown red).
- A payor change that affects several hospitals goes in `payor_events.json` (with `impacts` per ticker), not here, so
  every stock and the snapshot read it too.
- Read each year's growth with its own row and the row before (the base) before calling it good or bad.
