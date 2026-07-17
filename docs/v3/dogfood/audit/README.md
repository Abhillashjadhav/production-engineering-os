# Audit evidence — the original failed reviewer-integrity proof

This directory preserves, verbatim, the read-only proof that failed during the
first dogfood run `fs-fsc-pmevals-001`, so the infrastructure fix in this PR is
auditable against the exact event that motivated it.

## What happened

`original-failed-integrity-event.jsonl` is the ledger pair the old
`readonly_guard` emitted when the first `end_review` was attempted for
`v3-backend-api-security-reviewer`:

- `submit_review` at `13:09:01Z`
- `readonly_check` with **`verdict: "modified"`** at `13:09:12Z`

The `modified` verdict was a **false positive**. The whole-tree snapshot taken
at `12:03–12:04Z` captured `.claude/scheduled_tasks.lock` — an *untracked*
Claude Code runtime file the harness creates and deletes on its own. Between the
snapshot and the check the harness deleted its own lock, so `verify_unmodified`
reported `removed: .claude/scheduled_tasks.lock`. No reviewer wrote anything:
the six reviewers are read-only by tool configuration (Read/Grep/Glob only), and
`git status` was empty at the frozen candidate commit `243eddf` throughout.

## The fix (this PR)

`readonly_guard` now draws the reviewer read-only proof at the **git-tracked
boundary** (`readonly_snapshot` + `verify_unmodified` over `git ls-files`), so
untracked runtime files are excluded symmetrically on both sides and can never
register as a reviewer write. See `../readonly-proof.txt` for the executed proof
that the corrected guard is clean over this exact scenario on the frozen
candidate tree, and `tests/unit/test_readonly_guard.py` for the regression test.

## Why it is preserved, not rewritten

The event is real evidence of a real infrastructure defect the dogfood caught.
It is kept exactly as emitted; the clean verification is recorded separately in
`../verification-ledger.jsonl`. Nothing here was edited to make the run look
clean — the failure and its correction are both on the record.
