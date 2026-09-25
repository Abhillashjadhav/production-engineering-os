"""Read retained bytes and Git metadata only; never import or execute reviewed code."""

import argparse
import hashlib
import json
import subprocess
import tarfile
from collections import Counter
from pathlib import Path


def json_file(path):
    return json.loads(path.read_text())


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def file_map(root):
    return {
        path.relative_to(root).as_posix(): sha256(path.read_bytes())
        for path in root.rglob("*")
        if path.is_file()
    }


def tree_check(repo, commit, source):
    tree = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", commit + "^{tree}"], text=True
    ).strip()
    entries = subprocess.check_output(
        ["git", "-C", str(repo), "ls-tree", "-rz", "--full-tree", commit]
    ).split(b"\0")
    expected = {}
    mismatches = []
    for entry in filter(None, entries):
        metadata, filename = entry.split(b"\t", 1)
        mode, kind, digest = metadata.decode().split()
        name = filename.decode()
        path = source / name
        expected[name] = digest
        if kind != "blob" or not path.is_file():
            mismatches.append(name)
            continue
        data = str(path.readlink()).encode() if mode == "120000" else path.read_bytes()
        observed = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if observed != digest:
            mismatches.append(name)
    extras = sorted(set(file_map(source)) - set(expected))
    return {
        "commit": commit,
        "tree": tree,
        "tracked_files": len(expected),
        "mismatches": mismatches,
        "extra_files": extras,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume-root", type=Path, required=True)
    parser.add_argument("--process-repo", type=Path, required=True)
    parser.add_argument("--historical-repo", type=Path, required=True)
    parser.add_argument("--packet-repo", type=Path, required=True)
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    packet = here.parents[1] / "r4-repair-20260924"
    raw = args.resume_root / "retained-replay"
    errors = []

    def require(condition, message):
        if not condition:
            errors.append(message)

    archive_meta = json_file(packet / "resume-archive.json")
    archive = packet / archive_meta["archive"]
    require(archive.stat().st_size == archive_meta["bytes"], "archive byte length mismatch")
    require(sha256(archive.read_bytes()) == archive_meta["sha256"], "archive digest mismatch")
    archive_files = {}
    with tarfile.open(archive, "r:gz") as stream:
        for member in stream.getmembers():
            if member.isfile():
                content = stream.extractfile(member)
                if content is None:
                    raise ValueError("archive member has no readable content")
                name = member.name.removeprefix("retained-replay/")
                archive_files[name] = sha256(content.read())
    raw_files = file_map(raw)
    expected_files = {k: v for k, v in raw_files.items() if not k.startswith("retained-ledger/")}
    require(archive_files == expected_files, "archive differs from complete original replay minus duplicate ledger")
    ledger = file_map(raw / ".pmpe")
    require(len(ledger) == archive_meta["ledger_file_count"], "original ledger count mismatch")
    require(ledger == file_map(raw / "retained-ledger"), "omitted duplicate ledger differs")

    copies = {
        "resume-migration.json": "migration.json",
        "resume-source-manifest.json": "source-manifest.json",
        "resume-contract.draft.json": "contract.draft.json",
        "resume-compiled-plan.proposed.json": "compiled-plan.proposed.json",
        "resume-replay-summary.json": "replay-summary.json",
    }
    for stored, original in copies.items():
        require((packet / stored).read_bytes() == (raw / original).read_bytes(), f"copy mismatch: {stored}")

    validation = json_file(packet / "resume-validation.json")
    trees = {}
    for name, repo, commit in (
        ("process", args.process_repo, validation["sources"]["process"]["local"]),
        ("historical", args.historical_repo, validation["sources"]["historical"]["local"]),
        ("packet", args.packet_repo, "89e23a973a5813d32e8e426a525d6c61e2a9a7fd"),
    ):
        trees[name] = tree_check(repo, commit, args.resume_root / name)
        require(not trees[name]["mismatches"], f"tracked archive bytes mismatch: {name}")
        # The earlier Ruff check left metadata outside the reviewed source tree.
        # Disclose every extra; only assert that reviewed Python/source files are unchanged.
        unexpected_source = [
            path for path in trees[name]["extra_files"]
            if path.startswith("src/") or Path(path).suffix in {".py", ".pyc", ".pyo"}
        ]
        require(not unexpected_source, f"untracked source or bytecode files: {name}")
        if name in validation["sources"]:
            require(trees[name]["tree"] == validation["sources"][name]["tree"], f"tree identity mismatch: {name}")

    manifest = json_file(raw / "source-manifest.json")
    source_paths = json_file(raw / "source-paths.json")
    for key, digest in manifest["artifacts"].items():
        path = args.resume_root / "process/src/pmpe" / key.removeprefix("engine/") if key.startswith("engine/") else Path(source_paths[key])
        require("sha256:" + sha256(path.read_bytes()) == digest, f"bound artifact changed: {key}")

    summary = json_file(raw / "replay-summary.json")
    migration = json_file(raw / "migration.json")
    gates = {row["gate_id"]: row for row in json_file(raw / "gate-evidence.json")["gates"]}
    require({key: row["status"] for key, row in gates.items()} == summary["gates"], "gate summary mismatch")
    criteria = gates["GATE-001"]["criterion_results"]
    require(len(criteria) == 14 and all(row["status"] == "PASS" for row in criteria), "criterion result mismatch")
    observations = gates["GATE-003"]["evidence"]["observations"]
    processes = gates["GATE-003"]["evidence"]["process_records"]
    raw_processes = (raw / "historical-processes.jsonl").read_text().splitlines()
    raw_boundaries = (raw / "historical-digest-checks.jsonl").read_text().splitlines()
    require(len(observations) == summary["digest_boundaries"] == 117, "process-gate observation count mismatch")
    require(len(processes) == len(raw_processes) == summary["process_records"] == 56, "process count mismatch")
    require(summary["state"] == "HALTED", "retained terminal state is not HALTED")
    require(summary["fresh_model_calls"] == migration["fresh_model_calls"] == 0, "fresh-call claim mismatch")
    require(migration["status"] == "DRAFT_NOT_APPROVED" and migration["approval_receipt_created"] is False, "approval claim mismatch")
    handoff = json_file(args.resume_root / "pmos-handoff/summary.json")
    require({name: case["state"] for name, case in handoff["cases"].items()} == json_file(packet / "resume-pmos-handoff.json")["outcomes"], "handoff result mismatch")
    require(handoff["cases"]["unbound-gate"]["execution_calls"] == 0, "unbound handoff executed")
    static = json_file(packet / "resume-source-static-gates.json")
    require(static["status"] == "FAIL" and static["unapproved_architecture_edges"] == [["core", "unresolved_dynamic"]], "architecture failure claim mismatch")
    require(static["sast_findings"] == [], "SAST finding count mismatch")
    require(json_file(packet / "resume-secret-report.json")["finding_count"] == 0, "secret finding count mismatch")
    acceptance = here / "ACCEPTANCE.md"
    require(acceptance.is_file(), "missing independent follow-up acceptance matrix")
    if acceptance.is_file():
        text = acceptance.read_text()
        for phrase in ("NOT APPROVED", "UNVERIFIED", "117", "114", "GATE-003", "GATE-004", "fresh approved delivery"):
            require(phrase in text, f"acceptance matrix omits limit or count: {phrase}")

    result = {
        "status": "PASS" if not errors else "FAIL",
        "scope": "Data-only retained-claim consistency; no reviewed code or candidate executed",
        "errors": errors,
        "archive_sha256": archive_meta["sha256"],
        "archive_regular_files": len(archive_files),
        "original_ledger_files": len(ledger),
        "identical_artifact_copies": sorted(copies),
        "source_archives": trees,
        "bound_artifacts_checked": len(manifest["artifacts"]),
        "criteria": {"PASS": len(criteria)},
        "gates": summary["gates"],
        "terminal_state": summary["state"],
        "process_records": len(processes),
        "process_records_by_phase": dict(Counter(row["phase"] for row in processes)),
        "process_gate_observations": len(observations),
        "historical_digest_rows": len(raw_boundaries),
        "historical_artifacts_bound": migration["historical_artifacts_bound"],
        "fresh_model_calls": summary["fresh_model_calls"],
        "approval": migration["status"],
        "handoff_outcomes": {name: case["state"] for name, case in handoff["cases"].items()},
        "final_adversarial_rechecks": "UNVERIFIED; not executed",
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
