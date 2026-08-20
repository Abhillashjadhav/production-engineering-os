from __future__ import annotations

from pathlib import Path

import pytest

from pmpe.engineering.candidate import (
    CandidateViolation,
    ReviewSubject,
    freeze_review_subject,
    verify_review_subject,
)
from pmpe.engineering.ledger import EvidenceLedger
from pmpe.orchestration.lifecycle import PHASE_FOUR_POLICY, LifecycleState
from pmpe.quality.runtime_matrix import verify_runtime_matrix

D = "sha256:" + "a" * 64
E = "sha256:" + "b" * 64


def _review(**changes: str) -> ReviewSubject:
    values = {
        "protected_base_sha": "c" * 40,
        "pr_head_sha": "d" * 40,
        "prospective_merge_tree_digest": D,
        "repository_rules_digest": D,
        "architecture_policy_digest": D,
        "toolchain_policy_digest": D,
        "environment_profile_digest": D,
        "security_policy_digest": D,
        "verification_policy_digest": D,
        "evidence_policy_digest": D,
        "frozen_at": "2026-08-20T12:00:00Z",
    }
    values.update(changes)
    return ReviewSubject(**values)


def test_review_subject_freeze_invalidates_head_base_tree_or_policy_change(tmp_path: Path) -> None:
    subject = _review()
    freeze_review_subject(tmp_path, subject)
    assert verify_review_subject(tmp_path, subject) == subject.digest

    with pytest.raises(CandidateViolation, match="changed"):
        verify_review_subject(tmp_path, _review(protected_base_sha="e" * 40))
    with pytest.raises(CandidateViolation, match="changed"):
        freeze_review_subject(tmp_path, _review(evidence_policy_digest=E))


def test_ledger_idempotency_does_not_double_count_and_rejects_conflict(tmp_path: Path) -> None:
    ledger = EvidenceLedger(tmp_path, run_id="RUN-1")
    first = ledger.record(
        stage="checks",
        agent="ci",
        action="verify",
        output_digests={"result": D},
        idempotency_key="check:1",
    )
    retry = ledger.record(
        stage="checks",
        agent="ci",
        action="verify",
        output_digests={"result": D},
        idempotency_key="check:1",
    )
    assert retry == first
    assert len(ledger.read_all()) == 1

    with pytest.raises(ValueError, match="different evidence"):
        ledger.record(
            stage="checks",
            agent="ci",
            action="verify",
            output_digests={"result": E},
            idempotency_key="check:1",
        )


def test_declared_python_support_matches_required_ci_matrix() -> None:
    root = Path(__file__).parents[2]
    decision = verify_runtime_matrix(root / "pyproject.toml", root / ".github/workflows/ci.yml")
    assert decision.valid, decision.reasons
    assert decision.declared_targets == ("3.11", "3.12")
    assert decision.tested_targets == ("3.11", "3.12")


def test_phase_four_lifecycle_policy_requires_exact_readiness_and_native_merge_inputs() -> None:
    readiness = PHASE_FOUR_POLICY.rule(
        LifecycleState.REVIEW_REQUIRED,
        LifecycleState.PR_READY,
        reason="formal_review_clear",
    )
    merge = PHASE_FOUR_POLICY.rule(
        LifecycleState.PR_READY,
        LifecycleState.PR_MERGED,
        reason="native_merge_linearized",
    )
    assert {
        "protected_base_sha",
        "architecture_policy_digest",
        "toolchain_policy_digest",
        "environment_profile_digest",
        "security_policy_digest",
        "verification_policy_digest",
        "evidence_policy_digest",
    } <= set(readiness.required_evidence)
    assert {
        "finding_high_watermark_digest",
        "authority_revalidation_digest",
        "native_merge_gate_digest",
    } <= set(merge.required_evidence)
