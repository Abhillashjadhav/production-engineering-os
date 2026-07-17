"""PD-V3: the FullStackProductContract schema — structure of the V3 boundary
object. The typed model and semantic runnability rules land with the adapter
(V3 PR 2); this locks the schema itself: it must stay inside the documented
validator subset, and the approved example must validate."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pmpe.ingestion.schema import SchemaValidator

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "schemas" / "fullstack_product_contract.schema.json"
EXAMPLE = ROOT / "tests" / "fixtures" / "v3" / "fullstack_contract_approved.json"

_SUPPORTED_KEYWORDS = {
    # the documented pmpe.ingestion.SchemaValidator subset plus JSON-Schema
    # metadata keys that carry no validation semantics for it
    "type",
    "required",
    "properties",
    "items",
    "enum",
    "minItems",
    "minLength",
    "$schema",
    "$id",
    "title",
    "description",
}


def _keywords(node: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key not in ("properties",):
                found.add(key)
            if key == "properties" and isinstance(value, dict):
                for sub in value.values():
                    found |= _keywords(sub)
            else:
                found |= _keywords(value)
    elif isinstance(node, list):
        for item in node:
            found |= _keywords(item)
    return found


@pytest.fixture()
def example() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(EXAMPLE.read_text())
    return loaded


def test_schema_stays_inside_the_documented_validator_subset() -> None:
    schema = json.loads(SCHEMA.read_text())
    unsupported = _keywords(schema) - _SUPPORTED_KEYWORDS
    assert not unsupported, f"schema uses keywords the validator ignores: {unsupported}"


def test_approved_example_validates(example: dict[str, Any]) -> None:
    assert SchemaValidator(SCHEMA).validate(example) == []


def test_missing_required_section_is_rejected(example: dict[str, Any]) -> None:
    del example["screens"]
    errors = SchemaValidator(SCHEMA).validate(example)
    assert any("screens" in e for e in errors)


def test_screen_without_states_is_rejected(example: dict[str, Any]) -> None:
    example["screens"][0]["states"] = []
    errors = SchemaValidator(SCHEMA).validate(example)
    assert any("states" in e for e in errors)


def test_journey_step_requires_a_screen(example: dict[str, Any]) -> None:
    del example["primary_journey"][0]["screen_id"]
    errors = SchemaValidator(SCHEMA).validate(example)
    assert any("screen_id" in e for e in errors)


def test_unknown_persistence_kind_is_rejected(example: dict[str, Any]) -> None:
    example["data_entities"][0]["persistence"] = "s3_bucket"
    errors = SchemaValidator(SCHEMA).validate(example)
    assert any("persistence" in e for e in errors)


def test_deployment_target_kind_is_constrained(example: dict[str, Any]) -> None:
    example["deployment_target"]["kind"] = "production_cloud_now"
    errors = SchemaValidator(SCHEMA).validate(example)
    assert any("kind" in e for e in errors)
