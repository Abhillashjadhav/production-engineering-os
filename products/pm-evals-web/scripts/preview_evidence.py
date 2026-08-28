"""Record/verify digest-bound preview evidence for pm-evals Web.

The source digest covers the content of every tracked or unignored source file
under backend/ and frontend/ as it exists on disk — the exact inputs the
preview was built from. Recording binds that digest, the served artifact
fingerprints, and the executed journey results through
``pmpe.fullstack.preview`` (which fails closed on any dishonesty); ``verify``
recomputes the digest and refuses a preview built from anything else.

Usage:
  python preview_evidence.py record --kind local_preview \\
      --build-id <frontend BUILD_ID> --out preview-evidence.json \\
      --journeys a11y=passed keyboard=passed responsive=passed journeys=passed
  python preview_evidence.py verify --path preview-evidence.json
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from pmpe.contracts.digest import canonical_digest
from pmpe.fullstack.preview import record_preview, verify_preview

PRODUCT = Path(__file__).resolve().parents[1]
ROOT = PRODUCT.parents[1]
SOURCE_SCOPES = ("products/pm-evals-web/backend", "products/pm-evals-web/frontend")


def source_digest() -> str:
    tracked = subprocess.run(
        [
            "git",
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            *SOURCE_SCOPES,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    mapping: dict[str, str] = {}
    for rel in tracked.split("\0"):
        if not rel:
            continue
        source = ROOT / rel
        if source.is_file():
            mapping[rel] = hashlib.sha256(source.read_bytes()).hexdigest()
    if not mapping:
        raise SystemExit("no tracked source files found — refusing an empty digest")
    return canonical_digest(mapping)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    rec = sub.add_parser("record")
    rec.add_argument("--kind", required=True)
    rec.add_argument("--build-id", required=True)
    rec.add_argument("--out", required=True, type=Path)
    rec.add_argument("--journeys", nargs="+", required=True, metavar="NAME=RESULT")

    ver = sub.add_parser("verify")
    ver.add_argument("--path", required=True, type=Path)

    args = parser.parse_args()
    digest = source_digest()

    if args.command == "record":
        journeys = dict(item.split("=", 1) for item in args.journeys)
        evidence = record_preview(
            args.out,
            source_digest=digest,
            deployment_kind=args.kind,
            artifacts={
                "frontend-build-id": args.build_id,
                "source-tree": digest,
            },
            journeys=journeys,
            recorded_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        print(f"recorded {args.out} ({evidence.deployment_kind}, {len(journeys)} journeys)")
        return 0

    problems = verify_preview(args.path, expected_source_digest=digest)
    if problems:
        for problem in problems:
            print(f"PREVIEW REFUSED: {problem}", file=sys.stderr)
        return 1
    print(f"preview evidence verified against the current tree ({digest[:19]}…)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
