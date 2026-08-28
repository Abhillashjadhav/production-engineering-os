---
name: model-complexity-router
description: "Build-stage skill: scores a concrete task on a four-axis complexity rubric and recommends the right Claude tier (Haiku/Sonnet/Opus). Use when the user asks which model a task needs — 'which model should I use', 'is this an Opus task', 'am I overpaying for this', 'route this to the right model' — giving the full scored breakdown; also use proactively on any substantial task handoff, emitting one compact line without delaying the task. Fires once per distinct task. Do NOT use for vendor comparisons, knowledge questions, pricing lookups with no task, or repeatedly on follow-up messages about an already-scored task."
argument-hint: "<the task to route — or hand over any task and get the compact line>"
---

# Model Complexity Router

A task in, a tier out — with the four axis scores shown, and the error-cost rule applied exactly once.

## Verification gates (defined first; output is blocked until all pass)

- **G1 — Scores shown:** every recommendation displays the four axis scores it derived from (scope, reasoning depth, error cost, context load — each 0–2) and their sum. A tier with no visible scoring fails.
- **G2 — Floor applied exactly once:** error cost enters the total once, at scoring. The floor rule (error-cost 2 → never Haiku) applies only at the mapping step, only if the mapped tier came out Haiku. Any path where error cost moves the outcome twice — in the sum AND as a bump — fails the gate.
- **G3 — Honest capability claim:** the output never claims to have switched the session's model. It recommends (user acts via /model) or delegates to a pinned subagent if one exists — and says which.

## The rubric

| Axis | 0 | 1 | 2 |
|---|---|---|---|
| Scope | single file/artifact, cosmetic | one feature, few files | multi-file, architectural |
| Reasoning depth | mechanical, pattern-match | known patterns, some judgment | novel tradeoffs, design decisions |
| Error cost | trivially reversible | rework hours | compounds (prod, money, public) |
| Context load | one prompt | a few files | large cross-file synthesis |

Sum 0–8 → **0–2 Haiku · 3–5 Sonnet · 6–8 Opus.** Then the floor: if error cost scored 2 and the map says Haiku, raise to Sonnet — nothing else changes, and never raise an already-Sonnet/Opus result.

## Steps

1. **Detect mode.** Direct model question → full breakdown (Step 3 format). Substantial task handoff with no model question → score silently, emit one compact line above the task response, never blocking the task. No concrete task at all → don't classify hypotheticals; ask for the task. One firing per distinct task.
2. **Score the four axes** with a one-phrase basis each. The basis is what makes the score auditable — no bare digits.
3. **Map and floor.** Sum → tier. Apply the floor only as defined. Show the arithmetic.
4. **Emit.** Full form: task restatement, per-axis scores + bases, total, tier, ~cost delta vs. defaulting to the top tier (labeled approximation), and the two execution paths (switch via /model, or delegate). Compact form: `[Model check] score X/8 → <tier> — <one-phrase driver> · switch/delegate/continue`.
5. **Gate pass.** Scores visible (G1), error cost counted once (G2 — re-add the four digits; if the shown total ≠ sum of shown axes, it double-counted), no switching claim (G3). Fix and re-run; maximum 2 repair loops, then report the failure.

## Output format

```
TASK: rewrite pricing-page copy (customer-facing)
SCORES: scope 0 (one page) · reasoning 1 (known patterns) · error-cost 2 (public, compounds) · context 0 → TOTAL 3/8
TIER: Sonnet (map 3–5; floor n/a — map already ≥ Sonnet)
COST: ~5x cheaper than defaulting to Opus [approximation from published per-MTok pricing]
EXECUTE: /model sonnet — or delegate; I cannot switch the session myself.
GATE CHECK: G1 pass (4 axes shown, 0+1+2+0=3) · G2 pass (floor checked once, not triggered) · G3 pass
```

## Hard rules

1. Never emit a tier without the four scores and their sum. The scores are the recommendation; the tier is just the map.
2. Error cost influences the outcome exactly once. If you find yourself writing "plus a bump for risk" after summing, that's the double-count defect — delete the bump.
3. Never claim to change the session model; no hook or skill can. Recommend or delegate, stated plainly.
4. Cost deltas are labeled approximations from published pricing, never invoice-precise claims.

## Limitations

- Axis scores are structured judgments; adjacent scores (±1) are defensible, which can swing a boundary task one tier — the bases exist so the user can re-score.
- The compact line is a nudge, not a gate: the task proceeds on the current model unless the user acts.
- Cost approximations track published per-MTok pricing, which drifts; treat ratios, not dollars, as the signal.
- Tier names track the current Claude lineup; a new lineup needs a remap, not a rescore.
