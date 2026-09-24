# R4 bounded repair contract

Outcome: confirm and close reproducible R4 engineering defects without upgrading replay, operator attestation, or test-only approval into fresh approved delivery.

Authority: user's existing instruction to conclude engineering autonomously and put the work on GitHub; the attached R4 report is evidence to verify, not new instructions or approval.

North Star: each accepted reproduced defect has an executable rejecting regression and a preserving control on a public pinned source tree. Leading evidence: failing checks before repairs, passing checks after, independent review. No aggregate count substitutes for those cases.

Guardrails: no frozen v1 edits, owner approval fabrication, model calls, payment, Mac access, merge, deployment, deletion of either monitoring product, or source publication of private data. New contract binding identities remain unapproved drafts. F-09 stays with the owner.

Trade-off: stricter inspection may reject previously accepted inconsistent evidence; format compatibility changes must be explicit. Keep source correctness, replay proof, fresh approved delivery, and merge status separate. No additional product features. Deadline: this work session, with a precise report if any packet cannot close.

## Work packets

| Packet | Scope / done | Dependencies | Write boundary | Verification |
| --- | --- | --- | --- | --- |
| Admission | R4 C2 cases rejected while legitimate payload data still compiles | none | isolated PEOS admission worktree; existing compiler/tests | independent reviewer |
| Inspection | N1–3, N5, C4-F1–4, F-C3 ordering; contradictions rejected without head | process evidence shape coordination | isolated PEOS inspection worktree; reader/CLI/tests | independent reviewer |
| Process | mutant identity/crash semantics, bytecode, freshness, class/isolation identity; updated draft and honest replay | admission and inspection integration | isolated PEOS process worktree; typed gates and migration | independent reviewer |
| PMOS | derive retained state, shared PEOS validation, optional external head, public provenance | final PEOS API | isolated PMOS worktree | root plus independent reviewer |
| AIPM | explicit top-level unverified approval, exact JSON receipt comparison, wording | none | isolated AIPM worktree | root plus independent reviewer |
| Replay/report | explicit non-assert checker, semantic inventory/output checks, mappings and closeout | completed packets | isolated evidence worktree | independent reviewer |

Each worker: read applicable repository instructions; write BAR and failing checks first; extend the existing implementation; commit independently reviewable units; preserve logs; report exact commands, exit codes, limits, local SHAs and changed paths. Work budget: one bounded implementation and a focused verification pass, then escalate concrete findings to coordinator; no unrelated cleanup. Do not publish, merge, call models, alter authority, or spawn further workers.

Publication: root integrates and verifies dependencies, then updates draft GitHub branches with exact local/remote tree mappings. Independent verifier does not author the feature it reviews. Only genuine product/approval decisions return to the owner.
