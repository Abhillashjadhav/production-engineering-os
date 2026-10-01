"""Minimal contract-to-candidate-verification runtime with no deployment dependency."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import operator as comparison
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, NoReturn, Protocol

from pmpe.contracts.acceptance import (
    AcceptanceBuildPlan,
    CompiledCriterion,
    Operator,
    PropertyAssertion,
    compile_acceptance_plan,
)
from pmpe.contracts.authoring import verify_contract_approval
from pmpe.contracts.canonical import (
    CanonicalInputError,
    canonical_digest,
    canonical_json_bytes,
    strict_json_value_loads,
    strict_loads,
)
from pmpe.core_harness import CoreHarnessInvalidError, compile_required_harness
from pmpe.domain.errors import ContractViolation
from pmpe.evals.barebones_drift import observe_provider_behavior
from pmpe.evidence.ledger import EvidenceIntegrityError, EvidenceLedger
from pmpe.model_provider import (
    GENERIC_PROVIDER_ISOLATION,
    OFFLINE_PROVIDER_ISOLATION,
    ModelProvider,
)
from pmpe.release_gates import release_gate_results
from pmpe.task_tracker_harness import ACTION_TARGET, MEASURE_TARGET, REGISTRY_NAME, runner_source


class RunState(StrEnum):
    VALIDATED = "VALIDATED"
    BUILDING = "BUILDING"
    VERIFYING = "VERIFYING"
    RELEASE_READY = "RELEASE_READY"
    HALTED = "HALTED"
    STOPPED = "STOPPED"


@dataclass(frozen=True)
class TemplateTest:
    path: str
    node_id: str
    command: tuple[str, ...]


@dataclass(frozen=True)
class Template:
    version: str
    files: Mapping[str, str]
    actions: Mapping[str, str]
    context: Mapping[str, Any]
    proofs: Mapping[str, TemplateTest] = field(default_factory=dict)
    measures: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class BudgetCaps:
    max_attempts: int = 3
    max_model_calls: int = 8
    max_model_output_bytes: int = 1_000_000


@dataclass(frozen=True)
class Finding:
    code: str
    subject_id: str
    message: str
    files: tuple[str, ...] = ()


@dataclass(frozen=True)
class RunResult:
    run_id: str
    state: RunState
    cause: str
    attempts: int
    model_calls: int
    elapsed_ms: int
    evidence_path: Path
    annotation: Mapping[str, Any] = field(default_factory=dict)
    telemetry: Mapping[str, Any] = field(default_factory=dict)


class ContractInvalidError(ValueError):
    """The baseline proves that an admitted contract or template is not runnable."""


class TerminalPersistenceError(EvidenceIntegrityError):
    """The durable state of a terminal event cannot be confirmed."""


_SAFE_RELATIVE = re.compile(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\Z")
_MODULE_TARGET = re.compile(r"([A-Za-z_][A-Za-z0-9_.]*):([A-Za-z_][A-Za-z0-9_]*)\Z")
_CREDENTIAL = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{20,}"
)
_HIGH_RISK_CODE = re.compile(r"\b(?:eval|exec)\s*\(")
_ACTION_TIMEOUT_SECONDS = 10.0
_PYTEST_TIMEOUT_SECONDS = 30.0
_CANDIDATE_OUTPUT_LIMIT_BYTES = 1_000_000
_SANDBOX_PATH = "/usr/local/bin:/usr/bin:/bin"
_SANDBOX_RESERVED_ALIAS_ROOTS = tuple(
    Path(path) for path in ("/workspace", "/tmp", "/etc", "/dev", "/proc")
)
_PYTEST_RESULT_PREFIX = "__PMPE_PYTEST_RESULT__:"

_PROVIDER_ERROR_CODE = re.compile(r"[A-Z][A-Z0-9_]*\Z")
_MAX_SAFE_JSON_INTEGER = (1 << 53) - 1
_VERIFICATION_PROTOCOL = "external-json-response-v1"
_MAX_TOTAL_VERIFICATION_BYTES = 8_000_000
_MAX_TOTAL_VERIFICATION_SECONDS = 120.0
_TRUSTED_REGEX_TIMEOUT_SECONDS = _ACTION_TIMEOUT_SECONDS
_TRUSTED_REGEX_INPUT_LIMIT_BYTES = 1_000_000


def _classify_provider_error(error: RuntimeError) -> str:
    message = str(error)
    if _CREDENTIAL.search(message) or not _PROVIDER_ERROR_CODE.fullmatch(message):
        return "MODEL_PROVIDER_FAILED"
    return message


def _provider_behavior_payload(purpose: str, response: Mapping[str, Any]) -> dict[str, Any] | None:
    try:
        return asdict(observe_provider_behavior(purpose=purpose, response=response))
    except ValueError:
        return None


class CandidateSandbox(Protocol):
    """Trusted OS boundary used for every execution of generated code."""

    def run(
        self,
        workspace: Path,
        argv: Sequence[str],
        *,
        timeout_seconds: float,
        environment: Mapping[str, str],
    ) -> subprocess.CompletedProcess[str]: ...


class BubblewrapCandidateSandbox:
    """Run generated code with no network, host environment, or host filesystem view."""

    def __init__(self, executable: str = "bwrap", limiter: str = "prlimit") -> None:
        self.executable = executable
        self.limiter = limiter

    @staticmethod
    def _runtime_roots() -> tuple[Path, ...]:
        candidates = {
            Path("/usr"),
            Path("/bin"),
            Path("/sbin"),
            Path("/lib"),
            Path("/lib64"),
            Path(sys.base_prefix).resolve(),
            Path(sys.prefix).resolve(),
        }
        return tuple(sorted((item for item in candidates if item.exists()), key=str))

    @staticmethod
    def _host_read_only_paths() -> tuple[Path, ...]:
        return tuple(
            Path(path)
            for path in (
                "/etc/alternatives",
                "/etc/group",
                "/etc/ld.so.cache",
                "/etc/ld.so.conf",
                "/etc/ld.so.conf.d",
                "/etc/localtime",
                "/etc/nsswitch.conf",
                "/etc/passwd",
            )
        )

    @staticmethod
    def _parent_directories(path: Path) -> tuple[str, ...]:
        parents: list[str] = []
        current = path.parent
        while current != Path("/"):
            parents.append(str(current))
            current = current.parent
        return tuple(reversed(parents))

    @staticmethod
    def _trusted_command(
        argv: Sequence[str], runtime_roots: tuple[Path, ...]
    ) -> tuple[list[str], Path | None]:
        command = list(argv)
        if not command or command[0] != sys.executable:
            return command, None
        try:
            canonical = Path(sys.executable).resolve(strict=True)
        except OSError as exc:
            raise ContractInvalidError("active Python interpreter is unavailable") from exc
        if not canonical.is_file() or not any(
            canonical.is_relative_to(root) for root in runtime_roots
        ):
            raise ContractInvalidError("active Python interpreter is outside trusted runtime roots")
        active = Path(sys.executable)
        if any(active.is_relative_to(root) for root in runtime_roots):
            return command, canonical
        prefix = Path(sys.prefix)
        if prefix != Path(sys.base_prefix) and active.is_relative_to(prefix):
            relative = active.relative_to(prefix)
            if ".." in relative.parts:
                raise ContractInvalidError("active Python virtualenv path is invalid")
            try:
                mounted = prefix.resolve(strict=True) / relative
                mounted_target = mounted.resolve(strict=True)
            except OSError as exc:
                raise ContractInvalidError("active Python virtualenv is unavailable") from exc
            if not any(mounted.is_relative_to(root) for root in runtime_roots):
                raise ContractInvalidError(
                    "active Python virtualenv is outside trusted runtime roots"
                )
            if mounted_target != canonical:
                raise ContractInvalidError("active Python virtualenv target is inconsistent")
            command[0] = str(mounted)
            return command, canonical
        command[0] = str(canonical)
        return command, canonical

    @staticmethod
    def _interpreter_aliases(
        executable: Path,
        canonical: Path,
        runtime_roots: tuple[Path, ...],
    ) -> tuple[tuple[str, str], ...]:
        def first_link(path: Path) -> tuple[Path, Path, tuple[str, ...]] | None:
            parts = path.parts
            current = Path(parts[0])
            for index, part in enumerate(parts[1:], start=1):
                current /= part
                if current.is_symlink():
                    try:
                        return current, current.readlink(), parts[index + 1 :]
                    except OSError as exc:
                        raise ContractInvalidError(
                            "active Python interpreter alias is unavailable"
                        ) from exc
            return None

        if not executable.is_absolute():
            raise ContractInvalidError("active Python interpreter alias is not absolute")
        aliases: list[tuple[str, str]] = []
        current = executable
        seen: set[Path] = set()
        while current != canonical:
            if current in seen:
                raise ContractInvalidError("active Python interpreter alias has a cycle")
            seen.add(current)
            link_record = first_link(current)
            if link_record is None:
                raise ContractInvalidError(
                    "active Python interpreter alias does not reach the trusted runtime"
                )
            alias, link, remainder = link_record
            if not any(alias.is_relative_to(root) for root in runtime_roots):
                if any(
                    alias == root or alias.is_relative_to(root)
                    for root in _SANDBOX_RESERVED_ALIAS_ROOTS
                ):
                    raise ContractInvalidError(
                        "active Python interpreter alias uses a reserved path"
                    )
                aliases.append((str(link), str(alias)))
            target = link if link.is_absolute() else alias.parent / link
            current = Path(os.path.normpath(str(target.joinpath(*remainder))))
        if not any(current.is_relative_to(root) for root in runtime_roots):
            raise ContractInvalidError(
                "active Python interpreter alias escapes trusted runtime roots"
            )
        return tuple(aliases)

    def run(
        self,
        workspace: Path,
        argv: Sequence[str],
        *,
        timeout_seconds: float,
        environment: Mapping[str, str],
    ) -> subprocess.CompletedProcess[str]:
        return self._run(
            workspace,
            argv,
            timeout_seconds=timeout_seconds,
            environment=environment,
            input_data=None,
        )

    def run_with_input(
        self,
        workspace: Path,
        argv: Sequence[str],
        *,
        timeout_seconds: float,
        environment: Mapping[str, str],
        input_data: bytes,
    ) -> subprocess.CompletedProcess[str]:
        return self._run(
            workspace,
            argv,
            timeout_seconds=timeout_seconds,
            environment=environment,
            input_data=input_data,
        )

    def _run(
        self,
        workspace: Path,
        argv: Sequence[str],
        *,
        timeout_seconds: float,
        environment: Mapping[str, str],
        input_data: bytes | None,
    ) -> subprocess.CompletedProcess[str]:
        sandbox = shutil.which(self.executable, path=_SANDBOX_PATH)
        limiter = shutil.which(self.limiter, path=_SANDBOX_PATH)
        if sandbox is None or limiter is None:
            raise ContractInvalidError("candidate OS sandbox is unavailable")
        runtime_roots = self._runtime_roots()
        sandbox_command, canonical_interpreter = self._trusted_command(argv, runtime_roots)
        interpreter_aliases = (
            ()
            if canonical_interpreter is None
            else self._interpreter_aliases(
                Path(sandbox_command[0]), canonical_interpreter, runtime_roots
            )
        )
        sandbox_argv = [
            sandbox,
            "--die-with-parent",
            "--new-session",
            "--unshare-all",
            "--clearenv",
            "--tmpfs",
            "/",
            "--dir",
            "/workspace",
            "--dir",
            "/etc",
        ]
        created_directories: set[str] = {"/etc", "/workspace"}
        bound_roots: list[Path] = []
        for runtime_root in runtime_roots:
            if any(runtime_root.is_relative_to(bound) for bound in bound_roots):
                continue
            for parent in self._parent_directories(runtime_root):
                if any(Path(parent).is_relative_to(bound) for bound in bound_roots):
                    continue
                if parent not in created_directories:
                    sandbox_argv.extend(("--dir", parent))
                    created_directories.add(parent)
            sandbox_argv.extend(("--ro-bind", str(runtime_root), str(runtime_root)))
            bound_roots.append(runtime_root)
        for target, destination in interpreter_aliases:
            destination_path = Path(destination)
            for parent in self._parent_directories(destination_path):
                if parent not in created_directories:
                    sandbox_argv.extend(("--dir", parent))
                    created_directories.add(parent)
            sandbox_argv.extend(("--symlink", target, destination))
        for host_path in self._host_read_only_paths():
            sandbox_argv.extend(("--ro-bind-try", str(host_path), str(host_path)))
        sandbox_argv.extend(
            (
                "--ro-bind",
                str(workspace.resolve()),
                "/workspace",
                "--dev",
                "/dev",
                "--remount-ro",
                "/dev",
                "--proc",
                "/proc",
                "--size",
                str(64 * 1024 * 1024),
                "--tmpfs",
                "/tmp",
                "--dir",
                "/tmp/home",
            )
        )
        for name, value in sorted(environment.items()):
            sandbox_argv.extend(("--setenv", name, value))
        sandbox_argv.extend(("--chdir", "/workspace", "--", *sandbox_command))
        command = [
            limiter,
            f"--as={1024 * 1024 * 1024}",
            f"--cpu={int(timeout_seconds) + 1}",
            f"--fsize={64 * 1024 * 1024}",
            "--nofile=256",
            "--nproc=128",
            "--",
            *sandbox_argv,
        ]
        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            try:
                options: dict[str, Any] = {
                    "cwd": workspace,
                    "stdout": stdout_file,
                    "stderr": stderr_file,
                    "timeout": timeout_seconds,
                    "check": False,
                    "env": {"LC_ALL": "C", "PATH": _SANDBOX_PATH},
                }
                if input_data is not None:
                    options["input"] = input_data
                completed = subprocess.run(command, **options)
            except subprocess.TimeoutExpired as exc:
                raise ContractInvalidError("candidate execution timed out") from exc
            stdout_file.seek(0)
            stderr_file.seek(0)
            stdout = stdout_file.read(_CANDIDATE_OUTPUT_LIMIT_BYTES + 1)
            stderr = stderr_file.read(_CANDIDATE_OUTPUT_LIMIT_BYTES + 1)
        if (
            len(stdout) > _CANDIDATE_OUTPUT_LIMIT_BYTES
            or len(stderr) > _CANDIDATE_OUTPUT_LIMIT_BYTES
        ):
            raise ContractInvalidError("candidate output exceeded limit")
        try:
            decoded = subprocess.CompletedProcess[str](
                completed.args,
                completed.returncode,
                stdout.decode("utf-8"),
                stderr.decode("utf-8"),
            )
        except UnicodeDecodeError as exc:
            raise ContractInvalidError("candidate output is not UTF-8") from exc
        if decoded.returncode != 0 and decoded.stderr.lstrip().startswith("bwrap:"):
            raise ContractInvalidError("candidate OS sandbox could not establish isolation")
        return decoded


def _reject_non_json_constant(token: str) -> NoReturn:
    raise ValueError(f"non-JSON numeric constant: {token}")


def default_template() -> Template:
    """The one v1 template; products compose behavior inside this single skeleton."""

    return Template(
        version="barebones-1",
        files={
            "product.py": (
                '"""Product behavior generated from a PMOS contract."""\n\n'
                "def health() -> dict[str, str]:\n"
                '    return {"status": "not_implemented"}\n'
            )
        },
        actions={"health": "product:health"},
        context={"service": {"running": True}},
    )


def _safe_path(root: Path, relative: str) -> Path:
    if not _SAFE_RELATIVE.fullmatch(relative) or any(
        part in {".", ".."} for part in relative.split("/")
    ):
        raise ValueError(f"unsafe candidate path: {relative}")
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError(f"candidate path escapes workspace: {relative}")
    return target


def _write_files(root: Path, files: Mapping[str, str]) -> tuple[str, ...]:
    changed: list[str] = []
    for relative, content in sorted(files.items()):
        if not isinstance(relative, str) or not isinstance(content, str):
            raise ValueError("candidate files must map safe paths to UTF-8 text")
        target = _safe_path(root, relative)
        before = target.read_text() if target.is_file() else None
        if before == content:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        changed.append(relative)
    return tuple(changed)


def compile_barebones_plan(
    *,
    contract: Mapping[str, Any],
    repository_root: Path,
    template: Template | None = None,
) -> AcceptanceBuildPlan:
    """Compile the same deterministic plan used by the six-state runtime."""

    active_template = template or default_template()
    template_test_digests: dict[str, str] = {}
    for test_id, proof in active_template.proofs.items():
        if not _SAFE_RELATIVE.fullmatch(proof.path) or any(
            part in {".", ".."} for part in proof.path.split("/")
        ):
            raise ContractInvalidError(f"invalid template proof path: {test_id}")
        target = f"{proof.path}::{proof.node_id}"
        if proof.path not in active_template.files or target not in proof.command:
            raise ContractInvalidError(f"invalid template proof binding: {test_id}")
        template_test_digests[test_id] = (
            "sha256:" + hashlib.sha256(active_template.files[proof.path].encode()).hexdigest()
        )
    trusted_test_digests = {
        relative: "sha256:" + hashlib.sha256(content.encode()).hexdigest()
        for relative, content in active_template.files.items()
        if relative.startswith("tests/")
    }
    return compile_acceptance_plan(
        contract,
        repository_root=repository_root,
        registered_actions=frozenset(active_template.actions),
        template_version=active_template.version,
        template_test_digests=template_test_digests,
        registered_measures=frozenset(active_template.measures),
        trusted_test_digests=trusted_test_digests,
    )


def _path(value: Any, dotted_path: str) -> Any:
    current = value
    for part in dotted_path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            raise KeyError(dotted_path)
        current = current[part]
    return current


def _remaining_verification_time(deadline: float | None) -> float | None:
    if deadline is None:
        return None
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RuntimeError("TRUSTED_VERIFICATION_TIME_LIMIT")
    return remaining


def _bounded_regex_search(pattern: str, value: str, *, deadline: float | None = None) -> bool:
    """Evaluate the approved predicate outside the supervisor interpreter.

    Python's re engine has no built-in timeout; a short candidate response can
    otherwise monopolize the trusted verdict process. The child receives data
    on stdin, has no candidate import path, and cannot return a verdict.
    """
    payload = json.dumps({"pattern": pattern, "value": value}, ensure_ascii=False).encode()
    if len(payload) > _TRUSTED_REGEX_INPUT_LIMIT_BYTES:
        raise RuntimeError("TRUSTED_PREDICATE_INPUT_LIMIT")
    remaining = _remaining_verification_time(deadline)
    timeout = (
        min(_TRUSTED_REGEX_TIMEOUT_SECONDS, remaining)
        if remaining
        else _TRUSTED_REGEX_TIMEOUT_SECONDS
    )
    runner = (
        "import json,re,sys\n"
        "data=json.loads(sys.stdin.buffer.read(1000001))\n"
        "try:\n"
        " matched=bool(re.search(data['pattern'],data['value']))\n"
        "except re.error:\n"
        " raise SystemExit(2)\n"
        "sys.stdout.write('1' if matched else '0')\n"
    )
    try:
        completed = subprocess.run(
            (sys.executable, "-I", "-B", "-c", runner),
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
            cwd="/",
            env={"LC_ALL": "C", "PATH": _SANDBOX_PATH, "PYTHONNOUSERSITE": "1"},
        )
    except subprocess.TimeoutExpired as exc:
        cause = (
            "TRUSTED_VERIFICATION_TIME_LIMIT"
            if deadline is not None and time.monotonic() >= deadline
            else "TRUSTED_PREDICATE_TIMEOUT"
        )
        raise RuntimeError(cause) from exc
    except OSError as exc:
        raise RuntimeError("TRUSTED_PREDICATE_UNAVAILABLE") from exc
    if completed.returncode == 2:
        return False
    if completed.returncode != 0 or completed.stdout not in {b"0", b"1"}:
        raise RuntimeError("TRUSTED_PREDICATE_FAILED")
    return completed.stdout == b"1"


def _assertion_passes(
    assertion: PropertyAssertion, value: Any, *, deadline: float | None = None
) -> bool:
    _remaining_verification_time(deadline)
    try:
        actual = _path(value, assertion.path)
    except KeyError:
        return False

    def ordered(left: Any, right: Any, operation: Callable[[Any, Any], bool]) -> bool:
        if isinstance(left, bool) or isinstance(right, bool):
            return False
        numeric = (int, float)
        if isinstance(left, numeric) and isinstance(right, numeric):
            return operation(left, right)
        if isinstance(left, str) and isinstance(right, str):
            return operation(left, right)
        return False

    def contains(left: Any, right: Any, *, negate: bool = False) -> bool:
        if isinstance(left, list):
            present = any(canonical_digest(item) == canonical_digest(right) for item in left)
        elif isinstance(right, str) and isinstance(left, (str, Mapping)):
            present = right in left
        else:
            return False
        return not present if negate else present

    def matches(left: Any, right: Any) -> bool:
        return (
            isinstance(left, str)
            and isinstance(right, str)
            and _bounded_regex_search(right, left, deadline=deadline)
        )

    binary: dict[Operator, Callable[[Any, Any], bool]] = {
        Operator.EQ: lambda left, right: canonical_digest(left) == canonical_digest(right),
        Operator.NE: lambda left, right: canonical_digest(left) != canonical_digest(right),
        Operator.LT: lambda left, right: ordered(left, right, comparison.lt),
        Operator.LTE: lambda left, right: ordered(left, right, comparison.le),
        Operator.GT: lambda left, right: ordered(left, right, comparison.gt),
        Operator.GTE: lambda left, right: ordered(left, right, comparison.ge),
        Operator.CONTAINS: contains,
        Operator.NOT_CONTAINS: lambda left, right: contains(left, right, negate=True),
        Operator.MATCHES: matches,
    }
    if assertion.operator in binary:
        try:
            result = binary[assertion.operator](actual, assertion.value)
            _remaining_verification_time(deadline)
            return result
        except (TypeError, re.error):
            return False
    unary = {
        Operator.IS_TRUE: actual is True,
        Operator.IS_FALSE: actual is False,
        Operator.IS_NULL: actual is None,
        Operator.NOT_NULL: actual is not None,
    }
    _remaining_verification_time(deadline)
    return unary[assertion.operator]


def _run_action(
    workspace: Path,
    target: str,
    arguments: Mapping[str, Any],
    sandbox: CandidateSandbox,
    *,
    deadline: float | None = None,
) -> Any:
    match = _MODULE_TARGET.fullmatch(target)
    if match is None:
        raise ContractInvalidError(f"invalid template action target: {target}")
    module, function = match.groups()
    module_path = workspace / (module.replace(".", "/") + ".py")
    if not module_path.is_file():
        raise ContractInvalidError(f"template action module is missing: {module}")
    runner = (
        "import importlib,json,sys;"
        "sys.path.insert(0,'/workspace');"
        "m=importlib.import_module(sys.argv[2]);"
        "v=getattr(m,sys.argv[3])(**json.loads(sys.argv[4]));"
        "print(json.dumps(v,sort_keys=True,separators=(',',':')))"
    )
    remaining = _remaining_verification_time(deadline)
    timeout = min(_ACTION_TIMEOUT_SECONDS, remaining) if remaining else _ACTION_TIMEOUT_SECONDS
    completed = sandbox.run(
        workspace,
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            runner,
            "unused-workspace-argument",
            module,
            function,
            json.dumps(arguments),
        ],
        timeout_seconds=timeout,
        environment={
            "HOME": "/tmp/home",
            "LC_ALL": "C",
            "PATH": _SANDBOX_PATH,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "TMPDIR": "/tmp",
        },
    )
    if completed.returncode != 0:
        raise ContractInvalidError("action failed before an assertion")
    try:
        output = completed.stdout
        if isinstance(output, str):
            payload = output.encode("utf-8")
        elif isinstance(output, bytes):
            payload = output
        else:
            raise ContractInvalidError("action response has invalid output type")
        if len(payload) > _CANDIDATE_OUTPUT_LIMIT_BYTES:
            raise ContractInvalidError("candidate output exceeded limit")
        return strict_json_value_loads(payload)
    except (CanonicalInputError, UnicodeError) as exc:
        raise ContractInvalidError("action did not return one JSON value") from exc


def _run_fixed_task_tracker(
    workspace: Path,
    method: str,
    arguments: Mapping[str, Any],
    sandbox: CandidateSandbox,
    *,
    deadline: float | None,
) -> tuple[Mapping[str, Any], list[dict[str, Any]]]:
    """Collect data through the one fixed PMOS observer inside the candidate sandbox."""

    remaining = _remaining_verification_time(deadline)
    timeout = min(_ACTION_TIMEOUT_SECONDS, remaining) if remaining else _ACTION_TIMEOUT_SECONDS
    completed = sandbox.run(
        workspace,
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            runner_source(),
            json.dumps({"method": method, "arguments": dict(arguments)}, sort_keys=True),
            str(timeout),
            "/workspace/tests/acceptance/task_tracker.py",
        ],
        timeout_seconds=timeout,
        environment={
            "HOME": "/tmp/home",
            "LC_ALL": "C",
            "PATH": _SANDBOX_PATH,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "TMPDIR": "/tmp",
        },
    )
    if completed.returncode != 0:
        try:
            failure = strict_json_value_loads(completed.stdout.encode("utf-8"))
        except (CanonicalInputError, UnicodeError):
            failure = None
        code = failure.get("code") if isinstance(failure, Mapping) else None
        if code == "OBSERVER_TOTAL_TIMEOUT":
            raise RuntimeError("TRUSTED_OBSERVATION_TIME_LIMIT")
        if code == "OBSERVER_CHILD_TIMEOUT":
            raise ContractInvalidError("task-tracker child process timed out")
        raise ContractInvalidError("task-tracker observer failed before an assertion")
    try:
        envelope = strict_json_value_loads(completed.stdout.encode("utf-8"))
    except (CanonicalInputError, UnicodeError) as exc:
        raise ContractInvalidError("task-tracker observer returned malformed JSON") from exc
    if not isinstance(envelope, Mapping) or set(envelope) != {"status", "observation", "trace"}:
        raise ContractInvalidError("task-tracker observer response has invalid shape")
    result = envelope["observation"]
    trace = envelope["trace"]
    if envelope["status"] != "OK" or not isinstance(result, Mapping) or not isinstance(trace, list):
        raise ContractInvalidError("task-tracker observer response is incomplete")
    observed_trace: list[dict[str, Any]] = []
    for item in trace:
        if not isinstance(item, Mapping) or set(item) != {"argv", "result"}:
            raise ContractInvalidError("task-tracker command trace is malformed")
        argv = item["argv"]
        outcome = item["result"]
        if (
            not isinstance(argv, list)
            or not all(isinstance(value, str) for value in argv)
            or not isinstance(outcome, Mapping)
            or type(outcome.get("exit_code")) is not int
            or outcome["exit_code"] not in {0, 1, 2}
            or not isinstance(outcome.get("output"), Mapping)
            or outcome["output"].get("invalid_json") is True
        ):
            raise ContractInvalidError("task-tracker command trace has an invalid result")
        observed_trace.append({"argv": argv, "result": dict(outcome)})
    if method == "missing_acknowledged_records" and (
        len(observed_trace) != 11
        or any(item["argv"][-2] != "create" for item in observed_trace[:10])
        or observed_trace[-1]["argv"][-3:] != ["list", "--status", "all"]
    ):
        raise ContractInvalidError("task-tracker sequential measurement is incomplete")
    return dict(result), observed_trace


def _run_pytest_node(
    workspace: Path,
    test: TemplateTest,
    protected_paths: frozenset[str],
    sandbox: CandidateSandbox,
) -> bool:
    pytest_arguments = (
        test.command[3:]
        if len(test.command) >= 3 and test.command[1:3] == ("-m", "pytest")
        else test.command[1:]
    )
    trusted_runner = (
        "import json, os, sys, pytest\n"
        "root = '/workspace'\n"
        "protected = {os.path.realpath(os.path.join(root, p)) "
        "for p in json.loads(sys.argv[1])}\n"
        "writes = []\n"
        "write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND\n"
        "def resolve(path):\n"
        " try:\n"
        "  value = os.fspath(path)\n"
        "  return os.path.realpath(value) if isinstance(value, str) else ''\n"
        " except (OSError, TypeError, ValueError):\n"
        "  return ''\n"
        "def audit(event,args):\n"
        " path = resolve(args[0]) if args else ''\n"
        " targets = {path}\n"
        " if event in {'os.rename', 'os.replace'} and len(args) > 1:\n"
        "  targets.add(resolve(args[1]))\n"
        " def touches(target):\n"
        "  return any(item == target or item.startswith(target + os.sep) for item in protected)\n"
        " if event == 'open':\n"
        "  if path not in protected:\n"
        "   return\n"
        "  mode = args[1] or ''\n"
        "  flags = args[2] or 0\n"
        "  if any(character in mode for character in 'wax+') or flags & write_flags:\n"
        "   writes.append((event, path, str(mode), flags))\n"
        "  return\n"
        " if not any(touches(target) for target in targets if target):\n"
        "  return\n"
        " if event.startswith('os.') and event not in "
        "{'os.chdir', 'os.listdir', 'os.scandir', 'os.stat'}:\n"
        "  writes.append((event, path))\n"
        "sys.addaudithook(audit)\n"
        "class Recorder:\n"
        " def __init__(self): self.reports = {}\n"
        " def pytest_runtest_logreport(self, report):\n"
        "  if report.when == 'call' or report.outcome != 'passed':\n"
        "   self.reports[report.nodeid] = {'outcome': report.outcome, 'when': report.when}\n"
        "recorder = Recorder()\n"
        "sys.path.insert(0, root)\n"
        "code = pytest.main(sys.argv[2:], plugins=[recorder])\n"
        f"print({_PYTEST_RESULT_PREFIX!r} + json.dumps("
        "{'code': int(code), 'reports': recorder.reports, 'writes': writes}, sort_keys=True))\n"
        "raise SystemExit(5 if writes else code)\n"
    )
    pytest_command = (
        sys.executable,
        "-I",
        "-B",
        "-c",
        trusted_runner,
        json.dumps(sorted(protected_paths)),
        *pytest_arguments,
        "--noconftest",
        "--rootdir=/workspace",
        "-c",
        "/dev/null",
        "-p",
        "no:cacheprovider",
    )
    completed = sandbox.run(
        workspace,
        pytest_command,
        timeout_seconds=_PYTEST_TIMEOUT_SECONDS,
        environment={
            "HOME": "/tmp/home",
            "LC_ALL": "C",
            "PATH": _SANDBOX_PATH,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTEST_ADDOPTS": "",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PYTEST_PLUGINS": "",
            "TMPDIR": "/tmp",
        },
    )
    result_lines = [
        line.removeprefix(_PYTEST_RESULT_PREFIX)
        for line in completed.stdout.splitlines()
        if line.startswith(_PYTEST_RESULT_PREFIX)
    ]
    if len(result_lines) != 1:
        detail = completed.stderr.strip()
        raise ContractInvalidError(
            "human test produced no structured pytest result" + (f": {detail}" if detail else "")
        )
    try:
        structured = json.loads(result_lines[0], parse_constant=_reject_non_json_constant)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ContractInvalidError("human test produced malformed structured evidence") from exc
    expected_node = f"{test.path}::{test.node_id}"
    report = structured.get("reports", {}).get(expected_node)
    if not isinstance(report, Mapping):
        raise ContractInvalidError("bound human test node did not execute exactly once")
    if report.get("outcome") == "failed" and completed.returncode == 1:
        return False
    if report.get("outcome") == "passed" and completed.returncode == 0:
        return True
    raise ContractInvalidError(
        "bound human test was skipped, errored, or mutated evidence: "
        + json.dumps(structured.get("writes", []), sort_keys=True)
    )


def _criterion_findings(
    criterion: CompiledCriterion,
    *,
    workspace: Path,
    template: Template,
    sandbox: CandidateSandbox,
    observations: dict[str, dict[str, Any]] | None = None,
    deadline: float | None = None,
) -> tuple[Finding, ...]:
    if criterion.form == "measure":
        if (
            template.version != REGISTRY_NAME
            or template.measures.get(criterion.measure) != MEASURE_TARGET
        ):
            raise ContractInvalidError(
                f"{criterion.criterion_id}: measure has no independent observation adapter"
            )
        assert criterion.operator is not None and criterion.minimum_sample is not None
        result, trace = _run_fixed_task_tracker(
            workspace, "missing_acknowledged_records", {}, sandbox, deadline=deadline
        )
        sample_size = result.get("sample_size")
        if type(sample_size) is not int or sample_size < 0 or "value" not in result:
            raise ContractInvalidError("task-tracker measure returned invalid sample data")
        passed = sample_size >= criterion.minimum_sample and _assertion_passes(
            PropertyAssertion("value", criterion.operator, criterion.value),
            result,
            deadline=deadline,
        )
        if observations is not None:
            observations[criterion.criterion_id] = {
                "criterion_id": criterion.criterion_id,
                "action": criterion.measure,
                "target": MEASURE_TARGET,
                "response": dict(result),
                "response_digest": canonical_digest(result),
                "trace": trace,
                "assertions_passed": passed,
            }
        if passed:
            return ()
        return (
            Finding(
                "ASSERTION_FAILED",
                criterion.criterion_id,
                "compiled acceptance measure failed",
                ("product.py",),
            ),
        )
    if criterion.form != "given_when_then":
        raise ContractInvalidError(
            f"{criterion.criterion_id}: {criterion.form} has no independent observation adapter"
        )
    assert criterion.when is not None
    for item in criterion.given:
        if not _assertion_passes(item, template.context, deadline=deadline):
            raise ContractInvalidError(f"{criterion.criterion_id}: Given precondition is false")
    target = template.actions[criterion.when.action]
    action_trace: list[dict[str, Any]] | None = None
    if target == ACTION_TARGET:
        if template.version != REGISTRY_NAME:
            raise ContractInvalidError("task-tracker action is outside its fixed registry")
        result, action_trace = _run_fixed_task_tracker(
            workspace,
            "observe",
            criterion.when.arguments,
            sandbox,
            deadline=deadline,
        )
    else:
        result = _run_action(
            workspace, target, criterion.when.arguments, sandbox, deadline=deadline
        )
    wrapped = {"result": result}
    passed = all(_assertion_passes(item, wrapped, deadline=deadline) for item in criterion.then)
    if observations is not None:
        entry: dict[str, Any] = {
            "criterion_id": criterion.criterion_id,
            "action": criterion.when.action,
            "target": target,
            "response": result,
            "response_digest": canonical_digest(result),
            "assertions_passed": passed,
        }
        if action_trace is not None:
            entry["trace"] = action_trace
        observations[criterion.criterion_id] = entry
    if passed:
        return ()
    module = (
        "product.py"
        if target == ACTION_TARGET
        else target.split(":", maxsplit=1)[0].replace(".", "/") + ".py"
    )
    return (
        Finding(
            "ASSERTION_FAILED",
            criterion.criterion_id,
            "compiled acceptance assertion failed",
            (module,),
        ),
    )


def _materialize_snapshot(workspace: Path, snapshot: Mapping[str, bytes]) -> None:
    for relative, payload in sorted(snapshot.items()):
        target = _safe_path(workspace, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)


def _verify_snapshot(
    plan: AcceptanceBuildPlan,
    snapshot: Mapping[str, bytes],
    template: Template,
    sandbox: CandidateSandbox,
    *,
    criterion_results: dict[str, tuple[Finding, ...]] | None = None,
    observations: dict[str, dict[str, Any]] | None = None,
) -> tuple[Finding, ...]:
    """Verify each criterion against a fresh disposable copy of the exact snapshot."""

    findings: list[Finding] = []
    observed_bytes = 0
    deadline = time.monotonic() + _MAX_TOTAL_VERIFICATION_SECONDS
    for criterion in plan.criteria:
        if time.monotonic() > deadline:
            raise RuntimeError("TRUSTED_VERIFICATION_TIME_LIMIT")
        first_finding = len(findings)
        with tempfile.TemporaryDirectory(prefix="pmpe-verification-") as temporary:
            isolated = Path(temporary)
            _materialize_snapshot(isolated, snapshot)
            if _workspace_snapshot(isolated) != snapshot:
                raise ContractInvalidError("candidate snapshot changed before verification")
            try:
                findings.extend(
                    _criterion_findings(
                        criterion,
                        workspace=isolated,
                        template=template,
                        sandbox=sandbox,
                        observations=observations,
                        deadline=deadline,
                    )
                )
            except ContractInvalidError as exc:
                if criterion.human_test is None:
                    if criterion_results is not None:
                        criterion_results[criterion.criterion_id] = (
                            Finding("CANDIDATE_EXECUTION_FAILED", criterion.criterion_id, str(exc)),
                        )
                    raise
                findings.append(
                    Finding(
                        "CANDIDATE_EXECUTION_FAILED",
                        criterion.criterion_id,
                        str(exc),
                        (criterion.human_test.path,),
                    )
                )
            observed = _workspace_snapshot(isolated)
            if observed != snapshot:
                changed = tuple(
                    sorted(
                        {
                            *snapshot.keys(),
                            *observed.keys(),
                        }
                        - {
                            path
                            for path in set(snapshot).intersection(observed)
                            if snapshot[path] == observed[path]
                        }
                    )
                )
                findings.append(
                    Finding(
                        "CANDIDATE_MUTATED_DURING_VERIFICATION",
                        criterion.criterion_id,
                        "candidate changed its isolated verification snapshot",
                        changed,
                    )
                )
            if observations is not None and criterion.criterion_id in observations:
                observed_bytes += len(canonical_json_bytes(observations[criterion.criterion_id]))
                if observed_bytes > _MAX_TOTAL_VERIFICATION_BYTES:
                    raise ContractInvalidError("candidate observations exceeded total limit")
            if criterion_results is not None:
                criterion_results[criterion.criterion_id] = tuple(findings[first_finding:])
            if time.monotonic() > deadline:
                raise RuntimeError("TRUSTED_VERIFICATION_TIME_LIMIT")
    return tuple(findings)


def _security_findings(workspace: Path) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    for path in sorted(item for item in workspace.rglob("*") if item.is_file()):
        try:
            content = path.read_text()
        except UnicodeDecodeError:
            continue
        relative = str(path.relative_to(workspace))
        if _CREDENTIAL.search(content):
            findings.append(
                Finding("CRITICAL_CREDENTIAL", relative, "credential material", (relative,))
            )
        if path.suffix == ".py" and _HIGH_RISK_CODE.search(content):
            findings.append(
                Finding("HIGH_DYNAMIC_EXECUTION", relative, "dynamic execution", (relative,))
            )
        if path.suffix == ".py" and "TODO" in content:
            findings.append(Finding("LOW_TODO", relative, "TODO remains", (relative,)))
    return tuple(findings)


def _workspace_snapshot(workspace: Path) -> dict[str, bytes]:
    snapshot: dict[str, bytes] = {}
    for path in sorted(workspace.rglob("*")):
        if path.is_symlink():
            raise ContractInvalidError("candidate snapshot contains a symlink")
        mode = path.stat(follow_symlinks=False).st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise ContractInvalidError("candidate snapshot contains a non-regular file")
        snapshot[str(path.relative_to(workspace))] = path.read_bytes()
    return snapshot


def _candidate_manifest(
    snapshot: Mapping[str, bytes], ledger: EvidenceLedger
) -> tuple[str, tuple[str, ...]]:
    manifest: dict[str, str] = {}
    blobs: list[str] = []
    for relative, payload in sorted(snapshot.items()):
        digest = ledger.put_blob(payload)
        manifest[relative] = digest
        blobs.append(digest)
    manifest_blob = ledger.put_blob(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    )
    return manifest_blob, tuple(sorted(set(blobs)))


def _verify_frozen_inputs(
    contract: Mapping[str, Any],
    plan: AcceptanceBuildPlan,
    template: Template,
    template_digest: str,
) -> None:
    """Check the exact approved plan and action registry used by the supervisor."""
    plan_body = plan.as_dict()
    plan_body.pop("plan_digest")
    if (
        canonical_digest(contract) != plan.contract_digest
        or canonical_digest(plan_body) != plan.plan_digest
        or canonical_digest(asdict(template)) != template_digest
    ):
        raise ContractInvalidError("approved verifier inputs changed after admission")
    for criterion in plan.criteria:
        if criterion.form == "given_when_then" and (
            criterion.when is None or criterion.when.action not in template.actions
        ):
            raise ContractInvalidError("compiled action binding changed after admission")


def _model_request(
    *,
    contract: Mapping[str, Any],
    plan: AcceptanceBuildPlan,
    workspace: Path,
    findings: Sequence[Finding],
) -> dict[str, Any]:
    body = {
        "contract": contract,
        "plan": plan.as_dict(),
        "files": {
            str(path.relative_to(workspace)): path.read_text()
            for path in sorted(workspace.rglob("*"))
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix in {".json", ".md", ".py", ".toml", ".txt", ".yaml", ".yml"}
        },
        "findings": [asdict(item) for item in findings],
    }
    return {**body, "request_digest": canonical_digest(body)}


def _invoke_bound(
    provider: ModelProvider,
    *,
    purpose: str,
    request: Mapping[str, Any],
    budget: BudgetCaps,
    counters: dict[str, Any],
) -> Mapping[str, Any]:
    if counters["calls"] >= budget.max_model_calls:
        raise RuntimeError("MODEL_CALL_BUDGET_EXHAUSTED")
    counters["calls"] += 1
    response = provider.invoke(purpose=purpose, request=request)
    serialized = json.dumps(response, sort_keys=True, separators=(",", ":"))
    if _CREDENTIAL.search(serialized):
        raise RuntimeError("MODEL_RESPONSE_CONTAINS_CREDENTIAL")
    size = len(serialized.encode())
    counters["bytes"] += size
    if counters["bytes"] > budget.max_model_output_bytes:
        raise RuntimeError("MODEL_OUTPUT_BUDGET_EXHAUSTED")
    if response.get("request_digest") != request.get("request_digest"):
        raise RuntimeError("MODEL_RESPONSE_UNBOUND")
    usage = response.get("usage")
    if isinstance(usage, Mapping):
        for source, target in (("input_tokens", "tokens_in"), ("output_tokens", "tokens_out")):
            value = usage.get(source)
            if value is None:
                continue
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise RuntimeError("MODEL_PROVIDER_USAGE_INVALID")
            accumulated_tokens = counters[target] + value
            if accumulated_tokens > _MAX_SAFE_JSON_INTEGER:
                raise RuntimeError("MODEL_PROVIDER_USAGE_INVALID")
            counters[target] = accumulated_tokens
        estimated = usage.get("estimated_cost_usd")
        if estimated is not None:
            if not isinstance(estimated, (int, float)) or isinstance(estimated, bool):
                raise RuntimeError("MODEL_PROVIDER_USAGE_INVALID")
            if isinstance(estimated, int) and abs(estimated) > _MAX_SAFE_JSON_INTEGER:
                raise RuntimeError("MODEL_PROVIDER_USAGE_INVALID")
            try:
                estimated_value = float(estimated)
            except (OverflowError, ValueError) as exc:
                raise RuntimeError("MODEL_PROVIDER_USAGE_INVALID") from exc
            if not math.isfinite(estimated_value) or estimated_value < 0:
                raise RuntimeError("MODEL_PROVIDER_USAGE_INVALID")
            accumulated_cost = counters["estimated_cost_usd"] + estimated_value
            if not math.isfinite(accumulated_cost):
                raise RuntimeError("MODEL_PROVIDER_USAGE_INVALID")
            counters["estimated_cost_usd"] = accumulated_cost
    metadata = response.get("provider_metadata")
    if isinstance(metadata, Mapping):
        model = metadata.get("model")
        if isinstance(model, str) and model:
            observed = counters.get("provider_model_id")
            counters["provider_model_id"] = (
                model if not observed or observed == model else "multiple"
            )
    return response


def run_to_release_ready(
    *,
    contract: Mapping[str, Any],
    repository_root: Path,
    workspace: Path,
    run_id: str,
    provider: ModelProvider,
    template: Template | None = None,
    budget: BudgetCaps | None = None,
    stop_requested: Callable[[], bool] = lambda: False,
    candidate_sandbox: CandidateSandbox | None = None,
    approval_receipt: Mapping[str, Any] | None = None,
    approval_authority: str | None = None,
    approval_receipt_bytes: bytes | None = None,
    core_harness_mapping: Mapping[str, Any] | None = None,
) -> RunResult:
    """Run the frozen core, retaining candidate evidence without unsafe release."""

    started = time.monotonic()
    contract = copy.deepcopy(dict(contract))
    try:
        harness_plan = compile_required_harness(contract, core_harness_mapping)
    except CoreHarnessInvalidError as exc:
        raise ContractInvalidError(str(exc)) from exc
    active_template = copy.deepcopy(template or default_template())
    if active_template.version == REGISTRY_NAME and harness_plan is None:
        raise ContractInvalidError("fixed task-tracker template requires a bound core harness")
    if harness_plan is not None and active_template.version != REGISTRY_NAME:
        raise ContractInvalidError("bound core harness requires the fixed task-tracker template")
    template_digest = canonical_digest(asdict(active_template))
    active_budget = budget or BudgetCaps()
    active_sandbox = candidate_sandbox or BubblewrapCandidateSandbox()
    # The label describes the selected adapter mode, not release eligibility.
    # Import here because the offline adapter uses the candidate sandbox above.
    from pmpe.provider_isolation import OfflineConfinedProvider

    provider_write_isolation = (
        OFFLINE_PROVIDER_ISOLATION
        if type(provider) is OfflineConfinedProvider
        else GENERIC_PROVIDER_ISOLATION
    )
    counters: dict[str, Any] = {
        "calls": 0,
        "bytes": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "estimated_cost_usd": 0.0,
        "provider_model_id": "",
        "structured_criteria_count": 0,
        "human_test_count": 0,
        "verification_protocol": _VERIFICATION_PROTOCOL,
        "assurance_scope": "CANDIDATE_RESPONSE_ONLY",
        "provider_write_isolation": provider_write_isolation,
    }
    if harness_plan is not None:
        counters["core_harness"] = {
            "mapping_digest": harness_plan.mapping_digest,
            "required_condition_ids": [item.condition_id for item in harness_plan.conditions],
            "proof_status": "NOT_ESTABLISHED",
        }
    subject_digest = canonical_digest(contract)
    approval_inputs = (approval_receipt, approval_authority, approval_receipt_bytes)
    if any(item is None for item in approval_inputs) and not all(
        item is None for item in approval_inputs
    ):
        raise ContractInvalidError(
            "approval receipt, authority, and submitted bytes must be supplied together"
        )
    approval_payload: dict[str, Any] = {"status": "UNVERIFIED_DIRECT_CALL"}
    if (
        approval_receipt is not None
        and approval_authority is not None
        and approval_receipt_bytes is not None
    ):
        try:
            submitted_receipt = strict_loads(approval_receipt_bytes, "application/json")
        except CanonicalInputError as exc:
            raise ContractInvalidError("submitted approval receipt is malformed") from exc
        if canonical_digest(submitted_receipt) != canonical_digest(approval_receipt):
            raise ContractInvalidError("submitted approval receipt bytes do not match receipt")
        try:
            receipt_digest = verify_contract_approval(
                dict(contract),
                dict(approval_receipt),
                expected_approver=approval_authority,
            )
        except ContractViolation as exc:
            raise ContractInvalidError(str(exc)) from exc
        approval_payload = {
            "status": "VERIFIED",
            "authority": approval_authority,
            "receipt_digest": receipt_digest,
        }

    plan = compile_barebones_plan(
        contract=contract,
        repository_root=repository_root,
        template=active_template,
    )
    counters["structured_criteria_count"] = sum(
        item.form == "given_when_then" for item in plan.criteria
    )
    counters["human_test_count"] = sum(item.form == "human_test" for item in plan.criteria)
    _verify_frozen_inputs(contract, plan, active_template, template_digest)
    workspace_root = workspace.resolve()
    evidence_root = (repository_root / ".pmpe").resolve()
    if workspace_root.is_relative_to(evidence_root) or evidence_root.is_relative_to(workspace_root):
        raise ContractInvalidError("candidate workspace must not overlap evidence storage")
    if workspace.exists() and (not workspace.is_dir() or any(workspace.iterdir())):
        raise ContractInvalidError("candidate workspace must be empty")
    workspace.mkdir(parents=True, exist_ok=True)
    ledger = EvidenceLedger(repository_root, run_id)

    def append_terminal_event(
        *,
        event_type: str,
        state: RunState,
        subject_digest: str,
        payload: Mapping[str, Any],
        blob_digests: Sequence[str] = (),
    ) -> None:
        try:
            ledger.append(
                event_type=event_type,
                state=state,
                subject_digest=subject_digest,
                blob_digests=blob_digests,
                payload=payload,
            )
        except (EvidenceIntegrityError, OSError) as exc:
            raise TerminalPersistenceError(
                "terminal evidence append could not be confirmed"
            ) from exc

    def _terminal_telemetry() -> dict[str, Any]:
        counters["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        return dict(counters)

    def finish(
        state: RunState, cause: str, attempts: int, annotation: Mapping[str, Any] | None = None
    ) -> RunResult:
        return RunResult(
            run_id=run_id,
            state=state,
            cause=cause,
            attempts=attempts,
            model_calls=int(counters["calls"]),
            elapsed_ms=int(counters.get("elapsed_ms", (time.monotonic() - started) * 1000)),
            evidence_path=ledger.events_path,
            annotation=dict(annotation or {}),
            telemetry=dict(counters),
        )

    def record_release_gates(
        snapshot: Mapping[str, bytes],
        criterion_results: Mapping[str, tuple[Finding, ...]],
        attempt: int,
        state: RunState,
    ) -> tuple[str, list[dict[str, Any]]]:
        if not plan.release_gates:
            return "", []
        gates = release_gate_results(plan.release_gates, criterion_results)
        candidate_blob, candidate_file_blobs = _candidate_manifest(snapshot, ledger)
        evidence = {
            "attempt": attempt,
            "contract_digest": subject_digest,
            "plan_digest": plan.plan_digest,
            "candidate_digest": candidate_blob,
            "gates": gates,
        }
        blob = ledger.put_blob(json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode())
        ledger.append(
            event_type="release_gates_evaluated",
            state=state,
            subject_digest=subject_digest,
            blob_digests=(blob, candidate_blob, *candidate_file_blobs),
            payload=evidence,
        )
        return blob, gates

    def record_observations(
        snapshot: Mapping[str, bytes],
        observations: Mapping[str, dict[str, Any]],
        *,
        attempt: int,
        state: RunState,
    ) -> str:
        expected_ids = {criterion.criterion_id for criterion in plan.criteria}
        if set(observations) != expected_ids:
            raise ContractInvalidError("not every required criterion has an observation")
        candidate_blob, candidate_file_blobs = _candidate_manifest(snapshot, ledger)
        entries: list[dict[str, Any]] = []
        response_blobs: list[str] = []
        trace_blobs: list[str] = []
        for criterion_id in sorted(observations):
            observation = observations[criterion_id]
            response_digest = ledger.put_blob(canonical_json_bytes(observation["response"]))
            if response_digest != observation["response_digest"]:
                raise ContractInvalidError("observed response digest changed")
            response_blobs.append(response_digest)
            entry: dict[str, Any] = {
                "criterion_id": criterion_id,
                "action": observation["action"],
                "target": observation["target"],
                "response_digest": response_digest,
                "assertions_passed": observation["assertions_passed"],
            }
            if "trace" in observation:
                trace_digest = ledger.put_blob(canonical_json_bytes(observation["trace"]))
                entry["trace_digest"] = trace_digest
                trace_blobs.append(trace_digest)
            entries.append(entry)
        evidence = {
            "protocol": _VERIFICATION_PROTOCOL,
            "attempt": attempt,
            "contract_digest": subject_digest,
            "plan_digest": plan.plan_digest,
            "template_digest": template_digest,
            "candidate_digest": candidate_blob,
            "required_criterion_ids": sorted(expected_ids),
            "observations": entries,
        }
        evidence_blob = ledger.put_blob(canonical_json_bytes(evidence))
        ledger.append(
            event_type="supervisor_observations",
            state=state,
            subject_digest=subject_digest,
            blob_digests=(
                evidence_blob,
                candidate_blob,
                *candidate_file_blobs,
                *response_blobs,
                *trace_blobs,
            ),
            payload={**evidence, "evidence_digest": evidence_blob},
        )
        return evidence_blob

    plan_blob = ledger.put_blob(
        json.dumps(plan.as_dict(), sort_keys=True, separators=(",", ":")).encode()
    )
    contract_blob = ledger.put_blob(
        json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()
    )
    validation_blobs = [contract_blob, plan_blob]
    if approval_receipt_bytes is not None:
        receipt_blob = ledger.put_blob(approval_receipt_bytes)
        validation_blobs.append(receipt_blob)
        approval_payload["receipt_blob_digest"] = receipt_blob
    ledger.append(
        event_type="contract_validated",
        state=RunState.VALIDATED,
        subject_digest=subject_digest,
        blob_digests=tuple(validation_blobs),
        payload={
            "approval": approval_payload,
            "contract_digest": contract_blob,
            "plan_digest": plan.plan_digest,
            "template_digest": template_digest,
        },
    )

    unsupported = [
        {
            "criterion_id": item.criterion_id,
            "form": item.form,
            "code": "UNSUPPORTED_VERIFICATION_MODE",
            "message": f"{item.form} requires a trusted observation adapter",
        }
        for item in plan.criteria
        if item.form != "given_when_then"
        and not (
            item.form == "measure"
            and harness_plan is not None
            and active_template.measures.get(item.measure) == MEASURE_TARGET
        )
    ]
    if unsupported:
        append_terminal_event(
            event_type="halted",
            state=RunState.HALTED,
            subject_digest=subject_digest,
            payload={
                "cause": "UNSUPPORTED_VERIFICATION_MODE",
                "diagnostics": unsupported,
                "plan_digest": plan.plan_digest,
                "telemetry": dict(counters),
            },
        )
        return RunResult(
            run_id=run_id,
            state=RunState.HALTED,
            cause="UNSUPPORTED_VERIFICATION_MODE",
            attempts=0,
            model_calls=0,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            evidence_path=ledger.events_path,
            annotation={"diagnostics": unsupported},
            telemetry=dict(counters),
        )

    def record_execution_failure(exc: ContractInvalidError | RuntimeError | OSError) -> None:
        cause = "CONTRACT_INVALID" if isinstance(exc, ContractInvalidError) else "EXECUTION_FAILED"
        append_terminal_event(
            event_type="halted",
            state=RunState.HALTED,
            subject_digest=subject_digest,
            payload={
                "cause": cause,
                "detail": str(exc),
                "telemetry": _terminal_telemetry(),
            },
        )

    if stop_requested():
        append_terminal_event(
            event_type="stopped",
            state=RunState.STOPPED,
            subject_digest=subject_digest,
            payload={"cause": "STOP_REQUESTED", "telemetry": _terminal_telemetry()},
        )
        return finish(RunState.STOPPED, "STOP_REQUESTED", 0)

    try:
        _verify_frozen_inputs(contract, plan, active_template, template_digest)
        _write_files(workspace, active_template.files)
        protected_tests = {
            _safe_path(workspace, proof.path) for proof in active_template.proofs.values()
        }
        for relative, digest in plan.trusted_test_digests:
            trusted_path = _safe_path(workspace, relative)
            observed = "sha256:" + hashlib.sha256(trusted_path.read_bytes()).hexdigest()
            if observed != digest:
                raise ContractInvalidError(
                    "trusted test support does not match its compiled digest"
                )
            protected_tests.add(trusted_path)
        for criterion in plan.criteria:
            if criterion.human_test is None:
                continue
            relative = criterion.human_test.path
            source = repository_root / relative
            digest = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
            if digest != criterion.human_test.file_digest:
                raise ContractInvalidError("human test changed after compilation")
            _write_files(workspace, {relative: source.read_text()})
            protected_tests.add(_safe_path(workspace, relative))
        protected_package_initializers: set[Path] = set()
        for protected_test in protected_tests:
            parent = protected_test.parent
            while parent != workspace:
                protected_package_initializers.add(parent / "__init__.py")
                parent = parent.parent
        protected_tests.update(protected_package_initializers)
        baseline_observations: dict[str, dict[str, Any]] = {}
        baseline_snapshot = _workspace_snapshot(workspace)
        baseline = _verify_snapshot(
            plan,
            baseline_snapshot,
            active_template,
            active_sandbox,
            observations=baseline_observations,
        )
        if set(baseline_observations) != {item.criterion_id for item in plan.criteria}:
            raise ContractInvalidError("baseline did not observe every required criterion")
        non_template = tuple(item for item in plan.criteria if item.form != "satisfied_by_template")
        failed_ids = {item.subject_id for item in baseline}
        if any(item.code != "ASSERTION_FAILED" for item in baseline) or failed_ids != {
            item.criterion_id for item in non_template
        }:
            raise ContractInvalidError(
                "baseline must fail every non-template criterion by assertion"
            )
    except (ContractInvalidError, RuntimeError, OSError) as exc:
        record_execution_failure(exc)
        raise
    try:
        baseline_blob = ledger.put_blob(
            json.dumps(
                [asdict(item) for item in baseline], sort_keys=True, separators=(",", ":")
            ).encode()
        )
        baseline_observation_blob = record_observations(
            baseline_snapshot, baseline_observations, attempt=0, state=RunState.BUILDING
        )
    except (ContractInvalidError, RuntimeError, OSError) as exc:
        record_execution_failure(exc)
        raise
    ledger.append(
        event_type="meaningful_red_confirmed",
        state=RunState.BUILDING,
        subject_digest=subject_digest,
        blob_digests=(baseline_blob, baseline_observation_blob),
        payload={
            "findings": [asdict(item) for item in baseline],
            "observation_evidence_digest": baseline_observation_blob,
            "protocol": _VERIFICATION_PROTOCOL,
        },
    )

    findings: tuple[Finding, ...] = baseline
    previous_finding_digest = ""
    for attempt in range(1, active_budget.max_attempts + 1):
        try:
            _verify_frozen_inputs(contract, plan, active_template, template_digest)
        except ContractInvalidError as exc:
            record_execution_failure(exc)
            raise
        if stop_requested():
            append_terminal_event(
                event_type="stopped",
                state=RunState.STOPPED,
                subject_digest=subject_digest,
                payload={"cause": "STOP_REQUESTED", "telemetry": _terminal_telemetry()},
            )
            return finish(RunState.STOPPED, "STOP_REQUESTED", attempt - 1)
        try:
            request = _model_request(
                contract=contract,
                plan=plan,
                workspace=workspace,
                findings=findings,
            )
            response = _invoke_bound(
                provider,
                purpose="code",
                request=request,
                budget=active_budget,
                counters=counters,
            )
        except (ContractInvalidError, OSError) as exc:
            record_execution_failure(exc)
            raise
        except RuntimeError as exc:
            cause = _classify_provider_error(exc)
            append_terminal_event(
                event_type="halted",
                state=RunState.HALTED,
                subject_digest=subject_digest,
                payload={"cause": cause, "telemetry": _terminal_telemetry()},
            )
            return finish(RunState.HALTED, cause, attempt - 1)
        try:
            _verify_frozen_inputs(contract, plan, active_template, template_digest)
        except ContractInvalidError as exc:
            record_execution_failure(exc)
            raise
        files = response.get("files")
        if not isinstance(files, Mapping):
            append_terminal_event(
                event_type="halted",
                state=RunState.HALTED,
                subject_digest=subject_digest,
                payload={"cause": "CODER_RESPONSE_INVALID", "telemetry": _terminal_telemetry()},
            )
            return finish(RunState.HALTED, "CODER_RESPONSE_INVALID", attempt)
        try:
            response_paths = {
                _safe_path(workspace, relative) for relative in files if isinstance(relative, str)
            }
            if len(response_paths) != len(files):
                raise ValueError("candidate paths must be strings")
        except OSError as exc:
            record_execution_failure(exc)
            raise
        except ValueError:
            append_terminal_event(
                event_type="halted",
                state=RunState.HALTED,
                subject_digest=subject_digest,
                payload={"cause": "CODER_RESPONSE_INVALID", "telemetry": _terminal_telemetry()},
            )
            return finish(RunState.HALTED, "CODER_RESPONSE_INVALID", attempt)
        if protected_tests.intersection(response_paths):
            append_terminal_event(
                event_type="halted",
                state=RunState.HALTED,
                subject_digest=subject_digest,
                payload={"cause": "CODER_MODIFIED_EVIDENCE", "telemetry": _terminal_telemetry()},
            )
            return finish(RunState.HALTED, "CODER_MODIFIED_EVIDENCE", attempt)
        try:
            changed = _write_files(workspace, files)
        except OSError as exc:
            record_execution_failure(exc)
            raise
        except ValueError:
            append_terminal_event(
                event_type="halted",
                state=RunState.HALTED,
                subject_digest=subject_digest,
                payload={"cause": "CODER_RESPONSE_INVALID", "telemetry": _terminal_telemetry()},
            )
            return finish(RunState.HALTED, "CODER_RESPONSE_INVALID", attempt)
        coder_blob = ledger.put_blob(
            json.dumps(response, sort_keys=True, separators=(",", ":")).encode()
        )
        request_blob = ledger.put_blob(
            json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
        )
        coder_payload: dict[str, Any] = {
            "attempt": attempt,
            "changed": list(changed),
            "request_blob_digest": request_blob,
            "response_blob_digest": coder_blob,
        }
        coder_behavior = _provider_behavior_payload("code", response)
        if coder_behavior is not None:
            coder_payload["provider_behavior"] = coder_behavior
        ledger.append(
            event_type="coder_completed",
            state=RunState.BUILDING,
            subject_digest=subject_digest,
            blob_digests=(request_blob, coder_blob),
            payload=coder_payload,
        )
        finding_digest = canonical_digest([asdict(item) for item in findings])
        implicated = {path for item in findings for path in item.files}
        human_test_ids = {item.criterion_id for item in plan.criteria if item.form == "human_test"}
        human_test_repair = bool(changed) and any(
            item.subject_id in human_test_ids for item in findings
        )
        dependency_repair = any(
            item.code == "CANDIDATE_EXECUTION_FAILED" for item in findings
        ) and any(path.endswith(".py") for path in changed)
        if (
            previous_finding_digest == finding_digest
            and not implicated.intersection(changed)
            and not human_test_repair
            and not dependency_repair
        ):
            subjects = ",".join(sorted({item.subject_id for item in findings}))
            cause = f"REPEAT_FINDING_WITHOUT_RELEVANT_CHANGE:{subjects}"
            append_terminal_event(
                event_type="halted",
                state=RunState.HALTED,
                subject_digest=subject_digest,
                payload={
                    "cause": cause,
                    "findings": [asdict(item) for item in findings],
                    "telemetry": _terminal_telemetry(),
                },
            )
            return finish(RunState.HALTED, cause, attempt)

        try:
            verification_snapshot = _workspace_snapshot(workspace)
            security = _security_findings(workspace)
        except (ContractInvalidError, RuntimeError, OSError) as exc:
            record_execution_failure(exc)
            raise
        blocking_security = tuple(
            item for item in security if item.code.startswith(("CRITICAL_", "HIGH_"))
        )
        if blocking_security:
            findings = blocking_security
            record_release_gates(verification_snapshot, {}, attempt, RunState.BUILDING)
            finding_blob = ledger.put_blob(
                json.dumps(
                    [asdict(item) for item in findings],
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            )
            ledger.append(
                event_type="security_failed",
                state=RunState.BUILDING,
                subject_digest=subject_digest,
                blob_digests=(finding_blob,),
                payload={"attempt": attempt, "findings": [asdict(item) for item in findings]},
            )
        else:
            ledger.append(
                event_type="verification_started",
                state=RunState.VERIFYING,
                subject_digest=subject_digest,
                payload={"attempt": attempt, "changed": list(changed)},
            )
            criterion_results: dict[str, tuple[Finding, ...]] = {}
            observations: dict[str, dict[str, Any]] = {}
            try:
                findings = _verify_snapshot(
                    plan,
                    verification_snapshot,
                    active_template,
                    active_sandbox,
                    criterion_results=criterion_results,
                    observations=observations,
                )
            except ContractInvalidError as exc:
                implicated_files = tuple(
                    sorted(
                        {
                            target.split(":", maxsplit=1)[0].replace(".", "/") + ".py"
                            for target in (
                                *active_template.actions.values(),
                                *active_template.measures.values(),
                            )
                        }
                    )
                )
                findings = (
                    Finding(
                        "CANDIDATE_EXECUTION_FAILED",
                        "candidate",
                        str(exc),
                        implicated_files,
                    ),
                )
            except (RuntimeError, OSError) as exc:
                record_execution_failure(exc)
                raise
            expected_ids = {criterion.criterion_id for criterion in plan.criteria}
            if set(criterion_results) != expected_ids or set(observations) != expected_ids:
                findings += (
                    Finding(
                        "VERIFICATION_INCOMPLETE",
                        "candidate",
                        "every required criterion must have one trusted observation and result",
                    ),
                )
                observation_evidence_digest = ""
            else:
                try:
                    observation_evidence_digest = record_observations(
                        verification_snapshot,
                        observations,
                        attempt=attempt,
                        state=RunState.VERIFYING,
                    )
                except (ContractInvalidError, RuntimeError, OSError) as exc:
                    record_execution_failure(exc)
                    raise
            gate_evidence_digest, gates = record_release_gates(
                verification_snapshot, criterion_results, attempt, RunState.VERIFYING
            )
            if harness_plan is not None:
                observed_stages = harness_plan.observed_stages(gates)
                blocking_ids = [
                    item["condition_id"] for item in observed_stages if item["status"] != "PASS"
                ]
                stage_evidence = {
                    "attempt": attempt,
                    "mapping_digest": harness_plan.mapping_digest,
                    "contract_digest": subject_digest,
                    "plan_digest": plan.plan_digest,
                    "conditions": observed_stages,
                    "blocking_condition_ids": blocking_ids,
                    "release_eligible": False,
                }
                stage_blob = ledger.put_blob(canonical_json_bytes(stage_evidence))
                ledger.append(
                    event_type="core_conditions_evaluated",
                    state=RunState.VERIFYING,
                    subject_digest=subject_digest,
                    blob_digests=(stage_blob,),
                    payload={**stage_evidence, "evidence_digest": stage_blob},
                )
                counters["core_harness"] = {
                    "mapping_digest": harness_plan.mapping_digest,
                    "required_condition_ids": [
                        item.condition_id for item in harness_plan.conditions
                    ],
                    "blocking_condition_ids": blocking_ids,
                    "proof_status": "NOT_ESTABLISHED",
                }
            findings += tuple(
                Finding(
                    "RELEASE_GATE_FAILED"
                    if gate["status"] == "FAIL"
                    else "RELEASE_GATE_NOT_EVALUATED",
                    gate["gate_id"],
                    "every bound acceptance criterion must have explicit PASS evidence",
                )
                for gate in gates
                if gate["status"] != "PASS"
            )
            if not findings:
                # The response-level contract passed, but neither current
                # provider mode establishes a protected live-provider release
                # boundary. Retain candidate evidence without RELEASE_READY.
                evidence = {
                    "assertions": "passed",
                    "coverage": "complete",
                    "security": [asdict(item) for item in security],
                    "attempt": attempt,
                }
                blob = ledger.put_blob(json.dumps(evidence, sort_keys=True).encode())
                candidate_blob, candidate_file_blobs = _candidate_manifest(
                    verification_snapshot, ledger
                )
                candidate_payload: dict[str, Any] = {
                    "candidate_digest": candidate_blob,
                    "verification_protocol": _VERIFICATION_PROTOCOL,
                    "verification_observations_digest": observation_evidence_digest,
                    "assurance_scope": "CANDIDATE_RESPONSE_ONLY",
                    "provider_write_isolation": provider_write_isolation,
                    "plan_digest": plan.plan_digest,
                    "evidence_digest": blob,
                    "attempt": attempt,
                }
                if gate_evidence_digest:
                    candidate_payload["release_gate_evidence_digest"] = gate_evidence_digest
                ledger.append(
                    event_type="candidate_response_verified",
                    state=RunState.VERIFYING,
                    subject_digest=subject_digest,
                    blob_digests=(
                        blob,
                        candidate_blob,
                        observation_evidence_digest,
                        *candidate_file_blobs,
                        *((gate_evidence_digest,) if gate_evidence_digest else ()),
                    ),
                    payload=candidate_payload,
                )
                cause = "PROVIDER_WRITE_ISOLATION_UNVERIFIED"
                counters["candidate_response_verified"] = True
                append_terminal_event(
                    event_type="halted",
                    state=RunState.HALTED,
                    subject_digest=subject_digest,
                    blob_digests=(candidate_blob, observation_evidence_digest),
                    payload={
                        "cause": cause,
                        "candidate_digest": candidate_blob,
                        "verification_observations_digest": observation_evidence_digest,
                        "assurance_scope": "CANDIDATE_RESPONSE_ONLY",
                        "provider_write_isolation": provider_write_isolation,
                        "telemetry": _terminal_telemetry(),
                    },
                )
                return finish(
                    RunState.HALTED,
                    cause,
                    attempt,
                    {
                        "candidate_response_verified": True,
                        "candidate_digest": candidate_blob,
                        "verification_observations_digest": observation_evidence_digest,
                    },
                )
            finding_blob = ledger.put_blob(
                json.dumps(
                    [asdict(item) for item in findings],
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            )
            ledger.append(
                event_type="verification_failed",
                state=RunState.BUILDING,
                subject_digest=subject_digest,
                blob_digests=(finding_blob,),
                payload={"attempt": attempt, "findings": [asdict(item) for item in findings]},
            )
        previous_finding_digest = canonical_digest([asdict(item) for item in findings])

    append_terminal_event(
        event_type="halted",
        state=RunState.HALTED,
        subject_digest=subject_digest,
        payload={
            "cause": "ATTEMPT_BUDGET_EXHAUSTED",
            "findings": [asdict(item) for item in findings],
            "telemetry": _terminal_telemetry(),
        },
    )
    return finish(RunState.HALTED, "ATTEMPT_BUDGET_EXHAUSTED", active_budget.max_attempts)
