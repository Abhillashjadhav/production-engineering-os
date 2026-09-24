# R3 follow-up: retained-plan consistency and static proof imports

Final production source: `e719157ac43de6721f572d2c1eb7467c922bb883`, tree
`b1d1f1f9b1865da895040ebb41f60630b910a4e5`. This supersedes the implementation
status in `REVIEW.md` and `evidence.json`; those files remain historical evidence
of the earlier 188-test stage. No approved contract, receipt, scanner, protected
policy, allowlist or CI definition changed.

The independent reviewer reproduced two false eligibility cases: an ID-only
compiled criterion with a recalculated plan digest, and a verification failure
inserted after the final passing gate. A further seeded case changed a
well-shaped assertion while retaining the original contract. The final reader
reconstructs the entire compiled plan using the existing compiler, compares
canonical semantics, checks the latest verification attempt, and rejects
contradictory state-changing events after the gate result. It uses retained
trusted-test bytes without executing them. Positive controls preserve explicit
custom actions, measures, human tests and template proofs after their original
source files have been removed. All retained paths are validated before any
temporary materialization, including parent/absolute/alias, control-character
and drive-qualified paths.

The full protected-policy SAST check also reproduced the CI failure: an earlier
hook moved an existing generated test loader from its exact exception location
to line 934. The correction replaces that loader with an ordinary `import app`
in the generated portable tests. It makes no scanner exception change. The
generated package-root unittest invocation passes its two reference-app tests
and produces two assertion failures for a deliberately broken app. The evidence
probe's local-source imports were moved inside its function after an additional
Ruff scan caught the old bootstrap ordering; its behavior was rerun unchanged.

## Verification

| Evidence | Observed result |
| --- | --- |
| `followup-red.txt` | Seven failures before implementation: two reader commands across three inconsistent packets, plus generated-proof security scan |
| `control-path-red.txt`, `drive-path-red.txt` | Unsafe-path cases fail before their respective corrections |
| `followup-bounded-green.txt` | 207 tests pass at the earlier follow-up stage |
| `final-bounded-green.txt` | 209 tests pass after control-character handling, before two final drive-path cases |
| `inspection-final-green.txt` | All 44 final inspection tests pass, including both added drive-path cases |
| Independent reviewer at `e719157` | 88 compiler/inspection tests pass; original malformed-plan and later-failure probes reject, control remains eligible; both findings closed |
| `followup-mypy.txt` | Strict mypy passes all 192 source files |
| `followup-ruff.txt` | Changed source/tests and evidence probe pass lint and format checks |
| `security-before.json`, `security-after.json` | Full repository SAST: one protected-policy finding before, zero after; unchanged policy digest recorded |
| `independent-probe-after.txt` | Both original inconsistency probes return EVIDENCE_INVALID; positive control remains eligible |
| `probe-followup-results.txt` | Real TEST-ONLY runner passes intact; internally inconsistent gate-blob substitution rejects without an external anchor; original trusted head rejects rewrite |

The 209-test broad run and 44-test focused run overlap; they are not a combined
253-test result. The final collected scope has 211 cases, but a single final
211-case run is not claimed. A redundant combined invocation used an incorrect
unit/integration test path and collected no tests; it contributes no evidence.
The protected-policy check here is the full local SAST component, not a claim
that the external composed CI profile has completed.

Test-first history is retained in `cbf11b4`, `ddbe885`, `9408dc0`, and `4d16a49`,
before production corrections `1cb8208` and `e719157`. Each seeded follow-up
failure passed after its first relevant correction. Independent re-review
closed both material findings at `e719157` on 2026-09-24. This author note does
not replace the reviewer's separately retained report.

Reproduction, using the repository development environment:

```sh
PYTHONPATH=src python -B -m pytest -q tests/unit/test_release_gate_compiler.py tests/unit/test_release_gate_inspection.py tests/integration/test_release_gate_runtime.py tests/integration/test_barebones_cli.py tests/unit/test_support_package_v1.py
python -B reviews/r3-admission/probe.py
mypy
```

## Compatibility and trust limits

Generated proof bytes have changed. Existing assembled support bundles remain
verifiable using their pinned prior verifier. Verification against current
source requires reassembly because the verifier checks its canonical proof
bytes. Do not mutate a frozen bundle or silently migrate it; no automatic
migration is included.

This correction establishes internal consistency, not authenticity for an
unanchored, fully self-consistent rewritten store. A separately trusted
`expected_head_digest` remains necessary to authenticate that ledger head.
Deriving action/measure registration names from the retained contract only
supports normalization; it does not authenticate a registry. Process evidence
is checked for bindings and shape here, without re-executing its collectors.
There is no claim of M4 forgery prevention, signatures, live-model reliability,
OS isolation, or synthetic approval representing product-owner approval.
