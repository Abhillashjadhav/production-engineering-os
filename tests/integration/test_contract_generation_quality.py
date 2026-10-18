from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from pmpe.barebones import BudgetCaps, ContractInvalidError, RunState, run_to_release_ready


def contract() -> dict[str, Any]:
    return {
        "contract_id": "PMOS-QUALITY",
        "functional_requirements": {"FR-001": {"statement": "health reports ok"}},
        "acceptance_criteria": {"AC-001": {
            "requirement_refs": ["FR-001"],
            "given": [{"path": "service.running", "operator": "eq", "value": True}],
            "when": {"action": "health", "arguments": {}},
            "then": [{"path": "result.status", "operator": "eq", "value": "ok"}],
        }},
    }


class Provider:
    def __init__(self, *, repair: bool = False) -> None:
        self.requests: list[Mapping[str, Any]] = []
        self.review: Mapping[str, Any] = {}
        self.repair = repair

    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        if purpose == "advisory_review":
            self.review = request
            return {"request_digest": request["request_digest"], "summary": "source inspected"}
        self.requests.append(request)
        bad_type = not self.repair or len(self.requests) == 1
        value = '"wrong"' if bad_type else "1"
        return {
            "request_digest": request["request_digest"],
            "files": {"product.py": (
                'def health() -> dict[str, str]:\n    return {"status": "ok"}\n\n\n'
                f"def count() -> int:\n    return {value}\n"
            )},
        }


def test_passing_behavior_cannot_hide_type_defect(tmp_path: Path) -> None:
    result = run_to_release_ready(
        contract=contract(), repository_root=tmp_path, workspace=tmp_path / "candidate",
        run_id="quality-failure", provider=Provider(), enforce_quality=True,
        budget=BudgetCaps(max_attempts=1),
    )
    assert result.state is RunState.HALTED
    events = [json.loads(line) for line in result.evidence_path.read_text().splitlines()]
    quality = next(e for e in events if e["event_type"] == "generated_quality_checked")
    assert quality["payload"]["passed"] is False
    assert not any(e["event_type"] == "release_ready" for e in events)


def test_repair_uses_policy_and_review_receives_actual_source(tmp_path: Path) -> None:
    provider = Provider(repair=True)
    result = run_to_release_ready(
        contract=contract(), repository_root=tmp_path, workspace=tmp_path / "candidate",
        run_id="quality-repair", provider=provider, enforce_quality=True,
    )
    assert result.state is RunState.RELEASE_READY
    assert result.attempts == 2
    assert provider.requests[0]["generation_policy"]["profile"] == "python-stdlib-quality/v1"
    assert any(f["subject_id"] == "quality:types" for f in provider.requests[1]["findings"])
    assert "def count() -> int" in provider.review["files"]["product.py"]
    assert provider.review["contract"] == contract()
    events = [json.loads(line) for line in result.evidence_path.read_text().splitlines()]
    assert events[-1]["payload"]["quality"]["passed"] is True
    assert events[-1]["payload"]["quality"]["candidate_digest"]


def test_missing_tools_stop_before_any_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = Provider()
    monkeypatch.setattr("pmpe.quality.generated_python._tool_available", lambda name: False)
    with pytest.raises(ContractInvalidError, match="CHECKER_UNAVAILABLE"):
        run_to_release_ready(
            contract=contract(), repository_root=tmp_path, workspace=tmp_path / "candidate",
            run_id="missing-tools", provider=provider, enforce_quality=True,
        )
    assert not provider.requests


def test_cli_enables_quality_without_an_extra_user_flag() -> None:
    import inspect

    from pmpe.cli.barebones_cmd import _run

    # Behavioral CLI invocation remains covered by test_barebones_cli; this checks
    # that its public entry path does not silently use the compatibility default.
    assert "enforce_quality=True" in inspect.getsource(_run)
