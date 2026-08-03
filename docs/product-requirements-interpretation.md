# Product requirements interpretation

How the V1 build reads the product brief — what each requirement means operationally.

| Brief requirement | V1 interpretation |
|---|---|
| "PM converts MVP spec into production-ready software" | Phase Zero is the only admissible shipped lifecycle authority; the retired V1 executor remains a test fixture only |
| "Engineering involvement only for exceptions" | exceptions == escalation files; everything else is automatic and logged |
| "Validate specification" | schema validation (structure) + semantic validation (contradictions, testability, NSM quality, dependencies, unsupported decisions) |
| "Tests before implementation" | test architect writes workspace tests, `confirm_red` proves they fail, only then does implementation run — enforced by step order and checked by the E2E suite against git history |
| "Automated PR review" | deterministic reviewer over the workspace diff producing typed blocking/non-blocking findings |
| "Fix review findings where safe" | fix agent applies only allow-listed formatting-level fixes; everything else escalates |
| "Merge only when all gates pass" | merge gate = required gates green ∧ zero blocking findings ∧ traceability complete ∧ all escalations approved |
| "Deploy or produce deployment-ready artifact" | both: local process deploy (verified) and an artifact (run script + Dockerfile + instructions + rollback) |
| "Traceability from requirement to implementation" | every FR-xxx maps to plan task(s) → ADR(s) → code file(s) → test(s) → gate results → deployment evidence in the final report |
| "NSM must be an outcome, not activity" | validator flags NSMs built from activity verbs (clicks, signups, sessions, pageviews, logins, downloads) with no outcome language |
| "Telemetry hooks for metrics" | `MetricsRecorder` interface + JSONL events; per-run leading metrics computed into the final report; NSM/guardrail hooks named but fed by future usage data |

## North Star and leading metrics — where they land in code

- NSM (% of PM-initiated builds reaching verified production + first use, no engineer):
  recorded per run as `run_outcome` events; aggregation is V2 (needs fleet of runs).
- Leading metrics computed per run now: spec validation pass/fail, completion rate
  (steps done / steps total), duration per step and total, test pass rate, review
  blocking-finding count, % requirements linked to passing tests, escalation count.
- Guardrails instrumented as hooks: security findings count, rollback issued (bool),
  fix-agent intervention count, generated-code complexity (file/function size checks).
