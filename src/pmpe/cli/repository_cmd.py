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
    resolve_repository_root,
    scan_repository,
)
from pmpe.repository.governance import GovernanceCommandRunner


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


def _git_output(runner: GovernanceCommandRunner, root: Path, *args: str) -> str:
    result = runner.run(("git", *args), root, 20)
    if result.timed_out or result.returncode != 0:
        raise RepositorySecurityError("repository containment metadata is unavailable")
    try:
        raw = result.stdout.decode("utf-8") if isinstance(result.stdout, bytes) else result.stdout
    except UnicodeDecodeError as exc:
        raise RepositorySecurityError("repository containment metadata is malformed") from exc
    return raw


def _protected_repository_paths(repository: Path) -> tuple[Path, ...]:
    """Resolve every Git/worktree boundary that artifact writes must not touch."""

    runner = GovernanceCommandRunner(max_output_bytes=1_000_000)
    git_dir_value = _git_output(runner, repository, "rev-parse", "--absolute-git-dir").strip()
    common_dir_value = _git_output(
        runner,
        repository,
        "rev-parse",
        "--path-format=absolute",
        "--git-common-dir",
    ).strip()
    git_dir = Path(git_dir_value)
    common_dir = Path(common_dir_value)
    if (
        not git_dir_value
        or not common_dir_value
        or not git_dir.is_absolute()
        or not common_dir.is_absolute()
    ):
        raise RepositorySecurityError("absolute Git metadata containment could not be proven")
    worktree_output = _git_output(runner, repository, "worktree", "list", "--porcelain", "-z")
    worktrees = tuple(
        Path(record.removeprefix("worktree ")).resolve()
        for record in worktree_output.split("\0")
        if record.startswith("worktree ")
    )
    paths = {repository.resolve(), git_dir.resolve(), common_dir.resolve(), *worktrees}
    if not worktrees:
        raise RepositorySecurityError("repository worktree containment could not be proven")
    return tuple(sorted(paths, key=lambda item: str(item)))


def _outside_repository(output: Path, protected_paths: tuple[Path, ...]) -> Path:
    resolved = output.expanduser().resolve()
    if any(resolved == path or resolved.is_relative_to(path) for path in protected_paths):
        raise RepositorySecurityError(
            "repository-intelligence artifacts must be outside all Git and worktree boundaries"
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
    requested = Path(args.repo)
    try:
        root = resolve_repository_root(requested)
        protected_paths = _protected_repository_paths(root)
        snapshot_path = _outside_repository(Path(args.snapshot_out), protected_paths)
        governance_path = (
            _outside_repository(Path(args.governance_out), protected_paths)
            if args.governance_out
            else None
        )
        if governance_path is not None and governance_path == snapshot_path:
            raise RepositorySecurityError(
                "snapshot and governance artifacts require distinct output paths"
            )
        snapshot = scan_repository(
            requested,
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
                requested,
                repository=args.repository,
                ref=args.default_branch or args.commit,
                snapshot=snapshot,
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
    return (
        0
        if snapshot.disposition == "COMPLETE"
        and (observation is None or observation.disposition == "COMPLETE")
        else 3
    )


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
