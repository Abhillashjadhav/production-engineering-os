"""Typed contracts and evidence for personal workflow execution."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from pmpe.contracts.canonical import canonical_digest, canonical_json_bytes


class PersonalContractError(ValueError):
    """Raised when personal-work truth is incomplete or internally inconsistent."""


def _bounded_text(value: object, *, maximum: int = 4096) -> bool:
    return (
        type(value) is str
        and bool(value.strip())
        and "\0" not in value
        and len(value.encode("utf-8")) <= maximum
    )


def _safe_id(value: object) -> bool:
    return (
        type(value) is str
        and 0 < len(value) <= 128
        and value[0].isalnum()
        and all(character.isalnum() or character in "-_.:" for character in value)
    )


def _valid_digest(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


@dataclass(frozen=True)
class PersonalWorkContract:
    schema_version: str
    contract_id: str
    problem: str
    hypothesis: str
    proposed_answer: str
    target_outcome: str
    deadline: str
    north_star_metric: str
    leading_metrics: tuple[str, ...]
    guardrails: tuple[str, ...]
    trade_off: str
    scope: tuple[str, ...]
    non_goals: tuple[str, ...]
    workflow_ids: tuple[str, ...]
    workflow_source_ids: dict[str, tuple[str, ...]]
    evidence_source_bindings: dict[str, str]
    approval_policy_bindings: dict[str, str]
    input_digest: str
    approved_by: str
    contract_digest: str

    def __post_init__(self) -> None:
        payload = self.as_dict()
        claimed = str(payload.pop("contract_digest"))
        if not (
            self.schema_version == "1.0.0"
            and _safe_id(self.contract_id)
            and _bounded_text(self.problem)
            and _bounded_text(self.hypothesis)
            and _bounded_text(self.proposed_answer)
            and _bounded_text(self.target_outcome)
            and _bounded_text(self.deadline, maximum=128)
            and _bounded_text(self.north_star_metric, maximum=1024)
            and self.leading_metrics
            and self.guardrails
            and _bounded_text(self.trade_off, maximum=1024)
            and self.scope
            and self.non_goals
            and self.workflow_ids
            and len(self.workflow_ids) == len(set(self.workflow_ids))
            and all(_safe_id(item) for item in self.workflow_ids)
            and set(self.workflow_source_ids) == set(self.workflow_ids)
            and all(
                source_ids
                and len(source_ids) == len(set(source_ids))
                and all(_safe_id(source_id) for source_id in source_ids)
                for source_ids in self.workflow_source_ids.values()
            )
            and self.evidence_source_bindings
            and set().union(*self.workflow_source_ids.values())
            <= set(self.evidence_source_bindings)
            and all(
                _safe_id(source_id) and _valid_digest(record_digest)
                for source_id, record_digest in self.evidence_source_bindings.items()
            )
            and set(self.approval_policy_bindings) == set(self.workflow_ids)
            and all(
                _safe_id(workflow_id) and _valid_digest(policy_digest)
                for workflow_id, policy_digest in self.approval_policy_bindings.items()
            )
            and all(_bounded_text(item, maximum=1024) for item in self.leading_metrics)
            and all(_bounded_text(item, maximum=1024) for item in self.guardrails)
            and all(_bounded_text(item, maximum=1024) for item in self.scope)
            and all(_bounded_text(item, maximum=1024) for item in self.non_goals)
            and _valid_digest(self.input_digest)
            and _safe_id(self.approved_by)
            and _valid_digest(claimed)
            and claimed == canonical_digest(payload)
        ):
            raise PersonalContractError("personal work contract is malformed or incomplete")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def create_personal_work_contract(
    *,
    contract_id: str,
    problem: str,
    hypothesis: str,
    proposed_answer: str,
    target_outcome: str,
    deadline: str,
    north_star_metric: str,
    leading_metrics: tuple[str, ...],
    guardrails: tuple[str, ...],
    trade_off: str,
    scope: tuple[str, ...],
    non_goals: tuple[str, ...],
    workflow_ids: tuple[str, ...],
    workflow_source_ids: dict[str, tuple[str, ...]],
    evidence_source_bindings: dict[str, str],
    approval_policy_bindings: dict[str, str],
    input_digest: str,
    approved_by: str,
) -> PersonalWorkContract:
    payload: dict[str, Any] = {
        "approved_by": approved_by,
        "contract_id": contract_id,
        "deadline": deadline,
        "hypothesis": hypothesis,
        "input_digest": input_digest,
        "guardrails": list(guardrails),
        "leading_metrics": list(leading_metrics),
        "non_goals": list(non_goals),
        "north_star_metric": north_star_metric,
        "problem": problem,
        "proposed_answer": proposed_answer,
        "schema_version": "1.0.0",
        "scope": list(scope),
        "target_outcome": target_outcome,
        "trade_off": trade_off,
        "workflow_ids": list(workflow_ids),
        "workflow_source_ids": {
            workflow_id: list(source_ids) for workflow_id, source_ids in workflow_source_ids.items()
        },
        "evidence_source_bindings": dict(evidence_source_bindings),
        "approval_policy_bindings": dict(approval_policy_bindings),
    }
    return PersonalWorkContract(
        schema_version="1.0.0",
        contract_id=contract_id,
        problem=problem,
        hypothesis=hypothesis,
        proposed_answer=proposed_answer,
        target_outcome=target_outcome,
        deadline=deadline,
        north_star_metric=north_star_metric,
        leading_metrics=leading_metrics,
        guardrails=guardrails,
        trade_off=trade_off,
        scope=scope,
        non_goals=non_goals,
        workflow_ids=workflow_ids,
        workflow_source_ids=workflow_source_ids,
        evidence_source_bindings=evidence_source_bindings,
        approval_policy_bindings=approval_policy_bindings,
        input_digest=input_digest,
        approved_by=approved_by,
        contract_digest=canonical_digest(payload),
    )


@dataclass(frozen=True)
class TaskPacket:
    schema_version: str
    task_id: str
    workflow_id: str
    objective: str
    input_refs: tuple[str, ...]
    allowed_capabilities: tuple[str, ...]
    prohibited_capabilities: tuple[str, ...]
    depends_on: tuple[str, ...]
    definition_of_done: tuple[str, ...]
    budget: str
    approval_required: tuple[str, ...]
    verification_owner: str
    contract_digest: str
    packet_digest: str

    def __post_init__(self) -> None:
        payload = self.as_dict()
        claimed = str(payload.pop("packet_digest"))
        if not (
            self.schema_version == "1.0.0"
            and _safe_id(self.task_id)
            and _safe_id(self.workflow_id)
            and _bounded_text(self.objective)
            and self.input_refs
            and self.allowed_capabilities
            and self.prohibited_capabilities
            and self.definition_of_done
            and _bounded_text(self.budget, maximum=256)
            and all(_safe_id(item) for item in self.approval_required)
            and _safe_id(self.verification_owner)
            and all(_safe_id(item) for item in self.input_refs)
            and all(_safe_id(item) for item in self.allowed_capabilities)
            and all(_safe_id(item) for item in self.prohibited_capabilities)
            and all(_safe_id(item) for item in self.depends_on)
            and all(_bounded_text(item, maximum=1024) for item in self.definition_of_done)
            and _valid_digest(self.contract_digest)
            and _valid_digest(claimed)
            and claimed == canonical_digest(payload)
        ):
            raise PersonalContractError("task packet is malformed or incomplete")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def create_task_packet(
    *,
    task_id: str,
    workflow_id: str,
    objective: str,
    input_refs: tuple[str, ...],
    allowed_capabilities: tuple[str, ...],
    prohibited_capabilities: tuple[str, ...],
    depends_on: tuple[str, ...],
    definition_of_done: tuple[str, ...],
    budget: str,
    approval_required: tuple[str, ...],
    verification_owner: str,
    contract_digest: str,
) -> TaskPacket:
    payload: dict[str, Any] = {
        "allowed_capabilities": list(allowed_capabilities),
        "approval_required": list(approval_required),
        "budget": budget,
        "contract_digest": contract_digest,
        "definition_of_done": list(definition_of_done),
        "depends_on": list(depends_on),
        "input_refs": list(input_refs),
        "objective": objective,
        "prohibited_capabilities": list(prohibited_capabilities),
        "schema_version": "1.0.0",
        "task_id": task_id,
        "verification_owner": verification_owner,
        "workflow_id": workflow_id,
    }
    return TaskPacket(
        schema_version="1.0.0",
        task_id=task_id,
        workflow_id=workflow_id,
        objective=objective,
        input_refs=input_refs,
        allowed_capabilities=allowed_capabilities,
        prohibited_capabilities=prohibited_capabilities,
        depends_on=depends_on,
        definition_of_done=definition_of_done,
        budget=budget,
        approval_required=approval_required,
        verification_owner=verification_owner,
        contract_digest=contract_digest,
        packet_digest=canonical_digest(payload),
    )


@dataclass(frozen=True)
class TaskResult:
    task_id: str
    workflow_id: str
    status: str
    execution_batch: str
    output: dict[str, Any]
    evidence_refs: tuple[str, ...]
    packet_digest: str
    result_digest: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def create_task_result(
    *,
    packet: TaskPacket,
    output: dict[str, Any],
    evidence_refs: tuple[str, ...],
    execution_batch: str,
) -> TaskResult:
    payload: dict[str, Any] = {
        "evidence_refs": list(evidence_refs),
        "execution_batch": execution_batch,
        "output": output,
        "packet_digest": packet.packet_digest,
        "status": "COMPLETED",
        "task_id": packet.task_id,
        "workflow_id": packet.workflow_id,
    }
    return TaskResult(
        task_id=packet.task_id,
        workflow_id=packet.workflow_id,
        status="COMPLETED",
        execution_batch=execution_batch,
        output=output,
        evidence_refs=evidence_refs,
        packet_digest=packet.packet_digest,
        result_digest=canonical_digest(payload),
    )


@dataclass(frozen=True)
class ApprovalItem:
    approval_id: str
    workflow_id: str
    action_type: str
    target: str
    reason: str
    reversibility: str
    evidence_refs: tuple[str, ...]
    payload: dict[str, Any]
    payload_digest: str
    status: str = "PENDING_APPROVAL"

    def __post_init__(self) -> None:
        if not (
            _safe_id(self.approval_id)
            and _safe_id(self.workflow_id)
            and _safe_id(self.action_type)
            and _bounded_text(self.target, maximum=1024)
            and _bounded_text(self.reason, maximum=2048)
            and _bounded_text(self.reversibility, maximum=1024)
            and self.evidence_refs
            and all(_safe_id(item) for item in self.evidence_refs)
            and isinstance(self.payload, dict)
            and _valid_digest(self.payload_digest)
            and self.payload_digest == canonical_digest(self.payload)
            and self.status == "PENDING_APPROVAL"
        ):
            raise PersonalContractError("approval item is malformed or incomplete")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def create_approval_item(
    *,
    approval_id: str,
    workflow_id: str,
    action_type: str,
    target: str,
    reason: str,
    reversibility: str,
    evidence_refs: tuple[str, ...],
    payload: dict[str, Any],
) -> ApprovalItem:
    return ApprovalItem(
        approval_id=approval_id,
        workflow_id=workflow_id,
        action_type=action_type,
        target=target,
        reason=reason,
        reversibility=reversibility,
        evidence_refs=evidence_refs,
        payload=payload,
        payload_digest=canonical_digest(payload),
    )


@dataclass(frozen=True)
class EvidenceRecord:
    source_id: str
    kind: str
    title: str
    uri: str
    observed_at: str
    content_digest: str

    def __post_init__(self) -> None:
        if not (
            _safe_id(self.source_id)
            and _safe_id(self.kind)
            and _bounded_text(self.title, maximum=1024)
            and _bounded_text(self.uri, maximum=2048)
            and _bounded_text(self.observed_at, maximum=128)
            and _valid_digest(self.content_digest)
        ):
            raise PersonalContractError("evidence record is malformed or incomplete")

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class PersonalExecutionReport:
    schema_version: str
    run_id: str
    contract_digest: str
    task_graph_digest: str
    status: str
    outcome: str
    result_digests: tuple[str, ...]
    pending_approval_ids: tuple[str, ...]
    parallel_batches: int
    unauthorized_external_actions: int
    evidence_complete: bool
    evidence_ledger_digest: str
    mobile_review_digest: str
    report_digest: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.as_dict())
