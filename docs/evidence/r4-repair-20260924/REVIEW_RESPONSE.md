# Response to the R4 review

The R4 report is substantially right. The reviewed implementation was not ready to complete or merge. This repair round preserves the historical replay proof while closing the demonstrated admission, evidence, and process-evaluation gaps. The current implementation and verification status is recorded in the sibling README; this document explains the dispositions and design choices.

| Findings | Disposition and correction |
| --- | --- |
| F-C6-1, N-1, F-C6-2 | Accept. A failed assertion can be the result of an observer-encoded crash. Bind distinct mutant snapshot digests and reject observer crash/timeout markers; preserve the real task-store positive controls. A stricter set of failed criterion IDs alone is insufficient. Revised bindings are unapproved. |
| C2-F1/F2/F3/F4/F5 | Accept the reported cases. Extend the existing finite metadata grammar to the named parents and immediate requirement/criterion keys, preserve ordinary payload values, reject whitespace gate IDs. Do not claim that edit-distance heuristics detect every possible invented field name. A full closed schema would be a separate compatibility decision. |
| C4-F1, N2/N3/N5, F-C3-2/3/4 | Accept. Reverify contract/receipt/authority/plan identities independently of gate presence and require coherent release-attempt ordering. A terminal state label alone cannot manufacture a release. |
| N1 | Accept. Retained process results require per-kind semantic validation; a nonempty evidence dictionary and matching binding digest do not suffice. |
| N4 | Accept. Python `-B` prevents cache writes, but can still read existing bytecode. Use a clean private cache namespace before engine imports and refuse unbound local bytecode/source inventory gaps. Do not delete an operator's existing files to make admission pass. |
| F-C6-3 | Accept the claim problem. Operator attestation is insufficient for mechanical freshness. Keep it explicitly `NOT_EVALUATED`, with the attestation retained as evidence. An unsigned provider-attestation file inside the same packet would not independently solve the problem. No new release-satisfying freshness mechanism is asserted. |
| F-C6-4/5/6/7 | Accept bounded class-identity consistency checks, capture the admission-validated isolation report once, disclose its self-reported nature, and preserve the original frozen inventory in the new source binding. These measures do not defend against arbitrary root/in-process code changes or prove actual OS isolation. |
| F-C3-1, C4-F2/F3/F4/F5 | Accept. PMOS derives state from the verified ledger and invokes PEOS validation, distinguishes the captured head from an independently supplied reader anchor, and cites public commits. The genuine original-head rewrite case is a required regression. |
| F-C5-1/2/3 | Accept. Add top-level `approval_verified: false`, compare receipt JSON without Python's integer/float aliases, and state that approval is a carried declaration. AIPM's `VERIFIED` remains an integrity verdict. |
| R-02/R-03 | Accept. The historical checker now reconstructs inventories and criterion outcomes from pinned sources, rejects failed observers and inconsistent findings, derives mismatch totals, and uses explicit failures that survive `python -O`. |
| C7-01/C7-02 | Accept. Publish/map exact historical source trees, distinguish local test-head provenance from public review pins, and choose a stable contract ID before presenting the revised draft for approval. |
| R-01 | Accept the historical limit. A later checker cannot prove which engine the original process imported. Its output explicitly preserves that limitation. Current migration source/runtime identity is a separate check. Frozen historical runner bytes are unchanged. |
| R-04 | Historical commits are pinned and resolvable, but off main. No merge or repository-protection change is implied. Reference protection needs a separate repository-administration decision. |
| H-1 | Agree with the hygiene correction. Tracked cleanliness is distinct from ignored build artifacts. Verification uses archive copies or clean cache settings and reports which artifacts it creates. |

Two implementation details need care beyond the suggested edits. First, the exact ordering must respect the existing support-package producer, which has its own contract and receipt schema; it must use its own complete validation path, not an ungated bypass in the barebones validator. Second, admission rules must preserve ordinary metadata such as a scalar `release_date`, not just the 20 original application-data controls.

F-03 remains open until a revised approved contract actually completes on the current engine with adequate evidence of fresh generation. Historical replay and a draft migration do not close it. F-09 remains the owner's choice between the existing monitoring system and an observation-plane migration; neither is removed here. The career-assistant product remains outside this repair.

No owner approval, paid/provider call, merge or deployment is part of this repair round. The four verdicts remain separate: source correctness; retained replay proof; fresh approved delivery; and merge status.
