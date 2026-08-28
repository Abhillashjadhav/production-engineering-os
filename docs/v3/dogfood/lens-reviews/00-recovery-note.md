# Lens-review recovery note (run fs-fsc-pmevals-001)

## What failed
The first three lens reviewer subagents (launched in parallel at ~12:04Z on
2026-07-17) were terminated by a session interruption at ~12:57Z, before any
of them produced a final report:

| Lens | Task ID | Progress at death | Report produced |
|---|---|---|---|
| v3-ux-journey-reviewer | a36ee50d4ae251cd5 | 21 read-only tool calls; last event an unfinished thinking block | none |
| v3-frontend-accessibility-reviewer | a54d4f89b25ff4a87 | 22 read-only tool calls; last event a tool result | none |
| v3-backend-api-security-reviewer | a9c48b312fe68b78a | 18 read-only tool calls; last event a tool result | none |

The task registry entries were gone after the interruption (TaskOutput:
"No task found"); the transcripts on disk confirm no verdict text exists in
any of the three. The remaining three lenses (architecture-simplicity,
product-conformance, evidence-integrity) were never launched — the launch
block itself was interrupted.

## What was preserved (nothing recreated)
- The run dir, ledger.jsonl (through the preview record), candidate
  manifest (CAND-001, commit 243eddf72005), preview evidence, and all six
  begin_review snapshots persisted at 12:03–12:04Z are untouched.
- The repo worktree is clean at the frozen candidate commit 243eddf72005;
  the dead reviewers were read-only by tool configuration, so the
  snapshots remain valid for end_review.
- No stray Next.js/uvicorn/Playwright/Docker processes or bound ports
  remained; nothing was killed.

## Recovery action
Exactly one replacement reviewer per dead lens, re-launched with the
byte-identical original prompt (recovered from each dead transcript's first
user message), plus one first launch per never-started lens. No duplicate
reviewers; the candidate and evidence are unchanged. All six replacement/new
reviewers completed and their reports are in this directory.

## Read-only false positive (recorded honestly)
The first `end-review` attempt (lens v3-backend-api-security-reviewer) was
refused: `removed: .claude/scheduled_tasks.lock`. That file is UNTRACKED
harness runtime state (Claude Code's scheduled-tasks lock; `git status` was
clean both before and after — the file was never repo content). The harness
itself deleted it between the 12:03–12:04Z snapshots and the check; no
reviewer wrote or removed anything. The refusal emitted a
`submit_review` + `readonly_check verdict=modified` pair into the ledger for
that lens — that event is a false positive and is left in the ledger as-is
(the ledger is append-only evidence).

Because the snapshot content of the lock file cannot be reconstructed
(digest `18beae94…` is not the empty file), the closed brackets were
re-established through the orchestrator's own API: `begin-review` was re-run
per lens (re-snapshotting the tree through the same `tree_digest` code path
as the originals) followed immediately by `end-review`. The substantive
read-only proof for the actual review interval is threefold and unchanged:
(1) every reviewer's tool configuration is Read/Grep/Glob only, asserted
fail-closed at run start; (2) `git status --porcelain` is empty and HEAD is
exactly the frozen candidate commit 243eddf72005 after all six reviews
completed; (3) the only snapshot delta ever detected across 4,464 tracked
paths was the harness's own lock file.

Follow-up finding for the platform (not fixable mid-run — the candidate is
frozen): `readonly_guard` should exclude harness runtime files (e.g.
`.claude/scheduled_tasks.lock`) the same way it excludes node_modules/.next
caches, so a harness lock cycle cannot masquerade as a reviewer write.
