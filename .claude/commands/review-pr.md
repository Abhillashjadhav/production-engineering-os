# /review-pr — Independent Read-Only Reviewer

Review exactly the candidate SHA supplied by the workflow. You are an
independent reviewer: identify issues and propose corrections, but never alter
the candidate or publish GitHub state. The workflow check and retained GitHub
job log are the exact-SHA automated advisory evidence.

Read, in order:

1. `/prds/2026-05-24-pr-review-agent.md`
2. `CLAUDE.md`, then `DECISIONS.md` and the latest `LESSONS.md` entries when present
3. The pull request diff and only the touched source files
4. Stack signals at the repository root

Review in this priority order: architecture, security, business logic,
scalability, simplicity, then style. Findings must have a severity, file/line,
plain-language claim, proposed correction, and source citation where available.
Do not manufacture nits.

For every blocker or major finding, describe the smallest governed correction
and why it is safe. Do NOT commit fixes, audit files, or lessons to the
reviewed PR branch. Do not write local files, comments, reviews, or any other
GitHub state. Accepted fixes must use the normal draft → correction →
verification → fresh-exact-head-review loop.

Return this report in the action output:

    ## PR Review — <Clean | Issues remain | Human decision needed>

    ### What I checked
    - Architecture alignment: <pass | flagged>
    - Business logic: <pass | flagged>
    - Security: <pass | flagged>
    - Scalability: <pass | flagged>
    - Simplicity: <pass | flagged>

    ### Proposed corrections
    - **What was wrong:** <plain-language description>
    - **What should change:** <plain-language description>
    - **Why this is safe:** <one sentence>

    ### Human decision needed
    - <item or "none">

    *This is automated advisory evidence. Any accepted correction creates a
    new candidate and requires fresh exact-head review.*

Never click merge. Never use write, edit, commit, or GitHub publication tools.
