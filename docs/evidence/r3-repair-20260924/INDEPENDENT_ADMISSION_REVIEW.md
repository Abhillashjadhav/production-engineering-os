# Independent R3 admission and inspection review

**Final independent disposition: both findings below are CLOSED at
`e719157ac43de6721f572d2c1eb7467c922bb883` (tree
`b1d1f1f9b1865da895040ebb41f60630b910a4e5`).** The exact original probes now reject
both inconsistent packets with `EVIDENCE_INVALID`; the valid control still
passes. The independent focused suite passes 88 tests. See the re-review below.

Date: 2026-09-24. Implementation reviewed:
`8ba3476c5395192315477cabf8e8ab698224a737`, tree
`3a6f2a3d689c9d5656336c8dde4bedfc3ab404e9`. The inspected checkout was at
`4ea81251093dc6fc6e19562b7d84dea1e8f2a222`; its changes after the implementation
commit are documentation/evidence only.

**Initial verdict: REQUEST CHANGES for two reproduced internal-consistency
gaps.** No production source was edited. Probes create disposable synthetic
evidence fixtures only; they do not call a runner, provider or candidate. The
fixtures are not product-owner approvals or genuine execution claims.

## Findings

1. **Retained criteria with no executable form are accepted.** In
   `src/pmpe/evidence/release_gates.py`, the retained plan's `criteria` are checked
   only for string `criterion_id` values, then used as the set of compiled IDs.
   Replacing the plan criteria with `[{"criterion_id":"AC-001"}]`, recomputing
   its plan digest and updating the gate blob's plan reference produces a valid
   evidence chain and `inspect` exits zero with `release_eligible: true`.
   The original contract is unchanged; the claimed compiled criterion has no
   form, action or assertions. Validate the retained criterion shape and its
   contract-derived semantics, not merely ID presence.
2. **A recorded failure after the gate PASS is ignored.** The reader uses the
   latest `release_gates_evaluated` event but does not ensure it remains valid
   after subsequent verification/build/terminal events. Inserting a
   `verification_failed` event containing `ASSERTION_FAILED:AC-001` between the
   PASS gate event and `release_ready`, then recomputing only the synthetic
   ledger chain, still yields exit zero and `release_eligible: true`. The
   contract, plan and gate blob are unchanged. Reject contradictory events
   after the gate evidence used by the release; bind to the final verification
   attempt and require the correct event order.

These packets contain mechanical contradictions; rejecting them does not
require signatures or a claim of preventing fully self-consistent forgery.
Supplying the original independently retained head correctly rejects both
rewritten fixtures with exit 3 and an expected-head mismatch. The external-head
behavior and its stated trust limitation are accurate.

## Checks and reproduction

The 66 compiler and retained-inspection unit tests pass. An initial invocation
failed during setup because this review's temporary parent directory did not
yet exist; creating the allowed output directory and rerunning resolved that
review-environment error. An initial custom probe attempted `put_blob` on a
read-only inspection object and was rejected; the working probe keeps the
test fixture's original writer. Neither initial error is a product finding.

Working directory:
`/workspace/scratch/f9ac546f3a50/r3-20260924/peos-admission`.

```sh
PYTHONPATH=src /workspace/scratch/f9ac546f3a50/overnight-20260923/venv/bin/python -B -m pytest -q -p no:cacheprovider --basetemp=/workspace/scratch/f9ac546f3a50/r3-20260924/independent-review/admission-pytest tests/unit/test_release_gate_compiler.py tests/unit/test_release_gate_inspection.py
/workspace/scratch/f9ac546f3a50/overnight-20260923/venv/bin/python -B /workspace/scratch/f9ac546f3a50/r3-20260924/independent-review/admission_consistency_probe.py
```

| Probe | Unanchored inspection | Original external head |
| --- | --- | --- |
| Valid control | Exit 0; eligible | Exit 0 |
| Criterion ID without executable form | Exit 0; eligible (defect) | Exit 3; mismatch |
| Failure after gate PASS | Exit 0; eligible (defect) | Exit 3; mismatch |

The declaration scanner's scoped root/quality/release metadata checks and
explicit empty-container rejection pass the focused tests. Truly absent gates
remain compatible. This review does not claim exhaustive declaration-typo
recognition, live generation, candidate behavior, OS isolation, receipt
authentication or unanchored resistance to an evidence-directory writer.

## Independent re-review after repair

Reviewed `src/pmpe/evidence/compiled_plan.py`, the retained-reader integration,
chronology checks and added regression controls at the final revision above.
The reader reuses `compile_acceptance_plan` to reconstruct exact plan semantics.
It materializes only safe, blob-bound retained test files in a temporary
directory; it does not execute them or assume the default template. Absolute,
parent, alias, drive-qualified and control-character paths are rejected before
materialization. Custom actions, measures, human tests and template proofs
retain positive controls. Registered names remain normalization inputs, not
authenticated proof of a historical registry.

The chronology repair rejects contradictory run events after the PASS gate
event and checks its attempt against the latest preceding verification start.
The external-head comparison still rejects the original-head mismatch before
eligibility. These are internal-consistency checks; the existing unanchored
forgery limitation remains.

Independently reran the exact fault-injection probe and this focused suite from
the admission checkout:

```sh
PYTHONPATH=src /workspace/scratch/f9ac546f3a50/overnight-20260923/venv/bin/python -B -m pytest -o addopts='' -q -p no:cacheprovider --basetemp=/workspace/scratch/f9ac546f3a50/r3-20260924/independent-review/admission-recheck tests/unit/test_release_gate_compiler.py tests/unit/test_release_gate_inspection.py
/workspace/scratch/f9ac546f3a50/overnight-20260923/venv/bin/python -B /workspace/scratch/f9ac546f3a50/r3-20260924/independent-review/admission_consistency_probe.py
```

Observed: **88 passed in 1.22 seconds**. The valid probe remains exit 0 and
eligible; both inconsistent probes are exit 3, `EVIDENCE_INVALID`, with no
eligibility claim. Each mutated fixture also remains rejected by its original
external head. No candidate or provider was executed by this re-review.

The implementer's broader suite was not independently rerun here; no result
from it is claimed as independent evidence. Commit `1cb8208` was also inspected:
it replaces dynamic generated-proof execution with a static import and
documents package-root test discovery. No remaining material issue was found
in the reviewed admission/inspection changes.
