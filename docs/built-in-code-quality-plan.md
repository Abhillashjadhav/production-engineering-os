# Built-in code quality: PMOS contract to PEOS product delivery

Status: proposed implementation plan; no runtime changes.
Tracking: [#245](https://github.com/Abhillashjadhav/production-engineering-os/issues/245).
Baseline inspected: `1a431b23f837b04237c99ab7b924a234def10171`.

## Outcome

The user submits one approved PMOS contract to PEOS and receives the requested runnable product, verification evidence, and remaining product decisions. PEOS owns routine engineering work and technical QA. The user approves intended behavior and release, without designing templates, reading code, or operating the verification workflow.

The four practices discussed in chat have not been implemented by this work.

## Fit with existing PEOS

Extend the current entry path: approved contract → compile → template → baseline checks → Coder → verification → evidence. Keep the existing approval receipts, bounded repair, sandbox, and evidence chain.

The [older end-to-end plan](PMOS-PEOS-END-TO-END-PLAN.md) describes a broader target; the [frozen-core inventory](barebones-deletion-inventory.md) deliberately excludes architecture workers and deployment. This proposal changes that scope only through separately reviewed implementation PRs. Do not revive legacy orchestration or add another service.

## Four changes inside PEOS

### 1. Prepare a working repository automatically

After contract validation, PEOS selects a versioned starter whose capabilities match the contract. Extend `src/pmpe/barebones_selection.py` rather than creating a second selection system.

Each starter contains the directory layout, dependency lockfile, configuration example without secrets, basic error handling, build/type/lint/security commands, and one verification entry point. It must initialize, build, and run in a clean environment. Record its version and content digest.

Create starters from the existing product implementations; retain only reusable infrastructure. Admit a new product type when an actual contract demonstrates the need. An unsupported contract returns the exact capability gap; it never falls back to an unrelated scaffold.

### 2. Set architecture and checks before feature code

PEOS derives a short architecture record: module responsibilities, data ownership, interfaces, permitted dependency directions, and external services. Reuse existing components; justify each additional dependency.

A separate review challenges this proposal against the contract before coding. Enforce objective boundaries with executable checks; aesthetic preferences remain advisory.

Use the existing contract compiler to bind every requirement to an acceptance check. Include failure and permission scenarios where applicable. Freeze expected results and verification controls outside the builder's writable scope. Missing business decisions return to PMOS; routine technical choices remain PEOS responsibilities.

### 3. Generate, verify, and repair in small steps

The existing Coder implements one coherent behavior at a time. For a new behavior, first establish a meaningful failing acceptance check; preserve the current explicit template-satisfied exceptions.

Run relevant checks after each step and the full applicable suite on the final candidate. The Coder may repair implementation but cannot weaken requirements, tests, or security controls. Cap the build/review repair loop at three rounds within the existing time/token budget; repeated failure stops with the exact unmet requirement.

Run a separate review invocation over the actual candidate, requirements, and results. Challenge correctness, duplication, coupling, dependencies, and error handling. A blocking finding requires concrete code evidence and a reproducible check, or a violated declared architecture rule. Record dismissed findings and reasons.

REA is an optional PEOS inspection tool for supported artifacts and runtime traces. It does not determine intended behavior, replace executable checks, or become a mandatory dependency.

### 4. Deliver a verified product for the declared target

Extend delivery after the current core, without redefining `RELEASE_READY`. Produce the package, setup instructions, configuration requirements, startup command, and product-level evidence.

Verify from a clean checkout and exercise real UI/API/storage boundaries required by the contract. Record fixture-backed, live, untested, and unavailable integrations separately. A model grader is appropriate for declared AI-output evaluations, not as proof of ordinary code correctness.

For a requested customer link, use a configured hosting target after release approval, then smoke-test the deployed artifact and its critical journey. Without hosting access/configuration, report the specific delivery blocker. A local package is not a live product.

Bind results to the exact candidate and, when deployed, the deployment identity. Reverify changed code. For generated GitHub repositories, enforce required checks with branch rules; green checks alone do not prevent bypasses.

## Implementation order and proof

1. Intake/selection: pass existing valid contracts; reject unsupported capabilities, altered starters, and missing checks.
2. Pre-code controls: reject a planted dependency-boundary violation, contradictory criteria, and changed acceptance expectations.
3. Build/review: catch a real behavior defect, reject test tampering, and demonstrate bounded repair plus an honest stop.
4. Delivery: reproduce the build and critical journey in a clean environment; verify the deployed link when the contract requests one.

Use the existing refund, ticket, and task-tracker cases where available. These are cross-product checks of the shared mechanism, not another PMOS-only demonstration. Supported stacks need their own commands and scenarios; arbitrary-product support remains unproven.

## Measures and user experience

Outcome: proportion of delivered features meeting the approved contract without corrective work during seven days.
Leading measures: requirements with executed checks; defects caught before delivery.
Guardrails: user technical-QA minutes per feature, serious escaped defects, repair time, and verification cost. Establish the baseline before claiming improvement.

Return one short product report: what works, how to open/use it, what remains blocked, and what evidence supports readiness. No external API purchases, paid infrastructure, or extra bot are required by this plan; delivery uses available authorized infrastructure.

## Validation of this planning change

Documentation only. Checked the proposed entry path against the current README, selection module, acceptance grammar, runtime review behavior, contribution rules, and frozen-core scope. No implementation tests, REA analysis runs, product builds, deployments, or merges were performed. This plan is not implementation or quality certification.
