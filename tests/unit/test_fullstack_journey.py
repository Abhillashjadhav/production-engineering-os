"""PD-V3-16: UX architecture validation — the journey, screens, and states must
be coherent before any implementation, and the validated-journey record is the
fail-closed precondition later stages check."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pmpe.fullstack.contract import load_fullstack_contract
from pmpe.fullstack.journey import (
    JourneyNotValidated,
    record_validated_journey,
    require_validated_journey,
    validate_ux_architecture,
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


# --- coherence rules ----------------------------------------------------------------------


def test_approved_example_is_coherent(tmp_path: Path, data: dict[str, Any]) -> None:
    assert validate_ux_architecture(_contract(tmp_path, data)) == []


def test_journey_step_pointing_at_missing_screen_is_refused(
    tmp_path: Path, data: dict[str, Any]
) -> None:
    data["primary_journey"][0]["screen_id"] = "S-404"
    problems = validate_ux_architecture(_contract(tmp_path, data))
    assert any("J-1" in p and "S-404" in p for p in problems)


def test_screen_unreachable_from_the_journey_is_refused(
    tmp_path: Path, data: dict[str, Any]
) -> None:
    data["screens"].append(
        {
            "screen_id": "S-9",
            "name": "Orphan",
            "purpose": "No journey step ever reaches this screen.",
            "states": ["error", "success"],
        }
    )
    problems = validate_ux_architecture(_contract(tmp_path, data))
    assert any("S-9" in p and "journey" in p for p in problems)


def test_screen_state_outside_the_vocabulary_is_refused(
    tmp_path: Path, data: dict[str, Any]
) -> None:
    data["screens"][0]["states"].append("hyperspace")
    problems = validate_ux_architecture(_contract(tmp_path, data))
    assert any("hyperspace" in p for p in problems)


def test_screen_without_an_error_state_is_refused(tmp_path: Path, data: dict[str, Any]) -> None:
    """Error and recovery states are mandatory per screen (PD-V3 capability 2):
    a screen that cannot show failure hides it."""
    data["screens"][2]["states"] = ["empty", "loading", "success"]
    problems = validate_ux_architecture(_contract(tmp_path, data))
    assert any("S-3" in p and "error" in p for p in problems)


def test_vocabulary_state_no_screen_declares_is_refused(
    tmp_path: Path, data: dict[str, Any]
) -> None:
    """A vocabulary state no screen uses is an unimplementable promise."""
    data["ui_states"].append("celebration")
    problems = validate_ux_architecture(_contract(tmp_path, data))
    assert any("celebration" in p for p in problems)


def test_problems_accumulate(tmp_path: Path, data: dict[str, Any]) -> None:
    data["primary_journey"][0]["screen_id"] = "S-404"
    data["screens"][0]["states"].append("hyperspace")
    assert len(validate_ux_architecture(_contract(tmp_path, data))) >= 2


# --- the validated-journey record (fail-closed precondition) -------------------------------


def test_record_then_require_round_trips(tmp_path: Path, data: dict[str, Any]) -> None:
    contract = _contract(tmp_path, data)
    run_dir = tmp_path / "run"
    record_validated_journey(run_dir, contract)
    require_validated_journey(run_dir, contract.digest)  # does not raise


def test_recording_an_incoherent_journey_is_refused(tmp_path: Path, data: dict[str, Any]) -> None:
    data["primary_journey"][0]["screen_id"] = "S-404"
    contract = _contract(tmp_path, data)
    with pytest.raises(JourneyNotValidated, match="S-404"):
        record_validated_journey(tmp_path / "run", contract)
    assert not (tmp_path / "run" / "ux-architecture.json").exists()


def test_require_fails_closed_without_a_record(tmp_path: Path) -> None:
    with pytest.raises(JourneyNotValidated, match="no validated UX architecture"):
        require_validated_journey(tmp_path / "run", "sha256:abc")


def test_require_fails_closed_on_contract_mismatch(tmp_path: Path, data: dict[str, Any]) -> None:
    """A journey validated for one contract version proves nothing about another."""
    contract = _contract(tmp_path, data)
    run_dir = tmp_path / "run"
    record_validated_journey(run_dir, contract)
    with pytest.raises(JourneyNotValidated, match="different contract"):
        require_validated_journey(run_dir, "sha256:someothercontract")


def test_record_captures_the_screen_and_state_inventory(
    tmp_path: Path, data: dict[str, Any]
) -> None:
    contract = _contract(tmp_path, data)
    run_dir = tmp_path / "run"
    record_validated_journey(run_dir, contract)
    record = json.loads((run_dir / "ux-architecture.json").read_text())
    assert record["contract_digest"] == contract.digest
    assert [s["screen_id"] for s in record["screens"]] == ["S-1", "S-2", "S-3"]
    assert record["journey"][0]["step_id"] == "J-1"
    assert record["ui_states"] == list(contract.ui_states)
