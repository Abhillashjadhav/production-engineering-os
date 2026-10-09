# Stage A clean-workspace reproduction — baseline PEOS e8a929d / PMOS 0652843

Workspace: `/home/user/stageA-clean/` (fresh clones from the LOCAL repos; host repos untouched).
Logs: `/tmp/claude-0/-home-user/7921f78e-13c9-54cd-bb55-cb413fcf6daf/scratchpad/w2/` (abbreviated `w2/` below).
Exit-code ledger: `w2/exit-codes.txt`.

- PEOS clone: `/home/user/stageA-clean/peos` @ `e8a929df0feca124005dfc84f1b5bebdd207eab9`
- PMOS clone: `/home/user/stageA-clean/pmos` @ `0652843f02b5fbd5734331ffe5c00675a7b40b6b` (local `main` created from `origin/main` = `2acc3fa0` for the quality gate)
- Interpreters: `python3.12` = 3.12.3 (venvs); `python3` = 3.13.16 (used for the PMOS scripts, which the workflows invoke as `python` on CI 3.12)
- `bwrap`: not installed on host (expected; 4 tests skipped for that reason)
- Date: 2026-10-09

## Summary table

| Step | Command (run from) | Source of command | Exit | Actual totals | Log |
|---|---|---|---|---|---|
| A | `python3.12 -m venv .venv && .venv/bin/python -m pip install -e ".[dev]"` (peos) | README.md:97-99 | **0** | pip, 31s wall; installed pmpe-0.2.0 editable + dev extras (pytest 9.1.1, ruff 0.16.4, mypy 2.3.1, …). uv not needed. | `w2/A-peos-install.log` |
| B1 | `.venv/bin/python -m pytest tests/unit tests/integration tests/e2e -o addopts="" -rs` (peos) | pyproject `testpaths`/`addopts="-q"` overridden to empty; ci.yml `tests` job runs the same three dirs with `-q` | **1** | **1 failed, 2909 passed, 4 skipped, 2 warnings in 1459.21s (0:24:19)** | `w2/B-pytest.log` |
| B1-diag | `.venv/bin/python -m pytest tests/unit/test_support_package_v1.py::test_package_verification_rederives_every_port -o addopts="" -rs` (peos) | diagnostic re-run of the single failed test, NOT a replacement of B1 | 0 | 1 passed in 1.77s | `w2/B-pytest-rerun-single-failed-test.log` |
| B2 | `.venv/bin/ruff format --check src tests/unit tests/integration tests/e2e tests/conftest.py scripts/ci/classify_frontend_ci.py scripts/ci/evaluate_security_profile.py scripts/ci/run_trusted_security_entrypoint.py scripts/ci/verify_privacy_controls.py scripts/ci/verify_repository_secrets.py scripts/ci/verify_trusted_security_bootstrap.py examples/barebones/codex-cli-provider.py` (peos) | ci.yml `format-lint` / "ruff format" step (exact path list) | **0** | `308 files already formatted` | `w2/B-ruff-format.log` |
| B3 | `.venv/bin/ruff check src tests/unit tests/integration tests/e2e tests/conftest.py scripts/ci/classify_frontend_ci.py scripts/ci/evaluate_security_profile.py scripts/ci/run_trusted_security_entrypoint.py scripts/ci/verify_privacy_controls.py scripts/ci/verify_repository_secrets.py scripts/ci/verify_trusted_security_bootstrap.py examples/barebones/*.py` (peos) | ci.yml `format-lint` / "ruff lint" step (exact path list) | **0** | `All checks passed!` | `w2/B-ruff-check.log` |
| B4 | `.venv/bin/mypy --strict src/pmpe scripts/ci/classify_frontend_ci.py scripts/ci/evaluate_security_profile.py scripts/ci/run_trusted_security_entrypoint.py scripts/ci/verify_privacy_controls.py scripts/ci/verify_repository_secrets.py scripts/ci/verify_trusted_security_bootstrap.py examples/barebones/*.py` (peos) | ci.yml `types` job (pyproject `[tool.mypy]` strict=true, files=src/pmpe) | **0** | `Success: no issues found in 200 source files` | `w2/B-mypy.log` |
| C1 | `python3 tests/audit_repository.py` (pmos) | repository-audit.yml "Run offline repository audit" | **0** | `PASS repository audit: 40 lifecycle skills, 3 supporting skills, 7 reviewer personas` | `w2/C-audit_repository.log` |
| C2 | `python3 -B tests/test_handoff_setup.py -v` (pmos) | repository-audit.yml "Check offline handoff prerequisite diagnostics" | **0** | `Ran 6 tests … OK` | `w2/C-test_handoff_setup.log` |
| C3 | `python3 -B -m unittest discover -s tests -p 'test_beacon_*.py' -v` (pmos) | repository-audit.yml "Run offline Beacon hook and runner tests" | **0** | `Ran 7 tests … OK` | `w2/C-beacon_unittest.log` |
| C4 | `python3 -m unittest discover -s tests -p test_validation_regressions.py -v` (pmos) | repository-audit.yml "Reject planted validation failures" | **0** | `Ran 9 tests … OK` | `w2/C-validation_regressions.log` |
| C5 | `python3 tests/lint_skill.py <path>` for every `SKILL.md` (`find . -name SKILL.md -not -path './.git/*'`) (pmos) | repository-audit.yml "Lint all skills" | **0** (all) | **47 SKILL.md files: 47 PASS, 0 FAIL** | `w2/C-lint_skills.log` |
| C6 | `python3 tests/pr_quality_gate.py --base-ref main` (pmos; local `main` = origin/main 2acc3fa0) | pr-quality workflow / script `--base-ref` (required arg) | **0** | `PASS deterministic PR quality gate` (preceded by audit PASS line + per-skill 9-check PASS blocks) | `w2/C-pr_quality_gate.log` |
| C7 | `python3 -B tests/test_task_tracker_freeze.py -v` (pmos) | repository-audit.yml "Check the frozen task-tracker packet for approval-bound drift" | **1** | **Ran 3 tests: 2 ok, 1 FAIL** (`test_pmos_bound_artifacts_are_unchanged`, naming `.claude/skills/decision-to-contract/SKILL.md`) — matches the EXPECTED outcome exactly | `w2/C-task_tracker_freeze.log` |
| D0 | `python3.12 -m venv /home/user/stageA-clean/handoff-venv && /home/user/stageA-clean/handoff-venv/bin/python -m pip install /home/user/stageA-clean/peos` (non-editable, from local clone at e8a929d) | task spec (CI instead installs `git+https://…@297a11d7` / `@5c0f9e3a`) | **0** | `Successfully installed … pmpe-0.2.0 …` | `w2/D-handoff-venv-install.log` |
| D1 | `/home/user/stageA-clean/handoff-venv/bin/python -B tests/decision-to-contract/test_current_authoring.py -v` (pmos) | current-authoring.yml "Check documented-pin authoring and receipt-bound admission" | **1** | **Ran 7 tests: 5 ok, 2 FAIL** (`test_description_only_gate_is_rejected_by_current_compiler`, `test_historical_fixture_is_unbound_at_documented_pin`) | `w2/D-test_current_authoring.log` |
| D2 | `/home/user/stageA-clean/handoff-venv/bin/python scripts/check_handoff.py` (pmos) | current-authoring.yml "Check documented publisher provenance" | **2** | `HANDOFF_SETUP_BLOCKED: PUBLISHER_PROVENANCE_UNKNOWN` (see verbatim below) | `w2/D-check_handoff.log` |
| D3 | `/home/user/stageA-clean/handoff-venv/bin/python tests/decision-to-contract/validate_contract.py` (pmos) | repository-audit.yml "Execute PMOS to PEOS contract compatibility" (CI pins 5c0f9e3a) | **0** | `PASS answers publish an exact approved contract, engineering handoff starts, and planted failures are rejected` | `w2/D-validate_contract.log` |

## Failure text, verbatim

### B1 — PEOS full pytest run (exit 1)

Summary line:
```
====== 1 failed, 2909 passed, 4 skipped, 2 warnings in 1459.21s (0:24:19) ======
```

Skips (`-rs`), all four due to no bwrap/CI namespace runtime on this host (expected):
```
SKIPPED [1] tests/unit/test_candidate_sandbox.py:443: requires the dedicated CI namespace runtime
SKIPPED [1] tests/unit/test_candidate_sandbox.py:482: requires the dedicated CI namespace runtime
SKIPPED [1] tests/unit/test_candidate_sandbox.py:519: requires the dedicated CI namespace runtime
SKIPPED [1] tests/unit/test_real_behavior_drift_eval.py:391: requires the dedicated CI namespace runtime
```

The one failure (`tests/unit/test_support_package_v1.py:103` progress line `...............F..................`):
```
________________ test_package_verification_rederives_every_port ________________

tmp_path = PosixPath('/tmp/pytest-of-root/pytest-3/test_package_verification_rede0')

    def test_package_verification_rederives_every_port(tmp_path: Path) -> None:
        bundle = tmp_path / "bundle"
>       _assemble(tmp_path, bundle)

tests/unit/test_support_package_v1.py:349:
tests/unit/test_support_package_v1.py:149: in _assemble
    return assemble_support_package(
src/pmpe/support_package.py:1624: in assemble_support_package
    verification = _run_reference_verification(staged, forbidden, files)
...
            expected_receipt = f"PMPE_PROOF_COMPLETE:{capability}".encode()
            if proof.returncode != 0 or stdout != expected_receipt:
>               raise PackageContractError(f"forbidden-capability proof did not execute: {capability}")
E               pmpe.support_package.PackageContractError: forbidden-capability proof did not execute: low_confidence

src/pmpe/support_package.py:1450: PackageContractError
```
(Full traceback including the whole `_run_reference_verification` body is in `w2/B-pytest.log`, FAILURES section.)

Warnings (2):
```
tests/unit/test_repository_intelligence.py::test_remote_provider_cancellation_terminates_the_isolated_process
tests/unit/test_repository_intelligence.py::test_cancellation_during_adapter_blocks_snapshot_finalization
  /usr/lib/python3.12/multiprocessing/popen_fork.py:66: DeprecationWarning: This process (pid=1203) is multi-threaded, use of fork() may lead to deadlocks in the child.
    self.pid = os.fork()
```

Context (not a fix): the failing path spawns a `python -I -c <proof runner>` subprocess per capability with `_PROOF_PROCESS_TIMEOUT_SECONDS = 60.0` / `_PROOF_CHILD_STARTUP_TIMEOUT_SECONDS = 25.0` (`src/pmpe/support_package.py:37-38`, recorded in `w2/B-pytest-failure-context.log`). The failure branch hit is the "returncode != 0 or stdout != expected_receipt" one, not the timeout branch. A single diagnostic re-run of only that test (B1-diag) passed in 1.77s, so the failure is non-deterministic in the full ~25-minute run. The baseline result stands as recorded: exit 1, 1 failed.

Note on exit codes: the background wrapper shell reported exit 0 because its last command was an `echo`; the pytest process's own exit code (1) is what the ledger and this table record (`PYTEST_DONE exit=1` is appended at the end of `w2/B-pytest.log`).

### C7 — `tests/test_task_tracker_freeze.py` (exit 1; EXPECTED)
```
test_approved_contract_matches_recorded_contract_digest (__main__.TaskTrackerFreezeTests.test_approved_contract_matches_recorded_contract_digest) ... ok
test_manifest_matches_recorded_freeze_digest (__main__.TaskTrackerFreezeTests.test_manifest_matches_recorded_freeze_digest) ... ok
test_pmos_bound_artifacts_are_unchanged (__main__.TaskTrackerFreezeTests.test_pmos_bound_artifacts_are_unchanged) ... FAIL

======================================================================
FAIL: test_pmos_bound_artifacts_are_unchanged (__main__.TaskTrackerFreezeTests.test_pmos_bound_artifacts_are_unchanged)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/user/stageA-clean/pmos/tests/test_task_tracker_freeze.py", line 56, in test_pmos_bound_artifacts_are_unchanged
    self.assertEqual(
    ~~~~~~~~~~~~~~~~^
        drifted,
        ^^^^^^^^
    ...<3 lines>...
        "refreeze-candidate-20261009/README.md). Do not update digests here.",
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
AssertionError: Lists differ: ['.claude/skills/decision-to-contract/SKIL[164 chars]c26'] != []

First list contains 1 additional elements.
First extra element 0:
'.claude/skills/decision-to-contract/SKILL.md: frozen sha256:ad0978c8e3780f11ec40d06395653d2c45ce100449ca8c7edea56bac6593ee1f != current sha256:f14623cb4da6ecd9efe67324c2475d96715d12049e470bfe333e4dd953c21c26'

+ []
- ['.claude/skills/decision-to-contract/SKILL.md: frozen '
-  'sha256:ad0978c8e3780f11ec40d06395653d2c45ce100449ca8c7edea56bac6593ee1f != '
-  'current '
-  'sha256:f14623cb4da6ecd9efe67324c2475d96715d12049e470bfe333e4dd953c21c26'] : APPROVAL_BOUND_ARTIFACT_CHANGED. The frozen journey cannot run against this tree until the owner approves a re-freeze (see reviews/task-tracker-v1/refreeze-candidate-20261009/README.md). Do not update digests here.

----------------------------------------------------------------------
Ran 3 tests in 0.004s

FAILED (failures=1)
```

### D1 — `tests/decision-to-contract/test_current_authoring.py` with pmpe@e8a929d (exit 1)
```
test_description_only_gate_is_rejected_by_current_compiler (__main__.CurrentAuthoringTests.test_description_only_gate_is_rejected_by_current_compiler) ... FAIL
test_documented_pin_admits_receipt_bound_current_fixture (__main__.CurrentAuthoringTests.test_documented_pin_admits_receipt_bound_current_fixture)
A real synthetic contract follows the documented publisher seam. ... ok
test_historical_fixture_is_unbound_at_documented_pin (__main__.CurrentAuthoringTests.test_historical_fixture_is_unbound_at_documented_pin) ... FAIL
test_missing_product_truth_returns_questions_before_approval (__main__.CurrentAuthoringTests.test_missing_product_truth_returns_questions_before_approval) ... ok
test_new_input_remains_draft_until_exact_test_digest_is_approved (__main__.CurrentAuthoringTests.test_new_input_remains_draft_until_exact_test_digest_is_approved) ... ok
test_skill_example_publishes_and_compiles_with_supplied_truth (__main__.CurrentAuthoringTests.test_skill_example_publishes_and_compiles_with_supplied_truth) ... ok
test_unregistered_action_remains_blocked_without_registry_extension (__main__.CurrentAuthoringTests.test_unregistered_action_remains_blocked_without_registry_extension) ... ok

======================================================================
FAIL: test_description_only_gate_is_rejected_by_current_compiler (__main__.CurrentAuthoringTests.test_description_only_gate_is_rejected_by_current_compiler)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/user/stageA-clean/pmos/tests/decision-to-contract/test_current_authoring.py", line 154, in test_description_only_gate_is_rejected_by_current_compiler
    with self.assertRaises(AcceptanceCompileError) as failure:
AssertionError: AcceptanceCompileError not raised

======================================================================
FAIL: test_historical_fixture_is_unbound_at_documented_pin (__main__.CurrentAuthoringTests.test_historical_fixture_is_unbound_at_documented_pin)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/user/stageA-clean/pmos/tests/decision-to-contract/test_current_authoring.py", line 135, in test_historical_fixture_is_unbound_at_documented_pin
    with self.assertRaises(AcceptanceCompileError) as failure:
AssertionError: AcceptanceCompileError not raised

----------------------------------------------------------------------
Ran 7 tests in 0.046s

FAILED (failures=2)
```
Reading: both failing tests assert that the compiler at the documented pin (297a11d7) raises `AcceptanceCompileError` for (a) a description-only gate and (b) the historical fixture; the compiler at e8a929d accepts both instead. The 5 passing tests show publish/compile/admission for the current fixture, the skill example, draft-until-approved, missing-truth questions, and unregistered-action blocking all still work at e8a929d.

### D2 — `scripts/check_handoff.py` with pmpe@e8a929d (exit 2)
```
HANDOFF_SETUP_BLOCKED: PUBLISHER_PROVENANCE_UNKNOWN: the installed package does not identify the reviewed Git source.
Checked Python: /home/user/stageA-clean/handoff-venv/bin/python
Follow docs/HANDOFF.md using that same Python environment.
```
Why this diagnostic rather than a revision mismatch: the script's `REVIEWED_REVISION = "297a11d79e5d1e1eda1f8f94b7bec3046c41a0d6"` (`scripts/check_handoff.py:12`) is compared against `vcs_info.commit_id` in the installed dist's `direct_url.json`. A local-path install writes `{"dir_info": {}, "url": "file:///home/user/stageA-clean/peos"}` with no `vcs_info` at all, so the script cannot reach the commit comparison and reports provenance unknown (`w2/D-provenance-context.log`). Installing from `git+…@e8a929d` would instead produce the "installed e8a929d…; reviewed 297a11d7…" mismatch branch (line 48-51).

### D3 — `tests/decision-to-contract/validate_contract.py` with pmpe@e8a929d (exit 0)
```
PASS answers publish an exact approved contract, engineering handoff starts, and planted failures are rejected
```
No failure to report; the older-pin script runs green against e8a929d.

## Steps with no failures (totals)
- A: install OK (pip; 31s).
- B2/B3/B4: ruff format (308 files), ruff check, mypy --strict (200 files) all clean.
- C1-C6: audit PASS (40 lifecycle / 3 supporting / 7 personas); handoff setup 6/6; beacon 7/7; validation regressions 9/9; 47/47 SKILL.md lint PASS; PR quality gate PASS.

## Log index (`w2/`)
`exit-codes.txt`, `A-peos-install.log`, `B-pytest.log`, `B-pytest-failure-context.log`, `B-pytest-rerun-single-failed-test.log`, `B-ruff-format.log`, `B-ruff-check.log`, `B-mypy.log`, `C-python-version.log`, `C-audit_repository.log`, `C-test_handoff_setup.log`, `C-beacon_unittest.log`, `C-validation_regressions.log`, `C-pr_quality_gate.log`, `C-task_tracker_freeze.log`, `C-lint_skills.log`, `D-handoff-venv-install.log`, `D-test_current_authoring.log`, `D-check_handoff.log`, `D-validate_contract.log`, `D-provenance-context.log`.
