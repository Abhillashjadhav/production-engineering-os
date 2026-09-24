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
