# Issue 187 — Phase C recorded tool-agent test plan

## Scope

Prove one exact `recorded_tool_agent@1.0.0` path reaches the existing
`RELEASE_READY` evidence terminal under a strictly offline, credential-free,
non-deploying boundary. This does not introduce a template interface, provider
framework, plugin registry, live model, network tool, write tool, or deployment path.

## Positive proof

- Compile the Phase B contract and approval before executing any replay step.
- Match every recorded model request against the exact ordered message history,
  model identity, committed tool-schema digest, fixture digest, and previous step.
- Dispatch only `repository.lookup/v1` over `support-kb-v1` and
  `pure.transform/v1`; validate closed argument and result schemas.
- Seal the compiled plan, fixture, resource, schemas, each replay event, final
  answer, and `deployment_authority: false` into the existing hash-chained ledger.
- Reproduce byte-identical terminal evidence across three clean runs, excluding
  the caller-selected run identifier.

## Required negative proof

- fixture identity/digest, missing/extra/reused/out-of-order step, request,
  response, history, model, tool-schema, and terminal-consumption mismatch;
- unknown tool, extra/missing/invalid argument, unauthorized dataset, duplicate
  JSON key, direct prompt mutation, indirect resource mutation, and result schema
  mismatch;
- step, model-attempt, tool-call, byte, and wall-time exhaustion;
- provider credential or any ambient runtime environment input;
- traversal/symlink/path, subprocess, network, dynamic-code, recursive-agent,
  write, approval, cloud, and deployment authority remain structurally absent.

## Delivery gates

Red collection before implementation; focused tests; installed-wheel execution;
Ruff; strict mypy; full CI; fresh exact-head review; every P0/P1/P2 thread resolved.

