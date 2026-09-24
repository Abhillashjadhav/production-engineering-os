"""Retained-evidence consistency tests, not execution or authenticity claims."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pmpe.barebones import compile_barebones_plan
from pmpe.cli import main
from pmpe.contracts.canonical import canonical_digest, canonical_json_bytes
from pmpe.evidence.ledger import EvidenceLedger
from pmpe.support_package import (
    PackageContractError,
    SupportPackageContract,
    _load_release_candidate,
)


def _packet(root: Path, mutation: str = "", *, gated: bool = True) -> tuple[str, dict[str, Any]]:
    contract = json.loads(Path("examples/barebones/e1-contract.json").read_text())
    if gated:
        contract["binary_release_gates"] = {
            "GATE-001": {"description": "TEST ONLY", "acceptance_criterion_refs": ["AC-001"]}
        }
    subject = canonical_digest(contract)
    plan = compile_barebones_plan(contract=contract, repository_root=root).as_dict()
    if mutation == "plan-stripped":
        plan.pop("release_gates")
    if mutation == "plan-criteria-missing":
        plan["criteria"] = []
    if mutation in {"plan-stripped", "plan-criteria-missing"}:
        plan["plan_digest"] = canonical_digest(
            {key: value for key, value in plan.items() if key != "plan_digest"}
        )
    ledger = EvidenceLedger(root, "inspection")
    contract_blob = ledger.put_blob(canonical_json_bytes(contract))
    plan_blob = ledger.put_blob(canonical_json_bytes(plan))
    receipt = {
        "decision": "APPROVED",
        "approved_by": "fixture-human",
        "approved_contract_digest": subject,
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    receipt_blob = ledger.put_blob(canonical_json_bytes(receipt))
    ledger.append(
        event_type="contract_validated",
        state="VALIDATED",
        subject_digest=subject,
        blob_digests=(contract_blob, plan_blob, receipt_blob),
        payload={
            "contract_digest": contract_blob,
            "plan_digest": plan["plan_digest"],
            "approval": {
                "status": "VERIFIED",
                "authority": "fixture-human",
                "receipt_digest": receipt["receipt_digest"],
                "receipt_blob_digest": receipt_blob,
            },
        },
    )
    app = ledger.put_blob(b"def health():\n    return {'status':'ok'}\n")
    binding = ledger.put_blob((subject + "\n").encode())
    candidate = ledger.put_blob(
        canonical_json_bytes({"app.py": app, "package-contract-digest.txt": binding})
    )
    payload: dict[str, Any] = {"candidate_digest": candidate}
    terminal_blobs = [candidate, app, binding]
    if gated:
        evidence = {
            "attempt": 1,
            "contract_digest": subject,
            "plan_digest": plan["plan_digest"],
            "candidate_digest": candidate,
            "gates": [
                {
                    "gate_id": "GATE-001",
                    "acceptance_criterion_refs": ["AC-001"],
                    "status": "PASS",
                    "criterion_results": [
                        {"criterion_id": "AC-001", "status": "PASS", "findings": []}
                    ],
                }
            ],
        }
        if mutation in {"candidate_digest", "contract_digest", "plan_digest"}:
            evidence[mutation] = "sha256:" + "f" * 64
        if mutation == "gate-omitted":
            evidence["gates"] = []
        if mutation == "failed-criterion":
            evidence["gates"][0]["criterion_results"][0]["status"] = "FAIL"
        gate_blob = ledger.put_blob(canonical_json_bytes(evidence))
        ledger.append(
            event_type="release_gates_evaluated",
            state="VERIFYING",
            subject_digest=subject,
            blob_digests=(gate_blob, candidate, app, binding),
            payload=evidence,
        )
        if mutation == "blob-only":
            replacement = {**evidence, "candidate_digest": "sha256:" + "f" * 64}
            gate_blob = ledger.put_blob(canonical_json_bytes(replacement))
        terminal_blobs.append(gate_blob)
        if mutation != "missing-pointer":
            payload["release_gate_evidence_digest"] = gate_blob
    terminal = ledger.append(
        event_type="release_ready",
        state="RELEASE_READY",
        subject_digest=subject,
        blob_digests=terminal_blobs,
        payload=payload,
    )
    assert list(ledger.verify())
    return str(terminal["event_digest"]), contract


@pytest.mark.parametrize("gated", [False, True])
def test_consistent_release_packets_remain_inspectable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], gated: bool
) -> None:
    _packet(tmp_path, gated=gated)
    assert main(["barebones", "inspect", "inspection", "--repository-root", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["release_eligible"] is True


@pytest.mark.parametrize(
    "mutation",
    [
        "candidate_digest",
        "contract_digest",
        "plan_digest",
        "blob-only",
        "missing-pointer",
        "gate-omitted",
        "failed-criterion",
        "plan-stripped",
        "plan-criteria-missing",
    ],
)
@pytest.mark.parametrize("command", ["status", "inspect"])
def test_self_consistent_chain_does_not_hide_gate_binding_mismatch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], mutation: str, command: str
) -> None:
    _packet(tmp_path, mutation)
    assert main(["barebones", command, "inspection", "--repository-root", str(tmp_path)]) == 3
    assert json.loads(capsys.readouterr().out)["cause"] == "EVIDENCE_INVALID"


def test_support_candidate_rejects_m3_even_with_matching_expected_head(tmp_path: Path) -> None:
    head, contract = _packet(tmp_path, "candidate_digest")
    with pytest.raises(PackageContractError, match="gate"):
        _load_release_candidate(
            tmp_path,
            "inspection",
            SupportPackageContract(contract, canonical_digest(contract)),
            expected_head_digest=head,
        )


def test_inspection_can_check_existing_external_head_anchor(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    head, _ = _packet(tmp_path)
    args = [
        "barebones",
        "inspect",
        "inspection",
        "--repository-root",
        str(tmp_path),
        "--expected-head-digest",
    ]
    assert main([*args, head]) == 0
    capsys.readouterr()
    assert main([*args, "sha256:" + "f" * 64]) == 3
    assert "expected head" in json.loads(capsys.readouterr().out)["detail"]
