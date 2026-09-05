"""Real HTTP test against the native exporter supplied by LINKEDIN_OS_REPO.

No model call, research, native execution, or real product evidence is involved.
"""

import importlib
import json
import os
import socket
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import uvicorn
from fastapi.testclient import TestClient

from pm_evals_api.app import create_app
from pm_evals_monitoring.adapter import AdapterSettings, NormalizedRun, map_normalized_run
from pm_evals_monitoring.integration import bind_baseline
from pm_evals_monitoring.models import canonical_run_digest
from pm_evals_monitoring.outbox import enqueue, flush_resilient, http_post_sender


@pytest.mark.skipif(
    not os.environ.get("LINKEDIN_OS_REPO"), reason="requires the explicit native LinkedIn checkout"
)
def test_native_export_real_http_storage_and_independent_reviews(tmp_path):
    sys.path.insert(0, str(Path(os.environ["LINKEDIN_OS_REPO"]) / "src"))
    native = importlib.import_module("authority_os.monitoring_export")
    settings = AdapterSettings.model_validate_json(
        (Path(__file__).parents[2] / "adapters/linkedin-os.settings.json").read_text()
    )
    now = datetime.now(UTC) - timedelta(minutes=1)
    context = {key: "test-1" for key in native.CONTEXT_FIELDS}
    context.update(
        run_id="baseline",
        comparison_run_id="no-earlier-run",
        observed_at=now.isoformat(),
        since=(now - timedelta(minutes=1)).isoformat(),
        through=(now + timedelta(minutes=1)).isoformat(),
        case_id="frozen-test-input",
        input_fingerprint="sha256:" + "a" * 64,
    )
    rows = [
        {
            "run_id": "baseline",
            "recorded_at": now.isoformat(),
            "contract": contract,
            "status": "PASS",
            "mode": "enforce",
            "subject_id": "candidate",
            "evidence": {"cycle": 1},
        }
        for contract in native.CONTRACTS
    ]
    exported = native.build_normalized_export(context, rows)
    baseline = map_normalized_run(settings, NormalizedRun.model_validate(exported))
    candidate_context = dict(
        context,
        run_id="candidate",
        comparison_run_id="baseline",
        observed_at=(now + timedelta(seconds=10)).isoformat(),
    )
    candidate_rows = [
        dict(
            row,
            run_id="candidate",
            status="FAIL"
            if row["contract"]
            in {"tool_trajectory", "atomic_value_novelty", "critic_anchor_integrity"}
            else "PASS",
        )
        for row in rows
    ]
    candidate_rows.append(
        {
            "run_id": "candidate",
            "recorded_at": now.isoformat(),
            "contract": "draft_delivery",
            "status": "PASS",
            "mode": "diagnostic",
            "evidence": {"observed_status": "COMPLETED_WITH_WARNINGS"},
        }
    )
    candidate = bind_baseline(
        map_normalized_run(
            settings,
            NormalizedRun.model_validate(
                native.build_normalized_export(candidate_context, candidate_rows)
            ),
        ),
        baseline,
    )
    assert candidate.comparison.sha256 == canonical_run_digest(baseline)
    app = create_app(
        monitoring_data_dir=tmp_path / "store",
        monitoring_ingest_token="producer",
        monitoring_viewer_token="viewer",
        monitoring_adjudication_token="reviewer",
    )
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.01)
    try:
        assert server.started
        sender = http_post_sender(f"http://127.0.0.1:{listener.getsockname()[1]}", "producer")
        sender("/api/monitoring/runs", baseline.model_dump(mode="json"))
        enqueue(
            tmp_path / "queue",
            route="/api/monitoring/runs",
            identity="candidate",
            payload=candidate.model_dump(mode="json"),
        )
        assert flush_resilient(tmp_path / "queue", sender=sender)["sent"] == 1
        assert flush_resilient(tmp_path / "queue", sender=sender)["sent"] == 0
        client = TestClient(app)
        for layer in ("TOOL_TRAJECTORY", "SYSTEM", "OUTPUT"):
            observation = next(
                o
                for o in candidate.observations
                if o.evaluation.layer == layer and o.status == "FAIL"
            )
            payload = {
                "review_id": layer,
                "product_id": candidate.product.id,
                "environment": candidate.product.environment,
                "run_id": candidate.run_id,
                "case_id": observation.case.case_id,
                "observation_id": observation.observation_id,
                "layer": layer,
                "actual_failure": True,
                "silent": True,
                "evidence_scope": "TEST",
                "dataset_version": "planted-1",
                "reviewer_id": "independent-test-oracle",
                "reviewed_at": datetime.now(UTC).isoformat(),
                "evidence_refs": [
                    {"uri": "urn:planted-failure:" + layer, "sha256": "sha256:" + "b" * 64}
                ],
            }
            assert (
                client.post(
                    "/api/monitoring/detection-reviews",
                    json=payload,
                    headers={"Authorization": "Bearer producer"},
                ).status_code
                == 401
            )
            assert (
                client.post(
                    "/api/monitoring/detection-reviews",
                    json=payload,
                    headers={"Authorization": "Bearer reviewer"},
                ).status_code
                == 200
            )
        overview = client.get(
            "/api/monitoring/overview", headers={"Authorization": "Bearer viewer"}
        ).json()
        assert overview["products"][0]["delivery_outcome"] == "COMPLETED_WITH_WARNINGS"
        assert overview["products"][0]["source_facts"]
        assert len(overview["detection_metrics"]) == 3
        assert all(m["detected_silent_failures"] == 1 for m in overview["detection_metrics"])
        assert all(m["evidence_scope"] == "TEST" for m in overview["detection_metrics"])
        assert any(
            i["comparison_label"] != "Comparison unavailable" for i in overview["incidents"]
        )
        # Reopening the store must preserve completed delivery and review evidence.
        reopened = TestClient(
            create_app(monitoring_data_dir=tmp_path / "store", monitoring_viewer_token="viewer")
        )
        assert (
            reopened.get(
                "/api/monitoring/overview", headers={"Authorization": "Bearer viewer"}
            ).json()["detection_metrics"]
            == overview["detection_metrics"]
        )
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()


@pytest.mark.skipif(
    not os.environ.get("LINKEDIN_OS_REPO"), reason="requires native LinkedIn checkout"
)
def test_completed_dashboard_worker_binds_scores_without_touching_generation(tmp_path):
    import shutil

    from pm_evals_monitoring.diagnosis import diagnose_run
    from pm_evals_monitoring.models import RunEnvelope
    from pm_evals_monitoring.worker import collect_linkedin

    native_root = Path(os.environ["LINKEDIN_OS_REPO"])
    repo = tmp_path / "native"
    shutil.copytree(
        native_root / "src", repo / "src", ignore=shutil.ignore_patterns("__pycache__")
    )
    shutil.copytree(native_root / "config", repo / "config")
    (repo / "bin").mkdir()
    shutil.copy2(native_root / "bin/linkedin-os", repo / "bin/linkedin-os")
    sys.path.insert(0, str(native_root / "tests"))
    fixture = importlib.import_module("test_eval_package")
    context_factory = importlib.import_module("test_monitoring_export").context
    context = dict(context_factory(), comparison_run_id="NO_BASELINE")
    template = tmp_path / "context.json"
    template.write_text(json.dumps(context))
    settings = Path(__file__).parents[2] / "adapters/linkedin-os.settings.json"
    before = {}
    for name, scores in [
        ("a-baseline", (4, 4, 4, 4, 4)),
        ("b-candidate", (5, 4, 4, 4, 4)),
        ("c-later", (4, 4, 4, 4, 4)),
    ]:
        folder = repo / "data/private/draft-runs" / name
        folder.mkdir(parents=True, mode=0o700)
        run = {"run_id": name, "outcome": "COMPLETED_WITH_WARNINGS"}
        evaluation = {
            "run_id": name,
            "acceptance_contract": {
                "minimum_total": 18,
                "axis_floors": {
                    "hook_strength": 4,
                    "voice_fidelity": 4,
                    "middle_escalation": 3,
                    "earned_closer": 3,
                    "specificity_and_source_quality": 3,
                },
            },
            "results": [fixture._evaluated_result(scores)],
            "checks": [],
            "critic_scorecards": [],
        }
        identity = {
            "case_id": "frozen-input",
            "input_fingerprint": "sha256:" + "a" * 64,
            "comparison_run_id": "a-baseline"
            if name == "b-candidate"
            else "b-candidate"
            if name == "c-later"
            else "NO_BASELINE",
        }
        for filename, payload in [
            ("run-dashboard.json", run),
            ("eval-dashboard.json", evaluation),
            ("monitoring-identity.json", identity),
        ]:
            path = folder / filename
            path.write_text(json.dumps(payload))
            path.chmod(0o600)
            before[path] = path.read_bytes()
        (folder / "eval-dashboard.html").write_text("Completed synthetic dashboard")
    queue = tmp_path / "queue"
    result = collect_linkedin(repo, template, settings, queue)
    assert result == {"queued": 3, "invalid": 0, "incomplete": 0}
    assert all(path.read_bytes() == content for path, content in before.items())
    runs = {
        payload["payload"]["run_id"]: RunEnvelope.model_validate(payload["payload"])
        for payload in [json.loads(path.read_bytes()) for path in queue.glob("*.pending.json")]
    }
    baseline, candidate = runs["b-candidate"], runs["c-later"]
    assert baseline.comparison.sha256 == canonical_run_digest(runs["a-baseline"])
    assert candidate.comparison.sha256 == canonical_run_digest(baseline)
    diagnosis = diagnose_run(candidate, comparison=baseline)
    assert any(item.attribution == "DEGRADED_CHECK" for item in diagnosis.diagnoses)
    assert any(
        o.evaluation.layer == "TOOL_TRAJECTORY" and o.status == "NOT_EVALUATED"
        for o in candidate.observations
    )
    # A restart must reuse the verified export without rerunning drafting or
    # producing conflicting timestamps/identities.
    assert collect_linkedin(repo, template, settings, queue)["invalid"] == 0
    assert len(list(queue.glob("*.pending.json"))) == 3
