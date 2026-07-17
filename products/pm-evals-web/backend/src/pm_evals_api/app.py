"""pm-evals Web backend API (PD-V3, contract APIs API-1..3).

A thin, typed transport over the deterministic ``pm_evals_compare`` engine:
uploads are size-capped, processed in memory, and never persisted (PD-V3-08);
malformed files return named validation issues (422, journey step J-4);
incompatible-but-parseable pairs return the comparison with verdict HOLD
(PD-V3-04); reports are regenerated deterministically server-side with the
generation timestamp isolated to labeled fields (PD-V3-07). No egress: the
backend calls nothing.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

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

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # per file; bounded before any parsing (T3)

API_VERSION = "1.0.0"


class ValidationProblem(BaseModel):
    source: Literal["baseline", "candidate"]
    issues: list[ParseIssue]


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


def _config(min_matched_traces: int | None) -> CompareConfig:
    if min_matched_traces is None:
        return CompareConfig()
    if min_matched_traces < 1:
        raise HTTPException(status_code=422, detail="min_matched_traces must be >= 1")
    return CompareConfig(min_matched_traces=min_matched_traces)


def create_app() -> FastAPI:
    app = FastAPI(
        title="pm-evals Web API",
        version=API_VERSION,
        description="Compare two eval runs and receive an evidence-backed release verdict. "
        "Uploads are processed in memory and never stored.",
    )

    @app.get("/api/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", api_version=API_VERSION)

    validation_responses: dict[int | str, dict[str, Any]] = {
        413: {"description": "An uploaded file exceeds the size limit."},
        422: {
            "description": "Malformed upload(s): named per-source parse issues.",
            "model": list[ValidationProblem],
        },
    }

    @app.post("/api/compare", response_model=CompareResponse, responses=validation_responses)
    async def compare(
        baseline: UploadFile = File(...),
        candidate: UploadFile = File(...),
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
        baseline: UploadFile = File(...),
        candidate: UploadFile = File(...),
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
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if format == "markdown":
            return Response(
                content=render_markdown(comparison, generated_at=generated_at),
                media_type="text/markdown; charset=utf-8",
                headers={
                    # server-generated name: uploaded filenames never reach headers (T11)
                    "Content-Disposition": 'attachment; filename="eval-comparison.md"'
                },
            )
        return JSONResponse(
            content=json.loads(render_json(comparison, generated_at=generated_at)),
            headers={"Content-Disposition": 'attachment; filename="eval-comparison.json"'},
        )

    return app


app = create_app()
