# Issue #69 — exact-SHA evidence implementation plan

This plan is subordinate to issue #69. It records the dependency-safe implementation
order without changing the issue's scope or product decisions.

## Frozen base and atomic delivery

- Base commit: `3d0c335c361b07d6031d13975b999c6918b7330c`.
- One dedicated branch and one primary draft PR close issue #69.
- The PR remains draft until exact-head verification, independent advisory review,
  finding disposition, and the ready-state recheck are complete.
- Every readiness and completion decision fails closed on absent, mutable, stale,
  wrong-subject, or unverifiable evidence.

## Implementation slices

1. **Evidence primitives and immutable storage**
   - Define stage profiles, evidence subjects/items, environment and tool identities,
     retention classes, producer/execution provenance, and sealed manifests.
   - Canonically digest every item and bundle; append with idempotent event identity;
     reject mutation, omission, duplication, incompatible environments, and stale or
     wrong-subject evidence.
2. **Exact candidate, attestation, and readiness gates**
   - Bind protected-base SHA, PR head, prospective merge tree, repository policy
     digests, executable commands/scripts, required checks, advisory analysis,
     findings, and formal review state.
   - Separate advisory analysis, CI checks, formal GitHub reviews, human technical
     execution/interpretation, and product/governance authority.
3. **Native merge admission and asynchronous races**
   - Model enqueue and merge linearization as a native compare-and-swap decision over
     exact Git subjects, repository rules, checks, fresh eligible approvals, and no
     current normalized blockers.
   - Fail closed on bypass or gate failure. Preserve a native merge that wins an
     external authority/finding race as integration-only and prohibit rollout.
4. **Completion and false-DONE enforcement**
   - Bind observed merge, artifact, configuration, deployments, live observation,
     rollback readiness, and the final exact-head attestation.
   - Require a valid sealed bundle for readiness and completion; invalidate stale
     claims only through independently validated monitor inputs admitted by the
     lifecycle control plane.
5. **Intake lineage and deterministic replay**
   - Preserve safe pre-byte reservation/receipt/correction/quarantine/deletion or
     reconciliation evidence while excluding rejected raw bytes.
   - Replay deterministic admissions against immutable proposal digests; stochastic
     regeneration creates a new proposal subject.
6. **EADPR and supported-runtime policy**
   - Compute and seal mature fixed-due cohorts with exact numerator, denominator,
     pending/right-censored/excluded/manual-intervention subjects and target-policy
     suppression.
   - Enforce agreement between declared Python support and the required CI matrix.
7. **Recovery, planted failures, and documentation**
   - Cover evidence staleness recovery, finding/readiness cycles, merge-group checks,
     both dequeue-versus-merge race orderings, crash-window idempotency, rollback and
     incident evidence, and end-to-end false-DONE trajectories.
   - Document immutable evidence and native merge-gate operator requirements.

## Acceptance proof

The issue is complete only when the full repository suite is green at the exact final
head, planted false-DONE paths HOLD, the supported runtime declaration agrees with CI,
the immutable bundle digest is independently reconstructible, unresolved review
threads are zero, and native merge uses an expected-head comparison.
