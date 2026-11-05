# Framework — what belongs in the snapshot and what belongs in the deep dive

Agreed with the user on 5–6 Oct 2026. One data layer, two reports. The snapshot answers **"what changed this quarter
and why"**; the deep dive answers **"what is this business, how much room is left, and what could break it"**.

| | Snapshot | Deep dive |
| :--- | :--- | :--- |
| Horizon | this quarter vs last year and last quarter | 5–10 years back, about 3 years ahead |
| Cadence | every quarter, after results | once a year, or when the thesis changes |
| Output | reasons, flags, what to watch next quarter | thesis, the make-or-break point, open questions, value |
| Carrier | `<T>_Snapshot_Report_<Q>` | the finance model, updated and renamed as the Deepdive file, with the analysis on top of it |

## Rules for placing a topic

1. Anything the company reports **every quarter** goes in the snapshot. The Oppday deck is quarterly, so the
   dimensions of revenue it shows are snapshot material: payor, OPD/IPD, centre, volume, utilisation, revenue per bill,
   and for other hospitals whatever they show instead (foreign patients by nationality, branches).
2. Anything that changes slowly or needs a comparison across companies goes in the deep dive.
3. The same number may appear in both with a different question. Occupancy in the snapshot: how far did it move from
   last year. In the deep dive: how far is it from break-even and from full.
4. A snapshot flag that repeats is a question for the deep dive.

## Topic map

| Topic | Snapshot | Deep dive | Data |
| :--- | :--- | :--- | :--- |
| Revenue by payor, OPD/IPD, centre | this quarter | 5-year mix trend | `<T>_mda.json`, `<T>_ops_metrics.json` (charts) |
| Volume, utilisation, revenue per bill | volume or price drove revenue; flags | distance from break-even and full; when to expand | `<T>_ops_metrics.json` |
| Margin and fixed cost | incremental margin | phase of the cycle, margin ceiling | `<T>_financials.json` |
| Receivables, ECL, cash | flags | earnings quality | `<T>_financials.json`, notes |
| Parent vs subsidiaries | who caused the change (`LOCATE`) | revenue and profit **by hospital**, from the annual report | financials; One Report |
| Investment projects | progress and commitments, briefly, as the Oppday states them | size of the opportunity against a listed analogue; first-year loss | Oppday; notes; IFA report |
| Make-or-break point | none | **one** point specific to this stock, both sides sized (see below) | finance model; Oppday; IFA report |
| Medical team and doctor pipeline | none | who brings the doctors, and what a new building cannot buy (tier 2, external) | interviews, talks, Oppday |
| Risks | what to watch next quarter | the risks of this stock; what would falsify the thesis | — |
| Industry and competitors | none (peer table of the same quarter at most) | demand, supply, a feared threat tested against history; **new supply in the stock's own area** | peers' financials; `data/sector/Hospital/industry_notes.md` |
| Open questions | none | what the documents could not answer, kept as `pending` to follow up | — |
| Value | P/E now and what the price expects | valuation matrix and sensitivity (finance model) | finance model |
| Tier-2 and tier-3 sources | the quarter's `conflicts` table | conflicts that touch the thesis | `md/second_source`, `md/third_source`, `paper/_pack` |

Left out on purpose (user, 5 Oct 2026): a management and related-party section.

## The deep dive is built on the finance model

The deep dive **updates `<T>_finance_model` first**, then analyses from it; the workbook is delivered under the
Deepdive name with the analysis on top (cover and executive summary), so numbers and reading stay in one file.
Revenue by subsidiary hospital comes from the annual report (56-1 One Report), not from the quarterly filings.

## The make-or-break point (จุดชี้ชะตา)

Every deep dive names **one** point on which the stock's next few years turn. It is not the generic risk list
(economy, regulation, competition): those go under headwinds. It is the thing that is at once the largest risk and
the largest opportunity, and it is specific to this company.

Write it as two sized cases and a watch list:

- **If it fails:** what it does to group profit, in baht and as a share of current profit, and for how long
  (losses, depreciation and interest the existing hospitals must carry).
- **If it works:** what it adds that the company does not have today (a new market, a higher rung on the margin
  ladder, a new catchment), again sized where a document allows.
- **What will tell us, and when:** the two or three observable signs, each with the document that will show it.

Example, VIH: the new hospital. If it does not fill, its first-year loss, depreciation and interest pull down a
profit base of about 437 mn baht; if it works, it opens a premium market the existing four hospitals do not serve
and becomes the next S-curve. The same project is the top risk and the top growth driver, so it is argued once, in
one place, with both sides. Size it with the IFA report and a listed analogue's actual ramp-up; never with a guess.

For a stock with no such project the point may be a payor (an SSO rate decision for an SSO-heavy hospital), a
nationality (a hospital living on one foreign market), or a key contract. If there truly is none, say so.

## Open questions (`pending`)

When the documents cannot answer something that matters, the deep dive does not fill the gap and does not drop the
subject. It lists the question under **pending**, with why it matters, where the answer could come from, and when it
was raised. A pending item stays in every later deep dive until a document closes it.

Example, VIH: "How much new private-hospital supply is arriving in Samut Sakhon and western Bangkok?" The sector
papers say competition is local and name the EEC; none covers VIH's area. Matters because VIH is itself adding
supply there. Possible sources: Ministry of Public Health licence data, competitors' Oppday, the IFA report.

## The reference analyst (คุณ Pop)

Decided with the user on 6 Oct 2026. His **method** is level 1: it is how every report reads a quarter (playbook,
casebook), his notes in `md/analyst_notes/` are read first and get their own section ("มุมมองของคุณ Pop"), apart from
brokers and news. His **figures** are not level 1: a number from a post is checked against the filings and shown with
the result; when they differ the filing stands and the difference is listed. What he only re-posted (broker notes,
news) stays tier 2.

## Second and third sources

What separates tier 2 from tier 3 is whether the speaker is **named and answerable** for the content, not the channel.
Tier 3 is only anonymous material (the forum). The owner's own company-visit notes and manual notes are tier 2: save
them as `md/second_source/visit_<YYYY-MM-DD>.md` and `note_<YYYY-MM-DD>.md`; `second_source.py` picks them up, marks
them external and lists them with kind `visit` / `note`. News by a named publisher is tier 2; news the company itself
filed with SET (`set/news`) is tier 1. A YouTube clip takes the tier of who speaks: the company's Oppday or AGM is
tier 1, a named analyst is tier 2.

Tier 1 decides every figure. Tier 2 now includes **broker papers**, used to cross-check. Coverage is thin for VIH
and RJH and deep for CHG, BDMS, PR9 and BH; the large caps' papers are the guide to the industry picture (demand,
payor policy, capacity), read with their date and marked external. `script/fetch_paper/paper_pack.py` turns each
paper folder into cards and an index (`<folder>/_pack/INDEX.md`): read the index, then only the cards needed. The
shared, dated summary of the industry is `data/sector/Hospital/industry_notes.md`.

## The margin ladder (how to read any revenue dimension)

The owner's standing principle (full text: `analyst_playbook.md` §1c). Applied in every snapshot and deep dive; changed
only when a document shows otherwise, and then with the evidence shown and the owner told.

- By service, margin rises from OPD to IPD.
- By payor, margin rises from SSO to insurance to self-pay (cash is only slightly above insurance).
- A complex case brings more revenue per head than a simple one.
- SSO is also a funnel: more SSO patients are a channel to self-pay revenue later. Report the move down the ladder and
  the larger base together, and look for evidence of conversion; without a document it is a point to watch, not a result.

So a change in mix is read before a change in volume: fewer simple insured inpatient cases with a higher revenue
per bill is a different event from fewer cash inpatients. State which rung moved.
