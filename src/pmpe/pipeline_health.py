"""Conservative, run-scoped health projection for the fixed core harness.

The local ledger cannot attest a source revision, CI receipt, owner identity,
live-provider confinement, or an outside-verifier decision. This projection
never upgrades recorded candidate assertions into those missing proofs.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

_CHECKS = ("unit", "integration", "uat", "types", "lint", "build", "supported_host_ci")


def _last_event(events: Sequence[Mapping[str, Any]], event_type: str) -> Mapping[str, Any] | None:
    return next(
        (event for event in reversed(events) if event.get("event_type") == event_type), None
    )


def core_pipeline_health(
    events: Sequence[Mapping[str, Any]],
    approval: Mapping[str, str],
    assurance: str,
) -> dict[str, Any] | None:
    """Describe only what the identified local run and its verified chain record."""

    terminal = events[-1]
    terminal_payload = terminal.get("payload")
    if not isinstance(terminal_payload, Mapping):
        return None
    telemetry = terminal_payload.get("telemetry")
    core = telemetry.get("core_harness") if isinstance(telemetry, Mapping) else None
    mapping_digest = core.get("mapping_digest") if isinstance(core, Mapping) else None
    if not isinstance(mapping_digest, str):
        return None

    contract_digest = terminal.get("subject_digest")
    stages: list[dict[str, Any]] = []

    def add(name: str, status: str, reason: str, event_type: str | None = None) -> None:
        event = _last_event(events, event_type) if event_type else None
        stages.append(
            {
                "name": name,
                "status": status,
                "reason": reason,
                "proof_event_digest": event.get("event_digest") if event is not None else None,
                "scope": "LOCAL_RUN_EVIDENCE" if event is not None else "NOT_RECORDED",
            }
        )

    add(
        "mapped_contract",
        "PASS" if _last_event(events, "contract_validated") is not None else "UNKNOWN",
        "compiled_mapping_for_recorded_contract"
        if _last_event(events, "contract_validated")
        else "no_validation_event",
        "contract_validated",
    )
    add(
        "approval_receipt",
        "PASS" if approval.get("status") == "VERIFIED" else "BLOCKED",
        "recorded_digest_bound_receipt"
        if approval.get("status") == "VERIFIED"
        else "exact_digest_owner_receipt_missing",
        "contract_validated",
    )
    baseline = _last_event(events, "meaningful_red_confirmed")
    failed_baseline = any(
        event.get("event_type") == "supervisor_observation_failed"
        and isinstance(event.get("payload"), Mapping)
        and event["payload"].get("attempt") == 0
        for event in events
    )
    add(
        "meaningful_assertion_red",
        "PASS" if baseline is not None else "FAIL" if failed_baseline else "BLOCKED",
        "all_baseline_assertions_failed"
        if baseline is not None
        else "baseline_observer_error"
        if failed_baseline
        else "baseline_proof_missing",
        "meaningful_red_confirmed"
        if baseline is not None
        else "supervisor_observation_failed"
        if failed_baseline
        else None,
    )
    add(
        "provider_generation",
        "PASS" if _last_event(events, "coder_completed") else "BLOCKED",
        "coder_response_recorded"
        if _last_event(events, "coder_completed")
        else "coder_response_missing",
        "coder_completed",
    )
    candidate = _last_event(events, "candidate_response_verified")
    verification_failed = _last_event(events, "verification_failed")
    candidate_attempts = [
        event["payload"].get("attempt")
        for event in events
        if event.get("event_type") == "verification_started"
        and isinstance(event.get("payload"), Mapping)
        and type(event["payload"].get("attempt")) is int
    ]
    latest_attempt = max(candidate_attempts, default=None)
    latest_observer_error = next(
        (
            event
            for event in reversed(events)
            if event.get("event_type") == "supervisor_observation_failed"
            and isinstance(event.get("payload"), Mapping)
            and event["payload"].get("attempt") == latest_attempt
        ),
        None,
    )
    latest_observations = next(
        (
            event
            for event in reversed(events)
            if event.get("event_type") == "supervisor_observations"
            and isinstance(event.get("payload"), Mapping)
            and event["payload"].get("attempt") == latest_attempt
        ),
        None,
    )
    add(
        "candidate_observer_execution",
        "FAIL"
        if latest_observer_error is not None
        else "PASS"
        if latest_observations is not None
        else "BLOCKED",
        "observer_execution_failed"
        if latest_observer_error is not None
        else "complete_candidate_observations"
        if latest_observations is not None
        else "candidate_observations_missing",
        "supervisor_observation_failed"
        if latest_observer_error is not None
        else "supervisor_observations"
        if latest_observations is not None
        else None,
    )
    add(
        "candidate_case_assertions",
        "PASS"
        if assurance == "CANDIDATE_RESPONSE_VERIFIED" and candidate
        else "FAIL"
        if verification_failed and latest_observations is not None and latest_observer_error is None
        else "BLOCKED",
        "candidate_only_assertions_passed"
        if assurance == "CANDIDATE_RESPONSE_VERIFIED" and candidate
        else "candidate_assertions_failed"
        if verification_failed and latest_observations is not None and latest_observer_error is None
        else "candidate_assertions_not_observed",
        "candidate_response_verified"
        if candidate
        else "supervisor_observations"
        if latest_observations is not None and latest_observer_error is None
        else None,
    )
    for condition_id in ("GATE-001", "GATE-002", "GATE-003", "GATE-004", "GATE-005"):
        add(
            condition_id,
            "BLOCKED",
            "approved_live_run_verdict_missing"
            if condition_id == "GATE-001"
            else "independent_condition_proof_missing",
        )
    add("provider_write_confinement", "BLOCKED", "authenticated_live_boundary_unverified")
    for check in _CHECKS:
        add(check, "UNKNOWN", "no_commit_bound_check_receipt_in_run")
    add("outside_verifier", "BLOCKED", "final_independent_decision_missing")
    has_failure = any(item["status"] == "FAIL" for item in stages)
    return {
        "classification": "UNHEALTHY" if has_failure else "INCOMPLETE",
        "run_id": terminal.get("run_id"),
        "contract_digest": contract_digest,
        "mapping_digest": mapping_digest,
        "terminal_state": terminal.get("state"),
        "source_revision": None,
        "checked_at": None,
        "recording_gaps": ["source_revision", "wall_clock_time", "commit_bound_ci_receipts"],
        "stages": stages,
    }
