"""Versioned evidence adapters for pytest JSON and language-neutral TAP13."""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Iterable, Mapping
from typing import Any, Protocol, runtime_checkable

from pmpe.contracts.canonical import CanonicalInputError, strict_loads
from pmpe.evidence.models import (
    EvidenceError,
    EvidenceExpectation,
    NodeEvidence,
    ParsedEvidence,
)
from pmpe.execution import ExecutionCommand

_TAP_RESULT = re.compile(r"(ok|not ok)\s+[0-9]+\s+-\s+(.+?)(?:\s+#\s+(.+))?\Z")
_TAP_PLAN = re.compile(r"1\.\.([0-9]+)\Z")


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


@runtime_checkable
class EvidenceAdapter(Protocol):
    tool: str
    evidence_format: str

    def supports(self, command: ExecutionCommand) -> bool: ...

    def parse(self, stdout: bytes, stderr: bytes, return_code: int) -> ParsedEvidence: ...


class PytestJsonReportAdapter:
    tool = "pytest"
    evidence_format = "pytest-json-report/v1"

    def supports(self, command: ExecutionCommand) -> bool:
        executable = os.path.basename(command.argv[0])
        direct = executable in {"pytest", "py.test"}
        module = executable.startswith("python") and command.argv[1:3] == ("-m", "pytest")
        return (direct or module) and "--json-report" in command.argv

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
            message = str(_mapping(call.get("crash")).get("message", ""))
            setup_message = str(_mapping(setup.get("crash")).get("message", ""))
            if outcome == "passed":
                failure_kind = ""
            elif outcome == "skipped":
                failure_kind = "skip"
            elif setup.get("outcome") == "failed" or any(
                word in (setup_message + message).lower()
                for word in ("fixture", "setup", "config")
            ):
                failure_kind = "configuration"
            elif "assert" in message.lower():
                failure_kind = "assertion"
            else:
                failure_kind = "error"
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
        executable = os.path.basename(command.argv[0])
        reporter = "--test-reporter=tap" in command.argv or any(
            command.argv[index : index + 2] == ("--test-reporter", "tap")
            for index in range(len(command.argv) - 1)
        )
        return executable == "node" and "--test" in command.argv and reporter

    def parse(self, stdout: bytes, stderr: bytes, return_code: int) -> ParsedEvidence:
        if return_code == 124:
            return ParsedEvidence((), "timeout")
        if return_code not in {0, 1}:
            return ParsedEvidence((), "runner error")
        try:
            lines = [line.strip() for line in stdout.decode("utf-8").splitlines() if line.strip()]
        except UnicodeDecodeError:
            return ParsedEvidence((), "malformed TAP13 evidence")
        if not lines or lines[0] != "TAP version 13":
            return ParsedEvidence((), "malformed TAP13 evidence")
        if any(line.lower().startswith("bail out!") for line in lines):
            return ParsedEvidence((), "TAP13 bailout")
        plan_values = [match for line in lines if (match := _TAP_PLAN.fullmatch(line))]
        records = [
            (index, match)
            for index, line in enumerate(lines)
            if (match := _TAP_RESULT.fullmatch(line))
        ]
        if len(plan_values) != 1 or int(plan_values[0].group(1)) != len(records) or not records:
            return ParsedEvidence((), "vacuous or inconsistent TAP13 plan")
        raw_digest = _digest(stdout)
        nodes: list[NodeEvidence] = []
        for record_index, record in records:
            outcome = "passed" if record.group(1) == "ok" else "failed"
            metadata = {}
            for token in (record.group(3) or "").split():
                key, separator, value = token.partition("=")
                if separator:
                    metadata[key] = value
            directive = record.group(3) or ""
            if directive.upper().startswith("SKIP"):
                outcome = "skipped"
                failure_kind = "skip"
                assertion_id = ""
            elif outcome == "passed":
                failure_kind = ""
                assertion_id = metadata.get("assertion", "")
            else:
                failure_kind = metadata.get("kind", "error")
                assertion_id = metadata.get("assertion", "")
                boundary = next(
                    (
                        index
                        for index in range(record_index + 1, len(lines))
                        if _TAP_RESULT.fullmatch(lines[index]) or _TAP_PLAN.fullmatch(lines[index])
                    ),
                    len(lines),
                )
                diagnostics = "\n".join(lines[record_index + 1 : boundary])
                code_match = re.search(r"\bcode:\s*['\"]?([A-Za-z0-9_]+)", diagnostics)
                if code_match and code_match.group(1) == "ERR_ASSERTION":
                    failure_kind = "assertion"
                    assertion_id = code_match.group(1)
            nodes.append(
                NodeEvidence(
                    node_id=record.group(2),
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
                raise EvidenceError(
                    f"declared tool does not match command: {expectation.tool}"
                )


def default_adapter_registry() -> EvidenceAdapterRegistry:
    return EvidenceAdapterRegistry((PytestJsonReportAdapter(), Tap13Adapter()))
