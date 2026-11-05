# Writing the executive summary (Thai, qualitative, number-anchored)

The summary answers the question an investor asks first: **why did margins and profit change, and will it last?**
It appears on the Cover tab and as section 1 of the Markdown file, so write it once, in the assumptions file.

## Inputs to read before writing

1. The built `.md` from a first build, specifically:
   - profit bridge (YoY and QoQ)
   - GPM, SG&A% and ETR rows
   - revenue-mix growth
   - subsidiaries section 6
   - DSO/ECL, net cash, FCF
   - valuation matrix
2. The latest MD&A (`md/raw/combined_mda_all.md`, last document) for management's stated reasons.
3. Prior MD&As for one-offs that explain an unusual base period.

## Structure (each item is one sentence or two; include a number)

| Key | Content |
|---|---|
| `headline` | One line: profit direction and size, then the main reason. E.g. "กำไร Q2/2569 +11.6% YoY … จากรายได้ SSO กลุ่มโรคซับซ้อน …" |
| `margin_drivers` | 3–4 bullets: GPM level and change → cause (payor mix, price/RW rate, volume vs fixed cost, doctor-fee/drug cost ratio) |
| `profit_drivers` | 3–4 bullets: the bridge in words (volume, margin, SG&A, tax, other income); reported vs core growth when one-offs distort the base |
| `segment_notes` | Parent vs subsidiaries contribution (dividend-adjusted); revenue-mix shifts |
| `balance_sheet` | Net cash, leverage, CFO/FCF vs dividends, and working-capital warning signs (DSO, ECL, accrued SSO income) |
| `risks` | 2–3: policy (SSO rates), insurer claims, capex/ramp-up drag (quote the project grid), competition |
| `catalysts` | 1–2: guidance/targets and how far the current run-rate is from them |
| `valuation_view` | Fair value, upside and signal, which methods drive it, and why the range is wide or narrow |

## Rules

- Every figure quoted must be visible in the workbook, so a reader can find it. Round consistently (1 decimal for %, THB mn).
- Separate **what** (from the model) from **why** (from the MD&A or filing). If management gives no reason, say it is an inference
  ("น่าจะมาจาก…").
- Call out one-offs and base effects explicitly. They are the most common reason reported growth misleads.
- No generic filler ("บริษัทมีพื้นฐานแข็งแกร่ง") without a number behind it.
- Write in Thai. Keep English terms in brackets where they are standard (GPM, SSO, Adj RW, DSO, FCF).
