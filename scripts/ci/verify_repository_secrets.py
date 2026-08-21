"""Blocking, exact-SHA, no-ignore repository secret gate for CI."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from pmpe.contracts.digest import canonical_digest
from pmpe.quality import security_profiles
from pmpe.quality.security_profiles import SecretAllowlistEntry, scan_repository_secrets


def _file_digest(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allowlist", type=Path)
    args = parser.parse_args()

    allowlist_payload = json.loads(args.allowlist.read_text()) if args.allowlist else []
    if not isinstance(allowlist_payload, list):
        raise ValueError("secret allowlist must be a JSON list")
    allowlist = tuple(SecretAllowlistEntry(**entry) for entry in allowlist_payload)
    findings = scan_repository_secrets(
        args.root,
        candidate_sha=args.candidate_sha,
        allowlist=allowlist,
    )
    ruleset_file = Path(security_profiles.__file__ or "")
    if not ruleset_file.is_file():
        raise ValueError("security profile ruleset file is unavailable")
    payload = {
        "allowlist_digest": canonical_digest(allowlist_payload),
        "candidate_sha": args.candidate_sha,
        "committed_script_digest": _file_digest(Path(__file__)),
        "finding_count": len(findings),
        "findings": [asdict(item) for item in findings],
        "profile": "no-ignore-secret/v1",
        "tool_identity": {
            "name": "pmpe-no-ignore-secret",
            "ruleset_digest": _file_digest(ruleset_file),
            "version": "1.0.0",
        },
    }
    report = {**payload, "report_digest": canonical_digest(payload)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if findings:
        print(f"blocked: {len(findings)} credential-shaped value(s) detected; values redacted")
        return 1
    print(f"pass: exact-SHA repository secret gate {report['report_digest']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
