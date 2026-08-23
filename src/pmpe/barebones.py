"""Minimal contract-to-RELEASE_READY runtime with no deployment dependency."""

from __future__ import annotations

import hashlib
import json
import math
import operator as comparison
import re
import shutil
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
from pmpe.contracts.canonical import CanonicalInputError, canonical_digest, strict_loads
from pmpe.domain.errors import ContractViolation
from pmpe.evals.barebones_drift import observe_provider_behavior
from pmpe.evidence.ledger import EvidenceLedger
from pmpe.model_provider import ModelProvider


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
_PYTEST_RESULT_PREFIX = "__PMPE_PYTEST_RESULT__:"

_PROVIDER_ERROR_CODE = re.compile(r"[A-Z][A-Z0-9_]*\Z")


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
        executable_root = Path(sys.executable).resolve().parent.parent
        candidates = {
            Path("/usr"),
            Path("/bin"),
            Path("/sbin"),
            Path("/lib"),
            Path("/lib64"),
            Path(sys.base_prefix).resolve(),
            Path(sys.prefix).resolve(),
            executable_root,
        }
        return tuple(sorted((item for item in candidates if item.exists()), key=str))

    @staticmethod
    def _parent_directories(path: Path) -> tuple[str, ...]:
        parents: list[str] = []
        current = path.parent
        while current != Path("/"):
            parents.append(str(current))
            current = current.parent
        return tuple(reversed(parents))

    def run(
        self,
        workspace: Path,
        argv: Sequence[str],
        *,
        timeout_seconds: float,
        environment: Mapping[str, str],
    ) -> subprocess.CompletedProcess[str]:
        sandbox = shutil.which(self.executable, path=_SANDBOX_PATH)
        limiter = shutil.which(self.limiter, path=_SANDBOX_PATH)
        if sandbox is None or limiter is None:
            raise ContractInvalidError("candidate OS sandbox is unavailable")
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
        for runtime_root in self._runtime_roots():
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
        for host_path in (
            "/etc/alternatives",
            "/etc/group",
            "/etc/ld.so.cache",
            "/etc/ld.so.conf",
            "/etc/ld.so.conf.d",
            "/etc/localtime",
            "/etc/nsswitch.conf",
            "/etc/passwd",
        ):
            sandbox_argv.extend(("--ro-bind-try", host_path, host_path))
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
        sandbox_argv.extend(("--chdir", "/workspace", "--", *argv))
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
                completed = subprocess.run(
                    command,
                    cwd=workspace,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    timeout=timeout_seconds,
                    check=False,
                    env={"LC_ALL": "C", "PATH": _SANDBOX_PATH},
                )
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
        decoded = subprocess.CompletedProcess[str](
            completed.args,
            completed.returncode,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )
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


def _path(value: Any, dotted_path: str) -> Any:
    current = value
    for part in dotted_path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            raise KeyError(dotted_path)
        current = current[part]
    return current


def _assertion_passes(assertion: PropertyAssertion, value: Any) -> bool:
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
        return isinstance(left, str) and isinstance(right, str) and bool(re.search(right, left))

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
            return binary[assertion.operator](actual, assertion.value)
        except (TypeError, re.error):
            return False
    unary = {
        Operator.IS_TRUE: actual is True,
        Operator.IS_FALSE: actual is False,
        Operator.IS_NULL: actual is None,
        Operator.NOT_NULL: actual is not None,
    }
    return unary[assertion.operator]


def _run_action(
    workspace: Path,
    target: str,
    arguments: Mapping[str, Any],
    sandbox: CandidateSandbox,
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
        timeout_seconds=_ACTION_TIMEOUT_SECONDS,
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
        raise ContractInvalidError("action failed before an assertion: " + completed.stderr.strip())
    try:
        value = json.loads(
            completed.stdout,
            parse_constant=_reject_non_json_constant,
        )
        canonical_digest(value)
        return value
    except (json.JSONDecodeError, ValueError) as exc:
        raise ContractInvalidError("action did not return one JSON value") from exc


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
) -> tuple[Finding, ...]:
    protected_paths = frozenset(
        {
            *(relative for relative in template.files if relative.startswith("tests/")),
            *((criterion.human_test.path,) if criterion.human_test is not None else ()),
        }
    )
    if criterion.form == "satisfied_by_template":
        assert criterion.template_proof is not None
        proof = template.proofs[criterion.template_proof.test_id]
        proof_path = _safe_path(workspace, proof.path)
        digest = "sha256:" + hashlib.sha256(proof_path.read_bytes()).hexdigest()
        if digest != criterion.template_proof.file_digest:
            raise ContractInvalidError("template proof file does not match its compiled digest")
        if not _run_pytest_node(workspace, proof, protected_paths, sandbox):
            return (
                Finding(
                    "ASSERTION_FAILED",
                    criterion.criterion_id,
                    "template acceptance proof failed",
                    (proof.path,),
                ),
            )
        return ()
    if criterion.form == "human_test":
        assert criterion.human_test is not None
        human_test = TemplateTest(
            criterion.human_test.path,
            criterion.human_test.node_id,
            criterion.human_test.command,
        )
        if _run_pytest_node(workspace, human_test, protected_paths, sandbox):
            return ()
        return (
            Finding(
                "ASSERTION_FAILED",
                criterion.criterion_id,
                "human-authored acceptance assertion failed",
                (criterion.human_test.path,),
            ),
        )
    if criterion.form == "measure":
        assert criterion.operator is not None
        assert criterion.minimum_sample is not None
        target = template.measures[criterion.measure]
        observation = _run_action(workspace, target, {}, sandbox)
        if not isinstance(observation, Mapping):
            raise ContractInvalidError("measure did not return a JSON object")
        sample_size = observation.get("sample_size")
        if isinstance(sample_size, bool) or not isinstance(sample_size, int):
            raise ContractInvalidError("measure did not return an integer sample_size")
        assertion = PropertyAssertion("value", criterion.operator, criterion.value)
        if sample_size >= criterion.minimum_sample and _assertion_passes(assertion, observation):
            return ()
        module = target.split(":", maxsplit=1)[0].replace(".", "/") + ".py"
        return (
            Finding(
                "ASSERTION_FAILED",
                criterion.criterion_id,
                "compiled measure assertion failed",
                (module,),
            ),
        )
    assert criterion.when is not None
    if any(not _assertion_passes(item, template.context) for item in criterion.given):
        raise ContractInvalidError(f"{criterion.criterion_id}: Given precondition is false")
    target = template.actions[criterion.when.action]
    result = _run_action(workspace, target, criterion.when.arguments, sandbox)
    wrapped = {"result": result}
    if all(_assertion_passes(item, wrapped) for item in criterion.then):
        return ()
    module = target.split(":", maxsplit=1)[0].replace(".", "/") + ".py"
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
) -> tuple[Finding, ...]:
    """Verify each criterion against a fresh disposable copy of the exact snapshot."""

    findings: list[Finding] = []
    for criterion in plan.criteria:
        with tempfile.TemporaryDirectory(prefix="pmpe-verification-") as temporary:
            isolated = Path(temporary)
            _materialize_snapshot(isolated, snapshot)
            try:
                findings.extend(
                    _criterion_findings(
                        criterion,
                        workspace=isolated,
                        template=template,
                        sandbox=sandbox,
                    )
                )
            except ContractInvalidError as exc:
                if criterion.human_test is None:
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
    return {
        str(path.relative_to(workspace)): path.read_bytes()
        for path in sorted(workspace.rglob("*"))
        if path.is_file()
    }


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
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                counters[target] += value
        estimated = usage.get("estimated_cost_usd")
        if estimated is not None:
            if (
                not isinstance(estimated, (int, float))
                or isinstance(estimated, bool)
                or not math.isfinite(float(estimated))
                or estimated < 0
            ):
                raise RuntimeError("MODEL_PROVIDER_USAGE_INVALID")
            counters["estimated_cost_usd"] += float(estimated)
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
) -> RunResult:
    """Run the frozen core. It never deploys and stops at RELEASE_READY."""

    started = time.monotonic()
    active_template = template or default_template()
    active_budget = budget or BudgetCaps()
    active_sandbox = candidate_sandbox or BubblewrapCandidateSandbox()
    counters: dict[str, Any] = {
        "calls": 0,
        "bytes": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "estimated_cost_usd": 0.0,
        "provider_model_id": "",
        "structured_criteria_count": 0,
        "human_test_count": 0,
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

    template_test_digests: dict[str, str] = {}
    for test_id, proof in active_template.proofs.items():
        _safe_path(workspace, proof.path)
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

    plan = compile_acceptance_plan(
        contract,
        repository_root=repository_root,
        registered_actions=frozenset(active_template.actions),
        template_version=active_template.version,
        template_test_digests=template_test_digests,
        registered_measures=frozenset(active_template.measures),
        trusted_test_digests=trusted_test_digests,
    )
    counters["structured_criteria_count"] = sum(item.form != "human_test" for item in plan.criteria)
    counters["human_test_count"] = sum(item.form == "human_test" for item in plan.criteria)
    workspace_root = workspace.resolve()
    evidence_root = (repository_root / ".pmpe").resolve()
    if workspace_root.is_relative_to(evidence_root) or evidence_root.is_relative_to(workspace_root):
        raise ContractInvalidError("candidate workspace must not overlap evidence storage")
    if workspace.exists() and (not workspace.is_dir() or any(workspace.iterdir())):
        raise ContractInvalidError("candidate workspace must be empty")
    workspace.mkdir(parents=True, exist_ok=True)
    ledger = EvidenceLedger(repository_root, run_id)

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
        },
    )
    if stop_requested():
        ledger.append(
            event_type="stopped",
            state=RunState.STOPPED,
            subject_digest=subject_digest,
            payload={"cause": "STOP_REQUESTED", "telemetry": _terminal_telemetry()},
        )
        return finish(RunState.STOPPED, "STOP_REQUESTED", 0)

    _write_files(workspace, active_template.files)
    protected_tests = {
        _safe_path(workspace, proof.path) for proof in active_template.proofs.values()
    }
    for relative, digest in plan.trusted_test_digests:
        trusted_path = _safe_path(workspace, relative)
        observed = "sha256:" + hashlib.sha256(trusted_path.read_bytes()).hexdigest()
        if observed != digest:
            raise ContractInvalidError("trusted test support does not match its compiled digest")
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
    baseline = _verify_snapshot(
        plan,
        _workspace_snapshot(workspace),
        active_template,
        active_sandbox,
    )
    non_template = tuple(item for item in plan.criteria if item.form != "satisfied_by_template")
    failed_ids = {item.subject_id for item in baseline}
    if any(item.code != "ASSERTION_FAILED" for item in baseline) or failed_ids != {
        item.criterion_id for item in non_template
    }:
        raise ContractInvalidError("baseline must fail every non-template criterion by assertion")
    baseline_blob = ledger.put_blob(
        json.dumps(
            [asdict(item) for item in baseline], sort_keys=True, separators=(",", ":")
        ).encode()
    )
    ledger.append(
        event_type="meaningful_red_confirmed",
        state=RunState.BUILDING,
        subject_digest=subject_digest,
        blob_digests=(baseline_blob,),
        payload={"findings": [asdict(item) for item in baseline]},
    )

    findings: tuple[Finding, ...] = baseline
    previous_finding_digest = ""
    for attempt in range(1, active_budget.max_attempts + 1):
        if stop_requested():
            ledger.append(
                event_type="stopped",
                state=RunState.STOPPED,
                subject_digest=subject_digest,
                payload={"cause": "STOP_REQUESTED", "telemetry": _terminal_telemetry()},
            )
            return finish(RunState.STOPPED, "STOP_REQUESTED", attempt - 1)
        request = _model_request(
            contract=contract,
            plan=plan,
            workspace=workspace,
            findings=findings,
        )
        try:
            response = _invoke_bound(
                provider,
                purpose="code",
                request=request,
                budget=active_budget,
                counters=counters,
            )
        except RuntimeError as exc:
            cause = _classify_provider_error(exc)
            ledger.append(
                event_type="halted",
                state=RunState.HALTED,
                subject_digest=subject_digest,
                payload={"cause": cause, "telemetry": _terminal_telemetry()},
            )
            return finish(RunState.HALTED, cause, attempt - 1)
        files = response.get("files")
        if not isinstance(files, Mapping):
            ledger.append(
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
        except ValueError:
            ledger.append(
                event_type="halted",
                state=RunState.HALTED,
                subject_digest=subject_digest,
                payload={"cause": "CODER_RESPONSE_INVALID", "telemetry": _terminal_telemetry()},
            )
            return finish(RunState.HALTED, "CODER_RESPONSE_INVALID", attempt)
        if protected_tests.intersection(response_paths):
            ledger.append(
                event_type="halted",
                state=RunState.HALTED,
                subject_digest=subject_digest,
                payload={"cause": "CODER_MODIFIED_EVIDENCE", "telemetry": _terminal_telemetry()},
            )
            return finish(RunState.HALTED, "CODER_MODIFIED_EVIDENCE", attempt)
        try:
            changed = _write_files(workspace, files)
        except ValueError:
            ledger.append(
                event_type="halted",
                state=RunState.HALTED,
                subject_digest=subject_digest,
                payload={"cause": "CODER_RESPONSE_INVALID", "telemetry": _terminal_telemetry()},
            )
            return finish(RunState.HALTED, "CODER_RESPONSE_INVALID", attempt)
        coder_blob = ledger.put_blob(
            json.dumps(response, sort_keys=True, separators=(",", ":")).encode()
        )
        coder_payload: dict[str, Any] = {"attempt": attempt, "changed": list(changed)}
        coder_behavior = _provider_behavior_payload("code", response)
        if coder_behavior is not None:
            coder_payload["provider_behavior"] = coder_behavior
        ledger.append(
            event_type="coder_completed",
            state=RunState.BUILDING,
            subject_digest=subject_digest,
            blob_digests=(coder_blob,),
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
            ledger.append(
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

        verification_snapshot = _workspace_snapshot(workspace)
        security = _security_findings(workspace)
        blocking_security = tuple(
            item for item in security if item.code.startswith(("CRITICAL_", "HIGH_"))
        )
        if blocking_security:
            findings = blocking_security
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
            try:
                findings = _verify_snapshot(
                    plan,
                    verification_snapshot,
                    active_template,
                    active_sandbox,
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
            if not findings:
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
                review_body = {
                    "contract_digest": subject_digest,
                    "plan_digest": plan.plan_digest,
                    "evidence_digest": blob,
                    "instruction": "Return one non-blocking advisory annotation.",
                }
                review_request = {
                    **review_body,
                    "request_digest": canonical_digest(review_body),
                }
                try:
                    annotation = _invoke_bound(
                        provider,
                        purpose="advisory_review",
                        request=review_request,
                        budget=active_budget,
                        counters=counters,
                    )
                except RuntimeError as exc:
                    annotation = {"status": "unavailable", "cause": _classify_provider_error(exc)}
                release_payload: dict[str, Any] = {
                    "annotation": dict(annotation),
                    "candidate_digest": candidate_blob,
                    "telemetry": _terminal_telemetry(),
                }
                advisory_behavior = _provider_behavior_payload("advisory_review", annotation)
                if advisory_behavior is not None:
                    release_payload["provider_behavior"] = advisory_behavior
                ledger.append(
                    event_type="release_ready",
                    state=RunState.RELEASE_READY,
                    subject_digest=subject_digest,
                    blob_digests=(blob, candidate_blob, *candidate_file_blobs),
                    payload=release_payload,
                )
                return finish(RunState.RELEASE_READY, "PASS", attempt, annotation)
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

    ledger.append(
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
