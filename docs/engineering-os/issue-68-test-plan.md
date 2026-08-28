# Issue 68 — atomic implementation test plan

Authoritative issue: `#68`

Base commit: `165ff688ead5a14960638b2cdbdef74891326891`

## Outcome

Prove that one admitted issue produces one dedicated branch, one planning/test-only
commit, one primary draft pull request, scoped specialist worktrees, and a
deterministically integrated candidate without any workflow-owned merge.

## Meaningful red

The first commit adds executable tests against the not-yet-implemented
`pmpe.engineering.atomic` authority. Collection must fail because that module does
not exist. Implementation is not authorized until this red result is observed and
bound to this exact test-plan commit.

## Required proofs

1. Repository effects occur in this order: issue admission, exact-base branch,
   planning/test-only commit, primary draft PR.
2. Crash recovery re-admits matching effects without creating duplicates; a
   mismatched issue, base, branch, or primary PR fails closed.
3. Implementation leases require admitted meaningful-red evidence and restrict
   each specialist to its task and allowed paths.
4. Cancellation revokes mutation authority, freezes partial work, and prevents
   that output from becoming a candidate.
5. Specialist results integrate in deterministic task order and reject dirty,
   out-of-scope, stale, or duplicate submissions.
6. Ready-for-review and ready-to-draft are explicit exact-head repository effects;
   check/review drift invalidates prior evidence and no merge capability is exposed.
7. Every declared specialist route has a real worktree-isolated agent definition
   and an executable admission/eval contract.

## Verification

- Focused unit and integration tests for the new authority.
- Existing lifecycle, worktree, routing, and CLI suites.
- Full pytest, Ruff, strict mypy, Bandit high severity, and exact-head CI.

