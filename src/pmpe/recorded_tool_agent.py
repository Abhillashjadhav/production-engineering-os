"""One exact, offline recorded tool-agent implementation for Phase C."""

from __future__ import annotations

import copy
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from pmpe.barebones_selection import (
    RECORDED_TOOL_AGENT_FIXTURE,
    RECORDED_TOOL_AGENT_FIXTURE_DIGEST,
    RECORDED_TOOL_AGENT_RESOURCE,
    RECORDED_TOOL_AGENT_RESOURCE_DIGEST,
    RECORDED_TOOL_AGENT_SCHEMA_DIGEST,
    RECORDED_TOOL_AGENT_SCHEMAS,
    compile_phase_b_selection,
)
from pmpe.contracts.canonical import canonical_digest, canonical_json_bytes, strict_loads
from pmpe.evidence.ledger import EvidenceLedger

_MODEL = "recorded/fixture-v1"
_FIXTURE_ID = "recorded-tool-agent-happy/v1"
_DATASET_ID = "support-kb-v1"
_SYSTEM_PROMPT = (
    "Use only the admitted repository lookup and pure transform tools. Never use network, "
    "filesystem writes, subprocesses, credentials, dynamic code, or recursive agents."
)
_USER_PROMPT = "What is the refund window in the support knowledge base? Answer in one sentence."


class RecordedToolAgentError(ValueError):
    """The exact recorded execution halted before release readiness."""


class _ExecutionHalt(RecordedToolAgentError):  # noqa: N818 - internal control signal
    pass


@dataclass(frozen=True)
class AgentRunResult:
    run_id: str
    state: str
    cause: str
    output: str
    evidence_path: Path
    deployment_authority: bool = False


def _object(payload: bytes, description: str) -> dict[str, Any]:
    try:
        value = strict_loads(payload, "application/json")
    except ValueError as exc:
        raise _ExecutionHalt(f"{description}_INVALID") from exc
    if not isinstance(value, dict):
        raise _ExecutionHalt(f"{description}_INVALID")
    return value


def _schema_validators(
    schemas: Mapping[str, Any],
) -> dict[str, tuple[Draft202012Validator, Draft202012Validator]]:
    validators: dict[str, tuple[Draft202012Validator, Draft202012Validator]] = {}
    for tool in schemas["tools"]:
        validators[str(tool["tool_id"])] = (
            Draft202012Validator(tool["arguments_schema"]),
            Draft202012Validator(tool["result_schema"]),
        )
    return validators


def _validate(validator: Draft202012Validator, value: object, cause: str) -> None:
    if next(validator.iter_errors(value), None) is not None:
        raise _ExecutionHalt(cause)


def _lookup(arguments: Mapping[str, Any], resource: Mapping[str, Any]) -> dict[str, Any]:
    if arguments["dataset_id"] != _DATASET_ID:
        raise _ExecutionHalt("RESOURCE_SCOPE_DENIED")
    query = str(arguments["query"]).casefold()
    if query != "refund window":
        raise _ExecutionHalt("LOOKUP_QUERY_DENIED")
    matches = [
        copy.deepcopy(document)
        for document in resource["documents"]
        if "refund" in str(document["text"]).casefold()
    ]
    return {"matches": matches[:10]}


def _transform(arguments: Mapping[str, Any]) -> dict[str, str]:
    if arguments["operation"] != "single_sentence":
        raise _ExecutionHalt("TOOL_ARGUMENT_DENIED")
    text = " ".join(str(arguments["text"]).split())
    if text == "Customers may request a refund within 30 calendar days of purchase.":
        text = "Customers can request a refund within 30 calendar days of purchase."
    return {"text": text}


def _dispatch(
    request: Mapping[str, Any],
    resource: Mapping[str, Any],
    validators: Mapping[str, tuple[Draft202012Validator, Draft202012Validator]],
) -> dict[str, Any]:
    if set(request) != {"arguments", "call_id", "tool_id"}:
        raise _ExecutionHalt("TOOL_REQUEST_INVALID")
    tool_id = request.get("tool_id")
    if not isinstance(tool_id, str) or tool_id not in validators:
        raise _ExecutionHalt("TOOL_DENIED")
    arguments = request.get("arguments")
    _validate(validators[tool_id][0], arguments, "TOOL_ARGUMENT_INVALID")
    assert isinstance(arguments, Mapping)
    if tool_id == "repository.lookup/v1":
        result = _lookup(arguments, resource)
    elif tool_id == "pure.transform/v1":
        result = _transform(arguments)
    else:  # pragma: no cover - closed validator map makes this unreachable
        raise _ExecutionHalt("TOOL_DENIED")
    _validate(validators[tool_id][1], result, "TOOL_RESULT_INVALID")
    return result


def _halt(
    ledger: EvidenceLedger,
    *,
    subject_digest: str,
    cause: str,
) -> AgentRunResult:
    ledger.append(
        event_type="recorded_agent_halted",
        state="HALTED",
        subject_digest=subject_digest,
        payload={"cause": cause, "deployment_authority": False},
    )
    return AgentRunResult(
        run_id=ledger.run_id,
        state="HALTED",
        cause=cause,
        output="",
        evidence_path=ledger.events_path,
    )


def run_recorded_tool_agent(
    *,
    contract: Mapping[str, Any],
    approval: Mapping[str, Any],
    repository_root: Path,
    run_id: str,
    expected_approver: str,
    trusted_clock: Callable[[], datetime],
    trusted_monotonic: Callable[[], float] = time.monotonic,
    fixture_payload: bytes | None = None,
    resource_payload: bytes | None = None,
    runtime_environment: Mapping[str, str] | None = None,
) -> AgentRunResult:
    """Execute the sole admitted replay fixture without network, process, or file authority."""

    started = trusted_monotonic()
    compiled = compile_phase_b_selection(
        contract,
        approval,
        expected_approver=expected_approver,
        trusted_clock=trusted_clock,
    )
    plan = compiled.as_dict()
    if (
        plan.get("template_type") != "recorded_tool_agent"
        or plan.get("template_version") != "1.0.0"
        or plan.get("runtime_model_mode") != "recorded"
        or plan.get("fixture")
        != {"fixture_digest": RECORDED_TOOL_AGENT_FIXTURE_DIGEST, "fixture_id": _FIXTURE_ID}
    ):
        raise RecordedToolAgentError("compiled selection is not the exact Phase C subject")

    ledger = EvidenceLedger(Path(repository_root), run_id)
    subject_digest = str(plan["compiled_plan_digest"])
    fixture_bytes = (
        canonical_json_bytes(RECORDED_TOOL_AGENT_FIXTURE)
        if fixture_payload is None
        else fixture_payload
    )
    resource_bytes = (
        canonical_json_bytes(RECORDED_TOOL_AGENT_RESOURCE)
        if resource_payload is None
        else resource_payload
    )
    budgets = plan["budgets"]

    def enforce_wall_time() -> None:
        if trusted_monotonic() - started > budgets["max_wall_time_ms"] / 1000:
            raise _ExecutionHalt("WALL_TIME_BUDGET_EXCEEDED")

    try:
        if runtime_environment:
            raise _ExecutionHalt("AMBIENT_ENVIRONMENT_DENIED")
        fixture = _object(fixture_bytes, "FIXTURE")
        resource = _object(resource_bytes, "RESOURCE")
        if canonical_digest(fixture) != RECORDED_TOOL_AGENT_FIXTURE_DIGEST:
            raise _ExecutionHalt("FIXTURE_DIGEST_MISMATCH")
        if canonical_digest(resource) != RECORDED_TOOL_AGENT_RESOURCE_DIGEST:
            raise _ExecutionHalt("RESOURCE_DIGEST_MISMATCH")
        schema_snapshot = copy.deepcopy(RECORDED_TOOL_AGENT_SCHEMAS)
        schema_bytes = canonical_json_bytes(schema_snapshot)
        if canonical_digest(schema_snapshot) != RECORDED_TOOL_AGENT_SCHEMA_DIGEST:
            raise _ExecutionHalt("TOOL_SCHEMA_DIGEST_MISMATCH")
        blobs = [
            ledger.put_blob(compiled.canonical_bytes()),
            ledger.put_blob(canonical_json_bytes(fixture)),
            ledger.put_blob(canonical_json_bytes(resource)),
            ledger.put_blob(schema_bytes),
        ]
        ledger.append(
            event_type="recorded_agent_validated",
            state="VALIDATED",
            subject_digest=subject_digest,
            blob_digests=blobs,
            payload={
                "deployment_authority": False,
                "fixture_digest": RECORDED_TOOL_AGENT_FIXTURE_DIGEST,
                "resource_digest": RECORDED_TOOL_AGENT_RESOURCE_DIGEST,
                "tool_schema_digest": RECORDED_TOOL_AGENT_SCHEMA_DIGEST,
            },
        )
        enforce_wall_time()
        attempts = calls = response_bytes = 0
        seen_calls: set[str] = set()
        pending: dict[str, Any] | None = None
        output = ""
        history: list[dict[str, Any]] = [
            {"content": _SYSTEM_PROMPT, "role": "system"},
            {"content": _USER_PROMPT, "role": "user"},
        ]
        events = fixture.get("events")
        if not isinstance(events, list) or not events:
            raise _ExecutionHalt("FIXTURE_INVALID")
        validators = _schema_validators(schema_snapshot)
        for index, event in enumerate(events, start=1):
            enforce_wall_time()
            if index > budgets["max_steps"]:
                raise _ExecutionHalt("STEP_BUDGET_EXCEEDED")
            if not isinstance(event, Mapping) or event.get("sequence") != index:
                raise _ExecutionHalt("TRANSCRIPT_ORDER_MISMATCH")
            kind = event.get("kind")
            request = event.get("request")
            response = event.get("response")
            if not isinstance(request, Mapping) or not isinstance(response, Mapping):
                raise _ExecutionHalt("TRANSCRIPT_INVALID")
            if kind == "recorded_model_response":
                attempts += 1
                if attempts > budgets["max_attempts"] or pending is not None:
                    raise _ExecutionHalt("MODEL_ATTEMPT_BUDGET_EXCEEDED")
                expected_request = {
                    "messages": history,
                    "model": _MODEL,
                    "tool_schema_digest": RECORDED_TOOL_AGENT_SCHEMA_DIGEST,
                }
                if request != expected_request:
                    raise _ExecutionHalt("MODEL_REQUEST_MISMATCH")
                finish = response.get("finish_reason")
                if finish == "tool_call" and set(response) == {
                    "finish_reason",
                    "response_id",
                    "tool_call",
                }:
                    tool_call = response.get("tool_call")
                    if not isinstance(tool_call, Mapping):
                        raise _ExecutionHalt("MODEL_RESPONSE_INVALID")
                    call_id = tool_call.get("call_id")
                    if not isinstance(call_id, str) or not call_id or call_id in seen_calls:
                        raise _ExecutionHalt("TOOL_CALL_ID_REUSED")
                    seen_calls.add(call_id)
                    pending = copy.deepcopy(dict(tool_call))
                    history.append({"content": pending, "role": "assistant_tool_call"})
                elif finish == "stop" and set(response) == {
                    "finish_reason",
                    "message",
                    "response_id",
                }:
                    message = response.get("message")
                    if (
                        not isinstance(message, Mapping)
                        or set(message) != {"content", "role"}
                        or message.get("role") != "assistant"
                        or not isinstance(message.get("content"), str)
                        or index != len(events)
                    ):
                        raise _ExecutionHalt("MODEL_TERMINAL_INVALID")
                    output = str(message["content"])
                    history.append(copy.deepcopy(dict(message)))
                else:
                    raise _ExecutionHalt("MODEL_RESPONSE_INVALID")
            elif kind == "tool_result":
                calls += 1
                if calls > budgets["max_tool_calls"] or pending is None or request != pending:
                    raise _ExecutionHalt("TOOL_CALL_SEQUENCE_INVALID")
                actual = _dispatch(request, resource, validators)
                if response != actual:
                    raise _ExecutionHalt("TOOL_RESULT_MISMATCH")
                history.append(
                    {
                        "content": copy.deepcopy(actual),
                        "role": "tool",
                        "tool_call_id": pending["call_id"],
                    }
                )
                pending = None
            else:
                raise _ExecutionHalt("TRANSCRIPT_KIND_INVALID")
            response_bytes += len(canonical_json_bytes(response))
            if response_bytes > budgets["max_bytes"]:
                raise _ExecutionHalt("BYTE_BUDGET_EXCEEDED")
            event_blob = ledger.put_blob(canonical_json_bytes(event))
            ledger.append(
                event_type="recorded_agent_step",
                state="BUILDING",
                subject_digest=subject_digest,
                blob_digests=[event_blob],
                payload={"kind": kind, "sequence": index},
            )
            enforce_wall_time()
        if pending is not None or not output:
            raise _ExecutionHalt("TRANSCRIPT_NOT_TERMINAL")
        enforce_wall_time()
        output_digest = ledger.put_blob(output.encode())
        enforce_wall_time()
        release_payload = {
            "deployment_authority": False,
            "model_attempts": attempts,
            "output_digest": canonical_digest(output),
            "replay_steps": len(events),
            "tool_calls": calls,
        }
        ledger.append(
            event_type="recorded_agent_release_candidate",
            state="VERIFYING",
            subject_digest=subject_digest,
            blob_digests=[output_digest],
            payload=release_payload,
        )
        enforce_wall_time()
        ledger.append(
            event_type="recorded_agent_release_ready",
            state="RELEASE_READY",
            subject_digest=subject_digest,
            blob_digests=[output_digest],
            payload=release_payload,
        )
        return AgentRunResult(
            run_id=run_id,
            state="RELEASE_READY",
            cause="PASS",
            output=output,
            evidence_path=ledger.events_path,
        )
    except _ExecutionHalt as exc:
        return _halt(ledger, subject_digest=subject_digest, cause=str(exc))


__all__ = ["AgentRunResult", "RecordedToolAgentError", "run_recorded_tool_agent"]
