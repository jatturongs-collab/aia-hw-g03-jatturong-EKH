# Model specification (row-by-row)

Contents: 1. Column layout · 2. Statement hierarchy (tabs 1, 2, 6) · 3. Subsidiaries tab · 4. Revenue-mix tabs ·
5. Nature tab · 6. Project tab · 7. Valuation tab · 8. Cover tab · 9. Integrity checks · 10. Data provenance rules

## 1. Column layout

**Quarterly tabs (1–4):** column A = label, **B..O = the 14 most recent quarters that have hospital revenue**, P = TTM,
Q = source/notes. Headers use Thai BE years (`Q2/2569`). Freeze panes at B6.

- Flow rows: TTM = `SUM` of the last 4 quarters. For required rows the TTM stays blank unless all 4 quarters exist.
- Balance rows: TTM = latest quarter.
- Ratio rows: the same formula, re-evaluated on the TTM column with annualisation factor 1 (4 in quarter columns).
- Growth rows: YoY uses the column 4 to the left; QoQ uses the column 1 to the left. Both are blank in TTM.

**Annual tabs (6–8):** up to 5 fiscal years with data, then the prior-year YTD and the current YTD (e.g. `6M/2568`,
`6M/2569`) when the latest quarter is not Q4. YTD YoY compares with the prior-year YTD. Annualisation factor = 12/months.
Balance sheet values for the YTD columns come from that quarter-end.

## 2. Statement hierarchy (Consolidated, Separate, Annual)

```
ส่วนที่ 1: งบกำไรขาดทุน
  รายได้จากกิจการโรงพยาบาล (input)            ── % YoY, % QoQ
    รายได้เงินปันผล (input)                     ← separated because the parent books dividends from subsidiaries
    รายได้อื่น รวมดอกเบี้ยรับ (input = total revenues − hospital − dividend)
  รายได้รวม = hospital + dividend + other
    หัก ต้นทุนกิจการโรงพยาบาล (input)
  กำไรขั้นต้น = hospital revenue − cost        ── GPM (on hospital revenue, same basis as MD&A), % YoY
    ค่าใช้จ่ายในการขาย (input)                  ── % SG to Sales (on hospital revenue)
    ค่าใช้จ่ายในการบริหาร (input)               ── % SA to Sales (on hospital revenue)
  รวม SG&A                                     ── % of hospital revenue
  EBIT = total revenues − cost − SG&A          ── EBIT margin, % YoY   (ties to reported operating profit)
    ส่วนแบ่งกำไร (input, optional) · บวก รายได้ทางการเงิน (input, optional) · หัก ต้นทุนทางการเงิน (input, abs)
  PBT = EBIT + associates + finance income − finance cost
    หัก ภาษี (input = PBT − reported NP, so it always ties)   ── ETR
  Net profit  → หัก NCI → NP to owners          ── NPM (NP / total revenue, MD&A basis), % YoY, % QoQ
    รายการพิเศษหลังภาษี (from assumptions) → Core profit
    EPS (reported)
ข้อมูลประกอบ: D&A (cash flow), EBITDA, EBITDA margin, ECL (cash flow), ECL % revenue
ส่วนที่ 2: ฐานะการเงิน
  cash, short-term investments → cash total; receivables, inventories, total current assets, PPE, TOTAL ASSETS
  payables, interest-bearing debt (sum of loan/debenture lines), lease liabilities, TOTAL LIABILITIES
  equity to owners, NCI, TOTAL EQUITY (reported, never derived)
  Balance check = ROUND(assets − liabilities − equity, 2) → must be 0.00 ("n/a" if a total is missing)
  Net cash = cash total − debt − lease; D/E; IBD/E
ส่วนที่ 3: ROA, ROE (owners), ROIC = EBIT×(1−ETR)×ann / (equity + debt + lease − cash total), DSO, DIO
ส่วนที่ 4: CFO, CAPEX (PPE + payables for PPE + intangibles), FCF, dividends paid, CFO/NP
ส่วนที่ 5: tie-out — reported operating profit and NP to owners, with check rows
```

Formula rows are guarded (`IF(anchor="","",…)`) so missing periods show blank, not zero.
Optional rows (dividend income, finance income, associates, one-offs, NCI, debt, lease, ECL, short-term investments, finance cost)
count as 0 when absent.

## 3. Subsidiaries tab

Every input row is `IF(OR(Cons="",Sep=""),"",Cons − Sep)`; optional rows use `N(Cons) − N(Sep)`. Formula rows
recompute from those differences. Section 6 corrects for intra-group dividends, which make raw Cons − Sep misleading:

- Intra-group dividend = Separate dividend income − Consolidated dividend income
- Parent NP ex-dividend = Separate NP − intra-group dividend
- Subsidiaries NP (adjusted) = Consolidated NP − parent NP ex-dividend
- Subsidiaries' share of group NP and of hospital revenue; NPM for each side

## 4. Revenue-mix tabs (quarterly and annual)

OPD, IPD → Non-Capitation subtotal; SSO; other hospital revenue; gross → minus eliminations → hospital revenue.
Each has YoY growth rows, a link to the reported revenue, and a check (must be within ±1 THB mn). Mix % rows are based
on gross service revenue. For non-SSO categories the SSO row is empty and labelled "ไม่มีบริการ".

## 5. Nature tab (annual)

The base is hospital revenue and cost + SG&A linked from the annual tab. Five buckets come from the expenses-by-nature note
(staff, doctor fees, medicine & supplies, D&A, referral), each with % of revenue. "Other" = cost + SG&A − 5 buckets.
Columns with no note (e.g. interim) stay blank and are never estimated.

## 6. Project tab

Inputs: beds, capex, land (not depreciated), depreciation years, fixed opex, variable cost %, tax. Base NP comes from Consolidated
TTM NP to owners; base equity is the latest equity to owners.
Derived: annual depreciation = (capex − land)/years; bed-days = beds × 365; fixed + depreciation.
Grid 1: project NP = IF(EBT>0, EBT×(1−t), EBT), where EBT = bed-days × occupancy × revenue per bed-day / 1e6 × (1 − var%) − fixed − depreciation.
Grid 2: group ROE = (base NP + project NP) / base equity. A break-even occupancy row follows.
Rows = occupancy, columns = revenue per bed-day, with a colour scale.

## 7. Valuation tab

1. Market and base data: price, shares, market cap, TTM revenue, NP, core NP, TTM EPS (core), BVPS, TTM EBITDA,
   TTM FCF, net cash, ROE, last DPS.
2. Assumptions: rf, beta, ERP → Ke; g; payout; FY1 core NP (input with rationale; default = TTM core) → EPS1, DPS1.
3. Valuation matrix (low / base / high parameters → fair values; weight; weighted value; upside):

| Method | Basis | Parameter | Fair value |
|---|---|---|---|
| P/E | EPS FY1 | target P/E | P/E × EPS1 |
| P/BV | BVPS | target P/BV | P/BV × BVPS |
| EV/EBITDA | TTM EBITDA | multiple | (multiple × EBITDA + net cash) / shares |
| DDM (Gordon) | DPS FY1 | g | DPS1 / (Ke − g) |
| DCF (perpetuity) | TTM FCF | g | (FCF × (1+g)/(Ke − g) + net cash) / shares |

   The weighted fair value, upside, margin of safety, current P/E (TTM and FY1), P/BV, EV/EBITDA, trailing and forward yield,
   and signal (>15% = น่าสะสม, 0–15% = ถือ, <0 = แพงกว่ามูลค่า) follow.
4. Sensitivity A: P/E (rows) × EPS growth vs TTM (columns) → price.
5. Sensitivity B: DDM Ke × g.
6. Sensitivity C: justified P/BV = (ROE − g)/(Ke − g) × BVPS, ROE × Ke.
   All grids are formulas: green when ≥ price + 15%, red when below price.

## 8. Cover tab

The title is the English company name (SET: ticker). The subtitle holds the Thai name, quarter range and year range.
The meta line holds the category, data date, generation time and file name.
KPI block (all links): market cap, TTM revenue, latest GPM, latest NPM, TTM EBITDA margin, net cash, ROE, ROIC,
P/E, P/BV, trailing yield, fair value, upside, signal.
Then come the executive summary (from assumptions) and the profit bridge (latest quarter vs same quarter last year, and vs
previous quarter): volume effect = ΔRevenue × old GPM; margin effect = ΔGPM × new revenue; Δ other income; −Δ SG&A;
Δ associates + Δ finance income − Δ finance cost; −Δ tax; −Δ NCI. The sum must equal the reported NP (check row).
The TOC has hyperlinks. Integrity checks, colour legend and data provenance/gaps close the tab.

## 9. Integrity checks (Cover + check_workbook.py)

All must PASS: the balance check on Consolidated, Separate and Annual; EBIT tie (Consolidated); NP tie (Consolidated,
Separate, Annual); revenue-mix tie (quarterly, annual); bridge closes. `check_workbook.py` also demands zero
formula errors and agreement with LibreOffice.

## 10. Data provenance rules

- Inputs are blue. The source filing line appears in the source column. Derived values (Q4 = FY − 9M, cash-flow quarter =
  YTD difference) carry a cell comment.
- Jitta, manual or default values have a yellow fill and a comment. Jitta is used only for older consolidated totals
  (assets, liabilities, owners' equity, NP, CFO, D&A, DPS). Jitta working-capital lines use different definitions
  and are never used.
- Nothing is ever computed from a fixed ratio of another line.
