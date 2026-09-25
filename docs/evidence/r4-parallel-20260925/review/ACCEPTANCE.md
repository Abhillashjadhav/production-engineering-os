# Independent R4 evidence review — NOT APPROVED

Date: 2026-09-25. Reviewer: `/root/evidence_review`, separate from the architecture,
provenance and readiness workers. This follow-up checked retained bytes and inspected
source. It did not execute reviewed code, a candidate, a model, or an adversarial probe.

The resume packet accurately reports ordinary replay success and incomplete release
verification. No retained contradiction was found in the checked counts, file copies,
source identities or gate outcomes. **Source approval, fresh approved delivery and
merge readiness remain open.** The architecture workstream produced a design proposal,
not a production repair; final production source remains the earlier R4 tree.

## Acceptance matrix

| Obligation | Evidence checked in this follow-up | Disposition |
| --- | --- | --- |
| Exact source identity | All 1,316 tracked process files, 1,037 historical files and 157 packet files match their Git blobs. All 446 bound source-manifest artifacts match their SHA-256 digests. | Identity verified; this does not establish runtime correctness. |
| Complete retained archive | Archive SHA-256 matches `c5335994840a1416d7d08463b6cc48dfdff823f24471ca0936c8e76b1db88071`. Its 312 regular files exactly match the original replay excluding the documented duplicate ledger. All 295 original ledger files are present; the omitted duplicate is byte-identical. | PASS for retained archive consistency. |
| Retained task-store behavior | Stored GATE-001 has 14/14 PASS criteria. GATE-002 and GATE-005 are PASS. 56 process records divide into 14 baseline, 14 candidate and 14 for each original mutant. | RETAINED PASS; execution was not repeated by this reviewer. |
| Digest-boundary counts | Current GATE-003 contains 117 observations. The separate `historical-digest-checks.jsonl` has 114 migration/observer rows. | Both counts are consistent; they describe different collections. |
| Revised approval and freeze | Migration is `DRAFT_NOT_APPROVED`; `approval_receipt_created` is false. GATE-003 is NOT_EVALUATED because the approval packet is not bound. | BLOCKED; no new owner receipt or outer freeze. |
| Fresh generation | Zero fresh model calls. GATE-004 is NOT_EVALUATED; terminal state is HALTED. Source evaluator has no freshness PASS path, and retained validation rejects such a PASS. | BLOCKED by missing capability as well as missing fresh evidence. |
| Historical replay checker | Resume validation records the original-case method passing for all three historical cases. Prior independent report records additional earlier checks at earlier source identities. | Previously reported results remain tied to those revisions; no historical-runtime authentication claim. |
| PMOS handoff | Raw summary matches retained outcomes: positive RELEASE_READY, broken candidate HALTED, unbound gate CONTRACT_BLOCKED with zero execution calls. | RETAINED ordinary fixture PASS; no product-owner approval. |
| Static source gates | Existing report records zero SAST and secret findings but architecture FAIL on `core -> unresolved_dynamic`. | Architecture remains FAIL. Lint, formatting and typing claims were read, not rerun here. |
| Final context-binding recheck | Prior independent review explicitly records screening-stopped final verification. | UNVERIFIED; no substituted test or inferred PASS. |
| Final external-cache recheck | Prior independent review explicitly records screening-stopped final verification. | UNVERIFIED; benign metadata fixtures and static review do not close it. |
| Final integration, remote CI, merge | Existing handoff records review-only publication and unchanged PR heads. This workstream made no remote queries or writes. | NOT APPROVED; remote current state is for the coordinator to verify. |

The process archive contains four post-check Ruff metadata files outside `src`.
They are fully listed in `check-green.json`; no extra Python or bytecode files and
no tracked-file differences were found. Accordingly, the claim is exact tracked-source
identity, not that the entire scratch directory has no auxiliary files.

## Exact identities

| Scope | Local commit | Tree |
| --- | --- | --- |
| Process source inspected | `c67716638731ba3be4ceeab20be6e6fdee631fd3` | `872e53b7cb05bace2d825dca47ea7e27f78c7cf0` |
| Historical archive | `4d4a9afdc8a5a75b28fce10499ec5ff405b1b60d` | `ab13172635a9cf4bb94bceb6e95d338523f9d922` |
| Original packet archive | `89e23a973a5813d32e8e426a525d6c61e2a9a7fd` | `cdd94b8aebe8c20c4f6e3db2cd3a045771d5cd67` |
| Resume handoff reviewed | `a56c1c4671c34dd9748c30dd10cd1d0dcd6ecfc0` | `2c46b0c1ac13119019fb14ff332f0d5807b2b548` |

The process public equivalent is `ccabeecc7346dffa7354e88c1deec53b1674428a`, as
recorded in the existing publication map. Remote identity was not re-queried here.

## Independent source assessment of the two design blockers

**Architecture: concur with the need for an execution-boundary decision.**
`reject_bytecode` in `src/pmpe/process_sources.py` combines active module metadata,
current-prefix future-cache checks and local orphan-cache checks. Its registry-wide
scan can find a helper imported under an arbitrary alias or an earlier cache prefix.
The existing root/path inputs cannot enumerate every such alias. Replacing the scan
with file-derived names or provider/sandbox names omits that information; an assertion
that a caller supplied all names does not establish completeness.

The existing migration script sets a private cache prefix before importing `pmpe`
only in its main entry. That is a useful bounded starting point, but it does not
establish a universal pre-import invariant. `run_to_release_ready` receives already
constructed providers/sandboxes, and manifest construction occurs in an already
imported interpreter. The CLI also imports its engine before parsing arguments.
No currently enforced source-only bootstrap or complete module-admission inventory
was found in these paths. Moving or renaming registry enumeration would evade the
scanner rather than resolve the architectural incompatibility.

The architecture worker's proposal therefore accurately states a compatibility
choice: support an enforced earlier source-only entry and refuse unprepared gated
direct calls, or provide a separately reviewed complete admission mechanism. Its
proposal still needs a concrete completeness argument before implementation can be
approved. This is not a proof that every possible alternative design is impossible.

**Freshness: concur that owner approval and a live command alone cannot finish.**
`generation_provenance_result` in `src/pmpe/process_evaluators.py` assigns only FAIL
or NOT_EVALUATED, always emits `freshness_verified: False`, and treats `live_model`
as an attestation. `validate_process_gate_evidence` in
`src/pmpe/evidence/process_gate_validation.py` unconditionally raises for a
`generation_provenance` PASS. The binding validator still requires fresh mode.
`CommandModelProvider` supplies a command transport; it does not add independent
freshness verification. No alternate approved freshness verifier was found.

An exact revised contract can be reviewed, but signing it does not add this missing
capability. Completion needs a reviewed freshness evidence/trust contract and its
implementation, or an explicit owner-approved change to the delivery criterion.
Labels, unsigned local logs and operator statements must not silently become proof.

## Permitted final-check inventory and dependency order

| Order | Check | Prerequisite and limit |
| --- | --- | --- |
| 1 | Review the import-boundary and freshness evidence decisions. | Concrete acceptance criteria and supported callers must be settled before a repair that changes them. |
| 2 | Inspect final diffs and exact source identity. | After code owners finish; verify protected scanner/policy and frozen v1 bytes are unchanged. |
| 3 | Run unchanged source architecture/SAST observer, secret scanner, Ruff and typing checks. | Against one exact source revision, with caches/output outside it. These can run independently after that source is fixed. |
| 4 | Run narrowly selected clean admission/ordinary fixture checks already permitted. | Inspect selected test bodies first. Benign metadata fixtures do not certify actual hostile cache execution. |
| 5 | Run the original retained task-store replay and ordinary PMOS handoff. | Bind to final exact source and separate output directories; regenerate the draft/manifest only after dependencies are ready. This remains replay, not fresh delivery. |
| 6 | Recheck only `ReplayCheckerRegression.test_original_cases_pass` if checker evidence needs refreshing. | Original historical files, explicit historical source and packet, no mutation cases. |
| 7 | Review final retained outcomes and publication mappings. | Retain source correctness, historical consistency, fresh delivery and merge as separate verdicts. |
| 8 | Request approval for the exact revised delivery contract after readiness blockers are addressed. | Only then bind a genuine receipt/outer freeze and attempt an authorized fresh delivery using the approved freshness mechanism. |

The planted-bytecode execution and forged/re-chained release-ledger context probes
remain stopped by automatic security screening. Do not run their equivalents, a
whole suite containing them, or remote CI as a substitute. These exclusions are
verification limits, not permission to report a final PASS. No broad test suite is
needed for this documentation-only follow-up.

## Reproduction of this review check

`check_retained_review.py` uses Python's standard library to read files, archive
members and Git metadata. It never imports reviewed source, executes retained
commands, or modifies evidence. Supply the resume root and original repositories:

```sh
python3 -B docs/evidence/r4-parallel-20260925/review/check_retained_review.py \
  --resume-root /workspace/scratch/b6efdedb2992/pmos-r4-resume \
  --process-repo /workspace/scratch/f9ac546f3a50/r4-20260924/peos-process \
  --historical-repo /workspace/scratch/f9ac546f3a50/integration-20260924/peos-proof \
  --packet-repo /workspace/scratch/f9ac546f3a50/integration-20260924/pmos-approved
```

The initial diagnostic incorrectly required no auxiliary files in the process
directory; it exposed the disclosed Ruff metadata. After narrowing the claim to
tracked bytes and extra executable/source files, `check-red.json` failed solely
because this matrix was absent. That check was committed before this document.
`check-green.json` records the completed data-only consistency check. Its PASS
approves neither the production source nor the still-unverified final probes.
