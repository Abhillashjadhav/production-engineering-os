# V3 current-state assessment

Measured on `main` at `e94502b` (final V2 maintenance merge), 2026-07-16.

## Baseline verification

- Full V1+V2 suite: **338 passed** (`.venv/bin/python -m pytest`), exit 0.
- Historical V1 fixture pipeline → success; `pmpe demo` → all planted failures
  caught, verdict READY_FOR_PRODUCTION_APPROVAL. The V1 command is now retired.
- CI green on the merge commit (format-lint, types, tests 3.11/3.12, security,
  build-smoke including evals + pinned drift-HOLD + demo).

## Tooling available to V3 (verified in this environment)

| Tool | Status |
|---|---|
| Node 22.22.2, npm 10.9.7, pnpm, yarn | present |
| Docker CLI 29.3.1 + Compose v5.1.1 | CLI present; **daemon unavailable in the authoring sandbox** (`docker ps` fails). GitHub Actions runners provide a working daemon — container builds and compose E2E belong in CI; local preview verification uses built artifacts as processes (PD-V3-14) |
| Playwright Chromium | pre-installed at `/opt/pw-browsers` (chromium-1194); `@playwright/test` to be added per-product; CI installs via `npx playwright install chromium` |
| Python 3.11.15 + repo venv | present; pmpe installed editable |
| npm registry | reachable through the environment proxy |

## What V2 already provides (reused, not rebuilt)

- **Contract plane**: digest-locked ProductDecisionContract, versioned
  registry, ProductChangeRequests (`pmpe.contracts`).
- **Agent plane**: definition registry, read-only permission proofs,
  minimum-routing validation (`pmpe.agents`).
- **Assurance plane**: findings lifecycle, reconciliation, fixer gate,
  runtime read-only guard (`pmpe.assurance`).
- **Evidence primitives**: worktrees, append-only evidence ledger, candidate
  freeze rejecting dirty trees, executed-test evidence + executed
  traceability (`pmpe.engineering`, `pmpe.quality.test_evidence`,
  `pmpe.audit.executed`).
- **Reliability plane**: per-agent evals over real definitions, 14 trajectory
  rules, drift reporter with HOLD, submission validators (`pmpe.evals`,
  `pmpe.engineering.submissions`).
- **Run engine**: stage machine with hardened controls — dirty-freeze
  rejection, enforced binary release gates, retest-evidence binding, mandatory
  deployment integrity, readiness-before-authorization
  (`pmpe.engineering.engine`, `pmpe.deployment`).

## Gaps V3 must fill

1. **No web-product contract**: `MvpSpec`/`ProductDecisionContract` model CLI
   pipelines; nothing captures screens, UI states, user flows, API contracts,
   accessibility/responsive requirements, or deployment targets
   → FullStackProductContract.
2. **No UX architecture stage**: nothing validates a journey/screen/state
   inventory before implementation → journey validators + stage.
3. **No frontend toolchain integration**: evidence runner executes Python
   unittest only → typed-frontend test evidence (Vitest), browser-journey
   evidence (Playwright), accessibility/responsive evidence.
4. **No API-contract verification**: nothing binds a frontend client to a
   backend schema → OpenAPI contract check that fails CI on mismatch.
5. **No web preview verification**: deployment plane verifies local processes
   for the V1 generator stack only → built-artifact preview harness +
   container packaging seam, digest-bound.
6. **Trajectory rules are CLI-shaped**: no rules for mocked-backend passes,
   undocumented API fields, journey-before-implementation, preview/candidate
   divergence, accessibility/mobile regressions, storage violations
   → TRAJ-FS rules + planted fixtures.
7. **Reviewer roster lacks web lenses**: UX journey, frontend/accessibility,
   backend/API security lenses missing → new read-only reviewer definitions.
8. **No reusable comparison engine for eval runs**: `pmpe.evals.drift`
   compares agent-eval summaries, not trace-level baseline/candidate run
   files → deterministic `pm-evals-compare` domain package (the dogfood
   product's engine, reusable beyond it).

## Constraints carried forward

- Existing V1/V2 tests (338) stay green in every PR.
- The repo's PR discipline (atomic, reviewed, ledgered) continues; V3 rows
  append to `docs/CONTRIBUTION_LEDGER.md`; the V2 report
  (`docs/CONTRIBUTION_REPORT.md`) is referenced as the previous completed
  release and never edited.
