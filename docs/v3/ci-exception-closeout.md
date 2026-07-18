# V3 closeout — CI exception record

> **Locally verified and independently reviewed. PRs #51 and #52 were manually
> merged through an explicit owner-approved CI exception because GitHub-hosted
> Actions runners were unavailable. These merges are not CI-verified.**

## Scope

- **PR #51** — `fix(frontend): attribute an unreadable framework 422 to the request`
  (dogfood frontend F-3). Merge commit `0017f73610db87fac1b233c47f1de36d4a73ae59`.
- **PR #52** — `fix(engine): baseline-authoritative guardrail governance (F-4, PD-V3-19)`.
  Merge commit `c6a985486d47a21ca92e429e555ee3d66ed9f39d`.
- Final `main` head at closeout: `c6a985486d47a21ca92e429e555ee3d66ed9f39d`.

## Why the exception

From ~04:49Z onward, every GitHub Actions run for this repository failed at
**runner assignment** — jobs were created with `runner_id: 0`, `runner_name`
empty, completing in 1–3s with **no steps and no logs**. The last successful run
was #142 (push to `main` `0cdc96f`, 04:48Z). The signature (runs created but no
runner ever attached, repo-wide, persistent) is consistent with the private-repo
Actions minutes/spending limit being exhausted; a transient GitHub-hosted runner
incident is a less-likely alternative. The MCP integration also lacks
`actions: write`, so API re-run / workflow-dispatch returned 403; close→reopen
retriggers likewise startup-failed (runs `29633351138`, `29633761353`,
`29634232679`). Because substantive CI never executed, the merges were performed
manually by the repository owner as a deliberate, recorded exception.

## What WAS verified (local, on final `main` `c6a9854`)

| Gate | Result |
|---|---|
| PMPE engine suite (`tests/`) | 378 passed, exit 0 |
| Backend (`pm-evals-web/backend`) pytest | 85 passed (incl. OpenAPI-currency + golden-currency gates) |
| ruff check / ruff format --check | clean |
| mypy (strict) | clean |
| Frontend vitest | 80 passed |
| TypeScript `tsc --noEmit` | clean |
| Frontend production build (`next build`) | clean |
| Generated client drift (`generate:api-types`) | idempotent — no drift |
| Golden comparison fixtures | current (pinned to engine output) |
| Backend dependency audit (`pip-audit --require-hashes --strict`) | no known vulnerabilities |
| Frontend `npm audit --audit-level=high` | pass (exit 0); 2 pre-existing *moderate* advisories below threshold |
| Browser E2E (real production build + real backend, Playwright/Chromium) | 16/16 passed — axe-clean S-1/S-2/S-3, PROCEED/HOLD/INSUFFICIENT journeys, server-only validation, download integrity, keyboard-only + visible focus + AT announcements, trace filter, 375px mobile journey |

Independent fresh-context reviews (read-only) prior to merge: **APPROVE** on both
(#51 frontend/accessibility lens; #52 backend/API correctness+security lens).
The F-4 load-bearing threshold logic was mutation-verified
(`max→candidate_min` and `is None→truthiness` both caught by the suite; restored).

## Behaviour verification (merged source)

- Framework-level 422 fallback uses `source: "request"` (`frontend/src/lib/api.ts`).
- PD-V3-19 guardrail governance is **baseline-authoritative**
  (`backend/src/pm_evals_compare/compare.py`): baseline governs; candidate may
  **strengthen but never weaken**; effective threshold is
  `max(baseline_threshold, candidate_threshold)`; resolution uses explicit
  `is not None`, so an explicit `0.0` is honoured and cannot bypass the baseline;
  the locked `DEFAULT_MIN_PASS_RATE = 0.0` applies when the baseline omits one.
- Threshold provenance (baseline / candidate-declared / effective / policy /
  effect) is surfaced in the JSON report (via `model_dump`) and the Markdown
  report's `## Guardrails` section (`backend/src/pm_evals_compare/report.py`).

## Historical-evidence integrity

- CAND-001 candidate commit `243eddf72005` is **unchanged**.
- `docs/v3/dogfood/` (the CAND-001 HOLD verdict, failed findings, infrastructure-
  invalid event, and superseding evidence) is **unchanged** — last modified by
  PR #37, not by this session's merges.

## Honest readiness classification

**LOCALLY VERIFIED — CI EXCEPTION USED. NOT CI-VERIFIED. NOT PRODUCTION-READY.**

No production environment or adapter was executed; no named human approval is
bound to any candidate digest. CAND-002 was **not** run.
