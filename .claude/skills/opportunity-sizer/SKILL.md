---
name: opportunity-sizer
description: "Discovery-stage skill: builds a TAM/SAM/SOM opportunity size where every number carries a stated source or an explicit estimate label — no naked figures. Use when the user asks how big a market or opportunity is — 'size the market for X', 'TAM/SAM/SOM for Y', 'is this niche big enough', 'market-size inputs for the deck' — or when /pm routes such a request here. Do NOT use for definitions of sizing terms, for single-fact lookups like a company's market cap, for internal revenue forecasting, or for mapping idea risks (assumption-mapper's job)."
argument-hint: "<the product/segment to size + any known facts: counts, pricing, geography>"
---

# Opportunity Sizer

TAM/SAM/SOM with the receipts attached. A number without a source or an estimate label does not leave this skill.

## Verification gates (defined first; output is blocked until all pass)

- **G1 — No naked figures:** every number in the output carries `[SOURCE: <where it came from>]` or `[ESTIMATE: <derivation/assumption>]`. This includes intermediate numbers, not just the headline three.
- **G2 — Arithmetic reconciles and nests:** derivations shown, math correct, SOM ⊆ SAM ⊆ TAM. A SOM larger than its SAM, or a derivation that doesn't multiply out, fails the gate.
- **G3 — No invented citations:** a SOURCE tag names material the user provided or the skill actually retrieved this session. "Per Gartner"-style citations from memory are forbidden — an unverifiable recollection becomes an ESTIMATE or is cut.

## Steps

1. **Fix the unit of value.** Who pays, for what unit, at what price? (practice/month, seat/year, % of transaction). Pricing from the user is a SOURCE; pricing assumed is an ESTIMATE.
2. **Build TAM top-down or bottom-up — show which.** Bottom-up preferred: population count × price. Tag the population count's source; if fetched, cite what was fetched; if assumed, label it.
3. **Cut to SAM.** Apply the serviceable constraints (geography, segment, tech prerequisites). Every cut factor is a tagged number. Unknown share? Use a stated range (e.g. 40–60%) with the basis for its bounds — never a silently chosen midpoint.
4. **Cut to SOM.** Reachable share given channel, competition, time horizon — the most judgment-laden number, so the assumption gets the most explicit label and a stated horizon.
5. **Propagate uncertainty.** Ranges flow through the arithmetic; the output shows low/high, not one falsely precise figure. Name the single assumption the answer is most sensitive to.
6. **Gate pass.** Scan every number for a tag, re-run the arithmetic, verify every SOURCE traces to provided/retrieved material. Fix and re-run; maximum 2 repair loops, then report the failure instead of the output.

## Output format

```
SIZING: <product/segment> (method: bottom-up)
TAM: 130,000 US dental practices [SOURCE: ADA 2024, per user] × $99/mo [SOURCE: user pilot pricing] × 12
     ≈ $154M/yr [ESTIMATE: derivation above, rounded]
SAM: cloud-PMS practices = 40–60% of TAM [ESTIMATE: no data provided — range assumed, verify with PMS vendor share data]
     ≈ $62M–$93M/yr
SOM (3yr): 2–5% of SAM [ESTIMATE: single-channel sales, 2 competitors observed] ≈ $1.2M–$4.6M/yr
MOST SENSITIVE TO: cloud-PMS share — a real datum here collapses the SAM range
GATE CHECK: G1 pass (n/n numbers tagged) · G2 pass (nesting + math re-run) · G3 pass
```

## Hard rules

1. No naked figures — the gate the skill exists for. If a number can't be sourced or honestly derived, it doesn't appear.
2. Never cite a market report, analyst figure, or statistic from memory. Provided or retrieved-and-quoted, else it's an ESTIMATE with a derivation.
3. Unknowns become labeled ranges with stated bounds, never silently chosen values. False precision (a $1.37M SOM from three stacked guesses) must be rounded to match the weakest input.
4. State what would most change the answer. A sizing that doesn't name its most sensitive assumption isn't finished.

## Limitations

- Output quality tracks input quality: with no provided counts or pricing, everything is an ESTIMATE and the output says so — useful for order-of-magnitude, not for a board commitment.
- Bottom-up sizing misses budget-substitution dynamics (money coming from an existing line item); noted when relevant, not modeled.
- SOM is a judgment about execution, not a market fact — the tag and horizon make that explicit, they don't make it reliable.
- The skill sizes revenue opportunity, not profitability, CAC, or capacity to serve.
