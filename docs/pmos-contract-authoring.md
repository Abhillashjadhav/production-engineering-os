# PMOS contract authoring, validation, and migration

This guide describes the PM Agent OS (PMOS) contract accepted by Production
Engineering OS (PEOS). It is version-specific: the canonical bundle and manifest
described here are both **1.0.0**. “Latest” is not a compatibility promise.

All sample values are synthetic, contain no customer data or credentials, and are
not product decisions or production approvals. Start with the
[canonical bundle example](../examples/pmos-contracts/canonical-bundle-1.0.0.json)
and its [bound manifest](../examples/pmos-contracts/canonical-manifest-1.0.0.json).
The normative definitions are the
[bundle schema](../schemas/pmos_contract_bundle.schema.json) and
[manifest schema](../schemas/pmos_contract_manifest.schema.json); this guide
explains those definitions but does not replace them.

**Runtime boundary:** Direct canonical-bundle intake is not implemented at this
repository version. `PmosCompilationService` sends input to `CanonicalCompiler`,
whose format detector accepts only the V1, V2, and V3 markers listed below. If
the canonical example is passed to that service, it fails with
`AMBIGUOUS_SOURCE_FORMAT`; it is not an end-to-end admission request. Authors can
use the canonical example for schema authoring and deterministic semantic-rule
validation, but PEOS cannot yet admit a natively authored canonical bundle into
engineering. That production intake gap is an explicit blocker, not permission
to relabel canonical content as a legacy version or bypass durable intake.

## Ownership boundary

PMOS or an explicitly named product authority owns product truth: the problem,
outcomes, hypothesis, scope, priorities, requirements, UX, metrics, guardrails,
risks, privacy/security/data intent, QA expectations, release intent,
observability, rollback intent, open questions, and approvals. An empty field is
not permission for PEOS to choose a value.

PEOS owns deterministic mechanics: duplicate-aware parsing, schema and semantic
validation, compiler rules, canonical JSON and digest calculation, evidence
materialization, repository analysis, architecture and implementation artifacts,
and enforcement of approved gates. PEOS may diagnose missing or contradictory
truth, but cannot author, resolve, or approve it on PMOS's behalf.

A named approval asserts only its explicit subject and digest scope. A synthetic
name in an example is not an approval. Infrastructure availability, deployment,
monitoring evidence, rollback evidence, and independent review must be observed;
the contract cannot manufacture them.

## Canonical bundle 1.0.0

Author JSON against schema ID
`https://github.com/Abhillashjadhav/production-engineering-os/schemas/pmos_contract_bundle.schema.json`
with `schema_version` and `bundle_version` equal to `1.0.0`, and
`canonical_json_profile` equal to `RFC8785`.

The schema has two structural states:

1. A complete bundle contains every product section and has no
   `unresolved_product_truth` entries. Structural validity does not by itself
   mean semantic admission; named deterministic rules still inspect references,
   approval authority/freshness, contradictions, and ownership.
2. A compiler-produced incomplete bundle contains the identity/provenance core
   plus one or more blocking `unresolved_product_truth` records. It is valid
   evidence of a loss-aware conversion, but is not engineering-admissible.

The synthetic canonical example is structurally valid and its approval subjects
and extension payload carry their exact RFC 8785 digests. The executable example
test also runs every registered deterministic semantic rule with explicit,
matching synthetic authority grants. Those grants exist only in the test and do
not represent real authority evidence. The example therefore demonstrates valid
content authoring, not a deployable or currently intake-admissible contract.

Top-level fields are:

| Field | Owner and meaning |
| --- | --- |
| `bundle_id` | Stable bundle identifier; content identity is carried by a digest. |
| `bundle_version` | Version of this bundle instance, currently `1.0.0`. |
| `schema_id` | Exact normative bundle schema ID. |
| `schema_version` | Supported normative schema version, currently `1.0.0`. |
| `canonical_json_profile` | Digest serialization profile; must be `RFC8785`. |
| `contract_status` | PMOS-declared lifecycle status; approval records still control admission. |
| `provenance` | PMOS publication identity and optional compiler provenance. |
| `source_identity_mappings` | Stable source IDs/pointers mapped to canonical pointers. |
| `unresolved_product_truth` | Loss or ambiguity records; any entry blocks engineering. |
| `product` | Product name, customers/platform, problem, outcome, hypothesis, and priority. |
| `scope` | In-scope obligations and explicit non-goals. |
| `assumptions` | Product assumptions and how each will be validated. |
| `open_questions` | Named-owner questions with an explicit blocking flag. |
| `functional_requirements` | Product behavior with stable IDs and acceptance references. |
| `non_functional_requirements` | Quality attributes, targets, and evidence expectations. |
| `acceptance_criteria` | Verifiable outcomes bound to requirement IDs. |
| `ux` | Stories, journeys, flows, screens/states, edge cases, responsive and accessibility intent. |
| `backend_capabilities` | Required server-side capabilities. |
| `api_contracts` | Product-owned API method/path/purpose obligations. |
| `data` | Entities, fields, classifications, purposes, retention, and requirements. |
| `integrations` | External-system direction, purpose, and authentication intent. |
| `technical_constraints` | Approved constraints and their reasons, not inferred implementation choices. |
| `dependencies` | Declared product or external dependencies. |
| `security` | Threat-oriented requirements and secret-handling intent. |
| `privacy` | Residency, retention, deletion, telemetry, and lawful-purpose intent. |
| `metrics` | North stars, leading/success metrics, maturity policies, reporting, and windows. |
| `guardrails` | Thresholds and responses that constrain delivery/release. |
| `quality_assurance` | Expectations, golden cases, rubrics, and release gates. |
| `risks` | Severity and mitigation for each known risk. |
| `release` | Launch intent, audiences, environment, autonomy stage, gates, and approvals. |
| `observability` | Required signals and alert conditions. |
| `rollback` | Recovery triggers/evidence, RTO/RPO, data-loss and communication intent. |
| `required_approvals` | Approval obligations by purpose, role, and stage. |
| `approvals` | Versioned, authority-bound approval decisions over exact subjects. |
| `product_decisions` | Approved decisions linked to approval records. |
| `extensions` | Typed, digest-bound additive constraints. |

Required nested shapes are listed below. Registry keys are stable IDs and `*`
means each registry item. Optional fields remain governed by the schema; do not
add unknown fields because the core uses `additionalProperties: false`.

| Path | Required fields |
| --- | --- |
| `product` | `product_name`, `target_customers`, `target_platform`, `problem`, `outcome`, `hypothesis`, `priority` |
| `product.problem` | `statement`, `affected_customers` |
| `product.outcome` | `statement`, `customer_outcome`, `business_outcome`, `measurable_change` |
| `product.hypothesis` | `statement`, `falsification_condition` |
| `product.target_platform` | `kind`, `description` |
| `scope` | `in_scope`, `non_goals` |
| `assumptions.*` | `statement`, `validation_plan` |
| `open_questions.*` | `question`, `owner_ref`, `blocking` |
| `functional_requirements.*` | `title`, `statement`, `priority`, `acceptance_criterion_refs` |
| `non_functional_requirements.*` | `category`, `requirement`, `target`, `evidence_expectation` |
| `acceptance_criteria.*` | `criterion`, `requirement_refs`, `verification_method` |
| `ux` | `user_stories`, `primary_journey`, `flows`, `screens`, `ui_states`, `edge_cases`, `accessibility`, `responsive_requirements` |
| `ux.user_stories.*` | `as_a`, `i_want`, `so_that` |
| `ux.primary_journey.*` | `sequence`, `description`, `screen_ref` |
| `ux.flows.*` | `name`, `actor`, `goal`, `steps` |
| `ux.flows.*.steps.*` | `action`, `expected_outcome` |
| `ux.screens.*` | `name`, `purpose`, `state_refs` |
| `ux.ui_states.*` | `description` |
| `ux.edge_cases.*` | `condition`, `expected_behavior`, `requirement_refs` |
| `ux.accessibility.*` | `requirement`, `standard`, `level`, `evidence_expectation` |
| `ux.responsive_requirements.*` | `requirement` |
| `backend_capabilities.*` | `description` |
| `api_contracts.*` | `method`, `path`, `purpose` |
| `data` | `entities`, `requirements` |
| `data.entities.*` | `name`, `fields` |
| `data.entities.*.fields.*` | `type`, `required` |
| `data.requirements.*` | `requirement`, `classification`, `purpose`, `retention` |
| `integrations.*` | `name`, `direction`, `purpose`, `authentication` |
| `technical_constraints.*` | `constraint`, `reason` |
| `dependencies.*` | `description` |
| `security` | `requirements`, `secret_handling` |
| `security.requirements.*` | `threat`, `requirement`, `verification` |
| `privacy` | `requirements`, `data_residency`, `retention`, `deletion`, `telemetry`, `contract_data_policy` |
| `privacy.requirements.*` | `data_category`, `lawful_purpose`, `requirement` |
| `privacy.data_residency` | `allowed_regions`, `cross_border_transfer_policy` |
| `privacy.retention` | `policy`, `duration`, `owner_ref` |
| `privacy.deletion` | `trigger`, `deadline`, `verification` |
| `privacy.telemetry` | `purpose`, `allowed_fields`, `prohibited_fields`, `retention_duration` |
| `metrics` | `north_stars`, `leading`, `success`, `maturity_policies`, `reporting_policies` |
| `metrics.north_stars` | `mvp`, `end_state` |
| `metrics.north_stars.mvp`, `metrics.north_stars.end_state` | `metric_id`, `name`, `definition`, `direction`, `outcome_scope`, `maturity_policy_ref` |
| `metrics.leading.*` | `name`, `definition`, `direction`, `maturity_policy_ref` |
| `metrics.success.*` | `definition` |
| `metrics.maturity_policies.*` | `name`, `policy_version`, `owner_ref`, `approval_ref`, `metric_ref`, `applicable_autonomy_stages`, `target`, `reporting_policy_ref`, `evaluation_window`, `delivery_window`, `observation_window`, `reporting_window` |
| each metric window | `anchor_event`, `duration`, `time_zone` |
| an approved maturity target | `status`, `operator`, `value`, `unit` |
| a baseline-required maturity target | `status`, `baseline_plan`, `unit` |
| a retired maturity target | `status`, `retirement_reason`, `unit` |
| `metrics.reporting_policies.*` | `policy_version`, `owner_ref`, `approval_ref`, `calculation`, `denominator`, `inclusion_criteria`, `exclusions` |
| `guardrails.*` | `category`, `description`, `threshold`, `response` |
| `quality_assurance` | `expectations`, `golden_cases`, `evaluation_rubrics`, `release_gates` |
| `quality_assurance.expectations.*` | `expectation`, `evidence_type`, `requirement_refs` |
| `quality_assurance.golden_cases.*` | `scenario` |
| `quality_assurance.evaluation_rubrics.*` | `criterion` |
| `quality_assurance.release_gates.*` | `description` |
| `risks.*` | `description`, `severity`, `mitigation` |
| `release` | `launch_intent`, `eligible_audiences`, `deployment_target`, `requested_autonomy_stage`, `guardrail_refs`, `approval_refs`, `expectations` |
| `release.deployment_target` | `kind`, `environment`, `description` |
| `release.expectations.*` | `environment`, `expectation` |
| `observability` | `requirements` |
| `observability.requirements.*` | `requirement`, `signal`, `alert_condition` |
| `rollback` | `requirements`, `rto`, `rpo`, `data_loss_tolerance`, `customer_communication_intent` |
| `rollback.requirements.*` | `trigger`, `requirement`, `recovery_evidence` |
| `required_approvals.*` | `role`, `purpose` |
| `approvals.*` | `approval_version`, `actor_id`, `role`, `authority_policy_ref`, `authority_policy_version`, `decision`, `status`, `approved_at`, `valid_from`, `expires_at`, `subject`, `supersedes_approval_refs` |
| active approval status | `status` |
| revoked approval status | `status`, `revocation_reason`, `revoked_at` |
| superseded approval status | `status`, `superseded_by_approval_ref` |
| `approvals.*.subject` | `id`, `version`, `digest`, `digest_scope` |
| `product_decisions.*` | `decision`, `approval_ref` |
| `extensions.*` | `schema_id`, `schema_version`, `target_refs`, `effect`, `payload`, `payload_digest` |
| `extensions.*.payload` | `constraints` |
| `extensions.*.payload.constraints.*` | `target_pointer`, `operator`, `constraint_value`, `rationale` |
| `source_identity_mappings.*` | `source_id`, `source_pointer`, `canonical_pointer` |
| `unresolved_product_truth.*` | `blocking`, `question`, `reason_code`, plus `target_pointer` or `source_pointer` and `source_value` |
| `provenance` | `source_system`, `source_id`, `source_version`, `source_digest`, `published_at` |
| `provenance.compiler_provenance` | `compiler_id`, `compiler_version`, `input_digest` |

Named metric maturity policies are product-owned. Each applicable North Star
must point to a named-owner-approved, versioned policy and explicit evaluation,
delivery, observation, and reporting windows. There are no schema defaults for
targets, owners, approval references, or windows.

## Canonical manifest 1.0.0

The manifest is content-addressed. It does not contain caller-controlled archive
paths. Its fields are:

| Field | Meaning |
| --- | --- |
| `schema_id` | Exact normative manifest schema ID. |
| `schema_version` | Manifest schema version, currently `1.0.0`. |
| `manifest_id` | Logical lineage label, not content identity. |
| `manifest_version` | Manifest instance version. |
| `canonical_json_profile` | Must be `RFC8785`. |
| `created_at` | UTC RFC 3339 creation instant. |
| `bundle` | Required canonical member binding. |
| `members` | Optional attachment/extension-schema registry keyed by non-bundle member IDs. |
| `provenance` | Same required source publication fields as the bundle. |
| `approval_digest` | RFC 8785 digest of the bundle's `approvals` registry. |
| `approval_digest_scope` | Must be `CANONICAL_BUNDLE_APPROVALS_RFC8785`. |
| `manifest_digest` | RFC 8785 digest of the manifest projection without this field. |

`bundle` requires `bundle_id`, `bundle_version`, `content_digest`, `media_type`,
`member_id`, `schema_id`, and `schema_version`. Every `members` record requires
`content_digest`, `kind`, `media_type`, `schema_id`, and `schema_version`.
The bundle member ID is always `MEMBER-CANONICAL-BUNDLE` and cannot be repeated
inside `members`.

To update content, create a new immutable bundle/manifest version and recompute
the approval and content bindings. Do not edit an already registered contract or
reuse its digest as though the content were unchanged.

## Approvals and open questions

`required_approvals` defines obligations. `approvals` records actual decisions;
one does not substitute for the other. Each record names the actor, role,
versioned authority policy, decision, validity interval, status, exact subject,
subject version, digest, and digest scope. Revoked, superseded, expired,
wrong-authority, or stale-subject approvals do not satisfy a requirement.

Keep unresolved decisions in `open_questions` with a named `owner_ref` and
truthful `blocking` value. Do not place `TBD`, “engineering will decide,” or a
fabricated resolution in product-owned sections. Missing required truth,
blocking questions, or missing approvals lead to `PRODUCT_INPUT_REQUIRED`; PEOS
must return the field path, owner, rule, and requested remediation without
inventing an answer.

The [missing-approval example](../examples/pmos-contracts/invalid/missing-approval-v2-contract.json)
is an intentionally invalid V2 contract. The required `required_approvals` field
is absent, so the current compiler rejects it before adaptation with exactly
`SOURCE_SCHEMA_INVALID`. It is test data, not an authoring shortcut.

## Validate and interpret diagnostics

Install the project and development dependencies, then run the checked
documentation/example contract:

```bash
python -m pytest -q tests/unit/test_pmos_contract_documentation.py
```

For the older ProductDecisionContract CLI surface, use:

```bash
pmpe contract validate examples/v2-demo/contract.json
pmpe contract digest examples/v2-demo/contract.json
```

That CLI validates the V2 ProductDecisionContract; it is not a canonical-bundle
admission command. For supported V1/V2/V3 source payloads, the current full API
workflow is `PmosCompilationService.process(IntakeRequest(...))`: it reserves and
admits the input, calls `CanonicalCompiler`, persists compiler evidence, and
passes the result to `CanonicalContractAdmission`. It does not accept a natively
authored canonical bundle. Callers must provide configured intake, fingerprint,
evidence, authority, and validation collaborators; this guide does not invent
infrastructure or credentials.

Interpret outcomes conservatively:

| Outcome or diagnostic | Meaning and next action |
| --- | --- |
| `ENGINEERING_ADMITTED` | Structural, compiler, and deterministic semantic boundaries admit the exact evidence-bound input. |
| `PRODUCT_INPUT_REQUIRED` / `COMPILED_BLOCKED` | PMOS or the named product authority must supply or reconcile truth. No eligibility or due time is assigned. |
| `UNSUPPORTED_REPOSITORY_EXTENSION` | A repository owner must register/review the exact extension schema/version. |
| `SOURCE_SCHEMA_INVALID` | Fix the source field at the diagnostic `source_path`; do not ask PEOS to default it. |
| `SOURCE_FIELD_UNKNOWN` | Remove the unknown versioned field or publish through a reviewed extension/migration path. |
| `SOURCE_FIELD_UNMAPPED` | The compiler preserved truth in an unresolved record because no exact canonical mapping exists. |
| `REQUIRED_PRODUCT_TRUTH_ABSENT` | Supply the named canonical section and obtain required approval. |
| `UNSUPPORTED_SOURCE_VERSION` | Use a registered version or add a separately reviewed adapter/migration. |
| `AMBIGUOUS_SOURCE_FORMAT` | Supply exactly one recognized V1, V2, or V3 marker set. |

Compiler diagnostics identify `source_path` and `target_path`. Semantic
diagnostics additionally identify the rule, disposition/severity, owner, and
remediation. Retain the source/compiler/rule versions and digests with evidence;
do not paste secrets or personal data into diagnostic fields.

## Migrate V1, V2, and V3 inputs

The admitted adapter registry is explicit:

| Source | Version marker | Admitted value | Compiler rule |
| --- | --- | --- | --- |
| V1 MvpSpec | `spec_version` | string `1.0` | `PMOS-V1-1.0-TO-CANONICAL-1.0.0` |
| V2 ProductDecisionContract | `contract_version` | integer `1` | `PMOS-V2-1-TO-CANONICAL-1.0.0` |
| V3 FullStackProductContract | `contract_version` | integer `1` | `PMOS-V3-1-TO-CANONICAL-1.0.0` |

The compiler detects one format, validates its original versioned schema,
rejects unknown fields, applies the registered adapter, preserves stable source
identities, emits bundle/manifest/compiler evidence, and records every unmapped
or absent canonical section under `unresolved_product_truth`. A compilation may
therefore produce a schema-valid bundle while remaining blocked. Resolve each
diagnostic in PMOS and publish a new source attempt; do not edit compiler output
or let PEOS fabricate missing sections.

The migration registry is forward-only, pure, ordered, and versioned. A
downgrade, missing path, ambiguous path, cycle, overshoot, or failed/non-object
transform raises a migration error. Existing V1/V2/V3 inputs remain addressable;
they are not silently rewritten. The compiler evidence binds source format and
version, source digest, adapter/migration path, compiler/rule version, canonical
bundle digest, manifest digest, and diagnostics.

The [outdated-version example](../examples/pmos-contracts/invalid/outdated-v2-contract.json)
is a planted V2-shaped contract with `contract_version` set to `99`. The current
compiler selects the V2 shape but has no registered adapter for version `99`, so
it fails with exactly `UNSUPPORTED_SOURCE_VERSION` at `/contract_version` and
targets `/schema_version`. Never relabel old content as version 1 to bypass this
failure; author a reviewed migration or republish a truthful supported source.

Rollback selects a previously supported compiler/adapter registry for a new
attempt. It never downgrades or rewrites already stored canonical artifacts.

## Extensions

Extensions are typed, versioned, digest-bound additive constraints. Each entry
identifies its schema/version, exact target references, `effect`, `payload`, and
`payload_digest`. The core schema accepts only the tightening constraint shape;
extensions cannot remove required fields or weaken core truth. Semantic admission
also fails closed when the exact extension schema/version is not registered.

Use a core field whenever one exists. Publishing a new extension requires a
separate schema/policy review and repository-owner support; an arbitrary JSON
object in `extensions` is not a compatibility escape hatch.

## Security and privacy

Contracts describe security and privacy intent; they must not contain secrets,
credentials, tokens, customer records, or personal data. Use synthetic labels in
examples. `security.secret_handling` describes the required mechanism without
embedding a secret. `privacy.contract_data_policy` describes what contract
content is permitted.

Before parsing, the admitted intake boundary enforces size/content type and
secret/privacy/malware checks in bounded quarantine. Rejected raw bytes and their
ordinary digest are deletable quarantine data, not immutable evidence. Do not
use a public digest as a duplicate-input oracle. Intake failures, missing
deletion proof, or evidence-integrity failures remain security blocked under the
original opaque attempt handle.

## Observability, release, and rollback

The contract supplies intent, not operational proof. `observability` names the
required signals and alert conditions. `release` names launch intent, audience,
target environment, requested autonomy stage, referenced guardrails/approvals,
and expectations. `rollback` names triggers, requirements, recovery evidence,
RTO/RPO, data-loss tolerance, and customer-communication intent.

PEOS may compile architecture, tests, and gates from those approved obligations,
but it cannot claim that infrastructure exists, a deployment occurred,
observability works, rollback was exercised, or a human approved the result
without independent evidence. Missing owner or infrastructure input stays open
and blocked. Preserve prior-version migration notes and immutable evidence so a
documentation or compiler rollback does not erase contract history.

## Example safety notice

The canonical bundle and manifest examples are synthetic schema fixtures. Their
names, actors, policy IDs, timestamps, digests, targets, thresholds, release
intent, and approval records are demonstrations only. They authorize no real
product, customer, environment, deployment, monitoring claim, or rollback.
