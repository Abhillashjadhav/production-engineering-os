from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from pmpe.barebones import compile_barebones_plan
from pmpe.contracts.acceptance import AcceptanceCompileError
from tests.unit.test_release_gate_compiler import _contract, _gate


def _valid_gate(contract: dict[str, Any], enabled: bool) -> None:
    if enabled:
        contract["binary_release_gates"] = {"GATE-001": _gate()}


def _reject(contract: dict[str, Any], root: Path, code: str, subject: str) -> None:
    with pytest.raises(AcceptanceCompileError) as failure:
        compile_barebones_plan(contract=contract, repository_root=root)
    assert any(
        item.code == code and item.subject_id == subject for item in failure.value.diagnostics
    ), failure.value.diagnostics


@pytest.mark.parametrize(
    "parent",
    [
        "quality_assurence",
        "Quality_Assurance",
        "quality-assurance",
        "qualityassurance",
        "qa",
        "releases",
    ],
)
@pytest.mark.parametrize("with_valid_gate", [False, True])
def test_parent_alias_cannot_hide_a_gate(
    tmp_path: Path, parent: str, with_valid_gate: bool
) -> None:
    contract = _contract()
    _valid_gate(contract, with_valid_gate)
    contract[parent] = {"release_gates": {"GATE-002": _gate()}}
    _reject(contract, tmp_path, "RELEASE_GATE_CONTAINER_MISPLACED", parent)


@pytest.mark.parametrize("parent", ["quality_assurance", "release", "acceptance"])
@pytest.mark.parametrize("value", [None, [], [{"release_gates": {}}], False, 0, "all checks"])
def test_metadata_parent_requires_an_object(tmp_path: Path, parent: str, value: Any) -> None:
    contract = _contract()
    contract[parent] = value
    _reject(contract, tmp_path, "RELEASE_GATE_COLLECTION_INVALID", parent)


@pytest.mark.parametrize("with_valid_gate", [False, True])
def test_nested_release_wrapper_cannot_hide_gate(tmp_path: Path, with_valid_gate: bool) -> None:
    contract = _contract()
    _valid_gate(contract, with_valid_gate)
    contract["quality_assurance"] = {"release": {"release_gates": {"GATE-002": _gate()}}}
    _reject(contract, tmp_path, "RELEASE_GATE_CONTAINER_MISPLACED", "quality_assurance.release")


@pytest.mark.parametrize(
    "placement",
    ["criterion-map", "criterion-array", "requirement-map", "requirement-array", "acceptance"],
)
@pytest.mark.parametrize("with_valid_gate", [False, True])
def test_entry_metadata_gate_cannot_be_dropped(
    tmp_path: Path, placement: str, with_valid_gate: bool
) -> None:
    contract = _contract()
    _valid_gate(contract, with_valid_gate)
    if placement == "acceptance":
        target = contract["acceptance"] = {}
        subject = "acceptance.release_gates"
    else:
        collection = (
            "acceptance_criteria"
            if placement.startswith("criterion")
            else "functional_requirements"
        )
        identifier = "AC-001" if placement.startswith("criterion") else "FR-001"
        target = contract[collection][identifier]
        if placement.endswith("array"):
            target["id"] = identifier
            contract[collection] = [target]
            subject = f"{collection}[0].release_gates"
        else:
            subject = f"{collection}.{identifier}.release_gates"
    target["release_gates"] = {"GATE-002": _gate()}
    _reject(contract, tmp_path, "RELEASE_GATE_DECLARATIONS_IGNORED", subject)


@pytest.mark.parametrize("key", ["relase_gate", "relese_gats", "quality_gates", "go_live_gates"])
@pytest.mark.parametrize("with_valid_gate", [False, True])
def test_two_edit_and_named_synonym_gate_fields_are_not_ignored(
    tmp_path: Path, key: str, with_valid_gate: bool
) -> None:
    contract = _contract()
    _valid_gate(contract, with_valid_gate)
    contract[key] = {"GATE-002": _gate()}
    _reject(contract, tmp_path, "RELEASE_GATE_DECLARATIONS_IGNORED", key)


@pytest.mark.parametrize("shape", ["native-map", "native-array", "canonical-map"])
@pytest.mark.parametrize("padded", [" GATE-001", "GATE-001 ", "\tGATE-001\n", "\u00a0GATE-001"])
def test_gate_ids_with_surrounding_whitespace_are_rejected(
    tmp_path: Path, shape: str, padded: str
) -> None:
    contract = _contract()
    if shape == "native-array":
        contract["binary_release_gates"] = [
            {"id": "GATE-001", **_gate()},
            {"id": padded, **_gate()},
        ]
    elif shape == "canonical-map":
        contract["quality_assurance"] = {"release_gates": {"GATE-001": _gate(), padded: _gate()}}
    else:
        contract["binary_release_gates"] = {"GATE-001": _gate(), padded: _gate()}
    with pytest.raises(AcceptanceCompileError) as failure:
        compile_barebones_plan(contract=contract, repository_root=tmp_path)
    assert any(item.code == "RELEASE_GATE_ID_INVALID" for item in failure.value.diagnostics)


@pytest.mark.parametrize(
    "location",
    [
        "root-gate-text",
        "root-gates-number",
        "root-review-notes",
        "root-notes",
        "product-data",
        "root-payload",
        "quality-notes",
        "release-notes",
        "acceptance-notes",
        "requirement-notes",
        "criterion-notes",
        "action-arguments",
        "nested-action-arguments",
        "given-value",
        "then-value",
        "root-prose",
        "quality-prose",
        "release-prose",
        "requirement-prose",
        "criterion-prose",
    ],
)
def test_legitimate_payload_and_prose_are_not_gate_declarations(
    tmp_path: Path, location: str
) -> None:
    contract = _contract()
    criterion = contract["acceptance_criteria"]["AC-001"]
    requirement = contract["functional_requirements"]["FR-001"]
    business_data = {
        "release_gates": {"physical-north-gate": {"open": True}},
        "quality_assurence": {"gates": ["north"]},
        "quality_gates": ["material inspection"],
    }
    prose = "Release gates and quality_assurence are words in a railway operations note."
    if location == "root-gate-text":
        contract["gate"] = "north"
    elif location == "root-gates-number":
        contract["gates"] = 3
    elif location == "root-review-notes":
        contract["release_gates_review_notes"] = prose
    elif location in {"root-notes", "product-data", "root-payload"}:
        key = {"root-notes": "notes", "product-data": "product", "root-payload": "payload"}[
            location
        ]
        contract[key] = business_data
    elif location in {"quality-notes", "release-notes", "acceptance-notes"}:
        parent = {
            "quality-notes": "quality_assurance",
            "release-notes": "release",
            "acceptance-notes": "acceptance",
        }[location]
        contract[parent] = {"notes": business_data}
    elif location == "requirement-notes":
        requirement["notes"] = business_data
    elif location == "criterion-notes":
        criterion["notes"] = business_data
    elif location == "action-arguments":
        criterion["when"]["arguments"] = business_data
    elif location == "nested-action-arguments":
        criterion["when"]["arguments"] = {"contract": business_data}
    elif location == "given-value":
        criterion["given"][0]["value"] = business_data
    elif location == "then-value":
        criterion["then"][0]["value"] = business_data
    elif location == "root-prose":
        contract["description"] = prose
    elif location == "quality-prose":
        contract["quality_assurance"] = {"description": prose}
    elif location == "release-prose":
        contract["release"] = {"description": prose}
    elif location == "requirement-prose":
        requirement["statement"] = prose
    else:
        criterion["description"] = prose
    original = copy.deepcopy(contract)
    plan = compile_barebones_plan(contract=contract, repository_root=tmp_path)
    assert [item.criterion_id for item in plan.criteria] == ["AC-001"]
    assert "release_gates" not in plan.as_dict()
    assert contract == original
