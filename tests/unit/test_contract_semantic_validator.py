"""Issue #63 RED contract for canonical PMOS semantic admission.

The tests load the schema-valid issue #62 fixture, bind its approval subjects to
exact RFC 8785 digests, and then introduce one semantic defect at a time.  The
module import is deliberately deferred so this test-only commit collects and
fails because the issue #63 API is absent, rather than because of an import or
syntax error.
"""

from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from pmpe.contracts.canonical import canonical_digest
from pmpe.contracts.intake import CorrectionReference

ROOT = Path(__file__).resolve().parents[2]
VALID_BUNDLE = ROOT / "tests" / "fixtures" / "pmos" / "v1" / "valid_bundle.json"
EVALUATED_AT = "2026-07-31T00:00:00Z"
RECEIVED_AT = "2026-07-30T12:00:00Z"


def _api() -> ModuleType:
    try:
        return importlib.import_module("pmpe.validation.contracts")
    except ModuleNotFoundError:
        pytest.fail(
            "issue #63 canonical semantic validator is not implemented",
            pytrace=False,
        )


def _ready_bundle() -> dict[str, Any]:
    bundle = json.loads(VALID_BUNDLE.read_text())
    for policy in bundle["metrics"]["maturity_policies"].values():
        policy["target"] = {
            "operator": "AT_LEAST",
            "status": "APPROVED",
            "unit": "ratio",
            "value": 0.8,
        }
    for approval in bundle["approvals"].values():
        subject = approval["subject"]
        if subject["digest_scope"] == "NAMED_METRIC_MATURITY_POLICY":
            subject["digest"] = canonical_digest(
                bundle["metrics"]["maturity_policies"][subject["id"]]
            )
        elif subject["digest_scope"] == "NAMED_METRIC_REPORTING_POLICY":
            subject["digest"] = canonical_digest(
                bundle["metrics"]["reporting_policies"][subject["id"]]
            )
    for extension in bundle["extensions"].values():
        extension["payload_digest"] = canonical_digest(extension["payload"])
    projection = copy.deepcopy(bundle)
    projection.pop("approvals")
    bundle["approvals"]["APR-CONTRACT-001"]["subject"]["digest"] = canonical_digest(projection)
    return bundle


def _context(
    bundle: dict[str, Any],
    *,
    lineage_id: str = "LINEAGE-000001",
    attempt_id: str = "ATTEMPT-000001",
    correction_reference: CorrectionReference | None = None,
    possible_duplicate: bool = False,
) -> Any:
    api = _api()
    return api.ValidationContext(
        lineage_id=lineage_id,
        ingestion_attempt_id=attempt_id,
        bundle_digest=canonical_digest(bundle),
        evaluated_at=EVALUATED_AT,
        lineage_received_at=RECEIVED_AT,
        correction_reference=correction_reference,
        possible_duplicate=possible_duplicate,
    )


def _validate(bundle: dict[str, Any], **context: Any) -> Any:
    api = _api()
    return api.ContractSemanticValidator().validate(
        bundle,
        _context(bundle, **context),
    )


def _codes(result: Any) -> set[str]:
    return {item.rule_id for item in result.diagnostics}


def _reseal(bundle: dict[str, Any]) -> None:
    for approval in bundle.get("approvals", {}).values():
        subject = approval["subject"]
        if subject["digest_scope"] == "NAMED_METRIC_MATURITY_POLICY":
            policy = bundle["metrics"]["maturity_policies"].get(subject["id"])
            if policy is not None:
                subject["digest"] = canonical_digest(policy)
        elif subject["digest_scope"] == "NAMED_METRIC_REPORTING_POLICY":
            policy = bundle["metrics"]["reporting_policies"].get(subject["id"])
            if policy is not None:
                subject["digest"] = canonical_digest(policy)
    projection = copy.deepcopy(bundle)
    projection.pop("approvals", None)
    contract = bundle.get("approvals", {}).get("APR-CONTRACT-001")
    if contract is not None:
        contract["subject"]["digest"] = canonical_digest(projection)


def test_complete_exactly_approved_bundle_is_admitted() -> None:
    api = _api()
    result = _validate(_ready_bundle())
    assert result.disposition is api.Disposition.ADMITTED
    assert result.diagnostics == ()
    assert result.validator_version == "1.0.0"
    assert result.rule_set_version == "1.0.0"


@pytest.mark.parametrize(
    "section",
    [
        "product",
        "metrics",
        "scope",
        "functional_requirements",
        "acceptance_criteria",
        "ux",
        "data",
        "dependencies",
        "release",
        "rollback",
        "observability",
        "security",
        "privacy",
        "approvals",
        "required_approvals",
        "product_decisions",
    ],
)
def test_each_missing_product_truth_section_blocks_for_pm_input(section: str) -> None:
    api = _api()
    bundle = _ready_bundle()
    del bundle[section]
    result = _validate(bundle)
    assert result.disposition is api.Disposition.PRODUCT_INPUT_REQUIRED
    assert "COMP.COMPLETENESS" in _codes(result)


def test_schema_or_runtime_failure_is_error_not_product_input() -> None:
    api = _api()
    bundle = _ready_bundle()
    del bundle["bundle_id"]
    result = _validate(bundle)
    assert result.disposition is api.Disposition.ERROR
    assert "CORE.STRUCTURE" in _codes(result)


def test_stage_specific_optionality_does_not_require_production_approval_for_draft_pr() -> None:
    api = _api()
    bundle = _ready_bundle()
    assert bundle["release"]["requested_autonomy_stage"] == "DRAFT_PR"
    assert all(
        requirement.get("required_before") != "PRODUCTION"
        for requirement in bundle["required_approvals"].values()
    )
    assert _validate(bundle).disposition is api.Disposition.ADMITTED


def test_blocking_open_question_requires_product_input() -> None:
    api = _api()
    bundle = _ready_bundle()
    bundle["open_questions"]["QUESTION-001"]["blocking"] = True
    bundle["open_questions"]["QUESTION-001"].pop("resolution")
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition is api.Disposition.PRODUCT_INPUT_REQUIRED
    assert "QUESTION.UNRESOLVED" in _codes(result)
    assert result.diagnostics[0].remediation is not None


def test_compiler_unresolved_product_truth_blocks() -> None:
    api = _api()
    bundle = _ready_bundle()
    bundle["contract_status"] = "DRAFT"
    bundle["unresolved_product_truth"] = {
        "UNRESOLVED-OUTCOME": {
            "blocking": True,
            "question": "What customer outcome is approved?",
            "reason_code": "REQUIRED_PRODUCT_TRUTH_ABSENT",
            "target_pointer": "/product/outcome/customer_outcome",
        }
    }
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition is api.Disposition.PRODUCT_INPUT_REQUIRED
    assert "COMP.UNRESOLVED_PRODUCT_TRUTH" in _codes(result)


@pytest.mark.parametrize(
    ("mutation", "expected_rule"),
    [
        ("missing_requirement", "REF.REQUIREMENT"),
        ("wrong_entity", "REF.ENTITY"),
        ("wrong_acceptance", "REF.ACCEPTANCE"),
        ("missing_metric_policy", "REF.METRIC_POLICY"),
        ("missing_reporting_policy", "REF.REPORTING_POLICY"),
        ("missing_approval", "REF.APPROVAL"),
        ("missing_screen", "REF.UX"),
        ("bad_source_mapping", "REF.SOURCE_IDENTITY"),
    ],
)
def test_reference_and_identity_failures_block(mutation: str, expected_rule: str) -> None:
    api = _api()
    bundle = _ready_bundle()
    if mutation == "missing_requirement":
        bundle["acceptance_criteria"]["AC-001"]["requirement_refs"] = ["FR-MISSING"]
    elif mutation == "wrong_entity":
        bundle["functional_requirements"]["FR-001"]["entity_ref"] = "ENTITY-MISSING"
    elif mutation == "wrong_acceptance":
        bundle["functional_requirements"]["FR-001"]["acceptance_criterion_refs"] = ["AC-MISSING"]
    elif mutation == "missing_metric_policy":
        bundle["metrics"]["north_stars"]["mvp"]["maturity_policy_ref"] = "POLICY-METRIC-X"
    elif mutation == "missing_reporting_policy":
        bundle["metrics"]["maturity_policies"]["POLICY-METRIC-EADPR"]["reporting_policy_ref"] = (
            "POLICY-REPORTING-X"
        )
    elif mutation == "missing_approval":
        bundle["release"]["approval_refs"] = ["APR-MISSING"]
    elif mutation == "missing_screen":
        bundle["ux"]["primary_journey"]["JOURNEY-STEP-PUBLISH"]["screen_ref"] = "SCREEN-MISSING"
    else:
        bundle["source_identity_mappings"] = {
            "SOURCE-MAP-A": {
                "canonical_pointer": "/functional_requirements/FR-MISSING",
                "source_id": "FR-001",
                "source_pointer": "/functional_requirements/0",
            }
        }
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition is not api.Disposition.ADMITTED
    assert expected_rule in _codes(result)


@pytest.mark.parametrize(
    ("case", "expected_rule"),
    [
        ("missing", "APPROVAL.REQUIRED"),
        ("revoked", "APPROVAL.ACTIVE"),
        ("superseded", "APPROVAL.ACTIVE"),
        ("expired", "APPROVAL.FRESHNESS"),
        ("wrong_authority", "APPROVAL.AUTHORITY"),
        ("stale_subject", "APPROVAL.SUBJECT"),
    ],
)
def test_required_approval_failures_block(case: str, expected_rule: str) -> None:
    api = _api()
    bundle = _ready_bundle()
    approval = bundle["approvals"]["APR-CONTRACT-001"]
    if case == "missing":
        del bundle["approvals"]["APR-CONTRACT-001"]
    elif case == "revoked":
        approval["status"] = "REVOKED"
        approval["revoked_at"] = "2026-07-30T01:00:00Z"
        approval["revocation_reason"] = "Product decision withdrawn"
    elif case == "superseded":
        approval["status"] = "SUPERSEDED"
        approval["superseded_by_approval_ref"] = "APR-CONTRACT-NEW"
    elif case == "expired":
        approval["expires_at"] = "2026-07-30T23:59:59Z"
    elif case == "wrong_authority":
        approval["role"] = "ENGINEER"
    else:
        approval["subject"]["digest"] = "sha256:" + "0" * 64
    result = _validate(bundle)
    assert result.disposition is api.Disposition.PRODUCT_INPUT_REQUIRED
    assert expected_rule in _codes(result)


def test_approval_subject_binds_exact_bundle_version_and_id() -> None:
    bundle = _ready_bundle()
    bundle["approvals"]["APR-CONTRACT-001"]["subject"]["version"] = "2.0.0"
    result = _validate(bundle)
    assert "APPROVAL.SUBJECT" in _codes(result)


@pytest.mark.parametrize(
    ("case", "expected_rule"),
    [
        ("problem_hypothesis", "ALIGN.OUTCOME_HYPOTHESIS"),
        ("solution_non_goal", "ALIGN.SOLUTION_NON_GOAL"),
        ("metric_outcome", "ALIGN.METRIC_OUTCOME"),
        ("leading_equals_outcome", "ALIGN.LEADING_DISTINCT"),
        ("target_guardrail", "ALIGN.TARGET_GUARDRAIL"),
        ("scope_non_goal", "ALIGN.SCOPE_NON_GOAL"),
        ("undeclared_dependency", "ALIGN.DEPENDENCY"),
        ("autonomy_stage", "ALIGN.AUTONOMY"),
        ("production_without_approval", "ALIGN.RELEASE_APPROVAL"),
        ("telemetry_privacy", "ALIGN.SECURITY_PRIVACY"),
        ("ownership", "OWNERSHIP.PRODUCT_TRUTH"),
    ],
)
def test_named_contradiction_classes_block(case: str, expected_rule: str) -> None:
    api = _api()
    bundle = _ready_bundle()
    if case == "problem_hypothesis":
        bundle["product"]["hypothesis"]["statement"] = (
            "A decorative logo change will improve office catering."
        )
        bundle["product"]["hypothesis"]["falsification_condition"] = "The logo remains blue."
    elif case == "solution_non_goal":
        bundle["functional_requirements"]["FR-001"]["statement"] = bundle["scope"]["non_goals"][0]
    elif case == "metric_outcome":
        bundle["metrics"]["success"]["METRIC-SUCCESS-001"]["definition"] = (
            "Count decorative logo impressions."
        )
    elif case == "leading_equals_outcome":
        bundle["metrics"]["leading"]["METRIC-LEAD-001"]["definition"] = bundle["metrics"][
            "success"
        ]["METRIC-SUCCESS-001"]["definition"]
    elif case == "target_guardrail":
        bundle["guardrails"]["GUARD-SECURITY-001"]["threshold"] = "At most 0.5 ratio"
    elif case == "scope_non_goal":
        bundle["scope"]["non_goals"].append(bundle["scope"]["in_scope"][0])
    elif case == "undeclared_dependency":
        bundle["functional_requirements"]["FR-001"]["capability"] = "integration.stripe"
    elif case == "autonomy_stage":
        bundle["release"]["requested_autonomy_stage"] = "PRODUCTION"
        for policy in bundle["metrics"]["maturity_policies"].values():
            policy["applicable_autonomy_stages"] = ["DRAFT_PR"]
    elif case == "production_without_approval":
        bundle["release"]["requested_autonomy_stage"] = "PRODUCTION"
        bundle["required_approvals"]["APPROVAL-REQ-CONTRACT"]["required_before"] = "DRAFT_PR"
    elif case == "telemetry_privacy":
        bundle["privacy"]["telemetry"]["allowed_fields"].append("customer_records")
    else:
        bundle["product"]["outcome"]["customer_outcome"] = (
            "PEOS engineering will decide the customer outcome later."
        )
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition is api.Disposition.PRODUCT_INPUT_REQUIRED
    assert expected_rule in _codes(result)


def test_unknown_or_tampered_extension_fails_closed() -> None:
    api = _api()
    bundle = _ready_bundle()
    extension = bundle["extensions"]["EXT-REPOSITORY-001"]
    extension["schema_id"] = "https://unknown.invalid/extension.json"
    extension["payload_digest"] = canonical_digest(extension["payload"])
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition is api.Disposition.UNSUPPORTED_REPOSITORY_EXTENSION
    assert "EXTENSION.SUPPORTED" in _codes(result)


def test_extension_payload_digest_and_target_are_verified() -> None:
    api = _api()
    bundle = _ready_bundle()
    constraint = bundle["extensions"]["EXT-REPOSITORY-001"]["payload"]["constraints"][
        "EXT-CONSTRAINT-001"
    ]
    constraint["target_pointer"] = "/product/unknown"
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition is api.Disposition.UNSUPPORTED_REPOSITORY_EXTENSION
    assert "EXTENSION.CONSTRAINT" in _codes(result)


def test_advisory_model_suggestions_cannot_block_or_admit() -> None:
    api = _api()
    bundle = _ready_bundle()
    suggestion = api.AdvisorySuggestion(
        suggestion_id="MODEL-001",
        field_path="/product/hypothesis",
        explanation="Possible contradiction",
    )
    result = api.ContractSemanticValidator().validate(
        bundle,
        _context(bundle),
        advisory_suggestions=(suggestion,),
    )
    assert result.disposition is api.Disposition.ADMITTED
    assert result.advisory_suggestions == (suggestion,)


def test_validation_is_pure_repeatable_and_byte_deterministic() -> None:
    bundle = _ready_bundle()
    before = copy.deepcopy(bundle)
    first = _validate(bundle)
    second = _validate(bundle)
    assert bundle == before
    assert first.canonical_bytes() == second.canonical_bytes()


def test_rule_set_digest_and_input_binding_change_independently() -> None:
    api = _api()
    bundle = _ready_bundle()
    default = api.ContractSemanticValidator().validate(bundle, _context(bundle))
    registry = api.default_rule_registry(rule_set_version="1.0.1")
    changed_rules = api.ContractSemanticValidator(registry).validate(bundle, _context(bundle))
    assert changed_rules.rule_set_digest != default.rule_set_digest
    changed_bundle = copy.deepcopy(bundle)
    changed_bundle["assumptions"]["ASM-001"]["statement"] += " Clarified."
    _reseal(changed_bundle)
    changed_input = _validate(changed_bundle)
    assert changed_input.bundle_digest != default.bundle_digest

    mutated_evaluator = api.default_rule_registry().with_evaluator(
        "ALIGN.SCOPE_NON_GOAL", lambda _bundle, _context: ()
    )
    assert mutated_evaluator.digest != registry.digest


def test_missing_or_weakened_mandatory_rule_fails_closed() -> None:
    api = _api()
    bundle = _ready_bundle()
    missing = api.default_rule_registry().without("APPROVAL.SUBJECT")
    result = api.ContractSemanticValidator(missing).validate(bundle, _context(bundle))
    assert result.disposition is api.Disposition.ERROR
    assert "CORE.RULE_SET_INTEGRITY" in _codes(result)

    weakened = api.default_rule_registry().with_rule_metadata(
        "APPROVAL.SUBJECT", blocking=False, severity="WARNING"
    )
    result = api.ContractSemanticValidator(weakened).validate(bundle, _context(bundle))
    assert result.disposition is api.Disposition.ERROR
    assert "CORE.RULE_SET_INTEGRITY" in _codes(result)


def test_rule_exception_fails_closed_and_never_admits() -> None:
    api = _api()
    bundle = _ready_bundle()

    def explode(_bundle: Any, _context: Any) -> Any:
        raise RuntimeError("planted evaluator failure")

    registry = api.default_rule_registry().with_evaluator("ALIGN.SCOPE_NON_GOAL", explode)
    result = api.ContractSemanticValidator(registry).validate(bundle, _context(bundle))
    assert result.disposition is api.Disposition.ERROR
    assert "CORE.RULE_EVALUATION" in _codes(result)


def test_noncanonical_runtime_value_fails_closed_without_raising() -> None:
    api = _api()
    bundle = _ready_bundle()
    bundle["assumptions"]["ASM-001"]["statement"] = {"not-json"}
    context = api.ValidationContext(
        lineage_id="LINEAGE-000001",
        ingestion_attempt_id="ATTEMPT-000001",
        bundle_digest="sha256:" + "0" * 64,
        evaluated_at=EVALUATED_AT,
        lineage_received_at=RECEIVED_AT,
    )
    result = api.ContractSemanticValidator().validate(bundle, context)
    assert result.disposition is api.Disposition.ERROR
    assert "CORE.EVIDENCE_BINDING" in _codes(result)


def test_validator_never_fabricates_a_missing_product_default() -> None:
    bundle = _ready_bundle()
    del bundle["product"]
    before = copy.deepcopy(bundle)
    result = _validate(bundle)
    assert bundle == before
    assert result.disposition.value == "PRODUCT_INPUT_REQUIRED"
    assert all(
        item.remediation["recommended_technical_default"]
        == "NO_DEFAULT_ENGINEERING_MUST_NOT_INVENT_PRODUCT_TRUTH"
        for item in result.diagnostics
        if item.remediation is not None
    )


def test_unsupported_schema_or_rule_set_version_fails_closed() -> None:
    api = _api()
    bundle = _ready_bundle()
    bundle["schema_version"] = "9.0.0"
    result = _validate(bundle)
    assert result.disposition is api.Disposition.ERROR
    assert "CORE.UNSUPPORTED_VERSION" in _codes(result)


def test_context_digest_lineage_and_attempt_binding_is_mandatory() -> None:
    api = _api()
    bundle = _ready_bundle()
    context = api.ValidationContext(
        lineage_id="LINEAGE-000001",
        ingestion_attempt_id="ATTEMPT-000001",
        bundle_digest="sha256:" + "0" * 64,
        evaluated_at=EVALUATED_AT,
        lineage_received_at=RECEIVED_AT,
    )
    result = api.ContractSemanticValidator().validate(bundle, context)
    assert result.disposition is api.Disposition.ERROR
    assert "CORE.EVIDENCE_BINDING" in _codes(result)


def test_correction_lineage_mismatch_blocks() -> None:
    api = _api()
    bundle = _ready_bundle()
    result = _validate(
        bundle,
        lineage_id="LINEAGE-000002",
        attempt_id="ATTEMPT-000002",
        correction_reference=CorrectionReference(
            lineage_id="LINEAGE-000001",
            attempt_id="ATTEMPT-000001",
        ),
    )
    assert result.disposition is api.Disposition.ERROR
    assert "LINEAGE.CORRECTION_BINDING" in _codes(result)


def test_possible_duplicate_is_visible_but_does_not_coalesce_lineage() -> None:
    api = _api()
    bundle = _ready_bundle()
    result = _validate(
        bundle,
        lineage_id="LINEAGE-000002",
        attempt_id="ATTEMPT-000002",
        possible_duplicate=True,
    )
    assert result.disposition is api.Disposition.WARNING
    assert "LINEAGE.POSSIBLE_DUPLICATE" in _codes(result)


def test_pending_policy_has_no_eligibility_or_due_time() -> None:
    api = _api()
    bundle = _ready_bundle()
    policy = bundle["metrics"]["maturity_policies"]["POLICY-METRIC-EADPR"]
    policy["target"] = {
        "baseline_plan": "Approve after the first prospective cohort.",
        "status": "BASELINE_REQUIRED",
        "unit": "ratio",
    }
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition is api.Disposition.PRODUCT_INPUT_REQUIRED
    evidence = result.metric_eligibility["POLICY-METRIC-EADPR"]
    assert evidence["eligible_at"] is None
    assert evidence["due_at"] is None


@pytest.mark.parametrize(
    ("section", "record", "field"),
    [
        ("maturity_policies", "POLICY-METRIC-EADPR", "target"),
        ("maturity_policies", "POLICY-METRIC-EADPR", "delivery_window"),
        ("maturity_policies", "POLICY-METRIC-EADPR", "reporting_window"),
        ("reporting_policies", "POLICY-REPORTING-MVP", "denominator"),
        ("reporting_policies", "POLICY-REPORTING-MVP", "calculation"),
    ],
)
def test_missing_metric_target_window_or_denominator_requires_product_input(
    section: str,
    record: str,
    field: str,
) -> None:
    api = _api()
    bundle = _ready_bundle()
    del bundle["metrics"][section][record][field]
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition is api.Disposition.PRODUCT_INPUT_REQUIRED
    assert "COMP.COMPLETENESS" in _codes(result)


def test_invalid_semantic_field_type_is_a_structural_error() -> None:
    api = _api()
    bundle = _ready_bundle()
    bundle["metrics"]["success"] = ["not", "a", "registry"]
    result = _validate(bundle)
    assert result.disposition is api.Disposition.ERROR
    assert "CORE.STRUCTURE" in _codes(result)


@pytest.mark.parametrize(
    ("case", "expected_rule"),
    [
        ("ux_api", "ALIGN.CROSS_CHANNEL"),
        ("release_rollback", "ALIGN.RELEASE_ROLLBACK"),
        ("observability_privacy", "ALIGN.OBSERVABILITY_REPORTING"),
    ],
)
def test_cross_section_contradictions_block(case: str, expected_rule: str) -> None:
    api = _api()
    bundle = _ready_bundle()
    if case == "ux_api":
        bundle["ux"]["user_stories"]["US-001"]["i_want"] = "must retain customer records"
        bundle["data"]["requirements"]["DATA-001"]["requirement"] = (
            "must not retain customer records"
        )
    elif case == "release_rollback":
        bundle["release"]["requested_autonomy_stage"] = "PRODUCTION"
        bundle["rollback"]["data_loss_tolerance"] = "No data loss"
        bundle["rollback"]["rpo"] = "P1D"
        bundle["required_approvals"]["APPROVAL-REQ-PRODUCTION"] = {
            "purpose": "Approve production promotion",
            "required_before": "PRODUCTION",
            "role": "PRODUCT_OWNER",
        }
    else:
        bundle["observability"]["requirements"]["OBS-001"]["signal"] = "customer_records"
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition is api.Disposition.PRODUCT_INPUT_REQUIRED
    assert expected_rule in _codes(result)


def test_retrospective_policy_approval_never_backdates_eligibility() -> None:
    bundle = _ready_bundle()
    approval = bundle["approvals"]["APR-METRIC-EADPR"]
    approval["approved_at"] = "2026-07-30T18:00:00Z"
    approval["valid_from"] = "2026-07-30T18:00:00Z"
    _reseal(bundle)
    result = _validate(bundle)
    evidence = result.metric_eligibility["POLICY-METRIC-EADPR"]
    assert evidence["eligible_at"] == "2026-07-30T18:00:00Z"
    assert evidence["eligible_at"] != RECEIVED_AT


def test_secret_values_never_appear_in_diagnostics_or_advisories() -> None:
    api = _api()
    secret = "ghp_0123456789abcdefghijklmnop"
    bundle = _ready_bundle()
    bundle["product"]["outcome"]["customer_outcome"] = f"Engineering decides {secret}"
    _reseal(bundle)
    result = api.ContractSemanticValidator().validate(
        bundle,
        _context(bundle),
        advisory_suggestions=(
            api.AdvisorySuggestion(
                suggestion_id="MODEL-SECRET",
                field_path="/product/outcome/customer_outcome",
                explanation=f"Possible concern: {secret}",
            ),
        ),
    )
    assert secret not in result.canonical_bytes().decode()


def test_diagnostic_contract_is_machine_readable_and_pm_actionable() -> None:
    bundle = _ready_bundle()
    del bundle["product"]
    diagnostic = _validate(bundle).diagnostics[0]
    payload = diagnostic.as_dict()
    assert set(payload) == {
        "category",
        "disposition",
        "explanation",
        "field_path",
        "ingestion_attempt_id",
        "input_digest",
        "lineage_id",
        "next_action",
        "owner",
        "relationship",
        "remediation",
        "rule_id",
        "rule_set_digest",
        "rule_version",
        "severity",
    }
    assert payload["owner"] == "PMOS"
    assert payload["remediation"]["status"] == "OPEN"
