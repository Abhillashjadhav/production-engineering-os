# V3 threat model — pm-evals Web and the full-stack adapter

Scope: the product accepts untrusted files from a browser and renders derived
content; the adapter executes toolchains (npm, Playwright) against candidate
workspaces. No authentication exists by decision (PD-V3-12), so every control
is data-plane, not identity-plane.

## Assets

Uploaded eval-run content (potentially sensitive product data), the verdict's
integrity (the product's whole value), the evidence chain (digests, executed
results), and the host running verification.

## Threats and controls

| # | Threat | Control | Verified by |
|---|--------|---------|-------------|
| T1 | Uploaded data exfiltrated to third parties | No external egress in the backend; no analytics, fonts, or CDN calls in the frontend; API client talks only to its own origin | dependency/egress review lens; E2E network assertions; TRAJ-FS storage/egress rule |
| T2 | Uploaded data persisted | In-memory processing only; no file writes of upload content; no server-side session store in product V1 | backend tests asserting no filesystem writes during compare; planted-failure trajectory rule (uploaded data written to permanent storage) |
| T3 | Malicious JSON: oversized payloads (DoS) | Hard request-size limit and per-file size limit at the API boundary; bounded trace counts with an explicit validation error | API tests with oversized fixtures |
| T4 | Malicious JSON: deeply nested / pathological structures | Schema validation with depth/shape constraints before domain processing; pydantic strict types | backend fuzz-shaped fixture tests |
| T5 | Stored/reflected XSS via uploaded strings rendered in the dashboard (trace labels, criterion descriptions, notes) | React's default escaping; no `dangerouslySetInnerHTML`; Markdown report renders user strings as code/escaped text, never interpreted HTML | frontend component tests with hostile strings; E2E fixture containing `<script>`/HTML-injection labels |
| T6 | Verdict tampering between compare and report | Reports are regenerated deterministically from the same inputs server-side; the JSON report embeds the input digests it was computed from | determinism tests (PD-V3-07); digest fields asserted |
| T7 | Preview artifact differs from reviewed candidate | Preview artifact digest bound to candidate digest; mismatch fails closed | preview harness test + TRAJ-FS planted fixture |
| T8 | Mocked backend masks broken integration | Delivered E2E path forbids network mocking; a trajectory rule plants exactly this failure | Playwright config review + planted fixture |
| T9 | Supply chain: npm/PyPI dependencies | Minimal dependency policy (no design system, no client analytics); lockfiles committed; `npm audit`/`pip-audit` in CI as informational, high-severity blocking consistent with V1 policy | CI security jobs |
| T10 | Toolchain execution against the host (Playwright/npm scripts in candidate workspaces) | Verification runs in the isolated run workspace with the same worktree isolation V2 uses; no secrets exist in the environment for the product | existing read-only guard + workspace isolation |
| T11 | Path traversal via uploaded filenames | Filenames are never used for filesystem paths (in-memory processing); report download names are server-generated constants | API tests with hostile filenames |
| T12 | CSRF | No state-changing authenticated actions exist (no accounts, stateless API); POSTs are same-origin from the app; documented residual: if session state is ever added, CSRF tokens become required (recorded as a future-work gate) | threat-model review lens |

## Explicit non-goals (accepted residual risk, by product decision)

Multi-tenant isolation, rate limiting beyond size caps, audit logging of
uploads, and production observability are out of scope for product V1
(PD-V3-12) and recorded as known limitations, not silently absent.
