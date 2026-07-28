# Target architecture

## Architecture goals

Production Engineering OS (PEOS) consumes an approved PM Agent OS (PMOS) contract
bundle and produces a verified, deployable, observable product without inferring
missing business truth. The architecture separates:

- **control plane** — state, policy, permissions, budgets, approvals, stopping;
- **execution plane** — repository analysis, specialists, tests, build, deploy;
- **evidence plane** — content-addressed artifacts, test/review/deploy/observe proof;
- **security plane** — trust boundaries, least privilege, secrets, privacy, waivers.

Existing V1–V3 primitives are inputs to this target, not discarded systems.

## Component architecture

```mermaid
flowchart LR
    PMOS[PM Agent OS] -->|approved contract bundle| INTAKE[Contract intake and compiler]
    INTAKE --> VALIDATE[Deterministic contract validator]
    VALIDATE -->|product input request / PCR| PMOS
    VALIDATE --> CONTROL[Lifecycle control plane]

    CONTROL --> REPO[Repository intelligence]
    CONTROL --> ARCH[Architecture / ADR / threat model]
    CONTROL --> TESTPLAN[Requirement-to-test compiler]
    CONTROL --> DRAFT[Issue / branch / atomic draft PR]
    DRAFT --> ROUTER[Minimum specialist router]
    ROUTER --> WORKTREES[Scoped specialist worktrees]
    WORKTREES --> INTEGRATE[Deterministic integration]
    INTEGRATE --> VERIFY[Verification profiles]
    VERIFY --> REVIEW[Independent assurance]
    REVIEW --> FIX[Bounded accepted-findings repair]
    FIX --> VERIFY
    REVIEW --> READY[Reviewed PR ready]
    READY --> MERGE[Authorized exact-head merge]

    MERGE --> STAGING[Staging adapter and integration verification]
    STAGING --> CANARY[Canary / traffic control]
    CANARY --> PROD[Production adapter]
    PROD --> OBS[Live verification / observability / SLOs]
    OBS --> ROLLBACK[Rollback controller]
    OBS --> OUTCOME[OutcomeReport]
    OUTCOME --> PMOS

    CONTROL <--> EVIDENCE[(Evidence plane)]
    REPO --> EVIDENCE
    ARCH --> EVIDENCE
    TESTPLAN --> EVIDENCE
    DRAFT --> EVIDENCE
    VERIFY --> EVIDENCE
    REVIEW --> EVIDENCE
    MERGE --> EVIDENCE
    STAGING --> EVIDENCE
    CANARY --> EVIDENCE
    PROD --> EVIDENCE
    OBS --> EVIDENCE

    SECURITY[Security / privacy / supply-chain policy] --> VALIDATE
    SECURITY --> ARCH
    SECURITY --> VERIFY
    SECURITY --> STAGING
    SECURITY --> CANARY
    SECURITY --> PROD
```

## Planes and component responsibilities

### Control plane

| Component | Responsibility | Existing foundation | Target addition |
|---|---|---|---|
| Contract intake | Load, version, digest, compile formats | `pmpe.contracts`, three schemas | Unified bundle/manifest and loss-aware compiler (#62) |
| Contract policy | Completeness, contradiction, ownership, approvals | schema validators, V1 `RequirementValidator` | Versioned rule registry and PM-owned blockers (#63) |
| Lifecycle engine | Legal transitions, actor permissions, resume | V1/V2/V3 state machines | One transition policy, migration, budgets, bounded repair (#65) |
| Authorization | Human approvals and agent/task/file scope | policy engine, production approval, fixer gate | Exact action/artifact/config/target subjects and expiry |
| Budget controller | Tokens, credits, time, attempts, external compute | ledger `cost` field only | Per-stage/run budgets and `BUDGET_EXCEEDED` |
| GitHub governor | Issue/branch/PR atomicity and draft state | local Git adapter and PR records | Issue-first remote adapter; no merge authority (#68) |

The control plane is the only component that changes lifecycle state. Model output is
an untrusted proposal until a deterministic admission rule accepts it.

### Execution plane

| Component | Responsibility | Existing foundation | Target addition |
|---|---|---|---|
| Repository intelligence | Exact-SHA read-only normalized content snapshot plus separately versioned governance observation | arbitrary V2 assessment | deterministic scanners/adapters (#64) |
| Architecture compiler | Components, boundaries, ADRs, threats, deployment/observe/rollback design | V1 templates, V2 architect | admitted ArchitecturePack (#66) |
| Test compiler | Requirements/criteria/risks/guardrails to executable evidence nodes | V1 stack templates, executed traceability | generalized TestPlan and meaningful-red gate (#67) |
| Specialist router | Minimum capable roster | V2 router | five missing profiles and runtime worktree spawning (#68) |
| Worktree executor | Test/implementation tasks with scoped writes | `specialist_worktree` | lifecycle-managed worktrees and task/file permissions |
| Integration | Compose branches, run full checks, freeze candidate | V2 integration agent/freeze | exact commit/build/config subject binding |
| Verification runner | Pinned unit/integration/E2E/migration/perf/a11y/security/privacy/boundary profiles | quality gates and product CI | normalized profiles, reproducible toolchains (#69/#70) |
| Deployment adapters | Execute staging/canary/production and rollback | real local deploy, preview, simulated production | real protected-environment adapters (#71/#72) |
| Guided Mode | Progressive-disclosure product-owner interface | CLI/skills | parity UI over the same APIs (#74) |

### Evidence plane

The EvidenceBundle is a content-addressed manifest. Each item records:

- evidence type and schema version;
- producer identity and role;
- command/tool/model/rule-set version;
- subject commit/tree/artifact/config/environment/deployment digest;
- input and output digests;
- start/end time using explicit UTC event timestamps;
- PASS/FAIL/BLOCKED/NOT_PROVEN result;
- raw artifact reference, retention class, and redaction status;
- supersedes/duplicate relationship.

Evidence completeness uses stage-specific profiles. Each checkpoint seals a new
content-addressed EvidenceBundle that references and supersedes the prior stage bundle:

| Profile | Required members added at this stage |
|---|---|
| Contract admission | contract source/version/digest, validation, approvals, and rule-set digest |
| Pre-code | repository snapshot, architecture, ADRs, threat model, TestPlan, issue/branch/draft-PR record, and meaningful-red evidence |
| Candidate review | exact commit/tree, build/SBOM/provenance, deterministic verification, independent reviews, and finding lifecycle |
| Merge admission | reviewed exact PR head, required checks/approvals, merge actor/time/method/SHA, and primary issue linkage |
| Staging | immutable artifact/config/target, deployment, integration, migration, smoke, security, and teardown/rollback readiness |
| Canary | bounded cohort/traffic policy, deployment, complete SLO/guardrail window, abort decision, and rollback readiness |
| Production authorization | named approval bound to merge/artifact/config/migration/target/rollout subjects |
| Production deployment | progressive deployment, exact subject correlation, and rollback target |
| Completion | live SLO/guardrail observation window, acceptance evidence, final rollback readiness, and OutcomeReport |

A gate requires 100% of the members in its current and preceding applicable profiles,
not artifacts from future stages. Thus an MVP draft PR can seal a complete candidate
review bundle without pretending that production evidence already exists.

```mermaid
flowchart TB
    C[Contract bundle digest] --> R[Repository snapshot digest]
    C --> A[ArchitecturePack digest]
    R --> A
    A --> T[TestPlan digest]
    T --> H[Frozen PR head/source SHA]
    H --> B[Build artifact + SBOM digest]
    B --> V[Verification result digests]
    H --> RV[Review/finding digests]
    V --> RV[Review/finding digests]
    H --> M[Observed merge event + merge SHA]
    RV --> M
    M --> D[Deployment/config/target digests]
    D --> O[Observation/SLO window digest]
    O --> E[Sealed EvidenceBundle]
```

Any changed upstream digest invalidates dependent evidence. Corrections create a new
manifest; sealed evidence is not overwritten.

### Security boundaries

| Boundary | Trust rule |
|---|---|
| PMOS → intake | Contract content is untrusted until schema, digest, approvals, ownership, and semantic rules pass. No secret values are permitted. |
| Agent → control plane | Agent artifacts are untrusted proposals. Deterministic admission, task/file scope, and product-boundary rules apply. |
| Reviewer → candidate | Reviewer is read-only, sees the frozen exact candidate, and is separate from fixer/verifier. Formal GitHub approval is a distinct human event. |
| PEOS → GitHub | Least-privilege token; issue/branch/draft-PR only by stage. No force-push, self-approval, or merge authority. |
| PEOS → build/dependency network | Pinned/locked sources, egress allowlist, SCA/SBOM/provenance, no credential persistence. |
| PEOS → staging/production | Short-lived target-scoped identity, protected environment, exact-subject approval, network/data policy, audit log. |
| Product → telemetry | Data allowlist/minimization, tenant separation, retention/deletion, redaction, access control. |
| Evidence storage | Append-only/content-addressed after sealing; sensitive references instead of values; approved retention. |

## Deployment architecture

```mermaid
flowchart LR
    BUILD[Verified immutable artifact] --> STG[Isolated staging]
    STG -->|smoke + integration + migration + security| SGATE{Staging gate}
    SGATE -->|fail| SROLL[Teardown / staging rollback]
    SGATE -->|pass| CAPP{Canary authorization}
    CAPP --> CANARY[Bounded canary cohort]
    CANARY -->|SLO / guardrail breach| PROLL[Production rollback]
    CANARY -->|window passes| PAPP{Named production approval}
    PAPP --> PROD[Progressive production promotion]
    PROD --> LIVE[Live verification + observation window]
    LIVE -->|breach| PROLL
    LIVE -->|pass| COMPLETE[Evidence-backed COMPLETED]
```

The provider, protected environments, canary size/window, approvers, SLOs, RTO/RPO,
data rollback policy, and minimum observation window are human decisions. Until
provided, real deployment transitions are `BLOCKED`, not simulated successes.

## Observability architecture

All lifecycle and runtime events use correlation keys:

`contract_slice_id → run_id → issue → branch/worktree → commit/tree → build/SBOM →
PR → staging deployment → canary → production deployment → observation window →
OutcomeReport/PCR`.

Required telemetry classes:

- structured lifecycle and runtime logs with field allowlists;
- RED/USE or equivalent service metrics plus contract-approved business outcomes;
- distributed traces when an integration crosses process/service boundaries;
- SLO definitions and burn-rate/threshold evaluation;
- dashboards for delivery, release, SLO, security/privacy, cost, and autonomy;
- actionable alerts with owner, severity, deduplication, and runbook;
- rollback and incident events tied to the release;
- fleet aggregation for the metrics in `METRICS-AND-GATES.md`.

Vendor choice, data region, retention, and approved business signals are unresolved.

## PM Agent OS integration

### Inbound

PMOS sends:

1. bundle manifest and version;
2. product truth and traceable IDs;
3. approvals and approver roles;
4. outcome/leading/guardrail definitions and targets;
5. security/privacy/data intent;
6. release/observability/rollback intent.

PEOS returns `CONTRACT_INVALID` for structural/ownership violations and
`PRODUCT_INPUT_REQUIRED` for missing business truth. It never edits the approved
contract in place.

### Outbound

PEOS returns:

- validation diagnostics and ProductInputRequest;
- ArchitectureDecisionRequest for cross-boundary decisions;
- ProductChangeRequest for engineering-discovered product changes;
- release/incident/rollback evidence;
- OutcomeReport comparing hypothesis, outcome, metrics, guardrails, and SLO evidence;
- recommended options and engineering consequences, never an automatic product
  decision.

## Lifecycle state machine

### State invariants

- State and transition policy are versioned and stored outside chat.
- Every transition names its actor and exact evidence subjects.
- Unsupported infrastructure produces `BLOCKED`, not PASS.
- Repair attempts consume approved budgets and cannot weaken gates/tests.
- Production/canary/staging execution is distinct from policy simulation.
- `COMPLETED` requires deterministic contract, commit/build, verification, review,
  deployment, live observation, and rollback-readiness evidence. Model output alone
  can never satisfy a transition.

### Transition table

Abbreviations: **CP** control plane; **PM** named product owner; **EO** engineering
owner; **SO** security/operations owner; **HA** explicit human approval.

| From → next | Required input | Required evidence | Responsible actor and permitted action | Failure condition and rollback behavior | HA |
|---|---|---|---|---|---|
| `CONTRACT_RECEIVED → CONTRACT_INVALID` | Bundle bytes/manifest | Parse/schema/compiler diagnostics and source digest | CP validates only | Malformed, unsupported, lossy, ownership-invalid. No stateful work started; return diagnostics. | No |
| `CONTRACT_INVALID → CONTRACT_RECEIVED` | New version/corrected bundle | New source/version/digest and PM approval | PM submits; CP never edits old bundle | Same version with changed digest is refused; old record retained. | PM approval |
| `CONTRACT_RECEIVED → PRODUCT_INPUT_REQUIRED` | Structurally valid bundle | Named completeness/contradiction rules and field paths | CP requests missing product truth | Missing/contradictory product truth. No architecture/implementation; resume target recorded. | PM response |
| `PRODUCT_INPUT_REQUIRED → CONTRACT_RECEIVED` | Superseding bundle/PCR decision and, when downstream work exists, its issue/branch/draft-PR/worktree disposition | Resolution, approver, new version/digest, atomic-scope comparison, and durable disposition record | PM decides; CP halts worktrees and either reuses the same issue/branch/draft PR when the atomic outcome is unchanged or marks them superseded and requires a new issue/primary PR when scope changed | Unresolved/unauthorized input or any undispositioned active candidate remains product-input-required; old contract/candidate evidence is retained and cannot execute. | Yes |
| `CONTRACT_RECEIVED → CONTRACT_APPROVED` | Valid complete approved bundle | 100% contract gates, rule-set digest, approval metadata | CP admits and locks | Any blocker routes to invalid/input-required; no rollback needed. | Existing PM approval required |
| `CONTRACT_APPROVED → REPOSITORY_ANALYSED` | Locked contract and repository ref | Exact-SHA read-only RepositorySnapshot and scanner versions | CP invokes read-only repository intelligence | Dirty/unsupported/inaccessible critical facts → `BLOCKED`; discard partial recommendation, retain scan evidence. | No |
| `CONTRACT_APPROVED → BLOCKED` | Contract plus missing adapter/permission | Blocker owner, attempted evidence, resume target | CP stops; owner may provision/authorize | No repository mutation; resume from approved contract. | Depends on blocker |
| `BLOCKED → <recorded resume state>` | Resolved external state or approved superseding input | Resolution identity, changed external-state evidence, prior state/action, and unchanged upstream digests | CP rechecks then resumes the exact interrupted gate | Recheck failure remains blocked; no skip to a later or terminal state. | If permission/decision |
| `REPOSITORY_ANALYSED → ARCHITECTURE_PROPOSED` | Contract + snapshot | ArchitecturePack, ADRs, threat model, all digests | Architect proposes; CP admits structure/references | Missing/invalid pack remains analysed; no implementation. | No |
| `ARCHITECTURE_PROPOSED → PRODUCT_INPUT_REQUIRED` | Cross-boundary/irreversible finding | Decision request with options/consequences | CP/architect requests PM/security/ops decision | Never choose vendor, retention, UX, cost, or irreversible behavior by default. | Yes |
| `ARCHITECTURE_PROPOSED → ARCHITECTURE_APPROVED` | Admitted pack and resolved escalations | Engineering review, boundary policy, required approvals | EO approves technical design; CP locks pack | Rejected design returns to proposed; superseding pack invalidates downstream. | EO; PM/SO where boundary crossed |
| `ARCHITECTURE_APPROVED → TEST_PLAN_CREATED` | Locked contract/snapshot/architecture | TestPlan and coverage matrix digests | Test compiler proposes only | Unsupported test infrastructure → `BLOCKED`; missing product test oracle → input-required. | No |
| `TEST_PLAN_CREATED → TEST_PLAN_VALIDATED` | TestPlan and toolchain inventory | 100% required-ID mapping, applicability rules, planned meaningful-red evidence | CP/test validator admits | Missing/vague evidence mapping returns to created/input-required; no code. | No |
| `TEST_PLAN_CREATED → PRODUCT_INPUT_REQUIRED` | Missing acceptance oracle/threshold | Named unmapped IDs and questions | CP requests PM truth | Resume with superseding contract; downstream plan invalidated. | Yes |
| `TEST_PLAN_VALIDATED → IMPLEMENTATION_PLANNED` | Approved issue candidates and architecture/test plan | Ordered atomic tasks, dependencies, file/task scopes, rollback per task | Planner proposes; CP admits | Non-atomic/uncovered task plan refused; remain validated. | EO for plan exceptions |
| `IMPLEMENTATION_PLANNED → DRAFT_PR_OPEN` | Ready GitHub issue, dedicated branch, admitted atomic plan | GitHub issue/branch, initial planning/test commit, atomic draft PR, base/head, and rollback record | CP creates the draft PR only; never marks ready, approves, or merges | Missing issue, stale base, non-atomic scope, or PR failure → `BLOCKED`; no implementation starts. | No |
| `DRAFT_PR_OPEN → IMPLEMENTATION_IN_PROGRESS` | Draft PR, isolated worktrees, budgets, validated TestPlan | PR/branch/worktree records; meaningful-red execution where required | CP authorizes minimum specialists | Scope/budget/permission/test-order failure → `BLOCKED`; dispose worktree safely without deleting evidence. | No |
| `IMPLEMENTATION_IN_PROGRESS → VERIFICATION_FAILED` | Integrated candidate | Exact-SHA verification results | Verification runner executes only | Any required check FAIL/NOT_PROVEN; candidate not publishable. Roll back disposable integration/worktree as needed. | No |
| `IMPLEMENTATION_IN_PROGRESS → REVIEW_REQUIRED` | Integrated candidate with all deterministic gates pass | Frozen commit/tree/build/SBOM, test results, preliminary EvidenceBundle | CP freezes and opens review stage | Digest drift returns to verification; no PR readiness. | No |
| `VERIFICATION_FAILED → REPAIR_IN_PROGRESS` | Accepted engineering findings within scope/budget | Finding status, fixer/task/file allowlist, remaining attempts/cost | CP authorizes fixer only | Product finding → input-required; exhausted budget → budget-exceeded; unrepairable → blocked. | Owner decision for non-mechanical finding |
| `VERIFICATION_FAILED → PRODUCT_INPUT_REQUIRED` | Product-level finding or missing acceptance oracle discovered by verification | Finding/PCR linked to contract, requirement, failed proof, active issue/branch/draft PR, and stopped worktree record | CP requests PM truth, halts worktrees, and marks the existing draft PR/issue blocked on product input; no fixer may decide it | Superseding contract returns through intake and invalidates downstream evidence; it must satisfy the explicit reuse-or-supersede disposition before work resumes. | Yes |
| `REPAIR_IN_PROGRESS → VERIFICATION_FAILED` | Candidate changed by scoped fixes | Fix commits/files/checks and new candidate digest | Independent verifier reruns full affected and required gates | Any failure stays verification-failed; never weaken test/gate. | No |
| `REPAIR_IN_PROGRESS → REVIEW_REQUIRED` | All fixes verified and all gates green | New exact-SHA EvidenceBundle and fixer ≠ verifier proof | CP refreezes and requests fresh review | Stale previous review is invalid; digest drift returns to verification. | No |
| `VERIFICATION_FAILED → BUDGET_EXCEEDED` | Exhausted attempt/time/token/credit/external-compute budget | Budget policy, consumption ledger, last safe state | CP stops; only report/rollback/dispose actions allowed | No further repair. Worktrees disposed or retained per evidence policy. | Budget extension requires named owner |
| `BUDGET_EXCEEDED → <recorded resume state>` | Approved budget extension with unchanged scope | Named reason/new budget, interrupted state/action, and unchanged upstream digests | CP rechecks and resumes exactly the interrupted state; it cannot choose a later state | Changed product scope requires new contract; invalid extension remains stopped. Never default to repair without a candidate. | Yes |
| `BUDGET_EXCEEDED → BLOCKED` | No extension or external dependency | Terminal report and resume conditions | CP closes active execution safely | No completion claim. | No |
| `REVIEW_REQUIRED → REVIEW_FAILED` | Frozen candidate and required reviewer roster | Read-only proofs, exact candidate reviews, credible findings | Independent reviewers analyze only | Critical/high/credible-medium or integrity failure blocks. No reviewer fix. | Finding decisions by owner |
| `REVIEW_FAILED → REPAIR_IN_PROGRESS` | Reconciled accepted engineering findings and budget | Decisions/reasons, fixer scope, PCRs for product findings | CP authorizes fixer | Undecided/product findings remain failed/input-required; stale candidate forbidden. | Yes for non-mechanical decisions |
| `REVIEW_FAILED → PRODUCT_INPUT_REQUIRED` | Product-decision finding | PCR linked to contract/requirements, active issue/branch/draft PR, and stopped worktree record | CP halts execution and marks the existing draft PR/issue blocked on product input; PM decides and CP does not fix | Superseding contract returns to intake and invalidates downstream evidence; reuse or supersession must be recorded before another primary PR can exist. | Yes |
| `REVIEW_FAILED → REVIEW_REQUIRED` | Every blocking finding is dispositioned without a source change | Unchanged candidate digest, authorized `rejected-with-reason` records, independent disposition validation, and no unresolved finding | CP reopens readiness evaluation on the same frozen candidate; reviewers do not create a no-op repair | Missing authority/evidence or any accepted finding stays failed and uses repair/input-required. | Finding owner; independent validation |
| `REVIEW_REQUIRED → PR_READY` | Existing draft PR, all reviews complete, and blocking findings resolved | Exact-SHA sealed candidate-review EvidenceBundle, atomicity/issue/PR metadata, checks, and formal review when required | CP records readiness on the existing draft; it does not create, approve, undraft, or merge it | Missing review/check/evidence remains review-required; no self-approval/merge. | Formal review if repository policy requires |
| `PR_READY → PR_MERGED` | Existing draft PR marked ready by an authorized maintainer after all policies pass | GitHub-recorded exact head, required checks/approvals, merge actor/time/method/SHA, and primary issue linkage | Eligible maintainer marks ready and merges; CP only observes and validates | Changed head or missing check/review returns to review-required; rejected/closed PR → `BLOCKED`. | Yes |
| `PR_MERGED → STAGING_DEPLOYED` | Approved staging action and immutable artifact/config built from merged source | Merge/head/artifact parity plus real environment deployment ID and digest match | Deployment adapter deploys only | Adapter/infrastructure/check failure → `STAGING_FAILED`; teardown/rollback. | Per environment policy |
| `PR_MERGED → STAGING_FAILED` | Staging attempt using merged artifact | Failed deploy/check and cleanup evidence | CP records failure only | Candidate repair requires a new issue/PR; infrastructure failure blocks; no canary. | No |
| `STAGING_FAILED → REPOSITORY_ANALYSED` | Accepted code/config defect within approved product scope and a new remediation run | Failure mechanism, staging teardown, new defect issue, current target-branch SHA, and fresh exact-SHA RepositorySnapshot | Repository intelligence re-admits the changed upstream repository before architecture and TestPlan generation | Product change → contract input; infrastructure-only problem → blocked. Architecture must be reproposed/re-admitted even when the decision is “unchanged.” | Owner for classification |
| `STAGING_FAILED → BLOCKED` | Missing/broken infrastructure or failed cleanup | Blocker/owner/environment state | CP stops and protects environment | Human resolves; resume at staging with same exact artifact or reverify changed one. | Often SO |
| `STAGING_DEPLOYED → CANARY_DEPLOYED` | Staging pass, canary authorization, policy | Staging EvidenceBundle, bounded cohort/traffic/window, rollback readiness | Traffic/deploy adapter exposes canary only | Failure to deploy or any guardrail breach → `CANARY_FAILED`. | Per approved canary policy |
| `CANARY_DEPLOYED → CANARY_FAILED` | Canary telemetry window | Exact deploy, SLO/guardrail breach and detection evidence | CP aborts promotion and starts rollback | Immediate rollback; no averaging away critical breach. | No |
| `CANARY_FAILED → ROLLBACK_IN_PROGRESS` | Abort decision and rollback subject | Last-known-good/migration compatibility/runbook | Rollback adapter executes only | Rollback failure → `BLOCKED` with incident escalation. | No; pre-authorized emergency action |
| `CANARY_DEPLOYED → PRODUCTION_APPROVAL_REQUIRED` | Successful complete canary window | All canary gates, no unresolved findings, exact subjects | CP requests named production approval | No approval means wait/expire; canary remains bounded or is removed by policy. | Yes |
| `PRODUCTION_APPROVAL_REQUIRED → CANARY_FAILED` | Canary exposure remains active and its authorization expires or any SLO/guardrail/safety-budget signal breaches while approval is pending | Exact canary/traffic state, complete telemetry through breach, abort decision, and rollback subject | Independent watchdog/CP aborts the canary immediately; production approval cannot suppress or average away the breach | Enter rollback through the existing canary-failed path; missing telemetry also fails closed. | No |
| `PRODUCTION_APPROVAL_REQUIRED → PRODUCTION_DEPLOYED` | Named approval bound to merged source, artifact/config/migration/target/policy | GitHub merge/head/SHA, approval identity/time/reason/digests, protected-environment authorization, and successful complete DeploymentResult | Production adapter progressively promotes only the merge-bound immutable artifact while CP records each step | Unmerged, stale, mismatched, or expired subject is refused before mutation; after any mutation, adapter failure/interruption must use the rollback transition below. | Yes |
| `PRODUCTION_APPROVAL_REQUIRED → ROLLBACK_IN_PROGRESS` | Production promotion started but failed or was interrupted after any traffic/instance/config/data mutation | Append-only DeploymentAttempt with completed/unknown steps, exact subjects, last-known-good, and rollback/migration plan | Independent watchdog/CP fails closed and invokes rollback; a missing final adapter response never implies success | Rollback failure → `BLOCKED` plus incident escalation; the run cannot remain approval-required or claim deployment. | No; pre-authorized emergency action |
| `PRODUCTION_APPROVAL_REQUIRED → BLOCKED` | Rejection/expiry/missing approver | Decision/reason and safe canary teardown | CP stops promotion | No completion; resume needs new exact approval after revalidation. | Yes |
| `PRODUCTION_DEPLOYED → LIVE_VERIFICATION_FAILED` | Live health/journey/SLO/business/privacy/security window | Runtime telemetry and exact deployment correlation | CP evaluates; no model verdict | Any hard breach/missing required signal starts rollback. | No |
| `LIVE_VERIFICATION_FAILED → ROLLBACK_IN_PROGRESS` | Failed live gate | Failure, last-known-good, rollback/migration plan | Rollback adapter executes | Rollback failure → blocked/incident; never completed. | No |
| `ROLLBACK_IN_PROGRESS → ROLLED_BACK` | Completed rollback | Service/data verification, RTO/RPO, traffic/config state, incident link | CP verifies restored state | Verification failure → blocked; continue incident response. | No |
| `ROLLED_BACK → REPOSITORY_ANALYSED` | Approved follow-up within original product scope/budget and a new remediation run | Incident finding, new defect issue, current target-branch SHA, and fresh exact-SHA RepositorySnapshot | Repository intelligence re-admits the changed upstream repository; architecture and TestPlan are then reproposed and revalidated | Product change → new contract/PCR; infrastructure-only follow-up → blocked. Merged history is never rewritten. | Owner decision |
| `ROLLED_BACK → BUDGET_EXCEEDED` | Rollback restored the last-known-good state but delivery budget is exhausted | Rollback verification, consumption ledger, stopped run, and resume conditions | CP stops non-safety work only | No new implementation/deployment until a named owner extends budget; restored production remains monitored under operations policy. | Budget extension requires named owner |
| `PRODUCTION_DEPLOYED → COMPLETED` | Full observation window passed | Exact production subjects, acceptance/SLO/guardrail PASS, complete sealed EvidenceBundle, rollback readiness, OutcomeReport | CP alone records terminal completion | Missing/invalid/stale/model-only evidence routes to live-verification-failed or blocked. | Prior production approval already required |
| `COMPLETED → LIVE_VERIFICATION_FAILED` | Post-completion evidence invalidation leaves active production safety, acceptance, or SLO conformance unproven | Original completion event/bundle, invalid item/subject, detection event, and incident link | Integrity monitor or CP appends revocation evidence and reopens the record; it never erases the original claim | Existing live-failure path starts rollback; no approval is needed to fail safe. | No |
| `COMPLETED → BLOCKED` | Post-completion evidence invalidation with no active-production safety risk | Original completion event/bundle, invalid item/subject, safety assessment, incident, owner, and recorded resume gate | CP revokes terminal status append-only and blocks; resume must re-run the recorded gate and every downstream proof | Claim stays invalid until exact-subject evidence is rebuilt; no silent return to completed. | Owner for resume |

Any non-terminal state may transition to `BLOCKED` for an external dependency. A state
without active production exposure may transition to `BUDGET_EXCEEDED` when its approved
delivery budget is exhausted. Mandatory monitoring, abort, rollback, and incident actions
have a separately reserved safety budget and cannot be stopped by the delivery budget.
While canary or production exposure is active, budget exhaustion is a hard guardrail
breach: it routes through `CANARY_FAILED` or `LIVE_VERIFICATION_FAILED`, completes
rollback, and only then may enter `BUDGET_EXCEEDED`. Both stopped states record the exact
resume state; neither permits implementation, deployment, or completion while unresolved.
