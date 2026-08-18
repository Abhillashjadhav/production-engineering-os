"""Versioned evidence adapters for pytest JSON and language-neutral TAP13."""

from __future__ import annotations

import hashlib
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

    def parse(self, stdout: bytes, stderr: bytes, return_code: int) -> ParsedEvidence: ...


class PytestJsonReportAdapter:
    tool = "pytest"
    evidence_format = "pytest-json-report/v1"

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
            message = str(_mapping(call.get("crash")).get("message", ""))
            if outcome == "passed":
                failure_kind = ""
            elif outcome == "skipped":
                failure_kind = "skip"
            elif "assert" in message.lower():
                failure_kind = "assertion"
            elif any(word in message.lower() for word in ("fixture", "setup", "config")):
                failure_kind = "configuration"
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
        return ParsedEvidence(tuple(nodes))


class Tap13Adapter:
    tool = "node:test"
    evidence_format = "tap13/v1"

    def parse(self, stdout: bytes, stderr: bytes, return_code: int) -> ParsedEvidence:
        try:
            lines = [line.strip() for line in stdout.decode("utf-8").splitlines() if line.strip()]
        except UnicodeDecodeError:
            return ParsedEvidence((), "malformed TAP13 evidence")
        if not lines or lines[0] != "TAP version 13":
            return ParsedEvidence((), "malformed TAP13 evidence")
        plan_values = [match for line in lines if (match := _TAP_PLAN.fullmatch(line))]
        records = [match for line in lines if (match := _TAP_RESULT.fullmatch(line))]
        if len(plan_values) != 1 or int(plan_values[0].group(1)) != len(records) or not records:
            return ParsedEvidence((), "vacuous or inconsistent TAP13 plan")
        raw_digest = _digest(stdout)
        nodes: list[NodeEvidence] = []
        for record in records:
            outcome = "passed" if record.group(1) == "ok" else "failed"
            metadata = {}
            for token in (record.group(3) or "").split():
                key, separator, value = token.partition("=")
                if separator:
                    metadata[key] = value
            failure_kind = "" if outcome == "passed" else metadata.get("kind", "error")
            nodes.append(
                NodeEvidence(
                    node_id=record.group(2),
                    outcome=outcome,
                    failure_kind=failure_kind,
                    assertion_id=metadata.get("assertion", ""),
                    raw_output_digest=raw_digest,
                )
            )
        if return_code == 0 and any(node.outcome == "failed" for node in nodes):
            return ParsedEvidence((), "TAP13 exit code contradicts node outcomes")
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
            self.resolve(expectation.tool, expectation.evidence_format)


def default_adapter_registry() -> EvidenceAdapterRegistry:
    return EvidenceAdapterRegistry((PytestJsonReportAdapter(), Tap13Adapter()))
