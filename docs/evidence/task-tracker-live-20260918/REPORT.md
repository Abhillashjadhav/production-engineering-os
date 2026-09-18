# PMOS → PEOS: approved task-tracker run

**DEMONSTRATED FOR THE APPROVED FEATURE**, using the owner-authorized existing-container fallback.
One feature establishes feasibility; this is not a general platform-readiness result.

## Observed result

The real in-session model returned `product.py` once. Its exact bytes passed all 14 frozen criteria;
no manual product repair was made. The engine recorded 1 build attempt, 2 model calls (code and
non-blocking same-session advisory), and 75,131 ms elapsed. The advisory is not independent review.
Sources: [summary](summary.json), [engine result](live/result.json),
[model requests/responses](live/handoff), [generated product](live/candidate/product.py).

The original baseline failed all 14 criteria by assertion. Isolated persistence and filtering
mutations were rejected by the unchanged checks, without using crashes as substitutes.
Sources: [engine ledger](live/.pmpe/runs/task-tracker-live/events.jsonl),
[persistence diff](mutations/persistence/mutation.diff),
[persistence results](mutations/persistence/verification/result.json),
[filter diff](mutations/filtering/mutation.diff),
[filter results](mutations/filtering/verification/result.json).

| Criterion | Severity | Baseline | Live | Broken persistence | Broken filter | Clean replay |
| --- | --- | --- | --- | --- | --- | --- |
| AC-001 | major | FAIL | PASS | PASS | PASS | PASS |
| AC-002 | major | FAIL | PASS | FAIL | PASS | PASS |
| AC-003 | major | FAIL | PASS | FAIL | PASS | PASS |
| AC-004 | major | FAIL | PASS | FAIL | FAIL | PASS |
| AC-005 | critical | FAIL | PASS | FAIL | FAIL | PASS |
| AC-006 | major | FAIL | PASS | FAIL | PASS | PASS |
| AC-007 | major | FAIL | PASS | FAIL | PASS | PASS |
| AC-008 | major | FAIL | PASS | PASS | PASS | PASS |
| AC-009 | major | FAIL | PASS | FAIL | PASS | PASS |
| AC-010 | major | FAIL | PASS | FAIL | PASS | PASS |
| AC-011 | critical | FAIL | PASS | PASS | PASS | PASS |
| AC-012 | critical | FAIL | PASS | PASS | PASS | PASS |
| AC-013 | critical | FAIL | PASS | FAIL | PASS | PASS |
| AC-014 | critical | FAIL | PASS | FAIL | PASS | PASS |

Exact per-criterion observations are in [summary.json](summary.json) and
[process records](live/processes.jsonl). AC-013 performed ten strictly sequential creates,
each process exiting before the next started: **sample_size 10, missing records 0**.
AC-014 observed INVALID_TITLE (exit 2), then ID 1, then exactly that one stored task.
Concurrent creation is out of scope; no parallel-writer test was run.

## Approval and unchanged authority

The full proposal was regenerated from all 14 scenarios, including 14 detailed body sections.
Contract/grid/evaluator/prepared-manifest agreement was verified and reported before recording
approval digests. The existing publisher derived the approved contract and receipt.
The evaluator and expected outcomes were unchanged during building and verification.
Source: [frozen PMOS packet](https://github.com/Abhillashjadhav/PM-agent-OS/tree/3fa07a876fe25fc8998f739fe5b9ae05353ce191/reviews/task-tracker-v1).

Freeze digest: `sha256:1dd281e55cc20ce1861e3bed55799617191f38c5cc4e2322c7e463ef9a6e37f2`.
Generated product digest: `sha256:5ef500b5304cc7a5ba1a0e8498675cb01641b71c9c3e5e38bf01d5226e24ade5`.

All 218 frozen artifact entries, the manifest itself, materialized acceptance files and the
entry script were checked at their defined execution boundaries. The live run recorded 58
before/after observations with zero mismatches. Each mutation verification and clean replay
recorded 30 observations with zero mismatches. Error/timeout finally behavior is covered by
`python -m unittest discover -s tests/unit -p test_contract_file_entry.py -v` (6 passing tests).
Sources: [live digest checks](live/digest-checks.jsonl), [summary](summary.json),
[guard tests](../../../tests/unit/test_contract_file_entry.py).

A changed approved-contract replica was rejected before candidate execution. Replacing the
candidate evaluator was also rejected before its first process. These are bounded observed
tamper checks, not proof against a root adversary.
Sources: [contract tamper](tamper/contract/result.json),
[evaluator replacement](tamper/evaluator/result.json), [probe source](phase4-checks.py).

## Minimum implementation and reuse

One [file entry](../../../examples/barebones/contract-file.py) loads frozen Template fields,
checks compatibility and invokes the existing runtime/provider APIs. It records the explicit
host fallback and before/after hashes. No existing `src/` file, schema, publisher or observer
was modified. Compatibility checks cover runtime, dependencies, resource limiter, fallback
permission, evaluator bindings, receipt and exact compiled plan. Invalid inputs return reasons.
The checked profile is frozen and rechecked before every build/verification. Compatibility
means an attempt can be evaluated, not that delivery is guaranteed.
Sources: [entry documentation](../../../examples/barebones/contract-file.md),
[live compatibility](live/compatibility.json), [execution source](live/execution-source.json).

**New business actions do not require an engine-source change, only a CLI path.**
The separate `greeting.echo` contract/binding fixture loaded and executed with one passing
criterion and zero further engine edits. It is explicitly a DRAFT test fixture, not a second
approved product or live-model result. [Extension result](extension/result.json).

**Prior live-provider evidence already exists in the repository, unverified by this run.**
This corrects the earlier fixture-only assertion. Current live evidence is separately retained
in [handoff records](live/handoff); the earlier correction and historical evidence references
are in [the audit](https://github.com/Abhillashjadhav/production-engineering-os/blob/audit/task-tracker-seam/docs/evidence/task-tracker-audit-20260918/owner-amendment.md).

## Clean installation and launch

Fresh local clones used committed PEOS `02a718d0ebfbe1a938a4d1b56119aa8976627d0f` and
PMOS `88bc530e0a100c11988ce7d38349b14a038cd0cc`, then standard `python3 -m venv .venv`
and `.venv/bin/python -m pip install -e .`. Installation succeeded. The exact generated
candidate was copied without edits; all 14 criteria passed and eight separate CLI commands
completed the create/duplicate/complete/retry/filter journey. This was an artifact replay,
not a second live model generation or a real-sandbox run.
Sources: [install log](clean-install/install.log), [verification](clean-install/verification/result.json),
[journey](clean-install/journey.json), [journey checks](clean-install/journey-digests.jsonl).

After checking out this PR and PMOS PR #58 into sibling `peos` and `pmos` directories:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python examples/barebones/contract-file.py verify \
  --packet ../pmos/reviews/task-tracker-v1 \
  --root PM-agent-OS=../pmos --root production-engineering-os=. \
  --freeze-digest sha256:1dd281e55cc20ce1861e3bed55799617191f38c5cc4e2322c7e463ef9a6e37f2 \
  --candidate docs/evidence/task-tracker-live-20260918/live/candidate \
  --output /tmp/task-tracker-verification --authorized-host-fallback
python3 docs/evidence/task-tracker-live-20260918/live/candidate/product.py --store /tmp/my-tasks.json create "Buy milk"
python3 docs/evidence/task-tracker-live-20260918/live/candidate/product.py --store /tmp/my-tasks.json complete 1
python3 docs/evidence/task-tracker-live-20260918/live/candidate/product.py --store /tmp/my-tasks.json list --status completed
```

Use a new output directory for verification and an intentional store path for personal tasks.
Replace `verify --candidate ...` with `build` for fresh model generation; an active agent must
answer the retained file handoffs as documented in the entry guide. The original exact command,
entry hash and Python paths are recorded in each run’s `execution-source.json`.

## Permanent limitations

- **Creation is not idempotent.** Duplicate-on-retry is approved behavior, not a defect. There is no create retry-safety claim. Completion idempotency is AC-007.
- Concurrent creation and crash/power-loss durability are outside this single-writer experiment. AC-013 is a deterministic missing-record count, not statistical model-quality or latency evidence.
- The builder and orchestrator run as root. They can rewrite checkers/evidence or restore a transient change between snapshots. Hashes supply bounded tamper evidence, not prevention.
- Approval receipts remain forgeable from public hashes. No signing-authority repair was attempted; owner approval is recorded in the conversation and freeze artifact.
- The real-sandbox leg is **blocked by environment**. The prior `--unshare-all --share-net` retry and explicit namespace probe both failed user-namespace UID-map creation. The owner closed further attempts; none was made here.
- The authorized fallback lacks additional candidate **user, PID, mount, IPC, UTS, cgroup and network namespaces**, **read-only runtime/candidate mounts**, and **private tmpfs/proc**. It retains resource limits, timeouts, output/path validation and all acceptance/digest checks. Exact process argv is in the process records. It is not a second sandbox.
- Limits used: `prlimit --as=1073741824 --cpu=11 --fsize=67108864 --nofile=256 --nproc=128`; action timeout 10 s, child CLI timeout 2 s. Prior probes observed configured values; enforcement was not stress-tested, and root can weaken controls.
- Live generation depends on an active agent session. There is no claim of headless reproduction or independent model identity verification.
- Provider usage was unavailable. Engine token/cost counters initialized to zero are not measured zero usage or cost; this report records both as unknown.
- No merge, deployment or release occurred. One successful feature does not establish general product-building reliability.

The scope/limits are frozen in the [execution profile](https://github.com/Abhillashjadhav/PM-agent-OS/blob/3fa07a876fe25fc8998f739fe5b9ae05353ce191/reviews/task-tracker-v1/execution-profile.json); observed run metrics are in [summary.json](summary.json).

## Commit and review trace

- Starting PEOS provider: remote `1abfbd47061a947e8ce077523a60516a0b6cdcb0`; local `863fc449051033d3b51627e95ab50b7f301edd1f` (identical tree).
- Frozen PMOS: remote `3fa07a876fe25fc8998f739fe5b9ae05353ce191`; local `88bc530e0a100c11988ce7d38349b14a038cd0cc`; tree `b60a9c418dfa5551695e27acad946833dd93c9bf`.
- Tested PEOS implementation: remote `54df3c09a83c033499a638f7fb24531420eb38ec`; local `02a718d0ebfbe1a938a4d1b56119aa8976627d0f`; tree `641a11886955bbcd88120ea91a9e94ead3129855`.
- Evidence is a separate follow-up commit. Its exact published head and tree are recorded in the review on [PR #203](https://github.com/Abhillashjadhav/production-engineering-os/pull/203). The review is labelled orchestrator self-review.
- [Issue #202](https://github.com/Abhillashjadhav/production-engineering-os/issues/202), [PMOS issue #56](https://github.com/Abhillashjadhav/PM-agent-OS/issues/56), and [PMOS PR #58](https://github.com/Abhillashjadhav/PM-agent-OS/pull/58) preserve the owner decisions and execution status.

## Strict typing follow-up

GitHub CI found 39 type errors in the new entry after the first evidence commit.
Correction attempt 1 adds annotations and separates the verification result variable;
normalized executable operations/control flow are unchanged. The exact strict-mypy
CI command now passes all 199 source files locally. Six guard tests and unchanged
14/14 candidate verification also pass, with 30 matching digest observations.
No product, frozen artifact, existing engine source or expected outcome changed.
The live generation above retains its original source digest; this is a separate
verification using the corrected entry, not another live build.

Evidence: [before CI findings](type-correction/ci-before.json),
[mypy output](type-correction/mypy.log), [validation](type-correction/validation.json),
[unit tests](type-correction/unit-tests.log), [replay](type-correction/verification/result.json).
The initial local checker setup lacked the already-locked packaging dependency;
that environment finding is retained in type-correction/mypy-environment.log.
The automated review-admission job rejects draft PRs; it was not bypassed or
represented as an independent review.
