"""SYS-01/SYS-02: structural validation against schemas/mvp_spec.schema.json."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pmpe.domain.errors import SpecError
from pmpe.ingestion.loader import load_spec_data
from pmpe.ingestion.schema import SchemaValidator


@pytest.fixture()
def validator(schema_path: Path) -> SchemaValidator:
    return SchemaValidator(schema_path)


def test_golden_spec_has_no_schema_errors(
    validator: SchemaValidator, golden_spec_dict: dict[str, Any]
) -> None:
    assert validator.validate(golden_spec_dict) == []


def test_minimal_json_spec_is_valid(validator: SchemaValidator, fixtures_dir: Path) -> None:
    data = load_spec_data(fixtures_dir / "minimal_valid_spec.json")
    assert validator.validate(data) == []


def test_missing_required_field_is_reported(
    validator: SchemaValidator, golden_spec_dict: dict[str, Any]
) -> None:
    del golden_spec_dict["product_name"]
    errors = validator.validate(golden_spec_dict)
    assert any("product_name" in e for e in errors)


def test_wrong_type_is_reported(
    validator: SchemaValidator, golden_spec_dict: dict[str, Any]
) -> None:
    golden_spec_dict["scope"] = "not a list"
    errors = validator.validate(golden_spec_dict)
    assert any("scope" in e for e in errors)


def test_bad_enum_value_is_reported(
    validator: SchemaValidator, golden_spec_dict: dict[str, Any]
) -> None:
    golden_spec_dict["priority"] = "urgent"
    errors = validator.validate(golden_spec_dict)
    assert any("priority" in e for e in errors)


def test_unknown_capability_is_reported(
    validator: SchemaValidator, golden_spec_dict: dict[str, Any]
) -> None:
    golden_spec_dict["functional_requirements"][0]["capability"] = "blockchain.mine"
    errors = validator.validate(golden_spec_dict)
    assert any("capability" in e for e in errors)


def test_empty_scope_violates_min_items(
    validator: SchemaValidator, golden_spec_dict: dict[str, Any]
) -> None:
    golden_spec_dict["scope"] = []
    errors = validator.validate(golden_spec_dict)
    assert any("scope" in e for e in errors)


def test_unsupported_spec_version_is_reported(
    validator: SchemaValidator, golden_spec_dict: dict[str, Any]
) -> None:
    golden_spec_dict["spec_version"] = "9.9"
    errors = validator.validate(golden_spec_dict)
    assert any("spec_version" in e for e in errors)


def test_malformed_fixture_collects_multiple_errors(
    validator: SchemaValidator, fixtures_dir: Path
) -> None:
    data = load_spec_data(fixtures_dir / "malformed_spec.yaml")
    errors = validator.validate(data)
    assert len(errors) >= 4


def test_non_mapping_input_raises_spec_error(fixtures_dir: Path) -> None:
    with pytest.raises(SpecError):
        load_spec_data(fixtures_dir / "not_a_mapping.yaml")


def test_broken_syntax_raises_spec_error(fixtures_dir: Path) -> None:
    with pytest.raises(SpecError):
        load_spec_data(fixtures_dir / "broken_syntax.yaml")
