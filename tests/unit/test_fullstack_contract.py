"""PD-V3: the typed FullStackProductContract — approved-only runnability,
digest exposure, structural id uniqueness. Cross-reference journey rules are
the UX architecture stage's job (V3 PR 3), not the loader's."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pmpe.domain.errors import SpecError
from pmpe.fullstack.contract import load_fullstack_contract

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "tests" / "fixtures" / "v3" / "fullstack_contract_approved.json"


@pytest.fixture()
def data() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(EXAMPLE.read_text())
    return loaded


def _write(tmp_path: Path, data: dict[str, Any]) -> Path:
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(data))
    return path


def test_approved_example_round_trips(tmp_path: Path, data: dict[str, Any]) -> None:
    contract = load_fullstack_contract(_write(tmp_path, data))
    assert contract.contract_id == "FSC-PMEVALS-001"
    assert contract.runnable and contract.blockers == []
    assert [s.step_id for s in contract.primary_journey][:2] == ["J-1", "J-2"]
    assert contract.screen("S-2") is not None
    assert contract.screen("S-2").states == ("loading", "error", "success", "insufficient-evidence")
    assert contract.deployment_target.kind == "containerized_preview"
    assert contract.digest.startswith("sha256:")
    assert contract.raw == data


def test_digest_is_key_order_independent(tmp_path: Path, data: dict[str, Any]) -> None:
    reordered = {k: data[k] for k in sorted(data, reverse=True)}
    a = load_fullstack_contract(_write(tmp_path, data)).digest
    b = load_fullstack_contract(_write(tmp_path, reordered)).digest
    assert a == b


def test_draft_contract_is_not_runnable(tmp_path: Path, data: dict[str, Any]) -> None:
    data["contract_status"] = "DRAFT"
    contract = load_fullstack_contract(_write(tmp_path, data))
    assert not contract.runnable
    assert any("DRAFT" in b for b in contract.blockers)


def test_missing_approver_blocks(tmp_path: Path, data: dict[str, Any]) -> None:
    data["approved_by"] = "  "
    contract = load_fullstack_contract(_write(tmp_path, data))
    assert any("approver" in b for b in contract.blockers)


def test_blocking_unresolved_question_blocks(tmp_path: Path, data: dict[str, Any]) -> None:
    data["unresolved_questions"] = [
        {"id": "Q-1", "question": "Should reports include model config?", "blocking": True}
    ]
    contract = load_fullstack_contract(_write(tmp_path, data))
    assert any("Q-1" in b for b in contract.blockers)

    data["unresolved_questions"][0]["resolution"] = "No — deferred to V2 of the product."
    resolved = load_fullstack_contract(_write(tmp_path, data))
    assert resolved.runnable


def test_non_blocking_question_does_not_block(tmp_path: Path, data: dict[str, Any]) -> None:
    data["unresolved_questions"] = [
        {"id": "Q-2", "question": "Nice-to-have chart style?", "blocking": False}
    ]
    assert load_fullstack_contract(_write(tmp_path, data)).runnable


def test_duplicate_screen_id_is_rejected(tmp_path: Path, data: dict[str, Any]) -> None:
    data["screens"].append(dict(data["screens"][0]))
    with pytest.raises(SpecError, match="duplicate screen_id"):
        load_fullstack_contract(_write(tmp_path, data))


def test_duplicate_journey_step_id_is_rejected(tmp_path: Path, data: dict[str, Any]) -> None:
    data["primary_journey"].append(dict(data["primary_journey"][0]))
    with pytest.raises(SpecError, match="duplicate step_id"):
        load_fullstack_contract(_write(tmp_path, data))


def test_malformed_json_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{not json")
    with pytest.raises(SpecError, match="cannot read"):
        load_fullstack_contract(path)


def test_schema_violation_is_rejected(tmp_path: Path, data: dict[str, Any]) -> None:
    del data["screens"]
    with pytest.raises(SpecError, match="violates the schema"):
        load_fullstack_contract(_write(tmp_path, data))
