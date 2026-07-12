# ADR-003: Reference stack — python-stdlib-crud-api

Status: Accepted · Date: 2026-07-12 · Risk: low · Reversibility: reversible (adapter seam)

## Context
V1 supports one reference application type. The task suggests "a basic CRUD product
with authentication and persistence". Generated products must build, test, and deploy
in any environment the OS runs in.

## Decision
The single V1 stack is `python-stdlib-crud-api`: `http.server`-based JSON API, bearer
token auth (token injected via environment variable, compared with
`hmac.compare_digest`), SQLite persistence, unittest test suite. Zero third-party
dependencies in the generated product.

## Consequences
+ Generated product runs and tests hermetically; deploy verification is real (process + HTTP).
+ Auth and persistence exercised — the security gate has something real to check.
− Not production-grade for scale (single process, static token) — stated in the
  generated product's own README and in rollback/limitations docs. Additional stacks
  (Flask/FastAPI/Node) arrive as new `StackAdapter`s in V2.
