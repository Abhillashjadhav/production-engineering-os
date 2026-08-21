from __future__ import annotations

from dataclasses import replace

from pmpe.contracts.digest import canonical_digest
from pmpe.evals.eadpr import EadprSubject, compute_eadpr, verify_eadpr

D = "sha256:" + "a" * 64
START = "2026-07-01T00:00:00Z"
CUTOFF = "2026-08-01T00:00:00Z"
SEALED = "2026-08-01T00:00:01Z"


def _evidence_digest(slice_id: str, qualifying_at: str) -> str:
    return canonical_digest(
        {
            "authenticated_admission": True,
            "slice_id": slice_id,
            "qualifying_draft_pr_at": qualifying_at,
            "policy_version": "eadpr-v1",
        }
    )


def _verify_evidence(subject: EadprSubject) -> bool:
    return subject.evidence_bundle_digest == _evidence_digest(
        subject.slice_id, subject.qualifying_draft_pr_at
    )


def _subject(
    slice_id: str,
    due: str,
    *,
    success: str = "2026-07-15T00:00:00Z",
    manual: tuple[str, ...] = (),
    excluded: str = "",
) -> EadprSubject:
    return EadprSubject(
        slice_id,
        "2026-07-02T00:00:00Z",
        due,
        "eadpr-v1",
        success,
        _evidence_digest(slice_id, success) if success else "",
        manual,
        excluded,
    )


def test_fixed_due_cohort_seals_success_failure_pending_exclusion_and_manual_companion() -> None:
    subjects = (
        _subject("success", "2026-07-20T00:00:00Z"),
        _subject("late", "2026-07-20T00:00:00Z", success="2026-07-21T00:00:00Z"),
        _subject(
            "manual",
            "2026-07-20T00:00:00Z",
            manual=("2026-07-10T00:00:00Z",),
        ),
        _subject("pending", "2026-08-02T00:00:00Z"),
        _subject("excluded", "2026-07-20T00:00:00Z", excluded="unsupported repository"),
    )

    report = compute_eadpr(
        subjects,
        policy_version="eadpr-v1",
        target_approved=True,
        window_start=START,
        reporting_cutoff=CUTOFF,
        sealed_at=SEALED,
        evidence_verifier=_verify_evidence,
    )

    assert report.denominator_subjects == ("late", "manual", "success")
    assert report.numerator_subjects == ("success",)
    assert report.failure_subjects == ("late", "manual")
    assert report.pending_subjects == ("pending",)
    assert report.right_censored_subjects == ("pending",)
    assert report.excluded_subjects == ("excluded",)
    assert report.manual_intervention_subjects == ("manual",)
    assert report.rate == 0.3333
    assert report.manual_intervention_rate == 0.3333
    assert verify_eadpr(report, subjects, evidence_verifier=_verify_evidence)


def test_early_success_remains_pending_until_fixed_due_cohort_matures() -> None:
    report = compute_eadpr(
        (_subject("early", "2026-08-02T00:00:00Z"),),
        policy_version="eadpr-v1",
        target_approved=True,
        window_start=START,
        reporting_cutoff=CUTOFF,
        sealed_at=SEALED,
        evidence_verifier=_verify_evidence,
    )
    assert report.denominator_subjects == ()
    assert report.numerator_subjects == ()
    assert report.pending_subjects == ("early",)
    assert report.rate is None


def test_unapproved_target_suppresses_numeric_rates_but_preserves_counts() -> None:
    report = compute_eadpr(
        (_subject("one", "2026-07-20T00:00:00Z"),),
        policy_version="eadpr-v1",
        target_approved=False,
        window_start=START,
        reporting_cutoff=CUTOFF,
        sealed_at=SEALED,
        evidence_verifier=_verify_evidence,
    )
    assert report.status == "TARGET_NOT_APPROVED"
    assert report.rate is None
    assert report.manual_intervention_rate is None
    assert report.denominator_subjects == ("one",)


def test_sealed_report_cannot_be_rewritten_by_later_recovery() -> None:
    failed = _subject("one", "2026-07-20T00:00:00Z", success="")
    report = compute_eadpr(
        (failed,),
        policy_version="eadpr-v1",
        target_approved=True,
        window_start=START,
        reporting_cutoff=CUTOFF,
        sealed_at=SEALED,
        evidence_verifier=_verify_evidence,
    )
    recovered = replace(
        failed,
        qualifying_draft_pr_at="2026-08-02T00:00:00Z",
        evidence_bundle_digest=_evidence_digest("one", "2026-08-02T00:00:00Z"),
    )
    assert verify_eadpr(report, (recovered,), evidence_verifier=_verify_evidence)
    assert report.numerator_subjects == ()
    assert report.failure_subjects == ("one",)


def test_work_completed_before_prospective_eligibility_cannot_enter_numerator() -> None:
    subject = replace(
        _subject("one", "2026-07-20T00:00:00Z"),
        eligibility_at="2026-07-10T00:00:00Z",
        qualifying_draft_pr_at="2026-07-09T23:59:59Z",
    )
    report = compute_eadpr(
        (subject,),
        policy_version="eadpr-v1",
        target_approved=True,
        window_start=START,
        reporting_cutoff=CUTOFF,
        sealed_at=SEALED,
        evidence_verifier=_verify_evidence,
    )

    assert report.denominator_subjects == ("one",)
    assert report.numerator_subjects == ()
    assert report.failure_subjects == ("one",)


def test_digest_shaped_but_unverified_evidence_cannot_enter_numerator() -> None:
    fabricated = replace(_subject("one", "2026-07-20T00:00:00Z"), evidence_bundle_digest=D)
    report = compute_eadpr(
        (fabricated,),
        policy_version="eadpr-v1",
        target_approved=True,
        window_start=START,
        reporting_cutoff=CUTOFF,
        sealed_at=SEALED,
        evidence_verifier=_verify_evidence,
    )

    assert report.numerator_subjects == ()
    assert report.failure_subjects == ("one",)
