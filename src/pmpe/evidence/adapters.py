"""Versioned evidence adapters for pytest JSON and language-neutral TAP13."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
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
_TAP_ASSERTION_MARKER = re.compile(
    r"(?:^|\s)\[assertion:([A-Za-z0-9][A-Za-z0-9._:/-]{0,255})\](?=\s|\Z)"
)
_PYTHON_RUNNER = re.compile(r"python(?:3(?:\.[0-9]+)?)?\Z")
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
    covered: set[int] = set()
    previous_plan: dict[int, int] = {}
    for plan_index, indent, plan in plans:
        start = previous_plan.get(indent, -1)
        scoped = [
            (index, result)
            for index, result_indent, result in records
            if result_indent == indent and start < index < plan_index
        ]
        count = int(plan.group(1))
        if count != len(scoped) or [int(result.group(2)) for _, result in scoped] != list(
            range(1, count + 1)
        ):
            return False
        covered.update(index for index, _ in scoped)
        previous_plan[indent] = plan_index
    return bool(records) and covered == {index for index, _, _ in records}


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
        module = bool(_PYTHON_RUNNER.fullmatch(executable)) and command.argv[1:3] == (
            "-m",
            "pytest",
        )
        return (direct or module) and "--json-report" in command.argv

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
            if outcome == "passed":
                failure_kind = ""
            elif outcome == "skipped":
                failure_kind = "skip"
            else:
                failure_kind = _pytest_failure_kind(test, call, setup)
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
        return ParsedEvidence(tuple(nodes))


class Tap13Adapter:
    tool = "node:test"
    evidence_format = "tap13/v1"

    def supports(self, command: ExecutionCommand) -> bool:
        reporter = "--test-reporter=tap" in command.argv or any(
            command.argv[index : index + 2] == ("--test-reporter", "tap")
            for index in range(len(command.argv) - 1)
        )
        return command.argv[0] == "node" and "--test" in command.argv and reporter

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
        for record_index, indent, record in records:
            previous_peer = max(
                (
                    index
                    for index, record_indent, _ in records
                    if record_indent == indent and index < record_index
                ),
                default=-1,
            )
            if any(
                previous_peer < child_index < record_index and child_indent > indent
                for child_index, child_indent, _ in records
            ):
                continue
            outcome = "passed" if record.group(1) == "ok" else "failed"
            title = record.group(3)
            assertion_id = _tap_assertion_id(title)
            directive = record.group(4) or ""
            if directive.upper().startswith("SKIP"):
                outcome = "skipped"
                failure_kind = "skip"
                assertion_id = ""
            elif outcome == "passed":
                failure_kind = ""
            else:
                boundary = next(
                    (
                        index
                        for index, boundary_line in enumerate(
                            lines[record_index + 1 :], start=record_index + 1
                        )
                        if _leading_spaces(boundary_line) <= indent
                        and (
                            _TAP_RESULT.fullmatch(boundary_line.strip())
                            or _TAP_PLAN.fullmatch(boundary_line.strip())
                        )
                    ),
                    len(lines),
                )
                diagnostics = "\n".join(lines[record_index + 1 : boundary])
                code_match = re.search(r"\bcode:\s*['\"]?([A-Za-z0-9_]+)", diagnostics)
                failure_kind = (
                    "assertion"
                    if code_match and code_match.group(1) == "ERR_ASSERTION" and assertion_id
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
