# Troubleshooting

## `specification rejected` (exit 2)
The spec violates the schema. The message lists field-level problems
(`scope: expected array, got str`). Fix the listed fields; the contract is
`schemas/mvp_spec.schema.json` and every field is documented inline there.

## Historical V1 run is waiting for human approval

`pmpe status <run_id>` can inspect the stopped state and open escalation. The
installed CLI cannot approve, reject, or continue V1; those mutations are confined
to explicit migration and compatibility tests.

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

## Historical state needs migration

Use `pmpe status` or `pmpe report` for read-only inspection. Production code must
admit a new run through Phase Zero instead of replaying legacy handlers.

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
