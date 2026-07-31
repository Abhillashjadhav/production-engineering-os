"""Issue #76 integrated intake -> compile -> durable evidence lifecycle."""

from __future__ import annotations

import hashlib
import hmac
import importlib
import json
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from pmpe.contracts.canonical import canonical_digest, canonical_json_bytes
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


class PipelineAuthorityVerifier:
    """Test-only authority issuer; production admission exposes verification only."""

    issuer_id = "TEST-PIPELINE-AUTHORITY-001"
    key_version = "TEST-PIPELINE-AUTHORITY-KEY-V1"
    _key = b"issue-63-pipeline-authority-test-key"

    def issue(self, bundle: dict[str, Any]) -> Any:
        validation = _module("pmpe.validation.contracts")
        evidence = validation.ApprovalAuthorityEvidence(
            bundle_digest=canonical_digest(bundle),
            approvals_digest=canonical_digest(bundle.get("approvals", {})),
            authority_grants=(),
            requirement_grants=(),
            issuer_id=self.issuer_id,
            key_version=self.key_version,
            attestation="",
        )
        attestation = hmac.new(
            self._key,
            b"validation-authority-attestation\x00"
            + canonical_json_bytes(evidence.signed_payload()),
            hashlib.sha256,
        ).hexdigest()
        return replace(evidence, attestation=attestation)

    def verify(self, evidence: Any) -> bool:
        if evidence.issuer_id != self.issuer_id or evidence.key_version != self.key_version:
            return False
        expected = hmac.new(
            self._key,
            b"validation-authority-attestation\x00"
            + canonical_json_bytes(evidence.signed_payload()),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, evidence.attestation)


PIPELINE_AUTHORITY = PipelineAuthorityVerifier()


class PipelineValidationFingerprintProvider:
    key_version = "TEST-PIPELINE-VALIDATION-KEY-V1"
    _key = b"issue-63-pipeline-validation-test-key"

    def fingerprint(self, domain: str, payload: bytes) -> str:
        return hmac.new(
            self._key,
            domain.encode() + b"\x00" + payload,
            hashlib.sha256,
        ).hexdigest()

    def candidate_fingerprints(self, domain: str, payload: bytes) -> tuple[Any, ...]:
        intake = _module("pmpe.contracts.intake")
        return (intake.KeyedFingerprint(self.key_version, self.fingerprint(domain, payload)),)


class PipelineValidationAuthorityProvider:
    def authority_for(
        self,
        bundle: dict[str, Any],
    ) -> Any:
        validation = _module("pmpe.validation.contracts")
        return validation.ValidationAuthority(
            authority_grants=(),
            approval_requirement_grants=(),
            authority_identity=PIPELINE_AUTHORITY.issue(bundle),
        )


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
    validation_fingerprints = PipelineValidationFingerprintProvider()
    validation = _module("pmpe.validation.contracts")
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
    validation_store = validation.FileValidationEvidenceStore(
        tmp_path / "validation-evidence",
        fingerprint_provider=validation_fingerprints,
        anchor_path=tmp_path / ".validation-high-watermark.json",
    )
    semantic_validator = validation.ContractSemanticValidator(
        fingerprint_provider=validation_fingerprints,
        authority_evidence_verifier=PIPELINE_AUTHORITY,
        evidence_lookup=validation_store,
    )
    admission = validation.CanonicalContractAdmission(
        validator=semantic_validator,
        evidence_store=validation_store,
        authority_provider=PipelineValidationAuthorityProvider(),
        fingerprint_provider=validation_fingerprints,
        clock=clock,
    )
    return pipeline.PmosCompilationService(
        intake=coordinator,
        compiler=compiler.CanonicalCompiler(),
        evidence_store=pipeline.FileCompilationEvidenceStore(
            tmp_path / "evidence",
            fingerprint_provider=fingerprints,
        ),
        admission_boundary=admission,
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
    assert result.validation is not None
    assert result.validation.disposition.value == "PRODUCT_INPUT_REQUIRED"
    assert not result.engineering_admissible
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
    assert evidence["intake"] == result.intake.receipt.as_dict()
    assert "payload" not in evidence["intake"]
    assert (attempt_dir / "evidence-attestation.json").exists()
    validation_attempt = (
        tmp_path
        / "validation-evidence"
        / "artifacts"
        / "attempts"
        / f"{result.intake.receipt.attempt_id}.json"
    )
    assert validation_attempt.exists()
    assert not result.intake.quarantine_retained


def test_semantic_admission_boundary_is_a_required_pipeline_dependency(
    tmp_path: Path,
) -> None:
    pipeline = _module("pmpe.contracts.pipeline")
    compiler = _module("pmpe.contracts.compiler")
    service = _service(tmp_path)
    with pytest.raises(TypeError, match="admission_boundary"):
        pipeline.PmosCompilationService(
            intake=service.intake,
            compiler=compiler.CanonicalCompiler(),
            evidence_store=service.evidence_store,
        )


def test_semantic_admission_failure_never_returns_an_admissible_outcome(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)

    class FailingBoundary:
        @staticmethod
        def admit(_bundle: dict[str, Any], _intake: Any) -> Any:
            raise RuntimeError("simulated validation evidence failure")

    service.admission_boundary = FailingBoundary()
    result = service.process(
        _request(FIXTURES / "minimal_valid_spec.json", "semantic-boundary-failure")
    )
    assert result.status == "VALIDATION_SECURITY_BLOCKED"
    assert result.validation is None
    assert not result.engineering_admissible


def test_tampered_semantic_evidence_fails_closed_on_pipeline_replay(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    request = _request(FIXTURES / "minimal_valid_spec.json", "semantic-evidence-tamper")
    first = service.process(request)
    assert first.intake.receipt is not None
    evidence_path = (
        tmp_path
        / "validation-evidence"
        / "artifacts"
        / "attempts"
        / f"{first.intake.receipt.attempt_id}.json"
    )
    envelope = json.loads(evidence_path.read_text())
    envelope["payload"]["disposition"] = "ADMITTED"
    evidence_path.write_text(json.dumps(envelope))
    replay = service.process(request)
    assert replay.status == "VALIDATION_SECURITY_BLOCKED"
    assert replay.validation is None
    assert not replay.engineering_admissible


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
    assert len([path for path in (tmp_path / "evidence").iterdir() if path.is_dir()]) == 1


def test_compiler_failure_keeps_validated_source_for_safe_retry(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    request = _request(FIXTURES / "minimal_valid_spec.json", "compiler-crash")
    real_compile = service.compiler.compile

    def fail_once(*args: Any, **kwargs: Any) -> Any:
        service.compiler.compile = real_compile
        raise RuntimeError("simulated compiler crash")

    service.compiler.compile = fail_once
    failed = service.process(request)
    assert failed.status == "COMPILATION_SECURITY_BLOCKED"
    assert failed.intake.quarantine_retained
    assert failed.intake.disposition.terminal is False
    retried = service.process(request)
    assert retried.status == "COMPILED_BLOCKED"
    assert retried.intake.deletion_attestation.deleted
    assert not retried.intake.quarantine_retained


def test_tampered_compilation_evidence_fails_closed_on_retry(tmp_path: Path) -> None:
    service = _service(tmp_path)
    request = _request(FIXTURES / "minimal_valid_spec.json", "tamper")
    first = service.process(request)
    bundle_path = tmp_path / "evidence" / first.intake.receipt.attempt_id / "bundle.json"
    bundle = json.loads(bundle_path.read_text())
    bundle["bundle_version"] = "9.9.9"
    bundle_path.write_text(json.dumps(bundle))
    replay = service.process(request)
    assert replay.status == "EVIDENCE_SECURITY_BLOCKED"
    assert replay.compilation is None
    assert replay.replayed


def test_forged_compilation_intake_binding_cannot_finalize_retained_source(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    request = _request(FIXTURES / "minimal_valid_spec.json", "forged-compilation-binding")
    real_finalize = service._finalize_intake
    service._finalize_intake = lambda outcome: outcome
    first = service.process(request)
    assert first.status == "INTAKE_SECURITY_BLOCKED"
    assert first.intake.quarantine_retained
    evidence_path = (
        tmp_path / "evidence" / first.intake.receipt.attempt_id / "compiler-evidence.json"
    )
    evidence = json.loads(evidence_path.read_text())
    evidence["intake"]["attempt_id"] = "ATTEMPT-999999"
    evidence_path.write_bytes(
        _module("pmpe.contracts.canonical").canonical_json_bytes(evidence) + b"\n"
    )
    service._finalize_intake = real_finalize
    replay = service.process(request)
    assert replay.status == "EVIDENCE_SECURITY_BLOCKED"
    assert replay.compilation is None
    assert replay.intake.quarantine_retained
    assert replay.intake.deletion_attestation is None


def test_self_consistent_compiler_provenance_forgery_fails_keyed_attestation(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    request = _request(FIXTURES / "minimal_valid_spec.json", "forged-provenance")
    first = service.process(request)
    evidence_path = (
        tmp_path / "evidence" / first.intake.receipt.attempt_id / "compiler-evidence.json"
    )
    evidence = json.loads(evidence_path.read_text())
    evidence["source_format"] = "PMOS_V3"
    evidence["source_version"] = "1"
    evidence_path.write_bytes(
        _module("pmpe.contracts.canonical").canonical_json_bytes(evidence) + b"\n"
    )
    replay = service.process(request)
    assert replay.status == "EVIDENCE_SECURITY_BLOCKED"
    assert replay.compilation is None


def test_forged_blocked_intake_binding_cannot_finalize_retained_source(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    intake = _module("pmpe.contracts.intake")
    request = intake.IntakeRequest(
        retry_key="forged-blocked-binding",
        payload=b'{"spec_version":"9.9","product_name":"Unsupported"}',
        content_type="application/json",
        publisher="pm-agent-os",
        channel="contract-api",
        correction_reference=None,
    )
    real_finalize = service._finalize_intake
    service._finalize_intake = lambda outcome: outcome
    first = service.process(request)
    assert first.status == "INTAKE_SECURITY_BLOCKED"
    assert first.intake.quarantine_retained
    evidence_path = (
        tmp_path / "evidence" / first.intake.receipt.attempt_id / "compiler-diagnostics.json"
    )
    evidence = json.loads(evidence_path.read_text())
    evidence["intake"]["attempt_id"] = "ATTEMPT-999999"
    evidence_path.write_bytes(
        _module("pmpe.contracts.canonical").canonical_json_bytes(evidence) + b"\n"
    )
    service._finalize_intake = real_finalize
    replay = service.process(request)
    assert replay.status == "EVIDENCE_SECURITY_BLOCKED"
    assert replay.compilation is None
    assert replay.intake.quarantine_retained
    assert replay.intake.deletion_attestation is None


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
    assert evidence["intake"] == result.intake.receipt.as_dict()
    assert evidence["intake"]["content_type"] == "application/json"
    assert evidence["intake"]["publisher"] == "pm-agent-os"
    assert evidence["intake"]["channel"] == "contract-api"
    assert evidence["intake"]["quarantine_handle"] == result.intake.receipt.quarantine_handle
