# Issue and Pull Request Governance

Status: Phase 0 proposed repository policy
Scope: all Production Engineering OS product and engineering changes

## 1. Governing invariants

- No implementation begins until a corresponding GitHub issue exists.
- Every implementation unit uses `issue → dedicated branch → atomic draft PR →
  automated checks → independent review → corrections → approval → merge → closure`.
- One issue has one primary PR. A replacement PR must explicitly supersede the old one.
- A PR delivers one coherent outcome; unrelated capabilities require separate issues.
- Commits are meaningful checkpoints, not contribution-count artifacts.
- Model prose, screenshots of prose, and self-attestation are not completion evidence.
- Evidence is valid only for its exact commit, artifact, configuration, migration,
  deployment, environment, and observation subjects.
- A fixer cannot be the only verifier or approver of its own change.
- Direct changes to `main`, shared-branch force pushes, fabricated reviews, and
  production implementation inside planning PRs are prohibited.

This Phase 0 policy reconciles the repository instruction surface with concern-based
atomicity. `CLAUDE.md` now requires separate PRs when schema, runtime/compiler logic,
and narrative documentation are independently useful outcomes; tests, evidence, and
generated artifacts required to prove one outcome remain with that outcome. The
contract work demonstrates the rule: #62 is schema-only, #76 is compiler/migration
logic, and #77 is authoring/migration documentation.

## 2. Required issue template

```markdown
## Customer or engineering outcome
<!-- Observable result, not work volume. -->

## Problem
<!-- Current evidence-backed failure or gap. -->

## Why this capability is necessary
<!-- Link to outcome, lifecycle, metric, risk, or obligation. -->

## Scope
- ...

## Non-goals
- ...

## Dependencies
- Depends on #...
- Enables #...
- Can proceed independently from #...

## Product decisions
<!-- Approved decisions and unresolved product inputs. Never invent them. -->

## Architectural decisions
<!-- Boundaries, interfaces, invariants, and applicable ADRs. -->

## Important trade-offs
<!-- Dominant trade-off and why this direction is chosen. -->

## Acceptance criteria
- [ ] AC-...

## Test requirements
- ...

## Evidence requirements
<!-- Exact subjects, commands/attestations, tool versions, and expected artifacts. -->
- ...

## Risks
- ...

## Security and privacy considerations
- ...

## Rollback implications
- ...

## Expected repository boundaries affected
- `path/or/component`

## Definition of done
- [ ] All acceptance criteria have exact-subject PASS evidence.
- [ ] Required checks pass against the PR head.
- [ ] Blocking review findings are resolved.
- [ ] Documentation and durable state are current.
- [ ] Approved and merged by an eligible maintainer.
```

Issue authors must use stable requirement and acceptance-criterion IDs where the work
originates from a product contract. Unknown product facts are blockers or open questions,
not implementation assumptions.

## 3. Issue graph and planning

The umbrella issue owns the ordered capability graph. Child issues:

- name their prerequisite issues and downstream consumers;
- state which work can safely proceed independently;
- remain small enough for one coherent review but large enough to deliver a real outcome;
- do not duplicate capabilities already proven on the target branch;
- record scope changes before code changes;
- link ProductChangeRequests when new product decisions are required.

A child issue is not a substitute for a validated PMOS contract slice. Both must exist
before product implementation.

## 4. Branch naming

Use one dedicated branch per issue:

- documentation/planning: `docs/<issue-or-phase>-<outcome>`
- features: `feat/<issue-number>-<outcome>`
- defects: `fix/<issue-number>-<outcome>`
- security: `security/<issue-number>-<outcome>`
- operations: `ops/<issue-number>-<outcome>`

Examples:

- `docs/phase-0-pmos-peos-plan`
- `feat/62-contract-bundle-schema`
- `fix/123-stale-evidence-rejection`

Branches start from the current protected target branch. Do not reuse a merged branch,
mix issues, force-push a shared branch, or overwrite unrelated working-tree changes.

## 5. Commit rules

- Prefer a small number of coherent commits that explain real engineering progress.
- Use imperative messages such as `docs: define Phase 0 delivery controls` or
  `feat(contract): add versioned PMOS bundle`.
- Do not use empty, cosmetic, generated-noise, or artificially fragmented commits.
- Do not hide functional changes in formatting or dependency-only commits.
- Generated artifacts name their source and reproducible generation command.
- A correction commit identifies the finding it resolves when that is not obvious.
- Never amend or rewrite commits others may already depend on without coordination.

## 6. Atomic PR test

A PR is atomic only when all answers are yes:

1. Does it have one primary issue and one customer/engineering outcome?
2. Can it be reviewed, tested, approved, reverted, and released independently?
3. Are all changed boundaries necessary for that outcome?
4. Are its acceptance criteria internally complete?
5. Does it avoid unrelated cleanup and future capabilities?
6. Would splitting it create complete outcomes rather than meaningless fragments?

If unrelated work is discovered, open another issue. If an inseparable dependency makes
the outcome unreviewable, revise the issue boundary before proceeding.

## 7. Required PR description

```markdown
## Outcome
<!-- Customer or engineering result. -->

## Problem
<!-- Evidence-backed reason for the change. -->

## What changed
- ...

## Why this direction
<!-- Product and technical decisions. -->

## Scope
- ...

## Non-goals
- ...

## Decisions and trade-offs
- Decision:
- Dominant trade-off:
- Reversal condition:

## Acceptance criteria
- [ ] AC-...

## Tests and exact-subject evidence
| Gate | Subject | Command or attestation | Result | Evidence |
|---|---|---|---|---|

## Risks
- ...

## Security and privacy
- ...

## Rollback
- ...

## Open questions
- ...

## Next issue
- #...

Closes #<primary-issue> <!-- only when merge itself satisfies the full definition of done -->
Tracks #<umbrella-issue>
```

The title uses a clear outcome-oriented prefix. PRs start in draft and remain draft until
all required checks and review corrections pass. Every PR references its primary issue,
but `Closes #...` is used only when merging that PR satisfies the issue's entire
definition of done. If staging, canary, production, an observation window, or another
post-merge gate remains, use a non-closing `Tracks #<primary-issue>`/`Relates to
#<primary-issue>` reference and keep the issue open. Umbrella and related issues always
use non-closing links.

## 8. Verification and evidence

Required evidence is policy-selected from the change's contract, risk, and repository:

- exact commit SHA and tree/artifact/config/migration/deployment digests;
- requirement/acceptance/test/risk IDs and their coverage status;
- commands or attestations, exit codes, tool identities and versions, environments,
  timestamps, and immutable logs;
- unit, integration, end-to-end, migration, performance, accessibility, architecture,
  security, privacy, dependency, secret, deployment, and runtime results as applicable;
- exception approvals, reviewer identity, finding dispositions, and rollback proof.

Changing a bound subject invalidates its earlier evidence. A summary may link evidence
but cannot replace it. Local environmental failures must be distinguished from product
failures and reproduced in the supported CI environment where possible.

## 9. Independent review process

1. Freeze the exact PR head and collect read-only proof.
2. Run automated checks before asking a human to spend review time.
3. Run Codex `/review` or equivalent analysis on the complete diff. It is analysis, not a
   formal GitHub approval.
4. Record every credible finding with severity, location, reasoning, and disposition.
5. Fix all critical/high and credible medium findings; record rejected findings and why.
6. Use a separate repair pass; never silently let the reviewer rewrite the candidate.
7. Re-run the full affected and mandatory suite on the changed head.
8. Request formal GitHub review from an eligible collaborator when one exists.
9. Do not request a fabricated identity, self-approve, or claim a review without GitHub
   evidence.
10. If corrections change the candidate, earlier approvals and exact-subject evidence
    are stale unless repository policy explicitly and safely preserves them.

The current automated PR-review workflow must not be treated as independent approval
because its documented path permits the review context to edit and commit fixes. Until
that is redesigned under its own issue, treat its output as advisory analysis.

## 10. Severity and disposition

- **Critical:** exploitation, destructive data loss, unauthorized production action, or
  proof-integrity failure. Always blocks.
- **High:** likely acceptance, security/privacy, rollback, or lifecycle correctness
  failure. Always blocks.
- **Medium:** credible reliability, maintainability, test, or operational deficiency.
  Blocks unless explicitly rejected with evidence and owner reasoning.
- **Low:** non-blocking improvement; track when it has future value.

Dispositions are `accepted`, `fixed`, `rejected-with-reason`, `product-input-required`,
or `follow-up-issue`. A severity label alone is not resolution evidence.

## 11. Merge and issue closure

A PR may leave draft only when:

- the exact head has all required green checks and a complete EvidenceBundle;
- critical, high, and credible medium findings are resolved;
- required PR/review approvals exist; protected-environment approvals are acquired
  separately at their staging, canary, and production lifecycle gates, not as a
  prerequisite for leaving PR draft;
- scope, atomicity, documentation, migration, observability, and rollback are current.

Only an authorized maintainer may enqueue or authorize a merge through an enforced
merge queue or compare-and-swap gate that atomically admits the unchanged reviewed PR
head, protected-base SHA, prospective merge-tree digest, required checks, and approvals.
Generic branch protection or a normal maintainer merge is insufficient; any bypass
blocks deployment even when the resulting tree happens to match. Phase 0 explicitly
stays draft and unmerged until the user directs otherwise.

Close the primary issue through the merged PR only when merge itself satisfies its
definition of done. When its definition depends on post-merge staging, canary,
production, observation, rollback-drill, or feedback evidence, the PR must use a
non-closing issue reference; keep the issue open until those exact-subject gates pass,
then an eligible owner or governed automation closes it with the sealed evidence
reference. Do not close the umbrella until all child outcomes are complete and the
end-state metrics and evidence support completion. Reopen an issue when its acceptance
evidence is invalidated or the delivered capability materially fails its definition.

## 12. Contribution quality and governance metrics

Track:

- issues opened and completed;
- atomic PRs raised and merged;
- formal reviews requested and submitted;
- review findings identified and resolved;
- PRs reopened;
- rollbacks;
- escaped defects.

Use these as process health signals, not individual productivity targets. Healthy
contribution activity emerges from real decisions, bounded changes, useful review, and
evidence. Raw issue, commit, PR, or comment counts are not success measures.

## 13. Policy exceptions

Exceptions require a named owner, scope, reason, risk acceptance, evidence, expiry, and
recovery plan. An exception cannot:

- waive exact-subject provenance;
- treat model output as a deterministic pass;
- permit fabricated review or product truth;
- bypass critical/high security or privacy findings, or rollback failures;
- retroactively declare a deployment complete.

Emergency rollback is pre-authorized when defined guardrails breach. It still requires
post-action evidence and incident follow-up.
