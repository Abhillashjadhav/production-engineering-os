# PM Production Engineering OS — Architecture

Phase Zero is the sole admissible shipped lifecycle authority. The architecture below
documents the historical V1 fixture retained under `tests.legacy_v1`; it is not an
installed execution path.

Principles, in priority order: **extensibility → reliability → simplicity → speed →
low cost**. Extensibility comes from interfaces and adapters, not frameworks.

## System shape

Local-first, single-process CLI. No services, no queues, no network required for a
full build. Everything an engineer would audit — state, artifacts, logs, approvals —
is a file under the run directory.

```
                         tests.legacy_v1 (test fixture)
                                    │
                           legacy workflow harness
              state machine · idempotent steps · resume · escalation pauses
                                    │
 ┌──────────┬──────────┬───────────┼───────────┬──────────┬───────────┐
 │ ingestion│validation│ planning  │architecture│ testing  │implementation
 │ loader   │ validator│ planner   │ agent+ADRs │ architect│ generator
 └──────────┴──────────┴───────────┴───────────┴──────────┴───────────┘
                                    │
 ┌──────────┬──────────┬───────────┼───────────┬──────────┐
 │ quality  │  review  │  gitops   │ deployment│  audit   │
 │ gates    │ reviewer │  adapter  │ deployer  │ trace    │
 │ security │ fixer    │  PR record│ smoke     │ report   │
 │          │ merge    │           │ rollback  │          │
 └──────────┴──────────┴───────────┴───────────┴──────────┘
        cross-cutting: domain models · policies (risk engine) · telemetry · artifacts
```

## Module boundaries (`src/pmpe/`)

| Module | Responsibility | Key types |
|---|---|---|
| `domain/` | Typed models shared by all modules; no business logic | `MvpSpec`, `ValidationReport`, `EngineeringPlan`, `ArchitectureDoc`, `Adr`, `TestPlan`, `GateResult`, `ReviewReport`, `Finding`, `MergeDecision`, `DeploymentResult`, `TraceabilityReport`, `RiskLevel`, `Escalation` |
| `ingestion/` | Load JSON/YAML, validate against `schemas/mvp_spec.schema.json`, normalize (IDs, trimming, defaults), reject malformed input | `SpecLoader`, `SchemaValidator`, `normalize_spec` |
| `validation/` | Semantic checks: missing fields, contradictions, untestable acceptance criteria, activity-only NSM, undeclared dependencies, unsupported product decisions | `RequirementValidator` |
| `planning/` | Requirements → engineering tasks, components, data model, APIs, dependency graph, topological order, relative complexity | `EngineeringPlanner` |
| `architecture/` | Propose architecture for the chosen stack, record ADRs, flag security/scale/reliability implications, raise escalations for ambiguous/high-impact decisions | `ArchitectureAgent` |
| `testing/` | Generate tests *before* implementation, mapped to requirement IDs (`Covers: FR-xxx`); negative and edge cases; fixtures | `TestArchitect` |
| `implementation/` | Generate product code per plan task, small commits, never touch unplanned files, keep traceability markers | `ImplementationAgent` (interface), `StdlibCrudGenerator` (V1 provider) |
| `quality/` | Run gates: format, lint, static analysis/types, unit, integration, e2e, security, repo-wide regression; each gate returns a typed result | `QualityGateRunner`, `SecurityScanner` |
| `review/` | Deterministic PR review (correctness, architecture alignment, test sufficiency, security, maintainability, complexity, compat); safe-fix agent; merge gate | `PrReviewer`, `FixAgent`, `MergeGate` |
| `stacks/` | Everything specific to a generated product's technology: naming, code templates, test templates. V1 ships `python-stdlib-crud-api`; new stacks land here without touching the stages | naming helpers, `stdlib_code`, `stdlib_tests` |
| `gitops/` | Git adapter interface; V1: local repo per workspace, branch per run, commit per task, diff, local PR record | `GitAdapter`, `LocalGitAdapter` |
| `deployment/` | Deployment adapter interface; V1: local process deploy, health check, user-journey smoke test, rollback instructions, deployable artifact (run script + Dockerfile) | `DeploymentAdapter`, `LocalProcessDeployer` |
| `orchestration/` | Read-only legacy `RunState` projection and fixture support modules | `RunState` |
| `policies/` | Risk classification (low/medium/high) from declarative rules; approval requirements; every decision explainable | `PolicyEngine` |
| `telemetry/` | Structured JSONL event log per run; metric hooks for NSM, leading metrics, guardrails | `EventLog`, `MetricsRecorder` |
| `artifacts/` | Artifact store: writes every produced document under `runs/<id>/artifacts/` with an index | `ArtifactStore` |
| `audit/` | Traceability matrix (requirement → ADR → task → code → tests → findings → deployment) and final build report | `TraceabilityBuilder` |
| `cli.py` | legacy validation and read-only `status` / `report`; no V1 execution commands | — |

Rules that hold everywhere:

- `domain/` imports nothing from other pmpe modules; everyone imports `domain/`.
- Stage modules never import each other; only `orchestration/` composes them.
- Anything replaceable (agents, git, deployment, metrics) is a `Protocol` with a V1
  implementation — swap by config, not by edit.

## Workflow state machine

One run = one directory `runs/<run_id>/` containing `state.json`, `events.jsonl`,
`artifacts/`, `escalations/`, `approvals/`, and `workspace/` (the generated product's
own git repo).

Steps execute strictly in order; each is idempotent and persisted before/after:

```
 1 ingest            spec loaded, schema-validated, normalized
 2 validate          semantic validation; BLOCKED on errors (human gate)
 3 plan              engineering plan + dependency graph
 4 architecture      architecture doc + ADRs; may raise escalations
 5 acceptance        acceptance criteria normalized to Given/When/Then, IDs
 6 generate_tests    tests written into workspace (commit: test:)
 7 confirm_red       generated tests RUN and must FAIL (proves tests-first)
 8 implement         code generated task-by-task (commit per task: feat:)
 9 quality_gates     format, lint, types, unit, integration, security
10 create_pr         local PR record with diff summary
11 review            deterministic review findings (blocking / non-blocking)
12 fix               safe findings auto-fixed (commit: fix:); high-risk escalate
13 retest            all gates re-run after fixes
14 merge_gate        MERGE / NO_MERGE recommendation with reasons
15 merge             local merge to workspace main — only if gate says MERGE
16 deploy            local process deploy + deployable artifact
17 verify            health endpoint + main user journey smoke test
18 report            traceability matrix + final build report + metrics
```

Historical fixture transitions are `pending → running → done | failed | blocked`.
The test harness can exercise continuation semantics for compatibility, but shipped
code treats `RunState` as read-only evidence and cannot replay handlers.

## Risk model and human gates

Three levels, enforced by `policies/`:

- **low** — proceed automatically (logged).
- **medium** — proceed with an explicit, logged justification attached to the decision.
- **high** — write an `Escalation` and block the historical fixture; only test data
  can resolve it. Shipped approval authority belongs to Phase Zero.

High by default: contradictory requirements, missing product decisions, irreversible
architecture choices, security-sensitive changes beyond the spec's explicit scope,
possible data loss, destructive migrations (out of V1 scope entirely), unresolvable
test failures, production deploys with material risk. Medium never bypasses quality
gates — it only bypasses waiting for a human.

## Extensibility seams (V2 lands here, nothing else moves)

- `implementation.ImplementationAgent` → LLM-backed generator, more stacks
- `gitops.GitAdapter` → GitHub adapter (real PRs)
- `deployment.DeploymentAdapter` → container/cloud targets
- `telemetry.MetricsRecorder` → real analytics sink
- `policies` rules → org-specific risk policy files

## What V1 deliberately is not

No LLM calls, no cloud, no migrations, no UI, no multi-agent orchestration. The agent
seats are filled by deterministic rule/template providers so every decision is
explainable and every test runs offline (see `docs/adr/ADR-002`).
