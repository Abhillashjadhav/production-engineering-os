---
name: prototype-first-workflow
description: "Build-stage skill: turns a feature idea into the smallest testable prototype plan — built around what the prototype must disprove, not what it should demonstrate. Use when the user wants to test before building — 'plan the smallest prototype', 'how do we prototype this before committing', 'design the spike', 'fastest way to test if this works' — or when /pm routes such a request here. Do NOT use to execute the build, to make the build/kill call itself (ai-feature-go-no-go), to map assumptions without a test plan (assumption-mapper — its riskiest assumption is this skill's input), or for definitions of prototyping methods."
argument-hint: "<the feature idea + the risk you're arguing about + what users/partners you can reach>"
---

# Prototype-First Workflow

Prototypes exist to kill bad ideas cheaply. A prototype that can only succeed is a demo — this skill plans the one that can fail.

## Verification gates (defined first; output is blocked until all pass)

- **G1 — Kill hypothesis named:** the plan states what the prototype must DISPROVE — a falsifiable claim with a numeric threshold set before the run ("recruiters discard >80% of senior-candidate drafts"). Demonstrate-only plans ("show the drafts are useful") fail the gate.
- **G2 — Minimum lethal build:** every component of the plan is justified by the kill test. Scope that serves the demo but not the test is cut; if a cheaper build (Wizard-of-Oz, concierge, template sidecar) can kill the hypothesis, the plan must use it or say why not.
- **G3 — Consequences pre-committed:** thresholds carry their basis, measurement is defined (what's logged, window, N — from stated context only), and both branches exist: if killed → what, if survived → what. No invented user counts or benchmark thresholds.

## Steps

1. **Extract the fight.** What is the team actually arguing about? That disagreement is the kill hypothesis's home — the fixture risk ("recruiters won't trust AI drafts with senior candidates") converts directly. If nothing is contested, ask what would make the team abandon the idea; if truly nothing would, say the prototype is theater and stop.
2. **Write the kill hypothesis:** falsifiable, thresholded, time-boxed. Use the team's own claims as bars ("saves 30 min/day" → the prototype must clear it). The threshold's basis is stated — team claim, prior data, or an explicit stake-in-the-ground labeled as such.
3. **Design the minimum lethal build.** Start from the cheapest tier — paper/concierge → Wizard-of-Oz → sidecar/stub → flagged feature — and take the first tier that can genuinely kill the hypothesis. Justify each component against the test; name what was deliberately cut.
4. **Define measurement:** metrics (edit distance, discard rate, time-on-task), instrumentation, run window, and who participates — drawn from the stated context (e.g. 2 of 5 partner agencies), never invented cohorts.
5. **Pre-commit both branches.** Killed → the named decision (drop, reshape, retest a narrower claim). Survived → the next-larger test or the build ticket, with what changes in confidence. Write these BEFORE the run so results can't be renegotiated.
6. **Gate pass.** Kill hypothesis + threshold present (G1), every component test-justified (G2), measurement + branches from stated context (G3). Fix and re-run; maximum 2 repair loops, then report the failure.

## Output format

```
PROTOTYPE PLAN: AI-suggested replies (recruiting CRM)
KILL HYPOTHESIS (must disprove): "recruiters edit-beyond-recognition or discard >80%
of drafts on senior-candidate emails" — threshold basis: team's trust concern, stated
BUILD (minimum lethal): LLM sidecar drafting from 5 templates; no CRM integration;
2 of 5 partner agencies; 2 weeks. CUT: UI polish, all-role coverage, auto-send (serve demo, not test)
MEASURE: per-draft accept/edit/discard + edit distance + self-reported time, logged daily
IF KILLED: drop senior-candidate scope; retest junior-only claim before any build
IF SURVIVED: flagged pilot at all 5 agencies with the 30-min/day bar as the next kill line
GATE CHECK: G1 pass (falsifiable + threshold) · G2 pass (each component justified, cuts named) · G3 pass
```

## Hard rules

1. No plan ships without its kill hypothesis. "What must this disprove?" has an answer or the prototype is a demo — say which.
2. The team's own claims become the thresholds. A prototype that measures against softer bars than the pitch is rigged.
3. Never invent cohorts, baselines, or industry thresholds. Participants and bars come from the stated context or are labeled stakes-in-the-ground.
4. Both branches are written before the run. A plan with only a success path has already decided the result.

## Limitations

- The plan is a test design; running it, recruiting the users, and instrumenting the build are execution work.
- A survived kill hypothesis reduces one risk — it doesn't validate the feature; the plan says what the next test is, not that the idea is proven.
- Cheap-tier builds (Wizard-of-Oz) test desirability and behavior, not feasibility at scale — feasibility hypotheses need the sidecar tier or above, and the plan flags when that's the real question.
- Threshold choices with no prior data are labeled stakes-in-the-ground; they anchor honestly but aren't derived.
