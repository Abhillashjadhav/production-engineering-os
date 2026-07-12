# Changelog

All notable changes to PM Production Engineering OS. Format: Keep a Changelog;
versions: SemVer.

## [0.1.1] — 2026-07-12

### Fixed (independent review round — 8 finder angles, findings empirically verified)
- Generated tests/deployer no longer assume status default "open", a `/health`
  endpoint, an `entity.list` capability, or entities at all — valid non-golden specs
  now build, test green, and deploy (TCP-readiness fallback; shared auth probe).
- Required int/bool fields accept falsy values (0/False) in generated APIs.
- Spec-controlled strings are escaped into generated Python/SQL; query values
  URL-encoded (hostile product names/defaults covered by regression tests).
- Structural spec defects fail fast with a spec-fix message instead of offering an
  approval that would crash codegen; new validator rules REQUIREMENT_ID_FORMAT,
  CAPABILITY_DEPENDENCY, MISSING_HEALTH_CHECK.
- Resume robustness: no-op deploy commits, collision-proof escalation ids, atomic
  writes for every escalation/approval/state file, merge-gate crash-window heal.
- Security scanner test-file exemption is workspace-relative; chaos test hooks are
  rejected in user-facing config files; `pmpe status` shows approved/REJECTED/OPEN.

### Changed
- Oversized modules split to honor the 400-line budget (workflow engine into
  steps/context/render; stack templates into code/api and tests/tests-api halves).
- Known limitations documented in docs/known-limitations.md.

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
