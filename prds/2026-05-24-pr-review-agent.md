# PRD: PR Review Agent

**Date:** 2026-05-24
**Status:** Approved

## Problem
Abhillash vibe-codes 15 apps and merges blind. He can't read code well enough to gauge architecture quality, code simplicity, scalability, or business-logic correctness. Today he clicks "merge" and hopes — there's no review layer between his prompt and production.

## User
Abhillash, solo developer, 15 personal GitHub repos. Current alternative: manual merge with zero review. No competing tools in use; clean slate.

## Success metric
After 30 days of using the agent, Abhillash understands his own codebase better than today and reads LESSONS.md at least once per week.

## Scope (v1)
- Auto-runs on every PR open (no manual trigger, no draft skip)
- Independent read-only review: reviewer finds issues and proposes governed corrections
- One review pass per exact candidate; accepted fixes use the normal correction loop
- Review rubric prioritizes: architecture violations -> security -> business-logic correctness -> scalability -> code simplicity. Style/format is lowest priority.
- Reads CLAUDE.md + DECISIONS.md + the diff + scans package.json/schema/folder structure
- Emits the exact-SHA workflow check and retained job log as automated advisory evidence
- Never mutates the reviewed PR branch for audit, lessons, or fixes
- Lives in Config-repo template -> propagates to all future repos via "Use this template"
- One-time copy-prompt deploys to the 14 existing repos
- Tuned to a solo-dev context: over-engineering is itself a blocker, not a virtue

## Out of scope (cut from v1)
- No auto-merge — Abhillash always clicks the merge button
- No per-repo rubric customization — one rubric across all 15
- No external integrations (no Slack, email, dashboards, web UI)
- No multi-language deep specialization
- No refactoring suggestions outside the PR diff
- No SAST tools, dependency vulnerability scans, or performance benchmarks
- No fancy UI — all output lives in GitHub PR comments + repo markdown

## Non-goals (failure modes)
- **False confidence:** agent says "looks good" on a PR that later causes an incident
- **Theatrical correctness:** agent flags style/nits but misses real architecture/business-logic issues
- **Doesn't teach:** after 30 days, LESSONS.md is empty, generic, or unread

## Decisions log
- 2026-05-24: Chose independent review over reviewer-written fixes: a review must not change the candidate it claims to attest. Accepted fixes enter the normal draft → correction → verification → fresh-review loop.
- 2026-05-24: Chose one review pass per exact candidate over recursive review-generated commits, preventing stale or self-created heads from gaining review evidence.
- 2026-05-24: Chose auto-fire on every PR over label-gated — maximum coverage. Mitigation: 4-round cap protects token quota.
- 2026-05-24: Skipped web dashboard despite user's initial pull toward it — would double scope, undermines goal of reducing surface area.
- 2026-05-24: One rubric across all 15 repos in v1 — per-repo context comes from each repo's CLAUDE.md + DECISIONS.md, not from forking the rubric.
