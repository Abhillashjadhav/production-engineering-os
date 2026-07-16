# V2 current-state assessment

What exists at the V1 head (`6d7977e`, PR #1), what V2 reuses, and what V1 cannot do.

## V1 modules confirmed reusable (repository evidence)

| Module | Evidence of fitness | V2 role |
|---|---|---|
| `pmpe/domain/` (models, errors, serialize incl. `atomic_write_json`) | mypy --strict clean; used by every V1 stage | Extended with contract/finding/eval models; not rebuilt |
| `pmpe/orchestration/state.py` (atomic, resumable RunState) | `tests/unit/test_workflow_state.py`, crash-recovery e2e | Pattern reused for the V2 EngineeringRun stage machine |
| `pmpe/artifacts/store.py` | used by all 18 V1 steps | Stores V2 run artifacts unchanged |
| `pmpe/telemetry/events.py` (JSONL) | e2e asserts ≥18 events/run | Extended into the V2 evidence ledger (adds digests/agent/verdict fields) |
| `pmpe/policies/engine.py` | `tests/unit/test_policy_engine.py` | Risk classification reused; deployment policy builds on it |
| `pmpe/quality/gates.py` + `security_scan.py` | integration tests incl. planted vulnerability | Deterministic gates for V2 candidates, unchanged |
| `pmpe/gitops/local.py` | real-git integration tests | Candidate freeze + worktree isolation build on it |
| `pmpe/deployment/local.py` | e2e verified real deploy | Preserved as the local executor under the new environment policy |
| `pmpe/audit/traceability.py` | unit + e2e | Superseded for proof purposes by executed traceability; retained as the structural map |
| `pmpe/cli.py` | e2e CLI contract tests | Converted to a package; V1 commands preserved verbatim |
| V1 stack generators (`pmpe/stacks/*`) | red→green + capability-matrix tests | Used honestly in the V2 demo as the deterministic implementation executor — NOT presented as a general autonomous engineer |

All 151 V1 tests are preserved and must stay green (docs/evidence/v2-baseline-verification.md).

## What V1 cannot do (the V2 gap)

1. **No product/engineering boundary object.** V1 ingests an MVP spec directly; there is
   no approved, versioned, digest-locked contract, and no change-request mechanism —
   a spec edit mid-run would go unnoticed.
2. **Generation and review are the same codebase.** The V1 reviewer is deterministic
   code shipped with the generator; there is no independent, fresh-context,
   provably read-only assurance plane, and no separation of reviewer/fixer/verifier
   identities.
3. **Traceability is declared, not executed.** Coverage rests on `Covers:` markers and
   generator claims (documented in docs/known-limitations.md #1); skipped tests and
   import-error failures are not distinguished from meaningful evidence.
4. **No agent system.** V1 agents are Python classes. There are no Claude Code agent
   definitions, no routing, no permission model, no worktree isolation.
5. **No trajectory or drift measurement.** Events exist but nothing verifies stage
   order, digest constancy, self-review, or fixer scope; there is no baseline
   comparison, no judge calibration, no HOLD policy.
6. **Deployment policy is single-environment.** Local only; no environment
   classification, no digest-bound production approval.

## Constraints carried into V2

- CLAUDE.md: PR-only changes, skills need fixtures committed before SKILL.md,
  `tests/lint_skill.py` must pass on any new skill.
- No new runtime dependencies without an ADR (V1 has exactly PyYAML).
- Module budget ~400 lines (docs/technical-requirements.md), mypy --strict, ruff.
- PD-11: no model SDKs/API keys in the product; Python core stays deterministic.
