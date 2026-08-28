"""Case-level monitoring contract, diagnosis, storage, and API tests."""

from __future__ import annotations

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
from pm_evals_monitoring.models import CauseSignal


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
