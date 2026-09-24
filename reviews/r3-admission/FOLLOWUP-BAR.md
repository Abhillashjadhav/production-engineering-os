# Follow-up: full static gate and independent consistency findings

Parent authorization: repair PR #211's composed static-security failure without
scanner, policy, allowlist or CI changes. Independent review additionally found
a malformed retained compiled criterion and a contradictory later failure event
could still be reported eligible. Correct both with tests first and send the
parallel migration author the late delta. No remote writes.

BAR: reuse the normal package-root unittest import mechanism, existing compiler,
ledger reader and chronology; reproduce the failures before implementation;
keep the changes independently reviewable; add no policy, signature, external
source dependency or authentication claim. The full protected-policy SAST scan
reproduced one SEC_EXEC at support_package.py:934, formerly allowlisted at line
929. The new hook shifted an existing generated test loader. Padding source
lines or changing its exception would evade the problem and is excluded.

The loader will use an ordinary static import and its generated tests must still
pass for the reference app and fail on an intentionally broken decision. The
new retained-plan check must preserve explicit custom actions, measures, human
tests and template proofs without depending on default-template assumptions or
historical files outside the retained candidate. Internal consistency is the
scope; a caller still needs an external expected head to authenticate a fully
self-consistent rewritten store.
