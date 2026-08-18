"""Versioned evidence adapters for pytest JSON and language-neutral TAP13."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Iterator, Mapping
from pathlib import PurePosixPath
from typing import Any, Protocol, runtime_checkable

from pmpe.contracts.canonical import CanonicalInputError, strict_loads
from pmpe.evidence.models import (
    EvidenceError,
    EvidenceExpectation,
    NodeEvidence,
    ParsedEvidence,
)
from pmpe.execution import ExecutionCommand

_TAP_RESULT = re.compile(r"(ok|not ok)\s+([0-9]+)\s+-\s+(.+?)(?:\s+#\s+(.+))?\Z")
_TAP_PLAN = re.compile(r"1\.\.([0-9]+)\Z")
_TAP_ASSERTION_MARKER = re.compile(r"\[assertion:([A-Za-z0-9][A-Za-z0-9._:/-]{0,255})\]")
_TRUSTED_RUNNER_DIRECTORIES = {
    PurePosixPath("/usr/local/bin"),
    PurePosixPath("/usr/bin"),
    PurePosixPath("/bin"),
}


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _property(properties: object, name: str) -> str:
    if not isinstance(properties, list):
        return ""
    values = [
        item[1]
        for item in properties
        if isinstance(item, list)
        and len(item) == 2
        and item[0] == name
        and isinstance(item[1], str)
    ]
    return values[0] if len(values) == 1 else ""


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _pytest_failure_kind(
    test: Mapping[str, Any], call: Mapping[str, Any], setup: Mapping[str, Any]
) -> str:
    if setup.get("outcome") == "failed":
        return "configuration"
    crash = _mapping(call.get("crash"))
    message = crash.get("message", "")
    if not isinstance(message, str):
        return "error"
    normalized = message.strip()
    if re.match(r"(?i)^(?:fixture|setup|configuration|config)\b", normalized):
        return "configuration"
    longrepr = call.get("longrepr", test.get("longrepr", ""))
    traceback_assertion = isinstance(longrepr, str) and any(
        line.lstrip().startswith("E   assert ")
        or re.match(r"^AssertionError(?::|\Z)", line.strip())
        for line in longrepr.splitlines()
    )
    message_assertion = bool(re.match(r"^(?:AssertionError(?::|\Z)|assert(?:\s|\())", normalized))
    return "assertion" if message_assertion or traceback_assertion else "error"


def _leading_spaces(line: str) -> int:
    prefix = line[: len(line) - len(line.lstrip())]
    if "\t" in prefix:
        return -1
    return len(prefix)


def _tap_plan_is_consistent(
    records: list[tuple[int, int, re.Match[str]]],
    plans: list[tuple[int, int, re.Match[str]]],
) -> bool:
    records_by_indent: dict[int, list[tuple[int, int]]] = {}
    for index, indent, result in records:
        records_by_indent.setdefault(indent, []).append((index, int(result.group(2))))
    covered: set[int] = set()
    previous_plan: dict[int, int] = {}
    positions: dict[int, int] = {}
    for plan_index, indent, plan in plans:
        start = previous_plan.get(indent, -1)
        peers = records_by_indent.get(indent, [])
        position = positions.get(indent, 0)
        while position < len(peers) and peers[position][0] <= start:
            position += 1
        scoped_start = position
        while position < len(peers) and peers[position][0] < plan_index:
            position += 1
        scoped = peers[scoped_start:position]
        count = int(plan.group(1))
        if count != len(scoped) or [number for _, number in scoped] != list(range(1, count + 1)):
            return False
        covered.update(index for index, _number in scoped)
        positions[indent] = position
        previous_plan[indent] = plan_index
    return bool(records) and covered == {index for index, _, _ in records}


def _tap_leaf_records(
    records: Iterable[tuple[int, int, re.Match[str]]],
) -> Iterator[tuple[int, int, re.Match[str]]]:
    previous_indent: int | None = None
    for record in records:
        _index, indent, _match = record
        is_parent_summary = previous_indent is not None and previous_indent > indent
        previous_indent = indent
        if not is_parent_summary:
            yield record


def _tap_assertion_id(title: str) -> str:
    matches = _TAP_ASSERTION_MARKER.findall(title)
    return matches[0] if len(matches) == 1 else ""


def _is_trusted_system_runner(resolved_executable: str, names: set[str]) -> bool:
    path = PurePosixPath(resolved_executable)
    return (
        path.is_absolute()
        and ".." not in path.parts
        and path.parent in _TRUSTED_RUNNER_DIRECTORIES
        and path.name in names
    )


@runtime_checkable
class EvidenceAdapter(Protocol):
    tool: str
    evidence_format: str

    def supports(self, command: ExecutionCommand) -> bool: ...

    def supports_execution(self, command: ExecutionCommand, resolved_executable: str) -> bool: ...

    def parse(self, stdout: bytes, stderr: bytes, return_code: int) -> ParsedEvidence: ...


class PytestJsonReportAdapter:
    tool = "pytest"
    evidence_format = "pytest-json-report/v1"

    def supports(self, command: ExecutionCommand) -> bool:
        executable = command.argv[0]
        direct = executable in {"pytest", "py.test"}
        config_files: list[str] = []
        report_files: list[str] = []
        plugins: list[str] = []
        worker_counts: list[str] = []
        distributions: list[str] = []
        worker_restarts: list[str] = []
        malformed_config = False
        unsafe_override = False
        capture_override = False
        for index, argument in enumerate(command.argv):
            if argument in {"-c", "--config-file"}:
                if index + 1 >= len(command.argv):
                    malformed_config = True
                else:
                    config_files.append(command.argv[index + 1])
            elif argument.startswith("-c") and not argument.startswith("--"):
                config_files.append(argument[2:].removeprefix("="))
            elif argument.startswith("--config-file="):
                config_files.append(argument.removeprefix("--config-file="))
            if argument == "--json-report-file":
                if index + 1 >= len(command.argv):
                    malformed_config = True
                else:
                    report_files.append(command.argv[index + 1])
            elif argument.startswith("--json-report-file="):
                report_files.append(argument.removeprefix("--json-report-file="))
            if argument == "-p":
                if index + 1 >= len(command.argv):
                    malformed_config = True
                else:
                    plugins.append(command.argv[index + 1])
            elif argument.startswith("-p") and not argument.startswith("--"):
                plugins.append(argument[2:].removeprefix("="))
            for option, values in (
                ("--dist", distributions),
                ("--max-worker-restart", worker_restarts),
                ("--numprocesses", worker_counts),
            ):
                if argument == option:
                    if index + 1 >= len(command.argv):
                        malformed_config = True
                    else:
                        values.append(command.argv[index + 1])
                elif argument.startswith(option + "="):
                    values.append(argument.removeprefix(option + "="))
            if argument == "-n":
                if index + 1 >= len(command.argv):
                    malformed_config = True
                else:
                    worker_counts.append(command.argv[index + 1])
            elif argument.startswith("-n") and not argument.startswith("--"):
                worker_counts.append(argument[2:].removeprefix("="))
            if (
                argument in {"-o", "--override-ini"}
                or (argument.startswith("-o") and not argument.startswith("--"))
                or argument.startswith("--override-ini=")
            ):
                unsafe_override = True
            if (
                argument == "--capture"
                or argument.startswith("--capture=")
                or (
                    argument.startswith("-")
                    and not argument.startswith("--")
                    and "s" in argument[1:]
                )
            ):
                capture_override = True
        return (
            direct
            and not malformed_config
            and not unsafe_override
            and not capture_override
            and command.argv.count("--json-report") == 1
            and command.argv.count("--noconftest") == 1
            and config_files == ["/dev/null"]
            and report_files == ["/dev/stdout"]
            and plugins == ["no:terminal", "xdist.plugin"]
            and worker_counts == ["1"]
            and distributions == ["loadscope"]
            and worker_restarts == ["0"]
            and not any(
                argument == "--tx" or argument.startswith("--tx=") for argument in command.argv[1:]
            )
            and not any(argument.startswith("@") for argument in command.argv[1:])
        )

    def supports_execution(self, command: ExecutionCommand, resolved_executable: str) -> bool:
        return self.supports(command) and _is_trusted_system_runner(
            resolved_executable, {command.argv[0]}
        )

    def parse(self, stdout: bytes, stderr: bytes, return_code: int) -> ParsedEvidence:
        raw_digest = _digest(stdout)
        if return_code == 124:
            return ParsedEvidence((), "timeout")
        try:
            report = strict_loads(stdout)
        except (CanonicalInputError, UnicodeError):
            return ParsedEvidence((), "malformed pytest evidence")
        exitcode = report.get("exitcode")
        if type(exitcode) is not int or exitcode != return_code:
            return ParsedEvidence((), "pytest exit code mismatch")
        if exitcode == 4:
            return ParsedEvidence((), "usage failure")
        if exitcode == 3:
            return ParsedEvidence((), "internal failure")
        collectors = report.get("collectors", [])
        if exitcode == 2 or (
            isinstance(collectors, list)
            and any(_mapping(item).get("outcome") == "failed" for item in collectors)
        ):
            return ParsedEvidence((), "collection failure")
        tests = report.get("tests")
        if not isinstance(tests, list) or not tests:
            return ParsedEvidence((), "vacuous pytest result")
        nodes: list[NodeEvidence] = []
        for item in tests:
            test = _mapping(item)
            node_id = test.get("nodeid")
            outcome = test.get("outcome")
            assertion_id = _property(test.get("user_properties"), "assertion_id")
            if not isinstance(node_id, str) or outcome not in {"passed", "failed", "skipped"}:
                return ParsedEvidence((), "malformed pytest node result")
            call = _mapping(test.get("call"))
            setup = _mapping(test.get("setup"))
            teardown = _mapping(test.get("teardown"))
            if teardown.get("outcome") == "failed":
                return ParsedEvidence((), f"pytest teardown failure: {node_id}")
            if outcome == "passed":
                failure_kind = ""
            elif outcome == "skipped":
                failure_kind = "skip"
            else:
                failure_kind = _pytest_failure_kind(test, call, setup)
                if failure_kind == "assertion":
                    crash = _mapping(call.get("crash"))
                    message = crash.get("message", "")
                    diagnostics = message if isinstance(message, str) else ""
                    diagnostic_assertions = set(_TAP_ASSERTION_MARKER.findall(diagnostics))
                    if not assertion_id or diagnostic_assertions != {assertion_id}:
                        assertion_id = ""
            nodes.append(
                NodeEvidence(
                    node_id=node_id,
                    outcome=outcome,
                    failure_kind=failure_kind,
                    assertion_id=assertion_id,
                    raw_output_digest=raw_digest,
                )
            )
        if exitcode == 0 and any(node.outcome == "failed" for node in nodes):
            return ParsedEvidence((), "pytest success contradicts failed node")
        if exitcode == 1 and not any(node.outcome == "failed" for node in nodes):
            return ParsedEvidence((), "pytest runner error without failed node")
        return ParsedEvidence(tuple(nodes))


class Tap13Adapter:
    tool = "node:test"
    evidence_format = "tap13/v1"

    def supports(self, command: ExecutionCommand) -> bool:
        reporters: list[str] = []
        destinations: list[str] = []
        malformed = False
        unsafe_loader = False
        loader_options = {
            "--env-file",
            "--env-file-if-exists",
            "--experimental-loader",
            "--import",
            "--loader",
            "--require",
        }
        index = 1
        while index < len(command.argv):
            argument = command.argv[index]
            if (
                argument in loader_options
                or any(argument.startswith(option + "=") for option in loader_options)
                or argument == "-r"
                or (argument.startswith("-r") and not argument.startswith("--"))
            ):
                unsafe_loader = True
            if argument in {"--test-reporter", "--test-reporter-destination"}:
                if index + 1 >= len(command.argv):
                    malformed = True
                    break
                target = reporters if argument == "--test-reporter" else destinations
                target.append(command.argv[index + 1])
                index += 2
                continue
            if argument.startswith("--test-reporter="):
                reporters.append(argument.removeprefix("--test-reporter="))
            elif argument.startswith("--test-reporter-destination="):
                destinations.append(argument.removeprefix("--test-reporter-destination="))
            index += 1
        return (
            command.argv[0] == "node"
            and "--test" in command.argv
            and not malformed
            and not unsafe_loader
            and reporters == ["tap"]
            and not destinations
        )

    def supports_execution(self, command: ExecutionCommand, resolved_executable: str) -> bool:
        return self.supports(command) and _is_trusted_system_runner(resolved_executable, {"node"})

    def parse(self, stdout: bytes, stderr: bytes, return_code: int) -> ParsedEvidence:
        if return_code == 124:
            return ParsedEvidence((), "timeout")
        if return_code not in {0, 1}:
            return ParsedEvidence((), "runner error")
        try:
            lines = [line for line in stdout.decode("utf-8").splitlines() if line.strip()]
        except UnicodeDecodeError:
            return ParsedEvidence((), "malformed TAP13 evidence")
        if not lines or lines[0].strip() != "TAP version 13":
            return ParsedEvidence((), "malformed TAP13 evidence")
        if any(line.strip().lower().startswith("bail out!") for line in lines):
            return ParsedEvidence((), "TAP13 bailout")
        if any(_leading_spaces(line) < 0 for line in lines):
            return ParsedEvidence((), "malformed TAP13 indentation")
        plans = [
            (index, _leading_spaces(line), match)
            for index, line in enumerate(lines)
            if (match := _TAP_PLAN.fullmatch(line.strip()))
        ]
        records = [
            (index, _leading_spaces(line), match)
            for index, line in enumerate(lines)
            if (match := _TAP_RESULT.fullmatch(line.strip()))
        ]
        if not _tap_plan_is_consistent(records, plans):
            return ParsedEvidence((), "vacuous or inconsistent TAP13 plan")
        raw_digest = _digest(stdout)
        nodes: list[NodeEvidence] = []
        next_boundary = len(lines)
        boundaries: dict[int, int] = {}
        for index in range(len(lines) - 1, -1, -1):
            boundaries[index] = next_boundary
            stripped = lines[index].strip()
            if _TAP_RESULT.fullmatch(stripped) or _TAP_PLAN.fullmatch(stripped):
                next_boundary = index
        for record_index, _indent, record in _tap_leaf_records(records):
            outcome = "passed" if record.group(1) == "ok" else "failed"
            title = record.group(3)
            assertion_id = _tap_assertion_id(title)
            directive = record.group(4) or ""
            if directive.upper().startswith("SKIP"):
                outcome = "skipped"
                failure_kind = "skip"
                assertion_id = ""
            elif directive.upper().startswith("TODO"):
                outcome = "skipped"
                failure_kind = "todo"
                assertion_id = ""
            elif outcome == "passed":
                failure_kind = ""
            else:
                boundary = boundaries[record_index]
                diagnostics = "\n".join(lines[record_index + 1 : boundary])
                code_match = re.search(r"\bcode:\s*['\"]?([A-Za-z0-9_]+)", diagnostics)
                diagnostic_assertions = set(_TAP_ASSERTION_MARKER.findall(diagnostics))
                failure_kind = (
                    "assertion"
                    if code_match
                    and code_match.group(1) == "ERR_ASSERTION"
                    and assertion_id
                    and diagnostic_assertions == {assertion_id}
                    else "error"
                )
            nodes.append(
                NodeEvidence(
                    node_id=title,
                    outcome=outcome,
                    failure_kind=failure_kind,
                    assertion_id=assertion_id,
                    raw_output_digest=raw_digest,
                )
            )
        if return_code == 0 and any(node.outcome == "failed" for node in nodes):
            return ParsedEvidence((), "TAP13 exit code contradicts node outcomes")
        if return_code == 1 and not any(node.outcome == "failed" for node in nodes):
            return ParsedEvidence((), "TAP13 runner error without failed node")
        return ParsedEvidence(tuple(nodes))


class EvidenceAdapterRegistry:
    def __init__(self, adapters: Iterable[EvidenceAdapter]) -> None:
        self._adapters: dict[tuple[str, str], EvidenceAdapter] = {}
        for adapter in adapters:
            if not isinstance(adapter, EvidenceAdapter):
                raise EvidenceError("evidence adapter does not satisfy its protocol")
            key = (adapter.tool, adapter.evidence_format)
            if key in self._adapters:
                raise EvidenceError("duplicate tool/evidence-format adapter")
            self._adapters[key] = adapter

    def resolve(self, tool: str, evidence_format: str) -> EvidenceAdapter:
        try:
            return self._adapters[(tool, evidence_format)]
        except KeyError as exc:
            raise EvidenceError(
                f"unsupported tool/evidence-format combination: {tool}/{evidence_format}"
            ) from exc

    def validate_expectations(self, expectations: Iterable[EvidenceExpectation]) -> None:
        for expectation in expectations:
            adapter = self.resolve(expectation.tool, expectation.evidence_format)
            if not adapter.supports(expectation.command):
                raise EvidenceError(f"declared tool does not match command: {expectation.tool}")


def default_adapter_registry() -> EvidenceAdapterRegistry:
    return EvidenceAdapterRegistry((PytestJsonReportAdapter(), Tap13Adapter()))
