#!/usr/bin/env python3
"""Apply or verify the owner-approved candidate -> active re-freeze transition.

apply:  refuses unless the candidate's RFC 8785 digest equals the digest the owner
        approved; changes exactly four approval-metadata fields; writes the active
        manifest, freeze-bundle.sha256 and a machine-checkable transition record.
verify: recomputes every digest in the record from the files and checks that
        reverting the four fields in the active manifest reproduces the approved
        candidate digest byte-for-byte (artifact records and all other fields equal).
Standard library only; same canonical form as tests/test_task_tracker_freeze.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

CHANGED = ("status", "owner_approval_quote", "recorded_at", "approval_context")


def canonical(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def raw(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text("utf-8"))


def apply(args: argparse.Namespace) -> int:
    packet = args.packet
    candidate = load(args.candidate)
    if canonical(candidate) != args.approved_candidate_digest:
        sys.exit(f"REFUSED: candidate digest {canonical(candidate)} != approved {args.approved_candidate_digest}")
    if candidate.get("status") != "CANDIDATE_REFREEZE_UNAPPROVED":
        sys.exit("REFUSED: input is not an unapproved candidate")
    previous_path = packet / "freeze-manifest.json"
    previous = load(previous_path)
    previous_digest = (packet / "freeze-bundle.sha256").read_text("utf-8").strip()
    if canonical(previous) != previous_digest:
        sys.exit("REFUSED: current active manifest does not match freeze-bundle.sha256")
    active = dict(candidate)
    active.update(
        status="OWNER_CONFIRMED_FROZEN",
        owner_approval_quote=args.quote,
        recorded_at=args.recorded_at,
        approval_context=args.context,
    )
    for key in set(active) | set(candidate):
        if key not in CHANGED and active.get(key) != candidate.get(key):
            sys.exit(f"REFUSED: protected field would change: {key}")
    active_digest = canonical(active)
    record = {
        "kind": "pmos-task-tracker-refreeze-transition",
        "contract_id": "PMOS-TASK-TRACKER-001",
        "approved_candidate_digest": args.approved_candidate_digest,
        "candidate_manifest_path": str(args.candidate.relative_to(args.repo)),
        "candidate_manifest_raw_sha256": raw(args.candidate),
        "active_manifest_digest": active_digest,
        "superseded_active_digest": previous_digest,
        "superseded_manifest_path": "reviews/task-tracker-v1/refreeze-20261009/superseded-freeze-manifest.json",
        "changed_fields": {k: {"candidate": candidate.get(k), "active": active[k]} for k in CHANGED},
        "unchanged_fields": sorted(k for k in active if k not in CHANGED),
        "artifact_count": len(active["artifacts"]),
        "artifacts_digest": canonical(active["artifacts"]),
        "owner_quote_recorded_by": args.recorded_by,
    }
    out = packet / "refreeze-20261009"
    out.mkdir(exist_ok=False)
    (out / "superseded-freeze-manifest.json").write_bytes(previous_path.read_bytes())
    previous_path.write_text(json.dumps(active, indent=2, sort_keys=True) + "\n", "utf-8")
    (packet / "freeze-bundle.sha256").write_text(active_digest + "\n", "utf-8")
    (out / "transition.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", "utf-8")
    print(json.dumps({"active": active_digest, "candidate": args.approved_candidate_digest}))
    return 0


def verify(args: argparse.Namespace) -> int:
    packet = args.packet
    record = load(packet / "refreeze-20261009" / "transition.json")
    active = load(packet / "freeze-manifest.json")
    candidate = load(args.repo / record["candidate_manifest_path"])
    superseded = load(args.repo / record["superseded_manifest_path"])
    failures = []
    def check(label: str, ok: bool) -> None:
        print(("PASS " if ok else "FAIL ") + label)
        if not ok:
            failures.append(label)
    bundle = (packet / "freeze-bundle.sha256").read_text("utf-8").strip()
    check("freeze-bundle.sha256 == canonical(active manifest)", bundle == canonical(active) == record["active_manifest_digest"])
    check("candidate file digest == approved candidate digest", canonical(candidate) == record["approved_candidate_digest"])
    check("candidate raw bytes unchanged", raw(args.repo / record["candidate_manifest_path"]) == record["candidate_manifest_raw_sha256"])
    reverted = dict(active)
    for key, values in record["changed_fields"].items():
        reverted[key] = values["candidate"]
        check(f"active.{key} == recorded new value", active.get(key) == values["active"])
    check("reverting the four fields reproduces the approved candidate digest", canonical(reverted) == record["approved_candidate_digest"])
    check("only the four approval fields differ from the candidate", sorted(k for k in set(active) | set(candidate) if active.get(k) != candidate.get(k)) == sorted(CHANGED))
    check("artifact records identical to candidate", active["artifacts"] == candidate["artifacts"] and canonical(active["artifacts"]) == record["artifacts_digest"])
    check("status OWNER_CONFIRMED_FROZEN", active["status"] == "OWNER_CONFIRMED_FROZEN")
    check("superseded manifest digest recorded", canonical(superseded) == record["superseded_active_digest"])
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    for name in ("apply", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--repo", type=Path, required=True)
        p.add_argument("--packet", type=Path, required=True)
        if name == "apply":
            p.add_argument("--candidate", type=Path, required=True)
            p.add_argument("--approved-candidate-digest", required=True)
            p.add_argument("--quote", required=True)
            p.add_argument("--recorded-at", required=True)
            p.add_argument("--context", required=True)
            p.add_argument("--recorded-by", required=True)
    args = parser.parse_args()
    args.repo, args.packet = args.repo.resolve(), args.packet.resolve()
    if args.mode == "apply":
        args.candidate = args.candidate.resolve()
        return apply(args)
    return verify(args)


if __name__ == "__main__":
    raise SystemExit(main())
