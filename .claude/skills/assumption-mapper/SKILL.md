---
name: assumption-mapper
description: "Discovery-stage skill: breaks a product idea into its load-bearing assumptions, ranked riskiest-first, each tagged testable/untestable with a proposed test. Use when the user pitches an idea and asks what it depends on — 'map the assumptions', 'what are we betting on', 'what could kill this', 'what needs to be true', 'riskiest assumption first' — or when /pm routes such a request here. Do NOT use to write the PRD or spec (Build stage), to size the market (opportunity-sizer's job), for knowledge questions about assumption-testing methods, or for analyzing non-product documents."
argument-hint: "<the idea or pitch, 1-5 sentences>"
---

# Assumption Mapper

An idea in, its bets out — every bet ranked by risk and paired with the test that would settle it.

## Verification gates (defined first; output is blocked until all pass)

- **G1 — Tag completeness:** every assumption carries a `testable` or `untestable` tag. Every `testable` one carries a concrete proposed test (method + the evidence that would confirm or kill it). Every `untestable` one carries why it can't be pre-tested plus either a testable reformulation or an explicit "monitor in market, cannot pre-test" call. A bare tag = gate failure.
- **G2 — Ranking is derived:** risk rank follows stated impact × uncertainty, not listing order or vibes. Both factors appear with a one-line basis each.
- **G3 — No imported evidence:** the map contains no claims of existing user evidence ("users have told us…", uncited stats). Evidence gathering is the tests' job, not the map's.

## Steps

1. **Restate the idea** in one sentence and confirm the wedge: who, what change, why paid/used. Missing pieces are themselves assumptions — surface, don't fill.
2. **Extract assumptions across the four classic risks:** desirability (they want it), viability (they'll pay / it's worth building), feasibility (we can build it well enough), and adoption/trust (they'll actually switch, integrate, or share data). Aim for the load-bearing 5–9, not an exhaustive 30.
3. **Score each:** impact-if-wrong (H/M/L — what breaks if this is false) and confidence (H/M/L — what we actually know today). One line of basis each.
4. **Tag and pair:** `testable` → cheapest decisive test (interview script angle, fake-door, concierge run, design-partner LOI, technical spike) with a kill/confirm signal; `untestable` → why, plus a sharper testable reformulation where one exists.
5. **Rank riskiest-first** (high impact × low confidence at the top) and run the gates. Fix and re-run on failure; maximum 2 repair loops, then report the failure instead of the output.

## Output format

```
IDEA: <one-line restatement>
ASSUMPTIONS (riskiest first)
1. <assumption> — [desirability] impact H (<basis>) · confidence L (<basis>) — TESTABLE
   Test: <method> → kill signal: <evidence> / confirm signal: <evidence>
2. <assumption> — [trust] impact H (…) · confidence M (…) — UNTESTABLE as stated (<why>)
   Reformulate: <testable version> / or: monitor in market — cannot pre-test
GATE CHECK: G1 pass (n/n tagged+paired) · G2 pass · G3 pass
```

## Hard rules

1. No assumption ships without its tag, and no `testable` tag ships without a proposed test. This is the gate the skill exists for.
2. Never manufacture evidence to lower an assumption's risk. Confidence basis must come from the input or be labeled "no data — default low".
3. Proposed tests must be decisive and cheap-first: name the kill signal, not just the activity. "Talk to users" without what-would-change-our-mind is not a test.
4. If everything scores low-risk, say the idea as stated carries no falsifiable bet — that's a finding about vagueness, not a green light.

## Limitations

- The map is only as good as the pitch; a one-line idea yields assumption stubs the user must sharpen.
- Impact/confidence scores are structured judgments, not measurements — two reasonable PMs may differ by a notch; the basis lines exist so the reader can re-score.
- Proposed tests are designs, not executed research; running them (and the research plan around them) is research-brief territory.
- Covers product risk, not legal/regulatory review.
