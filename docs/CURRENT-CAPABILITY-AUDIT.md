# Current capability audit

Audit date: 2026-07-28
Audited default-branch commit: `8ddc4ccfeb88d7efd5531ca9411e5f2229cce0ec`
Repository: `Abhillashjadhav/production-engineering-os` (private)
Phase 0 issue: [#61](https://github.com/Abhillashjadhav/production-engineering-os/issues/61)
Umbrella issue: [#60](https://github.com/Abhillashjadhav/production-engineering-os/issues/60)

## Audit basis

This report treats repository files, executed checks, Git/GitHub records, and exact
digests as evidence. Earlier assessment documents and PR comments are useful history,
not proof that a capability exists at the audited commit.

The classification vocabulary is:

1. **Implemented and verified**
2. **Implemented but insufficiently tested**
3. **Partially implemented**
4. **Present only as documentation**
5. **Absent**
6. **Implemented but unsafe**
7. **Blocked by missing product decision**
8. **Blocked by missing infrastructure or permissions**

## Repository summary

| Item | Evidence-backed state |
|---|---|
| Identity | Local root and `origin` both resolve to `Abhillashjadhav/production-engineering-os`; connected GitHub reports a private repository and admin/push permission for `Abhillashjadhav`. |
| Default branch | `main`; local and `origin/main` were both `8ddc4cc…` after `git pull --ff-only origin main` reported “Already up to date.” |
| Worktree at audit start | Clean: `## main...origin/main`. No user changes were overwritten. |
| Phase 0 branch | `docs/phase-0-pmos-peos-plan`, created only after issues #60–#74 existed. |
| Size and shape | 484 tracked files at audited commit: Python package (`src/pmpe`), 450 collected core tests, PM skills/agents, V3 web product, schemas, evals, docs, and two Actions workflows. |
| Build systems | Root `setuptools`/`pyproject.toml`; web backend `setuptools`; frontend/e2e npm lockfiles; Dockerfiles and Compose preview. |
| Runtime data | File-based run state, JSON/JSONL artifacts, local generated SQLite products; no PEOS service database. |
| Remote activity | No open PRs and no pre-existing GitHub issues were returned by the connected GitHub app. At audit start, 63 remote branch refs other than the symbolic remote ref were visible locally; the Phase 0 branch adds one. |
| Divergent work | `origin/feature/github-portfolio-auditor-v1` is 6,158 added lines across 41 files beyond `origin/main`; PRs #53–#59 targeted that feature branch. It is not part of default-branch PEOS capability and was not folded into Phase 0. |
| Governance history | PRs exist, but sampled PRs #51 and #59 have zero formal GitHub review submissions. “Independent review” was recorded as comments by the repository owner. |
| Branch protection | Repository documentation recommends it; active GitHub branch-protection/ruleset state was not observable through the available connector, and local `gh` authentication is invalid. Classification: infrastructure/permission blocked. |

## What exists and is reusable

- Three contract inputs: V1 `MvpSpec`, V2 `ProductDecisionContract`, and V3
  `FullStackProductContract`.
- Schema loading, canonical JSON/digest calculation, versioned contract registration,
  run locking, mutation refusal, and ProductChangeRequests.
- V1 semantic checks for direct scope/non-goal contradictions, identifier validity,
  acceptance-criterion links, activity-only North Star Metrics, vague criteria, and
  unsupported deployment targets.
- V1 deterministic architecture, planning, tests-before-code, implementation,
  local Git workspace, quality gates, local deployment, smoke journey, rollback
  instructions, and structural traceability for one stdlib CRUD API stack.
- V2 agent admission, minimum routing policy, worktree primitive, candidate freeze,
  append-only evidence ledger, four-lens read-only assurance, finding reconciliation,
  fixer allowlists, independent fix verification, executed traceability, agent evals,
  trajectory evals, and drift HOLD behavior.
- V3 full-stack contract, journey/screen/state validation, API-contract checks,
  browser/a11y test sources, container preview evidence, six review lenses, and
  full-stack trajectory rules.
- Core CI jobs for formatting/lint, strict types, Python tests, Bandit, dependency
  audit, wheel/CLI smoke, web backend/frontend/browser/preview checks.

These primitives should be composed and hardened, not rebuilt.

## Capability classification

| Capability | Classification | Repository evidence and limits | Planned issue |
|---|---|---|---|
| PM Agent OS contract schema | **3 — Partially implemented** | `schemas/mvp_spec.schema.json`, `product_decision_contract.schema.json`, and `fullstack_product_contract.schema.json` are synchronized with packaged copies. No single schema contains the required end-to-end bundle. | [#62](https://github.com/Abhillashjadhav/production-engineering-os/issues/62) |
| Contract compiler | **5 — Absent** | Loaders type individual formats; there is no loss-aware compiler or canonical runtime bundle across V1/V2/V3. | [#76](https://github.com/Abhillashjadhav/production-engineering-os/issues/76) |
| Contract validator | **3 — Partially implemented** | Structural validation is tested; V1 semantic checks are useful but do not validate the full target contract. | [#63](https://github.com/Abhillashjadhav/production-engineering-os/issues/63) |
| Contradiction detection | **3 — Partially implemented** | `RequirementValidator._check_contradictions` catches exact scope/non-goal duplicates. No general hypothesis/solution/metric/guardrail/autonomy contradiction engine exists. | #63 |
| Open-question blocking | **1 — Implemented and verified** | V2 product-critical questions and V3 blocking questions prevent runnability; contract and full-stack unit tests exercise the behavior. | Reuse in #63 |
| Requirement IDs | **3 — Partially implemented** | V1 enforces `PREFIX-NUMBER`; V2 checks duplicate requirement IDs. Grammar/uniqueness is not uniform across every contract format and bundle member. | #62 |
| Acceptance-criterion IDs | **3 — Partially implemented** | IDs and requirement links exist; uniform pattern/uniqueness and bundle-wide references are incomplete. | #62/#63 |
| Risk classification | **6 — Implemented but unsafe** | `pmpe.policies.PolicyEngine`, named rules, risk tests, and declared contract risks exist for known scopes, but a decision type absent from `_DEFAULT_RULES` falls back to `MEDIUM` and `requires_approval()` blocks only `HIGH`. An unknown operation can therefore proceed with a logged justification instead of failing closed. | Replace the permissive fallback in #65; reuse known-rule metadata in #62 |
| Approval metadata | **1 — Implemented and verified** | Contract approval and production approval are named/timestamped; production approval is candidate-digest bound and tested. Roles, expiry, target config, and full deployment subjects need extension. | Reuse in #62/#72 |
| Repository intelligence | **5 — Absent** | `record_assessment` accepts an arbitrary dictionary. No deterministic exact-SHA repository snapshot exists on `main`. | [#64](https://github.com/Abhillashjadhav/production-engineering-os/issues/64) |
| Architecture generation | **3 — Partially implemented** | V1 is deterministic but single-stack; V2 agent output has structural admission. It is not compiled from a normalized repository snapshot. | [#66](https://github.com/Abhillashjadhav/production-engineering-os/issues/66) |
| ADR generation | **3 — Partially implemented** | V1 emits fixed ADRs and V2 requires ADR fields. Alternatives, threat links, approvals, and repository-bound enforcement are incomplete. | #66 |
| Threat modelling | **4 — Present only as documentation** | `docs/v3/threat-model.md` and product-specific threat documents exist; no per-run required/admitted ThreatModel artifact. | #66 |
| Requirement-to-test compilation | **3 — Partially implemented** | V1 templates map requirements for one stack; V2 plans require only a textual behavioral test. V3 has product-specific suites. | [#67](https://github.com/Abhillashjadhav/production-engineering-os/issues/67) |
| Test-before-code enforcement | **3 — Partially implemented** | V1 `confirm_red` enforces ordering. V2 ledger emits `task_tests` immediately before `task_implementation` from one submitted result, not an independently admitted generalized test plan. | #67 |
| Unit testing | **2 — Implemented but insufficiently tested** | 450 core tests collected; 449 passed locally, with one macOS path-canonicalization failure. The web backend has 85 tests and declares Python `>=3.11`, but only 84 pass on the therefore-supported Python 3.14 target; CI covers only 3.11. | Reuse; supported-version policy/matrix in #69 |
| Integration testing | **1 — Implemented and verified** | Core integration suite, git/worktree, generated API, run-engine, and full-stack orchestration tests exist; loopback tests passed outside the sandbox. | Reuse/extend #67 |
| End-to-end testing | **2 — Implemented but insufficiently tested** | Core E2E paths executed in the full suite. Playwright covers journeys/a11y/keyboard/responsive; later GitHub Actions `product-e2e` and containerized `product-preview` jobs executed those browser checks successfully. Node/Chromium/Docker remain unavailable locally, and the suites are product-specific rather than generalized PEOS gates. | #67/#69 |
| Migration testing | **5 — Absent** | No generalized schema/data migration verifier or release gate. | #67/#71/#72 |
| Performance testing | **5 — Absent** | No load/performance harness, budget compiler, or promotion gate. | #67 |
| Accessibility testing | **2 — Implemented but insufficiently tested** | V3 Playwright/axe suites exist and later GitHub Actions `product-e2e` and containerized `product-preview` jobs executed them successfully. Node is absent locally, and the suites remain product-specific rather than generalized PEOS gates. | #67 |
| Implementation orchestration | **3 — Partially implemented** | V1 implements one stack; V2 admits specialist artifacts but the skill/operator drives the actual work. GitHub issue/branch/PR state is not enforced. | [#68](https://github.com/Abhillashjadhav/production-engineering-os/issues/68) |
| Specialist-agent orchestration | **3 — Partially implemented** | Router and permissions are tested. Frontend, data, eval, security, and platform profiles named in `SPECIALIST_PROFILES` have no V2 agent files; selection fails closed. | #68 |
| Bounded repair loop | **5 — Absent** | V1 has one safe-fix pass and V2 has an accepted-finding fixer, but no cross-stage retry budget, attempt counter, or `BUDGET_EXCEEDED` transition. | [#65](https://github.com/Abhillashjadhav/production-engineering-os/issues/65) |
| Deterministic verification | **3 — Partially implemented** | Strong gates/evals/digests exist. Results are split across run engines and tool versions are not fully pinned; the current backend Ruff lower bound admits a version that reports eight lint errors. | [#69](https://github.com/Abhillashjadhav/production-engineering-os/issues/69) |
| Architecture-boundary checks | **5 — Absent** | Reviews discuss boundaries, but no machine-enforced import/component policy is generated from the architecture. | [#70](https://github.com/Abhillashjadhav/production-engineering-os/issues/70) |
| Security scanning | **3 — Partially implemented** | Bandit high passes, a Python regex scanner is tested, and product dependency audits exist. Coverage is not repository-wide or uniformly blocking. | #70 |
| Privacy verification | **5 — Absent** | Privacy intent and data-flow/retention/deletion verification are not a deterministic gate. | #70 |
| Dependency review | **3 — Partially implemented** | Backend hash lock audited clean; npm audit is configured. Root `pip-audit` is explicitly non-blocking and root runtime dependency is not locked. | #70 |
| Secret scanning | **3 — Partially implemented** | Manual path-only scan found no non-fixture match; generated Python scanner is regex-based. No GitHub secret-scanning or dedicated CI secret scanner is visible. | #70 |
| Independent code review | **6 — Implemented but unsafe** | V2/V3 reviewer agents are read-only within engineering runs. The repository PR workflow is a single reviewer-then-fixer context with `contents: write`, `Edit`, `Write`, and commit tools; it does not run on draft PRs. Sampled GitHub PRs have no formal reviews. | #68/#69/#70 |
| Evidence packaging | **3 — Partially implemented** | Ledgers, dogfood evidence, candidate manifests, preview evidence, and reports exist. There is no universal manifest covering the full target lifecycle. | #69 |
| Commit-bound provenance | **3 — Partially implemented** | Candidate and contract content digests are strong; completion is not universally bound to a Git commit SHA, built artifact, config, deployment, and observation. | #69 |
| Staging deployment | **3 — Partially implemented** | Policy authorizes `staging`; no staging executor runs. Container preview is CI verification, not environment promotion. | [#71](https://github.com/Abhillashjadhav/production-engineering-os/issues/71) |
| Smoke testing | **1 — Implemented and verified** | V1 local health/journey and V3 browser/preview sources exist; core smoke paths are exercised. Target staging/live smoke needs adapters. | Reuse in #71/#72 |
| Canarying | **3 — Partially implemented** | `simulate_production_deploy` models canary pass/fail and rollback in fixture mode only. | [#72](https://github.com/Abhillashjadhav/production-engineering-os/issues/72) |
| Production promotion | **3 — Partially implemented** | Digest-bound authorization and readiness policy are tested; production execution is explicitly simulated and touches no environment. | #72 |
| Observability | **3 — Partially implemented** | Local JSONL events and per-run metrics exist. No production logs/metrics/traces, dashboards, alerts, SLO windows, or fleet aggregation. | [#73](https://github.com/Abhillashjadhav/production-engineering-os/issues/73) |
| Rollback | **3 — Partially implemented** | V1 writes local rollback instructions; simulated canary marks rollback. No real executed production rollback or RTO/RPO proof. | #72 |
| Non-technical Guided Mode | **5 — Absent** | CLI, JSON, Markdown, and agent skills are the interfaces; there is no approved guided lifecycle UI. | [#74](https://github.com/Abhillashjadhav/production-engineering-os/issues/74) |
| PM Agent OS feedback loop | **3 — Partially implemented** | ProductChangeRequests carry engineering findings back to product. No post-release OutcomeReport from live metrics/hypothesis evidence. | #73 |
| False-DONE prevention | **3 — Partially implemented** | Freeze, executed traceability, binary gates, and preview digests prevent several false claims. No universal exact-SHA EvidenceBundle/terminal invariant exists. | #69 |

## Verification performed

| Check | Result at audit |
|---|---|
| `git pull --ff-only origin main` | PASS — already up to date |
| Schema JSON parse and root/package synchronization | PASS |
| Root Ruff format | PASS — 148 files already formatted |
| Root Ruff lint | PASS |
| Root mypy strict | PASS — 100 source files |
| Root Bandit high severity | PASS |
| Root pytest | 450 collected; 449 PASS; 1 FAIL on macOS because `Path.resolve()` canonicalizes `/tmp` to `/private/tmp`. The 19 loopback failures in the sandbox disappeared when rerun with loopback permission. |
| V2 contract and V1 spec CLI validation | PASS |
| Agent and trajectory eval suite | PASS — 11 agent suites at 1.00; zero trajectory violations |
| Planted drift regression | PASS — expected `HOLD`, exit 3 |
| Production-engineer skill lint | PASS — 9/9 gates |
| Wheel build | PASS after build-isolation network access was allowed |
| Root dependency audit | PASS when auditing the project dependency graph directly |
| Web backend tests on local Python 3.14 | 84 PASS, 1 FAIL; CI declares only Python 3.11 for this job. Deeply nested JSON is parsed differently and produces a different 422 message on 3.14. |
| Web backend mypy/format | PASS |
| Web backend Ruff with current allowed version | FAIL — eight findings, proving the unbounded `ruff>=0.4` lower-bound policy is not reproducible |
| Web backend hash-locked dependency audit | PASS — no known vulnerabilities |
| Frontend/unit/build, Playwright, container preview | **Blocked by infrastructure** — Node, npm, Docker, and Chromium are not installed in this environment |
| Active GitHub branch protection | **Blocked by tooling/permissions** — the available connector does not expose rulesets/protection and local `gh` authentication is invalid |
| PR Actions on reviewed head `1e052cee…` | **Infrastructure failure** — `ci` run 30377528370 completed failure: nine jobs failed and one was cancelled before any job step; step arrays were empty and logs were unavailable. Draft-only `PR Review Agent` run 30377528156 was correctly skipped. |
| Formal reviews on sampled PRs #51/#59 | No formal reviews returned |

## Key gaps and unsafe assumptions

1. **Three contracts are not one contract bundle.** V2 omits hypothesis, UX,
   accessibility, explicit security/privacy/data/QA/release/observability/rollback
   fields; V3 adds UX but omits outcome/hypothesis/metrics and digest source metadata.
2. **A narrative assessment can advance V2.** Repository analysis is an arbitrary
   submitted dictionary, not deterministic repository evidence.
3. **State machines diverge.** V1, V2, and V3 use different stages and terminal
   semantics. Target rollback, budget, product-input, and production states do not
   exist as one policy.
4. **Tests-before-code is not universal.** V1 is strong for one generator; V2 does
   not admit an independent executable test plan before specialist implementation.
5. **Review separation is inconsistent.** In-run reviewers are read-only; the GitHub
   workflow deliberately combines reviewer and fixer in one context with write
   permission and records no formal GitHub approval.
6. **Deployment wording must stay exact.** Local and container-preview deployment are
   real in their scopes; staging authorization and production/canary are not real
   environment executions.
7. **Toolchain drift is already visible.** Unbounded Ruff now fails the backend even
   though earlier records called it clean.
8. **Observability is telemetry scaffolding, not operations.** No production SLO,
   dashboard, alert, runbook, fleet metric, or feedback proof exists.
9. **Branch protections and reviewer eligibility are unknown.** Documentation must
   not claim enforcement or formal review until GitHub evidence is available.
10. **Current docs contradict one another.** `CLAUDE.md` says only Discovery is
    shipped and later stages are not, while `README.md` says all five PM stages are
    shipped. Neither statement is used as PEOS capability proof.

## Technical debt

- Root and backend tool dependencies use broad lower bounds; root has no dependency
  lock and the backend dev toolchain is not locked.
- Root CI makes `pip-audit` informational; no dedicated secret-scanning job exists.
- Source files exceed the documented “~400 lines” budget, including
  `engineering/engine.py` (691) and `fullstack/orchestration.py` (443).
- Evidence ledger crash windows can append duplicate events (documented limitation).
- Reviewer read-only snapshots do not detect newly created untracked files
  (documented limitation).
- Five specialist profile names are vocabulary without agent definitions.
- The 63 pre-existing remote branch refs create active/abandoned-work ambiguity.
- Product backend declares Python `>=3.11`, fails one test on Python 3.14, and CI
  verifies only 3.11; support must be capped or the supported-version matrix made green.

## Blockers requiring human or external input

- Production/staging infrastructure provider, accounts, protected environments,
  credential model, regions, and traffic-control mechanism.
- Production approval roles and an eligible independent GitHub collaborator.
- Product-owned metric targets, SLOs, canary size/window, cost/credit budget, RTO/RPO,
  privacy retention/deletion rules, and telemetry vendor/region.
- PM Agent OS bundle transport and the approved Guided Mode UX.
- GitHub branch protection/ruleset and security-feature state until authenticated
  GitHub administration metadata is observable.
- The initial GitHub Actions outage, where jobs stopped before exposing steps or logs,
  was historical. Later exact-head run `30421310105` executed all ten jobs: eight
  passed, `product-backend` failed comparison-engine lint, and `product-frontend`
  failed the high-severity dependency audit. Those two concrete implementation gates,
  not runner availability, now block exact-head CI verification and belong in
  dedicated implementation issues/PRs rather than this documentation-only Phase 0 PR.
