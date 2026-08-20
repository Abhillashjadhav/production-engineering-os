"""Fixed-due-cohort EADPR computation and immutable sealing."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime

from pmpe.contracts.digest import canonical_digest

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class EadprSubject:
    slice_id: str
    eligibility_at: str
    metric_due_at: str
    policy_version: str
    qualifying_draft_pr_at: str = ""
    evidence_bundle_digest: str = ""
    manual_intervention_at: tuple[str, ...] = ()
    exclusion_reason: str = ""


@dataclass(frozen=True)
class EadprReport:
    policy_version: str
    window_start: str
    reporting_cutoff: str
    status: str
    rate: float | None
    denominator_subjects: tuple[str, ...]
    numerator_subjects: tuple[str, ...]
    failure_subjects: tuple[str, ...]
    pending_subjects: tuple[str, ...]
    right_censored_subjects: tuple[str, ...]
    excluded_subjects: tuple[str, ...]
    manual_intervention_subjects: tuple[str, ...]
    manual_intervention_rate: float | None
    sealed_at: str
    report_digest: str = ""

    def with_digest(self) -> EadprReport:
        payload = asdict(self)
        payload["report_digest"] = ""
        return EadprReport(**{**payload, "report_digest": canonical_digest(payload)})


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("EADPR timestamps must carry a timezone")
    return parsed


def compute_eadpr(
    subjects: tuple[EadprSubject, ...],
    *,
    policy_version: str,
    target_approved: bool,
    window_start: str,
    reporting_cutoff: str,
    sealed_at: str,
) -> EadprReport:
    start = _time(window_start)
    cutoff = _time(reporting_cutoff)
    seal_time = _time(sealed_at)
    if start >= cutoff or seal_time < cutoff:
        raise ValueError("EADPR report bounds are invalid or not yet sealable")
    if len({item.slice_id for item in subjects}) != len(subjects):
        raise ValueError("EADPR slice identities must be unique")
    if any(_time(item.eligibility_at) > _time(item.metric_due_at) for item in subjects):
        raise ValueError("EADPR due time cannot precede eligibility")

    exclusions = sorted(
        item.slice_id
        for item in subjects
        if item.exclusion_reason or item.policy_version != policy_version
    )
    eligible = [
        item
        for item in subjects
        if not item.exclusion_reason and item.policy_version == policy_version
    ]
    mature = sorted(
        (item for item in eligible if start < _time(item.metric_due_at) <= cutoff),
        key=lambda item: item.slice_id,
    )
    pending = sorted(item.slice_id for item in eligible if _time(item.metric_due_at) > cutoff)
    right_censored = sorted(
        item.slice_id
        for item in eligible
        if _time(item.eligibility_at) <= cutoff < _time(item.metric_due_at)
    )
    denominator = tuple(item.slice_id for item in mature)
    manual = tuple(
        item.slice_id
        for item in mature
        if any(
            _time(item.eligibility_at) <= _time(at) <= _time(item.metric_due_at)
            for at in item.manual_intervention_at
        )
    )
    numerator = tuple(
        item.slice_id
        for item in mature
        if item.qualifying_draft_pr_at
        and _time(item.eligibility_at)
        <= _time(item.qualifying_draft_pr_at)
        <= _time(item.metric_due_at)
        and _DIGEST.fullmatch(item.evidence_bundle_digest)
        and item.slice_id not in manual
    )
    failures = tuple(sorted(set(denominator) - set(numerator)))
    numeric_allowed = target_approved
    rate = round(len(numerator) / len(denominator), 4) if denominator and numeric_allowed else None
    manual_rate = (
        round(len(manual) / len(denominator), 4) if denominator and numeric_allowed else None
    )
    report = EadprReport(
        policy_version=policy_version,
        window_start=window_start,
        reporting_cutoff=reporting_cutoff,
        status="SEALED" if target_approved else "TARGET_NOT_APPROVED",
        rate=rate,
        denominator_subjects=denominator,
        numerator_subjects=numerator,
        failure_subjects=failures,
        pending_subjects=tuple(pending),
        right_censored_subjects=tuple(right_censored),
        excluded_subjects=tuple(exclusions),
        manual_intervention_subjects=manual,
        manual_intervention_rate=manual_rate,
        sealed_at=sealed_at,
    )
    return report.with_digest()


def verify_eadpr(report: EadprReport, subjects: tuple[EadprSubject, ...]) -> bool:
    if report.report_digest != report.with_digest().report_digest:
        return False
    replayed = compute_eadpr(
        subjects,
        policy_version=report.policy_version,
        target_approved=report.status != "TARGET_NOT_APPROVED",
        window_start=report.window_start,
        reporting_cutoff=report.reporting_cutoff,
        sealed_at=report.sealed_at,
    )
    return replayed == report
