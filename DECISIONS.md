# DECISIONS.md — running architectural log

Format: "YYYY-MM-DD: Chose X over Y because Z."

- 2026-07-12: PRD created from the task specification itself (autonomous run — the
  prd-first 5-question protocol could not run interactively; the task spec answers all
  five questions). PRD: prds/2026-07-12-pm-production-engineering-os.md.
- 2026-07-12: Chose Python 3.11 + stdlib-first over Node/Go because the environment
  ships Python with ruff/black/mypy/pytest available, the existing repo tooling
  (tests/lint_skill.py) is Python, and "boring, proven technology" is a stated principle.
- 2026-07-12: Chose deterministic rule/template-based V1 agent providers behind
  `AgentProvider`-style interfaces over LLM-backed providers because the task requires
  explainable decisions, offline-runnable tests, and no single-LLM dependency; LLM
  providers become V2 adapters. (ADR-002)
- 2026-07-12: Chose one reference stack — python-stdlib CRUD API (token auth + SQLite)
  — over Flask/FastAPI because generated products then run and test hermetically with
  zero third-party dependencies. (ADR-003)
- 2026-07-12: Chose file/CLI-based human approvals (`pmpe approve`) over interactive
  prompts because the pipeline must be resumable and non-interactive-safe. (ADR-006)
- 2026-07-12: Chose additive repo layout (src/, schemas/, examples/, docs/, tests/unit|
  integration|e2e|fixtures alongside existing skill fixtures) over restructuring because
  the repo's pm-agent-os content is working code and must not be disturbed.
