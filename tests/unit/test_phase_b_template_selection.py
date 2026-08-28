from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

import pmpe.barebones_selection as selection_module
from pmpe.barebones_selection import (
    BAREBONES_E1_CONTENT_DIGEST,
    RECORDED_TOOL_AGENT_CONTENT_DIGEST,
    RECORDED_TOOL_AGENT_FIXTURE,
    RECORDED_TOOL_AGENT_FIXTURE_DIGEST,
    RECORDED_TOOL_AGENT_RESOURCE,
    RECORDED_TOOL_AGENT_RESOURCE_DIGEST,
    TemplateSelectionError,
    compile_phase_b_selection,
    load_phase_b_contract,
    phase_b_approval_subject,
)
from pmpe.contracts.canonical import canonical_digest, canonical_json_bytes, strict_loads

NOW = datetime(2026, 8, 28, 18, 0, tzinfo=UTC)


def _capability_binding(
    capability_id: str,
    criterion_id: str,
    verifier_id: str,
) -> dict[str, object]:
    return {
        "acceptance_criterion_ids": [criterion_id],
        "capability_id": capability_id,
        "verifier_id": verifier_id,
    }


def _e1_selection() -> dict[str, object]:
    return {
        "schema_version": "phase-b-template-selection/v1",
        "template_type": "barebones_e1",
        "template_version": "1.0.0",
        "template_content_digest": BAREBONES_E1_CONTENT_DIGEST,
        "capability_vocabulary_version": "phase-b-capabilities/v1",
        "capability_ids": ["e1.health"],
        "capability_bindings": [
            _capability_binding(
                "e1.health",
                "AC-001",
                "acceptance.given_when_then/v1",
            )
        ],
        "runtime_model_mode": "recorded",
        "configuration": {"service_name": "fixture-e1"},
        "tools": [],
        "budgets": {
            "max_attempts": 3,
            "max_bytes": 1_000_000,
            "max_steps": 8,
            "max_tool_calls": 0,
            "max_wall_time_ms": 120_000,
        },
        "fixture": {
            "fixture_id": "e1-no-model-fixture/v1",
            "fixture_digest": canonical_digest({"steps": []}),
        },
    }


def _tool_agent_selection() -> dict[str, object]:
    return {
        "schema_version": "phase-b-template-selection/v1",
        "template_type": "recorded_tool_agent",
        "template_version": "1.0.0",
        "template_content_digest": RECORDED_TOOL_AGENT_CONTENT_DIGEST,
        "capability_vocabulary_version": "phase-b-capabilities/v1",
        "capability_ids": [
            "agent.recorded_model",
            "tool.pure_transform",
            "tool.repository_lookup",
        ],
        "capability_bindings": [
            _capability_binding(
                "agent.recorded_model",
                "AC-001",
                "recorded_replay.strict/v1",
            ),
            _capability_binding(
                "tool.pure_transform",
                "AC-002",
                "tool_dispatch.closed/v1",
            ),
            _capability_binding(
                "tool.repository_lookup",
                "AC-003",
                "tool_dispatch.closed/v1",
            ),
        ],
        "runtime_model_mode": "recorded",
        "configuration": {"dataset_id": "support-kb-v1"},
        "tools": [
            {
                "resource_scopes": ["fixtures/support-kb-v1.json"],
                "tool_id": "repository.lookup/v1",
            },
            {"resource_scopes": [], "tool_id": "pure.transform/v1"},
        ],
        "budgets": {
            "max_attempts": 3,
            "max_bytes": 262_144,
            "max_steps": 12,
            "max_tool_calls": 6,
            "max_wall_time_ms": 30_000,
        },
        "fixture": {
            "fixture_id": "recorded-tool-agent-happy/v1",
            "fixture_digest": RECORDED_TOOL_AGENT_FIXTURE_DIGEST,
        },
    }


def _contract(selection: dict[str, object]) -> dict[str, object]:
    criteria = {
        binding["acceptance_criterion_ids"][0]: {
            "criterion": f"Exercise {binding['capability_id']}.",
            "requirement_refs": [f"FR-{index:03d}"],
            "verification_method": str(binding["verifier_id"]),
        }
        for index, binding in enumerate(selection["capability_bindings"], start=1)
    }
    requirements = {
        f"FR-{index:03d}": {
            "acceptance_criterion_refs": [
                selection["capability_bindings"][index - 1]["acceptance_criterion_ids"][0]
            ],
            "priority": "MUST",
            "statement": f"Exercise {capability}.",
            "title": f"Exercise {capability}",
        }
        for index, capability in enumerate(selection["capability_ids"], start=1)
    }
    return {
        "acceptance_criteria": criteria,
        "approved_at": "2026-08-28T17:00:00Z",
        "approved_by": "fixture-human",
        "contract_id": f"PHASE-B-{selection['template_type']}",
        "contract_status": "APPROVED",
        "contract_version": 1,
        "functional_requirements": requirements,
        "implementation_selection": selection,
    }


def _approval(contract: dict[str, object]) -> dict[str, object]:
    receipt = {
        "approved_at": "2026-08-28T17:00:00Z",
        "approved_by": "fixture-human",
        "decision": "APPROVED",
        "expires_at": "2026-08-29T17:00:00Z",
        "schema_version": "phase-b-template-approval/v1",
        "subject": phase_b_approval_subject(contract),
    }
    return {**receipt, "receipt_digest": canonical_digest(receipt)}


def _compile(selection: dict[str, object]):  # type: ignore[no-untyped-def]
    contract = _contract(selection)
    return compile_phase_b_selection(
        contract,
        _approval(contract),
        expected_approver="fixture-human",
        trusted_clock=lambda: NOW,
    )


@pytest.mark.parametrize("selection", [_e1_selection(), _tool_agent_selection()])
def test_each_exact_pair_compiles_byte_identically_three_times(
    selection: dict[str, object],
) -> None:
    outputs = [_compile(copy.deepcopy(selection)).canonical_bytes() for _ in range(3)]

    assert outputs[0] == outputs[1] == outputs[2]
    payload = json.loads(outputs[0])
    assert payload["template_type"] == selection["template_type"]
    assert payload["template_content_digest"] == selection["template_content_digest"]
    assert payload["runtime_model_mode"] == "recorded"
    assert payload["capability_ids"] == sorted(selection["capability_ids"])
    assert len(payload["capability_evidence_subjects"]) == len(selection["capability_ids"])


def test_published_schema_accepts_both_exact_positive_fixtures() -> None:
    schema = json.loads(Path("schemas/phase_b_template_selection.schema.json").read_text())
    Draft202012Validator.check_schema(schema)

    for selection in (_e1_selection(), _tool_agent_selection()):
        assert list(Draft202012Validator(schema).iter_errors(selection)) == []
        parsed = load_phase_b_contract(canonical_json_bytes(_contract(selection)))
        assert canonical_json_bytes(parsed) == canonical_json_bytes(_contract(selection))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("template_type", "unknown", "unknown template identity"),
        ("template_version", "latest", "unknown template identity"),
        ("template_content_digest", "sha256:" + "0" * 64, "content digest"),
        ("runtime_model_mode", "live", "recorded"),
        ("capability_vocabulary_version", "latest", "capability vocabulary"),
    ],
)
def test_identity_digest_runtime_and_vocabulary_fail_closed(
    field: str,
    value: str,
    message: str,
) -> None:
    selection = _e1_selection()
    selection[field] = value

    with pytest.raises(TemplateSelectionError, match=message):
        _compile(selection)


def test_duplicate_json_identity_member_fails_before_selection() -> None:
    payload = canonical_json_bytes(_contract(_e1_selection())).decode()
    duplicate = payload.replace(
        '"template_type":"barebones_e1"',
        '"template_type":"barebones_e1","template_type":"barebones_e1"',
    )

    with pytest.raises(ValueError, match="duplicate object member"):
        load_phase_b_contract(duplicate.encode())


@pytest.mark.parametrize(
    "mutation",
    [
        lambda selection: selection["capability_ids"].append("tool.repository_lookup"),
        lambda selection: selection["capability_ids"].remove("e1.health"),
        lambda selection: selection["capability_bindings"].append(
            _capability_binding(
                "tool.repository_lookup",
                "AC-001",
                "tool_dispatch.closed/v1",
            )
        ),
        lambda selection: selection["capability_bindings"][0].update({"verifier_id": "unknown/v1"}),
        lambda selection: selection["capability_bindings"][0].update(
            {"acceptance_criterion_ids": ["AC-MISSING"]}
        ),
    ],
)
def test_unsupported_undeclared_or_unverifiable_capabilities_fail_closed(
    mutation,  # type: ignore[no-untyped-def]
) -> None:
    contract = _contract(_e1_selection())
    mutation(contract["implementation_selection"])

    with pytest.raises(TemplateSelectionError):
        compile_phase_b_selection(
            contract,
            _approval(contract),
            expected_approver="fixture-human",
            trusted_clock=lambda: NOW,
        )


@pytest.mark.parametrize(
    ("configuration", "message"),
    [
        ({"service_name": "fixture-e1", "api_token": "synthetic"}, "secret"),
        ({"service_name": "sk-abcdefghijklmnopqrstuvwxyz"}, "credential"),
        ({"service_name": {"nested": "value"}}, "configuration"),
        ({"unknown": "value"}, "configuration"),
    ],
)
def test_secret_values_and_unregistered_configuration_fail_closed(
    configuration: dict[str, object],
    message: str,
) -> None:
    selection = _e1_selection()
    selection["configuration"] = configuration

    with pytest.raises(TemplateSelectionError, match=message):
        _compile(selection)


@pytest.mark.parametrize(
    "credential",
    [
        "gh" + "p_" + "a" * 36,
        "gl" + "pat-" + "a" * 24,
        "Bearer " + "a" * 26,
        "xox" + "b-" + "1" * 24,
        "sk_" + "live_" + "a" * 24,
        "npm_" + "a" * 24,
        "hf_" + "a" * 24,
        "https://alice:supersecret@example.com/path",
        "Authorization: abcdefghijklmnop",
        "Proxy-Authorization: abcdefghijklmnop",
        "https://example.com/callback?code=abcdefghijklmnop",
        "https://example.com/callback?return_api_key=abcdefghijklmnop",
        "https://example.com/callback#access_token=abcdefghijklmnop",
        "https://hooks.slack.com/services/T000/B000/SECRET",
        "https:////hooks.slack.com/services/T000/B000/SECRET",
        "https:\\\\hooks.slack.com\\services\\T000\\B000\\SECRET",
        "//hooks.slack.com/services/T000/B000/SECRET",
        "https://api.telegram.org/bot123456:ABCDEF/getMe",
        "https://discord.com/api/webhooks/123456/abcdef",
        "https://edge.discordapp.com/api%252fwebhooks/123456/abcdef",
        "refresh_token=abcdefghijklmnop",
        "credential abcdefghijklmnop",
    ],
)
def test_all_canonical_credential_formats_fail_closed(credential: str) -> None:
    selection = _e1_selection()
    selection["configuration"] = {"service_name": credential}

    with pytest.raises(TemplateSelectionError, match="credential"):
        _compile(selection)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda selection: selection["tools"].append(
            {"resource_scopes": [], "tool_id": "repository.lookup/v1"}
        ),
        lambda selection: selection["tools"].append(
            {"resource_scopes": ["../secret"], "tool_id": "shell/v1"}
        ),
        lambda selection: (
            selection["tools"][0]["resource_scopes"].append("*") if selection["tools"] else None
        ),
    ],
)
def test_tool_identity_and_resource_scope_are_exact(
    mutation,  # type: ignore[no-untyped-def]
) -> None:
    selection = _tool_agent_selection()
    mutation(selection)

    with pytest.raises(TemplateSelectionError, match="tool"):
        _compile(selection)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_attempts", 0),
        ("max_bytes", 0),
        ("max_steps", 0),
        ("max_tool_calls", -1),
        ("max_wall_time_ms", 0),
    ],
)
def test_every_budget_is_positive_and_bounded(field: str, value: int) -> None:
    selection = _e1_selection()
    selection["budgets"][field] = value

    with pytest.raises(TemplateSelectionError, match="budget"):
        _compile(selection)


def test_recorded_tool_agent_budget_covers_every_fixture_tool_call() -> None:
    selection = _tool_agent_selection()
    selection["budgets"]["max_tool_calls"] = 1

    with pytest.raises(TemplateSelectionError, match="recorded tool calls"):
        _compile(selection)


def test_recorded_tool_agent_budget_covers_every_fixture_model_attempt() -> None:
    selection = _tool_agent_selection()
    selection["budgets"]["max_attempts"] = 2

    with pytest.raises(TemplateSelectionError, match="recorded model attempts"):
        _compile(selection)


def test_recorded_tool_agent_budget_covers_every_fixture_replay_step() -> None:
    selection = _tool_agent_selection()
    selection["budgets"]["max_steps"] = len(RECORDED_TOOL_AGENT_FIXTURE["events"]) - 1

    with pytest.raises(TemplateSelectionError, match="recorded replay steps"):
        _compile(selection)


def test_recorded_tool_agent_budget_covers_every_fixture_response_byte() -> None:
    selection = _tool_agent_selection()
    required_bytes = sum(
        len(canonical_json_bytes(event["response"]))
        for event in RECORDED_TOOL_AGENT_FIXTURE["events"]
    )
    selection["budgets"]["max_bytes"] = required_bytes - 1

    with pytest.raises(TemplateSelectionError, match="recorded response bytes"):
        _compile(selection)


def test_fixture_identity_and_digest_are_required() -> None:
    selection = _e1_selection()
    selection["fixture"]["fixture_digest"] = "sha256:" + "3" * 64

    with pytest.raises(TemplateSelectionError, match="fixture"):
        _compile(selection)


def test_recorded_tool_agent_fixture_digest_binds_complete_replay_payload() -> None:
    fixture_path = Path("src/pmpe/fixtures/recorded_tool_agent_happy_v1.json")
    fixture = strict_loads(fixture_path.read_bytes(), "application/json")

    assert fixture == RECORDED_TOOL_AGENT_FIXTURE
    assert canonical_digest(fixture) == RECORDED_TOOL_AGENT_FIXTURE_DIGEST
    mutated = copy.deepcopy(fixture)
    mutated["events"][1]["response"]["matches"][0]["text"] = "Changed replay output."
    assert canonical_digest(mutated) != RECORDED_TOOL_AGENT_FIXTURE_DIGEST


def test_recorded_tool_agent_resource_is_packaged_and_digest_bound() -> None:
    resource_path = Path("src/pmpe/fixtures/support-kb-v1.json")
    resource = strict_loads(resource_path.read_bytes(), "application/json")

    assert resource == RECORDED_TOOL_AGENT_RESOURCE
    assert canonical_digest(resource) == RECORDED_TOOL_AGENT_RESOURCE_DIGEST
    assert resource["documents"][0]["text"] == (
        "Customers may request a refund within 30 calendar days of purchase."
    )
    manifest = selection_module._RECORDED_TOOL_AGENT_MANIFEST
    assert manifest["resources"] == [
        {
            "dataset_id": "support-kb-v1",
            "resource_digest": RECORDED_TOOL_AGENT_RESOURCE_DIGEST,
            "resource_scope": "fixtures/support-kb-v1.json",
        }
    ]
    assert canonical_digest(manifest) == RECORDED_TOOL_AGENT_CONTENT_DIGEST


def test_legacy_fixture_id_and_step_count_digest_is_rejected() -> None:
    selection = _tool_agent_selection()
    selection["fixture"]["fixture_digest"] = canonical_digest(
        {"fixture_id": "recorded-tool-agent-happy/v1", "steps": 4}
    )

    with pytest.raises(TemplateSelectionError, match="fixture"):
        _compile(selection)


@pytest.mark.parametrize(
    "criterion",
    [
        None,
        {"criterion": "Exercise E1.", "requirement_refs": ["FR-001"]},
        {
            "criterion": "",
            "requirement_refs": ["FR-001"],
            "verification_method": "acceptance.given_when_then/v1",
        },
        {
            "criterion": "Exercise E1.",
            "requirement_refs": [],
            "verification_method": "acceptance.given_when_then/v1",
        },
        {
            "criterion": "Exercise E1.",
            "requirement_refs": ["FR-MISSING"],
            "verification_method": "acceptance.given_when_then/v1",
        },
        {
            "criterion": "Exercise E1.",
            "requirement_refs": ["FR-001", "FR-001"],
            "verification_method": "acceptance.given_when_then/v1",
        },
        {
            "criterion": "Exercise E1.",
            "requirement_refs": ["FR-001"],
            "verification_method": "manual.review/v1",
        },
    ],
)
def test_referenced_acceptance_criterion_must_have_complete_valid_shape(
    criterion: object,
) -> None:
    contract = _contract(_e1_selection())
    contract["acceptance_criteria"]["AC-001"] = criterion

    with pytest.raises(TemplateSelectionError, match="malformed acceptance criterion"):
        compile_phase_b_selection(
            contract,
            _approval(contract),
            expected_approver="fixture-human",
            trusted_clock=lambda: NOW,
        )


@pytest.mark.parametrize(
    "requirement",
    [
        None,
        {"statement": "Exercise E1."},
        {
            "acceptance_criterion_refs": [],
            "priority": "MUST",
            "statement": "Exercise E1.",
            "title": "Exercise E1",
        },
        {
            "acceptance_criterion_refs": ["AC-OTHER"],
            "priority": "MUST",
            "statement": "Exercise E1.",
            "title": "Exercise E1",
        },
        {
            "acceptance_criterion_refs": ["AC-001"],
            "priority": "UNRANKED",
            "statement": "Exercise E1.",
            "title": "Exercise E1",
        },
        {
            "acceptance_criterion_refs": ["AC-001"],
            "priority": "MUST",
            "statement": "",
            "title": "Exercise E1",
        },
        {
            "acceptance_criterion_refs": ["AC-001"],
            "priority": "MUST",
            "statement": "Exercise E1.",
            "title": "Exercise E1",
            "unknown": "not admitted",
        },
    ],
)
def test_referenced_functional_requirement_must_have_complete_valid_shape(
    requirement: object,
) -> None:
    contract = _contract(_e1_selection())
    contract["functional_requirements"]["FR-001"] = requirement

    with pytest.raises(TemplateSelectionError, match="malformed functional requirement"):
        compile_phase_b_selection(
            contract,
            _approval(contract),
            expected_approver="fixture-human",
            trusted_clock=lambda: NOW,
        )


def test_referenced_functional_requirement_rejects_dangling_acceptance_reference() -> None:
    contract = _contract(_e1_selection())
    contract["functional_requirements"]["FR-001"]["acceptance_criterion_refs"].append("AC-MISSING")

    with pytest.raises(TemplateSelectionError, match="malformed functional requirement"):
        compile_phase_b_selection(
            contract,
            _approval(contract),
            expected_approver="fixture-human",
            trusted_clock=lambda: NOW,
        )


@pytest.mark.parametrize(
    "secondary",
    [
        None,
        {
            "criterion": "Exercise secondary behavior.",
            "requirement_refs": ["FR-MISSING"],
            "verification_method": "manual.review/v1",
        },
    ],
)
def test_bound_requirement_validates_referenced_criterion_closure(secondary: object) -> None:
    contract = _contract(_e1_selection())
    contract["acceptance_criteria"]["AC-SECONDARY"] = secondary
    contract["functional_requirements"]["FR-001"]["acceptance_criterion_refs"].append(
        "AC-SECONDARY"
    )

    with pytest.raises(TemplateSelectionError, match="malformed acceptance criterion"):
        compile_phase_b_selection(
            contract,
            _approval(contract),
            expected_approver="fixture-human",
            trusted_clock=lambda: NOW,
        )


def test_valid_referenced_criterion_closure_is_admitted() -> None:
    contract = _contract(_e1_selection())
    contract["acceptance_criteria"]["AC-SECONDARY"] = {
        "criterion": "Exercise secondary behavior.",
        "requirement_refs": ["FR-002"],
        "verification_method": "manual.review/v1",
    }
    contract["functional_requirements"]["FR-001"]["acceptance_criterion_refs"].append(
        "AC-SECONDARY"
    )
    contract["functional_requirements"]["FR-002"] = {
        "acceptance_criterion_refs": ["AC-SECONDARY"],
        "priority": "SHOULD",
        "statement": "Exercise secondary behavior.",
        "title": "Exercise secondary behavior",
    }

    compiled = compile_phase_b_selection(
        contract,
        _approval(contract),
        expected_approver="fixture-human",
        trusted_clock=lambda: NOW,
    )

    assert compiled.as_dict()["template_type"] == "barebones_e1"


def test_long_finite_criterion_closure_is_traversed_without_recursion() -> None:
    contract = _contract(_e1_selection())
    criteria = contract["acceptance_criteria"]
    requirements = contract["functional_requirements"]
    previous_requirement = "FR-001"
    for index in range(2, 1_102):
        criterion_id = f"AC-{index:04d}"
        requirement_id = f"FR-{index:04d}"
        requirements[previous_requirement]["acceptance_criterion_refs"].append(criterion_id)
        criteria[criterion_id] = {
            "criterion": f"Exercise closure step {index}.",
            "requirement_refs": [requirement_id],
            "verification_method": "manual.review/v1",
        }
        requirements[requirement_id] = {
            "acceptance_criterion_refs": [criterion_id],
            "priority": "SHOULD",
            "statement": f"Exercise closure step {index}.",
            "title": f"Exercise closure step {index}",
        }
        previous_requirement = requirement_id

    compiled = compile_phase_b_selection(
        contract,
        _approval(contract),
        expected_approver="fixture-human",
        trusted_clock=lambda: NOW,
    )

    assert compiled.as_dict()["template_type"] == "barebones_e1"


def test_referenced_functional_requirement_rejects_missing_entity() -> None:
    contract = _contract(_e1_selection())
    contract["functional_requirements"]["FR-001"]["entity_ref"] = "ENTITY-MISSING"

    with pytest.raises(TemplateSelectionError, match="malformed functional requirement"):
        compile_phase_b_selection(
            contract,
            _approval(contract),
            expected_approver="fixture-human",
            trusted_clock=lambda: NOW,
        )


def test_referenced_functional_requirement_resolves_existing_entity() -> None:
    contract = _contract(_e1_selection())
    contract["data"] = {"entities": {"ENTITY-CUSTOMER": {"fields": {}, "name": "Customer"}}}
    contract["functional_requirements"]["FR-001"]["entity_ref"] = "ENTITY-CUSTOMER"

    compiled = compile_phase_b_selection(
        contract,
        _approval(contract),
        expected_approver="fixture-human",
        trusted_clock=lambda: NOW,
    )

    assert compiled.as_dict()["template_type"] == "barebones_e1"


@pytest.mark.parametrize(
    "entity",
    [
        None,
        {},
        {"fields": {}, "name": ""},
        {"fields": [], "name": "Customer"},
        {"fields": {"bad-field": {"required": True, "type": "string"}}, "name": "Customer"},
        {"fields": {"email": {"required": "yes", "type": "string"}}, "name": "Customer"},
        {"fields": {}, "name": "Customer", "unknown": True},
    ],
)
def test_referenced_functional_requirement_rejects_malformed_entity_record(
    entity: object,
) -> None:
    contract = _contract(_e1_selection())
    contract["data"] = {"entities": {"ENTITY-CUSTOMER": entity}}
    contract["functional_requirements"]["FR-001"]["entity_ref"] = "ENTITY-CUSTOMER"

    with pytest.raises(TemplateSelectionError, match="malformed entity"):
        compile_phase_b_selection(
            contract,
            _approval(contract),
            expected_approver="fixture-human",
            trusted_clock=lambda: NOW,
        )


def test_capability_binding_rejects_noncanonical_acceptance_identifier() -> None:
    contract = _contract(_e1_selection())
    criterion = contract["acceptance_criteria"].pop("AC-001")
    contract["acceptance_criteria"]["ZZZ"] = criterion
    contract["functional_requirements"]["FR-001"]["acceptance_criterion_refs"] = ["ZZZ"]
    contract["implementation_selection"]["capability_bindings"][0]["acceptance_criterion_ids"] = [
        "ZZZ"
    ]

    with pytest.raises(TemplateSelectionError, match="unavailable acceptance criterion"):
        compile_phase_b_selection(
            contract,
            _approval(contract),
            expected_approver="fixture-human",
            trusted_clock=lambda: NOW,
        )


def test_unknown_selection_field_cannot_be_ignored() -> None:
    selection = _e1_selection()
    selection["deployment_provider"] = "aws"

    with pytest.raises(TemplateSelectionError, match="unknown field"):
        _compile(selection)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda contract, approval: contract["implementation_selection"]["configuration"].update(
            {"service_name": "mutated-e1"}
        ),
        lambda contract, approval: contract["implementation_selection"]["budgets"].update(
            {"max_steps": 7}
        ),
        lambda contract, approval: approval["subject"].update({"template_version": "2.0.0"}),
        lambda contract, approval: approval.update({"expires_at": "2026-08-28T17:59:59Z"}),
    ],
)
def test_approval_subject_mutation_or_expiry_fails_closed(
    mutation,  # type: ignore[no-untyped-def]
) -> None:
    contract = _contract(_e1_selection())
    approval = _approval(contract)
    mutation(contract, approval)

    with pytest.raises(TemplateSelectionError, match="approval"):
        compile_phase_b_selection(
            contract,
            approval,
            expected_approver="fixture-human",
            trusted_clock=lambda: NOW,
        )


def test_wrong_approver_fails_closed() -> None:
    contract = _contract(_e1_selection())

    with pytest.raises(TemplateSelectionError, match="approver"):
        compile_phase_b_selection(
            contract,
            _approval(contract),
            expected_approver="another-human",
            trusted_clock=lambda: NOW,
        )
