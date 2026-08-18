"""Issue #104 red-first contract for durable upstream admission receipts."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from pmpe.contracts.intake import KeyedFingerprint


class _FingerprintProvider:
    key_version = "test-v1"

    def __init__(self, key: bytes = b"issue-104-test-key") -> None:
        self.key = key

    def fingerprint(self, domain: str, payload: bytes) -> str:
        return hmac.new(self.key, domain.encode() + b"\0" + payload, hashlib.sha256).hexdigest()

    def candidate_fingerprints(self, domain: str, payload: bytes) -> tuple[KeyedFingerprint, ...]:
        return (KeyedFingerprint(self.key_version, self.fingerprint(domain, payload)),)


def _api():  # type: ignore[no-untyped-def]
    try:
        from pmpe import admission
    except (ImportError, ModuleNotFoundError):
        pytest.fail("issue #104 admission receipts are not implemented", pytrace=False)
    return admission


def _digest(character: str) -> str:
    return "sha256:" + character * 64


def test_durable_receipt_verifies_exact_kind_digest_and_bindings(tmp_path: Path) -> None:
    api = _api()
    provider = _FingerprintProvider()
    authority = api.FileArtifactAdmissionAuthority(tmp_path / "admissions", provider)
    verifier = api.FileArtifactAdmissionVerifier(tmp_path / "admissions", provider)

    receipt = authority.admit(
        artifact_kind="REPOSITORY_SNAPSHOT",
        artifact_digest=_digest("a"),
        subject_bindings={"repository": "owner/repo", "commit": "b" * 40},
    )

    assert verifier.verify(
        receipt,
        artifact_kind="REPOSITORY_SNAPSHOT",
        artifact_digest=_digest("a"),
        subject_bindings={"repository": "owner/repo", "commit": "b" * 40},
    )
    assert receipt.key_version == provider.key_version
    assert receipt.receipt_digest.startswith("sha256:")


def test_self_digest_without_durable_authority_evidence_is_rejected(tmp_path: Path) -> None:
    api = _api()
    provider = _FingerprintProvider()
    authority = api.FileArtifactAdmissionAuthority(tmp_path / "issuer", provider)
    receipt = authority.admit(
        artifact_kind="ARCHITECTURE_PACK",
        artifact_digest=_digest("c"),
        subject_bindings={"contract_digest": _digest("d")},
    )
    verifier = api.FileArtifactAdmissionVerifier(tmp_path / "different-ledger", provider)

    assert not verifier.verify(
        receipt,
        artifact_kind="ARCHITECTURE_PACK",
        artifact_digest=_digest("c"),
        subject_bindings={"contract_digest": _digest("d")},
    )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("artifact_kind", "CONTRACT"),
        ("artifact_digest", _digest("e")),
        ("subject_bindings", {"repository": "other/repo"}),
        ("key_version", "retired-key"),
        ("fingerprint", "0" * 64),
        ("receipt_digest", _digest("f")),
    ),
)
def test_tampered_or_mismatched_receipts_are_rejected(
    tmp_path: Path, field: str, value: object
) -> None:
    api = _api()
    provider = _FingerprintProvider()
    root = tmp_path / "admissions"
    authority = api.FileArtifactAdmissionAuthority(root, provider)
    verifier = api.FileArtifactAdmissionVerifier(root, provider)
    receipt = authority.admit(
        artifact_kind="REPOSITORY_SNAPSHOT",
        artifact_digest=_digest("1"),
        subject_bindings={"repository": "owner/repo", "commit": "2" * 40},
    )

    tampered = replace(receipt, **{field: value})

    assert not verifier.verify(
        tampered,
        artifact_kind="REPOSITORY_SNAPSHOT",
        artifact_digest=_digest("1"),
        subject_bindings={"repository": "owner/repo", "commit": "2" * 40},
    )


def test_receipt_replay_is_idempotent_and_conflicting_authority_is_rejected(
    tmp_path: Path,
) -> None:
    api = _api()
    root = tmp_path / "admissions"
    first = api.FileArtifactAdmissionAuthority(root, _FingerprintProvider())
    arguments = {
        "artifact_kind": "CANONICAL_CONTRACT",
        "artifact_digest": _digest("3"),
        "subject_bindings": {"lineage_id": "LINEAGE-001"},
    }

    assert first.admit(**arguments) == first.admit(**arguments)

    conflicting = api.FileArtifactAdmissionAuthority(root, _FingerprintProvider(b"other-key"))
    with pytest.raises(api.AdmissionReceiptConflict):
        conflicting.admit(**arguments)


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks are unavailable")
def test_receipt_authority_refuses_symlink_substitution(tmp_path: Path) -> None:
    api = _api()
    root = tmp_path / "admissions"
    root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("protected")
    kind_dir = root / "CANONICAL_CONTRACT"
    kind_dir.mkdir()
    target = kind_dir / (_digest("4").removeprefix("sha256:") + ".json")
    target.symlink_to(outside)

    with pytest.raises(api.AdmissionReceiptError):
        api.FileArtifactAdmissionAuthority(root, _FingerprintProvider()).admit(
            artifact_kind="CANONICAL_CONTRACT",
            artifact_digest=_digest("4"),
            subject_bindings={"lineage_id": "LINEAGE-002"},
        )

    assert outside.read_text() == "protected"


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks are unavailable")
def test_receipt_authority_refuses_a_symlinked_kind_directory(tmp_path: Path) -> None:
    api = _api()
    root = tmp_path / "admissions"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "CANONICAL_CONTRACT").symlink_to(outside, target_is_directory=True)

    with pytest.raises(api.AdmissionReceiptError):
        api.FileArtifactAdmissionAuthority(root, _FingerprintProvider()).admit(
            artifact_kind="CANONICAL_CONTRACT",
            artifact_digest=_digest("5"),
            subject_bindings={"lineage_id": "LINEAGE-003"},
        )

    assert list(outside.iterdir()) == []


def test_oversized_receipt_is_rejected_before_claiming_identity(tmp_path: Path) -> None:
    api = _api()
    root = tmp_path / "admissions"
    with pytest.raises(api.AdmissionReceiptError, match="size"):
        api.FileArtifactAdmissionAuthority(root, _FingerprintProvider()).admit(
            artifact_kind="CANONICAL_CONTRACT",
            artifact_digest=_digest("6"),
            subject_bindings={"large": "x" * (65 * 1024)},
        )

    assert not (root / "CANONICAL_CONTRACT" / (_digest("6")[7:] + ".json")).exists()


def test_short_writes_are_completed_before_receipt_is_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _api()
    provider = _FingerprintProvider()
    original_write = os.write

    def short_write(descriptor: int, payload: bytes) -> int:
        return original_write(descriptor, payload[: max(1, len(payload) // 3)])

    monkeypatch.setattr(os, "write", short_write)
    root = tmp_path / "admissions"
    receipt = api.FileArtifactAdmissionAuthority(root, provider).admit(
        artifact_kind="CANONICAL_CONTRACT",
        artifact_digest=_digest("7"),
        subject_bindings={"lineage_id": "LINEAGE-004"},
    )

    assert api.FileArtifactAdmissionVerifier(root, provider).verify(
        receipt,
        artifact_kind="CANONICAL_CONTRACT",
        artifact_digest=_digest("7"),
        subject_bindings={"lineage_id": "LINEAGE-004"},
    )


def test_noncanonical_durable_bytes_are_rejected(tmp_path: Path) -> None:
    api = _api()
    provider = _FingerprintProvider()
    root = tmp_path / "admissions"
    receipt = api.FileArtifactAdmissionAuthority(root, provider).admit(
        artifact_kind="CANONICAL_CONTRACT",
        artifact_digest=_digest("8"),
        subject_bindings={"lineage_id": "LINEAGE-005"},
    )
    path = root / "CANONICAL_CONTRACT" / (_digest("8")[7:] + ".json")
    parsed = json.loads(path.read_text())
    path.write_text(json.dumps(parsed, indent=2) + "\n")

    assert not api.FileArtifactAdmissionVerifier(root, provider).verify(
        receipt,
        artifact_kind="CANONICAL_CONTRACT",
        artifact_digest=_digest("8"),
        subject_bindings={"lineage_id": "LINEAGE-005"},
    )
