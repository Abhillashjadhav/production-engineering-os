# PD-V3-15 — Lens 5 (Product-Contract Conformance) — CAND-001

## Candidate digest verification

Recorded from the run dir's `candidate-manifest.json`:

- **candidate**: CAND-001, commit `243eddf72005f6f23ed70142053adbd27f7ae3c3`
- **tree_digest**: `sha256:3af7832792afa78c12aa88efab6030ebfeafdd45eb75f45c3d9a943470c03bcb`
- **contract_digest**: `sha256:f01af9c278d32e5c3c953f151662958c8580f109938e44016ac802dc563bad6f`

Cross-checks performed (read-only toolset; no hashing runtime available, so consistency was verified against the run's own executed records rather than recomputed): contract_digest matches the ledger `contract_lock` output (ledger.jsonl line 1) and `fullstack-run-state.json`; the run-dir `fullstack-contract.json` is line-for-line identical to `tests/fixtures/v3/fullstack_contract_approved.json`; tree_digest matches the ledger `freeze` output (line 19) and is the bound input of the `browser_verification` (line 20, verdict `passed`, `mocked=false`) and `preview` (line 21) events. Digest chain internally consistent.

## Findings (8)

1. **MAJOR — GATE-4 FAIL: reports are not identical for identical inputs.** `products/pm-evals-web/backend/src/pm_evals_api/app.py:162` injects `datetime.now()` into every `/api/report` response and `report.py:43-44` embeds it ("Generated at: …" / `generated_at`). Scenario: download the same comparison twice → byte-different Markdown/JSON. No executed test compares two report generations — such a test would fail. ProductChangeRequest: omit the timestamp or amend the gate text.
2. **MAJOR — Mobile requirement tested at the wrong viewport.** Contract requires 375px; the only executed mobile check runs the iPhone 12 profile at 390x844 (`products/pm-evals-web/e2e/playwright.config.ts:37`, `responsive.spec.ts:1-4`). The 375px no-horizontal-scroll property was never exercised → R-2 and GATE-3 NOT_PROVEN.
3. **MAJOR — Unit-suite execution is not evidence-bound to the candidate.** No test-run record with a verdict exists in the run dir (ledger `implement` events carry no verdicts). `products/pm-evals-web/backend/.pytest_cache/v/cache/lastfailed` is non-empty (`"tests/test_api.py::TestClient": true` — last cache-writing run not green), and the vitest cache `products/pm-evals-web/frontend/node_modules/.vite/vitest/da39a3ee.../results.json` records `tests/race-probe.test.tsx`, a file absent from the frozen tree — the recorded run was of a different tree state. Everything backed only by pytest/vitest (413 size cap, no-persistence, verdict determinism, filter behavior) is NOT_PROVEN.
4. **MAJOR — Preview is not the contracted artifact and its digest is unreconciled.** Contract deployment_target is `containerized_preview` (Docker Compose built from the frozen candidate); executed evidence records `deployment_kind: "local_preview"` (`preview-evidence.json:6`; ledger line 21 `kind=local_preview`). No compose build was executed. The preview source digest `sha256:6db7fc0e…` is scoped to backend/+frontend/ tracked files only (`scripts/preview_evidence.py:31-49`) and no executed record reconciles it to the frozen tree digest `sha256:3af78327…` → deployment target and the "digest-identical" guardrail NOT_PROVEN.
5. **MEDIUM — J-4 incompatible-pair half unproven and reinterpreted.** The only executed incompatible case surfaces as a HOLD verdict with reasons (`e2e/tests/journey.spec.ts:90-104`), not the contract's "clear validation errors" on S-1; the client pair-issues block (`frontend/src/components/upload-form.tsx:230-235`) is never exercised by executed evidence. Ambiguity flagged for the product owner.
6. **MEDIUM — J-7 filter half unexercised.** The filter input and direction select (`frontend/src/components/trace-explorer.tsx:89-111`) are touched by no executed browser test (journeys only click a trace button); the only claimed coverage is the digest-unbound vitest run (finding 3). Filtering behavior NOT_PROVEN.
7. **MAJOR — S-3 does not deliver its contracted purpose.** Contract: "per-criterion baseline vs candidate results and the evidence fields." The detail renders only flipped criteria as "now passes/now fails" (`trace-explorer.tsx:139-148`); unchanged criteria's baseline-vs-candidate results and the uploads' evidence fields (`label`/`notes`, `backend/src/pm_evals_compare/models.py:35-38`) are never shown — the `Comparison` payload does not even carry them. FAIL → ProductChangeRequest.
8. **MINOR — Declared UI states missing or unevidenced.** S-3 "loading" is not implemented at all (component is synchronous) — FAIL for that declared state; S-2 "loading"/"error" exist only as S-1's status/alert region (ambiguous screen ownership); S-1 "loading", S-3 "empty"/"error", and the "loading announced to AT" accessibility clause have no executed assertion — NOT_PROVEN.

## Verdict table

Evidence roots: `L20`/`L21` = ledger.jsonl browser_verification/preview events; e2e = `products/pm-evals-web/e2e/tests/`.

| Item | Verdict | Evidence pointer |
|---|---|---|
| **Journey** | | |
| J-1 | PASS | e2e/a11y.spec.ts:19-23 + L20 |
| J-2 | PASS | e2e/helpers.ts:20 (every executed journey) + L20 |
| J-3 | PASS | e2e/helpers.ts:21 + L20 |
| J-4 | NOT_PROVEN | e2e/journey.spec.ts:90-104 (finding 5) |
| J-5 | PASS | e2e/keyboard.spec.ts:36-42 + L20 |
| J-6 | PASS | e2e/journey.spec.ts:23-49 + L20 |
| J-7 | NOT_PROVEN | e2e/journey.spec.ts:45-48 inspect only (finding 6) |
| J-8 | PASS | e2e/journey.spec.ts:106-130 + L20 |
| J-9 | PASS | e2e/keyboard.spec.ts:61-64 + L20 |
| **Screens/states** | | |
| S-1 empty/error/success | PASS | e2e/a11y.spec.ts:19-34; keyboard.spec.ts:72-75 |
| S-1 loading | NOT_PROVEN | upload-form.tsx:258-260, no executed assertion (finding 8) |
| S-2 success / insufficient-evidence | PASS | e2e/journey.spec.ts:23-49 / :51-61 |
| S-2 loading/error | NOT_PROVEN | hosted in S-1 region only (finding 8) |
| S-3 success | PASS | e2e/journey.spec.ts:45-48 + keyboard.spec.ts:47-52 |
| S-3 empty/error | NOT_PROVEN | trace-explorer.tsx:67-74, 149-154, unexercised (finding 8) |
| S-3 loading | FAIL | not implemented (finding 8) |
| S-3 purpose (baseline-vs-candidate + evidence fields) | FAIL | trace-explorer.tsx:139-148 (finding 7) |
| **Backend capabilities** | | |
| BC-1 | NOT_PROVEN | app.py:34,57-64 implemented; cap/in-memory only pytest-backed (finding 3) |
| BC-2 | PASS | e2e/journey.spec.ts:63-104 vs real backend + L20 |
| BC-3 | PASS | e2e/journey.spec.ts:29-32 (payload-true numbers) |
| BC-4 | PASS | e2e/journey.spec.ts:23-61 (all three verdicts + T-006 evidence) |
| BC-5 | PASS | e2e/journey.spec.ts:106-130 |
| E-1/E-2 persistence "none" | NOT_PROVEN | backend/tests/test_api.py:145-154 unbound (finding 3) |
| **API contracts** | | |
| API-1 POST /api/compare | PASS | L20 (`mocked=false`) + app.py:118; schema "current" ledger line 18 |
| API-2 POST /api/report | PASS | e2e/journey.spec.ts:106-130 + app.py:134 |
| API-3 GET /api/health | PASS | L21 (scripts/preview.sh:31-40 health-gated) + app.py:106 |
| **Accessibility** | | |
| Labels on all controls | PASS | e2e/a11y.spec.ts (axe, all screens) + L20 |
| Keyboard-only + visible focus | PASS | e2e/keyboard.spec.ts:28-65 + L20 |
| Axe on every journey screen | PASS | e2e/a11y.spec.ts:19-52 + L20 |
| Status changes announced | NOT_PROVEN | keyboard.spec.ts:67-76 covers verdict/errors, not loading (finding 8) |
| **Responsive** | | |
| Desktop >=1280px | PASS | playwright.config.ts:29-31 (Desktop Chrome) + L20 |
| Mobile 375px | NOT_PROVEN | playwright.config.ts:37 runs 390px (finding 2) |
| **Release gates** | | |
| GATE-1 | PASS | L20 + journey/keyboard specs spanning J-1..J-9 vs built `next start` artifact |
| GATE-2 | PASS | e2e/journey.spec.ts:23-61 + L20 |
| GATE-3 | NOT_PROVEN | mobile check at wrong viewport (finding 2) |
| GATE-4 | FAIL | app.py:162 + report.py:43-44 (finding 1) |
| **Guardrails** | | |
| Deterministic verdict | NOT_PROVEN | test_api.py:139-142 exists, execution unbound (finding 3) |
| No third-party egress | NOT_PROVEN | no egress found in src (grep clean), no executed check exists |
| No permanent storage | NOT_PROVEN | test_api.py:145-154 unbound (finding 3) |
| No unsupported numerical claim | PASS | e2e/journey.spec.ts:30-31, 106-122 pin UI/report numbers to engine |
| No verdict without trace evidence | PASS | e2e/journey.spec.ts:35-49 (T-006 evidence asserted) |
| Accessible journey | PASS | a11y + keyboard suites + L20 |
| Responsive desktop+mobile | NOT_PROVEN | finding 2 |
| Digest-identical reviewed/tested/deployed | NOT_PROVEN | preview-evidence.json:4 vs manifest tree_digest (finding 4) |
| **Deployment target** | | |
| containerized_preview (Docker Compose) | NOT_PROVEN | preview-evidence.json:6 records `local_preview`; compose never executed (finding 4) |
| **Out of scope (11 exclusions)** | PASS | no auth/storage/billing/analytics/sharing found in `frontend/src` or `backend/src`; grep for external URLs clean |

**Summary**: 26 PASS, 15 NOT_PROVEN, 3 FAIL. The executed browser chain (ledger lines 20-21) is strong for the happy-path journey, verdicts, downloads, axe, and keyboard; the candidate cannot be called conformant on GATE-4 (report determinism, by design of the timestamp injection), S-3's contracted detail content, the 375px mobile requirement, the containerized preview, or anything whose only proof is the digest-unbound unit-test caches.
