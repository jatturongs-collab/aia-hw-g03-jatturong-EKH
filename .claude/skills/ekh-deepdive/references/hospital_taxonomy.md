# Thai hospital customer-segment taxonomy

Set `category` (1–5) in the assumptions file. It controls the SSO rows and the Cover label. Only Category 2 shows
SSO revenue. For the others the SSO row stays empty, never estimated, and OPD + IPD = 100% of hospital revenue.

| Cat | Profile | Tickers | Revenue notes |
|---|---|---|---|
| 1 | Foreigner & medical tourism (Non-SSO) | BH, BDMS, WPH, PR9 | Cash / IPMI / expat / fly-in; watch the international mix and currency |
| 2 | Social Security (SSO) powerhouse | BCH, CHG, RJH, SKR, LPH, VIH, PHG | SSO capitation + high-cost (Adj RW) ≈ 20–45% of revenue; watch registered members, capitation rate, RW rate cuts, accrued SSO income and DSO |
| 3 | Thai cash & private insurance (Non-SSO) | NTV, RPH, RAM, THG, AHC, CMR, PRINC, EKH, KDH, M-CHAI, NEW, NKT, VIBHA | Cash + life/health insurance; insurer claim policy (co-payment, simple-disease rejections) drives IPD |
| 4 | Aesthetics & elective surgery (Non-SSO) | MASTER, KLINIQ, TRP | Out-of-pocket; marketing spend drives SG&A%; OPD-heavy for clinics |
| 5 | Specialised biotech & fertility (Non-SSO) | SAFE, MEDEZE, BKGI | IVF, stem-cell banking, genomics; deferred revenue and recurring storage fees |

When a ticker is not listed, decide from the MD&A revenue table (is there an SSO/Capitation line?) and note the
reason in `category_note`.

The script cross-checks this table: if the MD&A revenue table has an SSO line for a non-Category-2 stock (or none for a
Category-2 stock), the snapshot lists it under GAPS so the category can be corrected.
