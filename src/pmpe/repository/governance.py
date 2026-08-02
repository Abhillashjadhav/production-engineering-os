"""Time-bound, separately reproducible mutable governance observations."""

from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import re
import selectors
import signal
import subprocess
import time
import uuid
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType, ModuleType
from typing import Any, Protocol, cast, final

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
    RepositorySnapshot,
    UnknownFact,
    WorktreeObservation,
    _assert_repository_model_bindings_sealed,
)
from pmpe.repository.redaction import (
    EvidenceRedactor,
    RedactionError,
    assert_distinct_identities_preserved,
)
from pmpe.repository.scanner import (
    Cancellation,
    CancellationSignal,
    RepositoryIntelligenceError,
    RepositorySecurityError,
    _cancellation_requested,
    _direct_imported_global_names,
    _implementation_module_evidence,
    _implementation_source_evidence,
    _module_attribute_value_evidence,
    _runtime_dependency_evidence,
    _sealed_fork_event,
    _sealed_fork_pipe,
    _sealed_fork_process,
    _spawn_guarded_git,
    _stop_guarded_process_group,
    _wait_for_exit_without_reaping,
)

GOVERNANCE_COLLECTOR_VERSION = "repository-governance/4.19.0"
GOVERNANCE_IMPLEMENTATION_MODULES = (
    "repository.governance",
    "repository.models",
    "repository.redaction",
    "repository.scanner",
    "contracts.canonical",
)
_GOVERNANCE_IMPLEMENTATION_PATHS = MappingProxyType(
    {
        "repository.governance": Path(__file__).resolve(),
        "repository.models": Path(__file__).resolve().parent / "models.py",
        "repository.redaction": Path(__file__).resolve().parent / "redaction.py",
        "repository.scanner": Path(__file__).resolve().parent / "scanner.py",
        "contracts.canonical": Path(__file__).resolve().parent.parent
        / "contracts"
        / "canonical.py",
    }
)
_GOVERNANCE_IMPORTED_SOURCE_DIGESTS = MappingProxyType(
    {
        name: "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in _GOVERNANCE_IMPLEMENTATION_PATHS.items()
    }
)
_REQUIRED_REMOTE_COVERAGE = frozenset({"remote_branches", "pull_requests", "issues", "governance"})
_GOVERNANCE_SCHEMA_VERSION = "pmpe.repository-governance/v2"
_GOVERNANCE_FIELDS = frozenset(
    {"schema_version", "branch_protection", "review_policy", "security_settings"}
)
_OBJECT_FORMAT_LENGTH = {"sha1": 40, "sha256": 64}
_REMOTE_PAYLOAD_FIELDS = frozenset(
    {
        "complete",
        "repository",
        "ref",
        "default_branch",
        "observed_at",
        "coverage",
        "remote_branches",
        "pull_requests",
        "issues",
        "governance",
        "query_provenance",
        "unknowns",
    }
)
_SAFE_REF = re.compile(r"^(?:HEAD|[A-Za-z0-9][A-Za-z0-9._/-]{0,255})$")
_SAFE_REMOTE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$")
_MAX_GOVERNANCE_BUDGETS = {
    "command_timeout_seconds": 120,
    "max_commands": 20_000,
    "max_branches": 10_000,
    "max_output_bytes": 64_000_000,
    "max_remote_items": 100_000,
    "max_remote_age_seconds": 86_400,
    "stale_pull_request_after_seconds": 31_536_000,
}


def _valid_ref(value: str) -> bool:
    return (
        bool(_SAFE_REF.fullmatch(value))
        and not any(marker in value for marker in ("..", "@{", "//", "\\"))
        and not value.endswith(("/", ".", ".lock"))
    )


def _valid_branch_ref(value: str) -> bool:
    prefix = "refs/heads/"
    if not value.startswith(prefix):
        return False
    name = value.removeprefix(prefix)
    return (
        name != "HEAD"
        and (name == "@" or _valid_ref(name))
        and all(
            part and not part.startswith(".") and not part.endswith((".", ".lock"))
            for part in name.split("/")
        )
    )


def _parse_porcelain_status(value: str) -> tuple[bool, bool, bool]:
    """Parse the bounded NUL porcelain-v1 grammar or fail closed."""

    records = value.split("\0")
    if not records or records[-1] != "":
        raise RepositoryIntelligenceError("local Git status output is malformed")
    records.pop()
    index_dirty = False
    worktree_dirty = False
    untracked = False
    position = 0
    allowed_codes = frozenset(" MTADRCU")
    while position < len(records):
        record = records[position]
        if len(record) < 4 or record[2] != " " or not record[3:]:
            raise RepositoryIntelligenceError("local Git status output is malformed")
        status = record[:2]
        if status == "??":
            untracked = True
        elif status == "!!" or status == "  " or any(code not in allowed_codes for code in status):
            raise RepositoryIntelligenceError("local Git status output is malformed")
        else:
            index_dirty = index_dirty or status[0] != " "
            worktree_dirty = worktree_dirty or status[1] != " "
            if any(code in {"R", "C"} for code in status):
                position += 1
                if position >= len(records) or not records[position]:
                    raise RepositoryIntelligenceError("local Git status output is malformed")
        position += 1
    return index_dirty, worktree_dirty, untracked


def _valid_object_id(value: str, object_format: str) -> bool:
    length = _OBJECT_FORMAT_LENGTH.get(object_format)
    return (
        length is not None
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


class Clock(Protocol):
    def now(self) -> str: ...


class IdProvider(Protocol):
    def new_id(self) -> str: ...


class RemoteProvider(Protocol):
    tool_identity: str
    api_version: str

    @property
    def collection_provenance(self) -> dict[str, Any]: ...

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


@final
class RecordedRemoteProvider:
    """Sealed, data-only remote input that cannot execute caller-supplied collection code."""

    __slots__ = (
        "_collection_provenance",
        "_delay_seconds",
        "_payload",
        "_permission_denied",
        "_sealed",
        "api_version",
    )

    tool_identity = "recorded-remote-payload/2.0.0"
    _collection_provenance: Mapping[str, Any]
    _delay_seconds: float
    _payload: bytes
    _permission_denied: bool
    _sealed: bool
    api_version: str

    def __init__(
        self,
        payload: dict[str, Any],
        *,
        api_version: str,
        delay_seconds: float = 0.0,
        permission_denied: bool = False,
    ) -> None:
        if not api_version.strip():
            raise ValueError("recorded remote API version is required")
        if not math.isfinite(delay_seconds) or not 0 <= delay_seconds <= 300:
            raise ValueError("recorded remote delay must be bounded")
        try:
            canonical_payload = json.dumps(
                payload,
                allow_nan=False,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("recorded remote payload is not canonical JSON") from exc
        provenance = {
            "source_kind": "RECORDED_UNATTESTED",
            "replay_provider": self.tool_identity,
            "api_version": api_version,
            "recorded_payload_digest": "sha256:" + hashlib.sha256(canonical_payload).hexdigest(),
            "attestation": "ABSENT",
        }
        object.__setattr__(self, "_payload", canonical_payload)
        object.__setattr__(self, "api_version", api_version)
        object.__setattr__(self, "_collection_provenance", MappingProxyType(provenance))
        object.__setattr__(self, "_delay_seconds", delay_seconds)
        object.__setattr__(self, "_permission_denied", permission_denied)
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("recorded remote input is immutable")
        object.__setattr__(self, name, value)

    def _assert_integrity(self) -> None:
        expected = {
            "source_kind": "RECORDED_UNATTESTED",
            "replay_provider": self.tool_identity,
            "api_version": self.api_version,
            "recorded_payload_digest": "sha256:" + hashlib.sha256(self._payload).hexdigest(),
            "attestation": "ABSENT",
        }
        if dict(self._collection_provenance) != expected:
            raise RepositorySecurityError("recorded remote provenance integrity check failed")

    @property
    def collection_provenance(self) -> dict[str, Any]:
        self._assert_integrity()
        return dict(self._collection_provenance)

    def collect(
        self,
        repository: str,
        ref: str,
        *,
        timeout_seconds: int,
        max_output_bytes: int,
        max_items: int,
        cancellation: Cancellation | None,
    ) -> dict[str, Any]:
        del repository, ref
        self._assert_integrity()
        if (
            timeout_seconds > _MAX_GOVERNANCE_BUDGETS["command_timeout_seconds"]
            or max_output_bytes > _MAX_GOVERNANCE_BUDGETS["max_output_bytes"]
            or max_items > _MAX_GOVERNANCE_BUDGETS["max_remote_items"]
        ):
            raise RepositoryIntelligenceError("recorded remote replay budget exceeds hard ceiling")
        if _cancellation_requested(cancellation):
            raise RepositoryIntelligenceError("recorded remote replay was cancelled")
        _preflight_json_limits(
            self._payload,
            max_bytes=max_output_bytes,
            max_items=max_items,
        )
        deadline = time.monotonic() + self._delay_seconds
        while time.monotonic() < deadline:
            if _cancellation_requested(cancellation):
                raise RepositoryIntelligenceError("recorded remote replay was cancelled")
            time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
        if self._permission_denied:
            raise PermissionError("recorded remote input reports permission denial")
        if _cancellation_requested(cancellation):
            raise RepositoryIntelligenceError("recorded remote replay was cancelled")
        decoded = json.loads(self._payload)
        if not isinstance(decoded, dict):
            raise RepositoryIntelligenceError("recorded remote payload is malformed")
        _bounded_remote_shape(decoded, max_bytes=max_output_bytes, max_items=max_items)
        return cast(dict[str, Any], decoded)


@final
class SystemUtcClock:
    __slots__ = ()

    def now(self) -> str:
        return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


@final
class RecordedUtcClock:
    """Data-only deterministic clock for reproducible observations."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        _parse_utc(value, field="recorded observation time")
        self._value = value

    def now(self) -> str:
        return self._value


@final
class UuidObservationIds:
    __slots__ = ()

    def new_id(self) -> str:
        return f"OBS-{uuid.uuid4()}"


@final
class RecordedObservationIds:
    """Data-only deterministic observation identifier provider."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        if not re.fullmatch(r"OBS-[A-Za-z0-9._:-]{1,200}", value):
            raise ValueError("recorded observation ID must be a safe opaque identifier")
        self._value = value

    def new_id(self) -> str:
        return self._value


class _SharedCancellation:
    def __init__(self, event: Any) -> None:
        self._event = event

    def cancelled(self) -> bool:
        return bool(self._event.is_set())


def _remote_provider_worker(
    connection: Any,
    provider: RemoteProvider,
    repository: str,
    ref: str,
    timeout_seconds: int,
    max_output_bytes: int,
    max_items: int,
    cancellation_event: Any,
) -> None:
    """Run injected remote I/O in a killable, output-bounded process."""

    isolated = False
    try:
        os.setsid()
        isolated = True
        safe_path = os.environ.get("PATH", "/usr/bin:/bin")
        os.environ.clear()
        os.environ.update(
            {
                "PATH": safe_path,
                "LC_ALL": "C",
                "GIT_TERMINAL_PROMPT": "0",
            }
        )
        connection.send_bytes(b"READY\0")
        result = provider.collect(
            repository,
            ref,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
            max_items=max_items,
            cancellation=_SharedCancellation(cancellation_event),
        )
        if not isinstance(result, dict):
            raise TypeError("remote provider result must be an object")
        _bounded_remote_shape(result, max_bytes=max_output_bytes, max_items=max_items)
        encoded = json.dumps(
            result,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > max_output_bytes:
            raise RepositoryIntelligenceError("remote observation byte budget was exceeded")
        connection.send_bytes(b"RESULT\0" + encoded)
    except PermissionError:
        connection.send_bytes(b"PERMISSION\0")
    except BaseException as exc:
        # Exception text can contain credentials. Only the safe type identity crosses
        # the process boundary and is later sanitized before persistence.
        with suppress(BrokenPipeError, EOFError, OSError):
            connection.send_bytes(b"ERROR\0" + type(exc).__name__.encode("ascii", errors="replace"))
    finally:
        connection.close()
        if isolated:
            while True:
                signal.pause()


class GovernanceCommandRunner:
    """Allowlisted local Git observation commands with mutation subcommands refused."""

    identity = "git-governance-readonly/1.10.0"
    __slots__ = ("_max_output_bytes",)
    _allowed = {
        "config",
        "status",
        "rev-parse",
        "for-each-ref",
        "rev-list",
        "worktree",
        "ls-files",
        "remote",
        "symbolic-ref",
    }
    _filter_probe = (
        "--name-only",
        "--get-regexp",
        r"^filter\..*\.(clean|smudge|process)$",
    )
    _status_probe = (
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        "--ignore-submodules=all",
    )

    def __init__(self, *, max_output_bytes: int = 8_000_000) -> None:
        if not 0 < max_output_bytes <= _MAX_GOVERNANCE_BUDGETS["max_output_bytes"]:
            raise RepositoryIntelligenceError(
                "governance command output budget exceeds hard ceiling"
            )
        self._max_output_bytes = max_output_bytes

    @property
    def max_output_bytes(self) -> int:
        return self._max_output_bytes

    def run(
        self,
        args: tuple[str, ...],
        cwd: Path,
        timeout: int,
        *,
        cancellation: Cancellation | None = None,
    ) -> CommandResult:
        if cancellation is not None and type(cancellation) is not CancellationSignal:
            raise RepositorySecurityError("governance cancellation requires the sealed signal")
        if len(args) < 2 or args[0] != "git" or args[1] not in self._allowed:
            raise RepositorySecurityError("command is outside the governance read-only allowlist")
        if args[1] == "config" and args[2:] != self._filter_probe:
            raise RepositorySecurityError("Git configuration reads are outside the safe probe")
        if args[1] == "ls-files" and args[2:] != ("--stage", "-z"):
            raise RepositorySecurityError("Git index reads are outside the safe probe")
        if args[1] == "status" and args[2:] != self._status_probe:
            raise RepositorySecurityError("Git status reads are outside the safe probe")
        if args[1] == "worktree" and (len(args) < 3 or args[2] != "list"):
            raise RepositorySecurityError("mutating Git worktree command was refused")
        if args[1] == "remote" and args[2:]:
            raise RepositorySecurityError("Git remote reads are outside the safe inventory")
        if args[1] == "symbolic-ref" and args[2:] != ("--quiet", "--short", "HEAD"):
            raise RepositorySecurityError("Git symbolic-ref reads are outside the safe probe")
        safe_environment = {
            "PATH": "/usr/bin:/bin",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
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
        process, guard = _spawn_guarded_git(args, cwd, safe_environment)
        if process.stdout is None:
            _stop_guarded_process_group(process, guard)
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
                if _cancellation_requested(cancellation):
                    cancelled = True
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
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
                    break
        except BaseException:
            _stop_guarded_process_group(process, guard)
            raise
        finally:
            selector.close()
            process.stdout.close()
        _stop_guarded_process_group(process, guard)
        returncode = process.returncode
        assert returncode is not None
        return CommandResult(
            args=args,
            returncode=126 if cancelled else 125 if output_exceeded else returncode,
            stdout=bytes(payload[: self.max_output_bytes]),
            stderr=b"",
            timed_out=timed_out,
        )


def _signal_process_group(process: subprocess.Popen[bytes], action: signal.Signals) -> bool:
    """Stop the isolated Git process group, including any unexpected descendant."""

    try:
        os.killpg(process.pid, action)
        return True
    except ProcessLookupError:
        return True
    except OSError:
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return True
        except OSError:
            pass
        # Content filters are refused and submodule recursion is disabled. Always
        # fall back to the parent and let the caller prove it was reaped.
        try:
            process.send_signal(action)
        except ProcessLookupError:
            return False
        except OSError:
            try:
                process.kill()
            except ProcessLookupError:
                return False
            except OSError as exc:
                raise RepositorySecurityError(
                    "bounded Git process group and parent could not be terminated"
                ) from exc
        return False


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
            encoded_bytes += len(
                json.dumps(current, ensure_ascii=False).encode("utf-8", errors="strict")
            )
        elif isinstance(current, bool):
            encoded_bytes += 4 if current else 5
        elif isinstance(current, int):
            try:
                encoded_bytes += len(str(current))
            except ValueError as exc:
                raise RepositoryIntelligenceError(
                    "remote observation numeric value exceeds the byte budget"
                ) from exc
        elif isinstance(current, float):
            if not math.isfinite(current):
                raise RepositoryIntelligenceError(
                    "remote observation contains a non-finite numeric value"
                )
            encoded_bytes += len(repr(current))
        elif isinstance(current, dict):
            if not all(isinstance(key, str) for key in current):
                raise RepositoryIntelligenceError("remote observation object keys must be strings")
            encoded_bytes += 2 + max(0, len(current) - 1)
            pending.extend(current.keys())
            pending.extend(current.values())
        elif isinstance(current, (list, tuple)):
            encoded_bytes += 2 + max(0, len(current) - 1)
            pending.extend(current)
        elif current is None:
            encoded_bytes += 4
        else:
            raise RepositoryIntelligenceError("remote observation contains an unsupported value")
        if encoded_bytes > max_bytes:
            raise RepositoryIntelligenceError("remote observation byte budget was exceeded")


def _preflight_json_limits(payload: bytes, *, max_bytes: int, max_items: int) -> None:
    """Bound encoded JSON bytes and value/key tokens before object materialization."""

    if max_bytes <= 0 or max_items <= 0:
        raise RepositoryIntelligenceError("remote observation budgets must be positive")
    if len(payload) > max_bytes:
        raise RepositoryIntelligenceError("recorded remote payload exceeds the byte budget")
    index = 0
    items = 0
    length = len(payload)
    whitespace_or_delimiter = b" \t\r\n,:]}"
    while index < length:
        current = payload[index]
        if current in whitespace_or_delimiter:
            index += 1
            continue
        if current in b"[{":
            items += 1
            index += 1
        elif current == ord('"'):
            items += 1
            index += 1
            while index < length:
                current = payload[index]
                index += 1
                if current == ord('"'):
                    break
                if current == ord("\\"):
                    if index >= length:
                        raise RepositoryIntelligenceError("recorded remote payload is malformed")
                    escape = payload[index]
                    index += 1
                    if escape == ord("u"):
                        index += 4
                        if index > length:
                            raise RepositoryIntelligenceError(
                                "recorded remote payload is malformed"
                            )
            else:
                raise RepositoryIntelligenceError("recorded remote payload is malformed")
        elif current in b"-0123456789":
            items += 1
            index += 1
            while index < length and payload[index] in b"0123456789+-.eE":
                index += 1
        elif payload.startswith(b"true", index):
            items += 1
            index += 4
        elif payload.startswith(b"false", index):
            items += 1
            index += 5
        elif payload.startswith(b"null", index):
            items += 1
            index += 4
        else:
            raise RepositoryIntelligenceError("recorded remote payload is malformed")
        if items > max_items:
            raise RepositoryIntelligenceError("remote observation item budget was exceeded")


def _stop_remote_process(process: Any) -> None:
    """Terminate and reap the isolated provider process and its descendants."""

    try:
        os.killpg(process.pid, signal.SIGKILL)
        group_proven = True
    except ProcessLookupError:
        group_proven = _wait_for_exit_without_reaping(process, 0.0)
        if not group_proven:
            with suppress(ProcessLookupError, OSError):
                process.kill()
    except (PermissionError, OSError):
        group_proven = False
        with suppress(ProcessLookupError, OSError):
            process.kill()
    process.join(timeout=1.0)
    if process.is_alive():
        raise RepositorySecurityError("bounded remote provider process could not be reaped")
    if not group_proven:
        raise RepositorySecurityError(
            "bounded remote-provider descendant termination could not be proven"
        )


def _governance_content_is_complete(value: dict[str, Any]) -> bool:
    if (
        value.get("schema_version") != _GOVERNANCE_SCHEMA_VERSION
        or set(value) != _GOVERNANCE_FIELDS
    ):
        return False
    branch_protection = value["branch_protection"]
    review_policy = value["review_policy"]
    security_settings = value["security_settings"]
    if (
        not isinstance(branch_protection, dict)
        or set(branch_protection)
        != {
            "observed",
            "protected",
            "required_checks",
            "required_signed_commits",
            "required_linear_history",
            "push_restrictions",
            "allow_force_pushes",
            "allow_deletions",
        }
        or branch_protection.get("observed") is not True
        or not isinstance(branch_protection.get("protected"), bool)
        or not isinstance(branch_protection.get("required_checks"), list)
        or not all(_is_str(item) for item in branch_protection["required_checks"])
        or len(set(branch_protection["required_checks"]))
        != len(branch_protection["required_checks"])
        or not all(
            isinstance(branch_protection.get(field), bool)
            for field in (
                "required_signed_commits",
                "required_linear_history",
                "push_restrictions",
                "allow_force_pushes",
                "allow_deletions",
            )
        )
        or not isinstance(review_policy, dict)
        or set(review_policy)
        != {
            "required_approvals",
            "dismiss_stale_reviews",
            "require_code_owner_reviews",
            "require_last_push_approval",
        }
        or not _is_int(review_policy.get("required_approvals"))
        or review_policy["required_approvals"] < 0
        or not all(
            isinstance(review_policy.get(field), bool)
            for field in (
                "dismiss_stale_reviews",
                "require_code_owner_reviews",
                "require_last_push_approval",
            )
        )
        or not isinstance(security_settings, dict)
        or set(security_settings) != {"observed", "leak_detection", "dependency_alerts"}
        or security_settings.get("observed") is not True
        or security_settings.get("leak_detection") not in {"ENABLED", "DISABLED"}
        or security_settings.get("dependency_alerts") not in {"ENABLED", "DISABLED"}
    ):
        return False
    pending: list[Any] = [value]
    visited = 0
    while pending:
        current = pending.pop()
        visited += 1
        if visited > 20_000:
            return False
        if current is None:
            return False
        if isinstance(current, str) and current.strip().upper() in {
            "UNKNOWN",
            "UNSUPPORTED",
            "BLOCKED",
            "UNAVAILABLE",
        }:
            return False
        if isinstance(current, dict):
            pending.extend(current.values())
        elif isinstance(current, (list, tuple)):
            pending.extend(current)
    return True


def _pagination_is_complete(
    provenance: tuple[QueryProvenance, ...], expected_counts: dict[str, int]
) -> bool:
    if {item.surface for item in provenance} != set(expected_counts):
        return False
    for surface, expected_count in expected_counts.items():
        pages = sorted(
            (item for item in provenance if item.surface == surface),
            key=lambda item: item.page if item.page is not None else 0,
        )
        if not pages or any(item.page is None or item.result_count is None for item in pages):
            return False
        if [item.page for item in pages] != list(range(1, len(pages) + 1)):
            return False
        if any(item.has_next_page != (index < len(pages) - 1) for index, item in enumerate(pages)):
            return False
        if sum(item.result_count or 0 for item in pages) != expected_count:
            return False
        if any(not item.query.strip() for item in pages):
            return False
    return True


def _is_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_remote_payload_types(value: dict[str, Any]) -> None:
    """Reject provider coercion before mutable evidence becomes authoritative."""

    if (
        set(value) != _REMOTE_PAYLOAD_FIELDS
        or not isinstance(value.get("complete"), bool)
        or not _is_str(value.get("repository"))
        or not _is_str(value.get("ref"))
        or not _is_str(value.get("default_branch"))
        or not _is_str(value.get("observed_at"))
        or not isinstance(value.get("coverage"), list)
        or not all(_is_str(item) for item in value["coverage"])
        or len(set(value["coverage"])) != len(value["coverage"])
        or not isinstance(value.get("governance"), dict)
    ):
        raise ValueError("remote payload envelope is malformed")

    records: tuple[tuple[str, tuple[tuple[str, Any], ...]], ...] = (
        (
            "remote_branches",
            (
                ("name", _is_str),
                ("sha", _is_str),
                ("comparison_ref", _is_str),
                ("ahead", _is_int),
                ("behind", _is_int),
                ("status", lambda item: item in {"OBSERVED", "UNKNOWN", "BLOCKED"}),
            ),
        ),
        (
            "pull_requests",
            (
                ("number", _is_int),
                ("draft", lambda item: isinstance(item, bool)),
                ("head", _is_str),
                ("updated_at", _is_str),
                ("mergeability", _is_str),
            ),
        ),
        (
            "issues",
            (("number", _is_int), ("state", lambda item: item in {"OPEN", "CLOSED"})),
        ),
        (
            "query_provenance",
            (
                ("surface", _is_str),
                ("query", _is_str),
                ("page", _is_int),
                ("has_next_page", lambda item: isinstance(item, bool)),
                ("result_count", _is_int),
            ),
        ),
        (
            "unknowns",
            (("fact", _is_str), ("status", _is_str), ("reason", _is_str)),
        ),
    )
    for key, required in records:
        collection = value.get(key)
        if not isinstance(collection, list):
            raise ValueError(f"remote {key} inventory is malformed")
        allowed_fields = {field for field, _predicate in required}
        if key == "query_provenance":
            allowed_fields.add("cursor")
        for item in collection:
            if (
                not isinstance(item, dict)
                or set(item) != allowed_fields
                or any(
                    field not in item or not predicate(item[field]) for field, predicate in required
                )
            ):
                raise ValueError(f"remote {key} record is malformed")
            if key == "query_provenance" and not (
                item.get("cursor") is None or isinstance(item.get("cursor"), str)
            ):
                raise ValueError("remote query cursor is malformed")
    if any(item["number"] < 1 for key in ("pull_requests", "issues") for item in value[key]):
        raise ValueError("remote record number is malformed")
    if any(
        item["ahead"] < 0 or item["behind"] < 0 or item["comparison_ref"] != value["ref"]
        for item in value["remote_branches"]
    ):
        raise ValueError("remote branch divergence is malformed")
    if not _valid_ref(value["default_branch"]):
        raise ValueError("remote default branch is malformed")


_SEALED_GOVERNANCE_IMPORT_NAMES = tuple(
    sorted(name for name, target in globals().items() if type(target) is ModuleType)
)
_SEALED_GOVERNANCE_IMPORT_PROCESS_IDENTITIES = tuple(
    (name, id(globals()[name])) for name in _SEALED_GOVERNANCE_IMPORT_NAMES
)


def _governance_direct_module_attribute_names() -> tuple[tuple[str, tuple[str, ...]], ...]:
    try:
        tree = ast.parse(_GOVERNANCE_IMPLEMENTATION_PATHS["repository.governance"].read_text())
    except (OSError, SyntaxError, UnicodeError) as exc:
        raise RepositoryIntelligenceError(
            "governance module attributes are unavailable for provenance binding"
        ) from exc
    attributes: dict[str, set[str]] = {name: set() for name in _SEALED_GOVERNANCE_IMPORT_NAMES}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in attributes
        ):
            attributes[node.value.id].add(node.attr)
    return tuple(
        (name, tuple(sorted(names))) for name, names in sorted(attributes.items()) if names
    )


def _governance_module_attribute_identities(
    attribute_names: tuple[tuple[str, tuple[str, ...]], ...],
) -> tuple[tuple[str, str, int], ...]:
    identities: list[tuple[str, str, int]] = []
    for module_name, names in attribute_names:
        module = globals().get(module_name)
        namespace = vars(module) if type(module) is ModuleType else {}
        for name in names:
            target = namespace.get(name)
            identities.append((module_name, name, id(target) if target is not None else -1))
    return tuple(identities)


def _governance_module_attribute_state_digest(
    attribute_names: tuple[tuple[str, tuple[str, ...]], ...],
) -> str:
    evidence: list[dict[str, Any]] = []
    for module_name, names in attribute_names:
        module = globals().get(module_name)
        if type(module) is not ModuleType:
            raise RepositorySecurityError("governance imported-module binding changed")
        namespace = vars(module)
        for name in names:
            if name not in namespace:
                raise RepositorySecurityError("governance imported-module attribute is unavailable")
            evidence.append(
                {
                    "module": module_name,
                    "attribute": name,
                    "state": _module_attribute_value_evidence(module_name, name, namespace[name]),
                }
            )
    return canonical_digest(evidence)


def _governance_external_global_names() -> tuple[str, ...]:
    return _direct_imported_global_names(_GOVERNANCE_IMPLEMENTATION_PATHS["repository.governance"])


def _governance_external_global_state_digest(names: tuple[str, ...]) -> str:
    evidence: list[dict[str, Any]] = []
    for name in names:
        if name not in globals():
            raise RepositorySecurityError("governance imported global binding is unavailable")
        target = globals()[name]
        evidence.append(
            {
                "binding": name,
                "state": (
                    {"guard": "identity"}
                    if type(target) is ModuleType or callable(target)
                    else _module_attribute_value_evidence(
                        "governance-imported-global", name, target
                    )
                ),
            }
        )
    return canonical_digest(evidence)


_SEALED_GOVERNANCE_MODULE_ATTRIBUTE_NAMES = _governance_direct_module_attribute_names()
_SEALED_GOVERNANCE_MODULE_ATTRIBUTE_STATE_DIGEST = _governance_module_attribute_state_digest(
    _SEALED_GOVERNANCE_MODULE_ATTRIBUTE_NAMES
)
_SEALED_GOVERNANCE_MODULE_ATTRIBUTE_PROCESS_IDENTITIES = _governance_module_attribute_identities(
    _SEALED_GOVERNANCE_MODULE_ATTRIBUTE_NAMES
)
_SEALED_GOVERNANCE_EXTERNAL_GLOBAL_NAMES = _governance_external_global_names()
_SEALED_GOVERNANCE_EXTERNAL_GLOBAL_PROCESS_IDENTITIES = tuple(
    (name, id(globals()[name])) for name in _SEALED_GOVERNANCE_EXTERNAL_GLOBAL_NAMES
)
_SEALED_GOVERNANCE_EXTERNAL_GLOBAL_STATE_DIGEST = _governance_external_global_state_digest(
    _SEALED_GOVERNANCE_EXTERNAL_GLOBAL_NAMES
)


def _assert_governance_import_bindings_sealed(*, verify_state: bool = False) -> None:
    current_identities = tuple(
        (
            name,
            id(target) if type(target) is ModuleType else -1,
        )
        for name in _SEALED_GOVERNANCE_IMPORT_NAMES
        for target in (globals().get(name),)
    )
    if current_identities != _SEALED_GOVERNANCE_IMPORT_PROCESS_IDENTITIES:
        raise RepositorySecurityError("governance imported-module bindings changed")
    if (
        _governance_module_attribute_identities(_SEALED_GOVERNANCE_MODULE_ATTRIBUTE_NAMES)
        != _SEALED_GOVERNANCE_MODULE_ATTRIBUTE_PROCESS_IDENTITIES
    ):
        raise RepositorySecurityError("governance imported-module attributes changed")
    if (
        tuple((name, id(globals().get(name))) for name in _SEALED_GOVERNANCE_EXTERNAL_GLOBAL_NAMES)
        != _SEALED_GOVERNANCE_EXTERNAL_GLOBAL_PROCESS_IDENTITIES
    ):
        raise RepositorySecurityError("governance imported global bindings changed")
    if verify_state and (
        _governance_module_attribute_state_digest(_SEALED_GOVERNANCE_MODULE_ATTRIBUTE_NAMES)
        != _SEALED_GOVERNANCE_MODULE_ATTRIBUTE_STATE_DIGEST
    ):
        raise RepositorySecurityError("governance imported-module attribute state changed")
    if verify_state and (
        _governance_external_global_state_digest(_SEALED_GOVERNANCE_EXTERNAL_GLOBAL_NAMES)
        != _SEALED_GOVERNANCE_EXTERNAL_GLOBAL_STATE_DIGEST
    ):
        raise RepositorySecurityError("governance imported global binding state changed")


def _governance_implementation_digest(
    extension_evidence: tuple[dict[str, str], ...] = (),
) -> str:
    _assert_governance_import_bindings_sealed(verify_state=True)
    try:
        _assert_repository_model_bindings_sealed()
    except ValueError as exc:
        raise RepositorySecurityError("repository model digest bindings changed") from exc
    evidence = _implementation_module_evidence(
        _GOVERNANCE_IMPLEMENTATION_PATHS,
        _GOVERNANCE_IMPORTED_SOURCE_DIGESTS,
    )
    evidence.extend(_runtime_dependency_evidence())
    evidence.extend(extension_evidence)
    return canonical_digest(
        sorted(evidence, key=lambda item: (item.get("label", ""), item["module"]))
    )


def _late_cancellation_input_digest(sanitized_inputs: dict[str, Any]) -> str:
    """Bind a cancellation first observed after the initial input digest fence."""

    rebound = dict(sanitized_inputs)
    unknowns = [dict(item) for item in cast(list[dict[str, Any]], rebound["evaluation_unknowns"])]
    if not any(item.get("fact") == "observation_cancellation" for item in unknowns):
        unknowns.append(
            {
                "fact": "observation_cancellation",
                "status": "BLOCKED",
                "reason": "Mutable governance observation was cancelled before finalization.",
            }
        )
    rebound["evaluation_unknowns"] = sorted(
        unknowns,
        key=lambda item: (item["fact"], item["status"], item["reason"]),
    )
    rebound["evaluation_disposition"] = "BLOCKED"
    return canonical_digest(rebound)


def _observation_from_dict(value: dict[str, Any]) -> GovernanceObservation:
    return GovernanceObservation(
        observation_id=str(value["observation_id"]),
        observed_at=str(value["observed_at"]),
        repository=str(value["repository"]),
        ref=str(value["ref"]),
        repository_snapshot_digest=cast(str | None, value["repository_snapshot_digest"]),
        repository_snapshot_commit=cast(str | None, value["repository_snapshot_commit"]),
        local_state=LocalState(**value["local_state"]),
        current_branch=str(value["current_branch"]),
        configured_remotes=tuple(value["configured_remotes"]),
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
        remote_default_branch=cast(str | None, value["remote_default_branch"]),
        pull_requests=tuple(PullRequestObservation(**item) for item in value["pull_requests"]),
        issues=tuple(IssueObservation(**item) for item in value["issues"]),
        governance=cast(dict[str, Any], value["governance"]),
        query_provenance=tuple(QueryProvenance(**item) for item in value["query_provenance"]),
        remote_observed_at=cast(str | None, value["remote_observed_at"]),
        remote_query_coverage=tuple(value["remote_query_coverage"]),
        remote_collection_provenance=cast(dict[str, Any], value["remote_collection_provenance"]),
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


def _observation_identity_groups(
    original: Mapping[str, Any], sanitized: Mapping[str, Any]
) -> dict[str, list[tuple[str, str]]]:
    """Pair mutable-observation identities before and after redaction."""

    groups: dict[str, list[tuple[str, str]]] = {
        "configured remotes": [],
        "branch references": [],
        "worktree paths": [],
        "query cursors": [],
        "unknown facts": [],
    }
    try:
        for raw_remote, safe_remote in zip(
            cast(list[str], original["configured_remotes"]),
            cast(list[str], sanitized["configured_remotes"]),
            strict=True,
        ):
            groups["configured remotes"].append((raw_remote, safe_remote))
        for collection, field, namespace in (
            ("local_branches", "name", "branch references"),
            ("remote_branches", "name", "branch references"),
            ("worktrees", "branch", "branch references"),
            ("worktrees", "path", "worktree paths"),
            ("query_provenance", "cursor", "query cursors"),
            ("unknowns", "fact", "unknown facts"),
        ):
            for raw_item, safe_item in zip(
                cast(list[dict[str, Any]], original[collection]),
                cast(list[dict[str, Any]], sanitized[collection]),
                strict=True,
            ):
                raw_value = raw_item[field]
                safe_value = safe_item[field]
                if raw_value is not None and safe_value is not None:
                    groups[namespace].append((str(raw_value), str(safe_value)))
    except (KeyError, TypeError, ValueError) as exc:
        raise RedactionError("redaction changed observation identity structure") from exc
    return groups


def _remote_identity_groups(
    original: Mapping[str, Any], sanitized: Mapping[str, Any]
) -> dict[str, list[tuple[str, str]]]:
    """Pair remote identities at their first redaction boundary."""

    groups: dict[str, list[tuple[str, str]]] = {
        "remote branch references": [],
        "remote query surfaces": [],
        "remote query expressions": [],
        "remote query cursors": [],
        "remote unknown facts": [],
    }
    try:
        for collection, field, namespace in (
            ("remote_branches", "name", "remote branch references"),
            ("remote_branches", "comparison_ref", "remote branch references"),
            ("query_provenance", "surface", "remote query surfaces"),
            ("query_provenance", "query", "remote query expressions"),
            ("query_provenance", "cursor", "remote query cursors"),
            ("unknowns", "fact", "remote unknown facts"),
        ):
            for raw_item, safe_item in zip(
                cast(list[dict[str, Any]], original[collection]),
                cast(list[dict[str, Any]], sanitized[collection]),
                strict=True,
            ):
                raw_value = raw_item.get(field)
                safe_value = safe_item.get(field)
                if raw_value is not None and safe_value is not None:
                    groups[namespace].append((str(raw_value), str(safe_value)))
    except (KeyError, TypeError, ValueError) as exc:
        raise RedactionError("redaction changed remote identity structure") from exc
    return groups


class GovernanceCollector:
    """Collect mutable local and injected remote observations without mutation."""

    def __init__(
        self,
        *,
        repository: str,
        snapshot: RepositorySnapshot | None = None,
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
        stale_pull_request_after_seconds: int = 2_592_000,
        cancellation: Cancellation | None = None,
    ) -> None:
        _assert_governance_import_bindings_sealed()
        self.repository = repository
        if snapshot is not None:
            if snapshot.repository != repository:
                raise RepositoryIntelligenceError(
                    "governance repository label does not match the bound snapshot"
                )
            if not snapshot.digest_is_valid():
                raise RepositorySecurityError("bound repository snapshot digest is invalid")
        if remote_provider is not None and type(remote_provider) is not RecordedRemoteProvider:
            raise RepositorySecurityError(
                "remote observations require the sealed data-only provider"
            )
        if type(clock) not in {SystemUtcClock, RecordedUtcClock}:
            raise RepositorySecurityError("governance observations require a sealed clock")
        if type(id_provider) not in {UuidObservationIds, RecordedObservationIds}:
            raise RepositorySecurityError(
                "governance observations require a sealed observation ID provider"
            )
        if command_runner is not None and type(command_runner) is not GovernanceCommandRunner:
            raise RepositorySecurityError("governance observations require the sealed Git reader")
        if command_runner is not None and command_runner.max_output_bytes != max_output_bytes:
            raise RepositorySecurityError(
                "governance command runner output budget must match the recorded collector budget"
            )
        if redactor is not None:
            raise RepositorySecurityError(
                "governance observations use only the sealed fixed state-free redaction policy"
            )
        if cancellation is not None and type(cancellation) is not CancellationSignal:
            raise RepositorySecurityError(
                "governance observations require the sealed cancellation signal"
            )
        self._snapshot = snapshot
        self._clock = clock
        self._id_provider = id_provider
        self._remote_provider = remote_provider
        self._runner = command_runner or GovernanceCommandRunner(max_output_bytes=max_output_bytes)
        self._redactor = EvidenceRedactor(environment={})
        self.timeout = command_timeout_seconds
        self.max_commands = max_commands
        self.max_branches = max_branches
        self.max_output_bytes = max_output_bytes
        self.max_remote_items = max_remote_items
        self.max_remote_age_seconds = max_remote_age_seconds
        self.stale_pull_request_after_seconds = stale_pull_request_after_seconds
        self._cancellation = cancellation
        self._sealed_cancellation_lock = (
            cancellation._lock if type(cancellation) is CancellationSignal else None
        )
        self._command_provenance: list[CommandProvenance] = []
        self._commands = 0
        self._local_unknowns: list[UnknownFact] = []
        extension_targets: list[tuple[str, Any]] = [
            ("clock", self.clock),
            ("id_provider", self.id_provider),
            ("command_runner", self.runner),
            ("redactor", self.redactor),
        ]
        if self.remote_provider is not None:
            extension_targets.append(("remote_provider", self.remote_provider))
        self._extension_implementation_evidence = tuple(
            _implementation_source_evidence(label, target) for label, target in extension_targets
        )
        self._sealed_extension_evidence_digest = canonical_digest(
            self._extension_implementation_evidence
        )
        self._sealed_execution_collaborators = (
            self.snapshot,
            self.clock,
            self.id_provider,
            self.remote_provider,
            self.runner,
            self.redactor,
            self.cancellation,
            self._sealed_cancellation_lock,
            self._extension_implementation_evidence,
        )
        self._sealed_execution_configuration = (
            self.repository,
            self.timeout,
            self.max_commands,
            self.max_branches,
            self.max_output_bytes,
            self.max_remote_items,
            self.max_remote_age_seconds,
            self.stale_pull_request_after_seconds,
        )

    @property
    def snapshot(self) -> RepositorySnapshot | None:
        return self._snapshot

    @property
    def clock(self) -> Clock:
        return self._clock

    @property
    def id_provider(self) -> IdProvider:
        return self._id_provider

    @property
    def remote_provider(self) -> RecordedRemoteProvider | None:
        return self._remote_provider

    @property
    def runner(self) -> GovernanceCommandRunner:
        return self._runner

    @property
    def redactor(self) -> EvidenceRedactor:
        return self._redactor

    @property
    def cancellation(self) -> CancellationSignal | None:
        return self._cancellation

    def _assert_execution_collaborators_sealed(self) -> None:
        _assert_governance_import_bindings_sealed()
        current = (
            self.snapshot,
            self.clock,
            self.id_provider,
            self.remote_provider,
            self.runner,
            self.redactor,
            self.cancellation,
            (self.cancellation._lock if type(self.cancellation) is CancellationSignal else None),
            self._extension_implementation_evidence,
        )
        if any(
            observed is not expected
            for observed, expected in zip(
                current, self._sealed_execution_collaborators, strict=True
            )
        ):
            raise RepositorySecurityError(
                "governance execution collaborators changed after provenance binding"
            )
        try:
            extension_evidence_digest = canonical_digest(self._extension_implementation_evidence)
        except Exception as exc:
            raise RepositorySecurityError(
                "governance implementation provenance evidence is malformed"
            ) from exc
        if (
            self._sealed_execution_configuration
            != (
                self.repository,
                self.timeout,
                self.max_commands,
                self.max_branches,
                self.max_output_bytes,
                self.max_remote_items,
                self.max_remote_age_seconds,
                self.stale_pull_request_after_seconds,
            )
            or extension_evidence_digest != self._sealed_extension_evidence_digest
            or self.redactor._environment_secrets != ()
            or type(self.clock) not in {SystemUtcClock, RecordedUtcClock}
            or type(self.id_provider) not in {UuidObservationIds, RecordedObservationIds}
            or (
                self.remote_provider is not None
                and type(self.remote_provider) is not RecordedRemoteProvider
            )
            or type(self.runner) is not GovernanceCommandRunner
            or type(self.redactor) is not EvidenceRedactor
            or (self.cancellation is not None and type(self.cancellation) is not CancellationSignal)
        ):
            raise RepositorySecurityError("governance execution collaborators are no longer sealed")

    def _assert_bound_snapshot_valid(self) -> None:
        if self.snapshot is not None and not self.snapshot.digest_is_valid():
            raise RepositorySecurityError("bound repository snapshot digest is invalid")

    def _is_cancelled(self) -> bool:
        self._assert_execution_collaborators_sealed()
        if self.cancellation is None:
            return False
        try:
            return self.cancellation.cancelled()
        except Exception:
            return True

    def _claim_completion(self) -> bool:
        self._assert_execution_collaborators_sealed()
        if self.cancellation is None:
            return True
        try:
            return self.cancellation.claim_completion()
        except Exception:
            return False

    def _execute(self, root: Path, command: tuple[str, ...]) -> CommandResult:
        self._assert_execution_collaborators_sealed()
        runner = self.runner
        cancellation = self.cancellation
        if self._is_cancelled():
            raise RepositoryIntelligenceError("governance observation was cancelled")
        if runner.max_output_bytes != self.max_output_bytes:
            raise RepositorySecurityError(
                "governance command runner output budget changed after collector construction"
            )
        if self._commands >= self.max_commands:
            raise RepositoryIntelligenceError("governance command budget was exhausted")
        self._commands += 1
        result = runner.run(
            command,
            root,
            self.timeout,
            cancellation=cancellation,
        )
        self._command_provenance.append(
            CommandProvenance(
                args=command,
                tool_identity=runner.identity,
                exit_status=result.returncode,
                timed_out=result.timed_out,
            )
        )
        self._assert_execution_collaborators_sealed()
        return result

    def _run(self, root: Path, *args: str) -> str:
        try:
            command = ("git", *args)
            result = self._execute(root, command)
            return _decode(result)
        except (FileNotFoundError, OSError) as exc:
            raise RepositoryIntelligenceError("local Git observation is unavailable") from exc

    def _collect_remote_bounded(self, ref: str) -> dict[str, Any]:
        self._assert_execution_collaborators_sealed()
        remote_provider = self.remote_provider
        cancellation = self.cancellation
        if remote_provider is None:
            raise RepositoryIntelligenceError("no remote provider was configured")
        if not hasattr(os, "fork") or not hasattr(os, "setsid"):
            raise RepositoryIntelligenceError(
                "bounded remote provider execution is unsupported on this platform"
            )
        receiver, sender = _sealed_fork_pipe(duplex=False)
        cancellation_event = _sealed_fork_event()
        process = _sealed_fork_process(
            target=_remote_provider_worker,
            args=(
                sender,
                remote_provider,
                self.repository,
                ref,
                self.timeout,
                self.max_output_bytes,
                self.max_remote_items,
                cancellation_event,
            ),
            daemon=True,
            name="pmpe-readonly-remote-provider",
        )
        try:
            process.start()
        except (OSError, RuntimeError) as exc:
            receiver.close()
            sender.close()
            raise RepositoryIntelligenceError(
                "bounded remote provider process could not start"
            ) from exc
        sender.close()
        deadline = time.monotonic() + self.timeout
        ready = False
        try:
            while True:
                self._assert_execution_collaborators_sealed()
                if _cancellation_requested(cancellation):
                    cancellation_event.set()
                    raise RepositoryIntelligenceError(
                        "bounded remote provider observation was cancelled"
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RepositoryIntelligenceError("bounded remote provider timed out")
                if receiver.poll(min(remaining, 0.05)):
                    try:
                        frame = receiver.recv_bytes(maxlength=self.max_output_bytes + 256)
                    except (EOFError, OSError) as exc:
                        raise RepositoryIntelligenceError(
                            "bounded remote provider output was absent or exceeded its byte budget"
                        ) from exc
                    raw_status, separator, payload = frame.partition(b"\0")
                    if not separator:
                        raise RepositoryIntelligenceError(
                            "bounded remote provider protocol was malformed"
                        )
                    try:
                        status = raw_status.decode("ascii")
                    except UnicodeDecodeError as exc:
                        raise RepositoryIntelligenceError(
                            "bounded remote provider protocol was malformed"
                        ) from exc
                    if status == "READY":
                        if payload:
                            raise RepositoryIntelligenceError(
                                "bounded remote provider protocol was malformed"
                            )
                        ready = True
                        continue
                    if not ready:
                        raise RepositoryIntelligenceError(
                            "bounded remote provider isolation was not established"
                        )
                    if status == "RESULT":
                        if len(payload) > self.max_output_bytes:
                            raise RepositoryIntelligenceError(
                                "bounded remote provider result exceeded its byte budget"
                            )
                        try:
                            decoded = json.loads(payload)
                        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                            raise RepositoryIntelligenceError(
                                "bounded remote provider result was malformed"
                            ) from exc
                        if not isinstance(decoded, dict):
                            raise RepositoryIntelligenceError(
                                "bounded remote provider result was malformed"
                            )
                        _bounded_remote_shape(
                            decoded,
                            max_bytes=self.max_output_bytes,
                            max_items=self.max_remote_items,
                        )
                        self._assert_execution_collaborators_sealed()
                        return cast(dict[str, Any], decoded)
                    if status == "PERMISSION":
                        raise PermissionError("bounded remote provider denied access")
                    safe_type = (
                        payload.decode("ascii", errors="replace")
                        if status == "ERROR"
                        else "UnknownError"
                    )
                    raise RepositoryIntelligenceError(
                        f"bounded remote provider failed safely: {safe_type}"
                    )
        finally:
            receiver.close()
            _stop_remote_process(process)

    def _current_branch(self, root: Path) -> str:
        result = self._execute(
            root,
            ("git", "symbolic-ref", "--quiet", "--short", "HEAD"),
        )
        if result.returncode == 1 and not result.timed_out:
            return "DETACHED"
        if result.returncode != 0 or result.timed_out:
            self._local_unknowns.append(
                UnknownFact(
                    fact="current_branch",
                    status="BLOCKED",
                    reason="The current branch could not be observed safely.",
                )
            )
            return "UNKNOWN"
        value = _decode(result).strip()
        if not _valid_ref(value):
            self._local_unknowns.append(
                UnknownFact(
                    fact="current_branch",
                    status="BLOCKED",
                    reason="The current branch identity is malformed.",
                )
            )
            return "UNKNOWN"
        return value

    def _configured_remotes(self, root: Path) -> tuple[str, ...]:
        raw = self._run(root, "remote")
        names = tuple(sorted(raw.splitlines()))
        if len(names) != len(set(names)) or any(
            _SAFE_REMOTE_NAME.fullmatch(name) is None for name in names
        ):
            self._local_unknowns.append(
                UnknownFact(
                    fact="configured_remotes",
                    status="BLOCKED",
                    reason="Configured Git remote names are malformed or duplicated.",
                )
            )
            return ()
        return names

    def _branches(self, root: Path, reference_commit: str) -> tuple[BranchObservation, ...]:
        raw = self._run(root, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads")
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
                full_ref, sha = line.rsplit(" ", 1)
            except ValueError as exc:
                raise RepositoryIntelligenceError("local branch output is malformed") from exc
            if not full_ref.startswith("refs/heads/") or full_ref == "refs/heads/":
                raise RepositoryIntelligenceError("local branch reference is malformed")
            name = full_ref.removeprefix("refs/heads/")
            ahead = behind = 0
            status = "OBSERVED"
            comparison = self._execute(
                root,
                (
                    "git",
                    "rev-list",
                    "--left-right",
                    "--count",
                    f"{reference_commit}...{full_ref}",
                ),
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
        raw = self._run(root, "worktree", "list", "--porcelain", "-z")
        results: list[WorktreeObservation] = []
        current: dict[str, str] = {}
        record_invalid = False
        record_number = 0
        allowed_fields = {"worktree", "HEAD", "branch", "bare", "detached", "locked", "prunable"}
        for field in (*raw.split("\0"), ""):
            if not field:
                if current or record_invalid:
                    record_number += 1
                    if record_invalid:
                        current = {}
                        record_invalid = False
                        continue
                    lifecycle_states = sum(key in current for key in ("branch", "detached", "bare"))
                    required_fields = {"worktree"}
                    if "bare" not in current:
                        required_fields.add("HEAD")
                    missing = required_fields - set(current)
                    invalid_identity_shape = "bare" in current and "HEAD" in current
                    if missing or lifecycle_states != 1:
                        self._local_unknowns.append(
                            UnknownFact(
                                fact=f"worktree_record:{record_number}",
                                status="BLOCKED",
                                reason=(
                                    "A Git worktree record is incomplete; mutable worktree state "
                                    "was not inferred."
                                ),
                            )
                        )
                        current = {}
                        continue
                    if invalid_identity_shape:
                        self._local_unknowns.append(
                            UnknownFact(
                                fact=f"worktree_record:{record_number}",
                                status="BLOCKED",
                                reason=(
                                    "A bare Git worktree record contains an unexpected HEAD; "
                                    "mutable worktree state was not inferred."
                                ),
                            )
                        )
                        current = {}
                        continue
                    if not Path(current["worktree"]).is_absolute() or (
                        "branch" in current and not _valid_branch_ref(current["branch"])
                    ):
                        self._local_unknowns.append(
                            UnknownFact(
                                fact=f"worktree_record:{record_number}",
                                status="BLOCKED",
                                reason=(
                                    "A Git worktree path or branch reference is malformed; "
                                    "mutable worktree state was not inferred."
                                ),
                            )
                        )
                        current = {}
                        continue
                    results.append(
                        WorktreeObservation(
                            path=current["worktree"],
                            # Git's documented bare-worktree porcelain form does not
                            # contain HEAD.  Preserve that absence instead of inventing
                            # an immutable revision for a mutable bare repository.
                            head_sha=current.get("HEAD", ""),
                            branch=current.get(
                                "branch", "BARE" if "bare" in current else "DETACHED"
                            ).removeprefix("refs/heads/"),
                            bare="bare" in current,
                            detached="detached" in current,
                            locked="locked" in current,
                            locked_reason=current.get("locked") or None,
                            prunable="prunable" in current,
                            prunable_reason=current.get("prunable") or None,
                        )
                    )
                    if "prunable" in current:
                        self._local_unknowns.append(
                            UnknownFact(
                                fact=f"worktree_prunable:{record_number}",
                                status="BLOCKED",
                                reason=(
                                    "Git reports a prunable worktree; its lifecycle state is "
                                    "preserved but cannot be represented as healthy active work."
                                ),
                            )
                        )
                    current = {}
                continue
            key, separator, value = field.partition(" ")
            if record_invalid:
                continue
            if key not in allowed_fields or key in current:
                self._local_unknowns.append(
                    UnknownFact(
                        fact=f"worktree_record:{record_number + 1}",
                        status="BLOCKED",
                        reason=(
                            "A Git worktree record contains an unknown or duplicate field; "
                            "mutable worktree state was not inferred."
                        ),
                    )
                )
                current = {}
                record_invalid = True
                continue
            if key in {"worktree", "HEAD", "branch"} and (not separator or not value):
                self._local_unknowns.append(
                    UnknownFact(
                        fact=f"worktree_record:{record_number + 1}",
                        status="BLOCKED",
                        reason="A required Git worktree field is malformed.",
                    )
                )
                current = {}
                record_invalid = True
                continue
            if key in {"bare", "detached"} and (separator or value):
                self._local_unknowns.append(
                    UnknownFact(
                        fact=f"worktree_record:{record_number + 1}",
                        status="BLOCKED",
                        reason="A marker-only Git worktree field contains an unexpected value.",
                    )
                )
                current = {}
                record_invalid = True
                continue
            if key in {"locked", "prunable"} and separator and not value:
                self._local_unknowns.append(
                    UnknownFact(
                        fact=f"worktree_record:{record_number + 1}",
                        status="BLOCKED",
                        reason="A Git worktree lifecycle reason is malformed.",
                    )
                )
                current = {}
                record_invalid = True
                continue
            current[key] = value
        return tuple(sorted(results, key=lambda item: item.path))

    def observe(self, repository_root: Path | str, *, ref: str) -> GovernanceObservation:
        self._assert_execution_collaborators_sealed()
        _assert_governance_import_bindings_sealed(verify_state=True)
        self._assert_bound_snapshot_valid()
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
                self.stale_pull_request_after_seconds,
            )
        ):
            raise RepositoryIntelligenceError("governance observation budgets must be positive")
        configured_budgets = {
            "command_timeout_seconds": self.timeout,
            "max_commands": self.max_commands,
            "max_branches": self.max_branches,
            "max_output_bytes": self.max_output_bytes,
            "max_remote_items": self.max_remote_items,
            "max_remote_age_seconds": self.max_remote_age_seconds,
            "stale_pull_request_after_seconds": self.stale_pull_request_after_seconds,
        }
        if any(value > _MAX_GOVERNANCE_BUDGETS[name] for name, value in configured_budgets.items()):
            raise RepositoryIntelligenceError(
                "governance observation budget exceeds a hard safety ceiling"
            )
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
        object_format = self._run(root, "rev-parse", "--show-object-format").strip()
        object_length = _OBJECT_FORMAT_LENGTH.get(object_format)
        if object_length is None:
            raise RepositoryIntelligenceError(
                f"Git object format {object_format!r} is explicitly unsupported"
            )
        ref_commit = self._run(
            root,
            "rev-parse",
            "--verify",
            "--end-of-options",
            f"{ref}^{{commit}}",
        ).strip()
        if not _valid_object_id(ref_commit, object_format):
            raise RepositoryIntelligenceError("governance observation ref identity is malformed")
        if self.snapshot is not None and (
            self.snapshot.commit_sha != ref_commit
            or self.snapshot.git_object_format != object_format
        ):
            raise RepositoryIntelligenceError(
                "governance ref does not resolve to the bound repository snapshot"
            )
        index_listing = self._run(root, "ls-files", "--stage", "-z")
        gitlinks = 0
        for record in index_listing.split("\0"):
            if not record:
                continue
            metadata, separator, _path = record.partition("\t")
            fields = metadata.split()
            if separator != "\t" or len(fields) != 3:
                raise RepositoryIntelligenceError("Git index metadata is malformed")
            mode, object_id, stage = fields
            if not re.fullmatch(r"[0-7]{6}", mode) or not _valid_object_id(
                object_id, object_format
            ):
                raise RepositoryIntelligenceError("Git index metadata is malformed")
            if stage != "0":
                self._local_unknowns.append(
                    UnknownFact(
                        fact="unmerged_index_state",
                        status="BLOCKED",
                        reason="The index contains an unmerged entry.",
                    )
                )
            if mode == "160000":
                gitlinks += 1
        if gitlinks:
            self._local_unknowns.append(
                UnknownFact(
                    fact="submodule_worktree_state",
                    status="UNSUPPORTED",
                    reason=(
                        "Gitlink entries are present; nested submodule worktree dirtiness is "
                        "not executed or inferred and remains a separate mutable unknown."
                    ),
                )
            )
        status_raw = self._run(
            root,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--ignore-submodules=all",
        )
        head_sha = self._run(root, "rev-parse", "HEAD").strip()
        if not _valid_object_id(head_sha, object_format):
            raise RepositoryIntelligenceError("local Git HEAD is malformed")
        index_dirty, worktree_dirty, untracked = _parse_porcelain_status(status_raw)
        local_state = LocalState(
            index_dirty=index_dirty,
            worktree_dirty=worktree_dirty,
            untracked=untracked,
            head_sha=head_sha,
            git_object_format=object_format,
        )
        for is_dirty, fact, explanation in (
            (index_dirty, "dirty_index", "The Git index contains uncommitted changes."),
            (
                worktree_dirty,
                "dirty_worktree",
                "The working tree contains unstaged tracked changes.",
            ),
            (untracked, "untracked_files", "The working tree contains untracked files."),
        ):
            if is_dirty:
                self._local_unknowns.append(
                    UnknownFact(fact=fact, status="BLOCKED", reason=explanation)
                )
        current_branch = self._current_branch(root)
        configured_remotes = self._configured_remotes(root)
        branches = self._branches(root, ref_commit)
        worktrees = self._worktrees(root)
        if any(not _valid_object_id(item.sha, object_format) for item in branches) or any(
            (item.bare and item.head_sha != "")
            or (not item.bare and not _valid_object_id(item.head_sha, object_format))
            for item in worktrees
        ):
            raise RepositoryIntelligenceError("local Git reference identity is malformed")
        clock = self.clock
        id_provider = self.id_provider
        observed_at = clock.now()
        observation_id = id_provider.new_id()
        self._assert_execution_collaborators_sealed()
        observed_at_value = _parse_utc(observed_at, field="observation time")

        remote_branches: tuple[RemoteBranchObservation, ...] = ()
        pull_requests: tuple[PullRequestObservation, ...] = ()
        issues: tuple[IssueObservation, ...] = ()
        governance: dict[str, Any] = {}
        provenance: tuple[QueryProvenance, ...] = ()
        remote_observed_at: str | None = None
        remote_default_branch: str | None = None
        remote_query_coverage: tuple[str, ...] = ()
        remote_collection_provenance: dict[str, Any] = {}
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
        remote_collection_status = "NOT_REQUESTED"
        sanitized_remote: dict[str, Any] = {}
        if self.remote_provider is not None:
            tool_identity = self.remote_provider.tool_identity
            api_version = self.remote_provider.api_version
            remote_collection_provenance = self.remote_provider.collection_provenance
            remote_collection_status = "STARTED"
            try:
                raw_remote = self._collect_remote_bounded(ref)
                self._assert_execution_collaborators_sealed()
            except (PermissionError, OSError):
                remote_collection_status = "PERMISSION_OR_IO_BLOCKED"
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
                remote_collection_status = "ERROR_BLOCKED"
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
                    redactor = self.redactor
                    sanitized_remote = cast(dict[str, Any], redactor.sanitize(raw_remote))
                    for namespace, identities in _remote_identity_groups(
                        raw_remote, sanitized_remote
                    ).items():
                        assert_distinct_identities_preserved(namespace, identities)
                except (RedactionError, Exception) as exc:
                    raise RepositorySecurityError(
                        "remote evidence redaction failed; observation was not created"
                    ) from exc
                self._assert_execution_collaborators_sealed()
                try:
                    _validate_remote_payload_types(raw_remote)
                    _validate_remote_payload_types(sanitized_remote)
                    if sanitized_remote.get("repository") != self.repository:
                        raise ValueError("remote repository identity does not match the request")
                    if sanitized_remote.get("ref") != ref:
                        raise ValueError("remote ref identity does not match the request")
                    remote_observed_at = cast(str, sanitized_remote["observed_at"])
                    remote_default_branch = cast(str, sanitized_remote["default_branch"])
                    remote_observed_value = _parse_utc(
                        remote_observed_at, field="remote observation time"
                    )
                    remote_age = (observed_at_value - remote_observed_value).total_seconds()
                    remote_query_coverage = tuple(
                        sorted(cast(list[str], sanitized_remote["coverage"]))
                    )
                    coverage_complete = set(remote_query_coverage) == _REQUIRED_REMOTE_COVERAGE
                    freshness_proven = -30 <= remote_age <= self.max_remote_age_seconds
                    remote_branches = tuple(
                        RemoteBranchObservation(
                            name=item["name"],
                            sha=item["sha"],
                            comparison_ref=item["comparison_ref"],
                            ahead=item["ahead"],
                            behind=item["behind"],
                            status=item["status"],
                        )
                        for item in sanitized_remote["remote_branches"]
                    )
                    parsed_pull_requests: list[PullRequestObservation] = []
                    for item in sanitized_remote["pull_requests"]:
                        update_age = (
                            remote_observed_value
                            - _parse_utc(
                                item["updated_at"],
                                field="pull request update time",
                            )
                        ).total_seconds()
                        if update_age < -30:
                            raise ValueError(
                                "pull request update time is later than the remote observation"
                            )
                        parsed_pull_requests.append(
                            PullRequestObservation(
                                number=item["number"],
                                draft=item["draft"],
                                head=item["head"],
                                updated_at=item["updated_at"],
                                mergeability=item["mergeability"],
                                stale=update_age > self.stale_pull_request_after_seconds,
                            )
                        )
                    pull_requests = tuple(parsed_pull_requests)
                    issues = tuple(
                        IssueObservation(number=item["number"], state=item["state"])
                        for item in sanitized_remote["issues"]
                    )
                    if len({item.name for item in remote_branches}) != len(remote_branches):
                        raise ValueError("remote branch inventory contains duplicate names")
                    if len({item.number for item in pull_requests}) != len(pull_requests):
                        raise ValueError("pull request inventory contains duplicate numbers")
                    if len({item.number for item in issues}) != len(issues):
                        raise ValueError("issue inventory contains duplicate numbers")
                    governance = cast(dict[str, Any], sanitized_remote["governance"])
                    governance_complete = _governance_content_is_complete(governance)
                    provenance = tuple(
                        QueryProvenance(
                            surface=item["surface"],
                            query=item["query"],
                            cursor=cast(str | None, item.get("cursor")),
                            page=cast(int | None, item.get("page")),
                            has_next_page=item["has_next_page"],
                            result_count=cast(int | None, item.get("result_count")),
                        )
                        for item in sanitized_remote["query_provenance"]
                    )
                    remote_unknowns = tuple(
                        UnknownFact(
                            fact=item["fact"],
                            status=item["status"],
                            reason=item["reason"],
                        )
                        for item in sanitized_remote["unknowns"]
                    )
                    unknown_mergeability = tuple(
                        item.number
                        for item in pull_requests
                        if item.mergeability not in {"MERGEABLE", "CONFLICTING"}
                    )
                    if unknown_mergeability:
                        remote_unknowns = (
                            *remote_unknowns,
                            *(
                                UnknownFact(
                                    fact=f"pull_request_mergeability:{number}",
                                    status="BLOCKED",
                                    reason=(
                                        "Pull request conflict/mergeability evidence is missing "
                                        "or unsupported."
                                    ),
                                )
                                for number in unknown_mergeability
                            ),
                        )
                    unresolved_remote_divergence = tuple(
                        item.name for item in remote_branches if item.status != "OBSERVED"
                    )
                    if unresolved_remote_divergence:
                        remote_unknowns = (
                            *remote_unknowns,
                            *(
                                UnknownFact(
                                    fact=f"remote_branch_divergence:{name}",
                                    status="BLOCKED",
                                    reason=(
                                        "Remote branch divergence was not observed completely."
                                    ),
                                )
                                for name in unresolved_remote_divergence
                            ),
                        )
                    if any(
                        not _valid_object_id(item.sha, object_format) for item in remote_branches
                    ) or any(
                        not _valid_object_id(item.head, object_format) for item in pull_requests
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
                    remote_collection_status = "INVALID_BLOCKED"
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
                    remote_collection_status = "EVALUATED"
                    unknowns = (
                        *self._local_unknowns,
                        *remote_unknowns,
                        UnknownFact(
                            fact="remote_collection_attestation",
                            status="BLOCKED",
                            reason=(
                                "Remote facts were supplied as reproducible recorded input, "
                                "but no independently verifiable collector attestation was "
                                "available; they cannot make this observation complete."
                            ),
                        ),
                    )
                    disposition = (
                        "BLOCKED"
                        if any(item.status == "BLOCKED" for item in unknowns)
                        else "PARTIAL"
                        if any(item.status in {"UNKNOWN", "UNSUPPORTED"} for item in unknowns)
                        else "COMPLETE"
                    )
                    pagination_complete = sanitized_remote.get(
                        "complete"
                    ) is True and _pagination_is_complete(
                        provenance,
                        {
                            "remote_branches": len(remote_branches),
                            "pull_requests": len(pull_requests),
                            "issues": len(issues),
                            "governance": 1 if governance else 0,
                        },
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
                    if not governance_complete:
                        disposition = "BLOCKED"
                        unknowns = (
                            *unknowns,
                            UnknownFact(
                                fact="remote_governance_completeness",
                                status="BLOCKED",
                                reason=(
                                    "Required branch-protection or review-policy facts are "
                                    "missing, empty, or explicitly unknown."
                                ),
                            ),
                        )

        revalidation_unknown_start = len(self._local_unknowns)
        try:
            final_ref_commit = self._run(
                root,
                "rev-parse",
                "--verify",
                "--end-of-options",
                f"{ref}^{{commit}}",
            ).strip()
            final_head_sha = self._run(root, "rev-parse", "HEAD").strip()
            final_index_listing = self._run(root, "ls-files", "--stage", "-z")
            final_status_raw = self._run(
                root,
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
                "--ignore-submodules=all",
            )
            final_current_branch = self._current_branch(root)
            final_configured_remotes = self._configured_remotes(root)
            final_branches = self._branches(root, ref_commit)
            final_worktrees = self._worktrees(root)
        except RepositoryIntelligenceError:
            disposition = "BLOCKED"
            unknowns = (
                *unknowns,
                UnknownFact(
                    fact="local_state_revalidation",
                    status="BLOCKED",
                    reason=("Mutable local state could not be revalidated before finalization."),
                ),
            )
        else:
            revalidation_unknowns = tuple(self._local_unknowns[revalidation_unknown_start:])
            if revalidation_unknowns:
                disposition = "BLOCKED"
                unknowns = (*unknowns, *revalidation_unknowns)
            if (
                final_ref_commit != ref_commit
                or final_head_sha != head_sha
                or final_index_listing != index_listing
                or final_status_raw != status_raw
                or final_current_branch != current_branch
                or final_configured_remotes != configured_remotes
                or final_branches != branches
                or final_worktrees != worktrees
            ):
                disposition = "BLOCKED"
                unknowns = (
                    *unknowns,
                    UnknownFact(
                        fact="concurrent_local_mutation",
                        status="BLOCKED",
                        reason=(
                            "The ref, HEAD, index, worktree, branch, remote, or worktree "
                            "inventory changed during collection; mixed-time facts were not "
                            "represented as complete."
                        ),
                    ),
                )

        if self._is_cancelled() and not any(
            item.fact == "observation_cancellation" for item in unknowns
        ):
            remote_collection_status = "CANCELLED"
            disposition = "BLOCKED"
            unknowns = (
                *unknowns,
                UnknownFact(
                    fact="observation_cancellation",
                    status="BLOCKED",
                    reason="Mutable governance observation was cancelled before finalization.",
                ),
            )
        collector_digest = _governance_implementation_digest(
            self._extension_implementation_evidence
        )
        inputs = {
            "repository": self.repository,
            "ref": ref,
            "resolved_ref_commit": ref_commit,
            "repository_snapshot_digest": (
                self.snapshot.snapshot_digest if self.snapshot is not None else None
            ),
            "repository_snapshot_commit": (
                self.snapshot.commit_sha if self.snapshot is not None else None
            ),
            "observation_id": observation_id,
            "observed_at": observed_at,
            "local_status": status_raw,
            "git_index_listing_digest": "sha256:"
            + hashlib.sha256(index_listing.encode("utf-8")).hexdigest(),
            "local_state": asdict(local_state),
            "current_branch": current_branch,
            "configured_remotes": configured_remotes,
            "local_branches": [asdict(item) for item in branches],
            "worktrees": [asdict(item) for item in worktrees],
            "command_provenance": [asdict(item) for item in self._command_provenance],
            "collector_configuration": {
                "command_timeout_seconds": self.timeout,
                "max_commands": self.max_commands,
                "max_branches": self.max_branches,
                "max_output_bytes": self.max_output_bytes,
                "max_remote_items": self.max_remote_items,
                "max_remote_age_seconds": self.max_remote_age_seconds,
                "stale_pull_request_after_seconds": self.stale_pull_request_after_seconds,
            },
            "remote_result": sanitized_remote,
            "remote_collection_status": remote_collection_status,
            "remote_observed_at": remote_observed_at,
            "remote_default_branch": remote_default_branch,
            "remote_query_coverage": remote_query_coverage,
            "remote_collection_provenance": remote_collection_provenance,
            "normalized_remote_evidence": {
                "remote_branches": [asdict(item) for item in remote_branches],
                "pull_requests": [asdict(item) for item in pull_requests],
                "issues": [asdict(item) for item in issues],
                "governance": governance,
                "query_provenance": [asdict(item) for item in provenance],
            },
            "evaluation_disposition": disposition,
            "evaluation_unknowns": [asdict(item) for item in unknowns],
            "tool_identity": tool_identity,
            "api_query_version": api_version,
            "collector_version": GOVERNANCE_COLLECTOR_VERSION,
            "collector_implementation_digest": collector_digest,
        }
        try:
            redactor = self.redactor
            sanitized_inputs = redactor.sanitize(inputs)
        except (RedactionError, Exception) as exc:
            raise RepositorySecurityError("observation redaction failed") from exc
        self._assert_execution_collaborators_sealed()
        self._assert_bound_snapshot_valid()
        input_digest = canonical_digest(sanitized_inputs)
        draft = GovernanceObservation(
            observation_id=observation_id,
            observed_at=observed_at,
            repository=self.repository,
            ref=ref,
            repository_snapshot_digest=(
                self.snapshot.snapshot_digest if self.snapshot is not None else None
            ),
            repository_snapshot_commit=(
                self.snapshot.commit_sha if self.snapshot is not None else None
            ),
            local_state=local_state,
            current_branch=current_branch,
            configured_remotes=configured_remotes,
            local_branches=branches,
            worktrees=worktrees,
            command_provenance=tuple(self._command_provenance),
            remote_branches=remote_branches,
            remote_default_branch=remote_default_branch,
            pull_requests=pull_requests,
            issues=issues,
            governance=governance,
            query_provenance=provenance,
            remote_observed_at=remote_observed_at,
            remote_query_coverage=remote_query_coverage,
            remote_collection_provenance=remote_collection_provenance,
            unknowns=unknowns,
            collector_version=GOVERNANCE_COLLECTOR_VERSION,
            collector_implementation_digest=collector_digest,
            tool_identity=tool_identity,
            api_query_version=api_version,
            observation_input_digest=input_digest,
            observation_output_digest="",
            disposition=disposition,
            redaction={
                "version": str(getattr(redactor, "version", "unknown")),
                "status": "SANITIZED_BEFORE_PERSISTENCE",
                "marker": "[REDACTED]",
                "mutable_truth": "TIME_BOUND_OBSERVATION_ONLY",
            },
        )
        original = draft.as_dict()
        try:
            sanitized = cast(dict[str, Any], redactor.sanitize(original))
            for namespace, identities in _observation_identity_groups(original, sanitized).items():
                assert_distinct_identities_preserved(namespace, identities)
        except (RedactionError, Exception) as exc:
            raise RepositorySecurityError("observation redaction failed") from exc
        self._assert_execution_collaborators_sealed()
        self._assert_bound_snapshot_valid()
        if self._is_cancelled() and not any(
            item.get("fact") == "observation_cancellation"
            for item in cast(list[dict[str, Any]], sanitized["unknowns"])
        ):
            cast(list[dict[str, Any]], sanitized["unknowns"]).append(
                {
                    "fact": "observation_cancellation",
                    "status": "BLOCKED",
                    "reason": "Mutable governance observation was cancelled before finalization.",
                }
            )
            sanitized["unknowns"] = sorted(
                cast(list[dict[str, Any]], sanitized["unknowns"]),
                key=lambda item: (item["fact"], item["status"], item["reason"]),
            )
            sanitized["disposition"] = "BLOCKED"
            sanitized["observation_input_digest"] = _late_cancellation_input_digest(
                sanitized_inputs
            )
        sanitized["observation_output_digest"] = canonical_digest(
            {key: value for key, value in sanitized.items() if key != "observation_output_digest"}
        )
        if (
            not any(
                item.get("fact") == "observation_cancellation"
                for item in cast(list[dict[str, Any]], sanitized["unknowns"])
            )
            and not self._claim_completion()
        ):
            cast(list[dict[str, Any]], sanitized["unknowns"]).append(
                {
                    "fact": "observation_cancellation",
                    "status": "BLOCKED",
                    "reason": "Mutable governance observation was cancelled before finalization.",
                }
            )
            sanitized["unknowns"] = sorted(
                cast(list[dict[str, Any]], sanitized["unknowns"]),
                key=lambda item: (item["fact"], item["status"], item["reason"]),
            )
            sanitized["disposition"] = "BLOCKED"
            sanitized["observation_input_digest"] = _late_cancellation_input_digest(
                sanitized_inputs
            )
            sanitized["observation_output_digest"] = canonical_digest(
                {
                    key: value
                    for key, value in sanitized.items()
                    if key != "observation_output_digest"
                }
            )
        return _observation_from_dict(sanitized)


def observe_governance(
    repository_root: Path | str,
    *,
    repository: str,
    ref: str,
    snapshot: RepositorySnapshot | None = None,
    clock: Clock | None = None,
    id_provider: IdProvider | None = None,
    remote_provider: RemoteProvider | None = None,
) -> GovernanceObservation:
    return GovernanceCollector(
        repository=repository,
        snapshot=snapshot,
        clock=clock or SystemUtcClock(),
        id_provider=id_provider or UuidObservationIds(),
        remote_provider=remote_provider,
    ).observe(repository_root, ref=ref)
