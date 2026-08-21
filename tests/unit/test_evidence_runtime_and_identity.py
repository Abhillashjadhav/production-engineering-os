from __future__ import annotations

import json
import multiprocessing
from pathlib import Path
from typing import Any

import pytest

import pmpe.engineering.candidate as candidate_module
from pmpe.engineering.candidate import (
    CandidateViolation,
    ReviewSubject,
    freeze_review_subject,
    verify_review_subject,
)
from pmpe.engineering.ledger import EvidenceLedger
from pmpe.orchestration.lifecycle import (
    PHASE_FOUR_POLICY,
    BudgetPolicy,
    LifecycleControlPlane,
    LifecycleState,
)
from pmpe.quality.runtime_matrix import verify_runtime_matrix

D = "sha256:" + "a" * 64
E = "sha256:" + "b" * 64


def _freeze_worker(
    run_dir: str,
    subject: ReviewSubject,
    results: Any,
) -> None:
    try:
        results.put(("success", freeze_review_subject(Path(run_dir), subject)))
    except CandidateViolation as exc:
        results.put(("violation", str(exc)))


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


def test_review_subject_first_write_is_serialized_across_processes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = multiprocessing.get_context("fork")
    first_write_entered = ctx.Event()
    release_first_write = ctx.Event()
    results = ctx.Queue()
    original_atomic_write = candidate_module.atomic_write_json

    def delayed_first_write(path: Path, payload: object) -> None:
        if Path(path).name == "review-subject.json" and not first_write_entered.is_set():
            first_write_entered.set()
            assert release_first_write.wait(timeout=5)
        original_atomic_write(path, payload)

    monkeypatch.setattr(candidate_module, "atomic_write_json", delayed_first_write)
    first = _review(pr_head_sha="d" * 40)
    second = _review(pr_head_sha="e" * 40)
    first_process = ctx.Process(
        target=_freeze_worker,
        args=(str(tmp_path), first, results),
    )
    second_process = ctx.Process(
        target=_freeze_worker,
        args=(str(tmp_path), second, results),
    )

    first_process.start()
    assert first_write_entered.wait(timeout=5)
    second_process.start()
    second_process.join(timeout=0.25)
    assert second_process.is_alive(), "second freezer bypassed the inter-process lock"

    release_first_write.set()
    first_process.join(timeout=5)
    second_process.join(timeout=5)
    assert first_process.exitcode == 0
    assert second_process.exitcode == 0

    outcomes = sorted(results.get(timeout=1) for _ in range(2))
    assert [kind for kind, _ in outcomes] == ["success", "violation"]
    persisted = json.loads((tmp_path / "review-subject.json").read_text())
    assert persisted == candidate_module.jsonable(first)


def test_review_subject_fsyncs_file_and_directory_before_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    synced: list[Path] = []
    original_fsync = candidate_module.os.fsync

    def recording_fsync(descriptor: int) -> None:
        synced.append(Path(candidate_module.os.readlink(f"/proc/self/fd/{descriptor}")))
        original_fsync(descriptor)

    monkeypatch.setattr(candidate_module.os, "fsync", recording_fsync)
    freeze_review_subject(tmp_path, _review())

    assert tmp_path / "review-subject.json" in synced
    assert tmp_path in synced


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


def test_ledger_idempotent_retry_repairs_a_truncated_crash_tail(tmp_path: Path) -> None:
    ledger = EvidenceLedger(tmp_path, run_id="RUN-1")
    ledger.record(
        stage="checks",
        agent="ci",
        action="first",
        output_digests={"result": D},
        idempotency_key="check:1",
    )
    with ledger.path.open("ab") as stream:
        stream.write(b'{"run_id":"RUN-1","idempotency_key":"check:2"')

    recovered = ledger.record(
        stage="checks",
        agent="ci",
        action="second",
        output_digests={"result": E},
        idempotency_key="check:2",
    )

    assert recovered["idempotency_key"] == "check:2"
    assert [event["action"] for event in ledger.read_all()] == ["first", "second"]


def test_declared_python_support_matches_required_ci_matrix() -> None:
    root = Path(__file__).parents[2]
    decision = verify_runtime_matrix(root / "pyproject.toml", root / ".github/workflows/ci.yml")
    assert decision.valid, decision.reasons
    assert decision.declared_targets == ("3.11", "3.12")
    assert decision.tested_targets == ("3.11", "3.12")

    backend = verify_runtime_matrix(
        root / "products/pm-evals-web/backend/pyproject.toml",
        root / ".github/workflows/ci.yml",
        job_name="product-backend",
    )
    assert backend.valid, backend.reasons
    assert backend.declared_targets == ("3.11", "3.12")
    assert backend.tested_targets == ("3.11", "3.12")


def test_phase_four_lifecycle_policy_requires_exact_readiness_and_native_merge_inputs() -> None:
    readiness = PHASE_FOUR_POLICY.rule(
        LifecycleState.REVIEW_REQUIRED,
        LifecycleState.PR_READY,
        reason="advisory_readiness_clear",
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


def test_new_lifecycle_runs_default_to_phase_four_policy(tmp_path: Path) -> None:
    policy = BudgetPolicy(
        version="budget-v1",
        limits={
            "tokens": 10,
            "credits": 10,
            "elapsed_seconds": 10,
            "external_compute_seconds": 10,
            "spend_microunits": 10,
        },
        repair_attempts_per_finding=1,
        repair_attempts_per_stage=1,
        reserved_safety_units=1,
        approved_by="owner",
    )
    control = LifecycleControlPlane.create(
        tmp_path,
        run_id="phase-four-default",
        subject_digest=D,
        initial_state=LifecycleState.CONTRACT_RECEIVED,
        budget_policy=policy,
    )
    metadata = (tmp_path / "lifecycle-metadata.json").read_text()

    assert control._policy is PHASE_FOUR_POLICY  # noqa: SLF001
    assert PHASE_FOUR_POLICY.digest in metadata
