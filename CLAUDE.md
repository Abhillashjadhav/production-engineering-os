# pm-agent-os

## What this repo is
An agentic PM operating system for Claude Code. One `/pm` command (`.claude/skills/pm/SKILL.md`) classifies any product request into lifecycle stage(s) — discovery, strategy, build, launch, iterate — and routes to stage skills. Stage 1 (Discovery, 7 skills) is shipped; the other four stages return "stage not yet shipped". The core rule of the whole system: no output returns to the user until its verification gate passes.

## PR rules (non-negotiable)
- No direct pushes to main. Every change lands through a PR.
- Every PR is reviewed with `/pr-review` before merge. No APPROVE, no merge.
- Lint before verdict: the reviewer runs `python3 tests/lint_skill.py <path>` on every changed SKILL.md and reports the result before issuing a verdict. Any lint FAIL is an automatic REQUEST CHANGES.
- One concern per PR. Schema changes, logic changes, and doc changes are separate PRs.
- PR description must state: what changed, why, and how to test the change.

## Verification-first skill discipline
Gates and fixtures come before instructions. For every new skill, `tests/<skill>/fixtures.md` (the gates and known-answer fixtures) is written and committed *before* `.claude/skills/<skill>/SKILL.md` — the commit order in the PR is the evidence.

A skill ships when:
1. Frontmatter passes `tests/lint_skill.py` (name, description with fire + no-fire triggers, Limitations section, ≤500 lines).
2. The body states its binary verification gates in a dedicated section, above the instructions.
3. The body has at least 3 explicit hard rules.
4. `tests/<skill>/fixtures.md` covers the three-gate harness (below).
5. The PR review returns APPROVE.

## Three-gate harness
Every skill's `tests/<skill>/fixtures.md` covers:
- **Gate 1 — Lint.** `python3 tests/lint_skill.py .claude/skills/<skill>/SKILL.md` exits 0.
- **Gate 2 — Trigger accuracy.** SHOULD-FIRE and SHOULD-NOT-FIRE phrasings; the skill's description must route all of them correctly.
- **Gate 3 — Known-answer.** A concrete fixture input with the expected output properties, including at least one case where a verification gate must catch a planted failure.

## What we do not ship
- Skills that produce unverifiable output: invented quotes, fabricated metrics, naked numbers with no source or estimate label.
- Skills without explicit failure guardrails.
- Skills that duplicate official Anthropic surfaces.

## Layout
- `.claude/skills/` — the `/pm` orchestrator and all stage skills (flat, one dir per skill)
- `tests/` — `lint_skill.py` plus per-skill `fixtures.md`
- `.claude/commands/pr-review.md` — the PR review command; `.claude/commands/review-pr.md` + `.github/workflows/pr-review.yml` — the CI reviewer agent (charter in `prds/2026-05-24-pr-review-agent.md`)
- `reviews/`, `LESSONS.md` — the reviewer agent's audit trail and pattern log

## Repo owner
Abhillash Jadhav — github.com/Abhillashjadhav
