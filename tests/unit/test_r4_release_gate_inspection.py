"""Unsigned retained mutations must remain internally consistent to be inspectable."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from pmpe.cli import main
from pmpe.contracts.canonical import canonical_digest, canonical_json_bytes
from pmpe.evidence.ledger import GENESIS_DIGEST, EvidenceLedger
from tests.unit.test_release_gate_inspection import _packet


def _rechain(ledger: EvidenceLedger, events: list[dict[str, Any]]) -> None:
    previous = GENESIS_DIGEST
    for sequence, event in enumerate(events, 1):
        event.update(sequence=sequence, previous_digest=previous)
        event["blob_digests"] = sorted(set(event["blob_digests"]))
        event.pop("event_digest", None)
        event["event_digest"] = canonical_digest(event)
        previous = event["event_digest"]
    ledger.events_path.write_bytes(b"".join(canonical_json_bytes(event) + b"\n" for event in events))
    assert len(tuple(ledger.verify())) == len(events)


def _replace_blob(
    ledger: EvidenceLedger, event: dict[str, Any], old: str, value: dict[str, Any]
) -> str:
    new = ledger.put_blob(canonical_json_bytes(value))
    event["blob_digests"] = [new if item == old else item for item in event["blob_digests"]]
    return new


def _mutated_packet(root: Path, mutation: str) -> None:
    gated = not mutation.startswith("ungated-")
    _packet(root, gated=gated)
    ledger = EvidenceLedger.open_existing(root, "inspection")
    # Mutations deliberately rebuild the hash chain without possessing an
    # external original head. Semantic validation must catch the contradiction.
    writer = EvidenceLedger.__new__(EvidenceLedger)
    writer.__dict__.update(ledger.__dict__, _read_only=False)
    events = [dict(event) for event in ledger.verify()]
    validation, terminal = events[0], events[-1]
    metadata = validation["payload"]
    if mutation in {"authority", "halted-authority"}:
        metadata["approval"]["authority"] = "contradictory-fixture-authority"
        if mutation == "halted-authority":
            terminal.update(event_type="halted", state="HALTED")
    elif mutation == "deleted-gate-key":
        old = metadata["contract_digest"]
        contract = json.loads(ledger.read_blob(old))
        contract.pop("binary_release_gates")
        metadata["contract_digest"] = _replace_blob(writer, validation, old, contract)
        gate = next(event for event in events if event["event_type"] == "release_gates_evaluated")
        events.remove(gate)
        terminal["payload"].pop("release_gate_evidence_digest")
    elif mutation == "ungated-subject":
        validation["subject_digest"] = "sha256:" + "f" * 64
        terminal["subject_digest"] = validation["subject_digest"]
    elif mutation == "ungated-plan":
        excluded = {metadata["contract_digest"], metadata["approval"]["receipt_blob_digest"]}
        old = next(blob for blob in validation["blob_digests"] if blob not in excluded)
        plan = json.loads(ledger.read_blob(old))
        plan["criteria"] = []
        plan["plan_digest"] = canonical_digest(
            {key: value for key, value in plan.items() if key != "plan_digest"}
        )
        _replace_blob(writer, validation, old, plan)
        metadata["plan_digest"] = plan["plan_digest"]
    elif mutation == "ungated-receipt":
        approval = metadata["approval"]
        old = approval["receipt_blob_digest"]
        receipt = json.loads(ledger.read_blob(old))
        receipt["approved_contract_digest"] = "sha256:" + "f" * 64
        receipt["receipt_digest"] = canonical_digest(
            {key: value for key, value in receipt.items() if key != "receipt_digest"}
        )
        approval["receipt_blob_digest"] = _replace_blob(writer, validation, old, receipt)
        approval["receipt_digest"] = receipt["receipt_digest"]
    elif mutation in {"failed-then-pass", "failed-event-then-pass", "duplicate-pass"}:
        gate = next(event for event in events if event["event_type"] == "release_gates_evaluated")
        earlier = copy.deepcopy(gate)
        if mutation != "duplicate-pass":
            earlier["payload"]["gates"][0]["status"] = "FAIL"
            earlier["payload"]["gates"][0]["criterion_results"][0]["status"] = "FAIL"
        earlier["blob_digests"].append(writer.put_blob(canonical_json_bytes(earlier["payload"])))
        events.insert(events.index(gate), earlier)
        if mutation == "failed-event-then-pass":
            failure = copy.deepcopy(earlier)
            failure.update(event_type="verification_failed", state="BUILDING")
            failure["payload"] = {"attempt": 1, "findings": ["seeded failure"]}
            events.insert(events.index(gate), failure)
    elif mutation in {"unknown-event", "ungated-unknown", "ungated-failure"}:
        event = copy.deepcopy(terminal)
        event.update(
            event_type="verification_failed" if mutation == "ungated-failure" else "unknown_event",
            state="VERIFYING",
            payload={"attempt": 1},
        )
        events.insert(-1, event)
    elif mutation == "missing-start":
        events = [event for event in events if event["event_type"] != "verification_started"]
    elif mutation == "coder-attempt":
        next(event for event in events if event["event_type"] == "coder_completed")["payload"][
            "attempt"
        ] = 2
    else:
        raise AssertionError(mutation)
    _rechain(writer, events)


@pytest.mark.parametrize("command", ["status", "evidence", "inspect"])
@pytest.mark.parametrize(
    "mutation",
    [
        "authority",
        "deleted-gate-key",
        "ungated-subject",
        "ungated-plan",
        "ungated-receipt",
        "failed-then-pass",
        "failed-event-then-pass",
        "duplicate-pass",
        "unknown-event",
        "ungated-unknown",
        "ungated-failure",
        "missing-start",
        "coder-attempt",
    ],
)
def test_r4_contradictions_are_rejected_without_an_external_head(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], mutation: str, command: str
) -> None:
    _mutated_packet(tmp_path, mutation)
    assert main(["barebones", command, "inspection", "--repository-root", str(tmp_path)]) == 3
    assert json.loads(capsys.readouterr().out)["cause"] == "EVIDENCE_INVALID"


@pytest.mark.parametrize("command", ["status", "evidence"])
def test_r4_halted_approval_is_also_reverified(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    _mutated_packet(tmp_path, "halted-authority")
    assert main(["barebones", command, "inspection", "--repository-root", str(tmp_path)]) == 3
    assert json.loads(capsys.readouterr().out)["cause"] == "EVIDENCE_INVALID"


def test_r4_status_does_not_trust_release_ready_state_on_an_unknown_event(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _packet(tmp_path)
    ledger = EvidenceLedger.open_existing(tmp_path, "inspection")
    events = [dict(event) for event in ledger.verify()]
    override = copy.deepcopy(events[-1])
    override["event_type"] = "operator_override"
    events.append(override)
    _rechain(ledger, events)
    assert main(["barebones", "status", "inspection", "--repository-root", str(tmp_path)]) == 3
    assert json.loads(capsys.readouterr().out)["cause"] == "EVIDENCE_INVALID"


@pytest.mark.parametrize("command", ["status", "evidence", "inspect"])
def test_r4_head_anchor_is_explicit_and_a_genuine_original_head_rejects_rewrite(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    original, rewritten = tmp_path / "original", tmp_path / "rewritten"
    original.mkdir()
    rewritten.mkdir()
    original_head, _ = _packet(original)
    rewritten_head, _ = _packet(rewritten, form="rewritten-contract")
    assert original_head != rewritten_head
    args = ["barebones", command, "inspection", "--repository-root", str(rewritten)]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["head_anchor"] == {"status": "NOT_PROVIDED"}
    assert main([*args, "--expected-head-digest", original_head]) == 3
    assert "expected head" in json.loads(capsys.readouterr().out)["detail"]
    assert main([*args, "--expected-head-digest", rewritten_head]) == 0
    assert json.loads(capsys.readouterr().out)["head_anchor"] == {
        "status": "VERIFIED",
        "expected_head_digest": rewritten_head,
    }
