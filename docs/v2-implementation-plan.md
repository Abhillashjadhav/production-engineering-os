# V2 implementation plan

> **Historical / superseded.** This completed V2 plan is retained for provenance only.
> See [README.md](../README.md) for the authoritative frozen alpha and current claim
> boundary.

## The two-plane design (PD-11)

```
 Claude Code plane (generative)                Python core (deterministic authority)
 ──────────────────────────────                ─────────────────────────────────────
 /production-engineer skill        drives      pmpe eng CLI — the ONLY way state moves
 .claude/agents/v2-*  produce artifacts  ──►   submissions validated against schemas,
   architect / planner / router                stage order, digests; recorded in the
   specialists / integration                   evidence ledger (JSONL, artifact digests)
   4 read-only reviewers / fixer         ◄──   gates, trajectory evals, drift, policy
```

Python never calls a model. Agents never mutate run state directly — they write
artifact files; `pmpe eng submit …` is the admission gate that validates, digests,
and records them. Everything the core does is therefore testable in CI with
**fixture agent outputs** (labeled synthetic); a live session uses the same
machinery with real agent outputs. This "live vs deterministic fixture mode" is a
property of where artifacts come from, not two code paths.

## New modules (all consuming reused V1 infrastructure)

| Module | Solves (tested requirement) |
|---|---|
| `pmpe/contracts/` — model, canonical digest, versioned store, ProductChangeRequest | PD-03 immutability, fail-closed mutation, versioning, unresolved-question blocking |
| `schemas/product_decision_contract.schema.json` (+ packaged copy) | contract structure validation via the existing SchemaValidator |
| `pmpe/agents/` — definition registry (frontmatter parser), permission model, router validation | PD-05/PD-06: read-only proof by tool config; minimum-routing enforcement with explicit not-selected reasons |
| `pmpe/engineering/` — EngineeringRun stage machine, evidence ledger, candidate freeze (commit+tree digest+manifest), artifact submissions, worktree isolation | stage order, resume, idempotence, frozen candidate, candidate-manifest.json |
| `pmpe/assurance/` — typed findings (PROPOSED→VERIFIED), reconciliation policy, fixer allowlist + scope gate, read-only runtime guard | PD-06/PD-07: preserved findings, accepted-IDs-only fixing, verifier ≠ fixer, tree-digest proof reviewers wrote nothing |
| `pmpe/quality/test_evidence.py` — stdlib unittest evidence runner (node id, outcome, failure kind: assertion/import/error/skip) | executed evidence; import-red and skips distinguishable |
| `pmpe/audit/executed.py` — executed traceability chain + per-requirement VERIFIED/FAILED/NOT_PROVEN/BLOCKED_PRODUCT_DECISION | anti-gaming: markers alone never prove coverage |
| `pmpe/evals/` — trajectory checks (14), agent eval registry + runner, drift reporter (A–E) + HOLD, judge calibration queue | planted trajectory/drift fixtures must be caught |
| `pmpe/deployment/policy.py` (+ simulated production executor) | environment ladder, digest-bound approval, canary/rollback fixture, honest fixture labeling |
| `pmpe/cli/` package (V1 commands preserved; adds `contract`, `change-request`, `eng`, `evals`, `drift`) | module budget; every capability reachable from the CLI |
| `.claude/agents/v2-*.md` (11 defs), `.claude/skills/production-engineer/` (fixtures first) | Claude-plane entry points; reviewers read-only by tool list |
| `evals/` (repo root) — agent cases, synthetic baseline, planted fixtures, provisional `thresholds.yaml` | drift comparison inputs |
| `examples/v2-demo/` + `tests/e2e/test_v2_demo.py` | the honest synthetic demonstration |

Explicitly NOT built (per PDs and principles): cloud adapter, loop runtime,
daemons, queues, model SDK calls, dashboards, new runtime dependencies.

## The demonstration (honesty contract)

Deterministic parts execute for real: contract locking, digest freeze, V1
generator as the demo's implementation executor (real code, real tests, real
gates, real local deploy), executed-traceability, trajectory evals, drift
comparison, deployment policy. Generative artifacts (architecture pack, plan,
routing decision, reviewer findings) are committed fixtures marked
`"synthetic": true` — validated by the same admission machinery a live run uses.
Planted failures: an `eval()` code defect, a requirement with no executed test
(conformance), an unjustified abstraction (complexity ledger), a reordered-stage
event log and a drifted eval result (trajectory/drift). Production approval is
demonstrated blocked; no production deployment is claimed.

## Commit sequence (small, test-first)

1. docs: V2 assessment, plan, locked decisions, baseline evidence
2. test: contract + change-request behaviour → 3. feat: contracts module + CLI
4. test: agent routing + permission fixtures → 5. feat: agent defs + registry/router/guards
6. test: assurance behaviour → 7. feat: findings, reconciliation, fixer gate, candidate freeze, ledger
8. test: executed traceability anti-gaming → 9. feat: test evidence + executed traceability
10. test: agent/trajectory eval fixtures → 11. feat: evals + drift + thresholds
12. test: deployment approval policy → 13. feat: environment ladder + simulated production
14. test+feat: engineering run engine + `pmpe eng` CLI
15. test: skill fixtures (before SKILL.md, per CLAUDE.md) → 16. feat: /production-engineer skill
17. feat: synthetic demo + e2e proof
18. docs: README identity, architecture, limitations; CI
19. fix: independent final review findings → draft PR
