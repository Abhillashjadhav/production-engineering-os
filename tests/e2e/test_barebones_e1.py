from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pmpe.barebones import RunState, run_to_release_ready


class E1Provider:
    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        if purpose == "code":
            return {
                "request_digest": request["request_digest"],
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
