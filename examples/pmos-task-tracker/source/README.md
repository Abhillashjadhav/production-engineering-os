# Approved task-tracker handoff

Status: **DEMONSTRATED FOR THE APPROVED FEATURE under the owner-authorized fallback.**

Read [ACCEPTANCE.md](ACCEPTANCE.md) first. It contains the three approved semantic
decisions, CLI/error rules and all 14 scenarios, observation methods,
severity, the strictly sequential ten-record measurement and permanent limitations.
AC-014 is critical: a rejected blank-title create must leave ID 1 available for the
next valid task, with exactly one task stored. Creation is not idempotent;
duplicate-on-retry is approved behavior. AC-007 covers completion idempotency.
Concurrent creation is out of scope. The sandbox decision is closed: no more
Bubblewrap attempts; the documented fallback lists every absent isolation.

| Artifact | Purpose |
| --- | --- |
| `publisher-input.json` | PMOS-owned intent passed to the existing publisher. |
| `contract.draft.json` | Exact `build_contract_draft` output, with blank approval fields. |
| `scenarios.json` | Concrete commands, expected observations and severity; criterion values match the contract. |
| `evaluator.py` | Frozen CLI observer; behaviorally validated against the live product and deliberately broken copies in PEOS #203. |
| `bindings.json` | Existing `Template` fields in a declarative file; uses the shipped meaningful-red skeleton and exact observer bytes. |
| `execution-profile.json` | Before/after digest policy, resources, admitted fallback and root/receipt limitations. |
| `review-manifest.json` | Raw-file digests for seven proposal artifacts, the PMOS skill and the PEOS source/profile inputs. |
| `proposal-validation.json` | Historical proposal-stage structural validation; not the final delivery result. |
| `contract.approved.json` / `approval-receipt.json` | Frozen approved contract and the existing receipt, with the public-hash forgery limitation retained. |
| `compiled-plan.json` | Exact approved plan, recomputed and compared before verification. |
| `freeze-manifest.json` / `freeze-bundle.sha256` | Approval-time digests covering all 218 frozen artifact entries and the canonical manifest anchor. |

Draft digest:
`sha256:0684ae3efbc62aef686e36b9acc871e92451c458ed0a53bb951cebc44748fe89`.

Canonical review-bundle digest:
`sha256:fbfe73637ec326330d3107aac1d43b023fc7c5473fe3ef7dfcede7e4d07af711`.
The bundle digest uses existing RFC 8785 `canonical_digest` over the manifest;
individual file entries use SHA-256 over raw bytes. The digest records the confirmed review bundle; the owner conversation supplies
approval, not a cryptographic signature.

## Historical proposal validation

The existing publisher returned `DRAFT_READY_FOR_APPROVAL`; the canonical loader
reported DRAFT and not runnable. Six requirements map to 14 criteria, including
one `measure` with `sample.minimum: 10` and threshold zero. Default health bindings
reject the new actions/measure with `ACTION_NOT_REGISTERED` and `MEASURE_INVALID`.
The existing `Template` API compiles the proposed bindings without engine edits.
Observer syntax, exact binding bytes, requirement coverage and publisher-output
identity were checked. Ruff 0.16.4 and `git diff --check` passed.

The amendment check failed on the prior proposal and passed after the changes.
AC-001 through AC-012 retain their exact scenario values. AC-013 retains the same
measure, threshold and sample minimum; its sequential ordering is now explicit.
Only the evaluator's documentation changed; its executable AST is unchanged.

At proposal validation, no product execution, generation or approval call occurred.
The owner has now confirmed the amended grid. The existing publisher produced
contract.approved.json and approval-receipt.json; compiled-plan.json and all
218 bound file hashes are recorded in freeze-manifest.json.
The initial proposal left loading, per-check digest enforcement and behavioral
validation pending. Those steps have now completed in PEOS PR #203; see the
live evidence below. Compilation alone remains insufficient delivery evidence.
If that work changes a bound source file, obtain approval of the new bytes before
product generation; this packet cannot approve future source code.

## Reproduce the frozen approved handoff

Use the [complete pinned clone/install/journey walkthrough](https://github.com/Abhillashjadhav/production-engineering-os/blob/d800d42abafe1b40e27e1a28763c1471643c6b61/docs/evidence/task-tracker-live-20260918/REPRODUCE.md).
It checks out PEOS `02959731e06d977e9ed61cfd15c962e5ebb85ee5` and PMOS
`9d55bf650d6586d90a0028241b468559349487c3`; the frozen artifact bytes in this
README correction are unchanged. A second model build is not required by Phase 5.

Once those sibling checkouts and the standard PEOS venv exist, run from PMOS:

```bash
../peos/.venv/bin/python ../peos/examples/barebones/contract-file.py verify \
  --packet reviews/task-tracker-v1 \
  --root PM-agent-OS=. --root production-engineering-os=../peos \
  --freeze-digest sha256:1dd281e55cc20ce1861e3bed55799617191f38c5cc4e2322c7e463ef9a6e37f2 \
  --candidate ../peos/docs/evidence/task-tracker-live-20260918/live/candidate \
  --output ../approved-handoff-verification --authorized-host-fallback
```

This existing verifier loads the approved contract and receipt, recomputes and
compares the compiled plan, and checks all 218 freeze entries and the manifest
anchor before and after every authoritative execution. It then runs all 14
frozen criteria against the retained generated product. Expected: exit zero,
all criteria PASS, no findings and no digest mismatches. A stale or changed
approval-bound artifact must fail. Use a fresh output directory for each run.
The full walkthrough also runs the existing eight-command user journey.

The former inline reproduction only checked the draft and review manifest; it
could print PASS after an approved-contract replica changed. Independent review
found that documentation defect. The [before/after evidence](reproduction-closeout/validation.json)
records its reproduction and this correction. This does not change the frozen
contract, evaluator, receipt, profile or any product semantics; receipt forgery
and the owner's closed real-sandbox exception remain stated limitations.

The engine and authority findings, amended sandbox argv and fallback probe are in
[PEOS's owner-amendment record](https://github.com/Abhillashjadhav/production-engineering-os/blob/audit/task-tracker-seam/docs/evidence/task-tracker-audit-20260918/owner-amendment.md).
New actions already work through the Python API. Historical live-model evidence
already exists in PEOS and remains unverified by this run. These correct the earlier
review; neither correction establishes this task tracker's delivery.

## Freeze record

Full proposal regenerated from all 14 scenarios by `python reviews/task-tracker-v1/render-proposal.py`.
Contract, grid, evaluator and prepared manifest agreed before recording the freeze.

Canonical freeze digest: `sha256:1dd281e55cc20ce1861e3bed55799617191f38c5cc4e2322c7e463ef9a6e37f2`.
Approval source: the owner’s “Confirmed — freeze the amended grid and proceed.”
The digest snapshot includes contract, receipt, plan, grid, evaluator, bindings,
profile, renderer, review manifest and all previously bound source bytes.
The Phase 3 entry script is recorded separately as engineering evidence;
existing bound source and approved outcomes must remain unchanged.

## Completed handoff

[PEOS PR #203](https://github.com/Abhillashjadhav/production-engineering-os/pull/203)
contains the file entry, actual in-session model build, unchanged acceptance
results, meaningful baseline, two rejected behavior mutations, two rejected
tamper probes and a separate new-action fixture. The live candidate passed all
14 criteria on build attempt 1, with no manual product repair. AC-013 measured
ten distinct acknowledgements and zero missing records; AC-014 retained ID 1
after rejection. Clean installation and retained-artifact replay also passed.

[Full evidence report](https://github.com/Abhillashjadhav/production-engineering-os/blob/feat/contract-file-run/docs/evidence/task-tracker-live-20260918/REPORT.md).
The real-sandbox leg remains environment-blocked. Root authority, forgeable
receipts, active-session generation, non-idempotent create and excluded concurrency
remain limitations. No broad platform-readiness, headless generation or release
claim is made. The approved contract, grid, evaluator and freeze manifest are
unchanged by this status update.
