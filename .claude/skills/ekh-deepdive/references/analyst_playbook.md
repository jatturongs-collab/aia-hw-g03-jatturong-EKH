# Analyst playbook — the core lens of this skill

This is how คุณ Pop (a retail investor who follows VIH closely) reads a Thai hospital quarter. It comes from his posts on
Q2/2567 to Q2/2569, his look back at 2567, his AGM 2568 summary, and 74 Facebook posts from Nov 2564 to Sep 2569
(`md/analyst_notes/fb/`, split by `split_fb_posts.py`: quarterly reads, valuation, dividend, ownership and insurance-policy
posts, plus broker notes he re-posted). **This file is the core logic of the narrative.** The
data pack supplies the numbers; this file decides which questions the report answers, in what order, and in what voice.
His raw posts are kept in each stock's `md/analyst_notes/`.

What his posts on **other hospitals** add (SSO-heavy, foreign-patient, a new hospital ramping up, a windfall
unwinding, checks on the statements, when he gives up on a stock) is in `pop_casebook.md`. Read the section of the
casebook that matches the stock's situation; this file stays the common core.

## 0. The one idea underneath everything

A hospital is a fixed-cost business. Doctors, nurses, buildings and admin cost roughly the same each quarter, so once
revenue passes break-even, **each extra baht of revenue carries only variable cost**. Profit then grows several times faster
than revenue. The investor's job each quarter is to find out:

1. Is revenue growing, and is the growth real (volume, price, mix), not a base effect?
2. Are fixed costs still flat, so that the growth drops to profit?
3. Which **phase** is the business in, and how long can it last?
4. What does that mean for next quarter, the full year, the dividend and the valuation?

Every section of the narrative should serve one of these four questions.

## 1. The business phase (his signature angle)

| Phase | What you see | What it means for the stock |
|---|---|---|
| **Investment** (ระยะลงทุน) | Revenue grows but costs grow with it, and capex ≥ 1.5× D&A (new branch, new centre ramping up). Profit does not grow. | Patience. Watch occupancy and the ramp-up. |
| **Cost peak** (จุดต้นทุนพีค) | Fixed costs stop rising: quarterly D&A flat for ≥ 4 quarters and capital commitments in the notes falling to near zero. Profit and valuation at their low. | K. Pop's buy point (at the latest, break-even). Needs both signals; one alone is a lead. |
| **Harvest** (ระยะเก็บเกี่ยว) | Revenue grows, fixed costs flat. Incremental gross margin (ΔGP/ΔRevenue) is far above the average GPM (Q2/2567: ~50% vs 24%). Profit grows 3–5× revenue, and net margin improves. | The best phase of a growth stock. |
| **Late harvest** (ระยะเก็บเกี่ยวช่วงท้าย) | Profit growth falls back towards revenue growth. No more acceleration. | The trap: growth slows and the market de-rates the P/E. Investors get stuck here. |
| **Saturation** (ระยะอิ่มตัว) | Capacity full: revenue and profit flat, capex below D&A. | A dividend stock, unless a new Investment phase begins. |

**Warning flags (not phases):** *Margin squeeze* (มาร์จิ้นถูกกด) — revenue grows, profit falls, capex not high: find the cause (doctor fees/wages, SSO/UC rates, mix). *Cost-cut profit* (กำไรโตจากลดต้นทุน) — revenue flat or down, profit up from lower costs: real but limited. While a flag is up the phase reads "ยังไม่ระบุช่วง". Names are defined once in `GLOSSARY.md`.

- **His filter:** a good business + a new investment + that investment about to pass break-even. He rejects a good
  company long past break-even and a good company with no new investment (casebook §0).
- **The script's label is a first guess.** It tests capex against D&A, which misses three cases: an opex-led build-out
  (new branches bringing rent, staff and doctor guarantees), costs that arrive after the opening (hospitals opened
  during COVID), and acquisitions. Before accepting "margin squeeze", check whether units opened in the last two years
  and where the cost sits (`LOCATE`).
- The digest's `PHASE` line computes this: TTM revenue growth vs TTM core PBT growth, the multiple, incremental GPM vs
  average GPM, and the quarterly multiples (shows whether leverage is accelerating or fading).
- Say the phase in plain words and give the reason (fixed costs flat, a new cost base, a new branch coming).
- A new hospital or a big capex project restarts the investment phase for part of the business: say when it opens
  (VIH: new hospital delayed to Q1–Q2/2570, per AGM 2568) and what it will do to fixed costs.
- "Not far from break-even" means high leverage both ways: a small revenue gain is a large profit gain, and a small
  loss is a large drop. Use the digest's core PBT margin.
- **Why the harvest comes fast:** an expansion usually relieves a capacity bottleneck (demand was already there), so
  revenue fills the new capacity quickly while profit starts from a low base near the *new* break-even. Two companies
  with the same revenue growth and the same P/E are not equal: the one just past its investment phase grows profit
  2–5× faster (EKH Q3/2561: revenue +32% QoQ, profit +104%; then IVF revenue arrived with no new fixed cost). This is
  what the peer table's profit-÷-revenue multiple and phase are for. "การคาดการณ์งบให้ถูก คือ การทำเหตุให้ถูก" —
  get the causes right and the forecast follows.
- **Leading signs in the statements** (how he timed VIH in 2563, before the profit showed). The digest prints them as
  `LEAD` lines:
  - *Depreciation stops rising* after years of quarterly increases: the fixed costs that depreciation brings with it
    (staff, utilities, interest on the expansion loan) have stopped growing too.
  - *Capital commitments* in the notes (ภาระผูกพันรายจ่ายฝ่ายทุน) run down from hundreds of millions to a few million:
    the build-out is finished, "ต้นทุนเข้าครบแล้ว รอ Ramp Up". The reverse is the first sign of a new project, before
    any announcement (VIH separate statements Q3/2565: 10.10 → 57.10 mn, "the new hospital may have started").
  - Headcount history and occupancy, when disclosed.
- **Leverage decays with distance.** Right after break-even, revenue +10% can mean profit +15–30%; the further revenue
  moves past break-even, the closer profit growth falls to revenue growth. A good company long past break-even grows
  profit in line with revenue; this is why he prefers the one just past its investment phase. Margin has a ceiling to
  name: hospitals at ~70% occupancy reach a net margin of 15–20% (VIH was at 8% when capacity was completed in 2563).
  The ceiling depends on payor mix: he puts SSO margin near 20% and cash/foreign near 32–34%, so an SSO-heavy
  hospital tops out lower (BCH net margin ~12%).
- **Find the normal anchor year.** Before judging long-run growth, pick the first year free of distortions. VIH left
  its investment phase in 2561; 2562–2565 were distorted by COVID and pent-up demand, and 2567 by the SSO RW>2 cut, so
  2568 (NP 437 mn) is the first clean year to compare with 2561 (177 mn). Say which years you exclude and why.

## 1b. Price = valuation + narrative; narrative = expectation − disappointment

(The heading is the user's framing. Pop's own words are "ราคาหุ้น = มูลค่า + ความคาดหวัง": good results or good
news already expected bring a falling price, and "คาดว่าจะผิดหวัง" is where he looks for opportunity.)

The share price has two parts. **Valuation** is what the market pays today for the profit (P/E, PEG, yield). **Narrative**
is the story the market believes about the future, and it moves with *expectation minus disappointment*: a harvest
phase that keeps delivering builds expectation and lifts the P/E; a quarter that misses, or leverage that fades toward
late harvest, is a disappointment that de-rates it even when profit still grows.

Each report answers three things (digest `EXPECT` lines, box "ราคา = มูลค่า + เรื่องเล่า"):

- **What does the price already expect?** P/E on normal profit and PEG. PEG < 0.7 with a harvest phase = low
  expectations and room to re-rate (VIH at AGM 2568: growth tied first in the sector, P/E 12× vs PR9's 26×). PEG > 1.5
  = high expectations; the next disappointment costs more.
- **Did this quarter beat or miss what the trend implied?** The script compares actual revenue and normal profit with the
  statistical projection made from the previous quarter. Say whether the miss or beat is noise (seasonality, one-off) or
  story (the phase changing).
- **Is the story strengthening or fading?** The quarterly profit-÷-revenue multiples: rising = harvest intact; falling
  toward 1× = late harvest, the classic trap. Also name what could disappoint next (high base, rate cuts, a new hospital's
  start-up costs) and what could surprise upward (price increase, a low base, epidemics returning).

Write this in `expectation` (2–3 items). Never state a target price or a buy/sell call.

### Valuation anchors he uses (all computed or cited, never a target)

- **Value the normal business, not the windfall.** When profit is far above normal (COVID Hospitel income in
  2564–2565) or below it, put the price on profit "in a normal situation" and say which periods are abnormal. Ask how
  long an unusually good profit can last; if peers with the same windfall are being sold on good news, the market is
  treating it as temporary.
- **Risk and reward stated separately.** Downside: P/E on normal profit against the peer range, and the dividend yield,
  if nothing goes as expected. Upside: what happens to the P/E if fixed costs stay flat and revenue grows 10–20%. He
  writes both before the results, with what each outcome would mean. The report gives the two sides as numbers and
  never a call.
- **Market cap per bed** against multi-branch peers (BCH, CHG), next to P/E and P/BV; a multi-branch network with
  SSO income spreads risk better than a single-site hospital and should not trade below one. (SSO helps only with
  scale and cost discipline; he calls it "high risk, low profit" for an operator without them — casebook §1.)
- **The information discount.** A hospital with no IR, no Oppday and no coverage trades cheap partly because it is
  hard to study; when management starts IR, Oppday, analyst meetings and company visits, that discount can close.

- **Ex-cash P/E** (digest `EXPECT: มูลค่าไม่รวมเงินสด`): (price − net cash per share) ÷ EPS. When cash is a quarter of
  the price (VIH Q2/2569: 2.15–2.30 of ~9 baht), the headline P/E overstates what the market pays for the hospital
  (VIH ~12× headline, ~8–9× ex-cash).
- **A strategic buyer's price** is an outside anchor: PRG (MBK group) paid 9.50 baht for 20% of VIH in Sep 2569,
  above the board price. Translate it: EV per bed 9.4 mn vs 10–12 mn per bed to build a new hospital, so buying was
  cheaper than building (KKP). Cite as external with the date; say what it confirms, not what the stock is worth.
- **Growth stock at a no-growth multiple.** When a hospital growing profit 20–40% trades near the P/E of peers growing
  ~3%, say so with the peer table (P/E and PEG columns). Also note rank: "P/E second lowest, EV/EBITDA lowest in the
  group".
- **Yield converted to price.** If payout can rise, show the DPS scenarios (digest `DIVIDEND` lines) and the yield at
  today's price; the risk to state is how long a high payout lasts once a new hospital is built.
- **Broker forecasts as the market's expectation.** When a broker note gives a quarterly or full-year forecast (KKP:
  2Q26 core profit 102 mn, 2026 core 480 mn, +14%), compare the actual with it as well as with the statistical
  projection. External, with broker and date.

### Signals that move the narrative (external, dated)

Profit can grow for quarters while the price does not move (fund outflows, a weak SET). What closes the gap is the
market noticing. He tracks, and the report may mention with source and date:

- a strategic shareholder entering at a premium (PRG/MBK 20% at 9.50, via a 125 mn-share big lot) — "confirmed by
  professionals"; ask what synergy is claimed (MBK: wellness, property development);
- top-10 shareholder changes (a well-known investor appearing), big lots, warrant conversions adding shares;
- fund eligibility: SETESG index, Thai ESG funds allowed to buy JUMP+ companies;
- coverage starting: analysts visiting management, first broker notes, the first earnings call.

These raise expectation; they do not change the profit. Keep them in `expectation`, never as a reason the stock "will"
rise.

## 1c. The margin ladder (given by the user; read every revenue dimension through it)

**Standing principle of the owner (stated again 7 Oct 2026). It is applied in every report and is never dropped or
weakened by a rewrite of this skill.** It changes only when a document shows otherwise for a company; then the report
shows that evidence beside the principle and tells the owner, and the owner decides whether the principle is updated.

Margin, from the lowest rung to the highest:

- **By service: OPD < IPD.**
- **By payor: SSO < insurance < self-pay (cash).** Cash is above insurance only slightly.
- **Complex disease > simple disease** in revenue per head.
- **SSO is also a funnel.** More insured SSO patients are one channel to self-pay revenue later: the same people and
  their families use services outside the scheme (specialist centres, check-ups, rooms, procedures not covered). So
  growth at the bottom rung is not read as "low-quality growth" and left there. Say both things: the mix moved down
  the ladder this quarter, and the base that can be converted grew. Then look for evidence of conversion in the
  documents (self-pay revenue at the SSO hospitals, specialist centres there, what management says) and write what is
  found. Conversion that no document shows is stated as the principle and a point to watch, never as a result.

Whenever revenue is split (payor, OPD/IPD, centre, nationality), say which rung grew and which shrank before
talking about the total: revenue can be flat while profit rises because the mix moved up the ladder, and the
reverse. The digest's `OPS` lines (from the Oppday slides: volume, utilisation, revenue per bill) show whether a
change came from volume or from price/case mix. Example, VIH Q2/2569: inpatient days −14.9% but revenue per IPD
bill +4.3% and non-capitation IPD revenue only −3.58% — the simple insured cases left (insurers tightened
approvals), the complex ones stayed. Occupancy and utilisation also move with the **denominator**: divide volume
by the rate to see whether the bed or capacity base changed before calling a fall in the rate a fall in demand.

## 2. The order of a quarterly read

0. **Locate the change before explaining it.** Consolidated − separate = subsidiaries (VIH: separate = Om Noi;
   subsidiaries = Nong Khaem, Samut Sakhon, Yaek Fai Chai). The digest's `LOCATE` line splits the YoY change in
   revenue, cost, selling and admin into parent and subsidiaries. A cost that rises three quarters in a row (selling
   expense Q4/2564–Q2/2565) is traced to the entity first, then to the Oppday for the reason.
1. **Strip other income** — "ตัดรายได้อื่นเพื่อดู Pure Operation". Core PBT = GP − SG&A − finance cost.
2. **Normalise both periods.** (Growth is compared before tax; a one-off or an incremental margin is sized after a
   flat 20% tax.) Add back or remove one-offs in the current *and* the base period, using management's
   own figures (SSO Adjust RW>2 retroactive cuts, lawsuit provisions and their reversal, dispute income). Headline
   growth must be on normal profit. Stop at profit before tax; the tax rate moves quarter to quarter.
3. **Revenue: growth, source and base.**
   - One line per payor: cash OPD, cash IPD, SSO, each with YoY, and records.
   - The reason: patient volume, revenue per case, new centres (heart, surgery), epidemics, government payment rules.
   - **Per-case numbers are compared with the same quarter only** (seasonality changes the mix). Q3 OPD revenue per visit is
     always lower because many low-bill respiratory cases (flu A/B, RSV in children) blend in. Visits and revenue per
     case are usually in the Oppday slides, not the MD&A.
   - **Is the base normal?** Read the digest's `BASE` lines (see §3).
4. **Gross margin YoY, and incremental margin.** "Revenue +51 mn, GP +26 mn, so the extra revenue earned ~50%, twice the
   average margin: only variable cost came with it." That is operating leverage in one sentence. QoQ GPM mostly shows
   seasonal volume, not performance. Two exceptions where he does use QoQ: right after fixed cost has stepped up
   (new capacity: is the next revenue dropping through?) and while a windfall is unwinding (YoY is meaningless).
5. **Fixed costs: how long have they been flat?** Read the digest's `COST BAND` lines: "selling 15–16 mn for five
   quarters, excluding Q4/2566, which is higher from bonuses; admin 63–66 mn for four quarters". Then ask whether a jump is
   a provision (ECL, lawsuit: check the cash-flow statement), a Q4 bonus, or a new cost base. A record low in selling
   baht or % is news; ask whether it can last.
   - **Is a cost rise committed?** Check depreciation in the same entity. If depreciation rose, the cost came with
     assets and stays. If depreciation is flat, the spending has no long-term commitment and can fall back — then
     watch whether it does once revenue normalises.
   - **Odd balance-sheet lines.** A jump in a vague line (other current assets in Q3/2564 = Moderna vaccine stock,
     the same pattern as BCH) is estimated against its usual level and sized as a worst case against one quarter's
     normal profit ("write-off 13–17 mn after tax vs 40–50 mn a quarter: still a profit").
6. **The long view of overheads.** Admin has stayed at about the same level for years while revenue grew from 600+ to
   800+ mn a quarter, so SG&A/sales keeps falling (`SG&A LONG RUN`).
7. **Profit and margin.** Normal profit growth vs revenue growth ("revenue +8.14%, profit +38%, because fixed costs did
   not rise"). Say whether the normal margin has **room to improve** and name the levers: occupancy still rising, a
   price increase not yet in a full quarter, the cash-patient mix.
8. **Next quarter and the full year** (see §4).
9. **Dividend and valuation.** Dividends follow profit, not revenue ("revenue +3.85% but profit +19%, so the dividend
   should follow the ~20%"). Show payout history (VIH 40% → 47% → 56% for 2566–2568), cash per share and cash as % of
   price. Then the **capacity** question: how much cash is committed (a new hospital, capex) and what is free? When the
   project is delayed (VIH new hospital: EIA, then the new city plan in 2569), free cash can go to a higher payout, an
   acquisition (raising the 8% Mae Sot stake gives an immediate return) or stay idle. Show payout scenarios; never
   promise one. In Q4
   and at the AGM: full-year growth vs the industry, and valuation vs peers — "VIH normal profit +27% in 2567, tied first
   in the sector with PR9, yet P/E 12× vs PR9's 26×".

## 3. The base-effect discipline

He never takes a YoY number at face value. Before calling growth weak or strong, ask what happened in the base quarter.

- **Epidemic years.** In 2566 respiratory outbreaks ran from Q3 into Q4, so **Q4/2566 revenue beat Q3/2566** even though
  Q3 is always the high season. That made Q3–Q4/2566 a high base, so Q3/2567's +3.28% was "impressive against a high
  base", not weak. The digest flags this automatically: a base quarter whose QoQ move is far from the usual move for
  that quarter, or whose share of the year's revenue is abnormal, is marked `ฐานสูงผิดปกติ` / `ฐานต่ำผิดปกติ`.
- **Government payment changes.** From Q3/2567 the UC (บัตรทอง) heart-surgery DRG was paid at ~7,000 instead of the 8,400
  billed, and stricter criteria cut case numbers; SSO cut the Adjust RW>2 rate retroactively (Q3–Q4/2567). Once a
  shock is in both periods, the comparison is clean again. So Q1–Q2/2568 growing 5–6% *against* a base that still had
  the old rates meant Q3/2568, against an already-cut base with epidemics back, should grow faster. He called it right.
- **Two-year view.** When the base is abnormal, also compare with two years ago (`BASE` line gives it) to see the
  underlying trend.
- **Always look one quarter ahead.** The digest's `ไตรมาสหน้า` base line says whether next quarter faces a high or low
  base. Write that into the outlook and watch-list ("Q4/2567 faces the high Q4/2566 base and a lower RW>2 accrual, so
  reported profit may dip; ex-RW>2 it still grows from the price increase").

## 4. Forecasting next quarter — a bridge, not a guess

Build next quarter from known pieces, each with a source:

- **Base:** same quarter last year, adjusted for its one-offs (`BASE` line + assumptions).
- **Seasonality:** the statistical table (Q2 usually weakest, Q3 strongest from respiratory disease; a strong Q2 points
  to a record Q3).
- **Known changes:** a price increase ("revenue ~+1.35%, profit +8.5–10%, the first increase in two years", from IR). Use
  the digest's `PRICE` line to translate a price change into % of core PBT. Also: lower accruals (RW>2 booked at
  7,200–9,000 instead of 12,000), a lost contract (foreign-worker health checks stopped in Q4/2567), a new centre.
- **Direction and size in words:** "profit may fall YoY in Q4 but is within what every hospital expected; excluding
  RW>2 it still grows". Put the numbers in `[คำนวณ: ...]` and the sources in `src`.

## 5. Strategy and management (from AGM, Oppday, IR Line, interviews)

Track what management says and check it the next quarter: growth focus (VIH: cash patients through Excellence
Centres, as they have better margins than government payors); new hospital timing; M&A (Mae Sot hospital, held 8%);
buybacks and why they are small (liquidity); price-increase policy (inflation and costs); COPAY; a competitor opening
nearby (Siriraj — different catchment); pending reversals (lawsuit provision 22 mn settled at 6 mn → 16 mn reversal).
All of this is external unless it is in the MD&A or Oppday slides: `"external": true` with the source (AGM, IR Line,
Money Talk, company visit).

- **Targets and the gap to them.** Track stated targets every quarter against the run-rate: VIH JUMP+ (Apr 2569)
  revenue 4,000 mn and EBITDA 1,000 mn by 2571; long-term GPM 30% and net margin 15% (earnings call, Q2/2569 at 27.5%
  and 14.1%). Say how far the TTM figure is from the target and what growth rate closing it needs.
- **Evidence of management quality, in numbers.** "Lean cost" shows as selling expense at a record low while revenue
  is at a record high; treating complex cases in-house shows as referral cost falling (VIH: 4.72% → 3.6% of revenue);
  doctor sharing across branches shows as doctor fees % of revenue falling (17.17%). Use expenses-by-nature or the
  earnings-call ratios, with the source.
- **Capital allocation.** For a cash-rich hospital, list the options management has named (new hospital, M&A stake,
  payout, borrowing cheaply) and which one the latest quarter points to. VIH management said it prefers buying a good
  hospital to building one (lower financing cost) and watches the bottom line more than revenue targets
  (company visit, 9 Dec 2567).
- **Sizing a new hospital by analogue.** Find a listed hospital of the same size, tier and price segment and read its
  profit at its occupancy (PR9: 200 beds, ~60% occupancy, NP 557 mn in 2566) as the long-run potential; set against it
  management's own feasibility (VIH: phase 1 opening, payback 8 years, cash-positive year) and the drag in the early
  years, when the group re-enters the investment phase. State it as a range with the analogue named, not a forecast.
- **New units dilute the average.** When margin falls while new branches open, compare mature units with new ones
  (KLINIQ: old-brand GPM at a record while new branches at 40–45% pull the total from 55% to 51%). For a hospital group,
  the parent/subsidiary split is the nearest equivalent.

## 6. Context he always adds

- **Industry:** grew faster than other hospitals in the same quarter? Use the peer table, or peers' own filings.
- **Economy:** "growth in a year when GDP grows ~2% is impressive". External unless in the MD&A.
- **Long-term thesis:** chronic disease in an ageing population and population inflow to the catchment (Bangkok's
  expansion belt, Samut Sakhon's migrant workers) — outlook only, with a source.
- **Payor rules shift demand between hospitals.** Ask for each change: who loses patients and who gains them?
  - Insurers refusing admission for simple disease (headache, stomach ache, flu A) since 2568, hitting 2569 harder: IPD
    falls at hospitals that relied on it; children's insurance sales drop, so parents who now pay themselves trade down
    to cheaper hospitals that still treat well. A complex-care hospital is hurt less ("ถ้าเบิกไม่ยากคงโตมากกว่านี้"
    — say what growth would have been without the headwind).
  - COPAY: from Apr 2569 the largest health insurer (~40% share) sells co-pay policies with no co-pay inside its network;
    a hospital in that network (VIH Nong Khaem, others applying) can take share from those outside.
  - SSO: a higher contribution ceiling (3 steps) lowers the risk of another retroactive rate cut like Q4/2567. But
    RW>2 under-payment is recurring (it happened in 2562–2563 too), each hospital accrues at its own rate, and a
    conservative accrual becomes hidden upside. Compare accrual policy across SSO hospitals (casebook §1).
- **Advantages the accounts do not show:** clinical position (most heart operations in Thailand, one of 13 SSO stroke
  thrombectomy referral centres), referrals from surrounding provinces and network hospitals, a catchment where ~80% of
  cash patients hold high-limit health insurance. These explain why growth persists; cite the source.

## 7. Where the skill goes further (keep doing this)

Receivables quality (aging, accrued SSO income, DSO; it flagged overdue receivables before the Q2/2569 ECL), base
adjustment for SSO rate cuts, MD&A growth sources, cash flow, expenses by nature, data checks.

## 8. Mistakes to avoid (found in the comparisons)

- Subtracting the prior-year YTD column to get a quarter (Q2/2569 ECL 6.261 instead of 5.659).
- Adding back a provision in the current period but not the reversal in the base period.
- Mixing definitions across periods (Q4/2568 "PBT +81%" took the current figure with other income and the base without).
- Forgetting a base-period one-off: Q3/2568 +38% and Q4/2568 +81% ignore the Q3–Q4/2567 SSO cuts (like-for-like ≈ +28%).
- Numbers from a secondary source that do not match the filing, or a line copied from the previous quarter. The pack
  is the only source of figures.
- Reading QoQ cost moves without seasonality (Q4 admin rises every year).
- Guessing the debtor behind an ECL without saying it is a guess. He does infer the debtor, then confirms with IR.
- Hindsight in a back-dated report (the Q3/2567 test report wrote "ต่อมาเกิดขึ้นจริงใน Q4/2567", and the Q2/2567 one used
  the Q3/2567 MD&A). A report for quarter X may use only what was public when X's results came out.
- Stopping at "the MD&A does not explain it" without opening the Oppday (Q3/2567 IPD drop: UC heart DRG payment).
- Letting a weak QoQ incremental margin override a strong YoY one: QoQ is seasonal; the phase is read on YoY/TTM.
- Treating a re-posted article as his view or as fact. The earnings-call summary he shared (25 Sep 2569) says payout
  "never below 70%"; the dividend history says 40–56%. Check every figure from `shared` posts against the filings.
- Reading "cost cut" as permanent. He asks whether a record-low cost is temporary or permanent, and explains a cut as
  abnormal cost returning to normal plus scale near break-even — both limited.

## 9. Tone

He writes as a long-term holder: results that keep missing what you expected mean you misread the business, not that
the market is wrong; a thesis that is intact is held through a weak price. In the report this becomes one question in
the closing paragraph: is the thesis still intact after this quarter, and which number would say it is not?


Short paragraphs, one metric per paragraph, the number first, then the reason: `#รายได้ 679 ล้านบาท +8.14% YoY จาก
ปริมาณผู้ป่วยที่มาใช้บริการมากขึ้น`. Explain a concept once, in plain words, when it carries the conclusion (operating
leverage, economies of scale, phase). Be fair about good news against a high base and honest about guesses ("เดาๆว่า").
End with one paragraph: is the business better, why, which phase, what next quarter looks like, and what it means for
the dividend and the valuation.

## Using stored analyst notes (`<stock>/md/analyst_notes/`)

- Files: `pop_<BE>Q<q>.md` for quarterly posts; other posts (look-backs, AGM) as `pop_<BE>_<topic>.md`. Each holds the
  original post and the external facts in it. The digest lists the notes for the latest quarter and the one before.
- Learn the angle from them; treat every fact as a **lead**: confirm it in the MD&A or Oppday and cite that; otherwise use
  `{"text": ..., "external": true, "src": "Pop Q3/2567 (IR Line)"}`.
- Never copy a number from a note without checking it against the pack.
