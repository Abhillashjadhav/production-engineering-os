# Metrics and gates

Metrics measure outcomes and system quality; they do not replace release gates. A
metric can improve while one release is unsafe, so every release is still evaluated
against its exact contract, candidate, deployment, and observation evidence.

## Measurement population

A **contract slice** is the smallest independently deployable set of approved
requirements and acceptance criteria with one immutable bundle version and stable
IDs.

A **submitted-slice lineage** begins at the first received attempt to describe that
independently deployable unit, before parsing, validation, or approval. The control
plane assigns an opaque immutable lineage ID and a distinct ingestion-attempt ID before
it inspects mutable contract content; neither ID is derived from publisher-supplied
slice identifiers, source references, or fields that a correction may change. Every
correction must reference the server-issued lineage ID or the immutable original
ingestion-attempt ID. Publisher identity, source reference, and claimed slice IDs are
audited attributes, not lineage keys. An attempt without a valid correction reference
starts a new lineage and raises a possible-duplicate finding; the system never silently
coalesces attempts by corrected content. Thus malformed first attempts remain in the
denominator and corrections in their admitted lineage do not add denominator entries.

An **eligible slice** has:

- passed deterministic contract validation;
- no unresolved product-critical question;
- all approvals required at contract admission, including product approval and applicable
  security/privacy policy and release-intent approvals;
- a supported repository or an approved adapter;
- approved per-run and applicable per-stage token, credit, elapsed-time,
  external-compute/spend, and repair-attempt budgets, plus a reserved safety budget for
  monitoring, abort, staging teardown/cleanup, rollback, and incident response.

Invalid or product-blocked inputs are reported separately and do not lower delivery
rate. A slice that became eligible and then failed, exhausted budget, or needed manual
code modification remains in the denominator. Eligibility is frozen only after
`REPOSITORY_ANALYSED` proves that the approved repository is supported or has an
approved adapter. Later architecture, canary, or exact-subject production approvals
are outcome gates and never remove a slice from the denominator.

The draft-PR evaluation window, production-delivery window, live observation window,
reporting window, and product success targets require human approval. Until every
window needed by a North Star is approved, its `metric_due_at` and due cohort are
undefined. Phase 1 contract intake records and validates these policy inputs but does
not compute a fleet rate. The Phase 6/#73 reporting component must emit
`TARGET_NOT_APPROVED`, omit the numeric rate, and report only clearly labelled raw
counts, pending inputs, and window-independent diagnostics. No phase may substitute an
agent-selected or retrospective window. A provisional baseline is permitted only after
a named owner approves a separately versioned policy before the affected slices become
eligible; provisional and target-policy series are never combined.

Each North Star uses a versioned maturity policy fixed when eligibility is admitted.
For EADPR, `metric_due_at` is `eligibility_at + approved draft-PR evaluation window`.
For VAPDR, it is `eligibility_at + approved production-delivery window + required live
observation window`. A slice enters **both** that metric's numerator opportunity and
denominator only when its fixed `metric_due_at` falls inside that report's bounded due
cohort.

For a period report with an approved `(window_start, reporting_cutoff]`, its rate cohort
is exactly the eligible slices satisfying
`window_start < metric_due_at <= reporting_cutoff`; the numerator and denominator use
that same predicate. A cumulative report must be explicitly labeled and substitutes
the approved program-inception instant for `window_start`. Before its due time, an
early success or terminal failure remains provisional and cannot enter the reported
rate. At the due time, the system seals the outcome-as-of-due: success only if every
numerator condition was satisfied by then; otherwise failure. A later recovery is
reported separately and never rewrites the historical due-cohort result (except a
separately versioned correction for invalid evidence). Due times, window bounds, and
policy versions cannot be changed retrospectively. Every report publishes due-cohort
eligible, success-as-of-due, failure-as-of-due, not-yet-due/pending context, and
excluded counts. This fixed, bounded due-cohort denominator prevents early successes
from producing a success-biased rate and prevents old slices from silently re-entering
every period while keeping unfinished future cohorts visible.

## End-state North Star Metric

### Verified autonomous production delivery rate

**Definition**

> Percentage of eligible approved contract slices that reach production, meet every
> acceptance criterion and required SLO/guardrail through the approved observation
> window, carry a complete exact-subject EvidenceBundle, and require no manual code,
> test, configuration, deployment/environment mutation, technical evidence execution,
> or other planned or unplanned manual engineering intervention as defined below.

```text
VAPDR =
  mature eligible slices satisfying all numerator conditions
  ----------------------------------------------------------
  all VAPDR-mature eligible slices in the cohort
```

Numerator conditions:

1. exact approved contract slice deployed;
2. exact candidate/build/config/migration digests match production;
3. all acceptance criteria and binary release gates pass;
4. required SLO and product guardrail window passes;
5. EvidenceBundle completeness is 100%;
6. no manual engineering intervention as defined in the autonomy guardrails below;
7. no false-DONE event, unplanned rollback, or Critical/High escaped defect in the
   observation window.

Product decisions, named approvals, and an authorized merge click are expected human
governance and do not count as manual engineering modification. Shared platform
capacity, organization credentials, or base infrastructure provisioned outside the
slice lineage before eligibility is also external governance. A human executing or
acting as the acceptance oracle for a slice-specific test/evidence procedure, rollout,
traffic shift, environment, artifact, configuration, repair, or post-eligibility
infrastructure does count, even when planned. A safe product-input request or
unsupported repository before eligibility does not count as failure; it is measured by
contract validation and repository-admission metrics.

**Why this is outcome-based:** it measures safely delivered, live, conformant product
outcomes—not commits, PRs, tokens, or deployments alone.

**Target:** requires product approval after a baseline cohort. The non-negotiable
release-level constraints are zero false DONE and zero critical/high security or
privacy findings; these severities are never waivable.

## MVP North Star Metric

### Evidence-backed autonomous draft PR rate

**Definition**

> Percentage of eligible approved contract slices that produce an atomic draft PR
> whose exact head SHA has passed every required candidate-readiness gate while the
> PR remains draft, has complete
> requirement-to-executed-test traceability and a sealed EvidenceBundle, with no
> manual engineering intervention as defined in the autonomy guardrails below.

```text
EADPR =
  mature eligible slices producing a qualifying draft PR
  -------------------------------------------------------
  all EADPR-mature eligible slices in the cohort
```

A draft PR is not a success if it is merely opened. It must be issue-linked, atomic,
exact-SHA bound, green on required checks, independently reviewed at the analysis
level, and free of unresolved blocking findings. Formal GitHub approval is tracked
separately because it requires an eligible human collaborator.

The draft PR is opened before implementation. “Candidate-readiness gate” therefore
means the pre-code, implementation, exact-head verification, and analysis-review gates
completed on that already-open draft before it may become ready for formal approval; it
does not mean a gate that must precede PR creation.

**Target:** requires a baseline cohort and product approval. Phase 1 only validates the
required policy inputs; Phase 6/#73 computes the cohort, and no phase may invent a
percentage.

## Leading indicators

| Metric | Formula | Direction | Initial gate or use |
|---|---|---|---|
| First-pass contract-validation rate | submitted-slice lineages whose initial received attempt passes validation without PM correction / all submitted-slice lineages initially received | Up | Count every initial attempt, including malformed, unapproved, incomplete, contradictory, and product-blocked attempts; corrections stay in the original lineage; independent of later eligibility; target after baseline |
| Product-input request precision | confirmed required product blockers / product-input requests | Up | Must be sampled before changing validator strictness |
| Repository-admission support rate | approved slices with a supported repository/adapter / approved slices analysed | Contextual | Report exclusions; never hide unsupported inputs |
| Requirement-to-test-plan coverage | required IDs with admitted evidence-producing tests / required IDs | 100% | Hard pre-code gate |
| Meaningful-red rate | planned test nodes failing for intended assertion before code / planned nodes requiring red | 100% | Hard pre-code gate |
| First-pass deterministic verification rate | candidates passing required checks before repair / candidates verified | Up | Diagnostic |
| Approved-contract-to-draft-PR time | elapsed from `CONTRACT_APPROVED` to qualifying draft PR | Down | Target after baseline; report p50/p95 |
| Approved-contract-to-production time | elapsed to successful observation-window close | Down | Target after real production exists; p50/p95 |
| Automated repair success rate | accepted engineering findings verified within budget / repairable accepted findings | Up | Guarded by regression and scope-violation metrics |
| Manual engineering intervention rate | for each North Star: slices in that metric's fixed mature due cohort with any manual engineering intervention observed by `metric_due_at` / all slices in the same mature due cohort | Down | Report EADPR and VAPDR companions separately; planned manual technical evidence is included; not-yet-due slices are pending, not denominator members |
| Review defect yield | credible findings before production / reviewed candidates | Interpret with escape rate | Never maximize alone |
| Evidence completeness rate | present valid required evidence items / required evidence items | 100% | Hard readiness/completion gate |
| Canary success rate | canaries promoted without breach / canaries started | Up | Not available until #72 |
| Rollback rate | releases requiring rollback / production releases | Contextual | Guardrail, not a success metric |
| Escaped-defect rate | confirmed production defects / production releases or slices | Down | Severity segmented |
| Contract-to-test compilation time/cost | elapsed and credits for compilation / compiled slice | Down within quality | Cost/latency diagnostic |
| State dwell time | time in each non-terminal lifecycle state | Down where avoidable | Finds approval/infrastructure bottlenecks |

The manual-intervention outcome is sealed separately for the EADPR and VAPDR due
cohorts using the same approved `(window_start, reporting_cutoff]` predicate as its
companion North Star. An intervention occurring after one metric's `metric_due_at` is
reported as later activity for that cohort and may still count by the later metric's
due time; it never retroactively changes a sealed rate except through a versioned
invalid-evidence correction.

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

- Zero critical or high SAST, dependency, secret, configuration, or
  architecture-boundary findings; neither severity is waivable.
- Required scanners execute with pinned tool/rule/advisory versions or the gate is
  `BLOCKED` with reason `infrastructure_unavailable`; unavailable scanning never passes.
- SBOM/provenance covers the exact build artifact.
- Secrets are referenced through an approved secret manager and never stored in
  contracts, evidence, source, logs, or fixtures.
- Permitted medium/low waivers are named, scoped, reasoned, expiring, and
  exact-subject bound.

## Privacy guardrails

- Data classification, collection purpose, allowed fields, residency, retention,
  deletion, telemetry allowlist, and access roles must be approved when applicable.
- Tests use synthetic or explicitly approved non-production data.
- Zero high/critical privacy finding or unauthorized sensitive field in
  logs/traces/evidence; neither severity is waivable.
- Required deletion/retention/export behavior is executed and evidenced.
- Missing privacy intent for a data-handling slice returns PRODUCT_INPUT_REQUIRED.

## Cost guardrails

- Every run and stage has approved token/credit, elapsed-time, external-compute, and
  repair-attempt budgets.
- A delivery-budget breach transitions to `BUDGET_EXCEEDED` only after rollout-scoped
  evidence proves zero staging resources, zero candidate canary exposure, and zero
  changed-production resources or exposure. Active or indeterminate staging first
  consumes the separately reserved safety budget to run and prove idempotent teardown.
  Active or indeterminate canary/changed-production exposure first consumes that budget
  to monitor, abort, roll back, and then clean staging. The restored or existing
  last-known-good production deployment remains active and monitored; a model summary
  can never convert a breach or incomplete cleanup to PASS.
- Fast mode never changes test/review/security/deployment gates.
- Report cost per eligible slice, qualifying draft PR, verified production slice, and
  failed/blocked terminal outcome.
- Do not optimize cost by lowering evidence completeness, severity policy, or
  independent review.

Budget values are unresolved human inputs. The Phase 0 run uses the requested
GPT-5.6 Sol xhigh/Fast configuration but must not treat that request as an unlimited
budget.

## Autonomy guardrails

- Manual engineering intervention means a human directly changes code, tests,
  configuration, deployment/environment/traffic state, or a release artifact, **or**
  executes or interprets an acceptance test, verification check, technical evidence
  procedure, repair, deployment, or rollback step for the slice. Planned operator work
  and an approved manual evidence procedure still count for autonomy metrics even when
  the lifecycle authorizes them.
- Product answers, candidate-bound approvals, formal review analysis/feedback, and
  shared platform provisioning completed outside the slice lineage before eligibility
  are separately categorized human governance. Merely reading existing evidence to
  make an approval or review decision does not count; executing a test/check, creating
  or manually interpreting a technical evidence result as its acceptance oracle, or
  mutating the candidate/environment does. Slice-specific or post-eligibility
  environment/infrastructure provisioning is manual engineering intervention, not
  hidden as governance.
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
  claims invalid when asserted, or left authoritative/used after their invalidation
  deadline, because of missing/invalid evidence, a stale subject, failed gate,
  unmet criterion/SLO, unapproved action, or unrecorded manual intervention
  ---------------------------------------------------------------------------
  all completion/readiness claims
```

An append-only, fail-closed revocation of a claim that was valid when asserted—such
as `PR_READY → REPOSITORY_ANALYSED` after the protected base advances—is correct
behavior, not false-DONE, provided no downstream action uses the invalidated claim and
revocation occurs within policy. Head-only drift instead returns to
`IMPLEMENTATION_IN_PROGRESS` for candidate integration and verification. Track normal
readiness supersession/revocation rate and invalidation-detection latency separately.
A claim used or left active past that deadline is false-DONE.

Target and hard guardrail: **0%**. Any nonzero result is a Critical process defect,
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
and time to detection. The canonical release severity vocabulary is the governance
scale **Critical, High, Medium, Low**. Imported `Sev-0` records normalize to Critical
and `Sev-1` to High; other numeric scales require an approved versioned mapping before
admission. Hard guardrails: zero Critical/High escaped defects in the North-Star
observation window and zero known unrecorded escape. Lower-severity target requires a
baseline.

## Gate sequence

| Gate | Required pass evidence | Failure transition |
|---|---|---|
| Contract admission | schema, completeness, contradictions, approvals, rule-set digest | CONTRACT_INVALID or PRODUCT_INPUT_REQUIRED |
| Repository admission | exact-SHA read-only snapshot, separately versioned governance observation with query provenance, supported toolchain or blocker | BLOCKED |
| Architecture approval | admitted pack/ADRs/threat model, named approvals | PRODUCT_INPUT_REQUIRED or BLOCKED |
| Test-plan validation | 100% ID mapping, meaningful-red plan, tool feasibility | PRODUCT_INPUT_REQUIRED or BLOCKED |
| Draft PR admission | ready issue, branch, initial planning/test commit, atomic draft PR | BLOCKED |
| Implementation authorization | existing draft PR, worktree, meaningful red, admitted plan | BLOCKED |
| Candidate verification | pinned checks, exact-SHA results, no hard failures | VERIFICATION_FAILED |
| Independent review | all required lenses; findings reconciled; no self-review | REVIEW_FAILED |
| PR readiness | existing draft PR, exact-SHA EvidenceBundle, required checks/reviews | REVIEW_REQUIRED or BLOCKED |
| Merge admission | reviewed head/base/prospective tree, eligible approval, observed merge actor/SHA, actual-tree equality | Head drift: IMPLEMENTATION_IN_PROGRESS; base/policy/toolchain/tree drift: REPOSITORY_ANALYSED; bypass/mismatch: BLOCKED |
| Staging | exact artifact/config, all integration/smoke/migration checks | STAGING_FAILED |
| Canary | bounded exposure and full guardrail window | CANARY_FAILED |
| Production authorization | named exact-subject approval and rollback readiness | PRODUCTION_APPROVAL_REQUIRED |
| Live completion | exact deploy, live verification, observation window, SLOs, evidence | LIVE_VERIFICATION_FAILED or COMPLETED |

No aggregate metric overrides a failed gate.
