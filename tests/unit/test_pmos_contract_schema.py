"""Issue #62: canonical PMOS contract-bundle and manifest schemas.

These tests intentionally exercise schema artifacts only. Runtime model,
compiler, migration, and semantic cross-reference validation belong to later
issues. The official Draft 2020-12 validator checks parsed instances. A separate
loader rejects duplicate keys, unpaired Unicode surrogates, Unicode
noncharacters, and inadmissible numeric tokens before validation; the
compiler/admission work in #76 remains responsible for general RFC 8785
canonicalization and digesting because JSON Schema operates on parsed instances.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from decimal import Decimal
from pathlib import Path
from typing import Any, NoReturn

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "schemas"
PACKAGED_SCHEMA_DIR = ROOT / "src" / "pmpe" / "schemas"
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "pmos" / "v1"

BUNDLE_SCHEMA = SCHEMA_DIR / "pmos_contract_bundle.schema.json"
MANIFEST_SCHEMA = SCHEMA_DIR / "pmos_contract_manifest.schema.json"
VALID_BUNDLE = FIXTURE_DIR / "valid_bundle.json"
VALID_MANIFEST = FIXTURE_DIR / "valid_manifest.json"
LEGACY_V1 = ROOT / "tests" / "fixtures" / "minimal_valid_spec.json"
LEGACY_V2 = ROOT / "tests" / "fixtures" / "v2" / "contract_approved.json"
LEGACY_V3 = ROOT / "tests" / "fixtures" / "v3" / "fullstack_contract_approved.json"
MAX_INTEROPERABLE_INTEGER = 2**53 - 1

_VALIDATION_KEYWORDS = {
    "$ref",
    "additionalProperties",
    "const",
    "enum",
    "items",
    "maxProperties",
    "minItems",
    "minLength",
    "minProperties",
    "pattern",
    "properties",
    "propertyNames",
    "required",
    "type",
    "uniqueItems",
    "oneOf",
}
_ANNOTATION_KEYWORDS = {
    "$comment",
    "$defs",
    "$id",
    "$schema",
    "description",
    "format",
    "title",
}


class DuplicateKeyError(ValueError):
    """Raised when input is not canonical JSON because an object key repeats."""


class NonJsonNumericConstantError(ValueError):
    """Raised when a numeric token cannot enter the RFC 8785 admission path."""


class InvalidUnicodeScalarError(ValueError):
    """Raised when input contains a code point RFC 8785 cannot serialize."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate object key: {key}")
        result[key] = value
    return result


def _reject_non_json_numeric_constant(value: str) -> NoReturn:
    raise NonJsonNumericConstantError(f"non-JSON numeric constant: {value}")


def _parse_finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise NonJsonNumericConstantError(f"non-finite numeric value: {value}")
    exact = Decimal(value)
    if exact == exact.to_integral_value() and abs(exact) > MAX_INTEROPERABLE_INTEGER:
        raise NonJsonNumericConstantError(
            f"integer-valued numeric token outside interoperable IEEE-754 range: {value}"
        )
    return parsed


def _parse_interoperable_int(value: str) -> int:
    parsed = int(value)
    if abs(parsed) > MAX_INTEROPERABLE_INTEGER:
        raise NonJsonNumericConstantError(
            f"integer-valued numeric token outside interoperable IEEE-754 range: {value}"
        )
    return parsed


def _admit_unicode_scalars(value: Any) -> Any:
    if isinstance(value, str):
        try:
            normalized = value.encode("utf-16-le", "surrogatepass").decode("utf-16-le")
        except UnicodeDecodeError as exc:
            raise InvalidUnicodeScalarError("unpaired Unicode surrogate code point") from exc
        if any(
            0xFDD0 <= ord(character) <= 0xFDEF or ord(character) & 0xFFFF in {0xFFFE, 0xFFFF}
            for character in normalized
        ):
            raise InvalidUnicodeScalarError("Unicode noncharacter code point")
        return normalized
    if isinstance(value, dict):
        normalized_object: dict[str, Any] = {}
        for key, child in value.items():
            normalized_key = _admit_unicode_scalars(key)
            if normalized_key in normalized_object:
                raise DuplicateKeyError(
                    f"duplicate object key after Unicode scalar normalization: {normalized_key}"
                )
            normalized_object[normalized_key] = _admit_unicode_scalars(child)
        return normalized_object
    if isinstance(value, list):
        return [_admit_unicode_scalars(child) for child in value]
    return value


def _load_json(path: Path) -> Any:
    value = json.loads(
        path.read_text(),
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=_reject_non_json_numeric_constant,
        parse_float=_parse_finite_float,
        parse_int=_parse_interoperable_int,
    )
    return _admit_unicode_scalars(value)


def _rfc8785_fixture_bytes(value: Any) -> bytes:
    """Serialize the fixture-domain subset exactly as RFC 8785 requires.

    The fixtures intentionally use ASCII object keys, safe integers, and no
    floating-point values. Within that domain, Python's compact sorted JSON
    serialization is byte-identical to RFC 8785; issue #76 owns the general
    ECMAScript-number and UTF-16-key-order implementation.
    """

    if isinstance(value, float):
        raise AssertionError("fixture digest helper does not admit floating-point values")
    if isinstance(value, dict):
        if any(not key.isascii() for key in value):
            raise AssertionError("fixture digest helper requires ASCII object keys")
        for child in value.values():
            _rfc8785_fixture_bytes(child)
    elif isinstance(value, list):
        for child in value:
            _rfc8785_fixture_bytes(child)
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _fixture_instance(path: Path) -> Any:
    """Load a fixture or apply its explicit one-defect mutation to a valid base."""

    fixture = _load_json(path)
    if not isinstance(fixture, dict) or "$fixture_base" not in fixture:
        return fixture

    base = copy.deepcopy(_load_json(FIXTURE_DIR / fixture["$fixture_base"]))
    for mutation in fixture["$mutations"]:
        parent = base
        parts = mutation["path"]
        for part in parts[:-1]:
            parent = parent[part]
        if mutation["op"] == "remove":
            del parent[parts[-1]]
        elif mutation["op"] == "replace":
            parent[parts[-1]] = mutation["value"]
        else:
            raise AssertionError(f"unsupported fixture mutation: {mutation['op']}")
    return base


def _validate_fixture(fixture: Path, schema_path: Path) -> list[str]:
    try:
        instance = _fixture_instance(fixture)
    except (
        json.JSONDecodeError,
        DuplicateKeyError,
        InvalidUnicodeScalarError,
        NonJsonNumericConstantError,
    ) as exc:
        return [str(exc)]
    schema = _load_json(schema_path)
    assert isinstance(schema, dict)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)

    def flatten(error: Any) -> list[Any]:
        return [error, *(nested for child in error.context for nested in flatten(child))]

    return [
        f"{error.json_path}: {error.message}"
        for error in sorted(
            (
                nested
                for top_level in validator.iter_errors(instance)
                for nested in flatten(top_level)
            ),
            key=lambda item: item.json_path,
        )
    ]


def _schema_keywords(node: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            found.add(key)
            if key in {"properties", "$defs"}:
                if isinstance(value, dict):
                    for child in value.values():
                        found |= _schema_keywords(child)
            else:
                found |= _schema_keywords(value)
    elif isinstance(node, list):
        for item in node:
            found |= _schema_keywords(item)
    return found


@pytest.mark.parametrize("schema_path", [BUNDLE_SCHEMA, MANIFEST_SCHEMA])
def test_schema_is_canonical_json_and_uses_a_covered_vocabulary(schema_path: Path) -> None:
    schema = _load_json(schema_path)
    rendered = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    assert schema_path.read_text() == rendered

    unsupported = _schema_keywords(schema) - _VALIDATION_KEYWORDS - _ANNOTATION_KEYWORDS
    assert unsupported == set()


@pytest.mark.parametrize("schema_path", [BUNDLE_SCHEMA, MANIFEST_SCHEMA])
def test_packaged_schema_copy_is_byte_identical(schema_path: Path) -> None:
    assert (PACKAGED_SCHEMA_DIR / schema_path.name).read_bytes() == schema_path.read_bytes()


def test_valid_canonical_bundle_passes() -> None:
    assert _validate_fixture(VALID_BUNDLE, BUNDLE_SCHEMA) == []


def test_valid_canonical_manifest_passes() -> None:
    assert _validate_fixture(VALID_MANIFEST, MANIFEST_SCHEMA) == []


@pytest.mark.parametrize("fixture_path", [VALID_BUNDLE, VALID_MANIFEST])
def test_valid_fixtures_are_canonical_json(fixture_path: Path) -> None:
    fixture = _load_json(fixture_path)
    assert fixture_path.read_text() == json.dumps(fixture, indent=2, sort_keys=True) + "\n"


@pytest.mark.parametrize(
    ("fixture_name", "schema_path", "expected"),
    [
        ("missing_security.json", BUNDLE_SCHEMA, "'security' is a required property"),
        ("unknown_schema_version.json", BUNDLE_SCHEMA, "'2.0.0' is not one of"),
        ("invalid_reference.json", BUNDLE_SCHEMA, "does not match"),
        ("wrong_reference_type.json", BUNDLE_SCHEMA, "does not match"),
        ("duplicate_namespace_collision.json", BUNDLE_SCHEMA, "does not match"),
        ("weakening_extension.json", BUNDLE_SCHEMA, "'ADD_CONSTRAINTS_ONLY' was expected"),
        ("weakening_extension_payload.json", BUNDLE_SCHEMA, "Additional properties"),
        ("invalid_timestamp.json", BUNDLE_SCHEMA, "does not match"),
        ("invalid_uri.json", BUNDLE_SCHEMA, "does not match"),
        ("invalid_timezone.json", BUNDLE_SCHEMA, "does not match"),
        ("invalid_duration.json", BUNDLE_SCHEMA, "does not match"),
        ("invalid_duration_dangling_day_time.json", BUNDLE_SCHEMA, "does not match"),
        ("invalid_duration_mixed_week.json", BUNDLE_SCHEMA, "does not match"),
        (
            "invalid_approval_digest_scope.json",
            MANIFEST_SCHEMA,
            "'CANONICAL_BUNDLE_APPROVALS_RFC8785' was expected",
        ),
        (
            "invalid_manifest_reference.json",
            MANIFEST_SCHEMA,
            "'MEMBER-CANONICAL-BUNDLE' was expected",
        ),
        ("invalid_manifest_device_path.json", MANIFEST_SCHEMA, "Additional properties"),
        ("invalid_manifest_parent_path.json", MANIFEST_SCHEMA, "Additional properties"),
        (
            "invalid_manifest_trailing_period_path.json",
            MANIFEST_SCHEMA,
            "Additional properties",
        ),
        ("invalid_manifest_unc_path.json", MANIFEST_SCHEMA, "Additional properties"),
        (
            "invalid_manifest_windows_drive_path.json",
            MANIFEST_SCHEMA,
            "Additional properties",
        ),
        (
            "invalid_manifest_windows_traversal_path.json",
            MANIFEST_SCHEMA,
            "Additional properties",
        ),
        ("duplicate_manifest_member_id.json", MANIFEST_SCHEMA, "does not match"),
        ("invalid_trailing_newline_bundle_id.json", BUNDLE_SCHEMA, "does not match"),
        ("invalid_trailing_newline_digest.json", BUNDLE_SCHEMA, "does not match"),
        ("invalid_trailing_newline_duration.json", BUNDLE_SCHEMA, "does not match"),
        (
            "invalid_trailing_newline_manifest_path.json",
            MANIFEST_SCHEMA,
            "Additional properties",
        ),
        ("invalid_trailing_newline_uri.json", BUNDLE_SCHEMA, "does not match"),
        (
            "invalid_exponent_overflow.json",
            BUNDLE_SCHEMA,
            "non-finite numeric value: 1e999",
        ),
        (
            "invalid_integer_outside_ieee754_range.json",
            BUNDLE_SCHEMA,
            "integer-valued numeric token outside interoperable IEEE-754 range: 9007199254740992",
        ),
        (
            "invalid_integral_float_outside_ieee754_range.json",
            BUNDLE_SCHEMA,
            "integer-valued numeric token outside interoperable IEEE-754 range: 9007199254740993.0",
        ),
        (
            "invalid_integral_scientific_outside_ieee754_range.json",
            BUNDLE_SCHEMA,
            "integer-valued numeric token outside interoperable IEEE-754 range: "
            "9.007199254740993e15",
        ),
        (
            "invalid_lone_surrogate.json",
            BUNDLE_SCHEMA,
            "unpaired Unicode surrogate code point",
        ),
        ("invalid_leading_metric_id_property.json", BUNDLE_SCHEMA, "Additional properties"),
        ("invalid_leading_north_star_collision.json", BUNDLE_SCHEMA, "does not match"),
        ("invalid_metric_ref_namespace.json", BUNDLE_SCHEMA, "not valid under any"),
        ("invalid_north_star_namespace_collision.json", BUNDLE_SCHEMA, "does not match"),
        (
            "missing_manifest_digest.json",
            MANIFEST_SCHEMA,
            "'manifest_digest' is a required property",
        ),
        ("missing_api_contracts.json", BUNDLE_SCHEMA, "'api_contracts' is a required property"),
        (
            "missing_backend_capabilities.json",
            BUNDLE_SCHEMA,
            "'backend_capabilities' is a required property",
        ),
        ("missing_data_entities.json", BUNDLE_SCHEMA, "'entities' is a required property"),
        ("missing_dependencies.json", BUNDLE_SCHEMA, "'dependencies' is a required property"),
        (
            "missing_evaluation_rubrics.json",
            BUNDLE_SCHEMA,
            "'evaluation_rubrics' is a required property",
        ),
        ("missing_metric_target.json", BUNDLE_SCHEMA, "'target' is a required property"),
        ("baseline_target_with_dummy_value.json", BUNDLE_SCHEMA, "not valid under any"),
        ("approved_target_with_baseline_plan.json", BUNDLE_SCHEMA, "not valid under any"),
        (
            "baseline_target_with_retirement_reason.json",
            BUNDLE_SCHEMA,
            "not valid under any",
        ),
        ("retired_target_with_baseline_plan.json", BUNDLE_SCHEMA, "not valid under any"),
        (
            "missing_metric_reporting_policy.json",
            BUNDLE_SCHEMA,
            "'reporting_policy_ref' is a required property",
        ),
        ("missing_mvp_north_star.json", BUNDLE_SCHEMA, "'mvp' is a required property"),
        ("active_approval_with_revocation.json", BUNDLE_SCHEMA, "not valid under any"),
        ("invalid_approval_subject_type.json", BUNDLE_SCHEMA, "not valid under any"),
        ("revoked_approval_without_evidence.json", BUNDLE_SCHEMA, "not valid under any"),
        ("superseded_approval_without_evidence.json", BUNDLE_SCHEMA, "not valid under any"),
        ("missing_privacy_telemetry.json", BUNDLE_SCHEMA, "'telemetry' is a required property"),
        (
            "missing_deployment_target.json",
            BUNDLE_SCHEMA,
            "'deployment_target' is a required property",
        ),
        (
            "missing_business_outcome.json",
            BUNDLE_SCHEMA,
            "'business_outcome' is a required property",
        ),
        (
            "missing_customer_outcome.json",
            BUNDLE_SCHEMA,
            "'customer_outcome' is a required property",
        ),
        ("missing_product_name.json", BUNDLE_SCHEMA, "'product_name' is a required property"),
        ("missing_product_priority.json", BUNDLE_SCHEMA, "'priority' is a required property"),
        (
            "missing_primary_journey.json",
            BUNDLE_SCHEMA,
            "'primary_journey' is a required property",
        ),
        (
            "missing_product_decisions.json",
            BUNDLE_SCHEMA,
            "'product_decisions' is a required property",
        ),
        (
            "missing_reporting_policies.json",
            BUNDLE_SCHEMA,
            "'reporting_policies' is a required property",
        ),
        ("missing_success_metrics.json", BUNDLE_SCHEMA, "'success' is a required property"),
        (
            "missing_source_identity_mappings.json",
            BUNDLE_SCHEMA,
            "'source_identity_mappings' is a required property",
        ),
        (
            "missing_required_approvals.json",
            BUNDLE_SCHEMA,
            "'required_approvals' is a required property",
        ),
        (
            "missing_target_platform.json",
            BUNDLE_SCHEMA,
            "'target_platform' is a required property",
        ),
        (
            "missing_ux_user_stories.json",
            BUNDLE_SCHEMA,
            "'user_stories' is a required property",
        ),
        ("missing_release_intent.json", BUNDLE_SCHEMA, "'launch_intent' is a required property"),
        ("missing_rollback_rto.json", BUNDLE_SCHEMA, "'rto' is a required property"),
        ("missing_approval_expiry.json", BUNDLE_SCHEMA, "'expires_at' is a required property"),
    ],
)
def test_invalid_fixtures_fail_closed(
    fixture_name: str,
    schema_path: Path,
    expected: str,
) -> None:
    errors = _validate_fixture(FIXTURE_DIR / fixture_name, schema_path)
    assert errors
    assert any(expected in error for error in errors), errors


def test_duplicate_object_members_fail_before_schema_validation() -> None:
    """RFC 8785/I-JSON duplicate rejection is a transport gate, not a schema claim."""

    duplicate_fixture = FIXTURE_DIR / "duplicate_requirement_id.json"
    with pytest.raises(DuplicateKeyError, match="duplicate object key: FR-001"):
        _fixture_instance(duplicate_fixture)


def test_non_json_numeric_constants_fail_before_schema_validation() -> None:
    fixture = FIXTURE_DIR / "invalid_non_finite_number.json"
    with pytest.raises(
        NonJsonNumericConstantError,
        match="non-JSON numeric constant: NaN",
    ):
        _fixture_instance(fixture)


def test_numeric_exponent_overflow_fails_before_schema_validation() -> None:
    fixture = FIXTURE_DIR / "invalid_exponent_overflow.json"
    with pytest.raises(
        NonJsonNumericConstantError,
        match="non-finite numeric value: 1e999",
    ):
        _fixture_instance(fixture)


def test_integer_outside_interoperable_range_fails_before_schema_validation() -> None:
    fixture = FIXTURE_DIR / "invalid_integer_outside_ieee754_range.json"
    with pytest.raises(
        NonJsonNumericConstantError,
        match=(
            "integer-valued numeric token outside interoperable IEEE-754 range: 9007199254740992"
        ),
    ):
        _fixture_instance(fixture)


@pytest.mark.parametrize(
    ("fixture_name", "token"),
    [
        ("invalid_integral_float_outside_ieee754_range.json", "9007199254740993.0"),
        (
            "invalid_integral_scientific_outside_ieee754_range.json",
            "9.007199254740993e15",
        ),
    ],
)
def test_integral_float_outside_interoperable_range_fails_before_schema_validation(
    fixture_name: str,
    token: str,
) -> None:
    with pytest.raises(
        NonJsonNumericConstantError,
        match=f"integer-valued numeric token outside interoperable IEEE-754 range: {token}",
    ):
        _fixture_instance(FIXTURE_DIR / fixture_name)


def test_unpaired_unicode_surrogate_fails_before_schema_validation() -> None:
    fixture = FIXTURE_DIR / "invalid_lone_surrogate.json"
    with pytest.raises(
        InvalidUnicodeScalarError,
        match="unpaired Unicode surrogate code point",
    ):
        _fixture_instance(fixture)


@pytest.mark.parametrize(
    "fixture_name",
    [
        "invalid_bmp_noncharacter.json",
        "invalid_supplementary_noncharacter.json",
    ],
)
def test_unicode_noncharacter_fails_before_schema_validation(
    fixture_name: str,
) -> None:
    with pytest.raises(
        InvalidUnicodeScalarError,
        match="Unicode noncharacter code point",
    ):
        _fixture_instance(FIXTURE_DIR / fixture_name)


def test_paired_unicode_surrogate_is_admitted_as_scalar() -> None:
    instance = _fixture_instance(FIXTURE_DIR / "valid_paired_surrogate.json")
    assert instance["product"]["product_name"] == "\U0001d11e"
    schema = _load_json(BUNDLE_SCHEMA)
    assert list(Draft202012Validator(schema).iter_errors(instance)) == []


@pytest.mark.parametrize(
    ("schema_path", "fixture_path"),
    [(BUNDLE_SCHEMA, VALID_BUNDLE), (MANIFEST_SCHEMA, VALID_MANIFEST)],
)
def test_schema_declares_duplicate_aware_rfc8785_admission(
    schema_path: Path,
    fixture_path: Path,
) -> None:
    schema = _load_json(schema_path)
    fixture = _load_json(fixture_path)
    assert schema["properties"]["canonical_json_profile"]["const"] == "RFC8785"
    assert "duplicate object member names" in schema["$comment"]
    assert "unpaired Unicode surrogate code points" in schema["$comment"]
    assert "Unicode noncharacter code points" in schema["$comment"]
    assert fixture["canonical_json_profile"] == "RFC8785"


def test_bundle_schema_covers_every_phase_zero_product_truth_section() -> None:
    schema = _load_json(BUNDLE_SCHEMA)
    assert isinstance(schema, dict)
    complete_branch = next(
        branch
        for branch in schema["oneOf"]
        if branch["properties"]["unresolved_product_truth"].get("maxProperties") == 0
    )
    required = set(complete_branch["required"])
    assert {
        "acceptance_criteria",
        "api_contracts",
        "approvals",
        "assumptions",
        "backend_capabilities",
        "bundle_id",
        "bundle_version",
        "canonical_json_profile",
        "contract_status",
        "data",
        "dependencies",
        "extensions",
        "functional_requirements",
        "guardrails",
        "integrations",
        "metrics",
        "non_functional_requirements",
        "observability",
        "open_questions",
        "privacy",
        "product",
        "product_decisions",
        "provenance",
        "quality_assurance",
        "release",
        "required_approvals",
        "risks",
        "rollback",
        "schema_id",
        "schema_version",
        "scope",
        "security",
        "source_identity_mappings",
        "technical_constraints",
        "ux",
    } <= required


def test_both_north_stars_and_exact_policy_inputs_are_required_without_defaults() -> None:
    schema = _load_json(BUNDLE_SCHEMA)
    metrics = schema["properties"]["metrics"]
    north_stars = metrics["properties"]["north_stars"]
    assert {"end_state", "mvp"} <= set(north_stars["required"])

    policy = metrics["properties"]["maturity_policies"]["additionalProperties"]
    required = set(policy["required"])
    assert {
        "approval_ref",
        "delivery_window",
        "evaluation_window",
        "metric_ref",
        "observation_window",
        "reporting_policy_ref",
        "reporting_window",
        "target",
    } <= required
    assert "reporting_policies" in metrics["required"]
    assert "success" in metrics["required"]
    reporting = metrics["properties"]["reporting_policies"]["additionalProperties"]
    assert {
        "approval_ref",
        "calculation",
        "denominator",
        "exclusions",
        "inclusion_criteria",
        "owner_ref",
        "policy_version",
    } <= set(reporting["required"])
    assert "default" not in json.dumps(metrics)


def test_legacy_success_metrics_and_nfr_categories_are_losslessly_representable() -> None:
    schema = _load_json(BUNDLE_SCHEMA)
    metrics = schema["properties"]["metrics"]
    success = metrics["properties"]["success"]
    assert success["propertyNames"] == {"$ref": "#/$defs/metric_id_success"}
    assert set(success["additionalProperties"]["required"]) == {"definition"}

    nfr = schema["properties"]["non_functional_requirements"]["additionalProperties"]
    categories = set(nfr["properties"]["category"]["enum"])
    assert {"COMPLIANCE", "OTHER"} <= categories
    assert "source_category" in nfr["properties"]

    bundle = _load_json(VALID_BUNDLE)
    assert bundle["metrics"]["success"]["METRIC-SUCCESS-001"]["definition"]
    assert (
        bundle["non_functional_requirements"]["NFR-LEGACY-CATEGORY"]["source_category"]
        == "operability"
    )


def test_metric_namespaces_make_stable_ids_structurally_disjoint() -> None:
    schema = _load_json(BUNDLE_SCHEMA)
    metrics = schema["properties"]["metrics"]
    leading = metrics["properties"]["leading"]
    north_stars = metrics["properties"]["north_stars"]["properties"]

    assert leading["propertyNames"] == {"$ref": "#/$defs/metric_id_leading"}
    assert "metric_id" not in leading["additionalProperties"]["properties"]
    assert north_stars["end_state"]["properties"]["metric_id"] == {
        "$ref": "#/$defs/metric_id_end_state"
    }
    assert north_stars["mvp"]["properties"]["metric_id"] == {"$ref": "#/$defs/metric_id_mvp"}


def test_leading_metric_target_is_bound_inside_its_approved_maturity_policy() -> None:
    bundle = _load_json(VALID_BUNDLE)
    leading = bundle["metrics"]["leading"]["METRIC-LEAD-001"]
    policy = bundle["metrics"]["maturity_policies"][leading["maturity_policy_ref"]]
    assert policy["metric_ref"] == "METRIC-LEAD-001"
    assert policy["target"] == {
        "baseline_plan": (
            "Approve a prospective first-pass validation target after the initial intake cohort."
        ),
        "status": "BASELINE_REQUIRED",
        "unit": "ratio",
    }
    approval = bundle["approvals"][policy["approval_ref"]]
    assert approval["subject"]["id"] == leading["maturity_policy_ref"]
    assert approval["subject"]["digest_scope"] == "NAMED_METRIC_MATURITY_POLICY"


def test_canonical_core_preserves_product_and_delivery_target_truth() -> None:
    schema = _load_json(BUNDLE_SCHEMA)
    product = schema["properties"]["product"]
    release = schema["properties"]["release"]

    assert {"priority", "product_name", "target_platform"} <= set(product["required"])
    assert {"business_outcome", "customer_outcome"} <= set(
        product["properties"]["outcome"]["required"]
    )
    assert set(product["properties"]["target_platform"]["required"]) == {
        "description",
        "kind",
    }
    assert "deployment_target" in release["required"]
    assert set(release["properties"]["deployment_target"]["required"]) == {
        "description",
        "environment",
        "kind",
    }


def test_canonical_core_preserves_typed_v1_v2_v3_product_truth() -> None:
    schema = _load_json(BUNDLE_SCHEMA)
    properties = schema["properties"]
    complete_branch = next(
        branch
        for branch in schema["oneOf"]
        if branch["properties"]["unresolved_product_truth"].get("maxProperties") == 0
    )

    assert {
        "api_contracts",
        "backend_capabilities",
        "dependencies",
        "product_decisions",
        "required_approvals",
    } <= set(complete_branch["required"])
    assert "entities" in properties["data"]["required"]
    assert {
        "evaluation_rubrics",
        "golden_cases",
        "release_gates",
    } <= set(properties["quality_assurance"]["required"])
    assert {
        "responsive_requirements",
        "primary_journey",
        "screens",
        "ui_states",
        "user_stories",
    } <= set(properties["ux"]["required"])


def test_unresolved_product_truth_is_explicitly_draft_only_and_blocking() -> None:
    schema = _load_json(BUNDLE_SCHEMA)
    branches = schema["oneOf"]
    complete = next(
        branch
        for branch in branches
        if branch["properties"]["unresolved_product_truth"].get("maxProperties") == 0
    )
    incomplete = next(
        branch
        for branch in branches
        if branch["properties"]["unresolved_product_truth"].get("minProperties") == 1
    )
    assert "product" in complete["required"]
    assert incomplete["properties"]["contract_status"]["const"] == "DRAFT"

    unresolved = schema["properties"]["unresolved_product_truth"]
    assert unresolved["additionalProperties"]["properties"]["blocking"]["const"] is True
    assert _load_json(VALID_BUNDLE)["unresolved_product_truth"] == {}


def test_actual_legacy_identity_truth_is_losslessly_representable() -> None:
    schema = _load_json(BUNDLE_SCHEMA)
    validator = Draft202012Validator(schema)

    def incomplete_bundle(
        source_path: Path,
        source: dict[str, Any],
        source_id: str,
        source_version: str | int,
        source_approved_by: str | None = None,
    ) -> dict[str, Any]:
        provenance: dict[str, Any] = {
            "published_at": "2026-07-30T00:00:00Z",
            "source_digest": f"sha256:{hashlib.sha256(source_path.read_bytes()).hexdigest()}",
            "source_id": source_id,
            "source_system": "PM_AGENT_OS",
            "source_version": source_version,
        }
        if source_approved_by is not None:
            provenance["source_approved_by"] = source_approved_by
        return {
            "bundle_id": f"BUNDLE-LEGACY-{source_id.upper().replace('.', '-')}",
            "bundle_version": "1.0.0",
            "canonical_json_profile": "RFC8785",
            "contract_status": "DRAFT",
            "provenance": provenance,
            "schema_id": (
                "https://github.com/Abhillashjadhav/production-engineering-os/"
                "schemas/pmos_contract_bundle.schema.json"
            ),
            "schema_version": "1.0.0",
            "source_identity_mappings": {},
            "unresolved_product_truth": {
                "UNRESOLVED-LEGACY-SOURCE": {
                    "blocking": True,
                    "question": (
                        "Supply or approve the missing canonical product truth before "
                        "engineering execution."
                    ),
                    "reason_code": "SOURCE_FIELD_UNMAPPED",
                    "source_pointer": "",
                    "source_value": source,
                }
            },
        }

    legacy_v1 = _load_json(LEGACY_V1)
    v1_bundle = incomplete_bundle(
        LEGACY_V1,
        legacy_v1,
        "minimal-valid-spec.json",
        legacy_v1["spec_version"],
    )
    assert list(validator.iter_errors(v1_bundle)) == []

    legacy_v2 = _load_json(LEGACY_V2)
    v2_bundle = incomplete_bundle(
        LEGACY_V2,
        legacy_v2,
        legacy_v2["contract_id"],
        legacy_v2["contract_version"],
        legacy_v2["approved_by"],
    )
    assert list(validator.iter_errors(v2_bundle)) == []

    legacy_v3 = _load_json(LEGACY_V3)
    v3_bundle = incomplete_bundle(
        LEGACY_V3,
        legacy_v3,
        legacy_v3["contract_id"],
        legacy_v3["contract_version"],
        legacy_v3["approved_by"],
    )
    assert list(validator.iter_errors(v3_bundle)) == []

    assert v1_bundle["provenance"]["source_version"] == "1.0"
    assert v2_bundle["provenance"]["source_approved_by"] == "abhillash (PM Agent OS)"
    assert v3_bundle["provenance"]["source_id"] == "FSC-PMEVALS-001"
    assert (
        v3_bundle["unresolved_product_truth"]["UNRESOLVED-LEGACY-SOURCE"]["source_value"][
            "backend_capabilities"
        ][0]["capability_id"]
        == "BC-1"
    )
    assert (
        v3_bundle["unresolved_product_truth"]["UNRESOLVED-LEGACY-SOURCE"]["source_value"][
            "screens"
        ][0]["screen_id"]
        == "S-1"
    )
    assert (
        v3_bundle["unresolved_product_truth"]["UNRESOLVED-LEGACY-SOURCE"]["source_value"][
            "primary_journey"
        ][0]["step_id"]
        == "J-1"
    )
    assert (
        v2_bundle["unresolved_product_truth"]["UNRESOLVED-LEGACY-SOURCE"]["source_value"][
            "approved_product_decisions"
        ][0]["id"]
        == "APD-001"
    )


def test_approval_lifecycle_variants_forbid_contradictory_evidence() -> None:
    schema = _load_json(BUNDLE_SCHEMA)
    branches = schema["properties"]["approvals"]["additionalProperties"]["oneOf"]
    by_status = {branch["properties"]["status"]["const"]: branch for branch in branches}

    assert by_status["ACTIVE"]["properties"]["revoked_at"] is False
    assert by_status["ACTIVE"]["properties"]["superseded_by_approval_ref"] is False
    assert by_status["REVOKED"]["properties"]["superseded_by_approval_ref"] is False
    assert by_status["SUPERSEDED"]["properties"]["revoked_at"] is False


def test_extensions_can_only_add_constraints() -> None:
    schema = _load_json(BUNDLE_SCHEMA)
    extension = schema["properties"]["extensions"]["additionalProperties"]
    effect = extension["properties"]["effect"]
    assert effect == {
        "const": "ADD_CONSTRAINTS_ONLY",
        "description": "Extensions may add constraints but can never weaken or replace core truth.",
    }
    payload = extension["properties"]["payload"]
    assert payload["additionalProperties"] is False
    operators = payload["properties"]["constraints"]["additionalProperties"]["properties"][
        "operator"
    ]["enum"]
    assert set(operators) == {
        "FORBID_VALUE",
        "LIMIT_ALLOWED_VALUES",
        "MATCH_PATTERN",
        "REQUIRE_PRESENT",
        "SET_MAXIMUM",
        "SET_MINIMUM",
    }


def test_manifest_binds_bundle_provenance_approvals_and_member_digests() -> None:
    schema = _load_json(MANIFEST_SCHEMA)
    required = set(schema["required"])
    assert {
        "approval_digest",
        "approval_digest_scope",
        "bundle",
        "canonical_json_profile",
        "manifest_digest",
        "members",
        "provenance",
        "schema_id",
        "schema_version",
    } <= required
    assert (
        schema["properties"]["approval_digest_scope"]["const"]
        == "CANONICAL_BUNDLE_APPROVALS_RFC8785"
    )
    bundle_required = set(schema["properties"]["bundle"]["required"])
    assert {
        "bundle_id",
        "bundle_version",
        "content_digest",
        "member_id",
        "schema_id",
        "schema_version",
    } <= bundle_required
    assert schema["properties"]["bundle"]["properties"]["member_id"] == {
        "const": "MEMBER-CANONICAL-BUNDLE"
    }
    assert "path" not in schema["properties"]["bundle"]["properties"]
    members = schema["properties"]["members"]
    assert members["propertyNames"] == {"$ref": "#/$defs/member_id"}
    member_required = set(members["additionalProperties"]["required"])
    assert {"content_digest", "schema_id", "schema_version"} <= member_required
    assert "path" not in members["additionalProperties"]["properties"]


def test_manifest_fixture_content_digests_bind_canonical_fixture_bytes() -> None:
    manifest = _load_json(VALID_MANIFEST)
    bundle = _load_json(VALID_BUNDLE)
    expected_approval_digest = (
        f"sha256:{hashlib.sha256(_rfc8785_fixture_bytes(bundle['approvals'])).hexdigest()}"
    )
    assert manifest["approval_digest"] == expected_approval_digest
    expected_bundle_digest = f"sha256:{hashlib.sha256(_rfc8785_fixture_bytes(bundle)).hexdigest()}"
    assert manifest["bundle"]["content_digest"] == expected_bundle_digest

    projection = copy.deepcopy(manifest)
    manifest_digest = projection.pop("manifest_digest")
    projection_bytes = _rfc8785_fixture_bytes(projection)
    assert manifest_digest == f"sha256:{hashlib.sha256(projection_bytes).hexdigest()}"

    mismatched = _fixture_instance(FIXTURE_DIR / "mismatched_manifest_binding.json")
    schema = _load_json(MANIFEST_SCHEMA)
    assert list(Draft202012Validator(schema).iter_errors(mismatched)) == []
    assert mismatched["bundle"]["content_digest"] != expected_bundle_digest


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "../secret.json",
        "nested/../secret.json",
        "./contract.json",
        "C:/secret.json",
        "C:\\secret.json",
        "..\\secret.json",
        "\\\\server\\share\\secret.json",
        "/absolute/secret.json",
        "CON",
        "nul.json",
        "dir/PRN.txt",
        "dir/prn.txt",
        "dir./member.json",
        "member.json.",
    ],
)
def test_manifest_rejects_caller_controlled_paths(unsafe_path: str) -> None:
    manifest = copy.deepcopy(_load_json(VALID_MANIFEST))
    manifest["bundle"]["path"] = unsafe_path
    schema = _load_json(MANIFEST_SCHEMA)
    assert list(Draft202012Validator(schema).iter_errors(manifest))


def _schema_patterns(node: Any) -> list[str]:
    patterns: list[str] = []
    if isinstance(node, dict):
        pattern = node.get("pattern")
        if isinstance(pattern, str):
            patterns.append(pattern)
        for value in node.values():
            patterns.extend(_schema_patterns(value))
    elif isinstance(node, list):
        for value in node:
            patterns.extend(_schema_patterns(value))
    return patterns


@pytest.mark.parametrize("schema_path", [BUNDLE_SCHEMA, MANIFEST_SCHEMA])
def test_every_exact_pattern_requires_true_end_of_string(schema_path: Path) -> None:
    schema = _load_json(schema_path)
    patterns = _schema_patterns(schema)
    assert patterns
    assert all(pattern.endswith(r"(?![\s\S])") for pattern in patterns)


def test_multi_level_iana_time_zone_is_representable() -> None:
    bundle = _load_json(VALID_BUNDLE)
    policy = bundle["metrics"]["maturity_policies"]["POLICY-METRIC-EADPR"]
    assert policy["evaluation_window"]["time_zone"] == "America/Argentina/Buenos_Aires"
    schema = _load_json(BUNDLE_SCHEMA)
    assert list(Draft202012Validator(schema).iter_errors(bundle)) == []


def test_product_owned_targets_privacy_release_rollback_and_approvals_are_typed() -> None:
    schema = _load_json(BUNDLE_SCHEMA)
    properties = schema["properties"]

    target = properties["metrics"]["properties"]["maturity_policies"]["additionalProperties"][
        "properties"
    ]["target"]
    assert len(target["oneOf"]) == 3
    branches = {branch["properties"]["status"]["const"]: branch for branch in target["oneOf"]}
    statuses = {status: set(branch["required"]) for status, branch in branches.items()}
    assert {"operator", "status", "unit", "value"} <= statuses["APPROVED"]
    assert branches["APPROVED"]["properties"]["baseline_plan"] is False
    assert branches["APPROVED"]["properties"]["retirement_reason"] is False
    assert {"baseline_plan", "status", "unit"} <= statuses["BASELINE_REQUIRED"]
    assert branches["BASELINE_REQUIRED"]["properties"]["retirement_reason"] is False
    assert "value" not in statuses["BASELINE_REQUIRED"]
    assert {"retirement_reason", "status", "unit"} <= statuses["RETIRED"]
    assert branches["RETIRED"]["properties"]["baseline_plan"] is False
    assert {"data_residency", "deletion", "retention", "telemetry"} <= set(
        properties["privacy"]["required"]
    )
    assert {"eligible_audiences", "guardrail_refs", "launch_intent"} <= set(
        properties["release"]["required"]
    )
    assert {"customer_communication_intent", "data_loss_tolerance", "rpo", "rto"} <= set(
        properties["rollback"]["required"]
    )
    approval_required = set(properties["approvals"]["additionalProperties"]["required"])
    assert {
        "approval_version",
        "authority_policy_ref",
        "authority_policy_version",
        "expires_at",
        "status",
        "subject",
        "supersedes_approval_refs",
        "valid_from",
    } <= approval_required
    subject = properties["approvals"]["additionalProperties"]["properties"]["subject"]
    assert len(subject["oneOf"]) == 3
    assert {branch["properties"]["digest_scope"]["const"] for branch in subject["oneOf"]} == {
        "CANONICAL_BUNDLE_EXCLUDING_APPROVALS",
        "NAMED_METRIC_MATURITY_POLICY",
        "NAMED_METRIC_REPORTING_POLICY",
    }
    assert len(properties["approvals"]["additionalProperties"]["oneOf"]) == 3


def test_portable_patterns_replace_non_asserting_format_annotations() -> None:
    for schema_path in (BUNDLE_SCHEMA, MANIFEST_SCHEMA):
        schema = _load_json(schema_path)
        assert "format" not in _schema_keywords(schema)


def test_official_validator_does_not_treat_boolean_as_number() -> None:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "number",
    }
    assert list(Draft202012Validator(schema).iter_errors(True))
