# Troubleshooting

## `specification rejected` (exit 2)
The spec violates the schema. The message lists field-level problems
(`scope: expected array, got str`). Fix the listed fields; the contract is
`schemas/mvp_spec.schema.json` and every field is documented inline there.

## `waiting for human approval: ESC-xxx` (exit 3)
Not an error — a HIGH-risk decision stopped the run. `pmpe status <run_id>` shows the
open escalations; approve or reject them (docs/usage.md) and `pmpe resume`.

## Run ends `no_merge` (exit 4)
Read `runs/<id>/artifacts/merge_decision.json`. Typical causes:
- a required gate failed → its `details` field carries the tool output tail
- a blocking review finding (rule `SEC_*` or `REV_*`) → file and line are in the reason
- an open escalation nobody approved

## `step 'confirm_red' failed: generated tests PASSED before implementation`
The generated suite is vacuous for this spec (it asserts nothing implementation-
dependent). This is a real gate catching a real problem — report it with the spec
that triggered it; the test architect templates need a case for that capability mix.

## `step 'deploy' failed: deployment verification failed`
The generated app did not become healthy or failed its user journey. The stderr tail
is in the message and in `runs/<id>/artifacts/deployment_result.json`. Port conflicts
are avoided by design (OS-assigned free port); the usual cause is an unwritable
runs directory for the SQLite file.

## Resume does nothing / re-runs the wrong step
`pmpe resume` re-enters at the first step that is not `done`/`skipped` — check
`pmpe status`. A `failed` step re-executes; `done` steps never re-execute. If the
workspace was manually edited, delete the run directory and start a fresh run —
runs are cheap and deterministic by design.

## `git ... failed` inside a workspace
The workspace repos use an isolated bot identity and ignore your global git config.
If a workspace is corrupted (e.g., disk full mid-commit), start a fresh run.

## format/lint gates say "ruff not available — gate skipped"
Informational: install ruff (`pip install ruff`) to enable them. Required gates
(compile, unit, integration, security) are stdlib-only and always run.

## Tests hang or ports leak in CI
Every server the suite starts is bound to 127.0.0.1 on an OS-assigned port and torn
down in `tearDown`/`finally`. If a sandbox forbids binding sockets, integration/e2e
tests cannot run there — run `pytest tests/unit` only and note the limitation.
