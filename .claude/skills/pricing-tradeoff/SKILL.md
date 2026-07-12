---
name: pricing-tradeoff
description: "Strategy-stage skill: turns a pricing question into structured options — every option carries a stated margin mechanism, never a naked price point. Use when the user is weighing pricing structures — 'per seat or usage-based', 'freemium vs free trial', 'structure the pricing options', 'bundle or unbundle the add-on', 'how should we price X' — or when /pm routes such a request here. Do NOT use to conjure a single price with no cost/margin context, to size markets (opportunity-sizer), to audit a roadmap's economics (roadmap-reality-check), or for definitions of pricing terms."
argument-hint: "<the pricing question + numbers: current price, margin, unit costs, usage distribution>"
---

# Pricing Tradeoff

A pricing question in, structured options out — each one showing how the money actually works. A price without a mechanism is a vibe with a dollar sign.

## Verification gates (defined first; output is blocked until all pass)

- **G1 — Margin mechanism per option:** every option states its mechanism — what the price covers, what absorbs the cost, and the margin consequence derived from input numbers (including the tail, not just the median). A naked price point fails the gate.
- **G2 — Input-only figures:** every dollar amount traces to the input or is `[ESTIMATE: derivation]`. No imported benchmarks ("industry attach rate is 20%") presented as fact.
- **G3 — Symmetric tradeoffs:** each option carries who it selects for/against and its failure mode. A strawman option (one obviously-broken alternative propping up a favorite) fails.

## Steps

1. **Bank the economics.** Price, margin, unit costs — and the cost *distribution*, not just the average: the heavy-user tail is where pricing structures break. Median $4 and top-decile $15 are different problems; if only an average is provided, flag the missing distribution as the first data gap.
2. **Identify the cost driver.** What makes one customer cost more than another (usage, seats, storage)? Structures that price the cost driver are stable; structures that absorb it are bets on the distribution — say which each option is.
3. **Build 3–4 genuine structures** (not 3 numbers on one structure): e.g. included-in-base, flat add-on, usage-based/tiered. Include the stakeholders' asks as options and cost them honestly — "sales wants it free" becomes a real option with its margin give-up quantified and the condition that would justify it.
4. **Run each mechanism.** Per option: margin math at median AND at the tail, who it attracts/repels (usage caps repel the power users who'd champion the product; included-free selects for upgrade-lift), and the failure mode (negative-margin whales, adoption friction, billing complexity).
5. **Recommend only with the deciding tradeoff named** — and the data needed to confirm it (usually the real usage distribution). If the input can't support a recommendation, deliver the structured options and the missing-data list instead; that is a complete output.
6. **Gate pass.** Every option has its mechanism (G1), every figure its provenance (G2), tradeoffs symmetric (G3). Fix and re-run; maximum 2 repair loops, then report the failure instead of the output.

## Output format

```
PRICING QUESTION: AI summary add-on (base $30/seat · 80% GM · LLM cost $4 median, $15 top-decile [input])
OPTION A — included in base (sales' ask)
  Mechanism: base absorbs $4/seat median → GM 80% → ~67%; top-decile users cost half the seat price
  Selects for: adoption, upgrade pressure. Fails if: upgrade lift < margin give-up (needs: lift data)
OPTION B — flat +$10/seat (finance's ask)
  Mechanism: $10 − $4 median = ~$6 contribution/seat; NEGATIVE ~$5 on top-decile; friction at point of value
  Selects for: committed teams. Fails if: attach rate collapses or whales concentrate
OPTION C — tiered: included to N summaries, usage-priced past cap
  Mechanism: prices the cost driver; tail pays for itself. Fails via: billing complexity, cap resentment
RECOMMENDATION: <option + the deciding tradeoff> — confirm with: full usage distribution beyond top-10% figure
GATE CHECK: G1 pass (n/n mechanisms) · G2 pass · G3 pass
```

## Hard rules

1. No naked price points. Every number an option proposes shows what it covers, what absorbs the rest, and the resulting margin — median and tail.
2. Never invent benchmarks, attach rates, or willingness-to-pay figures. Missing load-bearing data is named as the confirm-before-deciding list, not filled in.
3. Stakeholder asks are costed, not dismissed and not adopted — "free to drive upgrades" gets its mechanism and its break-even condition like any other option.
4. The tail is mandatory. Any option whose mechanism only works at the median must say what the top decile does to it.

## Limitations

- Mechanisms cover unit economics; full pricing strategy (competitive positioning, packaging psychology, price-testing design) is broader than this skill.
- Willingness-to-pay is not derivable from cost data — options are costed structures; validating what customers accept needs research (research-brief pairs with this).
- Margin math is static: no elasticity modeling, no volume-response curves — flip conditions are stated qualitatively with the data that would quantify them.
- Tax, billing-system, and contract constraints can eliminate options this skill scores as viable.
