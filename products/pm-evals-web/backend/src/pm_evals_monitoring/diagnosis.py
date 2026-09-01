"""Deterministic localization, evidence-bounded cause assessment, and projection."""

from __future__ import annotations

import base64
import json
from collections import Counter, defaultdict, deque
from datetime import UTC, datetime
from math import isfinite

from .models import (
    OVERVIEW_TREND_RUNS_PER_PRODUCT,
    AdjudicationRecord,
    Attribution,
    AttributionMetrics,
    CauseCategory,
    CauseConfidence,
    ChangeItem,
    CoverageHealth,
    EvidenceLevel,
    Incident,
    MaintenanceAssessment,
    MonitoringOverview,
    Observation,
    ObservationDiagnosis,
    ProductHealth,
    ProductRef,
    RunDiagnosis,
    RunEnvelope,
    RunHealth,
    RunReceipt,
    TrendPoint,
    canonical_run_digest,
    manifest_values,
)

_EVIDENCE_RANK: dict[str, int] = {
    "DEPENDENCY_ONLY": 0,
    "CHANGE_CORRELATION": 1,
    "CONTROLLED_REPLAY": 2,
    "HUMAN_ADJUDICATION": 3,
}


def _incident_id(*parts: str) -> str:
    payload = json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode()
    token = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    return f"incident-{token}"


def _signed_delta(observation: Observation) -> float | None:
    if observation.current_value is None or observation.expected_value is None:
        return None
    raw = observation.current_value - observation.expected_value
    if not isfinite(raw):
        return None
    return raw if observation.higher_is_better else -raw


def _verified_comparison_observation(
    run: RunEnvelope,
    observation: Observation,
    comparison: RunEnvelope | None,
    comparison_health: RunHealth | None,
) -> Observation | None:
    """Return the exact approved observation only when its value is comparable."""

    if (
        comparison is None
        or comparison_health != "HEALTHY"
        or comparison.observed_at >= run.observed_at
        or observation.expected_value is None
    ):
        return None
    candidate = next(
        (
            item
            for item in comparison.observations
            if item.observation_id == observation.observation_id
        ),
        None,
    )
    if candidate is None or candidate.status != "PASS" or candidate.current_value is None:
        return None
    same_case = (
        candidate.case.case_id == observation.case.case_id
        and candidate.case.use_case_id == observation.case.use_case_id
        and candidate.case.segment == observation.case.segment
        and candidate.case.input_fingerprint == observation.case.input_fingerprint
    )
    same_check = (
        candidate.evaluation.layer == observation.evaluation.layer
        and candidate.evaluation.concern == observation.evaluation.concern
        and candidate.evaluation.suite_id == observation.evaluation.suite_id
        and candidate.evaluation.suite_version == observation.evaluation.suite_version
        and candidate.evaluation.method == observation.evaluation.method
        and candidate.location.component_id == observation.location.component_id
        and candidate.location.stage_id == observation.location.stage_id
        and candidate.location.parameter_id == observation.location.parameter_id
        and candidate.unit == observation.unit
        and candidate.higher_is_better == observation.higher_is_better
    )
    if not same_case or not same_check:
        return None
    if candidate.current_value != observation.expected_value:
        return None
    return candidate


def _exceeds_degradation_tolerance(observation: Observation) -> bool:
    if (
        observation.status != "PASS"
        or observation.current_value is None
        or observation.expected_value is None
    ):
        return False
    if observation.higher_is_better:
        if observation.current_value >= observation.expected_value:
            return False
        regression_gap = observation.expected_value - observation.current_value
    else:
        if observation.current_value <= observation.expected_value:
            return False
        regression_gap = observation.current_value - observation.expected_value
    # Both operands are finite. A positive overflow therefore represents a real
    # regression beyond every finite tolerance, even though its magnitude cannot
    # be represented for display.
    return not isfinite(regression_gap) or regression_gap > observation.tolerance


def _verified_degraded_observation_ids(
    run: RunEnvelope,
    comparison: RunEnvelope | None,
    comparison_health: RunHealth | None,
) -> set[str]:
    return {
        observation.observation_id
        for observation in run.observations
        if _exceeds_degradation_tolerance(observation)
        and _verified_comparison_observation(
            run,
            observation,
            comparison,
            comparison_health,
        )
        is not None
    }


def _health(
    observations: list[Observation],
    degraded_observation_ids: set[str] | None = None,
) -> RunHealth:
    if any(item.status == "FAIL" for item in observations):
        return "FAILING"
    if any(
        item.status == "BLOCKED" or (item.required and item.status == "NOT_EVALUATED")
        for item in observations
    ):
        return "BLOCKED"
    if degraded_observation_ids and any(
        item.observation_id in degraded_observation_ids for item in observations
    ):
        return "DEGRADED"
    return "HEALTHY"


def _certified_comparison_health(comparison: RunEnvelope | None) -> RunHealth | None:
    """Return HEALTHY only when no missing ancestry could hide degradation."""

    if comparison is None:
        return None
    status_health = _health(comparison.observations)
    if status_health != "HEALTHY":
        return status_health
    if any(_exceeds_degradation_tolerance(item) for item in comparison.observations):
        return None
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
            "No controlled comparison or human decision identifies why this result changed.",
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


def diagnose_run(
    run: RunEnvelope,
    *,
    comparison: RunEnvelope | None = None,
) -> RunDiagnosis:
    """Localize the first observable break without claiming unearned causality."""

    by_id = {item.observation_id: item for item in run.observations}
    failed = {item.observation_id for item in run.observations if item.status == "FAIL"}
    degraded = _verified_degraded_observation_ids(
        run,
        comparison,
        _certified_comparison_health(comparison),
    )
    diagnosable = failed | degraded
    missing_evidence = {
        item.observation_id
        for item in run.observations
        if item.status in {"BLOCKED", "NOT_EVALUATED"}
    }
    remaining_dependencies = {
        observation_id: len(item.depends_on) for observation_id, item in by_id.items()
    }
    dependents: dict[str, list[str]] = defaultdict(list)
    for observation_id, item in by_id.items():
        for dependency_id in item.depends_on:
            dependents[dependency_id].append(observation_id)
    ready = deque(
        observation_id
        for observation_id, remaining in remaining_dependencies.items()
        if remaining == 0
    )
    topological_order: list[str] = []
    while ready:
        observation_id = ready.popleft()
        topological_order.append(observation_id)
        for dependent_id in dependents[observation_id]:
            remaining_dependencies[dependent_id] -= 1
            if remaining_dependencies[dependent_id] == 0:
                ready.append(dependent_id)
    if len(topological_order) != len(by_id):
        raise ValueError("observation dependency graph contains a cycle")

    classifications: dict[str, tuple[Attribution, tuple[str, ...], str]] = {}
    unresolved_ancestry: dict[str, bool] = {}
    regressed_ancestry: dict[str, set[str]] = {}
    for observation_id in topological_order:
        observation = by_id[observation_id]
        upstream_is_unresolved = any(
            unresolved_ancestry[dependency_id] for dependency_id in observation.depends_on
        )
        upstream_regressed_roots = {
            root_id
            for dependency_id in observation.depends_on
            for root_id in regressed_ancestry[dependency_id]
        }
        unresolved_ancestry[observation_id] = (
            observation_id in missing_evidence or upstream_is_unresolved
        )
        if observation_id not in diagnosable:
            regressed_ancestry[observation_id] = upstream_regressed_roots
            continue
        result: tuple[Attribution, tuple[str, ...], str]
        if upstream_is_unresolved:
            result = (
                "UNCONFIRMED",
                (),
                (
                    "At least one earlier branch in the declared dependency path is blocked "
                    "or not evaluated, so the starting point is unknown."
                ),
            )
            regressed_ancestry[observation_id] = upstream_regressed_roots
        elif upstream_regressed_roots:
            result = (
                "DOWNSTREAM_SYMPTOM",
                tuple(sorted(upstream_regressed_roots)),
                "A regressed upstream check can explain this later result.",
            )
            regressed_ancestry[observation_id] = upstream_regressed_roots
        elif observation_id in failed:
            result = (
                "LIKELY_STARTING_FAILURE",
                (observation_id,),
                "This is the earliest observed failure in the declared dependency path.",
            )
            regressed_ancestry[observation_id] = {observation_id}
        else:
            result = (
                "DEGRADED_CHECK",
                (observation_id,),
                "This check still passes, but its result regressed beyond the allowed tolerance.",
            )
            regressed_ancestry[observation_id] = {observation_id}
        classifications[observation_id] = result

    diagnoses: list[ObservationDiagnosis] = []
    for observation in sorted(
        (
            item
            for item in run.observations
            if item.status == "FAIL" or item.observation_id in degraded
        ),
        key=lambda item: (item.location.stage_index, item.observation_id),
    ):
        attribution, classified_roots, localization_reason = classifications[
            observation.observation_id
        ]
        delta = _signed_delta(observation)
        if attribution in {"LIKELY_STARTING_FAILURE", "DEGRADED_CHECK"}:
            cause = _cause_assessment(observation)
        elif attribution == "DOWNSTREAM_SYMPTOM":
            cause = (
                "UNCONFIRMED",
                "UNCONFIRMED",
                "DEPENDENCY_ONLY",
                "Treat this as a symptom until its upstream failure is resolved.",
            )
        else:
            cause = (
                "UNCONFIRMED",
                "UNCONFIRMED",
                "DEPENDENCY_ONLY",
                "Do not assign a cause until blocked or unevaluated upstream evidence is resolved.",
            )
        diagnoses.append(
            ObservationDiagnosis(
                observation_id=observation.observation_id,
                attribution=attribution,
                root_observation_ids=list(classified_roots),
                signed_delta=delta,
                regression_magnitude=(None if delta is None else abs(delta) if delta < 0 else 0.0),
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
        health=_health(run.observations, degraded),
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


def _coverage_health(
    run: RunEnvelope,
    *,
    axis: str,
    force_blocked: bool = False,
    degraded_observation_ids: set[str] | None = None,
) -> list[CoverageHealth]:
    grouped: dict[str, list[Observation]] = defaultdict(list)
    for item in run.observations:
        key = item.evaluation.layer if axis == "layer" else item.evaluation.concern
        grouped[key].append(item)
    result: list[CoverageHealth] = []
    for name, observations in sorted(grouped.items()):
        counts = Counter(item.status for item in observations)
        entirely_not_evaluated = all(item.status == "NOT_EVALUATED" for item in observations)
        result.append(
            CoverageHealth(
                name=name,
                health=(
                    "BLOCKED"
                    if force_blocked or entirely_not_evaluated
                    else _health(observations, degraded_observation_ids)
                ),
                pass_count=counts["PASS"],
                fail_count=counts["FAIL"],
                blocked_count=counts["BLOCKED"],
            )
        )
    return result


def _changes(run: RunEnvelope, comparison: RunEnvelope | None) -> list[ChangeItem]:
    if comparison is None:
        return []
    current = manifest_values(run.change_manifest)
    previous = manifest_values(comparison.change_manifest)
    return [
        ChangeItem(dimension=dimension, previous=previous[dimension], current=value)
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


def attribution_metrics_from_adjudications(
    records: list[AdjudicationRecord],
) -> AttributionMetrics:
    latest: dict[tuple[str, str], tuple[AdjudicationRecord, int]] = {}
    for index, item in enumerate(records):
        identity = (item.case_incident_id, item.observation_id)
        current = latest.get(identity)
        if current is None or (item.adjudicated_at, index) >= (
            current[0].adjudicated_at,
            current[1],
        ):
            latest[identity] = (item, index)
    case_records: dict[str, list[AdjudicationRecord]] = defaultdict(list)
    for item, _ in latest.values():
        case_records[item.case_incident_id].append(item)
    case_verdicts = {
        incident_id: (
            "INCORRECT"
            if any(item.verdict == "INCORRECT" for item in items)
            else "CORRECT"
            if all(item.verdict == "CORRECT" for item in items)
            else "UNRESOLVED"
        )
        for incident_id, items in case_records.items()
    }
    resolved = [verdict for verdict in case_verdicts.values() if verdict != "UNRESOLVED"]
    correct = resolved.count("CORRECT")
    incorrect = resolved.count("INCORRECT")
    sample = len(resolved)
    return AttributionMetrics(
        correctly_localized_rate=(correct / sample if sample else None),
        attribution_coverage=(sample / len(case_verdicts) if case_verdicts else None),
        false_attribution_rate=(incorrect / sample if sample else None),
        known_cause_sample_size=sample,
        production_adjudicated_sample_size=len(case_verdicts),
        guardrail_proven=(sample >= 149 and incorrect / sample < 0.02),
        label=(
            f"{sample} resolved independent case incidents"
            if records
            else "No adjudicated production incidents yet"
        ),
    )


def _digest_verified_comparison(
    run: RunEnvelope, comparison: RunEnvelope | None
) -> RunEnvelope | None:
    if comparison is None:
        return None
    # Legacy V0.2 envelopes did not require a comparison digest. Overview inputs
    # come from digest-checked ledger rows, so keep those comparisons readable.
    if (
        run.comparison.sha256 is not None
        and canonical_run_digest(comparison) != run.comparison.sha256
    ):
        return None
    return comparison


def _receipt_products(
    receipts: list[RunReceipt],
    *,
    generated_at: datetime,
    existing: list[ProductHealth],
) -> list[ProductHealth]:
    by_identity = {(item.product_id, item.environment): item for item in existing}
    latest: dict[tuple[str, str], RunReceipt] = {}
    for receipt in receipts:
        identity = (receipt.product.id, receipt.product.environment)
        if identity not in latest or receipt.observed_at >= latest[identity].observed_at:
            latest[identity] = receipt
    for identity, receipt in latest.items():
        current = by_identity.get(identity)
        if (
            current is not None
            and current.latest_run_id != "NOT_RECEIVED"
            and receipt.observed_at <= current.observed_at
        ):
            # Lifecycle evidence older than an actual completed envelope must
            # not replace that envelope, even when it reuses the same run ID.
            # Registered NOT_RECEIVED placeholders are not run evidence and
            # must accept their first real lifecycle receipt.
            continue
        overdue = generated_at > receipt.expected_next_run_at
        completed_run_present = (
            current is not None
            and current.latest_run_id == receipt.run_id
            and receipt.status == "COMPLETED"
        )
        if completed_run_present and not overdue:
            continue
        by_identity[identity] = ProductHealth(
            product_id=receipt.product.id,
            display_name=receipt.product.display_name,
            version=receipt.product.version,
            environment=receipt.product.environment,
            latest_run_id=receipt.run_id,
            observed_at=receipt.observed_at,
            health="BLOCKED",
            is_stale=overdue,
            freshness_sla_seconds=(
                current.freshness_sla_seconds
                if current is not None
                else receipt.product.freshness_sla_seconds
            ),
            pass_count=0,
            fail_count=0,
            blocked_count=1,
            layers=[],
            concerns=[],
        )
    return [by_identity[key] for key in sorted(by_identity)]


def _registered_products(
    products: list[ProductRef],
    *,
    generated_at: datetime,
    existing: list[ProductHealth],
) -> list[ProductHealth]:
    """Make configured products visible before their first producer emission."""

    by_identity = {(item.product_id, item.environment): item for item in existing}
    for product in products:
        identity = (product.id, product.environment)
        if identity in by_identity:
            by_identity[identity] = by_identity[identity].model_copy(
                update={"freshness_sla_seconds": product.freshness_sla_seconds}
            )
            continue
        by_identity[identity] = ProductHealth(
            product_id=product.id,
            display_name=product.display_name,
            version=product.version,
            environment=product.environment,
            latest_run_id="NOT_RECEIVED",
            observed_at=generated_at,
            health="BLOCKED",
            is_stale=True,
            freshness_sla_seconds=product.freshness_sla_seconds,
            pass_count=0,
            fail_count=0,
            blocked_count=1,
            layers=[],
            concerns=[],
        )
    return [by_identity[key] for key in sorted(by_identity)]


def build_empty_overview(
    *,
    generated_at: datetime | None = None,
    receipts: list[RunReceipt] | None = None,
    adjudications: list[AdjudicationRecord] | None = None,
    expected_products: list[ProductRef] | None = None,
) -> MonitoringOverview:
    reference_time = generated_at or datetime.now(UTC)
    products = _registered_products(
        expected_products or [], generated_at=reference_time, existing=[]
    )
    return MonitoringOverview(
        generated_at=reference_time,
        mode="NO_DATA",
        products=_receipt_products(receipts or [], generated_at=reference_time, existing=products),
        incidents=[],
        trend=[],
        attribution_metrics=attribution_metrics_from_adjudications(adjudications or []),
    )


def build_overview(
    runs: list[RunEnvelope],
    *,
    mode: str,
    generated_at: datetime | None = None,
    attribution_metrics: AttributionMetrics | None = None,
    receipts: list[RunReceipt] | None = None,
    adjudications: list[AdjudicationRecord] | None = None,
    expected_products: list[ProductRef] | None = None,
    trend_limit_per_product: int = OVERVIEW_TREND_RUNS_PER_PRODUCT,
) -> MonitoringOverview:
    if not runs:
        raise ValueError("at least one run is required")
    if trend_limit_per_product < 1:
        raise ValueError("trend_limit_per_product must be at least one")
    reference_time = generated_at or datetime.now(UTC)
    registered_by_identity = {
        (product.id, product.environment): product for product in expected_products or []
    }
    # The store returns runs in append order, which is the authoritative
    # server-owned tie-break when producer observation timestamps are equal.
    ordered = [
        item
        for _, item in sorted(
            enumerate(runs),
            key=lambda indexed: (
                indexed[1].observed_at,
                indexed[1].product.id,
                indexed[1].product.environment,
                indexed[0],
            ),
        )
    ]
    runs_by_identity = {
        (run.product.id, run.product.environment, run.run_id): run for run in ordered
    }
    latest: dict[tuple[str, str], RunEnvelope] = {}
    diagnoses: dict[tuple[str, str, str], RunDiagnosis] = {}
    trend_by_product: dict[tuple[str, str], list[TrendPoint]] = defaultdict(list)
    for run in ordered:
        run_identity = (run.product.id, run.product.environment, run.run_id)
        comparison_identity = (
            run.product.id,
            run.product.environment,
            run.comparison.run_id,
        )
        comparison = _digest_verified_comparison(run, runs_by_identity.get(comparison_identity))
        diagnosis = diagnose_run(
            run,
            comparison=comparison,
        )
        diagnoses[run_identity] = diagnosis
        latest[(run.product.id, run.product.environment)] = run
        evaluated = diagnosis.pass_count + diagnosis.fail_count
        trend_by_product[(run.product.id, run.product.environment)].append(
            TrendPoint(
                product_id=run.product.id,
                environment=run.product.environment,
                run_id=run.run_id,
                observed_at=run.observed_at,
                health=diagnosis.health,
                pass_rate=(diagnosis.pass_count / evaluated) if evaluated else 0.0,
            )
        )

    trend = sorted(
        (
            point
            for points in trend_by_product.values()
            for point in points[-trend_limit_per_product:]
        ),
        key=lambda point: (point.observed_at, point.product_id, point.environment),
    )
    products: list[ProductHealth] = []
    incidents: list[Incident] = []
    for (product_id, environment), run in sorted(latest.items()):
        run_identity = (product_id, environment, run.run_id)
        diagnosis = diagnoses[run_identity]
        by_id = {item.observation_id: item for item in run.observations}
        degraded_observation_ids = {
            item.observation_id
            for item in diagnosis.diagnoses
            if by_id[item.observation_id].status == "PASS"
        }
        registered = registered_by_identity.get((product_id, environment))
        freshness_sla_seconds = (
            registered.freshness_sla_seconds
            if registered is not None
            else run.product.freshness_sla_seconds
        )
        is_stale = (reference_time - run.observed_at).total_seconds() > freshness_sla_seconds
        products.append(
            ProductHealth(
                product_id=product_id,
                display_name=run.product.display_name,
                version=run.product.version,
                environment=environment,
                latest_run_id=run.run_id,
                observed_at=run.observed_at,
                health=("BLOCKED" if is_stale else diagnosis.health),
                is_stale=is_stale,
                freshness_sla_seconds=freshness_sla_seconds,
                pass_count=diagnosis.pass_count,
                fail_count=diagnosis.fail_count,
                blocked_count=diagnosis.blocked_count,
                layers=_coverage_health(
                    run,
                    axis="layer",
                    force_blocked=is_stale,
                    degraded_observation_ids=degraded_observation_ids,
                ),
                concerns=_coverage_health(
                    run,
                    axis="concern",
                    force_blocked=is_stale,
                    degraded_observation_ids=degraded_observation_ids,
                ),
            )
        )
        if is_stale:
            continue
        comparison_identity = (product_id, environment, run.comparison.run_id)
        comparison = _digest_verified_comparison(run, runs_by_identity.get(comparison_identity))
        comparison_health = _certified_comparison_health(comparison)
        run_changes = _changes(run, comparison)
        projected_diagnoses = [
            item
            for item in diagnosis.diagnoses
            if item.attribution in {"LIKELY_STARTING_FAILURE", "DEGRADED_CHECK"}
        ]
        for item_diagnosis in projected_diagnoses:
            projected_id = item_diagnosis.observation_id
            observation = by_id[projected_id]
            comparison_observation = _verified_comparison_observation(
                run,
                observation,
                comparison,
                comparison_health,
            )
            comparison_available = comparison_observation is not None
            downstream_ids = sorted(
                item.observation_id
                for item in diagnosis.diagnoses
                if item.attribution == "DOWNSTREAM_SYMPTOM"
                and projected_id in item.root_observation_ids
            )
            evidence = list(observation.evidence_refs)
            for signal in observation.cause_signals:
                evidence.extend(signal.evidence_refs)
            unique_evidence = {item.sha256: item for item in evidence}
            incidents.append(
                Incident(
                    incident_id=_incident_id(
                        product_id,
                        environment,
                        run.run_id,
                        projected_id,
                    ),
                    attribution=item_diagnosis.attribution,  # type: ignore[arg-type]
                    product_id=product_id,
                    product_name=run.product.display_name,
                    environment=environment,
                    run_id=run.run_id,
                    comparison_run_id=run.comparison.run_id,
                    comparison_label=(
                        run.comparison.label if comparison_available else "Comparison unavailable"
                    ),
                    observed_at=run.observed_at,
                    observation_id=projected_id,
                    case=observation.case,
                    component_id=observation.location.component_id,
                    stage_id=observation.location.stage_id,
                    parameter_id=observation.location.parameter_id,
                    owner_id=observation.location.owner_id,
                    fix_location=observation.location.fix_location,
                    layer=observation.evaluation.layer,
                    concern=observation.evaluation.concern,
                    current_value=observation.current_value,
                    expected_value=(
                        comparison_observation.current_value
                        if comparison_observation is not None
                        else None
                    ),
                    current_summary=observation.current_summary,
                    expected_summary=(
                        comparison_observation.current_summary
                        if comparison_observation is not None
                        else "The referenced comparison does not contain a matching passing "
                        "observation with this expected value, so the expectation is not verified."
                    ),
                    threshold=observation.threshold,
                    unit=observation.unit,
                    regression_magnitude=(
                        item_diagnosis.regression_magnitude if comparison_available else None
                    ),
                    downstream_observation_ids=downstream_ids,
                    reason_code=observation.reason_code,
                    cause_category=item_diagnosis.cause_category,
                    cause_confidence=item_diagnosis.cause_confidence,
                    evidence_level=item_diagnosis.evidence_level,
                    cause_reason=item_diagnosis.cause_reason,
                    changes_since_comparison=(run_changes if comparison_available else []),
                    maintenance=_maintenance(item_diagnosis.cause_category),
                    remediation=observation.remediation,
                    evidence_refs=list(unique_evidence.values()),
                )
            )

    default_metrics = attribution_metrics_from_adjudications(adjudications or [])
    return MonitoringOverview(
        generated_at=reference_time,
        mode=mode,  # type: ignore[arg-type]
        products=_receipt_products(
            receipts or [],
            generated_at=reference_time,
            existing=_registered_products(
                expected_products or [], generated_at=reference_time, existing=products
            ),
        ),
        incidents=sorted(incidents, key=lambda item: item.observed_at, reverse=True),
        trend=trend,
        attribution_metrics=attribution_metrics or default_metrics,
    )
