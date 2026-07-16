# Usage — pmpe CLI

## Commands

| Command | Purpose | Exit codes |
|---|---|---|
| `pmpe validate <spec>` | structure + semantic validation only | 0 ok · 2 malformed · 3 errors/questions |
| `pmpe run <spec>` | full 18-step lifecycle | 0 success · 1 failed · 2 malformed · 3 blocked · 4 NO_MERGE |
| `pmpe resume <run_id>` | continue after approval/fix/crash | same as run |
| `pmpe approve <run_id> <ESC-ID> --approver NAME --reason TEXT [--reject]` | record a human decision | 0 |
| `pmpe status <run_id>` | step statuses + open escalations | 0 |
| `pmpe report <run_id>` | print the final build report | 0 · 1 if not produced yet |

Common flags: `--runs-dir DIR`, `--config FILE`.

## The lifecycle a run executes

ingest → validate → plan → architecture → acceptance → generate_tests → confirm_red
(generated tests must FAIL before implementation) → implement (commit per task) →
quality_gates → create_pr → review → fix (safe fixes only) → retest → merge_gate →
merge → deploy (local, verified) → verify → report.

## When a run blocks (exit 3)

A HIGH-risk decision needs a human. The run wrote `runs/<id>/escalations/ESC-xxx.json`:

```bash
pmpe status <run_id>                       # see what is open and why
pmpe approve <run_id> ESC-001 --approver "abhillash" \
    --reason "local deploy fallback accepted for the pilot"
pmpe resume <run_id>
```

Rejecting (`--reject`) fails the run explicitly. Approvals never turn a failing
quality gate green — they only resolve the waiting-for-human check, and the merge
gate re-verifies every escalation has a decision.

## When a run ends NO_MERGE (exit 4)

The build completed but did not earn a merge: read
`runs/<id>/artifacts/merge_decision.json` for the exact reasons (failing gate,
blocking finding, traceability gap, or unresolved escalation). Nothing was merged or
deployed; the final report still exists for the audit trail. Fix the spec (or the
pipeline finding) and start a new run.

## Key artifacts per run

| Artifact | Content |
|---|---|
| `validation_report.json` | errors / warnings / questions with rule codes |
| `engineering_plan.{json,md}` | tasks, dependency graph, order, complexity |
| `architecture.md`, `adr/ADR-*.md` | architecture + decision records |
| `confirm_red.json` | proof tests failed before implementation |
| `gate_results{,_retest}.json` | every gate's result, duration, details |
| `pull_request.{json,md}` | PR record with commits and diff stat |
| `review_report{,_final}.{json,md}` | findings with rules and blocking flags |
| `merge_decision.{json,md}` | MERGE / NO_MERGE with reasons |
| `deployment_result.json`, `verification.json` | health, journey, rollback path |
| `traceability.{json,md}`, `final_report.md`, `metrics.json` | the audit trail |
