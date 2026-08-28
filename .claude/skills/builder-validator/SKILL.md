---
name: builder-validator
description: "Build-stage skill: freeze requirements into binary criteria, generate the artifact, then self-audit against the frozen criteria verbatim before delivery. Use when the user asks for an artifact WITH requirements attached — 'draft X and check it against these requirements', 'build Y to this spec', 'generate and self-QA before showing me' — or when /pm routes a spec-bearing generation request here. Do NOT use when no requirements exist to freeze, for reviewing work the user wrote themselves, for building eval harnesses from specs (prd-to-eval), or for knowledge questions about QA."
argument-hint: "<what to build + the requirements it must satisfy>"
---

# Builder-Validator

Freeze the checklist, then build, then grade against the frozen checklist — verbatim, every row, fails included.

## Verification gates (defined first; output is blocked until all pass)

- **G1 — Criteria frozen before generation:** requirements become numbered binary criteria (C1…Cn) before any artifact text is written, and they never change afterward. Criteria softened, reworded, or added post-generation fail the gate.
- **G2 — Full verbatim audit:** the delivered output includes the audit table — every frozen criterion quoted verbatim with PASS/FAIL and one line of evidence from the artifact. n frozen → n audited; a dropped row is the gate's primary catch (count check: audit rows must equal frozen count).
- **G3 — Fails stay fails:** a criterion that can't be satisfied is delivered as FAIL with the reason. Rewording the artifact or the criterion to launder a FAIL into a PASS fails the gate harder than the FAIL did.

## Steps

1. **Freeze.** Convert each requirement into a binary criterion — testable by looking at the artifact ("covers exactly 3 named competitors", not "good coverage"). Ambiguous requirement? Sharpen it with the user BEFORE freezing, or freeze the strictest defensible reading and say so. State the frozen list, numbered. It is now immutable for this run.
2. **Generate.** Build the artifact against the frozen list. Don't peek-and-soften: if C4 says 400 words, cut content, don't re-freeze at 600.
3. **Audit.** Table: each criterion verbatim · PASS/FAIL · evidence (quote, count, or pointer into the artifact). Facts the artifact needs but the input lacks (a price, a stat) are never invented to pass a criterion — mark the gap, FAIL the row if the criterion demands the fact.
4. **Repair loop.** FAIL rows → fix the artifact (never the criteria) → re-audit the fixed rows. Maximum 2 loops. Residual FAILs ship as FAILs with reasons — an honest 4/5 beats a laundered 5/5.
5. **Deliver** artifact + full audit table. "All criteria pass ✓" without the table is not a delivery.

## Output format

```
FROZEN CRITERIA (before generation)
C1. covers exactly 3 named competitors
C2. each competitor has pricing with source or "not public"
...
[ARTIFACT]
AUDIT (against frozen criteria, verbatim)
| C1 "covers exactly 3 named competitors" | PASS | Acme, Beta, Gamma |
| C2 "each competitor has pricing with source or 'not public'" | PASS | 2 sourced, 1 marked not public |
| C5 "no unsourced market-share claims" | FAIL → fixed loop 1: claim cut | PASS | — |
AUDIT COUNT: 5 frozen / 5 audited ✔
GATE CHECK: G1 pass (frozen pre-generation) · G2 pass (5/5 verbatim) · G3 pass (no laundering)
```

## Hard rules

1. The criteria freeze before the first artifact word and never move. Editing a criterion mid-run is the failure this skill exists to prevent.
2. Every frozen criterion appears verbatim in the audit. The count check (frozen n = audited n) runs before delivery, mechanically.
3. Never invent a fact to turn a FAIL into a PASS. Gate-critical facts come from the input or the row fails with "fact unavailable".
4. The audit table always ships with the artifact — the user sees the grades, not a summary of the grades.

## Limitations

- Binary criteria measure compliance, not quality — an artifact can pass 5/5 and still be mediocre prose; the freeze guarantees the contract, not the craft.
- The freeze is only as good as the requirements; vague requirements frozen strictly may FAIL rows the user didn't intend — the pre-freeze sharpening step is the mitigation, and it costs a round-trip.
- Self-audit is the same model grading its own work; the verbatim-quote + evidence discipline reduces but does not eliminate self-grading bias (adversarial review is /pr-review's job).
- Two repair loops maximum; deeper failures indicate the requirements and the ask disagree — escalated to the user, not looped forever.
