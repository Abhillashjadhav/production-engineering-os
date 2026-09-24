# Evidence-only security repair — attempt 1 of 2

Assigned prompt: PR #209's trusted/static security check reports SEC_EVAL at
`reviews/2026-09-24-independent-gate-review/adversarial_probes.py:86` because
the independent probe copied a planted security payload. Reuse the entire
existing `src/pmpe/demo/synthetic.py` source as the unused candidate file;
document reuse, rerun all four probes, retain before/after scan findings, and
commit evidence only. Do not change the scanner, allowlist, policy, runtime
source or approved contracts. No remote writes.

Before modification, the local repository scanner reproduced the exact finding
at line 86. `security-scan-before.json` retains it against local source commit
`aacfde34088abc425fb6d467cba388e5d54852de`, whose published tree is identical
to remote `b1d1fa7c86d016d518005368c96a07f44e881fbc`.

BAR before the repair:

1. Reuse exists: the original synthetic demonstration contains the established
   planted-security source; reuse the whole file without executing it.
2. Reproduced blocker: the repository scanner flags the duplicated payload in
   the new review script. The parent authorized this narrow correction.
3. Behavior boundary: only the independent review fixture changes; the real
   candidate security scan must still block before acceptance execution.
4. Failing check first: the unchanged scanner reproduced SEC_EVAL. The repaired
   review files must scan clean, while all four runtime probes still pass.
5. Revertibility: one evidence-only commit contains the repair and results.
6. No new dependency, approval, scanner exception or policy is introduced.

The source file's existing exact-path security allowances remain unchanged.
The copied candidate file receives no exception: the runtime scans its actual
content and must report a HIGH_DYNAMIC_EXECUTION finding for `unused.py`.
This uses the established fixture as data, with no import or demo execution.

Result of repair attempt 1: all four probes passed. The security-block case
retained NOT_EVALUATED for all three criteria, recorded the real
HIGH_DYNAMIC_EXECUTION finding for `unused.py`, and never started acceptance
verification. `results.txt` records the reused source path and SHA-256. The
unchanged repository scanner found zero findings in the review directory;
`security-scan-after.json` binds that result to the repaired script bytes.
The diff for `src`, `security`, `scripts`, `.github`, and `tests` is empty
relative to the pre-repair commit. `git diff --check` also passed. These are
local results; no new remote CI result is asserted.
