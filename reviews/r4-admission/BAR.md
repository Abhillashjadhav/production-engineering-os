# BAR — R4 compiler admission regression unit

1. **Already exists? Yes.** Extend `validate_gate_declaration_placement` and the
   existing gate-ID validator; a parallel scanner or evaluator is excluded.
2. **Approved criterion or reproduced blocker? Yes.** Scope is exactly R4
   C2-F1/F2/F3/F4/F5, with named negative cases and preserving controls below.
3. **Changes behavior with callers/tests? Yes.** Own branch
   `repair/r4-peos-admission`; compile/retained-plan readers may reject previously
   ignored metadata. Proper declarations and business payload data must preserve
   their current behavior. No runtime evidence behavior changes in this unit.
4. **Automated before/after check? Yes.** The existing compiler entrypoint permits
   direct negative/positive regression cases. Implementation is stopped until
   the new test-only commit records the expected failures on the current source.
5. **Revertible as one unit? Yes.** Compiler helper/ID guard, standalone tests and
   their evidence are isolated from sibling inspection and process-gate work.
6. **Unrequested setting/dependency/extension? No.** Reuse existing diagnostics,
   compiler and pytest; add no runtime dependency, setting or product criterion.

The initial test unit covers recognized parent aliases and malformed objects;
criterion/requirement map and array entries plus root acceptance; bounded gate
aliases; scalar/prose false positives; whitespace IDs. Positive controls include
nested arbitrary payloads containing gate-shaped data. The implementation BAR
will reference the observed RED evidence before production files change.

## Implementation unit — unlocked by observed RED

1. **Already exists? Yes.** Extend the same metadata helper and gate-ID guard;
   no parallel checker is introduced.
2. **Required by blocker? Yes.** `red.txt` records the accepted malformed parents,
   hidden entry metadata, aliases and padded IDs, plus the false-positive scalar
   keys. Existing malformed quality-assurance controls already reject.
3. **Existing behavior changes? Yes.** The isolated compiler branch now tightens
   finite metadata boundaries and permits scalar notes formerly rejected.
   Previously ignored non-object root acceptance/release metadata will reject.
4. **Failing automated check first? Yes.** The finalized standalone suite has
   59 failing cases and 23 passing controls before source edits. The earlier log
   additionally included six diagnostic-name expectations on already-rejected
   quality-assurance cases; it is retained and does not count as six new bugs.
5. **Single-unit rollback? Yes.** Revert this packet's compiler/test commits;
   sibling process and inspection changes are independent.
6. **New unrequested surface? No.** Fixed metadata boundaries and finite aliases
   only; no configuration, external inference, dependency or product policy.

## C2-F4 follow-up — ordinary scalar release date

1. **Already exists? Yes.** Narrow the same two-edit predicate; no second filter.
2. **Required blocker? Yes.** Author probe on `343d590` confirms the new distance-2
   rule rejects ordinary scalar `release_date`, contrary to C2-F4 preservation.
3. **Existing behavior changes? Yes.** This isolated follow-up corrects that new
   rejection while keeping the pre-existing one-edit malformed-key checks.
4. **Automated RED before fix? Yes.** Add and commit a direct scalar-date compiler
   regression before changing the predicate; retain its actual failure output.
5. **Revertible? Yes.** One predicate adjustment with its regression and evidence.
6. **New unrequested surface? No.** Parent explicitly approved container shape for
   newly broadened two-edit matches only. No new keyword exception or setting.
