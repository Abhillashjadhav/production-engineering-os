"""Read-only exact-Git-object repository scanner."""

from __future__ import annotations

import hashlib
import importlib.metadata
import inspect
import json
import multiprocessing
import os
import platform
import posixpath
import re
import selectors
import signal
import stat
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol, cast, final

import yaml

from pmpe.contracts.canonical import canonical_digest
from pmpe.repository.adapters import (
    AdapterContext,
    AdapterResult,
    RepositoryAdapter,
    TrackedFile,
    default_adapters,
)
from pmpe.repository.models import (
    AUDIT_CATEGORIES,
    AdapterMetadata,
    BoundaryCandidate,
    CommandProvenance,
    CommandResult,
    EvidenceItem,
    Finding,
    InventoryCategory,
    RepositorySnapshot,
    ScanConfig,
    ToolVersion,
)
from pmpe.repository.redaction import EvidenceRedactor, RedactionError

SCANNER_VERSION = "repository-scanner/2.2.0"
IMPLEMENTATION_MODULES = (
    "repository.adapters",
    "repository.models",
    "repository.redaction",
    "repository.scanner",
    "contracts.canonical",
)
_OBJECT_FORMAT_LENGTH = {"sha1": 40, "sha256": 64}


class RepositoryIntelligenceError(RuntimeError):
    """Safe fail-closed repository-intelligence failure."""


class RepositorySecurityError(RepositoryIntelligenceError):
    """A containment or evidence-safety guarantee could not be established."""


class RepositoryScanCancelledError(RepositoryIntelligenceError):
    """A scan stopped before an exact-SHA snapshot could be safely emitted."""

    def __init__(self, evidence_ref: str) -> None:
        self.finding = Finding(
            code="SCAN.CANCELLED",
            category="repository_topology",
            severity="HIGH",
            confidence="HIGH",
            explanation=(
                "The scan was cancelled before immutable repository identity could be "
                "established; no RepositorySnapshot was emitted."
            ),
            evidence_refs=(evidence_ref,),
            detector_id="repository-scanner",
            detector_version="1.1.0",
            blocking=True,
        )
        super().__init__(f"{self.finding.code}: {self.finding.explanation}")


class CommandRunner(Protocol):
    identity: str

    def run(self, args: tuple[str, ...], cwd: Path, timeout: int) -> CommandResult: ...


class Cancellation(Protocol):
    def cancelled(self) -> bool: ...


@final
class CancellationSignal:
    """Sealed cancellation capability with no caller-executed callback."""

    __slots__ = ("_cancel_after_checks", "_checks", "_event", "_lock")

    def __init__(self, *, cancel_after_checks: int | None = None) -> None:
        if cancel_after_checks is not None and cancel_after_checks < 1:
            raise ValueError("cancellation check limit must be positive")
        self._cancel_after_checks = cancel_after_checks
        self._checks = 0
        self._event = threading.Event()
        self._lock = threading.Lock()

    def cancel(self) -> None:
        self._event.set()

    def cancelled(self) -> bool:
        with self._lock:
            self._checks += 1
            threshold_reached = (
                self._cancel_after_checks is not None and self._checks >= self._cancel_after_checks
            )
        return self._event.is_set() or threshold_reached


_PROCESS_GROUP_GUARD = "import signal\nwhile True:\n signal.pause()"
_TRUSTED_GIT_CANDIDATES = (Path("/usr/bin/git"), Path("/bin/git"))


def _trusted_git_executable() -> str:
    """Resolve Git only from root-owned, non-writable operating-system paths."""

    for candidate in _TRUSTED_GIT_CANDIDATES:
        try:
            resolved = candidate.resolve(strict=True)
            metadata = resolved.stat()
        except OSError:
            continue
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != 0
            or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        ):
            continue
        return str(resolved)
    raise FileNotFoundError("a trusted operating-system Git executable is unavailable")


def _spawn_guarded_git(
    args: tuple[str, ...], cwd: Path, environment: dict[str, str]
) -> tuple[subprocess.Popen[bytes], subprocess.Popen[bytes]]:
    """Launch Git behind an inert group leader whose PID cannot be reused early."""

    if not args or args[0] != "git":
        raise RepositorySecurityError("guarded Git execution requires the logical Git command")
    executable = _trusted_git_executable()
    sealed_args = (executable, *args[1:])

    guard_environment = {"PATH": environment.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"}
    guard = subprocess.Popen(
        (sys.executable, "-I", "-S", "-c", _PROCESS_GROUP_GUARD),
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=guard_environment,
        process_group=0,
    )
    try:
        process = subprocess.Popen(
            sealed_args,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=environment,
            process_group=guard.pid,
        )
    except BaseException:
        with suppress(ProcessLookupError, OSError):
            os.killpg(guard.pid, signal.SIGKILL)
        with suppress(subprocess.TimeoutExpired):
            guard.wait(timeout=1.0)
        raise
    return process, guard


def _stop_guarded_process_group(
    process: subprocess.Popen[bytes], guard: subprocess.Popen[bytes]
) -> None:
    """Fence a retained group identity, then reap the command and its guard."""

    group_proven = _signal_process_group(guard, signal.SIGKILL)
    try:
        process.wait(timeout=1.0)
        guard.wait(timeout=1.0)
    except subprocess.TimeoutExpired as exc:
        raise RepositorySecurityError("bounded Git process group could not be reaped") from exc
    if not group_proven:
        raise RepositorySecurityError("bounded Git descendant termination could not be proven")


class _ScanCancelledError(RepositoryScanCancelledError):
    """An in-flight bounded scan operation was cancelled."""


class _ScanCommandBudgetError(RepositoryIntelligenceError):
    """A required scan command could not run within the declared budget."""


def _cancellation_requested(cancellation: Cancellation | None) -> bool:
    if cancellation is None:
        return False
    try:
        return cancellation.cancelled()
    except Exception:
        return True


@dataclass(frozen=True)
class TreeListingResult:
    result: CommandResult
    record_limit_exceeded: bool
    byte_limit_exceeded: bool
    cancelled: bool


class SubprocessCommandRunner:
    """Allowlisted local Git reader; it never invokes shells or project code."""

    identity = "git-readonly-subprocess/1.8.0"
    __slots__ = ()
    _allowed = {"rev-parse", "ls-tree", "cat-file", "version"}

    @staticmethod
    def _environment() -> dict[str, str]:
        return {
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

    def run(
        self,
        args: tuple[str, ...],
        cwd: Path,
        timeout: int,
        *,
        cancellation: Cancellation | None = None,
    ) -> CommandResult:
        if cancellation is not None and type(cancellation) is not CancellationSignal:
            raise RepositorySecurityError("Git cancellation requires the sealed signal")
        if len(args) < 2 or args[0] != "git" or args[1] not in self._allowed:
            raise RepositorySecurityError("command is outside the read-only Git allowlist")
        process, guard = _spawn_guarded_git(args, cwd, self._environment())
        if process.stdout is None:
            _stop_guarded_process_group(process, guard)
            raise RepositoryIntelligenceError("bounded Git command output is unavailable")
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        payload = bytearray()
        deadline = time.monotonic() + timeout
        timed_out = False
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
                events = selector.select(min(remaining, 0.05))
                if events:
                    chunk = os.read(process.stdout.fileno(), 65_536)
                    if not chunk:
                        break
                    payload.extend(chunk)
                    if len(payload) > 8_000_000:
                        timed_out = True
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
            returncode=126 if cancelled else 124 if timed_out else returncode,
            stdout=bytes(payload),
            stderr=b"",
            timed_out=timed_out,
        )

    def list_tree(
        self,
        args: tuple[str, ...],
        cwd: Path,
        timeout: int,
        *,
        max_records: int,
        max_output_bytes: int,
        cancellation: Cancellation | None = None,
    ) -> TreeListingResult:
        """Stream NUL-delimited tree records and stop before unbounded buffering."""

        if cancellation is not None and type(cancellation) is not CancellationSignal:
            raise RepositorySecurityError("Git cancellation requires the sealed signal")
        if len(args) < 2 or args[0:2] != ("git", "ls-tree"):
            raise RepositorySecurityError("bounded tree reader only accepts git ls-tree")
        process, guard = _spawn_guarded_git(args, cwd, self._environment())
        if process.stdout is None:
            _stop_guarded_process_group(process, guard)
            raise RepositoryIntelligenceError("bounded tree reader did not expose output")
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        payload = bytearray()
        record_limit = False
        record_count = 0
        byte_limit = False
        timed_out = False
        cancelled = False
        deadline = time.monotonic() + timeout
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
                record_count += chunk.count(0)
                if len(payload) > max_output_bytes:
                    byte_limit = True
                    break
                if record_count >= max_records:
                    record_limit = True
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
        complete_records = bytes(payload[:max_output_bytes]).split(b"\0")
        if complete_records and complete_records[-1]:
            complete_records = complete_records[:-1]
        complete_records = complete_records[:max_records]
        bounded_payload = b"\0".join(complete_records)
        if complete_records:
            bounded_payload += b"\0"
        return TreeListingResult(
            result=CommandResult(
                args=args,
                # A deliberate budget stop is represented by the finding flags, not
                # by the platform-dependent SIGTERM status in canonical provenance.
                returncode=0 if record_limit or byte_limit else returncode,
                stdout=bounded_payload,
                stderr=b"",
                timed_out=timed_out,
            ),
            record_limit_exceeded=record_limit,
            byte_limit_exceeded=byte_limit,
            cancelled=cancelled,
        )


def _signal_process_group(process: subprocess.Popen[bytes], action: signal.Signals) -> bool:
    """Stop the isolated immutable-object reader and any unexpected descendant."""

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
        # Always make a best-effort parent termination if process-group signalling
        # is unavailable. These immutable-object commands cannot invoke repository
        # code, so a successfully signalled and reaped parent is a safe fallback.
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


def _wait_for_exit_without_reaping(process: subprocess.Popen[bytes], timeout: float) -> bool:
    """Observe child exit while retaining its PID until the process group is fenced."""

    if not all(hasattr(os, name) for name in ("P_PID", "WEXITED", "WNOHANG", "WNOWAIT")):
        raise RepositorySecurityError("PID-safe bounded process observation is unsupported")
    waitid = cast(
        Callable[[int, int, int], object | None],
        vars(os)["waitid"],
    )
    deadline = time.monotonic() + timeout
    while True:
        try:
            result = waitid(
                os.P_PID,
                process.pid,
                os.WEXITED | os.WNOHANG | os.WNOWAIT,
            )
        except ChildProcessError as exc:
            raise RepositorySecurityError(
                "bounded process was reaped before its process group was fenced"
            ) from exc
        if result is not None:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)


def _valid_object_id(value: str, object_format: str) -> bool:
    length = _OBJECT_FORMAT_LENGTH.get(object_format)
    return (
        length is not None
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


def _implementation_source_evidence(label: str, target: Any) -> dict[str, str]:
    """Bind an injected output-affecting implementation without persisting its state."""

    implementation = target if inspect.isfunction(target) else target.__class__
    try:
        source_path_value = inspect.getsourcefile(implementation)
        if source_path_value is None:
            raise OSError("implementation source path is unavailable")
        source_digest = _sha256(Path(source_path_value).read_bytes())
        callable_target = target if callable(target) else getattr(target, "run", None)
        if callable_target is None and not inspect.isfunction(target) and callable(target):
            callable_target = inspect.getattr_static(implementation, "__call__", None)
        code_digest = (
            _sha256(inspect.getsource(callable_target).encode("utf-8"))
            if callable_target is not None
            else source_digest
        )
    except (OSError, TypeError, ValueError) as exc:
        raise RepositoryIntelligenceError(
            f"{label} implementation bytes are unavailable for provenance binding"
        ) from exc
    return {
        "label": label,
        "module": str(getattr(implementation, "__module__", "unknown")),
        "qualname": str(getattr(implementation, "__qualname__", type(target).__qualname__)),
        "source_digest": source_digest,
        "code_digest": code_digest,
    }


def _implementation_digest(
    extension_evidence: Sequence[dict[str, str]] = (),
) -> str:
    package_root = Path(__file__).resolve().parent
    paths = {
        "repository.adapters": package_root / "adapters.py",
        "repository.models": package_root / "models.py",
        "repository.redaction": package_root / "redaction.py",
        "repository.scanner": package_root / "scanner.py",
        "contracts.canonical": package_root.parent / "contracts" / "canonical.py",
    }
    try:
        evidence: list[dict[str, str]] = [
            {"module": name, "source_digest": _sha256(paths[name].read_bytes())}
            for name in IMPLEMENTATION_MODULES
        ]
    except OSError as exc:
        raise RepositoryIntelligenceError(
            "scanner implementation bytes are unavailable for provenance binding"
        ) from exc
    evidence.extend(extension_evidence)
    return canonical_digest(
        sorted(evidence, key=lambda item: (item.get("label", ""), item["module"]))
    )


def _adapter_worker(connection: Any, adapter: RepositoryAdapter, context: AdapterContext) -> None:
    """Evaluate one adapter in a killable, environment-isolated process."""

    isolated = False
    try:
        os.setsid()
        isolated = True
        os.environ.clear()
        os.environ.update({"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
        result = adapter.evaluator(context)
        if not isinstance(result, AdapterResult):
            raise TypeError("adapter result has an invalid type")
        payload = json.dumps(
            {"status": "RESULT", "result": asdict(result)},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        connection.send_bytes(payload)
    except BaseException as exc:
        with suppress(BrokenPipeError, EOFError, OSError):
            connection.send_bytes(
                json.dumps(
                    {"status": "ERROR", "error_type": type(exc).__name__},
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
    finally:
        connection.close()
        if isolated:
            while True:
                signal.pause()


def _stop_isolated_process(process: Any) -> None:
    """Terminate a forked evaluator and its descendants even if its parent exited."""

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
        raise RepositorySecurityError("bounded adapter process could not be reaped")
    if not group_proven:
        raise RepositorySecurityError("bounded adapter descendant termination could not be proven")


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _text(value: str | bytes) -> str:
    return value.decode("utf-8", errors="strict") if isinstance(value, bytes) else value


def _safe_relative_path(value: str) -> bool:
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts and value not in {"", "."}


def resolve_repository_root(repository_root: Path | str) -> Path:
    """Resolve a Git root with the same non-locking read-only policy as scans."""

    requested = Path(repository_root).resolve()
    runner = SubprocessCommandRunner()
    result = runner.run(("git", "rev-parse", "--show-toplevel"), requested, 20)
    if result.timed_out or result.returncode != 0:
        raise RepositoryIntelligenceError("path is not an accessible Git repository")
    try:
        root = Path(_text(result.stdout).strip()).resolve(strict=True)
    except (UnicodeDecodeError, OSError) as exc:
        raise RepositoryIntelligenceError("Git repository root is malformed") from exc
    if root != requested and root not in requested.parents:
        raise RepositorySecurityError("resolved Git repository root is outside the requested path")
    return root


def _symlink_escapes(path: str, target: bytes | None) -> bool:
    if target is None:
        return True
    try:
        value = target.decode("utf-8")
    except UnicodeDecodeError:
        return True
    if PurePosixPath(value).is_absolute():
        return True
    joined = posixpath.normpath(posixpath.join(posixpath.dirname(path), value))
    return joined == ".." or joined.startswith("../")


def _finding(
    code: str,
    category: str,
    explanation: str,
    evidence_refs: tuple[str, ...],
    *,
    blocking: bool = False,
    severity: str = "HIGH",
) -> Finding:
    return Finding(
        code=code,
        category=category,
        severity=severity,
        confidence="HIGH",
        explanation=explanation,
        evidence_refs=evidence_refs,
        detector_id="repository-scanner",
        detector_version="1.1.0",
        blocking=blocking,
    )


def _metadata(adapter: RepositoryAdapter) -> AdapterMetadata:
    return AdapterMetadata(
        adapter_id=adapter.adapter_id,
        version=adapter.version,
        detector_version=adapter.detector_version,
        file_patterns=adapter.file_patterns,
        supported_categories=adapter.supported_categories,
        failure_behavior=adapter.failure_behavior,
        detection_logic=adapter.detection_logic,
        evidence_emitted=adapter.evidence_emitted,
        confidence_semantics=adapter.confidence_semantics,
    )


def _snapshot_from_dict(value: dict[str, Any]) -> RepositorySnapshot:
    inventory = {
        name: InventoryCategory(
            status=str(category["status"]),
            items=tuple(EvidenceItem(**item) for item in category["items"]),
            reason=str(category["reason"]),
        )
        for name, category in cast(dict[str, dict[str, Any]], value["inventory"]).items()
    }
    return RepositorySnapshot(
        repository=str(value["repository"]),
        commit_sha=str(value["commit_sha"]),
        tree_sha=str(value["tree_sha"]),
        git_object_format=str(value["git_object_format"]),
        default_branch=cast(str | None, value["default_branch"]),
        default_branch_source=str(value["default_branch_source"]),
        scanner_version=str(value["scanner_version"]),
        scan_configuration_digest=str(value["scan_configuration_digest"]),
        adapter_set_digest=str(value["adapter_set_digest"]),
        implementation_digest=str(value["implementation_digest"]),
        tracked_tree_digest=str(value["tracked_tree_digest"]),
        scanned_content_digest=str(value["scanned_content_digest"]),
        scan_scope=str(value["scan_scope"]),
        included_paths=tuple(value["included_paths"]),
        tooling_digest=str(value["tooling_digest"]),
        tool_versions=tuple(ToolVersion(**item) for item in value["tool_versions"]),
        adapters=tuple(
            AdapterMetadata(
                **{
                    **item,
                    "file_patterns": tuple(item["file_patterns"]),
                    "supported_categories": tuple(item["supported_categories"]),
                }
            )
            for item in value["adapters"]
        ),
        command_provenance=tuple(
            CommandProvenance(
                args=tuple(item["args"]),
                tool_identity=str(item["tool_identity"]),
                exit_status=int(item["exit_status"]),
                timed_out=bool(item["timed_out"]),
            )
            for item in value["command_provenance"]
        ),
        inventory=inventory,
        findings=tuple(
            Finding(**{**item, "evidence_refs": tuple(item["evidence_refs"])})
            for item in value["findings"]
        ),
        boundary_candidates=tuple(
            BoundaryCandidate(**{**item, "evidence_paths": tuple(item["evidence_paths"])})
            for item in value["boundary_candidates"]
        ),
        unsupported_categories=tuple(value["unsupported_categories"]),
        disposition=str(value["disposition"]),
        redaction=cast(dict[str, Any], value["redaction"]),
        snapshot_digest=str(value["snapshot_digest"]),
        artifact_kind=str(value["artifact_kind"]),
    )


class RepositoryScanner:
    """Create a deterministic artifact from immutable tracked Git objects only."""

    def __init__(
        self,
        *,
        config: ScanConfig,
        adapters: Sequence[RepositoryAdapter] | None = None,
        command_runner: CommandRunner | None = None,
        redactor: Any | None = None,
        cancellation: Cancellation | None = None,
    ) -> None:
        self.config = config
        registered_adapters = default_adapters()
        requested_adapters = tuple(adapters) if adapters is not None else registered_adapters
        registered_by_id = {item.adapter_id: item for item in registered_adapters}
        if len(requested_adapters) != len(registered_adapters) or any(
            registered_by_id.get(item.adapter_id) is not item for item in requested_adapters
        ):
            raise RepositorySecurityError(
                "repository scans only execute the sealed built-in adapter registry"
            )
        self.adapters = tuple(sorted(requested_adapters, key=lambda item: item.adapter_id))
        adapter_ids = [item.adapter_id for item in self.adapters]
        if len(set(adapter_ids)) != len(adapter_ids) or any(
            not item.adapter_id
            or not item.version
            or not item.detector_version
            or not item.file_patterns
            or not item.supported_categories
            or not set(item.supported_categories).issubset(AUDIT_CATEGORIES)
            for item in self.adapters
        ):
            raise RepositoryIntelligenceError("repository adapter declaration is invalid")
        if command_runner is not None and type(command_runner) is not SubprocessCommandRunner:
            raise RepositorySecurityError("repository scans require the sealed Git reader")
        if redactor is not None and type(redactor) is not EvidenceRedactor:
            raise RepositorySecurityError("repository scans require the sealed redactor")
        if cancellation is not None and type(cancellation) is not CancellationSignal:
            raise RepositorySecurityError("repository scans require the sealed cancellation signal")
        self.runner = command_runner or SubprocessCommandRunner()
        # Exact-SHA snapshots never capture host environment values; excluding them
        # from the default redaction context preserves cross-host determinism.
        self.redactor = redactor or EvidenceRedactor(environment={})
        self.cancellation = cancellation
        extension_targets: list[tuple[str, Any]] = [
            ("command_runner", self.runner),
            ("redactor", self.redactor),
            *((f"adapter:{item.adapter_id}", item.evaluator) for item in self.adapters),
        ]
        if cancellation is not None:
            extension_targets.append(("cancellation", cancellation))
        self._extension_implementation_evidence = tuple(
            _implementation_source_evidence(label, target) for label, target in extension_targets
        )
        self._commands = 0
        self._command_provenance: list[CommandProvenance] = []
        self._tool_versions: tuple[ToolVersion, ...] = ()
        self._identity_resolved = False

    def _is_cancelled(self) -> bool:
        if self.cancellation is None:
            return False
        try:
            return self.cancellation.cancelled()
        except Exception:
            return True

    @staticmethod
    def _cancelled_finding(evidence_ref: str) -> Finding:
        return _finding(
            "SCAN.CANCELLED",
            "repository_topology",
            "The scan was cancelled before a complete repository artifact was finalized.",
            (evidence_ref,),
            blocking=True,
        )

    def _run(
        self, args: tuple[str, ...], root: Path, *, essential: bool = False
    ) -> CommandResult | None:
        if self._commands >= self.config.max_commands:
            if essential:
                raise RepositoryIntelligenceError("read-only Git command budget was exhausted")
            return None
        self._commands += 1
        try:
            if isinstance(self.runner, SubprocessCommandRunner):
                result = self.runner.run(
                    args,
                    root,
                    self.config.command_timeout_seconds,
                    cancellation=self.cancellation,
                )
            else:
                result = self.runner.run(args, root, self.config.command_timeout_seconds)
        except (FileNotFoundError, OSError) as exc:
            raise RepositoryIntelligenceError("read-only Git command is unavailable") from exc
        self._command_provenance.append(
            CommandProvenance(
                args=args,
                tool_identity=self.runner.identity,
                exit_status=result.returncode,
                timed_out=result.timed_out,
            )
        )
        if result.timed_out:
            raise RepositoryIntelligenceError("read-only Git command timed out")
        if result.returncode == 126:
            raise _ScanCancelledError(
                "repository:identity" if not self._identity_resolved else "repository:scan"
            )
        if result.returncode != 0:
            if essential:
                raise RepositoryIntelligenceError("path is not an accessible Git repository")
            raise RepositoryIntelligenceError("an immutable Git object could not be read")
        return result

    def _list_tree(self, args: tuple[str, ...], root: Path) -> TreeListingResult | None:
        if self._commands >= self.config.max_commands:
            return None
        self._commands += 1
        try:
            if isinstance(self.runner, SubprocessCommandRunner):
                listing = self.runner.list_tree(
                    args,
                    root,
                    self.config.command_timeout_seconds,
                    max_records=self.config.max_files + 1,
                    max_output_bytes=self.config.max_tree_output_bytes,
                    cancellation=self.cancellation,
                )
            else:
                listing = TreeListingResult(
                    result=self.runner.run(args, root, self.config.command_timeout_seconds),
                    record_limit_exceeded=False,
                    byte_limit_exceeded=False,
                    cancelled=False,
                )
        except (FileNotFoundError, OSError) as exc:
            raise RepositoryIntelligenceError("read-only Git command is unavailable") from exc
        result = listing.result
        self._command_provenance.append(
            CommandProvenance(
                args=args,
                tool_identity=self.runner.identity,
                exit_status=result.returncode,
                timed_out=result.timed_out,
            )
        )
        if result.timed_out:
            raise RepositoryIntelligenceError("bounded tracked-tree enumeration timed out")
        if listing.cancelled:
            return listing
        if result.returncode != 0 and not (
            listing.record_limit_exceeded or listing.byte_limit_exceeded
        ):
            raise RepositoryIntelligenceError("the immutable Git tree could not be read")
        return listing

    def _validate_config(self) -> None:
        if not self.config.repository.strip():
            raise RepositoryIntelligenceError("repository identity is required")
        positive = (
            self.config.max_files,
            self.config.max_directories,
            self.config.max_total_bytes,
            self.config.max_file_bytes,
            self.config.max_tree_output_bytes,
            self.config.max_commands,
            self.config.command_timeout_seconds,
            self.config.max_path_depth,
        )
        if any(value <= 0 for value in positive):
            raise RepositoryIntelligenceError("scan budgets must be positive")
        for path in self.config.include_paths:
            if not _safe_relative_path(path):
                raise RepositorySecurityError(
                    "configured scan paths must be contained in the repository"
                )

    def _collect_tool_versions(self, root: Path) -> tuple[ToolVersion, ...]:
        try:
            git_result = self._run(("git", "version"), root)
            if git_result is None:
                raise _ScanCommandBudgetError(
                    "Git version could not be observed within the command budget"
                )
            git_version = _text(git_result.stdout).strip()
            canonicalizer_version = importlib.metadata.version("rfc8785")
        except (
            FileNotFoundError,
            OSError,
            UnicodeDecodeError,
            importlib.metadata.PackageNotFoundError,
        ) as exc:
            raise RepositoryIntelligenceError("scanner tool versions are unavailable") from exc
        if not git_version.startswith("git version "):
            raise RepositoryIntelligenceError("Git version output is malformed")
        return tuple(
            sorted(
                (
                    ToolVersion("git", git_version.removeprefix("git version ")),
                    ToolVersion("python", platform.python_version()),
                    ToolVersion("pyyaml", str(yaml.__version__)),
                    ToolVersion("rfc8785", canonicalizer_version),
                ),
                key=lambda item: item.tool,
            )
        )

    def _command_budget_snapshot(
        self,
        commit_sha: str,
        tree_sha: str,
        git_object_format: str,
        config_digest: str,
        adapter_digest: str,
    ) -> RepositorySnapshot:
        finding = _finding(
            "BUDGET.COMMAND_COUNT",
            "repository_topology",
            "The command budget ended before required scanner tooling could be observed.",
            ("repository:scan-budget",),
            blocking=True,
        )
        return self._finalize(
            commit_sha=commit_sha,
            tree_sha=tree_sha,
            git_object_format=git_object_format,
            config_digest=config_digest,
            adapter_digest=adapter_digest,
            inventory_items={},
            findings=[finding],
            boundaries=[],
            statuses=dict.fromkeys(AUDIT_CATEGORIES, "BLOCKED"),
            reasons=dict.fromkeys(AUDIT_CATEGORIES, "scan command budget exhausted"),
            disposition="BLOCKED",
        )

    def _cancelled_snapshot(
        self,
        root: Path,
        commit_sha: str,
        tree_sha: str,
        git_object_format: str,
        config_digest: str,
        adapter_digest: str,
    ) -> RepositorySnapshot:
        finding = _finding(
            "SCAN.CANCELLED",
            "repository_topology",
            "The scan was cancelled before repository content was read.",
            ("repository:scan",),
            blocking=True,
        )
        return self._finalize(
            commit_sha=commit_sha,
            tree_sha=tree_sha,
            git_object_format=git_object_format,
            config_digest=config_digest,
            adapter_digest=adapter_digest,
            inventory_items={},
            findings=[finding],
            boundaries=[],
            statuses=dict.fromkeys(AUDIT_CATEGORIES, "BLOCKED"),
            reasons=dict.fromkeys(AUDIT_CATEGORIES, "scan cancelled"),
            disposition="BLOCKED",
        )

    def _resolve_identity(self, requested: Path) -> tuple[Path, str, str, str]:
        root_result = self._run(("git", "rev-parse", "--show-toplevel"), requested, essential=True)
        assert root_result is not None
        try:
            root = Path(_text(root_result.stdout).strip()).resolve(strict=True)
        except (UnicodeDecodeError, OSError) as exc:
            raise RepositoryIntelligenceError("Git repository root is malformed") from exc
        if root != requested.resolve() and root not in requested.resolve().parents:
            raise RepositorySecurityError(
                "resolved Git repository root is outside the requested path"
            )
        identity_result = self._run(
            (
                "git",
                "rev-parse",
                "--show-object-format",
                "--verify",
                "--end-of-options",
                f"{self._requested_commit}^{{commit}}",
            ),
            root,
            essential=True,
        )
        assert identity_result is not None
        try:
            object_format, commit_sha = _text(identity_result.stdout).splitlines()
        except UnicodeDecodeError as exc:
            raise RepositoryIntelligenceError("Git repository identity is malformed") from exc
        except ValueError as exc:
            raise RepositoryIntelligenceError("Git repository identity is malformed") from exc
        if object_format not in _OBJECT_FORMAT_LENGTH:
            raise RepositoryIntelligenceError(
                f"Git object format {object_format!r} is explicitly unsupported"
            )
        if not _valid_object_id(commit_sha, object_format):
            raise RepositoryIntelligenceError("Git commit identity is malformed")
        tree_result = self._run(
            (
                "git",
                "rev-parse",
                "--verify",
                "--end-of-options",
                f"{commit_sha}^{{tree}}",
            ),
            root,
        )
        if tree_result is None:
            return root, commit_sha, "0" * _OBJECT_FORMAT_LENGTH[object_format], object_format
        try:
            tree_sha = _text(tree_result.stdout).strip()
        except UnicodeDecodeError as exc:
            raise RepositoryIntelligenceError("Git tree identity is malformed") from exc
        if not _valid_object_id(tree_sha, object_format):
            raise RepositoryIntelligenceError("Git tree identity is malformed")
        return root, commit_sha, tree_sha, object_format

    def _list_files(
        self, root: Path, tree_sha: str, object_format: str
    ) -> tuple[list[TrackedFile], list[Finding], str, str]:
        findings: list[Finding] = []
        tracked_tree_digest = canonical_digest(
            {"git_object_format": object_format, "tree_sha": tree_sha}
        )
        if tree_sha == "0" * _OBJECT_FORMAT_LENGTH[object_format]:
            findings.append(
                _finding(
                    "BUDGET.COMMAND_COUNT",
                    "repository_topology",
                    "The command budget ended before the tracked tree could be enumerated.",
                    ("repository:scan-budget",),
                )
            )
            return [], findings, tracked_tree_digest, canonical_digest([])
        bounded_listing = self._list_tree(
            ("git", "ls-tree", "-r", "-z", "-l", "--full-tree", tree_sha), root
        )
        if bounded_listing is None:
            findings.append(
                _finding(
                    "BUDGET.COMMAND_COUNT",
                    "repository_topology",
                    "The command budget ended before the tracked tree could be enumerated.",
                    ("repository:scan-budget",),
                )
            )
            return [], findings, tracked_tree_digest, canonical_digest([])
        listing = bounded_listing.result
        if bounded_listing.cancelled:
            findings.append(
                _finding(
                    "SCAN.CANCELLED",
                    "repository_topology",
                    "The scan was cancelled during bounded tracked-tree enumeration.",
                    ("repository:tracked-tree",),
                    blocking=True,
                )
            )
        if bounded_listing.byte_limit_exceeded:
            findings.append(
                _finding(
                    "BUDGET.TREE_OUTPUT_BYTES",
                    "repository_topology",
                    "Tracked-tree enumeration exceeded its byte budget; results are explicitly "
                    "partial.",
                    ("repository:tracked-tree",),
                )
            )
        raw = listing.stdout if isinstance(listing.stdout, bytes) else listing.stdout.encode()
        entries: list[tuple[str, str, str, str, int]] = []
        for record in raw.split(b"\0"):
            if not record:
                continue
            try:
                metadata, raw_path = record.split(b"\t", 1)
                mode, object_type, object_id, raw_size = metadata.decode("ascii").split()
                path = raw_path.decode("utf-8")
                size = int(raw_size) if raw_size != "-" else 0
            except (ValueError, UnicodeDecodeError) as exc:
                raise RepositoryIntelligenceError("tracked-tree output is malformed") from exc
            if object_type not in {"blob", "commit"} or not _valid_object_id(
                object_id, object_format
            ):
                raise RepositoryIntelligenceError("tracked-tree output is malformed")
            if object_type == "commit" and mode != "160000":
                raise RepositoryIntelligenceError("tracked-tree output is malformed")
            if not _safe_relative_path(path):
                raise RepositoryIntelligenceError("tracked-tree output is malformed")
            if self.config.include_paths and not any(
                path == prefix or path.startswith(prefix.rstrip("/") + "/")
                for prefix in self.config.include_paths
            ):
                continue
            entries.append((mode, object_type, object_id, path, size))
        entries.sort(key=lambda item: item[3])
        if bounded_listing.record_limit_exceeded or len(entries) > self.config.max_files:
            findings.append(
                _finding(
                    "BUDGET.FILE_COUNT",
                    "repository_topology",
                    "The tracked file-count budget was exceeded; results are explicitly partial.",
                    ("repository:tracked-tree",),
                )
            )
            entries = entries[: self.config.max_files]
        directories = sorted(
            {
                "/".join(PurePosixPath(path).parts[:depth])
                for _, _, _, path, _ in entries
                for depth in range(1, len(PurePosixPath(path).parts))
            }
        )
        if len(directories) > self.config.max_directories:
            allowed_directories = set(directories[: self.config.max_directories])
            findings.append(
                _finding(
                    "BUDGET.DIRECTORY_COUNT",
                    "repository_topology",
                    "The tracked directory-count budget was exceeded; results are explicitly "
                    "partial.",
                    ("repository:tracked-tree",),
                )
            )
            entries = [
                entry
                for entry in entries
                if all(
                    "/".join(PurePosixPath(entry[3]).parts[:depth]) in allowed_directories
                    for depth in range(1, len(PurePosixPath(entry[3]).parts))
                )
            ]
        files: list[TrackedFile] = []
        total = 0
        total_exhausted = False
        for mode, object_type, object_id, path, size in entries:
            if self._is_cancelled():
                findings.append(
                    _finding(
                        "SCAN.CANCELLED",
                        "repository_topology",
                        "The scan was cancelled before every tracked blob was inspected.",
                        (path,),
                        blocking=True,
                    )
                )
                break
            if len(PurePosixPath(path).parts) > self.config.max_path_depth:
                findings.append(
                    _finding(
                        "BUDGET.PATH_DEPTH",
                        "repository_topology",
                        "A tracked path exceeds the configured traversal depth.",
                        (path,),
                    )
                )
                continue
            if total + size > self.config.max_total_bytes:
                if not total_exhausted:
                    findings.append(
                        _finding(
                            "BUDGET.TOTAL_BYTES",
                            "repository_topology",
                            "The aggregate byte budget was exceeded; results are explicitly "
                            "partial.",
                            (path,),
                        )
                    )
                    total_exhausted = True
                continue
            total += size
            if object_type == "commit":
                files.append(
                    TrackedFile(
                        path=path,
                        mode=mode,
                        object_id=object_id,
                        digest=f"git-object:{object_id}",
                        content=None,
                        binary=False,
                    )
                )
                continue
            oversized = size > self.config.max_file_bytes
            if oversized:
                findings.append(
                    _finding(
                        "BUDGET.FILE_BYTES",
                        "repository_topology",
                        "A tracked file exceeds the per-file byte budget.",
                        (path,),
                    )
                )
                files.append(
                    TrackedFile(
                        path=path,
                        mode=mode,
                        object_id=object_id,
                        digest=f"git-blob:{object_id}",
                        content=None,
                        binary=False,
                        oversized=True,
                    )
                )
                continue
            result = self._run(("git", "cat-file", "blob", object_id), root)
            if result is None:
                findings.append(
                    _finding(
                        "BUDGET.COMMAND_COUNT",
                        "repository_topology",
                        "The command budget ended before every tracked blob could be inspected.",
                        (path,),
                    )
                )
                break
            content = result.stdout if isinstance(result.stdout, bytes) else result.stdout.encode()
            files.append(
                TrackedFile(
                    path=path,
                    mode=mode,
                    object_id=object_id,
                    digest=_sha256(content),
                    content=content,
                    binary=b"\0" in content,
                )
            )
        scanned_content_digest = canonical_digest(
            [
                {
                    "path": file.path,
                    "mode": file.mode,
                    "object_id": file.object_id,
                    "file_digest": file.digest,
                    "oversized": file.oversized,
                }
                for file in files
            ]
        )
        return files, findings, tracked_tree_digest, scanned_content_digest

    def _apply_adapters(
        self, files: tuple[TrackedFile, ...]
    ) -> tuple[dict[str, list[EvidenceItem]], list[Finding], list[BoundaryCandidate], set[str]]:
        inventory: dict[str, list[EvidenceItem]] = {name: [] for name in AUDIT_CATEGORIES}
        findings: list[Finding] = []
        boundaries: list[BoundaryCandidate] = []
        supported: set[str] = set()
        context = AdapterContext(files=files)
        for adapter in self.adapters:
            if self._is_cancelled():
                findings.append(
                    _finding(
                        "SCAN.CANCELLED",
                        "repository_topology",
                        "The scan was cancelled during adapter evaluation.",
                        (f"adapter:{adapter.adapter_id}",),
                        blocking=True,
                    )
                )
                break
            supported.update(adapter.supported_categories)
            matched_context = AdapterContext(files=context.matching(adapter.file_patterns))
            status, result = self._run_adapter_bounded(
                adapter,
                matched_context,
            )
            if status == "CANCELLED":
                findings.append(self._cancelled_finding(f"adapter:{adapter.adapter_id}"))
                break
            if status != "RESULT" or result is None:
                findings.append(
                    _finding(
                        "ADAPTER.FAILURE",
                        adapter.supported_categories[0],
                        f"Adapter {adapter.adapter_id} failed; its categories remain visibly "
                        "partial.",
                        (f"adapter:{adapter.adapter_id}",),
                        blocking=True,
                    )
                )
                continue
            if not self._adapter_result_is_valid(adapter, matched_context, result):
                findings.append(
                    _finding(
                        "ADAPTER.INVALID_EVIDENCE",
                        adapter.supported_categories[0],
                        f"Adapter {adapter.adapter_id} emitted evidence that was not bound to "
                        "its declaration and matched immutable files.",
                        (f"adapter:{adapter.adapter_id}",),
                        blocking=True,
                    )
                )
                continue
            if self._is_cancelled():
                findings.append(self._cancelled_finding(f"adapter:{adapter.adapter_id}"))
                break
            for category, item in result.items:
                if category in inventory:
                    inventory[category].append(item)
            findings.extend(result.findings)
            boundaries.extend(result.boundaries)
        files_by_path = {item.path: item for item in files}
        inventory["architecture_boundaries"].extend(
            EvidenceItem(
                kind=f"BOUNDARY_{item.kind}",
                path=item.evidence_paths[0],
                file_digest=files_by_path[item.evidence_paths[0]].digest,
                detector_id=item.detector_id,
                detector_version=item.detector_version,
                confidence=item.confidence,
            )
            for item in boundaries
        )
        return inventory, findings, boundaries, supported

    @staticmethod
    def _adapter_result_is_valid(
        adapter: RepositoryAdapter,
        context: AdapterContext,
        result: AdapterResult,
    ) -> bool:
        files = {item.path: item for item in context.files}
        allowed_categories = set(adapter.supported_categories)
        allowed_confidence = {"HIGH", "MEDIUM", "LOW"}
        allowed_severity = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}

        for category, item in result.items:
            source = files.get(item.path)
            if (
                category not in allowed_categories
                or source is None
                or item.file_digest != source.digest
                or item.detector_id != adapter.adapter_id
                or item.detector_version != adapter.detector_version
                or item.confidence not in allowed_confidence
                or item.redaction_status != "SANITIZED"
                or not item.kind
                or not item.location
            ):
                return False
        for finding in result.findings:
            if (
                finding.category not in allowed_categories
                or finding.detector_id != adapter.adapter_id
                or finding.detector_version != adapter.detector_version
                or finding.confidence not in allowed_confidence
                or finding.severity not in allowed_severity
                or not finding.code
                or not finding.explanation
                or not finding.evidence_refs
                or not all(
                    reference == "repository:tracked-tree" or reference in files
                    for reference in finding.evidence_refs
                )
            ):
                return False
        if result.boundaries and "architecture_boundaries" not in allowed_categories:
            return False
        for boundary in result.boundaries:
            if (
                not boundary.kind
                or not boundary.name
                or not boundary.evidence_paths
                or not all(path in files for path in boundary.evidence_paths)
                or boundary.detector_id != adapter.adapter_id
                or boundary.detector_version != adapter.detector_version
                or boundary.confidence not in allowed_confidence
            ):
                return False
        return True

    def _run_adapter_bounded(
        self, adapter: RepositoryAdapter, context: AdapterContext
    ) -> tuple[str, AdapterResult | None]:
        if not hasattr(os, "fork") or not hasattr(os, "setsid"):
            return "ERROR", None
        process_context = multiprocessing.get_context("fork")
        receiver, sender = process_context.Pipe(duplex=False)
        process = process_context.Process(
            target=_adapter_worker,
            args=(sender, adapter, context),
            daemon=True,
            name=f"pmpe-readonly-adapter-{adapter.adapter_id}",
        )
        try:
            process.start()
        except (OSError, RuntimeError):
            receiver.close()
            sender.close()
            return "ERROR", None
        sender.close()
        deadline = time.monotonic() + self.config.command_timeout_seconds
        try:
            while True:
                if self._is_cancelled():
                    return "CANCELLED", None
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return "ERROR", None
                if receiver.poll(min(remaining, 0.05)):
                    try:
                        payload = receiver.recv_bytes(self.config.max_tree_output_bytes)
                        decoded = json.loads(payload)
                    except (EOFError, OSError, UnicodeDecodeError, ValueError, TypeError):
                        return "ERROR", None
                    if not isinstance(decoded, dict) or decoded.get("status") != "RESULT":
                        return "ERROR", None
                    try:
                        raw_result = decoded["result"]
                        result = AdapterResult(
                            items=tuple(
                                (str(category), EvidenceItem(**item))
                                for category, item in raw_result["items"]
                            ),
                            findings=tuple(
                                Finding(
                                    **{
                                        **item,
                                        "evidence_refs": tuple(item["evidence_refs"]),
                                    }
                                )
                                for item in raw_result["findings"]
                            ),
                            boundaries=tuple(
                                BoundaryCandidate(
                                    **{
                                        **item,
                                        "evidence_paths": tuple(item["evidence_paths"]),
                                    }
                                )
                                for item in raw_result["boundaries"]
                            ),
                        )
                    except (KeyError, TypeError, ValueError):
                        return "ERROR", None
                    return "RESULT", result
        finally:
            receiver.close()
            _stop_isolated_process(process)

    def _cross_cutting_findings(
        self, files: tuple[TrackedFile, ...], inventory: dict[str, list[EvidenceItem]]
    ) -> list[Finding]:
        findings: list[Finding] = [
            _finding(
                "ARCHITECTURE.HISTORY_COUPLING_UNSUPPORTED",
                "architecture_boundaries",
                "High-change and temporal-coupling analysis is unsupported by an exact-tree "
                "snapshot without governed history inputs; no hotspot was inferred.",
                ("repository:exact-tree",),
                severity="MEDIUM",
            )
        ]
        evidenced_paths = {
            category: {item.path for item in category_items}
            for category, category_items in inventory.items()
        }
        unsupported_relevant: dict[str, list[str]] = {
            "apis_data": [],
            "security_privacy": [],
            "observability_operations": [],
        }
        for file in files:
            lowered = file.path.lower()
            name = PurePosixPath(lowered).name
            suffix = PurePosixPath(lowered).suffix
            if file.binary:
                continue
            if (
                suffix == ".sql"
                or (
                    suffix in {".json", ".yaml", ".yml"}
                    and any(token in name for token in ("schema", "data-model", "data_model"))
                )
            ) and file.path not in evidenced_paths["apis_data"]:
                unsupported_relevant["apis_data"].append(file.path)
            if (
                any(
                    token in lowered
                    for token in ("privacy", "data-retention", "data_retention", "gdpr", "pii")
                )
                and file.path not in evidenced_paths["security_privacy"]
            ):
                unsupported_relevant["security_privacy"].append(file.path)
            if (
                any(
                    token in lowered
                    for token in ("prometheus", "grafana", "opentelemetry", "otel", "telemetry")
                )
                and file.path not in evidenced_paths["observability_operations"]
            ):
                unsupported_relevant["observability_operations"].append(file.path)
        for category, paths in unsupported_relevant.items():
            if paths:
                findings.append(
                    _finding(
                        "AUDIT.UNSUPPORTED_SUBCATEGORY",
                        category,
                        "Tracked content appears relevant to a required audit subcategory but "
                        "no versioned adapter emitted evidence; the category is blocked rather "
                        "than reported as not observed.",
                        tuple(sorted(set(paths))),
                        blocking=True,
                    )
                )
        expected_test_kinds = {
            "unit": "UNIT_TEST_FILE_SIGNAL",
            "integration": "INTEGRATION_TEST_FILE_SIGNAL",
            "e2e": "E2E_TEST_FILE_SIGNAL",
            "contract": "CONTRACT_TEST_FILE_SIGNAL",
            "security": "SECURITY_TEST_FILE_SIGNAL",
            "performance": "PERFORMANCE_TEST_FILE_SIGNAL",
            "mutation": "MUTATION_TEST_FILE_SIGNAL",
        }
        observed_test_kinds = {item.kind for item in inventory["tests_quality"]}
        missing_test_categories = tuple(
            name for name, kind in expected_test_kinds.items() if kind not in observed_test_kinds
        )
        if missing_test_categories:
            findings.append(
                _finding(
                    "QUALITY.TEST_CATEGORY_ABSENT",
                    "tests_quality",
                    "No deterministic tracked configuration or conventional file signal was "
                    f"observed for these test categories: {', '.join(missing_test_categories)}.",
                    ("repository:tracked-tree",),
                    severity="MEDIUM",
                )
            )
        absence_rules = (
            (
                "security_privacy",
                "SECURITY.CONTROL_EVIDENCE_ABSENT",
                "No tracked security-control configuration was observed.",
            ),
            (
                "observability_operations",
                "OPERATIONS.OBSERVABILITY_EVIDENCE_ABSENT",
                "No tracked logs, metrics, traces, alerts, SLO, or health-check evidence "
                "was observed.",
            ),
            (
                "documentation_governance",
                "GOVERNANCE.DOCUMENTATION_EVIDENCE_ABSENT",
                "No tracked repository governance document was observed.",
            ),
        )
        for category, code, explanation in absence_rules:
            if not any(item.confidence == "HIGH" for item in inventory[category]):
                findings.append(
                    _finding(
                        code,
                        "debt_risk",
                        explanation,
                        ("repository:tracked-tree",),
                        severity="MEDIUM",
                    )
                )
        if not any(
            item.kind == "ROLLBACK_MECHANISM" and item.confidence == "HIGH"
            for item in inventory["delivery_environments"]
        ):
            findings.append(
                _finding(
                    "DELIVERY.ROLLBACK_EVIDENCE_ABSENT",
                    "debt_risk",
                    "No tracked rollback mechanism was observed; this is an evidence gap, "
                    "not proof that operational rollback is impossible.",
                    ("category:delivery_environments",),
                    severity="MEDIUM",
                )
            )
        python_versions: dict[str, str] = {}
        for file in files:
            if file.content is None or file.binary:
                continue
            if file.path == ".python-version":
                python_versions[file.path] = file.content.decode("utf-8", errors="ignore").strip()
            if "dockerfile" in PurePosixPath(file.path).name.lower():
                match = re.search(rb"\bpython:([0-9]+(?:\.[0-9]+)?)", file.content)
                if match:
                    python_versions[file.path] = match.group(1).decode()
        if len(set(python_versions.values())) > 1:
            findings.append(
                _finding(
                    "RUNTIME.VERSION_DRIFT_SIGNAL",
                    "debt_risk",
                    "Different tracked Python runtime declarations were observed; this is a "
                    "drift signal.",
                    tuple(sorted(python_versions)),
                    severity="MEDIUM",
                )
            )
        known_suffixes = {
            ".md",
            ".txt",
            ".py",
            ".pyi",
            ".json",
            ".jsonl",
            ".yaml",
            ".yml",
            ".toml",
            ".lock",
            ".js",
            ".mjs",
            ".cjs",
            ".jsx",
            ".ts",
            ".tsx",
            ".css",
            ".html",
            ".svg",
            ".sql",
            ".sh",
            ".ini",
            ".cfg",
            ".dockerignore",
            ".typed",
        }
        # A non-generic item from a sealed adapter proves that the file's role is
        # already understood.  Do not then contradict that evidence merely because
        # the file uses a domain-specific suffix (for example .proto, .graphql,
        # Dockerfile.dev, or .env.production).  Repository-topology's TRACKED_FILE
        # item is intentionally excluded because it says nothing about file type.
        classified_paths = {
            item.path
            for category, category_items in inventory.items()
            if category != "repository_topology"
            for item in category_items
        }
        unknown = [
            file.path
            for file in files
            if PurePosixPath(file.path).suffix
            and PurePosixPath(file.path).suffix.lower() not in known_suffixes
            and not file.binary
            and file.path not in classified_paths
        ]
        unsupported_source_suffixes = {
            ".sh",
            ".bash",
            ".zsh",
            ".rb",
            ".go",
            ".rs",
            ".java",
            ".kt",
            ".php",
            ".swift",
            ".c",
            ".cc",
            ".cpp",
            ".cs",
        }
        unsupported_sources = sorted(
            {
                *unknown,
                *(
                    file.path
                    for file in files
                    if PurePosixPath(file.path).suffix.lower() in unsupported_source_suffixes
                    and not file.binary
                ),
            }
        )
        if unsupported_sources:
            findings.append(
                _finding(
                    "STACK.UNSUPPORTED_FILE_TYPE",
                    "languages_build_ecosystems",
                    "A tracked file type has no deterministic stack adapter; no ecosystem was "
                    "inferred for it.",
                    tuple(unsupported_sources),
                    blocking=True,
                )
            )
        unsupported_manifest_names = {
            "BUILD",
            "BUILD.bazel",
            "CMakeLists.txt",
            "Cargo.toml",
            "Gemfile",
            "GNUmakefile",
            "Jenkinsfile",
            "MODULE.bazel",
            "Makefile",
            "Procfile",
            "Rakefile",
            "SConstruct",
            "Tiltfile",
            "Vagrantfile",
            "WORKSPACE",
            "WORKSPACE.bazel",
            "build.gradle",
            "go.mod",
            "justfile",
            "pom.xml",
        }
        unsupported_manifests = sorted(
            file.path
            for file in files
            if PurePosixPath(file.path).name in unsupported_manifest_names
        )
        if unsupported_manifests:
            findings.append(
                _finding(
                    "STACK.UNSUPPORTED_ECOSYSTEM",
                    "languages_build_ecosystems",
                    "A tracked ecosystem manifest has no versioned adapter; its stack was not "
                    "guessed.",
                    tuple(unsupported_manifests),
                    blocking=True,
                )
            )
        extensionless_programs = sorted(
            file.path
            for file in files
            if not PurePosixPath(file.path).suffix
            and PurePosixPath(file.path).name not in {*unsupported_manifest_names, "Dockerfile"}
            and (
                file.mode == "100755"
                or (file.content is not None and file.content.startswith(b"#!"))
            )
        )
        if extensionless_programs:
            findings.append(
                _finding(
                    "STACK.UNSUPPORTED_EXTENSIONLESS_PROGRAM",
                    "languages_build_ecosystems",
                    "Tracked extensionless executable or shebang content has no deterministic "
                    "stack adapter; it was not executed or guessed.",
                    tuple(extensionless_programs),
                    blocking=True,
                )
            )
        by_name: dict[str, list[str]] = {}
        for file in files:
            name = PurePosixPath(file.path).name
            if name.endswith((".schema.json", ".config.json", ".config.yaml", ".config.yml")):
                by_name.setdefault(name, []).append(file.path)
        for paths in sorted(by_name.values()):
            if len(paths) > 1:
                findings.append(
                    _finding(
                        "CONFIG.DUPLICATE_PATH_SIGNAL",
                        "debt_risk",
                        "The same configuration basename appears in multiple tracked locations; "
                        "this is a duplication signal, not proof of drift.",
                        tuple(sorted(paths)),
                        severity="MEDIUM",
                    )
                )
        for file in files:
            if not file.path.startswith(".github/workflows/") or not file.content:
                continue
            if re.search(
                rb"\bpip\s+install\s+(?:[^\n]*\s)?(?:ruff|mypy|bandit|build)\s*(?:\n|$)",
                file.content,
            ):
                findings.append(
                    _finding(
                        "TOOL.UNPINNED_INSTALL_SIGNAL",
                        "debt_risk",
                        "A CI tool install appears unbounded; exact resolver behavior may drift.",
                        (file.path,),
                        severity="MEDIUM",
                    )
                )
        for file in files:
            if file.mode == "120000" and _symlink_escapes(file.path, file.content):
                findings.append(
                    _finding(
                        "SECURITY.SYMLINK_ESCAPE",
                        "security_privacy",
                        "A tracked symlink resolves outside the repository root and was not "
                        "followed.",
                        (file.path,),
                        blocking=True,
                        severity="CRITICAL",
                    )
                )
        return findings

    def _finalize(
        self,
        *,
        commit_sha: str,
        tree_sha: str,
        git_object_format: str,
        config_digest: str,
        adapter_digest: str,
        inventory_items: dict[str, list[EvidenceItem]],
        findings: list[Finding],
        boundaries: list[BoundaryCandidate],
        statuses: dict[str, str],
        reasons: dict[str, str],
        disposition: str,
        tracked_tree_digest: str | None = None,
        scanned_content_digest: str | None = None,
    ) -> RepositorySnapshot:
        findings = list(findings)
        statuses = dict(statuses)
        reasons = dict(reasons)
        if self._is_cancelled() and not any(item.code == "SCAN.CANCELLED" for item in findings):
            findings.append(self._cancelled_finding("repository:finalization"))
            statuses.update(dict.fromkeys(AUDIT_CATEGORIES, "BLOCKED"))
            reasons.update(dict.fromkeys(AUDIT_CATEGORIES, "scan cancelled"))
            disposition = "BLOCKED"
        implementation_digest = _implementation_digest(self._extension_implementation_evidence)
        inventory = {
            name: InventoryCategory(
                status=statuses.get(name, "SUPPORTED"),
                items=tuple(
                    sorted(
                        inventory_items.get(name, []),
                        key=lambda item: (item.path, item.kind, item.detector_id),
                    )
                ),
                reason=reasons.get(name, ""),
            )
            for name in AUDIT_CATEGORIES
        }
        draft = RepositorySnapshot(
            repository=self.config.repository,
            commit_sha=commit_sha,
            tree_sha=tree_sha,
            git_object_format=git_object_format,
            default_branch=self.config.default_branch,
            default_branch_source="SCAN_CONFIGURATION_NOT_OBSERVED",
            scanner_version=SCANNER_VERSION,
            scan_configuration_digest=config_digest,
            adapter_set_digest=adapter_digest,
            implementation_digest=implementation_digest,
            tracked_tree_digest=tracked_tree_digest or canonical_digest([]),
            scanned_content_digest=scanned_content_digest or canonical_digest([]),
            scan_scope=("INCLUDED_PATHS" if self.config.include_paths else "FULL_REPOSITORY"),
            included_paths=tuple(sorted(self.config.include_paths)),
            tooling_digest=canonical_digest(
                {
                    "scanner_version": SCANNER_VERSION,
                    "adapter_set_digest": adapter_digest,
                    "implementation_digest": implementation_digest,
                    "command_runner": self.runner.identity,
                    "redactor_version": str(getattr(self.redactor, "version", "unknown")),
                    "tool_versions": [asdict(item) for item in self._tool_versions],
                }
            ),
            tool_versions=self._tool_versions,
            adapters=tuple(_metadata(adapter) for adapter in self.adapters),
            command_provenance=tuple(self._command_provenance),
            inventory=inventory,
            findings=tuple(
                sorted(findings, key=lambda item: (item.code, item.evidence_refs, item.detector_id))
            ),
            boundary_candidates=tuple(
                sorted(boundaries, key=lambda item: (item.kind, item.name, item.evidence_paths))
            ),
            unsupported_categories=tuple(
                name
                for name in AUDIT_CATEGORIES
                if statuses.get(name) in {"UNSUPPORTED", "BLOCKED"}
            ),
            disposition=disposition,
            redaction={
                "version": str(getattr(self.redactor, "version", "unknown")),
                "status": "SANITIZED_BEFORE_PERSISTENCE",
                "read_only_method": (
                    "allowlisted immutable Git object reads; project code not executed"
                ),
            },
            snapshot_digest="",
        )
        try:
            sanitized = cast(dict[str, Any], self.redactor.sanitize(draft.as_dict()))
        except (RedactionError, Exception) as exc:
            raise RepositorySecurityError(
                "evidence redaction failed; artifact was not created"
            ) from exc
        if self._is_cancelled() and not any(item.code == "SCAN.CANCELLED" for item in findings):
            return self._finalize(
                commit_sha=commit_sha,
                tree_sha=tree_sha,
                git_object_format=git_object_format,
                config_digest=config_digest,
                adapter_digest=adapter_digest,
                inventory_items=inventory_items,
                findings=[*findings, self._cancelled_finding("repository:finalization")],
                boundaries=boundaries,
                statuses=dict.fromkeys(AUDIT_CATEGORIES, "BLOCKED"),
                reasons=dict.fromkeys(AUDIT_CATEGORIES, "scan cancelled"),
                disposition="BLOCKED",
                tracked_tree_digest=tracked_tree_digest,
                scanned_content_digest=scanned_content_digest,
            )
        sanitized["snapshot_digest"] = canonical_digest(
            {key: value for key, value in sanitized.items() if key != "snapshot_digest"}
        )
        return _snapshot_from_dict(sanitized)

    def scan(self, repository_root: Path | str, *, commit: str = "HEAD") -> RepositorySnapshot:
        self._validate_config()
        self._commands = 0
        self._command_provenance = []
        self._identity_resolved = False
        self._requested_commit = commit
        requested = Path(repository_root).resolve()
        root, commit_sha, tree_sha, object_format = self._resolve_identity(requested)
        self._identity_resolved = True
        # Root/ref resolution establishes the immutable identity but is excluded from
        # commit-stable provenance because equivalent refs (HEAD versus the exact SHA)
        # must yield byte-equivalent snapshots. Remaining commands are SHA-bound.
        self._command_provenance = self._command_provenance[2:]
        adapter_digest = canonical_digest([asdict(_metadata(item)) for item in self.adapters])
        config_digest = canonical_digest(asdict(self.config))
        try:
            self._tool_versions = self._collect_tool_versions(root)
            if self._is_cancelled():
                raise _ScanCancelledError("scan cancelled after immutable identity resolution")
            files, budget_findings, tree_digest, scanned_digest = self._list_files(
                root, tree_sha, object_format
            )
            inventory, adapter_findings, boundaries, supported = self._apply_adapters(tuple(files))
        except _ScanCommandBudgetError:
            return self._command_budget_snapshot(
                commit_sha,
                tree_sha,
                object_format,
                config_digest,
                adapter_digest,
            )
        except _ScanCancelledError:
            return self._cancelled_snapshot(
                root, commit_sha, tree_sha, object_format, config_digest, adapter_digest
            )
        findings = budget_findings + adapter_findings
        if self.config.include_paths:
            findings.append(
                _finding(
                    "SCAN.SCOPED_PARTIAL",
                    "repository_topology",
                    "Only explicitly included paths were inspected; the artifact is not a "
                    "whole-repository inventory.",
                    tuple(sorted(self.config.include_paths)),
                    severity="MEDIUM",
                )
            )
        if not any(item.code == "SCAN.CANCELLED" for item in findings):
            findings.extend(self._cross_cutting_findings(tuple(files), inventory))
        statuses = {
            name: (
                "OBSERVED"
                if inventory[name]
                else "NOT_OBSERVED"
                if name in supported
                else "UNSUPPORTED"
            )
            for name in AUDIT_CATEGORIES
        }
        reasons = {
            name: "No versioned adapter supports this category."
            for name in AUDIT_CATEGORIES
            if name not in supported
        }
        statuses["active_divergent_work"] = "UNSUPPORTED"
        reasons["active_divergent_work"] = (
            "Mutable branch, worktree, PR, issue, and governance facts belong only in "
            "GovernanceObservation."
        )
        if any(item.code.startswith("STACK.UNSUPPORTED") for item in findings):
            statuses["languages_build_ecosystems"] = "UNSUPPORTED"
            reasons["languages_build_ecosystems"] = (
                "The tracked ecosystem has no deterministic adapter."
            )
        for finding in findings:
            if finding.code == "AUDIT.UNSUPPORTED_SUBCATEGORY":
                statuses[finding.category] = "BLOCKED"
                reasons[finding.category] = (
                    "Relevant tracked content has no deterministic subcategory adapter."
                )
        unsupported_required = any(
            status in {"UNSUPPORTED", "BLOCKED"} and name != "active_divergent_work"
            for name, status in statuses.items()
        )
        blocking = any(item.blocking for item in findings) or unsupported_required
        partial_codes = {
            "ADAPTER.FAILURE",
            "BUDGET.FILE_COUNT",
            "BUDGET.DIRECTORY_COUNT",
            "BUDGET.TOTAL_BYTES",
            "BUDGET.FILE_BYTES",
            "BUDGET.TREE_OUTPUT_BYTES",
            "BUDGET.PATH_DEPTH",
            "BUDGET.COMMAND_COUNT",
            "MANIFEST.MALFORMED",
            "WORKFLOW.MALFORMED",
            "SCAN.SCOPED_PARTIAL",
            "SCAN.CANCELLED",
        }
        partial = any(item.code in partial_codes for item in findings)
        if partial:
            for name in AUDIT_CATEGORIES:
                if name != "active_divergent_work" and statuses[name] not in {
                    "UNSUPPORTED",
                    "BLOCKED",
                }:
                    statuses[name] = "PARTIAL"
                    reasons[name] = "A bounded scan or adapter failure made this category partial."
        disposition = "BLOCKED" if blocking else "PARTIAL" if partial else "COMPLETE"
        return self._finalize(
            commit_sha=commit_sha,
            tree_sha=tree_sha,
            git_object_format=object_format,
            config_digest=config_digest,
            adapter_digest=adapter_digest,
            tracked_tree_digest=tree_digest,
            scanned_content_digest=scanned_digest,
            inventory_items=inventory,
            findings=findings,
            boundaries=boundaries,
            statuses=statuses,
            reasons=reasons,
            disposition=disposition,
        )


def scan_repository(
    repository_root: Path | str,
    *,
    commit: str = "HEAD",
    config: ScanConfig,
) -> RepositorySnapshot:
    return RepositoryScanner(config=config).scan(repository_root, commit=commit)
