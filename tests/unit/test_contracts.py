"""PD-03: the ProductDecisionContract is versioned, digest-locked, and immutable
within a run; product changes flow through ProductChangeRequests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pmpe.contracts import (
    ContractStore,
    ContractViolation,
    canonical_digest,
    diff_contracts,
    load_contract,
)
from pmpe.contracts.change_request import ChangeRequestStore
from pmpe.domain.errors import SpecError

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "v2" / "contract_approved.json"


@pytest.fixture()
def contract_data() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text())


def _write(tmp_path: Path, data: dict[str, Any], name: str = "contract.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(data, indent=2))
    return path


# --- loading and semantic rules -------------------------------------------------------


def test_approved_contract_loads(contract_data: dict[str, Any], tmp_path: Path) -> None:
    contract = load_contract(_write(tmp_path, contract_data))
    assert contract.contract_id == "PDC-TEST-001"
    assert contract.contract_version == 1
    assert contract.runnable, contract.blockers


def test_missing_required_field_is_rejected(contract_data: dict[str, Any], tmp_path: Path) -> None:
    del contract_data["problem"]
    with pytest.raises(SpecError, match="problem"):
        load_contract(_write(tmp_path, contract_data))


def test_duplicate_json_member_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "duplicate.json"
    source.write_text('{"contract_id":"PDC-A","contract_id":"PDC-B"}')
    with pytest.raises(SpecError, match="duplicate object member"):
        load_contract(source)


def test_duplicate_release_gate_id_is_rejected(
    contract_data: dict[str, Any], tmp_path: Path
) -> None:
    duplicate = dict(contract_data["binary_release_gates"][0])
    duplicate["description"] = "A different gate hidden behind the same identifier."
    contract_data["binary_release_gates"].append(duplicate)
    with pytest.raises(SpecError, match="binary_release_gates: duplicate id"):
        load_contract(_write(tmp_path, contract_data))


def test_unsafe_contract_id_is_rejected(contract_data: dict[str, Any], tmp_path: Path) -> None:
    contract_data["contract_id"] = "../../outside-registry"
    with pytest.raises(SpecError, match="contract_id"):
        load_contract(_write(tmp_path, contract_data))


def test_draft_contract_is_not_runnable(contract_data: dict[str, Any], tmp_path: Path) -> None:
    contract_data["contract_status"] = "DRAFT"
    contract = load_contract(_write(tmp_path, contract_data))
    assert not contract.runnable
    assert any("APPROVED" in b for b in contract.blockers)


def test_approved_without_approver_is_not_runnable(
    contract_data: dict[str, Any], tmp_path: Path
) -> None:
    contract_data["approved_by"] = ""
    contract = load_contract(_write(tmp_path, contract_data))
    assert not contract.runnable


def test_unresolved_product_critical_question_blocks(
    contract_data: dict[str, Any], tmp_path: Path
) -> None:
    contract_data["unresolved_questions"] = [
        {"id": "Q-001", "question": "Is the endpoint public?", "product_critical": True}
    ]
    contract = load_contract(_write(tmp_path, contract_data))
    assert not contract.runnable
    assert any("Q-001" in b for b in contract.blockers)


def test_non_critical_question_does_not_block(
    contract_data: dict[str, Any], tmp_path: Path
) -> None:
    contract_data["unresolved_questions"] = [
        {"id": "Q-002", "question": "Logo color?", "product_critical": False}
    ]
    contract = load_contract(_write(tmp_path, contract_data))
    assert contract.runnable


# --- canonical digest -----------------------------------------------------------------


def test_digest_is_stable_across_key_order_and_whitespace(
    contract_data: dict[str, Any],
) -> None:
    reordered = json.loads(json.dumps(contract_data, sort_keys=True))
    shuffled = dict(reversed(list(reordered.items())))
    assert canonical_digest(contract_data) == canonical_digest(shuffled)


def test_digest_changes_on_any_field_change(contract_data: dict[str, Any]) -> None:
    before = canonical_digest(contract_data)
    contract_data["acceptance_criteria"][0]["criterion"] += " (changed)"
    assert canonical_digest(contract_data) != before


# --- immutability within a run (fail closed) ------------------------------------------


def test_locked_contract_mutation_fails_closed(
    contract_data: dict[str, Any], tmp_path: Path
) -> None:
    source = _write(tmp_path, contract_data)
    run_dir = tmp_path / "run"
    store = ContractStore(tmp_path / "registry")
    locked = store.lock_for_run(source, run_dir)
    assert locked.digest == canonical_digest(contract_data)

    store.verify_unchanged(run_dir)  # untouched -> fine

    tampered = json.loads((run_dir / "contract.json").read_text())
    tampered["scope"].append("Sneaky new scope")
    (run_dir / "contract.json").write_text(json.dumps(tampered))
    with pytest.raises(ContractViolation):
        store.verify_unchanged(run_dir)


def test_lock_refuses_non_runnable_contract(contract_data: dict[str, Any], tmp_path: Path) -> None:
    contract_data["contract_status"] = "DRAFT"
    source = _write(tmp_path, contract_data)
    store = ContractStore(tmp_path / "registry")
    with pytest.raises(ContractViolation, match="APPROVED"):
        store.lock_for_run(source, tmp_path / "run")


# --- versioning: changed contract is a new version, never an overwrite ----------------


def test_registering_same_version_with_different_content_fails(
    contract_data: dict[str, Any], tmp_path: Path
) -> None:
    store = ContractStore(tmp_path / "registry")
    store.register(_write(tmp_path, contract_data, "v1.json"))
    contract_data["scope"].append("More scope")
    with pytest.raises(ContractViolation, match="new version"):
        store.register(_write(tmp_path, contract_data, "v1b.json"))


def test_registering_identical_content_is_idempotent(
    contract_data: dict[str, Any], tmp_path: Path
) -> None:
    store = ContractStore(tmp_path / "registry")
    first = store.register(_write(tmp_path, contract_data, "a.json"))
    second = store.register(_write(tmp_path, contract_data, "b.json"))
    assert first.digest == second.digest


def test_registry_and_approval_use_one_rfc8785_numeric_digest(
    contract_data: dict[str, Any], tmp_path: Path
) -> None:
    contract_data["metadata"] = {"numeric_value": 1.0}
    source = _write(tmp_path, contract_data)
    record = ContractStore(tmp_path / "registry").register(source)
    from pmpe.contracts.canonical import canonical_digest as approval_digest

    assert record.digest == approval_digest(contract_data)


def test_new_version_registers_cleanly(contract_data: dict[str, Any], tmp_path: Path) -> None:
    store = ContractStore(tmp_path / "registry")
    store.register(_write(tmp_path, contract_data, "v1.json"))
    contract_data["contract_version"] = 2
    contract_data["scope"].append("More scope")
    record = store.register(_write(tmp_path, contract_data, "v2.json"))
    assert record.version == 2
    assert len(store.versions("PDC-TEST-001")) == 2


def test_diff_reports_requirement_level_changes(
    contract_data: dict[str, Any], tmp_path: Path
) -> None:
    old = _write(tmp_path, contract_data, "old.json")
    new_data = json.loads(json.dumps(contract_data))
    new_data["contract_version"] = 2
    new_data["functional_requirements"].append(
        {"id": "FR-002", "title": "Uptime history", "description": "...", "capability": ""}
    )
    new_data["scope"][0] = "Health endpoint with latency"
    new = _write(tmp_path, new_data, "new.json")
    delta = diff_contracts(old, new)
    assert "FR-002" in " ".join(delta.added)
    assert any("scope" in c for c in delta.changed)
    assert delta.old_digest != delta.new_digest


# --- ProductChangeRequest --------------------------------------------------------------


def test_change_request_lifecycle(contract_data: dict[str, Any], tmp_path: Path) -> None:
    store = ChangeRequestStore(tmp_path / "run")
    pcr = store.create(
        source_contract_id="PDC-TEST-001",
        source_contract_version=1,
        affected_requirement_ids=["FR-001"],
        engineering_finding="Health body shape conflicts with AC-001 wording.",
        reason="Cannot implement both interpretations safely.",
        options=["Return status only", "Return status + uptime"],
        engineering_consequences="Journey verification differs per option.",
        recommended_technical_default="Return status only",
        decision_owner="abhillash",
    )
    assert pcr.request_id == "PCR-001"
    assert pcr.status == "OPEN"

    second = store.create(
        source_contract_id="PDC-TEST-001",
        source_contract_version=1,
        affected_requirement_ids=["FR-001"],
        engineering_finding="Another conflict.",
        reason="r",
        options=["a"],
        engineering_consequences="c",
        recommended_technical_default="a",
        decision_owner="abhillash",
    )
    assert second.request_id == "PCR-002"

    approved = store.decide("PCR-001", status="APPROVED", resulting_contract_version=2)
    assert approved.resulting_contract_version == 2
    listed = store.list()
    assert [p.request_id for p in listed] == ["PCR-001", "PCR-002"]
    assert listed[0].status == "APPROVED"


def test_approving_without_resulting_version_fails_closed(tmp_path: Path) -> None:
    store = ChangeRequestStore(tmp_path / "run")
    pcr = store.create(
        source_contract_id="PDC-TEST-001",
        source_contract_version=1,
        affected_requirement_ids=["FR-001"],
        engineering_finding="f",
        reason="r",
        options=["a", "b"],
        engineering_consequences="c",
        recommended_technical_default="a",
        decision_owner="abhillash",
    )
    with pytest.raises(ContractViolation, match="resulting contract version"):
        store.decide(pcr.request_id, status="APPROVED")
    assert store.get(pcr.request_id).status == "OPEN"


def test_change_requests_survive_reload(tmp_path: Path) -> None:
    store = ChangeRequestStore(tmp_path / "run")
    store.create(
        source_contract_id="PDC-X",
        source_contract_version=1,
        affected_requirement_ids=[],
        engineering_finding="f",
        reason="r",
        options=["o"],
        engineering_consequences="c",
        recommended_technical_default="o",
        decision_owner="own",
    )
    reloaded = ChangeRequestStore(tmp_path / "run").list()
    assert len(reloaded) == 1 and reloaded[0].request_id == "PCR-001"
