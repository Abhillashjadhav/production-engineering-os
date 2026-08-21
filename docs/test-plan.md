# Test plan — PM Production Engineering OS V1

> V1 below documents the retained reference-stack fixture. The governed pre-release
> path uses the versioned executable `TestPlan` described in the next section.

## Executable TestPlan (Phase 1)

`TestPlanCompiler` converts the exact admitted contract, repository snapshot,
ArchitecturePack, and repository-observed test capabilities into a digest-bound
`TEST_PLAN` artifact before implementation may start.

The plan:

- maps requirements, acceptance criteria, risks, guardrails, release gates,
  rollback requirements, and accessibility requirements to evidence-producing nodes;
- selects or explicitly marks not applicable the unit, integration, end-to-end,
  migration, performance, accessibility, security/privacy, and release classes;
- distinguishes automated execution and interpretation from named manual evidence;
- blocks when a selected class has no command, locked tool, configuration path,
  or structured evidence format admitted by the trusted evidence registry;
- binds meaningful-red evidence to the plan digest, toolchain digest, pre-code commit,
  intended test node, and intended assertion; and
- makes any manual technical evidence visible as an autonomy intervention.

`TestPlanStore` persists one immutable plan and its durable compiler-admission
receipt per run. It returns an implementation authorization only after the receipt
verifies and the plan-bound command runs against the exact Git commit through the
isolated execution kernel. Raw runner output is parsed by the versioned evidence
adapter and admitted by the shared meaningful-red gate. Changing the plan, command,
commit, subject tree, runner, or assertion invalidates authorization.
There is no direct-worktree or unstructured-output fallback at this boundary.

Executed traceability later evaluates every plan target. Skips, import failures,
unexecuted nodes, and missing manual attestations never count as verified coverage.

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
- Legacy high-risk escalation and continuation behavior is exercised only through
  the explicit test harness; no installed command can mutate or continue it.

## Quality bars for this repo's CI

format (ruff format --check), lint (ruff check), types (mypy --strict on `src/pmpe`),
unit+integration+e2e (pytest), security (bandit -r src + built-in scanner self-test),
dependency audit (hash-locked `pip-audit --strict`, blocking), build (`pip install -e .` +
`pmpe validate examples/taskflow_mvp_spec.yaml` smoke).
