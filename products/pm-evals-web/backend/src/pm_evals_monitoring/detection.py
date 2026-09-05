"""Independent failure labels, including failures the dashboard never flagged."""

from __future__ import annotations

from collections import defaultdict
from typing import Literal

from pydantic import AwareDatetime, Field, field_validator, model_validator

from .models import DetectionMetric, EvidenceRef, StrictModel, validate_redacted_text

DetectionLayer = Literal["TOOL_TRAJECTORY", "SYSTEM", "OUTPUT"]
DETECTION_LAYERS: tuple[DetectionLayer, ...] = ("TOOL_TRAJECTORY", "SYSTEM", "OUTPUT")


class DetectionReview(StrictModel):
    review_id: str = Field(min_length=1, max_length=120)
    product_id: str = Field(min_length=1, max_length=120)
    environment: str = Field(min_length=1, max_length=120)
    run_id: str = Field(min_length=1, max_length=160)
    case_id: str = Field(min_length=1, max_length=120)
    observation_id: str | None = Field(default=None, min_length=1, max_length=160)
    layer: DetectionLayer
    actual_failure: bool
    silent: bool
    evidence_scope: Literal["TEST", "PRODUCTION"]
    dataset_version: str = Field(min_length=1, max_length=120)
    reviewer_id: str = Field(min_length=1, max_length=120)
    reviewed_at: AwareDatetime
    evidence_refs: list[EvidenceRef] = Field(min_length=1, max_length=20)

    @field_validator(
        "review_id",
        "product_id",
        "environment",
        "run_id",
        "case_id",
        "observation_id",
        "dataset_version",
        "reviewer_id",
    )
    @classmethod
    def redact_labels(cls, value: str | None) -> str | None:
        return validate_redacted_text(value) if value is not None else None

    @model_validator(mode="after")
    def validate_silent(self) -> DetectionReview:
        if self.silent and not self.actual_failure:
            raise ValueError("a silent failure must be independently confirmed as a failure")
        return self


class RecordedDetectionReview(DetectionReview):
    detected: bool


def detection_metrics(reviews: list[RecordedDetectionReview]) -> list[DetectionMetric]:
    groups: dict[
        tuple[str, str, Literal["TEST", "PRODUCTION"], str], list[RecordedDetectionReview]
    ] = defaultdict(list)
    for review in reviews:
        groups[
            (review.product_id, review.environment, review.evidence_scope, review.dataset_version)
        ].append(review)
    result: list[DetectionMetric] = []
    for (product, environment, scope, version), rows in sorted(groups.items()):
        for layer in DETECTION_LAYERS:
            selected = [row for row in rows if row.layer == layer]
            failures = [row for row in selected if row.actual_failure and row.silent]
            detected = sum(row.detected for row in failures)
            recall = detected / len(failures) if failures else None
            result.append(
                DetectionMetric(
                    product_id=product,
                    environment=environment,
                    layer=layer,
                    evidence_scope=scope,
                    dataset_version=version,
                    reviewed_cases=len(selected),
                    silent_failures=len(failures),
                    detected_silent_failures=detected,
                    missed_silent_failures=len(failures) - detected,
                    silent_failure_recall=recall,
                    status="UNPROVEN"
                    if recall is None
                    else "OBSERVED_ABOVE_TARGET"
                    if recall > 0.9
                    else "BELOW_TARGET",
                )
            )
    return result
