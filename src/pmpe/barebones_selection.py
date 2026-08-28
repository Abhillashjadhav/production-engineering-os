"""Exact Phase B implementation selection without a template registry or runtime."""

from __future__ import annotations

import copy
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, ValidationError

from pmpe.contracts.canonical import canonical_digest, canonical_json_bytes, strict_loads

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SAFE_SCOPE = re.compile(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\Z")
_CREDENTIAL = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{20,}"
)
_SECRET_NAME = re.compile(r"api_?key|credential|password|secret|token", re.IGNORECASE)

_SELECTION_FIELDS = {
    "budgets",
    "capability_bindings",
    "capability_ids",
    "capability_vocabulary_version",
    "configuration",
    "fixture",
    "runtime_model_mode",
    "schema_version",
    "template_content_digest",
    "template_type",
    "template_version",
    "tools",
}
_APPROVAL_FIELDS = {
    "approved_at",
    "approved_by",
    "decision",
    "expires_at",
    "receipt_digest",
    "schema_version",
    "subject",
}


class TemplateSelectionError(ValueError):
    """The Phase B contract cannot be selected without guessing or weakening policy."""


@dataclass(frozen=True)
class CompiledTemplateSelection:
    """Canonical compiler output for one exact implementation selection."""

    compiled_plan_digest: str
    payload: bytes

    def canonical_bytes(self) -> bytes:
        return bytes(self.payload)

    def as_dict(self) -> dict[str, Any]:
        import json

        value = json.loads(self.payload)
        if not isinstance(value, dict):  # pragma: no cover - constructor is private to this module
            raise TemplateSelectionError("compiled selection payload is malformed")
        return value


def _e1_content_manifest() -> dict[str, Any]:
    from pmpe.barebones import default_template

    template = default_template()
    return {
        "actions": dict(template.actions),
        "barebones_template_version": template.version,
        "context": dict(template.context),
        "files": dict(template.files),
        "measures": dict(template.measures),
        "proofs": {
            test_id: {
                "command": list(proof.command),
                "node_id": proof.node_id,
                "path": proof.path,
            }
            for test_id, proof in sorted(template.proofs.items())
        },
        "template_type": "barebones_e1",
        "template_version": "1.0.0",
    }


_RECORDED_TOOL_AGENT_MANIFEST: dict[str, Any] = {
    "candidate_boundary": {
        "arbitrary_filesystem": False,
        "dynamic_code": False,
        "network": False,
        "recursive_agents": False,
        "subprocess": False,
        "writes": False,
    },
    "model_boundary": {
        "credential_access": False,
        "live_fallback": False,
        "mode": "recorded",
        "ordered_replay": True,
    },
    "template_type": "recorded_tool_agent",
    "template_version": "1.0.0",
    "tools": [
        {
            "effect": "pure",
            "resource_scopes": [],
            "tool_id": "pure.transform/v1",
        },
        {
            "effect": "read_only",
            "resource_scopes": ["fixtures/support-kb-v1.json"],
            "tool_id": "repository.lookup/v1",
        },
    ],
}

BAREBONES_E1_CONTENT_DIGEST = canonical_digest(_e1_content_manifest())
RECORDED_TOOL_AGENT_CONTENT_DIGEST = canonical_digest(_RECORDED_TOOL_AGENT_MANIFEST)

_E1_FIXTURE_ID = "e1-no-model-fixture/v1"
_E1_FIXTURE_DIGEST = canonical_digest({"steps": []})
_TOOL_FIXTURE_ID = "recorded-tool-agent-happy/v1"


def _load_recorded_tool_agent_fixture() -> dict[str, Any]:
    fixture_path = Path(__file__).parent / "fixtures" / "recorded_tool_agent_happy_v1.json"
    fixture = strict_loads(fixture_path.read_bytes(), "application/json")
    if not isinstance(fixture, Mapping) or set(fixture) != {
        "events",
        "fixture_id",
        "schema_version",
    }:
        raise RuntimeError("recorded tool-agent fixture has an unexpected shape")
    if (
        fixture.get("fixture_id") != _TOOL_FIXTURE_ID
        or fixture.get("schema_version") != "recorded-tool-agent-fixture/v1"
    ):
        raise RuntimeError("recorded tool-agent fixture identity is not admitted")
    events = fixture.get("events")
    if not isinstance(events, list) or not events:
        raise RuntimeError("recorded tool-agent fixture must contain replay events")
    for expected_sequence, event in enumerate(events, start=1):
        if not isinstance(event, Mapping) or set(event) != {
            "kind",
            "request",
            "response",
            "sequence",
        }:
            raise RuntimeError("recorded tool-agent event has an unexpected shape")
        if event.get("sequence") != expected_sequence or event.get("kind") not in {
            "recorded_model_response",
            "tool_result",
        }:
            raise RuntimeError("recorded tool-agent event order or kind is invalid")
        if not isinstance(event.get("request"), Mapping) or not isinstance(
            event.get("response"), Mapping
        ):
            raise RuntimeError("recorded tool-agent event payload is malformed")
    canonical_json_bytes(fixture)
    return copy.deepcopy(dict(fixture))


RECORDED_TOOL_AGENT_FIXTURE = _load_recorded_tool_agent_fixture()
RECORDED_TOOL_AGENT_FIXTURE_DIGEST = canonical_digest(RECORDED_TOOL_AGENT_FIXTURE)
_TOOL_FIXTURE_DIGEST = RECORDED_TOOL_AGENT_FIXTURE_DIGEST


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _selection_schema() -> Draft202012Validator:
    import json

    schema_path = Path(__file__).parent / "schemas" / "phase_b_template_selection.schema.json"
    schema = json.loads(schema_path.read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _schema_error(error: ValidationError) -> TemplateSelectionError:
    path = tuple(str(item) for item in error.absolute_path)
    root = path[0] if path else ""
    if str(error.validator) == "additionalProperties":
        return TemplateSelectionError("implementation selection contains an unknown field")
    if root == "budgets":
        return TemplateSelectionError("execution budget is malformed or outside its bound")
    if root == "configuration":
        return TemplateSelectionError("configuration is malformed or contains a secret name")
    if root == "fixture":
        return TemplateSelectionError("fixture identity is malformed")
    if root == "tools":
        return TemplateSelectionError("tool identity or resource scope is malformed")
    if root == "runtime_model_mode":
        return TemplateSelectionError("runtime model mode must be recorded")
    if root == "capability_vocabulary_version":
        return TemplateSelectionError("capability vocabulary version is not admitted")
    return TemplateSelectionError(f"implementation selection schema rejected {root or 'value'}")


def _selection_object(contract: Mapping[str, Any]) -> dict[str, Any]:
    raw = contract.get("implementation_selection")
    if not isinstance(raw, Mapping):
        raise TemplateSelectionError("implementation_selection is required")
    selection = copy.deepcopy(dict(raw))
    if set(selection) != _SELECTION_FIELDS:
        raise TemplateSelectionError("implementation selection contains an unknown field")
    return selection


def _identity(selection: Mapping[str, Any]) -> str:
    template_type = selection.get("template_type")
    template_version = selection.get("template_version")
    if template_type == "barebones_e1" and template_version == "1.0.0":
        return "e1"
    if template_type == "recorded_tool_agent" and template_version == "1.0.0":
        return "tool-agent"
    raise TemplateSelectionError("unknown template identity; aliases and fallback are forbidden")


def _validate_shape(selection: Mapping[str, Any]) -> None:
    errors = sorted(
        _selection_schema().iter_errors(selection),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    )
    if errors:
        raise _schema_error(errors[0])


def load_phase_b_contract(payload: bytes) -> dict[str, Any]:
    """Parse duplicate-aware JSON and validate the public Phase B extension schema."""

    contract = strict_loads(payload, "application/json")
    selection = _selection_object(contract)
    _validate_shape(selection)
    return contract


def phase_b_approval_subject(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Return the complete immutable subject a human selection approval must bind."""

    selection = _selection_object(contract)
    return {
        "budgets_digest": canonical_digest(selection.get("budgets")),
        "capability_ids": copy.deepcopy(selection.get("capability_ids")),
        "capability_vocabulary_version": selection.get("capability_vocabulary_version"),
        "configuration_digest": canonical_digest(selection.get("configuration")),
        "contract_digest": canonical_digest(contract),
        "fixture": copy.deepcopy(selection.get("fixture")),
        "runtime_model_mode": selection.get("runtime_model_mode"),
        "selection_digest": canonical_digest(selection),
        "selection_schema_version": selection.get("schema_version"),
        "template_content_digest": selection.get("template_content_digest"),
        "template_type": selection.get("template_type"),
        "template_version": selection.get("template_version"),
        "tools_digest": canonical_digest(selection.get("tools")),
    }


def _timestamp(value: object, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise TemplateSelectionError(f"approval {field} is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TemplateSelectionError(f"approval {field} is malformed") from exc
    if parsed.tzinfo is None:
        raise TemplateSelectionError(f"approval {field} must be timezone-aware")
    return parsed


def _verify_approval(
    contract: Mapping[str, Any],
    approval: Mapping[str, Any],
    *,
    expected_approver: str,
    now: datetime,
) -> str:
    if set(approval) != _APPROVAL_FIELDS:
        raise TemplateSelectionError("approval receipt has an unexpected shape")
    claimed_digest = approval.get("receipt_digest")
    unsigned = dict(approval)
    unsigned.pop("receipt_digest", None)
    if (
        not isinstance(claimed_digest, str)
        or not _DIGEST.fullmatch(claimed_digest)
        or canonical_digest(unsigned) != claimed_digest
    ):
        raise TemplateSelectionError("approval receipt digest does not authenticate its content")
    approver = expected_approver.strip()
    if (
        not approver
        or approval.get("approved_by") != approver
        or contract.get("approved_by") != approver
    ):
        raise TemplateSelectionError("approval is not from the expected approver")
    if (
        approval.get("schema_version") != "phase-b-template-approval/v1"
        or approval.get("decision") != "APPROVED"
        or contract.get("contract_status") != "APPROVED"
        or approval.get("subject") != phase_b_approval_subject(contract)
    ):
        raise TemplateSelectionError("approval is not bound to the exact selection subject")
    approved_at = _timestamp(approval.get("approved_at"), field="approved_at")
    expires_at = _timestamp(approval.get("expires_at"), field="expires_at")
    if approval.get("approved_at") != contract.get("approved_at"):
        raise TemplateSelectionError("approval timestamp differs from the approved contract")
    if approved_at > now or expires_at <= now or expires_at <= approved_at:
        raise TemplateSelectionError("approval is not currently valid")
    return claimed_digest


def _expected_content_digest(identity: str) -> str:
    if identity == "e1":
        return BAREBONES_E1_CONTENT_DIGEST
    return RECORDED_TOOL_AGENT_CONTENT_DIGEST


def _expected_capabilities(identity: str) -> tuple[str, ...]:
    if identity == "e1":
        return ("e1.health",)
    return (
        "agent.recorded_model",
        "tool.pure_transform",
        "tool.repository_lookup",
    )


def _expected_verifier(identity: str, capability: str) -> str:
    if identity == "e1" and capability == "e1.health":
        return "acceptance.given_when_then/v1"
    if identity == "tool-agent" and capability == "agent.recorded_model":
        return "recorded_replay.strict/v1"
    if identity == "tool-agent" and capability in {
        "tool.pure_transform",
        "tool.repository_lookup",
    }:
        return "tool_dispatch.closed/v1"
    raise TemplateSelectionError("capability has no admitted automated verifier")


def _validate_configuration(identity: str, raw: object) -> dict[str, str | int | bool]:
    if not isinstance(raw, Mapping):
        raise TemplateSelectionError("configuration must be a flat named object")
    configuration = dict(raw)
    expected_keys = {"service_name"} if identity == "e1" else {"dataset_id"}
    if set(configuration) != expected_keys:
        raise TemplateSelectionError("configuration contains an unregistered name")
    for name, value in configuration.items():
        if _SECRET_NAME.search(str(name)):
            raise TemplateSelectionError("configuration contains a secret name")
        if not isinstance(value, (str, int, bool)) or isinstance(value, (dict, list)):
            raise TemplateSelectionError("configuration values must be flat JSON scalars")
        if isinstance(value, str) and _CREDENTIAL.search(value):
            raise TemplateSelectionError("configuration contains a credential-shaped value")
    if identity == "tool-agent" and configuration["dataset_id"] != "support-kb-v1":
        raise TemplateSelectionError("configuration dataset is not bound to the tool scope")
    return configuration


def _validate_tools(identity: str, raw: object) -> list[dict[str, Any]]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise TemplateSelectionError("tools must be an exact list")
    tools: list[dict[str, Any]] = []
    identities: set[str] = set()
    for item in raw:
        if not isinstance(item, Mapping) or set(item) != {"resource_scopes", "tool_id"}:
            raise TemplateSelectionError("tool record has an unexpected shape")
        tool_id = item.get("tool_id")
        scopes = item.get("resource_scopes")
        if not isinstance(tool_id, str) or tool_id in identities:
            raise TemplateSelectionError("tool identity is missing or duplicated")
        if not isinstance(scopes, list) or not all(isinstance(scope, str) for scope in scopes):
            raise TemplateSelectionError("tool resource scopes are malformed")
        if len(scopes) != len(set(scopes)) or any(
            not _SAFE_SCOPE.fullmatch(scope) or "*" in scope for scope in scopes
        ):
            raise TemplateSelectionError("tool resource scope is unsafe or duplicated")
        identities.add(tool_id)
        tools.append({"resource_scopes": sorted(scopes), "tool_id": tool_id})
    normalized = sorted(tools, key=lambda item: str(item["tool_id"]))
    expected = (
        []
        if identity == "e1"
        else [
            {"resource_scopes": [], "tool_id": "pure.transform/v1"},
            {
                "resource_scopes": ["fixtures/support-kb-v1.json"],
                "tool_id": "repository.lookup/v1",
            },
        ]
    )
    if normalized != expected:
        raise TemplateSelectionError("tool identity or resource scope is not admitted")
    return normalized


def _validate_budgets(identity: str, raw: object) -> dict[str, int]:
    if not isinstance(raw, Mapping):
        raise TemplateSelectionError("execution budget is required")
    expected = {
        "max_attempts",
        "max_bytes",
        "max_steps",
        "max_tool_calls",
        "max_wall_time_ms",
    }
    if set(raw) != expected or any(type(raw[field]) is not int for field in expected):
        raise TemplateSelectionError("execution budget has an unexpected shape")
    budgets = {field: int(raw[field]) for field in sorted(expected)}
    if (
        not 1 <= budgets["max_attempts"] <= 8
        or not 1 <= budgets["max_bytes"] <= 1_000_000
        or not 1 <= budgets["max_steps"] <= 64
        or not 0 <= budgets["max_tool_calls"] <= 16
        or not 1 <= budgets["max_wall_time_ms"] <= 120_000
    ):
        raise TemplateSelectionError("execution budget is outside its bound")
    if identity == "e1" and budgets["max_tool_calls"] != 0:
        raise TemplateSelectionError("E1 execution budget cannot authorize tool calls")
    if identity == "tool-agent" and budgets["max_tool_calls"] == 0:
        raise TemplateSelectionError("tool-agent execution budget must bound tool calls")
    return budgets


def _validate_fixture(identity: str, raw: object) -> dict[str, str]:
    if not isinstance(raw, Mapping) or set(raw) != {"fixture_digest", "fixture_id"}:
        raise TemplateSelectionError("fixture identity is malformed")
    fixture_id = raw.get("fixture_id")
    fixture_digest = raw.get("fixture_digest")
    expected = (
        (_E1_FIXTURE_ID, _E1_FIXTURE_DIGEST)
        if identity == "e1"
        else (_TOOL_FIXTURE_ID, _TOOL_FIXTURE_DIGEST)
    )
    if (fixture_id, fixture_digest) != expected:
        raise TemplateSelectionError("fixture identity or digest is not admitted")
    return {"fixture_digest": str(fixture_digest), "fixture_id": str(fixture_id)}


def _validate_capabilities(
    identity: str,
    selection: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> tuple[tuple[str, ...], list[dict[str, Any]]]:
    raw_capabilities = selection.get("capability_ids")
    if not isinstance(raw_capabilities, list) or not all(
        isinstance(item, str) for item in raw_capabilities
    ):
        raise TemplateSelectionError("capability IDs are malformed")
    capabilities = tuple(sorted(raw_capabilities))
    if capabilities != _expected_capabilities(identity):
        raise TemplateSelectionError("capability set is unsupported, undeclared, or incomplete")
    raw_bindings = selection.get("capability_bindings")
    if not isinstance(raw_bindings, list):
        raise TemplateSelectionError("capability bindings are required")
    criteria = contract.get("acceptance_criteria")
    if not isinstance(criteria, Mapping):
        raise TemplateSelectionError("capability bindings require acceptance criteria")
    requirements = contract.get("functional_requirements")
    if not isinstance(requirements, Mapping):
        raise TemplateSelectionError("acceptance criteria require functional requirements")
    bindings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_bindings:
        if not isinstance(item, Mapping) or set(item) != {
            "acceptance_criterion_ids",
            "capability_id",
            "verifier_id",
        }:
            raise TemplateSelectionError("capability binding has an unexpected shape")
        capability = item.get("capability_id")
        verifier = item.get("verifier_id")
        criterion_ids = item.get("acceptance_criterion_ids")
        if not isinstance(capability, str) or capability in seen or capability not in capabilities:
            raise TemplateSelectionError("capability binding is duplicated or undeclared")
        if verifier != _expected_verifier(identity, capability):
            raise TemplateSelectionError("capability has no admitted automated verifier")
        if (
            not isinstance(criterion_ids, list)
            or not criterion_ids
            or not all(isinstance(item, str) and item in criteria for item in criterion_ids)
            or len(criterion_ids) != len(set(criterion_ids))
        ):
            raise TemplateSelectionError(
                "capability references an unavailable acceptance criterion"
            )
        for criterion_id in criterion_ids:
            criterion = criteria[criterion_id]
            if not isinstance(criterion, Mapping) or set(criterion) != {
                "criterion",
                "requirement_refs",
                "verification_method",
            }:
                raise TemplateSelectionError(
                    "capability references a malformed acceptance criterion"
                )
            requirement_refs = criterion.get("requirement_refs")
            if (
                not isinstance(criterion.get("criterion"), str)
                or not str(criterion["criterion"]).strip()
                or not isinstance(criterion.get("verification_method"), str)
                or not str(criterion["verification_method"]).strip()
                or not isinstance(requirement_refs, list)
                or not requirement_refs
                or not all(
                    isinstance(reference, str) and reference in requirements
                    for reference in requirement_refs
                )
                or len(requirement_refs) != len(set(requirement_refs))
            ):
                raise TemplateSelectionError(
                    "capability references a malformed acceptance criterion"
                )
        seen.add(capability)
        bindings.append(
            {
                "acceptance_criterion_ids": sorted(criterion_ids),
                "capability_id": capability,
                "verifier_id": verifier,
            }
        )
    if seen != set(capabilities):
        raise TemplateSelectionError("a declared capability has no verifier binding")
    return capabilities, sorted(bindings, key=lambda item: str(item["capability_id"]))


def compile_phase_b_selection(
    contract: Mapping[str, Any],
    approval: Mapping[str, Any],
    *,
    expected_approver: str,
    trusted_clock: Callable[[], datetime] = _utc_now,
) -> CompiledTemplateSelection:
    """Compile one approved exact selection before any provider or tool execution."""

    try:
        canonical_json_bytes(contract)
        canonical_json_bytes(approval)
    except (TypeError, ValueError) as exc:
        raise TemplateSelectionError("contract or approval is outside canonical JSON") from exc
    selection = _selection_object(contract)
    identity = _identity(selection)
    _validate_shape(selection)
    if selection["capability_vocabulary_version"] != "phase-b-capabilities/v1":
        raise TemplateSelectionError("capability vocabulary version is not admitted")
    if selection["runtime_model_mode"] != "recorded":
        raise TemplateSelectionError("runtime model mode must be recorded")
    expected_content_digest = _expected_content_digest(identity)
    if selection["template_content_digest"] != expected_content_digest:
        raise TemplateSelectionError("template content digest does not match exact implementation")
    now = trusted_clock()
    if now.tzinfo is None:
        raise TemplateSelectionError("approval verification clock must be timezone-aware")
    receipt_digest = _verify_approval(
        contract,
        approval,
        expected_approver=expected_approver,
        now=now,
    )
    configuration = _validate_configuration(identity, selection["configuration"])
    tools = _validate_tools(identity, selection["tools"])
    budgets = _validate_budgets(identity, selection["budgets"])
    fixture = _validate_fixture(identity, selection["fixture"])
    capabilities, bindings = _validate_capabilities(identity, selection, contract)
    contract_digest = canonical_digest(contract)
    selection_digest = canonical_digest(selection)
    capability_subjects = []
    for binding in bindings:
        subject = {
            "acceptance_criterion_ids": binding["acceptance_criterion_ids"],
            "capability_id": binding["capability_id"],
            "contract_digest": contract_digest,
            "fixture_digest": fixture["fixture_digest"],
            "selection_digest": selection_digest,
            "template_content_digest": expected_content_digest,
            "verifier_id": binding["verifier_id"],
        }
        capability_subjects.append({**subject, "subject_digest": canonical_digest(subject)})
    shell = {
        "approval_receipt_digest": receipt_digest,
        "budgets": budgets,
        "capability_evidence_subjects": capability_subjects,
        "capability_ids": list(capabilities),
        "capability_vocabulary_version": "phase-b-capabilities/v1",
        "configuration": configuration,
        "contract_digest": contract_digest,
        "fixture": fixture,
        "runtime_model_mode": "recorded",
        "schema_version": "phase-b-compiled-selection/v1",
        "selection_digest": selection_digest,
        "template_content_digest": expected_content_digest,
        "template_type": selection["template_type"],
        "template_version": selection["template_version"],
        "tools": tools,
        "verifier_ids": sorted({str(item["verifier_id"]) for item in bindings}),
    }
    plan_digest = canonical_digest(shell)
    payload = canonical_json_bytes({**shell, "compiled_plan_digest": plan_digest})
    return CompiledTemplateSelection(plan_digest, payload)


__all__ = [
    "BAREBONES_E1_CONTENT_DIGEST",
    "RECORDED_TOOL_AGENT_CONTENT_DIGEST",
    "RECORDED_TOOL_AGENT_FIXTURE",
    "RECORDED_TOOL_AGENT_FIXTURE_DIGEST",
    "CompiledTemplateSelection",
    "TemplateSelectionError",
    "compile_phase_b_selection",
    "load_phase_b_contract",
    "phase_b_approval_subject",
]
