"""Normalization: stable IDs, trimming, typed MvpSpec construction."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pmpe.ingestion import ingest
from pmpe.ingestion.normalizer import normalize_spec


def test_golden_spec_normalizes_to_typed_model(golden_spec_dict: dict[str, Any]) -> None:
    spec = normalize_spec(golden_spec_dict)
    assert spec.product_name == "TaskFlow"
    assert [fr.id for fr in spec.functional_requirements] == [
        "FR-001",
        "FR-002",
        "FR-003",
        "FR-004",
        "FR-005",
        "FR-006",
        "FR-007",
    ]
    assert spec.entities[0].name == "Task"
    assert spec.deployment_target == "local"


def test_missing_ac_ids_are_assigned_uniquely(golden_spec_dict: dict[str, Any]) -> None:
    for ac in golden_spec_dict["acceptance_criteria"]:
        ac.pop("id", None)
    spec = normalize_spec(golden_spec_dict)
    ids = [ac.id for ac in spec.acceptance_criteria]
    assert len(ids) == len(set(ids))
    assert all(i.startswith("AC-") for i in ids)


def test_missing_story_ids_are_assigned(golden_spec_dict: dict[str, Any]) -> None:
    for story in golden_spec_dict["user_stories"]:
        story.pop("id", None)
    spec = normalize_spec(golden_spec_dict)
    ids = [s.id for s in spec.user_stories]
    assert len(ids) == len(set(ids))
    assert all(i.startswith("US-") for i in ids)


def test_strings_are_trimmed(golden_spec_dict: dict[str, Any]) -> None:
    golden_spec_dict["product_name"] = "  TaskFlow  \n"
    spec = normalize_spec(golden_spec_dict)
    assert spec.product_name == "TaskFlow"


def test_ingest_end_to_end_from_yaml(golden_spec_path: Path, schema_path: Path) -> None:
    spec = ingest(golden_spec_path, schema_path)
    assert spec.product_name == "TaskFlow"
    assert len(spec.acceptance_criteria) == 12
