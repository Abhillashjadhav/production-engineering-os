"""pm-evals Web backend API.

A thin, typed transport over the deterministic ``pm_evals_compare`` engine:
uploads are size-capped, processed in memory, and never persisted (PD-V3-08);
malformed files return named validation issues (422, journey step J-4);
incompatible-but-parseable pairs return the comparison with verdict HOLD
(PD-V3-04); reports are regenerated deterministically server-side with the
generation timestamp isolated to labeled fields (PD-V3-07). No egress: the
backend calls nothing. Production monitoring uses a separate versioned
observation contract and an explicitly configured local append-only store;
comparison uploads never enter that store.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from pm_evals_compare import (
    CompareConfig,
    Comparison,
    EvalRun,
    ParseIssue,
    compare_runs,
    parse_run,
    render_json,
    render_markdown,
)
from pm_evals_monitoring import (
    MonitoringOverview,
    MonitoringStore,
    RunDiagnosis,
    RunEnvelope,
    build_demo_overview,
    build_overview,
    diagnose_run,
)
from pm_evals_monitoring.models import IngestResponse

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # per file; capped at read-back (T3)
# Whole-request outer bound, enforced at the transport boundary before the
# multipart parser reads or disk-spools anything (dogfood F-1). Two full-size
# files plus multipart framing and any form fields fit comfortably under it.
MAX_REQUEST_BYTES = 2 * MAX_UPLOAD_BYTES + 1024 * 1024

API_VERSION = "1.2.0"


class SizeLimitResponse(BaseModel):
    """The 413 body — one documented shape for either size boundary: the
    whole-request cap (the middleware, before parsing) and the per-file cap
    (``_read_capped``, at read-back) both emit ``{"detail": str}``."""

    detail: str


class BodySizeLimitMiddleware:
    """Refuse an over-cap request body at the transport boundary — before the
    multipart parser reads it or spools parts to disk (dogfood F-1). A declared
    Content-Length over the cap is rejected without reading a byte; otherwise the
    body is buffered up to the cap and aborted the instant it is exceeded, so the
    app (and its parser) never sees an oversized body. The per-file cap in
    ``_read_capped`` still bounds each parsed part; this is the coarse outer
    bound on the whole request."""

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        for name, value in scope["headers"]:
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    break
                if declared > self.max_bytes:
                    await self._too_large(send)
                    return
                break

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > self.max_bytes:
                await self._too_large(send)
                return
            if not message.get("more_body", False):
                break

        buffered = bytes(body)
        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": buffered, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)

    async def _too_large(self, send: Send) -> None:
        payload = json.dumps(
            {"detail": f"The request exceeds the {self.max_bytes // (1024 * 1024)} MB limit."}
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(payload)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": payload})


class ValidationProblem(BaseModel):
    # "baseline" | "candidate" for upload issues, or a request-field name
    # (e.g. "min_matched_traces") for transport-level validation errors.
    source: str
    issues: list[ParseIssue]


class ValidationErrorResponse(BaseModel):
    """The single 422 envelope: every validation failure — malformed upload,
    out-of-range config, or a native transport type error — is reported as
    ``{"detail": [ValidationProblem, ...]}`` so one committed schema matches
    the wire for all of them (P-4)."""

    detail: list[ValidationProblem]


class CompareResponse(BaseModel):
    comparison: Comparison


class HealthResponse(BaseModel):
    status: Literal["ok"]
    api_version: str


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


async def _read_capped(upload: UploadFile, source: str) -> bytes:
    data = await upload.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"{source} file exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit",
        )
    return data


async def _parse_pair(
    baseline: UploadFile, candidate: UploadFile
) -> tuple[EvalRun, EvalRun, str, str]:
    base_bytes = await _read_capped(baseline, "baseline")
    cand_bytes = await _read_capped(candidate, "candidate")
    base_result = parse_run(base_bytes, source_name="baseline")
    cand_result = parse_run(cand_bytes, source_name="candidate")
    problems: list[dict[str, Any]] = []
    if not base_result.ok:
        problems.append(
            ValidationProblem(source="baseline", issues=base_result.issues).model_dump()
        )
    if not cand_result.ok:
        problems.append(
            ValidationProblem(source="candidate", issues=cand_result.issues).model_dump()
        )
    if problems:
        # malformed evidence: named issues, never a stack trace (J-4)
        raise HTTPException(status_code=422, detail=problems)
    assert base_result.run is not None and cand_result.run is not None
    return base_result.run, cand_result.run, _sha256(base_bytes), _sha256(cand_bytes)


def _validation_error(source: str, message: str, *, location: str | None = None) -> HTTPException:
    """A 422 in the single documented envelope: {"detail": [ValidationProblem]}."""
    problem = ValidationProblem(
        source=source, issues=[ParseIssue(location=location or source, message=message)]
    )
    return HTTPException(status_code=422, detail=[problem.model_dump()])


def _config(min_matched_traces: int | None) -> CompareConfig:
    if min_matched_traces is None:
        return CompareConfig()
    if min_matched_traces < 1:
        raise _validation_error("min_matched_traces", "must be >= 1")
    return CompareConfig(min_matched_traces=min_matched_traces)


def create_app(*, monitoring_data_dir: Path | None = None) -> FastAPI:
    monitoring_store = MonitoringStore(monitoring_data_dir) if monitoring_data_dir else None
    app = FastAPI(
        title="pm-evals Web API",
        version=API_VERSION,
        description="Compare two eval runs or inspect versioned production-eval observations. "
        "Comparison uploads are processed in memory and never stored.",
    )
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=MAX_REQUEST_BYTES)

    # The size-limit middleware wraps *every* route, so 413 is reachable on any
    # endpoint that receives an over-cap body — it is documented wherever it can
    # occur, including /api/health, so the committed contract never omits a
    # response a client could actually receive (PD-V3-13).
    size_limit_response: dict[int | str, dict[str, Any]] = {
        413: {
            "description": "The request exceeds a size limit — the whole-request cap "
            "(enforced before parsing) or an individual file's cap.",
            "model": SizeLimitResponse,
        },
    }

    @app.exception_handler(RequestValidationError)
    async def _on_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Map FastAPI's native transport errors (missing part, wrong type) into
        # the SAME {"detail": [ValidationProblem]} envelope every other 422 uses,
        # grouped by request field so the source is real, never mis-attributed.
        by_source: dict[str, list[ParseIssue]] = {}
        for err in exc.errors():
            parts = [str(p) for p in err["loc"] if p != "body"]
            source = parts[0] if parts else "request"
            by_source.setdefault(source, []).append(
                ParseIssue(location=".".join(parts) or source, message=err["msg"])
            )
        detail = [
            ValidationProblem(source=source, issues=issues).model_dump()
            for source, issues in by_source.items()
        ]
        return JSONResponse(status_code=422, content={"detail": detail})

    @app.get("/api/health", response_model=HealthResponse, responses=size_limit_response)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", api_version=API_VERSION)

    validation_responses: dict[int | str, dict[str, Any]] = {
        **size_limit_response,
        422: {
            "description": "A validation failure: one or more named per-source problems.",
            "model": ValidationErrorResponse,
        },
    }

    @app.post("/api/compare", response_model=CompareResponse, responses=validation_responses)
    async def compare(
        baseline: Annotated[UploadFile, File()],
        candidate: Annotated[UploadFile, File()],
        min_matched_traces: int | None = Form(default=None),
    ) -> CompareResponse:
        base_run, cand_run, base_digest, cand_digest = await _parse_pair(baseline, candidate)
        comparison = compare_runs(
            base_run,
            cand_run,
            config=_config(min_matched_traces),
            baseline_digest=base_digest,
            candidate_digest=cand_digest,
        )
        return CompareResponse(comparison=comparison)

    @app.post(
        "/api/report",
        responses={
            **validation_responses,
            200: {
                "description": "The comparison report as a downloadable attachment "
                "(text/markdown or application/json, server-generated filename).",
                "content": {
                    "text/markdown": {"schema": {"type": "string"}},
                    "application/json": {"schema": {"type": "object"}},
                },
            },
        },
    )
    async def report(
        baseline: Annotated[UploadFile, File()],
        candidate: Annotated[UploadFile, File()],
        format: Literal["markdown", "json"] = Form(default="markdown"),
        min_matched_traces: int | None = Form(default=None),
    ) -> Response:
        base_run, cand_run, base_digest, cand_digest = await _parse_pair(baseline, candidate)
        comparison = compare_runs(
            base_run,
            cand_run,
            config=_config(min_matched_traces),
            baseline_digest=base_digest,
            candidate_digest=cand_digest,
        )
        # No wall-clock timestamp in the artifact: identical inputs must produce
        # byte-identical reports (GATE-4 / PD-V3-07). The render functions leave
        # the field out when no timestamp is supplied.
        if format == "markdown":
            return Response(
                content=render_markdown(comparison),
                media_type="text/markdown; charset=utf-8",
                headers={
                    # server-generated name: uploaded filenames never reach headers (T11)
                    "Content-Disposition": 'attachment; filename="eval-comparison.md"'
                },
            )
        return JSONResponse(
            content=json.loads(render_json(comparison)),
            headers={"Content-Disposition": 'attachment; filename="eval-comparison.json"'},
        )

    @app.post("/api/monitoring/evaluate", response_model=RunDiagnosis)
    async def evaluate_monitoring_run(run: RunEnvelope) -> RunDiagnosis:
        """Replay diagnosis without mutating monitoring history."""
        return diagnose_run(run)

    @app.post(
        "/api/monitoring/runs",
        response_model=IngestResponse,
        responses={
            409: {"description": "The run identity already exists with different evidence."},
            503: {"description": "Monitoring persistence is not configured."},
        },
    )
    async def ingest_monitoring_run(run: RunEnvelope) -> IngestResponse:
        if monitoring_store is None:
            raise HTTPException(status_code=503, detail="Monitoring persistence is not configured")
        try:
            stored = monitoring_store.append(run)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return IngestResponse(stored=stored, duplicate=not stored, diagnosis=diagnose_run(run))

    @app.get("/api/monitoring/overview", response_model=MonitoringOverview)
    async def monitoring_overview() -> MonitoringOverview:
        runs = monitoring_store.list_runs_for_overview() if monitoring_store else []
        return build_overview(runs, mode="LIVE") if runs else build_demo_overview()

    frontend_dist = os.environ.get("PM_EVALS_FRONTEND_DIST")
    if frontend_dist and Path(frontend_dist).is_dir():
        # Optional single-process preview/deployment seam. API routes are
        # registered first; the SPA owns only the remaining paths.
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

    return app


_monitoring_dir = Path(os.environ.get("PM_EVALS_MONITORING_DATA_DIR", "/tmp/pm-evals-monitoring"))
app = create_app(monitoring_data_dir=_monitoring_dir)
