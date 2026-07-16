"""Trajectory evals: the required stage sequence and identity rules, verified from
the evidence ledger (the system of record, never chat transcripts)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pmpe.evals.trajectory import evaluate_trajectory

FIXTURES = Path(__file__).resolve().parents[2] / "evals" / "fixtures" / "trajectory"


def _load(name: str) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in (FIXTURES / name).read_text().splitlines()
        if line.strip()
    ]


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
