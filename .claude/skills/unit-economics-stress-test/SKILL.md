---
name: unit-economics-stress-test
description: "Build-stage skill: models a feature's per-user token cost at three scale points — every number derived from stated assumptions, arithmetic fully reproducible. Use when inference cost needs stress-testing before commitment — 'what does this cost per user at 1k/50k/1M users', 'will inference eat our margin at scale', 'run the unit economics on this feature' — or when /pm routes such a request here. If token counts or prices are missing it asks for them or proposes labeled assumptions — it never silently invents them. Do NOT use for portfolio-level roadmap economics (roadmap-reality-check), pricing-structure design (pricing-tradeoff), bare per-MTok price lookups, or general infra cost reduction."
argument-hint: "<the feature + tokens per use (in/out) + uses per user + your contract prices + scale points>"
---

# Unit Economics Stress Test

Per-user cost at three scales, every figure re-derivable from the assumptions on the page. If a reader with a calculator can't reproduce a number, it doesn't ship.

## Verification gates (defined first; output is blocked until all pass)

- **G1 — Reproducible arithmetic:** every number derives from stated assumptions with the derivation shown (tokens × price / 1M, uses × days, cost × users). Re-running the math from the assumption block must reproduce every figure exactly; rounding is shown, not hidden.
- **G2 — No unstated levers:** no bulk discounts, model downgrades, cache rates, or usage-decay curves the input didn't grant. A what-if beyond the stated assumptions appears only as `[ESTIMATE: <assumption> → <arithmetic>]`.
- **G3 — Assumptions complete or flagged:** missing load-bearing inputs (token counts, prices, usage rate) are requested or proposed as labeled assumptions the user confirms — never silently defaulted.

## Steps

1. **Freeze the assumption block.** Tokens per use (input/output, with any cacheable share), uses per user per period, contract prices, scale points. This block is the model's ground truth — everything downstream cites it. Anything missing → Step G3 behavior, before any math.
2. **Compute per-use cost:** input tokens × input price / 1M + output tokens × output price / 1M, each term shown. Apply stated cache/batch terms as given, as a separate visible variant — not silently blended.
3. **Compute per-user-per-month:** uses/day × days × per-use cost. Show the multiplication.
4. **Scale to the three points** by straight multiplication — and say so. Real curves bend (support, infra, contract tiers) only where the input granted a bend; otherwise the linear number stands with a note that no scale effects were assumed.
5. **Name the dominant assumption** — the input whose error moves the total most (usually usage rate, the least-measured number in every model). One labeled what-if is allowed to show its leverage, arithmetic included.
6. **Attach the margin hook:** cost/user/month next to the price/user/month if a price was provided; otherwise state "cost side only — no price provided." Route pricing-structure questions to pricing-tradeoff.
7. **Gate pass.** Recompute every figure from the assumption block (G1), scan for ungated levers (G2), confirm assumption provenance (G3). Fix and re-run; maximum 2 repair loops, then report the failure.

## Output format

```
ASSUMPTIONS (all stated by user)
2,000 in (1,200 cacheable) + 500 out per draft · 8 drafts/day × 22 days · $3/$15 per MTok, cached-in at 10% · scale: 1k/50k/1M
PER DRAFT: in 2,000×$3/1M = $0.0060 · out 500×$15/1M = $0.0075 → $0.0135
PER USER/MO: 8×22 = 176 drafts × $0.0135 = $2.376
SCALE (linear — no scale effects stated):
  1,000 → $2,376/mo · 50,000 → $118,800/mo · 1,000,000 → $2,376,000/mo
CACHE VARIANT (stated terms): 800×$3/1M + 1,200×$0.30/1M + $0.0075 = $0.01026/draft
  → $1.8058/user/mo → 1M users ≈ $1,805,760/mo (−24%)
DOMINANT ASSUMPTION: 8 drafts/day — unmeasured; at 4/day every figure halves [derivation: linear in usage]
MARGIN: cost side only — no price provided.
GATE CHECK: G1 pass (all figures re-derived) · G2 pass (0 unstated levers) · G3 pass
```

## Hard rules

1. Every number re-derives from the assumption block. An underivable figure — "volume discounts bring it to ~$1.6M" with no stated discount — is cut or converted to a labeled ESTIMATE with its assumption and arithmetic.
2. Never invent prices, token counts, or usage rates. Proposed defaults are labeled, attributed to nothing, and confirmed before they anchor the model.
3. Cache, batch, and discount terms apply only as stated, and always as visible variants — never silently blended into the base case.
4. The dominant assumption is named in every output. A cost model that doesn't say where it's most wrong invites false confidence.

## Limitations

- The model prices tokens, not the feature: infra, support, and storage costs enter only if stated.
- Linear scaling is a stated simplification — real usage distributions have heavy tails; a measured distribution replaces the flat rate when available.
- Token counts per use drift as prompts evolve; the model is a snapshot of the stated counts and says so.
- Contract prices change; figures inherit the input's price validity, and ratios survive price drift better than absolutes.
