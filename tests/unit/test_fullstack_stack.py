"""PD-V3-13: the stack adapter protocol and the reference full-stack stack.

A stack adapter declares what it can deliver (seven capability surfaces) and
assesses whether it can deliver a given contract — refusing, fail-closed,
anything it cannot honestly support."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pmpe.domain.errors import PmpeError
from pmpe.fullstack.contract import load_fullstack_contract
from pmpe.fullstack.stack import (
    CAPABILITY_SURFACES,
    REFERENCE_STACK,
    FullStackAdapter,
    get_stack,
)

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "tests" / "fixtures" / "v3" / "fullstack_contract_approved.json"


@pytest.fixture()
def data() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(EXAMPLE.read_text())
    return loaded


def _contract(tmp_path: Path, data: dict[str, Any]):  # noqa: ANN202
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(data))
    return load_fullstack_contract(path)


# --- capability surface declaration -------------------------------------------------------


def test_surface_vocabulary_is_the_locked_seven() -> None:
    assert CAPABILITY_SURFACES == (
        "frontend",
        "backend",
        "api_contract",
        "browser_test",
        "accessibility",
        "responsive",
        "preview",
    )


def test_reference_stack_declares_every_surface() -> None:
    declared = {c.surface for c in REFERENCE_STACK.capabilities()}
    assert declared == set(CAPABILITY_SURFACES)
    for capability in REFERENCE_STACK.capabilities():
        assert capability.tool.strip(), capability.surface
        assert capability.description.strip(), capability.surface


def test_reference_stack_satisfies_the_protocol() -> None:
    assert isinstance(REFERENCE_STACK, FullStackAdapter)


def test_reference_stack_never_claims_cloud() -> None:
    """PD-V3-14: no cloud deployment is claimed — the reference stack supports
    preview kinds only."""
    kinds = REFERENCE_STACK.supported_deployment_kinds()
    assert kinds == frozenset({"local_preview", "containerized_preview"})


# --- registry ------------------------------------------------------------------------------


def test_registry_returns_the_reference_stack() -> None:
    assert get_stack("nextjs-fastapi-playwright") is REFERENCE_STACK


def test_unknown_stack_fails_closed() -> None:
    with pytest.raises(PmpeError, match="no full-stack adapter"):
        get_stack("rails-hotwire")


# --- contract assessment (fail closed) -----------------------------------------------------


def test_reference_stack_can_deliver_the_approved_example(
    tmp_path: Path, data: dict[str, Any]
) -> None:
    assert REFERENCE_STACK.assess_contract(_contract(tmp_path, data)) == []


def test_cloud_deployment_target_is_refused(tmp_path: Path, data: dict[str, Any]) -> None:
    data["deployment_target"] = {
        "kind": "cloud",
        "description": "Deploy straight to production cloud.",
    }
    problems = REFERENCE_STACK.assess_contract(_contract(tmp_path, data))
    assert any("cloud" in p for p in problems)


def test_permanent_persistence_is_refused(tmp_path: Path, data: dict[str, Any]) -> None:
    """The reference stack ships no permanent store — a contract demanding one
    must be refused, not silently half-delivered."""
    data["data_entities"].append(
        {"entity_id": "E-99", "name": "Comparison history", "persistence": "permanent"}
    )
    problems = REFERENCE_STACK.assess_contract(_contract(tmp_path, data))
    assert any("E-99" in p and "permanent" in p for p in problems)


def test_missing_core_ui_states_is_refused(tmp_path: Path, data: dict[str, Any]) -> None:
    """A web contract whose state vocabulary lacks loading/error/success cannot
    be delivered honestly by a stack that promises those states everywhere."""
    data["ui_states"] = ["empty"]
    for screen in data["screens"]:
        screen["states"] = ["empty"]
    problems = REFERENCE_STACK.assess_contract(_contract(tmp_path, data))
    blob = " ".join(problems)
    assert "loading" in blob and "error" in blob and "success" in blob


def test_unsupported_api_method_is_refused(tmp_path: Path, data: dict[str, Any]) -> None:
    """The adapter verifies only what its API-contract tooling covers; the
    schema enum is wider than any one stack's promise."""
    data["api_contracts"].append(
        {
            "api_id": "API-99",
            "method": "PATCH",
            "path": "/api/settings",
            "purpose": "Partial settings update.",
        }
    )
    problems = REFERENCE_STACK.assess_contract(_contract(tmp_path, data))
    assert any("API-99" in p and "PATCH" in p for p in problems)


def test_assessment_problems_accumulate(tmp_path: Path, data: dict[str, Any]) -> None:
    data["deployment_target"]["kind"] = "cloud"
    data["data_entities"].append(
        {"entity_id": "E-98", "name": "History", "persistence": "permanent"}
    )
    problems = REFERENCE_STACK.assess_contract(_contract(tmp_path, data))
    assert len(problems) >= 2
