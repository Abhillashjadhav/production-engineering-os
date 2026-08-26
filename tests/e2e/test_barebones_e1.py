from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pmpe.barebones import RunState, run_to_release_ready

_METADATA = {
    "provider": "scripted-fixture",
    "model": "deterministic-e1",
    "prompt_version": "e1-v1",
}


class E1Provider:
    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        if purpose == "code":
            return {
                "request_digest": request["request_digest"],
                "provider_metadata": _METADATA,
                "files": {
                    "product.py": (
                        '"""E1 health product."""\n\n'
                        "def health() -> dict[str, str]:\n"
                        '    return {"status": "ok"}\n'
                    )
                },
            }
        return {
            "request_digest": request["request_digest"],
            "summary": "Deterministic evidence passed; human may release.",
            "provider_metadata": _METADATA,
        }


class ReadinessProvider:
    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        if purpose == "code":
            return {
                "request_digest": request["request_digest"],
                "provider_metadata": _METADATA,
                "files": {
                    "product.py": (
                        '"""Readiness evidence product."""\n\n'
                        "def health() -> dict[str, object]:\n"
                        "    return {\n"
                        '        "status": "ok",\n'
                        '        "component": "readiness-api",\n'
                        '        "checks": ["contract", "sandbox"],\n'
                        "    }\n"
                    )
                },
            }
        return {
            "request_digest": request["request_digest"],
            "summary": "Deterministic readiness evidence passed.",
            "provider_metadata": _METADATA,
        }


def test_e1_real_contract_reaches_release_ready(tmp_path: Path) -> None:
    contract = {
        "contract_id": "PMOS-E1",
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

    result = run_to_release_ready(
        contract=contract,
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="e1-real-contract",
        provider=E1Provider(),
    )

    assert result.state is RunState.RELEASE_READY
    assert result.cause == "PASS"
    assert result.attempts == 1
    assert result.model_calls == 2
    assert result.evidence_path.is_file()
    assert "status" not in result.annotation
    events = [json.loads(line) for line in result.evidence_path.read_text().splitlines()]
    coder = next(event for event in events if event["event_type"] == "coder_completed")
    release = next(event for event in events if event["event_type"] == "release_ready")
    assert events[0]["payload"]["approval"]["status"] == "UNVERIFIED_DIRECT_CALL"
    assert coder["payload"]["provider_behavior"]["purpose"] == "code"
    assert release["payload"]["provider_behavior"]["purpose"] == "advisory_review"
    assert coder["payload"]["provider_behavior"]["request_digest"].startswith("sha256:")
    assert release["payload"]["provider_behavior"]["output_digest"].startswith("sha256:")


def test_materially_different_readiness_contract_reaches_release_ready(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[2]
    contract_path = root / "examples/barebones/readiness-contract.json"
    receipt_path = root / "examples/barebones/readiness-approval-receipt.json"
    contract = json.loads(contract_path.read_text())
    receipt_source = receipt_path.read_bytes()

    result = run_to_release_ready(
        contract=contract,
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="readiness-real-contract",
        provider=ReadinessProvider(),
        approval_receipt=json.loads(receipt_source),
        approval_authority="fixture-human",
        approval_receipt_bytes=receipt_source,
    )

    assert result.state is RunState.RELEASE_READY
    assert result.cause == "PASS"
    assert result.telemetry["structured_criteria_count"] == 3
    events = [json.loads(line) for line in result.evidence_path.read_text().splitlines()]
    assert events[0]["payload"]["approval"]["status"] == "VERIFIED"
