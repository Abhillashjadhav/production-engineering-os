# Usage — pmpe CLI

## Default six-state journey

The installed product surface is one command group:

| Command | Purpose | Exit codes |
|---|---|---|
| `pmpe barebones compile <contract> --repository-root DIR` | compile acceptance truth and report deterministic coverage without starting a run | 0 valid · 3 halted |
| `pmpe barebones run <contract> ...` | run an approved contract through the bounded Coder and stop at `RELEASE_READY` or `HALTED` | 0 ready · 3 halted |
| `pmpe barebones status <run_id> --repository-root DIR` | verify the evidence chain and report its current state | 0 valid · 3 invalid |
| `pmpe barebones evidence <run_id> --repository-root DIR` | verify and locate the event log and referenced blobs | 0 valid · 3 invalid |
| `pmpe barebones inspect <run_id> --repository-root DIR [--workspace DIR] [--file PATH]` | inspect the sealed candidate and optionally detect workspace drift | 0 match · 3 invalid/drift |

The historical `pmpe barebones <contract> ...` spelling remains a compatibility alias
for `pmpe barebones run <contract> ...`, but it is not shown as a second product path.
All commands emit one JSON object so users and automation see the same state.

## Legacy-compatible commands

| Command | Purpose | Exit codes |
|---|---|---|
| `pmpe legacy validate <spec>` | structure + semantic validation only | 0 ok · 2 malformed · 3 errors/questions |
| `pmpe legacy status <run_id>` | read historical V1 step status and escalations | 0 |
| `pmpe legacy report <run_id>` | read a historical V1 final report | 0 · 1 if absent |

Common read-only flags: `--runs-dir DIR`, `--config FILE`.

## V1 execution is retired

The installed package does not expose commands that start, continue, or approve a
V1 workflow. The legacy executor lives only in `tests.legacy_v1`, which is outside
the packaged `src/pmpe` tree and excluded from the wheel. Its E2E fixtures preserve
compatibility and migration evidence without creating a production path.

Phase Zero is the sole admissible shipped lifecycle authority. Missing contract,
publisher, budget, approval, GitHub, deployment, or observation authority must stop
the control plane; the retired V1 files are never admissible substitutes.

## Historical artifacts

Read-only commands can inspect these artifacts from an existing V1 run:

| Artifact | Content |
|---|---|
| `state.json` | legacy step projection |
| `validation_report.json` | errors, warnings, and questions |
| `engineering_plan.{json,md}` | tasks and dependency order |
| `architecture.md`, `adr/ADR-*.md` | historical architecture evidence |
| `gate_results{,_retest}.json` | historical local gate results |
| `merge_decision.{json,md}` | legacy recommendation record |
| `traceability.{json,md}`, `final_report.md` | historical audit output |

These files remain readable but cannot authorize new execution, approval, merge,
deployment, or completion claims.
