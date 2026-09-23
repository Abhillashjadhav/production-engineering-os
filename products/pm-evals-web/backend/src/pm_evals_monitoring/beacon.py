"""Optional lifecycle metadata, without reading uploads, headers, or credentials."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send


POST_WORKFLOWS = {
    "/api/compare": "pm-evals.compare",
    "/api/report": "pm-evals.report",
    "/api/monitoring/evaluate": "pm-evals.evaluate",
    "/api/monitoring/runs": "pm-evals.ingest-run",
    "/api/monitoring/receipts": "pm-evals.ingest-receipt",
    "/api/monitoring/adjudications": "pm-evals.adjudicate",
    "/api/monitoring/detection-reviews": "pm-evals.detection-review",
}


def start_recording(workflow: str) -> Any:
    try:
        recorder = import_module("workflow_beacon").Run(
            workflow, project_root=Path.cwd(), run_id=str(uuid4())
        )
        # Do not enter a capture context: HTTP requests must not share or mutate
        # process environment IDs while they run concurrently.
        recorder.event("operation.started", status="started")
        return recorder
    except Exception:
        return None


def finish_recording(
    recorder: Any, *, code: int | None = None, error: BaseException | None = None
) -> None:
    if recorder is None:
        return
    try:
        failed = error is not None or (code is not None and code != 0)
        metadata: dict[str, object] = {}
        if code is not None:
            metadata["return_code"] = code
        if error is not None:
            metadata["error_type"] = type(error).__name__
        recorder.event(
            "operation.ended",
            status="failed" if failed else "completed",
            metadata=metadata,
        )
    except Exception:
        pass


class BeaconWorkflowMiddleware:
    """Observe selected POST operations; preserve response bytes and auth logic."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        workflow = POST_WORKFLOWS.get(scope.get("path", ""))
        if scope["type"] != "http" or scope.get("method") != "POST" or workflow is None:
            await self.app(scope, receive, send)
            return
        recorder = start_recording(workflow)
        response_status = 500
        error: BaseException | None = None

        async def observe_send(message: Message) -> None:
            nonlocal response_status
            if message["type"] == "http.response.start":
                response_status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, observe_send)
        except BaseException as exc:
            error = exc
            raise
        finally:
            # HTTP completion is transport status, not an evaluation PASS.
            finish_recording(
                recorder,
                code=0 if 200 <= response_status < 400 else response_status,
                error=error,
            )
