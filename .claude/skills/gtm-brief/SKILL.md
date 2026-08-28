---
name: gtm-brief
description: "Launch-stage skill: turns a feature plus its evidence into a GTM one-pager where every audience claim is tied to a stated source or labeled assumption. Use when a launch needs its go-to-market summarized on one page — 'draft the GTM one-pager', 'GTM brief for the launch', 'who are we selling this to and how', 'GTM summary for sales kickoff' — or when /pm routes such a request here. Do NOT use for full GTM strategy authoring, launch checklists (launch-checklist), announcements (announcement-drafter), or GTM definitions."
argument-hint: "<the feature + everything known: sales notes, ticket data, win/loss, pricing, customer base>"
---

# GTM Brief

One page on who buys and why — with every audience claim wearing its receipt or its `[ASSUMPTION]` label. Enthusiasm is not evidence.

## Verification gates (defined first; output is blocked until all pass)

- **G1 — Sourced or labeled, every audience claim:** who wants this, what they'll pay, why now — each tied to a stated source from the input (sales notes, ticket export, win/loss doc) or carrying `[ASSUMPTION: … — validation step]`. A bare audience claim fails.
- **G2 — Numbers reconcile:** figures quoted from the input exactly (41 tickets is 41, or honestly "dozens" — never "hundreds"). Pre-launch metrics have no baselines; the brief says "none — pre-launch" instead of inventing one.
- **G3 — Evidence-bounded scope:** positioning targets only competitors the input evidences; channels are only the motions that exist; the brief names its own weakest evidence in one line.

## Steps

1. **Inventory the evidence:** every demand signal, loss reason, and customer fact in the input, with its source tag. This inventory is the universe claims may cite — the same rule as competitor-teardown's OBSERVED discipline, pointed at your own market.
2. **Read the signals honestly.** 41 feature requests are demand for the capability, not proof of willingness to pay $10 — the brief keeps those separate, converting evidence gaps into labeled assumptions with validation steps ("attach-rate ≥15% [ASSUMPTION — measure in first 30 days]").
3. **Write the page:** audience & evidence · problem & today's alternative · positioning (competitor named only with cited basis) · channels (stated motions only) · pricing (as decided) · success measures (metric + target-or-assumption + baseline-or-"none — pre-launch").
4. **Confess the weakest link.** One line: the claim the launch most depends on with the least evidence behind it. Every honest GTM brief has one; a brief that doesn't is hiding it.
5. **Gate pass.** Every audience claim sourced/labeled (G1), every figure reconciled against input (G2), scope bounded and weakest link present (G3). Fix and re-run; maximum 2 repair loops, then report the failure.

## Output format

```
GTM BRIEF: AI meeting summaries — +$10/seat add-on
AUDIENCE: 10-50 seat agencies (our base skew [source: workspace data]) with active
demand signal: 41 'automatic recap' tickets YTD [source: tagged export], 3 enterprise
deals stalled on 'no AI features' [source: sales notes Q2]
PROBLEM & ALTERNATIVE: manual recaps post-call; losing 'AI-first' evaluations to
Fireflies [source: win/loss — 2 of 9 losses]
POSITIONING: summaries inside the scheduling flow they already use, vs. adding a
separate AI notetaker [basis: the win/loss pattern above]
CHANNELS: self-serve upgrade path + 4-person sales team on the 3 stalled deals [stated motions]
PRICING: +$10/seat (decided)
SUCCESS: attach rate ≥15% in 90 days [ASSUMPTION: no usage data pre-launch — measure
from day 1; baseline: none — pre-launch] · reopen 3 stalled deals [source: sales notes]
WEAKEST EVIDENCE: willingness to pay $10 — demand signals are feature requests, none
priced. Validate: first-30-day attach rate vs. the assumption above.
GATE CHECK: G1 pass (n/n sourced or labeled) · G2 pass · G3 pass
```

## Hard rules

1. No audience claim without a source tag or an ASSUMPTION label. "Customers consistently tell us…" requires the quotes to exist in the input.
2. Demand evidence never silently becomes pricing evidence. Feature requests, stalled deals, and loss reasons each support exactly what they support.
3. Never invent market stats, competitor claims, or baselines. Pre-launch means no usage numbers — the brief says so where a number would normally sit.
4. The weakest-evidence line is mandatory. Selling the launch to your own team on hidden assumptions is how GTM briefs fail.

## Limitations

- The brief is as good as the evidence inventory; signals the user didn't provide can't strengthen (or honestly weaken) it.
- Assumptions are labeled and paired with validation steps, but the brief doesn't run the validation — first-30-day data does.
- One page enforces selection: secondary audiences and channels are cut, not compressed; a multi-segment GTM needs one brief per segment.
- Positioning language here is strategic framing, not final copy — announcement-drafter owns the public words and its own overclaim gate.
