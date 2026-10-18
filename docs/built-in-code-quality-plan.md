# Built-in code quality: PMOS contract to PEOS product delivery

Status: partially implemented in reviewable PRs as of 2026-10-18; release blocked. See the implementation checkpoint before the original review.
Tracking: [#245](https://github.com/Abhillashjadhav/production-engineering-os/issues/245); planning PR [#246](https://github.com/Abhillashjadhav/production-engineering-os/pull/246).
Main baseline: `1a431b23f837b04237c99ab7b924a234def10171`. Existing planning baseline: `368bf4761f20e453fd7434822ee1fe562d06fc16`.

## Implementation checkpoint — 2026-10-18

Implementation is **partial; release remains blocked**. The owner authorized implementation in the conversation. Runtime changes are in an unmerged stack based on draft #240 (`7467778008ce1e49d6378140dda11edf451052c0`), not on main. Main is unchanged. The original source review below describes the main baseline and is retained as historical evidence; it is not a statement that every issue remains untouched.

| Packet | Implemented behavior | Work still required |
|---|---|---|
| T1.1 — execution boundary | Reuses #240's stricter response/test protocol and watchdog; adds provider-process cleanup and resource-bounded source compilation. | Establish authenticated provider write/credential isolation on an authorized supported host (#238). The release halt remains unconditional. A reproduced dynamic-interpreter startup failure has a bounded compatibility fix; exact supported-host CI must confirm it. |
| T1.2 — privacy and authority | Validates bounded contract, graph and provider context; checks known credential/canary patterns before provider calls and before evidence persistence; rejects unsafe source paths. | Protected approval issuer, general sensitive-data policy, external retention guarantees and complete shared-blob deletion. Pattern checks do not establish product privacy. |
| T1.3 — baseline reconciliation | Reuses the existing #234 proof-port retry in #265, with a reproduced empty-file race. Preserves protected secret-fixture locations without changing the scanner or allowlist. | Finish exact-head CI. Existing frontend dependency remediation needs a registry-enabled lockfile refresh (#261). |
| T2.1 — supported products | Protected, exact health and fixed fourteen-case task-tracker profiles bind starter, harness, checks and dependency inventory. Missing delivery adapters are explicit BLOCKED results. | Broader UI/API/database/background/AI capability profiles with actual verification adapters. |
| T2.2 — planning | Validates contract-bound graphs, coverage, dependencies, cycles, ownership and protected paths. The exact graph enters provider requests and evidence. | Semantic architecture generation and executable integration plans. Graphs are dependency context for whole-candidate generation, not an incremental executor. |
| T3.1 — bounded build | Cumulative reported token/call/output caps and wall-time checkpoints; bounded CLI/source inputs; frontend files in repair context. | Durable resume, dependency-ordered incremental execution and hard cancellation of synchronous provider calls. Provider-reported token usage is not independently metered; one call may overshoot. |
| T3.2 — repair quality | Required candidate checks and evidence readback recompute syntax, scanner and acceptance semantics from sealed source and observation blobs. Independent AI source review found defects that were fixed. | An active, source-aware independent advisory-review/repair loop. A local reviewer is not a runtime feature. |
| T4.1 — packaging | New product-package consumer binds an exact RELEASE_READY ledger and checks bounded no-follow source reads, tamper detection and fresh-directory syntax. | Actual clean-install and customer-journey proof. It always returns BLOCKED without those adapters; the current producer cannot qualify RELEASE_READY. |
| T4.2 — delivery | Existing release and approval gates stay enforced. | Authorized target deployment, post-deployment journey, monitoring and rollback proof. No deployment was performed. |

### Reviewable changes

The stack is [#265](https://github.com/Abhillashjadhav/production-engineering-os/pull/265) → [#259](https://github.com/Abhillashjadhav/production-engineering-os/pull/259) → [#260](https://github.com/Abhillashjadhav/production-engineering-os/pull/260) → [#262](https://github.com/Abhillashjadhav/production-engineering-os/pull/262) → [#263](https://github.com/Abhillashjadhav/production-engineering-os/pull/263) → [#264](https://github.com/Abhillashjadhav/production-engineering-os/pull/264). Each PR is one coherent concern: proof-race prerequisite, resource budgets, process cleanup, protected build/profile/graph/readback, privacy boundary, and package admission. Issues #252–#257 track these changes; #245 tracks the full outcome. No PR was merged.

### Validation and limits

Ruff check/format passed for 335 Python files; strict mypy passed for 205 source files. The latest focused core qualification ran 52 tests: 51 passed and one real-sandbox test was skipped on this host. The proof-package unit/CLI group passed all 88 tests after the fixture-location correction. Three broader local groups ran 2,658 tests with no failures and 21 skips (2,637 passed). The affected fourth group is being rerun. After the final interpreter-library change, 35 targeted regressions passed with one supported-host skip; a separate reviewer passed nine focused tests. These are overlapping selections, not additive totals. Two historical archive-publication tests could not run locally because the connector did not materialize the existing binary archive; GitHub retains the original blob. Exact-head GitHub CI remains queued/running.

A separate AI reviewer inspected the implementation and ran focused regressions. This is advisory evidence, not human approval or the required GitHub bot review. GitHub Codex explicitly refused all six review requests because the account's code-review quota is exhausted. No credits were purchased, no substitute approval was fabricated and no review/security check was disabled.

This local host cannot establish the required Bubblewrap namespace or protected offline interpreter ownership. No authenticated live-provider build, representative held-out complex product, clean install, public release or deployment has been qualified. A stronger control plane is not yet the requested autonomous usable-product delivery system.


### Exact implementation snapshot

| PR | Current head |
|---|---|
| #265 | `7f3413048d39a268083b5d806710ae5ddaff2620` |
| #259 | `2810e1ac4db51b9cccb8f7373d08ef15fc599387` |
| #260 | `82f5e4f95f39153b5f32aa68161c8e16eff8dbf5` |
| #262 | `2ff6edad18e946c72809cdd69c5dc3c230b95cd0` |
| #263 | `090d2895c87836105f45b55fc8d7cfc545c7e1a6` |
| #264 | `6f4da714c75401ccf9af34291c5ddc1dcc8e509c` |

All 34 changed source/test blob identities in final #264 were compared with reviewed local commit `c23d2c182d516fef6629c86659c4a7dd153608d0`; mismatches: zero. This establishes source correspondence, not successful CI or release authorization. The adjacent library directory and parent chain are part of the trusted interpreter installation; the loader compatibility fix is not a provider-isolation boundary.

## Outcome and scope

One approved PMOS contract enters PEOS. PEOS owns repository setup, technical decomposition, code generation, routine QA, bounded repair, packaging and the requested delivery verification. The owner approves product meaning and release, rather than writing templates, reading implementation code or manually operating QA.

The target is a complete customer-usable product within an explicitly supported capability profile, including complex products with several interacting components. A profile defines its stack, interfaces, data and security obligations, verification adapters and delivery target. Unsupported capabilities return exact gaps before generation. A finite test matrix cannot establish that any arbitrary product will work.

Keep one code generator and the existing six core states: `VALIDATED`, `BUILDING`, `VERIFYING`, `RELEASE_READY`, `HALTED`, `STOPPED`. Extend the current compiler, selection, Coder, sandbox and event/blob mechanisms. Deployment is a separately approved consumer of `RELEASE_READY`, within PEOS's product workflow; it does not redefine that state. Do not revive the legacy orchestration engine or add another bot/service.

This proposal expands the current [frozen-core scope](barebones-deletion-inventory.md). The [older end-to-end plan](PMOS-PEOS-END-TO-END-PLAN.md) supplies useful requirements, not proof of active functionality. Scope changes and implementation land in separately reviewed atomic PRs after plan review.

## What the review found

`VERIFIED` means source inspection or the specifically described bounded probe, not complete production certification. Missing active capabilities below are scoped to the supported core; retained legacy implementations and drafts are identified separately.

| ID | Priority | Weakness and customer consequence | Evidence | Planned closure |
|---|---|---|---|---|
| W01 | P0 | Generic provider commands inherit host user authority and environment. Candidate sandboxing alone does not protect verifier, approval inputs or evidence from the provider. | [CLI provider launch][provider]; draft #235 still blocks live-provider release. Actual deployment permissions remain unverified. | T1.1 |
| W02 | P0 | Main accepts inconsistent pytest reports, and setup/teardown failures can qualify as assertion RED. Candidate-produced JSON/sample counts cannot establish private function behavior, persisted state or honest measurement. | [Verifier][verifier]; bounded parser/response probes below. | T1.1, T2.2 |
| W03 | P1 | A regex predicate executes in the supervisor without a watchdog. Attempts/calls/output-byte caps exist, but cumulative token/wall-time caps and ordinary core checkpoint/resume are not complete. | [Predicate][predicate], [budget][budget], [workspace admission][workspace]. | T1.1, T3.1 |
| W04 | P1 | Receipt hashes bind content but do not authenticate an approver. Direct calls may explicitly omit approval inputs. Untrusted replacement of both contract and receipt must not authorize production. | [Approval verification][approval], [run admission][workspace]. | T1.2 |
| W05 | P1 | PEOS sends contract/plan/selected source to the provider and retains raw input/output/candidate evidence. Its own minimization, external retention and complete shared-blob deletion are not demonstrated by this path. | [Model request][request], [ledger][ledger]. Existing retention helpers are not blanket product-data deletion proof. | T1.2 |
| W06 | P1 | Runtime security checks cover narrow credential patterns, Python eval/exec and TODO markers. This is insufficient to establish generated-product authorization, privacy, egress or deletion behavior. | [Runtime scanner][scanner]. Repository security CI has a different scope. | T1.2, T2.2, T4.1 |
| W07 | P1 | Default starter is one Python health function; selection supports two exact recorded identities and the ordinary CLI does not pass a selected template into the core. Selection alone cannot build a complete application. | [Default template][template], [selection][selection], [CLI run][cli-run]. | T2.1 |
| W08 | P1 | Build tasks are requirement labels, without execution dependencies, ownership or an active architecture/data/interface model. Whole-plan retries are unsuitable for controlling complex integration. | [Compiled tasks][tasks], [generation loop][generation]. Legacy architecture/planner source is not active core behavior. | T2.2, T3.1 |
| W09 | P1 | Repair context omits JS/TS/CSS/HTML; advisory review sees digests rather than actual candidate code and is explicitly non-blocking. A model annotation is not code-quality verification. | [Request context][request], [advisory review][review]. | T3.1, T3.2 |
| W10 | P1 | Canonical support packaging verifies a fixed recorded/memory/fixture runtime. Mutable build inputs, reference-product previews and localhost tests do not establish clean installation of an arbitrary generated product. | [Package claim limits][package], [backend build][docker], [browser configuration][browser]. | T2.1, T4.1 |
| W11 | P1 | Existing monitoring authentication, durable storage and outbox retries are useful product-specific implementations. They do not establish a generated product's per-user permissions, migrations, restore, deletion or job-effect correctness. | [Monitoring authorization][auth], [storage][storage], [outbox][outbox]. Apply obligations only when the contract needs them. | T2.2, T4.1 |
| W12 | P1 | Core never deploys; legacy local deployment terminates its child and removes its verification DB, and production deployment is simulated. No current generic path proves a usable customer target and recovery. | [Core boundary][core], [local deployment][local], [simulation][simulation]. | T4.2 |

Current main scheduled [CI run 39110414795](https://github.com/Abhillashjadhav/production-engineering-os/actions/runs/39110414795), 2026-10-18: 12/13 jobs passed; frontend dependency audit failed on a high-severity `source-map-js` advisory, with three additional moderate findings. Core tests, candidate isolation, security-static, backend, E2E and preview jobs passed. A later successful **Trusted Security Finalizer** is a separate workflow, not a green full CI result. Fix and recheck the affected dependency/build path without suppressing the gate.

## Reconcile existing work first

| Existing work | Observed state | Reuse without overstating it |
|---|---|---|
| [#204](https://github.com/Abhillashjadhav/production-engineering-os/pull/204), [#223](https://github.com/Abhillashjadhav/production-engineering-os/pull/223) | Open, unmerged | Call-phase assertion classification; this alone does not establish a trusted observer. |
| [#209](https://github.com/Abhillashjadhav/production-engineering-os/pull/209), [#228](https://github.com/Abhillashjadhav/production-engineering-os/pull/228) | Open, unmerged | Explicit release-gate conjunction and approved-bundle admission. Reconcile overlapping compiler/runtime work against current heads. |
| [#235](https://github.com/Abhillashjadhav/production-engineering-os/pull/235), head `2122d55a` | Draft | Supervisor predicates, strict JSON, regex/aggregate deadlines, offline provider confinement. Authenticated live-provider authority remains unproved; preserve its release stop. |
| [#240](https://github.com/Abhillashjadhav/production-engineering-os/pull/240), head `74677780` | Draft, stacked on #235 | Fixed 14-case task-tracker observer, sequential creates/readback, traces and approval binding. Neither generic-product support nor full release proof. |
| [#238](https://github.com/Abhillashjadhav/production-engineering-os/issues/238) | Existing live-provider work | Complete authenticated provider/protected-verifier proof here; no paid API fallback or copying credentials into candidate workspaces. |

Do not merge this stack wholesale or count branch existence as implemented capability. First select one reviewed integration base, preserve approved requirements/receipts, and rerun exact-head compatibility and planted-failure checks. Historical task-tracker acceptance and its expressly admitted weaker-isolation limitations remain historical; they cannot authorize a stronger production claim.

## Four implementation stages

### 1. Make execution, approvals and evidence trustworthy

- **T1.1 — Provider/verifier boundary (W01–W03).** Reconcile the existing observer/parser/watchdog fixes. The whole provider process tree may write only admitted implementation paths; it cannot alter approved expectations, policy, verifier, approval inputs or the supervisor-owned verdict ledger. Broker only explicitly authorized credentials/network operations. Protect the supervisor with its own identity/permissions; another LLM invocation alone is not isolation. Preserve candidate-only/HALTED results until the actual authenticated provider boundary is demonstrated.
- **T1.2 — Approval and privacy policy (W04–W06).** Retain exact-digest receipts, and require an operator-controlled approval authority outside the builder's reach for production eligibility. Keep product approval and release approval separate. Define PEOS prompt/evidence privacy separately from generated-product privacy: allowed data/fields, provider destinations, logs, retention/deletion and backups. Use synthetic data, pre-send data checks, minimal task context and restricted evidence. Preserve raw approved input digests privately; do not silently redact and relabel them. The owner chooses business data/access rules once in PMOS; PEOS translates them into controls and tests.
- **T1.3 — Integration/CI baseline (W01–W06, W10).** Reconcile one supported branch, preserve all required gates, repair the current dependency audit and verify effective repository merge restrictions. The branch API reports main `protected:false`; effective ruleset configuration was not established by this audit. Required check evidence must bind the exact candidate; a green badge is not itself an access control.

**Exit test:** planted provider/grandchild writes, forged result/approver, test mutation, stale receipt, setup crash, pathological regex and secret/PII canaries cannot produce release eligibility. Valid supported behavior still passes. Verify forbidden reads/writes/egress and process cleanup on the actual supported host. Test PEOS run deletion including shared blobs, and distinguish external provider/backup retention that PEOS cannot control. No credential relocation or host-security change is implied by approval of this plan.

### 2. Compile the contract into a buildable product

- **T2.1 — Product profile and working starter (W07, W10).** Extend existing selection and wire the exact selected starter through the ordinary CLI into the engine. Bind stack/toolchain, lockfiles, configuration schema, starter digest, permitted dependencies, runtime integrations, verification adapters and delivery target. Bind a required-check manifest with executable build/type/lint, secret/dependency/security, functional, declared nonfunctional and release checks; each entry names command, tool/version, applicability and required evidence. Extract reusable infrastructure from existing products when justified; no copied product-specific engine. Unsupported capabilities block with an exact gap rather than silently using fixtures or a health scaffold.
- **T2.2 — Architecture, task graph and protected checks (W02, W06, W08, W11).** Generate a short architecture/data/interface/threat record and a compiler-validated task dependency graph. Each task names requirement/acceptance IDs, prerequisites, data/interface ownership, allowed files, outputs and affected integration checks. Reuse applicable canonical schema fields. Freeze approved expected outcomes outside builder authority. Add trusted browser/API/storage/process/job observers for supported product profiles; candidate JSON is output, never proof of an internal side effect or a security verdict.

**Exit test:** a non-health contract selects, builds and starts the correct starter via the supported CLI. Cycles, missing acceptance coverage, a missing required-check command/evidence, contradictory interfaces, duplicated ownership and unsupported observations block before feature generation. A fake success without persisted state, unauthorized second-user access and a broken producer/consumer interface fail the relevant unchanged checks. Stateless products are not forced to acquire accounts or a database.

### 3. Build, integrate and repair in bounded steps

- **T3.1 — Task execution and recovery (W03, W08, W09).** Keep one controlled Coder role. Before implementing each new behavior, establish a genuine failing acceptance assertion on a protocol-valid baseline; preserve explicit `satisfied_by_template` exceptions and already passing checks. Execute dependency-ready behavior slices, with scoped source/context for every supported stack. Run affected checks and integration milestones after changes, then every required check in the bound manifest on the final candidate. Persist task, contract, starter, plan, candidate, tool and environment identities with cumulative resource use. Implement explicit run-wide and task repair/call/output/token/wall-time limits; current main's token/time telemetry is not such a cap. Restore consumption on resume and invalidate stale dependent proofs. The earlier three-round suggestion is a proposed policy default, not a hidden replenishable allowance per task.
- **T3.2 — Code-quality review with evidence (W09).** Give a separate review invocation the actual source, architecture, requirements and trusted results. Correctness, coupling, dependency boundaries and error handling need specific findings. Convert a reproducible defect or violated declared rule into a protected check; record unsupported review concerns as advisory. REA remains an optional inspection tool for supported artifacts and traces, not a replacement for expected outcomes or executable checks. The Coder repairs implementation, not expectations. Repeated failure or budget exhaustion returns one named blocker and safe checkpoint, rather than shifting debugging to the PM.

**Exit test:** break one module's contract and verify failure at the first affected integration milestone. Interrupt before/after a task check; resume without losing completed work, resetting budgets, accepting stale proof or repeating non-idempotent effects. An irrelevant edit cannot clear the same finding. A real source-level review defect becomes a failing check and passes only after repair. No skipped required check counts as PASS.

### 4. Prove a usable product on the declared target

- **T4.1 — Clean package and complete journeys (W06, W10, W11).** Package the actual sealed candidate, source, locked build/runtime dependencies, configuration requirements, setup/start/stop commands and verified evidence. Check a clean supported environment without the builder's private venv/caches/model credentials. For accounts/private shared data, prove server-side role/ownership checks, fresh sessions and second-user denial. For persistence, prove restart, migration, restore and contracted deletion/retention. For jobs, prove bounded retry, poison-job isolation and crash-after-effect/before-ack behavior with the contract's idempotency rules. Preserve intentionally non-idempotent task creation in the approved task-tracker contract. Apply runtime AI-quality evals separately from ordinary code tests.
- **T4.2 — Approved delivery and recovery (W12).** After package verification and any required owner release approval, install/deploy the same artifact to an authorized configured target. Record artifact/config/deployment identity and verify a fresh customer's actual critical journey. A requested internet link needs real audience reachability and appropriate TLS/session configuration; localhost or a stopped process cannot satisfy it. Exercise configured monitoring, a failure and recovery/rollback with the declared data-loss tolerance. No purchase, public deployment or new permission is authorized by this planning change. Missing infrastructure/runtime integration is a precise delivery blocker, not a fabricated usable product.

**Exit test:** a fresh intended user opens the declared link or installed application, completes every critical journey, and retrieves the correct result across refresh/restart when persistence is required. No coder edits source/config to rescue the run. Break a dependency, confirm readiness/monitoring reflects the failure, and restore the journey through the declared recovery path. A changed artifact/config invalidates prior delivery proof.

## Dependency order and reusable proof

Critical path: **T1 trust boundary → T2 admitted architecture/observers → T3 integrated candidate → T4 verified customer delivery**. Product-profile/schema design and privacy-test preparation can proceed alongside T1, but cannot grant release eligibility. Each packet becomes one coherent issue/implementation PR with test-first evidence, compatibility checks and one responsible writer. Reuse existing issues before opening duplicates.

Use existing refund/ticket/task-tracker cases as regression material only after verifying actual approved contract identities. Prove shared behavior across supported stateful workflow/API, UI/API/persistence and background/AI-tool product families. This is a cross-product qualification matrix, not another PMOS-only/toy demonstration.

Include at least one real-demand complex contract withheld from starter design, with expected acceptance results frozen before code generation. Exercise fresh generation, a requested feature change, repair, interruption/resume, clean packaging and target delivery through the same entry point. For a multi-user operations product, applicable cases include role separation, durable state, background effects and upgrade/recovery. The example does not select a new product for the owner. Record failures and unavailable integrations; finite evidence qualifies only the tested capability envelope.

## Completion, measures and owner experience

Three claims stay separate: **candidate checks passed**, **package verified**, **customer delivery verified**. Every required check reports PASS, FAIL, BLOCKED, PENDING or UNKNOWN with exact input identity; an inapplicable check has a justified applicability decision. Only complete passing evidence supports the corresponding claim. Use new delivery metadata without changing the six core state meanings.

Proposed North Star: share of admitted supported product contracts whose critical customer journeys succeed on the declared target without corrective technical intervention during the agreed observation window. Freeze eligibility before the run; post-admission failures and blockers remain in the denominator. Report unsupported-intake rate separately. The previous seven-day window is a proposal to validate, not an approved reliability claim.

Leading measures: executed requirement/gate coverage, first-pass integrated journey success, defects caught before delivery. Guardrails: PM technical-QA minutes, serious escaped defects, forbidden data exposure, false success, repair attempts, cumulative credits/time and new dependency burden. Set product/performance thresholds from approved policy and measured baselines; do not invent an improvement percentage. No paid model API, GPU, connector or hosting requirement is introduced.

Return one short owner report: what works, how to open it, what is blocked, proof identity and the remaining product/release decision. Routine diagnosis and bounded repair stay in PEOS. Open decisions for the affected capability are target/audience, business roles/data rules, external-service authorization, approval authority and resource policy; PEOS supplies technical proposals rather than making the PM design the system.

## Validation and evidence limits

Review combined pinned source inspection of active core, selected legacy code, draft #235/#240 and existing repairs; exact-head CI metadata/logs; and bounded offline probes. Fresh base64 fetches verified Git blob IDs for `barebones.py` (`23170402c37da9b21d5091254078efe5aedec8a2`) and `contracts/acceptance.py` (`a63fe33180b60383434517626c41dcd2f1b86c83`) before repeating the probes.

| Probe | Observed main behavior | Scope |
|---|---|---|
| Failed pytest setup/call/teardown reports | All three accepted as assertion failure | Original parser function; injected completed-process fixture |
| Inconsistent embedded pytest status/write record with child exit 0 | Accepted as PASS | Parser-level evidence validation, not full exploit proof |
| Import-time expected JSON then exit, no health function | No criterion/security finding | Harmless local adapter fixture; public-output proof only |
| Accepted pathological regex and short adversarial value | Exceeded an external one-second watchdog; child terminated | Original predicate/compiler functions, not the complete service |

Source-extraction probes used standard-library fixture substitutions for unavailable package dependencies; canonicalization, actual Bubblewrap, authenticated model execution, a clean full build, deployment and security certification were not rerun. No product was generated in this planning change. This is a review and implementation plan, not completed remediation or a guarantee of arbitrary-product security.

Security requirements should be selected by product risk from [OWASP ASVS](https://owasp.org/projects/asvs); use [NIST SSDF](https://csrc.nist.gov/pubs/sp/800/218/final) as lifecycle guidance. Neither is a certification conferred by this plan.

[provider]: https://github.com/Abhillashjadhav/production-engineering-os/blob/1a431b23f837b04237c99ab7b924a234def10171/src/pmpe/cli/barebones_cmd.py#L143-L157
[verifier]: https://github.com/Abhillashjadhav/production-engineering-os/blob/1a431b23f837b04237c99ab7b924a234def10171/src/pmpe/barebones.py#L681-L707
[predicate]: https://github.com/Abhillashjadhav/production-engineering-os/blob/1a431b23f837b04237c99ab7b924a234def10171/src/pmpe/barebones.py#L511-L512
[budget]: https://github.com/Abhillashjadhav/production-engineering-os/blob/1a431b23f837b04237c99ab7b924a234def10171/src/pmpe/barebones.py#L64-L67
[workspace]: https://github.com/Abhillashjadhav/production-engineering-os/blob/1a431b23f837b04237c99ab7b924a234def10171/src/pmpe/barebones.py#L1008-L1070
[approval]: https://github.com/Abhillashjadhav/production-engineering-os/blob/1a431b23f837b04237c99ab7b924a234def10171/src/pmpe/contracts/authoring.py#L231-L326
[request]: https://github.com/Abhillashjadhav/production-engineering-os/blob/1a431b23f837b04237c99ab7b924a234def10171/src/pmpe/barebones.py#L909-L928
[ledger]: https://github.com/Abhillashjadhav/production-engineering-os/blob/1a431b23f837b04237c99ab7b924a234def10171/src/pmpe/evidence/ledger.py#L93-L174
[scanner]: https://github.com/Abhillashjadhav/production-engineering-os/blob/1a431b23f837b04237c99ab7b924a234def10171/src/pmpe/barebones.py#L865-L883
[template]: https://github.com/Abhillashjadhav/production-engineering-os/blob/1a431b23f837b04237c99ab7b924a234def10171/src/pmpe/barebones.py#L397-L411
[selection]: https://github.com/Abhillashjadhav/production-engineering-os/blob/1a431b23f837b04237c99ab7b924a234def10171/src/pmpe/barebones_selection.py#L319-L326
[cli-run]: https://github.com/Abhillashjadhav/production-engineering-os/blob/1a431b23f837b04237c99ab7b924a234def10171/src/pmpe/cli/barebones_cmd.py#L245-L272
[tasks]: https://github.com/Abhillashjadhav/production-engineering-os/blob/1a431b23f837b04237c99ab7b924a234def10171/src/pmpe/contracts/acceptance.py#L92-L104
[generation]: https://github.com/Abhillashjadhav/production-engineering-os/blob/1a431b23f837b04237c99ab7b924a234def10171/src/pmpe/barebones.py#L1174-L1198
[review]: https://github.com/Abhillashjadhav/production-engineering-os/blob/1a431b23f837b04237c99ab7b924a234def10171/src/pmpe/barebones.py#L1355-L1401
[package]: https://github.com/Abhillashjadhav/production-engineering-os/blob/1a431b23f837b04237c99ab7b924a234def10171/src/pmpe/support_package.py#L1528-L1551
[docker]: https://github.com/Abhillashjadhav/production-engineering-os/blob/1a431b23f837b04237c99ab7b924a234def10171/products/pm-evals-web/backend/Dockerfile#L2-L12
[browser]: https://github.com/Abhillashjadhav/production-engineering-os/blob/1a431b23f837b04237c99ab7b924a234def10171/products/pm-evals-web/e2e/playwright.config.ts#L21-L65
[auth]: https://github.com/Abhillashjadhav/production-engineering-os/blob/1a431b23f837b04237c99ab7b924a234def10171/products/pm-evals-web/backend/src/pm_evals_api/app.py#L277-L344
[storage]: https://github.com/Abhillashjadhav/production-engineering-os/blob/1a431b23f837b04237c99ab7b924a234def10171/products/pm-evals-web/backend/src/pm_evals_monitoring/storage.py#L109-L185
[outbox]: https://github.com/Abhillashjadhav/production-engineering-os/blob/1a431b23f837b04237c99ab7b924a234def10171/products/pm-evals-web/backend/src/pm_evals_monitoring/outbox.py#L342-L392
[core]: https://github.com/Abhillashjadhav/production-engineering-os/blob/1a431b23f837b04237c99ab7b924a234def10171/src/pmpe/barebones.py#L991-L1006
[local]: https://github.com/Abhillashjadhav/production-engineering-os/blob/1a431b23f837b04237c99ab7b924a234def10171/src/pmpe/deployment/local.py#L92-L131
[simulation]: https://github.com/Abhillashjadhav/production-engineering-os/blob/1a431b23f837b04237c99ab7b924a234def10171/src/pmpe/deployment/simulated.py#L1-L60
