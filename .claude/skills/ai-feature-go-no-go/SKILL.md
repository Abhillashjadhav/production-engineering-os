---
name: ai-feature-go-no-go
description: "Strategy-stage skill: turns an AI-feature idea plus context into a build/kill decision that names the single criterion it turns on. Use when the user asks for a go/no-go, build-or-kill, or ship-worthiness call on an AI or LLM-powered feature — 'should we build AI auto-replies', 'build or kill: LLM search', 'make the call on this AI feature' — or when /pm routes such a request here. Do NOT use for non-AI feature prioritization, for mapping assumptions without deciding (assumption-mapper), for model/vendor selection, or for launch-timing decisions."
argument-hint: "<the AI feature + context: users, error tolerance, volume, team, cost>"
---

# AI Feature Go/No-Go

A decision, not a discussion. The output is GO or NO-GO, and it names the one criterion doing the deciding — everything else is ranked context.

## Verification gates (defined first; output is blocked until all pass)

- **G1 — Pivot criterion named:** the decision states the SINGLE disqualifying (for NO-GO) or qualifying (for GO) criterion it turns on. Five co-equal reasons with no named pivot fails the gate. A conditional GO states its exact condition; "it depends" is not a decision.
- **G2 — Non-decisive factors marked:** supporting factors are ranked below the pivot and explicitly marked non-decisive. If removing the pivot wouldn't flip the decision, the pivot is wrong — find the real one.
- **G3 — No fabricated context:** the decision argues from provided context only. No invented compliance rulings, competitor moves, usage benchmarks, or user demand. Arithmetic uses input numbers; anything else is a labeled estimate.

## Steps

1. **Fix the failure surface.** What happens when the AI is wrong, who sees it, and can it be caught before harm? Error tolerance × review point is where most AI features live or die — check it first.
2. **Check the remaining axes,** in order: value density (does the feature remove real work — do the arithmetic on volume and FTEs), feasibility at quality bar (can current models meet the tolerance found in step 1), economics (per-unit cost vs. price/margin — route deep dives to roadmap-reality-check), and trust/adoption (will users accept AI in this moment).
3. **Find the pivot.** One axis almost always decides; the rest calibrate. Test it: if this criterion flipped, would the decision flip? If not, it's not the pivot.
4. **Write the decision.** GO / NO-GO / GO-IF (with the exact condition). Then the reversal line: what change in the world or the feature's design would flip this call — a NO-GO on unreviewed output may be a GO with human-in-the-loop, and the output must say that's a different, smaller feature.
5. **Gate pass.** One named pivot (G1), non-decisive factors marked (G2), every contextual claim traceable to input (G3). Fix and re-run; maximum 2 repair loops, then report the failure instead of the output.

## Output format

```
DECISION: NO-GO
PIVOT CRITERION (disqualifying): unreviewed generative output in a regulated,
payments-adjacent support flow with stated near-zero error tolerance. One wrong
auto-sent answer about a payment is an incident, and nothing in the design catches
it before the customer does.
NON-DECISIVE FACTORS (would not flip the decision alone):
- volume: 400 tickets/mo ÷ 1.5 FTE — no capacity crisis to justify the risk [input math]
- CSAT 4.6/5 — protecting a strength, not fixing a weakness
WHAT WOULD FLIP IT: agent-reviewed drafts instead of auto-send (a different, smaller
feature: GO-worthy on the same context) · or error tolerance materially loosening
GATE CHECK: G1 pass (one pivot) · G2 pass · G3 pass
```

## Hard rules

1. One pivot criterion, named, always. If two criteria genuinely co-decide, pick the one that fails first in deployment order and note the second as next-in-line — never present an unranked list as a decision.
2. Never hedge a decision into meaninglessness. "GO with monitoring and phased rollout" that doesn't name what would disqualify it is not a decision — it's postponed accountability.
3. Never invent context to make the call easier. Missing load-bearing context (error tolerance, volume) → ask for it or state the decision is provisional on the named missing fact.
4. The reversal line is mandatory. A decision that can't say what would flip it hasn't found its own pivot.

## Limitations

- The call is a structured judgment on provided context — it cannot see org politics, roadmap opportunity cost, or strategy fit beyond what the input states.
- Feasibility-at-quality-bar reads current-generation model capability as commonly known; a borderline call deserves a technical spike, and the output says so rather than guessing.
- GO-IF conditions are design requirements, not guarantees the condition is achievable.
- One feature per call; portfolio-level sequencing across many candidate features is roadmap territory.
