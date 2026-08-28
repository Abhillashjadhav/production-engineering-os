---
name: stakeholder-update
description: "Launch-stage skill: turns raw project state into audience-calibrated status updates whose numbers reconcile exactly to the input — emphasis varies by audience, facts never do. Use when project state needs communicating — 'write the launch status update for the exec team', 'weekly stakeholder update from these notes', 'update sales on where the launch stands' — or when /pm routes such a request here. Do NOT use for public launch announcements (announcement-drafter), for logging decisions to memory (pm-context-system), for one-off meeting summaries, or for cadence-process questions."
argument-hint: "<the project state: numbers, dates, issues, targets + who the update is for>"
---

# Stakeholder Update

The same truth, calibrated per audience. Emphasis and detail change with the reader; the numbers and the bad news never do.

## Verification gates (defined first; output is blocked until all pass)

- **G1 — Numbers reconcile:** every figure in the update appears in, or derives arithmetically from, the input state. No invented progress: nothing "on track" that the state marks late, no sentiment claims ("customers love it") without a signal in the state.
- **G2 — Calibration without drift:** audience versions differ in emphasis, ordering, and detail level — never in facts. Bad news present in the state appears in every version; a risk visible to engineering but hidden from the exec update fails the gate.
- **G3 — Context travels with comparisons:** a number measured against a target or assumption keeps its time frame and basis (11% at day 12 of a 90-day 15% assumption — not "missing target", not "strong adoption"). Delays carry cause + recovery, not omission.

## Steps

1. **Reconcile first.** Extract every number, date, target, and issue from the state into a fact table. This table is the update's source of truth — both versions cite it, and the gate check re-derives against it.
2. **Sort facts by audience relevance,** not by comfort: exec (risk, trajectory, decisions needed), sales (customer-visible wins, timing, talking points), team (details, blockers, credit). Relevance ranks facts; it never removes the uncomfortable ones.
3. **Frame comparisons honestly.** Every actual-vs-target keeps its denominator and clock (day 12 of 90). Ahead/behind/too-early-to-call each have a legitimate framing; pick the true one.
4. **Write the versions:** lead with what this audience must know, three-to-six tight facts with their anchors, delays with cause + recovery, then the audience-specific ask or next step from the state.
5. **Gate pass.** Re-derive every figure against the fact table (G1), diff the versions for missing bad news (G2), check every comparison for its context (G3). Fix and re-run; maximum 2 repair loops, then report the failure.

## Output format

```
FACT TABLE (from state): 40% rollout (target 100% Fri, 2d late — residency bug, fixed Tue)
· attach 11% at day 12 (assumption: 15% by day 90) · 14 tickets / 2 escalations (both
the bug) · 1 of 3 stalled deals reopened · error 0.3% vs 0.5% rollback line · cohort 3 Thu

TO EXEC — AI summaries: late but recovering, risk contained
Rollout at 40% vs 100% planned — 2 days late on an EU residency bug, fixed Tuesday;
cohort 3 resumes Thursday. Attach 11% at day 12 against a 15%-by-day-90 assumption —
tracking, too early to call. Errors 0.3% vs 0.5% rollback line. 2 escalations, both
the fixed bug. Decision needed: none this week.

TO SALES — one deal back, timing for the rest
Stalled deal #1 reopened, demo booked. Full rollout completes after Thursday's cohort
— safe to schedule demos from Friday. Known issue to acknowledge if asked: EU delay,
fixed. Attach 11% at day 12 (early).
GATE CHECK: G1 pass (n/n reconciled) · G2 pass (bad news in both) · G3 pass
```

## Hard rules

1. Every number re-derives from the state. If the state doesn't say it, the update doesn't claim it — including mood ("team is confident") and reception ("well received").
2. Bad news is never audience-filtered. Calibration decides how prominently, never whether.
3. Comparisons keep their clocks. An early number measured against a later target is framed as early, not as a miss and not as a win.
4. "On track" is a claim about the plan in the state, not a reassurance. Late is written as late, with cause and recovery.

## Limitations

- The update is only as current as the state provided; it reports, it doesn't fetch — stale input produces a faithful stale update.
- Audience calibration follows the stated audiences and their stated interests; unlisted audiences need another pass.
- The skill formats truth; it can't detect state that is itself wrong (a padded input produces a faithfully padded update).
- Tone is professional-neutral; org-specific voice is the user's edit, and the numbers must survive that edit.
