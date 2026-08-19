"""Customer-support adapter from visible workflow inputs to a decision contract."""

from __future__ import annotations

from dataclasses import dataclass

from pmpe.contracts.canonical import canonical_digest
from pmpe.workflows.decision import (
    DecisionContract,
    DecisionContractError,
    create_decision_contract,
)
from pmpe.workflows.support import SupportCase


@dataclass(frozen=True)
class _RuleMeaning:
    action: str
    required_fact: str
    human_question: str = ""


_RULES = {
    "RULE-RETURN-WINDOW": _RuleMeaning("refund", "FACT-ORDER-AGE"),
    "RULE-DAMAGE-REPLACE": _RuleMeaning("replacement", "FACT-DAMAGE-PHOTO"),
    "RULE-PROOF-REQUIRED": _RuleMeaning("request_evidence", "FACT-NO-RECEIPT"),
    "RULE-FINAL-SALE": _RuleMeaning("reject", "FACT-FINAL-SALE"),
    "RULE-CHANNEL-BOUNDARY": _RuleMeaning("reject", "FACT-CASH-DEMAND"),
    "RULE-HIGH-VALUE": _RuleMeaning(
        "escalate",
        "FACT-HIGH-VALUE",
        "A named human approver must decide this high-value claim.",
    ),
}


class CustomerSupportDiscoveryAdapter:
    vertical = "customer_support"

    def discover(self, case: SupportCase) -> DecisionContract:
        if type(case) is not SupportCase:
            raise DecisionContractError("customer-support input is not a visible support case")
        facts = {item.fact_id for item in case.facts}
        candidates: list[tuple[int, str, _RuleMeaning]] = []
        for policy in case.policies:
            meaning = _RULES.get(policy.rule_id)
            if meaning is None:
                raise DecisionContractError(f"unsupported policy rule: {policy.rule_id}")
            if meaning.required_fact not in facts:
                raise DecisionContractError(
                    f"policy {policy.rule_id} lacks required visible fact {meaning.required_fact}"
                )
            candidates.append((policy.priority, policy.rule_id, meaning))
        if not candidates:
            raise DecisionContractError("no visible policy can authorize a decision")

        highest = max(item[0] for item in candidates)
        selected = tuple(item for item in candidates if item[0] == highest)
        actions = {item[2].action for item in selected}
        questions = tuple(
            sorted(item[2].human_question for item in selected if item[2].human_question)
        )
        if len(actions) > 1:
            action = "escalate"
            status = "NEEDS_HUMAN_DECISION"
            questions = (
                "Equal-priority visible policies authorize contradictory actions; "
                "choose precedence.",
            )
        else:
            action = next(iter(actions))
            status = "NEEDS_HUMAN_DECISION" if action == "escalate" else "ADMITTED"
        fact_refs = tuple(sorted({item[2].required_fact for item in selected}))
        rule_refs = tuple(sorted(item[1] for item in selected))
        return create_decision_contract(
            vertical=self.vertical,
            case_id=case.case_id,
            input_digest=canonical_digest(case.as_dict()),
            selected_action=action,
            status=status,
            action_fact_refs=fact_refs,
            action_rule_refs=rule_refs,
            unresolved_questions=questions,
        )
