# PR Review Agent

The repository's automated advisory reviewer is the existing **Codex GitHub
integration** (`chatgpt-codex-connector[bot]`). It is not a human or formal
approval.

## Trigger and identity

`.github/workflows/pr-review.yml` runs only when a same-repository pull request
is non-draft and is opened, reopened, marked ready, or receives `synchronize`.
Its concurrency key is the pull request number, so a newer eligible head
cancels the previous run. The workflow checks out the event SHA (not a branch
name), then re-observes the current PR head immediately before review; a
mismatch fails closed. The reviewer is read-only: it cannot commit audit
records, lessons, or fixes to the candidate branch. The exact-SHA check and
retained GitHub job log are automated advisory evidence; accepted fixes use
the normal governed correction loop and receive a new review.

## Codex evidence policy

The gate uses no external reviewer credential. It re-observes the current PR
head and accepts a clean result only from the Codex bot when either its
GitHub-visible conversation comment identifies the current exact SHA or its
authenticated pull-request review is bound to that exact SHA. It paginates both
evidence surfaces and rejects any current exact-head Codex review body or
non-outdated review thread containing P0/P1/P2. Before admission, it requires
the conversation comments, review objects, and complete inline-thread surface
to remain byte-for-byte stable across two observations ten seconds apart. This
closes the GitHub publication window where a review object can appear before
its inline findings. GitHub may represent a clean
result as a conversation comment or a pull-request review; it is recorded truthfully as
`CODEX ADVISORY REVIEW — CLEAN — EXACT HEAD`. Missing, stale, owner-authored,
trigger-only, or finding-bearing evidence fails closed.

Draft pull requests are not reviewed. A synchronize event is a new candidate
and requires a fresh successful exact-head review. Review comments, reactions,
trigger comments, empty self-reviews, and duplicate requests are not formal
review evidence.

## Operator recovery

An administrator restores or verifies Codex GitHub integration availability/service capacity, then must retry or re-enter the exact-head review cycle by causing one substantive synchronized candidate run or marking the candidate ready for review. No reviewer secret or external credential is required. Do not treat rerunning an old workflow, a comment, or a reaction as review evidence for a newer head.
