# F-01: executable release-gate enforcement

Authorized scope: repair the silent loss of approved binary release gates in
the current acceptance compiler and `run_to_release_ready` path. Base source:
`dd4271b70fcb9cb5b9dd279fe516c2fe50806751`. Prior #203/#204/#205 integration is
owned by the parent reviewer and is not folded into this source branch.

Read `CLAUDE.md` and `.claude/commands/pr-review.md`. No applicable `AGENTS.md`
was found in this repository. One coherent concern: executable gate binding,
verification evidence and release refusal. Preserve historical artifacts,
contracts, evaluator semantics and gold expectations. Maximum two repair
attempts. No merge, deployment, paid/model calls or remote writes by this agent.

Agreed minimal representation: a gate names a non-empty, unique list of existing
`acceptance_criterion_refs`. It is the conjunction of those already compiled
mechanical checks. Accept PDC `binary_release_gates` arrays/ID maps and canonical
`quality_assurance.release_gates` ID maps. Refuse competing declarations,
malformed gates, unknown references and unsupported/unbound gates before build.
Record PASS/FAIL/NOT_EVALUATED for every gate from explicit criterion outcomes
on the exact candidate snapshot, bound to contract/plan/candidate digests.
RELEASE_READY requires every declared gate to have PASS evidence.

The parent explicitly approved this narrow subset after the PMOS reviewer found
that task-store gates G2–G5 concern process/evidence/disclosures rather than
product acceptance assertions. Do not map those gates to convenient AC IDs.
Leave original approved contracts and historical DEMONSTRATED receipts intact;
report the original unbound task-store contract blocked by the new compiler.
Positive controls use clearly labeled test-only bound contracts. Proposed future
bindings are not owner approval and require a new exact contract approval.

Expected interfaces: compiled plan release-gate records; optional criterion
outcome capture inside snapshot verification; release-gate ledger evidence;
optional canonical schema authoring field. Existing A/B/C/template evaluation
semantics and no-gate contract behavior stay unchanged. Tests precede production
edits and use the existing test-only local sandbox seam, not a claimed OS
isolation or live-model evaluation.

Before production edits, the parent pointed out `CONTRIBUTING.md`; it was read
and the RED test-only phase was committed as
`1b807a68dd2020bcabad0c5cfd649c236f602219` before implementation. Subsequent
commits preserve that chronology and use conventional commit prefixes.
