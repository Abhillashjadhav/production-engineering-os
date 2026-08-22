from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from pmpe.barebones import RunState, run_to_release_ready
from pmpe.contracts.acceptance import AcceptanceCompileError


def _contract() -> dict[str, Any]:
    return {
        "contract_id": "PMOS-EVAL",
        "functional_requirements": {"FR-001": {"statement": "health reports ok"}},
        "acceptance_criteria": {
            "AC-001": {
                "requirement_refs": ["FR-001"],
                "given": [{"path": "service.running", "operator": "eq", "value": True}],
                "when": {"action": "health", "arguments": {}},
                "then": [{"path": "result.status", "operator": "eq", "value": "ok"}],
            }
        },
    }


class PassingProvider:
    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        if purpose == "code":
            return {
                "request_digest": request["request_digest"],
                "files": {
                    "product.py": ('def health() -> dict[str, str]:\n    return {"status": "ok"}\n')
                },
            }
        return {"request_digest": request["request_digest"], "summary": "advisory only"}


class UnsuccessfulProvider:
    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        assert purpose == "code"
        return {
            "request_digest": request["request_digest"],
            "files": {
                "product.py": (
                    'def health() -> dict[str, str]:\n    return {"status": "not_implemented"}\n'
                )
            },
        }


class StaleResponseProvider:
    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"request_digest": "sha256:" + "0" * 64, "files": {}}


class SyntaxRepairProvider:
    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        if purpose == "advisory_review":
            return {"request_digest": request["request_digest"], "summary": "advisory"}
        self.calls += 1
        content = (
            "def health(:\n"
            if self.calls == 1
            else "def health() -> dict[str, str]:\n    return {'status': 'ok'}\n"
        )
        return {
            "request_digest": request["request_digest"],
            "files": {"product.py": content},
        }


def test_e2_unsatisfiable_run_halts_with_exact_requirement(tmp_path: Path) -> None:
    result = run_to_release_ready(
        contract=_contract(),
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="e2-unsatisfiable",
        provider=UnsuccessfulProvider(),
    )

    assert result.state is RunState.HALTED
    assert result.cause == "REPEAT_FINDING_WITHOUT_RELEVANT_CHANGE:AC-001"


def test_e3_stale_model_response_is_detected_as_drift(tmp_path: Path) -> None:
    result = run_to_release_ready(
        contract=_contract(),
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="e3-prompt-drift",
        provider=StaleResponseProvider(),
    )

    assert result.state is RunState.HALTED
    assert result.cause == "MODEL_RESPONSE_UNBOUND"


def test_coder_can_repair_a_candidate_syntax_failure(tmp_path: Path) -> None:
    result = run_to_release_ready(
        contract=_contract(),
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="syntax-repair",
        provider=SyntaxRepairProvider(),
    )

    assert result.state is RunState.RELEASE_READY
    assert result.attempts == 2


def test_e4_contradiction_stops_before_build(tmp_path: Path) -> None:
    contract = _contract()
    criterion = contract["acceptance_criteria"]["AC-001"]
    criterion["given"].append({"path": "service.running", "operator": "eq", "value": False})
    workspace = tmp_path / "candidate"

    with pytest.raises(AcceptanceCompileError):
        run_to_release_ready(
            contract=contract,
            repository_root=tmp_path,
            workspace=workspace,
            run_id="e4-contradiction",
            provider=PassingProvider(),
        )

    assert not workspace.exists()


def test_e5_repeated_runs_produce_identical_evidence(tmp_path: Path) -> None:
    roots = (tmp_path / "first", tmp_path / "second")
    event_logs: list[bytes] = []
    for root in roots:
        result = run_to_release_ready(
            contract=_contract(),
            repository_root=root,
            workspace=root / "candidate",
            run_id="e5-repeat",
            provider=PassingProvider(),
        )
        assert result.state is RunState.RELEASE_READY
        event_logs.append(result.evidence_path.read_bytes())

    assert event_logs[0] == event_logs[1]


def test_human_authored_escape_hatch_is_executable_and_protected(tmp_path: Path) -> None:
    test_file = tmp_path / "tests/acceptance/test_health.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        "from product import health\n\ndef test_health():\n    assert health()['status'] == 'ok'\n"
    )
    contract = _contract()
    contract["acceptance_criteria"]["AC-001"] = {
        "requirement_refs": ["FR-001"],
        "human_test": {
            "path": "tests/acceptance/test_health.py",
            "node_id": "test_health",
            "command": [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/acceptance/test_health.py::test_health",
            ],
        },
    }

    result = run_to_release_ready(
        contract=contract,
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="human-test",
        provider=PassingProvider(),
    )

    assert result.state is RunState.RELEASE_READY


class TamperingProvider:
    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        return {
            "request_digest": request["request_digest"],
            "files": {"tests/acceptance/test_health.py": "def test_health(): assert True\n"},
        }


def test_coder_cannot_rewrite_human_authored_evidence(tmp_path: Path) -> None:
    test_file = tmp_path / "tests/acceptance/test_health.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_health():\n    assert False\n")
    contract = _contract()
    contract["acceptance_criteria"]["AC-001"] = {
        "requirement_refs": ["FR-001"],
        "human_test": {
            "path": "tests/acceptance/test_health.py",
            "node_id": "test_health",
            "command": [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/acceptance/test_health.py::test_health",
            ],
        },
    }

    result = run_to_release_ready(
        contract=contract,
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="human-test-tamper",
        provider=TamperingProvider(),
    )

    assert result.state is RunState.HALTED
    assert result.cause == "CODER_MODIFIED_EVIDENCE"
