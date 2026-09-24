"""Retained-evidence consistency tests, not execution or authenticity claims."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from pmpe.barebones import compile_barebones_plan
from pmpe.cli import main
from pmpe.contracts.acceptance import compile_acceptance_plan
from pmpe.contracts.canonical import canonical_digest, canonical_json_bytes
from pmpe.evidence.ledger import EvidenceLedger
from pmpe.support_package import (
    PackageContractError,
    SupportPackageContract,
    _load_release_candidate,
)


def _packet(
    root: Path, mutation: str = "", *, gated: bool = True, form: str = "default"
) -> tuple[str, dict[str, Any]]:
    contract = json.loads(Path("examples/barebones/e1-contract.json").read_text())
    if gated:
        contract["binary_release_gates"] = {
            "GATE-001": {"description": "TEST ONLY", "acceptance_criterion_refs": ["AC-001"]}
        }
    extra_files: dict[str, str] = {}
    trusted: dict[str, str] = {}
    proof_digests: dict[str, str] = {}
    if form == "custom-action":
        contract["acceptance_criteria"]["AC-001"]["when"]["action"] = "custom_health"
    elif form == "measure":
        contract["acceptance_criteria"]["AC-001"] = {
            "requirement_refs": ["FR-001"],
            "measure": "custom_latency",
            "operator": "lte",
            "value": 200,
            "sample": {"minimum": 2},
        }
    elif form in {"human-test", "template-proof"}:
        path = "tests/test_health.py"
        source = "def test_health():\n    assert True\n"
        extra_files[path] = source
        (root / "tests").mkdir()
        (root / path).write_text(source)
        criterion = {"requirement_refs": ["FR-001"]}
        if form == "human-test":
            criterion["human_test"] = {
                "path": path,
                "node_id": "test_health",
                "command": ["pytest", path + "::test_health"],
            }
        else:
            digest = "sha256:" + hashlib.sha256(source.encode()).hexdigest()
            trusted[path] = digest
            proof_digests["health-proof"] = digest
            criterion["satisfied_by_template"] = {
                "template_version": "fixture-1",
                "test_id": "health-proof",
            }
        contract["acceptance_criteria"]["AC-001"] = criterion
    subject = canonical_digest(contract)
    plan = (
        compile_barebones_plan(contract=contract, repository_root=root).as_dict()
        if form == "default"
        else compile_acceptance_plan(
            contract,
            repository_root=root,
            registered_actions=frozenset({"custom_health"}),
            registered_measures=frozenset({"custom_latency"}),
            template_version="fixture-1",
            template_test_digests=proof_digests,
            trusted_test_digests=trusted,
        ).as_dict()
    )
    if mutation == "plan-stripped":
        plan.pop("release_gates")
    if mutation == "plan-criteria-missing":
        plan["criteria"] = []
    if mutation == "plan-criterion-malformed":
        plan["criteria"] = [{"criterion_id": "AC-001"}]
    if mutation == "plan-assertion-changed":
        plan["criteria"][0]["then"][0]["value"] = "broken"
    if mutation in {
        "plan-stripped",
        "plan-criteria-missing",
        "plan-criterion-malformed",
        "plan-assertion-changed",
    }:
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
    manifest = {
        "app.py": app,
        "package-contract-digest.txt": binding,
        **{path: ledger.put_blob(source.encode()) for path, source in extra_files.items()},
    }
    unsafe_paths = {
        "unsafe-parent": "../escaped.py",
        "unsafe-absolute": "/escaped.py",
        "unsafe-alias": "tests//escaped.py",
        "unsafe-nul": "tests/\x00escaped.py",
    }
    if mutation in unsafe_paths:
        manifest[unsafe_paths[mutation]] = app
    candidate = ledger.put_blob(canonical_json_bytes(manifest))
    payload: dict[str, Any] = {"candidate_digest": candidate}
    terminal_blobs = [candidate, *manifest.values()]
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
        if mutation == "verification-attempt-mismatch":
            ledger.append(
                event_type="verification_started",
                state="VERIFYING",
                subject_digest=subject,
                payload={"attempt": 2},
            )
        ledger.append(
            event_type="release_gates_evaluated",
            state="VERIFYING",
            subject_digest=subject,
            blob_digests=(gate_blob, candidate, *manifest.values()),
            payload=evidence,
        )
        if mutation == "blob-only":
            replacement = {**evidence, "candidate_digest": "sha256:" + "f" * 64}
            gate_blob = ledger.put_blob(canonical_json_bytes(replacement))
        terminal_blobs.append(gate_blob)
        if mutation != "missing-pointer":
            payload["release_gate_evidence_digest"] = gate_blob
        if mutation == "later-verification-failure":
            ledger.append(
                event_type="verification_failed",
                state="BUILDING",
                subject_digest=subject,
                payload={
                    "attempt": 1,
                    "findings": [
                        {
                            "code": "ASSERTION_FAILED",
                            "subject_id": "AC-001",
                            "detail": "seeded later failure",
                            "files": [],
                        }
                    ],
                },
            )
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


@pytest.mark.parametrize("form", ["custom-action", "measure", "human-test", "template-proof"])
def test_semantic_validation_preserves_retained_custom_forms_without_original_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], form: str
) -> None:
    _packet(tmp_path, form=form)
    if form in {"human-test", "template-proof"}:
        (tmp_path / "tests/test_health.py").unlink()
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
        "plan-criterion-malformed",
        "plan-assertion-changed",
        "later-verification-failure",
        "verification-attempt-mismatch",
        "unsafe-parent",
        "unsafe-absolute",
        "unsafe-alias",
        "unsafe-nul",
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
