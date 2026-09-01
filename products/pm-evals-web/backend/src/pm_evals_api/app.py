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
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import quote, unquote

from fastapi import FastAPI, File, Form, HTTPException, Request, Security, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
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
    AdjudicationRecord,
    AppendResponse,
    FutureObservationError,
    MonitoringOverview,
    MonitoringStore,
    ProductRef,
    RunDiagnosis,
    RunEnvelope,
    RunReceipt,
    build_demo_overview,
    build_empty_overview,
    build_overview,
    canonical_run_digest,
    case_incident_id,
    diagnose_run,
    replay_dimension_values,
)
from pm_evals_monitoring.models import MAX_FUTURE_CLOCK_SKEW, IngestResponse

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # per file; capped at read-back (T3)
# Whole-request outer bound, enforced at the transport boundary before the
# multipart parser reads or disk-spools anything (dogfood F-1). Two full-size
# files plus multipart framing and any form fields fit comfortably under it.
MAX_REQUEST_BYTES = 2 * MAX_UPLOAD_BYTES + 1024 * 1024

API_VERSION = "1.3.0"

_monitoring_ingestion_bearer = HTTPBearer(
    auto_error=False,
    scheme_name="MonitoringIngestionBearer",
    description="Bearer credential for trusted production-eval run producers.",
)


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


def _encode_replay_reference(run_id: str, observation_id: str) -> str:
    """Encode two otherwise-free identifiers into one unambiguous replay reference."""

    return f"{quote(run_id, safe='')}#{quote(observation_id, safe='')}"


def _decode_replay_reference(value: str) -> tuple[str, str]:
    if value.count("#") != 1:
        raise ValueError("controlled replay reference must contain one encoded delimiter")
    run_id, observation_id = value.split("#", 1)
    if not run_id or not observation_id:
        raise ValueError("controlled replay reference components must not be empty")
    return unquote(run_id), unquote(observation_id)


def _config(min_matched_traces: int | None) -> CompareConfig:
    if min_matched_traces is None:
        return CompareConfig()
    if min_matched_traces < 1:
        raise _validation_error("min_matched_traces", "must be >= 1")
    return CompareConfig(min_matched_traces=min_matched_traces)


def create_app(
    *,
    monitoring_data_dir: Path | None = None,
    monitoring_ingest_token: str | None = None,
    monitoring_ingest_credentials: dict[tuple[str, str], str] | None = None,
    monitoring_adjudication_token: str | None = None,
    monitoring_demo_mode: bool = False,
    monitoring_production: bool = False,
    monitoring_expected_products: list[ProductRef] | None = None,
    monitoring_ingest_limit_per_minute: int = 120,
) -> FastAPI:
    monitoring_store = MonitoringStore(monitoring_data_dir) if monitoring_data_dir else None
    scoped_credentials = monitoring_ingest_credentials or {}
    expected_products = monitoring_expected_products or []
    if monitoring_ingest_token and scoped_credentials:
        raise ValueError("legacy and product-scoped monitoring credentials cannot be mixed")
    if len(set(scoped_credentials.values())) != len(scoped_credentials):
        raise ValueError("each product monitoring identity requires a distinct credential")
    producer_tokens = set(scoped_credentials.values())
    if monitoring_ingest_token:
        producer_tokens.add(monitoring_ingest_token)
    if monitoring_adjudication_token in producer_tokens:
        raise ValueError("the monitoring adjudication credential must be distinct from producers")
    if monitoring_production and monitoring_demo_mode:
        raise ValueError("production monitoring cannot enable demo mode")
    expected_identities = {(product.id, product.environment) for product in expected_products}
    if monitoring_production and (
        monitoring_ingest_token or not scoped_credentials or not expected_identities
    ):
        raise ValueError("production monitoring requires scoped credentials and expected products")
    if monitoring_production and set(scoped_credentials) != expected_identities:
        raise ValueError(
            "production monitoring credentials and expected-product identities must match"
        )
    if monitoring_ingest_limit_per_minute < 1:
        raise ValueError("monitoring ingest limit must be positive")

    def authorize_product(
        credentials: HTTPAuthorizationCredentials | None,
        *,
        product_id: str,
        environment: str,
    ) -> None:
        supplied = credentials.credentials if credentials is not None else ""
        if monitoring_ingest_token:
            if secrets.compare_digest(supplied, monitoring_ingest_token):
                return
        else:
            expected = scoped_credentials.get((product_id, environment))
            if expected is not None and secrets.compare_digest(supplied, expected):
                return
            if any(
                secrets.compare_digest(supplied, token) for token in scoped_credentials.values()
            ):
                raise HTTPException(
                    status_code=403,
                    detail="Monitoring credential is not authorized for this product identity",
                )
        raise HTTPException(
            status_code=401,
            detail="Valid monitoring ingestion credentials are required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    def stored_comparison(run: RunEnvelope) -> RunEnvelope | None:
        if monitoring_store is None:
            return None
        comparison = monitoring_store.get_run(
            product_id=run.product.id,
            environment=run.product.environment,
            run_id=run.comparison.run_id,
        )
        if (
            comparison is None
            or run.comparison.sha256 is None
            or canonical_run_digest(comparison) != run.comparison.sha256
        ):
            return None
        return comparison

    def admit_product(product_id: str, environment: str) -> None:
        if monitoring_store is None:
            return
        if not monitoring_store.admit_ingest(
            product_id=product_id,
            environment=environment,
            limit_per_minute=monitoring_ingest_limit_per_minute,
        ):
            raise HTTPException(status_code=429, detail="Product ingestion rate limit exceeded")

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

    @app.post(
        "/api/monitoring/evaluate",
        response_model=RunDiagnosis,
        responses=validation_responses,
    )
    def evaluate_monitoring_run(run: RunEnvelope) -> RunDiagnosis:
        """Replay diagnosis without mutating monitoring history."""
        return diagnose_run(run, comparison=stored_comparison(run))

    @app.post(
        "/api/monitoring/runs",
        response_model=IngestResponse,
        responses={
            **validation_responses,
            401: {"description": "A valid monitoring ingestion credential is required."},
            403: {"description": "The credential belongs to another product identity."},
            409: {"description": "The run identity already exists with different evidence."},
            503: {
                "description": "Monitoring persistence or its ingestion credential is not configured."
            },
        },
    )
    def ingest_monitoring_run(
        run: RunEnvelope,
        credentials: Annotated[
            HTTPAuthorizationCredentials | None,
            Security(_monitoring_ingestion_bearer),
        ],
    ) -> IngestResponse:
        if monitoring_store is None:
            raise HTTPException(status_code=503, detail="Monitoring persistence is not configured")
        if not monitoring_ingest_token and not scoped_credentials:
            raise HTTPException(
                status_code=503,
                detail="Monitoring ingestion credential is not configured",
            )
        authorize_product(
            credentials,
            product_id=run.product.id,
            environment=run.product.environment,
        )
        admit_product(run.product.id, run.product.environment)
        if run.observed_at > datetime.now(UTC) + MAX_FUTURE_CLOCK_SKEW:
            raise _validation_error(
                "observed_at", "observed_at exceeds the allowed five-minute clock skew"
            )
        for observation in run.observations:
            for signal in observation.cause_signals:
                if signal.evidence_level == "HUMAN_ADJUDICATION":
                    raise _validation_error(
                        "cause_signals",
                        "product ingestion cannot assert human adjudication",
                    )
                if signal.evidence_level != "CONTROLLED_REPLAY":
                    continue
                assert signal.candidate_ref is not None
                try:
                    candidate_reference = _decode_replay_reference(signal.candidate_ref)
                except ValueError as exc:
                    raise _validation_error(
                        "candidate_ref",
                        "controlled replay candidate must use encoded run_id#observation_id",
                    ) from exc
                if candidate_reference != (run.run_id, observation.observation_id) or (
                    signal.candidate_status != observation.status
                ):
                    raise _validation_error(
                        "candidate_ref",
                        "controlled replay candidate must resolve to the ingested observation",
                    )
                assert signal.control_ref is not None
                try:
                    control_run_id, control_observation_id = _decode_replay_reference(
                        signal.control_ref
                    )
                except ValueError as exc:
                    raise _validation_error(
                        "control_ref",
                        "controlled replay control must use encoded run_id#observation_id",
                    ) from exc
                control_run = monitoring_store.get_run(
                    product_id=run.product.id,
                    environment=run.product.environment,
                    run_id=control_run_id,
                )
                control_observation = (
                    next(
                        (
                            item
                            for item in control_run.observations
                            if item.observation_id == control_observation_id
                        ),
                        None,
                    )
                    if control_run is not None
                    else None
                )
                if (
                    control_observation is None
                    or signal.control_status != control_observation.status
                ):
                    raise _validation_error(
                        "control_ref",
                        "controlled replay control does not resolve in stored evidence",
                    )
                if (
                    control_observation.case != observation.case
                    or control_observation.evaluation != observation.evaluation
                    or control_observation.location != observation.location
                ):
                    raise _validation_error(
                        "control_ref",
                        "controlled replay must compare the same case, evaluation, and location",
                    )
                control_measurement = (
                    control_observation.threshold,
                    control_observation.higher_is_better,
                    control_observation.unit,
                    control_observation.tolerance,
                    control_observation.required,
                    tuple(sorted(control_observation.depends_on)),
                )
                candidate_measurement = (
                    observation.threshold,
                    observation.higher_is_better,
                    observation.unit,
                    observation.tolerance,
                    observation.required,
                    tuple(sorted(observation.depends_on)),
                )
                if control_measurement != candidate_measurement:
                    raise _validation_error(
                        "control_ref",
                        "controlled replay must preserve the measurement definition",
                    )
                assert control_run is not None
                control_manifest = replay_dimension_values(
                    control_run.change_manifest, control_run.provenance
                )
                candidate_manifest = replay_dimension_values(run.change_manifest, run.provenance)
                actual_varied = {
                    dimension
                    for dimension, candidate_value in candidate_manifest.items()
                    if candidate_value != control_manifest[dimension]
                }
                if actual_varied != set(signal.varied_dimensions):
                    raise _validation_error(
                        "cause_signals",
                        "controlled replay varied dimensions do not match stored manifests",
                    )
        stored_digest = monitoring_store.get_run_digest(
            product_id=run.product.id,
            environment=run.product.environment,
            run_id=run.comparison.run_id,
        )
        if stored_digest is not None:
            if run.comparison.sha256 is None:
                raise _validation_error(
                    "comparison.sha256", "stored comparison references require a digest"
                )
            if stored_digest != run.comparison.sha256:
                raise _validation_error(
                    "comparison.sha256", "comparison digest does not match stored evidence"
                )
        try:
            stored = monitoring_store.append(run)
        except FutureObservationError as exc:
            raise _validation_error("observed_at", str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return IngestResponse(
            stored=stored,
            duplicate=not stored,
            diagnosis=diagnose_run(run, comparison=stored_comparison(run)),
        )

    @app.post(
        "/api/monitoring/receipts",
        response_model=AppendResponse,
        responses={
            **validation_responses,
            401: {"description": "A valid monitoring ingestion credential is required."},
            403: {"description": "The credential belongs to another product identity."},
            409: {"description": "The receipt identity exists with different evidence."},
            503: {"description": "Monitoring persistence is not configured."},
        },
    )
    def ingest_monitoring_receipt(
        receipt: RunReceipt,
        credentials: Annotated[
            HTTPAuthorizationCredentials | None,
            Security(_monitoring_ingestion_bearer),
        ],
    ) -> AppendResponse:
        if monitoring_store is None:
            raise HTTPException(status_code=503, detail="Monitoring persistence is not configured")
        if not monitoring_ingest_token and not scoped_credentials:
            raise HTTPException(
                status_code=503,
                detail="Monitoring ingestion credential is not configured",
            )
        authorize_product(
            credentials,
            product_id=receipt.product.id,
            environment=receipt.product.environment,
        )
        admit_product(receipt.product.id, receipt.product.environment)
        try:
            stored = monitoring_store.append_receipt(receipt)
        except FutureObservationError as exc:
            raise _validation_error("observed_at", str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return AppendResponse(stored=stored, duplicate=not stored)

    @app.post(
        "/api/monitoring/adjudications",
        response_model=AppendResponse,
        responses={
            **validation_responses,
            401: {"description": "A privileged adjudication credential is required."},
            409: {"description": "The adjudication identity exists with different evidence."},
            503: {"description": "Monitoring persistence or adjudication is not configured."},
        },
    )
    def ingest_monitoring_adjudication(
        record: AdjudicationRecord,
        credentials: Annotated[
            HTTPAuthorizationCredentials | None,
            Security(_monitoring_ingestion_bearer),
        ],
    ) -> AppendResponse:
        if monitoring_store is None or not monitoring_adjudication_token:
            raise HTTPException(
                status_code=503, detail="Monitoring adjudication is not configured"
            )
        supplied = credentials.credentials if credentials is not None else ""
        if not secrets.compare_digest(supplied, monitoring_adjudication_token):
            raise HTTPException(
                status_code=401,
                detail="Valid adjudication credentials are required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        run = monitoring_store.get_run(
            product_id=record.product_id,
            environment=record.environment,
            run_id=record.run_id,
        )
        if run is None:
            raise _validation_error("run_id", "adjudication run does not exist")
        observation_ids = {item.observation_id for item in run.observations}
        if record.observation_id not in observation_ids or not set(
            record.actual_root_observation_ids
        ).issubset(observation_ids):
            raise _validation_error(
                "observation_id", "adjudication observations do not exist in the stored run"
            )
        observation = next(
            item for item in run.observations if item.observation_id == record.observation_id
        )
        expected_case_incident_id = case_incident_id(
            product_id=run.product.id,
            environment=run.product.environment,
            run_id=run.run_id,
            case=observation.case,
        )
        if record.case_incident_id != expected_case_incident_id:
            raise _validation_error(
                "case_incident_id",
                "case incident identity must match the stored run and exact case",
            )
        diagnosis = diagnose_run(run, comparison=stored_comparison(run))
        diagnosed = next(
            (item for item in diagnosis.diagnoses if item.observation_id == record.observation_id),
            None,
        )
        if diagnosed is None:
            raise _validation_error(
                "observation_id",
                "observation does not represent an adjudicable diagnosis",
            )
        predicted = diagnosed.root_observation_ids
        if sorted(record.predicted_root_observation_ids) != sorted(predicted):
            raise _validation_error(
                "predicted_root_observation_ids",
                "predicted roots must match the server diagnosis",
            )
        if (
            diagnosed.attribution not in {"LIKELY_STARTING_FAILURE", "DEGRADED_CHECK"}
            and record.verdict != "UNRESOLVED"
        ):
            raise _validation_error(
                "verdict",
                "only independently projected root incidents may receive a resolved verdict",
            )
        derived_verdict = (
            "UNRESOLVED"
            if not record.actual_root_observation_ids
            else "CORRECT"
            if set(predicted) == set(record.actual_root_observation_ids)
            else "INCORRECT"
        )
        if record.verdict != derived_verdict:
            raise _validation_error(
                "verdict",
                "verdict must match the server comparison of predicted and actual roots",
            )
        try:
            stored = monitoring_store.append_adjudication(record)
        except FutureObservationError as exc:
            raise _validation_error("adjudicated_at", str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return AppendResponse(stored=stored, duplicate=not stored)

    @app.get("/api/monitoring/overview", response_model=MonitoringOverview)
    def monitoring_overview() -> MonitoringOverview:
        runs = monitoring_store.list_runs_for_overview() if monitoring_store else []
        receipts = monitoring_store.list_receipts() if monitoring_store else []
        adjudications = monitoring_store.list_adjudications() if monitoring_store else []
        if runs:
            return build_overview(
                runs,
                mode="LIVE",
                receipts=receipts,
                adjudications=adjudications,
                expected_products=expected_products,
            )
        if monitoring_demo_mode:
            return build_demo_overview()
        return build_empty_overview(
            receipts=receipts,
            adjudications=adjudications,
            expected_products=expected_products,
        )

    frontend_dist = os.environ.get("PM_EVALS_FRONTEND_DIST")
    if frontend_dist and Path(frontend_dist).is_dir():
        # Optional single-process preview/deployment seam. API routes are
        # registered first; the SPA owns only the remaining paths.
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

    return app


def _scoped_credentials_from_environment() -> dict[tuple[str, str], str]:
    raw = os.environ.get("PM_EVALS_INGEST_CREDENTIALS_JSON", "")
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("PM_EVALS_INGEST_CREDENTIALS_JSON must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise TypeError("PM_EVALS_INGEST_CREDENTIALS_JSON must be an object")
    result: dict[tuple[str, str], str] = {}
    for identity, token in payload.items():
        if not isinstance(identity, str) or not isinstance(token, str) or not token:
            raise RuntimeError("monitoring credential entries must be non-empty strings")
        parts = identity.split("|", 1)
        if len(parts) != 2 or not all(parts):
            raise RuntimeError("monitoring credential keys must use product_id|environment")
        result[(parts[0], parts[1])] = token
    if len(set(result.values())) != len(result):
        raise RuntimeError("monitoring credentials must be unique per product identity")
    return result


def _expected_products_from_environment() -> list[ProductRef]:
    raw = os.environ.get("PM_EVALS_EXPECTED_PRODUCTS_JSON", "")
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("PM_EVALS_EXPECTED_PRODUCTS_JSON must be valid JSON") from exc
    if not isinstance(payload, list):
        raise TypeError("PM_EVALS_EXPECTED_PRODUCTS_JSON must be an array")
    products = [ProductRef.model_validate(item) for item in payload]
    identities = [(item.id, item.environment) for item in products]
    if len(identities) != len(set(identities)):
        raise RuntimeError("expected product identities must be unique")
    return products


_monitoring_dir = Path(os.environ.get("PM_EVALS_MONITORING_DATA_DIR", "/tmp/pm-evals-monitoring"))
_production_monitoring = os.environ.get("PM_EVALS_PRODUCTION_MONITORING") == "1"
_scoped_credentials = _scoped_credentials_from_environment()
_expected_products = _expected_products_from_environment()
_resolved_monitoring_dir = _monitoring_dir.resolve(strict=False)
_tmp_root = Path("/tmp")
if _production_monitoring and (
    _resolved_monitoring_dir == _tmp_root
    or _tmp_root in _resolved_monitoring_dir.parents
    or not _scoped_credentials
    or not _expected_products
    or bool(os.environ.get("PM_EVALS_INGEST_TOKEN"))
    or set(_scoped_credentials)
    != {(product.id, product.environment) for product in _expected_products}
):
    raise RuntimeError(
        "production monitoring requires durable non-/tmp storage, product-scoped credentials, "
        "and an expected-product registry"
    )
app = create_app(
    monitoring_data_dir=_monitoring_dir,
    monitoring_ingest_token=os.environ.get("PM_EVALS_INGEST_TOKEN"),
    monitoring_ingest_credentials=_scoped_credentials,
    monitoring_adjudication_token=os.environ.get("PM_EVALS_ADJUDICATION_TOKEN"),
    monitoring_demo_mode=os.environ.get("PM_EVALS_DEMO_MODE") == "1",
    monitoring_production=_production_monitoring,
    monitoring_expected_products=_expected_products,
    monitoring_ingest_limit_per_minute=int(
        os.environ.get("PM_EVALS_INGEST_LIMIT_PER_MINUTE", "120")
    ),
)
