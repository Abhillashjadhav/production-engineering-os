---
name: regression-gatekeeper
description: "Iterate-stage skill: gates any prompt or model change behind a golden-set regression run — the run happens and its results are shown before any ship verdict exists. Use when a change wants to ship — 'we tweaked the prompt, safe to ship?', 'regression plan before the model swap', 'gate this change', 'what has to run before this goes out' — or when /pm routes such a request here. Do NOT use to decide whether an upgrade is worth pursuing (model-upgrade-evaluator), to build the golden set (golden-dataset-builder), for post-incident capture (failure-to-eval-capture), or for regression-testing definitions."
argument-hint: "<the change (prompt diff / model swap) + the golden set that exists + the intended ship date>"
---

# Regression Gatekeeper

No run, no verdict. The golden set exists to be run before shipping — a ship opinion formed without results is the failure this skill exists to prevent.

## Verification gates (defined first; output is blocked until all pass)

- **G1 — Run before verdict:** a ship verdict (SHIP/HOLD/INVESTIGATE) appears only alongside the golden-run results that justify it. With no run yet, the output is a run plan and `VERDICT: PENDING` — "the change is small, low risk" is not a verdict input.
- **G2 — Verdict rules pre-committed:** SHIP/HOLD/INVESTIGATE criteria are written before results arrive (zero gate regressions; any captured failure passing through = HOLD; drift bounds for INVESTIGATE) — so the results can't be renegotiated into a ship.
- **G3 — Per-case results + scope honesty:** results are shown as a per-case table (id, class, baseline, new, delta), never only an aggregate; the plan states what the golden set does NOT cover, and changes introducing new requirements with zero golden coverage get flagged for case collection before they can be gated.

## Steps

1. **Bank the change and the set:** what changed (prompt diff, model version), the golden set's size and class split (pass-class / fail-class), and whether baseline outputs are stored — if not, the plan runs both sides on the same cases.
2. **Write the run plan:** every golden runs on the changed configuration; fail-class cases must still catch their failure (the captured incident's assertion holds); pass-class cases must still pass their gates with rubric scores within the stated drift bound of baseline.
3. **Pre-commit the verdict rules,** before any result exists: SHIP = zero gate regressions and drift within bounds · HOLD = any fail-class case's bad behavior now passes through (the change reintroduced a captured failure) · INVESTIGATE = pass-class gate flips or drift beyond bounds on ≥N cases. These rules ship in the plan.
4. **Check coverage against the change's intent.** A change made FOR a new requirement (shorter summaries) that has zero golden coverage cannot be certified for that requirement — flag it, route 2–3 new human-verdicted cases to golden-dataset-builder, and say the gate covers regressions only until they exist.
5. **On results: apply the rules as written.** Produce the per-case table, apply the pre-committed criteria mechanically, and give the verdict with the failing/flipping cases named. A result that argues for renegotiating the rules gets an INVESTIGATE and a rule-review note, never an in-flight rule edit.
6. **Gate pass.** No verdict without results (G1), rules pre-committed and unedited (G2), table + coverage statement present (G3). Fix and re-run; maximum 2 repair loops, then report the failure.

## Output format

```
REGRESSION GATE: summarizer prompt change (shorter summaries) · golden set: 14 (9 pass / 5 fail-class)
RUN PLAN: all 14 on changed prompt; baseline = current prod prompt, same cases (both
sides run — no stored baselines). Pass criteria: fail-class assertions hold (incl.
F-4521 entity-invention); pass-class gates pass, rubric within 1pt of baseline.
VERDICT RULES (pre-committed): SHIP = 0 gate regressions, drift ≤1pt ·
HOLD = any fail-class case passes its bad behavior · INVESTIGATE = pass-class flip
or >1pt drift on ≥2 cases.
COVERAGE FLAG: "shorter summaries" has 0 golden coverage — the set gates regressions,
not the new requirement; 2-3 length-verdicted cases needed (→ golden-dataset-builder).
VERDICT: PENDING — no run, no verdict.
[after the run: per-case table — id · class · baseline · new · delta — then the
verdict per the rules above, failing cases named]
GATE CHECK: G1 pass (no unrun verdict) · G2 pass (rules pre-committed) · G3 pass
```

## Hard rules

1. No ship verdict without run results in hand. "Low risk" reasoning postpones the run; it never replaces it.
2. Verdict rules are written before results and never edited mid-flight. Results that want different rules get INVESTIGATE plus a rule-review note.
3. A reintroduced captured failure is an automatic HOLD — the golden set's fail-class cases are non-negotiable tripwires, whatever the aggregate looks like.
4. The gate certifies only what the set covers; uncovered requirements are named, not waved through under a green aggregate.

## Limitations

- The gate is as strong as the golden set; a thin set produces an honest-but-narrow certification, said explicitly with the coverage statement.
- This skill plans and adjudicates the run; executing 14 cases through the pipeline is operational work (the run plan is written to be executable by hand or CI).
- Rubric-drift bounds involve judge scoring and inherit judge calibration state — a stale judge widens error bars; recalibrate (judge-calibration-auditor) before high-stakes gates.
- Behavioral regressions outside the golden set's captured space are invisible here; production drift monitoring (drift-monitor-designer) is the complementary net.
