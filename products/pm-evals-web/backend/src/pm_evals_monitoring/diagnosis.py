"""Deterministic localization, evidence-bounded cause assessment, and projection."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime

from .models import (
    AttributionMetrics,
    CauseCategory,
    CauseConfidence,
    ChangeItem,
    ChangeManifest,
    CoverageHealth,
    EvidenceLevel,
    Incident,
    MaintenanceAssessment,
    MonitoringOverview,
    Observation,
    ObservationDiagnosis,
    ProductHealth,
    RunDiagnosis,
    RunEnvelope,
    RunHealth,
    TrendPoint,
)

_EVIDENCE_RANK: dict[str, int] = {
    "DEPENDENCY_ONLY": 0,
    "CHANGE_CORRELATION": 1,
    "CONTROLLED_REPLAY": 2,
    "HUMAN_ADJUDICATION": 3,
}


def _signed_delta(observation: Observation) -> float | None:
    if observation.current_value is None or observation.expected_value is None:
        return None
    raw = observation.current_value - observation.expected_value
    return raw if observation.higher_is_better else -raw


def _is_degraded(observation: Observation) -> bool:
    delta = _signed_delta(observation)
    return observation.status == "PASS" and delta is not None and delta < -observation.tolerance


def _health(observations: list[Observation]) -> RunHealth:
    if any(item.status == "FAIL" for item in observations):
        return "FAILING"
    if any(item.status == "BLOCKED" for item in observations):
        return "BLOCKED"
    if any(_is_degraded(item) for item in observations):
        return "DEGRADED"
    return "HEALTHY"


def _cause_assessment(
    observation: Observation,
) -> tuple[CauseCategory, CauseConfidence, EvidenceLevel, str]:
    supported = [
        item
        for item in observation.cause_signals
        if item.supports and item.category != "UNCONFIRMED"
    ]
    if not supported:
        return (
            "UNCONFIRMED",
            "UNCONFIRMED",
            "DEPENDENCY_ONLY",
            "No controlled comparison or human decision identifies why this case failed.",
        )

    strongest_rank = max(_EVIDENCE_RANK[item.evidence_level] for item in supported)
    strongest = [
        item for item in supported if _EVIDENCE_RANK[item.evidence_level] == strongest_rank
    ]
    categories = {item.category for item in strongest}
    if len(categories) != 1:
        return (
            "UNCONFIRMED",
            "UNCONFIRMED",
            strongest[0].evidence_level,
            "Equally strong evidence supports multiple causes; do not choose one yet.",
        )

    category = strongest[0].category
    contradicted = any(
        not item.supports
        and item.category == category
        and _EVIDENCE_RANK[item.evidence_level] >= strongest_rank
        for item in observation.cause_signals
    )
    if contradicted:
        return (
            "UNCONFIRMED",
            "UNCONFIRMED",
            strongest[0].evidence_level,
            "Evidence at the same or a stronger level contradicts this cause.",
        )

    level = strongest[0].evidence_level
    confidence: CauseConfidence
    if level == "HUMAN_ADJUDICATION":
        confidence = "CONFIRMED"
    elif level == "CONTROLLED_REPLAY":
        confidence = "SUPPORTED"
    else:
        confidence = "CANDIDATE"
    return category, confidence, level, " ".join(item.summary for item in strongest)


def diagnose_run(run: RunEnvelope) -> RunDiagnosis:
    """Localize the first observable break without claiming unearned causality."""

    by_id = {item.observation_id: item for item in run.observations}
    failed = {item.observation_id for item in run.observations if item.status == "FAIL"}
    missing_evidence = {
        item.observation_id
        for item in run.observations
        if item.status in {"BLOCKED", "NOT_EVALUATED"}
    }
    memo: dict[str, tuple[str, tuple[str, ...], str]] = {}

    def classify(observation_id: str) -> tuple[str, tuple[str, ...], str]:
        if observation_id in memo:
            return memo[observation_id]
        observation = by_id[observation_id]
        failed_dependencies = [item for item in observation.depends_on if item in failed]
        missing_dependencies = [
            item for item in observation.depends_on if item in missing_evidence
        ]
        if failed_dependencies:
            roots: set[str] = set()
            for dependency_id in failed_dependencies:
                attribution, dependency_roots, _ = classify(dependency_id)
                if attribution == "LIKELY_STARTING_FAILURE":
                    roots.add(dependency_id)
                else:
                    roots.update(dependency_roots)
            result = (
                "DOWNSTREAM_SYMPTOM",
                tuple(sorted(roots)),
                "A failed upstream check can explain this later failure.",
            )
        elif missing_dependencies:
            result = (
                "UNCONFIRMED",
                (),
                "Required upstream evidence is blocked or not evaluated, so the starting point is unknown.",
            )
        else:
            result = (
                "LIKELY_STARTING_FAILURE",
                (observation_id,),
                "This is the earliest observed failure in the declared dependency path.",
            )
        memo[observation_id] = result
        return result

    diagnoses: list[ObservationDiagnosis] = []
    for observation in sorted(
        (item for item in run.observations if item.status == "FAIL"),
        key=lambda item: (item.location.stage_index, item.observation_id),
    ):
        attribution, roots, localization_reason = classify(observation.observation_id)
        delta = _signed_delta(observation)
        if attribution == "LIKELY_STARTING_FAILURE":
            cause = _cause_assessment(observation)
        else:
            cause = (
                "UNCONFIRMED",
                "UNCONFIRMED",
                "DEPENDENCY_ONLY",
                "Treat this as a symptom until its upstream failure is resolved.",
            )
        diagnoses.append(
            ObservationDiagnosis(
                observation_id=observation.observation_id,
                attribution=attribution,  # type: ignore[arg-type]
                root_observation_ids=list(roots),
                signed_delta=delta,
                regression_magnitude=abs(delta) if delta is not None and delta < 0 else 0.0,
                localization_reason=localization_reason,
                cause_category=cause[0],
                cause_confidence=cause[1],
                evidence_level=cause[2],
                cause_reason=cause[3],
            )
        )

    counts = Counter(item.status for item in run.observations)
    return RunDiagnosis(
        run_id=run.run_id,
        product_id=run.product.id,
        health=_health(run.observations),
        pass_count=counts["PASS"],
        fail_count=counts["FAIL"],
        blocked_count=counts["BLOCKED"],
        not_evaluated_count=counts["NOT_EVALUATED"],
        likely_starting_observation_ids=[
            item.observation_id
            for item in diagnoses
            if item.attribution == "LIKELY_STARTING_FAILURE"
        ],
        diagnoses=diagnoses,
    )


def _coverage_health(run: RunEnvelope, *, axis: str) -> list[CoverageHealth]:
    grouped: dict[str, list[Observation]] = defaultdict(list)
    for item in run.observations:
        key = item.evaluation.layer if axis == "layer" else item.evaluation.concern
        grouped[key].append(item)
    result: list[CoverageHealth] = []
    for name, observations in sorted(grouped.items()):
        counts = Counter(item.status for item in observations)
        result.append(
            CoverageHealth(
                name=name,
                health=_health(observations),
                pass_count=counts["PASS"],
                fail_count=counts["FAIL"],
                blocked_count=counts["BLOCKED"],
            )
        )
    return result


def _manifest_values(manifest: ChangeManifest) -> dict[str, str]:
    return {
        "USE_CASE": manifest.use_case_version,
        "DEPLOYMENT": manifest.deployment_id,
        "MODEL": f"{manifest.model.provider}/{manifest.model.name}@{manifest.model.snapshot}",
        "PROMPT": manifest.prompt_version,
        "CONFIGURATION": manifest.config_version,
        "TOOLSET": manifest.toolset_version,
        "EVALUATOR": manifest.evaluator_version,
        "RUBRIC": manifest.rubric_version,
        "GOLDEN_DATASET": manifest.golden_dataset_version,
        "PRODUCTION_COHORT": manifest.production_cohort,
    }


def _changes(run: RunEnvelope, comparison: RunEnvelope | None) -> list[ChangeItem]:
    if comparison is None:
        return []
    current = _manifest_values(run.change_manifest)
    previous = _manifest_values(comparison.change_manifest)
    return [
        ChangeItem(dimension=dimension, previous=previous[dimension], current=value)  # type: ignore[arg-type]
        for dimension, value in current.items()
        if value != previous[dimension]
    ]


def _maintenance(category: CauseCategory) -> MaintenanceAssessment:
    if category == "EVAL_DETERIORATION":
        return MaintenanceAssessment(
            eval_action="REVIEW_AFTER_ADJUDICATION",
            golden_dataset_action="KEEP",
            reason="Review the evaluator after a human confirms the product behaviour stayed correct.",
        )
    if category == "GOLDEN_DATASET_GAP":
        return MaintenanceAssessment(
            eval_action="KEEP",
            golden_dataset_action="REVIEW_AFTER_ADJUDICATION",
            reason="Add coverage only after the missing production case is adjudicated.",
        )
    if category == "USE_CASE_DRIFT":
        return MaintenanceAssessment(
            eval_action="INVESTIGATE",
            golden_dataset_action="REVIEW_AFTER_ADJUDICATION",
            reason="Confirm the changed use case, then review whether evals and approved cases still represent it.",
        )
    if category == "UNCONFIRMED":
        return MaintenanceAssessment(
            eval_action="INVESTIGATE",
            golden_dataset_action="INVESTIGATE",
            reason="Do not change either asset until replay or adjudication separates the cause.",
        )
    return MaintenanceAssessment(
        eval_action="KEEP",
        golden_dataset_action="KEEP",
        reason="Current evidence points to the product path, not the eval or approved case set.",
    )


def build_overview(
    runs: list[RunEnvelope],
    *,
    mode: str,
    generated_at: datetime | None = None,
    attribution_metrics: AttributionMetrics | None = None,
) -> MonitoringOverview:
    if not runs:
        raise ValueError("at least one run is required")
    ordered = sorted(
        runs,
        key=lambda item: (
            item.observed_at,
            item.product.id,
            item.product.environment,
            item.run_id,
        ),
    )
    runs_by_identity = {
        (run.product.id, run.product.environment, run.run_id): run for run in ordered
    }
    latest: dict[tuple[str, str], RunEnvelope] = {}
    diagnoses: dict[tuple[str, str, str], RunDiagnosis] = {}
    trend: list[TrendPoint] = []
    for run in ordered:
        diagnosis = diagnose_run(run)
        run_identity = (run.product.id, run.product.environment, run.run_id)
        diagnoses[run_identity] = diagnosis
        latest[(run.product.id, run.product.environment)] = run
        evaluated = diagnosis.pass_count + diagnosis.fail_count
        trend.append(
            TrendPoint(
                product_id=run.product.id,
                environment=run.product.environment,
                observed_at=run.observed_at,
                health=diagnosis.health,
                pass_rate=(diagnosis.pass_count / evaluated) if evaluated else 0.0,
            )
        )

    products: list[ProductHealth] = []
    incidents: list[Incident] = []
    for (product_id, environment), run in sorted(latest.items()):
        run_identity = (product_id, environment, run.run_id)
        diagnosis = diagnoses[run_identity]
        products.append(
            ProductHealth(
                product_id=product_id,
                display_name=run.product.display_name,
                version=run.product.version,
                environment=environment,
                latest_run_id=run.run_id,
                observed_at=run.observed_at,
                health=diagnosis.health,
                pass_count=diagnosis.pass_count,
                fail_count=diagnosis.fail_count,
                blocked_count=diagnosis.blocked_count,
                layers=_coverage_health(run, axis="layer"),
                concerns=_coverage_health(run, axis="concern"),
            )
        )
        by_id = {item.observation_id: item for item in run.observations}
        diagnosis_by_id = {item.observation_id: item for item in diagnosis.diagnoses}
        comparison = runs_by_identity.get((product_id, environment, run.comparison.run_id))
        changes = _changes(run, comparison)
        for starting_id in diagnosis.likely_starting_observation_ids:
            observation = by_id[starting_id]
            item_diagnosis = diagnosis_by_id[starting_id]
            downstream_ids = sorted(
                item.observation_id
                for item in diagnosis.diagnoses
                if item.attribution == "DOWNSTREAM_SYMPTOM"
                and starting_id in item.root_observation_ids
            )
            evidence = list(observation.evidence_refs)
            for signal in observation.cause_signals:
                evidence.extend(signal.evidence_refs)
            unique_evidence = {item.sha256: item for item in evidence}
            incidents.append(
                Incident(
                    incident_id=f"{product_id}:{environment}:{run.run_id}:{starting_id}",
                    product_id=product_id,
                    product_name=run.product.display_name,
                    environment=environment,
                    run_id=run.run_id,
                    comparison_run_id=run.comparison.run_id,
                    comparison_label=run.comparison.label,
                    observed_at=run.observed_at,
                    observation_id=starting_id,
                    case=observation.case,
                    component_id=observation.location.component_id,
                    stage_id=observation.location.stage_id,
                    parameter_id=observation.location.parameter_id,
                    owner_id=observation.location.owner_id,
                    fix_location=observation.location.fix_location,
                    layer=observation.evaluation.layer,
                    concern=observation.evaluation.concern,
                    current_value=observation.current_value,
                    expected_value=observation.expected_value,
                    current_summary=observation.current_summary,
                    expected_summary=observation.expected_summary,
                    threshold=observation.threshold,
                    unit=observation.unit,
                    regression_magnitude=item_diagnosis.regression_magnitude,
                    downstream_observation_ids=downstream_ids,
                    reason_code=observation.reason_code,
                    cause_category=item_diagnosis.cause_category,
                    cause_confidence=item_diagnosis.cause_confidence,
                    evidence_level=item_diagnosis.evidence_level,
                    cause_reason=item_diagnosis.cause_reason,
                    changes_since_comparison=changes,
                    maintenance=_maintenance(item_diagnosis.cause_category),
                    remediation=observation.remediation,
                    evidence_refs=list(unique_evidence.values()),
                )
            )

    default_metrics = AttributionMetrics(
        correctly_localized_rate=None,
        attribution_coverage=None,
        false_attribution_rate=None,
        known_cause_sample_size=0,
        production_adjudicated_sample_size=0,
        guardrail_proven=False,
        label="No adjudicated production incidents yet",
    )
    return MonitoringOverview(
        generated_at=generated_at or datetime.now(UTC),
        mode=mode,  # type: ignore[arg-type]
        products=products,
        incidents=sorted(incidents, key=lambda item: item.observed_at, reverse=True),
        trend=trend,
        attribution_metrics=attribution_metrics or default_metrics,
    )
