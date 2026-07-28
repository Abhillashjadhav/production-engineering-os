# Metrics and gates

Metrics measure outcomes and system quality; they do not replace release gates. A
metric can improve while one release is unsafe, so every release is still evaluated
against its exact contract, candidate, deployment, and observation evidence.

## Measurement population

A **contract slice** is the smallest independently deployable set of approved
requirements and acceptance criteria with one immutable bundle version and stable
IDs.

An **eligible slice** has:

- passed deterministic contract validation;
- no unresolved product-critical question;
- all approvals required at contract admission, including product approval and applicable
  security/privacy policy and release-intent approvals;
- a supported repository or an approved adapter;
- an approved cost/time budget.

Invalid or product-blocked inputs are reported separately and do not lower delivery
rate. A slice that became eligible and then failed, exhausted budget, or needed manual
code modification remains in the denominator. Eligibility is frozen on entry to
`CONTRACT_APPROVED`: later architecture, canary, or exact-subject production approvals
are outcome gates and never remove a slice from the denominator.

The reporting window and product success targets require human approval. Until then,
Phase 1 may calculate the metrics but must label target-dependent verdicts
`TARGET_NOT_APPROVED`.

## End-state North Star Metric

### Verified autonomous production delivery rate

**Definition**

> Percentage of eligible approved contract slices that reach production, meet every
> acceptance criterion and required SLO/guardrail through the approved observation
> window, carry a complete exact-subject EvidenceBundle, and require no manual code,
> test, configuration, or unplanned engineering modification.

```text
VAPDR =
  eligible slices satisfying all numerator conditions
  ---------------------------------------------------
  all eligible slices entering CONTRACT_APPROVED
```

Numerator conditions:

1. exact approved contract slice deployed;
2. exact candidate/build/config/migration digests match production;
3. all acceptance criteria and binary release gates pass;
4. required SLO and product guardrail window passes;
5. EvidenceBundle completeness is 100%;
6. no manual code/test/config modification or unplanned engineering intervention;
7. no false-DONE event, unplanned rollback, or severity-0/1 escaped defect in the
   observation window.

Product decisions and named approvals are expected human governance and do not count
as manual engineering modification. A safe product-input request or unsupported
repository before eligibility does not count as failure; it is measured by contract
validation metrics.

**Why this is outcome-based:** it measures safely delivered, live, conformant product
outcomes—not commits, PRs, tokens, or deployments alone.

**Target:** requires product approval after a baseline cohort. The non-negotiable
release-level constraints are zero false DONE and zero unwaived critical/high
security or privacy findings.

## MVP North Star Metric

### Evidence-backed autonomous draft PR rate

**Definition**

> Percentage of eligible approved contract slices that produce an atomic draft PR
> whose exact head SHA has passed every required pre-PR gate, has complete
> requirement-to-executed-test traceability and a sealed EvidenceBundle, with no
> manual code/test/config modification or unplanned engineering intervention.

```text
EADPR =
  eligible slices producing a qualifying draft PR
  ------------------------------------------------
  all eligible slices entering CONTRACT_APPROVED
```

A draft PR is not a success if it is merely opened. It must be issue-linked, atomic,
exact-SHA bound, green on required checks, independently reviewed at the analysis
level, and free of unresolved blocking findings. Formal GitHub approval is tracked
separately because it requires an eligible human collaborator.

**Target:** requires a baseline cohort and product approval. Phase 1 must not invent a
percentage.

## Leading indicators

| Metric | Formula | Direction | Initial gate or use |
|---|---|---|---|
| First-pass contract-validation rate | eligible contracts passing without a PM correction / contracts received | Up | Diagnostic; target after baseline |
| Product-input request precision | confirmed required product blockers / product-input requests | Up | Must be sampled before changing validator strictness |
| Requirement-to-test-plan coverage | required IDs with admitted evidence-producing tests / required IDs | 100% | Hard pre-code gate |
| Meaningful-red rate | planned test nodes failing for intended assertion before code / planned nodes requiring red | 100% | Hard pre-code gate |
| First-pass deterministic verification rate | candidates passing required checks before repair / candidates verified | Up | Diagnostic |
| Approved-contract-to-draft-PR time | elapsed from `CONTRACT_APPROVED` to qualifying draft PR | Down | Target after baseline; report p50/p95 |
| Approved-contract-to-production time | elapsed to successful observation-window close | Down | Target after real production exists; p50/p95 |
| Automated repair success rate | accepted engineering findings verified within budget / repairable accepted findings | Up | Guarded by regression and scope-violation metrics |
| Manual engineering intervention rate | eligible slices with manual code/test/config/unplanned intervention / eligible slices | Down | Companion to both North Stars |
| Review defect yield | credible findings before production / reviewed candidates | Interpret with escape rate | Never maximize alone |
| Evidence completeness rate | present valid required evidence items / required evidence items | 100% | Hard readiness/completion gate |
| Canary success rate | canaries promoted without breach / canaries started | Up | Not available until #72 |
| Rollback rate | releases requiring rollback / production releases | Contextual | Guardrail, not a success metric |
| Escaped-defect rate | confirmed production defects / production releases or slices | Down | Severity segmented |
| Contract-to-test compilation time/cost | elapsed and credits for compilation / compiled slice | Down within quality | Cost/latency diagnostic |
| State dwell time | time in each non-terminal lifecycle state | Down where avoidable | Finds approval/infrastructure bottlenecks |

## Quality guardrails

| Guardrail | Pass/fail rule |
|---|---|
| Acceptance conformance | 100% required criteria PASS; `NOT_PROVEN` fails release |
| Required executed-test coverage | 100% of required requirement/criterion/risk/guardrail IDs have admitted passing evidence |
| Evidence completeness | 100% valid required items; any digest mismatch or missing item fails |
| Independent review | Zero unresolved critical/high/credible-medium findings; reviewer is not fixer; formal approval status is represented honestly |
| Architecture conformance | Zero unapproved boundary violations or ADR drift |
| Regression | Zero new hard-gate regression; approved soft thresholds may not weaken silently |
| False DONE | Exactly zero; any event reopens/blocks the release and records an incident |

## Reliability guardrails

| Guardrail | Pass/fail rule |
|---|---|
| Deterministic replay | Unchanged inputs/toolchain produce the same admitted artifacts/digests |
| Crash recovery | Resume is idempotent; no authoritative action is double-counted |
| Staging health | Required health, smoke, integration, migration, and journey checks all pass |
| Canary/live SLO | Every approved SLO/guardrail stays within threshold for the complete observation window |
| Rollback readiness | Rollback mechanism, compatibility, RTO/RPO, and runbook drill are proven before production |
| Evidence availability | Required evidence remains readable for the approved retention window |

Exact availability, latency, error, saturation, RTO, RPO, and observation-window
values are product/operations inputs and remain unresolved.

## Security guardrails

- Zero unwaived critical or high SAST, dependency, secret, configuration, or
  architecture-boundary findings.
- Required scanners execute with pinned tool/rule/advisory versions or the gate is
  `BLOCKED` with reason `infrastructure_unavailable`; unavailable scanning never passes.
- SBOM/provenance covers the exact build artifact.
- Secrets are referenced through an approved secret manager and never stored in
  contracts, evidence, source, logs, or fixtures.
- Waivers are named, scoped, reasoned, expiring, and exact-subject bound.

## Privacy guardrails

- Data classification, collection purpose, allowed fields, residency, retention,
  deletion, telemetry allowlist, and access roles must be approved when applicable.
- Tests use synthetic or explicitly approved non-production data.
- Zero unwaived high/critical privacy finding or unauthorized sensitive field in
  logs/traces/evidence.
- Required deletion/retention/export behavior is executed and evidenced.
- Missing privacy intent for a data-handling slice returns PRODUCT_INPUT_REQUIRED.

## Cost guardrails

- Every run and stage has approved token/credit, elapsed-time, external-compute, and
  repair-attempt budgets.
- A budget breach transitions to `BUDGET_EXCEEDED`; it cannot be converted to PASS by
  a model summary.
- Fast mode never changes test/review/security/deployment gates.
- Report cost per eligible slice, qualifying draft PR, verified production slice, and
  failed/blocked terminal outcome.
- Do not optimize cost by lowering evidence completeness, severity policy, or
  independent review.

Budget values are unresolved human inputs. The Phase 0 run uses the requested
GPT-5.6 Sol xhigh/Fast configuration but must not treat that request as an unlimited
budget.

## Autonomy guardrails

- Manual modification means a human directly changes code, tests, configuration, or
  deployment state outside an approved lifecycle action.
- Product answers, approvals, reviewer feedback, and infrastructure provisioning are
  separately categorized human governance, not hidden as autonomy.
- Zero task/file permission violation, unapproved product change, self-approval,
  force-push, unapproved merge, or production action.
- Repair attempts and specialist selection remain within approved bounds.
- Safe blocking is reported; agents never fill missing product truth.

## Developer-experience guardrails

- Every blocked state names the failed rule, evidence, owner, remediation, and exact
  resume command/action.
- State and evidence can be inspected without the original chat thread.
- A failed run does not require destructive reset; resume/rollback paths are tested.
- p50/p95 setup, feedback, and local verification times are reported after baseline.
- Platform-specific failures are distinguished from product failures.
- Toolchains are reproducible; version drift is not offloaded to contributors.

## False-DONE metric

```text
false-DONE rate =
  completion/readiness claims later proven to have any missing/invalid required
  evidence, stale subject, failed gate, unmet criterion/SLO, unapproved action,
  or unrecorded manual intervention
  ---------------------------------------------------------------------------
  all completion/readiness claims
```

Target and hard guardrail: **0%**. Any nonzero result is a severity-0 process defect,
sets the affected release to `BLOCKED` or rollback flow, and requires a planted
regression test before the incident can close.

## Rollback metrics

Track, by release and severity:

- planned and unplanned rollback rate;
- time from breach detection to rollback start;
- time to verified service restoration;
- rollback success rate;
- data restoration/RPO conformance;
- rollback-trigger false-positive rate;
- percentage of production releases with a successful pre-release rollback drill.

Hard gates: rollback mechanism and drill evidence exist before production; a failed
rollback is never COMPLETED. Acceptable rollback-rate targets require baseline and
human approval; “lower is always better” is unsafe because a healthy system rolls
back when guardrails demand it.

## Escaped-defect metrics

```text
escaped-defect rate =
  confirmed production defects attributable to a release
  ------------------------------------------------------
  production releases (also report per eligible slice)
```

Segment by severity, detection source, originating requirement, missing/failed gate,
and time to detection. Hard guardrails: zero severity-0/1 escaped defects in the
North-Star observation window and zero known unrecorded escape. Lower-severity target
requires a baseline.

## Gate sequence

| Gate | Required pass evidence | Failure transition |
|---|---|---|
| Contract admission | schema, completeness, contradictions, approvals, rule-set digest | CONTRACT_INVALID or PRODUCT_INPUT_REQUIRED |
| Repository admission | exact-SHA read-only snapshot, supported toolchain or blocker | BLOCKED |
| Architecture approval | admitted pack/ADRs/threat model, named approvals | PRODUCT_INPUT_REQUIRED or BLOCKED |
| Test-plan validation | 100% ID mapping, meaningful-red plan, tool feasibility | PRODUCT_INPUT_REQUIRED or BLOCKED |
| Draft PR admission | ready issue, branch, initial planning/test commit, atomic draft PR | BLOCKED |
| Implementation authorization | existing draft PR, worktree, meaningful red, admitted plan | BLOCKED |
| Candidate verification | pinned checks, exact-SHA results, no hard failures | VERIFICATION_FAILED |
| Independent review | all required lenses; findings reconciled; no self-review | REVIEW_FAILED |
| PR readiness | existing draft PR, exact-SHA EvidenceBundle, required checks/reviews | REVIEW_REQUIRED or BLOCKED |
| Merge admission | exact reviewed head, eligible approval, GitHub merge actor/SHA | REVIEW_REQUIRED or BLOCKED |
| Staging | exact artifact/config, all integration/smoke/migration checks | STAGING_FAILED |
| Canary | bounded exposure and full guardrail window | CANARY_FAILED |
| Production authorization | named exact-subject approval and rollback readiness | PRODUCTION_APPROVAL_REQUIRED |
| Live completion | exact deploy, live verification, observation window, SLOs, evidence | LIVE_VERIFICATION_FAILED or COMPLETED |

No aggregate metric overrides a failed gate.
