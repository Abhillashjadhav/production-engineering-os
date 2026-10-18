"""Generated quality is bound to repair, evidence, and the strict release gate."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import pytest

from pmpe.barebones import (
    BudgetCaps,
    CandidateSandbox,
    ContractInvalidError,
    RunState,
    run_to_release_ready,
)
from pmpe.evidence.ledger import EvidenceLedger
from pmpe.quality.generated_python import PythonCheck, PythonQualityReport
from tests.conftest import _LocalCandidateTestSandbox


def _contract() -> dict[str, Any]:
    return {
        "contract_id": "PMOS-QUALITY",
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


class Provider:
    def __init__(self, *, repair: bool = False, good_first: bool = False) -> None:
        self.requests: list[Mapping[str, Any]] = []
        self.review: Mapping[str, Any] | None = None
        self.repair = repair
        self.good_first = good_first

    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        if purpose == "advisory_review":
            self.review = request
            return {"request_digest": request["request_digest"], "summary": "source inspected"}
        self.requests.append(request)
        bad_type = not self.good_first and (not self.repair or len(self.requests) == 1)
        value = '"wrong"' if bad_type else "1"
        return {
            "request_digest": request["request_digest"],
            "files": {
                "product.py": (
                    'def health() -> dict[str, str]:\n    return {"status": "ok"}\n\n\n'
                    f"def count() -> int:\n    return {value}\n"
                )
            },
        }


def _events(root: Path, run_id: str) -> tuple[Mapping[str, Any], ...]:
    return tuple(EvidenceLedger.open_existing(root, run_id).verify())


def _sandbox() -> CandidateSandbox:
    return cast(CandidateSandbox, _LocalCandidateTestSandbox())


def test_type_defect_blocks_candidate_verification_despite_passing_behavior(
    tmp_path: Path,
) -> None:
    result = run_to_release_ready(
        contract=_contract(),
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="quality-failure",
        provider=Provider(),
        candidate_sandbox=_sandbox(),
        enforce_quality=True,
        budget=BudgetCaps(max_attempts=1),
    )
    assert result.state is RunState.HALTED
    assert result.cause == "ATTEMPT_BUDGET_EXHAUSTED"
    events = _events(tmp_path, result.run_id)
    quality = next(e for e in events if e["event_type"] == "generated_quality_checked")
    assert quality["payload"]["passed"] is False
    assert any(
        finding["subject_id"] == "quality:types"
        for e in events
        if e["event_type"] == "verification_failed"
        for finding in e["payload"]["findings"]
    )
    assert not any(e["event_type"] == "candidate_response_verified" for e in events)


def test_repair_policy_and_source_review_retain_provider_isolation_halt(tmp_path: Path) -> None:
    provider = Provider(repair=True)
    result = run_to_release_ready(
        contract=_contract(),
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="quality-repair",
        provider=provider,
        candidate_sandbox=_sandbox(),
        enforce_quality=True,
    )
    assert result.state is RunState.HALTED
    assert result.cause == "PROVIDER_WRITE_ISOLATION_UNVERIFIED"
    assert result.attempts == 2
    assert result.model_calls == 3
    assert provider.requests[0]["generation_policy"]["profile"] == "python-stdlib-quality/v1"
    assert any(f["subject_id"] == "quality:types" for f in provider.requests[1]["findings"])
    assert provider.review is not None
    assert "def count() -> int" in provider.review["files"]["product.py"]
    assert provider.review["contract"] == _contract()
    assert provider.review["quality"]["passed"] is True
    events = _events(tmp_path, result.run_id)
    assert len([e for e in events if e["event_type"] == "generated_quality_checked"]) == 2
    assert events[-1]["payload"]["quality"]["passed"] is True
    assert events[-1]["payload"]["quality"]["candidate_digest"]
    assert events[-1]["payload"]["provider_write_isolation"] == "UNVERIFIED_GENERIC_COMMAND"
    assert not any(e["event_type"] == "release_ready" for e in events)


def test_missing_tools_stop_before_workspace_or_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = Provider()
    monkeypatch.setattr("pmpe.quality.generated_python._tool_available", lambda name: False)
    with pytest.raises(ContractInvalidError, match="GENERATION_CHECKER_UNAVAILABLE"):
        run_to_release_ready(
            contract=_contract(),
            repository_root=tmp_path,
            workspace=tmp_path / "candidate",
            run_id="missing-tools",
            provider=provider,
            candidate_sandbox=_sandbox(),
            enforce_quality=True,
        )
    assert not provider.requests
    assert not (tmp_path / "candidate").exists()


def test_checker_diagnostic_is_privacy_checked_before_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = Provider(repair=True)

    def private_report(*_args: Any, **_kwargs: Any) -> PythonQualityReport:
        return PythonQualityReport(
            "python-stdlib-quality/v1",
            "sha256:" + "0" * 64,
            (PythonCheck("types", "FAIL", "PEOS_PRIVATE_CANARY_QUALITY"),),
        )

    monkeypatch.setattr("pmpe.barebones.check_python_candidate", private_report)
    result = run_to_release_ready(
        contract=_contract(),
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="private-diagnostic",
        provider=provider,
        candidate_sandbox=_sandbox(),
        enforce_quality=True,
    )
    assert result.state is RunState.HALTED
    assert result.cause == "MODEL_REQUEST_PRIVACY_BLOCKED"
    assert result.model_calls == 1
    assert len(provider.requests) == 1
    events = _events(tmp_path, result.run_id)
    assert not any(e["event_type"] == "generated_quality_checked" for e in events)
    assert "PEOS_PRIVATE_CANARY_QUALITY" not in result.evidence_path.read_text()


def test_review_cannot_exceed_call_budget(tmp_path: Path) -> None:
    provider = Provider(good_first=True)
    result = run_to_release_ready(
        contract=_contract(),
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="review-budget",
        provider=provider,
        candidate_sandbox=_sandbox(),
        enforce_quality=True,
        budget=BudgetCaps(max_attempts=1, max_model_calls=1),
    )
    assert result.state is RunState.HALTED
    assert result.cause == "MODEL_CALL_BUDGET_EXHAUSTED"
    assert result.model_calls == 1
    assert provider.review is None
    assert not any(
        e["event_type"] == "candidate_response_verified" for e in _events(tmp_path, result.run_id)
    )


def test_review_usage_is_charged_after_code_usage(tmp_path: Path) -> None:
    class UsageProvider(Provider):
        def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
            response = dict(super().invoke(purpose=purpose, request=request))
            response["usage"] = {"input_tokens": 7, "output_tokens": 3}
            return response

    provider = UsageProvider(good_first=True)
    result = run_to_release_ready(
        contract=_contract(),
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="review-usage",
        provider=provider,
        candidate_sandbox=_sandbox(),
        enforce_quality=True,
        budget=BudgetCaps(max_attempts=1, max_input_tokens=14, max_output_tokens=6),
    )
    assert result.cause == "PROVIDER_WRITE_ISOLATION_UNVERIFIED"
    assert result.model_calls == 2
    assert result.telemetry["tokens_in"] == 14
    assert result.telemetry["tokens_out"] == 6
