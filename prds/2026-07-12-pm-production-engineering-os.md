# PRD: PM Production Engineering OS (V1)

**Date:** 2026-07-12
**Status:** Approved (autonomous run — the full task specification served as the PRD source; see DECISIONS.md)

## Problem
Approved MVP specifications produced by the PM OS die in the handoff to engineering: a PM
holding a validated, structured spec still needs engineers for every step between "spec
approved" and "product live", even when the build is a routine CRUD product. The cost is
days-to-weeks of engineering intervention per build for work that is mechanical when the
spec is complete.

## User
A product manager (Abhillash first, then AI/technical PMs) holding a structured MVP spec
from pm-agent-os. Current alternative: hand the spec to an engineer, or vibe-code it with
no validation, no tests-first discipline, no review, and no traceability.

## Success metric
One sample PM OS specification runs end-to-end — validate → plan → architecture → tests
→ implementation → quality gates → review → fix → merge gate → local deploy → production
verification → traceability report — with zero human intervention, and the repo's own
E2E test proves it (binary: `pytest tests/e2e` passes).

## Scope (v1)
- Spec ingestion (JSON/YAML) with schema validation and normalization
- Requirement validator: missing fields, contradictions, untestable acceptance criteria, activity-only NSM detection
- Deterministic engineering planner, architecture agent (with ADRs), test architect (tests before code), implementation agent
- One reference stack: Python-stdlib CRUD API with token auth and SQLite persistence
- Quality gate runner (format, lint, types, unit, integration, e2e, security, regression)
- Local git workspace per run, PR record, deterministic PR review, safe-fix agent, merge gate
- Local process deployment with health check + user-journey smoke test, rollback instructions
- Policy engine with low/medium/high risk levels and file-based human approval gates
- Telemetry hooks + final traceability report mapping every requirement to code, tests, review, deployment

## Out of scope (cut from v1)
- LLM-backed agent providers (interfaces exist; V1 providers are deterministic)
- Any cloud deployment, database migrations, multi-stack support, visual UI
- Remote GitHub PR automation (local PR record only; adapter interface exists)
- Billing, teams, permissions, marketplace, enterprise features

## Non-goals (failure modes)
- If the pipeline merges anything while a blocking finding or failing gate remains, V1 has failed.
- If any automated decision cannot be explained from logged rules and artifacts, V1 has failed.
- If a high-risk decision proceeds without a recorded human approval, V1 has failed.
- If the system silently makes a product decision (e.g., invents scope), V1 has failed.

## Decisions log
See /DECISIONS.md (running architectural log for this build).
