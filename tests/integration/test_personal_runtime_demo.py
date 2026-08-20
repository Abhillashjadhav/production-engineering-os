"""End-to-end offline proof for governed runtime capabilities."""

from __future__ import annotations

import json

from pmpe.cli import main
from pmpe.personal.runtime.registry import EventRegistry


def test_runtime_demo_exercises_all_controls_without_external_writes(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    output = tmp_path / "runtime"
    assert main(["personal-runtime", "quickstart", "--output", str(output)]) == 0
    assert "external writes: 0" in capsys.readouterr().out
    report = json.loads((output / "runtime-assurance-report.json").read_text())
    assert report["status"] == "COMPLETED"
    assert report["calendar"]["external_writes"] == 0
    assert report["worker"]["status"] == "COMPLETED"
    assert report["recovery"] == {
        "retry_status": "COMPLETED",
        "rollback_status": "ROLLED_BACK",
        "rollback_verified": True,
    }
    assert report["learning"] == {"installed_regression_cases": 0, "proposals": 1}
    assert len(EventRegistry(output / "runtime-events.jsonl").read()) == report["event_count"]
