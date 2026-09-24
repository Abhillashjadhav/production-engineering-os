# R4 retained inspection repair

The existing reader now checks contract/subject/plan identity and re-verifies a
VERIFIED receipt against the recorded authority before accepting a release with
no gates. Receipt and plan binding checks also apply to validated HALTED runs.
Only release-ready candidates undergo full retained-plan reconstruction.

The latest releasing attempt must contain `coder_completed`,
`verification_started`, then exactly `release_gates_evaluated, release_ready`
when gated, or `release_ready` when ungated. Duplicate results for the same
attempt, contradictory failures, missing starts, and unknown interposed events
are rejected. A state named RELEASE_READY cannot substitute for its terminal
event. Earlier failed attempts remain permitted when followed by a coherent new
coder/verification attempt.

All three CLI readers report `head_anchor`: NOT_PROVIDED or VERIFIED with the
supplied expected digest. VERIFIED means equality to that supplied value; its
independent origin is the caller's responsibility. A fully consistent unsigned
rewrite remains inspectable without an external anchor. Tests reject a rewrite
using the genuine original packet head, not an invented mismatch value.

Process evidence uses the same pure `process_gate_validation.py` helper as the
process worker, included in this branch so imports work independently. The
reader also binds that evidence's run and attempt to its enclosing gate event.
The helper rejects freshness claims based only on self-reported attestation.

## Verification

Interpreter: `/workspace/scratch/f9ac546f3a50/overnight-20260923/venv/bin/python`.

Baseline command (exit 1): `PYTHONPATH=src python -m pytest -q tests/unit/test_release_gate_inspection.py tests/unit/test_barebones_cli_journey.py`.
`baseline.txt` records five pre-existing journey fixture failures also observed
in the prior remote CI. Their fixtures now contain a real compiled plan, full
test-only receipt, coder completion, and verification start. The filesystem
failure stub also supports the integer descriptor accepted by `os.scandir`.

RED command (exit 1), with unchanged source exported from `50bb80b`:
`PYTHONPATH=/tmp/r4-peos-inspection-red-source/src python -m pytest -o addopts='' -q tests/unit/test_r4_release_gate_inspection.py tests/unit/test_release_gate_inspection.py`.
Result: **45 failed, 44 passed** (`red.txt`). Initial test import and rewrite
fixture-registration mistakes were corrected, then this full RED was rerun;
all 45 recorded failures reach their intended mutation/anchor assertions.

GREEN command (exit 0):
`PYTHONPATH=src python -m pytest -o addopts='' -q tests/unit/test_r4_release_gate_inspection.py tests/unit/test_release_gate_inspection.py tests/unit/test_barebones_cli_journey.py tests/unit/test_process_gate_evidence_r4.py`.
Result: **106 passed in 2.51s** (`reader-green.txt`).

Ruff check and mypy on the changed reader and CLI passed. Final package and
cross-packet integration results will be appended when complete. No models,
remote mutation, frozen-input changes, approval fabrication, or release claim.

## Support-package protocol

The real `seal_support_release` producer emits its own package contract and
five-field receipt with exactly `contract_validated, release_ready`. It has no
barebones plan or coder attempt. The package-specific reader retains its existing
exact contract, receipt, fixed file surface, canonical runtime, and external-head
checks, while a small sequence guard rejects additional events or gate
declarations. No generic no-gates bypass is introduced. The existing support
test file is untouched, preserving exact-line synthetic-secret approvals.

RED (exit 1): `PYTHONPATH=/tmp/r4-peos-inspection-red-source/src python -m pytest -o addopts='' -q tests/unit/test_r4_package_release_inspection.py`.
Result: **1 failed, 3 passed**. The failure is a re-chained unknown interposed
event; real seal+assembly and already-rejected gate/identity mutations preserve
the earlier behavior.

GREEN (exit 0): `PYTHONPATH=src python -m pytest -o addopts='' -q tests/unit/test_r4_package_release_inspection.py tests/unit/test_support_package_v1.py`.
Result: **88 passed in 56.02s**. Ruff format/check, mypy for the package guard and
reader, and diff-check pass. Raw logs are `package-red.txt` and `package-green.txt`.

Independent review: the verifier's archived `7a9abc1` reader probe preserved
gated/ungated and unsigned-rewrite controls while rejecting its nine
contradictions and RELEASE_READY-state override. An additional process-evidence
context-binding concern is being reproduced with the process worker; N1 is not
claimed fully closed until that cross-packet integration is checked.

## Process-context follow-up

The independent verifier reproduced two additional N1 contradictions using its
completed task-store fixture: changing only one mutant's candidate manifest or
plan digest, re-binding the gate blob, and re-chaining the ledger still passed
without an external head. The genuine original head rejected both. This was a
diagnostic composition of the reader archive and process runtime, not a claim
about a public combined tree.

The shared helper follow-up (process commit `0bba24f`, included here as `b030847`)
requires expected candidate/plan/contract/receipt identities. The reader passes
those identities only after verifying its enclosing contract, receipt, compiled
plan, and released candidate. The helper rechecks mutant context and the frozen
approval packet against them. This closes internal contradictions, not unsigned
rewrite authentication.

Final focused command (exit 0), with that helper and reader hook:
`PYTHONPATH=src python -m pytest -o addopts='' -q tests/unit/test_r4_release_gate_inspection.py tests/unit/test_release_gate_inspection.py tests/unit/test_barebones_cli_journey.py tests/unit/test_process_gate_evidence_r4.py`.
Result: **113 passed in 2.94s** (`context-green.txt`). This includes preserving
G2/G3 pure controls and candidate, plan, observer-marker, and frozen-contract
mutations. Ruff check and mypy on both changed modules pass. The earlier full
support result remains attributed to pre-context `c517b0f`; it was not repeated
for this isolated context-argument change. Root owns final combined-tree replay,
independent verification, exact-SHA CI, and publication.
