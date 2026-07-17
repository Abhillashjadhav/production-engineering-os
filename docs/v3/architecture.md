# V3 architecture — the full-stack adapter and the dogfood product

## Two planes, one discipline

V3 adds a **full-stack stack adapter** to Production Engineering OS without
weakening any existing adapter, and uses it to deliver **pm-evals Web**. The
OS plane lives under `src/pmpe/fullstack/`; the product lives under
`products/pm-evals-web/`. The OS never imports product code; the product never
imports the OS — the run engine drives the product through artifacts,
validators, and executed evidence, exactly as V2 does for the CLI stack.

## Repository layout (target state)

```
src/pmpe/fullstack/            # the V3 adapter (OS plane)
  contract.py                  # FullStackProductContract model + admission
  journey.py                   # UX architecture validation (screens/states/flows)
  api_contract.py              # OpenAPI contract verification
  web_evidence.py              # Vitest/Playwright/axe executed-evidence decoders
  preview.py                   # built-artifact preview harness + digest binding
schemas/fullstack_product_contract.schema.json   (+ packaged copy)
.claude/agents/v3-*.md         # full-stack reviewer/specialist definitions
evals/fixtures/trajectory/planted_fs_*.jsonl     # TRAJ-FS planted fixtures
products/pm-evals-web/         # the dogfood product
  contract.json                # its FullStackProductContract
  backend/                     # FastAPI app + pm_evals_compare domain package
    pyproject.toml             #   own package: pm-evals-web-backend
    src/pm_evals_compare/      #   deterministic comparison engine (reusable)
    src/pm_evals_api/          #   FastAPI: upload, validate, compare, report
    tests/                     #   pytest (unit + API)
  frontend/                    # Next.js + TypeScript + React
    src/                       #   app shell, typed API client, screens
    tests/                     #   Vitest + Testing Library
  e2e/                         # Playwright: real frontend + real backend
  fixtures/                    # synthetic, realistic eval-run JSON files
  Dockerfile.backend, Dockerfile.frontend, compose.yaml
  scripts/preview.sh           # one-command built-artifact preview runner
```

The product's Python packages are **separate distributions** from `pmpe`
(their tests run in their own pytest rootdir); the pmpe suite's 338 tests stay
isolated and green. CI grows dedicated jobs per surface.

## The comparison engine (domain layer)

`pm_evals_compare` is a pure, deterministic Python package (stdlib + pydantic
only): parse eval-run files → validate schema and cross-file compatibility →
match traces by identifier → compute per-criterion and overall deltas, newly
passing/failing traces, hard-gate regressions → evaluate rubric coverage and
guardrail thresholds → emit `PROCEED`/`HOLD`/`INSUFFICIENT_EVIDENCE` with
trace-level evidence → render Markdown and JSON reports. No I/O, no clock
(timestamps injected), no randomness — property: identical inputs, identical
outputs (PD-V3-07). The FastAPI layer is a thin, typed transport over it.

## Eval-run input format

One JSON format (documented + JSON-Schema-validated): a run carries
`run_id`, `suite`, optional `model`/`config` metadata, `criteria[]`
(id, description, `hard_gate: bool`, optional threshold) and `traces[]`
(trace id, input digest/label, per-criterion `pass|fail` results, optional
score/notes). Compatibility requires same suite, overlapping criteria ids, and
matchable trace ids. Arbitrary spreadsheet formats are excluded (PD-V3-12).

## API surface (FastAPI)

- `POST /api/compare` — multipart upload: `baseline` + `candidate` files,
  optional guardrail config; in-memory processing; size and format limits;
  returns the full typed comparison (deltas, changed traces, verdict,
  evidence). Stateless: repeat requests re-upload (PD-V3-08; no session store
  in product V1 — "optional ephemeral session state" is deferred, documented).
- `POST /api/report` — same inputs (or the comparison JSON) → Markdown/JSON
  report download responses.
- `GET /api/health` — liveness for preview verification.
- OpenAPI schema is the **contract**: the frontend's client types are
  generated from it, and CI diffs the committed schema against the live app's
  schema — any mismatch fails CI (adapter: `pmpe.fullstack.api_contract`).

## Frontend (Next.js + TypeScript)

Single-page journey (PD-V3-03): explainer → two upload dropzones with
client-side schema pre-validation (mirror of the backend rules, backend
remains authoritative) → Compare Runs → dashboard (pass rates, net change,
criterion deltas, changed-trace table with filter + detail drawer, verdict
panel with evidence) → download buttons. All five UI states implemented per
screen (loading/empty/error/success/insufficient-evidence). Minimal
hand-rolled component styling (CSS modules); no design-system dependency.
Accessibility: labeled controls, keyboard-completable journey, focus
management, axe-core automated checks in E2E.

## Verification chain (extends V2, never bypasses it)

1. **Contract admission**: FullStackProductContract validated + digest-locked
   (reuses `pmpe.contracts` storage; new schema + model).
2. **UX architecture stage**: journey/screen/state inventory validated before
   any frontend implementation (PD-V3-16); admission validator refuses
   implementation artifacts submitted before a validated journey.
3. **Executed evidence**: backend pytest via the existing subprocess evidence
   runner; frontend Vitest and Playwright emit machine-readable results
   (JSON reporters) decoded into the same executed-evidence model — coverage
   is proven by executed tests on every surface.
4. **Browser journey verification**: Playwright drives the real frontend
   against the real backend (no mocks in the delivered path): uploads real
   fixtures, compares, inspects a changed trace, downloads both reports,
   exercises malformed/incompatible files, mobile viewport, keyboard-only.
5. **Preview verification**: build production artifacts (`next build`,
   backend wheel), start via `scripts/preview.sh` (local) or
   `docker compose up` (CI), health-check, run the browser suite against the
   built preview, and bind {candidate digest, preview artifact digest, test
   evidence, review evidence, release report} in the evidence pack
   (PD-V3-10/14).
6. **Assurance**: six read-only lenses (PD-V3-15) over the frozen candidate;
   findings → reconciliation → fixer gate → verified fixes, unchanged from V2.
7. **Trajectory + drift**: TRAJ-FS rules (12 planted failure classes) over the
   run ledger; drift categories extended with web-surface coverage.

## Digest binding for web artifacts

The candidate freeze already digests the workspace tree. V3 adds a **preview
artifact digest**: a canonical digest over the built artifact inventory
(frontend build output manifest + backend wheel) recorded at build time,
re-computed at preview start, and bound to the candidate digest in the ledger.
A preview whose artifact digest does not match what was built from the frozen
candidate fails closed (TRAJ-FS rule + runtime check).

## Deployment seam (future, documented — not built)

`compose.yaml` is the deployment unit. The seam for Vercel/Render/Fly.io:
frontend as a static/Node build with `NEXT_PUBLIC_API_BASE_URL`, backend as a
container with a health endpoint and no egress; a future `pmpe.deployment`
executor would push the same digest-bound images. No cloud deployment is
performed or claimed in V3 (PD-V3-14).
