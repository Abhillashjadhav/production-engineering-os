"""Trajectory evals: the required stage sequence and identity rules, verified from
the evidence ledger (the system of record, never chat transcripts)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pmpe.contracts.canonical import canonical_digest
from pmpe.evals.trajectory import evaluate_trajectory

FIXTURES = Path(__file__).resolve().parents[2] / "evals" / "fixtures" / "trajectory"


def _load(name: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (FIXTURES / name).read_text().splitlines() if line.strip()]


def _checks(name: str) -> set[str]:
    return {v.check_id for v in evaluate_trajectory(_load(name))}


def _make_policy_derived_capability_chain(events: list[dict[str, Any]]) -> None:
    policy_digest = events[0]["output_digests"]["capability_policy"]
    events[1]["detail"] = (
        "capability=write_support_draft;authority_origin=boundary_policy;source=webhook:ticket-481"
    )
    grant_digest = canonical_digest(
        {
            "authority_origin": "boundary_policy",
            "capability": "write_support_draft",
            "capability_policy": policy_digest,
            "source": "webhook:ticket-481",
        }
    )
    events[1]["output_digests"]["capability_grant"] = grant_digest
    events[2]["input_digests"]["capability_grant"] = grant_digest
    use_digest = canonical_digest(
        {
            "capability": "write_support_draft",
            "capability_grant": grant_digest,
            "capability_policy": policy_digest,
        }
    )
    events[2]["output_digests"]["capability_use"] = use_digest
    events[3]["input_digests"]["capability_uses"] = canonical_digest(
        {"capability_uses": [use_digest]}
    )


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
    assert "external-provider.example" in violations[0].evidence


def test_allowed_external_destination_does_not_trigger_traj_15() -> None:
    events = _load("planted_unapproved_external_destination.jsonl")
    allowed_digest = "sha256:9c3a1c9eebddce686d1015b2bb26bfea00119ce16f5e4a0787fc1b98887d04de"
    events[0]["detail"] = "allowed=approved.example,external-provider.example"
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


def test_external_input_cannot_become_capability_authority_even_with_ready_final_verdict() -> None:
    events = _load("planted_inbound_authority_inheritance.jsonl")
    assert events[-1]["verdict"] == "READY_FOR_PRODUCTION_APPROVAL"
    violations = [v for v in evaluate_trajectory(events) if v.check_id == "TRAJ-16"]
    assert violations
    assert "external_input" in violations[0].evidence


def test_policy_derived_capability_grant_is_allowed() -> None:
    events = _load("planted_inbound_authority_inheritance.jsonl")
    _make_policy_derived_capability_chain(events)
    assert "TRAJ-16" not in {v.check_id for v in evaluate_trajectory(events)}


def test_capability_grant_without_bound_policy_fails_closed() -> None:
    events = _load("planted_inbound_authority_inheritance.jsonl")[1:]
    assert "TRAJ-16" in {v.check_id for v in evaluate_trajectory(events)}


def test_capability_grant_with_mismatched_policy_digest_fails_closed() -> None:
    events = _load("planted_inbound_authority_inheritance.jsonl")
    events[1]["input_digests"]["capability_policy"] = (
        "sha256:3333333333333333333333333333333333333333333333333333333333333333"
    )
    assert "TRAJ-16" in {v.check_id for v in evaluate_trajectory(events)}


def test_capability_outside_frozen_policy_fails_closed() -> None:
    events = _load("planted_inbound_authority_inheritance.jsonl")
    _make_policy_derived_capability_chain(events)
    events[1]["detail"] = (
        "capability=deploy_production;authority_origin=boundary_policy;source=webhook:ticket-481"
    )
    policy_digest = events[0]["output_digests"]["capability_policy"]
    events[1]["output_digests"]["capability_grant"] = canonical_digest(
        {
            "authority_origin": "boundary_policy",
            "capability": "deploy_production",
            "capability_policy": policy_digest,
            "source": "webhook:ticket-481",
        }
    )
    violations = [v for v in evaluate_trajectory(events) if v.check_id == "TRAJ-16"]
    assert any("exceeds the frozen capability policy" in v.description for v in violations)


def test_capability_grant_digest_must_bind_the_exact_evidence() -> None:
    events = _load("planted_inbound_authority_inheritance.jsonl")
    _make_policy_derived_capability_chain(events)
    events[1]["output_digests"]["capability_grant"] = "sha256:" + "6" * 64
    violations = [v for v in evaluate_trajectory(events) if v.check_id == "TRAJ-16"]
    assert any("grant digest does not match" in v.description for v in violations)


def test_missing_capability_grant_cannot_be_hidden_by_release_readiness() -> None:
    events = _load("planted_inbound_authority_inheritance.jsonl")
    _make_policy_derived_capability_chain(events)
    events.pop(1)
    violations = [v for v in evaluate_trajectory(events) if v.check_id == "TRAJ-16"]
    assert any("without a preceding validated grant" in v.description for v in violations)


def test_renamed_capability_grant_cannot_be_hidden_by_release_readiness() -> None:
    events = _load("planted_inbound_authority_inheritance.jsonl")
    _make_policy_derived_capability_chain(events)
    events[1]["action"] = "unrecognized_grant"
    violations = [v for v in evaluate_trajectory(events) if v.check_id == "TRAJ-16"]
    assert any("without a preceding validated grant" in v.description for v in violations)


def test_release_readiness_requires_a_preceding_capability_use() -> None:
    events = _load("planted_inbound_authority_inheritance.jsonl")
    _make_policy_derived_capability_chain(events)
    events.pop(2)
    violations = [v for v in evaluate_trajectory(events) if v.check_id == "TRAJ-16"]
    assert any("lacks a preceding validated capability use" in v.description for v in violations)


def test_capability_use_must_bind_the_preceding_grant() -> None:
    events = _load("planted_inbound_authority_inheritance.jsonl")
    _make_policy_derived_capability_chain(events)
    events[2]["input_digests"]["capability_grant"] = "sha256:" + "4" * 64
    violations = [v for v in evaluate_trajectory(events) if v.check_id == "TRAJ-16"]
    assert any("without a preceding validated grant" in v.description for v in violations)


def test_capability_use_digest_must_bind_the_exact_evidence() -> None:
    events = _load("planted_inbound_authority_inheritance.jsonl")
    _make_policy_derived_capability_chain(events)
    events[2]["output_digests"]["capability_use"] = "sha256:" + "7" * 64
    violations = [v for v in evaluate_trajectory(events) if v.check_id == "TRAJ-16"]
    assert any("use digest does not match" in v.description for v in violations)


def test_release_readiness_binds_the_complete_capability_use_set() -> None:
    events = _load("planted_inbound_authority_inheritance.jsonl")
    _make_policy_derived_capability_chain(events)
    events[3]["input_digests"]["capability_uses"] = "sha256:" + "5" * 64
    violations = [v for v in evaluate_trajectory(events) if v.check_id == "TRAJ-16"]
    assert any("incomplete capability-use evidence" in v.description for v in violations)
