# Independent R4 verification: completed work and remaining limits

Date: 2026-09-24. Reviewer: `/root/pmos_skill_forward_check`, separate from the
implementation owners. This is a record of completed checks, not approval of
the final integrated source or a product delivery.

**Disposition: independent verification is incomplete.** The completed checks
below reproduce the R3 failures and confirm several R4 repairs. They also
confirmed two residual issues at the tested intermediate revisions: retained
negative-control context was not bound to the enclosing release, and active
external bytecode caches escaped admission. Implementers subsequently reported
repairs, but their final revisions were not independently rechecked.

The coordinator instructed this reviewer to stop all adversarial execution
because automatic security screening had stopped further testing. No blocked
test was retried or rephrased. This report was consolidated from existing
observations and outputs. Final context-binding and external-prefix tampering
rechecks are **NOT COMPLETED due to automatic screening**.

## Authority and boundaries

Read the complete supplied R4 review at
`upload/Pasted markdown(20260924-162913).md` and the shared
`r4-20260924/peos-proof/docs/evidence/r4-repair-20260924/WORK_CONTRACT.md`.
All probe source, disposable archives, copied evidence and outputs were written
under `r4-20260924/independent-review/`. No repair worktree implementation was
edited, no commit was made, and no publication, merge, deployment, live model,
paid API, owner approval or sandbox retry was performed by this reviewer.

Retained-reader and replay-checker checks only read and mutate private copies
of evidence. Task-store and freshness probes additionally executed local,
deterministic TEST-ONLY fixture programs in private workspaces. A real
`CommandModelProvider` class was exercised with a local stdin/stdout replay
program; it did not contact a model service. These fixture runs are not fresh
approved delivery.

## Exact independently examined source identities

| Scope | Commit | Tree | Status |
| --- | --- | --- | --- |
| R3 baseline archive | `fd367478ac42f3d876393c1782379bd9a9c09579` | `db2b29b173aaec89cec5fb43688419fc9f96aef2` | Independent reproductions completed |
| Initial R4 admission | `343d590fdbc4f8cfa8c026867eb0209c3b5e83e6` | `7e0f8ed2b0bf985fa5464979367fcf4ea4cdbea2` | 32 independent rows completed |
| Final admission source | `b87856dce869e4590f34be67b6de9e9afc9a6c4a` | `96414f58f8a3374f593e9e8f68fa077c226982aa` | 34 independent rows completed |
| R4 retained reader | `7a9abc139acb0a4441902d0c57c52d19e99f242c` | `8890ad89fdf278f9437c129f95b606b0e51e90be` | Independent reader checks completed |
| R4 process runtime | `1589230b912406914bb430810956a4d18e58731b` | `2178920291d59dc9cc098d8a0af87e585812d8a2` | Independent runtime checks completed; residual context/cache issues found |

Archive metadata is retained in `baseline-source.json`, `admission-source.json`,
`admission-final-source.json`, `inspection-source.json` and
`process-source.json`. Admission, reader and process probes imported from these
archives with `-B`; the bytecode probes deliberately planted caches only in
further disposable copies. The replay checker used the coordinator's explicitly
supplied historical source tree and an empty private cache prefix.

Later reader source
`00a4d48c8bea4dd1edf11271bc4874be09f936c7`, tree
`68d0c3f576da8e99820f31804aaeb83afd1cb499`, and process context repair
`0bba24f` were **IMPLEMENTER-REPORTED, not independently rechecked**. The final
external-cache repair had not been independently tested. Compiler evidence
head `108ebb280b938f676d0c8bf622d087ab992417ab` was reported to leave source
unchanged from the independently checked `b87856d`; no additional independent
suite result is claimed for that evidence-only head.

## Completed outcomes

### Compiler admission

At final admission source, **34 custom rows met their expected outcomes**:
24 malformed or misplaced declarations were rejected and 10 preserving
controls compiled. Covered the reported parent aliases, non-object metadata
containers, criterion/requirement/root-acceptance placement, nested
`quality_assurance.release`, misplaced gates beside a valid gate, two-edit
container aliases, explicit synonyms and whitespace gate IDs.

Preserving controls included ordinary ungated contracts, native and canonical
gate declarations, scalar prose and business payload keys inside action
arguments. The follow-up scalar `release_date` control compiles, while the
one-edit malformed `release_gate: null` declaration still rejects. This
supports the documented finite grammar; it is not a claim that every arbitrary
unknown wrapper or natural-language synonym is recognized.

Evidence: `admission-after/results.json`, `admission-final/results.json` and
`admission_probe.py`.

### Retained inspection and trusted-head limits

The independent 13-row probe used its own synthetic full receipt,
`coder_completed` and `verification_started` records. It invoked `status`,
`evidence` and `inspect` without a head, then checked `inspect` against the
genuine original head.

At the R3 baseline, nine internal contradictions were accepted without a head:
authority/receipt mismatch; deleted contract gate key; ungated subject mismatch;
ungated failure followed by release; earlier same-attempt gate FAIL followed
by PASS, with and without a separate failure event; unknown intervening event;
missing verification start; and coder/start attempt mismatch. An appended
`operator_override` with READY state also misled `status`, although `inspect`
already rejected it. The genuine original head rejected every rewrite.

At reader `7a9abc`, all ten malformed cases rejected across all three commands.
Coherent gated and ungated controls remained inspectable. A fully consistent
candidate rewrite remained accepted without an external head and rejected
against the original head, preserving the disclosed unsigned-evidence limit.

Evidence: `inspection-before/results.json`, `inspection-after/results.json`
and `inspection_probe.py`.

### Actual task-store negative-control semantics

The private runtime probe read the exact frozen observer/template, original
retained product and original mutants. It used only GATE-001/002 fixture
bindings and an unapproved TEST-ONLY direct-call contract. A mechanical fixture
`RELEASE_READY` therefore does not imply approved release eligibility.

At the R3 baseline, retained mutants, targeted crashes, arbitrary crashes and
the same snapshot in both mutant slots all produced GATE-002 PASS. The targeted
crashes failed exactly the same ten persistence criteria and two filtering
criteria as the legitimate mutants, reproducing why an exact failure-set check
alone would not repair the defect.

At process `1589230`, all seven focused rows behaved as intended:

| Row | Observed result |
| --- | --- |
| Original retained mutants | GATE-002 PASS; 56 observer processes; no mutant crash markers |
| Targeted-path crashes | GATE-002 FAIL; same intended 10/2 failed criteria; 9/2 marker-bearing mutant observations |
| Arbitrary crashes | GATE-002 FAIL |
| Missing prerequisite | GATE-002 FAIL |
| Explicit exit | GATE-002 FAIL |
| Identical snapshot in both slots | Compilation refused before provider invocation |
| Snapshot replaced after digest binding | Admission refused before provider invocation |

The intentionally broken baseline retained 13 marker-bearing observations;
these did not wrongly invalidate the legitimate negative-control case. Each
executed row recorded 56 observer processes. Identity-rejection rows recorded
zero provider invocations and zero observer processes.

Evidence: `task-store-before-resolved/results.json`,
`task-store-after/results.json`, per-case `observer-processes.json`, and
`task_store_probe.py`.

### Freshness, class identity and bytecode

At the R3 baseline, an actual command provider replaying local bytes with
`fresh/live_model` labels produced GATE-004 PASS, as did a class spoofing the
command provider's module/qualified name. Honest replay stayed NOT_EVALUATED.
At `1589230`, both honest and mislabeled local-command replay stayed
NOT_EVALUATED/HALTED, and the spoofed provider class was refused at admission.

Valid timestamp caches planted in private engine and adapter copies loaded
under `-B` while their `.py` bytes stayed unchanged. At the R3 baseline both
were admitted; at `1589230` source-root caches were refused. A clean control
remained admitted.

**Residual N4 variant reproduced at `1589230`:** putting the same valid caches
under the interpreter's active external `PYTHONPYCACHEPREFIX` loaded the cache
payload and still allowed inventory admission for both engine and adapter.
This was sent to the process implementer. The later active-cache-path repair
was not independently rechecked before screening stopped testing.

Evidence: `freshness-before/results.json`, `freshness-after/results.json`,
`bytecode-before/results.json`, `bytecode-after/results.json`,
`bytecode-active-prefix/results.json`, `freshness_probe.py` and
`bytecode_probe.py`.

### Additional retained process context gap

A diagnostic composition loaded reader `7a9abc` with process/compiler
`1589230`, over copied evidence from the actual completed local task-store
control. This composition is explicitly **not** a published combined tree.
The unmodified control passed with and without its genuine original head.

Two re-chained mutations were accepted without a head: changing only a mutant
control's `candidate_digest` to another valid manifest, or changing only its
`plan_digest`, while leaving the enclosing release candidate and plan intact.
Both rejected with the genuine original head. Contradictory reasons and a
mutant stdout crash marker correctly rejected without a head. These results
confirm an internal context-binding gap, separate from the fully consistent
unsigned-rewrite limit.

Source inspection also found that the outer-freeze validator did not compare
its retained contract/receipt/plan identities with the enclosing release.
That related G3 issue was **SOURCE-ONLY** in this independent review; no
independent G3 mutation reproduction was completed. Implementers accepted the
context findings and reported a repair, but final rechecks are incomplete.

Evidence: `process-context-before-clean-control/results.json` and
`process_context_probe.py`. The earlier `process-context-before/` run
canonicalized the positive control's gate blob and therefore changed its head;
the corrected run preserves that control byte-for-byte and is the authoritative
positive-head check.

### Historical replay checker

Read the coordinator's complete checker and test implementation. Independently
ran the supplied seven unittest cases: **7 passed in 2.439 seconds**. Those
include all three original replay cases and rejection of optimized-interpreter
truncation, process crash, invented inventories, swapped stdout, forged
criterion status and observer markers.

An additional seven-row data-only probe ran the checker under `-O` throughout:
the retained positive passed; altered action target, arguments, boolean count,
reported mismatch, duplicate criterion and timeout marker each exited 1.
The positive reported 30 boundaries, 14 process records, 218 matching frozen
source entries and zero mismatches. No historical candidate was executed by
this checker review. The checker explicitly labels historical runtime
authentication as NOT_ESTABLISHED_BY_RETAINED_PACKET.

These checks ran against the then-uncommitted checker at
`peos-proof/docs/evidence/r3-repair-20260924/check_replay_complete.py`.
The coordinator subsequently reported commit `438babc` with formatting-only
changes. The final committed bytes were not independently rerun or hash-pinned
by this reviewer. Evidence: `replay-checker-independent/results.json` and
`replay_checker_probe.py`.

## Commands and reproducibility limits

All probe commands used
`/workspace/scratch/f9ac546f3a50/overnight-20260923/venv/bin/python -B`
from `/workspace/scratch/f9ac546f3a50/r4-20260924/independent-review`, followed
by these arguments. These are records of completed work, not instructions to
resume the stopped testing.

```text
inspection_probe.py --source baseline-source --output inspection-before
inspection_probe.py --source inspection-source --output inspection-after --expect-fixed
admission_probe.py --source admission-source --output admission-after
admission_probe.py --source admission-final-source --output admission-final
task_store_probe.py --source baseline-source --packet /workspace/scratch/f9ac546f3a50/integration-20260924/pmos-approved/reviews/task-tracker-v1 --historical /workspace/scratch/f9ac546f3a50/integration-20260924/peos-proof --output task-store-before-resolved --legacy-bindings --cases control local_crash crash same_snapshot
task_store_probe.py --source process-source --packet /workspace/scratch/f9ac546f3a50/integration-20260924/pmos-approved/reviews/task-tracker-v1 --historical /workspace/scratch/f9ac546f3a50/integration-20260924/peos-proof --output task-store-after
freshness_probe.py --source baseline-source --output freshness-before
freshness_probe.py --source process-source --output freshness-after --expect-fixed
bytecode_probe.py --source baseline-source --output bytecode-before
bytecode_probe.py --source process-source --output bytecode-after --expect-fixed
bytecode_probe.py --source process-source --output bytecode-active-prefix --expect-fixed
process_context_probe.py --runtime-source process-source --reader-source inspection-source --packet task-store-after/control --output process-context-before-clean-control
replay_checker_probe.py --repo /workspace/scratch/f9ac546f3a50/r4-20260924/peos-proof --packet /workspace/scratch/f9ac546f3a50/integration-20260924/pmos-approved/reviews/task-tracker-v1 --output replay-checker-independent
```

The replay unittest command ran from `r4-20260924/peos-proof`:

```sh
R4_REPLAY_PACKET=/workspace/scratch/f9ac546f3a50/integration-20260924/pmos-approved/reviews/task-tracker-v1 /workspace/scratch/f9ac546f3a50/overnight-20260923/venv/bin/python -B docs/evidence/r4-repair-20260924/test_replay_checker.py
```

Probe scripts were extended between runs; each retained result directory
describes the actual rows executed. In particular, the initial bytecode runs
had three rows; external-prefix rows were added for the five-row residual
probe. The first task-store harness used a relative workspace and was
interrupted before baseline execution; the subsequent absolute-path run is
the completed result. No failed or interrupted harness attempt is counted as
a successful verification.

## What remains unverified

- Final integrated source, final context-binding repair and final external
  cache repair, including their interaction.
- Final PMOS and AIPM repair branches; their workers' results are not this
  reviewer's independently reproduced evidence.
- Final publication mappings, remote SHAs, remote CI and merge/draft flags.
- Fresh owner-approved delivery, independent provider freshness, additional OS
  sandbox isolation, and owner authentication by unsigned receipts.

Source correctness, historical replay consistency, fresh approved delivery
and merge status remain separate. Completed fixture checks establish none of
the latter two. This report does not close the final integration review.
