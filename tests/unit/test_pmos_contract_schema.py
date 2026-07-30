"""Issue #62: canonical PMOS contract-bundle and manifest schemas.

These tests intentionally exercise schema artifacts only. Runtime model,
compiler, migration, and semantic cross-reference validation belong to later
issues. The official Draft 2020-12 validator checks parsed instances. A separate
duplicate-aware loader enforces the declared RFC 8785 transport precondition
before schema validation because JSON Schema cannot observe duplicate raw keys.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

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

_VALIDATION_KEYWORDS = {
    "$ref",
    "additionalProperties",
    "const",
    "enum",
    "items",
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


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate object key: {key}")
        result[key] = value
    return result


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(), object_pairs_hook=_reject_duplicate_keys)


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
    except (json.JSONDecodeError, DuplicateKeyError) as exc:
        return [str(exc)]
    schema = _load_json(schema_path)
    assert isinstance(schema, dict)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    return [
        f"{error.json_path}: {error.message}"
        for error in sorted(validator.iter_errors(instance), key=lambda item: item.json_path)
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
            "invalid_manifest_reference.json",
            MANIFEST_SCHEMA,
            "'MEMBER-CANONICAL-BUNDLE' was expected",
        ),
        ("invalid_manifest_device_path.json", MANIFEST_SCHEMA, "does not match"),
        ("invalid_manifest_parent_path.json", MANIFEST_SCHEMA, "does not match"),
        ("invalid_manifest_trailing_period_path.json", MANIFEST_SCHEMA, "does not match"),
        ("invalid_manifest_unc_path.json", MANIFEST_SCHEMA, "does not match"),
        ("invalid_manifest_windows_drive_path.json", MANIFEST_SCHEMA, "does not match"),
        ("invalid_manifest_windows_traversal_path.json", MANIFEST_SCHEMA, "does not match"),
        ("duplicate_manifest_member_id.json", MANIFEST_SCHEMA, "does not match"),
        ("invalid_trailing_newline_bundle_id.json", BUNDLE_SCHEMA, "does not match"),
        ("invalid_trailing_newline_digest.json", BUNDLE_SCHEMA, "does not match"),
        ("invalid_trailing_newline_duration.json", BUNDLE_SCHEMA, "does not match"),
        ("invalid_trailing_newline_manifest_path.json", MANIFEST_SCHEMA, "does not match"),
        ("invalid_trailing_newline_uri.json", BUNDLE_SCHEMA, "does not match"),
        (
            "mismatched_manifest_binding.json",
            MANIFEST_SCHEMA,
            "Additional properties",
        ),
        ("missing_metric_target.json", BUNDLE_SCHEMA, "'target' is a required property"),
        (
            "missing_metric_reporting_policy.json",
            BUNDLE_SCHEMA,
            "'reporting_policy_ref' is a required property",
        ),
        ("missing_mvp_north_star.json", BUNDLE_SCHEMA, "'mvp' is a required property"),
        ("invalid_approval_subject_type.json", BUNDLE_SCHEMA, "not valid under any"),
        ("revoked_approval_without_evidence.json", BUNDLE_SCHEMA, "not valid under any"),
        ("superseded_approval_without_evidence.json", BUNDLE_SCHEMA, "not valid under any"),
        ("missing_privacy_telemetry.json", BUNDLE_SCHEMA, "'telemetry' is a required property"),
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
    assert fixture["canonical_json_profile"] == "RFC8785"


def test_bundle_schema_covers_every_phase_zero_product_truth_section() -> None:
    schema = _load_json(BUNDLE_SCHEMA)
    assert isinstance(schema, dict)
    required = set(schema["required"])
    assert {
        "acceptance_criteria",
        "approvals",
        "assumptions",
        "bundle_id",
        "bundle_version",
        "canonical_json_profile",
        "contract_status",
        "data",
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
        "provenance",
        "quality_assurance",
        "release",
        "risks",
        "rollback",
        "schema_id",
        "schema_version",
        "scope",
        "security",
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
    assert "default" not in json.dumps(metrics)


def test_leading_metric_target_is_bound_inside_its_approved_maturity_policy() -> None:
    bundle = _load_json(VALID_BUNDLE)
    leading = bundle["metrics"]["leading"]["METRIC-LEAD-001"]
    policy = bundle["metrics"]["maturity_policies"][leading["maturity_policy_ref"]]
    assert policy["metric_ref"] == leading["metric_id"]
    assert policy["target"]["status"] == "APPROVED"
    approval = bundle["approvals"][policy["approval_ref"]]
    assert approval["subject"]["id"] == leading["maturity_policy_ref"]
    assert approval["subject"]["digest_scope"] == "NAMED_METRIC_MATURITY_POLICY"


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
        "bundle",
        "canonical_json_profile",
        "members",
        "provenance",
        "schema_id",
        "schema_version",
    } <= required
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
    members = schema["properties"]["members"]
    assert members["propertyNames"] == {"$ref": "#/$defs/member_id"}
    member_required = set(members["additionalProperties"]["required"])
    assert {"content_digest", "schema_id", "schema_version"} <= member_required


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
def test_manifest_paths_reject_cross_platform_escape_forms(unsafe_path: str) -> None:
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

    assert {"operator", "status", "unit", "value"} <= set(
        properties["metrics"]["properties"]["maturity_policies"]["additionalProperties"][
            "properties"
        ]["target"]["required"]
    )
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
    assert len(subject["oneOf"]) == 2
    assert {branch["properties"]["digest_scope"]["const"] for branch in subject["oneOf"]} == {
        "CANONICAL_BUNDLE_EXCLUDING_APPROVALS",
        "NAMED_METRIC_MATURITY_POLICY",
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
