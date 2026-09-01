"""Production monitoring lifecycle, trust, and horizontal adapter tests."""

from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from pm_evals_api.app import create_app
from pm_evals_monitoring import (
    AdapterSettings,
    AdjudicationRecord,
    NormalizedRun,
    ProductRef,
    RunEnvelope,
    RunReceipt,
    build_demo_runs,
    build_overview,
    canonical_run_digest,
    case_incident_id,
    map_normalized_run,
)
from pm_evals_monitoring import outbox as outbox_module
from pm_evals_monitoring import storage as storage_module
from pm_evals_monitoring.diagnosis import attribution_metrics_from_adjudications
from pm_evals_monitoring.outbox import enqueue, flush
from pm_evals_monitoring.storage import MonitoringStore


def _run() -> RunEnvelope:
    run = next(item for item in build_demo_runs() if item.run_id == "dream-job-2026-08-24")
    result = run.model_copy(deep=True)
    result.run_id = "production-test-run"
    result.observed_at = datetime.now(UTC)
    return result


def _case_incident(run: RunEnvelope, observation_id: str) -> str:
    observation = next(item for item in run.observations if item.observation_id == observation_id)
    return case_incident_id(
        product_id=run.product.id,
        environment=run.product.environment,
        run_id=run.run_id,
        case=observation.case,
    )


def test_dashboard_free_text_rejects_private_paths_and_credentials() -> None:
    payload = _run().model_dump(mode="json")
    payload["observations"][0]["current_summary"] = "proof at /Users/person/private.json"
    with pytest.raises(ValidationError, match="private or absolute path"):
        RunEnvelope.model_validate(payload)

    payload = _run().model_dump(mode="json")
    payload["observations"][0]["expected_summary"] = "api_key=bad"
    with pytest.raises(ValidationError, match="credential assignment"):
        RunEnvelope.model_validate(payload)

    payload = _run().model_dump(mode="json")
    payload["observations"][0]["extensions"] = {
        "native_metadata": {"contact": "candidate@example.com"}
    }
    with pytest.raises(ValidationError, match="email address"):
        RunEnvelope.model_validate(payload)

    payload = _run().model_dump(mode="json")
    payload["observations"][0]["evidence_refs"][0]["uri"] = "/private/eval.json"
    with pytest.raises(ValidationError, match="private or absolute path"):
        RunEnvelope.model_validate(payload)

    payload = _run().model_dump(mode="json")
    payload["observations"][0]["evidence_refs"][0]["uri"] = "https://user:secret@example.com/eval"
    with pytest.raises(ValidationError, match="email address|opaque artifact"):
        RunEnvelope.model_validate(payload)

    payload = _run().model_dump(mode="json")
    payload["observations"][0]["case"]["case_id"] = "candidate@example.com"
    with pytest.raises(ValidationError):
        RunEnvelope.model_validate(payload)

    for absolute_path in (
        "/root/customer.json",
        "/opt/app/private-data",
        "/mnt/cases/raw.json",
        "C:/Users/customer/private.json",
        r"\\server\share\customer.json",
        "//server/share/customer.json",
        r"[\\server\share\customer.json]",
        "[//server/share/customer.json]",
        "[C:/Users/customer/private.json]",
    ):
        payload = _run().model_dump(mode="json")
        payload["observations"][0]["current_summary"] = f"proof at {absolute_path}"
        with pytest.raises(ValidationError, match="private or absolute path"):
            RunEnvelope.model_validate(payload)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("product", "version"), "candidate@example.com"),
        (("change_manifest", "prompt_version"), "/private/raw-prompt"),
        (("change_manifest", "model", "snapshot"), "api_key=raw-secret"),
        (("observations", 0, "location", "owner_id"), "candidate@example.com"),
        (("observations", 0, "evaluation", "suite_version"), "/private/suite"),
        (("observations", 0, "reason_code"), "password=raw-secret"),
    ],
)
def test_every_exporter_controlled_dashboard_label_is_redacted(
    path: tuple[str | int, ...], value: str
) -> None:
    payload = _run().model_dump(mode="json")
    target: object = payload
    for part in path[:-1]:
        if isinstance(part, int):
            assert isinstance(target, list)
            target = target[part]
        else:
            assert isinstance(target, dict)
            target = target[part]
    assert isinstance(target, dict)
    final = path[-1]
    assert isinstance(final, str)
    target[final] = value

    with pytest.raises(ValidationError):
        RunEnvelope.model_validate(payload)

    payload = _run().model_dump(mode="json")
    payload["observations"][0]["case"]["use_case_id"] = "/private/raw-case"
    with pytest.raises(ValidationError):
        RunEnvelope.model_validate(payload)


def test_product_scoped_credentials_refuse_cross_namespace_write(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            monitoring_data_dir=tmp_path,
            monitoring_ingest_credentials={
                ("dream-job-agent", "production"): "dream-token",
                ("linkedin-research-os", "production"): "linkedin-token",
            },
        )
    )
    response = client.post(
        "/api/monitoring/runs",
        json=_run().model_dump(mode="json"),
        headers={"Authorization": "Bearer linkedin-token"},
    )
    assert response.status_code == 403
    assert client.get("/api/monitoring/overview").json()["mode"] == "NO_DATA"


def test_started_receipt_makes_missing_product_visible(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            monitoring_data_dir=tmp_path,
            monitoring_ingest_credentials={("dream-job-agent", "production"): "dream-token"},
        )
    )
    now = datetime.now(UTC)
    receipt = RunReceipt(
        receipt_id="receipt-1",
        run_id="scheduled-run-1",
        product=_run().product,
        status="STARTED",
        observed_at=now,
        expected_next_run_at=now + timedelta(days=1),
        detail_code="RUN_STARTED",
    )
    response = client.post(
        "/api/monitoring/receipts",
        json=receipt.model_dump(mode="json"),
        headers={"Authorization": "Bearer dream-token"},
    )
    assert response.status_code == 200
    overview = client.get("/api/monitoring/overview").json()
    assert overview["mode"] == "NO_DATA"
    assert overview["products"][0]["health"] == "BLOCKED"
    assert overview["products"][0]["latest_run_id"] == "scheduled-run-1"


@pytest.mark.parametrize("receipt_run_id", ["older-run", "newer-completed-run"])
def test_older_receipt_does_not_override_newer_completed_run(receipt_run_id: str) -> None:
    run = _run()
    run.run_id = "newer-completed-run"
    now = datetime.now(UTC)
    run.observed_at = now
    receipt = RunReceipt(
        receipt_id="older-receipt",
        run_id=receipt_run_id,
        product=run.product,
        status="FAILED",
        observed_at=now - timedelta(minutes=5),
        expected_next_run_at=now + timedelta(days=1),
        detail_code="RUN_FAILED",
    )

    overview = build_overview([run], receipts=[receipt], generated_at=now, mode="LIVE")

    assert overview.products[0].latest_run_id == run.run_id
    assert overview.products[0].health != "BLOCKED"


def test_first_receipt_replaces_registered_not_received_placeholder(tmp_path: Path) -> None:
    product = _run().product
    client = TestClient(
        create_app(
            monitoring_data_dir=tmp_path,
            monitoring_ingest_credentials={(product.id, product.environment): "dream-token"},
            monitoring_expected_products=[product],
        )
    )
    now = datetime.now(UTC)
    receipt = RunReceipt(
        receipt_id="first-real-receipt",
        run_id="first-scheduled-run",
        product=product,
        status="STARTED",
        observed_at=now,
        expected_next_run_at=now + timedelta(days=1),
        detail_code="RUN_STARTED",
    )

    response = client.post(
        "/api/monitoring/receipts",
        json=receipt.model_dump(mode="json"),
        headers={"Authorization": "Bearer dream-token"},
    )

    assert response.status_code == 200
    overview = client.get("/api/monitoring/overview").json()
    assert overview["products"][0]["latest_run_id"] == receipt.run_id
    assert datetime.fromisoformat(overview["products"][0]["observed_at"]) == receipt.observed_at


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("run_id", "candidate@example.com"),
        ("run_id", "/private/raw-run"),
        ("comparison.run_id", "api_key=exposed"),
        ("comparison.label", "Owner candidate@example.com"),
    ],
)
def test_run_and_comparison_references_enforce_privacy_boundary(field: str, value: str) -> None:
    payload = _run().model_dump(mode="json")
    target: dict[str, object] = payload
    path = field.split(".")
    for part in path[:-1]:
        nested = target[part]
        assert isinstance(nested, dict)
        target = nested
    target[path[-1]] = value

    with pytest.raises(ValidationError):
        RunEnvelope.model_validate(payload)


def test_expected_product_is_visible_before_first_emission(tmp_path: Path) -> None:
    product = ProductRef(
        id="linkedin-research-os",
        display_name="LinkedIn Research OS",
        version="AWAITING_FIRST_RUN",
        environment="production",
    )
    client = TestClient(
        create_app(monitoring_data_dir=tmp_path, monitoring_expected_products=[product])
    )
    overview = client.get("/api/monitoring/overview").json()
    assert overview["mode"] == "NO_DATA"
    assert overview["products"] == [
        {
            "product_id": "linkedin-research-os",
            "display_name": "LinkedIn Research OS",
            "version": "AWAITING_FIRST_RUN",
            "environment": "production",
            "latest_run_id": "NOT_RECEIVED",
            "observed_at": overview["generated_at"],
            "health": "BLOCKED",
            "is_stale": True,
            "freshness_sla_seconds": 93600,
            "pass_count": 0,
            "fail_count": 0,
            "blocked_count": 1,
            "layers": [],
            "concerns": [],
        }
    ]


def test_product_ingestion_is_rate_limited(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            monitoring_data_dir=tmp_path,
            monitoring_ingest_token="producer-token",
            monitoring_ingest_limit_per_minute=1,
        )
    )
    run = _run()
    first = client.post(
        "/api/monitoring/runs",
        json=run.model_dump(mode="json"),
        headers={"Authorization": "Bearer producer-token"},
    )
    second = client.post(
        "/api/monitoring/runs",
        json=run.model_dump(mode="json"),
        headers={"Authorization": "Bearer producer-token"},
    )
    assert first.status_code == 200
    assert second.status_code == 429


def test_ingestion_rate_limit_uses_a_rolling_window_across_minute_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = MonitoringStore(tmp_path)
    moments = iter(
        [
            datetime.fromtimestamp(119.9, UTC),
            datetime.fromtimestamp(120.1, UTC),
            datetime.fromtimestamp(180.0, UTC),
        ]
    )

    class TestClock:
        @classmethod
        def now(cls, tz: object) -> datetime:
            assert tz is UTC
            return next(moments)

    monkeypatch.setattr(storage_module, "datetime", TestClock)

    assert store.admit_ingest(
        product_id="dream-job-agent", environment="production", limit_per_minute=1
    )
    assert not store.admit_ingest(
        product_id="dream-job-agent", environment="production", limit_per_minute=1
    )
    assert store.admit_ingest(
        product_id="dream-job-agent", environment="production", limit_per_minute=1
    )


def test_ingestion_rate_limit_preserves_legacy_counts_during_rolling_deploy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = MonitoringStore(tmp_path)
    with store._connect() as connection:
        connection.execute(
            """INSERT INTO ingest_rate(product_id, environment, minute_epoch, request_count)
               VALUES (?, ?, ?, ?)""",
            ("dream-job-agent", "production", 2, 1),
        )

    class TestClock:
        @classmethod
        def now(cls, tz: object) -> datetime:
            assert tz is UTC
            return datetime.fromtimestamp(120.1, UTC)

    monkeypatch.setattr(storage_module, "datetime", TestClock)
    assert store.admit_ingest(
        product_id="dream-job-agent", environment="production", limit_per_minute=2
    )
    assert not store.admit_ingest(
        product_id="dream-job-agent", environment="production", limit_per_minute=2
    )
    with store._connect() as connection:
        legacy_count = connection.execute(
            "SELECT request_count FROM ingest_rate WHERE minute_epoch = 2"
        ).fetchone()[0]
        event_count = connection.execute("SELECT COUNT(*) FROM ingest_rate_events").fetchone()[0]
    assert legacy_count == 2
    assert event_count == 1


def test_stored_comparison_requires_matching_digest(tmp_path: Path) -> None:
    client = TestClient(
        create_app(monitoring_data_dir=tmp_path, monitoring_ingest_token="producer-token")
    )
    baseline = _run()
    baseline.run_id = "baseline"
    baseline.comparison.run_id = "bootstrap"
    headers = {"Authorization": "Bearer producer-token"}
    assert (
        client.post(
            "/api/monitoring/runs", json=baseline.model_dump(mode="json"), headers=headers
        ).status_code
        == 200
    )

    candidate = _run()
    candidate.run_id = "candidate"
    candidate.comparison.run_id = "baseline"
    missing = client.post(
        "/api/monitoring/runs", json=candidate.model_dump(mode="json"), headers=headers
    )
    assert missing.status_code == 422
    assert missing.json()["detail"][0]["source"] == "comparison.sha256"

    candidate.comparison.sha256 = MonitoringStore(tmp_path).get_run_digest(
        product_id=baseline.product.id,
        environment=baseline.product.environment,
        run_id="baseline",
    )
    accepted = client.post(
        "/api/monitoring/runs", json=candidate.model_dump(mode="json"), headers=headers
    )
    assert accepted.status_code == 200


def test_adjudication_is_privileged_and_drives_metrics(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            monitoring_data_dir=tmp_path,
            monitoring_ingest_token="producer-token",
            monitoring_adjudication_token="review-token",
        )
    )
    run = _run()
    failed = next(
        item for item in run.observations if item.observation_id == "source-linkedin-coverage"
    )
    failed.status = "FAIL"
    failed.current_value = 0.5
    assert (
        client.post(
            "/api/monitoring/runs",
            json=run.model_dump(mode="json"),
            headers={"Authorization": "Bearer producer-token"},
        ).status_code
        == 200
    )
    observation_id = failed.observation_id
    record = AdjudicationRecord(
        adjudication_id="adjudication-1",
        product_id=run.product.id,
        environment=run.product.environment,
        run_id=run.run_id,
        case_incident_id=_case_incident(run, observation_id),
        observation_id=observation_id,
        predicted_root_observation_ids=[observation_id],
        actual_root_observation_ids=[observation_id],
        verdict="CORRECT",
        adjudicated_at=datetime.now(UTC),
        adjudicator_id="eval-reviewer",
        reason_code="KNOWN_CAUSE_CONFIRMED",
    )
    denied = client.post(
        "/api/monitoring/adjudications",
        json=record.model_dump(mode="json"),
        headers={"Authorization": "Bearer producer-token"},
    )
    accepted = client.post(
        "/api/monitoring/adjudications",
        json=record.model_dump(mode="json"),
        headers={"Authorization": "Bearer review-token"},
    )
    assert denied.status_code == 401
    assert accepted.status_code == 200
    metrics = client.get("/api/monitoring/overview").json()["attribution_metrics"]
    assert metrics["correctly_localized_rate"] == 1.0
    assert metrics["false_attribution_rate"] == 0.0
    assert metrics["guardrail_proven"] is False

    contradictory = record.model_copy(
        update={
            "adjudication_id": "adjudication-contradictory",
            "actual_root_observation_ids": [run.observations[-1].observation_id],
        }
    )
    rejected = client.post(
        "/api/monitoring/adjudications",
        json=contradictory.model_dump(mode="json"),
        headers={"Authorization": "Bearer review-token"},
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"][0]["source"] == "verdict"

    wrong_incident = record.model_copy(
        update={
            "adjudication_id": "adjudication-wrong-case",
            "case_incident_id": "case-sha256:" + "0" * 64,
        }
    )
    rejected = client.post(
        "/api/monitoring/adjudications",
        json=wrong_incident.model_dump(mode="json"),
        headers={"Authorization": "Bearer review-token"},
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"][0]["source"] == "case_incident_id"

    future = record.model_copy(
        update={
            "adjudication_id": "adjudication-from-future",
            "adjudicated_at": datetime.now(UTC) + timedelta(minutes=6),
        }
    )
    rejected = client.post(
        "/api/monitoring/adjudications",
        json=future.model_dump(mode="json"),
        headers={"Authorization": "Bearer review-token"},
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"][0]["source"] == "adjudicated_at"

    passing = next(item for item in run.observations if item.status == "PASS")
    non_diagnosis = record.model_copy(
        update={
            "adjudication_id": "adjudication-pass",
            "observation_id": passing.observation_id,
            "predicted_root_observation_ids": [passing.observation_id],
            "actual_root_observation_ids": [passing.observation_id],
        }
    )
    rejected = client.post(
        "/api/monitoring/adjudications",
        json=non_diagnosis.model_dump(mode="json"),
        headers={"Authorization": "Bearer review-token"},
    )
    assert rejected.status_code == 422


def test_adjudication_metrics_count_latest_incident_once() -> None:
    now = datetime.now(UTC)
    first = AdjudicationRecord(
        adjudication_id="first",
        product_id="product",
        environment="production",
        run_id="run",
        case_incident_id="case-sha256:" + "1" * 64,
        observation_id="observation",
        predicted_root_observation_ids=["root-a"],
        actual_root_observation_ids=["root-a"],
        verdict="CORRECT",
        adjudicated_at=now,
        adjudicator_id="reviewer",
        reason_code="INITIAL",
    )
    correction = first.model_copy(
        update={
            "adjudication_id": "correction",
            "actual_root_observation_ids": ["root-b"],
            "verdict": "INCORRECT",
            "adjudicated_at": now + timedelta(seconds=1),
        }
    )
    sibling_check = first.model_copy(
        update={
            "adjudication_id": "same-case-second-check",
            "observation_id": "observation-two",
        }
    )
    one_case = attribution_metrics_from_adjudications([first, sibling_check])
    assert one_case.production_adjudicated_sample_size == 1
    assert one_case.known_cause_sample_size == 1
    metrics = attribution_metrics_from_adjudications([first, correction])
    assert metrics.production_adjudicated_sample_size == 1
    assert metrics.known_cause_sample_size == 1
    assert metrics.false_attribution_rate == 1.0


def test_unconfirmed_diagnosis_cannot_invent_a_resolved_root(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            monitoring_data_dir=tmp_path,
            monitoring_ingest_token="producer-token",
            monitoring_adjudication_token="review-token",
        )
    )
    run = _run()
    upstream = next(
        item for item in run.observations if item.observation_id == "source-linkedin-coverage"
    )
    downstream = next(
        item for item in run.observations if item.observation_id == "eligible-job-coverage"
    )
    upstream.status = "BLOCKED"
    upstream.current_value = None
    downstream.status = "FAIL"
    downstream.current_value = 0.0
    assert (
        client.post(
            "/api/monitoring/runs",
            json=run.model_dump(mode="json"),
            headers={"Authorization": "Bearer producer-token"},
        ).status_code
        == 200
    )
    claimed = AdjudicationRecord(
        adjudication_id="invented-root",
        product_id=run.product.id,
        environment=run.product.environment,
        run_id=run.run_id,
        case_incident_id=_case_incident(run, downstream.observation_id),
        observation_id=downstream.observation_id,
        predicted_root_observation_ids=[downstream.observation_id],
        actual_root_observation_ids=[downstream.observation_id],
        verdict="CORRECT",
        adjudicated_at=datetime.now(UTC),
        adjudicator_id="eval-reviewer",
        reason_code="KNOWN_CAUSE_CONFIRMED",
    )
    rejected = client.post(
        "/api/monitoring/adjudications",
        json=claimed.model_dump(mode="json"),
        headers={"Authorization": "Bearer review-token"},
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"][0]["source"] == "predicted_root_observation_ids"

    unresolved = claimed.model_copy(
        update={
            "adjudication_id": "unresolved-root",
            "predicted_root_observation_ids": [],
            "actual_root_observation_ids": [],
            "verdict": "UNRESOLVED",
        }
    )
    accepted = client.post(
        "/api/monitoring/adjudications",
        json=unresolved.model_dump(mode="json"),
        headers={"Authorization": "Bearer review-token"},
    )
    assert accepted.status_code == 200
    metrics = client.get("/api/monitoring/overview").json()["attribution_metrics"]
    assert metrics["production_adjudicated_sample_size"] == 1
    assert metrics["known_cause_sample_size"] == 0
    assert metrics["guardrail_proven"] is False


def test_downstream_symptom_cannot_count_as_an_independent_localization(
    tmp_path: Path,
) -> None:
    client = TestClient(
        create_app(
            monitoring_data_dir=tmp_path,
            monitoring_ingest_token="producer-token",
            monitoring_adjudication_token="review-token",
        )
    )
    run = _run()
    upstream = next(
        item for item in run.observations if item.observation_id == "source-linkedin-coverage"
    )
    downstream = next(
        item for item in run.observations if item.observation_id == "eligible-job-coverage"
    )
    upstream.status = "FAIL"
    upstream.current_value = 0.0
    downstream.status = "FAIL"
    downstream.current_value = 0.0
    assert (
        client.post(
            "/api/monitoring/runs",
            json=run.model_dump(mode="json"),
            headers={"Authorization": "Bearer producer-token"},
        ).status_code
        == 200
    )
    record = AdjudicationRecord(
        adjudication_id="downstream-is-not-independent",
        product_id=run.product.id,
        environment=run.product.environment,
        run_id=run.run_id,
        case_incident_id=_case_incident(run, downstream.observation_id),
        observation_id=downstream.observation_id,
        predicted_root_observation_ids=[upstream.observation_id],
        actual_root_observation_ids=[upstream.observation_id],
        verdict="CORRECT",
        adjudicated_at=datetime.now(UTC),
        adjudicator_id="eval-reviewer",
        reason_code="KNOWN_CAUSE_CONFIRMED",
    )
    rejected = client.post(
        "/api/monitoring/adjudications",
        json=record.model_dump(mode="json"),
        headers={"Authorization": "Bearer review-token"},
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"][0]["source"] == "verdict"


def test_controlled_replay_must_match_case_check_and_manifest_changes(
    tmp_path: Path,
) -> None:
    client = TestClient(
        create_app(monitoring_data_dir=tmp_path, monitoring_ingest_token="producer-token")
    )
    control = _run()
    control.run_id = "replay-control"
    control.observed_at = datetime.now(UTC) - timedelta(seconds=1)
    source = next(
        item for item in control.observations if item.observation_id == "source-linkedin-coverage"
    )
    candidate = control.model_copy(deep=True)
    candidate.run_id = "replay-candidate"
    candidate.observed_at = datetime.now(UTC)
    candidate.comparison.run_id = control.run_id
    candidate.comparison.sha256 = canonical_run_digest(control)
    candidate.change_manifest.toolset_version = "connectors@replay"
    candidate.provenance.toolset_digest = "sha256:" + "3" * 64
    candidate_source = next(
        item
        for item in candidate.observations
        if item.observation_id == "source-linkedin-coverage"
    )
    candidate_source.status = "FAIL"
    candidate_source.current_value = 0.0
    planted = next(item for item in build_demo_runs() if item.run_id == "dream-job-2026-08-28")
    signal = next(
        item for item in planted.observations if item.observation_id == "source-linkedin-coverage"
    ).cause_signals[0]
    candidate_source.cause_signals = [
        signal.model_copy(
            deep=True,
            update={
                "control_ref": f"{control.run_id}#{source.observation_id}",
                "candidate_ref": f"{candidate.run_id}#{candidate_source.observation_id}",
            },
        )
    ]
    headers = {"Authorization": "Bearer producer-token"}
    assert (
        client.post(
            "/api/monitoring/runs", json=control.model_dump(mode="json"), headers=headers
        ).status_code
        == 200
    )

    wrong_check = candidate.model_copy(deep=True)
    wrong_check.run_id = "replay-wrong-check"
    wrong_source = next(
        item
        for item in wrong_check.observations
        if item.observation_id == candidate_source.observation_id
    )
    wrong_source.cause_signals[
        0
    ].candidate_ref = f"{wrong_check.run_id}#{wrong_source.observation_id}"
    wrong_source.cause_signals[0].control_ref = f"{control.run_id}#input-constraint-completeness"
    rejected = client.post(
        "/api/monitoring/runs", json=wrong_check.model_dump(mode="json"), headers=headers
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"][0]["source"] == "control_ref"

    wrong_manifest = candidate.model_copy(deep=True)
    wrong_manifest.run_id = "replay-wrong-manifest"
    wrong_manifest.change_manifest.deployment_id = "changed-deployment"
    wrong_manifest_source = next(
        item
        for item in wrong_manifest.observations
        if item.observation_id == candidate_source.observation_id
    )
    wrong_manifest_source.cause_signals[
        0
    ].candidate_ref = f"{wrong_manifest.run_id}#{wrong_manifest_source.observation_id}"
    rejected = client.post(
        "/api/monitoring/runs",
        json=wrong_manifest.model_dump(mode="json"),
        headers=headers,
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"][0]["source"] == "cause_signals"

    hidden_digest_change = candidate.model_copy(deep=True)
    hidden_digest_change.run_id = "replay-hidden-config-change"
    hidden_digest_change.provenance.config_digest = "sha256:" + "4" * 64
    hidden_digest_source = next(
        item
        for item in hidden_digest_change.observations
        if item.observation_id == candidate_source.observation_id
    )
    hidden_digest_source.cause_signals[
        0
    ].candidate_ref = f"{hidden_digest_change.run_id}#{hidden_digest_source.observation_id}"
    rejected = client.post(
        "/api/monitoring/runs",
        json=hidden_digest_change.model_dump(mode="json"),
        headers=headers,
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"][0]["source"] == "cause_signals"

    accepted = client.post(
        "/api/monitoring/runs", json=candidate.model_dump(mode="json"), headers=headers
    )
    assert accepted.status_code == 200
    diagnosis = next(
        item
        for item in accepted.json()["diagnosis"]["diagnoses"]
        if item["observation_id"] == candidate_source.observation_id
    )
    assert diagnosis["evidence_level"] == "CONTROLLED_REPLAY"


def test_horizontal_mapper_uses_settings_without_product_branches() -> None:
    root = Path(__file__).resolve().parents[2]
    payload = json.loads((root / "adapters/dream-job.settings.json").read_text())
    settings = AdapterSettings.model_validate(payload)
    third_payload = dict(payload)
    third_payload["adapter_id"] = "third-product-monitoring"
    third_payload["product"] = {
        **payload["product"],
        "id": "third-product",
        "display_name": "Third Product",
    }
    third = AdapterSettings.model_validate(third_payload)
    template = _run()
    normalized = NormalizedRun.model_validate(
        {
            "format_version": "normalized-eval-run/0.1",
            "run_id": "mapped-run",
            "observed_at": template.observed_at,
            "product_version": "release-1",
            "comparison": template.comparison.model_dump(mode="json"),
            "change_manifest": template.change_manifest.model_dump(mode="json"),
            "provenance": template.provenance.model_dump(mode="json"),
            "cases": [
                {
                    "case_type": "job-search",
                    "case": template.observations[0].case.model_dump(mode="json"),
                    "checks": [
                        {
                            "definition_id": "input-constraint-completeness",
                            "status": "PASS",
                            "current_value": 1.0,
                            "expected_value": 1.0,
                            "reason_code": "INPUT_COMPLETE",
                        }
                    ],
                }
            ],
        }
    )
    first = map_normalized_run(settings, normalized)
    product_three = map_normalized_run(third, normalized)
    assert first.product.id == "dream-job-agent"
    assert product_three.product.id == "third-product"
    assert [item.status for item in first.observations] == [
        item.status for item in product_three.observations
    ]
    assert first.observations[1].status == "BLOCKED"

    second_case = normalized.cases[0].model_copy(deep=True)
    second_case.case.segment = "different-segment"
    second_case.case.input_fingerprint = "sha256:" + "1" * 64
    repeated_case_id = normalized.model_copy(
        deep=True, update={"cases": [normalized.cases[0], second_case]}
    )
    repeated = map_normalized_run(settings, repeated_case_id)
    assert len({item.observation_id for item in repeated.observations}) == len(
        repeated.observations
    )

    normalized_payload = normalized.model_dump(mode="json")
    normalized_payload["cases"][0]["checks"][0]["extensions"] = {
        "native_private_data": "candidate@example.com"
    }
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        NormalizedRun.model_validate(normalized_payload)

    normalized_payload = normalized.model_dump(mode="json")
    normalized_payload["run_id"] = "PrivateRunTokenABC123456789012345678901234567890"
    with pytest.raises(ValidationError, match="high-entropy token"):
        NormalizedRun.model_validate(normalized_payload)

    selected_definition_count = len(settings.case_types["job-search"])
    excessive_case_count = 2000 // selected_definition_count + 1
    excessive = normalized.model_copy(
        deep=True,
        update={"cases": [normalized.cases[0]] * excessive_case_count},
    )
    with pytest.raises(ValueError, match="2,000 observation limit"):
        map_normalized_run(settings, excessive)


def test_late_comparison_is_used_only_when_its_digest_matches() -> None:
    baseline = _run()
    baseline.run_id = "late-baseline"
    baseline.observed_at = datetime.now(UTC) - timedelta(minutes=1)
    different = baseline.model_copy(deep=True)
    different.product.version = "different-evidence"
    candidate = baseline.model_copy(deep=True)
    candidate.run_id = "late-candidate"
    candidate.observed_at = datetime.now(UTC)
    candidate.comparison.run_id = baseline.run_id
    candidate.comparison.sha256 = canonical_run_digest(different)
    failure = candidate.observations[0]
    failure.status = "FAIL"
    failure.current_value = 0.0

    overview = build_overview([baseline, candidate], mode="LIVE")
    incident = next(item for item in overview.incidents if item.run_id == candidate.run_id)
    assert incident.expected_summary.startswith("The referenced comparison does not contain")
    assert incident.changes_since_comparison == []


def test_late_mismatched_comparison_cannot_create_an_adjudicable_regression(
    tmp_path: Path,
) -> None:
    client = TestClient(
        create_app(
            monitoring_data_dir=tmp_path,
            monitoring_ingest_token="producer-token",
            monitoring_adjudication_token="review-token",
        )
    )
    baseline = _run()
    baseline.run_id = "late-baseline"
    baseline.observed_at = datetime.now(UTC)
    baseline.comparison.run_id = "bootstrap"
    candidate = baseline.model_copy(deep=True)
    candidate.run_id = "late-candidate"
    candidate.observed_at = baseline.observed_at - timedelta(minutes=1)
    candidate.comparison.run_id = baseline.run_id
    candidate.comparison.sha256 = "sha256:" + "0" * 64
    baseline.observations[0].threshold = 0.8
    candidate.observations[0].threshold = 0.8
    candidate.observations[0].current_value = 0.9

    headers = {"Authorization": "Bearer producer-token"}
    assert (
        client.post(
            "/api/monitoring/runs", json=candidate.model_dump(mode="json"), headers=headers
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/monitoring/runs", json=baseline.model_dump(mode="json"), headers=headers
        ).status_code
        == 200
    )

    record = AdjudicationRecord(
        adjudication_id="late-comparison-adjudication",
        product_id=candidate.product.id,
        environment=candidate.product.environment,
        run_id=candidate.run_id,
        case_incident_id=_case_incident(candidate, candidate.observations[0].observation_id),
        observation_id=candidate.observations[0].observation_id,
        predicted_root_observation_ids=[candidate.observations[0].observation_id],
        actual_root_observation_ids=[candidate.observations[0].observation_id],
        verdict="CORRECT",
        adjudicated_at=datetime.now(UTC),
        adjudicator_id="eval-reviewer",
        reason_code="KNOWN_CAUSE_CONFIRMED",
    )
    rejected = client.post(
        "/api/monitoring/adjudications",
        json=record.model_dump(mode="json"),
        headers={"Authorization": "Bearer review-token"},
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"][0]["source"] == "observation_id"


def test_both_product_settings_map_through_the_same_contract() -> None:
    root = Path(__file__).resolve().parents[2]
    template = _run()
    products: list[str] = []
    for filename, case_type, definition_id in (
        ("dream-job.settings.json", "job-search", "input-constraint-completeness"),
        ("linkedin-os.settings.json", "critic", "critic-anchor-integrity"),
    ):
        settings = AdapterSettings.model_validate(
            json.loads((root / "adapters" / filename).read_text())
        )
        normalized = NormalizedRun.model_validate(
            {
                "run_id": f"{settings.product.id}-test-run",
                "observed_at": template.observed_at,
                "product_version": "release-1",
                "comparison": template.comparison.model_dump(mode="json"),
                "change_manifest": template.change_manifest.model_dump(mode="json"),
                "provenance": template.provenance.model_dump(mode="json"),
                "cases": [
                    {
                        "case_type": case_type,
                        "case": template.observations[0].case.model_dump(mode="json"),
                        "checks": [
                            {
                                "definition_id": definition_id,
                                "status": "PASS",
                                "current_value": 1.0,
                                "expected_value": 1.0,
                                "reason_code": "CHECK_PASSED",
                            }
                        ],
                    }
                ],
            }
        )
        products.append(map_normalized_run(settings, normalized).product.id)
    assert products == ["dream-job-agent", "linkedin-research-os"]


def test_outbox_retries_without_losing_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    synced: list[Path] = []
    real_fsync_directory = outbox_module._fsync_directory

    def record_fsync(path: Path) -> None:
        synced.append(path)
        real_fsync_directory(path)

    monkeypatch.setattr(outbox_module, "_fsync_directory", record_fsync)
    outbox = tmp_path / "nested" / "monitoring-outbox"
    path = enqueue(
        outbox,
        route="/api/monitoring/runs",
        identity="run:dream-job-agent:production:1",
        payload={"run_id": "1"},
    )
    assert path.exists()
    assert tmp_path in synced
    assert tmp_path / "nested" in synced
    assert outbox in synced
    synced.clear()
    assert (
        enqueue(
            outbox,
            route="/api/monitoring/runs",
            identity="run:dream-job-agent:production:1",
            payload={"run_id": "1"},
        )
        == path
    )
    assert outbox in synced

    existing_outbox = tmp_path / "already-created-outbox"
    existing_outbox.mkdir()
    existing_outbox.chmod(0o700)
    synced.clear()
    enqueue(
        existing_outbox,
        route="/api/monitoring/receipts",
        identity="receipt:dream-job-agent:production:existing",
        payload={"receipt_id": "existing"},
    )
    assert tmp_path in synced

    def fail(_: str, __: dict[str, object]) -> None:
        raise RuntimeError("offline")

    with pytest.raises(RuntimeError, match="offline"):
        flush(outbox, sender=fail)
    assert path.exists()

    delivered: list[tuple[str, dict[str, object]]] = []
    assert flush(outbox, sender=lambda route, payload: delivered.append((route, payload))) == 1
    assert delivered == [("/api/monitoring/runs", {"run_id": "1"})]
    assert not path.exists()
    assert list(outbox.glob("*.sent.json"))


def test_outbox_rejects_shared_root_before_mutating_it() -> None:
    before = stat.S_IMODE(Path("/tmp").stat().st_mode)

    with pytest.raises(ValueError, match="shared system root"):
        enqueue(
            Path("/tmp"),
            route="/api/monitoring/runs",
            identity="run:dream-job-agent:production:unsafe",
            payload={"run_id": "unsafe"},
        )

    assert stat.S_IMODE(Path("/tmp").stat().st_mode) == before


def test_outbox_flush_rejects_shared_root_before_scanning_it() -> None:
    sent = False

    def sender(_: str, __: dict[str, object]) -> None:
        nonlocal sent
        sent = True

    with pytest.raises(ValueError, match="shared system root"):
        flush(Path("/tmp"), sender=sender)

    assert not sent


def test_sent_outbox_identity_is_not_reenqueued(tmp_path: Path) -> None:
    outbox = tmp_path / "monitoring-outbox"
    identity = "run:dream-job-agent:production:delivered"
    payload = {"run_id": "delivered"}
    pending = enqueue(
        outbox,
        route="/api/monitoring/runs",
        identity=identity,
        payload=payload,
    )
    delivered: list[dict[str, object]] = []
    assert flush(outbox, sender=lambda _route, item: delivered.append(item)) == 1

    sent = enqueue(
        outbox,
        route="/api/monitoring/runs",
        identity=identity,
        payload=payload,
    )

    assert sent.name.endswith(".sent.json")
    assert not pending.exists()
    assert flush(outbox, sender=lambda _route, item: delivered.append(item)) == 0
    assert delivered == [payload]
    with pytest.raises(ValueError, match="different evidence"):
        enqueue(
            outbox,
            route="/api/monitoring/runs",
            identity=identity,
            payload={"run_id": "changed"},
        )


def test_flush_reconciles_legacy_pending_and_sent_duplicate(tmp_path: Path) -> None:
    outbox = tmp_path / "monitoring-outbox"
    pending = enqueue(
        outbox,
        route="/api/monitoring/runs",
        identity="run:dream-job-agent:production:legacy-duplicate",
        payload={"run_id": "legacy-duplicate"},
    )
    sent = pending.with_name(pending.name.replace(".pending.json", ".sent.json"))
    sent.write_bytes(pending.read_bytes())
    sent.chmod(0o600)
    delivered: list[dict[str, object]] = []

    assert flush(outbox, sender=lambda _route, item: delivered.append(item)) == 0

    assert delivered == []
    assert not pending.exists()
    assert sent.exists()


@pytest.mark.parametrize(
    "shared_root",
    [
        Path("/"),
        Path("/tmp"),
        Path("/var/tmp"),
        Path("/home"),
        Path("/var"),
        Path("/usr"),
        Path("/etc"),
    ],
)
def test_monitoring_store_rejects_shared_roots_before_mutating_them(
    shared_root: Path,
) -> None:
    before = stat.S_IMODE(shared_root.stat().st_mode) if shared_root.exists() else None

    with pytest.raises(ValueError, match="shared system root"):
        MonitoringStore(shared_root)

    after = stat.S_IMODE(shared_root.stat().st_mode) if shared_root.exists() else None
    assert after == before


def test_existing_store_and_outbox_must_already_be_private(tmp_path: Path) -> None:
    store_dir = tmp_path / "public-store"
    outbox_dir = tmp_path / "public-outbox"
    store_dir.mkdir(mode=0o755)
    outbox_dir.mkdir(mode=0o755)

    with pytest.raises(ValueError, match="owner-only mode 0700"):
        MonitoringStore(store_dir)
    with pytest.raises(ValueError, match="owner-only mode 0700"):
        enqueue(
            outbox_dir,
            route="/api/monitoring/runs",
            identity="run:dream-job-agent:production:public-dir",
            payload={"run_id": "public-dir"},
        )

    assert stat.S_IMODE(store_dir.stat().st_mode) == 0o755
    assert stat.S_IMODE(outbox_dir.stat().st_mode) == 0o755


def test_concurrently_created_directories_are_validated_not_chmodded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_mkdir = Path.mkdir

    def race_creation(target: Path) -> None:
        def raced_mkdir(
            path: Path,
            mode: int = 0o777,
            parents: bool = False,
            exist_ok: bool = False,
        ) -> None:
            if path == target and not path.exists():
                os.mkdir(path, 0o755)
                path.chmod(0o755)
                raise FileExistsError(path)
            real_mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)

        with monkeypatch.context() as context:
            context.setattr(Path, "mkdir", raced_mkdir)
            if "store" in target.name:
                with pytest.raises(ValueError, match="owner-only mode 0700"):
                    MonitoringStore(target)
            else:
                with pytest.raises(ValueError, match="owner-only mode 0700"):
                    enqueue(
                        target,
                        route="/api/monitoring/runs",
                        identity="run:dream-job-agent:production:raced-dir",
                        payload={"run_id": "raced-dir"},
                    )
        assert stat.S_IMODE(target.stat().st_mode) == 0o755

    race_creation(tmp_path / "raced-store")
    race_creation(tmp_path / "raced-outbox")


def test_outbox_does_not_publish_a_partial_item(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outbox = tmp_path / "monitoring-outbox"
    real_write = outbox_module.os.write
    calls = 0

    def interrupted_write(descriptor: int, data: object) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            return real_write(descriptor, memoryview(data)[:8])
        raise OSError("simulated full filesystem")

    with monkeypatch.context() as context:
        context.setattr(outbox_module.os, "write", interrupted_write)
        with pytest.raises(OSError, match="simulated full filesystem"):
            enqueue(
                outbox,
                route="/api/monitoring/runs",
                identity="run:dream-job-agent:production:partial",
                payload={"run_id": "partial"},
            )
    assert not list(outbox.glob("*.pending.json"))
    assert not list(outbox.glob("*.tmp"))
    crash_leftover = outbox / f".{('a' * 64)}.{('b' * 16)}.tmp"
    crash_leftover.write_bytes(b"partial crash evidence")
    path = enqueue(
        outbox,
        route="/api/monitoring/runs",
        identity="run:dream-job-agent:production:partial",
        payload={"run_id": "partial"},
    )
    assert path.exists()
    assert not crash_leftover.exists()


def test_auxiliary_ledgers_are_private_and_recover_a_torn_tail(tmp_path: Path) -> None:
    store = MonitoringStore(tmp_path)
    now = datetime.now(UTC)
    receipt = RunReceipt(
        receipt_id="private-receipt",
        run_id="scheduled-run",
        product=_run().product,
        status="STARTED",
        observed_at=now,
        expected_next_run_at=now + timedelta(days=1),
        detail_code="RUN_STARTED",
    )
    adjudication = AdjudicationRecord(
        adjudication_id="private-adjudication",
        product_id="dream-job-agent",
        environment="production",
        run_id="run",
        case_incident_id="case-sha256:" + "2" * 64,
        observation_id="observation",
        predicted_root_observation_ids=["root"],
        actual_root_observation_ids=["root"],
        verdict="CORRECT",
        adjudicated_at=now,
        adjudicator_id="reviewer",
        reason_code="KNOWN_CAUSE_CONFIRMED",
    )
    assert store.append_receipt(receipt)
    assert store.append_adjudication(adjudication)

    with store.receipt_path.open("ab") as handle:
        handle.write(b'{"receipt_version":')
    with store.adjudication_path.open("ab") as handle:
        handle.write(b'{"adjudication_version":')

    recovered = MonitoringStore(tmp_path)
    assert recovered.list_receipts() == [receipt]
    assert recovered.list_adjudications() == [adjudication]
    assert stat.S_IMODE(os.stat(tmp_path).st_mode) == 0o700
    for path in (
        recovered.log_path,
        recovered.lock_path,
        recovered.receipt_path,
        recovered.adjudication_path,
        recovered.index_path,
    ):
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_store_syncs_new_directories_and_rejects_a_symlink_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    synced: list[Path] = []
    real_fsync_directory = storage_module._fsync_directory

    def record_fsync(path: Path) -> None:
        synced.append(path)
        real_fsync_directory(path)

    monkeypatch.setattr(storage_module, "_fsync_directory", record_fsync)
    data_dir = tmp_path / "nested" / "monitoring"
    MonitoringStore(data_dir)
    assert tmp_path in synced
    assert tmp_path / "nested" in synced
    assert data_dir in synced

    existing_data_dir = tmp_path / "already-created-store"
    existing_data_dir.mkdir()
    existing_data_dir.chmod(0o700)
    synced.clear()
    MonitoringStore(existing_data_dir)
    assert tmp_path in synced

    unsafe = tmp_path / "unsafe"
    unsafe.mkdir()
    unsafe.chmod(0o700)
    target = tmp_path / "outside.sqlite3"
    target.touch()
    (unsafe / "observations.sqlite3").symlink_to(target)
    with pytest.raises(ValueError, match="must not be a symlink"):
        MonitoringStore(unsafe)

    with pytest.raises(ValueError, match="shared system root"):
        MonitoringStore(Path("/tmp"))


def test_v01_adjudication_is_verified_and_migrated_on_read(tmp_path: Path) -> None:
    store = MonitoringStore(tmp_path)
    run = _run()
    run.observations[0].status = "FAIL"
    run.observations[0].current_value = 0.0
    assert store.append(run)
    observation = run.observations[0]
    current = AdjudicationRecord(
        adjudication_id="legacy-adjudication",
        product_id=run.product.id,
        environment=run.product.environment,
        run_id=run.run_id,
        case_incident_id=_case_incident(run, observation.observation_id),
        observation_id=observation.observation_id,
        predicted_root_observation_ids=[observation.observation_id],
        actual_root_observation_ids=[observation.observation_id],
        verdict="CORRECT",
        adjudicated_at=datetime.now(UTC),
        adjudicator_id="legacy-reviewer",
        reason_code="LEGACY_KNOWN_CAUSE",
    )
    legacy = current.model_dump(mode="json", exclude={"case_incident_id"})
    legacy["adjudication_version"] = "0.1"
    store.adjudication_path.write_text(json.dumps(legacy, sort_keys=True) + "\n")

    recovered = MonitoringStore(tmp_path)
    migrated = recovered.list_adjudications()
    assert migrated == [current]
    assert migrated[0].adjudication_version == "0.2"

    rejected_dir = tmp_path / "contradictory"
    rejected_store = MonitoringStore(rejected_dir)
    assert rejected_store.append(run)
    contradictory = dict(legacy)
    contradictory["actual_root_observation_ids"] = [run.observations[1].observation_id]
    rejected_store.adjudication_path.write_text(json.dumps(contradictory, sort_keys=True) + "\n")
    with pytest.raises(ValueError, match="completed adjudication ledger record is invalid"):
        MonitoringStore(rejected_dir)
