"""Small fixed kernel for plan-bound red-test execution.

Compilation decides *what* argv to run.  This module only proves *where* and
*how* it ran: an exact Git commit is materialized without consulting the caller
worktree, the argv is executed without a shell in a bounded OS sandbox, and an
independent subject copy is re-hashed before keyed evidence is admitted.
"""

from __future__ import annotations

import hashlib
import io
import math
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
    max_memory_bytes: int = 1024 * 1024 * 1024
    max_processes: int = 128
    max_file_bytes: int = 64 * 1024 * 1024
    max_open_files: int = 256
    executable_path: str = "/usr/local/bin:/usr/bin:/bin"

    def __post_init__(self) -> None:
        path_entries = self.executable_path.split(":")
        if (
            not 0 < self.timeout_seconds <= 3600
            or not 0 < self.max_output_bytes <= 16 * 1024 * 1024
            or not 0 < self.max_archive_bytes <= 256 * 1024 * 1024
            or not 16 * 1024 * 1024 <= self.max_memory_bytes <= 8 * 1024 * 1024 * 1024
            or not 0 < self.max_processes <= 1024
            or not 0 < self.max_file_bytes <= 1024 * 1024 * 1024
            or not 16 <= self.max_open_files <= 4096
            or not path_entries
            or any(
                not entry.startswith("/")
                or any(part in {"", ".", ".."} for part in entry.split("/")[1:])
                for entry in path_entries
            )
            or "\0" in self.executable_path
        ):
            raise ExecutionError("execution policy exceeds its bounded domain")

    @property
    def digest(self) -> str:
        return canonical_digest(
            {
                "executable_path": self.executable_path,
                "max_archive_bytes": self.max_archive_bytes,
                "max_file_bytes": self.max_file_bytes,
                "max_memory_bytes": self.max_memory_bytes,
                "max_open_files": self.max_open_files,
                "max_output_bytes": self.max_output_bytes,
                "max_processes": self.max_processes,
                "timeout_seconds": self.timeout_seconds,
            }
        )


@dataclass(frozen=True)
class CommandOutcome:
    return_code: int
    stdout: bytes
    stderr: bytes
    isolation_status: bytes = b""
    resolved_executable: str = ""


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
    resolved_executable: str
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
    status_pipe: tuple[int, int] | None = None,
) -> CommandOutcome:
    status_read, status_write = status_pipe if status_pipe is not None else (None, None)
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
            pass_fds=(() if status_write is None else (status_write,)),
        )
    except FileNotFoundError as exc:
        if status_read is not None:
            os.close(status_read)
        if status_write is not None:
            os.close(status_write)
        raise ExecutableUnavailable(f"executable is unavailable: {argv[0]}") from exc
    if status_write is not None:
        os.close(status_write)
    assert process.stdout is not None
    assert process.stderr is not None
    os.set_blocking(process.stdout.fileno(), False)
    os.set_blocking(process.stderr.fileno(), False)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    streams: dict[str, bytearray] = {
        "stdout": bytearray(),
        "stderr": bytearray(),
        "status": bytearray(),
    }
    if status_read is not None:
        os.set_blocking(status_read, False)
        selector.register(status_read, selectors.EVENT_READ, "status")
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
                if len(streams["status"]) > 64 * 1024:
                    _kill_process_group(process)
                    raise ExecutionIsolationUnavailable("sandbox status exceeded its limit")
                if len(streams["stdout"]) + len(streams["stderr"]) > max_output_bytes:
                    _kill_process_group(process)
                    raise OutputLimitExceeded("bounded execution output exceeded its limit")
        try:
            return_code = process.wait(timeout=max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired as exc:
            _kill_process_group(process)
            raise ExecutionTimedOut("bounded execution timed out") from exc
        return CommandOutcome(
            return_code,
            bytes(streams["stdout"]),
            bytes(streams["stderr"]),
            bytes(streams["status"]),
        )
    finally:
        selector.close()
        if status_read is not None:
            with suppress(OSError):
                os.close(status_read)
        _kill_process_group(process)


class BubblewrapSandbox:
    """Linux namespace sandbox with only the disposable workspace writable."""

    identity = "bubblewrap-readonly-root-no-network-rlimit/2"

    def __init__(self, executable: str = "bwrap", limiter_executable: str = "prlimit") -> None:
        self.executable = executable
        self.limiter_executable = limiter_executable
        self._available: bool | None = None

    def _argv(
        self,
        workspace: Path,
        command: ExecutionCommand,
        policy: ExecutionPolicy,
        status_fd: int | None = None,
        executable: str | None = None,
    ) -> list[str]:
        argv = [
            executable or self.executable,
            "--die-with-parent",
            "--new-session",
            "--unshare-all",
            "--clearenv",
            "--ro-bind",
            "/",
            "/",
            "--dir",
            "/workspace",
            "--bind",
            str(workspace),
            "/workspace",
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
            "--chdir",
            "/workspace",
        ]
        if status_fd is not None:
            argv.extend(("--json-status-fd", str(status_fd)))
        argv.extend(("--", *command.argv))
        return argv

    def _resource_argv(
        self,
        *,
        limiter: str,
        sandbox: str,
        workspace: Path,
        command: ExecutionCommand,
        policy: ExecutionPolicy,
        status_fd: int,
    ) -> list[str]:
        return [
            limiter,
            f"--as={policy.max_memory_bytes}",
            f"--cpu={math.ceil(policy.timeout_seconds) + 1}",
            f"--fsize={policy.max_file_bytes}",
            f"--nofile={policy.max_open_files}",
            f"--nproc={policy.max_processes}",
            "--",
            *self._argv(
                workspace,
                command,
                policy,
                status_fd,
                executable=sandbox,
            ),
        ]

    @staticmethod
    def _host_path(workspace: Path, sandbox_path: PurePosixPath) -> Path | None:
        workspace_mount = PurePosixPath("/workspace")
        private_tmp = PurePosixPath("/tmp")
        try:
            relative = sandbox_path.relative_to(workspace_mount)
        except ValueError:
            try:
                sandbox_path.relative_to(private_tmp)
            except ValueError:
                return Path(str(sandbox_path))
            return None
        candidate = workspace.joinpath(*relative.parts).resolve()
        try:
            candidate.relative_to(workspace.resolve())
        except ValueError:
            return None
        return candidate

    @staticmethod
    def _canonical_sandbox_path(sandbox_path: PurePosixPath) -> PurePosixPath | None:
        aliases = (
            (PurePosixPath("/proc/self/cwd"), PurePosixPath("/workspace")),
            (PurePosixPath("/proc/self/root"), PurePosixPath("/")),
        )
        for alias, target in aliases:
            try:
                relative = sandbox_path.relative_to(alias)
            except ValueError:
                continue
            return target.joinpath(*relative.parts)
        try:
            sandbox_path.relative_to(PurePosixPath("/proc"))
        except ValueError:
            return sandbox_path
        return None

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        executable = shutil.which(self.executable, path=_GIT_ENV["PATH"])
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
            sandbox_executable = self._canonical_sandbox_path(PurePosixPath(command.argv[0]))
            executable = (
                self._host_path(workspace, sandbox_executable)
                if sandbox_executable is not None
                else None
            )
        elif "/" in command.argv[0]:
            executable = (workspace / requested).resolve()
            try:
                workspace_relative = executable.relative_to(workspace.resolve())
            except ValueError:
                executable = None
                sandbox_executable = None
            else:
                sandbox_executable = PurePosixPath("/workspace").joinpath(*workspace_relative.parts)
        else:
            executable = None
            sandbox_executable = None
            for entry in policy.executable_path.split(":"):
                candidate = self._canonical_sandbox_path(PurePosixPath(entry) / command.argv[0])
                if candidate is None:
                    continue
                host_candidate = self._host_path(workspace, candidate)
                if (
                    host_candidate is not None
                    and host_candidate.is_file()
                    and os.access(host_candidate, os.X_OK)
                ):
                    executable = host_candidate
                    sandbox_executable = candidate
                    break
        if (
            executable is None
            or sandbox_executable is None
            or not executable.is_file()
            or not os.access(executable, os.X_OK)
        ):
            raise ExecutableUnavailable(f"executable is unavailable: {command.argv[0]}")
        sandbox = shutil.which(self.executable, path=_GIT_ENV["PATH"])
        limiter = shutil.which(self.limiter_executable, path=_GIT_ENV["PATH"])
        if sandbox is None:
            raise ExecutionIsolationUnavailable("bubblewrap is unavailable")
        if limiter is None:
            raise ExecutionIsolationUnavailable("process resource limiter is unavailable")
        if not self.is_available():
            raise ExecutionIsolationUnavailable("bubblewrap could not establish isolation")
        status_pipe = os.pipe()
        outcome = _run_bounded_process(
            self._resource_argv(
                limiter=limiter,
                sandbox=sandbox,
                workspace=workspace,
                command=command,
                policy=policy,
                status_fd=status_pipe[1],
            ),
            cwd=workspace,
            environment=_GIT_ENV,
            timeout_seconds=policy.timeout_seconds,
            max_output_bytes=policy.max_output_bytes,
            status_pipe=status_pipe,
        )
        if not outcome.isolation_status:
            raise ExecutionIsolationUnavailable("bubblewrap could not establish isolation")
        return CommandOutcome(
            outcome.return_code,
            outcome.stdout,
            outcome.stderr,
            outcome.isolation_status,
            str(sandbox_executable),
        )


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
    deadline = time.monotonic() + policy.timeout_seconds

    def remaining_time(maximum: float) -> float:
        budget = deadline - time.monotonic()
        if budget <= 0:
            raise ExecutionTimedOut("exact-commit materialization timed out")
        return min(maximum, budget)

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
        timeout_seconds=remaining_time(30.0),
        max_output_bytes=4096,
    )
    resolved_identity = resolved.stdout.decode("ascii", "replace").strip()
    if resolved.return_code != 0 or resolved_identity != commit_sha:
        raise ExecutionError("commit does not resolve to the exact admitted identity")
    integrity = _run_bounded_process(
        [
            *base,
            "fsck",
            "--strict",
            "--no-reflogs",
            "--no-dangling",
            commit_sha,
        ],
        cwd=repository,
        environment=_GIT_ENV,
        timeout_seconds=remaining_time(120.0),
        max_output_bytes=min(policy.max_output_bytes, 1024 * 1024),
    )
    if integrity.return_code != 0:
        raise ExecutionError("reachable Git object integrity verification failed")
    listed = _run_bounded_process(
        [*base, "ls-tree", "-rz", "--full-tree", commit_sha],
        cwd=repository,
        environment=_GIT_ENV,
        timeout_seconds=remaining_time(60.0),
        max_output_bytes=min(policy.max_archive_bytes, 8 * 1024 * 1024),
    )
    if listed.return_code != 0:
        raise ExecutionError("exact commit tree could not be listed")
    records = [record for record in listed.stdout.split(b"\0") if record]
    if len(records) > _MAX_ARCHIVE_MEMBERS:
        raise ExecutionError("repository tree contains too many members")
    remaining_bytes = policy.max_archive_bytes
    archive_buffer = io.BytesIO()
    with tarfile.open(fileobj=archive_buffer, mode="w:") as archive:
        for record in records:
            try:
                header, raw_path = record.split(b"\t", 1)
                mode, object_type, object_id = header.decode("ascii").split(" ", 2)
                path = raw_path.decode("utf-8")
            except (UnicodeDecodeError, ValueError) as exc:
                raise ExecutionError("repository tree entry is malformed") from exc
            _safe_archive_path(path)
            if object_type != "blob" or mode not in {"100644", "100755"}:
                raise ExecutionError("repository tree contains an unsupported entry")
            blob = _run_bounded_process(
                [*base, "cat-file", "blob", object_id],
                cwd=repository,
                environment=_GIT_ENV,
                timeout_seconds=remaining_time(30.0),
                max_output_bytes=max(1, remaining_bytes),
            )
            if blob.return_code != 0 or len(blob.stdout) > remaining_bytes:
                raise ExecutionError("repository blob exceeds the snapshot bound")
            remaining_bytes -= len(blob.stdout)
            member = tarfile.TarInfo(path)
            member.size = len(blob.stdout)
            member.mode = 0o755 if mode == "100755" else 0o644
            member.mtime = 0
            archive.addfile(member, io.BytesIO(blob.stdout))
    remaining_time(policy.timeout_seconds)
    encoded = archive_buffer.getvalue()
    if len(encoded) > policy.max_archive_bytes:
        raise ExecutionError("repository snapshot exceeds its archive bound")
    return encoded


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
            resolved_executable = PurePosixPath(outcome.resolved_executable)
            if (
                not outcome.resolved_executable
                or not resolved_executable.is_absolute()
                or ".." in resolved_executable.parts
                or "\0" in outcome.resolved_executable
            ):
                raise ExecutionError("sandbox did not report a canonical executable identity")
            after = _snapshot_digest(subject)
            if before != after:
                raise ExecutionError("independent exact-commit subject changed during execution")
            evidence = {
                "command_digest": canonical_digest(list(command.argv)),
                "commit_sha": commit_sha,
                "isolation_policy": self.sandbox.identity,
                "plan_digest": plan_digest,
                "policy_digest": self.policy.digest,
                "resolved_executable": outcome.resolved_executable,
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
            resolved_executable=str(evidence["resolved_executable"]),
            execution_digest=execution_digest,
            receipt_bindings=bindings,
            receipt=receipt,
        )
