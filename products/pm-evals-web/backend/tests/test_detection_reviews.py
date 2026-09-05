from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_monitoring_production import _run

from pm_evals_api.app import create_app
from pm_evals_monitoring.detection import RecordedDetectionReview, detection_metrics
from pm_evals_monitoring.storage import MonitoringStore


@pytest.fixture
def review_api(tmp_path: Path):
    run = _run()
    observation = next(o for o in run.observations if o.evaluation.layer == "TOOL_TRAJECTORY")
    observation.status = "FAIL"
    observation.current_value = 0.0
    MonitoringStore(tmp_path / "store").append(run)
    client = TestClient(
        create_app(
            monitoring_data_dir=tmp_path / "store",
            monitoring_ingest_token="producer",
            monitoring_adjudication_token="reviewer",
            monitoring_viewer_token="viewer",
        )
    )
    payload = {
        "review_id": "review-one",
        "product_id": run.product.id,
        "environment": run.product.environment,
        "run_id": run.run_id,
        "case_id": observation.case.case_id,
        "observation_id": observation.observation_id,
        "layer": observation.evaluation.layer,
        "actual_failure": True,
        "silent": True,
        "evidence_scope": "TEST",
        "dataset_version": "golden-v1",
        "reviewer_id": "independent-human",
        "reviewed_at": datetime.now(UTC).isoformat(),
        "evidence_refs": [{"uri": "urn:evidence:test", "sha256": "sha256:" + "a" * 64}],
    }
    with client:
        yield client, payload, MonitoringStore(tmp_path / "store")


def _post_review(client, payload, token="reviewer"):
    return client.post(
        "/api/monitoring/detection-reviews",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )


def _metrics(client):
    response = client.get("/api/monitoring/overview", headers={"Authorization": "Bearer viewer"})
    assert response.status_code == 200
    return response.json()["detection_metrics"]


def test_review_cannot_count_a_stored_observation_under_invented_cases(review_api):
    client, payload, store = review_api
    for case_id in ("invented-case-one", "invented-case-two"):
        response = _post_review(client, dict(payload, case_id=case_id, review_id=case_id))
        assert response.status_code == 422
        assert "review case must match" in response.text
    assert store.list_detection_reviews() == []
    assert _metrics(client) == []


def test_review_retry_is_idempotent_but_another_id_cannot_double_count(review_api):
    client, payload, store = review_api
    assert _post_review(client, payload).json() == {"stored": True, "duplicate": False}
    assert _post_review(client, payload).json() == {"stored": False, "duplicate": True}
    assert _post_review(client, dict(payload, review_id="another-review")).status_code == 409
    assert len(store.list_detection_reviews()) == 1
    metric = next(m for m in _metrics(client) if m["layer"] == "TOOL_TRAJECTORY")
    assert metric["silent_failures"] == 1
    assert metric["detected_silent_failures"] == 1


@pytest.mark.parametrize("token", ["producer", "viewer", "unknown"])
def test_only_independent_reviewer_can_supply_failure_labels(review_api, token):
    client, payload, store = review_api
    assert _post_review(client, payload, token).status_code == 401
    assert store.list_detection_reviews() == []


@pytest.mark.parametrize("claimed_detection", [True, False])
def test_client_cannot_override_server_detection(review_api, claimed_detection):
    client, payload, store = review_api
    assert _post_review(client, dict(payload, detected=claimed_detection)).status_code == 422
    assert store.list_detection_reviews() == []
    assert _post_review(client, payload).status_code == 200
    assert store.list_detection_reviews()[0].detected is True


def test_uninstrumented_failure_is_a_miss_and_test_results_do_not_mask_production(review_api):
    client, payload, store = review_api
    assert _post_review(client, payload).status_code == 200
    missed = dict(
        payload,
        review_id="production-missed-case",
        evidence_scope="PRODUCTION",
        case_id="independently-found-uninstrumented-case",
    )
    missed.pop("observation_id")
    assert _post_review(client, missed).status_code == 200
    records = store.list_detection_reviews()
    assert [r.detected for r in records] == [True, False]
    metrics = {m["evidence_scope"]: m for m in _metrics(client) if m["layer"] == "TOOL_TRAJECTORY"}
    assert metrics["TEST"]["silent_failure_recall"] == 1.0
    assert metrics["TEST"]["status"] == "OBSERVED_ABOVE_TARGET"
    assert metrics["PRODUCTION"]["silent_failures"] == 1
    assert metrics["PRODUCTION"]["missed_silent_failures"] == 1
    assert metrics["PRODUCTION"]["silent_failure_recall"] == 0.0
    assert metrics["PRODUCTION"]["status"] == "BELOW_TARGET"


@pytest.mark.parametrize(
    ("field", "value"), [("observation_id", "unknown-observation"), ("layer", "OUTPUT")]
)
def test_unknown_observation_or_wrong_layer_cannot_be_recorded(review_api, field, value):
    client, payload, store = review_api
    assert _post_review(client, dict(payload, **{field: value})).status_code == 422
    assert store.list_detection_reviews() == []


def test_misses_are_counted_and_layers_are_never_averaged():
    rows = []
    for layer in ("TOOL_TRAJECTORY", "SYSTEM", "OUTPUT"):
        for index in range(10):
            rows.append(
                RecordedDetectionReview(
                    review_id=f"{layer}-{index}",
                    product_id="p",
                    environment="local",
                    run_id="r",
                    case_id=str(index),
                    layer=layer,
                    actual_failure=True,
                    silent=True,
                    evidence_scope="TEST",
                    dataset_version="1",
                    reviewer_id="human",
                    reviewed_at=datetime.now(UTC),
                    evidence_refs=[{"uri": "urn:evidence:test", "sha256": "sha256:" + "a" * 64}],
                    detected=layer != "TOOL_TRAJECTORY" or index < 9,
                )
            )
    metrics = {m.layer: m for m in detection_metrics(rows)}
    assert metrics["TOOL_TRAJECTORY"].silent_failure_recall == 0.9
    assert metrics["TOOL_TRAJECTORY"].status == "BELOW_TARGET"
    assert metrics["SYSTEM"].status == "OBSERVED_ABOVE_TARGET"
    assert metrics["OUTPUT"].status == "OBSERVED_ABOVE_TARGET"
    remaining = detection_metrics([rows[0]])
    assert next(m for m in remaining if m.layer == "OUTPUT").status == "UNPROVEN"
