# Independent gate review — 2026-09-24

PR REVIEW: executable release-gate enforcement, external-review F-01

Reviewed implementation: `91383de192b6483d721e4573d92634e8a8b645c6`, tree
`4f1bd0babc90f25ed7c5feff4ca93762d97e23fd`, against base
`dd4271b70fcb9cb5b9dd279fe516c2fe50806751`. Commit
`417b0a01f8b402890813bc93b68e23d1a5563381` adds author evidence only; source
is unchanged. This review was performed by the separate PMOS integration
reviewer, not the gate implementation author. No source edits were made.

LINT: N/A — no SKILL.md changed. `git diff --check` passed.

SPEC COMPLIANCE: PASS. The compiler supports the agreed explicit conjunction
of existing executable acceptance criteria. Duplicate, unsupported, unbound,
unknown and conflicting gate declarations fail compilation before provider
execution. No descriptions are interpreted as executable checks.

NOVELTY: PASS. This connects declared gates to the existing compiler and current
runner without new evaluators or dependencies.

HARD RULES: PASS. Gate outcomes derive from explicit criterion outcomes;
missing results remain NOT_EVALUATED. FAIL or NOT_EVALUATED blocks release.
Gate evidence binds the contract, plan and exact candidate manifest. The
positive release references the gate evidence. Original approval/receipt
semantics and historical fixtures remain unchanged.

TESTABILITY: PASS. Independently reran all 26 focused compiler/runtime tests
and the PMOS current-run handoff regression. Four additional real-runtime
probes in `adversarial_probes.py` produced the results in `results.txt`:

| Probe | Criterion outcomes | Result |
| --- | --- | --- |
| Three passing checks | PASS / PASS / PASS | Gate PASS; RELEASE_READY |
| Second assertion fails | PASS / FAIL / PASS | Gate FAIL; HALTED |
| Second execution crashes | PASS / FAIL / NOT_EVALUATED | Gate FAIL; HALTED |
| Security block | NOT_EVALUATED for all | Gate NOT_EVALUATED; HALTED |

Every probe verifies the ledger chain, exact gate payload blob, candidate
manifest and candidate source bytes. The no-gate E1 compiled plan's serialized
shape and digest also matched the unchanged pre-gate main core:
`sha256:465768d2560b7cca1c98d1c31695b4b546e5ec8bf77178f97208fc9d05bf7231`.

The initial ad hoc probe assumed the first ledger blob was the gate payload;
ledger references are sorted. The probe was corrected to compute the payload
digest and passed. This required no production correction. The saved script
contains the corrected probe; this is review evidence, not a new product test.

BLOAT: PASS. Gate parsing and outcome derivation remain in small modules; the
runtime additions are limited to explicit outcome capture and retained evidence.

VERDICT: APPROVE

Required changes before merge: none from this bounded review. Merge remains
the parent's separately controlled action; this review does not authorize it.

## Reproduce and scope

From the repository root, with its declared test dependencies installed:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m pytest -q tests/unit/test_release_gate_compiler.py tests/integration/test_release_gate_runtime.py
PYTHONDONTWRITEBYTECODE=1 python reviews/2026-09-24-independent-gate-review/adversarial_probes.py
```

These synthetic TEST-ONLY contracts and fixed providers make no live-model,
owner-approval, deployment or OS-isolation claim. The local subprocess seam is
explicit. The previously approved task-store process/evidence gates remain
unbound and blocked by the new compiler; the historical DEMONSTRATED result is
not a new current-run demonstration. No approved contracts or frozen receipts
were changed. This bounded review does not certify all PEOS behavior.
