# Authorized R4 admission packet

Implement C2-F1/F2/F3/F4/F5 from the supplied 2026-09-24 R4 report, using the
isolated `r4-20260924/peos-admission` branch based on prior #211 local head
`23ca4cbb4cc474fe6fe65d479029c8deb8a152cb`. Reproduce before implementation,
write BAR for the unit, commit failing tests first, then extend the existing
compiler. Check misspelled parent keys and malformed containers, misplaced gate
keys in criteria/requirements/root acceptance, bounded two-edit and explicit
synonym aliases, false positives on prose, and surrounding whitespace in IDs.
Preserve legitimate arbitrary payload data; do not recursively interpret it as
contract declarations. Document finite grammar and remaining scope.

Read the shared WORK_CONTRACT in the R4 proof worktree and the owner-supplied
AGENTS.md plus CLAUDE.md from the integration proof worktree. Preserve frozen v1
artifacts, scanner/policy/allowlist and fixture line numbers. No model calls,
deployment, merge, publication, new agents or unrelated work. Retain meaningful
RED and preserving controls, a focused GREEN pass, lint/types and exact commits.
The implementer does not issue independent approval. Parent integrates and
publishes after independent review.
