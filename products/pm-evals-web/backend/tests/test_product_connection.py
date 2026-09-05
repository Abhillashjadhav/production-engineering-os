"""Cross-boundary tests for reusable, evidence-preserving product connections."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pm_evals_api.app import create_app
from pm_evals_monitoring.adapter import AdapterSettings, NormalizedRun, map_normalized_run
from pm_evals_monitoring.integration import bind_baseline, connection_report
from test_monitoring_production import _run


def test_viewer_access_is_separate_from_writes(tmp_path: Path) -> None:
    client = TestClient(create_app(
        monitoring_data_dir=tmp_path / "store",
        monitoring_ingest_token="producer",
        monitoring_viewer_token="viewer",
    ))
    assert client.get("/api/monitoring/overview").status_code == 401
    assert client.get("/api/monitoring/overview", headers={"Authorization": "Bearer producer"}).status_code == 401
    assert client.get("/api/monitoring/overview", headers={"Authorization": "Bearer viewer"}).status_code == 200
    assert client.post("/api/monitoring/runs", json=_run().model_dump(mode="json"), headers={"Authorization": "Bearer viewer"}).status_code == 401


def test_viewer_cannot_reuse_producer_credential() -> None:
    with pytest.raises(ValueError, match="distinct"):
        create_app(monitoring_ingest_token="same", monitoring_viewer_token="same")


def test_normalized_facts_preserve_warning_and_individual_records() -> None:
    settings = AdapterSettings.model_validate_json((Path(__file__).parents[2] / "adapters/linkedin-os.settings.json").read_text())
    template = _run()
    checks = [{"definition_id": item, "status": "PASS", "current_value": 1.0, "expected_value": 1.0, "reason_code": "CHECK_PASSED"} for item in settings.case_types["linkedin-run"]]
    fact = {"contract": "gate_citation", "subject_id": "candidate-opaque", "cycle": 1, "recorded_status": "PASS", "observed_status": "FAIL", "mode": "diagnostic", "value": 0.0, "evidence_refs": []}
    normalized = NormalizedRun.model_validate({
        "run_id": template.run_id, "observed_at": template.observed_at,
        "product_version": "1", "comparison": template.comparison,
        "change_manifest": template.change_manifest, "provenance": template.provenance,
        "delivery_outcome": "COMPLETED_WITH_WARNINGS", "source_facts": [fact, dict(fact, cycle=2, observed_status="PASS", value=1.0)],
        "cases": [{"case_type": "linkedin-run", "case": template.observations[0].case, "checks": checks}],
    })
    mapped = map_normalized_run(settings, normalized)
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
