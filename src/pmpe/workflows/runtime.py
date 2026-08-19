"""Fixed deterministic kernel for executing compiled business decisions."""

from __future__ import annotations

import html
import os
import tempfile
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pmpe.contracts.canonical import canonical_digest, canonical_json_bytes
from pmpe.workflows.decision import DecisionContract
from pmpe.workflows.support import SupportCase


class WorkflowEvidenceError(ValueError):
    """Raised when plan or evidence bindings are missing or inconsistent."""


def _trusted_contract(case: SupportCase, contract: DecisionContract) -> bool:
    """Resolve verification from runtime-owned configuration, never caller input."""
    if contract.vertical != "customer_support":
        return False
    from pmpe.workflows.support_discovery import CustomerSupportDiscoveryAdapter

    return CustomerSupportDiscoveryAdapter().verify(case, contract)


@dataclass(frozen=True)
class WorkflowNode:
    node_id: str
    operation: str
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class ExecutableWorkflowPlan:
    schema_version: str
    contract_digest: str
    input_digest: str
    nodes: tuple[WorkflowNode, ...]
    plan_digest: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def digest_is_valid(self) -> bool:
        payload = self.as_dict()
        claimed = str(payload.pop("plan_digest"))
        return claimed == canonical_digest(payload)


@dataclass(frozen=True)
class StepEvidence:
    node_id: str
    operation: str
    input_digest: str
    output_digest: str


@dataclass(frozen=True)
class WorkflowReport:
    schema_version: str
    case_id: str
    selected_action: str
    status: str
    input_digest: str
    contract_digest: str
    plan_digest: str
    execution_digest: str
    step_evidence: tuple[StepEvidence, ...]
    unresolved_questions: tuple[str, ...]
    evidence_complete: bool
    report_digest: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.as_dict())


@dataclass(frozen=True)
class WorkflowReportPaths:
    json_path: Path
    markdown_path: Path


def compile_workflow(contract: DecisionContract) -> ExecutableWorkflowPlan:
    if not contract.digest_is_valid():
        raise WorkflowEvidenceError("decision contract digest is invalid")
    nodes = (
        WorkflowNode("WF-001", "bind_visible_facts", contract.action_fact_refs),
        WorkflowNode("WF-002", "apply_named_rules", contract.action_rule_refs),
        WorkflowNode("WF-003", "emit_bounded_decision", (contract.selected_action,)),
    )
    payload = {
        "contract_digest": contract.contract_digest,
        "input_digest": contract.input_digest,
        "nodes": [asdict(item) for item in nodes],
        "schema_version": "1.0.0",
    }
    return ExecutableWorkflowPlan(
        schema_version="1.0.0",
        contract_digest=contract.contract_digest,
        input_digest=contract.input_digest,
        nodes=nodes,
        plan_digest=canonical_digest(payload),
    )


def _execution_steps(
    contract: DecisionContract, plan: ExecutableWorkflowPlan
) -> tuple[StepEvidence, ...]:
    previous = plan.input_digest
    steps: list[StepEvidence] = []
    for node in plan.nodes:
        output = canonical_digest(
            {
                "contract_digest": contract.contract_digest,
                "evidence_refs": list(node.evidence_refs),
                "input_digest": previous,
                "node_id": node.node_id,
                "operation": node.operation,
            }
        )
        steps.append(StepEvidence(node.node_id, node.operation, previous, output))
        previous = output
    return tuple(steps)


def execute_workflow(
    case: SupportCase,
    contract: DecisionContract,
    plan: ExecutableWorkflowPlan,
) -> WorkflowReport:
    input_digest = canonical_digest(case.as_dict())
    if input_digest != contract.input_digest or input_digest != plan.input_digest:
        raise WorkflowEvidenceError("input digest does not match visible case")
    if case.case_id != contract.case_id:
        raise WorkflowEvidenceError("contract case identity does not match visible case")
    if not contract.digest_is_valid() or contract.contract_digest != plan.contract_digest:
        raise WorkflowEvidenceError("contract digest does not match executable plan")
    if not _trusted_contract(case, contract):
        raise WorkflowEvidenceError("decision contract is not independently authorized")
    if not plan.digest_is_valid():
        raise WorkflowEvidenceError("plan digest is invalid")
    if plan != compile_workflow(contract):
        raise WorkflowEvidenceError("plan contents differ from deterministic compilation")
    steps = _execution_steps(contract, plan)
    execution_digest = canonical_digest(
        {
            "contract_digest": contract.contract_digest,
            "plan_digest": plan.plan_digest,
            "selected_action": contract.selected_action,
            "steps": [asdict(item) for item in steps],
        }
    )
    status = "NEEDS_HUMAN_DECISION" if contract.status == "NEEDS_HUMAN_DECISION" else "COMPLETED"
    payload: dict[str, Any] = {
        "case_id": case.case_id,
        "contract_digest": contract.contract_digest,
        "evidence_complete": True,
        "execution_digest": execution_digest,
        "input_digest": input_digest,
        "plan_digest": plan.plan_digest,
        "schema_version": "1.0.0",
        "selected_action": contract.selected_action,
        "status": status,
        "step_evidence": [asdict(item) for item in steps],
        "unresolved_questions": list(contract.unresolved_questions),
    }
    return WorkflowReport(
        schema_version="1.0.0",
        case_id=case.case_id,
        selected_action=contract.selected_action,
        status=status,
        input_digest=input_digest,
        contract_digest=contract.contract_digest,
        plan_digest=plan.plan_digest,
        execution_digest=execution_digest,
        step_evidence=steps,
        unresolved_questions=contract.unresolved_questions,
        evidence_complete=True,
        report_digest=canonical_digest(payload),
    )


def verify_workflow_report(
    case: SupportCase,
    contract: DecisionContract,
    plan: ExecutableWorkflowPlan,
    report: WorkflowReport,
) -> bool:
    try:
        expected = execute_workflow(case, contract, plan)
    except WorkflowEvidenceError:
        return False
    return report == expected and report.canonical_bytes() == expected.canonical_bytes()


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        with suppress(FileNotFoundError):
            os.unlink(temporary)
        raise


def write_workflow_report(
    root: Path,
    case: SupportCase,
    contract: DecisionContract,
    plan: ExecutableWorkflowPlan,
    report: WorkflowReport,
) -> WorkflowReportPaths:
    if not verify_workflow_report(case, contract, plan, report):
        raise WorkflowEvidenceError("unverified report cannot be persisted as complete")
    json_path = Path(root) / "workflow-report.json"
    markdown_path = Path(root) / "workflow-report.md"
    questions = "\n".join(
        f"  - <code>{html.escape(question).replace(chr(10), '&#10;')}</code>"
        for question in report.unresolved_questions
    )
    if not questions:
        questions = "  - none"
    markdown = (
        f"# Workflow result: {report.case_id}\n\n"
        f"- Status: {report.status}\n"
        f"- Selected action: {report.selected_action}\n"
        f"- Evidence complete: {'yes' if report.evidence_complete else 'no'}\n"
        f"- Unresolved questions:\n{questions}\n"
        f"- Input: `{report.input_digest}`\n"
        f"- Contract: `{report.contract_digest}`\n"
        f"- Plan: `{report.plan_digest}`\n"
        f"- Execution: `{report.execution_digest}`\n"
        f"- Report: `{report.report_digest}`\n"
    ).encode()
    _write_atomic(json_path, report.canonical_bytes() + b"\n")
    _write_atomic(markdown_path, markdown)
    return WorkflowReportPaths(json_path, markdown_path)
