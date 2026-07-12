# ADR-001: Python 3.11, stdlib-first, single package

Status: Accepted · Date: 2026-07-12 · Risk: low · Reversibility: reversible

## Context
The OS needs a runtime that exists in every target environment (local, CI, Claude Code
sandboxes) and supports strong typing, and the repo already uses Python for tooling.

## Decision
Implement the OS as one Python 3.11 package (`src/pmpe/`) with PyYAML as the only
runtime dependency. Dev tooling: ruff (format+lint), mypy --strict, pytest, bandit.

## Consequences
+ Installs anywhere `pip` exists; tests run offline; boring and proven.
+ mypy --strict over Protocol interfaces gives compile-time seams.
− No async/parallel step execution in V1 (not needed; steps are sequential by design).
