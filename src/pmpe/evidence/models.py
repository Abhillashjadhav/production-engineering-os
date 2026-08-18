"""Typed plan expectations, submissions, and adapter-derived node evidence."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from pmpe.contracts.canonical import canonical_digest
from pmpe.execution import ExecutionCommand, ExecutionResult

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_COMMIT = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")


class EvidenceError(ValueError):
    pass


def _valid_node_id(value: str) -> bool:
    return (
        bool(value)
        and len(value.encode("utf-8")) <= 1024
        and all(ord(item) >= 32 for item in value)
    )


@dataclass(frozen=True)
class NodeExpectation:
    node_id: str
    assertion_id: str

    def __post_init__(self) -> None:
        if not _valid_node_id(self.node_id) or not _IDENTIFIER.fullmatch(self.assertion_id):
            raise EvidenceError("node and assertion identifiers must be bounded and canonical")


@dataclass(frozen=True)
class EvidenceExpectation:
    command_id: str
    tool: str
    evidence_format: str
    plan_digest: str
    commit_sha: str
    subject_digest: str
    command: ExecutionCommand
    nodes: tuple[NodeExpectation, ...]

    def __post_init__(self) -> None:
        node_ids = [node.node_id for node in self.nodes]
        if (
            not _IDENTIFIER.fullmatch(self.command_id)
            or not _IDENTIFIER.fullmatch(self.tool)
            or not _IDENTIFIER.fullmatch(self.evidence_format)
            or not _DIGEST.fullmatch(self.plan_digest)
            or not _COMMIT.fullmatch(self.commit_sha)
            or not _DIGEST.fullmatch(self.subject_digest)
            or type(self.command) is not ExecutionCommand
            or not self.nodes
            or any(type(node) is not NodeExpectation for node in self.nodes)
            or len(node_ids) != len(set(node_ids))
        ):
            raise EvidenceError("evidence expectation is malformed or duplicate")


def evidence_plan_digest(expectations: Iterable[EvidenceExpectation]) -> str:
    """Canonical digest of executable expectation content, excluding observations."""
    commands = []
    for expectation in expectations:
        if type(expectation) is not EvidenceExpectation:
            raise EvidenceError("plan contains a malformed evidence expectation")
        commands.append(
            {
                "command": list(expectation.command.argv),
                "command_id": expectation.command_id,
                "evidence_format": expectation.evidence_format,
                "nodes": [
                    {"assertion_id": node.assertion_id, "node_id": node.node_id}
                    for node in expectation.nodes
                ],
                "tool": expectation.tool,
            }
        )
    if not commands:
        raise EvidenceError("vacuous plan has no admitted commands")
    return canonical_digest({"commands": commands})


@dataclass(frozen=True)
class EvidenceSubmission:
    command_id: str
    execution: ExecutionResult
    stdout: bytes
    stderr: bytes

    def __post_init__(self) -> None:
        if (
            not _IDENTIFIER.fullmatch(self.command_id)
            or type(self.execution) is not ExecutionResult
            or type(self.stdout) is not bytes
            or type(self.stderr) is not bytes
        ):
            raise EvidenceError("evidence submission is malformed")


@dataclass(frozen=True)
class NodeEvidence:
    node_id: str
    outcome: str
    failure_kind: str
    assertion_id: str
    raw_output_digest: str


@dataclass(frozen=True)
class ParsedEvidence:
    nodes: tuple[NodeEvidence, ...]
    blocking_failure: str = ""


@dataclass(frozen=True)
class EvidenceDecision:
    authorized: bool
    nodes: tuple[NodeEvidence, ...]
    reasons: tuple[str, ...]
