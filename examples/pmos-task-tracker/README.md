# PMOS task-tracker reference harness

This is PEOS's first **fixed product reference**, not a generic loader for an
arbitrary application's tests. It maps the owner-approved PMOS task-tracker
definition to PEOS's current core without editing the historical packet. The
original files in [`source/`](source/) are raw copies from PMOS commit
`2acc3fa0c81f1237f8ab7b5681b478630c530931`; the renderer checks their
SHA-256 values before it emits anything. `source/README.md` and
`source/execution-profile.json` are retained for provenance, including their
historical fallback directions. **This runner does not use that fallback.**

PMOS's [current handoff instructions](https://github.com/Abhillashjadhav/PM-agent-OS/blob/2acc3fa0c81f1237f8ab7b5681b478630c530931/docs/HANDOFF.md)
pin PEOS `297a11d79e5d1e1eda1f8f94b7bec3046c41a0d6` for a distinct,
TEST-ONLY authoring health fixture. That pin does not establish compatibility
of PMOS's historical task-tracker approval with this new mapping or the current
PEOS main branch.

## Contract and evidence boundary

The original PMOS approved contract, receipt, all 14 acceptance criteria and
five release-condition descriptions remain byte-for-byte unchanged. The new
[`mapped/contract.draft.json`](mapped/contract.draft.json) is version 2 and
remains the immutable **DRAFT** reviewed by the owner. On October 2, the owner
approved its exact canonical digest
`sha256:4f4b04110e57a641e5ed49c497dd76d89bb6474d5761d1add4c44ba94b8f8592`
in conversation. The existing publisher derived
[`approved/contract-approved.json`](approved/contract-approved.json) and
[`approved/approval-receipt.json`](approved/approval-receipt.json) without
changing the reviewed draft, mapping, 14 cases or five conditions. The receipt
is a digest-bound record of that authorization, not a cryptographic signature
or proof that any release condition passed. The historical version-1 receipt
cannot authorize the version-2 contract.

[`mapped/core-harness-mapping.json`](mapped/core-harness-mapping.json) binds:

- GATE-001 to every original AC-001 through AC-014, with no severity skip
- GATE-002 to meaningful assertion RED and regression observations
- GATE-003 to approval-bound before/after integrity checks
- GATE-004 to in-session build provenance and criterion-linked command traces
- GATE-005 to a truthful limitations and assurance report

All five conditions are required. The mapping's digest is a contract field,
and the fixed observer, wrapper and protocol-valid baseline identities are
part of that mapping. The compiler refuses a missing, changed or incomplete
mapping. It reports all five gate proofs as `NOT_ESTABLISHED`: descriptions,
compilation and a test fixture cannot prove their runtime satisfaction.

The fixed `pmos-task-tracker-v1` adapter runs each acceptance criterion with a
fresh private store. Within a criterion, every setup/step launches a fresh
sequential product CLI process, with an individual timeout and a total
observation deadline. Successful observations keep the complete command/result
sequence as a separate evidence blob. An ordinary observer error keeps its
available command/result prefix in a separate blob, explicitly marked
incomplete and classified as execution failure rather than assertion RED. AC-013
runs exactly ten sequential creates followed by
a fresh list process; a passing value needs at least ten distinct valid
acknowledgements and zero missing records. Invalid-input product results with
their expected JSON and exit codes are assertion observations. Observer,
process, setup, timeout and protocol errors are execution failures, not
meaningful assertion RED. The shipped baseline returns valid
`NOT_IMPLEMENTED` JSON; AC-013 records sample size zero and fails its minimum.

The retained task-tracker product in `tests/fixtures/` is a **test fixture**.
It is not evidence of a new in-session model build or a live authenticated
provider. The current engine still halts on provider-write isolation even if
that fixture passes all 14 product cases. GATE-002 through GATE-005 need their
own complete proof; the fixture does not substitute for any of them.

## Reproduce the bounded checks

In an installed PEOS checkout with its locked dependencies:

```bash
python examples/pmos-task-tracker/render_core_mapping.py
pmpe barebones compile examples/pmos-task-tracker/mapped/contract.draft.json \
  --template pmos-task-tracker-v1 \
  --core-harness-mapping examples/pmos-task-tracker/mapped/core-harness-mapping.json
pytest tests/integration/test_pmos_core_harness.py -q
```

The renderer must reproduce the checked-in mapped files exactly. `compile`
reports `COMPILES` and `CORE_HARNESS_PROOF_PENDING`, not run or release
eligibility. Most integration tests use a test-only issuer, provider and local
candidate sandbox; they cover the public CLI, all 14 cases, the ten-create
measurement, persistence and filtering repairs, evidence readback and a
terminal `HALTED` result. One fixture test admits the new owner-approved
contract and receipt, while still using a test-only provider and sandbox. The dedicated
Linux CI candidate-isolation matrix also selects one ordinary product UAT on
the real candidate sandbox; its result must be checked on the exact published
commit. Neither test route stands in for live provider proof. Current stage
definitions and proof requirements are in
[`docs/pipeline-health.md`](../../docs/pipeline-health.md).
