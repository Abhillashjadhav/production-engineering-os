"""Vertical-neutral decision contract compiled from visible business truth."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from pmpe.contracts.canonical import canonical_digest, canonical_json_bytes


class DecisionContractError(ValueError):
    """Raised when visible truth cannot produce a safe decision contract."""


@dataclass(frozen=True)
class DecisionContract:
    schema_version: str
    vertical: str
    case_id: str
    input_digest: str
    selected_action: str
    status: str
    action_fact_refs: tuple[str, ...]
    action_rule_refs: tuple[str, ...]
    unresolved_questions: tuple[str, ...]
    contract_digest: str

    def __post_init__(self) -> None:
        payload = self.as_dict()
        claimed_digest = str(payload.pop("contract_digest"))
        if not (
            self.schema_version == "1.0.0"
            and self.vertical
            and self.case_id
            and self.input_digest.startswith("sha256:")
            and self.selected_action
            and self.status in {"ADMITTED", "NEEDS_HUMAN_DECISION"}
            and self.action_fact_refs
            and self.action_rule_refs
            and (
                (self.status == "ADMITTED" and not self.unresolved_questions)
                or (self.status == "NEEDS_HUMAN_DECISION" and self.unresolved_questions)
            )
            and claimed_digest == canonical_digest(payload)
        ):
            raise DecisionContractError("decision contract is malformed or incomplete")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.as_dict())

    def digest_is_valid(self) -> bool:
        payload = self.as_dict()
        claimed = str(payload.pop("contract_digest"))
        return claimed == canonical_digest(payload)


def create_decision_contract(
    *,
    vertical: str,
    case_id: str,
    input_digest: str,
    selected_action: str,
    status: str,
    action_fact_refs: tuple[str, ...],
    action_rule_refs: tuple[str, ...],
    unresolved_questions: tuple[str, ...] = (),
) -> DecisionContract:
    payload: dict[str, Any] = {
        "action_fact_refs": list(action_fact_refs),
        "action_rule_refs": list(action_rule_refs),
        "case_id": case_id,
        "input_digest": input_digest,
        "schema_version": "1.0.0",
        "selected_action": selected_action,
        "status": status,
        "unresolved_questions": list(unresolved_questions),
        "vertical": vertical,
    }
    return DecisionContract(
        schema_version="1.0.0",
        vertical=vertical,
        case_id=case_id,
        input_digest=input_digest,
        selected_action=selected_action,
        status=status,
        action_fact_refs=action_fact_refs,
        action_rule_refs=action_rule_refs,
        unresolved_questions=unresolved_questions,
        contract_digest=canonical_digest(payload),
    )
