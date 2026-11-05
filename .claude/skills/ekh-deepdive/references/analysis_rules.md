# Interpretation rules

The script already applies these rules and prints its verdicts in the digest. Your narrative must agree with them.
They are kept from the Antigravity skill, which had sound rules and unreliable numbers.

## 1. YoY tiers

| tier | absolute YoY | what the narrative must do |
|---|---|---|
| T1 | ≤ 3% | explain stability or offsetting factors (e.g. foreign patients up, Thai patients down) |
| T2 | 3–10% | name the distinct root cause (volume vs intensity/price, operating leverage) |
| T3 | > 10% | cite documentary evidence (capex, new building D&A, a big dividend, a provision, a one-off) |

A T3 change without documentary support stays a `🚩 Red Flag (Unexplained)`. You must not invent a reason.

The script flags the following when YoY is over 10% and the change is at least 1 THB mn:
- revenue, GP, SG&A, admin, selling, EBIT, NP, core NP, D&A, receivables, cash + deposits, other income
- each revenue-mix line
- ECL, judged by its absolute change

## 2. Incremental GPM = ΔGP / ΔRevenue

| value (revenue rising) | reading |
|---|---|
| > 40% | strong operating leverage: fixed costs absorbed |
| 20–40% | normal for a hospital |
| 15–20% | on the low side: variable costs are high |
| < 15% | **do not claim high operating leverage.** Say the incremental revenue carried variable costs or the fixed costs of a new service or branch still ramping up. |
| negative | negative operating leverage: find the root cause (next list) |

When incremental GPM is negative, check four causes against the documents:

1. **D&A drag:** the digest prints ΔD&A / ΔCOGS.
2. **Falling occupancy:** fixed costs are under-absorbed. Use only a document's occupancy figure.
3. **Loss of high-margin patients:** e.g. fewer fly-in or foreign patients.
4. **Mix and intensity:** OPD growing faster than IPD, elective surgery deferred, insurers' simple-disease screening.

Also:

- **Revenue falling:** the script calls it "resilient" when GP holds up and "decremental" when GP falls.
- **Revenue change under 1%:** incremental GPM is not interpreted.

## 3. SG&A discipline

- **Selling not reported separately:** Admin = total SG&A. That is an accounting presentation, not a cost saving.
- **Revenue down YoY and SG&A/revenue up:** this is **cost rigidity**. Never call it "discipline". Discretionary costs (OT, bonus, promotion, outsourcing) should have flexed with volume.
- **Take ECL out first.** ECL comes from the cash-flow statement and Thai hospitals book it in admin (set `"ecl_line"` in the
  assumptions file if a company books it elsewhere). The pack carries `admin_x` and `sga_x` (before ECL) for every period.
  Compare both periods before ECL: a reversal in the base period (negative ECL) flatters it.
- **Selling and admin moving in opposite directions:** the digest's `split_yoy` decides, using admin before ECL:
  - `genuine_saving`: admin before ECL grew no faster than revenue + 3 pt → the selling cut is real. Do not call it reclassification.
  - `reclass`: the selling fall is matched (±30%) by a rise in admin before ECL → suspect reclassification unless the MD&A explains it.
  - `mixed`: admin before ECL rose for its own reasons → find them. The text also warns when a pre-tax one-off sits in either period.
- **Cost records:** a 📉 record low (selling, SG&A %, SG&A before ECL over ≥ 6 quarters) is shown next to the revenue 🏆 records.

## 3b. Core PBT (hospital operations only)

Used by experienced Thai hospital investors because other income, interest, dividends and quarterly tax swings hide the business:

- `core_pbt` = GP − SG&A − finance cost (no other income, interest income, dividend income or associates).
- `core_pbt_x` = `core_pbt` + ECL − pre-tax one-offs. One-offs come from the assumptions file: `amount_pretax`, or the
  "<x> ลบ. ก่อนภาษี" in the label (never grossed up with an assumed tax rate). Give `"line": "other_income"` for a one-off
  booked outside GP/SG&A so it is not taken out twice. When the MD&A splits a one-off across lines, list the parts:
  `"pretax_items": [{"amount": 13.07, "line": "admin"}, {"amount": 2.77, "line": "other_income"}]`. Parts in
  admin/selling are also added back to SG&A before ECL, so a provision reversal in the base period is not read as cost
  growth. Use the MD&A's own one-off total for `amount_after_tax`, so Core Profit matches management's figure.
- Lead with `core_pbt_x` YoY and YTD when it tells a different story from NP, and say why (ECL, one-offs, other income).

## 3c. Receivables and ECL (interim notes)

`fs_notes.py` reads the latest filing's receivables note: the ECL allowance per group (trade vs other/accrued income) and the
aging of trade receivables, current period vs the last year-end. Use it to say *where* an ECL charge sits (which group, how much
moved past 3 months). The note does not name the debtor type (insurer, corporate, government): never guess it, put it on the
watch-list as a question for Oppday. The allowance movement should roughly equal YTD ECL in the cash-flow statement; a gap means
write-offs.

Quarterly ECL, D&A and CFO are derived from cumulative statements. The pack checks that each quarter = YTD(this year) −
YTD(earlier quarter of the SAME year) and that the quarters add up to YTD. Subtracting the prior-year column is a common error.

## 3d. Expenses by nature and dividends

- Condensed interim statements (TAS 34) usually have **no expenses-by-nature note**. Section 2.7 then shows staff, doctor fees,
  referral and medicine as n/a with the reason, fills what the filing does disclose (D&A, ECL, bad debt, inventory write-down,
  post-employment provision, directors' and management pay) and adds the last two annual notes as % of revenue. Never estimate a
  missing bucket from the annual ratio. In a Q4 report the annual note fills every bucket.
- Section 2.8 shows DPS, EPS and payout history, cash and net cash per share (with the share count used, including warrant
  conversions), and a DPS table at last year's payout, +5 pt and +10 pt on a mechanical full-year core profit (YTD actual +
  the seasonality table's remaining quarters). Present it as scenarios; the company's policy is what the documents say.

## 4. Hospital categories

| category | examples | mix shown | narrative focus |
|---|---|---|---|
| 1 Premium / foreign (non-SSO) | BH, BDMS, WPH, PR9 | OPD/IPD + Thai/foreign (no SSO rows) | foreign growth by country or region (from documents), Thai patients' drivers: seasonality, purchasing power, insurance co-pay, high base, management response |
| 2 SSO-based | VIH, BCH, CHG, RJH, SKR, LPH | OPD/IPD/SSO | SSO as a defensive cushion; registered members; high-cost-case reimbursement; SSO rate cuts (retroactive adjustments are one-offs) |
| 3 General / regional | NTV, RAM, THG, AHC... | as disclosed | |

The category comes from the assumptions file, or else from the finance-sheet taxonomy.

Only categories 1–5 are accepted. `snapshot.py` refuses any other ticker (no default category), because these rules are
hospital rules. Other businesses need their own skill.

## 5. Seasonality (Thai hospitals)

The script's table uses the company's own history: the median QoQ for each quarter-of-year, and last year's same quarter × the latest YTD growth. Use these typical drivers only as context, and confirm them with that history:

- **Q1:** new SSO registrations, PM2.5/respiratory illness; revenue often falls QoQ from Q4.
- **Q2:** Songkran holidays, a low season for elective cases.
- **Q3:** rainy season with influenza, RSV and dengue; often the peak quarter.
- **Q4:** early cool season; year-end SSO adjustments.

Because revenue is seasonal and fixed cost per quarter is similar, GPM and incremental GPM are read **YoY first**; QoQ is context only.

Do not write occupancy rates, patient counts, bed numbers or payment rates unless a document states them, and cite it.

## 6. Momentum score (transparent)

The score starts at 5.0; the table below adds or subtracts points, and the result is clamped to 0–10.

| component | points |
|---|---|
| revenue YoY | +1.5 if > 10%, +1 if > 4%, +0.5 if ≥ 0, else −1 |
| GPM YoY | +1 if > +0.5 pt, −0.5 if < −0.5 pt, −1.5 if < −1 pt |
| core NP YoY | +1.5 if > 10%, +0.5 if ≥ 0, −0.5 if > −10%, else −1.5 |
| core NP QoQ vs this quarter's historical median QoQ | ±0.5 |
| CFO / EBITDA (TTM) | +0.5 if ≥ 0.8, −0.5 if < 0.6 |
| DSO YoY | −0.5 if > +10 days, +0.5 if < −10 days |

Labels: ≥ 7.5 Strong, ≥ 6 Positive, ≥ 4.5 Neutral, ≥ 3 Weak, else Negative.

The score describes the numbers; it is not a recommendation.

## Source hierarchy

1. SET/SEC filings and company documents (statements, MD&A, Oppday, 56-1, factsheet) are tier 1 and decide every figure.
2. `md/second_source/` (news, interviews, transcripts, broker notes) and `md/analyst_notes/` are tier 2: context only,
   always `external`, never in a table.
3. `md/third_source/` (web-board posts by other investors) is tier 3: leads and questions only, never a figure or a
   stated fact; usable only as an investor's observation marked `external`, after looking for it in tier 1.
4. Where tier 2 or 3 contradicts tier 1, keep tier 1 and list the contradiction under `conflicts` with both sources and the
   likely reason. Never average the two, and never drop the contradiction silently.
