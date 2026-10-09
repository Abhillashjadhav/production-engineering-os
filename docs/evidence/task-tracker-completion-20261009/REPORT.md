# PMOS → PEOS task-tracker journey: completion run, 2026-10-09

Contract `PMOS-TASK-TRACKER-001`, canonical digest
`sha256:501e0fd5eae05bceffeef928d1b731173dd8be87c988340f2761575d29b7e80e`, approved freeze
`sha256:1dd281e55cc20ce1861e3bed55799617191f38c5cc4e2322c7e463ef9a6e37f2`.

Verdict: **the approved journey works end to end at its pinned commits and was re-run live in
this session (RELEASE_READY, 14/14). It is BLOCKED on current `main` of both repositories by one
approval decision, not by code.** This is one feature under the owner-authorized container
fallback; it is not a platform-readiness or production claim.

Everything under `runs/` was produced in this session. `mode` in each result distinguishes
`AUTHORIZED_HOST_FALLBACK_NO_ADDITIONAL_ISOLATION` real execution from nothing else; no
mocked run is presented as real. Unit tests (`tests/unit/`) are the only mocked layer.

## 1. Completion map

Levels: I = implemented, T = locally tested, N = integrated on a main branch, D = demonstrated
in a real run, P = deployed. Deployment is out of scope for both repositories by design.

| Requirement | Implementation | Verification evidence | Level | Remaining gap | Next action |
| --- | --- | --- | --- | --- | --- |
| Approved contract, receipt, 14 criteria, bindings, profile, freeze (PMOS owns) | PMOS `reviews/task-tracker-v1/` (on `main`) | `runs/01-pinned-verify`, PMOS `tests/test_task_tracker_freeze.py` (2 of 3 pass) | I T N D | One bound PMOS file (`decision-to-contract/SKILL.md`) drifted after the freeze | Owner approves re-freeze digest `sha256:20e67cca…` (PMOS `reviews/task-tracker-v1/refreeze-candidate-20261009/`) |
| PMOS → PEOS publisher path (draft, exact-digest approval, receipt, compile, admission) | PEOS `pmpe legacy contract …`, `verify_contract_approval`; PMOS `docs/HANDOFF.md` | PMOS `check_handoff.py` → `HANDOFF_SETUP_OK`; `test_current_authoring.py` 7/7 at pin `297a11d7` | I T N D | Documented pin is a PEOS commit not on PEOS `main`; release baseline undecided (PMOS BAR 2026-10-01) | Owner decides the supported PEOS pin; no code needed for this journey |
| File entry: load frozen bindings, compatibility, digest guard, host fallback (`contract-file.py`) | PEOS `examples/barebones/contract-file.py` (PR #203, now merged into this branch, clean merge) | `tests/unit/test_contract_file_entry.py`; `runs/01`, `03`, `06c`, `07`, `08*` | I T D | Not on PEOS `main` (PR #203 open since Sept 21) | Merge this branch's PR #203 content to `main` |
| In-session model provider (file handoff, no key, no CLI) | PEOS `examples/barebones/session-file-provider.py` (PR #199, merged here) | `tests/unit/test_session_file_provider.py`; `runs/03` two live calls; `runs/04` bad digest → `MODEL_PROVIDER_FAILED` | I T D | Needs an active agent session; not headless | None for this journey |
| BAR Gate (`AGENTS.md`) in both repos | PMOS `main`; PEOS only on PR #197 branch, merged here | file present on both branches | I N(PMOS) | PEOS `main` still lacks it | Merge |
| Engine: meaningful RED → one bounded coder → verify → RELEASE_READY/HALTED | PEOS `src/pmpe/barebones.py` (`main`) | `runs/03` ledger: `contract_validated, meaningful_red_confirmed, coder_completed, verification_started, release_ready` | I T N D | — | — |
| Failed/blocked work cannot read as complete | entry (`result.json` only on completion), engine (`HALTED`), `pmpe barebones status` | `runs/04` HALTED exit 1; `runs/06b` interrupted → no `result.json`, status `BUILDING/IN_PROGRESS`; `runs/08*` refusals exit 2; `runs/08d` mutation → FAIL exit 1 | I T D | SIGKILL leaves no `failure.json` (only absence of `result.json`) | Accept as documented; regression script classifies it `BLOCKED` |
| Clean-install reproduction (`REPRODUCE.md`) | PEOS docs + `clean-install/journey.py` | `fresh-setup/01-verbatim-python3.log` FAILS (python3 = 3.13); `fresh-setup/02-corrected-python3.12.log` PASSES 14/14 + 8/8 | I T D | Docs said `python3` | Fixed on this branch (`python3.12`) |
| Repeatable regression report | PEOS `examples/barebones/task-tracker-regression.py` (new, thin wrapper over the entry) | `tests/unit/test_task_tracker_regression_report.py` 5/5; `regression-report/report-pinned.json` PASS, `report-current.json` BLOCKED with diff | I T D | Not on `main` | Merge |
| Real Bubblewrap sandbox leg | PEOS `candidate_sandbox` | — | — | `BLOCKED_BY_ENVIRONMENT`, owner closed retries | Not retried, per settled decision |
| Approval-receipt signing | PEOS admission | — | — | Public-hash receipts remain forgeable | Deferred by owner |

## 2. The journey, traced

1. **User request** → PMOS `prd-first` / `decision-to-contract` captured the task-tracker intent as
   `publisher-input.json` (problem, user, outcome, 6 FRs, 14 ACs, gates, limitations).
2. **Planning / contract** → the existing PEOS publisher produced `contract.draft.json`, the owner
   approved its exact digest, the publisher emitted `contract.approved.json` + `approval-receipt.json`;
   `compile_barebones_plan` produced `compiled-plan.json` (plan digest `sha256:1dad520e…`).
3. **Freeze** → `freeze-manifest.json` binds 218 artifacts (14 PMOS, 204 PEOS source files) by raw SHA-256.
4. **Execution** → `contract-file.py build` loads the bindings, checks compatibility (CPython 3.12,
   `prlimit`, no dependencies, fallback authorized, receipt bound, plan unchanged), runs the baseline
   RED (14 assertion failures on the skeleton), hands one `code` request to the session through the
   file shim, receives `product.py`, then one non-blocking `advisory_review`.
5. **Verification** → the frozen evaluator runs every criterion in fresh CLI processes under
   `prlimit`, with all 218 + materialized artifacts hashed before and after each process.
6. **Result the user receives** → `result.json` (`state: RELEASE_READY, cause: PASS`), the generated
   `candidate/product.py`, the hash-chained ledger `.pmpe/runs/task-tracker-live/events.jsonl`, and
   the retained request/response pairs. The person then uses the product directly:
   `python product.py --store ./my-tasks.json create "Buy milk"`.

## 3. Real runs in this session

| Run | What | Outcome |
| --- | --- | --- |
| 01 | `verify` retained Sept candidate at pinned PEOS `f7669c2` + PMOS `9d55bf6` | exit 0, 14/14 PASS, 30 digest checks, 0 mismatches |
| 02 | `verify` on PEOS branch + PMOS `main` with the approved freeze | exit 2, refused before execution: `APPROVAL_BOUND_ARTIFACT_CHANGED` naming 5 files |
| 03 | **live `build`** at pinned commits, this session as the model | `RELEASE_READY`, `PASS`, 1 attempt, 2 model calls, 28 processes, 58 digest checks, 0 mismatches; product `sha256:a0130398…` differs from the Sept candidate (new bytes) |
| 04 | tool failure: provider returns wrong `request_digest` | `HALTED`, `MODEL_PROVIDER_FAILED`, exit 1, no candidate claimed |
| 05 | tool failure: no response before the shim deadline | shim `RESPONSE_TIMEOUT` after 540 s (engine budget wins over the caller's `PMPE_PROVIDER_TIMEOUT_SECONDS`), engine `HALTED`, `MODEL_PROVIDER_FAILED`, exit 1 |
| 06 | 8-command user journey (`journey.py`) against run 03's product | PASS, 16 digest checks |
| 06b | build SIGKILLed while waiting for the model (simulated session loss) | no `result.json`; ledger ends at `meaningful_red_confirmed`; `pmpe barebones status` → `BUILDING / IN_PROGRESS` |
| 06c | recovery: new output dir, `verify` run 03's candidate | 14/14 PASS (same output dir correctly refused: `FileExistsError`) |
| 07 | **dry run** on current code with the UNAPPROVED re-freeze candidate | 14/14 PASS, compatible, plan digest unchanged — proves only the approval step is missing |
| 08a–c | wrong freeze digest / `verify` without `--candidate` / no fallback flag | refused: `FREEZE_DIGEST_MISMATCH` (1), `--candidate is required` (2), `HOST_FALLBACK_NOT_AUTHORIZED` (2) |
| 08d | mutated product (list ignores `--status`) | AC-004, AC-005 FAIL, exit 1 |
| 08e | mutated evaluator inside candidate | refused before first process: `APPROVAL_BOUND_ARTIFACT_CHANGED`, exit 2 |
| 08f | mutated approved contract (severity edit) in a packet copy | refused: `approval receipt is not bound to the approved contract`, exit 2 |
| 08g | product-level invalid input (direct CLI) | `INVALID_TITLE/ID/STATUS/COMMAND`, `NOT_FOUND` exit 2; `STORE_INVALID`, `STORE_IO` exit 1 |
| 09 | regression report pinned → current | `PASS` → `BLOCKED`, `outcome_changed: true`, 14 criteria `PASS → null` |
| fresh | `REPRODUCE.md` verbatim, then with `python3.12` | verbatim FAILS at install (3.13); corrected PASSES 14/14 + 8/8 |

Session responder: `session-responder.py` delivered pre-authored `session-authored-product.py`
(written by this session from the contract before launch) to the shim; it is transport, not
generation by a separate model. Model identity and tokens are unreported by design of the shim.

## 4. Exact blockers today

1. **Approval-bound drift (the only blocker for current `main`).** Five frozen bytes changed after
   the freeze: PMOS `.claude/skills/decision-to-contract/SKILL.md`; PEOS `src/pmpe/barebones.py`,
   `src/pmpe/cli/barebones_cmd.py`, `src/pmpe/contracts/acceptance.py`,
   `src/pmpe/evals/real_behavior_drift_eval.py`. The entry fails closed, as the approved profile
   requires. Resolution is an owner decision: approve re-freeze digest
   `sha256:20e67cca5a1745cf5d7244019a1ccdebf3b9d4e29cc69fbaf016f2f469f6a4c0` after reviewing those
   five diffs (run 07 shows the result would be 14/14 PASS with the plan unchanged).
2. **Unmerged code.** The entry, provider shim, `AGENTS.md`, evidence and tests live on PR #203's
   stack; PEOS `main` has none of them. This branch carries the clean merge.
3. **Environment.** No Bubblewrap user namespaces (owner closed retries); `python3` is 3.13 on this
   host (docs fixed). Neither blocks the authorized fallback journey.

## 5. Commands

Start (one sequence, sibling checkouts `peos/` and `pmos/`, Linux, `python3.12`, `prlimit`):

```bash
git clone --branch claude/pmos-peos-completion-ds46x1 https://github.com/Abhillashjadhav/production-engineering-os.git peos
git clone --branch claude/pmos-peos-completion-ds46x1 https://github.com/Abhillashjadhav/PM-agent-OS.git pmos
cd peos && python3.12 -m venv .venv && .venv/bin/python -m pip install -e ".[dev]"
```

Checks (one command each):

```bash
.venv/bin/python -m pytest tests/unit tests/integration tests/e2e -q      # PEOS suite
.venv/bin/ruff check src tests && .venv/bin/mypy                            # lint + strict typing
(cd ../pmos && python3 -B -m unittest discover -s tests -p 'test_*.py')    # PMOS offline suite
(cd ../pmos && python3 -B tests/test_task_tracker_freeze.py)               # RED until re-freeze approved
```

Demonstration (repeatable; replay needs no model, `build` needs an agent session to answer
`OUTPUT/handoff/call-*/request.json`):

```bash
# today: refused on current code, exit 2, names the five drifted files
.venv/bin/python examples/barebones/contract-file.py verify --packet ../pmos/reviews/task-tracker-v1 \
  --root PM-agent-OS=../pmos --root production-engineering-os=. \
  --freeze-digest sha256:1dd281e55cc20ce1861e3bed55799617191f38c5cc4e2322c7e463ef9a6e37f2 \
  --candidate docs/evidence/task-tracker-live-20260918/live/candidate --output /tmp/tt-verify --authorized-host-fallback

# after the owner approves the re-freeze: same command with the new --freeze-digest → 14/14 PASS
# regression report (PASS / FAIL / BLOCKED, diffed against the previous report):
.venv/bin/python examples/barebones/task-tracker-regression.py --packet ../pmos/reviews/task-tracker-v1 \
  --root PM-agent-OS=../pmos --root production-engineering-os=. --freeze-digest sha256:<approved> \
  --candidate docs/evidence/task-tracker-live-20260918/live/candidate --output /tmp/tt-reg --report /tmp/tt-report.json \
  --previous docs/evidence/task-tracker-completion-20261009/regression-report/report-pinned.json --authorized-host-fallback
```

Pinned reproduction that passes today without any approval: `docs/evidence/task-tracker-live-20260918/REPRODUCE.md`.

## 6. Useful work sitting on other branches (not merged, not used here)

- PEOS #240 (`agent/peos-pmos-core-harness-20261001`): a second, re-approved task-tracker
  contract (version-2 draft, Oct 2) and a fixed core harness; ends `HALTED` by design. Competes
  with the frozen packet; not adopted because the owner settled on `PMOS-TASK-TRACKER-001`.
- PEOS #228 (`feat/approved-bundle-run`, 257 commits ahead): `pmpe barebones run-bundle`, typed
  process gates. A supported-CLI path for bundles; large R3/R4 stack, unreviewed on `main`.
- PEOS #235: opt-in Bubblewrap launcher for the offline provider; `mergeable_state: dirty`.
- PMOS #63–#66: handoff fixture proving `RELEASE_READY/HALTED/CONTRACT_BLOCKED` at PEOS pin `5ccc46ce`.

## 7. Limitations carried forward (unchanged, approved)

Container fallback without namespaces; root can alter evidence between hashes; receipts
forgeable; model identity/tokens unreported; create not idempotent; concurrency out of scope;
no deployment surface exists in either repository.

## 8. Branch checks (PEOS `claude/pmos-peos-completion-ds46x1`)

Ruff check: pass. Ruff format: 299 files already formatted. Strict mypy: 187 source files, no
issues. New unit tests: 5/5 (regression report). Full `pytest tests/unit tests/integration
tests/e2e`: still running at commit time (91 %, 0 failures, 1 skip); its final line is recorded in
`branch-tests.log` by a follow-up commit. PMOS branch: offline suite 29/29, repository audit PASS,
PR quality gate PASS, current-authoring 7/7 at pin `297a11d7`, drift test 2/3 (RED by design).
