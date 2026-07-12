# ADR-002: Deterministic rule/template agent providers in V1

Status: Accepted · Date: 2026-07-12 · Risk: medium · Reversibility: reversible (interface seam)

## Context
The task requires: explainable automated decisions, tests-before-implementation that
run in CI with no network, deterministic re-runnable builds, and no dependency on a
single LLM provider. LLM-backed generation satisfies none of these without substantial
eval infrastructure that is out of V1 scope.

## Decision
Every agent seat (planner, architecture, test architect, implementation, reviewer,
fixer) is an interface. V1 ships deterministic providers: rule engines over the spec
and code templates for exactly one reference stack. LLM-backed providers are V2
adapters implementing the same interfaces.

## Consequences
+ Every decision traces to a named rule; the whole pipeline is a deterministic function of the spec.
+ The E2E suite proves the full lifecycle hermetically.
− V1 can only build products expressible in the reference stack templates — acceptable,
  because V1 scope is exactly one reference application type.
