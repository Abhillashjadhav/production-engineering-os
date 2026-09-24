"""Read-only repository-intelligence CLI seam."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

from pmpe.repository import (
    RecordedObservationIds,
    RecordedUtcClock,
    RepositoryIntelligenceError,
    RepositorySecurityError,
    ScanConfig,
    observe_governance,
    resolve_repository_root,
    scan_repository,
)
from pmpe.repository.governance import GovernanceCommandRunner


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


@dataclass(frozen=True)
class _PreparedOutput:
    path: Path
    parent_descriptor: int
    parent_identity: tuple[int, int]
    reservation: str

    def close(self) -> None:
        try:
            os.unlink(self.reservation, dir_fd=self.parent_descriptor)
            os.fsync(self.parent_descriptor)
        except FileNotFoundError:
            pass
        os.close(self.parent_descriptor)


def _prepare_output(path: Path, protected_paths: tuple[Path, ...]) -> _PreparedOutput:
    """Open and pin a validated output directory before an untrusted scan runs."""

    requested = path.expanduser()
    validated = _outside_repository(requested, protected_paths)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(validated.parent, flags)
        identity = os.fstat(descriptor)
        revalidated = _outside_repository(requested, protected_paths)
        current = os.stat(revalidated.parent, follow_symlinks=False)
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise RepositorySecurityError("artifact output directory could not be pinned") from exc
    except RepositorySecurityError:
        if descriptor is not None:
            os.close(descriptor)
        raise
    assert descriptor is not None
    if revalidated != validated or (current.st_dev, current.st_ino) != (
        identity.st_dev,
        identity.st_ino,
    ):
        os.close(descriptor)
        raise RepositorySecurityError("artifact output containment changed during preparation")
    reservation = f".pmpe-intelligence-reservation.{secrets.token_hex(16)}"
    reservation_descriptor: int | None = None
    try:
        reservation_descriptor = os.open(
            reservation,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=descriptor,
        )
    except OSError as exc:
        os.close(descriptor)
        raise RepositorySecurityError("artifact output reservation could not be created") from exc
    finally:
        if reservation_descriptor is not None:
            os.close(reservation_descriptor)
    return _PreparedOutput(
        path=validated,
        parent_descriptor=descriptor,
        parent_identity=(identity.st_dev, identity.st_ino),
        reservation=reservation,
    )


def _revalidate_output(
    output: _PreparedOutput,
    protected_paths: tuple[Path, ...],
    repository: Path,
) -> None:
    """Reject path replacement while continuing to rely on the pinned descriptor."""

    try:
        current_protected = tuple(
            sorted(
                {*protected_paths, *_protected_repository_paths(repository)},
                key=lambda item: str(item),
            )
        )
        current = _outside_repository(output.path, current_protected)
        parent = os.stat(current.parent, follow_symlinks=False)
        pinned = os.fstat(output.parent_descriptor)
        reservation = os.stat(
            output.reservation,
            dir_fd=output.parent_descriptor,
            follow_symlinks=False,
        )
    except (OSError, RepositorySecurityError) as exc:
        raise RepositorySecurityError("artifact output containment changed during scan") from exc
    if current != output.path or (parent.st_dev, parent.st_ino) != output.parent_identity:
        raise RepositorySecurityError("artifact output containment changed during scan")
    if (pinned.st_dev, pinned.st_ino) != output.parent_identity:
        raise RepositorySecurityError("artifact output descriptor identity changed during scan")
    if not stat.S_ISREG(reservation.st_mode) or reservation.st_nlink != 1:
        raise RepositorySecurityError("artifact output reservation changed during scan")


def _atomic_write(
    output: _PreparedOutput,
    payload: bytes,
    protected_paths: tuple[Path, ...],
    repository: Path,
) -> None:
    _revalidate_output(output, protected_paths, repository)
    temporary = f".{output.path.name}.{secrets.token_hex(16)}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(temporary, flags, 0o600, dir_fd=output.parent_descriptor)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(payload)
            stream.write(b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        _revalidate_output(output, protected_paths, repository)
        os.replace(
            temporary,
            output.path.name,
            src_dir_fd=output.parent_descriptor,
            dst_dir_fd=output.parent_descriptor,
        )
        os.fsync(output.parent_descriptor)
    except OSError as exc:
        raise RepositorySecurityError("artifact write could not be completed safely") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            os.unlink(temporary, dir_fd=output.parent_descriptor)
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise RepositorySecurityError("temporary artifact cleanup could not be proven") from exc


def _cmd_scan(args: argparse.Namespace) -> int:
    requested = Path(args.repo)
    snapshot_output: _PreparedOutput | None = None
    governance_output: _PreparedOutput | None = None
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
        snapshot_output = _prepare_output(snapshot_path, protected_paths)
        if governance_path is not None:
            governance_output = _prepare_output(governance_path, protected_paths)
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
            clock = RecordedUtcClock(args.observed_at) if args.observed_at else None
            try:
                ids = RecordedObservationIds(args.observation_id) if args.observation_id else None
            except ValueError as exc:
                raise RepositoryIntelligenceError(str(exc)) from exc
            observation = observe_governance(
                requested,
                repository=args.repository,
                ref=snapshot.commit_sha,
                snapshot=snapshot,
                clock=clock,
                id_provider=ids,
            )
        _atomic_write(snapshot_output, snapshot.canonical_bytes(), protected_paths, root)
        if governance_output is not None and observation is not None:
            _atomic_write(
                governance_output,
                observation.canonical_bytes(),
                protected_paths,
                root,
            )
    except RepositoryIntelligenceError as exc:
        print(f"repository intelligence blocked: {exc}", file=sys.stderr)
        return 1
    finally:
        if governance_output is not None:
            governance_output.close()
        if snapshot_output is not None:
            snapshot_output.close()
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
