"""Issue #62: canonical PMOS contract-bundle and manifest schemas.

These tests intentionally exercise schema artifacts only. Runtime model,
compiler, migration, and semantic cross-reference validation belong to later
issues. The small evaluator below covers every validation keyword used by the
two schemas so CI can verify the normative wire contract without adding a
runtime dependency.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest

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
}
_ANNOTATION_KEYWORDS = {
    "$defs",
    "$id",
    "$schema",
    "description",
    "format",
    "title",
}
_TYPE_CHECKS: dict[str, type | tuple[type, ...]] = {
    "array": list,
    "boolean": bool,
    "integer": int,
    "number": (int, float),
    "object": dict,
    "string": str,
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


def _resolve_ref(root: dict[str, Any], reference: str) -> dict[str, Any]:
    assert reference.startswith("#/"), f"only local references are permitted: {reference}"
    node: Any = root
    for part in reference[2:].split("/"):
        node = node[part.replace("~1", "/").replace("~0", "~")]
    assert isinstance(node, dict)
    return node


def _validation_errors(
    value: Any,
    schema: dict[str, Any],
    root: dict[str, Any],
    path: str = "$",
) -> list[str]:
    """Evaluate the deliberately bounded JSON Schema vocabulary used here."""

    if "$ref" in schema:
        referenced = _resolve_ref(root, schema["$ref"])
        siblings = {key: item for key, item in schema.items() if key != "$ref"}
        errors = _validation_errors(value, referenced, root, path)
        if siblings:
            errors.extend(_validation_errors(value, siblings, root, path))
        return errors

    errors: list[str] = []
    expected = schema.get("type")
    if expected is not None:
        expected_type = _TYPE_CHECKS[expected]
        if expected == "integer" and isinstance(value, bool):
            return [f"{path}: expected integer, got boolean"]
        if not isinstance(value, expected_type):
            return [f"{path}: expected {expected}, got {type(value).__name__}"]

    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: expected constant {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: unsupported value {value!r}")

    if isinstance(value, str):
        if len(value) < int(schema.get("minLength", 0)):
            errors.append(f"{path}: shorter than minLength")
        pattern = schema.get("pattern")
        if pattern is not None and re.fullmatch(pattern, value) is None:
            errors.append(f"{path}: does not match {pattern!r}")

    if isinstance(value, list):
        if len(value) < int(schema.get("minItems", 0)):
            errors.append(f"{path}: fewer than minItems")
        if schema.get("uniqueItems"):
            canonical = [json.dumps(item, sort_keys=True, separators=(",", ":")) for item in value]
            if len(canonical) != len(set(canonical)):
                errors.append(f"{path}: duplicate array item")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                errors.extend(_validation_errors(item, item_schema, root, f"{path}[{index}]"))

    if isinstance(value, dict):
        if len(value) < int(schema.get("minProperties", 0)):
            errors.append(f"{path}: fewer than minProperties")
        for required in schema.get("required", []):
            if required not in value:
                errors.append(f"{path}: missing required field {required!r}")

        property_names = schema.get("propertyNames")
        if isinstance(property_names, dict):
            for key in value:
                errors.extend(
                    _validation_errors(key, property_names, root, f"{path}.<property:{key}>")
                )

        properties = schema.get("properties", {})
        for key, child_schema in properties.items():
            if key in value:
                errors.extend(_validation_errors(value[key], child_schema, root, f"{path}.{key}"))

        extra_schema = schema.get("additionalProperties", True)
        for key in value.keys() - properties.keys():
            if extra_schema is False:
                errors.append(f"{path}: unexpected field {key!r}")
            elif isinstance(extra_schema, dict):
                errors.extend(_validation_errors(value[key], extra_schema, root, f"{path}.{key}"))

    return errors


def _validate_fixture(fixture: Path, schema_path: Path) -> list[str]:
    try:
        instance = _fixture_instance(fixture)
    except (json.JSONDecodeError, DuplicateKeyError) as exc:
        return [str(exc)]
    schema = _load_json(schema_path)
    assert isinstance(schema, dict)
    return _validation_errors(instance, schema, schema)


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
        ("missing_security.json", BUNDLE_SCHEMA, "missing required field 'security'"),
        ("duplicate_requirement_id.json", BUNDLE_SCHEMA, "duplicate object key: FR-001"),
        ("unknown_schema_version.json", BUNDLE_SCHEMA, "unsupported value '2.0.0'"),
        ("invalid_reference.json", BUNDLE_SCHEMA, "does not match"),
        ("weakening_extension.json", BUNDLE_SCHEMA, "ADD_CONSTRAINTS_ONLY"),
        ("invalid_manifest_reference.json", MANIFEST_SCHEMA, "does not match"),
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


def test_north_star_policy_and_windows_are_required_without_defaults() -> None:
    schema = _load_json(BUNDLE_SCHEMA)
    north_star = schema["properties"]["metrics"]["properties"]["north_star"]
    required = set(north_star["required"])
    assert {
        "maturity_policy_ref",
        "evaluation_window",
        "delivery_window",
        "observation_window",
        "reporting_window",
    } <= required
    assert "default" not in json.dumps(north_star)


def test_extensions_can_only_add_constraints() -> None:
    schema = _load_json(BUNDLE_SCHEMA)
    extension = schema["properties"]["extensions"]["additionalProperties"]
    effect = extension["properties"]["effect"]
    assert effect == {
        "const": "ADD_CONSTRAINTS_ONLY",
        "description": "Extensions may add constraints but can never weaken or replace core truth.",
    }


def test_manifest_binds_bundle_provenance_approvals_and_member_digests() -> None:
    schema = _load_json(MANIFEST_SCHEMA)
    required = set(schema["required"])
    assert {
        "approval_digest",
        "bundle_digest",
        "bundle_id",
        "bundle_member_ref",
        "bundle_version",
        "members",
        "provenance",
        "schema_id",
        "schema_version",
    } <= required
    members = schema["properties"]["members"]
    assert members["propertyNames"] == {"$ref": "#/$defs/stable_id"}
    member_required = set(members["additionalProperties"]["required"])
    assert {"content_digest", "schema_id", "schema_version"} <= member_required
