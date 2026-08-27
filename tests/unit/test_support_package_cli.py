from __future__ import annotations

import json
from pathlib import Path

import pmpe.support_package as support_package_module
from pmpe.cli import main
from pmpe.contracts.canonical import canonical_digest, canonical_json_bytes
from pmpe.evidence.ledger import EvidenceLedger


def _release_evidence(tmp_path: Path, contract: Path) -> tuple[Path, str, str]:
    payload = json.loads(contract.read_text())
    receipt = json.loads(Path("examples/support-package/approval-receipt.json").read_text())
    root = tmp_path / "release-evidence"
    run_id = "support-release"
    ledger = EvidenceLedger(root, run_id)
    app_digest = ledger.put_blob(support_package_module._APP_SOURCE.encode())
    binding_digest = ledger.put_blob((canonical_digest(payload) + "\n").encode())
    candidate_digest = ledger.put_blob(
        canonical_json_bytes(
            {
                "app.py": app_digest,
                "package-contract-digest.txt": binding_digest,
            }
        )
    )
    contract_digest = ledger.put_blob(canonical_json_bytes(payload))
    receipt_blob = ledger.put_blob(canonical_json_bytes(receipt))
    ledger.append(
        event_type="contract_validated",
        state="VALIDATED",
        subject_digest=contract_digest,
        blob_digests=(contract_digest, receipt_blob),
        payload={
            "approval": {
                "status": "VERIFIED",
                "authority": "fixture-human",
                "receipt_digest": receipt["receipt_digest"],
                "receipt_blob_digest": receipt_blob,
            },
            "contract_digest": contract_digest,
            "plan_digest": "sha256:" + "1" * 64,
        },
    )
    terminal = ledger.append(
        event_type="release_ready",
        state="RELEASE_READY",
        subject_digest=canonical_digest(payload),
        blob_digests=(app_digest, binding_digest, candidate_digest),
        payload={"candidate_digest": candidate_digest},
    )
    return root, run_id, str(terminal["event_digest"])


def test_package_support_build_and_verify_cli(tmp_path: Path) -> None:
    contract = Path("examples/support-package/contract.json")
    receipt = Path("examples/support-package/approval-receipt.json")
    bundle = tmp_path / "bundle"
    evidence_root, run_id, head = _release_evidence(tmp_path, contract)

    assert (
        main(
            [
                "barebones",
                "package",
                "build",
                "--contract",
                str(contract),
                "--approval-receipt",
                str(receipt),
                "--expected-approver",
                "fixture-human",
                "--release-evidence-root",
                str(evidence_root),
                "--release-run-id",
                run_id,
                "--expected-release-head-digest",
                head,
                "--output",
                str(bundle),
            ]
        )
        == 0
    )
    manifest_digest = json.loads((bundle / "manifest.json").read_text())["manifest_digest"]
    assert (
        main(
            [
                "barebones",
                "package",
                "verify",
                "--bundle",
                str(bundle),
                "--expected-manifest-digest",
                manifest_digest,
            ]
        )
        == 0
    )
    assert json.loads((bundle / "manifest.json").read_text())["state"] == "PACKAGE_READY"


def test_package_support_cli_rejects_tampered_bundle(tmp_path: Path) -> None:
    contract = Path("examples/support-package/contract.json")
    receipt = Path("examples/support-package/approval-receipt.json")
    bundle = tmp_path / "bundle"
    evidence_root, run_id, head = _release_evidence(tmp_path, contract)
    assert (
        main(
            [
                "barebones",
                "package",
                "build",
                "--contract",
                str(contract),
                "--approval-receipt",
                str(receipt),
                "--expected-approver",
                "fixture-human",
                "--release-evidence-root",
                str(evidence_root),
                "--release-run-id",
                run_id,
                "--expected-release-head-digest",
                head,
                "--output",
                str(bundle),
            ]
        )
        == 0
    )
    manifest_digest = json.loads((bundle / "manifest.json").read_text())["manifest_digest"]
    (bundle / "app.py").write_text("tampered\n")

    assert (
        main(
            [
                "barebones",
                "package",
                "verify",
                "--bundle",
                str(bundle),
                "--expected-manifest-digest",
                manifest_digest,
            ]
        )
        == 2
    )


def test_package_support_cli_requires_a_verified_release_run(tmp_path: Path) -> None:
    result = main(
        [
            "barebones",
            "package",
            "build",
            "--contract",
            "examples/support-package/contract.json",
            "--approval-receipt",
            "examples/support-package/approval-receipt.json",
            "--expected-approver",
            "fixture-human",
            "--release-evidence-root",
            str(tmp_path / "missing"),
            "--release-run-id",
            "missing-run",
            "--expected-release-head-digest",
            "sha256:" + "0" * 64,
            "--output",
            str(tmp_path / "bundle"),
        ]
    )

    assert result == 2
