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
import math
import re
import sys
from pathlib import Path

import pmpe
import pmpe.barebones
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


def exported_jsonl(directory, name):
    """Read an adapter-written JSONL export with its exact one-line serialization."""
    path = directory / name
    if path.is_symlink() or not path.is_file():
        fail(name + " is missing or not a regular file")
    try:
        content = path.read_text()
        if not content or not content.endswith("\n"):
            raise ValueError("missing records or final newline")
        rows = [json.loads(line) for line in content.splitlines()]
        if any(not isinstance(row, dict) for row in rows) or content != "".join(
            json.dumps(row, sort_keys=True, default=str) + "\n" for row in rows
        ):
            raise ValueError("record shape or serialization differs from adapter output")
        return rows
    except (OSError, UnicodeError, ValueError) as exc:
        fail(name + " is malformed: " + str(exc))


def valid_guard_check(item, stage, subject):
    return (
        set(item)
        == {
            "stage",
            "subject",
            "checked",
            "expected_inventory_digest",
            "observed_inventory_digest",
            "mismatches",
        }
        and item["stage"] == stage
        and item["subject"] == subject
        and type(item["checked"]) is int
        and item["checked"] > 0
        and isinstance(item["expected_inventory_digest"], str)
        and re.fullmatch(r"sha256:[0-9a-f]{64}", item["expected_inventory_digest"]) is not None
        and item["expected_inventory_digest"] == item["observed_inventory_digest"]
        and item["mismatches"] == []
    )


def verify_historical_exports(directory, gate_evidence, migration):
    """Bind raw process outputs to ledger records and check historical guard chronology.

    The older guard's inventory paths are not exported in the ledger. Its two
    migration checks can be checked for shape and internal consistency here,
    but their path-dependent inventory digests are not independently attested.
    """
    by_kind = {
        gate["binding"]["kind"]: gate["evidence"]
        for gate in gate_evidence["gates"]
        if isinstance(gate.get("binding"), dict) and isinstance(gate.get("evidence"), dict)
    }
    boundaries = by_kind.get("digest_boundaries", {})
    provenance = by_kind.get("generation_provenance", {})
    protected = boundaries.get("protected_inventory")
    historical_count = migration.get("historical_artifacts_bound")
    if not isinstance(protected, dict) or type(historical_count) is not int:
        fail("historical-digest-checks.jsonl has no bound inventory counts")
    bound = boundaries.get("process_records")
    if not isinstance(bound, list) or bound != provenance.get("process_records"):
        fail("historical-processes.jsonl has no consistent ledger-bound process records")
    processes = exported_jsonl(directory, "historical-processes.jsonl")
    if len(processes) != len(bound):
        fail("historical-processes.jsonl count differs from ledger-bound records")
    for index, (raw, recorded) in enumerate(zip(processes, bound, strict=True)):
        if (
            not isinstance(recorded, dict)
            or set(raw)
            != {
                "argv",
                "check_index",
                "criterion_id",
                "elapsed_ms",
                "environment",
                "exit_code",
                "mode",
                "stderr",
                "stdout",
                "timeout_seconds",
            }
            or type(raw["check_index"]) is not int
            or raw["check_index"] != index
            or index != recorded.get("process_index")
            or raw["criterion_id"] != "fixture"
            or raw["mode"] != "AUTHORIZED_HOST_FALLBACK_NO_ADDITIONAL_ISOLATION"
            or not isinstance(raw["elapsed_ms"], (int, float))
            or not math.isfinite(raw["elapsed_ms"])
            or raw["elapsed_ms"] < 0
            or raw["argv"] != recorded.get("executed_argv")
            or raw["environment"] != recorded.get("environment")
            or raw["exit_code"] != recorded.get("exit_code")
            or raw["timeout_seconds"] != recorded.get("timeout_seconds")
            or not isinstance(raw["stdout"], str)
            or not isinstance(raw["stderr"], str)
            or "sha256:" + hashlib.sha256(raw["stdout"].encode()).hexdigest()
            != recorded.get("stdout_digest")
            or "sha256:" + hashlib.sha256(raw["stderr"].encode()).hexdigest()
            != recorded.get("stderr_digest")
        ):
            fail("historical-processes.jsonl differs from ledger-bound process " + str(index))

    checks = exported_jsonl(directory, "historical-digest-checks.jsonl")
    if len(checks) != 2 * len(bound) + 2:
        fail("historical-digest-checks.jsonl count differs from process chronology")
    for endpoint, stage in ((checks[0], "migration_before"), (checks[-1], "migration_after")):
        if not valid_guard_check(endpoint, stage, "frozen-v1"):
            fail("historical-digest-checks.jsonl migration inventory check is invalid")
        if endpoint["checked"] != historical_count + 1:
            fail("migration.json historical count differs from historical-digest-checks.jsonl")
    if any(
        checks[0][key] != checks[-1][key]
        for key in ("checked", "expected_inventory_digest", "observed_inventory_digest")
    ):
        fail("historical-digest-checks.jsonl migration inventory changed")
    for index in range(len(bound)):
        before, after = checks[2 * index + 1 : 2 * index + 3]
        for item, stage in ((before, "before"), (after, "after")):
            if (
                not valid_guard_check(item, stage, "fixture")
                or item["checked"] != historical_count + len(protected) + 2
            ):
                fail("historical-digest-checks.jsonl check differs at process " + str(index))
        if any(
            before[key] != after[key]
            for key in ("checked", "expected_inventory_digest", "observed_inventory_digest")
        ):
            fail("historical-digest-checks.jsonl inventory changed at process " + str(index))


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
    verify_historical_exports(directory, evidence, migration)
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
    current_runtime_imports = {
        "pmpe": str(Path(pmpe.__file__).resolve()),
        "pmpe.barebones": str(Path(pmpe.barebones.__file__).resolve()),
    }
    recorded_manifest_digest = (
        "sha256:" + hashlib.sha256((HERE / "source-manifest.json").read_bytes()).hexdigest()
    )
    runtime_imports = migration.get("runtime_imports")
    if runtime_imports != current_runtime_imports and not (
        manifest == recorded_manifest_digest
        and runtime_imports == recorded_migration["runtime_imports"]
    ):
        fail("migration.json runtime_imports differ from the replay source checkout")
    source_bound = {"source_manifest_digest", "proposed_contract_digest", "runtime_imports"}
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
            "migration.json approval, model-call or historical-input claims "
            "differ from the recorded run"
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
