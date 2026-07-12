---
name: golden-dataset-builder
description: "Iterate-stage skill: curates real outputs plus human judgments into golden eval cases — every case carrying the human verdict and the human's reason, no unlabeled cases, ever. Use when reviewed outputs need structuring into a reusable test set — 'build a golden dataset from these outputs', 'turn these human-graded examples into golden cases', 'we need a regression set, here are outputs and verdicts' — or when /pm routes such a request here. Do NOT use to grade the outputs (human judgment is input), to capture a single production failure (failure-to-eval-capture), to generate synthetic cases, or for golden-dataset definitions."
argument-hint: "<the outputs + whatever human review notes exist, however messy>"
---

# Golden Dataset Builder

Real outputs, real human judgments, structured to last. A golden case without its human verdict and reason isn't golden — it's sand.

## Verification gates (defined first; output is blocked until all pass)

- **G1 — No unlabeled cases:** every golden carries the human verdict AND the human's reason. Cases missing either are quarantined with the specific ask ("needs verdict", "'fine I guess' — pass or fail, and why?") — never included, never auto-labeled, never upgraded from ambiguity.
- **G2 — Labels are the human's, verbatim:** reasons are stored as written; paraphrasing a reason into something stronger or cleaner corrupts provenance. Ambiguous verdicts go back as questions, not interpretations.
- **G3 — Set integrity:** duplicates collapsed to one case with provenance noted; the set report shows candidates → goldens + quarantined, verdict balance (a set of only passes tests nothing), and failure-pattern coverage.

## Steps

1. **Inventory the raw material:** every output-review pair, however informal. Nothing is discarded — cases split into golden-ready (verdict + reason) and quarantine (missing pieces, each with its unblock question).
2. **Structure each golden:** id · input (or reference) · output · verdict · reason (verbatim) · label author · date · the eval criterion it exercises (mapped where an eval exists; `unmapped` honestly otherwise — unmapped goldens are seeds for eval-engine, noted as such).
3. **Deduplicate** on output identity; keep one case, note the duplication (frequency is metadata, not case count).
4. **Report the set:** N candidates → K goldens / M quarantined (with asks); pass/fail balance; which known failure patterns are covered and which have zero cases — a coverage gap is a collection task, not a generation task.
5. **State the maintenance loop:** new production failures arrive via failure-to-eval-capture; the set re-runs on every prompt/model change via regression-gatekeeper; label disputes route to the criterion owner. The golden set is infrastructure, and this section is its operating manual.
6. **Gate pass.** Zero unlabeled goldens (G1), all reasons verbatim (G2), dedup + balance + coverage reported (G3). Fix and re-run; maximum 2 repair loops, then report the failure.

## Output format

```
GOLDEN SET: meeting summarizer (6 candidates → 2 goldens · 3 quarantined · 1 duplicate)
GOLDENS
GC-1 (from O2) — verdict: FAIL — reason [Priya, verbatim]: "the action items are
wrong, it assigned Marco's task to Lena" — exercises: action-item attribution gate
GC-2 (from O5) — verdict: PASS — reason [Priya, verbatim]: "perfect example of what
we want: short, all decisions captured" — exercises: decision coverage + concision
QUARANTINE (not goldens until unblocked)
Q-1 (O1) — verdict "good" present, reason missing → ask Priya: good because what?
Q-2 (O3) — no review → needs verdict + reason
Q-3 (O4) — "fine I guess" — ambiguous → ask Marco: pass or fail, and why?
DEDUP: O6 = O1 (duplicate export) — collapsed, frequency noted.
BALANCE: 1 pass / 1 fail — minimum viable; coverage gaps: no case exercises the
no-invented-content gate yet → collection task, not generation.
GATE CHECK: G1 pass (2/2 labeled, 0 auto-labels) · G2 pass (verbatim) · G3 pass
```

## Hard rules

1. Never label a case yourself. The skill's entire value is provenance — an inferred "pass" is a poisoned well, and a bigger set is not worth it.
2. Never paraphrase a reason. "The action items are wrong" stays as Priya wrote it; interpretation happens at eval-design time, attributed.
3. Quarantine is a first-class output: every quarantined case carries the exact question that unblocks it, addressed to the person who can answer.
4. Report the balance. A one-sided set gets said out loud, with the collection task that fixes it — never padded with synthetic counterweights.

## Limitations

- Golden quality equals label quality; inconsistent human reviewers produce an honest set with inconsistent teeth — cross-reviewer disputes are surfaced, not resolved here.
- The set covers observed behavior only; failure modes nobody has hit have no goldens — guardrail-designer and synthetic adversarial cases (kept separate, labeled synthetic) cover the speculative space.
- Verbatim reasons can be terse; terse-but-real beats eloquent-but-invented, and the quarantine asks are how terse improves.
- Privacy: cases containing user data need failure-to-eval-capture's scrubbing discipline before entering a shared set — flagged when detected, not silently included.
