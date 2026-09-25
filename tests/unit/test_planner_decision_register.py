"""The AI task planner's owner-decision register keeps open choices explicit.

Product authority (owner, 2026-09-25): no requirement may be implemented on an
unanswered decision, and no decision may be recorded as answered without its source.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

REGISTER = Path(__file__).resolve().parents[2] / "docs/ai-task-planner/decision-register.json"
STATUSES = {"DECIDED", "PARTIALLY_DECIDED", "OPEN"}
# The register's shape is pinned here, so any change to it is a visible test change.
# Requirement -> the decisions it depends on (README table); none may silently disappear.
REQUIREMENT_REFS = {
    "R1": ["D17"],
    "R2": ["D9", "D15a", "D20", "D22"],
    "R3": ["D15a"],
    "R4": ["D8", "D10", "D18", "D20", "D23"],
    "R5": ["D17"],
    "R6": ["D16", "D19b"],
    "R7": ["D19a"],
    "R8": ["D11", "D12a", "D12b", "D26"],
    "R9": ["D11", "D7"],
    "R10": ["D11"],
    "R11": ["D13a", "D13b"],
    "R12": ["D10", "D14", "D15b"],
    "R13": ["D25"],
    "R14": ["D5"],
    "R15": ["D21"],
    "R16": ["D1", "D7"],
    "R17": ["D1", "D2", "D3"],
}
REQUIREMENTS = set(REQUIREMENT_REFS)
DECISIONS = {f"D{number}" for number in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 14, 16, 17, 18)} | {
    "D12a", "D12b", "D13a", "D13b", "D15a", "D15b", "D19a", "D19b",
    "D20", "D21", "D22", "D23", "D25", "D26",
}  # fmt: skip


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
    if set(value["requirements"]) != REQUIREMENTS:
        errors.append("requirements: inventory must be R1-R17")
    if set(decisions) != DECISIONS:
        errors.append("decisions: inventory changed")
    for requirement_id, requirement in value["requirements"].items():
        refs = requirement["decision_refs"]
        pinned = REQUIREMENT_REFS.get(requirement_id)
        if pinned is not None and refs != pinned:
            errors.append(f"{requirement_id}: decision_refs must be {pinned}")
        if not refs or not set(refs) <= set(decisions):
            errors.append(requirement_id + ": unknown or missing decision reference")
            continue
        expected = sorted(ref for ref in refs if decisions[ref]["status"] != "DECIDED")
        if requirement["blocked_by"] != expected:
            errors.append(f"{requirement_id}: blocked_by must be {expected}")
        if requirement["status"] != ("BLOCKED" if expected else "SETTLED"):
            errors.append(requirement_id + ": status contradicts its decisions")
    return errors


# A timed answer: a locator plus exactly one approved annotation, nothing else.
TIMED_SOURCE = re.compile(
    r"owner (interview|message) \d{4}-\d{2}-\d{2} \d{2}:\d{2}(-\d{2}:\d{2})? IST"
    r" \((private handoff|this session); paraphrased\)"
)

# Untimed session instructions, each bound to the one decision it answers.
INSTRUCTION_SOURCES = {
    "D25": "owner task instructions, this session's opening request (constraint list; paraphrased)",
}


def _real_timestamps(source: str) -> bool:
    """Every date and clock time in a source is a real one (ranges end after they start)."""
    stamp = re.search(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})(?:-(\d{2}:\d{2}))?", source)
    if stamp is None:
        return True
    try:
        start = datetime.strptime(f"{stamp[1]} {stamp[2]}", "%Y-%m-%d %H:%M")
        end = datetime.strptime(f"{stamp[1]} {stamp[3]}", "%Y-%m-%d %H:%M") if stamp[3] else start
    except ValueError:
        return False
    return end >= start


def source_errors(value: dict[str, Any]) -> list[str]:
    """Sources locate private material and never carry it (answers are paraphrased)."""
    return [
        decision_id
        for decision_id, decision in value["decisions"].items()
        if (
            decision["source"] is not None
            if decision["status"] == "OPEN"
            else not (
                isinstance(decision["source"], str)
                and (
                    decision["source"] == INSTRUCTION_SOURCES.get(decision_id)
                    or (
                        TIMED_SOURCE.fullmatch(decision["source"])
                        and _real_timestamps(decision["source"])
                    )
                )
            )
        )
    ]


def test_every_answer_source_names_a_time_or_an_exact_message() -> None:
    """A source must let an auditor find the answer: a clock time or the exact message."""
    assert source_errors(register()) == []


def test_open_decisions_carry_no_source() -> None:
    """An unanswered decision has nothing to locate, so it cannot carry text (Codex #219)."""
    value = register()
    value["decisions"]["D2"]["source"] = "copied private text"
    assert source_errors(value) == ["D2"]


def test_impossible_source_timestamps_are_refused() -> None:
    """An auditor cannot locate 2026-99-99 99:99 (Codex #219)."""
    for stamp in ("2026-99-99 99:99", "2026-09-25 16:61", "2026-09-25 16:23-25:00"):
        value = register()
        value["decisions"]["D1"]["source"] = (
            f"owner interview {stamp} IST (private handoff; paraphrased)"
        )
        assert source_errors(value) == ["D1"], stamp


def test_free_text_in_a_source_is_refused() -> None:
    """Only a locator plus one approved annotation; no room for copied wording (Codex #219)."""
    for suffix in (" (verbatim private answer)", " (private handoff; 'quoted')", ""):
        value = register()
        value["decisions"]["D1"]["source"] = "owner interview 2026-09-25 16:23 IST" + suffix
        assert source_errors(value) == ["D1"], suffix


def test_opening_request_locator_is_bound_to_its_decision() -> None:
    """Only the spending constraint came from the opening request (Codex #219)."""
    value = register()
    value["decisions"]["D1"]["source"] = value["decisions"]["D25"]["source"]
    assert source_errors(value) == ["D1"]


def test_no_requirement_can_go_missing() -> None:
    """Deleting a requirement must not leave the register green (Codex #219)."""
    for missing in (["R2"], [f"R{number}" for number in range(1, 18)]):
        value = register()
        for requirement_id in missing:
            del value["requirements"][requirement_id]
        assert "requirements: inventory must be R1-R17" in requirement_errors(value), missing


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


def test_no_decision_can_go_missing() -> None:
    """Deleting an unreferenced open decision must not leave the register green (Codex #219)."""
    value = register()
    del value["decisions"]["D4"]
    assert "decisions: inventory changed" in requirement_errors(value)


def test_requirement_dependencies_are_pinned() -> None:
    """Dropping a blocker and reconciling the requirement must still fail (Codex #219)."""
    value = register()
    value["requirements"]["R6"]["decision_refs"] = ["D16"]
    value["requirements"]["R6"]["blocked_by"] = []
    value["requirements"]["R6"]["status"] = "SETTLED"
    assert "R6: decision_refs must be ['D16', 'D19b']" in requirement_errors(value)


def test_undecided_entries_carry_no_default() -> None:
    """A partially decided entry still has an unanswered part, so no fallback (Codex #219)."""
    for change in (
        {"default": "manual export"},
        {"note": "Default to manual export meanwhile"},
        {"note": "assumed: copy-paste until decided"},
    ):
        value = register()
        value["decisions"]["D22"].update(change)
        assert default_errors(value) == ["D22"], change


def default_errors(value: dict[str, Any]) -> list[str]:
    """No decision names a default; an undecided one names no fallback or assumption."""
    return [
        decision_id
        for decision_id, decision in value["decisions"].items()
        if "default" in decision
        or (
            decision["status"] != "DECIDED"
            and re.search(r"default|assum|fallback", json.dumps(decision).lower())
        )
    ]


def test_decided_entries_carry_no_open_parts() -> None:
    """A DECIDED entry that still lists open parts cannot settle a requirement (Codex #219)."""
    value = register()
    value["decisions"]["D17"]["open_parts"] = ["which dates count as upcoming"]
    assert "D17: a DECIDED entry has open_parts" in requirement_errors(value)


def test_every_requirement_keeps_its_statement() -> None:
    """An ID without its obligation is not a requirement (Codex #219)."""
    for statement in (None, "", "   "):
        value = register()
        value["requirements"]["R2"]["statement"] = statement
        assert "R2: statement is missing" in requirement_errors(value), statement
    value = register()
    del value["requirements"]["R2"]["statement"]
    assert "R2: statement is missing" in requirement_errors(value)


def test_no_open_decision_carries_an_implementation_default() -> None:
    assert default_errors(register()) == []


def test_register_is_not_an_approved_contract() -> None:
    value = register()
    assert value["contract_status"] == "NOT_APPROVED"
    assert value["complete_product_claim"] == "BLOCKED"
