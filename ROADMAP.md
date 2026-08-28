# Roadmap — PM Production Engineering OS

> **Historical / superseded.** This roadmap predates the frozen alpha and is not a
> shipped-capability claim. See [README.md](README.md) for the authoritative current
> architecture, evidence, non-goals, and promotion gates.

## V1 (shipped) — one honest vertical slice

Spec → validate → plan → architecture → tests-first → implement → gates → PR record →
review → safe fixes → merge gate → local deploy → verified journey → traceability
report. One stack (`python-stdlib-crud-api`), deterministic agents, file-based human
gates. See `docs/` and the e2e suite for the proof.

## V2 candidates (in priority order)

1. **LLM-backed agent providers** behind the existing interfaces
   (`ImplementationAgent`, reviewer, planner) — the single highest-leverage seam
   (ADR-002). Requires: golden-set evals per agent seat before any LLM provider is
   trusted with a gate (reuse pm-agent-os `eval-engine` / `regression-gatekeeper`
   discipline), provider-agnostic client, per-run cost telemetry (guardrail metric).
2. **GitHub adapter** (`GitAdapter`): real branches/PRs/checks on a remote, PR review
   posted as review comments; the local PR record becomes the offline fallback.
3. **Second stack adapter** (`pmpe/stacks/`): Flask or FastAPI + Postgres variant to
   prove the adapter seam with a dependency-bearing stack (adds dependency-audit gate
   for generated products).
4. **Container/cloud deployment adapters**: build the already-emitted Dockerfile,
   deploy to a real staging target, keep the same health + journey verification;
   production targets remain HIGH-risk human gates.
5. **Fleet metrics aggregator**: roll per-run `metrics.json` into the North Star
   (% of builds reaching verified production + first use without engineer
   intervention) across runs; wire guardrail alarms (rollback rate, rescue rate).
6. **Web dashboard** over `runs/` (read-only first): status, escalations, approvals —
   only after the core loop has real usage.

## Explicit non-goals (unchanged from V1)

Autonomous destructive migrations, security-sensitive changes without escalation,
billing/teams/marketplace, multi-agent orchestration without a demonstrated functional
win.
