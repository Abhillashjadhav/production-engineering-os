"""Case-level monitoring contract, diagnosis, storage, and API tests."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from pm_evals_api.app import create_app
from pm_evals_monitoring import (
    MonitoringStore,
    build_demo_overview,
    build_demo_runs,
    build_overview,
    diagnose_run,
)
from pm_evals_monitoring.models import CauseSignal, RunEnvelope


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


def test_required_not_evaluated_observation_blocks_run_health() -> None:
    run = next(
        item for item in build_demo_runs() if item.run_id == "dream-job-2026-08-24"
    ).model_copy(deep=True)
    required = run.observations[0]
    required.status = "NOT_EVALUATED"
    required.current_value = None

    diagnosis = diagnose_run(run)
    overview = build_overview([run], mode="LIVE")

    assert diagnosis.health == "BLOCKED"
    assert overview.products[0].health == "BLOCKED"
    affected_layer = next(
        item for item in overview.products[0].layers if item.name == required.evaluation.layer
    )
    assert affected_layer.health == "BLOCKED"


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

    overview = build_overview([production, staging], mode="LIVE")
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

    overview = build_overview([baseline, foreign_baseline, current], mode="LIVE")
    incident = next(item for item in overview.incidents if item.product_id == "dream-job-agent")

    assert {item.dimension for item in incident.changes_since_comparison} == {
        "DEPLOYMENT",
        "TOOLSET",
        "PRODUCTION_COHORT",
    }


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
    conflicting.observations[0].current_value = 0.5
    try:
        store.append(conflicting)
    except ValueError as exc:
        assert "different evidence" in str(exc)
    else:  # pragma: no cover - protects the immutable-history guarantee
        raise AssertionError("a conflicting run identity was accepted")


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


def test_monitoring_api_bounds_live_trend_history(tmp_path: Path) -> None:
    store = MonitoringStore(tmp_path)
    template = next(run for run in build_demo_runs() if run.run_id == "dream-job-2026-08-24")
    for index in range(35):
        run = template.model_copy(deep=True)
        run.run_id = f"dream-history-{index:02d}"
        run.comparison.run_id = "dream-history-00"
        run.observed_at = template.observed_at + timedelta(days=index)
        assert store.append(run) is True

    client = TestClient(create_app(monitoring_data_dir=tmp_path))
    response = client.get("/api/monitoring/overview")

    assert response.status_code == 200
    assert len(response.json()["trend"]) == 30


def test_monitoring_api_runs_planted_demo_and_persists_live_run(tmp_path: Path) -> None:
    client = TestClient(create_app(monitoring_data_dir=tmp_path))

    demo = client.get("/api/monitoring/overview")
    assert demo.status_code == 200
    assert demo.json()["mode"] == "PLANTED_DEMO"

    run = _failed_dream_job_run()
    ingested = client.post("/api/monitoring/runs", json=run.model_dump(mode="json"))
    assert ingested.status_code == 200
    assert ingested.json()["diagnosis"]["likely_starting_observation_ids"] == [
        "source-linkedin-coverage"
    ]

    live = client.get("/api/monitoring/overview")
    assert live.status_code == 200
    assert live.json()["mode"] == "LIVE"
    assert live.json()["products"][0]["health"] == "FAILING"
    assert live.json()["incidents"][0]["case"]["case_id"] == "dj-linkedin-pm-bengaluru-042"

    duplicate = client.post("/api/monitoring/runs", json=run.model_dump(mode="json"))
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
