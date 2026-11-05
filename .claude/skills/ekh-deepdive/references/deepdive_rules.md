# Deep-dive rules

## COVID base year

Thai hospitals had abnormal revenue and profit in CE 2020–2022 (BE 2563–2565): COVID testing, vaccines and hospitels. VIH, for example, had ROE of 62.9% in 2564.

- **Full-period CAGR:** still reported.
- **Trend CAGR, lifecycle metrics and scorecard growth/margin:** measured from the first fiscal year after 2022 that is at least two years before the latest year, and never from a COVID year when a later one exists.
- **Stating the base:** the report prints the base year. Your narrative must use the same base, or say which one it uses.

## Business phases — ONE vocabulary (rule)

**Canonical names (decided 4 Nov 2026, from `GLOSSARY.md`; defined once in `stock-snapshot/scripts/snapshot.py` as `PH_*`):**
ระยะลงทุน (Investment) → จุดต้นทุนพีค (Cost peak) → ระยะเก็บเกี่ยว (Harvest) → ระยะเก็บเกี่ยวช่วงท้าย (Late harvest) →
ระยะอิ่มตัว (Saturation). Re-investment is not a phase: it is a new Investment phase starting (the dormitory loop).
"Margin squeeze", "cost-cut profit" and "revenue not growing" are **warning flags** (`FLAG_*`), never phases: the phase
shows "ยังไม่ระบุช่วง" until the cause is found. Do not write "Phase 1–4", "Inflection" or "Golden Harvest" anywhere.

Two lenses use these names. They answer different questions and can differ — say both and explain.

### Lens A — investment cycle (is the company building?)

Uses capex/D&A averaged over the last two years (CD), plus the D&A, revenue, core-NP and GPM trends from the base year.

| phase | rule |
|---|---|
| Investment | CD ≥ 1.5 and (D&A growing faster than revenue, or GPM falling); also CD ≥ 1.2 and GPM rising while D&A still grows faster than revenue |
| Cost peak | CD ≥ 1.2, GPM rising, and D&A growing no faster than revenue. Only a candidate here: confirm it with the quarterly signals in `stock-snapshot` (`LEAD: จุดต้นทุนพีค`: D&A flat ≥ 4 quarters AND capital commitments down > 30%) |
| Harvest | CD < 1.2, GPM rising, core NP growing faster than revenue |
| Late harvest | CD < 1.2 and GPM falling (a new project starting = a new Investment phase) |
| Saturation | CD < 1.2, GPM not falling, core NP not faster than revenue, and revenue and core-NP CAGR both < 2% (NEW cut-off `SAT_GROWTH`, tune with the owner) |
| Transition | anything else |

The rule looks backward. A new hospital announced but not yet in capex does not change it. Say so in the narrative and cite the announcement.

### Lens B — profit phase of the existing business (investor lens, คุณ Pop)

Computed per fiscal year (section 4.1): revenue growth, Core PBT growth (before ECL and one-offs), their ratio,
incremental GP ÷ incremental revenue vs average GPM, SG&A growth.

| phase / flag | rule |
|---|---|
| Investment | profit grows < 0.8× revenue and capex ≥ 1.5× D&A: building ahead of revenue |
| Harvest | profit grows ≥ 2× revenue and incremental GP margin > average GPM: fixed costs flat |
| Late harvest | profit grows 0.8–2× revenue: leverage fading, P/E de-rate risk |
| Saturation | revenue flat/down, profit within ±5%, capex < 1.2× D&A |
| flag: มาร์จิ้นถูกกด | profit grows < 0.8× revenue without heavy capex: find the cost or price cause (phase stays "ยังไม่ระบุช่วง") |
| flag: กำไรโตจากลดต้นทุน | revenue flat/down, profit up > 5% |
| flag: รายได้ไม่โต | revenue flat/down and not Saturation (profit down > 5%, or capex high) |

Cost peak is **not** decided per year in Lens B: it needs quarterly D&A and the commitments note.

COVID years are shown but not used for the verdict. Lens A describes the **investment cycle**; Lens B the **profit phase
of the existing business**. They can differ — e.g. VIH: Lens A "Cost peak" or "Investment" (new hospital being built)
while the existing hospitals are in Harvest on Lens B. Say both and explain.

## Reference analyst (คุณ Pop): method first, figures checked

Decided 6 Oct 2026. His way of reading a hospital stock is the method of this report, so his notes and own posts
(`<stock>/md/analyst_notes/`, digest block `REFERENCE ANALYST`) are read **before** the company's documents and decide
which questions the report answers and in what order. His figures are not taken on trust:

- Each point goes into `pop_view` with a verdict: `confirmed`, `differs`, `not_in_filings`, `opinion`.
- `differs` → the filing's figure is used everywhere, and both sides go into `conflicts`. Never average.
- `not_in_filings` → may be mentioned as his statement, never as a fact of the report; add it to `pending` when it matters.
- Posts he only shared, and undated posts, are not his view: tier 2, or not used.
- A back-dated deep dive reads only posts dated up to 135 days after its last quarter (the script filters them).
- His target prices and buy/sell opinions are never carried into the report.

## Price = valuation + narrative

Narrative = expectation − disappointment. The digest's `VALUATION` line gives P/E on TTM normal profit and PEG (on TTM
growth and on the CAGR from the base year); peers get P/E/PEG from their own factsheets when the price date is within
150 days of their latest quarter. Write `expectation` (2–3 items): what the price already assumes, whether the phase is
intact or fading, what could disappoint or surprise. No target price.

## Quality scorecard (0–10 each, averaged)

| component | points |
|---|---|
| ROE latest FY | ≥20% 10, ≥15% 8, ≥10% 6, ≥5% 4, else 2 |
| revenue CAGR from base | >10% 9, >5% 7, ≥0 5, else 2 |
| balance sheet | net cash and D/E < 0.3: 10; net cash: 8; D/E < 1: 6; else 3 |
| CFO/EBITDA average of 3 years | ≥0.85 9, ≥0.75 7, ≥0.6 5, else 3 |
| ROIC (+1 if payout 40–90%) | ≥15% 9, ≥10% 7, ≥6% 5, else 3 |
| GPM change from base | > +2 pt 9, > 0 7, > −2 pt 5, else 3 |

The scorecard measures financial quality; it is not a moat rating or a recommendation. The moat rating is your judgement, with a stated reason.

## Peers

- **Where the numbers come from:** each peer's own `report/<T>_financials.json`, run through the same definitions. Nothing is typed in by hand.
- **Peer growth:** the CAGR uses the same post-COVID base rule.
- **Missing peers:** if a peer the user cares about is missing, say so and suggest running `run_finance_sheet.py <peer>`. Do not fill it from memory or websites. If you must mention an outside figure, mark it `external`.

## Never estimate

These appear only when a document gives them, with `src`:

- beds and OPD rooms
- occupancy and patient days
- patient counts and SSO members
- payment rates (AdjRW)
- project capex and beds
- market share
- population and aging statistics

When the latest document is old (e.g. the One Report 2565 is the newest in the folder), use it and state its date.

## The make-or-break point and open questions

- **`pivot`:** name the one point on which the next few years turn — the thing that is both the largest risk and the
  largest opportunity, specific to this stock (VIH: the new hospital pulls profit down if it does not fill, and opens
  a premium market if it does). Argue both sides in one place and size each in baht from documents (IFA report, a listed
  analogue's ramp-up). Generic risks (economy, regulation) stay under headwinds.
- **`pending`:** when no document answers a question that matters (e.g. how much new supply is arriving in the stock's
  own area), do not guess and do not drop it. List it with why it matters and where the answer could come from.
- **Industry:** start `tailwinds` / `headwinds` from `<AI_ROOT>/data/sector/Hospital/industry_notes.md` (dated tier-2
  notes shared by all hospital deep dives); every item taken from it is `external` with its source and date. Then test
  the stock against it: why does this one grow faster or slower than the group, and is it adding to the supply wave?

## Sector and the stock's position (section 7, owner's alpha question, 10 Oct 2026)

Source: `<AI_ROOT>/data/sector/Hospital/sector_trend.json`, built by `python3 script/sector/sector_trend.py` from the
Jitta factsheets of the listed hospitals (core panel of 17; RAM, PRINC, CMR, VIBHA, THG left out for structure changes).
The **median** is the benchmark, not the total, because BDMS is more than half of the group's revenue.

- **7.1 Position:** the stock's revenue CAGR vs the core median and its rank in four windows (pre-COVID 2016–19, since
  2019, post-COVID base to latest, latest half-year YoY), plus its payor group. A sector growing slower than before is not
  a reason to stop; the question is whether this stock can keep beating the median and why.
- **7.2 Early signals (computed):** acceleration (recent window vs older), quarters beating the median YoY (count and
  trend over six quarters), half-year net margin vs a year earlier (half-year, so one quarter's one-off does not decide
  it), and rank move. Each gets better / worse / neutral.
- **7.2 Leading indicators (yours):** the computed signals are still reported numbers. The edge is seeing the turn first,
  so look in the documents for what moves **before** revenue: SSO insured persons by hospital, beds/wards opening, Oppday
  volume and occupancy, guidance changes, payor rule changes, competing supply in the catchment. Each with `src`.
- Jitta figures here are tier 2 for context; company tables still use the filings. If the json is older than the
  stock's latest quarter, re-run `sector_trend.py` first.

## Red flags

Flags are raised on the latest fiscal year vs the prior one when:

- a key line (revenue, GP, SG&A, NP, core NP, D&A, capex, receivables, cash, CFO) changes by more than 15% and by at least 5 THB mn, or
- an expense-by-nature share of revenue moves by at least 1 pt.

Each flag needs a sourced explanation, marked `partial` if the explanation is incomplete. If none is given, it stays 🚩.
