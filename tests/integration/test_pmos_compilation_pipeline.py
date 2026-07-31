"""Issue #76 integrated intake -> compile -> durable evidence lifecycle."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from tests.unit.test_pmos_intake import (
    CleanMalwareScanner,
    FixedClock,
    SequenceIds,
    TestCipher,
    TestFingerprintProvider,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
BUNDLE_SCHEMA = json.loads((ROOT / "schemas" / "pmos_contract_bundle.schema.json").read_text())
MANIFEST_SCHEMA = json.loads((ROOT / "schemas" / "pmos_contract_manifest.schema.json").read_text())


def _module(name: str) -> ModuleType:
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError:
        pytest.fail(f"issue #76 module {name!r} is not implemented", pytrace=False)


def _service(tmp_path: Path) -> Any:
    intake = _module("pmpe.contracts.intake")
    pipeline = _module("pmpe.contracts.pipeline")
    compiler = _module("pmpe.contracts.compiler")
    clock = FixedClock()
    ids = SequenceIds()
    fingerprints = TestFingerprintProvider()
    ledger = intake.FileIntakeLedger(
        tmp_path / "ledger",
        clock=clock,
        id_provider=ids,
        fingerprint_provider=fingerprints,
    )
    quarantine = intake.FileQuarantineStore(
        tmp_path / "quarantine",
        cipher=TestCipher(),
        max_bytes=2_000_000,
    )
    coordinator = intake.IntakeCoordinator(
        ledger=ledger,
        quarantine=quarantine,
        fingerprint_provider=fingerprints,
        malware_scanner=CleanMalwareScanner(),
        clock=clock,
        max_bytes=2_000_000,
        allowed_content_types={"application/json", "application/yaml"},
    )
    return pipeline.PmosCompilationService(
        intake=coordinator,
        compiler=compiler.CanonicalCompiler(),
        evidence_store=pipeline.FileCompilationEvidenceStore(tmp_path / "evidence"),
    )


def _request(path: Path, retry_key: str) -> Any:
    intake = _module("pmpe.contracts.intake")
    return intake.IntakeRequest(
        retry_key=retry_key,
        payload=path.read_bytes(),
        content_type="application/json",
        publisher="pm-agent-os",
        channel="contract-api",
        correction_reference=None,
    )


@pytest.mark.parametrize(
    ("fixture", "retry_key"),
    [
        (FIXTURES / "minimal_valid_spec.json", "v1"),
        (FIXTURES / "v2" / "contract_approved.json", "v2"),
        (FIXTURES / "v3" / "fullstack_contract_approved.json", "v3"),
    ],
)
def test_supported_input_produces_durable_schema_valid_evidence(
    tmp_path: Path,
    fixture: Path,
    retry_key: str,
) -> None:
    result = _service(tmp_path).process(_request(fixture, retry_key))
    assert result.status == "COMPILED_BLOCKED"
    assert result.compilation.blocked
    assert list(Draft202012Validator(BUNDLE_SCHEMA).iter_errors(result.compilation.bundle)) == []
    assert (
        list(Draft202012Validator(MANIFEST_SCHEMA).iter_errors(result.compilation.manifest)) == []
    )
    attempt_dir = tmp_path / "evidence" / result.intake.receipt.attempt_id
    assert (attempt_dir / "bundle.json").read_bytes() == result.compilation.bundle_bytes + b"\n"
    assert (attempt_dir / "manifest.json").read_bytes() == result.compilation.manifest_bytes + b"\n"
    evidence = json.loads((attempt_dir / "compiler-evidence.json").read_text())
    assert evidence["bundle_digest"] == result.compilation.bundle_digest
    assert evidence["manifest_digest"] == result.compilation.manifest_digest
    assert evidence["intake"]["lineage_id"] == result.intake.receipt.lineage_id
    assert evidence["intake"]["attempt_id"] == result.intake.receipt.attempt_id
    assert "payload" not in evidence["intake"]
    assert not result.intake.quarantine_retained


def test_acknowledgement_retry_returns_same_compilation_without_new_object(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    request = _request(FIXTURES / "minimal_valid_spec.json", "ack-retry")
    first = service.process(request)
    second = service.process(request)
    assert second.replayed
    assert second.intake.reservation == first.intake.reservation
    assert second.compilation.bundle_digest == first.compilation.bundle_digest
    assert second.compilation.manifest_digest == first.compilation.manifest_digest
    assert len(list((tmp_path / "evidence").iterdir())) == 1


def test_unsupported_source_is_deleted_and_emits_no_bundle_or_manifest(
    tmp_path: Path,
) -> None:
    intake = _module("pmpe.contracts.intake")
    request = intake.IntakeRequest(
        retry_key="unsupported",
        payload=b'{"spec_version":"9.9","product_name":"Unsupported"}',
        content_type="application/json",
        publisher="pm-agent-os",
        channel="contract-api",
        correction_reference=None,
    )
    result = _service(tmp_path).process(request)
    assert result.status == "COMPILATION_BLOCKED"
    assert result.compilation is None
    assert result.intake.deletion_attestation.deleted
    attempt_dir = tmp_path / "evidence" / result.intake.receipt.attempt_id
    assert not (attempt_dir / "bundle.json").exists()
    assert not (attempt_dir / "manifest.json").exists()
    diagnostic = json.loads((attempt_dir / "compiler-diagnostics.json").read_text())
    assert diagnostic["diagnostics"][0]["code"] == "UNSUPPORTED_SOURCE_VERSION"


def test_rejected_secret_never_reaches_compiler_or_immutable_evidence(tmp_path: Path) -> None:
    intake = _module("pmpe.contracts.intake")
    payload = b'{"spec_version":"1.0","token":"ghp_abcdefghijklmnopqrstuvwxyz123456"}'
    result = _service(tmp_path).process(
        intake.IntakeRequest(
            retry_key="secret",
            payload=payload,
            content_type="application/json",
            publisher="pm-agent-os",
            channel="contract-api",
            correction_reference=None,
        )
    )
    assert result.status == "INTAKE_REJECTED"
    assert result.compilation is None
    evidence_bytes = b"\n".join(
        path.read_bytes() for path in (tmp_path / "evidence").rglob("*") if path.is_file()
    )
    assert payload not in evidence_bytes
    assert b"ghp_" not in evidence_bytes


def test_compiler_evidence_is_bound_to_exact_intake_receipt(tmp_path: Path) -> None:
    result = _service(tmp_path).process(
        _request(FIXTURES / "v2" / "contract_approved.json", "receipt-binding")
    )
    evidence_path = (
        tmp_path / "evidence" / result.intake.receipt.attempt_id / "compiler-evidence.json"
    )
    evidence = json.loads(evidence_path.read_text())
    assert evidence["intake"] == {
        "attempt_id": result.intake.receipt.attempt_id,
        "fingerprint": result.intake.receipt.fingerprint,
        "key_version": result.intake.receipt.key_version,
        "lineage_id": result.intake.receipt.lineage_id,
        "received_at": result.intake.receipt.received_at,
    }
