"""Privacy policy is enforced at the real runtime/evidence boundaries."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from pmpe.barebones import BudgetCaps, _invoke_bound, _model_request, run_to_release_ready
from pmpe.privacy_policy import PrivacyPolicyError


class RecordingProvider:
    def __init__(self, response: Mapping[str, Any] | None = None) -> None:
        self.calls: list[Mapping[str, Any]] = []
        self.response = response

    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls.append(request)
        return self.response or {"request_digest": request["request_digest"], "files": {}}


def _request() -> dict[str, Any]:
    return {
        "contract": {"requirements": [{"statement": "A health endpoint"}]},
        "plan": {"tasks": []},
        "files": {"product.py": "def health(): return 'ok'\n"},
        "findings": [],
        "request_digest": "sha256:bound",
    }


def _counters() -> dict[str, Any]:
    return {
        "calls": 0,
        "bytes": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "estimated_cost_usd": 0.0,
        "provider_model_id": "",
    }


@pytest.mark.parametrize("purpose", ["code", "advisory_review"])
def test_runtime_never_calls_provider_for_nested_canary(purpose: str) -> None:
    request = _request()
    request["plan"]["tasks"].append({"context": "PEOS_PRIVATE_CANARY_customer_9273"})
    provider = RecordingProvider()
    counters = _counters()
    with pytest.raises(PrivacyPolicyError) as failure:
        _invoke_bound(
            provider, purpose=purpose, request=request, budget=BudgetCaps(), counters=counters
        )
    assert provider.calls == []
    assert counters["calls"] == 0
    assert "9273" not in str(failure.value)


def test_response_canary_is_blocked_after_actual_usage_is_charged() -> None:
    provider = RecordingProvider(
        {
            "request_digest": "sha256:bound",
            "files": {"product.py": "PEOS_PRIVATE_CANARY_customer_9273"},
            "usage": {"input_tokens": 13, "output_tokens": 8},
        }
    )
    counters = _counters()
    with pytest.raises(PrivacyPolicyError) as failure:
        _invoke_bound(
            provider, purpose="code", request=_request(), budget=BudgetCaps(), counters=counters
        )
    assert len(provider.calls) == 1
    assert counters["calls"] == 1
    assert counters["tokens_in"] == 13
    assert counters["tokens_out"] == 8
    assert counters["bytes"] > 0
    assert "9273" not in str(failure.value)


def test_provider_error_with_canary_is_sanitized() -> None:
    class LeakingProvider:
        def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
            raise RuntimeError("PEOS_PRIVATE_CANARY_customer_9273")

    with pytest.raises(RuntimeError) as failure:
        _invoke_bound(
            LeakingProvider(),
            purpose="code",
            request=_request(),
            budget=BudgetCaps(),
            counters=_counters(),
        )
    assert str(failure.value) == "MODEL_PROVIDER_FAILED"
    assert failure.value.__cause__ is None


def test_contract_canary_rejected_before_evidence_ledger_exists(tmp_path: Path) -> None:
    contract = json.loads(
        (Path(__file__).parents[2] / "examples/barebones/e1-contract.json").read_text()
    )
    contract["functional_requirements"]["FR-001"]["statement"] += (
        " PEOS_PRIVATE_CANARY_customer_9273"
    )
    provider = RecordingProvider()
    with pytest.raises(PrivacyPolicyError) as failure:
        run_to_release_ready(
            contract=contract,
            repository_root=tmp_path,
            workspace=tmp_path / "workspace",
            run_id="privacy-rejected",
            provider=provider,
        )
    assert provider.calls == []
    assert not (tmp_path / ".pmpe").exists()
    assert "9273" not in str(failure.value)


def test_model_request_rejects_symlink_context_before_read(tmp_path: Path) -> None:
    (tmp_path / "product.py").symlink_to(tmp_path / "outside.py")

    class Plan:
        def as_dict(self) -> dict[str, Any]:
            return {"tasks": []}

    with pytest.raises(PrivacyPolicyError):
        _model_request(contract={}, plan=Plan(), workspace=tmp_path, findings=[])  # type: ignore[arg-type]


def test_task_graph_canary_rejected_before_evidence_ledger_exists(tmp_path: Path) -> None:
    from pmpe.barebones import compile_barebones_plan

    contract = json.loads(
        (Path(__file__).parents[2] / "examples/barebones/e1-contract.json").read_text()
    )
    plan = compile_barebones_plan(contract=contract, repository_root=tmp_path)
    mapping = {
        "plan_digest": plan.plan_digest,
        "architecture_digest": "a" * 64,
        "tasks": [
            {
                "task_id": "PRODUCT",
                "requirement_refs": ["FR-001"],
                "acceptance_ids": ["AC-001"],
                "prerequisites": [],
                "data_owners": [],
                "interface_owners": [],
                "allowed_files": ["product.py"],
                "outputs": ["PEOS_PRIVATE_CANARY_customer_9273"],
                "affected_checks": ["AC-001"],
            }
        ],
    }
    provider = RecordingProvider()
    with pytest.raises(PrivacyPolicyError):
        run_to_release_ready(
            contract=contract,
            repository_root=tmp_path,
            workspace=tmp_path / "workspace",
            run_id="private-graph",
            provider=provider,
            task_graph_mapping=mapping,
        )
    assert provider.calls == []
    assert not (tmp_path / ".pmpe").exists()
