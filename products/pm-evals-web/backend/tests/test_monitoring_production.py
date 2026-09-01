"""Production monitoring lifecycle, trust, and horizontal adapter tests."""

from __future__ import annotations

import json
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
    map_normalized_run,
)
from pm_evals_monitoring.outbox import enqueue, flush


def _run() -> RunEnvelope:
    run = next(item for item in build_demo_runs() if item.run_id == "dream-job-2026-08-24")
    result = run.model_copy(deep=True)
    result.run_id = "production-test-run"
    result.observed_at = datetime.now(UTC)
    return result


def test_dashboard_free_text_rejects_private_paths_and_credentials() -> None:
    payload = _run().model_dump(mode="json")
    payload["observations"][0]["current_summary"] = "proof at /Users/person/private.json"
    with pytest.raises(ValidationError, match="private or absolute path"):
        RunEnvelope.model_validate(payload)

    payload = _run().model_dump(mode="json")
    payload["observations"][0]["expected_summary"] = "api_key=secret-value"
    with pytest.raises(ValidationError, match="credential assignment"):
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

    from pm_evals_monitoring import MonitoringStore

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


def test_outbox_retries_without_losing_evidence(tmp_path: Path) -> None:
    path = enqueue(
        tmp_path,
        route="/api/monitoring/runs",
        identity="run:dream-job-agent:production:1",
        payload={"run_id": "1"},
    )
    assert path.exists()

    def fail(_: str, __: dict[str, object]) -> None:
        raise RuntimeError("offline")

    with pytest.raises(RuntimeError, match="offline"):
        flush(tmp_path, sender=fail)
    assert path.exists()

    delivered: list[tuple[str, dict[str, object]]] = []
    assert flush(tmp_path, sender=lambda route, payload: delivered.append((route, payload))) == 1
    assert delivered == [("/api/monitoring/runs", {"run_id": "1"})]
    assert not path.exists()
    assert list(tmp_path.glob("*.sent.json"))
