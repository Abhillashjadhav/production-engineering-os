---
name: model-upgrade-evaluator
description: "Iterate-stage skill: turns a new model release into a re-test plan for current prompts and shelved ideas — every verdict cites a run result, no capability assumed from release notes. Use when a new model version lands — 'new model dropped, what should we re-test', 'worth migrating our prompts?', 'build the upgrade evaluation plan', 're-test our shelved ideas' — or when /pm routes such a request here. Do NOT use to gate an already-decided migration's ship (regression-gatekeeper), for per-task tier routing (model-complexity-router), for release-notes summaries, or for academic benchmarking."
argument-hint: "<the release + your surface: production prompts with their golden sets, the shelved-ideas log with kill reasons, run budget>"
---

# Model Upgrade Evaluator

Release notes are hypotheses. A new model changes two lists — what might now break (current prompts) and what might now work (shelved ideas) — and both get answered by runs, not by the announcement.

## Verification gates (defined first; output is blocked until all pass)

- **G1 — Every verdict cites a run:** MIGRATE/STAY/RESURRECT/STILL-DEAD verdicts exist only with per-case run evidence (counts, deltas, the failing or passing cases named). Before runs execute, every verdict slot reads `PENDING`. Release-note claims appear only as hypotheses-to-test, never as capability facts.
- **G2 — Kill reasons become resurrection tests:** each shelved idea is re-tested against the specific reason it was killed (the historical failing case or its closest reconstruction) — not a fresh demo that avoids the old trap. A resurrection test that doesn't encode the kill reason fails.
- **G3 — Budget-honest coverage:** the plan ranks runs within the stated budget, names what's cut, and marks unscheduled items `UNTESTED — not a verdict`. Claimed coverage beyond scheduled runs fails.

## Steps

1. **Inventory both lists:** production prompts with their golden sets (these re-run under regression-gatekeeper rules — fail-class assertions must hold), and the shelved-ideas log with each idea's kill reason stated as a testable condition.
2. **Convert release-note claims into targeted hypotheses.** "Better instruction-following" → which of our golden failures were instruction-following failures? Those cases are the test. A claim that maps to none of our cases gets a note: "no surface to test this on — irrelevant until we have one."
3. **Design resurrection tests from kill reasons.** "Degraded beyond 4 docs" → the historical 5-doc case (or its reconstruction, labeled). "Hallucinated priorities" → the hallucination check on the old triage inputs. The bar for RESURRECT is the old failure passing, not a new demo dazzling.
4. **Rank within budget:** production prompts first (regression risk is live risk), then shelved ideas by value-if-unblocked. State the cut list. An afternoon buys what it buys; the plan says so.
5. **Pre-commit verdict templates:** MIGRATE (goldens ≥ baseline, deltas cited) · STAY (regressions, cases named) · RESURRECT (kill-reason test passes, run cited) · STILL DEAD (run cited) · UNTESTED (explicitly not a verdict). Fill them only from results.
6. **Gate pass.** No filled verdict without its run evidence (G1), every resurrection test encodes its kill reason (G2), coverage matches schedule (G3). Fix and re-run; maximum 2 repair loops, then report the failure.

## Output format

```
UPGRADE EVALUATION: <model version> (budget: one afternoon)
HYPOTHESES FROM RELEASE NOTES (to test, not to trust)
  H1 "better instruction-following" → classifier goldens #3,#7,#11 (past IF failures)
  H2 "2x context" → multi-doc resurrection test (below)
RE-TEST PLAN (ranked, budget-shaped)
  1. summarizer goldens (14) · 2. support-draft (12) · 3. classifier (20)
  4. shelved: multi-doc synthesis — resurrection test: the historical 5-doc case
     [kill reason: degraded >4 docs] · CUT (budget): auto-triage — UNTESTED
VERDICTS (filled only from runs)
  summarizer: PENDING → [after run: MIGRATE — 14/14, fail-class held, rubric +0.4 avg]
  multi-doc synthesis: PENDING → [after run: RESURRECT only if the 5-doc case passes; else STILL DEAD, run cited]
  auto-triage: UNTESTED — not a verdict; first in queue next budget.
GATE CHECK: G1 pass (0 unrun verdicts) · G2 pass (kill reasons encoded) · G3 pass (cuts named)
```

## Hard rules

1. Nothing is assumed from release notes — not capability, not safety, not cost. Notes generate hypotheses; runs generate verdicts.
2. Resurrection requires the old failure to pass, on the case (or labeled reconstruction) that killed it. New demos that route around the trap prove nothing.
3. UNTESTED is an honest state, never rounded to a verdict in either direction.
4. Production re-tests inherit regression-gatekeeper's tripwire: a fail-class golden passing its bad behavior through = the migration is a HOLD for that prompt, whatever the rest says.

## Limitations

- The evaluation covers your surface, not the model: a clean sweep means your prompts and cases work, not that the model is better in general.
- Reconstructed kill cases (original inputs lost) are labeled and weaker than originals; verdicts on them say so.
- Cost/latency deltas are part of MIGRATE math only when measured in the runs — pricing-page arithmetic goes to unit-economics-stress-test.
- One release per evaluation; comparing three candidate models is this skill run three times plus a decision the user owns.
