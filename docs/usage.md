# Usage — pmpe CLI

## Legacy-compatible commands

| Command | Purpose | Exit codes |
|---|---|---|
| `pmpe validate <spec>` | structure + semantic validation only | 0 ok · 2 malformed · 3 errors/questions |
| `pmpe status <run_id>` | read historical V1 step status and escalations | 0 |
| `pmpe report <run_id>` | read a historical V1 final report | 0 · 1 if absent |

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
