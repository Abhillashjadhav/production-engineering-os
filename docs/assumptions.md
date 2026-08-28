# Assumptions and open decisions (Phase 2)

Conservative assumptions made where safe; anything that materially affects product
behavior is listed under "Decisions that would normally need the PM".

## Documented assumptions

| # | Assumption | Basis | Risk if wrong |
|---|---|---|---|
| A1 | Python 3.11 stdlib-first is an acceptable implementation stack for the OS itself | Only runtime in repo/env; "boring, proven technology" principle | Low — modules are small, portable |
| A2 | V1 agent seats are deterministic rule/template providers behind interfaces; LLM providers arrive as V2 adapters | Task requires explainable decisions, offline tests, no single-LLM dependency | Medium — deterministic generation limits V1 to the reference stack, which V1 scope already limits |
| A3 | Reference product = `python-stdlib-crud-api`: token-auth + SQLite CRUD API ("basic CRUD product with authentication and persistence" from the task's suggested list) | Hermetic: generated product has zero third-party deps, runs/tests anywhere | Low |
| A4 | "PR" in V1 = local git branch + PR record artifact; no remote calls | Task forbids assuming remote permissions | Low — `GitAdapter` seam exists |
| A5 | "Deploy" in V1 = local process on a free localhost port + deployable artifact (run script, Dockerfile, instructions) | Task: "deploy to a safe environment where supported" | Low — `DeploymentAdapter` seam exists |
| A6 | Historical V1 approvals are file-based fixtures with no shipped mutation command | V1 is test-only; Phase Zero owns admissible execution authority | Retired from product surface |
| A7 | YAML input supported via PyYAML (present in env, declared as dependency); JSON via stdlib | Task: "Support JSON or YAML" | Low |
| A8 | Run outputs live under `./runs/` (gitignored); the repo itself is never the build workspace | Keeps the OS repo clean; test isolation | Low |
| A9 | Security gate uses bandit when available and always runs the built-in deterministic scanner | bandit not preinstalled everywhere; CI installs it | Low |
| A10 | The three-gate/fixtures discipline of this repo applies to *skills*; the new Python system is governed by its own pytest suite + CI, and lands as one PR (one concern: the V1 slice) | CLAUDE.md scope | Low |

## Decisions that would normally need the PM (defaulted, flagged)

1. **Deterministic vs LLM-backed generation in V1** — defaulted to deterministic (A2).
   Changing this changes cost, latency, and failure modes; it is the first V2 decision.
2. **Reference stack choice** (A3) — a different reference product (e.g., a web UI app)
   would change the test architect and deployer templates.
3. **Merge semantics** — V1 merges only inside the generated workspace's local git.
   Nothing ever merges into *this* repository automatically.

No open questions block V1: the task specification explicitly authorizes proceeding
through low-risk engineering decisions without further approval.
