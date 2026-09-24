# R4 admission and retained inspection integration

Implemented, not merged. This joins the independently scoped compiler, retained-reader and support-package changes in the existing #211 stack. New process bindings are in the separate #212 stack.

Root verification:

- Combined preserving/regression run: 321 passed, exit 0, at local e7e0a687aa2b3cbda6d9b33321f8bce04df0fa0a before the final process-context helper/reader change. This includes the real support producer, the previously failing CLI journey fixtures, compiler and gate-reader cases. See combined-regressions.txt; do not attribute this run to later source.
- The final context helper and reader changes were read by root at local 58ea189774cebfde02bd247963da545b7dd38367 (tree 0f29a1462ef2fcd0ebb9be2423628d4a30c000af). Candidate and plan are checked against the enclosing release; outer approval artifacts are checked against its contract, plan, receipt, draft and publisher source. This is SOURCE-ONLY root verification, not an executed tampering recheck.
- Final source Ruff check, format (200 files) and strict mypy (194 source files): exit 0, logs retained. Root PMOS handoff checks against this integrated reader before the context-only change: 13 passed, exit 0.
- Author final reader/journey/helper tests: 113 passed at 00a4d48c8bea4dd1edf11271bc4874be09f936c7. This remains AUTHOR-REPORTED; its exact commands and logs are in reviews/r4-inspection.
- Independent compiler checks passed on b87856d, and independent reader checks passed on 7a9abc. The separate reviewer then found the inner-to-outer process-context mismatch, which prompted the final change.

Automatic security screening stopped the independent reviewer during further tampering verification. The final context-binding and external-cache adversarial rechecks are BLOCKED_AUTOMATIC_SECURITY_SCREENING, not PASS. No blocked probe was rerouted to another worker. The central R4 report records completed versus unavailable evidence separately. This draft still requires review before completion or merge.

The support-package reader validates its own exact two-event protocol, validated package contract, receipt, candidate and optional original head. It does not enter a barebones no-gate bypass. The existing support-package fixture module is unchanged.

No policy/allowlist change, owner authentication, fresh model call, approved product delivery, merge or deployment is established. A consistently rewritten unsigned evidence store still needs an independently retained head to detect substitution. Public local-to-remote source mappings are retained by the central R4 publication report.
