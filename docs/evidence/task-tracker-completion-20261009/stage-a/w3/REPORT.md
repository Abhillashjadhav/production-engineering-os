# W3 integration review — PMOS/PEOS task-tracker completion branch

Read-only review, 2026-10-09. No repository or GitHub state was modified.

Baseline checked:
- PEOS `/home/user/production-engineering-os`, branch `claude/pmos-peos-completion-ds46x1` = `e8a929df0feca124005dfc84f1b5bebdd207eab9`; local `main` = `1a431b23f837b04237c99ab7b924a234def10171`.
- PMOS `/home/user/PM-agent-OS`, branch `claude/pmos-peos-completion-ds46x1` = `0652843f02b5fbd5734331ffe5c00675a7b40b6b`; local `main` = `2acc3fa0c81f1237f8ab7b5681b478630c530931`.

## 1. Integration state

### PEOS (production-engineering-os)

Ancestry of the three stacked PR heads in `e8a929d` (`git merge-base --is-ancestor`):

| Ref | SHA | Ancestor of e8a929d |
|---|---|---|
| origin/docs/pmos-peos-bar-gate | `640c8f718a99df34efc1be5b9a3306326451dec7` | YES |
| origin/feat/in-session-provider | `1abfbd47061a947e8ce077523a60516a0b6cdcb0` | YES |
| origin/feat/contract-file-run | `f7669c2cd1bb9600b0fe7bd26e621b95a3402fb1` | YES |

Local remote-tracking refs match those SHAs exactly.

`git log --oneline main..e8a929d` (15 commits):

```
e8a929d docs(evidence): state the derived branch test counts
3b7cb66 docs(evidence): record the full branch test suite result
592b40f docs(evidence): record the 2026-10-09 task-tracker completion run
b8abb7c feat(barebones): repeatable regression report over the frozen task-tracker entry
c8178d2 docs(task-tracker): name python3.12 in the documented setup commands
86017f8 Merge remote-tracking branch 'origin/feat/contract-file-run' into claude/pmos-peos-completion-ds46x1
f7669c2 test(evidence): retain walkthrough before and after checks with chronology
d800d42 docs(task-tracker): close Phase 5 with pinned clean reproduction evidence
0295973 fix(barebones): satisfy strict typing and retain unchanged-candidate replay
90c1bd1 test(task-tracker): retain live delivery and deliberate-failure evidence
54df3c0 feat(barebones): load frozen bindings with digest-checked host fallback
1abfbd4 fix(provider): clear the five reviewed lint findings
e67ec19 feat: add the approved in-session model-provider handoff
8f58def test: specify bounded session-file provider handoff
640c8f7 docs: install the owner-supplied BAR Gate
```

Pushed: `git ls-remote origin claude/pmos-peos-completion-ds46x1` returns `e8a929df0feca124005dfc84f1b5bebdd207eab9  refs/heads/claude/pmos-peos-completion-ds46x1`.

Remote `main`: after `git fetch origin main`, `FETCH_HEAD` = `origin/main` = `1a431b23f837b04237c99ab7b924a234def10171`. `git log main..FETCH_HEAD` is empty. PEOS main has NOT moved since the local baseline.

Note: the three stacked PRs record base SHA `dd4271b70fcb9cb5b9dd279fe516c2fe50806751` for `main`; `git log dd4271b..main` lists 17 commits (merges of #233, #236, #237, #243, #244 and their commits). The PR base snapshots are older than current main, but current main has not moved since e8a929d was cut.

### PMOS (PM-agent-OS)

`git log --oneline main..0652843` (4 commits):

```
0652843 docs(task-tracker): record 2026-10-09 status, drift and re-freeze pointer
2781407 docs: record the unapproved re-freeze candidate for PMOS-TASK-TRACKER-001
d9a843c ci: run the frozen task-tracker drift check in the repository audit
ac42da2 test: detect approval-bound drift in the frozen task-tracker packet
```

Pushed: `git ls-remote origin claude/pmos-peos-completion-ds46x1` returns `0652843f02b5fbd5734331ffe5c00675a7b40b6b  refs/heads/claude/pmos-peos-completion-ds46x1`.

Remote `main`: after `git fetch origin main`, `FETCH_HEAD` = `origin/main` = `2acc3fa0c81f1237f8ab7b5681b478630c530931`. `git log main..FETCH_HEAD` is empty. PMOS main has NOT moved.

Note: PMOS PR #63 records base `27d0418cb258fa5e374447f88185ff1b7117f182`; `git log 27d0418..main` lists ~75 commits (merges #59–#62, #67–#74). PR #63's `mergeable_state` is `dirty`.

### GitHub PR state (`mcp__github__pull_request_read`, method `get`)

PEOS:

| PR | Title | state | draft | merged | mergeable_state | head ref | head sha | base ref |
|---|---|---|---|---|---|---|---|---|
| 197 | Install the owner-supplied BAR Gate for bounded implementation | open | true | false | unknown | docs/pmos-peos-bar-gate | `640c8f718a99df34efc1be5b9a3306326451dec7` | main |
| 199 | Add the cloud session provider and retain Phase 0 evidence | open | true | false | unstable | feat/in-session-provider | `1abfbd47061a947e8ce077523a60516a0b6cdcb0` | docs/pmos-peos-bar-gate |
| 203 | Build the approved task tracker through frozen file bindings | open | false | false | clean | feat/contract-file-run | `f7669c2cd1bb9600b0fe7bd26e621b95a3402fb1` | feat/in-session-provider |

PMOS:

| PR | Title | state | draft | merged | mergeable_state | head ref | head sha | base ref |
|---|---|---|---|---|---|---|---|---|
| 63 | test: prove PMOS handoff through current PEOS terminal states | open | true | false | dirty | fix/current-peos-handoff-20260924 | `0b6bd55152efc918f9a042fc898e961dcf527b96` | main |
| 64 | docs: preserve product intent through executable gate handoff | open | true | false | clean | docs/current-peos-handoff-20260924 | `f7c1f41289e37690fc196dc7082991afe4e74d94` | fix/current-peos-handoff-20260924 |
| 65 | fix: verify retained handoff evidence against a caller-held head | open | true | false | clean | fix/r3-retained-head-20260924 | `13a08d260d28043fe5901c11ed5764ebe135027c` | fix/current-peos-handoff-20260924 |
| 66 | docs: clarify retained-head and fixture evidence boundaries | open | true | false | clean | docs/r3-retained-head-20260924 | `394f0386827c1c0e6357717c906323855c2c37e0` | fix/r3-retained-head-20260924 |

All seven PRs are open and unmerged. The PEOS PR head SHAs equal the three ancestor commits of e8a929d exactly. None of PMOS PRs 63–66 are ancestors of the PMOS branch (their heads sit on separate 20260924 branches; the PMOS branch is 4 commits on top of main).

PR for `claude/pmos-peos-completion-ds46x1`: `list_pull_requests` with `state=all`, `head=Abhillashjadhav:claude/pmos-peos-completion-ds46x1` returned `[]` for both repos; `search_pull_requests` for `pmos-peos-completion-ds46x1 user:Abhillashjadhav` returned `total_count: 0`. No PR exists for this branch in either repo. `gh run list --branch claude/pmos-peos-completion-ds46x1` lists no workflow runs in either repo.

## 2. CI coverage

### PEOS `.github/workflows/ci.yml`

Triggers: `push` to `main` only, `pull_request`, `workflow_dispatch`, `schedule`. A push to `claude/pmos-peos-completion-ds46x1` does not trigger `ci.yml`; it runs only once a PR is opened (or by manual dispatch). `pr-review.yml` and `trusted-security.yml` use `pull_request_target` (PR-only). `repository-intelligence-wheel.yml` and `evals-linkedin-connection.yml` are path-filtered `pull_request` workflows whose paths (`src/pmpe/repository/**`, `products/pm-evals-web/**`, etc.) this branch does not touch.

Jobs that would run on a PR from this branch:

| Job | Relevant steps for this branch |
|---|---|
| format-lint | `ruff format --check` on `src tests/unit tests/integration tests/e2e tests/conftest.py ... examples/barebones/codex-cli-provider.py` (only that one example file is format-checked); `ruff check ... examples/barebones/*.py` (lints `contract-file.py`, `session-file-provider.py`, `task-tracker-regression.py`) |
| types | `mypy --strict src/pmpe ... examples/barebones/*.py` (type-checks all three new example files) |
| tests (3.11, 3.12) | `pytest tests/unit -q`, `pytest tests/integration -q`, `pytest tests/e2e -q` |
| candidate-isolation (3.11, 3.12) | explicit list of sandbox tests + `tests/e2e/test_barebones_e1.py::test_e1_real_contract_reaches_release_ready`; none of the three new test files |
| security-static | bandit on `src scripts/ci`, pip-audit, secret gate, `pytest tests/unit/test_security_profiles.py` |
| product-backend, product-e2e, product-preview, build-smoke | unrelated product/legacy paths; `build-smoke` runs `pmpe legacy ...` and `tests/e2e/test_full_pipeline.py` only |

`pyproject.toml` `[tool.pytest.ini_options]`: `testpaths = ["tests/unit", "tests/integration", "tests/e2e"]`, `addopts = "-q"`. `[tool.ruff] include` = `src/**`, `tests/unit/**`, `tests/integration/**`, `tests/e2e/**`, `tests/conftest.py` (examples are reached via the explicit CLI globs above, not the include list).

Collection (`.venv/bin/python -m pytest --collect-only -q`, from the repo dir):

```
tests/unit/test_contract_file_entry.py: 6
tests/unit/test_session_file_provider.py: 6
tests/unit/test_task_tracker_regression_report.py: 5
```

All three are under `tests/unit`, so the `tests` job's `pytest tests/unit -q` collects them. Local run: `17 passed`.

End-to-end execution of the entry scripts: no CI step invokes `examples/barebones/contract-file.py` or `examples/barebones/task-tracker-regression.py` (grep of `.github/` for `contract-file`, `task-tracker-regression`, `barebones` finds only the ruff/mypy globs and the `test_barebones_e1` selector). The entry scripts are linted and type-checked in CI, and exercised only indirectly through the unit tests, which import `contract-file.py`/`task-tracker-regression.py` as modules and spawn `session-file-provider.py` as a subprocess. No CI job runs a frozen-packet `check`/`build`/`verify` end to end. The branch evidence logs (`docs/evidence/task-tracker-completion-20261009/branch-{tests,mypy,ruff,ruff-format}.log`) are retained manual runs, not CI output.

### PMOS workflows

`repository-audit.yml` (triggers: `pull_request`, `push` to `main`; python 3.12). Steps in order: `tests/audit_repository.py`; `tests/test_handoff_setup.py`; Beacon unittests; `test_validation_regressions.py`; **`python -B tests/test_task_tracker_freeze.py -v`** (added on this branch by `d9a843c`, the 2-line diff to the workflow); `Lint all skills` loop over `find . -name SKILL.md -not -path './.git/*'`; `pip install git+...production-engineering-os.git@5c0f9e3a8f2c66b212c5e1adfb373e4fd2681bf9`; `tests/decision-to-contract/validate_contract.py`; `py_compile` checks.

`tests/test_task_tracker_freeze.py` is wired and would be RED on this branch. Local run on `0652843`: `Ran 3 tests ... FAILED (failures=1)`, process exit code 1. The failing test is `test_pmos_bound_artifacts_are_unchanged`:

```
.claude/skills/decision-to-contract/SKILL.md: frozen sha256:ad0978c8e3780f11ec40d06395653d2c45ce100449ca8c7edea56bac6593ee1f != current sha256:f14623cb4da6ecd9efe67324c2475d96715d12049e470bfe333e4dd953c21c26
```

Because the workflow runs steps sequentially without `continue-on-error`, the audit job stops at the freeze step; the skill-lint loop and the pinned-compiler steps after it would not execute on this branch.

Origin of the drift: `decision-to-contract/SKILL.md` is byte-identical on `main` and on `0652843` (both sha256 `f14623cb...`); the branch does not change it (`git diff --stat main..0652843 -- .claude/skills/decision-to-contract` is empty). The frozen digest `ad0978c8...` predates commit `33ba7ec` ("fix: bind PMOS contract gates and preserve exact draft approval", 2026-09-26 00:12 +0530, on `main`), which landed four minutes after the packet restore `5aefeb5` (00:08 +0530). The drift exists on `main` already; the branch adds the detector.

Skill lint loop: `find . -name SKILL.md` includes `./.claude/skills/decision-to-contract/SKILL.md`; `python3 tests/lint_skill.py .claude/skills/decision-to-contract/SKILL.md` on the branch prints 9 `PASS` lines, exit 0. The loop covers the skill, but on this branch the loop sits after the RED freeze step.

`current-authoring.yml` (triggers: `pull_request`, `push` to `main`; python 3.12): installs `git+...production-engineering-os.git@297a11d79e5d1e1eda1f8f94b7bec3046c41a0d6`, runs `scripts/check_handoff.py`, then `tests/decision-to-contract/test_current_authoring.py`. Nothing on the branch touches this workflow.

Pin constants:

| Location | Value | Where the commit sits in PEOS |
|---|---|---|
| `scripts/check_handoff.py` `REVIEWED_REVISION` (line 12) | `297a11d79e5d1e1eda1f8f94b7bec3046c41a0d6` | commit exists ("docs: retain integrated R4 verification and blocked independent recheck", 2026-09-24); NOT an ancestor of PEOS `main` or of `e8a929d`; reachable from `origin/docs/w3-proof-reconciliation`, `origin/feat/approved-bundle-run`, `origin/fix/r4-call-phase-red` |
| `current-authoring.yml` pip pin | `297a11d79e5d1e1eda1f8f94b7bec3046c41a0d6` | same as above (matches `REVIEWED_REVISION`) |
| `repository-audit.yml` pip pin | `5c0f9e3a8f2c66b212c5e1adfb373e4fd2681bf9` | "Accept canonical ProductDecisionContract arrays in compiler (#192)", 2026-09-01; ancestor of PEOS `main` and of `e8a929d` |

Neither PMOS pin points at `e8a929d` or at any commit on the completion branch; PMOS CI does not install the branch's `contract-file.py` entry.

## 3. Regression coverage of the failure boundaries

Files inspected: `tests/unit/test_contract_file_entry.py` (6 tests), `tests/unit/test_session_file_provider.py` (6), `tests/unit/test_task_tracker_regression_report.py` (5), `tests/unit/test_barebones_cli_journey.py`, `tests/unit/test_barebones_drift.py`, `tests/e2e/*.py`, plus PMOS `tests/test_task_tracker_freeze.py`.

| Boundary | Automated test | Notes |
|---|---|---|
| Wrong provider request digest | `tests/unit/test_session_file_provider.py::SessionFileProviderTests::test_wrong_digest_is_rejected_and_retained` | Response carrying `sha256:bbb…` for a `sha256:aaa…` request: non-zero exit, empty stdout, `RESPONSE_DIGEST_MISMATCH` on stderr, `call.json` status `failed`. Engine-level analogue: `tests/e2e/test_barebones_evals.py::test_e3_stale_model_response_is_rejected_as_unbound`. |
| Absent response / timeout | `test_session_file_provider.py::test_missing_response_times_out`; `test_session_file_provider.py::test_old_response_is_not_reused_for_another_call` | Both assert `RESPONSE_TIMEOUT` with `PMPE_PROVIDER_TIMEOUT_SECONDS=1`; the second proves a stale `call-old/response.json` is not consumed. Malformed/symlinked responses: `test_malformed_response_is_rejected`, `test_response_symlink_is_rejected` (`RESPONSE_INVALID`). |
| SIGKILL interruption | NONE | `contract-file.py:228` issues `os.killpg(..., SIGKILL)` on candidate-process timeout, and the entry's SIGKILL behavior (no `result.json`, status `BUILDING/IN_PROGRESS`) is recorded only as manual evidence (`REPORT.md` line 29; run `06b`, line 64). `test_contract_file_entry.py::test_after_check_runs_on_execution_exception` covers a raised `subprocess.TimeoutExpired` inside `guard.boundary` — the Python-exception path, not an external kill of the entry. |
| Wrong freeze digest | PARTIAL: `tests/unit/test_contract_file_entry.py::ContractFileEntryTest::test_changed_manifest_rejected`; PMOS `tests/test_task_tracker_freeze.py::TaskTrackerFreezeTests::test_manifest_matches_recorded_freeze_digest` | `DigestGuard.__init__` raises `TamperDetectedError("FREEZE_DIGEST_MISMATCH")` when `canonical_digest(manifest) != expected`; no test constructs the guard with a wrong `expected` (a wrong `--freeze-digest`). `test_changed_manifest_rejected` rewrites the manifest after construction and hits the `APPROVAL_BOUND_ARTIFACT_CHANGED` path via the manifest's own raw-digest entry. The PMOS test checks the manifest against `freeze-bundle.sha256`, not the PEOS entry. |
| Missing `--candidate` | NONE | `contract-file.py` `verify` raises `ValueError("--candidate is required for verify")` (exit 2 via `failure.json`); `task-tracker-regression.py` marks `--candidate` `required=True`. No test exercises either. |
| Missing `--authorized-host-fallback` | NONE | Flag is passed into `compatibility(...)`; no test asserts the incompatible/refusal result when it is absent. |
| Product mutation | NONE (automated, for the entry) | Evidence only: `REPORT.md` line 29 cites `runs/08d mutation → FAIL exit 1`. Closest automated check: `tests/unit/test_task_tracker_regression_report.py::test_one_failed_criterion_is_fail_even_with_exit_zero` (classifier reports `FAIL` for a failed criterion; no product is mutated). Engine-level mutation tests exist (`tests/e2e/test_barebones_evals.py::test_non_assertion_mutation_cannot_satisfy_meaningful_red`, `::test_each_criterion_verifies_a_fresh_exact_snapshot`) but do not go through the task-tracker entry. |
| Evaluator mutation | `tests/unit/test_contract_file_entry.py::ContractFileEntryTest::test_evaluator_replacement_rejected`; `::test_nonprotected_evaluator_binding_rejected` | First: `tests/check.py` in the candidate differs from the frozen template; `HostExecution.run` raises `TamperDetectedError`. Second: an action bound to a non-`tests/` file is refused with `ValueError` at `load_template`. `::test_unsafe_template_path_rejected` covers `../` escape. |
| Approved-contract mutation | `tests/unit/test_contract_file_entry.py::ContractFileEntryTest::test_changed_approved_artifact_rejected`; PMOS `tests/test_task_tracker_freeze.py::TaskTrackerFreezeTests::test_a_changed_bound_byte_is_reported_on_a_copy`; `::test_approved_contract_matches_recorded_contract_digest` | PEOS test changes a manifest-bound artifact and asserts `TamperDetectedError` on `guard.check("before")`. PMOS negative control appends a byte to `contract.approved.json` on a copy and deletes `evaluator.py`, asserting both are reported. |
| Interrupted run reads as not complete | `tests/unit/test_task_tracker_regression_report.py::test_interrupted_run_without_any_record_is_blocked`; `::test_refusal_before_execution_is_blocked_not_pass` | `classify(tmp_path, None)` with no `result.json`/`failure.json` yields `BLOCKED` with blocker `NO_RESULT`; a `failure.json` carrying `APPROVAL_BOUND_ARTIFACT_CHANGED` yields `BLOCKED`, not `PASS`. These test the report classifier only; nothing automated interrupts a real entry run. |

## 4. Branch diff review

`git diff --stat main..e8a929d -- . ':(exclude)docs/evidence'`:

```
 AGENTS.md                                         |  14 +
 BAR.md                                            | 152 ++++++++
 examples/barebones/contract-file.md               |  61 ++++
 examples/barebones/contract-file.py               | 411 ++++++++++++++++++++++
 examples/barebones/session-file-provider.py       | 132 +++++++
 examples/barebones/task-tracker-regression.py     | 163 +++++++++
 tests/unit/test_contract_file_entry.py            | 113 ++++++
 tests/unit/test_session_file_provider.py          | 138 ++++++++
 tests/unit/test_task_tracker_regression_report.py |  66 ++++
 9 files changed, 1250 insertions(+)
```

Full diff (including `docs/evidence`): 140 files changed, 7637 insertions, 0 deletions. No existing file is modified or deleted; every change is an addition. No `src/pmpe`, schema, workflow, or `pyproject.toml` change.

Items not directly task-tracker code:
- `AGENTS.md` (+14) and `BAR.md` (+152): the owner-supplied BAR Gate policy text and bootstrap record from PR #197 (`640c8f7`). Process documentation, no runtime effect; it is the base of the PR stack rather than part of the task-tracker implementation.
- `examples/barebones/session-file-provider.py` + `tests/unit/test_session_file_provider.py`: the in-session provider from PR #199. `contract-file.py` builds a `CommandModelProvider` around `session-file-provider.py` in `build` mode, so it is a dependency, not unrelated.
- Nothing else in the non-evidence diff looks unrelated.

`docs/evidence/task-tracker-completion-20261009/` at `e8a929d`: 21 files. No file exceeds 200 KB. Largest: `refreeze-candidate/freeze-manifest.candidate.json` 46,800 bytes; `fresh-setup/verification/processes.jsonl` 19,509; `REPORT.md` 13,714; `fresh-setup/verification/digest-checks.jsonl` 8,477; everything else under 6 KB.

PMOS branch diff (`git diff --stat main..0652843`): 7 files, 1316 insertions, 0 deletions: `.github/workflows/repository-audit.yml` (+2), `reviews/task-tracker-v1/README.md` (+13), `reviews/task-tracker-v1/refreeze-candidate-20261009/{README.md,candidate-freeze-digest.txt,changed-entries.json,freeze-manifest.candidate.json}` (+56/+1/+32/+1146), `tests/test_task_tracker_freeze.py` (+66). No skill, publisher, or pin change.
