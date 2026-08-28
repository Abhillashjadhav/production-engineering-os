---
name: feedback-pattern-miner
description: "Discovery-stage skill: turns a raw feedback dump — support tickets, app-store reviews, NPS verbatims, survey answers — into ranked themes whose counts reconcile exactly to the input total. Use when the user provides a list of discrete feedback items and asks what the patterns, top complaints, or priorities are — 'rank these tickets by theme', 'what are people complaining about most', 'mine this review export' — or when /pm routes such a request here. Do NOT use for interview transcripts (interview-synthesizer's job), for replying to a single feedback item, or for process questions about how to collect feedback."
argument-hint: "<paste the feedback items, one per line or numbered>"
---

# Feedback Pattern Miner

A feedback dump in, ranked themes out — and the books must balance: every input item accounted for, exactly once.

## Verification gates (defined first; output is blocked until all pass)

- **G1 — Reconciliation:** sum of theme counts (including `unclassified`) equals the input item total. The output must show the arithmetic. Off by one = gate failure.
- **G2 — One primary theme per item:** each item is counted in exactly one theme. Overlaps become secondary tags outside the counts.
- **G3 — No invented evidence:** every cited item ID exists in the input; every quoted fragment is a verbatim substring of its item.

## Steps

1. **Number the input.** Assign IDs (F1, F2, …) in given order and state the total N. If the input isn't itemizable (prose, transcript), stop and route: interview material belongs to interview-synthesizer.
2. **Cluster.** Group items by the underlying problem, not surface wording ("sync breaks" and "events dropped" are one theme). Name each theme by the user problem, not the feature request phrasing.
3. **Force nothing.** Items that fit no theme go to `unclassified` — a counted bucket, not a trash can. Force-fitting noise into a theme to look tidy is a gate failure.
4. **Count and rank.** Primary assignment only. Rank themes by count, descending; ties broken by severity of language in the items, stated as a judgment.
5. **Gate pass.** Verify: counts sum to N (G1), no item in two counts (G2), every ID and quote real (G3). Fix and re-run on failure; maximum 2 repair loops, then report the failure instead of the output.
6. **Deliver** with the reconciliation line and one representative verbatim fragment per theme.

## Output format

```
THEMES (N items in)
1. <theme name> — <count> items: F4, F7, F1
   e.g. "sync dropped my events again" [F4]
...
unclassified — <count> items: F10

RECONCILIATION: 3+3+2+1+1 = 10 of 10 items accounted for ✔ (each counted once)
Secondary tags (not counted): F2 also touches onboarding
GATE CHECK: G1 pass · G2 pass · G3 pass
```

## Hard rules

1. Never drop an item. An item you can't place goes to `unclassified`, visibly counted.
2. Never count an item twice. Cross-cutting items get one primary theme (the user's main complaint) plus an uncounted secondary tag.
3. Counts are counts, not impressions — recount the IDs listed per theme before showing the reconciliation line; the listed IDs are the ground truth for the number.
4. Ranking is by evidence in this dataset only. Never inflate a theme because it "feels" more common than the count shows, and never import frequency claims from outside the input.

## Limitations

- Themes reflect this input set only — a support-ticket dump over-represents users angry enough to write; say so when the source skews.
- Clustering granularity is a judgment call; the counts are exact but two reasonable people might split/merge themes differently. The item IDs per theme let the reader re-cut them.
- Counts measure frequency, not impact — a 1-item theme can still be a churn risk; ranking by count is a starting order, not a roadmap.
- Very large dumps (500+ items) should be batched; the gate arithmetic still applies per batch and in the merged total.
