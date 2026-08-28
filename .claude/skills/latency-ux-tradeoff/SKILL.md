---
name: latency-ux-tradeoff
description: "Build-stage skill: designs the waiting experience for an AI flow — every recommendation tied to a stated user-tolerance threshold, measured or labeled heuristic, never vibes. Use when latency is shaping UX decisions — 'the summary takes 12 seconds, how should the UX handle it', 'stream or spinner', 'sync or async for a 45-second generation', 'users bail during generation' — or when /pm routes such a request here. Do NOT use to make the model faster (engineering), for model-cost selection (model-complexity-router), for threshold knowledge questions with no flow attached, or for visual spinner styling with no latency tradeoff."
argument-hint: "<the flow + latency numbers (p50/p95) + anything measured about user waiting behavior>"
---

# Latency UX Tradeoff

Waiting is a design surface. Every recommendation here hangs on a number — what users actually tolerate — or it doesn't ship.

## Verification gates (defined first; output is blocked until all pass)

- **G1 — Threshold-tied:** every recommendation cites the user-tolerance threshold it serves — measured from the input when available, otherwise a named heuristic explicitly labeled `[heuristic, not measured on your users]`. "Feels fast enough" fails the gate.
- **G2 — p50 AND p95 designed for:** the tail is a real user, not a rounding error — show the arithmetic (p95 at 30 uses/session ≈ 1.5 tail hits per session). A design that only works at p50 fails.
- **G3 — Mechanism + cost:** each recommendation names its mechanism (stream, skeleton, optimistic UI, async+notify, precompute, cache) and its tradeoff (precompute burns tokens on unopened items; streaming reveals drafts). No invented user research — unstated thresholds are heuristics, labeled.

## Steps

1. **Bank the numbers:** p50/p95, what already renders fast, and any measured waiting behavior (bail rates, session patterns). Measured beats heuristic; a stated "40% bail at 3s" outranks any industry band.
2. **Fix the tolerance thresholds** for THIS flow: from measurements first; where none exist, apply the standard bands (~0.1s imperceptible · ~1s keeps flow · ~10s attention lost) explicitly labeled heuristic. High-frequency flows (30x/session) get tighter thresholds than one-shot flows — state the adjustment.
3. **Compare latency to thresholds** at p50 and p95 separately. Each crossing is a design problem with a named user cost (bail, distrust, context-switch).
4. **Design per crossing,** cheapest mechanism first: don't block what's already fast (ship the 300ms core, load the AI in place) · stream when partial output has value · skeleton/progress when it doesn't · async+notify past the attention threshold · precompute/cache when frequency justifies the spend (route the token math to unit-economics-stress-test if material).
5. **State each mechanism's cost** — tokens, complexity, perceived-quality risk (streaming shows the draft), staleness (precompute). A mechanism with no stated cost is an ad, not a design.
6. **Gate pass.** Every recommendation threshold-cited (G1), tail addressed with arithmetic (G2), mechanisms costed and thresholds provenance-labeled (G3). Fix and re-run; maximum 2 repair loops, then report the failure.

## Output format

```
LATENCY UX: candidate fit-summary (4s p50 / 11s p95 · 30 profiles/session · measured: 40% bail at 3s blocked)
R1. Never block profile render — core data ships at 300ms, summary loads into a card
    [threshold: measured 3s/40% bail — blocking would cross it on every open]
R2. Stream the summary into the card as it generates
    [threshold: interviews — "appears while they scan"; p50 4s lands mid-scan]
    cost: partial text visible; mitigation: sentence-level chunks
R3. p95 (11s > 3s bail line, ~1.5 hits/session at 30 profiles): skeleton + "still
    writing" state; past 10s [heuristic band, labeled] offer notify-when-ready
    cost: an extra UI state to build and test
CONSIDERED, NOT CHOSEN: precompute on list view — kills all waiting, but burns tokens
on unopened profiles → route to unit-economics-stress-test before adopting.
GATE CHECK: G1 pass (n/n threshold-cited) · G2 pass (p50+p95, math shown) · G3 pass
```

## Hard rules

1. No recommendation without its threshold, and no threshold without provenance — measured (cited from input) or heuristic (labeled). Vibes are banned.
2. Never contradict the user's measurements with generic reassurance. "Users don't mind short waits" against a measured 40% bail is fabrication.
3. The p95 user is designed for, with the frequency arithmetic shown.
4. Every mechanism ships with its cost. Recommendations that only list benefits fail their own tradeoff.

## Limitations

- Heuristic bands are population-level defaults, not your users — the label exists so the reader knows which recommendations deserve a measurement before hardening.
- The skill designs the waiting experience; it doesn't reduce latency (engineering) or price the mechanisms (unit-economics-stress-test — flagged when material).
- Perceived latency varies with user intent (scanning vs deciding); the design targets the stated flow, and a different flow re-runs the call.
- Streaming recommendations assume the backend can stream; if unknown, that's a stated prerequisite, not an assumption.
