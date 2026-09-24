"""Deterministic end-to-end demonstration of runtime assurance controls."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pmpe.contracts.authoring import write_json_atomic
from pmpe.personal.runtime.calendar import (
    CalendarApproval,
    FakeCalendarConnector,
    GovernedCalendarAdapter,
)
from pmpe.personal.runtime.learning import OutcomeLearningLoop
from pmpe.personal.runtime.models import EvidenceSubject, digest_for
from pmpe.personal.runtime.recovery import FakeRecoverableConnector, RecoveryController, RetryPolicy
from pmpe.personal.runtime.registry import EventRegistry
from pmpe.personal.runtime.workers import (
    BoundedProductWorkerAdapter,
    FakeProductWorkerConnector,
    ProductWorkerRequest,
    WorkerBudget,
    WorkerStep,
)

_TIME = "2026-08-20T10:00:00+05:30"


def synthetic_runtime_input() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "calendar": [
            {
                "end": "2026-08-20T10:00:00+05:30",
                "event_id": "CAL-VOICE-001",
                "start": "2026-08-20T09:30:00+05:30",
                "title": "Voice support pilot review",
            }
        ],
        "contract": {
            "contract_id": "PERSONAL-VOICE-001",
            "guardrail": "No worker changes approved product truth.",
            "outcome": "A reviewer can inspect verified pilot evidence.",
        },
        "task": {
            "objective": "Prepare bounded evidence for the voice-support review.",
            "task_id": "TASK-VOICE-001",
        },
        "input_artifact": {"case_ids": ["VOICE-001", "VOICE-002"]},
        "calendar_change": {
            "changes": {
                "end": "2026-08-20T10:30:00+05:30",
                "title": "Voice support pilot review — evidence review",
            },
            "event_id": "CAL-VOICE-001",
        },
        "worker_outputs": {
            "artifact.write": {"artifact": "pilot-brief.md", "status": "written-locally"},
            "eval.run": {"cases": 2, "failed": 1, "passed": 1},
        },
    }


def run_runtime_demo(output: Path) -> dict[str, Path]:
    root = Path(output)
    context = synthetic_runtime_input()
    input_path = root / "synthetic-runtime-input.json"
    registry_path = root / "runtime-events.jsonl"
    proposals_path = root / "regression-proposals.json"
    summary_path = root / "runtime-assurance-report.json"
    write_json_atomic(input_path, context)

    subject = EvidenceSubject(
        contract_digest=digest_for(context["contract"]),
        task_digest=digest_for(context["task"]),
        artifact_digest=digest_for(context["input_artifact"]),
    )
    registry = EventRegistry(registry_path)

    calendar_connector = FakeCalendarConnector(context["calendar"])
    calendar = GovernedCalendarAdapter(calendar_connector, registry)
    change = context["calendar_change"]
    mutation = calendar.propose_update(event_id=change["event_id"], changes=change["changes"])
    approval = CalendarApproval(
        approval_id="APPROVAL-CALENDAR-RUNTIME-001",
        action_type="calendar.update",
        payload_digest=mutation.payload_digest,
        approver="synthetic-demo-user",
        approved_at=_TIME,
    )
    calendar_digest = calendar.apply_approved(
        mutation,
        approval,
        subject=subject,
        occurred_at=_TIME,
    )

    worker_connector = FakeProductWorkerConnector(context["worker_outputs"])
    worker = BoundedProductWorkerAdapter(worker_connector, registry)
    worker_result = worker.run(
        ProductWorkerRequest(
            task_id=context["task"]["task_id"],
            objective=context["task"]["objective"],
            subject=subject,
            product_truth_digest=subject.contract_digest,
            capability_allowlist=("artifact.write", "eval.run"),
            steps=(
                WorkerStep("artifact.write", {"format": "markdown"}),
                WorkerStep("eval.run", {"suite": "voice-support-synthetic"}),
            ),
            budget=WorkerBudget(max_steps=2, max_output_bytes=2048),
        ),
        occurred_at=_TIME,
    )
    output_subject = EvidenceSubject(
        contract_digest=subject.contract_digest,
        task_digest=subject.task_digest,
        artifact_digest=worker_result.artifact_digest,
    )

    retry_connector = FakeRecoverableConnector({"revision": "approved"}, ("retryable", "success"))
    retry_result = RecoveryController(retry_connector, registry).execute(
        operation_id="OP-RETRY-001",
        subject=output_subject,
        policy=RetryPolicy(max_attempts=2),
        rollback_target_digest=retry_connector.state_digest(),
        occurred_at=_TIME,
    )
    rollback_connector = FakeRecoverableConnector({"revision": "last-known-good"}, ("terminal",))
    rollback_result = RecoveryController(rollback_connector, registry).execute(
        operation_id="OP-ROLLBACK-001",
        subject=output_subject,
        policy=RetryPolicy(max_attempts=2),
        rollback_target_digest=rollback_connector.state_digest(),
        occurred_at=_TIME,
    )

    registry.append_evaluation(
        occurred_at=_TIME,
        subject=output_subject,
        case_id="VOICE-002",
        verdict="FAIL",
        score=0.45,
        failure_class="delayed-delivery-escalation",
    )
    proposals = OutcomeLearningLoop(registry).propose(occurred_at=_TIME)
    write_json_atomic(
        proposals_path,
        {
            "proposals": [proposal.as_dict() for proposal in proposals],
            "schema_version": "1.0.0",
        },
    )
    events = registry.read()
    write_json_atomic(
        summary_path,
        {
            "calendar": {
                "approval_id": approval.approval_id,
                "external_writes": 0,
                "local_fake_writes": calendar_connector.write_count,
                "post_calendar_digest": calendar_digest,
            },
            "event_count": len(events),
            "event_registry_head": events[-1].event_digest,
            "learning": {
                "installed_regression_cases": 0,
                "proposals": len(proposals),
            },
            "recovery": {
                "retry_status": retry_result.status,
                "rollback_status": rollback_result.status,
                "rollback_verified": rollback_result.rollback_verified,
            },
            "schema_version": "1.0.0",
            "status": "COMPLETED",
            "worker": {
                "artifact_digest": worker_result.artifact_digest,
                "status": worker_result.status,
                "steps_used": worker_result.steps_used,
            },
        },
    )
    return {
        "events": registry_path,
        "input": input_path,
        "proposals": proposals_path,
        "report": summary_path,
    }
