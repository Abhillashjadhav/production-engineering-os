---
name: build-buy-partner
description: "Strategy-stage skill: turns a needed capability into a build/buy/partner recommendation — all three options scored on the same axes before any verdict. Use when the user must decide how to acquire a capability — 'build or buy X', 'build vs buy vs partner for Y', 'should we build our own Z or use a vendor' — or when /pm routes such a request here. Do NOT use for vendor selection after a buy decision is made, for AI-feature ship decisions (ai-feature-go-no-go), for contract negotiation, or for definitions of the framework."
argument-hint: "<the capability + context: team size, is it core, volumes, compliance needs>"
---

# Build / Buy / Partner

Three options, one scoring matrix, then a verdict. The matrix comes first because a recommendation written before the scoring is a preference wearing a framework.

## Verification gates (defined first; output is blocked until all pass)

- **G1 — Same axes, all three, matrix first:** build, buy, and partner are each scored on the same named axes, and the full matrix appears before the recommendation. A skipped option, an option scored on fewer axes, or a verdict-first draft fails the gate.
- **G2 — Scores carry bases:** every cell is a comparative label (strong/moderate/weak) with a one-line basis. Hard numbers appear only from the input or as labeled estimates with derivations — no invented vendor pricing or build-cost figures.
- **G3 — Decision cites its differentials:** the recommendation names which axis differences decided it, and a kill-the-recommendation line states what fact would flip it.

## Steps

1. **Define the capability and its role.** Core differentiation or adjacent plumbing? This classification drives the differentiation axis and must be argued, not assumed — customer-visible ≠ core.
2. **Fix the axes.** Default five: time to capability · total cost class (build + maintain vs per-unit/licence vs partner rev-share) · differentiation value · risk (compliance, vendor lock-in, partner dependency — name which) · reversibility. Add a context axis if the input demands it (e.g. data residency); every axis applies to all three options.
3. **Score the matrix.** All three options, every axis, label + basis. Use input numbers where they exist (volume × unit price = run-rate, tagged to input). Where an option is degenerate (no partner motion exists), score it honestly weak with that basis — don't silently drop it.
4. **Read the matrix.** The verdict comes from axis differentials, stated: which columns win where, and which differences carry the decision weight given the context (a 12-engineer team weights time-to-capability heavier than unit cost).
5. **Write the reversal.** What fact flips the call — volume crossover (shown as labeled estimate), the capability becoming core, a partner motion materializing. Include the second-best option and the trigger for revisiting.
6. **Gate pass.** Matrix complete and first (G1), every cell based (G2), differentials + kill line present (G3). Fix and re-run; maximum 2 repair loops, then report the failure instead of the output.

## Output format

```
CAPABILITY: e-signature in proposal flow — classified: adjacent (customer-asked, not differentiating)
MATRIX (before verdict)
| Axis                | BUILD           | BUY                    | PARTNER           |
| time to capability  | weak (quarters) | strong (weeks, API)    | moderate (bizdev) |
| cost class          | weak (eng + maintain + compliance) | strong ($1,000/mo run-rate [input: $0.50 × 2,000]) | moderate (rev-share) |
| differentiation     | weak (adjacent) | neutral                | neutral           |
| risk                | compliance burden ours (ESIGN/eIDAS) | vendor lock-in, low | dependency, no existing motion |
| reversibility       | weak (sunk)     | strong (swap vendors)  | weak (contractual)|
RECOMMENDATION: BUY — decided by time-to-capability and compliance-risk differentials;
build's only win is unit cost at volumes we don't have.
WOULD FLIP IT: e-sign becomes core differentiation, or volume grows past the build
crossover [ESTIMATE: order-of-magnitude above 2,000/mo — derive before acting].
SECOND BEST: partner, if a motion materializes. Revisit trigger: volume 10x or strategy shift.
GATE CHECK: G1 pass (3 options × n axes, matrix first) · G2 pass · G3 pass
```

## Hard rules

1. No recommendation before the complete matrix. If the answer feels obvious, the matrix is cheap; if the matrix changes the answer, it just paid for itself.
2. Never drop an option. A degenerate option (no partner exists) is scored weak with its basis, visibly — absence of a column is a gate failure, absence of a partner is just a weak score.
3. Never invent pricing, build estimates, or vendor terms. Input numbers and labeled estimates only; a decision resting on an invented number is worse than no decision.
4. The differentiation axis must be argued from the product's wedge, not from whether customers ask for the capability — customers ask for plumbing too.

## Limitations

- The matrix structures judgment; axis weights come from stated context and are re-weighable by the reader — two honest readers can land differently on close calls, and the differential line shows exactly where.
- Vendor-market specifics (which vendor, actual contract terms) are out of scope — this decides the mode, vendor selection comes after a BUY.
- Build-cost scoring uses cost classes, not engineering estimates; a real build candidate deserves an engineering spike before commitment.
- Partner scoring assumes arm's-length partnership; M&A-grade options are beyond this skill.
