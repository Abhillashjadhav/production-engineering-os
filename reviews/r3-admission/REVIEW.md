# R3 author review: declaration admission and retained gate bindings

This is author review evidence, not independent approval. Parent review and
publication remain separate. Implementation commit:
`8ba3476c5395192315477cabf8e8ab698224a737`, tree
`3a6f2a3d689c9d5656336c8dde4bedfc3ab404e9`; base
`f18395a3edb53d7c450fc87660e55b1dc1ce073b`.

PR REVIEW: F-R3-03 and the M3 consistency part of F-R3-05

LINT: N/A — no SKILL.md changed. Changed source/test Ruff checks pass.

SPEC COMPLIANCE: PASS. Declaration discovery rejects misplaced aliases,
single-edit typos and canonical-name prefixes/suffixes at root,
`quality_assurance`, and `release` metadata boundaries. It rejects empty
declared collections and preserves truly absent gates. It does not recursively
interpret arbitrary application data or prose. Both recognized containers
remain supported; a valid gate cannot hide another misplaced declaration.

NOVELTY: PASS. Reuses the compiler, ledger reader and existing optional expected
head mechanism. No signing system, dependency or second evaluator is added.

HARD RULES: PASS. Status/evidence/inspect and the support-package candidate
reader validate declared gates against the retained plan, explicit PASS
criterion results, gate payload blob, latest gate event and released candidate.
Missing/failed/inconsistent records raise EVIDENCE_INVALID before eligibility.
The shared helper uses the caller's existing ledger read limits. Contract
approval/authentication semantics are unchanged.

TESTABILITY: PASS.

| Check | Observed result |
| --- | --- |
| Initial declaration regressions before code | 17 failures; positive controls pass |
| Initial reader regressions before code | 18 failures; 2 positive controls pass |
| Additional suffix/compiled-criterion cases | 6 failures before their correction |
| Final compiler/runtime/CLI/support-package suite | 188 passed |
| Final strict mypy | 191 source files pass |
| Changed-file Ruff format/check | PASS |
| New executable source and review-script static scan | Zero findings |
| Security policy/scanner/CI diff against base | Empty |
| Actual runtime/M3 probe | PASS; retained in probe-results.txt |

Tests precede implementation: `6f6b6d7` before `aef0303`; `685d724` and the
additional cases in `ce35a62` before `8ba3476`. Parent-requested alias additions
precede `f8b09d3`. Each seeded failure passed after its first correction.
The first broad compatibility run found an existing no-gate comparison's error
message being preempted. Moving gate-specific subject validation after the
absent-gate branch restored that path; the second broad run passed. Both logs
are retained. The runtime probe initially reused stale contract/draft receipt
identities; one fixture-only correction bound its new TEST-ONLY contract and
passed. Its initial error is also retained. No acceptance or security check was
weakened to make a test pass.

BLOAT: PASS. Declaration placement and evidence reading live in separate small
helpers. Compiler and consumer changes are narrow calls into those helpers.

VERDICT: READY FOR INDEPENDENT REVIEW

Required parent checks: inspect the shared reader; rerun the retained probe;
combine the parallel typed process-gate serializer using its `as_dict()` method.
The reader compares canonical serialized gate shapes so tuple/list JSON
normalization does not alter the AC-only format. Process results are checked
for matching binding, PASS, nonempty evidence and envelope identity; this
reader does not re-execute process collectors.

## Reproduction and limits

```sh
PYTHONPATH=src python -m pytest -q tests/unit/test_release_gate_compiler.py tests/unit/test_release_gate_inspection.py tests/integration/test_release_gate_runtime.py tests/integration/test_barebones_cli.py tests/unit/test_support_package_v1.py
python reviews/r3-admission/probe.py
mypy
```

The probe runs a fixed TEST-ONLY provider through the real current runner,
then substitutes the terminal gate blob and reconstructs a valid ledger chain.
Inspection rejects that M3 mismatch without an external anchor. Supplying the
original head through `--expected-head-digest` separately rejects the rewritten
chain. The fixture issuer is not a product owner and the local execution seam
does not prove OS isolation or live-model behavior.

**Trust boundary:** a fully self-consistent rewrite of contract, plan, candidate,
gate outcomes and ledger remains unauthenticated without an independently
trusted expected head. Reading the expected head from the same evidence store
does not provide that trust. This patch makes no unanchored M4 forgery-prevention
claim and adds no signatures. Original frozen contracts/receipts are untouched.
