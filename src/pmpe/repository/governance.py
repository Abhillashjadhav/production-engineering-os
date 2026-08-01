"""Time-bound, separately reproducible mutable governance observations."""

from __future__ import annotations

import hashlib
import os
import re
import selectors
import signal
import subprocess
import time
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
from pmpe.repository.scanner import (
    Cancellation,
    RepositoryIntelligenceError,
    RepositorySecurityError,
)

GOVERNANCE_COLLECTOR_VERSION = "repository-governance/1.2.0"
_REQUIRED_REMOTE_COVERAGE = frozenset({"remote_branches", "pull_requests", "issues", "governance"})
_SAFE_REF = re.compile(r"^(?:HEAD|[A-Za-z0-9][A-Za-z0-9._/-]{0,255})$")


def _valid_ref(value: str) -> bool:
    return (
        bool(_SAFE_REF.fullmatch(value))
        and not any(marker in value for marker in ("..", "@{", "//", "\\"))
        and not value.endswith(("/", ".", ".lock"))
    )


class Clock(Protocol):
    def now(self) -> str: ...


class IdProvider(Protocol):
    def new_id(self) -> str: ...


class RemoteProvider(Protocol):
    tool_identity: str
    api_version: str

    def collect(
        self,
        repository: str,
        ref: str,
        *,
        timeout_seconds: int,
        max_output_bytes: int,
        max_items: int,
        cancellation: Cancellation | None,
    ) -> dict[str, Any]: ...


class SystemUtcClock:
    def now(self) -> str:
        return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


class UuidObservationIds:
    def new_id(self) -> str:
        return f"OBS-{uuid.uuid4()}"


class GovernanceCommandRunner:
    """Allowlisted local Git observation commands with mutation subcommands refused."""

    identity = "git-governance-readonly/1.2.0"
    _allowed = {"config", "status", "rev-parse", "for-each-ref", "rev-list", "worktree"}
    _filter_probe = (
        "--name-only",
        "--get-regexp",
        r"^filter\..*\.(clean|smudge|process)$",
    )

    def __init__(self, *, max_output_bytes: int = 8_000_000) -> None:
        self.max_output_bytes = max_output_bytes

    def run(
        self,
        args: tuple[str, ...],
        cwd: Path,
        timeout: int,
        *,
        cancellation: Cancellation | None = None,
    ) -> CommandResult:
        if len(args) < 2 or args[0] != "git" or args[1] not in self._allowed:
            raise RepositorySecurityError("command is outside the governance read-only allowlist")
        if args[1] == "config" and args[2:] != self._filter_probe:
            raise RepositorySecurityError("Git configuration reads are outside the safe probe")
        if args[1] == "worktree" and (len(args) < 3 or args[2] != "list"):
            raise RepositorySecurityError("mutating Git worktree command was refused")
        safe_environment = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_CONFIG_COUNT": "6",
            "GIT_CONFIG_KEY_0": "core.fsmonitor",
            "GIT_CONFIG_VALUE_0": "false",
            "GIT_CONFIG_KEY_1": "core.untrackedCache",
            "GIT_CONFIG_VALUE_1": "false",
            "GIT_CONFIG_KEY_2": "core.preloadIndex",
            "GIT_CONFIG_VALUE_2": "false",
            "GIT_CONFIG_KEY_3": "core.attributesFile",
            "GIT_CONFIG_VALUE_3": os.devnull,
            "GIT_CONFIG_KEY_4": "core.excludesFile",
            "GIT_CONFIG_VALUE_4": os.devnull,
            "GIT_CONFIG_KEY_5": "submodule.recurse",
            "GIT_CONFIG_VALUE_5": "false",
            "LC_ALL": "C",
        }
        try:
            process = subprocess.Popen(
                args,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=safe_environment,
                start_new_session=True,
            )
        except OSError:
            raise
        if process.stdout is None:
            process.kill()
            raise RepositoryIntelligenceError("governance command output is unavailable")
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        payload = bytearray()
        deadline = time.monotonic() + timeout
        timed_out = False
        output_exceeded = False
        cancelled = False
        try:
            while True:
                if cancellation is not None and cancellation.cancelled():
                    cancelled = True
                    _signal_process_group(process, signal.SIGTERM)
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    _signal_process_group(process, signal.SIGKILL)
                    break
                events = selector.select(min(remaining, 0.1))
                if not events:
                    continue
                chunk = os.read(process.stdout.fileno(), 65_536)
                if not chunk:
                    break
                payload.extend(chunk)
                if len(payload) > self.max_output_bytes:
                    output_exceeded = True
                    _signal_process_group(process, signal.SIGTERM)
                    break
        finally:
            selector.close()
            process.stdout.close()
        try:
            returncode = process.wait(timeout=max(0.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            _signal_process_group(process, signal.SIGKILL)
            returncode = process.wait()
            timed_out = True
        return CommandResult(
            args=args,
            returncode=126 if cancelled else 125 if output_exceeded else returncode,
            stdout=bytes(payload[: self.max_output_bytes]),
            stderr=b"",
            timed_out=timed_out,
        )


def _signal_process_group(process: subprocess.Popen[bytes], action: signal.Signals) -> None:
    """Stop the isolated Git process group, including any unexpected descendant."""

    try:
        os.killpg(process.pid, action)
    except ProcessLookupError:
        return
    except PermissionError:
        # Content filters are refused and submodule recursion is disabled before
        # mutable observation, so the allowlisted Git parent is the only expected
        # process on hosts that prohibit group signalling.
        process.send_signal(action)
    except OSError as exc:
        raise RepositorySecurityError("bounded Git process group could not be terminated") from exc


def _decode(result: CommandResult) -> str:
    if result.timed_out:
        raise RepositoryIntelligenceError("governance observation command timed out")
    if result.returncode != 0:
        raise RepositoryIntelligenceError("governance observation command failed")
    try:
        return result.stdout.decode("utf-8") if isinstance(result.stdout, bytes) else result.stdout
    except UnicodeDecodeError as exc:
        raise RepositoryIntelligenceError("governance observation output is malformed") from exc


def _parse_utc(value: str, *, field: str) -> datetime:
    if not value.endswith("Z"):
        raise RepositoryIntelligenceError(f"{field} must be an RFC 3339 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise RepositoryIntelligenceError(f"{field} must be an RFC 3339 UTC timestamp") from exc
    if parsed.tzinfo != UTC:
        raise RepositoryIntelligenceError(f"{field} must use UTC")
    return parsed


def _bounded_remote_shape(value: Any, *, max_bytes: int, max_items: int) -> None:
    pending = [value]
    items = 0
    encoded_bytes = 0
    while pending:
        current = pending.pop()
        items += 1
        if items > max_items:
            raise RepositoryIntelligenceError("remote observation item budget was exceeded")
        if isinstance(current, str):
            encoded_bytes += len(current.encode("utf-8", errors="replace"))
        elif isinstance(current, bytes):
            encoded_bytes += len(current)
        elif isinstance(current, dict):
            pending.extend(current.keys())
            pending.extend(current.values())
        elif isinstance(current, (list, tuple)):
            pending.extend(current)
        elif current is not None and not isinstance(current, (bool, int, float)):
            raise RepositoryIntelligenceError("remote observation contains an unsupported value")
        if encoded_bytes > max_bytes:
            raise RepositoryIntelligenceError("remote observation byte budget was exceeded")


def _governance_implementation_digest() -> str:
    package_root = Path(__file__).resolve().parent
    sources = (
        ("repository.governance", package_root / "governance.py"),
        ("repository.models", package_root / "models.py"),
        ("repository.redaction", package_root / "redaction.py"),
        ("contracts.canonical", package_root.parent / "contracts" / "canonical.py"),
    )
    try:
        evidence = [
            {
                "module": name,
                "source_digest": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for name, path in sources
        ]
    except OSError as exc:
        raise RepositoryIntelligenceError(
            "governance implementation bytes are unavailable for provenance binding"
        ) from exc
    return canonical_digest(evidence)


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
        remote_observed_at=cast(str | None, value["remote_observed_at"]),
        remote_query_coverage=tuple(value["remote_query_coverage"]),
        unknowns=tuple(UnknownFact(**item) for item in value["unknowns"]),
        collector_version=str(value["collector_version"]),
        collector_implementation_digest=str(value["collector_implementation_digest"]),
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
        max_commands: int = 2_000,
        max_branches: int = 1_000,
        max_output_bytes: int = 8_000_000,
        max_remote_items: int = 20_000,
        max_remote_age_seconds: int = 300,
        cancellation: Cancellation | None = None,
    ) -> None:
        self.repository = repository
        self.clock = clock
        self.id_provider = id_provider
        self.remote_provider = remote_provider
        self.runner = command_runner or GovernanceCommandRunner(max_output_bytes=max_output_bytes)
        self.redactor = redactor or EvidenceRedactor()
        self.timeout = command_timeout_seconds
        self.max_commands = max_commands
        self.max_branches = max_branches
        self.max_output_bytes = max_output_bytes
        self.max_remote_items = max_remote_items
        self.max_remote_age_seconds = max_remote_age_seconds
        self.cancellation = cancellation
        self._command_provenance: list[CommandProvenance] = []
        self._commands = 0
        self._local_unknowns: list[UnknownFact] = []

    def _execute(self, root: Path, command: tuple[str, ...]) -> CommandResult:
        if self.cancellation is not None and self.cancellation.cancelled():
            raise RepositoryIntelligenceError("governance observation was cancelled")
        if self._commands >= self.max_commands:
            raise RepositoryIntelligenceError("governance command budget was exhausted")
        self._commands += 1
        result = self.runner.run(
            command,
            root,
            self.timeout,
            cancellation=self.cancellation,
        )
        self._command_provenance.append(
            CommandProvenance(
                args=command,
                tool_identity=self.runner.identity,
                exit_status=result.returncode,
                timed_out=result.timed_out,
            )
        )
        return result

    def _run(self, root: Path, *args: str) -> str:
        try:
            command = ("git", *args)
            result = self._execute(root, command)
            return _decode(result)
        except (FileNotFoundError, OSError) as exc:
            raise RepositoryIntelligenceError("local Git observation is unavailable") from exc

    def _branches(self, root: Path, ref: str) -> tuple[BranchObservation, ...]:
        raw = self._run(
            root, "for-each-ref", "--format=%(refname:short) %(objectname)", "refs/heads"
        )
        branches: list[BranchObservation] = []
        lines = raw.splitlines()
        if len(lines) > self.max_branches:
            self._local_unknowns.append(
                UnknownFact(
                    fact="local_branch_inventory",
                    status="BLOCKED",
                    reason="The local branch-count budget was exceeded.",
                )
            )
            lines = lines[: self.max_branches]
        for line in lines:
            try:
                name, sha = line.rsplit(" ", 1)
            except ValueError as exc:
                raise RepositoryIntelligenceError("local branch output is malformed") from exc
            ahead = behind = 0
            status = "OBSERVED"
            comparison = self._execute(
                root,
                ("git", "rev-list", "--left-right", "--count", f"{ref}...{name}"),
            )
            if comparison.returncode == 0 and not comparison.timed_out:
                try:
                    left, right = _decode(comparison).strip().split()
                    behind, ahead = int(left), int(right)
                except (ValueError, RepositoryIntelligenceError):
                    status = "UNKNOWN"
            else:
                status = "UNKNOWN"
            if status == "UNKNOWN":
                self._local_unknowns.append(
                    UnknownFact(
                        fact=f"local_branch_divergence:{name}",
                        status="BLOCKED",
                        reason="The branch comparison could not be evaluated.",
                    )
                )
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
        self._commands = 0
        self._local_unknowns = []
        if not _valid_ref(ref):
            raise RepositorySecurityError("governance observation ref is invalid")
        if any(
            value <= 0
            for value in (
                self.timeout,
                self.max_commands,
                self.max_branches,
                self.max_output_bytes,
                self.max_remote_items,
                self.max_remote_age_seconds,
            )
        ):
            raise RepositoryIntelligenceError("governance observation budgets must be positive")
        root = Path(repository_root).resolve()
        filter_probe = self._execute(
            root,
            ("git", "config", *GovernanceCommandRunner._filter_probe),
        )
        if filter_probe.timed_out:
            raise RepositoryIntelligenceError("Git content-filter safety probe timed out")
        if filter_probe.returncode == 126:
            raise RepositoryIntelligenceError("governance observation was cancelled")
        if filter_probe.returncode == 0:
            raise RepositorySecurityError(
                "repository-defined Git content filters prevent a code-free governance scan"
            )
        if filter_probe.returncode != 1:
            raise RepositoryIntelligenceError("Git content-filter safety could not be proven")
        status_raw = self._run(
            root,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--ignore-submodules=all",
        )
        head_sha = self._run(root, "rev-parse", "HEAD").strip()
        if not re.fullmatch(r"[0-9a-f]{40}", head_sha):
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
        observed_at_value = _parse_utc(observed_at, field="observation time")

        remote_branches: tuple[RemoteBranchObservation, ...] = ()
        pull_requests: tuple[PullRequestObservation, ...] = ()
        issues: tuple[IssueObservation, ...] = ()
        governance: dict[str, Any] = {}
        provenance: tuple[QueryProvenance, ...] = ()
        remote_observed_at: str | None = None
        remote_query_coverage: tuple[str, ...] = ()
        unknowns: tuple[UnknownFact, ...] = (
            *self._local_unknowns,
            UnknownFact(
                fact="remote_governance",
                status="UNSUPPORTED",
                reason="No read-only remote provider was requested.",
            ),
        )
        tool_identity = self.runner.identity
        api_version = GOVERNANCE_COLLECTOR_VERSION
        disposition = "BLOCKED" if self._local_unknowns else "PARTIAL"
        sanitized_remote: dict[str, Any] = {}
        if self.remote_provider is not None:
            tool_identity = self.remote_provider.tool_identity
            api_version = self.remote_provider.api_version
            try:
                raw_remote = self.remote_provider.collect(
                    self.repository,
                    ref,
                    timeout_seconds=self.timeout,
                    max_output_bytes=self.max_output_bytes,
                    max_items=self.max_remote_items,
                    cancellation=self.cancellation,
                )
                _bounded_remote_shape(
                    raw_remote,
                    max_bytes=self.max_output_bytes,
                    max_items=self.max_remote_items,
                )
            except (PermissionError, OSError):
                disposition = "BLOCKED"
                unknowns = (
                    *self._local_unknowns,
                    UnknownFact(
                        fact="remote_governance",
                        status="BLOCKED",
                        reason=(
                            "The bounded read-only remote provider denied access or failed; "
                            "no value was inferred."
                        ),
                    ),
                )
            except Exception as exc:
                disposition = "BLOCKED"
                unknowns = (
                    *self._local_unknowns,
                    UnknownFact(
                        fact="remote_governance",
                        status="BLOCKED",
                        reason=f"The bounded remote provider failed safely: {type(exc).__name__}.",
                    ),
                )
            else:
                try:
                    sanitized_remote = cast(dict[str, Any], self.redactor.sanitize(raw_remote))
                except (RedactionError, Exception) as exc:
                    raise RepositorySecurityError(
                        "remote evidence redaction failed; observation was not created"
                    ) from exc
                try:
                    remote_observed_at = str(sanitized_remote["observed_at"])
                    remote_observed_value = _parse_utc(
                        remote_observed_at, field="remote observation time"
                    )
                    remote_age = (observed_at_value - remote_observed_value).total_seconds()
                    remote_query_coverage = tuple(
                        sorted(str(item) for item in sanitized_remote.get("coverage", []))
                    )
                    coverage_complete = _REQUIRED_REMOTE_COVERAGE.issubset(remote_query_coverage)
                    freshness_proven = -30 <= remote_age <= self.max_remote_age_seconds
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
                    remote_unknowns = tuple(
                        UnknownFact(
                            fact=str(item["fact"]),
                            status=str(item["status"]),
                            reason=str(item["reason"]),
                        )
                        for item in sanitized_remote.get("unknowns", [])
                    )
                    if any(
                        not re.fullmatch(r"[0-9a-f]{40}", item.sha) for item in remote_branches
                    ) or any(
                        not re.fullmatch(r"[0-9a-f]{40}", item.head) for item in pull_requests
                    ):
                        raise ValueError("remote commit identity is malformed")
                    if any(
                        item.status not in {"UNKNOWN", "UNSUPPORTED", "BLOCKED"}
                        for item in remote_unknowns
                    ):
                        raise ValueError("remote unknown status is malformed")
                    if any(
                        (item.page is not None and item.page < 1)
                        or (item.result_count is not None and item.result_count < 0)
                        for item in provenance
                    ):
                        raise ValueError("remote pagination evidence is malformed")
                except (KeyError, TypeError, ValueError, RepositoryIntelligenceError):
                    disposition = "BLOCKED"
                    unknowns = (
                        *self._local_unknowns,
                        UnknownFact(
                            fact="remote_metadata_shape",
                            status="BLOCKED",
                            reason="Remote metadata shape or observation time is invalid.",
                        ),
                    )
                else:
                    unknowns = (*self._local_unknowns, *remote_unknowns)
                    disposition = (
                        "BLOCKED"
                        if any(item.status == "BLOCKED" for item in unknowns)
                        else "PARTIAL"
                        if any(item.status in {"UNKNOWN", "UNSUPPORTED"} for item in unknowns)
                        else "COMPLETE"
                    )
                    pagination_complete = (
                        sanitized_remote.get("complete") is True
                        and bool(provenance)
                        and all(not item.has_next_page for item in provenance)
                    )
                    if not pagination_complete or not coverage_complete or not freshness_proven:
                        disposition = "BLOCKED"
                        unknowns = (
                            *unknowns,
                            UnknownFact(
                                fact="remote_metadata_completeness",
                                status="BLOCKED",
                                reason=(
                                    "Remote query coverage, pagination, or freshness was not "
                                    "proven; the result is not represented as complete."
                                ),
                            ),
                        )

        collector_digest = _governance_implementation_digest()
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
            "remote_observed_at": remote_observed_at,
            "remote_query_coverage": remote_query_coverage,
            "tool_identity": tool_identity,
            "api_query_version": api_version,
            "collector_version": GOVERNANCE_COLLECTOR_VERSION,
            "collector_implementation_digest": collector_digest,
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
            remote_observed_at=remote_observed_at,
            remote_query_coverage=remote_query_coverage,
            unknowns=unknowns,
            collector_version=GOVERNANCE_COLLECTOR_VERSION,
            collector_implementation_digest=collector_digest,
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
            sanitized = cast(dict[str, Any], self.redactor.sanitize(draft.as_dict()))
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
