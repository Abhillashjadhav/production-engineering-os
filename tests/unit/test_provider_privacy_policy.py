"""Pre-send privacy checks at the ModelProvider boundary."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from typing import Any

import pytest

from pmpe.model_provider import PrivacyCheckedProvider
from pmpe.privacy_policy import (
    PrivacyPolicyError,
    ProviderPrivacyPolicy,
    validate_private_payload,
    validate_provider_request,
)


def test_quality_code_request_is_declared_and_still_privacy_checked() -> None:
    request = {
        **_request(),
        "task_graph": {},
        "generation_policy": {"profile": "python-stdlib-quality/v1"},
    }
    validate_provider_request("code", request)
    request["generation_policy"] = {"instructions": ["PEOS_PRIVATE_CANARY_customer_9273"]}
    with pytest.raises(PrivacyPolicyError):
        validate_provider_request("code", request)


def test_source_review_has_a_purpose_specific_exact_shape() -> None:
    request = {
        "contract_digest": "sha256:contract",
        "plan_digest": "sha256:plan",
        "evidence_digest": "sha256:evidence",
        "instruction": "Review the source",
        "contract": {},
        "files": {"product.py": "x = 1\n"},
        "generation_policy": {},
        "quality": {},
        "request_digest": "sha256:request",
    }
    validate_provider_request("advisory_review", request)
    with pytest.raises(PrivacyPolicyError):
        validate_provider_request("code", request)
    with pytest.raises(PrivacyPolicyError):
        validate_provider_request("advisory_review", {**request, "undeclared": "context"})
    request["quality"] = {"details": "PEOS_PRIVATE_CANARY_customer_9273"}
    with pytest.raises(PrivacyPolicyError):
        validate_provider_request("advisory_review", request)


class RecordingProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Mapping[str, Any]]] = []

    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls.append((purpose, request))
        return {"request_digest": request["request_digest"], "files": {}}


def _request() -> dict[str, Any]:
    return {
        "contract": {"name": "synthetic tracker", "requirements": ["Create a task"]},
        "plan": {"tasks": [{"name": "implement the task endpoint"}]},
        "files": {"product.py": "def health(): return 'ok'\n"},
        "findings": [],
        "request_digest": "sha256:approved-original",
    }


@pytest.mark.parametrize("purpose", ["code", "advisory_review"])
@pytest.mark.parametrize(
    "path,value",
    [
        (("contract", "requirements", 0), "ghp_" + "A" * 36),
        (("plan", "tasks", 0, "name"), "PEOS_PRIVATE_CANARY_customer_9273"),
        (("files", "product.py"), "AWS_ACCESS_KEY_ID=AKIA" + "A" * 16),
        (("contract", "credentials"), {"nested": {"password": "example"}}),
    ],
)
def test_nested_credential_and_private_canary_never_reach_provider(
    purpose: str, path: tuple[str | int, ...], value: Any
) -> None:
    request = _request()
    node: Any = request
    for segment in path[:-1]:
        node = node[segment]
    node[path[-1]] = value
    provider = RecordingProvider()
    guarded = PrivacyCheckedProvider(provider)

    with pytest.raises(PrivacyPolicyError) as failure:
        guarded.invoke(purpose=purpose, request=request)

    assert provider.calls == []
    assert failure.value.rule_id.startswith("POL-")
    assert str(failure.value) == "MODEL_REQUEST_PRIVACY_BLOCKED"
    assert "9273" not in repr(failure.value)
    assert "AKIA" not in repr(failure.value)


def test_ambient_secret_value_is_blocked_even_without_a_known_token_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canary = "unguessable-owner-only-value-17321"
    monkeypatch.setenv("PEOS_PLANTED_SECRET", canary)
    request = _request()
    request["contract"]["requirements"].append(f"Service uses {canary}")
    provider = RecordingProvider()

    with pytest.raises(PrivacyPolicyError) as failure:
        PrivacyCheckedProvider(provider).invoke(purpose="code", request=request)

    assert provider.calls == []
    assert canary not in str(failure.value)


@pytest.mark.parametrize("extra", [{"environment": {"HOME": "/private"}}, {"arbitrary": 1}])
def test_only_declared_request_context_reaches_provider(extra: dict[str, Any]) -> None:
    provider = RecordingProvider()
    with pytest.raises(PrivacyPolicyError):
        PrivacyCheckedProvider(provider).invoke(purpose="code", request={**_request(), **extra})
    assert provider.calls == []


def test_exact_approved_bytes_are_passed_without_relabeling_or_redaction() -> None:
    original = _request()
    approved = copy.deepcopy(original)
    provider = RecordingProvider()
    guarded = PrivacyCheckedProvider(
        provider,
        policy=ProviderPrivacyPolicy(destination="offline_confined", retention="run_local"),
    )

    guarded.invoke(purpose="code", request=original)

    assert original == approved
    assert provider.calls == [("code", original)]
    assert provider.calls[0][1] is original
    assert provider.calls[0][1]["request_digest"] == "sha256:approved-original"


@pytest.mark.parametrize("purpose", ["code", "advisory_review"])
def test_excessive_context_fails_before_provider_call(purpose: str) -> None:
    request = _request()
    request["files"]["product.py"] = "safe" * 250_001
    provider = RecordingProvider()
    with pytest.raises(PrivacyPolicyError) as failure:
        PrivacyCheckedProvider(provider).invoke(purpose=purpose, request=request)
    assert provider.calls == []
    assert len(str(failure.value)) < 80


def test_undeclared_destination_cannot_opt_in() -> None:
    with pytest.raises(ValueError):
        ProviderPrivacyPolicy(destination="https://unreviewed.example", retention="run_local")


def test_provider_failure_does_not_echo_private_response_or_exception() -> None:
    class LeakingProvider:
        def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
            raise RuntimeError("provider stderr: PEOS_PRIVATE_CANARY_customer_9273")

    with pytest.raises(RuntimeError) as failure:
        PrivacyCheckedProvider(LeakingProvider()).invoke(purpose="code", request=_request())
    assert str(failure.value) == "MODEL_PROVIDER_FAILED"
    assert failure.value.__cause__ is None
    assert "9273" not in json.dumps({"error": str(failure.value)})


def test_private_response_blocked_before_core_can_persist_it() -> None:
    class LeakingProvider:
        def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
            return {
                "request_digest": request["request_digest"],
                "files": {"product.py": "PEOS_PRIVATE_CANARY_customer_9273"},
            }

    with pytest.raises(PrivacyPolicyError) as failure:
        PrivacyCheckedProvider(LeakingProvider()).invoke(purpose="code", request=_request())
    assert "9273" not in repr(failure.value)


def test_approved_contract_and_receipt_can_be_scanned_before_evidence_ledger() -> None:
    receipt = {"approver": "fixture-human", "contract_digest": "sha256:bound"}
    validate_private_payload(receipt)
    with pytest.raises(PrivacyPolicyError) as failure:
        validate_private_payload({**receipt, "note": "PEOS_PRIVATE_CANARY_customer_9273"})
    assert "9273" not in str(failure.value)
