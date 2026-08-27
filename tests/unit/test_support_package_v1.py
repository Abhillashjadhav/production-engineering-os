from __future__ import annotations

import hashlib
import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

import pmpe.support_package as support_package_module
from pmpe.contracts.canonical import canonical_digest, canonical_json_bytes
from pmpe.evidence.ledger import EvidenceLedger
from pmpe.support_package import (
    PackageContractError,
    PackageResult,
    assemble_support_package,
    load_support_package_contract,
    verify_support_package,
)


def _contract() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "contract_status": "APPROVED",
        "approved_by": "fixture-human",
        "product": {
            "name": "customer-support-agent",
            "product_type": "customer_support",
            "product_version": "1.0.0",
        },
        "capabilities": {
            "required": [
                "ticket_intake",
                "policy_bound_decision",
                "prioritization",
                "response_drafting",
                "human_escalation",
            ],
            "forbidden": [
                "autonomous_refund_payment",
                "credential_collection",
            ],
        },
        "runtime": {
            "model_gateway": "recorded",
            "ticket_repository": "memory",
            "ticket_connector": "fixture",
        },
        "limits": {
            "max_model_calls_per_ticket": 2,
            "max_processing_seconds": 30,
            "max_response_bytes": 16384,
        },
        "escalation": {
            "missing_required_fact": True,
            "contradictory_facts": True,
            "forbidden_capability_attempt": True,
            "outside_policy_bounds": True,
            "additional_confidence_below": 0.75,
        },
    }


def _write_contract(tmp_path: Path, payload: dict[str, object] | None = None) -> Path:
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(payload or _contract()))
    return path


def _assemble(
    tmp_path: Path,
    bundle: Path,
    payload: dict[str, object] | None = None,
    *,
    verified_release_approval: bool = True,
    release_approver: str = "fixture-human",
) -> PackageResult:
    contract_path = _write_contract(tmp_path, payload)
    contract = json.loads(contract_path.read_text())
    receipt = {
        "schema_version": "1.0.0",
        "decision": "APPROVED",
        "approved_by": "fixture-human",
        "approved_contract_digest": canonical_digest(contract),
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    release_receipt = dict(receipt)
    release_receipt["approved_by"] = release_approver
    release_receipt.pop("receipt_digest")
    release_receipt["receipt_digest"] = canonical_digest(release_receipt)
    receipt_path = tmp_path / "approval-receipt.json"
    receipt_path.write_text(json.dumps(receipt))
    run_id = f"support-release-{bundle.name}"
    evidence_root = tmp_path / f"release-evidence-{bundle.name}"
    ledger = EvidenceLedger(evidence_root, run_id)
    app = support_package_module._APP_SOURCE.encode()
    binding = (canonical_digest(contract) + "\n").encode()
    app_digest = ledger.put_blob(app)
    binding_digest = ledger.put_blob(binding)
    candidate_manifest = {
        "app.py": app_digest,
        "package-contract-digest.txt": binding_digest,
    }
    candidate_digest = ledger.put_blob(canonical_json_bytes(candidate_manifest))
    contract_blob = ledger.put_blob(canonical_json_bytes(contract))
    receipt_blob = ledger.put_blob(canonical_json_bytes(release_receipt))
    ledger.append(
        event_type="contract_validated",
        state="VALIDATED",
        subject_digest=canonical_digest(contract),
        blob_digests=(contract_blob, receipt_blob),
        payload={
            "approval": (
                {
                    "status": "VERIFIED",
                    "authority": release_approver,
                    "receipt_digest": release_receipt["receipt_digest"],
                    "receipt_blob_digest": receipt_blob,
                }
                if verified_release_approval
                else {"status": "UNVERIFIED_DIRECT_CALL"}
            ),
            "contract_digest": contract_blob,
            "plan_digest": "sha256:" + "1" * 64,
        },
    )
    terminal = ledger.append(
        event_type="release_ready",
        state="RELEASE_READY",
        subject_digest=canonical_digest(contract),
        blob_digests=(app_digest, binding_digest, candidate_digest),
        payload={"candidate_digest": candidate_digest},
    )
    return assemble_support_package(
        contract_path,
        receipt_path,
        evidence_root,
        run_id,
        terminal["event_digest"],
        "fixture-human",
        bundle,
    )


def test_contract_requires_approval_and_exact_known_fields(tmp_path: Path) -> None:
    payload = _contract()
    payload["contract_status"] = "DRAFT"
    with pytest.raises(PackageContractError, match="approved"):
        load_support_package_contract(_write_contract(tmp_path, payload))

    payload = _contract()
    payload["deployment_provider"] = "aws"
    with pytest.raises(PackageContractError, match="unknown field"):
        load_support_package_contract(_write_contract(tmp_path, payload))


def test_published_contract_and_manifest_schemas_validate_reference_artifacts(
    tmp_path: Path,
) -> None:
    contract = _contract()
    contract_schema = json.loads(
        Path("src/pmpe/schemas/support_package_contract.schema.json").read_text()
    )
    Draft202012Validator(contract_schema).validate(contract)

    bundle = tmp_path / "bundle"
    _assemble(tmp_path, bundle, contract)
    manifest_schema = json.loads(
        Path("src/pmpe/schemas/support_package_manifest.schema.json").read_text()
    )
    Draft202012Validator(manifest_schema).validate(
        json.loads((bundle / "manifest.json").read_text())
    )


def test_capabilities_are_flat_exact_sets_without_graph_resolution(tmp_path: Path) -> None:
    payload = _contract()
    capabilities = payload["capabilities"]
    assert isinstance(capabilities, dict)
    capabilities["required"] = [*capabilities["required"], "unknown_capability"]
    with pytest.raises(PackageContractError, match="unsupported required capability"):
        load_support_package_contract(_write_contract(tmp_path, payload))


def test_every_forbidden_capability_has_a_negative_proof(tmp_path: Path) -> None:
    payload = _contract()
    capabilities = payload["capabilities"]
    assert isinstance(capabilities, dict)
    capabilities["forbidden"] = [*capabilities["forbidden"], "delete_customer_data"]
    with pytest.raises(PackageContractError, match="negative proof"):
        load_support_package_contract(_write_contract(tmp_path, payload))


def test_confidence_is_additive_and_deterministic_escalation_is_mandatory(
    tmp_path: Path,
) -> None:
    payload = _contract()
    escalation = payload["escalation"]
    assert isinstance(escalation, dict)
    escalation["missing_required_fact"] = False
    with pytest.raises(PackageContractError, match="deterministic escalation"):
        load_support_package_contract(_write_contract(tmp_path, payload))


def test_assembly_preserves_release_ready_and_emits_package_ready_manifest(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    result = _assemble(tmp_path, bundle)
    manifest = json.loads((bundle / "manifest.json").read_text())

    assert result.state == "PACKAGE_READY"
    assert manifest["state"] == "PACKAGE_READY"
    assert manifest["evidence_schema_version"] == "2.0.0-package"
    assert manifest["state_vocabulary"] == {
        "candidate_terminal": "RELEASE_READY",
        "package_terminal": "PACKAGE_READY",
    }
    assert manifest["ports"]["model_gateway"]["mode"] == "recorded"
    assert manifest["ports"]["model_gateway"]["corpus_digest"].startswith("sha256:")
    assert manifest["forbidden_capability_proofs"] == {
        "autonomous_refund_payment": (
            "tests/test_forbidden_capabilities.py::ForbiddenCapabilityTests::test_no_payment"
        ),
        "credential_collection": (
            "tests/test_forbidden_capabilities.py::ForbiddenCapabilityTests::test_no_credentials"
        ),
    }
    assert "observability" not in manifest["ports"]
    assert verify_support_package(bundle).state == "PACKAGE_READY"
    assert (
        verify_support_package(bundle, expected_manifest_digest=result.manifest_digest).state
        == "PACKAGE_READY"
    )
    with pytest.raises(PackageContractError, match="trusted expected digest"):
        verify_support_package(bundle, expected_manifest_digest="sha256:" + "0" * 64)


def test_bundle_verification_fails_closed_on_source_or_corpus_tampering(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _assemble(tmp_path, bundle)
    (bundle / "app.py").write_text("print('tampered')\n")
    with pytest.raises(PackageContractError, match="digest"):
        verify_support_package(bundle)

    bundle = tmp_path / "second"
    _assemble(tmp_path, bundle)
    (bundle / "recorded-corpus.json").write_text("{}\n")
    with pytest.raises(PackageContractError, match="digest"):
        verify_support_package(bundle)

    bundle = tmp_path / "symlink-bundle"
    _assemble(tmp_path, bundle)
    source = bundle / "app.py"
    target = tmp_path / "same-app.py"
    target.write_bytes(source.read_bytes())
    source.unlink()
    source.symlink_to(target)
    with pytest.raises(PackageContractError, match="symbolic link"):
        verify_support_package(bundle)


def test_bundle_verification_rederives_manifest_claims_and_approval(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _assemble(tmp_path, bundle)
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["claims"]["live_model_quality"] = "PROVEN"
    manifest.pop("manifest_digest")
    manifest["manifest_digest"] = canonical_digest(manifest)
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(PackageContractError, match="derived claims"):
        verify_support_package(bundle)

    bundle = tmp_path / "approval-tamper"
    _assemble(tmp_path, bundle)
    receipt_path = bundle / "approval-receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["approved_by"] = "attacker"
    receipt.pop("receipt_digest")
    receipt["receipt_digest"] = canonical_digest(receipt)
    receipt_path.write_text(json.dumps(receipt))
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["approval-receipt.json"] = (
        "sha256:" + hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    )
    manifest["package_subject_digest"] = canonical_digest(manifest["files"])
    manifest.pop("manifest_digest")
    manifest["manifest_digest"] = canonical_digest(manifest)
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(PackageContractError, match="approval"):
        verify_support_package(bundle)


def test_package_rejects_unapproved_release_run(tmp_path: Path) -> None:
    with pytest.raises(PackageContractError, match="verified release approval"):
        _assemble(tmp_path, tmp_path / "bundle", verified_release_approval=False)

    with pytest.raises(PackageContractError, match="verified release approval"):
        _assemble(tmp_path, tmp_path / "attacker-bundle", release_approver="attacker")


def test_package_verification_rederives_every_port(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _assemble(tmp_path, bundle)
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["ports"]["ticket_connector"]["mode"] = "live"
    manifest.pop("manifest_digest")
    manifest["manifest_digest"] = canonical_digest(manifest)
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(PackageContractError, match="port binding"):
        verify_support_package(bundle)


def test_nested_manifest_is_not_excluded_from_inventory(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _assemble(tmp_path, bundle)
    nested = bundle / "config" / "manifest.json"
    nested.parent.mkdir(exist_ok=True)
    nested.write_text("{}\n")
    with pytest.raises(PackageContractError, match="inventory"):
        verify_support_package(bundle)


def test_manifest_schema_version_and_unknown_fields_fail_closed(tmp_path: Path) -> None:
    for field, value in (("schema_version", "2.0.0"), ("unknown", True)):
        bundle = tmp_path / field
        _assemble(tmp_path, bundle)
        manifest_path = bundle / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest[field] = value
        manifest.pop("manifest_digest")
        manifest["manifest_digest"] = canonical_digest(manifest)
        manifest_path.write_text(json.dumps(manifest))
        with pytest.raises(PackageContractError, match="manifest schema"):
            verify_support_package(bundle)

    bundle = tmp_path / "approval-unknown"
    _assemble(tmp_path, bundle)
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["approval"]["unknown"] = True
    manifest.pop("manifest_digest")
    manifest["manifest_digest"] = canonical_digest(manifest)
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(PackageContractError, match="approval binding"):
        verify_support_package(bundle)


def test_each_declared_forbidden_proof_selector_must_execute(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _assemble(tmp_path, bundle)
    (bundle / "tests" / "test_forbidden_capabilities.py").write_text(
        "import unittest\nclass Unrelated(unittest.TestCase):\n"
        "    def test_passes(self): self.assertTrue(True)\n"
    )
    capabilities = _contract()["capabilities"]
    assert isinstance(capabilities, dict)
    forbidden = capabilities["forbidden"]
    assert isinstance(forbidden, list)
    assert all(isinstance(item, str) for item in forbidden)
    with pytest.raises(PackageContractError, match="proof did not execute"):
        support_package_module._run_reference_verification(bundle, forbidden)


def test_corpus_and_proof_implementations_are_verifier_owned(tmp_path: Path) -> None:
    for relative, replacement, message in (
        ("recorded-corpus.json", b"{}\n", "trusted v1 corpus"),
        (
            "tests/test_forbidden_capabilities.py",
            (
                b"import unittest\nclass ForbiddenCapabilityTests(unittest.TestCase):\n"
                b"    def test_no_payment(self): pass\n"
                b"    def test_no_credentials(self): pass\n"
            ),
            "proof implementation",
        ),
    ):
        bundle = tmp_path / relative.replace("/", "-")
        _assemble(tmp_path, bundle)
        target = bundle / relative
        target.write_bytes(replacement)
        manifest_path = bundle / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        digest = "sha256:" + hashlib.sha256(replacement).hexdigest()
        manifest["files"][relative] = digest
        if relative == "recorded-corpus.json":
            manifest["ports"]["model_gateway"]["corpus_digest"] = digest
        manifest["source_digest"] = canonical_digest(
            {name: value for name, value in manifest["files"].items() if name.endswith(".py")}
        )
        manifest["package_subject_digest"] = canonical_digest(manifest["files"])
        manifest.pop("manifest_digest")
        manifest["manifest_digest"] = canonical_digest(manifest)
        manifest_path.write_text(json.dumps(manifest))
        with pytest.raises(PackageContractError, match=message):
            verify_support_package(bundle)


def test_package_contains_no_secret_values_and_records_an_sbom(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _assemble(tmp_path, bundle)

    all_text = "\n".join(
        path.read_text(errors="replace") for path in bundle.rglob("*") if path.is_file()
    )
    assert "OPENAI_API_KEY=" not in all_text
    assert "DATABASE_URL=" not in all_text
    sbom = json.loads((bundle / "sbom.spdx.json").read_text())
    assert sbom["spdxVersion"] == "SPDX-2.3"
    assert sbom["packages"][0]["name"] == "customer-support-agent"


def test_clean_runtime_journey_uses_only_reference_adapters(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _assemble(tmp_path, bundle)
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = int(reservation.getsockname()[1])
    process = subprocess.Popen(
        [sys.executable, "app.py", "--port", str(port)],
        cwd=bundle,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        for _ in range(50):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/ready", timeout=0.2) as r:
                    assert r.status == 200
                    break
            except OSError:
                time.sleep(0.05)
        else:
            raise AssertionError("reference package did not become ready")

        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/tickets",
            data=json.dumps(
                {
                    "ticket_id": "TICKET-1",
                    "text": "The delivered item is damaged.",
                    "facts": ["delivery_damage"],
                }
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            result = json.loads(response.read())
        assert result["status"] == "DRAFTED"
        assert result["priority"] == "high"
        assert result["model_mode"] == "recorded"
        assert result["connector_mode"] == "fixture"

        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/tickets",
            data=json.dumps(
                {
                    "ticket_id": "TICKET-LOW-CONFIDENCE",
                    "text": "I need help with my order.",
                    "facts": ["general_request"],
                }
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            result = json.loads(response.read())
        assert result["status"] == "NEEDS_HUMAN_DECISION"
        assert result["reasons"] == ["recorded_confidence_below_threshold"]
        assert result["confidence"] == 0.7
    finally:
        process.terminate()
        process.wait(timeout=5)
