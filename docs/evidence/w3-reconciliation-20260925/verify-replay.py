"""Verify a freshly generated W3 replay directory against the recorded verdicts.

Usage (from a PEOS checkout, source-only interpreter):
    PYTHONPATH=src python -B docs/evidence/w3-reconciliation-20260925/verify-replay.py <replay dir>

Checks, exiting 1 on the first failure:
1. the replay's evidence ledger (<dir>/.pmpe) verifies end to end (hash chain and blobs);
2. its one release_gates_evaluated event is the summary's gate_evidence_event_digest,
   <dir>/gate-evidence.json equals that event's payload, and the summary's
   contract_digest and plan_digest equal that payload's;
3. criterion and gate verdicts derived from that ledger payload equal verdicts.json;
4. <dir>/source-manifest.json hashes to the source_manifest_digest that the ledger's
   gate evidence and <dir>/migration.json both bind;
5. status, approval, state, cause, gates and record counts in <dir>/replay-summary.json
   equal the recorded replay-summary.json (source-bound digests are expected to differ).
"""

import hashlib
import json
import sys
from pathlib import Path

from pmpe.evidence.ledger import EvidenceIntegrityError, EvidenceLedger

HERE = Path(__file__).resolve().parent
STABLE = (
    "status",
    "approval",
    "state",
    "cause",
    "gates",
    "process_records",
    "digest_boundaries",
    "fresh_model_calls",
)


def fail(message):
    print("FAIL: " + message)
    raise SystemExit(1)


def bound_manifest_digests(value):
    """Every source_manifest_digest recorded anywhere in a JSON value."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "source_manifest_digest":
                yield item
            yield from bound_manifest_digests(item)
    elif isinstance(value, list):
        for item in value:
            yield from bound_manifest_digests(item)


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
    # Source-bound digests may differ between runs, but never from their own ledger.
    if any(summary[key] != evidence.get(key) for key in ("contract_digest", "plan_digest")):
        fail("replay-summary.json digests differ from the ledger's gate evidence")
    if json.loads((directory / "gate-evidence.json").read_text()) != evidence:
        fail("gate-evidence.json differs from the ledger's gate-evidence event")
    manifest = (
        "sha256:" + hashlib.sha256((directory / "source-manifest.json").read_bytes()).hexdigest()
    )
    bound = set(bound_manifest_digests(evidence))
    migration = json.loads((directory / "migration.json").read_text())
    if bound != {manifest} or migration.get("source_manifest_digest") != manifest:
        fail("source-manifest.json differs from the manifest the ledger and migration bind")
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
