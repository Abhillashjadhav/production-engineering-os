# Changelog

All notable changes to PM Production Engineering OS. Format: Keep a Changelog;
versions: SemVer.

## [Unreleased]

### Added
- Frozen six-state contract-to-`RELEASE_READY` alpha core with deterministic acceptance compilation, meaningful-RED baseline, one bounded Coder, Bubblewrap verification, and hash-chained evidence (#141).
- Standard-library OpenAI Responses API reference provider with strict structured output, fixed endpoint handling, redirect rejection, bounded output, and non-secret usage metadata (#148).
- Response-binding, plan-determinism, read-only ledger inspection, and behavioural-drift comparison evidence separated into distinct claims (#149).
- Governed personal runtime adapters for exact-payload calendar approval, budgeted and
  allowlisted product workers, digest-bound append-only event/eval evidence, bounded retry
  with verified rollback, and proposal-only outcome learning (#121).
- `pmpe personal-runtime quickstart` deterministic local demo, synthetic fixture, runtime
  documentation, and unit/integration assurance tests. No real connectors or external writes.

### Changed
- Public claims now use an evidence-first alpha boundary and an explicit local defective-code threat model; arbitrary generation, production readiness, deployment, and platform validation are not claimed (#147).
- The default CLI exposes only the frozen barebones journey and an explicit `legacy` compatibility boundary (#150).
- The 0.2.0 deployment ladder and larger multi-agent lifecycle below are historical legacy behavior, superseded as the default product surface by the frozen alpha core. They are not evidence for current alpha deployment or production-readiness claims.

### Security
- Candidate execution fails closed without Bubblewrap and `prlimit`, clears the environment, removes network and host filesystem authority, mounts the candidate read-only, and bounds process resources and output. This shares the host kernel and is not a hosted or multi-tenant adversarial boundary (#141, #147).

## [0.2.0] — 2026-07-16

### Added (V2 — contract-driven engineering runs)
- **ProductDecisionContract**: schema, typed model with semantic runnability
  (APPROVED + named approver + no unresolved product-critical questions),
  canonical digest, versioned registry, run-scoped immutability lock (fail
  closed on mutation), id-keyed contract diff, and the ProductChangeRequest
  store — product changes are a new version and a new run, never an overwrite.
- **Agent plane**: eleven `v2-*` agent definitions with enforceable
  frontmatter permissions; read-only provable from the tool list (empty list =
  inherit-all = NOT read-only); worktree isolation for write-capable
  specialists; minimum-routing validation (every task routed once by
  capability, no zero-task selections, unused profiles explicitly justified).
- **Engineering run engine + `pmpe eng`**: deterministic admission over agent
  artifacts, digest-bound evidence-ledger events in the trajectory grammar,
  resume that re-verifies the locked contract and appends nothing, candidate
  freeze/verify, runtime read-only review proof, re-runnable reconciliation
  (duplicates linked, REC-001 auto-accept, product findings → PCRs, undecided
  findings block), fixer scoped to ACCEPTED ids, verifier ≠ fixer, retest/
  refreeze/verify, draft-PR record, and the deployment ladder.
- **Executed traceability**: subprocess evidence harness with failure kinds
  (assertion/import/error/skip); requirements classified VERIFIED / FAILED /
  NOT_PROVEN / BLOCKED_PRODUCT_DECISION — markers, skips, and import-dead
  tests never count as coverage.
- **Evals**: agent evals sharing the engine's admission validators (planted
  failures + product-boundary cases; permission and fire/no-fire cases
  auto-generated), trajectory checks TRAJ-01..14 over the ledger, drift
  reports across five categories with new-hard-gate-failure = HOLD, and
  judge-calibration reporting. Thresholds shipped as labeled provisional
  defaults.
- **Deployment policy**: local/test automatic after checks, staging after all
  assurance gates, production only with a named, digest-bound human approval;
  production execution is fixture-mode only (no cloud adapter by decision).
- **`/production-engineer` skill** (fixtures committed first) with modes
  start/status/resume/report/review-only/eval-only.
- **Synthetic demonstration** (`pmpe demo`, `examples/v2-demo/`): four planted
  failures detected by the real machinery, accepted findings fixed and
  independently verified, the run's own ledger trajectory-clean, production
  honestly blocked; everything labeled synthetic.

### Changed
- README now leads with the PM Agent OS / Production Engineering OS boundary
  and corrects V1 overclaims (deterministic checker ≠ independent review;
  marker traceability ≠ executed coverage); V2 reference in
  docs/v2-production-engineering.md.
- CI additionally runs the eval suites and the synthetic demo from the
  installed wheel.

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
