# Product decisions and trade-offs

Status: Phase 0 decisions for umbrella issue
[#60](https://github.com/Abhillashjadhav/production-engineering-os/issues/60).
These decisions govern implementation planning; they do not supply missing customer,
business, infrastructure, privacy, or launch truth.

## Responsibility boundary

The proposed PM Agent OS / Production Engineering OS split is directionally correct
with the following clarifications.

| Concern | PM Agent OS owns | Production Engineering OS owns | Approval boundary |
|---|---|---|---|
| Problem, outcome, hypothesis, scope | Product truth and trade-offs | Validate presence/consistency; never rewrite | Named product approver |
| Requirements and UX | User-visible behavior, flows, accessibility intent, acceptance | Compile architecture/tests and verify conformance | Product approves user-visible changes |
| Metrics and SLOs | Outcome definitions, targets, guardrail intent, observation window | Instrumentation, calculation, alerts, gate execution | Product/business approves targets; engineering approves mechanism |
| Security/privacy/data | Risk appetite, policy/compliance intent, classifications, retention/deletion outcomes | Threat model, controls, scans, verification, incident/rollback mechanics | Security/privacy owner for material risk or waiver |
| Architecture | Technical constraints that are product facts | Reversible design, ADRs, threat/deployment/observability architecture | Engineering owner; product input if user-visible, irreversible, vendor/data, cost, or launch trade-off changes |
| QA | Acceptance and release confidence intent | Test strategy, test code, environments, deterministic evidence | Engineering owner; product owns acceptance interpretation |
| Release/deployment | Launch intent, eligible audience, business guardrails | Staging/canary/production execution and verification | Named production approver bound to exact subject |
| Rollback | Product RTO/RPO, data-loss tolerance, customer communication intent | Rollback design, automation, rehearsal, execution evidence | Engineering/operations; product for irreversible data/customer trade-offs |
| Post-release learning | Hypothesis decision and roadmap response | OutcomeReport, evidence, incident/PCR generation | Product decides what changes next |

“Architecture approved” therefore means an engineering approval, not a new product
decision. “Production approved” means a named human authorization for a specific
artifact, configuration, migration, target, and rollout policy; launch intent alone
is insufficient.

## Decision record

### PD-P0-01 — Autonomy versus safety

- **Chosen direction:** bounded, fail-closed autonomy. Deterministic policy controls
  state, evidence, permissions, budgets, and gates; agents propose work.
- **Reason:** the repository already follows “agents propose; Python disposes,” and
  missing product truth or stale evidence must never be guessed through.
- **Benefit:** safe resume, clear escalation, no model-only completion.
- **Downside:** more PRODUCT_INPUT_REQUIRED/BLOCKED outcomes and slower happy paths.
- **Dominant trade-off:** autonomy yield versus false-DONE/unsafe-action risk.
- **Reversal condition:** only if measured safe-block false-positive cost exceeds the
  risk reduction and an equally auditable control is proven.
- **Evidence to revisit:** at least two release cohorts with blocker precision,
  false-DONE rate, escaped defects, manual interventions, and rollback outcomes.

### PD-P0-02 — Delivery speed versus verification depth

- **Chosen direction:** risk-tiered verification with non-weakenable minimum gates.
- **Reason:** not every change needs the same suite, but every omitted test class
  requires a named rule and evidence.
- **Benefit:** preserves safety while avoiding maximum-cost verification for low risk.
- **Downside:** risk classification and applicability policy add complexity.
- **Dominant trade-off:** lead time/cost versus confidence.
- **Reversal condition:** a gate is removed or reduced only after production evidence
  shows low defect yield and no material coverage loss.
- **Evidence to revisit:** gate duration/cost, defect yield by gate, escaped-defect
  origin, and risk-tier calibration.

### PD-P0-03 — Standard contract versus repository flexibility

- **Chosen direction:** one required standard core plus typed, versioned extensions
  that may strengthen but not weaken the core.
- **Reason:** three current contract formats prove both the need for a common seam and
  repository/product-specific detail.
- **Benefit:** portable lifecycle and traceability with explicit flexibility.
- **Downside:** compatibility/compiler maintenance and more authoring structure.
- **Dominant trade-off:** interoperability versus local fit.
- **Reversal condition:** the core demonstrably blocks multiple valid repository
  classes despite extensions.
- **Evidence to revisit:** compilation loss/error rates across at least five materially
  different repositories and contract-author effort.

### PD-P0-04 — One orchestrator versus multiple specialists

- **Chosen direction:** one deterministic control-plane orchestrator with the minimum
  specialist roster selected per task.
- **Reason:** multiple independent orchestrators create conflicting authority, while a
  monolithic model lacks specialist permissions and review independence.
- **Benefit:** one state authority, least privilege, focused expertise.
- **Downside:** routing, worktree integration, and agent-contract maintenance.
- **Dominant trade-off:** coordination simplicity versus specialist quality/isolation.
- **Reversal condition:** routing overhead or integration defects exceed measurable
  specialist benefit.
- **Evidence to revisit:** route accuracy, review defect yield by specialist,
  integration failures, latency, and cost.

### PD-P0-05 — Automatic repair versus bounded failure

- **Chosen direction:** repair only accepted engineering findings, within file/task
  scope, with per-finding and per-stage attempt/cost limits; then stop.
- **Reason:** current fixer scoping is strong, but an unbounded loop would spend
  indefinitely or erode gates.
- **Benefit:** efficient correction without runaway or product-scope mutation.
- **Downside:** recoverable problems may require human continuation.
- **Dominant trade-off:** repair success versus cost/scope creep.
- **Reversal condition:** bounds may change when repair telemetry proves a different
  optimum without higher escaped-defect or gate-weakening rates.
- **Evidence to revisit:** repair success by attempt, regression rate, scope violations,
  tokens/time per attempt, and findings requiring human work.

### PD-P0-06 — Automatic deployment versus human approval

- **Chosen direction:** local/test and approved staging may automate after gates;
  canary is policy-bounded; production requires named exact-subject human approval.
- **Reason:** launch intent is not authorization to touch an environment, and the
  current repository has no real production adapter.
- **Benefit:** separation of duties and controlled blast radius.
- **Downside:** approval latency and operator dependency.
- **Dominant trade-off:** release throughput versus production risk.
- **Reversal condition:** production approval policy can be relaxed only for a
  separately approved low-risk class with strong environment controls and audit.
- **Evidence to revisit:** approval wait time, canary outcomes, rollback frequency,
  incident severity, and protected-environment audit.

### PD-P0-07 — Architecture consistency versus local optimization

- **Chosen direction:** the admitted ArchitecturePack sets enforceable boundaries;
  local deviations require an ADR or fail.
- **Reason:** optimization without boundary evidence creates drift and weakens
  repository-wide review.
- **Benefit:** predictable composition, security boundaries, and easier rollback.
- **Downside:** small local improvements may wait for an ADR.
- **Dominant trade-off:** global maintainability versus local speed/performance.
- **Reversal condition:** the architecture itself becomes the bottleneck and a
  reviewed superseding ADR improves measured outcomes.
- **Evidence to revisit:** boundary violation frequency, change lead time, performance
  bottlenecks, and architecture-review findings.

### PD-P0-08 — Non-technical simplicity versus transparency

- **Chosen direction:** progressive disclosure: plain-language guided steps backed by
  expandable raw IDs, digests, commands, costs, risks, and evidence.
- **Reason:** hiding technical truth creates false confidence; exposing only artifacts
  makes the system unusable for product owners.
- **Benefit:** approachable governance without an alternate control plane.
- **Downside:** Guided Mode information architecture is harder to design.
- **Dominant trade-off:** cognitive load versus informed control.
- **Reversal condition:** user research shows progressive disclosure still prevents
  safe task completion.
- **Evidence to revisit:** product-owner task completion, comprehension, approval
  errors, accessibility results, and support interventions.

### PD-P0-09 — Reusable platform versus project-specific logic

- **Chosen direction:** stable lifecycle/contracts/evidence core with adapter-based
  repository, test, deployment, telemetry, and UI implementations.
- **Reason:** V1’s one-stack generator and V3’s product-specific web path demonstrate
  the cost of embedding project behavior in the core.
- **Benefit:** reuse with honest unsupported capability blocking.
- **Downside:** adapter interfaces and compatibility testing add design work.
- **Dominant trade-off:** breadth/reuse versus first-project speed.
- **Reversal condition:** an abstraction has only one durable implementation and
  measurably increases failure/maintenance cost.
- **Evidence to revisit:** adapter count, duplicated logic, implementation effort,
  contract-test failures, and change amplification.

### PD-P0-10 — Cost versus reasoning depth

- **Chosen direction:** deterministic code for mechanical checks; frontier/xhigh
  reasoning for ambiguous architecture, high-risk plans, and independent review;
  cheaper models only for bounded tasks with equivalent gates.
- **Reason:** model cost should buy judgment, not replace parsers, schemas, or tests.
- **Benefit:** higher reasoning quality where error cost is high and lower spend on
  mechanical work.
- **Downside:** routing and calibration are required; cheap outputs can still fail.
- **Dominant trade-off:** reasoning quality versus tokens/latency.
- **Reversal condition:** evals show a lower-cost tier meets the same gate/defect bar
  for a task class.
- **Evidence to revisit:** per-stage cost, latency, eval pass rate, repair rate, review
  defect escape, and manual intervention.

### PD-P0-11 — Fast mode versus credit consumption

- **Chosen direction:** Fast mode may reduce latency but never changes gate depth,
  permissions, or evidence. Each run needs a contract/operator cost-credit budget plus
  a separately reserved safety budget for monitoring, abort, rollback, and incident
  actions. Ordinary work stops at BUDGET_EXCEEDED only after evidence proves zero
  rollout-owned staging, candidate-canary, and changed-production resources or
  exposure. Active or indeterminate staging first tears down; active or indeterminate
  canary/changed-production exposure first rolls back and then cleans staging. The
  restored or existing last-known-good production deployment is not removed.
- **Reason:** speed is a scheduling/cost choice, not a safety policy.
- **Benefit:** faster interactive progress without a hidden verification downgrade.
- **Downside:** credits may exhaust earlier; the exact budget is currently missing.
- **Dominant trade-off:** wall-clock latency versus credit consumption.
- **Reversal condition:** measured Fast mode spend or quality is worse for the stage,
  or the approved budget does not support it.
- **Evidence to revisit:** credits/tokens per accepted stage, elapsed time, retries,
  quality gates, and budget-exceeded rate.

### PD-P0-12 — One large workflow versus atomic lifecycle stages

- **Chosen direction:** explicit atomic stages with persisted inputs, evidence,
  permitted actions, failure transitions, and rollback.
- **Reason:** the current V1/V2/V3 state machines are strong locally but divergent; one
  opaque workflow would make resume and audit worse.
- **Benefit:** isolated repair, safe resume, independent verification, and observable
  bottlenecks.
- **Downside:** more states, artifacts, and transition code.
- **Dominant trade-off:** operational clarity versus system complexity.
- **Reversal condition:** state complexity produces more defects than it prevents and
  a simpler model preserves all invariants.
- **Evidence to revisit:** invalid-transition defects, crash recovery, operator
  comprehension, state dwell time, and maintenance cost.

### PD-P0-13 — File-type splitting versus outcome atomicity

- **Chosen direction:** one independently reviewable outcome per issue/primary PR.
  Split schema, runtime/compiler logic, and narrative documentation when each is a
  useful outcome; keep the tests, evidence, and generated artifacts needed to prove
  one outcome with it. Contract intake is therefore #62 schema, #76 compiler/migrations,
  and #77 documentation.
- **Reason:** the prior `CLAUDE.md` file-type rule conflicted with outcome-based
  atomicity and made issue #62 non-executable as written.
- **Benefit:** repository instructions and the issue graph agree; each PR can be
  reverted and reviewed independently without artificial test/evidence separation.
- **Downside:** cross-issue sequencing and temporary incomplete capability states.
- **Dominant trade-off:** review/revert clarity versus end-to-end delivery latency.
- **Reversal condition:** evidence shows a split cannot yield independently valid
  intermediate states or repeatedly causes integration defects.
- **Evidence to revisit:** cross-PR defect rate, blocked time, review size, rollback
  isolation, and duplicated coordination work.

## Contradictions and tensions identified

| Tension | Finding | Resolution in this plan |
|---|---|---|
| Problem versus solution | The mission is a general production system; current implementation is mostly a local-first single-stack pipeline plus one V3 product path. | Keep claims scoped; build adapters and unified contracts rather than rename existing simulation as production. |
| Hypothesis versus metrics | No approved product hypothesis or outcome target for this transformation was supplied. | Record architecture direction, but leave business target thresholds as PRODUCT_INPUT_REQUIRED. |
| North Star versus safety | “Delivery rate” can reward shipping and punish safe blocking. | Denominator includes only validated eligible slices; guardrails separately enforce false-DONE, security, rollback, and escaped defects. |
| MVP North Star versus manual handholding | “Without manual engineering handholding” is not operationally defined. | Use the full autonomy-guardrail definition: count planned or unplanned human technical execution, acceptance-oracle interpretation, code/test/config/artifact/environment/traffic/deployment/rollback mutation, and slice-specific/post-eligibility infrastructure work as manual engineering intervention; product decisions, approvals, formal review judgment, and pre-eligibility shared-platform provisioning remain governance. |
| Autonomy versus deployment | Proposed lifecycle automates through production, while the repository explicitly has fixture-only production. | Phase the work; real production remains blocked until infrastructure, provider, protected environment, approval, SLO, canary, and rollback decisions exist. |
| PM ownership versus contract contents | Security/privacy/data/QA/release/observability/rollback are requested in the contract but engineering also owns their execution. | PM owns intent/thresholds/policy; PEOS owns design, verification, execution, and evidence. |
| Architecture ownership versus approval | PEOS owns architecture, but `ARCHITECTURE_APPROVED` has no named approver. | Require an engineering owner; require product/security/operations approval only for cross-boundary decisions. |
| Independent review versus GitHub evidence | Repository comments claim independent reviews, but sampled PRs have zero formal review submissions and the workflow combines reviewer/fixer. | Track local/Codex analysis separately from formal GitHub review; never self-approve or fabricate a reviewer. |
| Tests before code versus V2 flow | V1 confirms red before code; V2 accepts specialist results that include both `tests_run` and commits. | Add an independently admitted executable TestPlan and meaningful-red evidence before implementation authorization. |
| Cost versus current instruction | The run requests GPT-5.6 Sol xhigh and Fast mode but supplies no credit budget. | Use the requested mode for Phase 0; mark budget thresholds as unresolved and require them in the target contract/operator policy. |
| Atomic PRs versus historical workflow | The GitHub reviewer can commit fixes and audit files into the reviewed PR in one context. | Target flow separates reviewer, approved fixer, verifier, and formal GitHub approver, with fix scope and new exact-SHA review evidence. |
| File-type versus outcome atomicity | `CLAUDE.md` required all schema, logic, and documentation changes to be separate, while #62 and Phase 0 governance originally treated a complete contract bundle as one PR. | Amend the repository rule to concern-based atomicity and split the independently useful contract schema (#62), compiler (#76), and documentation (#77). Required tests/evidence stay with their concern. |
| Repository documentation | `CLAUDE.md` says only Discovery is shipped; `README.md` says all five PM stages are shipped. | Treat neither as capability proof; resolve doc consistency under a dedicated issue only if it affects #62/#74 scope. |
| One-time approval versus continuing product authority | A contract can be valid at intake and later revoked, expired, or superseded while engineering or rollout work remains active. | Revalidate versioned product authority before every forward transition/mutation; stop no-rollout work at product input, clean staging, and roll back active exposure before re-admission. Safety actions remain separately authorized. |
| Intake traceability versus rejected-input confidentiality | A normal retained digest supports integrity but makes a deleted low-entropy secret or personal payload dictionary-testable. | Retain only opaque IDs plus a keyed, non-enumerable receipt fingerprint; keep the ordinary digest inside deletable quarantine and record it durably only after raw-input admission. |
| Metric continuity versus cohort validity | Allowing eligibility before maturity-window policy exists creates lineages that cannot receive a non-retrospective due time. | Make the applicable approved maturity policy an eligibility prerequisite; keep pre-policy lineages in explicit baseline/pending-policy counts and admit them prospectively after approval. |
| Reproducibility versus vulnerability intelligence freshness | A pinned scanner/advisory snapshot is reproducible but can miss newly disclosed critical vulnerabilities. | Pin tools and evidence digests while separately enforcing an approved advisory maximum age; stale, unverifiable, or unavailable intelligence blocks rather than passes. |

## Unresolved questions requiring human input

1. What is the approved product hypothesis and target adoption/outcome for PEOS itself?
2. What target values and reporting windows apply to the North Star, MVP North Star,
   lead time, manual intervention, cost, escaped defects, rollback, and reliability?
3. Which staging/production provider, accounts, regions, protected environments,
   traffic-control adapter, and credential boundary are approved?
4. Who is eligible to approve architecture exceptions, security/privacy waivers,
   canary, and production? Is there an eligible GitHub collaborator for formal review?
5. What are the SLOs, canary size/window, RTO/RPO, data migration/rollback rules, and
   minimum live observation window?
6. What privacy classification, residency, retention, deletion, telemetry allowlist,
   and observability vendor are approved?
7. How will PM Agent OS deliver bundles and receive OutcomeReports/PCRs?
8. Is Guided Mode a web UI, terminal UI, or both, and what approved UX/accessibility
   flows govern it?
9. What per-run/stage token, credit, time, and repair-attempt budgets apply?
