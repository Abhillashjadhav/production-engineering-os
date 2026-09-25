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
   gate evidence and <dir>/migration.json both bind; contract.draft.json and
   compiled-plan.proposed.json hash to the bound contract and plan digests; candidate/
   and each mutants/<id>.manifest.json match the bound candidate and mutant digests; and
   every migration.json claim (status, receipt, model calls, historical freeze and
   original contract) except its source-bound digests and publisher-result.json's
   approval match the recorded no-approval run; publisher-input.proposed.json hashes to
   the contract's and the publisher result's source_digest;
5. status, approval, state, cause, gates and record counts in <dir>/replay-summary.json
   equal the recorded replay-summary.json (source-bound digests are expected to differ).
"""

import hashlib
import json
import sys
from pathlib import Path

from pmpe.contracts.canonical import canonical_digest
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


def tree_digest(root):
    """Raw digest of the sorted {relative path: raw file digest} map, as the engine binds."""
    if root.is_symlink() or not root.is_dir():
        fail(f"{root.name}/ is not a directory")
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            fail(f"{root.name}/ holds a symlink or special file")
        if path.is_file():
            files[path.relative_to(root).as_posix()] = (
                "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
            )
    encoded = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


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
    # The exports behind the verdicts must be the contract and plan the ledger binds.
    contract = json.loads((directory / "contract.draft.json").read_text())
    if not isinstance(contract, dict) or canonical_digest(contract) != summary["contract_digest"]:
        fail("contract.draft.json differs from the ledger-bound contract digest")
    plan = json.loads((directory / "compiled-plan.proposed.json").read_text())
    if (
        not isinstance(plan, dict)
        or plan.get("plan_digest") != summary["plan_digest"]
        or canonical_digest({k: v for k, v in plan.items() if k != "plan_digest"})
        != summary["plan_digest"]
        or plan.get("contract_digest") != summary["contract_digest"]
    ):
        fail("compiled-plan.proposed.json differs from the ledger-bound plan digest")
    # The candidate and negative controls behind the verdicts are the ones the ledger binds.
    if tree_digest(directory / "candidate") != evidence.get("candidate_digest"):
        fail("candidate/ differs from the ledger-bound candidate digest")
    mutants = {
        mutant["id"]: mutant["snapshot_digest"]
        for gate in evidence["gates"]
        if (gate.get("binding") or {}).get("kind") == "negative_controls"
        for mutant in gate["binding"]["mutants"]
    }
    exported = {path.name: path for path in (directory / "mutants").iterdir()}
    if set(exported) != {identifier + ".manifest.json" for identifier in mutants} or any(
        "sha256:" + hashlib.sha256(exported[identifier + ".manifest.json"].read_bytes()).hexdigest()
        != digest
        for identifier, digest in mutants.items()
    ):
        fail("mutants/ manifests differ from the ledger-bound mutant snapshot digests")
    # The retained no-approval, no-model-call and historical-input claims behind the
    # verdicts: every field but the two source-bound digests equals the recorded run's.
    recorded_migration = json.loads((HERE / "migration.json").read_text())
    source_bound = {"source_manifest_digest", "proposed_contract_digest"}
    if (
        set(migration) != set(recorded_migration)
        or any(
            migration[key] != recorded_migration[key]
            for key in set(recorded_migration) - source_bound
        )
        or migration.get("fresh_model_calls") != summary["fresh_model_calls"]
        or migration.get("proposed_contract_digest") != summary["contract_digest"]
    ):
        fail(
            "migration.json approval, model-call or historical-input claims differ from the recorded run"
        )
    publisher = json.loads((directory / "publisher-result.json").read_text())
    if (
        publisher.get("approval") != "NOT_APPROVED"
        or publisher.get("draft_digest") != summary["contract_digest"]
    ):
        fail("publisher-result.json approval claim differs from the recorded run")
    # The publisher input behind the draft is the one the ledger-bound contract names.
    publisher_input = json.loads((directory / "publisher-input.proposed.json").read_text())
    if not (
        isinstance(publisher_input, dict)
        and canonical_digest(publisher_input)
        == contract.get("source_digest")
        == publisher.get("source_digest")
    ):
        fail("publisher-input.proposed.json differs from the contract's bound source digest")
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
