"""Cross-boundary tests for reusable, evidence-preserving product connections."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_monitoring_production import _run

from pm_evals_api.app import create_app
from pm_evals_monitoring.adapter import AdapterSettings, NormalizedRun, map_normalized_run
from pm_evals_monitoring.integration import bind_baseline, connection_report


def test_viewer_access_is_separate_from_writes(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            monitoring_data_dir=tmp_path / "store",
            monitoring_ingest_token="producer",
            monitoring_viewer_token="viewer",
        )
    )
    assert client.get("/api/monitoring/overview").status_code == 401
    assert (
        client.get(
            "/api/monitoring/overview", headers={"Authorization": "Bearer producer"}
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/api/monitoring/overview", headers={"Authorization": "Bearer viewer"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/monitoring/runs",
            json=_run().model_dump(mode="json"),
            headers={"Authorization": "Bearer viewer"},
        ).status_code
        == 401
    )


def test_viewer_cannot_reuse_producer_credential() -> None:
    with pytest.raises(ValueError, match="distinct"):
        create_app(monitoring_ingest_token="same", monitoring_viewer_token="same")


def test_viewer_cannot_reuse_independent_reviewer_credential() -> None:
    with pytest.raises(ValueError, match="distinct"):
        create_app(monitoring_adjudication_token="same", monitoring_viewer_token="same")


def test_replay_of_stored_comparisons_requires_viewer_access(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            monitoring_data_dir=tmp_path / "store",
            monitoring_ingest_token="producer",
            monitoring_adjudication_token="reviewer",
            monitoring_viewer_token="viewer",
        )
    )
    payload = _run().model_dump(mode="json")
    for token in (None, "producer", "reviewer"):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        assert client.get("/api/monitoring/overview", headers=headers).status_code == 401
        assert (
            client.post("/api/monitoring/evaluate", json=payload, headers=headers).status_code
            == 401
        )
    assert (
        client.post(
            "/api/monitoring/evaluate",
            json=payload,
            headers={"Authorization": "Bearer viewer"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/monitoring/runs",
            json=payload,
            headers={"Authorization": "Bearer reviewer"},
        ).status_code
        == 401
    )


def test_normalized_facts_preserve_warning_and_individual_records() -> None:
    settings = AdapterSettings.model_validate_json(
        (Path(__file__).parents[2] / "adapters/linkedin-os.settings.json").read_text()
    )
    template = _run()
    checks = [
        {
            "definition_id": item,
            "status": "PASS",
            "current_value": 1.0,
            "expected_value": 1.0,
            "reason_code": "CHECK_PASSED",
        }
        for item in settings.case_types["linkedin-run"]
    ]
    checks[0]["recorded_threshold"] = {"value": 0.5}
    checks[1]["recorded_threshold"] = {"value": None}
    fact = {
        "contract": "gate_citation",
        "subject_id": "candidate-opaque",
        "cycle": 1,
        "recorded_status": "PASS",
        "observed_status": "FAIL",
        "mode": "diagnostic",
        "value": 0.0,
        "evidence_refs": [],
    }
    normalized = NormalizedRun.model_validate(
        {
            "run_id": template.run_id,
            "observed_at": template.observed_at,
            "product_version": "1",
            "comparison": template.comparison,
            "change_manifest": template.change_manifest,
            "provenance": template.provenance,
            "delivery_outcome": "COMPLETED_WITH_WARNINGS",
            "source_facts": [fact, dict(fact, cycle=2, observed_status="PASS", value=1.0)],
            "cases": [
                {
                    "case_type": "linkedin-run",
                    "case": template.observations[0].case,
                    "checks": checks,
                }
            ],
        }
    )
    normalized = NormalizedRun.model_validate(normalized.model_dump())
    mapped = map_normalized_run(settings, normalized)
    assert mapped.observations[0].threshold == 0.5
    assert mapped.observations[1].threshold is None
    assert mapped.delivery_outcome == "COMPLETED_WITH_WARNINGS"
    assert [f.observed_status for f in mapped.source_facts] == ["FAIL", "PASS"]
    assert len(mapped.source_facts) == 2
    assert connection_report(mapped)["delivery_outcome"] == "COMPLETED_WITH_WARNINGS"


def test_baseline_binding_copies_exact_values_and_digest() -> None:
    baseline = _run()
    current = baseline.model_copy(deep=True)
    current.run_id = "next-run"
    current.comparison.run_id = baseline.run_id
    baseline.observations[0].current_value = 0.3
    bound = bind_baseline(current, baseline)
    assert bound.observations[0].expected_value == 0.3
    assert bound.comparison.sha256.startswith("sha256:")


def test_baseline_binding_rejects_different_product() -> None:
    baseline = _run()
    current = baseline.model_copy(deep=True)
    current.product.id = "another-product"
    with pytest.raises(ValueError, match="product"):
        bind_baseline(current, baseline)


def test_additive_fields_do_not_change_legacy_run_digest(tmp_path: Path) -> None:
    import hashlib

    from pm_evals_monitoring.models import canonical_run_line
    from pm_evals_monitoring.storage import MonitoringStore

    run = _run()
    payload = run.model_dump(mode="json")
    payload.pop("source_facts")
    payload.pop("delivery_outcome")
    legacy = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    assert canonical_run_line(run) == legacy
    store = MonitoringStore(tmp_path / "store")
    store.log_path.write_bytes(legacy)
    store.rebuild_index()
    assert (
        store.get_run_digest(
            product_id=run.product.id, environment=run.product.environment, run_id=run.run_id
        )
        == "sha256:" + hashlib.sha256(legacy).hexdigest()
    )
    assert store.append(run) is False


def test_different_case_does_not_hide_valid_candidate_comparison() -> None:
    from datetime import timedelta

    from pm_evals_monitoring.diagnosis import _verified_comparison_observation

    baseline = _run()
    measured = baseline.observations[0]
    unrelated = baseline.observations[1]
    unrelated.case = unrelated.case.model_copy(update={"case_id": "unrelated"})
    unrelated.status = "NOT_EVALUATED"
    unrelated.current_value = None
    candidate = baseline.model_copy(deep=True)
    candidate.run_id = "candidate"
    candidate.observed_at = baseline.observed_at + timedelta(seconds=1)
    observation = candidate.observations[0]
    observation.expected_value = measured.current_value
    assert (
        _verified_comparison_observation(candidate, observation, baseline, "BLOCKED") == measured
    )
