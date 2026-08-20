# Exact-head pull-request review policy

## User outcome

No change is called `RELEASE_READY` until GitHub contains an independent Codex review of
the exact current head and the required deterministic checks are green. A new commit makes
the prior review stale.

## Required repository setting

In the GitHub ruleset protecting `main`, require this status check:

```text
PR Review Agent / review
```

Also require the repository's deterministic CI checks and disallow bypass for normal
contributors. Repository administrators retain GitHub's emergency bypass authority, so a
bypass is never evidence that PMPE admitted the change.

The workflow deliberately runs from the protected base branch with read-only permissions.
It waits for a GitHub-visible Codex advisory tied to the exact pull-request head and fails
closed when that evidence is missing or a current P0, P1, or P2 finding remains.
The required job runs unconditionally: draft and fork submissions fail explicitly instead
of using a job-level condition that GitHub could report as a successful skipped check.

## Operating sequence

1. Open the pull request as draft while implementation is changing.
2. Run deterministic checks and record the current head SHA.
3. Mark the pull request ready for review.
4. Wait for both deterministic CI and `PR Review Agent / review` on that exact head.
5. Address findings. Every repair creates a new head and therefore requires a new review.
6. Reconcile every current review thread.
7. A named human decides whether to merge.

Do not merge a small or documentation-only pull request early. PR #117 demonstrated the
failure shape: green CI plus zero reviews is still `REVIEW_REQUIRED`, not release-ready.

## What the review count means

Codex reviews are independent advisory evidence. They do not count as the repository
owner's personal GitHub review contribution, and they never replace a named human release
decision.
