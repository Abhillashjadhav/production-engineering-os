"""The AI task planner's owner-decision register keeps open choices explicit.

Product authority (owner, 2026-09-25): no requirement may be implemented on an
unanswered decision, and no decision may be recorded as answered without its source.
"""

from __future__ import annotations

import json
import re
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


def requirement_errors(value: dict[str, Any]) -> list[str]:
    """Blockers are derived from every referenced decision, never trusted as listed."""
    decisions = value["decisions"]
    errors = []
    for requirement_id, requirement in value["requirements"].items():
        refs = requirement["decision_refs"]
        if not refs or not set(refs) <= set(decisions):
            errors.append(requirement_id + ": unknown or missing decision reference")
            continue
        expected = sorted(ref for ref in refs if decisions[ref]["status"] != "DECIDED")
        if requirement["blocked_by"] != expected:
            errors.append(f"{requirement_id}: blocked_by must be {expected}")
        if requirement["status"] != ("BLOCKED" if expected else "SETTLED"):
            errors.append(requirement_id + ": status contradicts its decisions")
    return errors


SOURCE_LOCATOR = re.compile(
    r"(owner (interview|message) \d{4}-\d{2}-\d{2} \d{2}:\d{2}(-\d{2}:\d{2})? IST"
    r"|owner task instructions, this session's opening request)"
)


def test_every_answer_source_names_a_time_or_an_exact_message() -> None:
    """A source must let an auditor find the answer: a clock time or the exact message."""
    for decision_id, decision in register()["decisions"].items():
        if decision["status"] != "OPEN":
            assert SOURCE_LOCATOR.match(decision["source"]), decision_id


def test_requirements_reference_known_decisions_and_block_on_open_parts() -> None:
    assert requirement_errors(register()) == []


def test_dropped_or_invented_blockers_are_detected() -> None:
    dropped = register()
    dropped["requirements"]["R2"]["blocked_by"] = ["D20"]
    invented = register()
    invented["requirements"]["R1"]["blocked_by"] = ["D14"]
    invented["requirements"]["R1"]["status"] = "BLOCKED"
    assert any(error.startswith("R2:") for error in requirement_errors(dropped))
    assert any(error.startswith("R1:") for error in requirement_errors(invented))


def test_task_inference_waits_on_the_data_handling_decision() -> None:
    """Inferring tasks sends transcript text to a model service, which D20 governs (Codex #219)."""
    value = register()
    assert "D20" in value["requirements"]["R4"]["decision_refs"]
    for decision_id in ("D18", "D23"):
        value["decisions"][decision_id]["status"] = "DECIDED"
    value["requirements"]["R4"]["blocked_by"] = ["D20"]
    value["requirements"]["R4"]["status"] = "BLOCKED"
    assert not any(error.startswith("R4:") for error in requirement_errors(value))
    value["requirements"]["R4"]["blocked_by"] = []
    value["requirements"]["R4"]["status"] = "SETTLED"
    assert any(error.startswith("R4:") for error in requirement_errors(value))


def test_no_open_decision_carries_an_implementation_default() -> None:
    for decision_id, decision in register()["decisions"].items():
        assert "default" not in decision, decision_id
        if decision["status"] == "OPEN":
            assert "assumed" not in json.dumps(decision).lower(), decision_id


def test_register_is_not_an_approved_contract() -> None:
    value = register()
    assert value["contract_status"] == "NOT_APPROVED"
    assert value["complete_product_claim"] == "BLOCKED"
