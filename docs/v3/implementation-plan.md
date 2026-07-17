# V3 implementation plan — atomic PR partition

Seventeen atomic PRs. Every PR: one independently meaningful capability,
acceptance tests before implementation, fresh-context read-only review with a
scope charter, green CI, squash-merge, ledger row. Existing 338 V1/V2 tests
stay green in every PR. Numbering continues the contribution ledger (V3 PRs
are ledger rows 19+, titled "V3: …").

| PR | Delivers | Acceptance (evidence) |
|----|----------|------------------------|
| 1 | V3 contract, architecture, threat model, plan, FullStackProductContract JSON Schema + example | docs internally consistent; schema valid + example validates; independent review of the artifact set |
| 2 | `pmpe.fullstack.contract` typed model + admission (approved-only, digest, runnability) + product scaffolding decision records | model round-trips the example; non-runnable refused (mutation-tested); packaged schema sync-guarded |
| 3 | UX architecture stage: journey/screen/UI-state/flow validation (`pmpe.fullstack.journey`) | planted violations refused: screen without states, journey step without screen, missing error/recovery state, implementation-before-journey admission refusal |
| 4 | `pm_evals_compare` deterministic domain engine + run-file schema + fixtures | golden comparisons; determinism property (identical inputs ⇒ identical outputs); HOLD/PROCEED/INSUFFICIENT_EVIDENCE planted cases; hard-gate regression detection; report rendering |
| 5 | FastAPI backend: upload, validation, compare, report endpoints; size/format limits; no egress | API tests: happy path, malformed, incompatible, oversized, hostile filenames/strings; OpenAPI schema committed |
| 6 | Next.js app shell + typed API client generated/validated from OpenAPI; contract-mismatch CI check (`pmpe.fullstack.api_contract`) | tsc strict clean; client types match committed schema; planted schema drift fails the check |
| 7 | Upload + compatibility-validation journey (screens, client-side pre-validation, error states) | Vitest component tests incl. hostile strings; states: empty/loading/error |
| 8 | Comparison dashboard + criterion deltas + changed-trace table/detail | component tests over golden fixture render; verdict panel shows evidence |
| 9 | Markdown/JSON download + error/recovery + insufficient-evidence states | download tests; every UI state reachable and tested |
| 10 | Accessibility + keyboard + responsive verification (axe + deterministic checks) | axe clean on primary journey; keyboard-only completion test; mobile viewport test |
| 11 | Playwright E2E: real frontend + real backend journey (no mocks) | full journey incl. malformed/incompatible, trace inspection, both downloads; runs headless in CI |
| 12 | Containerized preview + digest-bound verification (`pmpe.fullstack.preview`, Dockerfiles, compose, `scripts/preview.sh`) | built-artifact preview starts + passes E2E locally; compose builds + passes E2E in CI; artifact digest bound to candidate digest, mismatch fails closed |
| 13 | Full-stack reviewer roles + permission enforcement (six lenses, read-only proven) | permission proofs mutation-tested; roster enforced |
| 14 | TRAJ-FS trajectory rules + drift extensions + 12 planted fixtures | every planted fixture caught by its intended rule; good run clean |
| 15 | Integrated V3 orchestration: engine stages for journey/web-evidence/preview + `pmpe eng` surface | stage machine tests; full synthetic V3 run trajectory-clean |
| 16 | Dogfood run: pm-evals Web driven through V3 (contract→journey→plans→tests-first→freeze→reviews→fixes→traceability→browser+preview verification→draft PR→release decision) | the run's evidence ledger + artifacts committed as the dogfood record; defects fixed via reviewed PRs |
| 17 | Final evidence pack, demo instructions, docs, ledger closure, V3 contribution report | pack complete (approved contract, UX architecture, screen/state inventory, API contract, requirement traceability, executed backend/frontend/browser-journey/accessibility/responsive evidence, assurance findings + decisions, candidate + preview digests, release verdict, known limitations, human decisions, demo instructions); demo path documented; definition-of-done checklist confirmed |

Deviations from this partition require the scope analysis recorded in the PR
body. PRs 4–5 (backend) and 6–11 (frontend/E2E) each leave `main` green and
independently usable: the engine as a library, the API standalone, the UI
against the real API from PR 7 onward.

## CI evolution

- PR 4: `product-backend` job (pytest for `products/pm-evals-web/backend`).
- PR 6: `product-frontend` job (npm ci, tsc, vitest, next build) plus
  `npm audit --audit-level=high` (blocking on high severity, informational
  otherwise — parity with the pip-audit policy; threat T9).
- PR 6: `api-contract` step (schema diff fails on mismatch).
- PR 11: `product-e2e` job (start backend+frontend, Playwright chromium).
- PR 12: `product-preview` job (docker compose build + E2E against containers).
All jobs additive; existing jobs untouched.
