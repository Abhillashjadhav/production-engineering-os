# PD-V3-15 — Lens 2 (Frontend Correctness + Accessibility) — CAND-001

**Digest verification.** `/tmp/claude-0/.../scratchpad/dogfood/run/candidate-manifest.json`: candidate CAND-001, commit `243eddf72005f6f23ed70142053adbd27f7ae3c3` — matches the `243eddf72005` prefix I was given. Verified tree digest: **`sha256:3af7832792afa78c12aa88efab6030ebfeafdd45eb75f45c3d9a943470c03bcb`**. The ledger's `browser_verification` event (`ledger.jsonl:20`) binds its execution to this same digest (`input_digests.candidate`), `mocked=false`, suites `a11y,keyboard,responsive,journeys`, verdict `passed`; corroborated by `preview-evidence.json` (all four suites passed, local_preview). Evidence is EXECUTED, not merely claimed.

No injection sinks found: zero `dangerouslySetInnerHTML`/`innerHTML`/`href=` in `frontend/src`; filenames, server messages, and payload strings render only as JSX text nodes; the one built URL is a `createObjectURL` blob URL (`download-panel.tsx:29`).

## Findings

**F1 — MEDIUM — `products/pm-evals-web/frontend/src/components/upload-form.tsx:113-146` — stale file-read race: last-*completed* read wins, not last-*selected*.** `handleSelect` has no per-source generation token; `pendingReads` only blocks submit *while* reads are in flight. Scenario: user picks a large baseline A (slow read), immediately re-picks small B; B's read applies first, then A's late completion overwrites state at line 143. After both settle, `pendingReads===0`, the note shows A, and submit sends A — while the file input and the user's intent hold B. The line 78-83 comment claims this window is closed; it is not.

**F2 — MEDIUM — `products/pm-evals-web/frontend/src/lib/api.ts:45-53` — typed-client discipline: the 422 parser depends on a `detail` wrapper absent from the generated contract types.** `api-types.gen.ts:230-238` declares the 422 body as top-level `ValidationProblem[]`; the backend actually emits FastAPI's `{"detail": [...]}` (`backend/src/pm_evals_api/app.py:85`), so the client reads `body.detail` — a shape the contract does not document (the generated 422 type is dead/wrong). The subsequent `detail as ValidationProblem[]` cast validates only `"source" in p`, not `issues`; a source-bearing entry without an `issues` array would throw at `upload-form.tsx:246` / `download-panel.tsx:94` (`problem.issues.map`), collapsing the error state.

**F3 — MINOR — `products/pm-evals-web/frontend/src/lib/api.ts:30-35` — fallback misattributes framework 422s to the baseline file.** `frameworkFallback` hardcodes `source: "baseline"`; a missing *candidate* part or bad form field renders as "**baseline**: The request was not accepted…" (`upload-form.tsx:249`), pointing the user at the wrong file.

**F4 — MINOR (a11y) — `products/pm-evals-web/frontend/src/components/upload-form.tsx:258-259` and `download-panel.tsx:84-88` — `role="status"` live regions are conditionally mounted with their initial content.** Live regions inserted into the DOM already containing text are inconsistently announced across AT/browser pairs; the region should exist before its content changes. The executed check (`e2e/tests/keyboard.spec.ts:67-76`) asserts only role/`aria-live` attributes and text presence, so it cannot catch a missed announcement. (Error paths use `role="alert"`, which is announced on insertion — those are fine.)

**F5 — MINOR (evidence) — `products/pm-evals-web/e2e/playwright.config.ts:37` — mobile evidence runs at 390px, contract declares 375px.** The `mobile-chromium` project uses the iPhone 12 profile (390x844); `responsive.spec.ts` therefore never exercised the contract's 375px viewport. Practical risk is low (`globals.css:90-92` makes the table self-scrolling ≤480px; `overflow-wrap:anywhere` on digests), but the declared viewport was not executed.

**F6 — MINOR (a11y) — `products/pm-evals-web/frontend/src/components/trace-explorer.tsx:126` — `aria-expanded` without `aria-controls`.** Trace buttons toggle a detail region rendered after the whole list (`:136-156`); AT users get an "expanded" announcement with no programmatic link to what expanded.

State machines otherwise sound: every handoff transition passes through `null` (`upload-form.tsx:116,154`), so Dashboard/DownloadPanel/TraceExplorer unmount and reset — no stale verdict, filter, or download error can survive a new comparison; loading disables inputs and hides reset; error and success states are mutually exclusive by construction. `pct`/`signedPct` (`dashboard.tsx:17-25`) preserve sign (including −0 → unsigned zero) and never invent values; all rendered numbers come straight from the typed payload.

## Contract checklist

| Requirement (contract `tests/fixtures/v3/fullstack_contract_approved.json:58-67`) | Verdict | Evidence |
|---|---|---|
| Every form control has an accessible label | **PASS** | `upload-form.tsx:195,213`, `trace-explorer.tsx:91,100` (explicit `htmlFor`/`useId`); axe suite executed clean on all four screens (`a11y.spec.ts`, ledger `browser_verification` passed) |
| Primary journey completable keyboard-only, visible focus | **PASS** | `keyboard.spec.ts:28-65` executed (ledger): Tab-*reachability* to submit/trace/download/reset, Enter activation, 3px outline asserted; `globals.css:29` `:focus-visible`. Caveat: focus visibility asserted on one control only; file pick uses `setInputFiles` (OS dialog, standard limit) |
| Axe passes on every screen of the primary journey | **PASS** | `a11y.spec.ts:19-52` covers S-1 empty, S-1 error, S-2+downloads, S-3 detail against real build + real backend; EXECUTED per `ledger.jsonl:20` (`mocked=false`, passed) — not merely claimed |
| Status changes announced to AT | **NOT_PROVEN** | Errors: PASS pattern (`role="alert"` on insertion). Loading/verdict: mechanism present (`role="status"` `aria-live="polite"`, `upload-form.tsx:259`) but conditionally mounted (F4), and the executed test checks attributes/text only, not announcement behavior |
| Responsive: desktop ≥1280px / mobile 375px no horizontal scroll | **PASS** (desktop) / **NOT_PROVEN** (375px) | Desktop Chrome project (1280px) ran all non-responsive suites, passed. Mobile executed only at 390px (F5); `responsive.spec.ts:8-16` overflow assertions passed there, 375px never run |

**Candidate digest verified: `sha256:3af7832792afa78c12aa88efab6030ebfeafdd45eb75f45c3d9a943470c03bcb` (CAND-001, commit `243eddf72005f6f23ed70142053adbd27f7ae3c3`).** No ProductChangeRequest flags. Findings only — nothing fixed.
