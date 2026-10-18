"""A normal task-tracker path is not a secret, while real keys remain blocked."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest

from pmpe import barebones, privacy_policy
from pmpe.privacy_policy import PrivacyPolicyError, validate_private_payload

_NORMAL_PATH = "/tmp/task-tracker-acceptance-7e4af/tasks.json"


@pytest.mark.parametrize(
    "text",
    [
        _NORMAL_PATH,
        "Trace refers to /tmp/task-tracker-acceptance-7e4af/tasks.json",
        "The task-tracker-acceptance suite has fourteen cases.",
    ],
)
def test_normal_task_tracker_path_and_prose_are_not_credentials(text: str) -> None:
    validate_private_payload({"trace": text})
    assert barebones._CREDENTIAL.search(text) is None


@pytest.mark.parametrize(
    "key",
    [
        "sk-" + "A" * 24,
        "sk-proj-" + "B" * 28,
        "ghp_" + "C" * 36,
        "AKIA" + "D" * 16,
        "-----BEGIN PRIVATE KEY-----",
    ],
)
def test_real_standalone_credential_shapes_are_still_blocked(key: str) -> None:
    with pytest.raises(PrivacyPolicyError):
        validate_private_payload({"source": "token is " + key})
    assert barebones._CREDENTIAL.search(key)


def test_ambient_secret_remains_blocked_without_secret_tuple_in_scanner_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canary = "opaque-owner-only-value-73162"
    monkeypatch.setenv("PEOS_PLANTED_SECRET", canary)
    assert "ambient_secrets" not in inspect.signature(privacy_policy._check_string).parameters
    with pytest.raises(PrivacyPolicyError) as failure:
        validate_private_payload({"statement": "The value is " + canary})
    assert failure.value.rule_id == "POL-017"
    assert canary not in str(failure.value)
    frames: list[tuple[str, dict[str, Any]]] = []
    traceback = failure.value.__traceback__
    while traceback is not None:
        frames.append((traceback.tb_frame.f_code.co_name, traceback.tb_frame.f_locals))
        traceback = traceback.tb_next
    assert all(
        locals_.get("__tracebackhide__") is True
        for name, locals_ in frames
        if name in {"validate_private_payload", "_check_string", "_ambient_secret_values"}
    )


def test_normal_path_does_not_trigger_candidate_security_finding(tmp_path: Path) -> None:
    (tmp_path / "product.py").write_text(f"TRACE = {_NORMAL_PATH!r}\n")
    assert not any(
        item.code == "CRITICAL_CREDENTIAL" for item in barebones._security_findings(tmp_path)
    )
