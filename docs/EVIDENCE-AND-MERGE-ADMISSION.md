# Evidence and native merge admission

Issue #69 makes readiness and completion evidence-defined. A status label, model
statement, PR comment, check summary, or deployment message cannot independently make
a candidate ready or complete.

## EvidenceBundle authority

`pmpe.audit.evidence` defines stage-scoped, content-addressed manifests. Every evidence
item binds:

- an exact delivery-chain subject;
- a producer authority and execution mode;
- a named, versioned, digest-bound tool;
- a full invocation or committed script digest;
- an OS, architecture, runtime, dependency, container, configuration, and applicable
  hardware fingerprint;
- a result, observed time, optional expiry, output digest, and retention class.

The canonical manifest digest is the seal. `ImmutableEvidenceStore` persists the
manifest under that address and appends an idempotent event. A retry with the same
event identity and bytes is a no-op; reusing the identity for another bundle fails.
Superseding manifests point to their predecessor and never rewrite it.

Mutable GitHub metadata and comments may carry a bundle pointer. They are explicitly
rejected as a required evidence item. Rejected intake bytes are also excluded: the
contract-admission projection retains reservation, safe receipt or failed-finalization
status, lineage/correction identifiers, safe diagnostic codes, and deletion or
reconciliation proof. Only admitted content may receive an immutable payload reference.

## Stage profiles

| Profile | Governing proof |
|---|---|
| Contract admission | Pre-byte reservation, safe receipt/finalization outcome, terminal disposition |
| Pre-code | Repository snapshot, architecture, test plan, meaningful red |
| Candidate review | Exact base/head/prospective tree, checks, advisory analysis, finding inventory |
| Merge admission | Candidate evidence plus fresh eligible formal review and native gate proof |
| Staging | Observed merge/tree, immutable artifact/config, current finding high-watermark |
| Completion | Exact final head, merge/tree, artifact/config, deployment, live observation, rollback readiness |
| Rollback/incident | Executed rollback, restored service/data/traffic/config, RTO/RPO |

An absent class, non-pass result, stale expiry, wrong subject, environment mismatch,
mutable medium, malformed tool identity, or seal mismatch produces HOLD. Under the
Phase 4 lifecycle policy, the control plane also requires a caller-supplied sealed
bundle verifier at draft-to-ready and completion transitions. Only the control plane
changes lifecycle state; observer and integrity-monitor output remains evidence input.

## Review and merge ordering

Advisory analysis and exact-candidate checks gate draft-to-ready. They are not formal
GitHub approval. A fresh eligible formal approval is collected only after readiness
and is rechecked at merge admission. An exact-head `CHANGES_REQUESTED`, or a normalized
critical/high/credible-medium blocker from any authenticated source, revokes readiness.
Approval eligibility never controls whether a source can report a blocker.

The repository policy in `.github/merge-admission-policy.yml` is versioned input to the
native gate. Enqueue validates exact head, protected base, prospective tree, current
rules and policy profiles, successful exact-input PR checks, a fresh approval, and a
classified blocker-free finding high-watermark. Merge-group checks created by that
enqueue may be pending or running, but must remain exact, fresh, and successful before
linearization. Missing, wrong-subject, stale, cancelled, failed, or over-time queue
checks revoke admission.

A bypass, external merge, gate authorization failure, or observed merge-tree mismatch
is an incident even if file content looks equivalent. External contract authority and
asynchronous findings cannot be represented as atomic GitHub inputs. They are checked
before enqueue and monitored for dequeue. If dequeue wins, merge is prevented. If the
native merge linearizes first, repository integration is retained but artifact build,
staging, and promotion are forbidden; authority revocation routes to product input and
a blocking engineering finding requires a fresh remediation issue and primary PR from
a new repository snapshot.

## Metrics and runtime support

`pmpe.evals.eadpr` seals each mature fixed-due cohort without admitting early success
or rewriting a due-time failure after recovery. Reports contain exact numerator,
denominator, failure, pending/right-censored, excluded, and manual-intervention subject
sets. Until a target policy is approved, status is `TARGET_NOT_APPROVED` and numeric
rates are suppressed.

Root and product-backend package support are deliberately capped to Python 3.11 and
3.12. The runtime gate reads each `requires-python` declaration and its required CI
test matrix; a declared-but-untested or tested-but-undeclared target fails.

## Recovery

Expired but obtainable security/advisory evidence moves `REVIEW_REQUIRED` or `PR_READY`
to exact-candidate `VERIFICATION_FAILED`; a fresh passing snapshot returns to
`REVIEW_REQUIRED`. `BLOCKED` is reserved for unavailable or unverifiable verification
infrastructure. No refreshed evidence silently restores an old readiness or approval.
