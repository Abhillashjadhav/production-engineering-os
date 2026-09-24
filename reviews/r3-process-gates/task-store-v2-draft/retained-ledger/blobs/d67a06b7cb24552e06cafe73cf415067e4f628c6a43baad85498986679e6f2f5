"""Admission and semantic validation for personal workflow requests."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from pmpe.config import packaged_schema_dir
from pmpe.contracts.canonical import CanonicalInputError, canonical_digest, strict_loads
from pmpe.personal.models import EvidenceRecord


class PersonalInputError(ValueError):
    """Raised when a workflow request cannot be admitted without inventing truth."""


_ACTIVITY_METRICS = (
    "number of prompts",
    "prompts generated",
    "number of tasks",
    "tasks created",
    "number of logins",
    "daily active users",
)


def _validator() -> Draft202012Validator:
    schema_path = packaged_schema_dir() / "personal_workflow_request.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def _path(error: Any) -> str:
    return "/" + "/".join(str(item) for item in error.absolute_path)


def _referenced_source_ids(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"evidence_source_ids", "source_ids"} and isinstance(child, list):
                yield from (str(item) for item in child)
            else:
                yield from _referenced_source_ids(child)
    elif isinstance(value, list):
        for child in value:
            yield from _referenced_source_ids(child)


def _require_unique(items: list[dict[str, Any]], key: str, label: str) -> None:
    values = [str(item[key]) for item in items]
    if len(values) != len(set(values)):
        raise PersonalInputError(f"{label} contains a duplicate {key}")


def _parse_timestamp(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PersonalInputError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise PersonalInputError(f"{label} must include an explicit timezone")
    return parsed


def validate_personal_context(context: dict[str, Any]) -> tuple[EvidenceRecord, ...]:
    errors = sorted(_validator().iter_errors(context), key=lambda item: list(item.absolute_path))
    if errors:
        first = errors[0]
        raise PersonalInputError(
            f"workflow request violates schema at {_path(first)}: {first.message}"
        )

    selected = tuple(str(item) for item in context["workflow_ids"])
    inputs = context["workflow_inputs"]
    if set(inputs) != set(selected):
        raise PersonalInputError("workflow_inputs must contain exactly the selected workflow_ids")

    sources = context["evidence_sources"]
    _require_unique(sources, "source_id", "evidence_sources")
    source_ids = {str(item["source_id"]) for item in sources}
    evidence: list[EvidenceRecord] = []
    for source in sources:
        actual = canonical_digest(source["content"])
        if source["content_digest"] != actual:
            raise PersonalInputError(
                f"evidence source {source['source_id']} content_digest does not match content"
            )
        evidence.append(
            EvidenceRecord(
                source_id=str(source["source_id"]),
                kind=str(source["kind"]),
                title=str(source["title"]),
                uri=str(source["uri"]),
                observed_at=str(source["observed_at"]),
                content_digest=actual,
            )
        )

    referenced = set(_referenced_source_ids(inputs))
    unknown = sorted(referenced - source_ids)
    if unknown:
        raise PersonalInputError(f"workflow input references unknown evidence source {unknown[0]}")
    for workflow_id, workflow_input in inputs.items():
        admitted = set(workflow_input["evidence_source_ids"])
        outside_packet = sorted(set(_referenced_source_ids(workflow_input)) - admitted)
        if outside_packet:
            raise PersonalInputError(
                f"workflow {workflow_id} references evidence outside its task packet: "
                f"{outside_packet[0]}"
            )

    metric = str(context["success"]["north_star"]).lower()
    if any(term in metric for term in _ACTIVITY_METRICS):
        raise PersonalInputError("north_star must describe an outcome, not an activity")

    if "weekly-pm-command-centre" in inputs:
        command = inputs["weekly-pm-command-centre"]
        for event in command["calendar_events"]:
            start = _parse_timestamp(str(event["start"]), f"event {event['event_id']} start")
            end = _parse_timestamp(str(event["end"]), f"event {event['event_id']} end")
            if end <= start:
                raise PersonalInputError(f"event {event['event_id']} must end after it starts")
        _require_unique(command["calendar_events"], "event_id", "calendar_events")
        _require_unique(command["commitments"], "commitment_id", "commitments")
        _require_unique(command["messages"], "message_id", "messages")

    if "meeting-to-decision" in inputs:
        meeting = inputs["meeting-to-decision"]
        _parse_timestamp(str(meeting["scheduled_at"]), "meeting scheduled_at")
        _require_unique(meeting["action_items"], "action_id", "action_items")

    if "evidence-to-roadmap-to-release" in inputs:
        roadmap = inputs["evidence-to-roadmap-to-release"]
        _require_unique(roadmap["claims"], "claim_id", "claims")
        _require_unique(roadmap["options"], "option_id", "options")
        option_ids = {str(item["option_id"]) for item in roadmap["options"]}
        if roadmap["approved_option_id"] not in option_ids:
            raise PersonalInputError("approved_option_id must identify an explicit supplied option")
        _require_unique(roadmap["release_checks"], "check_id", "release_checks")

    if "goal-to-verified-release" in inputs:
        _require_unique(
            inputs["goal-to-verified-release"]["acceptance_checks"],
            "check_id",
            "acceptance_checks",
        )
    if "ai-eval-release-gate" in inputs:
        _require_unique(inputs["ai-eval-release-gate"]["golden_cases"], "case_id", "golden_cases")
    if "issue-to-draft-pr" in inputs:
        _require_unique(inputs["issue-to-draft-pr"]["checks"], "check_id", "checks")

    return tuple(sorted(evidence, key=lambda item: item.source_id))


def load_personal_request(path: Path) -> tuple[dict[str, Any], tuple[EvidenceRecord, ...]]:
    try:
        payload = strict_loads(Path(path).read_bytes(), "application/json")
    except (OSError, CanonicalInputError) as exc:
        raise PersonalInputError("personal workflow request is unreadable or malformed") from exc
    return payload, validate_personal_context(payload)
