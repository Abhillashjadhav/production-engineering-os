# BAR — independent retained-evidence follow-up

Date: 2026-09-25. Scope: additive review record and a permitted final-check inventory.

1. **Does this already exist? Yes.** Reuse the R4 resume packet and prior independent review; this follow-up records their exact limits and checks their retained claims, without replacing either implementation or evidence.
2. **Is there an approved criterion or reproduced blocker? Yes.** The owner requested parallel independent work; final integrated review is still open, architecture admission failed, and two final adversarial rechecks were stopped by automatic security screening.
3. **Does this change behavior with a caller or test? No.** It adds review documentation and a data-only evidence consistency check on an isolated branch; production source, original packets, and workflows remain untouched.
4. **Does a check fail before and pass after? Yes.** `check-red.json` fails only for the absent follow-up matrix; the check was committed at `73f19ad3ffa1a2095a38dde671030ee47bde30ea` before the matrix. `check-green.json` records completed retained-byte consistency after the matrix was added. The initial auxiliary-file diagnostic is retained separately.
5. **Can this be reverted as one unit? Yes.** Every addition is confined to this review directory and its own branch.
6. **Does this add an unrequested setting, dependency or extension? No.** It uses Python's standard library and existing evidence files only.

The data-only check must not execute a candidate, planted bytecode, a forged or re-chained ledger, or a blocked probe. Passing it establishes consistency of retained review claims, not completion of blocked final tests or fresh delivery.
