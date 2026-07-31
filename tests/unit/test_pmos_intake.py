"""Issue #76: durable fail-closed intake, quarantine, deletion, and reconciliation."""

from __future__ import annotations

import base64
import hashlib
import hmac
import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

VALID_PAYLOAD = b'{"spec_version":"1.0","product_name":"Safe Product"}'
FIXED_TIME = "2026-07-31T08:00:00Z"


def _module() -> ModuleType:
    try:
        return importlib.import_module("pmpe.contracts.intake")
    except ModuleNotFoundError:
        pytest.fail("issue #76 intake module is not implemented", pytrace=False)


@dataclass
class FixedClock:
    value: str = FIXED_TIME

    def now(self) -> str:
        return self.value


class SequenceIds:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def new_id(self, kind: str) -> str:
        next_value = self.counts.get(kind, 0) + 1
        self.counts[kind] = next_value
        return f"{kind.upper()}-{next_value:06d}"


class TestFingerprintProvider:
    key_version = "TEST-KEY-V1"
    _key = b"test-only-key-material"

    def fingerprint(self, domain: str, payload: bytes) -> str:
        assert domain in {"payload", "retry-key"}
        return hmac.new(
            self._key,
            b"pmpe-intake:" + domain.encode() + b"\x00" + payload,
            hashlib.sha256,
        ).hexdigest()


class TestCipher:
    """Deterministic test cipher; production cryptography is a provider boundary."""

    key_version = "TEST-CIPHER-V1"

    def encrypt(self, payload: bytes) -> bytes:
        return b"sealed:" + base64.b64encode(payload[::-1])

    def decrypt(self, payload: bytes) -> bytes:
        assert payload.startswith(b"sealed:")
        return base64.b64decode(payload.removeprefix(b"sealed:"))[::-1]


class CleanMalwareScanner:
    def scan(self, payload: bytes) -> Any:
        module = _module()
        return module.MalwareScanResult(clean=True, engine="test", signature_version="1")


class MalwareScanner:
    def scan(self, payload: bytes) -> Any:
        module = _module()
        return module.MalwareScanResult(
            clean=False,
            engine="test",
            signature_version="1",
            finding_code="TEST-MALWARE",
        )


def _coordinator(tmp_path: Path, **overrides: Any) -> Any:
    module = _module()
    clock = overrides.pop("clock", FixedClock())
    ids = overrides.pop("ids", SequenceIds())
    fingerprints = overrides.pop("fingerprints", TestFingerprintProvider())
    ledger = overrides.pop(
        "ledger",
        module.FileIntakeLedger(
            tmp_path / "ledger",
            clock=clock,
            id_provider=ids,
            fingerprint_provider=fingerprints,
        ),
    )
    quarantine = overrides.pop(
        "quarantine",
        module.FileQuarantineStore(
            tmp_path / "quarantine",
            cipher=TestCipher(),
            max_bytes=2048,
        ),
    )
    return module.IntakeCoordinator(
        ledger=ledger,
        quarantine=quarantine,
        fingerprint_provider=fingerprints,
        malware_scanner=overrides.pop("malware_scanner", CleanMalwareScanner()),
        clock=clock,
        max_bytes=2048,
        allowed_content_types={"application/json", "application/yaml"},
        **overrides,
    )


def _request(payload: bytes = VALID_PAYLOAD, **overrides: Any) -> Any:
    module = _module()
    values = {
        "retry_key": "publisher-retry-001",
        "payload": payload,
        "content_type": "application/json",
        "publisher": "pm-agent-os",
        "channel": "contract-api",
        "correction_reference": None,
    }
    values.update(overrides)
    return module.IntakeRequest(**values)


def test_issue76_public_intake_components_exist() -> None:
    module = _module()
    for name in (
        "FileIntakeLedger",
        "FileQuarantineStore",
        "IntakeCoordinator",
        "IntakeReceipt",
        "IntakeRequest",
        "IntakeReservation",
        "IntakeReconciler",
        "KeyedFingerprintProvider",
        "MalwareScanner",
        "QuarantineCipher",
        "QuarantineStore",
    ):
        assert hasattr(module, name), f"missing intake component: {name}"


def test_retry_key_resolves_exactly_one_durable_reservation(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    first = coordinator.receive(_request())
    second = coordinator.receive(_request())
    assert first.reservation == second.reservation
    assert first.receipt == second.receipt
    assert second.replayed is True
    quarantine_files = list((tmp_path / "quarantine").glob("*.sealed"))
    assert len(quarantine_files) <= 1
    reloaded = _coordinator(tmp_path).ledger.reservation_for_retry_key("publisher-retry-001")
    assert reloaded == first.reservation


def test_reservation_exists_before_quarantine_write(tmp_path: Path) -> None:
    module = _module()
    observed: list[bool] = []
    coordinator = _coordinator(tmp_path)
    real_store = coordinator.quarantine

    class AssertingStore:
        def put(self, handle: str, payload: bytes, metadata: dict[str, Any]) -> None:
            observed.append(coordinator.ledger.reservation_by_handle(handle) is not None)
            real_store.put(handle, payload, metadata)

        def read(self, handle: str) -> bytes:
            return real_store.read(handle)

        def delete(self, handle: str) -> Any:
            return real_store.delete(handle)

        def exists(self, handle: str) -> bool:
            return real_store.exists(handle)

    coordinator.quarantine = AssertingStore()
    outcome = coordinator.receive(_request())
    assert observed == [True]
    assert outcome.reservation.quarantine_handle
    assert isinstance(outcome.reservation, module.IntakeReservation)


def test_receipt_is_durable_before_parsing_or_scanning(tmp_path: Path) -> None:
    observed: list[bool] = []
    coordinator = _coordinator(tmp_path)

    class AssertingScanner:
        def scan(self, payload: bytes) -> Any:
            reservation = coordinator.ledger.reservation_for_retry_key("publisher-retry-001")
            observed.append(coordinator.ledger.receipt(reservation.attempt_id) is not None)
            return CleanMalwareScanner().scan(payload)

    coordinator.malware_scanner = AssertingScanner()
    outcome = coordinator.receive(_request())
    assert observed == [True]
    assert outcome.receipt.received_at == FIXED_TIME
    assert outcome.receipt.lineage_id == outcome.reservation.lineage_id
    assert outcome.receipt.attempt_id == outcome.reservation.attempt_id


def test_receipt_contains_only_safe_metadata_and_keyed_fingerprint(tmp_path: Path) -> None:
    outcome = _coordinator(tmp_path).receive(_request())
    receipt = outcome.receipt.as_dict()
    assert receipt["publisher"] == "pm-agent-os"
    assert receipt["channel"] == "contract-api"
    assert receipt["key_version"] == "TEST-KEY-V1"
    assert receipt["fingerprint"]
    rendered = json.dumps(receipt, sort_keys=True)
    assert hashlib.sha256(VALID_PAYLOAD).hexdigest() not in rendered
    assert "Safe Product" not in rendered
    assert "publisher-retry-001" not in rendered
    assert not hasattr(outcome.receipt, "verify_fingerprint")


def test_quarantine_payload_and_ordinary_digest_are_encrypted_and_deleted(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator(tmp_path)
    outcome = coordinator.receive(_request())
    files = list((tmp_path / "quarantine").glob("*"))
    assert outcome.deletion_attestation is not None
    assert outcome.deletion_attestation.deleted
    assert not coordinator.quarantine.exists(outcome.reservation.quarantine_handle)
    rendered = b"\n".join(path.read_bytes() for path in files if path.is_file())
    assert VALID_PAYLOAD not in rendered
    assert hashlib.sha256(VALID_PAYLOAD).hexdigest().encode() not in rendered


@pytest.mark.parametrize(
    ("payload", "content_type", "code"),
    [
        (b"x" * 2049, "application/json", "PAYLOAD_TOO_LARGE"),
        (VALID_PAYLOAD, "text/plain", "CONTENT_TYPE_REJECTED"),
        (b"{not-json", "application/json", "MALFORMED_INPUT"),
        (
            b'{"token":"ghp_abcdefghijklmnopqrstuvwxyz123456"}',
            "application/json",
            "SECRET_DETECTED",
        ),
        (
            b'{"customer_email":"person@example.com"}',
            "application/json",
            "PRIVACY_PATTERN_DETECTED",
        ),
    ],
)
def test_admission_rejections_delete_bytes_and_retain_sanitized_terminal_evidence(
    tmp_path: Path,
    payload: bytes,
    content_type: str,
    code: str,
) -> None:
    outcome = _coordinator(tmp_path).receive(_request(payload, content_type=content_type))
    assert outcome.status == "REJECTED"
    assert outcome.admitted_payload is None
    assert outcome.deletion_attestation.deleted
    assert any(finding.code == code for finding in outcome.findings)
    assert not outcome.quarantine_retained
    rendered = json.dumps(outcome.disposition.as_dict(), sort_keys=True)
    assert payload.decode(errors="ignore") not in rendered
    assert hashlib.sha256(payload).hexdigest() not in rendered


def test_malware_result_blocks_and_deletes_without_retaining_scanner_payload(
    tmp_path: Path,
) -> None:
    outcome = _coordinator(
        tmp_path,
        malware_scanner=MalwareScanner(),
    ).receive(_request())
    assert outcome.status == "REJECTED"
    assert any(finding.code == "MALWARE_DETECTED" for finding in outcome.findings)
    assert outcome.deletion_attestation.deleted
    assert outcome.disposition.status == "REJECTED"


def test_valid_payload_is_admitted_only_after_all_checks_and_quarantine_cleanup(
    tmp_path: Path,
) -> None:
    outcome = _coordinator(tmp_path).receive(_request())
    assert outcome.status == "ADMITTED"
    assert outcome.admitted_payload == VALID_PAYLOAD
    assert outcome.deletion_attestation.deleted
    assert not outcome.quarantine_retained
    assert outcome.disposition.status == "ADMITTED"


def test_invalid_correction_reference_creates_new_lineage_and_duplicate_finding(
    tmp_path: Path,
) -> None:
    module = _module()
    reference = module.CorrectionReference("LINEAGE-999999", "ATTEMPT-999999")
    outcome = _coordinator(tmp_path).receive(_request(correction_reference=reference))
    assert outcome.reservation.lineage_id != reference.lineage_id
    assert any(finding.code == "POSSIBLE_DUPLICATE" for finding in outcome.findings)


def test_valid_correction_reuses_lineage_only_after_terminal_cleanup(tmp_path: Path) -> None:
    module = _module()
    coordinator = _coordinator(tmp_path)
    original = coordinator.receive(_request())
    reference = module.CorrectionReference(
        original.reservation.lineage_id,
        original.reservation.attempt_id,
    )
    correction = coordinator.receive(
        _request(
            retry_key="publisher-retry-002",
            payload=b'{"spec_version":"1.0","product_name":"Corrected"}',
            correction_reference=reference,
        )
    )
    assert correction.reservation.lineage_id == original.reservation.lineage_id
    assert correction.reservation.attempt_id != original.reservation.attempt_id
    assert correction.receipt.correction_reference == reference


def test_correction_cannot_resume_while_original_cleanup_is_unresolved(
    tmp_path: Path,
) -> None:
    module = _module()
    coordinator = _coordinator(tmp_path)
    original = coordinator.ledger.reserve(
        retry_key="original",
        publisher="pm-agent-os",
        channel="contract-api",
        correction_reference=None,
    )
    reference = module.CorrectionReference(original.lineage_id, original.attempt_id)
    blocked = coordinator.receive(_request(retry_key="correction", correction_reference=reference))
    assert blocked.status == "SECURITY_BLOCKED"
    assert blocked.admitted_payload is None
    assert any(finding.code == "CORRECTION_PREDECESSOR_UNRESOLVED" for finding in blocked.findings)
    assert not coordinator.quarantine.exists(blocked.reservation.quarantine_handle)


def test_receipt_failure_remains_reconcilable_under_original_handle(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    ledger = coordinator.ledger
    real_finalize = ledger.finalize_receipt

    def fail_once(receipt: Any) -> None:
        ledger.finalize_receipt = real_finalize
        raise OSError("simulated durable receipt failure")

    ledger.finalize_receipt = fail_once
    outcome = coordinator.receive(_request())
    assert outcome.status == "SECURITY_BLOCKED"
    reservation = ledger.reservation_for_retry_key("publisher-retry-001")
    assert reservation.quarantine_handle == outcome.reservation.quarantine_handle
    assert reservation.reconciliation_required
    assert any(finding.code == "RECEIPT_FINALIZATION_FAILED" for finding in outcome.findings)


def test_deletion_failure_is_security_blocked_and_never_ordinary_rejection(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator(tmp_path)
    real_delete = coordinator.quarantine.delete

    def fail_delete(handle: str) -> Any:
        raise OSError("simulated deletion failure")

    coordinator.quarantine.delete = fail_delete
    outcome = coordinator.receive(_request(b"{not-json"))
    assert outcome.status == "SECURITY_BLOCKED"
    assert outcome.disposition.status == "SECURITY_BLOCKED"
    assert outcome.quarantine_retained
    assert outcome.reservation.reconciliation_required
    coordinator.quarantine.delete = real_delete


def test_disposition_failure_after_deletion_remains_reconcilable(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator(tmp_path)
    ledger = coordinator.ledger
    real_write = ledger.write_disposition

    def fail_once(disposition: Any) -> None:
        ledger.write_disposition = real_write
        raise OSError("simulated disposition failure")

    ledger.write_disposition = fail_once
    outcome = coordinator.receive(_request(b"{not-json"))
    assert outcome.status == "SECURITY_BLOCKED"
    assert outcome.deletion_attestation.deleted
    assert outcome.reservation.reconciliation_required
    assert any(finding.code == "DISPOSITION_WRITE_FAILED" for finding in outcome.findings)


def test_reconciler_completes_cleanup_or_keeps_security_blocked(tmp_path: Path) -> None:
    module = _module()
    coordinator = _coordinator(tmp_path)
    original_delete = coordinator.quarantine.delete

    def fail_delete(handle: str) -> Any:
        raise OSError("simulated temporary deletion failure")

    coordinator.quarantine.delete = fail_delete
    blocked = coordinator.receive(_request(b"{not-json"))
    assert blocked.status == "SECURITY_BLOCKED"
    coordinator.quarantine.delete = original_delete
    report = module.IntakeReconciler(
        ledger=coordinator.ledger,
        quarantine=coordinator.quarantine,
        clock=FixedClock(),
    ).reconcile()
    assert report.resolved_attempt_ids == (blocked.reservation.attempt_id,)
    reservation = coordinator.ledger.reservation_by_attempt(blocked.reservation.attempt_id)
    assert not reservation.reconciliation_required
    assert coordinator.ledger.disposition(blocked.reservation.attempt_id).terminal


def test_orphan_watchdog_blocks_reserved_handle_and_reconciles_it(tmp_path: Path) -> None:
    module = _module()
    coordinator = _coordinator(tmp_path)
    reservation = coordinator.ledger.reserve(
        retry_key="orphan",
        publisher="pm-agent-os",
        channel="contract-api",
        correction_reference=None,
    )
    coordinator.quarantine.put(
        reservation.quarantine_handle,
        VALID_PAYLOAD,
        {"ordinary_digest": hashlib.sha256(VALID_PAYLOAD).hexdigest()},
    )
    report = module.IntakeReconciler(
        ledger=coordinator.ledger,
        quarantine=coordinator.quarantine,
        clock=FixedClock(),
    ).reconcile()
    assert reservation.attempt_id in report.resolved_attempt_ids
    assert not coordinator.quarantine.exists(reservation.quarantine_handle)
    disposition = coordinator.ledger.disposition(reservation.attempt_id)
    assert disposition.status == "SECURITY_BLOCKED"
    assert disposition.terminal


def test_terminal_retry_never_allocates_second_quarantine_object(tmp_path: Path) -> None:
    ids = SequenceIds()
    coordinator = _coordinator(tmp_path, ids=ids)
    first = coordinator.receive(_request())
    second = coordinator.receive(_request())
    assert first.reservation.quarantine_handle == second.reservation.quarantine_handle
    assert ids.counts["quarantine"] == 1
    assert ids.counts["attempt"] == 1
    assert ids.counts["lineage"] == 1


def test_no_public_fingerprint_validation_or_payload_logging_api(tmp_path: Path) -> None:
    module = _module()
    coordinator = _coordinator(tmp_path)
    coordinator.receive(_request())
    public_names = {name for name in dir(module) if not name.startswith("_")}
    assert "validate_fingerprint" not in public_names
    assert "verify_fingerprint" not in public_names
    ledger_text = "\n".join(
        path.read_text(errors="ignore")
        for path in (tmp_path / "ledger").rglob("*")
        if path.is_file()
    )
    assert "Safe Product" not in ledger_text
    assert hashlib.sha256(VALID_PAYLOAD).hexdigest() not in ledger_text
