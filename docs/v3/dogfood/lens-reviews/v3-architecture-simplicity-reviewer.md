# PD-V3-15 — Lens 4 (Architecture & Simplicity) — CAND-001

All evidence below was read from the frozen tree at commit `243eddf72005f6f23ed70142053adbd27f7ae3c3`.

## Candidate digest (verified)

- CAND-001, commit `243eddf72005f6f23ed70142053adbd27f7ae3c3`
- Tree digest `sha256:3af7832792afa78c12aa88efab6030ebfeafdd45eb75f45c3d9a943470c03bcb` — matches the ledger's `freeze` output digest and the `browser_verification`/`preview` input digests; contract digest `sha256:f01af9c2...bad6f` matches the `contract_lock` entry. No shell is available in this session, so the tree hash was cross-checked against the ledger, not recomputed.

## Findings

**F-1 (Medium) — Executed-evidence decoders absent; browser/preview verdicts are asserted, not decoded (architecture drift).**
`docs/v3/architecture.md:19` lists `web_evidence.py` ("Vitest/Playwright/axe executed-evidence decoders") and lines 99–102 promise JSON-reporter results "decoded into the same executed-evidence model." No `web_evidence.py` exists under `src/pmpe/fullstack/`; `products/pm-evals-web/e2e/playwright.config.ts:20` configures `reporter: [["list"]]` only; `products/pm-evals-web/scripts/preview.sh:51` and `.github/workflows/ci.yml:184` pass hardcoded `--journeys a11y=passed keyboard=passed responsive=passed journeys=passed`; `src/pmpe/fullstack/orchestration.py:233` takes `passed: bool` from the caller. Scenario: a suite that silently skips (wrong testMatch, filtered project) still records "passed" per suite — the only real gate is the shell exit code of the preceding step. Per-suite verdicts in the evidence pack are NOT_PROVEN as executed properties.

**F-2 (Medium) — Preview digest binds sources, not built artifacts; no backend wheel exists (architecture drift).**
`docs/v3/architecture.md:107-112,119-125` requires a digest "over the built artifact inventory (frontend build output manifest + backend wheel) recorded at build time, re-computed at preview start." Implemented: `products/pm-evals-web/scripts/preview_evidence.py:34-49` digests git-tracked *source* files; the only build fingerprint is Next's `BUILD_ID` (an opaque token, not a content digest, `preview_evidence.py:75`); `preview.sh:20` runs the backend from source via `PYTHONPATH=src` — no wheel is built anywhere. Scenario: `.next/` or installed backend code modified between build and serve verifies clean; the documented fail-closed property holds only for sources.

**F-3 (Low-Medium) — The mirror's fail-open invariant rests on hand-synced constants with no cross-seam guard.**
The mirror is contained and honest today (single module, blocking vs advisory channels, authority declared at `frontend/src/lib/validate.ts:2-23`, fail-open paths executed e2e via `journey.spec.ts` fixtures). But `validate.ts:25-26` duplicates `MAX_UPLOAD_BYTES` (`backend/src/pm_evals_api/app.py:34`) and `FORMAT_VERSION` (`backend/src/pm_evals_compare/models.py:17`), and mirrors refusal strings character-for-character (`compare.py:78-85` ↔ `validate.ts:155-174`) with no parity test on either side. Scenario: backend raises its limit to 10 MB — the client now *blocks* a file the server accepts, silently violating the mirror's own documented fail-open rule.

**F-4 (Low) — Layout/config drift from the accepted architecture, undocumented.**
`docs/v3/architecture.md:25` places the product contract at `products/pm-evals-web/contract.json` — it lives at `tests/fixtures/v3/fullstack_contract_approved.json` (a test-fixture path for the locked product contract). `architecture.md:36` names `Dockerfile.backend, Dockerfile.frontend, compose.yaml` — actual: `backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml`. `architecture.md:88` says "CSS modules" — actual: one global stylesheet (`frontend/src/app/globals.css`), no `*.module.css`. All work; all are undeclared deviations.

**F-5 (Low) — Stale phase comments contradict the delivered structure.**
`products/pm-evals-web/frontend/src/components/upload-form.tsx:269` — "The full evidence dashboard (S-2, J-6) renders here in PR 8" (it renders in `workspace.tsx:27`); `frontend/src/app/page.tsx:6` — "Downloads (J-8) land in PR 9" (`DownloadPanel` ships, `workspace.tsx:28-32`). Scenario: a maintainer hunting the S-2 render site is pointed at the wrong component.

**F-6 (Low) — Configuration/API surface nobody sets.**
`backend/src/pm_evals_compare/compare.py:31` `hard_gate_coverage` field: settable by no caller (always default 1.0; not exposed via API or UI). `backend/src/pm_evals_compare/models.py:54` `hard_gate_ids()`: zero callers. `frontend/src/lib/api.ts:119` `health()`: no production caller (health is consumed by curl/Docker healthcheck only); traceable to requirement NONE for the client function.

NOT_PROVEN annotation (no defect asserted): the claim that the containerized compose path "runs in CI" (`docker-compose.yml:1-3`, `preview.sh:6`) has a defined job (`ci.yml:155-214`, and the backend `HEALTHCHECK` wiring for `service_healthy` is present) but this run's ledger records only `kind=local_preview` — containerized execution is unevidenced for CAND-001.

## Complexity Ledger — web surface

| Component | Verdict | Justification |
|---|---|---|
| `pm_evals_compare` (models/compare/report) | KEEP | Pure engine, stdlib+pydantic, serves BC-2..BC-5, PD-V3-04/05/07 |
| `pm_evals_api/app.py` (factory + 3 routes) | KEEP | Thin transport over the engine; API-1..3 exactly, nothing more |
| `scripts/export_openapi.py` | KEEP | Regenerates the committed contract; parity enforced by `test_api.py:157` in CI |
| Backend deps (pydantic, fastapi, python-multipart, uvicorn; dev: pytest/mypy/ruff/httpx) | KEEP | Each traceable (multipart uploads, ASGI, TestClient) |
| `CompareConfig.hard_gate_coverage`, `hard_gate_ids()` | QUESTION | No caller/setter — F-6 |
| Frontend deps (next/react/react-dom; dev: vitest, testing-library, jsdom, openapi-typescript, tsc) | KEEP | 3 runtime deps; no state manager, no design system — matches architecture:88 |
| `lib/api.ts` typed client | KEEP | OpenAPI-derived, CI-guarded (`ci.yml:105-108`); `health()` export QUESTION (F-6) |
| `lib/api-types.gen.ts` | KEEP | Generated, drift fails CI |
| `lib/validate.ts` mirror | KEEP | Locked decision; contained + honest; constant coupling unguarded (F-3) |
| Components (workspace, upload-form, dashboard, trace-explorer, download-panel, explainer) | KEEP | 1:1 with contract screens/journey steps; no single-caller abstraction layers; small duplicated error-list render (upload-form:244-254 ≈ download-panel:92-102) below abstraction threshold |
| `next.config.mjs` rewrite (BACKEND_URL) | KEEP | Same-origin seam; build-time bake honestly documented in Dockerfile:2-4, playwright.config.ts:41-44 — exemplary seam honesty |
| e2e (@playwright/test + @axe-core/playwright only; 4 specs + 1 helper) | KEEP | PD-V3-09/10; chromium-only mobile seam documented |
| Dockerfiles + docker-compose.yml | KEEP | Deployment unit per architecture:129; CI execution NOT_PROVEN this run |
| `scripts/preview.sh` + `preview_evidence.py` | QUESTION | Structure fine; evidence semantics drift — F-1, F-2 |

Net judgment: the delivered web surface is close to minimal for the approved outcome — the complexity findings concentrate on the evidence/preview seam and documentation drift, not on excess product structure. No fixes were made.

Digest recorded: `sha256:3af7832792afa78c12aa88efab6030ebfeafdd45eb75f45c3d9a943470c03bcb` (CAND-001, `243eddf72005f6f23ed70142053adbd27f7ae3c3`).
