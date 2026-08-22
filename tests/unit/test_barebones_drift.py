from __future__ import annotations

import pytest

from pmpe.evals.barebones_drift import (
    compare_provider_behavior,
    observe_provider_behavior,
)

_REQUEST_DIGEST = "sha256:" + "1" * 64


def _response(*, status: str, prompt_version: str) -> dict[str, object]:
    return {
        "request_digest": _REQUEST_DIGEST,
        "files": {"product.py": f"def health():\n    return {{'status': {status!r}}}\n"},
        "provider_metadata": {
            "provider": "openai-responses",
            "model": "gpt-example-2026-01-01",
            "prompt_version": prompt_version,
        },
    }


def test_prompt_change_with_behavior_change_is_detected_and_attributed() -> None:
    baseline = observe_provider_behavior(
        purpose="code", response=_response(status="ok", prompt_version="prompt-v1")
    )
    current = observe_provider_behavior(
        purpose="code", response=_response(status="degraded", prompt_version="prompt-v2")
    )

    drift = compare_provider_behavior(baseline, current)

    assert drift.detected is True
    assert drift.cause == "PROVIDER_CONFIGURATION_CHANGED"
    assert drift.attribution == ("prompt_version",)


def test_behavior_change_without_identity_change_is_unattributed() -> None:
    baseline = observe_provider_behavior(
        purpose="code", response=_response(status="ok", prompt_version="prompt-v1")
    )
    current = observe_provider_behavior(
        purpose="code", response=_response(status="degraded", prompt_version="prompt-v1")
    )

    drift = compare_provider_behavior(baseline, current)

    assert drift.detected is True
    assert drift.cause == "UNATTRIBUTED_BEHAVIOR_DRIFT"
    assert drift.attribution == ()


def test_identical_behavior_is_not_drift_even_after_prompt_change() -> None:
    baseline = observe_provider_behavior(
        purpose="code", response=_response(status="ok", prompt_version="prompt-v1")
    )
    current = observe_provider_behavior(
        purpose="code", response=_response(status="ok", prompt_version="prompt-v2")
    )

    drift = compare_provider_behavior(baseline, current)

    assert drift.detected is False
    assert drift.cause == "NO_BEHAVIOR_DRIFT"


def test_different_requests_are_not_comparable() -> None:
    baseline = observe_provider_behavior(
        purpose="code", response=_response(status="ok", prompt_version="prompt-v1")
    )
    changed = _response(status="ok", prompt_version="prompt-v1")
    changed["request_digest"] = "sha256:" + "2" * 64
    current = observe_provider_behavior(purpose="code", response=changed)

    with pytest.raises(ValueError, match="not comparable"):
        compare_provider_behavior(baseline, current)


def test_malformed_request_digest_is_rejected() -> None:
    response = _response(status="ok", prompt_version="prompt-v1")
    response["request_digest"] = "not-a-digest"

    with pytest.raises(ValueError, match="digest-bound metadata"):
        observe_provider_behavior(purpose="code", response=response)
