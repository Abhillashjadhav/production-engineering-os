from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from pmpe.support_package import (
    PackageContractError,
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


def test_contract_requires_approval_and_exact_known_fields(tmp_path: Path) -> None:
    payload = _contract()
    payload["contract_status"] = "DRAFT"
    with pytest.raises(PackageContractError, match="approved"):
        load_support_package_contract(_write_contract(tmp_path, payload))

    payload = _contract()
    payload["deployment_provider"] = "aws"
    with pytest.raises(PackageContractError, match="unknown field"):
        load_support_package_contract(_write_contract(tmp_path, payload))


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
    result = assemble_support_package(_write_contract(tmp_path), bundle)
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


def test_bundle_verification_fails_closed_on_source_or_corpus_tampering(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    assemble_support_package(_write_contract(tmp_path), bundle)
    (bundle / "app.py").write_text("print('tampered')\n")
    with pytest.raises(PackageContractError, match="digest"):
        verify_support_package(bundle)

    bundle = tmp_path / "second"
    assemble_support_package(_write_contract(tmp_path), bundle)
    (bundle / "recorded-corpus.json").write_text("{}\n")
    with pytest.raises(PackageContractError, match="digest"):
        verify_support_package(bundle)


def test_package_contains_no_secret_values_and_records_an_sbom(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    assemble_support_package(_write_contract(tmp_path), bundle)

    all_text = "\n".join(
        path.read_text(errors="replace")
        for path in bundle.rglob("*")
        if path.is_file()
    )
    assert "OPENAI_API_KEY=" not in all_text
    assert "DATABASE_URL=" not in all_text
    sbom = json.loads((bundle / "sbom.spdx.json").read_text())
    assert sbom["spdxVersion"] == "SPDX-2.3"
    assert sbom["packages"][0]["name"] == "customer-support-agent"


def test_clean_runtime_journey_uses_only_reference_adapters(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    assemble_support_package(_write_contract(tmp_path), bundle)
    port = 18765
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
    finally:
        process.terminate()
        process.wait(timeout=5)
