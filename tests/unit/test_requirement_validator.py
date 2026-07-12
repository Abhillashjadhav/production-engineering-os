"""SYS-03/SYS-04: semantic validation — contradictions, testability, NSM quality."""

from __future__ import annotations

from typing import Any

import pytest

from pmpe.domain.models import IssueKind
from pmpe.ingestion.normalizer import normalize_spec
from pmpe.validation.validator import RequirementValidator
from tests.conftest import (
    mutate_activity_nsm,
    mutate_contradictory,
    mutate_missing_entity,
    mutate_production_target,
    mutate_unknown_requirement_ac,
    mutate_vague_ac,
)


@pytest.fixture()
def validator() -> RequirementValidator:
    return RequirementValidator()


def _report(validator: RequirementValidator, data: dict[str, Any]):  # noqa: ANN202
    return validator.validate(normalize_spec(data))


def test_golden_spec_passes_clean(
    validator: RequirementValidator, golden_spec_dict: dict[str, Any]
) -> None:
    report = _report(validator, golden_spec_dict)
    assert report.ok, [i.message for i in report.errors]
    assert report.questions == []


def test_scope_non_goal_contradiction_is_a_blocking_error(
    validator: RequirementValidator, golden_spec_dict: dict[str, Any]
) -> None:
    mutate_contradictory(golden_spec_dict)
    report = _report(validator, golden_spec_dict)
    assert not report.ok
    assert any(i.code == "CONTRADICTION" for i in report.errors)
    assert any("Bulk task import" in i.message for i in report.errors)


def test_activity_only_nsm_is_flagged_as_question(
    validator: RequirementValidator, golden_spec_dict: dict[str, Any]
) -> None:
    mutate_activity_nsm(golden_spec_dict)
    report = _report(validator, golden_spec_dict)
    assert any(i.code == "NSM_ACTIVITY_ONLY" for i in report.questions)


def test_outcome_nsm_is_not_flagged(
    validator: RequirementValidator, golden_spec_dict: dict[str, Any]
) -> None:
    report = _report(validator, golden_spec_dict)
    assert not any(i.code == "NSM_ACTIVITY_ONLY" for i in report.questions)


def test_vague_acceptance_criterion_is_flagged(
    validator: RequirementValidator, golden_spec_dict: dict[str, Any]
) -> None:
    mutate_vague_ac(golden_spec_dict)
    report = _report(validator, golden_spec_dict)
    flagged = [i for i in report.questions if i.code == "AC_UNTESTABLE"]
    assert flagged and any("AC-VAGUE" in i.message for i in flagged)


def test_ac_referencing_unknown_requirement_is_an_error(
    validator: RequirementValidator, golden_spec_dict: dict[str, Any]
) -> None:
    mutate_unknown_requirement_ac(golden_spec_dict)
    report = _report(validator, golden_spec_dict)
    assert any(i.code == "AC_UNKNOWN_REQUIREMENT" for i in report.errors)


def test_requirement_without_acceptance_criteria_is_an_error(
    validator: RequirementValidator, golden_spec_dict: dict[str, Any]
) -> None:
    golden_spec_dict["acceptance_criteria"] = [
        ac for ac in golden_spec_dict["acceptance_criteria"] if ac["requirement"] != "FR-006"
    ]
    report = _report(validator, golden_spec_dict)
    assert any(i.code == "FR_WITHOUT_AC" and "FR-006" in i.message for i in report.errors)


def test_entity_capability_without_declared_entity_is_an_error(
    validator: RequirementValidator, golden_spec_dict: dict[str, Any]
) -> None:
    mutate_missing_entity(golden_spec_dict)
    report = _report(validator, golden_spec_dict)
    assert any(i.code == "MISSING_ENTITY" and "Project" in i.message for i in report.errors)


def test_undeclared_external_dependency_is_a_warning(
    validator: RequirementValidator, golden_spec_dict: dict[str, Any]
) -> None:
    golden_spec_dict["functional_requirements"][1]["description"] = (
        "POST /tasks stores the task in Postgres."
    )
    report = _report(validator, golden_spec_dict)
    assert any(i.code == "MISSING_DEPENDENCY" for i in report.warnings)


def test_production_deployment_target_raises_question(
    validator: RequirementValidator, golden_spec_dict: dict[str, Any]
) -> None:
    mutate_production_target(golden_spec_dict)
    report = _report(validator, golden_spec_dict)
    assert any(i.code == "UNSUPPORTED_DEPLOYMENT" for i in report.questions)


def test_missing_recommended_fields_warn(
    validator: RequirementValidator, golden_spec_dict: dict[str, Any]
) -> None:
    del golden_spec_dict["success_metrics"]
    del golden_spec_dict["risks"]
    report = _report(validator, golden_spec_dict)
    warned = {i.code for i in report.warnings}
    assert "MISSING_RECOMMENDED" in warned
    assert report.ok  # warnings never block


def test_malicious_field_name_is_rejected(
    validator: RequirementValidator, golden_spec_dict: dict[str, Any]
) -> None:
    """Entity/field names become SQL identifiers in generated code — injection guard."""
    golden_spec_dict["entities"][0]["fields"].append(
        {"name": "notes TEXT; DROP TABLE tasks; --", "type": "string"}
    )
    report = _report(validator, golden_spec_dict)
    assert any(i.code == "INVALID_IDENTIFIER" for i in report.errors)


def test_reserved_field_name_is_rejected(
    validator: RequirementValidator, golden_spec_dict: dict[str, Any]
) -> None:
    golden_spec_dict["entities"][0]["fields"].append({"name": "id", "type": "int"})
    report = _report(validator, golden_spec_dict)
    assert any(i.code == "INVALID_IDENTIFIER" and "reserved" in i.message for i in report.errors)


def test_entity_capabilities_without_create_are_rejected(
    validator: RequirementValidator, golden_spec_dict: dict[str, Any]
) -> None:
    """V1 tests entities through create; list/read/update/delete alone are unverifiable."""
    golden_spec_dict["functional_requirements"] = [
        fr for fr in golden_spec_dict["functional_requirements"] if fr["id"] != "FR-002"
    ]
    golden_spec_dict["acceptance_criteria"] = [
        ac for ac in golden_spec_dict["acceptance_criteria"] if ac["requirement"] != "FR-002"
    ]
    report = _report(validator, golden_spec_dict)
    assert any(i.code == "CAPABILITY_DEPENDENCY" for i in report.errors)


def test_requirement_id_grammar_is_enforced(
    validator: RequirementValidator, golden_spec_dict: dict[str, Any]
) -> None:
    """FR ids key traceability and Covers: markers — 'fr1' would dead-end the merge gate."""
    golden_spec_dict["functional_requirements"][0]["id"] = "fr1"
    for ac in golden_spec_dict["acceptance_criteria"]:
        if ac["requirement"] == "FR-001":
            ac["requirement"] = "fr1"
    report = _report(validator, golden_spec_dict)
    assert any(i.code == "REQUIREMENT_ID_FORMAT" for i in report.errors)


def test_missing_health_check_is_a_warning_only(
    validator: RequirementValidator, golden_spec_dict: dict[str, Any]
) -> None:
    golden_spec_dict["functional_requirements"] = [
        fr for fr in golden_spec_dict["functional_requirements"] if fr["id"] != "FR-007"
    ]
    golden_spec_dict["acceptance_criteria"] = [
        ac for ac in golden_spec_dict["acceptance_criteria"] if ac["requirement"] != "FR-007"
    ]
    report = _report(validator, golden_spec_dict)
    assert any(i.code == "MISSING_HEALTH_CHECK" for i in report.warnings)
    assert report.ok  # deployable, with TCP-readiness fallback


def test_issue_kinds_are_typed(
    validator: RequirementValidator, golden_spec_dict: dict[str, Any]
) -> None:
    mutate_contradictory(golden_spec_dict)
    report = _report(validator, golden_spec_dict)
    assert all(i.kind is IssueKind.ERROR for i in report.errors)
