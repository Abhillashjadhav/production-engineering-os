# Production Engineering OS — V2 guide

PM Agent OS decides what should be built and verifies product reasoning.
Production Engineering OS turns that approved decision into verified software
and keeps it conformant. This document is the V2 reference: the contract, the
run, the agents, the assurance system, the evals, and the deployment ladder.

The twelve locked product decisions behind this design are recorded in
[v2-approved-product-decisions.md](v2-approved-product-decisions.md) (PD-01..PD-12).

## The two planes (PD-01/PD-02/PD-11)

| Plane | Owner | Owns |
|---|---|---|
| Product intent | PM Agent OS (`/pm`, the 40 skills) | what to build, for whom, why, acceptance |
| Engineering execution | Production Engineering OS (`pmpe`) | how it is built, verified, and deployed |

Inside the engineering plane the split repeats (PD-11): **Claude Code is the
runtime** for generative work (architecture packs, plans, routings, code,
reviews — produced by the agents in `.claude/agents/v2-*.md`), and the
**deterministic Python core owns state, validation, and gates**. There are no
model SDKs, API keys, or provider calls anywhere in the product: an agent's
output enters a run only through `pmpe eng submit`, where a deterministic
validator admits or rejects it. CI exercises the same admission machinery with
labeled synthetic fixtures.

## The ProductDecisionContract (PD-03)

The contract is the only source of product behaviour — never chat history,
never repository archaeology. Format: JSON validated against
`schemas/product_decision_contract.schema.json`; the load path also enforces
unique requirement ids. Key fields:

- identity/approval: `contract_id`, `contract_version`, `contract_status`,
  `approved_by`, `approved_at`, `source_digest`
- intent: `product_name`, `problem`, `target_user`, `desired_outcome`,
  `scope`, `out_of_scope`
- verifiable behaviour: `functional_requirements` (each with a `capability`),
  `acceptance_criteria` (each bound to a requirement),
  `binary_release_gates`, `scored_eval_rubric`, `golden_cases`
- guardrails and context: `north_star_metric`, `leading_metrics`,
  `guardrails`, `non_functional_requirements`, `known_risks`,
  `approved_product_decisions`, `unresolved_questions`, `required_approvals`

**Runnability** is semantic, not structural: only an `APPROVED` contract with
a named approver, an approval timestamp, and zero unresolved product-critical
questions can enter a run (`pmpe contract validate` reports the blockers).

**Immutability**: `pmpe eng start` registers the contract and locks a
canonical digest (sha256 over sorted-keys/minimal-separator JSON) into
`contract.lock.json`. Every later load re-verifies it and fails closed on any
mutation. Registering the same version with a different digest is refused —
a changed contract is a **new version**, never an overwrite. `pmpe contract
diff` shows id-keyed added/removed/changed entries between versions.

## The ProductChangeRequest flow (PD-03/PD-04/PD-07)

Engineering never edits product intent. When a run surfaces a product
question — a reviewer marks a finding `requires_product_decision`, or the
architect faces a user-visible/scope/AC/data-policy/commercial/irreversible
trade-off (PD-04) — it becomes a ProductChangeRequest recording the finding,
why implementation cannot proceed safely, the options, the engineering
consequences, and a recommended technical default. The decision owner decides
(`pmpe change-request decide`); an APPROVED PCR must name the resulting new
contract version, and that version starts a **new run**. Agent outputs
containing `scope_changes`, `acceptance_criteria_changes`,
`requirement_changes`, or `metric_changes` are rejected at admission.

## The engineering run (`pmpe eng`)

Stage machine (each stage advanced only by an admitted artifact or an
engine-owned action):

```
contract_lock → assessment → architecture → plan → route → implement
    → integrate → freeze → review → reconcile
    → [fix → retest → refreeze → verify]   (only when findings were accepted)
    → draft_pr → deploy → release_report → complete
```

Every step appends a digest-bound event to `ledger.jsonl` (the evidence
ledger — the run's system of record, never a chat transcript). The event
grammar is documented in `src/pmpe/evals/trajectory.py` and is exactly what
the trajectory evals audit.

Commands: `start`, `status`, `resume`, `assess`, `submit`, `freeze`,
`review-begin`/`review-end`, `reconcile`, `gates`, `verify-fix`, `draft-pr`,
`approve-production`, `deploy`, `report`. Exit codes: 0 success, 1 pipeline
error, 2 rejected/malformed artifact, 3 blocked on a human gate.

**Resume**: `run-state.json` is the single persisted state document.
`pmpe eng resume` re-verifies the locked contract, appends nothing to the
ledger, and continues at the persisted stage; completed stages reject
re-submission instead of silently re-running.

## The agent plane (PD-04/PD-05/PD-06)

Agent definitions live in `.claude/agents/v2-*.md`; the frontmatter tool list
is the enforceable permission surface.

| Agent | Stage | Permissions |
|---|---|---|
| v2-system-architect | architecture | read-only |
| v2-implementation-planner | plan | read-only |
| v2-engineer-router | route | read-only |
| v2-backend-engineer, v2-test-engineer | implement | write, **worktree isolation** |
| v2-integration-engineer | integrate/freeze | write |
| four reviewers (code, product-conformance, architecture-simplicity, eval-integrity) | review | **read-only, provable** |
| v2-approved-findings-fixer | fix | write, scoped to ACCEPTED findings |

Read-only is a *provable* property: `tools ⊆ {Read, Grep, Glob}`. An empty
tool list means "inherit all tools" in Claude Code and therefore fails the
read-only check by design. At run time the engine adds a second proof: a
content snapshot before each review, verified after it (`readonly_check`
ledger events; a modified tree fails the round).

**Routing (PD-05)**: specialists are execution agents, not architecture. The
router must produce the *minimum* covering set — every task routed exactly
once to the profile owning its capability, no zero-task selections, and every
unused profile explicitly justified in `not_selected`. A selected specialist
without an agent definition file is refused.

## Assurance (PD-06/PD-07)

Four independent reviewers examine the **same frozen candidate**
(`candidate-manifest.json` binds commit, tree digest, and contract digest;
any change to the tree invalidates reviews, approvals, and deployments) in
fresh contexts, blind to each other. Reviewers never fix.

Finding lifecycle: `PROPOSED → ACCEPTED | REJECTED | DUPLICATE |
PRODUCT_DECISION_REQUIRED`, then `ACCEPTED → FIXED → VERIFIED`. Reviewer
originals are stored verbatim and never rewritten. Reconciliation is
deterministic policy: duplicates (same file+line+title) are linked, never
erased; product findings become PCRs; low-severity + mechanically-fixable
findings auto-accept under the named rule REC-001; everything else needs a
recorded owner decision — undecided findings block the run (exit 3), they are
never silently dropped. The fixer may touch only ACCEPTED finding ids, and
the verifier of a fix is never its fixer. After fixes: retest (the workspace
suite actually re-runs), re-freeze, verify.

## Executed traceability

Markers never prove coverage; execution does. The evidence harness runs the
workspace's test suite in a subprocess and records per-node outcomes with
failure kinds (`assertion`, `import`, `error`, `skip`). Classification per
requirement:

- **VERIFIED** — a mapped test executed and passed, none failed by assertion
- **FAILED** — a mapped test failed through its own assertion (meaningful red)
- **NOT_PROVEN** — unmapped, not executed, skipped, or dead on import — none
  of which is evidence
- **BLOCKED_PRODUCT_DECISION** — an open PCR covers the requirement

## Evals and drift

Three layers, all deterministic and CI-runnable (`pmpe evals run --suite all`,
`pmpe drift compare`):

1. **Agent evals** (`evals/agents/*.yaml`) — each case is validated by the
   same submission validators the engine uses at admission, so a planted
   failure an eval misses would also slip into a live run, and vice versa.
   Permission cases (read-only, worktree) and stage fire/no-fire cases are
   auto-generated from the agent definitions and the stage map.
2. **Trajectory evals** — TRAJ-01..TRAJ-14 over an evidence ledger: contract
   locked before architecture, digest constancy, tests before implementation,
   router-selected implementers only, freeze before review, same-candidate
   reviews, recorded read-only proof, fixer scoped to accepted findings,
   product findings produce PCRs, retest after fixes, draft PR after
   assurance, production deploys carry an approval digest. Any violation is a
   hard HOLD.
3. **Drift** — baseline vs current across five categories (agent behaviour,
   trajectory, eval coverage, judge calibration, engineering output). Any NEW
   hard-gate failure absent from the baseline is a HOLD, always. Thresholds
   in `evals/thresholds.yaml` are **provisional and labeled so** — they are
   example defaults, not production-calibrated values.

## Deployment ladder (PD-08/PD-09)

| Environment | Gate |
|---|---|
| local, test | automatic once required checks pass |
| staging | automatic once every assurance gate passes |
| production | named, recorded human approval **bound to the exact candidate digest** |

A changed candidate invalidates the approval (fail closed). Readiness
additionally requires rollback instructions (`deploy/ROLLBACK.md`), a
runnable artifact (`deploy/run.sh`), and verified health + user-journey
checks. The OS records a **draft PR** and never merges (PD-08). There is
deliberately **no real cloud adapter**: the production path executes only in
fixture mode and its report always states "no real environment was touched."

## Live mode vs fixture mode

- **Live**: the `/production-engineer` skill drives a run inside Claude Code —
  it spawns the stage agents, submits their artifacts through `pmpe eng
  submit`, and relays the engine's verdicts. Generative quality comes from
  the live agents; admission, gates, and evidence are the Python core's.
- **Fixture**: CI and `pmpe demo` drive the same engine with labeled
  synthetic artifacts (`"label": "synthetic-fixture"`). This proves the
  machinery — validators, gates, ledger, trajectory audits — deterministically.
  It does not prove live generation quality; that is what the agent evals and
  the review round are for. Every synthetic artifact and report says it is
  synthetic.

## The demonstration

`pmpe demo --base-dir <dir>` runs the complete pipeline against a workspace
with four planted failures and writes an evidence-quoting report; see
[examples/v2-demo/README.md](../examples/v2-demo/README.md) and
`tests/e2e/test_v2_demo.py` for exactly what is asserted.

## What V1 claimed vs what V2 enforces

V1's review step was a deterministic checker (not independent reviewers), its
traceability bound requirements to test *markers* (annotations, not proof of
execution), and its deployment stopped at a local process. V2 replaces these:
four independent read-only reviewers on a frozen candidate, executed
traceability that counts only real test executions (skips and import-dead
tests count against coverage, not toward it), and an explicit deployment
ladder that ends at a fixture-mode production path behind a digest-bound
human approval. V1's pipeline (`pmpe run`) is preserved unchanged and its
stack generators serve as the demo's deterministic implementation executor.
