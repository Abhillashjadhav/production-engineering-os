from __future__ import annotations

import hashlib
import json
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
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


def _trusted_verify(bundle: Path) -> PackageResult:
    manifest = json.loads((bundle / "manifest.json").read_text())
    return verify_support_package(bundle, expected_manifest_digest=str(manifest["manifest_digest"]))


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


@pytest.mark.parametrize("threshold", [0.01, 0.6, 0.7, 0.9, 0.99])
def test_every_admitted_confidence_threshold_is_provable(tmp_path: Path, threshold: float) -> None:
    payload = _contract()
    escalation = payload["escalation"]
    assert isinstance(escalation, dict)
    escalation["additional_confidence_below"] = threshold
    result = _assemble(tmp_path, tmp_path / f"bundle-{threshold}", payload)
    assert result.state == "PACKAGE_READY"


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
    assert _trusted_verify(bundle).state == "PACKAGE_READY"
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
        _trusted_verify(bundle)

    bundle = tmp_path / "second"
    _assemble(tmp_path, bundle)
    (bundle / "recorded-corpus.json").write_text("{}\n")
    with pytest.raises(PackageContractError, match="digest"):
        _trusted_verify(bundle)

    bundle = tmp_path / "symlink-bundle"
    _assemble(tmp_path, bundle)
    source = bundle / "app.py"
    target = tmp_path / "same-app.py"
    target.write_bytes(source.read_bytes())
    source.unlink()
    source.symlink_to(target)
    with pytest.raises(PackageContractError, match="symbolic link"):
        _trusted_verify(bundle)


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
        _trusted_verify(bundle)

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
        _trusted_verify(bundle)


def test_bundle_verification_binds_runtime_policy_to_contract(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _assemble(tmp_path, bundle)
    policy_path = bundle / "runtime-policy.json"
    policy_path.write_text('{"additional_confidence_below":0.8,"max_processing_seconds":30}\n')
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["runtime-policy.json"] = (
        "sha256:" + hashlib.sha256(policy_path.read_bytes()).hexdigest()
    )
    manifest["package_subject_digest"] = canonical_digest(manifest["files"])
    manifest.pop("manifest_digest")
    manifest["manifest_digest"] = canonical_digest(manifest)
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(PackageContractError, match="runtime policy"):
        _trusted_verify(bundle)


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
        _trusted_verify(bundle)


def test_nested_manifest_is_not_excluded_from_inventory(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _assemble(tmp_path, bundle)
    nested = bundle / "config" / "manifest.json"
    nested.parent.mkdir(exist_ok=True)
    nested.write_text("{}\n")
    with pytest.raises(PackageContractError, match="inventory"):
        _trusted_verify(bundle)


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
            _trusted_verify(bundle)

    bundle = tmp_path / "approval-unknown"
    _assemble(tmp_path, bundle)
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["approval"]["unknown"] = True
    manifest.pop("manifest_digest")
    manifest["manifest_digest"] = canonical_digest(manifest)
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(PackageContractError, match="approval binding"):
        _trusted_verify(bundle)


def test_runtime_proofs_execute_only_digest_pinned_application_bytes(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _assemble(tmp_path, bundle)
    capabilities = _contract()["capabilities"]
    assert isinstance(capabilities, dict)
    forbidden = capabilities["forbidden"]
    assert isinstance(forbidden, list)
    assert all(isinstance(item, str) for item in forbidden)
    expected_files = {
        name: "sha256:" + hashlib.sha256((bundle / name).read_bytes()).hexdigest()
        for name in ("app.py", "recorded-corpus.json", "runtime-policy.json")
    }
    (bundle / "app.py").write_text("raise RuntimeError('must never execute')\n")
    with pytest.raises(PackageContractError, match="inputs changed before immutable verification"):
        support_package_module._run_reference_verification(
            bundle,
            forbidden,
            expected_files,
        )


def test_runtime_proofs_require_completion_and_standard_library_imports(tmp_path: Path) -> None:
    capabilities = _contract()["capabilities"]
    assert isinstance(capabilities, dict)
    forbidden = capabilities["forbidden"]
    assert isinstance(forbidden, list)
    assert all(isinstance(item, str) for item in forbidden)
    for index, (source, message) in enumerate(
        (
            ("raise SystemExit(0)\n", "differs from canonical v1"),
            ("import third_party_only_on_main\n", "non-standard-library dependency"),
            ("third_party = __import__('third_party')\n", "unresolved dynamic import"),
            (
                "loader = __import__\nthird_party = loader('third_party')\n",
                "unresolved dynamic import",
            ),
            (
                "import builtins\nloader = getattr(builtins, '__import__')\n"
                "third_party = loader('third_party')\n",
                "unresolved dynamic import",
            ),
            (
                "def decide(payload):\n    return 200, {'status': 'DRAFTED'}\n",
                "differs from canonical v1",
            ),
        )
    ):
        bundle = tmp_path / f"{index}-{message.replace(' ', '-')}"
        _assemble(tmp_path, bundle)
        (bundle / "app.py").write_text(source)
        expected_files = {
            name: "sha256:" + hashlib.sha256((bundle / name).read_bytes()).hexdigest()
            for name in ("app.py", "recorded-corpus.json", "runtime-policy.json")
        }
        with pytest.raises(PackageContractError, match=message):
            support_package_module._run_reference_verification(bundle, forbidden, expected_files)


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
            _trusted_verify(bundle)


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
    assert sbom["creationInfo"]["created"] == "2026-08-27T00:00:00Z"
    assert sbom["packages"][0]["name"] == "customer-support-agent"
    assert sbom["packages"][0]["filesAnalyzed"] is False
    assert sbom["packages"][0]["licenseConcluded"] == "NOASSERTION"
    assert sbom["packages"][0]["licenseDeclared"] == "NOASSERTION"
    assert sbom["packages"][0]["copyrightText"] == "NOASSERTION"


@pytest.mark.parametrize(
    "secret",
    [
        "AWS_ACCESS_KEY_ID=AKIAABCDEFGHIJKLMNOP",
        'password = "hunter2"',
        "ghp_0123456789abcdefghijklmnop",
        "github_pat_0123456789abcdefghijklmnop",
        "glpat-0123456789abcdefghijklmnop",
        "xox" + "b-0123456789-abcdefghijklmnop",
        "https://example.com/callback?code=abcdefghijklmnop",
        "https://example.com/callback#code=abcdefghijklmnop",
        "https://hooks.slack.com/services/T00000000/B00000000/abcdefghijklmnop",
        "//hooks.slack.com/services/T00000000/B00000000/abcdefghijklmnop",
        "///hooks.slack.com/services/T00000000/B00000000/abcdefghijklmnop",
        "\\\\hooks.slack.com\\services\\T00000000\\B00000000\\abcdefghijklmnop",
        "//hooks%2eslack.com/services/T00000000/B00000000/abcdefghijklmnop",
        "//hooks.slack.com/servi\tces/T00000000/B00000000/abcdefghijklmnop",
        '{"webhook":"https://hooks.slack.com/servi\\tces/T/B/abcdefghijklmnop"}',
        '{"webhook":"https://hooks.slack.com/servi\\u0009ces/T/B/abcdefghijklmnop"}',
        '{"webhook":"https:\\/\\/hooks.slack.com\\/services\\/T\\/B\\/abcdefghijklmnop"}',
        '{"webhook":"https://hooks.slack.com/servi\\u0063es/T/B/abcdefghijklmnop"}',
        '["https:\\/\\/hooks.slack.com\\/services\\/T\\/B\\/abcdefghijklmnop"]',
        '{"to\\u006ben":"abcdefghijklmnop"}',
        '{"x-api-\\u006bey":"abcdefghijklmnop"}',
        '\ufeff["https:\\/\\/hooks.slack.com\\/services\\/T\\/B\\/abcdefghijklmnop"]',
        '{"webhook":"https:\\/\\/hooks.slack.com\\/services\\/T\\/B\\/abcdefghijklmnop"}\n{"ok":true}',
        '{\n  "webhook": "https:\\/\\/hooks.slack.com\\/services\\/T\\/B\\/'
        'abcdefghijklmnop"\n}\n{"ok":true}',
        '{"ok":true}\nnot-json\n'
        '{"webhook":"https:\\/\\/hooks.slack.com\\/services\\/T\\/B\\/abcdefghijklmnop"}',
        'true\njunk {"webhook":"https:\\/\\/hooks.slack.com\\/services\\/T\\/B\\/'
        'abcdefghijklmnop"}',
        'junk\n"{\\"webhook\\":\\"https:\\\\/\\\\/hooks.slack.com\\\\/services'
        '\\\\/T\\\\/B\\\\/abcdefghijklmnop\\"}"',
        "https://hooks.slack.com/foo/../services/T00000000/B00000000/abcdefghijklmnop",
        "https://canary.discord.com/api/webhooks/123456/abcdefghijklmnop",
        "https://canary.discord.com/%61pi/webhooks/123456/abcdefghijklmnop",
        "https://api.telegram.org/%62ot123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ/sendMessage",
    ],
)
def test_secret_scan_covers_copied_release_evidence(tmp_path: Path, secret: str) -> None:
    blob = tmp_path / "release-evidence" / ".pmpe" / "blobs" / "historical"
    blob.parent.mkdir(parents=True)
    blob.write_text(secret + "\n")
    with pytest.raises(PackageContractError, match="secret value pattern"):
        support_package_module._secret_scan(tmp_path)


def test_secret_scan_rejects_redundant_scheme_slash_webhook(tmp_path: Path) -> None:
    blob = tmp_path / "release-evidence" / ".pmpe" / "blobs" / "historical"
    blob.parent.mkdir(parents=True)
    blob.write_text("https:////hooks.slack.com/services/T/B/abcdefghijklmnop\n")
    with pytest.raises(PackageContractError, match="secret value pattern"):
        support_package_module._secret_scan(tmp_path)


@pytest.mark.parametrize("separator", ["", "/"])
def test_secret_scan_rejects_special_scheme_webhook_without_authority_slashes(
    tmp_path: Path, separator: str
) -> None:
    blob = tmp_path / "release-evidence" / ".pmpe" / "blobs" / "historical"
    blob.parent.mkdir(parents=True)
    blob.write_text(f"https:{separator}hooks.slack.com/services/T/B/abcdefghijklmnop\n")
    with pytest.raises(PackageContractError, match="secret value pattern"):
        support_package_module._secret_scan(tmp_path)


def test_reference_verification_preserves_windows_systemroot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = tmp_path / "bundle"
    _assemble(tmp_path, bundle)
    captured: list[dict[str, str]] = []
    original_popen = subprocess.Popen

    def record_environment(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        environment = kwargs.get("env")
        assert isinstance(environment, dict)
        captured.append(environment)
        return original_popen(*args, **kwargs)  # type: ignore[arg-type,return-value]

    monkeypatch.setenv("SYSTEMROOT", r"C:\\Windows")
    monkeypatch.setattr(subprocess, "Popen", record_environment)
    _trusted_verify(bundle)
    assert captured
    assert all(item["SYSTEMROOT"] == r"C:\\Windows" for item in captured)


def test_secret_scan_rejects_non_utf8_copied_evidence(tmp_path: Path) -> None:
    blob = tmp_path / "release-evidence" / ".pmpe" / "blobs" / "historical"
    blob.parent.mkdir(parents=True)
    blob.write_bytes("https://hooks.slack.com/services/T/B/abcdefghijklmnop".encode("utf-16le"))
    with pytest.raises(PackageContractError, match="NUL bytes"):
        support_package_module._secret_scan(tmp_path)


def test_secret_scan_fails_closed_at_nested_json_depth_limit(tmp_path: Path) -> None:
    value: object = {
        "webhook": "\\u0068ttps:\\/\\/hooks.slack.com\\/services\\/T\\/B\\/abcdefghijklmnop"
    }
    for _ in range(5):
        value = json.dumps(value)
    blob = tmp_path / "release-evidence" / ".pmpe" / "blobs" / "historical"
    blob.parent.mkdir(parents=True)
    blob.write_text(str(value))
    with pytest.raises(PackageContractError, match="JSON decode depth"):
        support_package_module._secret_scan(tmp_path)


def test_secret_scan_enforces_malformed_json_recovery_limit(tmp_path: Path) -> None:
    blob = tmp_path / "release-evidence" / ".pmpe" / "blobs" / "historical"
    blob.parent.mkdir(parents=True)
    blob.write_text("{" * 4_098)
    with pytest.raises(PackageContractError, match="JSON stream exceeds scan limit"):
        support_package_module._secret_scan(tmp_path)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/docs#install",
        "https://example.com/search?q=hello%20world",
        "https://discord.com/developers/docs/intro",
        "https://support.discord.com/hc/en-us",
    ],
)
def test_secret_scan_allows_ordinary_url_normalization(tmp_path: Path, url: str) -> None:
    blob = tmp_path / "release-evidence" / ".pmpe" / "blobs" / "historical"
    blob.parent.mkdir(parents=True)
    blob.write_text(url + "\n")
    support_package_module._secret_scan(tmp_path)


def test_failed_release_preflight_does_not_reserve_run_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_preflight(*args: object, **kwargs: object) -> dict[str, object]:
        raise PackageContractError("preflight failed")

    monkeypatch.setattr(support_package_module, "_run_reference_verification", fail_preflight)
    with pytest.raises(PackageContractError, match="preflight failed"):
        support_package_module.seal_support_release(
            Path("examples/support-package/contract.json"),
            Path("examples/support-package/approval-receipt.json"),
            tmp_path,
            "retryable-run",
            "fixture-human",
        )
    assert not (tmp_path / ".pmpe" / "runs" / "retryable-run" / "events.jsonl").exists()


def test_interrupted_release_ledger_is_not_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_append = EvidenceLedger.append

    def interrupt_terminal(self: EvidenceLedger, **kwargs: object) -> Mapping[str, object]:
        if kwargs.get("event_type") == "release_ready":
            raise OSError("interrupted")
        return original_append(self, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(EvidenceLedger, "append", interrupt_terminal)
    with pytest.raises(PackageContractError, match="ledger publication failed"):
        support_package_module.seal_support_release(
            Path("examples/support-package/contract.json"),
            Path("examples/support-package/approval-receipt.json"),
            tmp_path,
            "interrupted-run",
            "fixture-human",
        )
    assert not (tmp_path / ".pmpe" / "runs" / "interrupted-run").exists()


def test_committed_release_and_bundle_are_idempotently_recoverable(tmp_path: Path) -> None:
    first = support_package_module.seal_support_release(
        Path("examples/support-package/contract.json"),
        Path("examples/support-package/approval-receipt.json"),
        tmp_path / "release",
        "idempotent-run",
        "fixture-human",
    )
    second = support_package_module.seal_support_release(
        Path("examples/support-package/contract.json"),
        Path("examples/support-package/approval-receipt.json"),
        tmp_path / "release",
        "idempotent-run",
        "fixture-human",
    )
    assert second == first

    bundle = tmp_path / "bundle"
    built = _assemble(tmp_path, bundle)
    manifest = json.loads((bundle / "manifest.json").read_text())
    with socket.socket() as occupied_port:
        occupied_port.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        occupied_port.bind(("127.0.0.1", 8080))
        recovered = assemble_support_package(
            tmp_path / "contract.json",
            tmp_path / "approval-receipt.json",
            tmp_path / "release-evidence-bundle",
            "support-release-bundle",
            manifest["release_candidate"]["head_event_digest"],
            "fixture-human",
            bundle,
        )
    assert recovered == built

    (bundle / "Dockerfile").write_text('FROM busybox\nCMD ["false"]\n')
    manifest = json.loads((bundle / "manifest.json").read_text())
    manifest["files"]["Dockerfile"] = (
        "sha256:" + hashlib.sha256((bundle / "Dockerfile").read_bytes()).hexdigest()
    )
    manifest["package_subject_digest"] = canonical_digest(manifest["files"])
    manifest.pop("manifest_digest")
    manifest["manifest_digest"] = canonical_digest(manifest)
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(PackageContractError, match="requested deterministic build"):
        assemble_support_package(
            tmp_path / "contract.json",
            tmp_path / "approval-receipt.json",
            tmp_path / "release-evidence-bundle",
            "support-release-bundle",
            manifest["release_candidate"]["head_event_digest"],
            "fixture-human",
            bundle,
        )


def test_failed_final_verification_does_not_publish_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = tmp_path / "bundle"

    def fail_verification(*args: object, **kwargs: object) -> PackageResult:
        raise PackageContractError("final verification failed")

    monkeypatch.setattr(support_package_module, "_verify_support_package", fail_verification)
    with pytest.raises(PackageContractError, match="final verification failed"):
        _assemble(tmp_path, bundle)
    assert not bundle.exists()


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


def test_runtime_enforces_approved_request_deadline(tmp_path: Path) -> None:
    payload = _contract()
    limits = payload["limits"]
    assert isinstance(limits, dict)
    limits["max_processing_seconds"] = 1
    bundle = tmp_path / "deadline-bundle"
    _assemble(tmp_path, bundle, payload)
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
    stdout = ""
    try:
        for _ in range(50):
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/ready", timeout=0.2
                ) as response:
                    assert response.status == 200
                    break
            except OSError:
                time.sleep(0.05)
        else:
            raise AssertionError("reference package did not become ready")

        with socket.create_connection(("127.0.0.1", port), timeout=3) as client:
            client.sendall(
                b"POST /tickets HTTP/1.1\r\nHost: localhost\r\n"
                b"Content-Length: 100\r\nContent-Type: application/json\r\n\r\n"
            )

            def drip_body() -> None:
                for _ in range(6):
                    time.sleep(0.4)
                    try:
                        client.sendall(b"{")
                    except OSError:
                        return

            sender = threading.Thread(target=drip_body)
            started = time.monotonic()
            sender.start()
            response = client.recv(4096)
            elapsed = time.monotonic() - started
            sender.join(timeout=3)
        assert response == b"" or b" 400 " in response
        assert elapsed < 2.5

        with socket.create_connection(("127.0.0.1", port), timeout=3) as client:
            client.sendall(b"POST /tickets HTTP/1.1\r\nX-Slow: ")

            def drip_header() -> None:
                for _ in range(6):
                    time.sleep(0.4)
                    try:
                        client.sendall(b"x")
                    except OSError:
                        return

            sender = threading.Thread(target=drip_header)
            started = time.monotonic()
            sender.start()
            client.recv(4096)
            elapsed = time.monotonic() - started
            sender.join(timeout=3)
        assert elapsed < 2.5

        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{port}/missing?access_token=live-secret",
                timeout=2,
            )
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
    finally:
        process.terminate()
        stdout, _ = process.communicate(timeout=5)
    assert "live-secret" not in stdout
