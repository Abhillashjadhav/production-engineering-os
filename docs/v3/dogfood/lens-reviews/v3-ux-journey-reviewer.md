# PD-V3-15 — Lens 1 (UX Journey Conformance) — CAND-001

## Digest verification (done first)

- Manifest at the run dir matches the briefing: candidate `CAND-001`, commit `243eddf72005f6f23ed70142053adbd27f7ae3c3`; `candidates/CAND-001.json` is field-identical.
- Validated-journey record (`ux-architecture.json:2`) is bound to the SAME contract digest as the manifest (`sha256:f01af9c2…bad6f`) — charter's blocking check passes. The run-dir `fullstack-contract.json` is textually identical to `tests/fixtures/v3/fullstack_contract_approved.json`. Ledger (`ledger.jsonl` lines 1, 19–20) binds contract lock, freeze, and browser verification to the same contract digest and tree digest `sha256:3af78327…3bcb`. Note: my toolset is read-only (no hash execution), so this is metadata/textual cross-verification, not cryptographic recomputation.

## Findings

**F-1 — MAJOR — J-7 / S-3** — `products/pm-evals-web/frontend/src/components/trace-explorer.tsx:136-156` (data ceiling at `frontend/src/lib/api-types.gen.ts:90-126`, source fields at `backend/src/pm_evals_compare/models.py:31-37`). The Trace Detail does not deliver S-3's contract purpose — "per-criterion baseline vs candidate results and the evidence fields" — it renders only the criteria that *flipped* plus a flip direction; unchanged per-criterion results and the trace's evidence fields (`label`, `results`, `notes`) never reach the UI because the Comparison payload carries only trace-id lists. Scenario: a PM opens T-006 expecting to see each criterion's baseline vs candidate outcome and the trace's evidence; they see only "C-GROUNDED — now fails" and cannot judge the rest of the trace. Fix requires an API/payload change to approved behaviour — ProductChangeRequest, not a code fix.

**F-2 — MINOR — S-3 declared state "loading"** — `trace-explorer.tsx:59-86`. S-3 declares a `loading` state (contract `screens[2].states`) that has no implementation and is unreachable: the explorer renders synchronously from the in-memory payload with no loading branch. Scenario: contract/state audit finds a declared state no user or test can ever observe; reconciling the declaration is a ProductChangeRequest.

**F-3 — MINOR — J-7 browser-E2E coverage (GATE-1)** — no spec in `products/pm-evals-web/e2e/tests/` touches the "Filter changed traces" input or the "Show" select (grep: zero matches); every browser path clicks a trace button directly (`journey.spec.ts:45`, `keyboard.spec.ts:46`, `a11y.spec.ts:49`, `responsive.spec.ts:29`). Filtering is proven only in jsdom (`frontend/tests/trace-explorer.test.tsx:24-48`). Scenario: the filter half of J-7 regresses in the real build and GATE-1's "full primary journey passes browser E2E" still reports green.

**F-4 — MINOR — J-1 wording overclaim** — `frontend/src/lib/explainer.tsx:28-29`: "no data leaves this app." The "never stored" half is backend-tested (`backend/tests/test_api.py:145`, `test_uploads_leave_no_residue`), but no test verifies the no-third-party-egress guardrail the sentence rests on. Scenario: a dependency adds telemetry; the promise shown to the user is now false and nothing red-flags it.

**F-5 — MINOR — Preview evidence vs contract deployment target** — `preview-evidence.json:6` records `deployment_kind: "local_preview"` (ledger line 21 `kind=local_preview`) while the contract declares `containerized_preview` (Docker Compose, contract lines 84–87); additionally the evidence's `source_digest` (`sha256:6db7fc0e…`) does not textually match the frozen `tree_digest` (`sha256:3af78327…`) — journey "passed" claims bind to the candidate only via the ledger's input digest. Scenario: E2E green is claimed for an artifact whose binding to the frozen tree the evidence file itself cannot prove. Primary owner is the evidence-integrity lens; recorded here because every per-step PASS leans on it.

**F-6 — NOTE — Ledger journey-record digest is self-referential** — `ledger.jsonl` line 2: `journey_validation` output digest for `journey_record` is byte-identical to the contract digest, which cannot be the digest of `ux-architecture.json`'s own content (it contains `validated_at`). Binding-by-content is not established; for the evidence-integrity lens.

**F-7 — NOTE — Stale build-plan comments misdescribe implemented surface** — `frontend/src/app/page.tsx:6` ("Downloads (J-8) land in PR 9") and `frontend/src/components/upload-form.tsx:269` ("dashboard … renders here in PR 8") both describe surfaces as future/elsewhere though they ship in `workspace.tsx:27-33`. No user impact; misleads maintainers auditing step coverage.

**F-8 — NOTE — S-2 loading/error render inside the S-1 form region** — `upload-form.tsx:241-276`: the dashboard's declared `loading`/`error` states exist only as the S-1 compare-status (`role=status`) and API alert (`role=alert`); acceptable on a single page and recovery never requires a reload (error resets phase to `empty`, form stays usable; downloads clear errors on retry, `download-panel.tsx:48-63`), but S-2 itself has no loading/error surface.

## Per-step verdicts

| Step | Verdict | Evidence |
|---|---|---|
| J-1 | PASS | `frontend/src/lib/explainer.tsx:2-33` rendered at `app/page.tsx:10`; `e2e/tests/a11y.spec.ts:19-23` |
| J-2 | PASS | labeled baseline file input, `upload-form.tsx:194-211` |
| J-3 | PASS | labeled candidate file input, `upload-form.tsx:212-229` |
| J-4 | PASS | fail-open mirror `lib/validate.ts:69-179` + server-error alert `upload-form.tsx:241-256`; `journey.spec.ts:63-104` |
| J-5 | PASS | gated submit `upload-form.tsx:99-106,236-238`; keyboard activation `keyboard.spec.ts:34-42` |
| J-6 | PASS | verdict/reasons/evidence traces, rates, deltas `dashboard.tsx:31-156`; payload-true numbers `journey.spec.ts:23-49` |
| J-7 | FAIL | detail lacks contract-declared per-criterion baseline-vs-candidate results and evidence fields (F-1), `trace-explorer.tsx:136-156` |
| J-8 | PASS | `download-panel.tsx:43-107`; download integrity `journey.spec.ts:106-130` |
| J-9 | PASS | reset without auth `upload-form.tsx:174-181,270-272`; keyboard path `keyboard.spec.ts:61-64` |

Screen states: S-1 empty/loading/error/success all reachable and honest (`upload-form.tsx:23,72,183-276`); S-2 success and insufficient-evidence reachable (`dashboard.tsx:66-72`, `journey.spec.ts:51-61`), loading/error hosted in the S-1 region (F-8); S-3 empty/error/success reachable (`trace-explorer.tsx:67-74,113-114,149-154`; honest no-evidence error unit-tested at `frontend/tests/trace-explorer.test.tsx:91-104`), loading declared but unreachable (F-2).

## Candidate digest verified

- Candidate: `CAND-001`, commit `243eddf72005f6f23ed70142053adbd27f7ae3c3`
- Contract digest: `sha256:f01af9c278d32e5c3c953f151662958c8580f109938e44016ac802dc563bad6f` (matches validated-journey record and ledger)
- Tree digest: `sha256:3af7832792afa78c12aa88efab6030ebfeafdd45eb75f45c3d9a943470c03bcb`
