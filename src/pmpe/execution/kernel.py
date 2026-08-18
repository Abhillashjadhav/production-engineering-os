"""Small fixed kernel for plan-bound red-test execution.

Compilation decides *what* argv to run.  This module only proves *where* and
*how* it ran: an exact Git commit is materialized without consulting the caller
worktree, the argv is executed without a shell in a bounded OS sandbox, and an
independent subject copy is re-hashed before keyed evidence is admitted.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import selectors
import shutil
import signal
import subprocess
import tarfile
import tempfile
import time
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol, runtime_checkable

from pmpe.admission import AdmissionReceipt, FileArtifactAdmissionAuthority
from pmpe.contracts.canonical import canonical_digest

_COMMIT = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_MAX_ARGUMENTS = 128
_MAX_ARGUMENT_BYTES = 8192
_MAX_ARCHIVE_MEMBERS = 100_000
_GIT_ENV = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_NO_REPLACE_OBJECTS": "1",
    "LC_ALL": "C",
    "PATH": "/usr/local/bin:/usr/bin:/bin",
}


class ExecutionError(RuntimeError):
    pass


class ExecutableUnavailableError(ExecutionError):
    pass


class ExecutionTimedOutError(ExecutionError):
    pass


class OutputLimitExceededError(ExecutionError):
    pass


class ExecutionCleanupError(ExecutionError):
    pass


class ExecutionIsolationUnavailableError(ExecutionError):
    pass


ExecutableUnavailable = ExecutableUnavailableError
ExecutionTimedOut = ExecutionTimedOutError
OutputLimitExceeded = OutputLimitExceededError
ExecutionIsolationUnavailable = ExecutionIsolationUnavailableError


@dataclass(frozen=True)
class ExecutionCommand:
    argv: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            type(self.argv) is not tuple
            or not self.argv
            or len(self.argv) > _MAX_ARGUMENTS
            or any(
                type(argument) is not str
                or not argument
                or "\0" in argument
                or len(argument.encode("utf-8")) > _MAX_ARGUMENT_BYTES
                for argument in self.argv
            )
        ):
            raise ExecutionError("command must be a bounded non-empty argv tuple")


@dataclass(frozen=True)
class ExecutionPolicy:
    timeout_seconds: float = 300.0
    max_output_bytes: int = 1024 * 1024
    max_archive_bytes: int = 64 * 1024 * 1024
    executable_path: str = "/usr/local/bin:/usr/bin:/bin"

    def __post_init__(self) -> None:
        if (
            not 0 < self.timeout_seconds <= 3600
            or not 0 < self.max_output_bytes <= 16 * 1024 * 1024
            or not 0 < self.max_archive_bytes <= 256 * 1024 * 1024
            or not self.executable_path.startswith("/")
            or "\0" in self.executable_path
        ):
            raise ExecutionError("execution policy exceeds its bounded domain")

    @property
    def digest(self) -> str:
        return canonical_digest(
            {
                "executable_path": self.executable_path,
                "max_archive_bytes": self.max_archive_bytes,
                "max_output_bytes": self.max_output_bytes,
                "timeout_seconds": self.timeout_seconds,
            }
        )


@dataclass(frozen=True)
class CommandOutcome:
    return_code: int
    stdout: bytes
    stderr: bytes


@runtime_checkable
class SandboxRunner(Protocol):
    identity: str

    def run(
        self,
        workspace: Path,
        command: ExecutionCommand,
        policy: ExecutionPolicy,
    ) -> CommandOutcome: ...


@dataclass(frozen=True)
class ExecutionResult:
    commit_sha: str
    command: ExecutionCommand
    return_code: int
    stdout_digest: str
    stderr_digest: str
    subject_digest_before: str
    subject_digest_after: str
    isolation_policy: str
    execution_digest: str
    receipt_bindings: Mapping[str, str]
    receipt: AdmissionReceipt


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    if process.poll() is None:
        process.wait()


def _run_bounded_process(
    argv: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: float,
    max_output_bytes: int,
) -> CommandOutcome:
    try:
        process = subprocess.Popen(  # noqa: S603 - argv is explicit and shell remains disabled
            list(argv),
            cwd=cwd,
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            close_fds=True,
        )
    except FileNotFoundError as exc:
        raise ExecutableUnavailable(f"executable is unavailable: {argv[0]}") from exc
    assert process.stdout is not None
    assert process.stderr is not None
    os.set_blocking(process.stdout.fileno(), False)
    os.set_blocking(process.stderr.fileno(), False)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    streams: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}
    deadline = time.monotonic() + timeout_seconds
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _kill_process_group(process)
                raise ExecutionTimedOut("bounded execution timed out")
            events = selector.select(min(remaining, 0.1))
            if not events and process.poll() is not None:
                events = [(key, selectors.EVENT_READ) for key in selector.get_map().values()]
            for key, _mask in events:
                try:
                    chunk = os.read(key.fd, 16 * 1024)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                streams[str(key.data)].extend(chunk)
                if sum(len(value) for value in streams.values()) > max_output_bytes:
                    _kill_process_group(process)
                    raise OutputLimitExceeded("bounded execution output exceeded its limit")
        try:
            return_code = process.wait(timeout=max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired as exc:
            _kill_process_group(process)
            raise ExecutionTimedOut("bounded execution timed out") from exc
        return CommandOutcome(return_code, bytes(streams["stdout"]), bytes(streams["stderr"]))
    finally:
        selector.close()
        _kill_process_group(process)


class BubblewrapSandbox:
    """Linux namespace sandbox with only the disposable workspace writable."""

    identity = "bubblewrap-readonly-root-no-network/1"

    def __init__(self, executable: str = "bwrap") -> None:
        self.executable = executable
        self._available: bool | None = None

    def _argv(
        self,
        workspace: Path,
        command: ExecutionCommand,
        policy: ExecutionPolicy,
    ) -> list[str]:
        return [
            self.executable,
            "--die-with-parent",
            "--new-session",
            "--unshare-all",
            "--clearenv",
            "--ro-bind",
            "/",
            "/",
            "--dev",
            "/dev",
            "--proc",
            "/proc",
            "--tmpfs",
            "/tmp",
            "--dir",
            "/tmp/home",
            "--setenv",
            "HOME",
            "/tmp/home",
            "--setenv",
            "PATH",
            policy.executable_path,
            "--bind",
            str(workspace),
            str(workspace),
            "--chdir",
            str(workspace),
            "--",
            *command.argv,
        ]

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        executable = shutil.which(self.executable)
        if executable is None:
            self._available = False
            return False
        try:
            outcome = _run_bounded_process(
                [executable, "--ro-bind", "/", "/", "--", "/bin/true"],
                cwd=Path("/"),
                environment=_GIT_ENV,
                timeout_seconds=2.0,
                max_output_bytes=4096,
            )
        except ExecutionError:
            self._available = False
            return False
        self._available = outcome.return_code == 0
        return self._available

    def run(
        self,
        workspace: Path,
        command: ExecutionCommand,
        policy: ExecutionPolicy,
    ) -> CommandOutcome:
        requested = Path(command.argv[0])
        if requested.is_absolute():
            executable = requested
        elif "/" in command.argv[0]:
            executable = (workspace / requested).resolve()
            try:
                executable.relative_to(workspace.resolve())
            except ValueError:
                executable = Path("")
        else:
            located = shutil.which(command.argv[0], path=policy.executable_path)
            executable = Path(located) if located is not None else Path("")
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise ExecutableUnavailable(f"executable is unavailable: {command.argv[0]}")
        if shutil.which(self.executable) is None:
            raise ExecutionIsolationUnavailable("bubblewrap is unavailable")
        if not self.is_available():
            raise ExecutionIsolationUnavailable("bubblewrap could not establish isolation")
        outcome = _run_bounded_process(
            self._argv(workspace, command, policy),
            cwd=workspace,
            environment=_GIT_ENV,
            timeout_seconds=policy.timeout_seconds,
            max_output_bytes=policy.max_output_bytes,
        )
        if outcome.return_code != 0 and outcome.stderr.startswith(b"bwrap:"):
            raise ExecutionIsolationUnavailable("bubblewrap could not establish isolation")
        return outcome


def _safe_archive_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if not name or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ExecutionError("repository archive contains an unsafe path")
    return path


def _extract_snapshot(archive: bytes, destination: Path) -> None:
    destination.mkdir(mode=0o700)
    total_size = 0
    seen: set[PurePosixPath] = set()
    try:
        source = tarfile.open(fileobj=io.BytesIO(archive), mode="r:")  # noqa: SIM115
    except tarfile.TarError as exc:
        raise ExecutionError("exact-commit archive is malformed") from exc
    with source:
        members = source.getmembers()
        if len(members) > _MAX_ARCHIVE_MEMBERS:
            raise ExecutionError("repository archive contains too many members")
        for member in members:
            path = _safe_archive_path(member.name)
            if path in seen or not (member.isdir() or member.isfile()):
                raise ExecutionError("repository archive contains unsupported members")
            seen.add(path)
            total_size += member.size
            if total_size > len(archive) * 100 + 1024 * 1024:
                raise ExecutionError("repository archive expansion is unbounded")
        for member in sorted(
            members,
            key=lambda item: (len(PurePosixPath(item.name).parts), item.name),
        ):
            relative = _safe_archive_path(member.name)
            target = destination.joinpath(*relative.parts)
            if member.isdir():
                target.mkdir(mode=0o700, parents=True, exist_ok=True)
                continue
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            extracted = source.extractfile(member)
            if extracted is None:
                raise ExecutionError("repository archive member is unreadable")
            payload = extracted.read(member.size + 1)
            if len(payload) != member.size:
                raise ExecutionError("repository archive member size is inconsistent")
            target.write_bytes(payload)
            target.chmod(0o700 if member.mode & 0o111 else 0o600)


def _snapshot_digest(root: Path) -> str:
    entries: list[dict[str, str]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise ExecutionError("materialized subject contains an unsupported file")
        relative = path.relative_to(root).as_posix()
        if path.is_file():
            entries.append(
                {
                    "digest": _sha256(path.read_bytes()),
                    "kind": "file",
                    "path": relative,
                }
            )
        else:
            entries.append({"digest": "", "kind": "directory", "path": relative})
    return canonical_digest(entries)


def _exact_commit_archive(repository: Path, commit_sha: str, policy: ExecutionPolicy) -> bytes:
    if not _COMMIT.fullmatch(commit_sha):
        raise ExecutionError("commit identity is not a full canonical Git object ID")
    if not repository.is_dir():
        raise ExecutionError("repository is unavailable")
    base = [
        "git",
        "--no-replace-objects",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "protocol.file.allow=never",
    ]
    resolved = _run_bounded_process(
        [*base, "rev-parse", "--verify", f"{commit_sha}^{{commit}}"],
        cwd=repository,
        environment=_GIT_ENV,
        timeout_seconds=min(policy.timeout_seconds, 30.0),
        max_output_bytes=4096,
    )
    resolved_identity = resolved.stdout.decode("ascii", "replace").strip()
    if resolved.return_code != 0 or resolved_identity != commit_sha:
        raise ExecutionError("commit does not resolve to the exact admitted identity")
    archived = _run_bounded_process(
        [*base, "archive", "--format=tar", commit_sha],
        cwd=repository,
        environment=_GIT_ENV,
        timeout_seconds=min(policy.timeout_seconds, 60.0),
        max_output_bytes=policy.max_archive_bytes,
    )
    if archived.return_code != 0:
        raise ExecutionError("exact commit could not be archived")
    return archived.stdout


class IsolatedExecutionKernel:
    def __init__(
        self,
        *,
        authority: FileArtifactAdmissionAuthority,
        sandbox: SandboxRunner,
        policy: ExecutionPolicy | None = None,
    ) -> None:
        if not isinstance(sandbox, SandboxRunner):
            raise ExecutionError("sandbox runner does not satisfy the execution boundary")
        self.authority = authority
        self.sandbox = sandbox
        self.policy = policy or ExecutionPolicy()

    def execute(
        self,
        *,
        repository: Path,
        commit_sha: str,
        plan_digest: str,
        command: ExecutionCommand,
    ) -> ExecutionResult:
        if not _DIGEST.fullmatch(plan_digest):
            raise ExecutionError("plan digest is not canonical SHA-256")
        root = Path(tempfile.mkdtemp(prefix="pmpe-red-execution-"))
        evidence: dict[str, object] | None = None
        try:
            archive = _exact_commit_archive(Path(repository), commit_sha, self.policy)
            subject = root / "subject"
            workspace = root / "workspace"
            _extract_snapshot(archive, subject)
            shutil.copytree(subject, workspace)
            before = _snapshot_digest(subject)
            outcome = self.sandbox.run(workspace, command, self.policy)
            after = _snapshot_digest(subject)
            if before != after:
                raise ExecutionError("independent exact-commit subject changed during execution")
            evidence = {
                "command_digest": canonical_digest(list(command.argv)),
                "commit_sha": commit_sha,
                "isolation_policy": self.sandbox.identity,
                "plan_digest": plan_digest,
                "policy_digest": self.policy.digest,
                "return_code": outcome.return_code,
                "stderr_digest": _sha256(outcome.stderr),
                "stdout_digest": _sha256(outcome.stdout),
                "subject_digest": before,
            }
        finally:
            try:
                shutil.rmtree(root)
            except OSError as exc:
                raise ExecutionCleanupError("isolated execution cleanup failed") from exc
        if evidence is None:
            raise ExecutionError("execution produced no evidence")
        bindings = {key: str(value) for key, value in evidence.items()}
        execution_digest = canonical_digest(evidence)
        receipt = self.authority.admit(
            artifact_kind="RED_TEST_EXECUTION",
            artifact_digest=execution_digest,
            subject_bindings=bindings,
        )
        return ExecutionResult(
            commit_sha=commit_sha,
            command=command,
            return_code=int(str(evidence["return_code"])),
            stdout_digest=str(evidence["stdout_digest"]),
            stderr_digest=str(evidence["stderr_digest"]),
            subject_digest_before=str(evidence["subject_digest"]),
            subject_digest_after=str(evidence["subject_digest"]),
            isolation_policy=self.sandbox.identity,
            execution_digest=execution_digest,
            receipt_bindings=bindings,
            receipt=receipt,
        )
