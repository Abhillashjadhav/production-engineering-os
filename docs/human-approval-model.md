# Human approval model

Default operating model: **exception-based human intervention**. The pipeline runs
autonomously and stops only where policy says a human owns the decision.

## Risk levels

| Level | Behavior | Record |
|---|---|---|
| low | proceed automatically | decision event in `events.jsonl` |
| medium | proceed, but a written justification is attached to the decision and logged | decision event with `justification` |
| high | STOP. Write `runs/<id>/escalations/<esc_id>.json`, mark the step `blocked`, exit non-zero | resumes only after approval |

## What is high-risk (V1 policy defaults)

- Contradictory product requirements (validator errors)
- Missing product decision the spec should have made
- Irreversible architecture choices (anything the ADR marks `reversibility: irreversible`)
- Security-sensitive changes beyond what the spec explicitly requires
- Possible data loss; destructive migrations (also out of V1 scope entirely)
- Production deployment with material risk (`deployment_target: production` requests)
- Test failures the fix agent cannot resolve with allow-listed safe fixes
- Low system confidence (any component reporting it cannot complete deterministically)

## The approval flow

```
pipeline blocks → runs/<id>/escalations/ESC-001.json written, run exits with code 3
$ pmpe status <run_id>            # shows the blocked step + open escalations
$ pmpe approve <run_id> ESC-001 --approver "name" --reason "why this is acceptable"
$ pmpe resume <run_id>            # re-enters at the blocked step
```

Approvals are stored in `runs/<id>/approvals/ESC-001.json` (approver, reason, UTC
timestamp) and echoed into the final build report. Rejecting is `pmpe approve ... --reject`,
which marks the run failed with the rejection recorded.

Rules that never bend:

1. An approval satisfies exactly one escalation; it is not a blanket waiver.
2. Approvals never turn a failing quality gate green — they only unblock waiting.
3. The merge gate independently re-verifies that every escalation raised during the run
   has a matching approval; a missing one is NO_MERGE regardless of anything else.
4. The PM owns product decisions: escalations about scope/contradictions can only be
   resolved by an approval that states the product decision taken, which is copied into
   the traceability report.
