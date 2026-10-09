# W2: full PEOS suite and the `test_package_verification_rederives_every_port` failure

The W2 worker stopped on an API rate limit (HTTP 429) after it had finished the runs below
but before it wrote this report. The integration owner wrote this report from W2's raw logs
in this directory. Nothing here is a W2 claim that the logs do not show.

## Environment

- PEOS clone at `4b1558fd5bedd04e7beacb28ffb9f41ddaa7b577`.
- Python 3.12.3 venv with `pip install -e ".[dev]"` (`logs/venv-install.log`, `logs/pip-freeze.txt`).
- 4 CPUs, 15 GB RAM.
- Git prerequisite of the owner addendum: `/usr/bin/git` resolves to UID 0, mode 0755, git 2.43.0. This
  environment is compliant, so no Git-ownership failure can occur here. No security setting was changed.

## Full-suite runs

Command: `pytest tests/unit tests/integration tests/e2e -o addopts="" -rs`.

| Run | Tree | Window (UTC) | Result | Exit |
| --- | --- | --- | --- | --- |
| full-1 | unmodified 4b1558f | 14:3x, killed at about 56 % | **ENVIRONMENT FAILURE**: SIGKILL by the OOM killer during the W4 runaway git loop (`logs/env-incident-oom.log`); not a test result | 137 |
| full-2 | unmodified 4b1558f | 15:00:58 to 15:24:59 | **2911 passed, 4 skipped, 0 failed**, 2 warnings, 1440.7 s | 0 |
| full-fix | 4b1558f + `proposed-production-fix.patch` (separate clone) | 15:25:16 to 15:49:23 | **2911 passed, 4 skipped, 0 failed**, 2 warnings, 1446.8 s | 0 |

The 4 skips are bwrap-only: `test_candidate_sandbox.py:443/482/519` and
`test_real_behavior_drift_eval.py:391`, each with "requires the dedicated CI namespace runtime".

The recorded failure is preserved unchanged:
`docs/evidence/task-tracker-completion-20261009/stage-a/w2/B-pytest.log` shows 2909 passed,
4 skipped, 1 failed at e8a929d. The failure did not recur naturally in full-2. A passing run
does not erase that recorded failure.

## Root cause

**Mechanism.** In `_PROOF_RUNNER`, at about lines 212–215 of `src/pmpe/support_package.py`,
the documented-port loop reads the port file once. It then caches
`documented_url = "http://127.0.0.1:" + handle.read() + "/health"`.

The app writes that file with `Path.write_text` (line 875), which creates the file and then
writes it. A reader can therefore see the file while it is still empty. If it does, the loop
caches `http://127.0.0.1:/health` permanently. Every request then fails until the startup
deadline passes. The runner then hits `assert documented_health == {"status":"healthy"}` and
exits 1, with no receipt on stdout. Its stderr is discarded. The verifier finally raises
`forbidden-capability proof did not execute: <capability>`.

The verified-port loop is not affected, because `int("")` raises and the loop retries.

| Evidence | Observed | Log |
| --- | --- | --- |
| The race window exists in the **unmodified** app | Tight observer, 1000 startups during load: **343** showed an EMPTY port file before content; 740 empty reads in total; 0 partial reads; 0 never published | `logs/observer-tight-during-full2.log`, `observer-tight-*.log` |
| A cached empty URL is the failure | Runner with a stderr print only: `DIAG documented_url='http://127.0.0.1:/health' documented_health=None`, then AssertionError at runner line 54, rc=1 | `logs/harness-deterministic.log` (C) |
| Deterministic trigger (write delayed 0.5 s) | Original runner: 5/5 FAIL rc=1 at line 53, for every capability | `harness-deterministic.log` (B) |
| Exact recorded message through the real test path | `_assemble` → `assemble_support_package` → `_run_reference_verification`, injected on `low_confidence`: `pmpe.support_package.PackageContractError: forbidden-capability proof did not execute: low_confidence` | `logs/samepath-D1-demo-injected-low_confidence.log:143` |
| Control without injection | 1 passed | `logs/samepath-D2-demo-no-injection.log` |
| Delaying the verified-port write instead | PASS (that loop retries) | `harness-deterministic.log` (D) |
| Proposed fix, same injections | documented-port delay 5/5 PASS; both delays 5/5 PASS; same-path tests pass | `harness-deterministic.log` (E, F), `samepath-D4/D5` |

**Rejected hypotheses.**
- H2 (partial read): 0 partial reads observed.
- H3 (startup timeout too short): an empty read fails regardless of the timeout.
- H4 (port reuse): no evidence.
- H5 (state leakage between modules): the prefix-order runs pass (`logs/repro/`).

**What is proven and what is not.** The mechanism and its exact failure path are reproduced
deterministically, and the race window was observed in the unmodified product. The original
2026-10-09 failure was **not** caught with stderr, so attributing that specific failure to this
race is a strong inference, not a direct observation.

## Fix

The fix is a one-line change in the **production, approval-bound** file
`src/pmpe/support_package.py` (`proposed-production-fix.patch`):
`str(int(handle.read()))`. An empty or partial read now raises inside the existing `try` and
is retried instead of cached.

No test-only correction is supported by this evidence: the defect is in the shipped proof
runner. The fix is **not applied** to the repository. It changes a bound byte, so it needs the
owner's approval, and a later re-freeze must bind the new bytes.

The task-tracker entry never imports `pmpe.support_package`. Running
`python -X importtime contract-file.py --help` shows 0 imports of it, and `barebones_cmd`
imports `support_package_cmd` only lazily, inside CLI registration. The task-tracker journey
is therefore unaffected by this defect.

## Static checks (4b1558f, ci.yml path lists)

Logs: `static-ruff-format.log`, `static-ruff-check.log`, `static-mypy.log` and, for the fix
clone, `static-peos-fix.log`. The integration owner reran these on the real tree; see
`../owner/static-checks.log`.

## Redaction note

GitHub push protection rejected `logs/repro/d-prefix-order-1/pytest.log`: its verbose test IDs contain the repository's own dummy credential fixtures. The bracketed parameters of those test IDs were replaced with `[REDACTED-FIXTURE-PARAM]`. Test names, outcomes and totals are unchanged, and no other file was altered.
