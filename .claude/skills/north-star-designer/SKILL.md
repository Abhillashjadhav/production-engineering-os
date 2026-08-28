---
name: north-star-designer
description: "Strategy-stage skill: designs a north star metric and its input-metric tree for a product — the NSM must be leading, not lagging, and the output states the causality check it passed. Use when the user wants to choose or fix their top metric — 'design a north star metric', 'what should our NSM be', 'is MRR a good north star', 'build the metric tree' — or when /pm routes such a request here. Do NOT use for definitions of metric concepts, for analytics instrumentation setup, for diagnosing why a metric moved (research-brief), or for setting OKR targets on existing metrics."
argument-hint: "<the product + how it makes money + anything known about what drives retention>"
---

# North Star Designer

A product in, a metric tree out — rooted in a number that leads value, not one that reports it after the fact.

## Verification gates (defined first; output is blocked until all pass)

- **G1 — Leading, with the check stated:** the proposed NSM passes the causality test, written out in the output: *when this number moves this week, revenue/retention moves later — and the reverse is not true*, plus what a team can do this week to move it. Revenue, churn, NPS, and their composites are lagging — proposing one as NSM fails the gate.
- **G2 — Tree is actionable:** every input metric maps to the team or lever that moves it. An input metric no one owns fails.
- **G3 — Gaming named:** the output names at least one way the NSM can be gamed and pairs a guardrail metric against it. No invented correlations or benchmark values — the tree builds on stated facts, and assumed links are labeled assumptions.

## Steps

1. **Locate the value moment.** What event means the user got what they came for (meeting successfully scheduled, document shipped, ticket resolved)? The NSM lives at or next to this moment — value delivered, countable, weekly-moveable.
2. **Run the causality test on candidates.** For each candidate: does moving it move revenue later (leading), or does revenue move it (lagging)? Write the test result for the winner — this sentence is the gate's evidence. If the user currently tracks a lagging NSM, reject it explicitly with the classification and reason.
3. **Shape the NSM.** Rate over raw count where volume masks quality (successfully scheduled per active team, not total bookings); per-unit where growth masks decay. State the exact definition: numerator, denominator, window.
4. **Build the tree.** NSM at root → 2–4 input metrics that mechanically compose or drive it, each mapped to its owner/lever (integrations connected → onboarding team; scheduling success rate → product reliability). Use stated facts (e.g. a known retention correlation) as tree structure; label every assumed link.
5. **Name the gaming path.** How would a team hit the number while destroying the value (auto-scheduling junk meetings)? Pair the guardrail (meetings kept / not cancelled within 24h).
6. **Gate pass.** Causality check written (G1), every input owned (G2), gaming + guardrail present, no invented data (G3). Fix and re-run; maximum 2 repair loops, then report the failure instead of the output.

## Output format

```
NORTH STAR: weekly meetings successfully scheduled per active team
  (numerator: meetings booked and not cancelled <24h; denominator: teams with ≥1 active user that week)
CAUSALITY CHECK (leading): teams scheduling more successful meetings this week renew
and expand seats later; raising MRR does not cause more meetings. Weekly lever: fix
scheduling failures, drive calendar+video connection.
REJECTED: MRR (current) — lagging: records value already captured; not weekly-actionable.
TREE
├─ teams fully connected (calendar + video) — owner: onboarding [stated retention correlation]
├─ scheduling success rate — owner: product/reliability
└─ weekly active teams — owner: growth
GAMING: junk/auto meetings inflate the count → guardrail: % meetings kept (not cancelled/no-show)
GATE CHECK: G1 pass (check stated) · G2 pass (n/n owned) · G3 pass
```

## Hard rules

1. The causality check is written into the output, always. An NSM asserted as "leading" without the test sentence fails its own gate.
2. Lagging metrics are rejected by name and class when the user proposes them — never softened into "also track MRR as your north star alongside…". One north star; lagging metrics live downstream as results.
3. Never invent correlations. "X drives retention" appears in the tree only if the input stated it or it's labeled an assumption to verify.
4. Every metric ships with its exact definition (numerator, denominator, window). An undefined metric can't be gamed-checked or owned.

## Limitations

- The causality test is a design-time argument, not a measured proof — the output flags that the NSM→revenue link should be validated against cohort data once instrumented.
- Tree structure leans on stated facts and labeled assumptions; a product with no known retention driver gets a provisional tree and says so.
- Guardrails catch the named gaming path, not all gaming paths.
- Instrumenting the metrics and setting targets are downstream work — this skill defines what to measure, not the dashboards or the numbers to hit.
