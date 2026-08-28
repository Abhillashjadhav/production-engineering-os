---
name: launch-checklist
description: "Launch-stage skill: turns a feature plus team context into a tailored launch checklist where every item has a named owner role and a verifiable done condition. Use when a ship date is approaching and the work needs enumerating — 'build the launch checklist', 'what do we need before we ship', 'launch readiness list', 'we ship in 3 weeks, what has to happen' — or when /pm routes such a request here. Do NOT use to write announcements (announcement-drafter), GTM one-pagers (gtm-brief), ship/no-ship decisions (ai-feature-go-no-go), or for definitions of launch process."
argument-hint: "<the feature + context: teams that exist, rollout mechanics, regions, pricing, current state>"
---

# Launch Checklist

A checklist where every box can actually be checked: named owner, observable done condition, no ceremonial items.

## Verification gates (defined first; output is blocked until all pass)

- **G1 — Owner + verifiable done, every item:** each item carries a named owner role drawn from the stated context and a done condition someone can verify by looking ("macro IDs listed", "flag removed for cohort 1", "residency test passed on EU workspace"). "Align with X" and "make sure Y is ready" fail the gate.
- **G2 — Context-tailored, context-bounded:** items derive from the stated context; owners are roles that exist in it. Generic-template items that contradict context (PR agency, app-store assets for a B2B web product) fail, as does inventing teams the input didn't mention.
- **G3 — Rollback is an item:** the checklist contains rollback criteria with an owner and an observable trigger; unknown thresholds are labeled placeholders for the user to fill, never invented numbers.

## Steps

1. **Bank the context:** teams that exist (and their stated readiness), rollout mechanics (flag? cohorts?), regions and their constraints, pricing decisions, existing surfaces (docs, status page). This inventory bounds who can own anything.
2. **Walk the failure surfaces, not a template:** how does this launch break? Unprepared support, unwired billing, region compliance, missing rollback path, stale docs. Each stated context element that can fail becomes items; template items that match nothing stated get cut.
3. **Write each item to pass G1:** owner role from the inventory · action · done condition observable enough that a second person could audit the box. Quantities from context (3 support agents, 4 salespeople) make conditions concrete.
4. **Sequence into phases:** blockers-before-ship · day-of · week-after. An item with no phase hasn't been thought about; place everything.
5. **Add the rollback item:** trigger (labeled placeholder if the threshold isn't stated), mechanism (the flag that exists), owner, and the communication step that follows it.
6. **Gate pass.** Every item owner+done checked (G1), every owner exists in context and every item earns its place (G2), rollback present (G3). Fix and re-run; maximum 2 repair loops, then report the failure.

## Output format

```
LAUNCH CHECKLIST: AI summaries GA (context: 3 support · 4 sales · EU residency · flag · +$10/seat)
BLOCKERS BEFORE SHIP
☐ Support enablement — owner: support lead — done when: all 3 agents ran the feature
  on 2 test workspaces AND top-5-question macros exist (macro IDs listed)
☐ EU residency check — owner: PM + eng — done when: summary generation verified to
  run in EU region for an EU workspace (test workspace evidence attached)
☐ Billing wiring — owner: PM — done when: +$10/seat add-on purchasable and appears
  on a test invoice
DAY OF
☐ Flag removal cohort 1 (10%) — owner: eng — done when: flag off for cohort, error
  dashboard green for 4h
WEEK AFTER
☐ ...
ROLLBACK — owner: eng on-call — trigger: summaries error rate > [X% — set before ship,
not set here] → re-enable flag → status page + in-app notice within 30 min
GATE CHECK: G1 pass (n/n owner+done) · G2 pass (0 phantom teams) · G3 pass
```

## Hard rules

1. No item without an owner and a verifiable done condition. A box that can't be audited is decoration.
2. Owners are roles from the stated context only. If a needed function doesn't exist (no marketing team), the checklist says so as a gap — it doesn't staff a phantom.
3. Never invent thresholds, dates, or readiness states. Unknowns are labeled placeholders assigned to someone to resolve — that resolution is itself an item.
4. Every item sits in a phase, and rollback is always present. A launch plan without a rollback path is a hope, not a plan.

## Limitations

- The checklist enumerates and assigns; it cannot verify completion — the done conditions are written so a human (or a later /pm run) can.
- Tailoring is bounded by the stated context; undisclosed teams, dependencies, or compliance regimes produce gaps the checklist can't name.
- Rollback design here is operational (trigger/mechanism/comms), not architectural — deep rollback engineering belongs to the eng team.
- Phase timing is relative (before/day-of/after); calendar dates need the user's release plan.
