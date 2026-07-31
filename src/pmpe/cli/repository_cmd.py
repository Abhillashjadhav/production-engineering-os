"""Read-only repository-intelligence CLI seam."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from pmpe.repository import (
    RepositoryIntelligenceError,
    RepositorySecurityError,
    ScanConfig,
    observe_governance,
    scan_repository,
)


class _ArgumentClock:
    def __init__(self, value: str) -> None:
        self.value = value

    def now(self) -> str:
        return self.value


class _ArgumentIds:
    def __init__(self, value: str) -> None:
        self.value = value

    def new_id(self) -> str:
        return self.value


def _outside_repository(output: Path, repository: Path) -> Path:
    resolved = output.expanduser().resolve()
    root = repository.expanduser().resolve()
    if resolved == root or resolved.is_relative_to(root):
        raise RepositorySecurityError(
            "repository-intelligence artifacts must be written outside the scanned repository"
        )
    return resolved


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.write(b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.replace(path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _cmd_scan(args: argparse.Namespace) -> int:
    root = Path(args.repo)
    try:
        snapshot_path = _outside_repository(Path(args.snapshot_out), root)
        governance_path = (
            _outside_repository(Path(args.governance_out), root) if args.governance_out else None
        )
        snapshot = scan_repository(
            root,
            commit=args.commit,
            config=ScanConfig(
                repository=args.repository,
                default_branch=args.default_branch,
            ),
        )
        observation = None
        if governance_path is not None:
            clock = _ArgumentClock(args.observed_at) if args.observed_at else None
            ids = _ArgumentIds(args.observation_id) if args.observation_id else None
            observation = observe_governance(
                root,
                repository=args.repository,
                ref=args.default_branch or args.commit,
                clock=clock,
                id_provider=ids,
            )
        _atomic_write(snapshot_path, snapshot.canonical_bytes())
        if governance_path is not None and observation is not None:
            _atomic_write(governance_path, observation.canonical_bytes())
    except RepositoryIntelligenceError as exc:
        print(f"repository intelligence blocked: {exc}", file=sys.stderr)
        return 1
    summary = {
        "snapshot_digest": snapshot.snapshot_digest,
        "snapshot_disposition": snapshot.disposition,
        "governance_observation_id": (
            observation.observation_id if observation is not None else None
        ),
    }
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0 if snapshot.disposition == "COMPLETE" else 3


def register(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    repository = sub.add_parser(
        "repository", help="collect deterministic read-only repository intelligence"
    )
    commands = repository.add_subparsers(dest="repository_command", required=True)
    scan = commands.add_parser(
        "scan", help="scan an exact Git commit without executing project code"
    )
    scan.add_argument("--repo", required=True)
    scan.add_argument("--repository", required=True)
    scan.add_argument("--commit", default="HEAD")
    scan.add_argument("--default-branch")
    scan.add_argument("--snapshot-out", required=True)
    scan.add_argument("--governance-out")
    scan.add_argument("--observed-at")
    scan.add_argument("--observation-id")
    scan.set_defaults(fn=_cmd_scan)
