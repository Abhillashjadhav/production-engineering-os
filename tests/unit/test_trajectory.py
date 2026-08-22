"""Trajectory evals: the required stage sequence and identity rules, verified from
the evidence ledger (the system of record, never chat transcripts)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pmpe.evals.trajectory import evaluate_trajectory

FIXTURES = Path(__file__).resolve().parents[2] / "evals" / "fixtures" / "trajectory"


def _load(name: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (FIXTURES / name).read_text().splitlines() if line.strip()]


def _checks(name: str) -> set[str]:
    return {v.check_id for v in evaluate_trajectory(_load(name))}


def test_compliant_ledger_has_no_violations() -> None:
    assert evaluate_trajectory(_load("good_run.jsonl")) == []


def test_review_before_freeze_is_caught() -> None:
    assert "TRAJ-07" in _checks("planted_review_before_freeze.jsonl")


def test_contract_digest_mutation_is_caught() -> None:
    assert "TRAJ-02" in _checks("planted_contract_mutation.jsonl")


def test_self_review_is_caught() -> None:
    assert "TRAJ-06" in _checks("planted_self_review.jsonl")


def test_reviewer_candidate_mismatch_is_caught() -> None:
    assert "TRAJ-08" in _checks("planted_reviewer_digest_mismatch.jsonl")


def test_reviewer_write_is_caught() -> None:
    assert "TRAJ-09" in _checks("planted_reviewer_wrote.jsonl")


def test_unauthorized_fix_is_caught() -> None:
    assert "TRAJ-10" in _checks("planted_unauthorized_fix.jsonl")


def test_missing_retest_after_fix_is_caught() -> None:
    assert "TRAJ-12" in _checks("planted_missing_retest.jsonl")


def test_production_deploy_without_approval_is_caught() -> None:
    assert "TRAJ-14" in _checks("planted_prod_deploy_no_approval.jsonl")


def test_architecture_before_contract_lock_is_caught() -> None:
    assert "TRAJ-01" in _checks("planted_architecture_first.jsonl")


def test_implementation_before_architecture_is_caught() -> None:
    assert "TRAJ-03" in _checks("planted_implement_before_architecture.jsonl")


def test_unrouted_specialist_is_caught() -> None:
    assert "TRAJ-04" in _checks("planted_unrouted_specialist.jsonl")


def test_implementation_before_its_tests_is_caught() -> None:
    assert "TRAJ-05" in _checks("planted_implementation_before_tests.jsonl")


def test_product_decision_without_change_request_is_caught() -> None:
    assert "TRAJ-11" in _checks("planted_product_decision_no_pcr.jsonl")


def test_unrelated_change_request_does_not_satisfy_traj_11() -> None:
    """A single stray change_request_created event must not excuse every
    product-decision finding — the binding is by finding id."""
    events = _load("planted_product_decision_no_pcr.jsonl")
    events.append(
        {
            "action": "change_request_created",
            "agent": "pmpe-core",
            "stage": "reconcile",
            "detail": "RF-999",
            "input_digests": {},
            "output_digests": {},
            "verdict": "",
        }
    )
    assert "TRAJ-11" in {v.check_id for v in evaluate_trajectory(events)}


def test_draft_pr_before_assurance_is_caught() -> None:
    assert "TRAJ-13" in _checks("planted_draft_pr_before_assurance.jsonl")


def test_unapproved_external_destination_is_caught_even_with_ready_final_verdict() -> None:
    events = _load("planted_unapproved_external_destination.jsonl")
    assert events[-1]["verdict"] == "READY_FOR_PRODUCTION_APPROVAL"
    violations = [v for v in evaluate_trajectory(events) if v.check_id == "TRAJ-15"]
    assert violations
    assert "huggingface.co" in violations[0].evidence


def test_allowed_external_destination_does_not_trigger_traj_15() -> None:
    events = _load("planted_unapproved_external_destination.jsonl")
    allowed_digest = "sha256:9a20f5753eb2613ebca5d2b6d7c8a2ff03ada237b0e7db2639c82e39bee9f2be"
    events[0]["detail"] = "allowed=api.openai.com,huggingface.co"
    events[0]["output_digests"]["egress_policy"] = allowed_digest
    events[1]["input_digests"]["egress_policy"] = allowed_digest
    assert "TRAJ-15" not in {v.check_id for v in evaluate_trajectory(events)}


def test_external_destination_without_bound_policy_fails_closed() -> None:
    events = _load("planted_unapproved_external_destination.jsonl")[1:]
    assert "TRAJ-15" in {v.check_id for v in evaluate_trajectory(events)}


def test_external_destination_with_mismatched_policy_digest_fails_closed() -> None:
    events = _load("planted_unapproved_external_destination.jsonl")
    events[1]["input_digests"]["egress_policy"] = (
        "sha256:2222222222222222222222222222222222222222222222222222222222222222"
    )
    assert "TRAJ-15" in {v.check_id for v in evaluate_trajectory(events)}
