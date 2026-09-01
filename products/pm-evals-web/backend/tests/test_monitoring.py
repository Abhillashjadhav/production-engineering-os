"""Case-level monitoring contract, diagnosis, storage, and API tests."""

from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from pm_evals_api.app import create_app
from pm_evals_monitoring import (
    FutureObservationError,
    MonitoringStore,
    build_demo_overview,
    build_demo_runs,
    build_overview,
    canonical_run_digest,
    diagnose_run,
)
from pm_evals_monitoring.models import CauseSignal, RunEnvelope

INGEST_TOKEN = "test-monitoring-ingest-token"


def _ingest_headers(token: str = INGEST_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _failed_dream_job_run():
    return next(run for run in reversed(build_demo_runs()) if run.product.id == "dream-job-agent")


def test_planted_failure_localizes_exact_case_and_downstream_symptoms() -> None:
    run = _failed_dream_job_run()
    diagnosis = diagnose_run(run)
    by_id = {item.observation_id: item for item in diagnosis.diagnoses}

    assert diagnosis.health == "FAILING"
    assert diagnosis.likely_starting_observation_ids == ["source-linkedin-coverage"]
    start = by_id["source-linkedin-coverage"]
    assert start.attribution == "LIKELY_STARTING_FAILURE"
    assert start.cause_category == "PROMPT_CONFIG_TOOL_CHANGE"
    assert start.cause_confidence == "SUPPORTED"
    assert start.evidence_level == "CONTROLLED_REPLAY"
    assert by_id["resume-evidence-coverage"].attribution == "DOWNSTREAM_SYMPTOM"
    assert by_id["resume-evidence-coverage"].root_observation_ids == ["source-linkedin-coverage"]


def test_dependency_only_localization_does_not_claim_a_cause() -> None:
    run = _failed_dream_job_run().model_copy(deep=True)
    source = next(
        item for item in run.observations if item.observation_id == "source-linkedin-coverage"
    )
    source.cause_signals = []

    diagnosis = diagnose_run(run)
    start = next(
        item for item in diagnosis.diagnoses if item.observation_id == source.observation_id
    )
    assert start.attribution == "LIKELY_STARTING_FAILURE"
    assert start.cause_category == "UNCONFIRMED"
    assert start.cause_confidence == "UNCONFIRMED"


def test_missing_expected_value_preserves_unknown_regression_magnitude() -> None:
    run = _failed_dream_job_run().model_copy(deep=True)
    source = next(
        item for item in run.observations if item.observation_id == "source-linkedin-coverage"
    )
    source.expected_value = None

    diagnosis = diagnose_run(run)
    start = next(
        item for item in diagnosis.diagnoses if item.observation_id == source.observation_id
    )

    assert start.signed_delta is None
    assert start.regression_magnitude is None


@pytest.mark.parametrize(
    ("status", "current_value", "threshold", "higher_is_better"),
    [
        ("PASS", 0.5, 0.8, True),
        ("FAIL", 0.9, 0.8, True),
        ("PASS", 0.5, 0.2, False),
        ("FAIL", 0.1, 0.2, False),
    ],
)
def test_numeric_status_must_match_the_directional_pass_bar(
    status: str,
    current_value: float,
    threshold: float,
    higher_is_better: bool,
) -> None:
    payload = _failed_dream_job_run().model_dump(mode="json")
    observation = payload["observations"][0]
    observation["status"] = status
    observation["current_value"] = current_value
    observation["threshold"] = threshold
    observation["higher_is_better"] = higher_is_better

    with pytest.raises(ValidationError, match="contradicts the numeric pass bar"):
        RunEnvelope.model_validate(payload)


def test_implausibly_future_observation_time_is_rejected(tmp_path: Path) -> None:
    future_time = datetime.now(UTC) + timedelta(minutes=6)
    payload = _failed_dream_job_run().model_dump(mode="json")
    payload["observed_at"] = future_time.isoformat()

    accepted_before_clock_correction = RunEnvelope.model_validate(payload)
    rollback_dir = tmp_path / "clock-rollback"
    rollback_dir.mkdir()
    (rollback_dir / "observations.jsonl").write_bytes(
        MonitoringStore._canonical_line(accepted_before_clock_correction)
    )
    restored = MonitoringStore(rollback_dir)

    assert restored.list_runs() == [accepted_before_clock_correction]
    assert restored.append(accepted_before_clock_correction) is False

    mutated = _failed_dream_job_run().model_copy(deep=True)
    mutated.observed_at = future_time
    with pytest.raises(FutureObservationError, match="five-minute clock skew"):
        MonitoringStore(tmp_path / "new-evidence").append(mutated)

    client = TestClient(
        create_app(
            monitoring_data_dir=tmp_path / "api",
            monitoring_ingest_token=INGEST_TOKEN,
        )
    )
    response = client.post(
        "/api/monitoring/runs",
        json=payload,
        headers=_ingest_headers(),
    )
    assert response.status_code == 422
    assert response.json()["detail"][0]["source"] == "observed_at"


def test_overflowing_delta_is_unavailable_without_poisoning_history(tmp_path: Path) -> None:
    run = _failed_dream_job_run().model_copy(deep=True)
    source = next(
        item for item in run.observations if item.observation_id == "source-linkedin-coverage"
    )
    source.current_value = 1e308
    source.expected_value = -1e308
    source.threshold = 1.5e308

    diagnosis = diagnose_run(run)
    source_diagnosis = next(
        item for item in diagnosis.diagnoses if item.observation_id == source.observation_id
    )
    store = MonitoringStore(tmp_path)

    assert source_diagnosis.signed_delta is None
    assert source_diagnosis.regression_magnitude is None
    assert store.append(run) is True
    assert store.list_runs() == [run]
    assert (
        build_overview(
            store.list_runs(),
            mode="LIVE",
            generated_at=run.observed_at,
        )
        .products[0]
        .health
        == "FAILING"
    )


@pytest.mark.parametrize(
    ("higher_is_better", "approved_value", "current_value", "threshold", "failed_value"),
    [
        (True, 1e308, -1e308, -1e308, -1.5e308),
        (False, -1e308, 1e308, 1e308, 1.5e308),
    ],
)
def test_overflowing_passing_regression_fails_closed(
    higher_is_better: bool,
    approved_value: float,
    current_value: float,
    threshold: float,
    failed_value: float,
) -> None:
    baseline = next(
        run for run in build_demo_runs() if run.run_id == "dream-job-2026-08-24"
    ).model_copy(deep=True)
    baseline.run_id = f"overflow-approved-{higher_is_better}"
    baseline_source = next(
        item for item in baseline.observations if item.observation_id == "source-linkedin-coverage"
    )
    baseline_source.current_value = approved_value
    baseline_source.expected_value = approved_value
    baseline_source.threshold = threshold
    baseline_source.higher_is_better = higher_is_better

    current = baseline.model_copy(deep=True)
    current.run_id = f"overflow-degraded-{higher_is_better}"
    current.comparison.run_id = baseline.run_id
    current.observed_at = baseline.observed_at + timedelta(days=1)
    current_source = next(
        item
        for item in current.observations
        if item.observation_id == baseline_source.observation_id
    )
    current_source.current_value = current_value
    current_source.expected_value = approved_value

    baseline = RunEnvelope.model_validate(baseline.model_dump(mode="python"))
    current = RunEnvelope.model_validate(current.model_dump(mode="python"))
    current.comparison.sha256 = canonical_run_digest(baseline)
    diagnosis = diagnose_run(current, comparison=baseline)
    degraded = next(
        item
        for item in diagnosis.diagnoses
        if item.observation_id == current_source.observation_id
    )
    overview = build_overview(
        [baseline, current],
        mode="LIVE",
        generated_at=current.observed_at,
    )

    assert diagnosis.health == "DEGRADED"
    assert degraded.attribution == "DEGRADED_CHECK"
    assert degraded.signed_delta is None
    assert degraded.regression_magnitude is None
    assert overview.products[0].health == "DEGRADED"
    assert overview.incidents[0].regression_magnitude is None

    latest = current.model_copy(deep=True)
    latest.run_id = f"after-overflow-{higher_is_better}"
    latest.comparison.run_id = current.run_id
    latest.observed_at = current.observed_at + timedelta(days=1)
    latest_source = next(
        item
        for item in latest.observations
        if item.observation_id == current_source.observation_id
    )
    latest_source.status = "FAIL"
    latest_source.current_value = failed_value
    latest_source.expected_value = current_value
    latest = RunEnvelope.model_validate(latest.model_dump(mode="python"))

    latest_overview = build_overview(
        [baseline, current, latest],
        mode="LIVE",
        generated_at=latest.observed_at,
    )
    latest_incident = next(
        item
        for item in latest_overview.incidents
        if item.observation_id == latest_source.observation_id
    )
    assert latest_incident.comparison_label == "Comparison unavailable"
    assert latest_incident.expected_value is None


def test_observation_extensions_require_finite_json_values(tmp_path: Path) -> None:
    run = _failed_dream_job_run()
    overflowing_json = run.model_dump_json().replace(
        '"extensions":{}',
        '"extensions":{"nested":{"score":1e400}}',
        1,
    )

    with pytest.raises(ValidationError, match="finite JSON numbers"):
        RunEnvelope.model_validate_json(overflowing_json)

    client = TestClient(
        create_app(
            monitoring_data_dir=tmp_path,
            monitoring_ingest_token=INGEST_TOKEN,
        )
    )
    response = client.post(
        "/api/monitoring/runs",
        content=overflowing_json,
        headers={**_ingest_headers(), "content-type": "application/json"},
    )
    assert response.status_code == 422
    assert "finite JSON numbers" in str(response.json())


def test_controlled_replay_requires_a_real_control_and_fixed_dimensions() -> None:
    run = _failed_dream_job_run()
    source = next(
        item for item in run.observations if item.observation_id == "source-linkedin-coverage"
    )
    signal = source.cause_signals[0].model_dump()
    signal["held_constant"] = []

    with pytest.raises(ValidationError, match="held constant"):
        CauseSignal.model_validate(signal)


def test_controlled_replay_requires_distinct_artifacts() -> None:
    run = _failed_dream_job_run()
    source = next(
        item for item in run.observations if item.observation_id == "source-linkedin-coverage"
    )
    signal = source.cause_signals[0].model_dump()
    signal["candidate_ref"] = signal["control_ref"]

    with pytest.raises(ValidationError, match="distinct control and candidate"):
        CauseSignal.model_validate(signal)


def test_controlled_replay_requires_varied_dimension_to_match_cause() -> None:
    run = _failed_dream_job_run()
    source = next(
        item for item in run.observations if item.observation_id == "source-linkedin-coverage"
    )
    signal = source.cause_signals[0].model_dump()
    signal["held_constant"] = [
        dimension for dimension in signal["held_constant"] if dimension != "MODEL"
    ]
    signal["held_constant"].append("TOOLSET")
    signal["varied_dimensions"] = ["MODEL"]

    with pytest.raises(ValidationError, match="asserted cause does not match"):
        CauseSignal.model_validate(signal)

    signal["supports"] = False
    with pytest.raises(ValidationError, match="asserted cause does not match"):
        CauseSignal.model_validate(signal)


def test_controlled_replay_requires_every_dimension_to_be_accounted_for() -> None:
    run = _failed_dream_job_run()
    source = next(
        item for item in run.observations if item.observation_id == "source-linkedin-coverage"
    )
    signal = source.cause_signals[0].model_dump()
    signal["held_constant"].remove("PRODUCTION_COHORT")

    with pytest.raises(ValidationError, match="classify every change dimension"):
        CauseSignal.model_validate(signal)


def test_blocked_upstream_prevents_false_starting_failure() -> None:
    run = _failed_dream_job_run().model_copy(deep=True)
    source = next(
        item for item in run.observations if item.observation_id == "source-linkedin-coverage"
    )
    source.status = "BLOCKED"
    source.current_value = None
    diagnosis = diagnose_run(run)
    by_id = {item.observation_id: item for item in diagnosis.diagnoses}

    assert "source-linkedin-coverage" not in diagnosis.likely_starting_observation_ids
    assert by_id["eligible-job-coverage"].attribution == "UNCONFIRMED"


def test_not_evaluated_upstream_prevents_false_starting_failure() -> None:
    run = _failed_dream_job_run().model_copy(deep=True)
    source = next(
        item for item in run.observations if item.observation_id == "source-linkedin-coverage"
    )
    source.status = "NOT_EVALUATED"
    source.current_value = None
    diagnosis = diagnose_run(run)
    by_id = {item.observation_id: item for item in diagnosis.diagnoses}

    assert "source-linkedin-coverage" not in diagnosis.likely_starting_observation_ids
    assert by_id["eligible-job-coverage"].attribution == "UNCONFIRMED"


def test_missing_parallel_branch_overrides_known_failed_dependency() -> None:
    run = _failed_dream_job_run().model_copy(deep=True)
    blocked = next(
        item for item in run.observations if item.observation_id == "pii-disclosure-rate"
    )
    blocked.status = "BLOCKED"
    blocked.current_value = None
    eligible = next(
        item for item in run.observations if item.observation_id == "eligible-job-coverage"
    )
    eligible.depends_on.append(blocked.observation_id)

    diagnosis = diagnose_run(run)
    by_id = {item.observation_id: item for item in diagnosis.diagnoses}

    assert by_id["source-linkedin-coverage"].attribution == "LIKELY_STARTING_FAILURE"
    assert by_id["eligible-job-coverage"].attribution == "UNCONFIRMED"
    assert by_id["enrichment-completeness"].attribution == "UNCONFIRMED"
    assert by_id["eligible-job-coverage"].root_observation_ids == []


def test_missing_evidence_propagates_through_a_passing_intermediate() -> None:
    run = _failed_dream_job_run().model_copy(deep=True)
    source = next(
        item for item in run.observations if item.observation_id == "source-linkedin-coverage"
    )
    source.status = "BLOCKED"
    source.current_value = None
    intermediate = next(
        item for item in run.observations if item.observation_id == "eligible-job-coverage"
    )
    intermediate.status = "PASS"
    intermediate.current_value = intermediate.expected_value

    diagnosis = diagnose_run(run)
    by_id = {item.observation_id: item for item in diagnosis.diagnoses}

    assert "eligible-job-coverage" not in by_id
    assert by_id["enrichment-completeness"].attribution == "UNCONFIRMED"
    assert by_id["enrichment-completeness"].cause_confidence == "UNCONFIRMED"
    assert "enrichment-completeness" not in diagnosis.likely_starting_observation_ids


def test_regressed_root_propagates_through_a_passing_intermediate() -> None:
    run = _failed_dream_job_run().model_copy(deep=True)
    intermediate = next(
        item for item in run.observations if item.observation_id == "eligible-job-coverage"
    )
    intermediate.status = "PASS"
    intermediate.current_value = intermediate.expected_value

    diagnosis = diagnose_run(run)
    by_id = {item.observation_id: item for item in diagnosis.diagnoses}

    assert "eligible-job-coverage" not in by_id
    downstream = by_id["enrichment-completeness"]
    assert downstream.attribution == "DOWNSTREAM_SYMPTOM"
    assert downstream.root_observation_ids == ["source-linkedin-coverage"]
    assert downstream.cause_confidence == "UNCONFIRMED"
    assert diagnosis.likely_starting_observation_ids == ["source-linkedin-coverage"]


def test_degraded_passing_check_is_projected_as_an_exact_case() -> None:
    baseline = next(item for item in build_demo_runs() if item.run_id == "dream-job-2026-08-24")
    current = baseline.model_copy(deep=True)
    current.run_id = "dream-job-2026-08-25-degraded"
    current.comparison.run_id = baseline.run_id
    current.observed_at = baseline.observed_at + timedelta(days=1)
    regressed = next(
        item for item in current.observations if item.observation_id == "source-linkedin-coverage"
    )
    regressed.current_value = 0.85
    current.comparison.sha256 = canonical_run_digest(baseline)

    diagnosis = diagnose_run(
        current,
        comparison=baseline,
    )
    overview = build_overview([baseline, current], mode="LIVE", generated_at=current.observed_at)

    assert diagnosis.health == "DEGRADED"
    assert diagnosis.fail_count == 0
    degraded = next(
        item for item in diagnosis.diagnoses if item.observation_id == regressed.observation_id
    )
    assert degraded.attribution == "DEGRADED_CHECK"
    assert degraded.regression_magnitude == pytest.approx(0.06)
    assert diagnosis.likely_starting_observation_ids == []
    assert overview.products[0].health == "DEGRADED"
    assert len(overview.incidents) == 1
    assert overview.incidents[0].attribution == "DEGRADED_CHECK"
    assert overview.incidents[0].case.case_id == regressed.case.case_id
    assert overview.incidents[0].regression_magnitude == pytest.approx(0.06)


def test_passing_regression_requires_a_verified_healthy_comparison() -> None:
    baseline = next(item for item in build_demo_runs() if item.run_id == "dream-job-2026-08-24")
    current = baseline.model_copy(deep=True)
    current.run_id = "dream-job-unverified-degradation"
    current.comparison.run_id = baseline.run_id
    current.observed_at = baseline.observed_at + timedelta(days=1)
    regressed = next(
        item for item in current.observations if item.observation_id == "source-linkedin-coverage"
    )
    regressed.current_value = 0.85

    mismatched = baseline.model_copy(deep=True)
    mismatched_source = next(
        item for item in mismatched.observations if item.observation_id == regressed.observation_id
    )
    mismatched_source.current_value = 0.90

    unhealthy = baseline.model_copy(deep=True)
    unrelated = next(
        item for item in unhealthy.observations if item.observation_id == "pii-disclosure-rate"
    )
    unrelated.status = "FAIL"
    unrelated.current_value = 0.1

    assert diagnose_run(current).health == "HEALTHY"
    for overview in (
        build_overview([current], mode="LIVE", generated_at=current.observed_at),
        build_overview(
            [mismatched, current],
            mode="LIVE",
            generated_at=current.observed_at,
        ),
        build_overview(
            [unhealthy, current],
            mode="LIVE",
            generated_at=current.observed_at,
        ),
    ):
        assert overview.products[0].health == "HEALTHY"
        assert overview.incidents == []


def test_required_not_evaluated_observation_blocks_run_health() -> None:
    run = next(
        item for item in build_demo_runs() if item.run_id == "dream-job-2026-08-24"
    ).model_copy(deep=True)
    required = run.observations[0]
    required.status = "NOT_EVALUATED"
    required.current_value = None

    diagnosis = diagnose_run(run)
    overview = build_overview([run], mode="LIVE", generated_at=run.observed_at)

    assert diagnosis.health == "BLOCKED"
    assert overview.products[0].health == "BLOCKED"
    affected_layer = next(
        item for item in overview.products[0].layers if item.name == required.evaluation.layer
    )
    assert affected_layer.health == "BLOCKED"


def test_entirely_optional_unevaluated_coverage_is_not_healthy() -> None:
    run = next(
        item for item in build_demo_runs() if item.run_id == "dream-job-2026-08-24"
    ).model_copy(deep=True)
    optional = next(
        item for item in run.observations if item.observation_id == "pii-disclosure-rate"
    )
    optional.required = False
    optional.status = "NOT_EVALUATED"
    optional.current_value = None
    optional.depends_on = []
    run.observations = [optional]

    diagnosis = diagnose_run(run)
    overview = build_overview([run], mode="LIVE", generated_at=run.observed_at)

    assert diagnosis.health == "HEALTHY"
    assert overview.products[0].health == "HEALTHY"
    assert overview.products[0].layers[0].health == "BLOCKED"
    assert overview.products[0].concerns[0].health == "BLOCKED"


def test_stale_healthy_run_is_blocked_and_not_projected_as_current() -> None:
    run = next(item for item in build_demo_runs() if item.run_id == "dream-job-2026-08-24")
    generated_at = run.observed_at + timedelta(seconds=run.product.freshness_sla_seconds + 1)

    overview = build_overview([run], mode="LIVE", generated_at=generated_at)
    product = overview.products[0]

    assert product.is_stale is True
    assert product.health == "BLOCKED"
    assert all(item.health == "BLOCKED" for item in [*product.layers, *product.concerns])
    assert overview.incidents == []


def test_dependency_validation_and_diagnosis_support_contract_maximum_depth() -> None:
    payload = _failed_dream_job_run().model_dump(mode="json")
    template = payload["observations"][0]
    observations = []
    for index in range(2000):
        observation = deepcopy(template)
        observation_id = f"deep-{index:04d}"
        observation["observation_id"] = observation_id
        observation["location"]["stage_index"] = index + 1
        observation["status"] = "FAIL"
        observation["current_value"] = 0.0
        observation["expected_value"] = 1.0
        observation["depends_on"] = [f"deep-{index - 1:04d}"] if index else []
        observation["cause_signals"] = []
        observations.append(observation)
    payload["observations"] = observations

    run = RunEnvelope.model_validate(payload)
    diagnosis = diagnose_run(run)

    assert len(diagnosis.diagnoses) == 2000
    assert diagnosis.likely_starting_observation_ids == ["deep-0000"]
    assert diagnosis.diagnoses[-1].attribution == "DOWNSTREAM_SYMPTOM"
    assert diagnosis.diagnoses[-1].root_observation_ids == ["deep-0000"]


def test_iterative_dependency_validation_still_rejects_cycles() -> None:
    payload = _failed_dream_job_run().model_dump(mode="json")
    first = deepcopy(payload["observations"][0])
    second = deepcopy(payload["observations"][0])
    first["observation_id"] = "cycle-a"
    first["depends_on"] = ["cycle-b"]
    second["observation_id"] = "cycle-b"
    second["depends_on"] = ["cycle-a"]
    payload["observations"] = [first, second]

    with pytest.raises(ValidationError, match="dependency graph contains a cycle"):
        RunEnvelope.model_validate(payload)


def test_overview_keeps_environments_and_reused_run_ids_separate() -> None:
    production = _failed_dream_job_run().model_copy(deep=True)
    staging = next(
        run
        for run in build_demo_runs()
        if run.product.id == "dream-job-agent" and run.run_id == "dream-job-2026-08-24"
    ).model_copy(deep=True)
    staging.product.environment = "staging"
    staging.run_id = production.run_id
    staging.observed_at = production.observed_at + timedelta(minutes=1)

    overview = build_overview(
        [production, staging],
        mode="LIVE",
        generated_at=staging.observed_at,
    )
    by_environment = {item.environment: item for item in overview.products}

    assert set(by_environment) == {"production", "staging"}
    assert by_environment["production"].health == "FAILING"
    assert by_environment["staging"].health == "HEALTHY"
    assert {(item.product_id, item.environment) for item in overview.trend} == {
        ("dream-job-agent", "production"),
        ("dream-job-agent", "staging"),
    }
    assert overview.incidents[0].environment == "production"


def test_comparison_run_is_resolved_within_product_and_environment() -> None:
    runs = build_demo_runs()
    baseline = next(run for run in runs if run.run_id == "dream-job-2026-08-24")
    current = _failed_dream_job_run()
    foreign_baseline = next(
        run for run in runs if run.run_id == "linkedin-os-2026-08-24"
    ).model_copy(deep=True)
    foreign_baseline.run_id = baseline.run_id
    foreign_baseline.observed_at = baseline.observed_at + timedelta(seconds=1)

    overview = build_overview(
        [baseline, foreign_baseline, current],
        mode="LIVE",
        generated_at=current.observed_at,
    )
    incident = next(item for item in overview.incidents if item.product_id == "dream-job-agent")

    assert {item.dimension for item in incident.changes_since_comparison} == {
        "DEPLOYMENT",
        "TOOLSET",
        "PRODUCTION_COHORT",
    }


def test_missing_comparison_is_never_presented_as_verified_evidence() -> None:
    run = _failed_dream_job_run()

    overview = build_overview([run], mode="LIVE", generated_at=run.observed_at)
    incident = overview.incidents[0]

    assert incident.comparison_run_id == run.comparison.run_id
    assert incident.comparison_label == "Comparison unavailable"
    assert incident.expected_value is None
    assert incident.regression_magnitude is None
    assert "not verified" in incident.expected_summary
    assert incident.changes_since_comparison == []


def test_comparison_requires_a_matching_passing_observation_and_value() -> None:
    runs = build_demo_runs()
    baseline = next(run for run in runs if run.run_id == "dream-job-2026-08-24")
    current = _failed_dream_job_run()

    missing_observation = baseline.model_copy(deep=True)
    missing_observation.observations = [
        item
        for item in missing_observation.observations
        if item.observation_id == "pii-disclosure-rate"
    ]
    missing_incident = build_overview(
        [missing_observation, current],
        mode="LIVE",
        generated_at=current.observed_at,
    ).incidents[0]

    different_value = baseline.model_copy(deep=True)
    comparison_source = next(
        item
        for item in different_value.observations
        if item.observation_id == "source-linkedin-coverage"
    )
    comparison_source.current_value = 0.90
    mismatched_incident = build_overview(
        [different_value, current],
        mode="LIVE",
        generated_at=current.observed_at,
    ).incidents[0]

    unhealthy = baseline.model_copy(deep=True)
    unrelated = next(
        item for item in unhealthy.observations if item.observation_id == "pii-disclosure-rate"
    )
    unrelated.status = "FAIL"
    unhealthy_incident = build_overview(
        [unhealthy, current],
        mode="LIVE",
        generated_at=current.observed_at,
    ).incidents[0]

    not_earlier = baseline.model_copy(deep=True)
    not_earlier.observed_at = current.observed_at
    not_earlier_incident = build_overview(
        [not_earlier, current],
        mode="LIVE",
        generated_at=current.observed_at,
    ).incidents[0]

    for incident in (
        missing_incident,
        mismatched_incident,
        unhealthy_incident,
        not_earlier_incident,
    ):
        assert incident.comparison_label == "Comparison unavailable"
        assert incident.expected_value is None
        assert incident.regression_magnitude is None
        assert incident.changes_since_comparison == []


def test_demo_overview_points_to_case_cause_and_fix_without_asset_churn() -> None:
    overview = build_demo_overview()

    assert overview.mode == "PLANTED_DEMO"
    assert {item.product_id for item in overview.products} == {
        "dream-job-agent",
        "linkedin-research-os",
    }
    incident = overview.incidents[0]
    assert incident.case.case_id == "dj-linkedin-pm-bengaluru-042"
    assert incident.parameter_id == "linkedin-source-coverage"
    assert len(incident.downstream_observation_ids) == 5
    assert incident.cause_category == "PROMPT_CONFIG_TOOL_CHANGE"
    assert incident.cause_confidence == "SUPPORTED"
    assert incident.fix_location == "LinkedIn source adapter / connector-v2 mapping"
    assert incident.maintenance.eval_action == "KEEP"
    assert incident.maintenance.golden_dataset_action == "KEEP"
    changed = {item.dimension for item in incident.changes_since_comparison}
    assert "TOOLSET" in changed
    assert "MODEL" not in changed
    assert overview.attribution_metrics.guardrail_proven is False


def test_overview_incident_ids_are_collision_free_for_legal_delimiters() -> None:
    template = _failed_dream_job_run().model_dump(mode="json")
    first_payload = deepcopy(template)
    first_payload["product"]["id"] = "a"
    first_payload["product"]["environment"] = "b:c"
    first_payload["run_id"] = "d"
    second_payload = deepcopy(template)
    second_payload["product"]["id"] = "a:b"
    second_payload["product"]["environment"] = "c"
    second_payload["run_id"] = "d"

    first = RunEnvelope.model_validate(first_payload)
    second = RunEnvelope.model_validate(second_payload)
    overview = build_overview(
        [first, second],
        mode="LIVE",
        generated_at=first.observed_at,
    )

    assert len(overview.incidents) == 2
    assert len({incident.incident_id for incident in overview.incidents}) == 2


def test_eval_taxonomy_separates_layers_from_concerns() -> None:
    overview = build_demo_overview()
    dream = next(item for item in overview.products if item.product_id == "dream-job-agent")

    assert {item.name for item in dream.layers} >= {"INPUT", "RETRIEVAL_TOOL", "OUTPUT", "OUTCOME"}
    assert {item.name for item in dream.concerns} >= {"INVARIANT", "CAPABILITY", "PRIVACY"}


def test_store_is_append_only_deduplicated_and_digest_checked(tmp_path: Path) -> None:
    store = MonitoringStore(tmp_path)
    run = _failed_dream_job_run()

    assert store.append(run) is True
    assert store.append(run) is False
    assert store.list_runs() == [run]

    conflicting = run.model_copy(deep=True)
    conflicting.observations[0].current_value = 1.1
    try:
        store.append(conflicting)
    except ValueError as exc:
        assert "different evidence" in str(exc)
    else:  # pragma: no cover - protects the immutable-history guarantee
        raise AssertionError("a conflicting run identity was accepted")


def test_store_normalizes_equivalent_timestamp_offsets_for_idempotency(
    tmp_path: Path,
) -> None:
    run = _failed_dream_job_run()
    payload = run.model_dump(mode="json")
    payload["observed_at"] = run.observed_at.astimezone(timezone(timedelta(hours=2))).isoformat()
    equivalent_retry = RunEnvelope.model_validate(payload)
    store = MonitoringStore(tmp_path)

    assert equivalent_retry.observed_at.utcoffset() == timedelta(0)
    assert store.append(run) is True
    assert store.append(equivalent_retry) is False


def test_store_rolls_back_log_when_indexing_fails(tmp_path: Path) -> None:
    store = MonitoringStore(tmp_path)
    run = _failed_dream_job_run()
    original_log = store.log_path.read_bytes()
    with sqlite3.connect(store.index_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_monitoring_index_insert
            BEFORE INSERT ON runs
            BEGIN
                SELECT RAISE(FAIL, 'injected index failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="injected index failure"):
        store.append(run)

    assert store.log_path.read_bytes() == original_log
    assert store.list_runs() == []

    with sqlite3.connect(store.index_path) as connection:
        connection.execute("DROP TRIGGER reject_monitoring_index_insert")
    assert store.append(run) is True
    assert MonitoringStore(tmp_path).list_runs() == [run]


def test_store_reconciles_before_retry_if_append_rollback_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = MonitoringStore(tmp_path)
    run = _failed_dream_job_run()
    with sqlite3.connect(store.index_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_monitoring_index_insert
            BEFORE INSERT ON runs
            BEGIN
                SELECT RAISE(FAIL, 'injected index failure');
            END
            """
        )

    def fail_rollback(_byte_offset: int) -> None:
        raise OSError("injected rollback failure")

    monkeypatch.setattr(store, "_truncate_log", fail_rollback)
    with pytest.raises(RuntimeError, match="must be reconciled"):
        store.append(run)
    with pytest.raises(sqlite3.IntegrityError, match="injected index failure"):
        store.list_runs()

    with sqlite3.connect(store.index_path) as connection:
        connection.execute("DROP TRIGGER reject_monitoring_index_insert")
    assert store.append(run) is False
    assert store.list_runs() == [run]


def test_store_serializes_appends_across_instances(tmp_path: Path) -> None:
    first_store = MonitoringStore(tmp_path)
    second_store = MonitoringStore(tmp_path)
    first_run = _failed_dream_job_run()
    second_run = first_run.model_copy(deep=True)
    second_run.run_id = f"{first_run.run_id}-parallel"
    ready = threading.Barrier(2)

    def append(store: MonitoringStore, run: RunEnvelope) -> bool:
        ready.wait()
        return store.append(run)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(append, first_store, first_run)
        second_future = executor.submit(append, second_store, second_run)
        assert first_future.result() is True
        assert second_future.result() is True

    with sqlite3.connect(first_store.index_path) as connection:
        rows = connection.execute(
            "SELECT byte_offset, byte_length FROM runs ORDER BY byte_offset"
        ).fetchall()
    assert len(rows) == 2
    assert rows[0][0] == 0
    assert rows[0][0] + rows[0][1] == rows[1][0]
    assert rows[1][0] + rows[1][1] == first_store.log_path.stat().st_size
    assert {run.run_id for run in first_store.list_runs()} == {
        first_run.run_id,
        second_run.run_id,
    }


def test_store_identity_is_collision_free_for_legal_control_characters(
    tmp_path: Path,
) -> None:
    template = _failed_dream_job_run().model_dump(mode="json")
    first_payload = deepcopy(template)
    first_payload["product"]["id"] = "a"
    first_payload["product"]["environment"] = "b\x1fc"
    first_payload["run_id"] = "d"
    second_payload = deepcopy(template)
    second_payload["product"]["id"] = "a\x1fb"
    second_payload["product"]["environment"] = "c"
    second_payload["run_id"] = "d"
    first = RunEnvelope.model_validate(first_payload)
    second = RunEnvelope.model_validate(second_payload)
    store = MonitoringStore(tmp_path)

    assert store.append(first) is True
    assert store.append(second) is True
    assert {
        (run.product.id, run.product.environment, run.run_id) for run in store.list_runs()
    } == {("a", "b\x1fc", "d"), ("a\x1fb", "c", "d")}


def test_store_deduplicates_an_identity_from_a_legacy_index_key(tmp_path: Path) -> None:
    store = MonitoringStore(tmp_path)
    run = _failed_dream_job_run()
    assert store.append(run) is True
    legacy_key = f"{run.product.id}\x1f{run.product.environment}\x1f{run.run_id}"
    with sqlite3.connect(store.index_path) as connection:
        connection.execute("UPDATE runs SET run_key = ?", (legacy_key,))

    assert store.append(run) is False
    assert store.list_runs() == [run]


def test_store_recovers_from_an_unterminated_final_append(tmp_path: Path) -> None:
    store = MonitoringStore(tmp_path)
    run = _failed_dream_job_run()
    assert store.append(run) is True
    complete_history = store.log_path.read_bytes()
    with store.log_path.open("ab") as handle:
        handle.write(b'{"contract_version":"0.2","run_id":"torn')

    recovered = MonitoringStore(tmp_path)

    assert recovered.log_path.read_bytes() == complete_history
    assert recovered.list_runs() == [run]


def test_store_rejects_corruption_in_a_completed_record(tmp_path: Path) -> None:
    store = MonitoringStore(tmp_path)
    assert store.append(_failed_dream_job_run()) is True
    with store.log_path.open("ab") as handle:
        handle.write(b"not-json\n")

    with pytest.raises(ValueError, match="completed monitoring log record is invalid"):
        MonitoringStore(tmp_path)


def test_overview_history_query_is_bounded_and_keeps_latest_comparisons(
    tmp_path: Path,
) -> None:
    store = MonitoringStore(tmp_path)
    for run in build_demo_runs():
        assert store.append(run) is True

    bounded = store.list_runs_for_overview(trend_limit_per_product=2)
    identities = {(run.product.id, run.run_id) for run in bounded}

    assert len(bounded) == 6
    assert ("dream-job-agent", "dream-job-2026-08-24") in identities
    assert ("dream-job-agent", "dream-job-2026-08-28") in identities
    assert ("linkedin-research-os", "linkedin-os-2026-08-24") in identities
    assert ("linkedin-research-os", "linkedin-os-2026-08-28") in identities
    assert ("dream-job-agent", "dream-job-2026-08-25") not in identities
    assert ("linkedin-research-os", "linkedin-os-2026-08-26") not in identities


def test_missing_comparison_ancestry_cannot_certify_a_degraded_baseline(
    tmp_path: Path,
) -> None:
    approved = next(
        run for run in build_demo_runs() if run.run_id == "dream-job-2026-08-24"
    ).model_copy(deep=True)
    approved.run_id = "approved-root"
    degraded = approved.model_copy(deep=True)
    degraded.run_id = "passing-but-degraded"
    degraded.comparison.run_id = approved.run_id
    degraded.observed_at = approved.observed_at + timedelta(days=1)
    degraded_source = next(
        item for item in degraded.observations if item.observation_id == "source-linkedin-coverage"
    )
    degraded_source.current_value = 0.85
    degraded.comparison.sha256 = canonical_run_digest(approved)

    current = degraded.model_copy(deep=True)
    current.run_id = "latest-failure"
    current.comparison.run_id = degraded.run_id
    current.observed_at = degraded.observed_at + timedelta(days=1)
    current_source = next(
        item
        for item in current.observations
        if item.observation_id == degraded_source.observation_id
    )
    current_source.status = "FAIL"
    current_source.current_value = 0.42
    current_source.expected_value = degraded_source.current_value
    current.comparison.sha256 = canonical_run_digest(degraded)

    store = MonitoringStore(tmp_path)
    for run in (approved, degraded, current):
        assert store.append(run) is True

    verified_degradation = build_overview(
        [approved, degraded],
        mode="LIVE",
        generated_at=degraded.observed_at,
    )
    assert verified_degradation.products[0].health == "DEGRADED"

    bounded = store.list_runs_for_overview(trend_limit_per_product=1)
    assert {run.run_id for run in bounded} == {degraded.run_id, current.run_id}
    overview = build_overview(bounded, mode="LIVE", generated_at=current.observed_at)
    incident = overview.incidents[0]
    assert incident.comparison_label == "Comparison unavailable"
    assert incident.expected_value is None
    assert incident.regression_magnitude is None
    assert incident.changes_since_comparison == []


def test_bounded_history_loads_comparisons_for_every_retained_trend_run(
    tmp_path: Path,
) -> None:
    first_baseline = next(
        run for run in build_demo_runs() if run.run_id == "dream-job-2026-08-24"
    ).model_copy(deep=True)
    first_baseline.run_id = "first-trend-baseline"
    latest_baseline = first_baseline.model_copy(deep=True)
    latest_baseline.run_id = "latest-trend-baseline"
    latest_baseline.observed_at = first_baseline.observed_at + timedelta(hours=1)

    historical = first_baseline.model_copy(deep=True)
    historical.run_id = "retained-degraded-history"
    historical.comparison.run_id = first_baseline.run_id
    historical.observed_at = first_baseline.observed_at + timedelta(days=1)
    historical_source = next(
        item
        for item in historical.observations
        if item.observation_id == "source-linkedin-coverage"
    )
    historical_source.current_value = 0.85
    historical.comparison.sha256 = canonical_run_digest(first_baseline)

    latest = latest_baseline.model_copy(deep=True)
    latest.run_id = "latest-healthy-run"
    latest.comparison.run_id = latest_baseline.run_id
    latest.comparison.sha256 = canonical_run_digest(latest_baseline)
    latest.observed_at = first_baseline.observed_at + timedelta(days=2)

    store = MonitoringStore(tmp_path)
    for run in (first_baseline, latest_baseline, historical, latest):
        assert store.append(run) is True

    bounded = store.list_runs_for_overview(trend_limit_per_product=2)
    assert {run.run_id for run in bounded} == {
        first_baseline.run_id,
        latest_baseline.run_id,
        historical.run_id,
        latest.run_id,
    }
    overview = build_overview(
        bounded,
        mode="LIVE",
        generated_at=latest.observed_at,
        trend_limit_per_product=2,
    )
    historical_point = next(point for point in overview.trend if point.run_id == historical.run_id)
    assert historical_point.health == "DEGRADED"


def test_equal_observation_times_use_server_arrival_order(tmp_path: Path) -> None:
    first = _failed_dream_job_run().model_copy(deep=True)
    first.run_id = "z-arrived-first"
    second = next(
        run for run in build_demo_runs() if run.run_id == "dream-job-2026-08-24"
    ).model_copy(deep=True)
    second.run_id = "a-arrived-second"
    second.observed_at = first.observed_at
    store = MonitoringStore(tmp_path)

    assert store.append(first) is True
    assert store.append(second) is True

    all_runs = store.list_runs()
    assert [run.run_id for run in all_runs] == [first.run_id, second.run_id]
    overview = build_overview(all_runs, mode="LIVE", generated_at=second.observed_at)
    assert overview.products[0].latest_run_id == second.run_id
    assert overview.products[0].health == "HEALTHY"

    bounded = store.list_runs_for_overview(trend_limit_per_product=1)
    assert [run.run_id for run in bounded] == [second.run_id]


def test_monitoring_api_bounds_live_trend_history(tmp_path: Path) -> None:
    store = MonitoringStore(tmp_path)
    template = next(run for run in build_demo_runs() if run.run_id == "dream-job-2026-08-24")
    history_start = template.observed_at - timedelta(days=34)
    for index in range(35):
        run = template.model_copy(deep=True)
        run.run_id = f"dream-history-{index:02d}"
        run.comparison.run_id = "dream-history-00"
        run.observed_at = history_start + timedelta(days=index)
        assert store.append(run) is True

    client = TestClient(create_app(monitoring_data_dir=tmp_path))
    response = client.get("/api/monitoring/overview")

    assert response.status_code == 200
    assert len(response.json()["trend"]) == 30


def test_monitoring_api_shows_no_data_then_persists_live_run(tmp_path: Path) -> None:
    client = TestClient(
        create_app(monitoring_data_dir=tmp_path, monitoring_ingest_token=INGEST_TOKEN)
    )

    empty = client.get("/api/monitoring/overview")
    assert empty.status_code == 200
    assert empty.json()["mode"] == "NO_DATA"

    run = _failed_dream_job_run().model_copy(deep=True)
    run.observed_at = datetime.now(UTC)
    for observation in run.observations:
        observation.cause_signals = []
    baseline = next(
        item for item in build_demo_runs() if item.run_id == run.comparison.run_id
    ).model_copy(deep=True)
    baseline.observed_at = run.observed_at - timedelta(minutes=1)
    baseline_response = client.post(
        "/api/monitoring/runs",
        json=baseline.model_dump(mode="json"),
        headers=_ingest_headers(),
    )
    assert baseline_response.status_code == 200
    run.comparison.sha256 = MonitoringStore(tmp_path).get_run_digest(
        product_id=baseline.product.id,
        environment=baseline.product.environment,
        run_id=baseline.run_id,
    )
    ingested = client.post(
        "/api/monitoring/runs",
        json=run.model_dump(mode="json"),
        headers=_ingest_headers(),
    )
    assert ingested.status_code == 200
    assert ingested.json()["diagnosis"]["likely_starting_observation_ids"] == [
        "source-linkedin-coverage"
    ]

    live = client.get("/api/monitoring/overview")
    assert live.status_code == 200
    assert live.json()["mode"] == "LIVE"
    assert live.json()["products"][0]["health"] == "FAILING"
    assert live.json()["incidents"][0]["case"]["case_id"] == "dj-linkedin-pm-bengaluru-042"

    duplicate = client.post(
        "/api/monitoring/runs",
        json=run.model_dump(mode="json"),
        headers=_ingest_headers(),
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True


def test_ingest_diagnosis_uses_the_exact_stored_comparison(tmp_path: Path) -> None:
    client = TestClient(
        create_app(monitoring_data_dir=tmp_path, monitoring_ingest_token=INGEST_TOKEN)
    )
    observed_at = datetime.now(UTC)
    baseline = next(
        run for run in build_demo_runs() if run.run_id == "dream-job-2026-08-24"
    ).model_copy(deep=True)
    baseline.run_id = "ingest-verified-baseline"
    baseline.observed_at = observed_at - timedelta(minutes=1)
    current = baseline.model_copy(deep=True)
    current.run_id = "ingest-degraded-current"
    current.comparison.run_id = baseline.run_id
    current.observed_at = observed_at
    regressed = next(
        item for item in current.observations if item.observation_id == "source-linkedin-coverage"
    )
    regressed.current_value = 0.85

    baseline_response = client.post(
        "/api/monitoring/runs",
        json=baseline.model_dump(mode="json"),
        headers=_ingest_headers(),
    )
    current.comparison.sha256 = MonitoringStore(tmp_path).get_run_digest(
        product_id=baseline.product.id,
        environment=baseline.product.environment,
        run_id=baseline.run_id,
    )
    current_response = client.post(
        "/api/monitoring/runs",
        json=current.model_dump(mode="json"),
        headers=_ingest_headers(),
    )
    live_response = client.get("/api/monitoring/overview")

    assert baseline_response.status_code == 200
    assert current_response.status_code == 200
    assert current_response.json()["diagnosis"]["health"] == "DEGRADED"
    assert current_response.json()["diagnosis"]["diagnoses"][0]["attribution"] == "DEGRADED_CHECK"
    assert live_response.status_code == 200
    assert live_response.json()["products"][0]["health"] == "DEGRADED"


def test_monitoring_ingestion_rejects_missing_or_wrong_credentials(tmp_path: Path) -> None:
    client = TestClient(
        create_app(monitoring_data_dir=tmp_path, monitoring_ingest_token=INGEST_TOKEN)
    )
    payload = _failed_dream_job_run().model_dump(mode="json")

    missing = client.post("/api/monitoring/runs", json=payload)
    wrong = client.post(
        "/api/monitoring/runs",
        json=payload,
        headers=_ingest_headers("wrong-token"),
    )

    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert wrong.status_code == 401
    assert client.get("/api/monitoring/overview").json()["mode"] == "NO_DATA"


def test_monitoring_ingestion_fails_closed_without_configured_credential(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app(monitoring_data_dir=tmp_path))

    response = client.post(
        "/api/monitoring/runs",
        json=_failed_dream_job_run().model_dump(mode="json"),
        headers=_ingest_headers(),
    )

    assert response.status_code == 503
    assert client.get("/api/monitoring/overview").json()["mode"] == "NO_DATA"


def test_monitoring_body_routes_document_and_return_custom_validation_shape(
    tmp_path: Path,
) -> None:
    client = TestClient(
        create_app(monitoring_data_dir=tmp_path, monitoring_ingest_token=INGEST_TOKEN)
    )
    schema = client.app.openapi()  # type: ignore[attr-defined]

    for path, headers in (
        ("/api/monitoring/evaluate", {}),
        ("/api/monitoring/runs", _ingest_headers()),
    ):
        validation_schema = schema["paths"][path]["post"]["responses"]["422"]["content"][
            "application/json"
        ]["schema"]
        assert validation_schema == {"$ref": "#/components/schemas/ValidationErrorResponse"}

        response = client.post(path, json={}, headers=headers)
        assert response.status_code == 422
        problem = response.json()["detail"][0]
        assert set(problem) == {"source", "issues"}
