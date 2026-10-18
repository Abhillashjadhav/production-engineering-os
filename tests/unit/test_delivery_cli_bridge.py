"""Delivery CLI reads exact packaged bytes and requires an external digest."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pmpe.cli import barebones_cmd, main
from pmpe.delivery import assemble_delivery
from pmpe.evidence.ledger import EvidenceIntegrityError
from pmpe.quality.generated_python import check_python_candidate


def test_delivery_verifier_cli_requires_exact_external_digest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = {"product.py": b'def health() -> dict[str, str]:\n    return {"status": "ok"}\n'}
    quality = check_python_candidate(source).as_dict()
    output = tmp_path / "delivery"
    package = assemble_delivery(
        source,
        quality=quality,
        identity={
            "candidate_digest": quality["candidate_digest"],
            "contract_digest": "sha256:" + "a" * 64,
            "plan_digest": "sha256:" + "b" * 64,
            "head_event_digest": "sha256:" + "c" * 64,
        },
        output=output,
    )
    command = [
        "barebones",
        "verify-delivery",
        str(output),
        "--expected-manifest-digest",
        package["manifest_digest"],
    ]
    assert main(command) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "VERIFIED_SOURCE_PACKAGE"
    (output / "product/product.py").write_text("tampered")
    assert main(command) == 3
    assert json.loads(capsys.readouterr().out)["status"] == "INVALID_DELIVERY"


def test_delivery_export_rejects_unverified_release_before_loading_sources(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    terminal = {
        "event_type": "release_ready",
        "state": "RELEASE_READY",
        "event_digest": "sha256:" + "a" * 64,
        "payload": {"provider_write_isolation": "UNVERIFIED"},
    }
    monkeypatch.setattr(barebones_cmd, "_open_verified_events", lambda *_: (object(), (terminal,)))
    monkeypatch.setattr(barebones_cmd, "_verification_assurance", lambda *_: "LEGACY_UNVERIFIED")
    with pytest.raises(EvidenceIntegrityError, match="independently verified"):
        barebones_cmd._export_verified_run(
            tmp_path,
            "run",
            expected_approver="human",
            compiler_root=tmp_path,
            expected_head_digest=str(terminal["event_digest"]),
        )
