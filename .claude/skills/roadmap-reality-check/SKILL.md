---
name: roadmap-reality-check
description: "Strategy-stage skill: audits a roadmap against unit economics — every item tagged supported or unsupported with the economic mechanism stated. Use when the user provides a roadmap plus business numbers and asks what's economically justified — 'reality-check this roadmap', 'which items pay for themselves', 'what survives contact with the P&L', 'does this lineup make economic sense' — or when /pm routes such a request here. Do NOT use to author a roadmap, to prioritize purely by customer impact without economics, to size markets (opportunity-sizer's job), or for definitions of unit-economics terms."
argument-hint: "<the roadmap items + your numbers: price, margin, CAC, churn, user count>"
---

# Roadmap Reality Check

A roadmap in, an economics audit out. Every item must show its causal chain to money — or wear the UNSUPPORTED tag until it can.

## Verification gates (defined first; output is blocked until all pass)

- **G1 — Tag + mechanism:** every roadmap item is tagged `SUPPORTED` or `UNSUPPORTED (as stated)`, and every tag carries a stated economic mechanism — the causal chain to revenue, gross margin, retention, or CAC, quantified from provided numbers where possible. A tag without a mechanism fails.
- **G2 — Input-only arithmetic:** all math uses numbers from the input; anything else is `[ESTIMATE: derivation]`. Imported industry benchmarks ("PLG converts at 3%") presented as fact fail the gate.
- **G3 — Flip conditions:** every UNSUPPORTED item names the missing evidence or number that would flip it. UNSUPPORTED is a verdict on the stated case, not a kill order — the output must say so.

## Steps

1. **Bank the numbers.** Extract price, margin, CAC, churn, user count, and any per-item figures from the input. These are the only facts. Missing a number the audit needs? Say which, and either ask or proceed with a labeled ESTIMATE range.
2. **Trace each item's mechanism.** Which lever does it pull — new revenue (deals, expansion), margin (COGS, support cost), retention (churn), or acquisition (CAC, conversion)? Write the chain: R4 → fewer settings tickets → lower support cost / less rage-churn. Flag every assumed link (ticket volume → churn is an assumption unless the input ties them).
3. **Run the arithmetic.** COGS-heavy features get the margin math (a $6/user/mo AI feature against a $49 price moves gross margin ~12 points — show it). Deal-unblocking features get ARR vs. CAC. Refactors get cost-of-inaction.
4. **Tag honestly.** SUPPORTED = the provided numbers plus stated mechanism carry the case. UNSUPPORTED (as stated) = the mechanism is missing a load-bearing number or the math goes the wrong way. Strategic bets without economics stay UNSUPPORTED with their flip condition — the tag measures evidence, not vision.
5. **Summarize exposure.** N supported / M unsupported, plus the single biggest economic exposure on the roadmap (usually the item that quietly changes COGS or CAC the most).
6. **Gate pass.** Check every item for tag + mechanism (G1), every figure for provenance (G2), every UNSUPPORTED for a flip condition (G3). Fix and re-run; maximum 2 repair loops, then report the failure instead of the output.

## Output format

```
ROADMAP REALITY CHECK (inputs: $49/user/mo · 78% GM · CAC $900 · churn 2.2%/mo · 2,000 users)
R1. AI meeting summaries — UNSUPPORTED (as stated)
    Mechanism: adds ~$6/user/mo COGS → GM 78% → ~66% (−12pts) [derived from input]
    Flip condition: evidence the feature lifts retention or supports a price increase ≥ the margin cost
R2. SSO + audit logs — SUPPORTED
    Mechanism: unblocks $110k ARR (3 named deals, per sales notes) at standard margin; no new per-user COGS
...
SUMMARY: 2 supported / 3 unsupported · biggest exposure: R1 margin compression
GATE CHECK: G1 pass (n/n tagged+mechanism) · G2 pass · G3 pass
```

## Hard rules

1. No tag without a mechanism, no mechanism without its chain to a named lever (revenue, margin, retention, CAC). "Strategic" is not a mechanism.
2. Never import benchmarks as facts. Industry conversion rates, adoption curves, or cost figures not in the input appear only as `[ESTIMATE]` with a derivation, and an item whose case rests on one stays UNSUPPORTED (as stated).
3. Show the margin math for anything with per-unit COGS — AI features especially. A feature that moves gross margin more than 2 points must have that movement in its mechanism line.
4. UNSUPPORTED items keep their flip condition. The audit's job is to name the missing number, not to kill ideas.

## Limitations

- The audit is as good as the numbers provided; wrong inputs produce a confidently wrong audit — garbage in is not detectable from inside.
- Mechanisms are causal hypotheses made explicit, not proven causation — the assumed links are flagged so the reader knows which chains to test.
- Second-order effects (competitive response, cannibalization between items) are noted only when the input surfaces them.
- This audits economics, not desirability or feasibility — an item can be SUPPORTED and still be the wrong thing to build.
