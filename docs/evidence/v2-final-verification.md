# V2 final verification record — 2026-07-16 (atomic series)

Branch `atomic/pr18-release` at the commit carrying this file — the final PR of
the 18-PR atomic reconstruction (see `docs/CONTRIBUTION_LEDGER.md`). Every
command below was executed in this session against this tree.

| # | Check | Command | Result |
|---|---|---|---|
| 1 | Full test suite | `.venv/bin/python -m pytest` | **338 passed** (exit 0) — the monolith's 311, plus 15 review-added tests from the atomic series' reviews, plus 12 regression tests added by the PR-18 hardening round (below) |
| 2 | Format | `ruff format --check src tests/unit tests/integration tests/e2e tests/conftest.py` | 130 files clean |
| 3 | Lint | `ruff check src tests/unit tests/integration tests/e2e tests/conftest.py` | All checks passed |
| 4 | Types | `mypy` (strict, per pyproject) | Success: no issues found in 92 source files |
| 5 | Security (own source) | `bandit -r src -q --severity-level high` | exit 0, no high-severity issues |
| 6 | Skill lint | `python tests/lint_skill.py .claude/skills/production-engineer/SKILL.md` | 9/9 PASS |
| 7 | Build | `python -m build --wheel` | pmpe-0.2.0-py3-none-any.whl |
| 8 | Clean-install smoke | fresh venv + wheel: `pmpe validate`, `pmpe contract validate examples/v2-demo/contract.json`, `pmpe evals run --suite all --ledger evals/fixtures/trajectory/good_run.jsonl` | spec OK · contract OK (digest printed) · 0 eval failures, all 11 agents pass rate 1.00 |
| 9 | Drift gate fires | `pmpe drift compare --baseline evals/baselines/synthetic-baseline.json --current evals/fixtures/drift/current_hard_gate_failure.json` | HOLD, exit 3 (as required) |
| 10 | Full demo | `pmpe demo --base-dir <tmp>` | all four planted failures detected (SEC_EVAL defect, NOT_PROVEN coverage gap, dead-module complexity, TRAJ-03 trajectory violation); drift HOLD; product-decision finding became PCR-001; fixes verified (verifier ≠ fixer); retest evidence digest-bound to the shipped candidate; local+staging authorized; production blocked pending a named human approval (readiness attested from executed evidence); release verdict recorded with both contract gates evaluated; verdict READY_FOR_PRODUCTION_APPROVAL |
| 11 | Secret scan | `git grep` for token patterns (sk-, AKIA, ghp_, key/secret assignments) | no real secrets (only the labeled fake fixtures in `tests/unit/test_security_scanner.py` and V1's generated-test templates) |
| 12 | Worktree | `git status --short` | clean at commit time |

## The PR-18 hardening round (owner-mandated blocking findings)

Five release-integrity gaps were confirmed against the reviewed monolith and
fixed in this PR — the only intentional product-behaviour changes of the whole
reconstruction, each with a regression test proven mutation-sensitive (neutering
the guard fails exactly the new test):

1. **Dirty worktrees cannot freeze** (`freeze_candidate`): a worktree with
   uncommitted or untracked changes is rejected — the manifest can never record
   a commit that lacks the digested content.
2. **Binary release gates are enforced** (`record_release_report`): every gate
   of the digest-locked contract must be evaluated and pass before any release
   verdict; the evaluation is persisted as a run artifact and ledger event.
3. **Test/retest evidence binds to the candidate** (`record_gates`/`freeze`):
   the tested tree digest is recorded with the gate event; on the no-fix path it
   must equal the frozen candidate, and a refreeze must freeze exactly the
   retested tree.
4. **Every deployment path verifies candidate integrity** (`deploy`): the
   workspace is mandatory and always re-verified against the frozen manifest —
   the former optional-verification path is gone.
5. **Production readiness precedes authorization** (`deploy`): rollback
   instructions, a runnable artifact, and health/user-journey attestations
   (fail-closed defaults) are required before the approval check even runs.

## Verification lineage

This tree was delivered twice, with independent review both times:

1. **Monolith review (closed PR #2, preserved as `backup/v2-monolith`)** — four
   independent read-only reviewers (code correctness, product conformance,
   architecture simplicity, eval/test integrity) examined the final V2 tree.
   Every confirmed finding was either fixed empirically (commits `7d7d5c1`,
   `03a24fb`, `0a6437f`, `8f1e7aa`, `c36ad98`, each with tests that fail on the
   old behavior) or recorded as an accepted limitation with rationale in
   `docs/known-limitations.md` §11–16.
2. **Atomic reconstruction (PRs 12–18 of the 18-PR series, this delivery)** —
   each atomic PR received a fresh-context, read-only, scope-chartered
   independent review with empirical mutation testing before merge; every V2 PR
   that drew findings had them fixed and re-verified. The per-PR review records
   live as comments on PRs #14–#20; the verdicts and merge commits are in
   `docs/CONTRIBUTION_LEDGER.md`.

Deltas vs the reviewed monolith (`backup/v2-monolith`), all deliberate and
itemized in the final contribution report: this ledger and evidence record; 15
review-added tests from the atomic reviews; the CI drift step pinned to exit 3;
and the five hardening fixes above with their 12 regression tests (plus the
supporting demo/CLI/test updates). Everything else is byte-identical.
