from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from pmpe import barebones
from pmpe.barebones import BudgetCaps, RunState, run_to_release_ready
from pmpe.contracts.acceptance import AcceptanceCompileError
from pmpe.evidence.ledger import EvidenceLedger


class _TestOnlyProvider:
    def __init__(self, status: str = "ok") -> None:
        self.status = status
        self.calls = 0

    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls += 1
        return {
            "request_digest": request["request_digest"],
            "files": {"product.py": f"def health():\n    return {{'status': {self.status!r}}}\n"},
        }


def _contract() -> dict[str, Any]:
    path = Path(__file__).parents[2] / "examples/barebones/e1-contract.json"
    contract: dict[str, Any] = json.loads(path.read_text())
    contract["contract_id"] = "TEST-ONLY-BOUND-RELEASE-GATE"
    contract["binary_release_gates"] = [
        {
            "id": "GATE-001",
            "description": "TEST ONLY: health acceptance must pass.",
            "acceptance_criterion_refs": ["AC-001"],
        }
    ]
    return contract


@pytest.mark.parametrize("status", ["ok", "broken"])
def test_every_bound_gate_has_snapshot_bound_runtime_evidence(tmp_path: Path, status: str) -> None:
    result = run_to_release_ready(
        contract=_contract(),
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="test-only-gates",
        provider=_TestOnlyProvider(status),
        budget=BudgetCaps(max_attempts=1),
    )
    assert result.state is (RunState.RELEASE_READY if status == "ok" else RunState.HALTED)
    ledger = EvidenceLedger.open_existing(tmp_path, result.run_id)
    events = list(ledger.verify())
    gate_events = [event for event in events if event["event_type"] == "release_gates_evaluated"]
    assert len(gate_events) == 1
    evidence = gate_events[0]["payload"]
    assert evidence["plan_digest"].startswith("sha256:")
    assert evidence["candidate_digest"] in gate_events[0]["blob_digests"]
    assert evidence["contract_digest"] == gate_events[0]["subject_digest"]
    gate = evidence["gates"][0]
    assert gate["gate_id"] == "GATE-001"
    assert gate["acceptance_criterion_refs"] == ["AC-001"]
    assert gate["status"] == ("PASS" if status == "ok" else "FAIL")
    assert gate["criterion_results"][0]["criterion_id"] == "AC-001"
    assert gate["criterion_results"][0]["status"] == gate["status"]
    if status == "ok":
        assert events[-1]["payload"]["release_gate_evidence_digest"] in events[-1]["blob_digests"]
    else:
        assert all(event["event_type"] != "release_ready" for event in events)


def test_unbound_gate_fails_before_provider_or_workspace(tmp_path: Path) -> None:
    contract = _contract()
    del contract["binary_release_gates"][0]["acceptance_criterion_refs"]
    provider = _TestOnlyProvider()
    with pytest.raises(AcceptanceCompileError):
        run_to_release_ready(
            contract=contract,
            repository_root=tmp_path,
            workspace=tmp_path / "candidate",
            run_id="unbound-test-only",
            provider=provider,
        )
    assert provider.calls == 0
    assert not (tmp_path / "candidate").exists()
    assert not (tmp_path / ".pmpe").exists()


def test_missing_criterion_outcome_is_not_inferred_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = barebones._verify_snapshot

    def lose_outcomes(*args: Any, **kwargs: Any) -> Any:
        kwargs.pop("criterion_results", None)
        return original(*args, **kwargs)

    monkeypatch.setattr(barebones, "_verify_snapshot", lose_outcomes)
    result = run_to_release_ready(
        contract=_contract(),
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="missing-outcome",
        provider=_TestOnlyProvider(),
        budget=BudgetCaps(max_attempts=1),
    )
    assert result.state is RunState.HALTED
    events = list(EvidenceLedger.open_existing(tmp_path, result.run_id).verify())
    evidence = next(event for event in events if event["event_type"] == "release_gates_evaluated")
    assert evidence["payload"]["gates"][0]["status"] == "NOT_EVALUATED"
    assert all(event["event_type"] != "release_ready" for event in events)
