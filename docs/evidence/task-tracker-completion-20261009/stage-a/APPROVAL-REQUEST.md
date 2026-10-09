# Approval request — re-freeze of PMOS-TASK-TRACKER-001 on one integrated baseline

Status: UNAPPROVED. Nothing below replaces the active manifest or records approval.

## 1. Proposed source baseline (bound bytes locked)

| Repository | Source commit for bound bytes | Branch head carrying it | Bound entries | Notes |
| --- | --- | --- | --- | --- |
| production-engineering-os | `e8a929df0feca124005dfc84f1b5bebdd207eab9` | `f06755c` (claude/pmos-peos-completion-ds46x1) | 204 | = current `main` 1a431b2 bytes + `examples/barebones/session-file-provider.py` (from PR 199). Commits after e8a929d touch only tests/docs; `git diff e8a929d..f06755c -- src schemas examples/barebones/session-file-provider.py pyproject.toml` is empty. |
| PM-agent-OS | `0652843f02b5fbd5734331ffe5c00675a7b40b6b` | `cafe8b4` (same branch name) | 14 | = current `main` 2acc3fa bytes for all 14 bound files. Commits after 0652843 touch only tests/, workflow and the unapproved candidate directory. |

Supported-baseline recommendation: adopt PEOS `e8a929d` lineage (current main plus the PR 197/199/203 stack) as the only baseline for this contract. The handoff pin `297a11d7` (PR 209 lineage) REJECTS the approved contract: `RELEASE_GATE_UNBOUND` on GATE-001..GATE-005, because the approved contract's five gates carry no `acceptance_criterion_refs`. Porting that enforcement (PR 209 commit 85358d5) onto e8a929d was probed: it would change 2 bound files, add 4 new ones, and still refuse the approved contract. It is not a path to this journey without changing the approved contract, which would be a new product approval.

## 2. The five drifted bound files (complete diffs: stageA/w1/diff-1..5.patch, 458 lines total)

| # | File | Introduced by | What changed | Effect on contract / evaluator / execution / authority |
| --- | --- | --- | --- | --- |
| 1 | PMOS `.claude/skills/decision-to-contract/SKILL.md` | PMOS PR 68 (33ba7ec) | Prose only: 7-item verification gate incl. "every binary release gate has `acceptance_criterion_refs`"; `pmpe legacy contract …` names; stricter approval wording; new hard rules 2 and 3 | Contract: skill text now asks gates to carry refs, which the frozen contract's gates lack (PEOS code enforces nothing here at either commit; plan identical). Evaluator/execution: none. Authority: tightened wording, same mechanism (`verify_contract_approval`, `APPROVAL_RECEIPT_INVALID`). |
| 2 | PEOS `src/pmpe/barebones.py` | PEOS PR 243 (f1ac859) | Catch `OSError` from the provider alongside `RuntimeError`; `_classify_provider_error` | Execution: a provider `OSError` now ends `HALTED / MODEL_PROVIDER_FAILED` with a ledger event instead of an uncaught exception; advisory `OSError` → `{"status":"unavailable"}`. No contract, evaluator or authority change. |
| 3 | PEOS `src/pmpe/cli/barebones_cmd.py` | PEOS PR 243 (f1ac859) | Provider constructed after approval check; malformed command → `ContractInvalidError` (exit 3); stream `OSError` terminates the child | Execution only; approval check still precedes provider construction. |
| 4 | PEOS `src/pmpe/contracts/acceptance.py` | PEOS PR 244 (2c6d962, b3f89cd) | Criteria with assertion diagnostics are not compiled or counted as coverage; non-mapping `human_test` → `INVALID_HUMAN_TEST_REFERENCE` (previously silently dropped) | Compiler strictly tighter; the frozen contract (13 gwt + 1 measure, no human_test) compiles with zero diagnostics to the identical plan. |
| 5 | PEOS `src/pmpe/evals/real_behavior_drift_eval.py` | PEOS PR 233 (0d49f40) | Constant-size bwrap argv via one sealed memfd image for the drift-eval harness | Not on the contract run path (nothing in `src/` on the run path imports it). Bundle identity only. |

Full bound set recomputed from git object bytes at the baseline: 218 entries, 5 changed (the five above), 0 missing. No additional drift.

## 3. Recomputed candidate manifest

- Location: PMOS `reviews/task-tracker-v1/refreeze-candidate-20261009/freeze-manifest.candidate.json` at `cafe8b4` (identical copy: scratchpad/stageA/freeze-manifest.candidate.json). Active packet untouched.
- Artifact count: 218 (14 PMOS + 204 PEOS).
- Candidate canonical digest (RFC 8785): **`sha256:82f6365cd895892c4cb9fadd279f82e2755cc62bed2c60d95f49233d4c1c7f42`**
  (supersedes the review's `sha256:20e67cca…`, whose artifact set was byte-identical; only metadata text differed.)
- Unchanged, verified at the baseline and cross-checked on the pinned tree: approved contract digest `sha256:501e0fd5eae05bceffeef928d1b731173dd8be87c988340f2761575d29b7e80e`; receipt verifies to `sha256:4b1f17711268f9bceca6d7b4fd4082bc35a65ddee383c6eb7eee28b5a64609ef`; compiled plan equals frozen `compiled-plan.json` (`canonical_digest` `sha256:4d552932…`), `plan_digest` `sha256:1dad520ebc6ac6973aeb23d80fe5c98d67e3d8a5fa20d902f56d45a180777b28`; 14 criteria, zero diagnostics.
- Dry run (UNAPPROVED, isolated packet copy, run 10): verify on the baseline under this candidate → 14/14 PASS, 0 findings, compatible, 0 digest mismatches.
- Note on digests: the active freeze digest written in step 2 of the procedure is computed after your quote and timestamp are recorded in the manifest, so it will differ from the candidate digest above while binding the identical artifact set. It will be reported back with the exact `--freeze-digest` value.

## 4. What this approval authorizes, and what it does not

Authorizes (Stage B):
1. Replace `reviews/task-tracker-v1/freeze-manifest.json` with the candidate, status `OWNER_CONFIRMED_FROZEN`, your quote and timestamp recorded verbatim; write the new digest to `freeze-bundle.sha256`; update the packet README and the PEOS entry docs; the old manifest, receipt and evidence remain as history.
2. A fresh live build on the approved baseline through `contract-file.py build` + `session-file-provider.py` (host fallback, active session model required, identity unreported by the shim), then the full failure-boundary recheck and the regression reports.
3. Turning the PMOS freeze guard green by the approved bytes, never by editing the test.

Does not authorize: merging either branch, opening PRs, any deployment, Bubblewrap retries, receipt signing, changes to the approved contract or its 14 criteria, or adoption of a new publisher pin.

Pin decision folded in (your call, no code prepared for adoption): keep `297a11d7` for the generic PMOS current-authoring job (it is the only lineage satisfying that job's two gate-enforcement assertions) and record `e8a929d` as the task-tracker baseline in `docs/HANDOFF.md`; OR move the handoff pin to `e8a929d` (patch prepared and validated: `HANDOFF_SETUP_OK`, test_handoff_setup 6/6, but test_current_authoring 5/7 with the two `RELEASE_GATE_UNBOUND` assertions failing). My recommendation: the first; a single pin satisfying both does not exist today.

## 5. Observed checks and blockers at the baseline

PEOS branch (f06755c): ruff check pass, ruff format pass, mypy strict pass (187 files), entry tests 7/7, provider tests 6/6, regression-report tests 5/5. Full suite: see clean-room table below.
PMOS branch (cafe8b4): offline suite pass, repository audit PASS, PR quality gate PASS, freeze guard 3 pass + 1 RED (the live drift check, by design until re-freeze), negative drift-detection test pass.
Clean-room reproduction (disposable clones at e8a929d / 0652843; full logs in stage-a/w2/):

| Step | Command (source) | Exit | Result |
| --- | --- | --- | --- |
| PEOS install | `python3.12 -m venv .venv && .venv/bin/python -m pip install -e ".[dev]"` (README) | 0 | ok |
| PEOS pytest | `pytest tests/unit tests/integration tests/e2e -o addopts="" -rs` (pyproject/ci.yml) | 1 | **2909 passed, 4 skipped, 1 failed** in 24m19s; skips are bwrap-only; the failure `test_support_package_v1.py::test_package_verification_rederives_every_port` (`forbidden-capability proof did not execute: low_confidence`) is unrelated to the task tracker and passed on an isolated re-run (non-deterministic) |
| PEOS ruff format --check | ci.yml path list | 0 | 308 files already formatted |
| PEOS ruff check | ci.yml path list | 0 | All checks passed |
| PEOS mypy --strict | ci.yml path list | 0 | 200 source files, no issues |
| PMOS audit_repository | repository-audit.yml | 0 | PASS (40 lifecycle, 3 supporting, 7 personas) |
| PMOS test_handoff_setup / beacon / validation_regressions | repository-audit.yml | 0/0/0 | 6 ok / 7 ok / 9 ok |
| PMOS lint every SKILL.md | repository-audit.yml | 0 | 47 pass, 0 fail |
| PMOS pr_quality_gate --base-ref main | repo rule | 0 | PASS |
| PMOS test_task_tracker_freeze | repository-audit.yml (branch) | 1 | 2 ok, 1 FAIL = the live drift check, as designed |
| Handoff: pmpe from local PEOS @e8a929d, test_current_authoring | current-authoring.yml | 1 | 5 ok, 2 FAIL: `RELEASE_GATE_UNBOUND` assertions (PEOS main lineage does not enforce gate refs) |
| Handoff: check_handoff.py | current-authoring.yml | 2 | `PUBLISHER_PROVENANCE_UNKNOWN` for a path install; with a git+ install at e8a929d and the pin patch applied: `HANDOFF_SETUP_OK` |
| Handoff: validate_contract.py (historical gate) | repository-audit.yml | 0 | PASS at e8a929d |

Blockers: (a) this approval; (b) no CI runs on branch pushes in either repo, so "required checks green" needs pull requests, which I am not authorized to open; (c) SIGKILL-interruption, missing-candidate and missing-fallback-flag refusals remain manual evidence only.

## 6. Request

Please approve, in writing, the re-freeze of PMOS-TASK-TRACKER-001 over baseline PEOS `e8a929d` / PMOS `0652843` with candidate digest `sha256:82f6365cd895892c4cb9fadd279f82e2755cc62bed2c60d95f49233d4c1c7f42`, and state your pin decision. I will not proceed to Stage B without that exact approval.
