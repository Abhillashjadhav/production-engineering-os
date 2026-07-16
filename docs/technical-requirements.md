# Technical requirements document (TRD)

> Target requirements for the full V1 system. Delivery status per requirement is
> tracked in docs/CONTRIBUTION_LEDGER.md; nothing here is a claim that a
> capability already exists on this branch.

## Runtime
- Python ≥ 3.11; runtime dependency: PyYAML only. Dev: ruff, black (check parity), mypy, pytest, bandit.
- Install: `pip install -e .` → console script `pmpe`.

## Functional requirements (system)

| ID | Requirement | Verified by |
|---|---|---|
| SYS-01 | Ingest JSON or YAML spec; reject malformed input with actionable errors | unit: schema tests; e2e failure path |
| SYS-02 | Schema defined in `schemas/mvp_spec.schema.json` and enforced | unit |
| SYS-03 | Semantic validation produces typed errors / warnings / questions | unit |
| SYS-04 | Contradiction and activity-NSM detection | unit (fixtures with planted failures) |
| SYS-05 | Engineering plan: tasks with IDs, dependencies, topological order, complexity | unit + integration |
| SYS-06 | Architecture doc + ≥3 ADRs per run; escalation on high-impact decisions | integration + e2e |
| SYS-07 | Tests generated before implementation; red state recorded | e2e (git history + state) |
| SYS-08 | Implementation only via plan tasks; one commit per task; no unplanned files | integration + reviewer check |
| SYS-09 | Quality gates: format, lint, types*, unit, integration, security, regression (*types gate applies to OS code in CI; generated stack runs compile-check) | integration |
| SYS-10 | PR record + deterministic review with blocking/non-blocking findings | integration |
| SYS-11 | Safe-fix agent restricted to allow-listed fixes; re-runs gates | integration |
| SYS-12 | Merge gate: gates ∧ findings ∧ traceability ∧ approvals → MERGE/NO_MERGE with reasons | unit + e2e planted failure |
| SYS-13 | Local deploy: real process, health, user journey, rollback instructions, result recorded | e2e |
| SYS-14 | Resumable runs; idempotent steps; atomic state writes | unit + failure-recovery test |
| SYS-15 | Policy engine: low/medium/high; high blocks until `pmpe approve` | unit + e2e |
| SYS-16 | Telemetry: JSONL event log + per-run metrics in final report | unit + e2e |
| SYS-17 | Final traceability report: every FR mapped end-to-end | unit + e2e |

## Non-functional requirements

- Deterministic: same spec + same config ⇒ same plan, same code, same decisions.
- Offline: no network required for any pipeline step or test.
- Isolated: pipeline writes only under its run directory; tests only under tmp.
- Explainable: every decision event carries the rule ID that produced it.
- Secure: no secrets in code or artifacts; generated auth token created at deploy time
  and injected via environment; secret-pattern scanning in the security gate.
- Typed: mypy --strict clean on `src/pmpe`.
- Module budget: no source file over ~400 lines; functions small; enforced in review.

## Error handling contract

- Malformed input → `SpecError` with field-level messages, exit 2.
- Blocked on human gate → exit 3 (escalation files written).
- Step failure → state `failed` with captured error, exit 1; `resume` allowed after fix.
- Never swallow exceptions: every step wraps work, records the error, re-raises to the
  engine which persists state before exiting.
