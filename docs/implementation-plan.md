# Implementation plan (file-by-file)

Order of commits mirrors this order; tests land before the code they test.

## Commit 1 — PRD + decisions (done)
- `prds/2026-07-12-pm-production-engineering-os.md`, `DECISIONS.md`

## Commit 2 — Design docs
- `ARCHITECTURE.md`, `docs/repository-assessment.md`, `docs/assumptions.md`,
  `docs/risk-register.md`, `docs/human-approval-model.md`, `docs/test-plan.md`,
  `docs/implementation-plan.md`, `docs/adr/ADR-001..006.md`,
  `docs/workflow-state-machine.md` (in ARCHITECTURE.md), `docs/product-requirements-interpretation.md`,
  `docs/technical-requirements.md`

## Commit 3 — Contract: schema + examples + packaging
- `schemas/mvp_spec.schema.json` — documented input contract
- `examples/taskflow_mvp_spec.yaml` — the sample PM OS spec (golden path)
- `examples/README.md`
- `pyproject.toml` (package `pmpe`, console script `pmpe`, ruff/mypy/pytest config)
- `.gitignore` additions (`runs/`, caches)

## Commit 4 — Failing test scaffold (Phase 4)
- `tests/fixtures/*.yaml|json` — valid, contradictory, activity-NSM, malformed, high-risk specs
- `tests/unit/test_schema_validation.py`, `test_normalizer.py`, `test_requirement_validator.py`,
  `test_planner.py`, `test_policy_engine.py`, `test_workflow_state.py`,
  `test_security_scanner.py`, `test_merge_gate.py`, `test_traceability.py`
- `tests/integration/test_ingest_to_plan.py`, `test_generation_workspace.py`,
  `test_quality_gates.py`, `test_git_adapter.py`, `test_review_and_fix.py`
- `tests/e2e/test_full_pipeline.py`, `test_failure_paths.py`
- `tests/conftest.py`
- Run pytest; confirm failures are import errors / missing modules only.

## Commits 5..10 — Implementation (each commit = one module group, tests go green incrementally)
5. `src/pmpe/domain/`, `src/pmpe/artifacts/`, `src/pmpe/telemetry/`, `src/pmpe/config.py`
6. `src/pmpe/ingestion/`, `src/pmpe/validation/`
7. `src/pmpe/planning/`, `src/pmpe/architecture/`, `src/pmpe/testing/`, `src/pmpe/implementation/` (+ reference-stack templates)
8. `src/pmpe/quality/`, `src/pmpe/gitops/`
9. `src/pmpe/review/` (reviewer, fixer, merge gate), `src/pmpe/deployment/`
10. `src/pmpe/policies/`, `src/pmpe/orchestration/`, `src/pmpe/audit/`, `src/pmpe/cli.py`

## Commit 11 — Docs + CI
- `SECURITY.md`, `CONTRIBUTING.md`, `ROADMAP.md`, `CHANGELOG.md`
- `docs/setup.md`, `docs/usage.md`, `docs/troubleshooting.md`,
  `docs/checklists/{security,pr-review,deployment}-checklist.md`,
  `docs/branch-protection.md`
- `.github/workflows/ci.yml`, `.github/pull_request_template.md`
- README pointer section

## Commit 12+ — Review fixes
- Findings from the independent review (Phase 6/7), each as its own `fix:`/`refactor:` commit.
