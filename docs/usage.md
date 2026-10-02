# Usage — pmpe CLI

## Default six-state journey

The installed product surface is one command group:

| Command | Purpose | Exit codes |
|---|---|---|
| `pmpe barebones compile <contract> --repository-root DIR` | compile acceptance truth and report deterministic coverage without starting a run | 0 valid · 3 halted |
| `pmpe barebones run <contract> ...` | run an approved structured contract through the bounded Coder, retain candidate-only evidence when verification passes, and stop at `HALTED` | 3 halted; the reserved 0 ready path is unavailable in the current provider modes |
| `pmpe barebones status <run_id> --repository-root DIR` | verify the evidence chain and report its current state, with a conservative stage-health projection for mapped runs | 0 valid · 3 invalid |
| `pmpe barebones evidence <run_id> --repository-root DIR` | verify and locate the event log and referenced blobs | 0 valid · 3 invalid |
| `pmpe barebones inspect <run_id> --repository-root DIR [--workspace DIR] [--file PATH]` | inspect the sealed candidate and optionally detect workspace drift | 0 match · 3 invalid/drift |

The historical `pmpe barebones <contract> ...` spelling remains a compatibility alias
for `pmpe barebones run <contract> ...`, but it is not shown as a second product path.
All commands emit one JSON object so users and automation see the same state.
An invalid contract, provider command, or non-empty workspace is rejected before
a run ledger is created. After admission, the tested provider-launch, request,
candidate-path and snapshot I/O failures persist a `HALTED` event when evidence
storage remains available, so `status` and `inspect` agree with the immediate
CLI result. A terminal append I/O failure instead returns `UNKNOWN` with
`EVIDENCE_PERSISTENCE_UNCONFIRMED`; `status` may retain the earlier in-progress
event. Other evidence-storage failures may also leave an incomplete ledger.
An immediate failure response alone never proves a terminal event was stored.

## Fixed PMOS task-tracker reference

The [task-tracker reference harness](../examples/pmos-task-tracker/README.md)
adds one packaged `pmos-task-tracker-v1` template for the unchanged PMOS
14-case packet. Compile with both `--template pmos-task-tracker-v1` and
`--core-harness-mapping PATH`; the mapping digest must be bound in the contract.
The immutable checked-in draft still compiles as `CORE_HARNESS_PROOF_PENDING`.
The owner's exact-digest approval produced a separate approved contract and
receipt under `examples/pmos-task-tracker/approved/`. This admits the mapped
requirements but does not satisfy runtime conditions. A test-only issued copy can
exercise all 14 cases and the ten-create measure, but still halts on provider
write isolation. The five mapped conditions remain required; their runtime
proofs are not established by static compilation or fixture tests. See the
[pipeline-health definition](pipeline-health.md) for how passed, failed,
skipped and blocked stages are reported.

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
