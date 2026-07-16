"""The evidence ledger: structured, append-only, digest-bearing run events."""

from __future__ import annotations

from pathlib import Path

from pmpe.engineering.ledger import EvidenceLedger

DIGEST = "sha256:aaaa"


def test_ledger_records_structured_events(tmp_path: Path) -> None:
    ledger = EvidenceLedger(tmp_path / "run", run_id="eng-001")
    ledger.record(
        stage="architecture",
        agent="v2-system-architect",
        action="submit",
        input_digests={"contract": DIGEST},
        output_digests={"architecture_pack": "sha256:cccc"},
        verdict="accepted",
        next_state="plan",
    )
    events = ledger.read_all()
    assert len(events) == 1
    event = events[0]
    for key in (
        "run_id",
        "ts",
        "stage",
        "agent",
        "action",
        "input_digests",
        "output_digests",
        "verdict",
        "next_state",
    ):
        assert key in event, key
    assert event["run_id"] == "eng-001"


def test_ledger_is_append_only(tmp_path: Path) -> None:
    ledger = EvidenceLedger(tmp_path / "run", run_id="eng-001")
    ledger.record(stage="a", agent="x", action="one")
    ledger.record(stage="b", agent="y", action="two")
    assert [e["action"] for e in ledger.read_all()] == ["one", "two"]
