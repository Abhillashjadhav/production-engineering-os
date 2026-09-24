"""Offline TEST-ONLY runtime and M3 inspection probe; no external authority claim."""

import contextlib
import hashlib
import io
import json
import runpy
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from pmpe.barebones import BudgetCaps, run_to_release_ready
from pmpe.cli import main
from pmpe.contracts.canonical import canonical_digest, canonical_json_bytes
from pmpe.evidence.ledger import EvidenceLedger


def probe():
    helpers = runpy.run_path(
        str(ROOT / "reviews/2026-09-24-independent-gate-review/adversarial_probes.py")
    )
    sandbox = runpy.run_path(str(ROOT / "tests/conftest.py"))["_LocalCandidateTestSandbox"]
    contract = json.loads((ROOT / "examples/barebones/e1-contract.json").read_text())
    contract["contract_id"] = "TEST-ONLY-R3-INSPECTION"
    contract["approved_by"] = "test-only-r3-fixture"
    contract["binary_release_gates"] = {
        "GATE-001": {
            "description": "TEST ONLY health check",
            "acceptance_criterion_refs": ["AC-001"],
        }
    }
    receipt = json.loads((ROOT / "examples/barebones/e1-approval-receipt.json").read_text())
    receipt["approved_by"] = contract["approved_by"]
    receipt["contract_id"] = contract["contract_id"]
    receipt["approved_contract_digest"] = canonical_digest(contract)
    receipt["draft_digest"] = canonical_digest(
        {**contract, "contract_status": "DRAFT", "approved_by": "", "approved_at": ""}
    )
    receipt.pop("receipt_digest")
    receipt["receipt_digest"] = canonical_digest(receipt)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        result = run_to_release_ready(
            contract=contract,
            repository_root=root,
            workspace=root / "candidate",
            run_id="test-only-r3",
            provider=helpers["Provider"]("def health():\n    return {'status':'ok'}\n"),
            candidate_sandbox=sandbox(),
            budget=BudgetCaps(max_attempts=1),
            approval_receipt=receipt,
            approval_authority=contract["approved_by"],
            approval_receipt_bytes=canonical_json_bytes(receipt),
        )
        assert str(result.state) == "RELEASE_READY"
        args = ["barebones", "inspect", result.run_id, "--repository-root", str(root)]
        with contextlib.redirect_stdout(io.StringIO()):
            assert main(args) == 0
        ledger = EvidenceLedger.open_existing(root, result.run_id)
        events = list(ledger.verify())
        genuine_head = events[-1]["event_digest"]
        gate_event = next(
            event for event in events if event["event_type"] == "release_gates_evaluated"
        )
        old_digest = events[-1]["payload"]["release_gate_evidence_digest"]
        replacement = {**gate_event["payload"], "candidate_digest": "sha256:" + "f" * 64}
        content = canonical_json_bytes(replacement)
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        (ledger.blobs_directory / digest.removeprefix("sha256:")).write_bytes(content)
        # M3: swap only the terminal's gate-blob reference, then retain a valid chain.
        events[-1]["payload"]["release_gate_evidence_digest"] = digest
        events[-1]["blob_digests"] = sorted(
            digest if item == old_digest else item for item in events[-1]["blob_digests"]
        )
        previous = "sha256:" + "0" * 64
        for event in events:
            event["previous_digest"] = previous
            event["event_digest"] = canonical_digest(
                {key: value for key, value in event.items() if key != "event_digest"}
            )
            previous = event["event_digest"]
        ledger.events_path.write_bytes(
            b"".join(canonical_json_bytes(event) + b"\n" for event in events)
        )
        assert list(ledger.verify())
        with contextlib.redirect_stdout(io.StringIO()) as output:
            assert main(args) == 3
        assert json.loads(output.getvalue())["cause"] == "EVIDENCE_INVALID"
        with contextlib.redirect_stdout(io.StringIO()) as output:
            assert main([*args, "--expected-head-digest", genuine_head]) == 3
        assert "expected head" in json.loads(output.getvalue())["detail"]
    print("PASS: real TEST-ONLY current run; intact gate evidence inspects successfully.")
    print(
        "PASS: M3 gate-blob substitution with valid chain is rejected without an external anchor."
    )
    print("PASS: separately supplied original head rejects the rewritten chain.")
    print("LIMIT: no live model, OS-isolation, owner-approval or unanchored M4 authenticity claim.")


if __name__ == "__main__":
    probe()
