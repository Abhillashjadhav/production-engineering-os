"""Independent, offline TEST-ONLY release-gate probes; no model or OS-isolation claim."""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import runpy
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from pmpe.barebones import BudgetCaps, default_template, run_to_release_ready
from pmpe.evidence.ledger import EvidenceLedger


class Provider:
    def __init__(self, code, extra=None):
        self.code = code
        self.extra = extra or {}
        self.calls = 0

    def invoke(self, *, purpose, request):
        self.calls += 1
        return {
            "request_digest": request["request_digest"],
            "files": {"product.py": self.code, **self.extra},
        }


def main():
    sandbox = runpy.run_path(str(ROOT / "tests/conftest.py"))["_LocalCandidateTestSandbox"]
    # Reuse the established planted-security fixture as data; never import or run it.
    planted_security_source = (ROOT / "src/pmpe/demo/synthetic.py").read_text()
    base = json.loads((ROOT / "examples/barebones/e1-contract.json").read_text())
    base["contract_id"] = "TEST-ONLY-INDEPENDENT-REVIEW"
    base["binary_release_gates"] = [
        {
            "id": "GATE-001",
            "description": "TEST ONLY conjunction",
            "acceptance_criterion_refs": ["AC-001", "AC-002", "AC-003"],
        }
    ]
    for name, mode in [("AC-002", "second"), ("AC-003", "third")]:
        criterion = copy.deepcopy(base["acceptance_criteria"]["AC-001"])
        criterion["when"]["arguments"] = {"mode": mode}
        base["acceptance_criteria"][name] = criterion
    template = default_template()
    template = dataclasses.replace(
        template,
        files={
            **template.files,
            "product.py": "def health(mode='first'):\n    return {'status':'missing'}\n",
        },
    )
    cases = [
        (
            "all-pass",
            "def health(mode='first'):\n    return {'status':'ok'}\n",
            {},
            "RELEASE_READY",
            ["PASS", "PASS", "PASS"],
        ),
        (
            "second-assertion-fails",
            "def health(mode='first'):\n"
            "    return {'status':'broken' if mode=='second' else 'ok'}\n",
            {},
            "HALTED",
            ["PASS", "FAIL", "PASS"],
        ),
        (
            "second-crashes",
            "def health(mode='first'):\n"
            "    if mode=='second': raise ValueError('TEST ONLY forced failure')\n"
            "    return {'status':'ok'}\n",
            {},
            "HALTED",
            ["PASS", "FAIL", "NOT_EVALUATED"],
        ),
        (
            "security-blocked",
            "def health(mode='first'):\n    return {'status':'ok'}\n",
            {"unused.py": planted_security_source},
            "HALTED",
            ["NOT_EVALUATED"] * 3,
        ),
    ]
    for name, code, extra, state, statuses in cases:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = run_to_release_ready(
                contract=copy.deepcopy(base),
                repository_root=root,
                workspace=root / "candidate",
                run_id="review-" + name,
                provider=Provider(code, extra),
                budget=BudgetCaps(max_attempts=1),
                template=template,
                candidate_sandbox=sandbox(),
            )
            ledger = EvidenceLedger.open_existing(root, result.run_id)
            events = list(ledger.verify())
            event = next(e for e in events if e["event_type"] == "release_gates_evaluated")
            gate = event["payload"]["gates"][0]
            observed = [item["status"] for item in gate["criterion_results"]]
            assert str(result.state) == state, (name, result.state)
            assert observed == statuses, (name, observed)
            digest = "sha256:" + hashlib.sha256(
                json.dumps(event["payload"], sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            assert digest in event["blob_digests"]
            assert json.loads(ledger.read_blob(digest)) == event["payload"]
            manifest = json.loads(ledger.read_blob(event["payload"]["candidate_digest"]))
            assert ledger.read_blob(manifest["product.py"]).decode() == code
            for relative, content in extra.items():
                assert ledger.read_blob(manifest[relative]).decode() == content
            if name == "security-blocked":
                security_event = next(
                    item for item in events if item["event_type"] == "security_failed"
                )
                assert any(
                    finding["code"] == "HIGH_DYNAMIC_EXECUTION"
                    and finding["subject_id"] == "unused.py"
                    for finding in security_event["payload"]["findings"]
                )
                assert all(item["event_type"] != "verification_started" for item in events)
            assert all(
                item["event_type"] != "release_ready"
                or item["payload"]["candidate_digest"] == event["payload"]["candidate_digest"]
                for item in events
            )
            print(
                json.dumps(
                    {
                        "case": name,
                        "state": str(result.state),
                        "gate": gate["status"],
                        "criteria": observed,
                        "candidate_and_gate_blobs_verified": True,
                        "security_fixture_source": (
                            "src/pmpe/demo/synthetic.py" if name == "security-blocked" else None
                        ),
                        "security_fixture_sha256": (
                            hashlib.sha256(planted_security_source.encode()).hexdigest()
                            if name == "security-blocked"
                            else None
                        ),
                    },
                    sort_keys=True,
                )
            )
    print("INDEPENDENT ADVERSARIAL PROBES: PASS (4 cases)")


if __name__ == "__main__":
    main()
