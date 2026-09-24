# R3 typed process gates — unapproved task-store v2 migration

This is an executable **DRAFT**, not owner approval, fresh generation, isolation certification,
or release eligibility. Frozen v1 artifacts, evaluator, criteria, golden cases and historical
DEMONSTRATED result were not changed. The old v1 contract remains unbound on the strict compiler.

## Concrete result

`task-store-v2-draft/contract.draft.json` is produced by the existing
`build_contract_draft` publisher from `publisher-input.proposed.json`. The publisher's
`DRAFT_READY_FOR_APPROVAL` means structurally complete input; it does not confer approval.
`publisher-result.json` retains the new source/draft digests and source map.
The updated input changes only the proposed version/ID and binary-gate bindings.
Original AC/FR/golden/guardrail values are checked for equality in the builder.

| Gate | Retained offline result | Evidence and limit |
| --- | --- | --- |
| GATE-001 | PASS | All 14 unchanged candidate criteria passed. |
| GATE-002 | PASS | Baseline failed by assertion; persistence mutant failed 10 criteria and filtering mutant failed 2, all by assertions; each changes product.py only. |
| GATE-003 | NOT_EVALUATED | Source checks passed with 117 complete observations. No new outer owner-approved packet exists. |
| GATE-004 | NOT_EVALUATED | Explicit retained replay provider; zero fresh model calls. |
| GATE-005 | PASS | Actual uid, exact sandbox/delegate source identity, profile-bound fallback limitations, unsigned/forgeable receipt limits and historical blocked sandbox leg are disclosed. |

The runtime ends **HALTED**, with no release_ready event. There are 56 recorded processes:
14 baseline, 14 candidate, and 14 for each mutant. Records have explicit run, phase, attempt,
criterion and process identities; requested/executed argv, environment, exit code, and retained
stdout/stderr observations. Output blobs encode the sandbox API's text observations as UTF-8;
no separate raw binary subprocess-stream claim is made. The historical sidecar labels are
non-authoritative; the current collector supplies the criterion identity.

`gate-evidence.json` and `replay-summary.json` are convenience projections. The complete
`retained-ledger/` contains every referenced blob and the event chain; no source blobs are
redacted or omitted. It can be copied to a fresh directory's `.pmpe` and verified with
`EvidenceLedger.open_existing(root, "draft-v2-offline-retained-replay").verify()`.
Hash-chain consistency is not a signature or independent owner authentication.

## Acyclic approval and integrity

The immutable source manifest binds the complete current `src/pmpe` inventory, current adapter,
historical adapter, evaluator/template, execution profile, original scenarios/grid/input and
original freeze manifest. The template digest covers exact tester/template bytes and registry
configuration. Sandbox identity includes delegate identity; an undeclared reporter cannot claim
isolation. Source labels reserve engine/, approval/ and protected/ to prevent overwritten checks.

The v2 publisher input and draft refer to the source-manifest digest. They are deliberately
**outside** that manifest, along with the future approved contract/receipt/plan/outer freeze.
After actual owner approval, an externally pinned outer manifest binds those later artifacts.
The runtime requires contract, receipt, reviewed draft, compiled plan, source manifest and
publisher input, verifies the input's source_digest and reconstructs the reviewed draft through
the publisher. It guards every supplied outer artifact along with sources before/after processes.
No contract contains its own outer freeze digest.

Command-after and release-before observations complete before the final gate verdict. An observed
mismatch permanently poisons the run and produces PROCESS_INTEGRITY_MISMATCH; restoring bytes
cannot authorize another model call or a later release. Before/after hashes still cannot prevent
a privileged actor from changing and restoring bytes between observations or rewriting checker
and evidence. Exact approval/freeze digests require an out-of-band trusted anchor.

## Supported invocation and after-approval recipe

The supported typed-gate entry is the Python API `run_to_release_ready` with `ProcessGateInputs`.
The existing CLI does not supply these inputs and refuses process-gate contracts before provider
or workspace effects. The committed script below is an offline migration/replay builder, not a
fresh model adapter. No new sandbox attempt or paid/live call was performed here.

1. Review the exact proposed bindings, new source/adapter manifest and publisher draft. In
   particular, the proposed G2 must-fail subsets (persistence AC-002/005/013; filtering AC-004)
   are proposals for owner review, not new owner decisions inferred by this implementation.
2. Only after actual approval, use the existing publisher to obtain the approved contract and
   receipt from this exact reviewed draft. Compile its plan with the frozen Template. Retain the
   updated publisher input, draft, approved contract, receipt, plan and source manifest as files.
3. Make an outer manifest `{"schema_version":"1","artifacts":{role:raw_sha256,...}}` for roles
   `contract`, `receipt`, `draft`, `plan`, `source_manifest`, `publisher_input`, plus any other
   approval-bound artifacts. Retain the expected raw manifest digest outside the candidate/evidence
   store. Neither this draft nor its replay creates that approval anchor.
4. Supply actual fresh-session provider identity/attestation and independently prepared intended
   mutant snapshots through the existing API. Static mutant inputs must cover exactly the
   generated candidate file inventory, preserve protected tests and satisfy every bound negative
   control; otherwise the runtime refuses or halts. This draft's retained mutants do not prove
   a future candidate's controls, and replay cannot satisfy the fresh gate.

Minimal call, after constructing the frozen `template` and an explicitly profile-bound `sandbox`:

```python
from pmpe.barebones import run_to_release_ready
from pmpe.cli.barebones_cmd import CommandModelProvider
from pmpe.process_gates import ProcessGateInputs

# All values here come from the actually approved packet/operator, not this replay.
inputs = ProcessGateInputs(
    source_manifest=source_manifest_bytes,
    source_paths=manifest_source_paths,  # includes adapter and exact delegate sources
    execution_profile=execution_profile_bytes,
    approval_freeze=outer_manifest_bytes,
    approval_freeze_expected_digest=trusted_outer_digest,
    approval_paths=outer_artifact_paths,  # six required role names above + all extra bound files
    generation_mode="fresh",
    provider_attestation={"kind": "live_model", "statement": actual_session_attestation},
    negative_controls=operator_prepared_mutant_snapshots,
    real_sandbox_leg=actual_or_explicitly_historical_sandbox_disclosure,
)
result = run_to_release_ready(
    contract=approved_contract, repository_root=run_root, workspace=fresh_empty_workspace,
    run_id=unique_run_id, template=template, candidate_sandbox=sandbox,
    provider=CommandModelProvider(actual_session_command, timeout_seconds=120),
    process_gate_inputs=inputs, approval_receipt=approved_receipt,
    approval_receipt_bytes=exact_receipt_bytes, approval_authority=expected_owner,
)
```

For this packet, add the repository's `scripts` directory to Python's import path and import
`r3_task_store_migration` to reuse `HistoricalHostExecution` and `load_historical_adapter`.
The stable module name is retained in the manifest. Its delegate is the untouched frozen
HostExecution adapter; source/path maps are retained in `source-paths.json` and may be relocated
only to identical bytes. The whole source inventory and adapter identity are checked again.
The engine records a command provider and an explicit freshness attestation; it cannot prove
that a live model was behind an arbitrary external command.

## Reproduce this offline draft

From the committed repository, using the approved source snapshots named in the task:

```sh
PYTHONPATH=src /path/to/venv/bin/python scripts/r3_task_store_migration.py \
  --packet /path/to/pmos-approved/reviews/task-tracker-v1 \
  --historical-engine /path/to/peos-proof \
  --output /new/empty/output/location --replay
```

The output directory must not exist. The original 218-artifact freeze is checked against its
fixed previously retained digest before and after replay, plus legacy per-process checks.
Historical `_verify_snapshot`/adapter verify alone is behavioral evidence, not gate proof.
This script calls the current gated runtime and deliberately halts the unapproved replay.

## Verification and chronology

Initial RED: df1fa6b; typed implementation: 7ffc934. Outer packet RED: dee0f98;
terminal-tamper RED: e2b6b0a; fix: 4caebd1. Namespace RED/fix: 3b86c89/4d0e399.
Publisher-source RED/fix: 6f5d7c3/68ae80f. Admission changes through e719157 and their closure
6a9a1ec are integrated; source serialization retains both placement checks and typed gates.
Local hashes will map to the stacked publication lineage; exact tree comparison is required.

Combined bounded checks passed 208 tests before the publisher follow-up; all 41 focused
process controls passed after it. No broad optional full suite is claimed. Retained failed
logs include a malformed SHA command invocation, a one-line lint correction, and an internal
mypy SQLite cache error; these are not counted as passes. Fresh-cache type-check, final lint,
source/execution/architecture probe, secret scan and ledger verification have separate receipts.
The full dependency/privacy composed security matrix remains a GitHub CI check.

The preliminary nonpublisher draft was superseded, explicitly labeled in
`superseded-nonpublisher-replay.json`; its omitted preliminary ledger is not offered as proof.
The final publisher-built packet and complete ledger in task-store-v2-draft are the deliverable.
