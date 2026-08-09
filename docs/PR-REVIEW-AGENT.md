# PR Review Agent

The repository's automated advisory reviewer is **Claude Code** running as
`claude[bot]` through `anthropics/claude-code-action@v1`. It is not a human or
formal approval, and it never satisfies a required independent human/formal
review.

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

## Credential and failure policy

Repository administrators must configure the Actions secret
`CLAUDE_CODE_OAUTH_TOKEN` with a supported Claude Code OAuth credential. The
workflow deliberately runs a credential preflight before invoking the reviewer:
absent or expired credentials, quota exhaustion, and reviewer-service failures
leave the `PR Review Agent / review` check failed and visible in GitHub. A
skipped, failed, missing, stale, or wrong-SHA result is not review evidence and
must block merge admission.

Draft pull requests are not reviewed. A synchronize event is a new candidate
and requires a fresh successful exact-head review. Review comments, reactions,
trigger comments, empty self-reviews, and duplicate requests are not formal
review evidence.

## Operator recovery

An administrator restores service by updating the configured secret or the
reviewer's service capacity, then causes one substantive synchronized candidate
run or marks the candidate ready for review. Do not treat rerunning an old
workflow, a comment, or a reaction as review evidence for a newer head.
