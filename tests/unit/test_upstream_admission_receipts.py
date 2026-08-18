"""Issue #104 red-first contract for durable upstream admission receipts."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
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


def test_publication_has_no_intermediate_hard_link_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _api()

    def forbidden_link(*args: object, **kwargs: object) -> None:
        raise AssertionError("receipt publication must not create a second durable link")

    monkeypatch.setattr(os, "link", forbidden_link)
    receipt = api.FileArtifactAdmissionAuthority(
        tmp_path / "admissions", _FingerprintProvider()
    ).admit(
        artifact_kind="CANONICAL_CONTRACT",
        artifact_digest=_digest("9"),
        subject_bindings={"lineage_id": "LINEAGE-006"},
    )

    assert receipt.artifact_digest == _digest("9")


def test_new_ledger_directories_are_persisted_in_their_parents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _api()
    fsynced_directories: set[Path] = set()
    original_fsync = os.fsync

    def recording_fsync(descriptor: int) -> None:
        linked_path = Path(os.readlink(f"/proc/self/fd/{descriptor}"))
        if linked_path.is_dir():
            fsynced_directories.add(linked_path)
        original_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", recording_fsync)
    root = tmp_path / "admissions"
    api.FileArtifactAdmissionAuthority(root, _FingerprintProvider()).admit(
        artifact_kind="CANONICAL_CONTRACT",
        artifact_digest=_digest("a"),
        subject_bindings={"lineage_id": "LINEAGE-007"},
    )

    assert tmp_path in fsynced_directories
    assert root in fsynced_directories
    assert root / "CANONICAL_CONTRACT" in fsynced_directories


def test_concurrent_first_admissions_tolerate_directory_creation_races(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _api()
    root = tmp_path / "admissions"
    provider = _FingerprintProvider()
    original_mkdir = os.mkdir
    creation_barrier = threading.Barrier(8)

    def synchronized_mkdir(
        path: str | bytes, mode: int = 0o777, *, dir_fd: int | None = None
    ) -> None:
        if path == root.name:
            creation_barrier.wait(timeout=5)
        original_mkdir(path, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "mkdir", synchronized_mkdir)

    def admit(index: int) -> object:
        return api.FileArtifactAdmissionAuthority(root, provider).admit(
            artifact_kind="CANONICAL_CONTRACT",
            artifact_digest="sha256:" + f"{index:x}" * 64,
            subject_bindings={"lineage_id": f"LINEAGE-{index:03d}"},
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        receipts = list(pool.map(admit, range(8)))

    assert len(receipts) == 8


def test_exact_replay_fsyncs_the_receipt_directory_before_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _api()
    root = tmp_path / "admissions"
    authority = api.FileArtifactAdmissionAuthority(root, _FingerprintProvider())
    arguments = {
        "artifact_kind": "CANONICAL_CONTRACT",
        "artifact_digest": _digest("b"),
        "subject_bindings": {"lineage_id": "LINEAGE-008"},
    }
    authority.admit(**arguments)
    fsynced_directories: list[Path] = []
    original_fsync = os.fsync

    def recording_fsync(descriptor: int) -> None:
        linked_path = Path(os.readlink(f"/proc/self/fd/{descriptor}"))
        if linked_path.is_dir():
            fsynced_directories.append(linked_path)
        original_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", recording_fsync)

    authority.admit(**arguments)

    assert root / "CANONICAL_CONTRACT" in fsynced_directories


def test_mkdir_race_loser_persists_the_shared_parent_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _api()
    root = tmp_path / "admissions"
    original_mkdir = os.mkdir
    original_fsync = os.fsync
    raced = False
    fsynced_directories: set[Path] = set()

    def raced_mkdir(
        path: str | bytes, mode: int = 0o777, *, dir_fd: int | None = None
    ) -> None:
        nonlocal raced
        if path == root.name and not raced:
            raced = True
            original_mkdir(path, mode, dir_fd=dir_fd)
            raise FileExistsError(path)
        original_mkdir(path, mode, dir_fd=dir_fd)

    def recording_fsync(descriptor: int) -> None:
        linked_path = Path(os.readlink(f"/proc/self/fd/{descriptor}"))
        if linked_path.is_dir():
            fsynced_directories.add(linked_path)
        original_fsync(descriptor)

    monkeypatch.setattr(os, "mkdir", raced_mkdir)
    monkeypatch.setattr(os, "fsync", recording_fsync)
    api.FileArtifactAdmissionAuthority(root, _FingerprintProvider()).admit(
        artifact_kind="CANONICAL_CONTRACT",
        artifact_digest=_digest("c"),
        subject_bindings={"lineage_id": "LINEAGE-009"},
    )

    assert tmp_path in fsynced_directories


def test_non_ascii_receipt_digest_fails_closed(tmp_path: Path) -> None:
    api = _api()
    provider = _FingerprintProvider()
    root = tmp_path / "admissions"
    receipt = api.FileArtifactAdmissionAuthority(root, provider).admit(
        artifact_kind="CANONICAL_CONTRACT",
        artifact_digest=_digest("d"),
        subject_bindings={"lineage_id": "LINEAGE-010"},
    )

    malformed = replace(receipt, receipt_digest="é")

    assert not api.FileArtifactAdmissionVerifier(root, provider).verify(
        malformed,
        artifact_kind="CANONICAL_CONTRACT",
        artifact_digest=_digest("d"),
        subject_bindings={"lineage_id": "LINEAGE-010"},
    )


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are unavailable")
def test_fifo_receipt_is_opened_nonblocking_and_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _api()
    root = tmp_path / "admissions"
    kind = root / "CANONICAL_CONTRACT"
    target = kind / (_digest("e")[7:] + ".json")
    receipt = api.FileArtifactAdmissionAuthority(root, _FingerprintProvider()).admit(
        artifact_kind="CANONICAL_CONTRACT",
        artifact_digest=_digest("e"),
        subject_bindings={"lineage_id": "LINEAGE-011"},
    )
    target.unlink()
    os.mkfifo(target)
    original_open = os.open
    inspected = False

    def guarded_open(
        path: str | bytes,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal inspected
        if path == target.name:
            inspected = True
            assert flags & os.O_NONBLOCK
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", guarded_open)
    verifier = api.FileArtifactAdmissionVerifier(root, _FingerprintProvider())

    assert not verifier.verify(
        receipt,
        artifact_kind="CANONICAL_CONTRACT",
        artifact_digest=_digest("e"),
        subject_bindings={"lineage_id": "LINEAGE-011"},
    )
    assert inspected


def test_publication_does_not_use_replacing_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _api()

    def forbidden_rename(*args: object, **kwargs: object) -> None:
        raise AssertionError("receipt publication must be atomic and no-replace")

    monkeypatch.setattr(os, "rename", forbidden_rename)

    receipt = api.FileArtifactAdmissionAuthority(
        tmp_path / "admissions", _FingerprintProvider()
    ).admit(
        artifact_kind="CANONICAL_CONTRACT",
        artifact_digest=_digest("1"),
        subject_bindings={"lineage_id": "LINEAGE-012"},
    )

    assert receipt.artifact_digest == _digest("1")


def test_exact_receipt_won_by_publication_race_is_fsynced_before_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _api()
    from pmpe.admission import receipts as receipt_module

    fsynced_files: set[Path] = set()
    original_fsync = os.fsync

    def raced_publication(
        source: str,
        target: str,
        *,
        source_directory: int,
        target_directory: int,
    ) -> None:
        source_fd = os.open(source, os.O_RDONLY, dir_fd=source_directory)
        try:
            payload = os.read(source_fd, 64 * 1024)
        finally:
            os.close(source_fd)
        target_fd = os.open(
            target,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=target_directory,
        )
        try:
            os.write(target_fd, payload)
        finally:
            os.close(target_fd)
        raise FileExistsError(target)

    def recording_fsync(descriptor: int) -> None:
        linked_path = Path(os.readlink(f"/proc/self/fd/{descriptor}"))
        if linked_path.is_file():
            fsynced_files.add(linked_path)
        original_fsync(descriptor)

    monkeypatch.setattr(receipt_module, "_rename_noreplace", raced_publication)
    monkeypatch.setattr(os, "fsync", recording_fsync)
    root = tmp_path / "admissions"
    api.FileArtifactAdmissionAuthority(root, _FingerprintProvider()).admit(
        artifact_kind="CANONICAL_CONTRACT",
        artifact_digest=_digest("2"),
        subject_bindings={"lineage_id": "LINEAGE-013"},
    )

    target = root / "CANONICAL_CONTRACT" / (_digest("2")[7:] + ".json")
    assert target in fsynced_files


def test_surrogate_receipt_strings_fail_closed(tmp_path: Path) -> None:
    api = _api()
    provider = _FingerprintProvider()
    root = tmp_path / "admissions"
    receipt = api.FileArtifactAdmissionAuthority(root, provider).admit(
        artifact_kind="CANONICAL_CONTRACT",
        artifact_digest=_digest("3"),
        subject_bindings={"lineage_id": "LINEAGE-014"},
    )

    malformed = replace(receipt, fingerprint="\ud800")

    assert not api.FileArtifactAdmissionVerifier(root, provider).verify(
        malformed,
        artifact_kind="CANONICAL_CONTRACT",
        artifact_digest=_digest("3"),
        subject_bindings={"lineage_id": "LINEAGE-014"},
    )


def test_preexisting_exact_receipt_file_is_fsynced_on_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _api()
    root = tmp_path / "admissions"
    authority = api.FileArtifactAdmissionAuthority(root, _FingerprintProvider())
    arguments = {
        "artifact_kind": "CANONICAL_CONTRACT",
        "artifact_digest": _digest("4"),
        "subject_bindings": {"lineage_id": "LINEAGE-015"},
    }
    authority.admit(**arguments)
    target = root / "CANONICAL_CONTRACT" / (_digest("4")[7:] + ".json")
    fsynced_files: set[Path] = set()
    original_fsync = os.fsync

    def recording_fsync(descriptor: int) -> None:
        linked_path = Path(os.readlink(f"/proc/self/fd/{descriptor}"))
        if linked_path.is_file():
            fsynced_files.add(linked_path)
        original_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", recording_fsync)

    authority.admit(**arguments)

    assert target in fsynced_files
