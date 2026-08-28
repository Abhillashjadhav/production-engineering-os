# S-3 Trace Detail — requirement traceability

This PR completes screen **S-3 (Trace Detail)** of the locked
FullStackProductContract (`tests/fixtures/v3/fullstack_contract_approved.json`).
It resolves finding **P-1** from the dogfood verification report
(`docs/v3/dogfood/verification-report.md`) — which is preserved unchanged as
audit history; the frozen candidate `243eddf72005` keeps its valid `HOLD`
verdict. This PR is the separate follow-up that finding called for.

## Contract requirement

- **Screen S-3 "Trace Detail"** — purpose: *"Inspect one changed trace:
  per-criterion baseline vs candidate results and the evidence fields."*
- **States:** empty, loading, error, success.
- **Journey J-7** — inspect a changed trace.

Gap (P-1): the old UI rendered only the *flipped* criteria and a flip
direction; the payload carried only trace-id lists, so unchanged per-criterion
results and the trace's evidence fields never reached the UI.

## Implementation → evidence

| Contract element | Implementation | Executed evidence |
|---|---|---|
| per-criterion baseline vs candidate results, every criterion | `pm_evals_compare.compare` — `CriterionCell` + `TraceComparison`, `Comparison.trace_details` (verdict logic in the domain, PD-V3-04) | `backend/tests/test_compare.py::test_a_changed_trace_lists_every_shared_criterion_not_only_flips`, `::test_every_criterion_cell_state_is_computed_in_the_domain` |
| the evidence fields (label, notes), both sides | `TraceComparison.baseline_label/notes`, `candidate_label/notes` | `test_compare.py::test_trace_detail_carries_both_sides_evidence_fields`; e2e `journey.spec.ts` (GDPR label surfaced) |
| edge states: missing, conflicting, insufficient, not-evaluated | `_criterion_cell` state machine (7 states) | `test_compare.py::test_every_criterion_cell_state_is_computed_in_the_domain` |
| API carries the detail | `openapi.json` regenerated; `/api/compare` response | `test_api.py::test_compare_response_carries_per_trace_criterion_details`; committed-schema byte pin |
| frontend renders the typed contract only (no re-comparison) | `components/trace-explorer.tsx` renders `trace_details` as a `<table>` | `frontend/tests/trace-explorer.test.tsx` (9 cases) |
| S-3 success / empty / loading / error states | `TraceExplorer` branches; loading wired via `UploadForm.onLoadingChange` → `Workspace` | `trace-explorer.test.tsx` (empty/loading/error); e2e `journey.spec.ts` (success) |
| accessibility: labels, keyboard, visible focus, axe, table semantics | `<table>` caption + `<th scope>`; `.table-scroll` | e2e `a11y.spec.ts::S-3 trace detail is axe-clean`, `keyboard.spec.ts` (Tab to trace, Enter opens detail) |
| responsive: 375px mobile, no page overflow | `.table-scroll { overflow-x: auto }`, `table { min-width }` | e2e `responsive.spec.ts::the S-3 criterion table does not overflow the page at 375px` |
| determinism (PD-V3-07) | sorted iteration, no clock | `test_compare.py::test_trace_details_are_deterministic`; golden fixtures byte-pinned |
| typed client / golden fixtures in sync | `api-types.gen.ts`, `frontend/tests/fixtures/comparison_*.json` regenerated | drift check + `test_golden_fixtures.py` |

## Known bound (independent-review note)

`trace_details` is eager: O(changed traces × shared criteria) full cells, each
carrying prose verdict + rationale. It is bounded by the input (MAX_TRACES=5000 ×
MAX_CRITERIA=200) and the 5 MB upload cap, but a pathological all-changed input
yields a large `/api/compare` response (~10–20× amplification vs the old
trace-id lists). Realistic inputs (a handful of changed traces) are small. If
this becomes a problem, the follow-up is an on-demand per-trace detail endpoint
rather than eager inclusion; not needed for the current contract ("inspect one
changed trace").

## Out of scope (separate follow-ups, not started here)

422 wire-shape vs OpenAPI, size-cap-before-parse + parser differentials
(duplicate-key / NaN), backend lockfile, containerized-preview execution.
