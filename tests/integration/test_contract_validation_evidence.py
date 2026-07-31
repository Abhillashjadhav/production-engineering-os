"""Issue #63 immutable validation evidence and first-pass accounting contract."""

from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from pmpe.contracts.canonical import canonical_digest
from pmpe.contracts.intake import CorrectionReference
from tests.integration.test_pmos_compilation_pipeline import _request, _service

ROOT = Path(__file__).resolve().parents[2]
VALID_BUNDLE = ROOT / "tests" / "fixtures" / "pmos" / "v1" / "valid_bundle.json"


def _api() -> ModuleType:
    try:
        return importlib.import_module("pmpe.validation.contracts")
    except ModuleNotFoundError:
        pytest.fail(
            "issue #63 validation evidence implementation is absent",
            pytrace=False,
        )


def _bundle() -> dict[str, Any]:
    bundle = json.loads(VALID_BUNDLE.read_text())
    for policy in bundle["metrics"]["maturity_policies"].values():
        policy["target"] = {
            "operator": "AT_LEAST",
            "status": "APPROVED",
            "unit": "ratio",
            "value": 0.8,
        }
    for approval in bundle["approvals"].values():
        subject = approval["subject"]
        if subject["digest_scope"] == "NAMED_METRIC_MATURITY_POLICY":
            subject["digest"] = canonical_digest(
                bundle["metrics"]["maturity_policies"][subject["id"]]
            )
        elif subject["digest_scope"] == "NAMED_METRIC_REPORTING_POLICY":
            subject["digest"] = canonical_digest(
                bundle["metrics"]["reporting_policies"][subject["id"]]
            )
    for extension in bundle["extensions"].values():
        extension["payload_digest"] = canonical_digest(extension["payload"])
    projection = copy.deepcopy(bundle)
    projection.pop("approvals")
    bundle["approvals"]["APR-CONTRACT-001"]["subject"]["digest"] = canonical_digest(projection)
    return bundle


def _context(
    bundle: dict[str, Any],
    lineage: str,
    attempt: str,
    *,
    correction: CorrectionReference | None = None,
) -> Any:
    api = _api()
    return api.ValidationContext(
        lineage_id=lineage,
        ingestion_attempt_id=attempt,
        bundle_digest=canonical_digest(bundle),
        evaluated_at="2026-07-31T00:00:00Z",
        lineage_received_at="2026-07-30T12:00:00Z",
        correction_reference=correction,
    )


def test_first_attempt_is_counted_once_and_correction_cannot_erase_it(tmp_path: Path) -> None:
    api = _api()
    validator = api.ContractSemanticValidator()
    store = api.FileValidationEvidenceStore(tmp_path / "evidence")
    first_bundle = _bundle()
    del first_bundle["product"]
    first = validator.validate(
        first_bundle,
        _context(first_bundle, "LINEAGE-000001", "ATTEMPT-000001"),
    )
    store.record(first)

    corrected_bundle = _bundle()
    corrected = validator.validate(
        corrected_bundle,
        _context(
            corrected_bundle,
            "LINEAGE-000001",
            "ATTEMPT-000002",
            correction=CorrectionReference(
                lineage_id="LINEAGE-000001",
                attempt_id="ATTEMPT-000001",
            ),
        ),
    )
    store.record(corrected)
    summary = store.lineage_summary("LINEAGE-000001")
    assert summary["denominator_entries"] == 1
    assert summary["first_pass_attempt_id"] == "ATTEMPT-000001"
    assert summary["first_pass_disposition"] == "PRODUCT_INPUT_REQUIRED"
    assert summary["latest_disposition"] == "ADMITTED"
    assert summary["attempt_ids"] == ["ATTEMPT-000001", "ATTEMPT-000002"]


def test_evidence_is_write_once_and_replay_is_idempotent(tmp_path: Path) -> None:
    api = _api()
    bundle = _bundle()
    result = api.ContractSemanticValidator().validate(
        bundle,
        _context(bundle, "LINEAGE-000001", "ATTEMPT-000001"),
    )
    store = api.FileValidationEvidenceStore(tmp_path / "evidence")
    store.record(result)
    store.record(result)
    loaded = store.load_attempt("ATTEMPT-000001")
    assert loaded == result.as_dict()

    changed = copy.deepcopy(result.as_dict())
    changed["disposition"] = "WARNING"
    with pytest.raises(api.ValidationEvidenceError, match="different"):
        store._write_attempt_for_test("ATTEMPT-000001", changed)


def test_correction_requires_stored_original_attempt(tmp_path: Path) -> None:
    api = _api()
    bundle = _bundle()
    result = api.ContractSemanticValidator().validate(
        bundle,
        _context(
            bundle,
            "LINEAGE-000001",
            "ATTEMPT-000002",
            correction=CorrectionReference(
                lineage_id="LINEAGE-000001",
                attempt_id="ATTEMPT-MISSING",
            ),
        ),
    )
    store = api.FileValidationEvidenceStore(tmp_path / "evidence")
    with pytest.raises(api.ValidationEvidenceError, match="correction"):
        store.record(result)


def test_publisher_source_id_never_coalesces_immutable_lineages(tmp_path: Path) -> None:
    api = _api()
    store = api.FileValidationEvidenceStore(tmp_path / "evidence")
    bundle = _bundle()
    first = api.ContractSemanticValidator().validate(
        bundle,
        _context(bundle, "LINEAGE-000001", "ATTEMPT-000001"),
    )
    second = api.ContractSemanticValidator().validate(
        bundle,
        _context(bundle, "LINEAGE-000002", "ATTEMPT-000002"),
    )
    store.record(first)
    store.record(second)
    assert store.lineage_summary("LINEAGE-000001")["denominator_entries"] == 1
    assert store.lineage_summary("LINEAGE-000002")["denominator_entries"] == 1
    assert store.metric_summary()["first_pass_denominator"] == 2


def test_evidence_artifact_contains_no_raw_payload_or_secret(tmp_path: Path) -> None:
    api = _api()
    bundle = _bundle()
    secret = "ghp_0123456789abcdefghijklmnop"
    bundle["product"]["outcome"]["customer_outcome"] = f"Engineering decides {secret}"
    projection = copy.deepcopy(bundle)
    projection.pop("approvals")
    bundle["approvals"]["APR-CONTRACT-001"]["subject"]["digest"] = canonical_digest(projection)
    result = api.ContractSemanticValidator().validate(
        bundle,
        _context(bundle, "LINEAGE-000001", "ATTEMPT-000001"),
    )
    store = api.FileValidationEvidenceStore(tmp_path / "evidence")
    store.record(result)
    materialized = b"".join(path.read_bytes() for path in (tmp_path / "evidence").rglob("*json"))
    assert secret.encode() not in materialized
    assert b"quarantined" not in materialized


def test_compiler_output_binds_validation_to_issue_76_intake_identity(tmp_path: Path) -> None:
    api = _api()
    compiled = _service(tmp_path / "compilation").process(
        _request(ROOT / "tests" / "fixtures" / "minimal_valid_spec.json", "semantic-binding")
    )
    assert compiled.intake.receipt is not None
    assert compiled.compilation is not None
    context = api.ValidationContext.from_intake_receipt(
        compiled.intake.receipt,
        bundle_digest=compiled.compilation.bundle_digest,
        evaluated_at="2026-07-31T00:00:00Z",
    )
    result = api.ContractSemanticValidator().validate(compiled.compilation.bundle, context)
    assert result.lineage_id == compiled.intake.receipt.lineage_id
    assert result.ingestion_attempt_id == compiled.intake.receipt.attempt_id
    assert result.bundle_digest == compiled.compilation.bundle_digest
    assert result.disposition is api.Disposition.PRODUCT_INPUT_REQUIRED
    assert "COMP.UNRESOLVED_PRODUCT_TRUTH" in {
        diagnostic.rule_id for diagnostic in result.diagnostics
    }
