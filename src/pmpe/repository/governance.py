"""Time-bound, separately reproducible mutable governance observations."""

from __future__ import annotations

import os
import subprocess
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast

from pmpe.contracts.canonical import canonical_digest
from pmpe.repository.models import (
    BranchObservation,
    CommandProvenance,
    CommandResult,
    GovernanceObservation,
    IssueObservation,
    LocalState,
    PullRequestObservation,
    QueryProvenance,
    RemoteBranchObservation,
    UnknownFact,
    WorktreeObservation,
)
from pmpe.repository.redaction import EvidenceRedactor, RedactionError
from pmpe.repository.scanner import RepositoryIntelligenceError, RepositorySecurityError


class Clock(Protocol):
    def now(self) -> str: ...


class IdProvider(Protocol):
    def new_id(self) -> str: ...


class RemoteProvider(Protocol):
    tool_identity: str
    api_version: str

    def collect(self, repository: str, ref: str) -> dict[str, Any]: ...


class SystemUtcClock:
    def now(self) -> str:
        return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


class UuidObservationIds:
    def new_id(self) -> str:
        return f"OBS-{uuid.uuid4()}"


class GovernanceCommandRunner:
    """Allowlisted local Git observation commands with mutation subcommands refused."""

    identity = "git-governance-readonly/1.0.0"
    _allowed = {"status", "rev-parse", "for-each-ref", "rev-list", "worktree"}

    def run(self, args: tuple[str, ...], cwd: Path, timeout: int) -> CommandResult:
        if len(args) < 2 or args[0] != "git" or args[1] not in self._allowed:
            raise RepositorySecurityError("command is outside the governance read-only allowlist")
        if args[1] == "worktree" and (len(args) < 3 or args[2] != "list"):
            raise RepositorySecurityError("mutating Git worktree command was refused")
        safe_environment = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
            "LC_ALL": "C",
        }
        try:
            result = subprocess.run(
                args,
                cwd=cwd,
                capture_output=True,
                check=False,
                timeout=timeout,
                env=safe_environment,
            )
        except subprocess.TimeoutExpired:
            return CommandResult(args=args, returncode=124, stdout=b"", stderr=b"", timed_out=True)
        return CommandResult(
            args=args,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )


def _decode(result: CommandResult) -> str:
    if result.timed_out:
        raise RepositoryIntelligenceError("governance observation command timed out")
    if result.returncode != 0:
        raise RepositoryIntelligenceError("governance observation command failed")
    try:
        return result.stdout.decode("utf-8") if isinstance(result.stdout, bytes) else result.stdout
    except UnicodeDecodeError as exc:
        raise RepositoryIntelligenceError("governance observation output is malformed") from exc


def _observation_from_dict(value: dict[str, Any]) -> GovernanceObservation:
    return GovernanceObservation(
        observation_id=str(value["observation_id"]),
        observed_at=str(value["observed_at"]),
        repository=str(value["repository"]),
        ref=str(value["ref"]),
        local_state=LocalState(**value["local_state"]),
        local_branches=tuple(BranchObservation(**item) for item in value["local_branches"]),
        worktrees=tuple(WorktreeObservation(**item) for item in value["worktrees"]),
        command_provenance=tuple(
            CommandProvenance(
                args=tuple(item["args"]),
                tool_identity=str(item["tool_identity"]),
                exit_status=int(item["exit_status"]),
                timed_out=bool(item["timed_out"]),
            )
            for item in value["command_provenance"]
        ),
        remote_branches=tuple(RemoteBranchObservation(**item) for item in value["remote_branches"]),
        pull_requests=tuple(PullRequestObservation(**item) for item in value["pull_requests"]),
        issues=tuple(IssueObservation(**item) for item in value["issues"]),
        governance=cast(dict[str, Any], value["governance"]),
        query_provenance=tuple(QueryProvenance(**item) for item in value["query_provenance"]),
        unknowns=tuple(UnknownFact(**item) for item in value["unknowns"]),
        tool_identity=str(value["tool_identity"]),
        api_query_version=str(value["api_query_version"]),
        observation_input_digest=str(value["observation_input_digest"]),
        observation_output_digest=str(value["observation_output_digest"]),
        disposition=str(value["disposition"]),
        redaction=cast(dict[str, Any], value["redaction"]),
        artifact_kind=str(value["artifact_kind"]),
    )


class GovernanceCollector:
    """Collect mutable local and injected remote observations without mutation."""

    def __init__(
        self,
        *,
        repository: str,
        clock: Clock,
        id_provider: IdProvider,
        remote_provider: RemoteProvider | None = None,
        command_runner: GovernanceCommandRunner | None = None,
        redactor: Any | None = None,
        command_timeout_seconds: int = 20,
    ) -> None:
        self.repository = repository
        self.clock = clock
        self.id_provider = id_provider
        self.remote_provider = remote_provider
        self.runner = command_runner or GovernanceCommandRunner()
        self.redactor = redactor or EvidenceRedactor()
        self.timeout = command_timeout_seconds
        self._command_provenance: list[CommandProvenance] = []

    def _run(self, root: Path, *args: str) -> str:
        try:
            command = ("git", *args)
            result = self.runner.run(command, root, self.timeout)
            self._command_provenance.append(
                CommandProvenance(
                    args=command,
                    tool_identity=self.runner.identity,
                    exit_status=result.returncode,
                    timed_out=result.timed_out,
                )
            )
            return _decode(result)
        except (FileNotFoundError, OSError) as exc:
            raise RepositoryIntelligenceError("local Git observation is unavailable") from exc

    def _branches(self, root: Path, ref: str) -> tuple[BranchObservation, ...]:
        raw = self._run(
            root, "for-each-ref", "--format=%(refname:short) %(objectname)", "refs/heads"
        )
        branches: list[BranchObservation] = []
        for line in raw.splitlines():
            try:
                name, sha = line.rsplit(" ", 1)
            except ValueError as exc:
                raise RepositoryIntelligenceError("local branch output is malformed") from exc
            ahead = behind = 0
            status = "OBSERVED"
            comparison = self.runner.run(
                ("git", "rev-list", "--left-right", "--count", f"{ref}...{name}"),
                root,
                self.timeout,
            )
            self._command_provenance.append(
                CommandProvenance(
                    args=("git", "rev-list", "--left-right", "--count", f"{ref}...{name}"),
                    tool_identity=self.runner.identity,
                    exit_status=comparison.returncode,
                    timed_out=comparison.timed_out,
                )
            )
            if comparison.returncode == 0 and not comparison.timed_out:
                try:
                    left, right = _decode(comparison).strip().split()
                    behind, ahead = int(left), int(right)
                except (ValueError, RepositoryIntelligenceError):
                    status = "UNKNOWN"
            else:
                status = "UNKNOWN"
            branches.append(
                BranchObservation(
                    name=name,
                    sha=sha,
                    ahead=ahead,
                    behind=behind,
                    status=status,
                )
            )
        return tuple(sorted(branches, key=lambda item: item.name))

    def _worktrees(self, root: Path) -> tuple[WorktreeObservation, ...]:
        raw = self._run(root, "worktree", "list", "--porcelain")
        results: list[WorktreeObservation] = []
        current: dict[str, str] = {}
        for line in (*raw.splitlines(), ""):
            if not line:
                if current:
                    results.append(
                        WorktreeObservation(
                            path=current.get("worktree", "UNKNOWN"),
                            head_sha=current.get("HEAD", "UNKNOWN"),
                            branch=current.get("branch", "DETACHED").removeprefix("refs/heads/"),
                        )
                    )
                    current = {}
                continue
            key, _, value = line.partition(" ")
            current[key] = value
        return tuple(sorted(results, key=lambda item: item.path))

    def observe(self, repository_root: Path | str, *, ref: str) -> GovernanceObservation:
        self._command_provenance = []
        root = Path(repository_root).resolve()
        status_raw = self._run(root, "status", "--porcelain=v1", "--untracked-files=all")
        head_sha = self._run(root, "rev-parse", "HEAD").strip()
        if len(head_sha) != 40:
            raise RepositoryIntelligenceError("local Git HEAD is malformed")
        index_dirty = False
        worktree_dirty = False
        untracked = False
        for line in status_raw.splitlines():
            if line.startswith("??"):
                untracked = True
                continue
            if len(line) < 2:
                raise RepositoryIntelligenceError("local Git status output is malformed")
            index_dirty = index_dirty or line[0] not in {" ", "?"}
            worktree_dirty = worktree_dirty or line[1] not in {" ", "?"}
        local_state = LocalState(
            index_dirty=index_dirty,
            worktree_dirty=worktree_dirty,
            untracked=untracked,
            head_sha=head_sha,
        )
        branches = self._branches(root, ref)
        worktrees = self._worktrees(root)
        observed_at = self.clock.now()
        observation_id = self.id_provider.new_id()
        if not observed_at.endswith("Z"):
            raise RepositoryIntelligenceError("observation clock must provide a UTC Z timestamp")

        remote_branches: tuple[RemoteBranchObservation, ...] = ()
        pull_requests: tuple[PullRequestObservation, ...] = ()
        issues: tuple[IssueObservation, ...] = ()
        governance: dict[str, Any] = {}
        provenance: tuple[QueryProvenance, ...] = ()
        unknowns: tuple[UnknownFact, ...] = (
            UnknownFact(
                fact="remote_governance",
                status="UNSUPPORTED",
                reason="No read-only remote provider was requested.",
            ),
        )
        tool_identity = self.runner.identity
        api_version = "local-git/1.0.0"
        disposition = "COMPLETE"
        sanitized_remote: dict[str, Any] = {}
        if self.remote_provider is not None:
            tool_identity = self.remote_provider.tool_identity
            api_version = self.remote_provider.api_version
            try:
                raw_remote = self.remote_provider.collect(self.repository, ref)
                sanitized_remote = cast(dict[str, Any], self.redactor.sanitize(raw_remote))
                remote_branches = tuple(
                    RemoteBranchObservation(name=str(item["name"]), sha=str(item["sha"]))
                    for item in sanitized_remote.get("remote_branches", [])
                )
                pull_requests = tuple(
                    PullRequestObservation(
                        number=int(item["number"]),
                        draft=bool(item["draft"]),
                        head=str(item["head"]),
                    )
                    for item in sanitized_remote.get("pull_requests", [])
                )
                issues = tuple(
                    IssueObservation(number=int(item["number"]), state=str(item["state"]))
                    for item in sanitized_remote.get("issues", [])
                )
                governance = cast(dict[str, Any], sanitized_remote.get("governance", {}))
                provenance = tuple(
                    QueryProvenance(
                        query=str(item["query"]),
                        cursor=cast(str | None, item.get("cursor")),
                        page=cast(int | None, item.get("page")),
                        has_next_page=bool(item.get("has_next_page", True)),
                        result_count=cast(int | None, item.get("result_count")),
                    )
                    for item in sanitized_remote.get("query_provenance", [])
                )
                unknowns = tuple(
                    UnknownFact(
                        fact=str(item["fact"]),
                        status=str(item["status"]),
                        reason=str(item["reason"]),
                    )
                    for item in sanitized_remote.get("unknowns", [])
                )
                if any(item.status == "BLOCKED" for item in unknowns):
                    disposition = "BLOCKED"
                pagination_complete = (
                    sanitized_remote.get("complete") is True
                    and bool(provenance)
                    and all(not item.has_next_page for item in provenance)
                )
                if not pagination_complete:
                    disposition = "BLOCKED"
                    unknowns = (
                        *unknowns,
                        UnknownFact(
                            fact="remote_metadata_completeness",
                            status="BLOCKED",
                            reason=(
                                "Remote query coverage or pagination completion was not proven; "
                                "the returned subset is not represented as complete."
                            ),
                        ),
                    )
            except (PermissionError, OSError):
                disposition = "BLOCKED"
                unknowns = (
                    UnknownFact(
                        fact="remote_governance",
                        status="BLOCKED",
                        reason=(
                            "The read-only remote provider denied access; no value was inferred."
                        ),
                    ),
                )
            except (RedactionError, Exception) as exc:
                raise RepositorySecurityError(
                    "remote evidence redaction failed; observation was not created"
                ) from exc

        inputs = {
            "repository": self.repository,
            "ref": ref,
            "observation_id": observation_id,
            "observed_at": observed_at,
            "local_status": status_raw,
            "local_state": asdict(local_state),
            "local_branches": [asdict(item) for item in branches],
            "worktrees": [asdict(item) for item in worktrees],
            "command_provenance": [asdict(item) for item in self._command_provenance],
            "remote_result": sanitized_remote,
            "tool_identity": tool_identity,
            "api_query_version": api_version,
        }
        try:
            sanitized_inputs = self.redactor.sanitize(inputs)
        except (RedactionError, Exception) as exc:
            raise RepositorySecurityError("observation redaction failed") from exc
        input_digest = canonical_digest(sanitized_inputs)
        draft = GovernanceObservation(
            observation_id=observation_id,
            observed_at=observed_at,
            repository=self.repository,
            ref=ref,
            local_state=local_state,
            local_branches=branches,
            worktrees=worktrees,
            command_provenance=tuple(self._command_provenance),
            remote_branches=remote_branches,
            pull_requests=pull_requests,
            issues=issues,
            governance=governance,
            query_provenance=provenance,
            unknowns=unknowns,
            tool_identity=tool_identity,
            api_query_version=api_version,
            observation_input_digest=input_digest,
            observation_output_digest="",
            disposition=disposition,
            redaction={
                "version": str(getattr(self.redactor, "version", "unknown")),
                "status": "SANITIZED_BEFORE_PERSISTENCE",
                "marker": "[REDACTED]",
                "mutable_truth": "TIME_BOUND_OBSERVATION_ONLY",
            },
        )
        try:
            sanitized = cast(dict[str, Any], self.redactor.sanitize(asdict(draft)))
        except (RedactionError, Exception) as exc:
            raise RepositorySecurityError("observation redaction failed") from exc
        sanitized["observation_output_digest"] = canonical_digest(
            {key: value for key, value in sanitized.items() if key != "observation_output_digest"}
        )
        return _observation_from_dict(sanitized)


def observe_governance(
    repository_root: Path | str,
    *,
    repository: str,
    ref: str,
    clock: Clock | None = None,
    id_provider: IdProvider | None = None,
    remote_provider: RemoteProvider | None = None,
) -> GovernanceObservation:
    return GovernanceCollector(
        repository=repository,
        clock=clock or SystemUtcClock(),
        id_provider=id_provider or UuidObservationIds(),
        remote_provider=remote_provider,
    ).observe(repository_root, ref=ref)
