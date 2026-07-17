"""The pm-evals Web API: typed transport over the deterministic engine.

Covers the contract APIs (API-1..3), the malformed/incompatible journeys
(J-4), size caps (T3), hostile filenames (T11), no-persistence (T2), and the
determinism guardrail at the transport level (PD-V3-07)."""

from __future__ import annotations

import json
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from pm_evals_api.app import MAX_REQUEST_BYTES, MAX_UPLOAD_BYTES, create_app

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


def test_compare_response_carries_per_trace_criterion_details(client: TestClient) -> None:
    """S-3: the payload must carry a per-trace, per-criterion comparison for every
    changed trace (not only flipped criteria) so the frontend renders, never
    re-computes, the verdict."""
    response = client.post("/api/compare", files=_files(candidate=REGRESSION))
    comparison = response.json()["comparison"]
    details = {t["trace_id"]: t for t in comparison["trace_details"]}
    assert "T-006" in details  # the regressed trace is inspectable
    cells = {c["criterion_id"]: c for c in details["T-006"]["criteria"]}
    # every shared criterion is present, each with both sides + a verdict/rationale
    assert len(cells) >= 1
    for cell in cells.values():
        assert "baseline_result" in cell and "candidate_result" in cell
        assert cell["state"] and cell["verdict"] and cell["rationale"]


def test_malformed_file_returns_named_issues(client: TestClient) -> None:
    response = client.post("/api/compare", files=_files(candidate=b"{broken"))
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail[0]["source"] == "candidate"
    assert "not valid JSON" in detail[0]["issues"][0]["message"]


def test_duplicate_object_key_upload_is_refused_at_the_wire(client: TestClient) -> None:
    """Evidence integrity end-to-end: a run whose results map repeats a criterion
    key (which json.loads would silently coalesce to the last value) must reach
    the client as a named 422, never a silently-accepted 200 with a hidden flip."""
    poisoned = (
        b'{"format_version": 1, "run_id": "r", "suite": "support-copilot",'
        b' "criteria": [{"id": "C-ACC"}],'
        b' "traces": [{"trace_id": "T-1", "results": {"C-ACC": "pass", "C-ACC": "fail"}}]}'
    )
    response = client.post("/api/compare", files=_files(candidate=poisoned))
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail[0]["source"] == "candidate"
    assert "duplicate key" in detail[0]["issues"][0]["message"]


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


def test_whole_request_body_over_cap_is_refused_before_multipart_parsing(
    client: TestClient,
) -> None:
    """P-5 / dogfood F-1: a request body far larger than any legitimate two-file
    upload must be refused at the transport boundary — before Starlette's
    multipart parser reads and disk-spools it. Sent as multipart with a valid
    boundary but no matching parts: WITHOUT the size middleware the parser reads
    the whole body first and only then errors (4xx); WITH it, the oversize body
    is rejected 413 before a single byte reaches the parser. That the status is
    413 (not the parser's own error) is the proof the cap fires ahead of it."""
    oversize = b"x" * (3 * MAX_UPLOAD_BYTES)  # ~15 MB, over the whole-request cap
    response = client.post(
        "/api/compare",
        content=oversize,
        headers={"content-type": "multipart/form-data; boundary=zzzzzzzzzz"},
    )
    assert response.status_code == 413
    assert isinstance(response.json()["detail"], str)


def test_every_413_shares_one_documented_string_detail_envelope(client: TestClient) -> None:
    """The 413 body is a single documented shape — {"detail": str} — for both the
    per-file cap and the whole-request cap, so the committed contract matches the
    wire for either boundary (the #39 reviewer's open 413 NOTE)."""
    per_file = client.post(
        "/api/compare",
        files=_files(baseline=b'{"padding": "' + b"x" * MAX_UPLOAD_BYTES + b'"}'),
    )
    whole_request = client.post(
        "/api/compare",
        content=b"x" * (3 * MAX_UPLOAD_BYTES),
        headers={"content-type": "multipart/form-data; boundary=zzzzzzzzzz"},
    )
    for response in (per_file, whole_request):
        assert response.status_code == 413
        body = response.json()
        assert set(body) == {"detail"}, body
        assert isinstance(body["detail"], str) and body["detail"]


def test_committed_openapi_documents_the_413_body(client: TestClient) -> None:
    """The 413 must carry a content schema in the committed contract, not just a
    prose description — the typed client can only surface a shape the contract
    documents."""
    schema = client.app.openapi()  # type: ignore[attr-defined]
    ref = schema["paths"]["/api/compare"]["post"]["responses"]["413"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    name = ref.rsplit("/", 1)[-1]
    model = schema["components"]["schemas"][name]
    assert model["properties"]["detail"]["type"] == "string"


def _streamed(total_bytes: int, chunk: int = 256 * 1024) -> Iterator[bytes]:
    """A generator body: httpx sends it with Transfer-Encoding: chunked and NO
    Content-Length, so the size guard's header fast path cannot apply and the cap
    must be enforced inside the streaming buffer loop instead."""
    sent = 0
    while sent < total_bytes:
        n = min(chunk, total_bytes - sent)
        yield b"x" * n
        sent += n


def test_chunked_over_cap_body_without_content_length_is_refused_before_parsing(
    client: TestClient,
) -> None:
    """The adversarial F-1 path: an oversized body with NO Content-Length
    (chunked transfer) cannot take the header fast path — refusal depends
    entirely on the streaming buffer aborting at the cap, before the multipart
    parser reads or disk-spools the body. Delete the loop's size check and this
    is the test that fails; the Content-Length tests would still pass."""
    response = client.post(
        "/api/compare",
        content=_streamed(3 * MAX_UPLOAD_BYTES),  # ~15 MB, over the whole-request cap
        headers={"content-type": "multipart/form-data; boundary=zzzzzzzzzz"},
    )
    assert response.status_code == 413
    assert isinstance(response.json()["detail"], str)


def test_request_body_exactly_at_the_cap_is_not_size_rejected(client: TestClient) -> None:
    """The cap is inclusive: a body of exactly MAX_REQUEST_BYTES must pass the
    size guard — it then fails the multipart parser as non-conforming (a 4xx that
    is NOT 413). This pins the '>' comparison on both the header fast path and
    the buffer loop; a '>' -> '>=' regression would falsely reject a legitimate
    maximum-size upload and turn this 4xx into a 413."""
    response = client.post(
        "/api/compare",
        content=b"x" * MAX_REQUEST_BYTES,
        headers={"content-type": "multipart/form-data; boundary=zzzzzzzzzz"},
    )
    assert response.status_code != 413


def test_request_body_one_byte_over_the_cap_is_refused(client: TestClient) -> None:
    """The other side of the boundary: exactly one byte over the cap is refused
    413, so the guard is a true threshold, not an approximate one."""
    response = client.post(
        "/api/compare",
        content=b"x" * (MAX_REQUEST_BYTES + 1),
        headers={"content-type": "multipart/form-data; boundary=zzzzzzzzzz"},
    )
    assert response.status_code == 413
    assert isinstance(response.json()["detail"], str)


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


def _assert_validation_envelope(response: Any) -> None:
    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"detail"}, body  # one documented envelope: {"detail": [...]}
    assert isinstance(body["detail"], list) and body["detail"]
    for problem in body["detail"]:
        assert set(problem) == {"source", "issues"}, problem
        assert isinstance(problem["source"], str) and problem["source"]
        assert isinstance(problem["issues"], list) and problem["issues"]
        for issue in problem["issues"]:
            assert {"location", "message"} <= set(issue), issue


def test_every_422_shares_one_documented_envelope(client: TestClient) -> None:
    """P-4: malformed-parse, out-of-range config, native type errors, and a
    missing part must all return the SAME {"detail": [ValidationProblem]} shape
    the committed OpenAPI documents — not three different wire shapes."""
    malformed = client.post("/api/compare", files=_files(candidate=b"{broken"))
    bad_config = client.post("/api/compare", files=_files(), data={"min_matched_traces": "0"})
    non_integer = client.post("/api/compare", files=_files(), data={"min_matched_traces": "abc"})
    missing_part = client.post(
        "/api/compare", files={"baseline": ("b.json", BASELINE, "application/json")}
    )
    for response in (malformed, bad_config, non_integer, missing_part):
        _assert_validation_envelope(response)
    # the config error names its own field, not a mis-attributed upload source
    assert bad_config.json()["detail"][0]["source"] == "min_matched_traces"
    assert missing_part.json()["detail"][0]["source"] == "candidate"


def test_committed_openapi_documents_the_422_envelope(client: TestClient) -> None:
    schema = client.app.openapi()  # type: ignore[attr-defined]
    ref = schema["paths"]["/api/compare"]["post"]["responses"]["422"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    name = ref.rsplit("/", 1)[-1]
    model = schema["components"]["schemas"][name]
    assert list(model["properties"]) == ["detail"]
    assert model["properties"]["detail"]["type"] == "array"


def test_health_documents_the_413_it_can_return(client: TestClient) -> None:
    """The size-limit middleware wraps every route, so an over-cap body to
    /api/health returns a 413 — the committed contract must document it, not
    claim health can only ever return 200 (PD-V3-13: no undocumented response a
    client could receive)."""
    schema = client.app.openapi()  # type: ignore[attr-defined]
    responses = schema["paths"]["/api/health"]["get"]["responses"]
    assert "413" in responses
    ref = responses["413"]["content"]["application/json"]["schema"]["$ref"]
    assert ref.rsplit("/", 1)[-1] == "SizeLimitResponse"


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


def test_spooled_upload_and_error_path_leave_no_residue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PD-V3-08 / dogfood F-7: the small-file success case never crosses
    Starlette's 1 MB spool threshold, so it never causes the disk write whose
    cleanup it claims to verify. Force a part large enough to actually roll over
    to disk, prove the rollover happened, and confirm no residue remains — on the
    success path AND the malformed error path."""
    spool = tmp_path / "spool"
    spool.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(spool))

    rollovers = 0
    original_rollover = tempfile.SpooledTemporaryFile.rollover

    def counting_rollover(self: Any) -> Any:
        nonlocal rollovers
        rollovers += 1
        return original_rollover(self)

    monkeypatch.setattr(tempfile.SpooledTemporaryFile, "rollover", counting_rollover)

    padded = json.loads(BASELINE)
    padded["model"] = "x" * (1024 * 1024 + 1000)  # > Starlette's 1 MB spool threshold
    big_baseline = json.dumps(padded).encode()

    client = TestClient(create_app())

    # Success path with a genuine disk spool.
    ok = client.post("/api/compare", files=_files(baseline=big_baseline))
    assert ok.status_code == 200
    assert rollovers >= 1, "the >1 MB part never spooled — the cleanup stays untested"
    assert list(spool.iterdir()) == []  # the rolled-over temp file was cleaned up

    # Malformed error path: a >1 MB part still spools, then parsing fails 422.
    malformed = client.post(
        "/api/compare",
        files=_files(baseline=big_baseline, candidate=b"{" + b"x" * (1024 * 1024)),
    )
    assert malformed.status_code == 422
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
