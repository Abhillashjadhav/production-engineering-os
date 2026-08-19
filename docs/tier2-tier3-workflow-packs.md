# Tier 2 and Tier 3 governed workflow packs

Issues: #123, #124, #125.

These packs extend the same Personal Execution OS contract used by Tier 1. They are not
standalone prompts. Every run has an outcome contract, per-task evidence allowlist,
deterministic checks, exact approval payloads, a mobile review, and a verified report.

## Tier 2: operational completion

| Workflow | User outcome |
|---|---|
| `prd-architecture-task-compiler` | Traceable PRD, architecture brief, and task packet |
| `release-readiness-room` | Evidence-bound go/no-go record |
| `experiment-to-decision` | Hypothesis, result, and decision record |
| `incident-to-prevention` | Owned prevention work with verification checks |
| `migration-impact-planner` | Dependency-bound migration and rollback plan |
| `docs-runbook-drift-maintainer` | Evidence-backed documentation repair proposal |
| `customer-research-synthesis` | Sourced themes with conflicts preserved |
| `competitive-market-watch` | Freshness-aware market change report |
| `verified-executive-update` | Executive update generated only from verified state |

## Tier 3: governed building and learning

| Workflow | User outcome |
|---|---|
| `research-to-prototype` | Evidence-bound prototype contract and test plan |
| `idea-to-deploy-starter` | Starter plus cost, security, monitoring, and rollback checks |
| `data-to-small-tool` | Small-tool contract, transformations, and tests |
| `repo-doctor` | Repository diagnosis, bounded repair plan, and verification commands |
| `learning-to-build-coach` | Sequenced practice tasks and deterministic feedback |
| `career-proof-pack` | README, demo outline, and case-study evidence pack |

## Run all 21 packs

```bash
pmpe personal-demo quickstart --output /tmp/pmpe-all-tiers
```

Run one pack from a generated starter:

```bash
pmpe personal-workflows starter \
  --pack repo-doctor \
  --output /tmp/pmpe-repo-doctor
pmpe personal-workflows run \
  --context /tmp/pmpe-repo-doctor/synthetic-workflow-request.json \
  --output /tmp/pmpe-repo-doctor-run
```

The output includes `workflow-catalog.json`, the task graph, workflow results, evidence
ledger, approval outbox, mobile review, and verified execution report.

## PMOS boundary

Guided Mode exposes the versioned catalogue at `/api/workflows/catalog`. The catalogue
declares the problem, output, inputs, permissions, deterministic checks, budget, approvals,
and recovery rule for every extended pack.

Local identity remains identity matching, not authentication. Protocols and fakes do not
claim a live provider. Sending, publishing, merging, deploying, purchasing, or destructive
actions require an authenticated production adapter and a fresh exact approval. PEOS remains
the implementation and verification authority for engineering changes.
