# Test plan — PM Production Engineering OS V1

Tests are written before implementation (Phase 4 scaffolds them failing; the commit
history is the evidence). All tests run offline and deterministically.

## Layers

| Layer | Location | Runner | Covers |
|---|---|---|---|
| Unit | `tests/unit/` | pytest | schema validation, normalizer, requirement validator (incl. contradiction + activity-NSM detection), planner graph/ordering, policy engine risk levels, workflow state transitions, security scanner, merge gate logic, traceability builder |
| Integration | `tests/integration/` | pytest | ingestion→validation→plan on real example spec; test-architect + implementation into a real tmp workspace; quality gate runner on generated code; git adapter against a real local git repo; reviewer + fixer round-trip |
| E2E | `tests/e2e/` | pytest | full pipeline runs on `examples/` specs (below) |
| Fixtures | `tests/fixtures/` | — | valid spec, contradictory spec, activity-NSM spec, malformed spec, spec requiring high-risk escalation |

## The end-to-end proof (required by the task)

`tests/e2e/test_full_pipeline.py` asserts, on the sample TaskFlow spec:

1. valid specification accepted (ingest + validate pass)
2. engineering plan created (tasks, dependency graph, order)
3. architecture artifacts generated (doc + ≥3 ADRs)
4. tests created **before** implementation (workspace git history: test commit precedes feat commits; `confirm_red` recorded a failing run)
5. implementation produced (files exist, workspace tests now pass)
6. quality gates ran (every configured gate has a recorded result)
7. review findings generated (report exists; findings list may be empty of blockers)
8. safe findings fixed (fix step recorded; gates re-ran)
9. merge eligibility determined (MERGE with reasons; and a planted-failure variant yields NO_MERGE)
10. final report generated (traceability: every FR maps to task, code, test, gate, deployment evidence)

Plus: local deployment boots the generated app, `/health` returns 200, and the main
user journey (create task → list → complete) passes over real HTTP.

## Failure-path tests (gates must catch planted failures)

- Contradictory spec → validation blocks, escalation written, exit code 3.
- Activity-only NSM → validator flags it.
- Malformed spec (missing required fields / bad types) → ingestion rejects.
- Planted blocking review finding → merge gate returns NO_MERGE.
- Simulated crash mid-run → `resume` completes without re-executing done steps.
- High-risk escalation → run blocks until `pmpe approve`, then resumes.

## Quality bars for this repo's CI

format (ruff format --check), lint (ruff check), types (mypy --strict on `src/pmpe`),
unit+integration+e2e (pytest), security (bandit -r src + built-in scanner self-test),
dependency audit (pip-audit, non-blocking warn in V1), build (`pip install -e .` +
`pmpe validate examples/taskflow_mvp_spec.yaml` smoke).
