# Changelog

All notable changes to PM Production Engineering OS. Format: Keep a Changelog;
versions: SemVer.

## [0.1.0] — 2026-07-12

### Added
- `pmpe` package and CLI (`validate`, `run`, `resume`, `approve`, `status`, `report`)
  with contract exit codes (0/1/2/3/4).
- Input contract `schemas/mvp_spec.schema.json` (+ packaged copy) and golden example
  `examples/taskflow_mvp_spec.yaml`.
- 18-step resumable workflow engine with atomic state, JSONL event log, artifact store.
- Requirement validator: contradictions, untestable ACs, activity-only NSM detection,
  entity/data-model gaps, undeclared dependencies, unsupported deployment targets,
  identifier constraints.
- Deterministic engineering planner (capability-driven task graph), architecture agent
  with ADRs, policy engine (low/medium/high, named rules), file-based human approvals.
- python-stdlib-crud-api stack adapter: tests-first generation (`confirm_red` proves
  red before implementation), SQLite + env-token-auth CRUD API templates.
- Quality gates (compile/format/lint/unit/integration/security), built-in security
  scanner, deterministic PR reviewer, allow-listed fix agent, merge gate.
- Local git adapter (branch per run, commit per task, PR record artifact) and local
  process deployer with health + user-journey verification, rollback instructions,
  Dockerfile artifact.
- Traceability report (requirement → task → ADR → code → tests → findings →
  deployment) and final build report with per-run leading metrics.
- Test suite: 136 tests (unit, integration, e2e incl. failure paths, crash recovery,
  CLI contract), CI workflow, PR template, full documentation set under `docs/`.
