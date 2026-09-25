"""Verify a freshly generated W3 replay directory against the recorded verdicts.

Usage (from a PEOS checkout, source-only interpreter):
    PYTHONPATH=src python -B docs/evidence/w3-reconciliation-20260925/verify-replay.py <replay dir>

Checks, exiting 1 on the first failure:
1. the replay's evidence ledger (<dir>/.pmpe) verifies end to end (hash chain and blobs);
2. its one release_gates_evaluated event is the summary's gate_evidence_event_digest, and
   <dir>/gate-evidence.json equals that event's payload;
3. criterion and gate verdicts derived from that ledger payload equal verdicts.json;
4. state, cause, gates and record counts in <dir>/replay-summary.json equal the
   recorded replay-summary.json (source-bound digests are expected to differ).
"""

import json
import sys
from pathlib import Path

from pmpe.evidence.ledger import EvidenceIntegrityError, EvidenceLedger

HERE = Path(__file__).resolve().parent
STABLE = ("state", "cause", "gates", "process_records", "digest_boundaries", "fresh_model_calls")


def fail(message):
    print("FAIL: " + message)
    raise SystemExit(1)


def main(directory):
    summary = json.loads((directory / "replay-summary.json").read_text())
    try:
        ledger = EvidenceLedger.open_existing(directory, summary["run_id"])
        events = [e for e in ledger.verify() if e["event_type"] == "release_gates_evaluated"]
    except EvidenceIntegrityError as exc:
        fail("evidence ledger does not verify: " + str(exc))
    if len(events) != 1 or events[0]["event_digest"] != summary["gate_evidence_event_digest"]:
        fail("ledger gate-evidence event differs from the summary's digest")
    evidence = events[0]["payload"]
    if json.loads((directory / "gate-evidence.json").read_text()) != evidence:
        fail("gate-evidence.json differs from the ledger's gate-evidence event")
    criteria, gates = {}, {}
    for gate in evidence["gates"]:
        reasons = gate.get("evidence", {}).get("reasons", [])
        gates[gate["gate_id"]] = {"reasons": reasons, "status": gate["status"]}
        for result in gate.get("criterion_results", []):
            criteria[result["criterion_id"]] = result["status"]
    recorded = json.loads((HERE / "verdicts.json").read_text())
    derived = {
        "criteria": dict(sorted(criteria.items())),
        "criteria_passed": sum(status == "PASS" for status in criteria.values()),
        "criteria_total": len(criteria),
        "gates": gates,
    }
    if any(derived[key] != recorded[key] for key in derived):
        fail("verdicts derived from gate-evidence.json differ from verdicts.json")
    expected = json.loads((HERE / "replay-summary.json").read_text())
    if any(summary[key] != expected[key] for key in STABLE):
        fail("replay-summary.json differs from the recorded summary on " + ", ".join(STABLE))
    print(
        f"OK: ledger verified; {derived['criteria_passed']}/{derived['criteria_total']} "
        "criteria and gate verdicts match verdicts.json; summary matches"
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        fail("usage: verify-replay.py <replay dir>")
    main(Path(sys.argv[1]).resolve())
