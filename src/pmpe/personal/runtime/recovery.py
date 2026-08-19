"""Bounded retry and verified rollback controls for runtime mutations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pmpe.personal.runtime.models import (
    EvidenceSubject,
    RuntimeGovernanceError,
    digest_for,
    require_identifier,
)
from pmpe.personal.runtime.registry import EventRegistry


class RetryableRuntimeError(RuntimeError):
    """A connector failure that policy may retry within the exact operation budget."""


class TerminalRuntimeError(RuntimeError):
    """A connector failure that must enter rollback without retry."""


class RecoverableConnector(Protocol):
    def state_digest(self) -> str: ...

    def apply(self, attempt: int) -> dict[str, Any]: ...

    def rollback(self, target_digest: str) -> None: ...

    def verify(self, expected_digest: str) -> bool: ...


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int

    def __post_init__(self) -> None:
        if not 1 <= self.max_attempts <= 10:
            raise RuntimeGovernanceError("retry attempts exceed the governed bound")


@dataclass(frozen=True)
class RecoveryResult:
    status: str
    attempts: int
    final_state_digest: str
    rollback_attempted: bool
    rollback_verified: bool


class FakeRecoverableConnector:
    """Scripted local mutation target for deterministic recovery exercises."""

    def __init__(
        self,
        initial_state: dict[str, Any],
        outcomes: tuple[str, ...],
        *,
        rollback_verifies: bool = True,
    ) -> None:
        if not outcomes:
            raise RuntimeGovernanceError("fake recovery outcomes cannot be empty")
        self._initial_state = dict(initial_state)
        self._state = dict(initial_state)
        self._outcomes = outcomes
        self._rollback_verifies = rollback_verifies

    def state_digest(self) -> str:
        return digest_for(self._state)

    def apply(self, attempt: int) -> dict[str, Any]:
        outcome = self._outcomes[min(attempt - 1, len(self._outcomes) - 1)]
        if outcome == "retryable":
            raise RetryableRuntimeError("synthetic transient failure")
        self._state = {"attempt": attempt, "state": "mutated"}
        if outcome == "terminal":
            raise TerminalRuntimeError("synthetic terminal failure")
        if outcome != "success":
            raise RuntimeGovernanceError("unknown fake recovery outcome")
        self._state = {"attempt": attempt, "state": "applied"}
        return dict(self._state)

    def rollback(self, target_digest: str) -> None:
        if target_digest != digest_for(self._initial_state):
            raise RuntimeGovernanceError("rollback target does not name the initial state")
        self._state = (
            dict(self._initial_state)
            if self._rollback_verifies
            else {"state": "rollback-incomplete"}
        )

    def verify(self, expected_digest: str) -> bool:
        return self.state_digest() == expected_digest


class RecoveryController:
    """Retry one exact operation and require positive rollback verification on failure."""

    def __init__(self, connector: RecoverableConnector, registry: EventRegistry) -> None:
        self.connector = connector
        self.registry = registry

    def execute(
        self,
        *,
        operation_id: str,
        subject: EvidenceSubject,
        policy: RetryPolicy,
        rollback_target_digest: str,
        occurred_at: str,
    ) -> RecoveryResult:
        require_identifier(operation_id, field="operation_id")
        if self.connector.state_digest() != rollback_target_digest:
            raise RuntimeGovernanceError("rollback target is not the current pre-operation state")
        attempts = 0
        failure_class: str | None = None
        for attempt in range(1, policy.max_attempts + 1):
            attempts = attempt
            try:
                output = self.connector.apply(attempt)
            except RetryableRuntimeError as exc:
                failure_class = type(exc).__name__
                try:
                    state_unchanged = self.connector.state_digest() == rollback_target_digest
                    self.registry.append(
                        event_type="runtime.retry_scheduled",
                        occurred_at=occurred_at,
                        subject=subject,
                        payload={
                            "attempt": attempt,
                            "error_class": type(exc).__name__,
                            "operation_id": operation_id,
                            "state_unchanged": state_unchanged,
                        },
                    )
                except Exception as reconciliation_exc:
                    failure_class = f"retry_reconciliation:{type(reconciliation_exc).__name__}"
                    break
                if state_unchanged and attempt < policy.max_attempts:
                    continue
                break
            except TerminalRuntimeError as exc:
                failure_class = type(exc).__name__
                break
            except Exception as exc:  # an indeterminate provider result must enter rollback
                failure_class = type(exc).__name__
                break
            else:
                try:
                    final_digest = self.connector.state_digest()
                    self.registry.append(
                        event_type="runtime.operation_completed",
                        occurred_at=occurred_at,
                        subject=subject,
                        payload={
                            "attempts": attempt,
                            "operation_id": operation_id,
                            "output_digest": digest_for(output),
                            "state_digest": final_digest,
                        },
                    )
                except Exception as exc:
                    failure_class = f"post_apply_verification:{type(exc).__name__}"
                    break
                return RecoveryResult(
                    status="COMPLETED",
                    attempts=attempt,
                    final_state_digest=final_digest,
                    rollback_attempted=False,
                    rollback_verified=False,
                )

        audit_errors: list[str] = []
        try:
            self.registry.append(
                event_type="runtime.rollback_started",
                occurred_at=occurred_at,
                subject=subject,
                payload={
                    "attempts": attempts,
                    "failure_class": failure_class,
                    "operation_id": operation_id,
                    "rollback_target_digest": rollback_target_digest,
                },
            )
        except Exception as exc:
            audit_errors.append(f"rollback_started:{type(exc).__name__}")
        rollback_error: str | None = None
        try:
            self.connector.rollback(rollback_target_digest)
            verified = self.connector.verify(rollback_target_digest)
        except Exception as exc:  # provider failure must fail closed, never claim rollback
            rollback_error = type(exc).__name__
            verified = False
        state_digest_available = True
        try:
            final_digest = self.connector.state_digest()
            if final_digest != rollback_target_digest:
                verified = False
                rollback_error = (
                    "FINAL_STATE_MISMATCH"
                    if rollback_error is None
                    else f"{rollback_error}+FINAL_STATE_MISMATCH"
                )
        except Exception as exc:
            state_digest_available = False
            verified = False
            read_error = type(exc).__name__
            rollback_error = (
                read_error if rollback_error is None else f"{rollback_error}+{read_error}"
            )
            final_digest = digest_for({"operation_id": operation_id, "state_digest": "UNAVAILABLE"})
        try:
            self.registry.append(
                event_type=(
                    "runtime.rollback_verified" if verified else "runtime.rollback_unverified"
                ),
                occurred_at=occurred_at,
                subject=subject,
                payload={
                    "operation_id": operation_id,
                    "rollback_error_class": rollback_error,
                    "rollback_target_digest": rollback_target_digest,
                    "state_digest": final_digest,
                    "state_digest_available": state_digest_available,
                    "verified": verified,
                },
            )
        except Exception as exc:
            audit_errors.append(f"rollback_result:{type(exc).__name__}")
        if audit_errors:
            safety = "verified" if verified else "unverified"
            raise RuntimeGovernanceError(
                f"runtime audit failed during rollback ({', '.join(audit_errors)}); "
                f"rollback state is {safety}"
            )
        return RecoveryResult(
            status="ROLLED_BACK" if verified else "BLOCKED_ROLLBACK_UNVERIFIED",
            attempts=attempts,
            final_state_digest=final_digest,
            rollback_attempted=True,
            rollback_verified=verified,
        )
