"""The pm-evals Web API: typed transport over the deterministic engine.

Covers the contract APIs (API-1..3), the malformed/incompatible journeys
(J-4), size caps (T3), hostile filenames (T11), no-persistence (T2), and the
determinism guardrail at the transport level (PD-V3-07)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from pm_evals_api.app import MAX_UPLOAD_BYTES, create_app

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
BASELINE = (FIXTURES / "baseline.json").read_bytes()
IMPROVED = (FIXTURES / "candidate_improved.json").read_bytes()
REGRESSION = (FIXTURES / "candidate_regression.json").read_bytes()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def _files(
    baseline: bytes = BASELINE,
    candidate: bytes = IMPROVED,
    *,
    baseline_name: str = "baseline.json",
    candidate_name: str = "candidate.json",
) -> dict[str, Any]:
    return {
        "baseline": (baseline_name, baseline, "application/json"),
        "candidate": (candidate_name, candidate, "application/json"),
    }


def test_health(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_compare_improved_proceeds(client: TestClient) -> None:
    response = client.post("/api/compare", files=_files())
    assert response.status_code == 200
    comparison = response.json()["comparison"]
    assert comparison["verdict"] == "PROCEED"
    assert comparison["matched_traces"] == 8
    assert comparison["baseline_digest"].startswith("sha256:")
    assert comparison["newly_passing_traces"] == ["T-003", "T-004", "T-005"]


def test_compare_regression_holds_with_evidence(client: TestClient) -> None:
    response = client.post("/api/compare", files=_files(candidate=REGRESSION))
    assert response.status_code == 200
    comparison = response.json()["comparison"]
    assert comparison["verdict"] == "HOLD"
    kinds = {r["kind"] for r in comparison["reasons"]}
    assert "hard_gate_regression" in kinds
    gate_reason = next(r for r in comparison["reasons"] if r["kind"] == "hard_gate_regression")
    assert gate_reason["trace_ids"] == ["T-006"]  # trace-level evidence (PD-V3-05)


def test_malformed_file_returns_named_issues(client: TestClient) -> None:
    response = client.post("/api/compare", files=_files(candidate=b"{broken"))
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail[0]["source"] == "candidate"
    assert "not valid JSON" in detail[0]["issues"][0]["message"]


def test_both_files_malformed_reports_both(client: TestClient) -> None:
    response = client.post("/api/compare", files=_files(baseline=b"[]", candidate=b"{"))
    assert response.status_code == 422
    sources = [p["source"] for p in response.json()["detail"]]
    assert sources == ["baseline", "candidate"]


def test_incompatible_pair_holds(client: TestClient) -> None:
    other = json.loads(BASELINE)
    other["suite"] = "another-suite"
    response = client.post("/api/compare", files=_files(candidate=json.dumps(other).encode()))
    assert response.status_code == 200
    comparison = response.json()["comparison"]
    assert comparison["verdict"] == "HOLD"
    assert any(r["kind"] == "incompatible" for r in comparison["reasons"])


def test_oversized_upload_is_refused(client: TestClient) -> None:
    big = b'{"format_version": 1, "padding": "' + b"x" * MAX_UPLOAD_BYTES + b'"}'
    response = client.post("/api/compare", files=_files(baseline=big))
    assert response.status_code == 413
    assert "baseline" in response.json()["detail"]


def test_hostile_filenames_never_reach_response_headers(client: TestClient) -> None:
    response = client.post(
        "/api/report",
        files=_files(baseline_name='../../etc/passwd";x="', candidate_name="<script>.json"),
        data={"format": "markdown"},
    )
    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert disposition == 'attachment; filename="eval-comparison.md"'


def test_markdown_report_downloads(client: TestClient) -> None:
    response = client.post(
        "/api/report", files=_files(candidate=REGRESSION), data={"format": "markdown"}
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert "## Verdict: HOLD" in response.text
    assert "Generated at:" not in response.text  # no uncontrolled wall-clock (GATE-4)


def test_json_report_downloads(client: TestClient) -> None:
    response = client.post("/api/report", files=_files(), data={"format": "json"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["comparison"]["verdict"] == "PROCEED"
    assert "generated_at" not in payload  # deterministic: no wall-clock field
    assert response.headers["content-disposition"] == (
        'attachment; filename="eval-comparison.json"'
    )


def test_reports_are_byte_identical_for_identical_inputs(client: TestClient) -> None:
    """GATE-4: identical inputs produce byte-identical reports (no clock)."""

    def _report(fmt: str) -> bytes:
        return client.post(
            "/api/report", files=_files(candidate=REGRESSION), data={"format": fmt}
        ).content

    assert _report("markdown") == _report("markdown")
    assert _report("json") == _report("json")


def test_invalid_min_matched_traces_is_refused(client: TestClient) -> None:
    response = client.post("/api/compare", files=_files(), data={"min_matched_traces": "0"})
    assert response.status_code == 422


def test_verdict_is_deterministic_across_requests(client: TestClient) -> None:
    first = client.post("/api/compare", files=_files(candidate=REGRESSION)).json()
    second = client.post("/api/compare", files=_files(candidate=REGRESSION)).json()
    assert first == second  # PD-V3-07 at the transport level


def test_uploads_leave_no_residue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PD-V3-08: nothing persisted. Spool space is redirected to a fresh dir,
    which must be empty once the request cycle completes."""
    spool = tmp_path / "spool"
    spool.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(spool))
    client = TestClient(create_app())
    response = client.post("/api/compare", files=_files(candidate=REGRESSION))
    assert response.status_code == 200
    assert list(spool.iterdir()) == []


def test_openapi_schema_is_committed_and_current(client: TestClient) -> None:
    """The committed OpenAPI schema is the contract (PD-V3-13): the live app
    must match it byte-for-byte under the export serialization (the CI diff
    and typed client build on this)."""
    committed = (Path(__file__).resolve().parents[1] / "openapi.json").read_text()
    live = json.dumps(
        client.app.openapi(),  # type: ignore[attr-defined]
        indent=2,
        sort_keys=True,
    )
    assert live + "\n" == committed


def test_deeply_nested_json_gets_named_issues_not_500(client: TestClient) -> None:
    """Pathological nesting must stay inside the locked malformed->422 mapping
    (T4): a ~2 KB bomb of 1000 nested arrays previously escaped as a bare 500."""
    bomb = b"[" * 1000 + b"]" * 1000
    response = client.post("/api/compare", files=_files(candidate=bomb))
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail[0]["source"] == "candidate"
    assert detail[0]["issues"][0]["message"].startswith("not valid JSON")


def test_input_digests_are_the_real_sha256(client: TestClient) -> None:
    """The digests are the verdict's evidence provenance — pin them to the
    actual bytes, not just the prefix."""
    import hashlib

    response = client.post("/api/compare", files=_files(candidate=REGRESSION))
    comparison = response.json()["comparison"]
    assert comparison["baseline_digest"] == "sha256:" + hashlib.sha256(BASELINE).hexdigest()
    assert comparison["candidate_digest"] == "sha256:" + hashlib.sha256(REGRESSION).hexdigest()
    assert comparison["baseline_digest"] != comparison["candidate_digest"]
