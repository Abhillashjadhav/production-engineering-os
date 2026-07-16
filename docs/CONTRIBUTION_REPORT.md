# Final contribution report — the 18-PR atomic reconstruction

Date: 2026-07-16. The monolithic V1/V2 deliveries (PRs #1 and #2, closed
unmerged, preserved immutably as `backup/v1-monolith` = `6d7977e` and
`backup/v2-monolith` = `d44cb65`) were re-delivered as 18 sequential atomic
pull requests. Each PR branched from fresh `main`, passed CI, received a
fresh-context read-only independent review with a scope charter and empirical
mutation testing, and was squash-merged only after an APPROVE verdict. Per-row
detail (outcome, requirements, tests, verdicts, limitations) lives in
`docs/CONTRIBUTION_LEDGER.md`; the full review records are comments on the PRs.

## The 18 PRs

| # | GH | Title | Merge | Review |
|---|----|-------|-------|--------|
| 1 | #3 | Repository foundation | 89599f9 | APPROVE (2 rounds) |
| 2 | #4 | Specification ingestion | 2a41462 | APPROVE (2 rounds) |
| 3 | #5 | Requirement validation | 81452bf | APPROVE (1 round) |
| 4 | #6 | Engineering planning | 6254e2c | APPROVE (1 round) |
| 5 | #7 | Architecture decisions | 062cb9e | APPROVE (2 rounds) |
| 6 | #8 | Tests-before-code | b312e46 | APPROVE (1 round) |
| 7 | #9 | Reference implementation | 33d7c30 | APPROVE (2 rounds) |
| 8 | #10 | Quality and security gates | e56069b | APPROVE (2 rounds) |
| 9 | #11 | Durable workflow runtime | 217f7d9 | APPROVE (2 rounds) |
| 10 | #12 | Review and merge control | 00f751b | APPROVE (1 round) |
| 11 | #13 | Deployment, audit, V1 completion | 077782e | APPROVE (1 round) |
| 12 | #14 | ProductDecisionContract (V2 start) | ff98707 | APPROVE (2 rounds) |
| 13 | #15 | Engineering agent plane | e2ba689 | APPROVE (2 rounds) |
| 14 | #16 | Independent assurance reviewers | c68720a | APPROVE (2 rounds) |
| 15 | #17 | Findings and approved fixes | 56ae2d0 | APPROVE (2 rounds) |
| 16 | #18 | Executed traceability | 98f154c | APPROVE (2 rounds) |
| 17 | #19 | Agent and trajectory reliability (evals) | 1070751 | APPROVE (2 rounds) |
| 18 | #20 | Release orchestration, V2 completion | 2d89195 | APPROVE (2 rounds, three finding sources reconciled) |

13 of 18 PRs drew a REQUEST_CHANGES round; every finding was fixed and
re-verified empirically (mutation-killing tests, claim corrections, or both)
before merge. The reviews were adversarial in substance: reviewers ran suites
in scratch venvs, neutered guards to prove tests would catch removal, drove
the demo from wheel installs, and re-measured every count in every PR body.

## Verification from merged `main` (2d89195)

- Full V1+V2 suite: **338 passed** (`pytest`), on Python 3.11 and 3.12 in CI.
- V1 demonstration: `pmpe run examples/taskflow_mvp_spec.yaml` → full
  pipeline, `"status": "success"`, exit 0.
- V2 demonstration: `pmpe demo` → all four planted failures caught (SEC_EVAL
  defect, NOT_PROVEN coverage gap, dead-module complexity, TRAJ-03 trajectory
  violation), drift HOLD, product-decision finding → PCR-001, verifier ≠
  fixer, local+staging authorized, production blocked pending a named
  human approval, release verdict READY_FOR_PRODUCTION_APPROVAL recorded with
  both contract gates evaluated. Exit 0.
- Gates: ruff format/check clean, mypy --strict clean (92 files), bandit
  high-severity clean, skill lint 9/9, wheel builds and smokes
  (validate / contract validate / evals 0 failures / drift HOLD exit 3).
- The 20 completion conditions of the V2 specification (§16 of the source
  instruction) are confirmed on this tree — enumerated below with their
  in-repo evidence; conditions 19–20 (draft PR only, no auto-merge) hold for
  the *product* (the run engine's draft-PR handoff never merges, PD-08) —
  the series' own merges to `main` were explicit owner-authorized delivery
  operations.

### The 20 completion conditions

| # | Condition | Evidence on this tree |
|---|-----------|-----------------------|
| 1 | Existing V1 behaviour remains green | all V1 tests in the 338-passed suite; `pmpe run` exit 0 |
| 2 | Approved contract immutable + digest-locked | `pmpe.contracts.store` lock, mutation fails closed (`test_contracts.py`) |
| 3 | Product changes → versioned ProductChangeRequests | `ChangeRequestStore`; demo RF-003 → PCR-001 |
| 4 | System Architect → verified Architecture Pack | `validate_architecture_pack` at admission (`test_run_engine.py`) |
| 5 | Implementation Planner → traceable vertical tasks | `validate_plan`: requirement ids + behavioural test per task |
| 6 | Engineer Router selects only necessary specialists | `validate_routing` minimum-routing (`test_agent_plane.py`) |
| 7 | Specialists execute in bounded isolated scope | worktree isolation + task-scoped submissions (`test_worktree_isolation.py`) |
| 8 | Integration produces a frozen candidate | `freeze_candidate` digest manifest; dirty trees rejected (`test_candidate_freeze.py`) |
| 9 | Four independent read-only reviews, same candidate | same-candidate rule + read-only proofs + tree-digest guard (`test_assurance.py`, `test_run_engine.py`) |
| 10 | Separate fixer modifies only accepted findings | `FixerGate` + engine fixer authorization (`test_assurance.py`, `test_run_engine.py`) |
| 11 | Every requirement maps to executed evidence | `build_executed_traceability` (`test_executed_traceability.py`); demo FR-002 NOT_PROVEN→VERIFIED |
| 12 | Agent-level evals pass | `pmpe evals run --suite all` → 0 failures, 11 agents pass rate 1.00 |
| 13 | Trajectory evals pass | good run clean; 14 planted fixtures caught (`test_trajectory.py`) |
| 14 | Drift measurement detects planted drift | `pmpe drift compare` → HOLD, exit 3 (CI-pinned) |
| 15 | Production blocked without candidate-bound approval | digest-bound approval + readiness gate (`test_run_engine.py`, demo) |
| 16 | Synthetic demonstration completes honestly | `pmpe demo` exit 0, all planted failures caught, SYNTHETIC-labeled |
| 17 | All tests/lint/types/security/build checks pass | CI green on `2d89195`; local gates clean |
| 18 | Documentation matches actual behaviour | claim-accuracy enforced per review round (rows 13, 15–18) |
| 19 | A draft PR is open | the engine's `draft_pr` stage records the handoff and has no merge path (PD-08); the original draft PR #2 was closed superseded by owner instruction |
| 20 | No product main-merge, external deployment, API key, model SDK, or loop runtime | engine has no merge/auto-deploy path; simulated executor labeled; no SDK deps in `pyproject.toml`; PD-10/PD-11 upheld |

## Nothing lost, every delta deliberate

File inventory vs both backups: no file from `backup/v2-monolith` is missing
from `main`; the only V1-backup path absent is `src/pmpe/cli.py`, which became
the `src/pmpe/cli/` package in PR 12 with V1 commands preserved verbatim in
`core.py` (independently verified). Content deltas vs `backup/v2-monolith`,
each reviewed and intentional:

1. `docs/CONTRIBUTION_LEDGER.md` + this report (the audit trail itself).
2. `docs/evidence/v2-final-verification.md` regenerated for the merged tree.
3. **15 review-added tests** from the atomic series' independent reviews
   (3 agent-plane, 6 assurance, 1 contracts, 1 executed-traceability,
   2 security-scanner, 1 ingest-to-plan, 1 generation-workspace).
4. The CI drift step pinned to exit code 3 (a crash can no longer satisfy the
   planted-regression proof).
5. **The PR-18 hardening round** — five release-integrity fixes, the only
   product-behaviour changes of the reconstruction, owner-mandated and
   mutation-verified (12 regression tests): dirty worktrees cannot freeze;
   contract binary release gates enforced and persisted at the release report;
   test/retest evidence digest-bound to the shipped candidate; candidate
   integrity verified on every deployment path; production readiness precedes
   authorization. Touched: `engineering/candidate.py`, `engineering/engine.py`,
   `cli/eng_cmd.py`, `demo/synthetic.py` (+ demo `.gitignore` for bytecode
   caches, already excluded from the candidate digest).
6. Two one-line documentation reconciliations correcting inaccuracies the
   backup itself carried: the integration-engineer definition now shows the
   real `pmpe eng freeze --run-dir <run> --repo <workspace>` invocation, and
   the skill fixtures cite the actual
   `planted_implement_before_architecture.jsonl` fixture.

## Delivery-rule compliance

Every PR: one problem, tests landing with the capability they verify, no
future-stage interfaces (submission validators were deliberately moved to
PR 17 to land with their consumer and tests; three agent definitions were
staged to avoid present-tense claims about the then-unshipped `pmpe eng` CLI
and restored once it existed). Skill discipline held: `tests/production-engineer/fixtures.md`
was committed before `SKILL.md` inside PR 18. No stacking — each branch cut
from freshly pulled `main` after the previous squash-merge.
