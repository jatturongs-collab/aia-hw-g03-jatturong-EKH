# Assumptions file guide (`<TICKER>_assumptions.json`)

This file holds everything that needs judgement. It must be readable by a reviewer, so every value carries a
source or a rationale. The complete worked example is `assets/VIH_assumptions_example.json`.

Contents: 1. Schema · 2. Revenue mix · 3. One-offs · 4. Market data · 5. Valuation assumptions · 6. Project · 7. Manual facts

## 1. Schema

```jsonc
{
  "company": {"name_th": "...", "name_en": "..."},
  "category": 2,                      // 1-5, see hospital_taxonomy.md
  "has_sso": true,
  "market": {"price": 8.75, "shares_mn": 627.229, "as_of": "2026-09-18", "source": "...",
             "shares_note": "...", "dps_last_fy": 0.40, "dps_note": "..."},
  "revenue_mix": {"source": "...",
                  "quarterly": {"2026Q2": {"opd": 275.06, "ipd": 279.71, "sso": 204.81, "elim": 6.38, "other": null}},
                  "annual":    {"FY2025": {...}, "6M2026": {...}, "6M2025": {...}}},
  "one_offs": [{"period": "2024Q4", "amount_after_tax": -19.24, "label": "what + source"}],
  "manual_facts": {"C|rev_hosp|FY2020": {"v": 2289.9, "src": "One Report 2564 p.145"}},
  "executive_summary": {"headline": "...", "margin_drivers": [], "profit_drivers": [], "segment_notes": [],
                        "balance_sheet": [], "risks": [], "catalysts": [], "valuation_view": "..."},
  "valuation": {"rf": 0.0229, "beta": 0.85, "erp": 0.08, "g": 0.03, "payout": 0.57,
                "notes": {"rf": "...", "beta": "...", "erp": "...", "g": "...", "payout": "..."},
                "forecast": {"fy1": {"label": "FY2569E", "np": 462.0, "rationale": "..."}},
                "pe": [12, 14, 16], "pbv": [1.2, 1.4, 1.6], "ev_ebitda": [6, 7, 8],
                "ddm_g": [0.02, 0.03, 0.04], "dcf_g": [0.02, 0.03, 0.04],
                "weights": {"pe": 0.35, "pbv": 0.15, "ev": 0.15, "ddm": 0.20, "dcf": 0.15},
                "sensitivity": {"pe": [...], "eps_growth": [...], "ke": [...], "g": [...], "roe": [...]}},
  "project": {"name": "...", "short_name": "ศาลายา", "beds": 200, "capex": 2750, "land_value": 550,
              "dep_years": 20, "fixed_opex": 85, "variable_cost_ratio": 0.45, "tax_rate": 0.2,
              "occupancy": [...], "rev_per_bed_day": [...], "source": "..."}
}
```

Periods use CE keys (`2026Q2`, `FY2025`, `6M2026`); the sheets convert them to BE (Q2/2569). Amounts are THB million.

## 2. Revenue mix

Source: MD&A table "โครงสร้างรายได้" (quarterly MD&A for quarters; the Q4/annual MD&A or One Report for years),
in `md/raw/combined_mda_all.md`. `grep -n "รายได้จากผู้ป่วยนอก\|โครงการประกันสังคม" combined_mda_all.md` finds the tables.

- `opd` / `ipd` = non-capitation patients (cash, insurance, check-ups, government contracts)
- `sso` = SSO capitation + high-cost reimbursement
- `elim` = inter-company eliminations, entered as a positive number
- `other` = any other line in the MD&A table

Rules:

- The reconciliation row (`hosp − reported`) must be within ±1 THB mn in every period. If it isn't, the digits were misread.
- Enter the prior-year YTD (e.g. `6M2025`) as well, so YTD growth works.
- If MD&A doesn't disclose a quarter, leave it out. The row shows blank; don't interpolate.

## 3. One-offs (Core profit)

Include only items that management or the auditor explicitly describes as non-recurring or retroactive:

- SSO/NHSO retroactive rate adjustments (Adj RW cuts)
- reversal or recognition of litigation provisions
- gains or losses on asset sales, impairment, insurance compensation

Enter each item **after tax** (pre-tax × (1 − 20%) unless the tax effect is stated), in the quarter it was booked, with
the label naming the MD&A or filing page. The builder rolls quarters up into FY and YTD. If the timing inside a
half-year is unclear, pick the quarter where the line item visibly moved and say so in the label.

## 4. Market data

`init` pre-fills price, listed shares and DPS from the SET factsheet (`trading_stat`, `corporate_action_historical`).
Check the price date. If the user gives a newer price, use theirs and cite it. `dps_last_fy` = the sum of dividends declared
from the last full fiscal year's profit.

## 5. Valuation assumptions

Starting ranges for Thai hospitals. Move them with evidence and write the reason in `notes`:

| Item | Typical | Guidance |
|---|---|---|
| rf | current Thai 10-year yield | Look it up (e.g. tradingeconomics.com/thailand/government-bond-yield) and date it |
| beta | 0.7–1.0 | SET-reported betas for illiquid mid-caps are biased low; use a sector beta and say so |
| ERP | 7–8% | Common in Thai broker research |
| g | 2–4% | Inflation + modest real growth in healthcare spending |
| payout | last FY DPS × shares / NP | Check the stated dividend policy (e.g. ≥40%) |
| P/E | small/mid SSO hospitals 12–18×; premium cash hospitals 20–30× | Anchor on the stock's own 5-year band and peers |
| P/BV | 1.2–2.5× | Should be consistent with ROE via the justified P/BV grid |
| EV/EBITDA | 6–10× (mid-cap) to 15×+ (premium) | |

FY1 forecast: YTD actual + the second half modelled from the prior year's second half × growth, with the reason in `rationale`
(guidance, SSO rate changes, new capacity). Weights should favour methods that fit the company:

- P/E and DDM for steady payers
- DCF only when FCF is representative, i.e. not during a capex surge

## 6. Project

Include a project only if it is disclosed (One Report, Opp Day, SET news) or provided by the user. Put the source in `source`,
and write "unverified" if the user gave numbers that don't appear in filings. Occupancy should span ramp-up to maturity
(e.g. 20–70%). Revenue per bed-day should bracket the group's current IPD revenue per patient-day.

## 7. Manual facts

The key format is `"<C|S>|<line key>|<period>"`, for example `"C|rev_hosp|FY2020"`. Line keys are those in
`extract_financials.py` LABELS. Use a manual fact only when a figure exists in a document the parser cannot read, such as a
scanned page. `src` must name the document and page. Manual facts show yellow in the workbook.
