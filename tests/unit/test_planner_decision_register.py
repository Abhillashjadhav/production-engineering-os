"""The AI task planner's owner-decision register keeps open choices explicit.

Product authority (owner, 2026-09-25): no requirement may be implemented on an
unanswered decision, and no decision may be recorded as answered without its source.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REGISTER = Path(__file__).resolve().parents[2] / "docs/ai-task-planner/decision-register.json"
STATUSES = {"DECIDED", "PARTIALLY_DECIDED", "OPEN"}


def register() -> dict[str, Any]:
    value = json.loads(REGISTER.read_text())
    assert isinstance(value, dict)
    return value


def test_every_decision_has_status_question_and_answer_source() -> None:
    decisions = register()["decisions"]
    assert decisions, "register must not be empty"
    for decision_id, decision in decisions.items():
        assert decision["status"] in STATUSES, decision_id
        assert decision["question"].strip(), decision_id
        if decision["status"] == "OPEN":
            assert decision["answer"] is None, decision_id
        else:
            assert decision["answer"].strip(), decision_id
            assert decision["source"].strip(), decision_id
        if decision["status"] != "DECIDED":
            assert decision["open_parts"], decision_id


def test_requirements_reference_known_decisions_and_block_on_open_parts() -> None:
    value = register()
    decisions = value["decisions"]
    for requirement_id, requirement in value["requirements"].items():
        refs = requirement["decision_refs"]
        assert refs and set(refs) <= set(decisions), requirement_id
        blocking = sorted(
            ref for ref in requirement["blocked_by"] if decisions[ref]["status"] != "DECIDED"
        )
        assert set(requirement["blocked_by"]) <= set(decisions), requirement_id
        assert requirement["blocked_by"] == blocking, requirement_id
        expected = "BLOCKED" if blocking else "SETTLED"
        assert requirement["status"] == expected, requirement_id
        # A settled requirement's own decisions must all be fully decided.
        if expected == "SETTLED":
            assert all(decisions[ref]["status"] == "DECIDED" for ref in refs), requirement_id


def test_no_open_decision_carries_an_implementation_default() -> None:
    for decision_id, decision in register()["decisions"].items():
        assert "default" not in decision, decision_id
        if decision["status"] == "OPEN":
            assert "assumed" not in json.dumps(decision).lower(), decision_id


def test_register_is_not_an_approved_contract() -> None:
    value = register()
    assert value["contract_status"] == "NOT_APPROVED"
    assert value["complete_product_claim"] == "BLOCKED"
