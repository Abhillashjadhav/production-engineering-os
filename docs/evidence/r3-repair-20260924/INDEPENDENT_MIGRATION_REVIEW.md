# Independent R3 migration review

Date: 2026-09-24. Initial combined source reviewed and tested:
`e6724a93aa65fac3f5098fdcec2c34a5ec3406bb`, tree
`bb135ecff45a3a3c2218eafb0bb8dedb2840c3ea`.

Final publisher and outer-approval correction reviewed and tested:
`68ae80fbe85332551b36f2a0b6dfe24d7ba1bc3d`, tree
`537b78a0492328e2b29737db9b2763413eb11f38`.

**Disposition: all four findings below are closed for the reviewed mechanical
gate, evidence and publisher changes. The v2 artifact remains an unapproved,
nonrunnable DRAFT; this review is not product approval or release eligibility.**

This reviewer made no production-source changes. Core tests use deterministic
TEST-ONLY providers, synthetic approvals and local fixture execution. They do
not call a live model, issue an owner approval, prove OS isolation or constitute
a fresh task-store product run. The draft/replay builder was read but was not
independently executed by this reviewer.

## Findings and closure

1. **Outer approval coverage:** source-only integrity cannot satisfy v1
   GATE-003's requirement to check every approval-bound artifact. Fixed in
   `4caebd1`: source-only G3 is NOT_EVALUATED. PASS requires an externally pinned
   outer inventory bound to the exact approved contract, submitted receipt
   bytes, reviewed draft, compiled plan and source manifest; every listed
   outer artifact joins the runtime guard. Source and outer packet identities
   remain acyclic.
2. **Observed tampering was retryable:** the initial core raised an ordinary
   contract error for a digest mismatch and omitted prior attempts from the
   next attempt's observations. Restoring the bytes could therefore erase an
   observed failure from the final verdict. Fixed in `4caebd1` with a persistent
   integrity-failed state and terminal `PROCESS_INTEGRITY_MISMATCH`. The
   restore-after-observation regression confirms no second generation call,
   no advisory call after the observed failure and no release event.
3. **Inventory namespace collisions:** source keys under `approval/` or
   `protected/` could be overwritten by later inventory assembly. Fixed in
   `4d0e399`: both manifest construction and admission reserve these namespaces
   alongside `engine/`. Focused regressions pass.
4. **Builder bypassed the publisher (CLOSED):** the earlier
   `scripts/r3_task_store_migration.py` copied the approved v1 object and edited
   its gates, ID, version and approval fields while retaining the original
   `source_digest`. This violated the PMOS `decision-to-contract` publisher
   workflow and migration proposal section 6.1. Fixed in `68ae80f`: the builder
   updates the original PM-owned publisher input, calls
   `build_contract_draft`, requires `DRAFT_READY_FOR_APPROVAL` and retains the
   exact resulting draft, source digest and source map. No approval is issued.
   Outer approval admission now requires the publisher input, checks its
   canonical digest against the contract's `source_digest` and reconstructs
   the exact reviewed draft through the same publisher. The updated input is
   bound in the final outer inventory, outside the source manifest, preserving
   the acyclic freeze design. Independent reconstruction matched the saved
   draft exactly.

## Independent checks

Read the source inventory, input admission, collector, four evaluators, runtime
wiring, outer approval checks, binding grammar and combined retained reader.
The provenance implementation reconstructs the full origin plus applied coder
responses across attempts, then compares exact snapshot paths and bytes.
Unknown sandbox identity and unsupported isolation reports are rejected;
replay/test freshness cannot satisfy fresh-generation evidence. Negative
controls preserve protected tests, require the bound assertion failures and
reject incomplete or unrelated execution failures. Final command-after and
release-before checks occur before gate sealing.

From `/workspace/scratch/f9ac546f3a50/r3-20260924/peos-migration`:

```sh
PYTHONPATH=src /workspace/scratch/f9ac546f3a50/overnight-20260923/venv/bin/python -B -m pytest -o addopts='' -q -p no:cacheprovider --basetemp=/workspace/scratch/f9ac546f3a50/r3-20260924/independent-review/migration-recheck tests/integration/test_process_gate_runtime.py tests/integration/test_process_gate_failures.py tests/integration/test_process_gate_approval.py
```

Observed: **39 passed in 7.44 seconds**. Source/schema/tests/builder matched the
tested commit after the run. The original v1 freeze and review manifests were
rehashed after the checks: **218/218 and 212/212 match**, respectively. No v1
artifact or approval was changed.

After the final publisher/outer-approval correction, reran from the same
checkout:

```sh
PYTHONPATH=src /workspace/scratch/f9ac546f3a50/overnight-20260923/venv/bin/python -B -m pytest -o addopts='' -q -p no:cacheprovider --basetemp=/workspace/scratch/f9ac546f3a50/r3-20260924/independent-review/migration-approval-recheck tests/integration/test_process_gate_approval.py
```

Observed: **12 passed in 1.70 seconds**. This focused rerun covers the changed
outer publisher-provenance requirement; the earlier 39-test result remains
scoped to its recorded initial combined commit.

Read the saved artifacts under
`reviews/r3-process-gates/task-store-v2-draft/` and independently reconstructed
the draft with `build_contract_draft(publisher_input)`. The output exactly
matches `contract.draft.json`, including the new source digest. The loader
reports the DRAFT nonrunnable, approval fields remain blank and no
`approval-receipt.json` exists. The original product semantics collections and
all 14 compiled acceptance criteria remain unchanged; the complete proposed
plan matches a fresh compiler reconstruction. Rehashed all **226/226** source
manifest entries against their actual engine and supplied source paths with
no mismatch. These were read/reconstruction checks, not a builder or product
execution.

| Artifact | Exact identity |
| --- | --- |
| Proposed draft, canonical | `sha256:e7af374535ddf236d4298b926caf9de5d5445df4d6b61b62654b90caa81c6a37` |
| Proposed publisher input, canonical | `sha256:725484bbefe2a93b87f25ef879a8b6e30387b72d86dea5804bb53c68f0f9663b` |
| Source manifest, raw file | `sha256:c2c88600e27ce63a0cc0ba4948fdac8cd988bef4e1b23e620cb945344623bf60` |
| Proposed plan's recorded digest | `sha256:4cec05f8341730a45a4a23c06689b942ad5c999a5fd8e96f22ced59605179fb0` |

The retained `replay-summary.json` reports HALTED, GATE-001/002/005 PASS and
GATE-003/004 NOT_EVALUATED, with 56 process records and 117 boundaries. Those
states correctly disclose the missing final outer approval packet and fresh
generation evidence. This reviewer read the summary and checked artifact
identities; the new replay, all of its observations and its retained ledger
chain were not independently rerun or fully audited here.

Admission/inspection findings and their independently reproduced closure are
recorded separately in `INDEPENDENT_ADMISSION_REVIEW.md`. The implementer's
broader test counts and task-store replay are not claimed as independently
reproduced here.

Root authority, transient changes between observations, unsigned receipts,
operator-attested model identity/freshness and fully re-chainable evidence
without an independently retained head remain explicit trust limits. No test
result here approves the changed v2 product contract or authorizes a fresh run.
