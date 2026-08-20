"""Governance and integrity tests for the Personal Execution OS runtime."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from pmpe.personal.runtime import (
    BoundedProductWorkerAdapter,
    CalendarApproval,
    CalendarMutation,
    EventRegistry,
    EvidenceSubject,
    FakeCalendarConnector,
    FakeProductWorkerConnector,
    FakeRecoverableConnector,
    GovernedCalendarAdapter,
    OutcomeLearningLoop,
    ProductWorkerRequest,
    RecoveryController,
    RegistryIntegrityError,
    RetryPolicy,
    RuntimeGovernanceError,
    WorkerBudget,
    WorkerStep,
)
from pmpe.personal.runtime.models import digest_for


def _subject() -> EvidenceSubject:
    return EvidenceSubject(
        contract_digest=digest_for({"contract": 1}),
        task_digest=digest_for({"task": 1}),
        artifact_digest=digest_for({"artifact": 1}),
    )


def _calendar() -> list[dict[str, str]]:
    return [
        {
            "end": "2026-08-20T10:00:00Z",
            "event_id": "CAL-001",
            "start": "2026-08-20T09:00:00Z",
            "title": "Review",
        }
    ]


class _FailingEventRegistry(EventRegistry):
    def __init__(self, path: Path, fail_on: set[str]) -> None:
        super().__init__(path)
        self.fail_on = fail_on

    def append(self, **kwargs):  # type: ignore[no-untyped-def]
        if kwargs["event_type"] in self.fail_on:
            raise OSError("synthetic audit failure")
        return super().append(**kwargs)


def test_registry_is_hash_chained_and_parallel_safe(tmp_path: Path) -> None:
    registry = EventRegistry(tmp_path / "events.jsonl")

    def append(index: int) -> None:
        registry.append(
            event_type="test.observed",
            occurred_at="2026-08-20T10:00:00Z",
            subject=_subject(),
            payload={"index": index},
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(append, range(12)))
    events = registry.read()
    assert [event.sequence for event in events] == list(range(1, 13))
    assert events[0].previous_event_digest is None
    assert all(
        event.previous_event_digest == events[index - 1].event_digest
        for index, event in enumerate(events[1:], start=1)
    )


def test_registry_rejects_tampered_history(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    registry = EventRegistry(path)
    registry.append(
        event_type="test.observed",
        occurred_at="2026-08-20T10:00:00Z",
        subject=_subject(),
        payload={"status": "original"},
    )
    path.write_text(path.read_text().replace("original", "tampered"))
    with pytest.raises(RegistryIntegrityError):
        registry.read()


def test_calendar_requires_approval_for_the_exact_payload(tmp_path: Path) -> None:
    connector = FakeCalendarConnector(_calendar())
    adapter = GovernedCalendarAdapter(connector, EventRegistry(tmp_path / "events.jsonl"))
    mutation = adapter.propose_update(event_id="CAL-001", changes={"title": "New review"})
    wrong = CalendarApproval(
        approval_id="APPROVAL-001",
        action_type="calendar.update",
        payload_digest=digest_for({"different": True}),
        approver="owner",
        approved_at="2026-08-20T10:00:00Z",
    )
    with pytest.raises(RuntimeGovernanceError, match="exact payload"):
        adapter.apply_approved(
            mutation, wrong, subject=_subject(), occurred_at="2026-08-20T10:00:00Z"
        )
    assert connector.write_count == 0

    approval = CalendarApproval(
        approval_id="APPROVAL-002",
        action_type="calendar.update",
        payload_digest=mutation.payload_digest,
        approver="owner",
        approved_at="2026-08-20T10:01:00Z",
    )
    adapter.apply_approved(
        mutation, approval, subject=_subject(), occurred_at="2026-08-20T10:01:00Z"
    )
    assert connector.snapshot()[0]["title"] == "New review"
    assert connector.write_count == 1


def test_calendar_approval_fails_if_snapshot_changes(tmp_path: Path) -> None:
    connector = FakeCalendarConnector(_calendar())
    adapter = GovernedCalendarAdapter(connector, EventRegistry(tmp_path / "events.jsonl"))
    mutation = adapter.propose_update(event_id="CAL-001", changes={"title": "Approved title"})
    connector.apply_update("CAL-001", {"title": "Concurrent title"})
    approval = CalendarApproval(
        approval_id="APPROVAL-001",
        action_type="calendar.update",
        payload_digest=mutation.payload_digest,
        approver="owner",
        approved_at="2026-08-20T10:00:00Z",
    )
    with pytest.raises(RuntimeGovernanceError, match="changed after approval"):
        adapter.apply_approved(
            mutation, approval, subject=_subject(), occurred_at="2026-08-20T10:00:00Z"
        )
    assert connector.snapshot()[0]["title"] == "Concurrent title"


def test_calendar_approval_is_single_use_and_payload_cannot_mutate(tmp_path: Path) -> None:
    connector = FakeCalendarConnector(_calendar())
    adapter = GovernedCalendarAdapter(connector, EventRegistry(tmp_path / "events.jsonl"))
    mutation = adapter.propose_update(event_id="CAL-001", changes={"title": "Approved title"})
    approval = CalendarApproval(
        approval_id="APPROVAL-001",
        action_type="calendar.update",
        payload_digest=mutation.payload_digest,
        approver="owner",
        approved_at="2026-08-20T10:00:00Z",
    )
    mutation.changes["title"] = "Unapproved title"
    with pytest.raises(RuntimeGovernanceError, match="mutation changed"):
        adapter.apply_approved(
            mutation, approval, subject=_subject(), occurred_at="2026-08-20T10:00:00Z"
        )
    assert connector.write_count == 0

    exact = adapter.propose_update(event_id="CAL-001", changes={"title": "Approved title"})
    exact_approval = CalendarApproval(
        approval_id="APPROVAL-002",
        action_type="calendar.update",
        payload_digest=exact.payload_digest,
        approver="owner",
        approved_at="2026-08-20T10:01:00Z",
    )
    adapter.apply_approved(
        exact, exact_approval, subject=_subject(), occurred_at="2026-08-20T10:01:00Z"
    )
    with pytest.raises(RuntimeGovernanceError, match="already been consumed"):
        adapter.apply_approved(
            exact, exact_approval, subject=_subject(), occurred_at="2026-08-20T10:02:00Z"
        )
    assert connector.write_count == 1


def test_calendar_approval_consumption_survives_adapter_restart(tmp_path: Path) -> None:
    registry_path = tmp_path / "events.jsonl"
    connector = FakeCalendarConnector(_calendar())
    first = GovernedCalendarAdapter(connector, EventRegistry(registry_path))
    mutation = first.propose_update(event_id="CAL-001", changes={"title": "Review"})
    approval = CalendarApproval(
        approval_id="APPROVAL-RESTART-001",
        action_type="calendar.update",
        payload_digest=mutation.payload_digest,
        approver="owner",
        approved_at="2026-08-20T10:00:00Z",
    )
    first.apply_approved(mutation, approval, subject=_subject(), occurred_at="2026-08-20T10:00:00Z")
    restarted = GovernedCalendarAdapter(connector, EventRegistry(registry_path))
    with pytest.raises(RuntimeGovernanceError, match="already been consumed"):
        restarted.apply_approved(
            mutation, approval, subject=_subject(), occurred_at="2026-08-20T10:01:00Z"
        )
    assert connector.write_count == 1


def test_calendar_approval_reservation_is_atomic_for_concurrent_calls(tmp_path: Path) -> None:
    registry = EventRegistry(tmp_path / "events.jsonl")
    connector = FakeCalendarConnector(_calendar())
    adapter = GovernedCalendarAdapter(connector, registry)
    mutation = adapter.propose_update(event_id="CAL-001", changes={"title": "Review"})
    approval = CalendarApproval(
        approval_id="APPROVAL-CONCURRENT-001",
        action_type="calendar.update",
        payload_digest=mutation.payload_digest,
        approver="owner",
        approved_at="2026-08-20T10:00:00Z",
    )

    def apply_once() -> str:
        return adapter.apply_approved(
            mutation, approval, subject=_subject(), occurred_at="2026-08-20T10:00:00Z"
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(apply_once) for _ in range(2)]
    outcomes = []
    for future in futures:
        try:
            outcomes.append(future.result())
        except RuntimeGovernanceError as exc:
            outcomes.append(str(exc))
    assert connector.write_count == 1
    assert sum("consumed" in outcome for outcome in outcomes) == 1


def test_calendar_snapshot_check_and_write_are_serialized(tmp_path: Path) -> None:
    connector = FakeCalendarConnector(_calendar())
    adapter = GovernedCalendarAdapter(connector, EventRegistry(tmp_path / "events.jsonl"))
    first = adapter.propose_update(event_id="CAL-001", changes={"title": "First"})
    second = adapter.propose_update(event_id="CAL-001", changes={"title": "Second"})
    approvals = (
        CalendarApproval(
            approval_id="APPROVAL-SNAPSHOT-001",
            action_type="calendar.update",
            payload_digest=first.payload_digest,
            approver="owner",
            approved_at="2026-08-20T10:00:00Z",
        ),
        CalendarApproval(
            approval_id="APPROVAL-SNAPSHOT-002",
            action_type="calendar.update",
            payload_digest=second.payload_digest,
            approver="owner",
            approved_at="2026-08-20T10:00:00Z",
        ),
    )

    def apply(pair: tuple[CalendarMutation, CalendarApproval]) -> str:
        return adapter.apply_approved(
            pair[0], pair[1], subject=_subject(), occurred_at="2026-08-20T10:00:00Z"
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(apply, pair) for pair in zip((first, second), approvals, strict=True)
        ]
    outcomes = []
    for future in futures:
        try:
            outcomes.append(future.result())
        except RuntimeGovernanceError as exc:
            outcomes.append(str(exc))
    assert connector.write_count == 1
    assert sum("changed after approval" in outcome for outcome in outcomes) == 1


def test_calendar_prejournals_before_mutation_and_blocks_on_completion_audit_failure(
    tmp_path: Path,
) -> None:
    connector = FakeCalendarConnector(_calendar())
    registry = _FailingEventRegistry(tmp_path / "events.jsonl", {"calendar.update_applied"})
    adapter = GovernedCalendarAdapter(connector, registry)
    mutation = adapter.propose_update(event_id="CAL-001", changes={"title": "Approved"})
    approval = CalendarApproval(
        approval_id="APPROVAL-001",
        action_type="calendar.update",
        payload_digest=mutation.payload_digest,
        approver="owner",
        approved_at="2026-08-20T10:00:00Z",
    )
    with pytest.raises(RuntimeGovernanceError, match="indeterminate"):
        adapter.apply_approved(
            mutation, approval, subject=_subject(), occurred_at="2026-08-20T10:00:00Z"
        )
    assert connector.write_count == 1
    assert [event.event_type for event in registry.read()] == ["calendar.update_started"]


def _worker_request(**changes: object) -> ProductWorkerRequest:
    values: dict[str, object] = {
        "task_id": "TASK-001",
        "objective": "Build local evidence.",
        "subject": _subject(),
        "product_truth_digest": _subject().contract_digest,
        "capability_allowlist": ("artifact.write",),
        "steps": (WorkerStep("artifact.write", {"name": "brief"}),),
        "budget": WorkerBudget(max_steps=1, max_output_bytes=256),
    }
    values.update(changes)
    return ProductWorkerRequest(**values)  # type: ignore[arg-type]


def test_worker_honors_capability_and_output_budgets(tmp_path: Path) -> None:
    adapter = BoundedProductWorkerAdapter(
        FakeProductWorkerConnector({"artifact.write": {"artifact": "brief.md"}}),
        EventRegistry(tmp_path / "events.jsonl"),
    )
    result = adapter.run(_worker_request(), occurred_at="2026-08-20T10:00:00Z")
    assert result.status == "COMPLETED"
    assert result.steps_used == 1

    forbidden = _worker_request(steps=(WorkerStep("network.write", {}),))
    with pytest.raises(RuntimeGovernanceError, match="allowlist"):
        adapter.run(forbidden, occurred_at="2026-08-20T10:00:00Z")


def test_worker_cannot_return_product_truth_changes(tmp_path: Path) -> None:
    adapter = BoundedProductWorkerAdapter(
        FakeProductWorkerConnector(
            {"artifact.write": {"product_truth": {"north_star_metric": "changed"}}}
        ),
        EventRegistry(tmp_path / "events.jsonl"),
    )
    with pytest.raises(RuntimeGovernanceError, match="product-truth"):
        adapter.run(_worker_request(), occurred_at="2026-08-20T10:00:00Z")


def test_worker_stops_on_output_budget(tmp_path: Path) -> None:
    adapter = BoundedProductWorkerAdapter(
        FakeProductWorkerConnector({"artifact.write": {"artifact": "x" * 300}}),
        EventRegistry(tmp_path / "events.jsonl"),
    )
    with pytest.raises(RuntimeGovernanceError, match="output budget"):
        adapter.run(_worker_request(), occurred_at="2026-08-20T10:00:00Z")


def test_recovery_retries_within_budget_then_completes(tmp_path: Path) -> None:
    connector = FakeRecoverableConnector({"revision": "base"}, ("retryable", "success"))
    controller = RecoveryController(connector, EventRegistry(tmp_path / "events.jsonl"))
    result = controller.execute(
        operation_id="OP-001",
        subject=_subject(),
        policy=RetryPolicy(max_attempts=2),
        rollback_target_digest=connector.state_digest(),
        occurred_at="2026-08-20T10:00:00Z",
    )
    assert result.status == "COMPLETED"
    assert result.attempts == 2
    assert not result.rollback_attempted


def test_failed_operation_is_only_rolled_back_after_verification(tmp_path: Path) -> None:
    connector = FakeRecoverableConnector({"revision": "base"}, ("terminal",))
    controller = RecoveryController(connector, EventRegistry(tmp_path / "events.jsonl"))
    result = controller.execute(
        operation_id="OP-001",
        subject=_subject(),
        policy=RetryPolicy(max_attempts=2),
        rollback_target_digest=connector.state_digest(),
        occurred_at="2026-08-20T10:00:00Z",
    )
    assert result.status == "ROLLED_BACK"
    assert result.rollback_verified


def test_unverified_rollback_fails_closed(tmp_path: Path) -> None:
    connector = FakeRecoverableConnector(
        {"revision": "base"}, ("terminal",), rollback_verifies=False
    )
    result = RecoveryController(connector, EventRegistry(tmp_path / "events.jsonl")).execute(
        operation_id="OP-001",
        subject=_subject(),
        policy=RetryPolicy(max_attempts=1),
        rollback_target_digest=connector.state_digest(),
        occurred_at="2026-08-20T10:00:00Z",
    )
    assert result.status == "BLOCKED_ROLLBACK_UNVERIFIED"
    assert not result.rollback_verified


def test_recovery_rolls_back_even_when_rollback_audit_start_fails(tmp_path: Path) -> None:
    connector = FakeRecoverableConnector({"revision": "base"}, ("terminal",))
    target = connector.state_digest()
    registry = _FailingEventRegistry(tmp_path / "events.jsonl", {"runtime.rollback_started"})
    with pytest.raises(RuntimeGovernanceError, match="audit failed during rollback"):
        RecoveryController(connector, registry).execute(
            operation_id="OP-001",
            subject=_subject(),
            policy=RetryPolicy(max_attempts=1),
            rollback_target_digest=target,
            occurred_at="2026-08-20T10:00:00Z",
        )
    assert connector.verify(target)


def test_success_audit_failure_enters_verified_rollback(tmp_path: Path) -> None:
    connector = FakeRecoverableConnector({"revision": "base"}, ("success",))
    target = connector.state_digest()
    registry = _FailingEventRegistry(tmp_path / "events.jsonl", {"runtime.operation_completed"})
    result = RecoveryController(connector, registry).execute(
        operation_id="OP-001",
        subject=_subject(),
        policy=RetryPolicy(max_attempts=1),
        rollback_target_digest=target,
        occurred_at="2026-08-20T10:00:00Z",
    )
    assert result.status == "ROLLED_BACK"
    assert connector.verify(target)


def test_post_apply_state_read_failure_enters_verified_rollback(tmp_path: Path) -> None:
    class PostApplyReadFailureConnector(FakeRecoverableConnector):
        def __init__(self) -> None:
            super().__init__({"revision": "base"}, ("success",))
            self.read_count = 0

        def state_digest(self) -> str:
            self.read_count += 1
            if self.read_count == 3:
                raise OSError("synthetic post-apply read failure")
            return super().state_digest()

    connector = PostApplyReadFailureConnector()
    target = connector.state_digest()
    result = RecoveryController(connector, EventRegistry(tmp_path / "events.jsonl")).execute(
        operation_id="OP-POST-READ-001",
        subject=_subject(),
        policy=RetryPolicy(max_attempts=1),
        rollback_target_digest=target,
        occurred_at="2026-08-20T10:00:00Z",
    )
    assert result.status == "ROLLED_BACK"
    assert result.rollback_verified


def test_retry_state_read_failure_enters_verified_rollback(tmp_path: Path) -> None:
    class RetryReadFailureConnector(FakeRecoverableConnector):
        def __init__(self) -> None:
            super().__init__({"revision": "base"}, ("retryable",))
            self.read_count = 0

        def state_digest(self) -> str:
            self.read_count += 1
            if self.read_count == 3:
                raise OSError("synthetic retry reconciliation failure")
            return super().state_digest()

    connector = RetryReadFailureConnector()
    target = connector.state_digest()
    result = RecoveryController(connector, EventRegistry(tmp_path / "events.jsonl")).execute(
        operation_id="OP-RETRY-READ-001",
        subject=_subject(),
        policy=RetryPolicy(max_attempts=1),
        rollback_target_digest=target,
        occurred_at="2026-08-20T10:00:00Z",
    )
    assert result.status == "ROLLED_BACK"
    assert result.rollback_verified


def test_final_rollback_state_read_failure_is_audited_as_unverified(tmp_path: Path) -> None:
    class FinalReadFailureConnector(FakeRecoverableConnector):
        def __init__(self) -> None:
            super().__init__({"revision": "base"}, ("terminal",))
            self.read_count = 0

        def state_digest(self) -> str:
            self.read_count += 1
            if self.read_count >= 3:
                raise OSError("synthetic rollback read failure")
            return super().state_digest()

    registry = EventRegistry(tmp_path / "events.jsonl")
    connector = FinalReadFailureConnector()
    target = connector.state_digest()
    result = RecoveryController(connector, registry).execute(
        operation_id="OP-ROLLBACK-READ-001",
        subject=_subject(),
        policy=RetryPolicy(max_attempts=1),
        rollback_target_digest=target,
        occurred_at="2026-08-20T10:00:00Z",
    )
    assert result.status == "BLOCKED_ROLLBACK_UNVERIFIED"
    assert not result.rollback_verified
    assert registry.read()[-1].event_type == "runtime.rollback_unverified"


def test_final_rollback_digest_must_still_match_target(tmp_path: Path) -> None:
    class DriftingRollbackConnector(FakeRecoverableConnector):
        def verify(self, expected_digest: str) -> bool:
            verified = super().verify(expected_digest)
            self._state = {"revision": "drifted"}
            return verified

    registry = EventRegistry(tmp_path / "events.jsonl")
    connector = DriftingRollbackConnector({"revision": "base"}, ("terminal",))
    target = connector.state_digest()
    result = RecoveryController(connector, registry).execute(
        operation_id="OP-ROLLBACK-DRIFT-001",
        subject=_subject(),
        policy=RetryPolicy(max_attempts=1),
        rollback_target_digest=target,
        occurred_at="2026-08-20T10:00:00Z",
    )
    assert result.status == "BLOCKED_ROLLBACK_UNVERIFIED"
    assert not result.rollback_verified
    assert registry.read()[-1].event_type == "runtime.rollback_unverified"


def test_learning_loop_only_proposes_regression_cases(tmp_path: Path) -> None:
    registry = EventRegistry(tmp_path / "events.jsonl")
    registry.append_evaluation(
        occurred_at="2026-08-20T10:00:00Z",
        subject=_subject(),
        case_id="CASE-001",
        verdict="FAIL",
        score=0.2,
        failure_class="handoff",
    )
    installed_suite = [{"case_id": "EXISTING-001"}]
    original = json.dumps(installed_suite, sort_keys=True)
    proposals = OutcomeLearningLoop(registry).propose(occurred_at="2026-08-20T10:01:00Z")
    assert len(proposals) == 1
    assert proposals[0].status == "PROPOSED"
    assert json.dumps(installed_suite, sort_keys=True) == original
    assert registry.read()[-1].event_type == "learning.regression_proposed"
    assert OutcomeLearningLoop(registry).propose(occurred_at="2026-08-20T10:02:00Z") == ()
