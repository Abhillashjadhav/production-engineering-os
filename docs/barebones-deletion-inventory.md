# Bare-bones core deletion inventory

Issue: #140

Status: architecture frozen; inventory only. No item is deleted until its surviving
consumer and E1 coverage are identified.

## Frozen core

```text
PMOS contract
  -> deterministic compile + coverage
  -> one composable template
  -> meaningful baseline RED
  -> Coder
  -> assertions + evals + local security
  -> RELEASE_READY or HALTED
  -> human decision
```

The primary user is an engineer operating the CLI with an approved PMOS contract.
The core stops at `RELEASE_READY`. It has one mandatory LLM worker (`Coder`), one
external adapter (`ModelProvider`), one hash-chained event log, and one content-
addressed blob directory.

## Current surface

- 32 top-level Python packages under `src/pmpe`.
- About 51,000 source lines and 94,000 Python source-plus-test lines.
- 29 lifecycle states, including staging, canary, production, rollback, GitHub PR,
  review, and multiple pre-build planning states.
- At least four overlapping evidence implementations: `audit`, `evidence`,
  `engineering.ledger`, and `quality.test_evidence`.
- Separate planner, architecture agent, implementation agent, reviewer, fixer,
  specialist router, repository adapter, deployment adapters, and workflow engines.

This surface is materially larger than the frozen product requires.

## Package decisions

| Existing package | Decision | Frozen-core destination | Reason / precondition |
|---|---|---|---|
| `contracts` | KEEP + REDUCE | `contracts` | Keep canonical digest, schema, grammar, compiler, and human-test references. Remove legacy format machinery only after one real PMOS bundle migrates losslessly. |
| `validation` | MERGE | `contracts` | Contract completeness, contradiction, ownership, and compile-time coverage are one boundary. |
| `ingestion` | MERGE | `contracts` | Loading and normalization are contract intake, not a separate subsystem. |
| `admission` | MERGE | `contracts` | Admission is the compiler result: valid, invalid, or human input required. |
| `testing` | KEEP + REDUCE | `contracts` / `verify` | Retain deterministic assertion compilation and meaningful-RED admission. Delete test-planning abstractions not used by E1. |
| `stacks` | MERGE → ONE | `template` | Keep one composable scaffold. Remove stack selection after E1 proves the surviving template. |
| `implementation` | KEEP + REDUCE | `coder` | One bounded Coder interface and workspace. No Test Writer or Repairer role. |
| `planning` | DELETE / INLINE | compiler proposal input | Planning cannot be an authoritative worker or state. A model proposal may be validated by the compiler. |
| `agents` | DELETE / INLINE | `coder` | Registry/router are unnecessary with one mandatory worker. |
| `architecture` | DELETE | none | Architecture generation and taste-grading are not part of the minimum runtime. Keep only ordinary import-boundary tests if E1 needs them. |
| `orchestration` | KEEP + REWRITE SMALL | `engine` | Replace 29 states with `VALIDATED`, `BUILDING`, `VERIFYING`, `RELEASE_READY`, `HALTED`, `STOPPED`. Preserve proven budget and append-only transition invariants. |
| `execution` | MERGE | `engine` | Execution kernel is an implementation detail of the one engine. |
| `policies` | MERGE | `engine` | State, budget, retry, and release rules belong to the engine. |
| `workflows` | MERGE / DEFER | `engine` | Keep only the contract-to-release-ready path. Product-specific support workflows move out of core. |
| `audit` | MERGE | `evidence` | Convert semantic claims to events and blobs; retain digest/integrity primitives. |
| `evidence` | KEEP + REDUCE | `evidence` | One versioned hash-chained `events.jsonl` plus `.pmpe/blobs/<sha256>`. Release bundle is a generated projection. |
| `artifacts` | MERGE | `evidence` | Blob persistence is evidence storage. No storage interface. |
| `telemetry` | MERGE | `evidence` | Runtime events are the evidence log; aggregate metrics are derived views. |
| `engineering` | MERGE + REDUCE | `engine` / `evidence` | Keep candidate digest, bounded work, and finding identity. Remove PR/merge/deployment lifecycle from core. |
| `quality` | KEEP + REDUCE | `verify` | One verifier result. Tests, deterministic evals, coverage, secret scan, SAST, and dependency scan. Critical/high and credentials block. |
| `evals` | KEEP + REDUCE | `evals` | Keep E1-E5 and product-declared deterministic evals. Rubric scores remain advisory or are deleted. |
| `assurance` | MERGE / DELETE | `verify` | Findings are verifier output. Remove separate fixer and review loops. |
| `review` | DELETE RUNTIME | evidence annotation | One advisory review fires after deterministic PASS and cannot transition state or block. Human owns release. |
| `repository` | DEFER | outside core | No mandatory GitHub/repository adapter. Retain only if a post-E1 consumer is approved. |
| `gitops` | DEFER | outside core | Local Git convenience is not necessary to prove contract-to-release-ready. |
| `deployment` | DELETE FROM CORE | outside repository core | Core stops at `RELEASE_READY`; no deployment flags or provider credentials. |
| `fullstack` | MOVE / DEFER | product/template fixture | It is a generated-product example, not core orchestration. Use it only if selected as E1. |
| `guided` | DEFER | product adapter | CLI is the primary v1 interface. A UI must later consume the same engine. |
| `personal` | MOVE OUT OF CORE | separate product | Personal execution workflows are not Production Engineering OS runtime responsibilities. |
| `demo` | KEEP AS FIXTURE | E1 fixture | Replace synthetic success claims with one real contract run. |
| `repository`, `guided`, `personal`, `fullstack` dependencies in CLI | REMOVE FROM DEFAULT PATH | thin CLI | Default CLI exposes compile, run, status, evidence, and serve only. |
| `domain` | KEEP + REDUCE | shared types | Retain only types used by the frozen core. |
| `cli` | KEEP + REDUCE | `cli` | Thin calls over the compiler and engine; no alternate business logic. |

## State inventory

| Frozen state | Absorbs existing states |
|---|---|
| `VALIDATED` | contract received/approved, repository analysed, architecture/test/implementation planned |
| `BUILDING` | draft PR open, implementation and repair in progress |
| `VERIFYING` | verification failed, review required/failed |
| `RELEASE_READY` | PR ready; no merge or deployment implication |
| `HALTED` | contract invalid, product input required, blocked, budget exceeded, repeated finding |
| `STOPPED` | explicit human cancellation |

`TESTS_FAILING` is an event/invariant, not a state. `RELEASED`, PR merge, staging,
canary, production, live observation, and rollback are outside the core.

## Evidence inventory

The surviving storage is:

```text
.pmpe/runs/<run-id>/events.jsonl
.pmpe/blobs/<sha256>
```

Each event contains `schema_version`, `sequence`, `previous_digest`, `event_digest`,
`run_id`, `state`, `event_type`, `subject_digest`, and referenced blob digests.
Contract, plan, candidate diff, verifier results, findings, and advisory review bodies
are blobs. Status, explanation, and the release evidence bundle are deterministic
projections over the event chain.

## Deletion order

1. Freeze the current default branch and retain compatibility tests.
2. Define and validate the acceptance-criteria grammar against one real PMOS contract.
3. Add compile-time task/test coverage and the human-authored test reference.
4. Prove meaningful RED on the untouched template, including the explicit
   `satisfied_by_template` exception.
5. Establish the two-file evidence format and migrate one E1 run.
6. Introduce the six-state engine using existing budget and transition invariants.
7. Route the CLI E1 path through compiler → template → Coder → verify.
8. Pass E1, then E2-E5.
9. Delete or move packages only when no surviving E1-E5 import or compatibility
   obligation depends on them.
10. Reopen backlog items only when a failing eval demonstrates the need.

## Stop conditions

- If the real PMOS contract cannot express most acceptance criteria without guessing,
  stop and revise the grammar before changing runtime code.
- If a deletion breaks an E1-E5 requirement, restore the smallest necessary primitive,
  not its previous subsystem.
- No new adapter, worker, lifecycle state, evidence type, or template is admitted
  without a second real consumer or a failing eval.
