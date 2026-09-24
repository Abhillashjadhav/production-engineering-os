from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from pmpe.barebones import compile_barebones_plan
from pmpe.contracts.acceptance import AcceptanceCompileError


def _contract() -> dict[str, Any]:
    path = Path(__file__).parents[2] / "examples/barebones/e1-contract.json"
    contract: dict[str, Any] = json.loads(path.read_text())
    contract["contract_id"] = "TEST-ONLY-RELEASE-GATES"
    return contract


def _gate(**changes: Any) -> dict[str, Any]:
    return {
        "description": "TEST ONLY: the named mechanical acceptance checks must pass.",
        "acceptance_criterion_refs": ["AC-001"],
        **changes,
    }


@pytest.mark.parametrize("shape", ["pdc_array", "pdc_map", "canonical_map"])
def test_release_gate_bindings_are_preserved_in_the_compiled_plan(
    tmp_path: Path, shape: str
) -> None:
    contract = _contract()
    if shape == "pdc_array":
        contract["binary_release_gates"] = [{"id": "GATE-001", **_gate()}]
    elif shape == "pdc_map":
        contract["binary_release_gates"] = {"GATE-001": _gate()}
    else:
        contract["quality_assurance"] = {"release_gates": {"GATE-001": _gate()}}
    original = copy.deepcopy(contract)

    plan = compile_barebones_plan(contract=contract, repository_root=tmp_path)

    assert plan.as_dict()["release_gates"] == (
        {"gate_id": "GATE-001", "acceptance_criterion_refs": ("AC-001",)},
    )
    assert contract == original


@pytest.mark.parametrize("refs", [None, [], "AC-001", [""], [1], ["AC-001", "AC-001"]])
def test_release_gate_invalid_binding_refuses_compilation(tmp_path: Path, refs: Any) -> None:
    contract = _contract()
    contract["binary_release_gates"] = [{"id": "GATE-001", **_gate(acceptance_criterion_refs=refs)}]
    with pytest.raises(AcceptanceCompileError) as failure:
        compile_barebones_plan(contract=contract, repository_root=tmp_path)
    assert any(item.subject_id == "GATE-001" for item in failure.value.diagnostics)


@pytest.mark.parametrize("canonical", [False, True])
def test_description_only_gate_is_unbound_not_silently_dropped(
    tmp_path: Path, canonical: bool
) -> None:
    contract = _contract()
    gates = {"GATE-001": {"description": "An unsupported process gate must pass."}}
    if canonical:
        contract["quality_assurance"] = {"release_gates": gates}
    else:
        contract["binary_release_gates"] = gates
    with pytest.raises(AcceptanceCompileError) as failure:
        compile_barebones_plan(contract=contract, repository_root=tmp_path)
    assert any(item.code == "RELEASE_GATE_UNBOUND" for item in failure.value.diagnostics)


@pytest.mark.parametrize(
    "gates",
    [
        None,
        "all tests pass",
        [None],
        [{"id": "GATE-001", **_gate()}, {"id": "GATE-001", **_gate()}],
        {"": _gate()},
        {"GATE-001": None},
        {"GATE-001": _gate(acceptance_criterion_refs=["AC-UNKNOWN"])},
        {"GATE-001": _gate(judge="model decides")},
        {"GATE-001": _gate(id="GATE-OTHER")},
    ],
)
def test_malformed_or_unsupported_gate_cannot_be_dropped(tmp_path: Path, gates: Any) -> None:
    contract = _contract()
    contract["binary_release_gates"] = gates
    with pytest.raises(AcceptanceCompileError):
        compile_barebones_plan(contract=contract, repository_root=tmp_path)


def test_competing_gate_declarations_are_not_merged_by_guessing(tmp_path: Path) -> None:
    contract = _contract()
    contract["binary_release_gates"] = {"GATE-001": _gate()}
    contract["quality_assurance"] = {"release_gates": {"GATE-002": _gate()}}
    with pytest.raises(AcceptanceCompileError) as failure:
        compile_barebones_plan(contract=contract, repository_root=tmp_path)
    assert any(
        item.code == "RELEASE_GATE_DECLARATIONS_CONFLICT" for item in failure.value.diagnostics
    )


def test_contract_without_release_gates_still_compiles(tmp_path: Path) -> None:
    plan = compile_barebones_plan(contract=_contract(), repository_root=tmp_path)
    assert [criterion.criterion_id for criterion in plan.criteria] == ["AC-001"]


@pytest.mark.parametrize(
    ("container", "key"),
    [
        (None, "release_gates"),
        (None, "binary_release_gate"),
        (None, "binary_release_gatez"),
        (None, "gates"),
        ("quality_assurance", "binary_release_gates"),
        ("quality_assurance", "release_gate"),
        ("release", "gates"),
    ],
)
@pytest.mark.parametrize("with_valid_gate", [False, True])
def test_misplaced_gate_does_not_disappear_beside_valid_gate(
    tmp_path: Path, container: str | None, key: str, with_valid_gate: bool
) -> None:
    contract = _contract()
    if with_valid_gate:
        contract["binary_release_gates"] = {"GATE-001": _gate()}
    target = contract if container is None else contract.setdefault(container, {})
    target[key] = {"GATE-002": _gate()}
    with pytest.raises(AcceptanceCompileError) as failure:
        compile_barebones_plan(contract=contract, repository_root=tmp_path)
    assert any(
        item.code == "RELEASE_GATE_DECLARATIONS_IGNORED" for item in failure.value.diagnostics
    )


@pytest.mark.parametrize("shape", ["native-map", "native-list", "canonical"])
def test_empty_declared_gate_collection_is_not_absent(tmp_path: Path, shape: str) -> None:
    contract = _contract()
    if shape == "canonical":
        contract["quality_assurance"] = {"release_gates": {}}
    else:
        contract["binary_release_gates"] = [] if shape == "native-list" else {}
    with pytest.raises(AcceptanceCompileError) as failure:
        compile_barebones_plan(contract=contract, repository_root=tmp_path)
    assert any(item.code == "RELEASE_GATE_COLLECTION_EMPTY" for item in failure.value.diagnostics)


def test_gate_words_in_prose_or_action_data_are_not_declarations(tmp_path: Path) -> None:
    contract = _contract()
    contract["notes"] = {"gates": "These are physical railway gates, not release metadata."}
    contract["acceptance_criteria"]["AC-001"]["when"]["arguments"] = {"gates": []}
    plan = compile_barebones_plan(contract=contract, repository_root=tmp_path)
    assert "release_gates" not in plan.as_dict()
