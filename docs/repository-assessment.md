# Repository assessment (Phase 1)

Date: 2026-07-12 · Branch: `claude/pm-production-engineering-os-ggzl9x`

## What exists

| Area | Contents | Verdict |
|---|---|---|
| `.claude/skills/` | `/pm` orchestrator + 40 stage skills (Markdown) | Working product — do not touch |
| `.claude/agents/` | 7 reviewer personas | Working — do not touch |
| `.claude/commands/` | `pr-review.md`, `review-pr.md` | Working — do not touch |
| `.github/workflows/pr-review.yml` | CI reviewer agent | Working — leave; add new CI beside it |
| `tests/` | `lint_skill.py` + per-skill `fixtures.md` dirs (Markdown fixtures, no pytest modules) | Additive extension safe: `tests/unit|integration|e2e|fixtures` |
| `prds/`, `reviews/`, `LESSONS.md` | PRD + audit trail convention | Reuse convention (PRD added for this build) |
| `README.md`, `CLAUDE.md` | pm-agent-os docs and repo rules | Keep; add a pointer section only |
| `concise-rewriter/`, `context-auditor/`, `eval-rubric-generator/`, `token-cost-estimator/`, `test-files/` | Legacy root-level skill dirs | Leave untouched |
| Application code | **None** — no pyproject, no src/, no Python package | Greenfield for this system |

## Existing stack

- Python 3.11.15 (only runtime present; `tests/lint_skill.py` is Python).
- Dev tools available: ruff 0.15.8, black 26.3.1, mypy 1.19.1, pytest 9.0.2, PyYAML;
  bandit 1.9.4 installable via pip (verified).
- git available; remote is GitHub (`Abhillashjadhav/production-engineering-os`).

## Reusable components

- The repo's *discipline* (gates-before-instructions, fixtures-before-implementation,
  PR-review-before-merge) is reused as the engineering discipline of this build.
- `prds/` + `DECISIONS.md` conventions from the `prd-first` skill.
- No reusable application code exists.

## Constraints

1. Do not overwrite or restructure pm-agent-os content (README, tests/, skills).
2. CLAUDE.md: every change lands through a PR; lint before verdict; one concern per PR
   (this build is one concern: the V1 vertical slice, delivered as one PR of small commits).
3. No assumption of remote repository admin permissions (branch protection is a
   recommendation document, not an applied setting).
4. Tests must run offline and deterministically (CI and sandbox have no LLM access).
