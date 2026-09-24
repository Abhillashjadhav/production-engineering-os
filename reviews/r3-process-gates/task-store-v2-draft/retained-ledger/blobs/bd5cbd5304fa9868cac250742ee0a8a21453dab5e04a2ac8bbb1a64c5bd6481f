"""Capability- and budget-bounded product-worker adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pmpe.contracts.canonical import canonical_json_bytes
from pmpe.personal.runtime.models import (
    EvidenceSubject,
    RuntimeGovernanceError,
    digest_for,
    require_identifier,
)
from pmpe.personal.runtime.registry import EventRegistry

_PRODUCT_TRUTH_KEYS = {
    "acceptance_criteria",
    "contract",
    "guardrails",
    "north_star_metric",
    "product_truth",
    "requirements",
}


@dataclass(frozen=True)
class WorkerStep:
    capability: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class WorkerBudget:
    max_steps: int
    max_output_bytes: int

    def __post_init__(self) -> None:
        if not 0 < self.max_steps <= 100 or not 0 < self.max_output_bytes <= 1_000_000:
            raise RuntimeGovernanceError("worker budget is outside the runtime bound")


@dataclass(frozen=True)
class ProductWorkerRequest:
    task_id: str
    objective: str
    subject: EvidenceSubject
    product_truth_digest: str
    capability_allowlist: tuple[str, ...]
    steps: tuple[WorkerStep, ...]
    budget: WorkerBudget

    def __post_init__(self) -> None:
        require_identifier(self.task_id, field="task_id")
        if not self.objective or not self.capability_allowlist or not self.steps:
            raise RuntimeGovernanceError("worker request is incomplete")
        if self.product_truth_digest != self.subject.contract_digest:
            raise RuntimeGovernanceError("worker product truth is not bound to the contract")


@dataclass(frozen=True)
class WorkerInvocation:
    """The deliberately narrow input visible to a live worker provider."""

    task_id: str
    objective: str
    capability: str
    arguments: dict[str, Any]
    product_truth_digest: str
    remaining_output_bytes: int


class ProductWorkerConnector(Protocol):
    def execute(self, invocation: WorkerInvocation) -> dict[str, Any]: ...


class FakeProductWorkerConnector:
    """Deterministic handlers used by tests and the offline demo."""

    def __init__(self, outputs: dict[str, dict[str, Any]]) -> None:
        self.outputs = outputs
        self.invocations: list[WorkerInvocation] = []

    def execute(self, invocation: WorkerInvocation) -> dict[str, Any]:
        self.invocations.append(invocation)
        if invocation.capability not in self.outputs:
            raise RuntimeGovernanceError("fake worker has no configured capability output")
        return dict(self.outputs[invocation.capability])


@dataclass(frozen=True)
class ProductWorkerResult:
    task_id: str
    status: str
    outputs: tuple[dict[str, Any], ...]
    steps_used: int
    output_bytes: int
    artifact_digest: str


def _contains_product_truth_mutation(value: Any) -> bool:
    if isinstance(value, dict):
        if _PRODUCT_TRUTH_KEYS & set(value):
            return True
        return any(_contains_product_truth_mutation(child) for child in value.values())
    if isinstance(value, list):
        return any(_contains_product_truth_mutation(child) for child in value)
    return False


class BoundedProductWorkerAdapter:
    """Execute allowlisted steps without granting product-truth mutation authority."""

    def __init__(self, connector: ProductWorkerConnector, registry: EventRegistry) -> None:
        self.connector = connector
        self.registry = registry

    def run(self, request: ProductWorkerRequest, *, occurred_at: str) -> ProductWorkerResult:
        if len(request.steps) > request.budget.max_steps:
            raise RuntimeGovernanceError("worker step budget exceeded before execution")
        allowed = set(request.capability_allowlist)
        if any(step.capability not in allowed for step in request.steps):
            raise RuntimeGovernanceError("worker requested a capability outside its allowlist")

        outputs: list[dict[str, Any]] = []
        output_bytes = 0
        for step in request.steps:
            step_output = self.connector.execute(
                WorkerInvocation(
                    task_id=request.task_id,
                    objective=request.objective,
                    capability=step.capability,
                    arguments=step.arguments,
                    product_truth_digest=request.product_truth_digest,
                    remaining_output_bytes=request.budget.max_output_bytes - output_bytes,
                )
            )
            if not isinstance(step_output, dict) or _contains_product_truth_mutation(step_output):
                raise RuntimeGovernanceError("worker attempted to return product-truth changes")
            output_bytes += len(canonical_json_bytes(step_output))
            if output_bytes > request.budget.max_output_bytes:
                raise RuntimeGovernanceError("worker output budget exceeded")
            outputs.append(step_output)

        artifact_digest = digest_for({"outputs": outputs, "task_id": request.task_id})
        result = ProductWorkerResult(
            task_id=request.task_id,
            status="COMPLETED",
            outputs=tuple(outputs),
            steps_used=len(request.steps),
            output_bytes=output_bytes,
            artifact_digest=artifact_digest,
        )
        result_subject = EvidenceSubject(
            contract_digest=request.subject.contract_digest,
            task_digest=request.subject.task_digest,
            artifact_digest=artifact_digest,
        )
        self.registry.append(
            event_type="product_worker.completed",
            occurred_at=occurred_at,
            subject=result_subject,
            payload={
                "capabilities": [step.capability for step in request.steps],
                "input_artifact_digest": request.subject.artifact_digest,
                "output_bytes": output_bytes,
                "steps_used": len(request.steps),
                "task_id": request.task_id,
            },
        )
        return result
