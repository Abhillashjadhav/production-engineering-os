# R4 admission: implementation and bounded evidence

This is an implementer report, not independent approval. Scope is C2-F1 through
C2-F5 only. Inspection, process-gate semantics, replay, owner approval and
delivery remain separate work packets. No frozen v1 artifact changed.

Base: `23ca4cbb4cc474fe6fe65d479029c8deb8a152cb`.
Final production source: `b87856dce869e4590f34be67b6de9e9afc9a6c4a`, tree
`96414f58f8a3374f593e9e8f68fa077c226982aa`.

| Finding | Correction | Executable proof |
| --- | --- | --- |
| C2-F1 | Reject recognized parent aliases, non-object root metadata and misplaced named parent wrappers | Parent aliases, malformed objects and nested QA/release cases; absent-gate and valid-gate-alongside variants |
| C2-F2 | Inspect immediate criterion/requirement item keys in map and array collections, plus root acceptance keys | Five placement forms, each both alone and beside a valid gate |
| C2-F3 | Bounded spelling check plus explicit quality/go-live synonyms | Named two-edit and synonym declarations cannot disappear |
| C2-F4 | Container shape distinguishes ambiguous gate fields from scalar prose | Twenty constructed payload/prose controls, plus scalar release_date follow-up |
| C2-F5 | Reject a gate ID differing from its stripped value | Leading/trailing, tab/newline and non-breaking whitespace in three supported collection forms |

The public compiler interface and compiled-plan serialization are unchanged.
Only `contracts/gate_declarations.py` and the gate-ID/duplicate-diagnostic guards
in `contracts/release_gates.py` changed in production. The helper remains the
shared admission path; no second compiler or natural-language interpreter was
added. Skill lint is not applicable: no SKILL.md changed.

## Exact finite boundary and compatibility

Recognized metadata contexts are the contract root; its `quality_assurance`,
`release` and `acceptance` objects; and immediate mapping entries of
`functional_requirements` and `acceptance_criteria` in map or array form. The
three root metadata containers must be objects when present. Misplaced known
parent wrappers with object/array values reject instead of being traversed.
Root parent names are checked after lowercasing/removing non-alphanumerics,
with one-edit matching and the explicit `qa` alias.

Gate names use the same normalization. Canonical gate names, one-edit variants
and the explicit `quality_gates`/`go_live_gates` synonyms reject in unsupported
locations even with malformed scalar values. The newly broadened two-edit
matches, generic `gate`/`gates`, and canonical-name prefixes/suffixes require an
object or array value. The finite edit matcher includes adjacent transpositions.
This preserves scalar `gate: north`, gate review notes and `release_date`.

This is not schema closure or universal typo detection. Arbitrary unknown
fields, other synonyms, scalar two-edit fields, and nested business payloads
are outside this declaration detector. Action arguments, assertion values,
product data, notes and prose are not recursively searched. Authors must use
exact supported declaration containers for executable gates. Ambiguous
container-shaped alias keys at metadata boundaries reject; this does not
establish their intended natural-language meaning.

Compatibility tightens for metadata previously ignored: non-object root
`release`/`acceptance`, parent aliases/wrappers, gate fields at the named entry
boundaries and surrounding whitespace in IDs now reject. The existing
no-gate contract and supported gate map/array forms continue to compile.
No approval, external-head trust, policy, scanner, allowlist, CI or approved
synthetic-fixture line numbers changed.

## Test-first sequence and results

1. `997147e59bdb2886a91ee2b13cfa2b56273341e4`: new tests and BAR first.
   On the original source, 56 missing rejections and three false-positive scalar
   cases failed; 23 controls passed. `red.txt` retains this run. The earlier
   `red-initial-diagnostic-expectation.txt` additionally contains six mismatched
   diagnostic-name expectations on already-rejected QA containers; those are
   not six extra defects.
2. `343d590fdbc4f8cfa8c026867eb0209c3b5e83e6`: initial narrow implementation.
   174 focused tests and 41 existing acceptance-compiler tests passed.
3. Author review identified scalar `release_date` as a new two-edit false
   positive. `40922652e13e40163d8f8cfca05af5d0c2f1e5a8` commits its RED test
   before the parent-approved predicate correction in `b87856d`. Original
   one-edit malformed-key rejection is retained.
4. Final focused run: **216 passed, exit 0** (`final-green.txt`). This includes
   83 new admission cases, 44 prior gate-compiler cases, 44 inspection cases,
   four runtime cases and 41 acceptance-compiler cases. Earlier green runs are
   historical and are not added to this total.
5. Changed-file Ruff lint/format and strict mypy (192 source files) pass. One
   import-spacing failure was corrected once; its first output is retained.
6. Full local SAST and the existing exact-source repository secret gate both
   report zero findings with unchanged protected policy. Their receipts bind
   `b87856d`; this does not claim external composed CI completion.

Reproduce using the existing development environment:

```sh
PYTHONPATH=src python -B -m pytest -q -o addopts='' tests/unit/test_release_gate_admission_boundaries.py tests/unit/test_release_gate_compiler.py tests/unit/test_release_gate_inspection.py tests/integration/test_release_gate_runtime.py tests/unit/test_acceptance_compiler.py
ruff check src/pmpe/contracts/gate_declarations.py src/pmpe/contracts/release_gates.py tests/unit/test_release_gate_admission_boundaries.py
ruff format --check src/pmpe/contracts/gate_declarations.py src/pmpe/contracts/release_gates.py tests/unit/test_release_gate_admission_boundaries.py
mypy
```

Independent review and publication belong to the coordinator. These are
offline synthetic compiler/runtime checks, not fresh generation, owner approval,
approved delivery, merge or deployment.
