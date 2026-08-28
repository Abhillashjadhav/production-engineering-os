# ADR-006: File/CLI-based human approval gates

Status: Accepted · Date: 2026-07-12 · Risk: low · Reversibility: reversible

## Context
High-risk decisions require human approval, but the pipeline must be non-interactive,
resumable, and auditable.

## Decision
Escalations are files (`runs/<id>/escalations/ESC-xxx.json`); a blocked run exits with
code 3. Approvals are recorded by `pmpe approve <run> <esc> --approver --reason` as
files and are verified again by the merge gate. `pmpe resume` continues the run.

## Consequences
+ Approvals are durable evidence in the audit trail, not lost console input.
+ Works identically in terminals, CI, and agent harnesses.
− Slightly more ceremony than an interactive [y/N] — intended.
