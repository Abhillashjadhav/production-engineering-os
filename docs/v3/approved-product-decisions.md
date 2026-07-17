# V3 approved product decisions — Verified Full-Stack Web Product Delivery

Locked decisions for Production Engineering OS V3 and its dogfood product,
**pm-evals Web — Compare Eval Runs**. These are product intent: changing any
of them requires a ProductChangeRequest, never an engineering fix.

## The mission

- **PD-V3-01 — Full-stack delivery, not CLI enhancement**: V3 exists so a
  non-developer-facing product ships as a working browser application —
  frontend, backend, browser tests, preview deployment artifacts, and complete
  evidence-backed traceability. V1/V2 behaviour must remain green throughout.
- **PD-V3-02 — Target user**: a non-technical AI Product Manager evaluating
  whether a model, prompt, retrieval, or agent change is safe to release. No
  terminal in the primary journey, ever.
- **PD-V3-03 — The primary journey (locked)**: open app → read what it does →
  upload baseline results JSON → upload candidate results JSON → clear
  validation errors for malformed/incompatible files → "Compare Runs" → view
  overall pass rates, net change, criterion-level improvements/regressions,
  newly passing traces, newly failing traces, hard-gate regressions, release
  verdict, and the evidence supporting it → filter/inspect individual changed
  traces → download the comparison as Markdown and JSON → repeat without
  signing in.

## Verdicts (locked semantics)

- **PD-V3-04 — Three verdicts only**: `PROCEED`, `HOLD`,
  `INSUFFICIENT_EVIDENCE`.
  - **HOLD** when: any newly failing hard-gate criterion; malformed or
    incompatible evidence; missing result coverage required by the rubric; a
    configured guardrail threshold is violated.
  - **INSUFFICIENT_EVIDENCE** when: files are structurally valid but do not
    contain enough comparable traces; required criteria or trace identifiers
    cannot be matched reliably; release rules cannot be evaluated from the
    supplied evidence.
  - **PROCEED** only when: all required evidence is available; no hard-gate
    regression exists; configured guardrails pass.
- **PD-V3-05 — No verdict without trace-level evidence**: every verdict names
  the traces and criteria it rests on. No unsupported numerical claim anywhere
  in the UI or reports.

## Metrics

- **PD-V3-06 — North Star**: percentage of evaluated product changes receiving
  an evidence-backed pre-release verdict through the browser interface.
  Leading: successful comparison completion rate; time to first completed
  comparison; % of uploaded file pairs passing compatibility validation; % of
  reports downloaded; repeat comparisons per session. (V1 of the product ships
  no analytics — these are definitions for future instrumentation, not
  implemented collection.)

## Guardrails (locked)

- **PD-V3-07 — Determinism**: identical inputs yield an identical verdict and
  identical reports, byte-for-byte modulo generation timestamps, which are
  isolated to clearly labeled fields.
- **PD-V3-08 — Data stays local**: no uploaded data sent to third-party
  services; no external egress from the backend; uploaded result files are
  processed in memory and never permanently stored.
- **PD-V3-09 — Accessible + responsive**: the primary journey is completable
  keyboard-only with accessible labels and focus behaviour; desktop and mobile
  layouts both work; automated accessibility checks plus deterministic
  acceptance tests.
- **PD-V3-10 — Digest-identical candidate**: the reviewed candidate, the
  tested artifact, and the deployed preview artifact must be digest-identical
  (extends V2's candidate freeze to web build artifacts).

## Scope

- **PD-V3-11 — In scope (product V1)**: working browser UI; frontend app;
  backend comparison API; reusable deterministic comparison engine; local file
  upload + in-memory processing; schema and compatibility validation;
  comparison dashboard; criterion-level delta view; changed-trace table and
  detail view; verdict with explicit reasons; Markdown + JSON report download;
  loading/empty/error/success/insufficient-evidence states; responsive
  interface; basic accessibility compliance; local dev environment;
  containerized runnable artifact; browser-level E2E tests; synthetic but
  realistic fixtures; deployment-ready preview artifact; complete
  requirement-to-code-to-test traceability.
- **PD-V3-12 — Excluded (product V1)**: authentication; user accounts;
  permanent cloud storage; billing; collaboration; live model execution;
  production observability platform; multi-project history; real production
  deployment; external analytics; automatic public sharing; arbitrary
  spreadsheet formats.

## Engineering-plane decisions

- **PD-V3-13 — One opinionated reference stack**: Next.js + TypeScript + React
  frontend (minimal component styling, no large design-system dependency);
  FastAPI backend; reusable deterministic Python comparison package; typed
  schemas on both sides; OpenAPI-validated contract (mismatch fails CI);
  Playwright browser tests; pytest backend tests; Vitest + Testing Library
  frontend tests; Docker Compose packaging.
- **PD-V3-14 — Preview evidence is honest**: the preview is a locally runnable
  containerized artifact. Verification starts the *built* application (never
  only dev servers) and binds preview artifact digest, candidate digest, test
  evidence, review evidence, and release report. No real cloud deployment is
  claimed; the exact seam for Vercel/Render/Fly.io is documented.
  *Environment constraint (documented deviation)*: the authoring sandbox has a
  Docker CLI but no daemon; container builds and compose-based browser E2E run
  in CI (GitHub Actions runners have a daemon), while local preview
  verification runs the same built production artifacts as supervised
  processes from one runner script. Both paths verify the built artifact; the
  evidence pack records which path produced each piece of evidence.
- **PD-V3-15 — Full-stack assurance extends, never weakens, V2**: independent
  fresh-context read-only reviewers for UX journey conformance, frontend
  correctness + accessibility, backend/API correctness + security,
  architecture simplicity, product-contract conformance, and eval/evidence
  integrity. The fixer touches only accepted finding IDs and allowed files.
  Product-behaviour changes go through ProductChangeRequests.
- **PD-V3-16 — Journey before implementation**: no frontend implementation
  before the UX architecture (information architecture, screen inventory,
  user flows, component/state map, error/recovery states, accessibility and
  responsive requirements) is validated. No mocked backend in the delivered
  E2E path.
- **PD-V3-17 — Dogfood or it didn't happen**: pm-evals Web is built through
  Production Engineering OS V3 itself — contract admitted, journey validated,
  plans generated, tests before implementation, isolated work, frozen
  candidate, independent reviews, accepted fixes, executed traceability,
  browser journey verification, preview verification, draft PR, evidence-backed
  release decision. Defects V3 exposes in itself are fixed through normal
  reviewed PRs and recorded as learning evidence.
- **PD-V3-18 — Honest evidence only**: synthetic evidence is labeled
  synthetic; no real-user claims from fixtures; no manufactured timestamps or
  activity; disagreement and uncertainty are preserved in the record.
