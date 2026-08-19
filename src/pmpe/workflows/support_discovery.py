"""Customer-support adapter from visible workflow inputs to a decision contract."""

from __future__ import annotations

from pmpe.contracts.canonical import canonical_digest
from pmpe.workflows.decision import (
    DecisionContract,
    DecisionContractError,
    create_decision_contract,
)
from pmpe.workflows.support import SupportCase


class CustomerSupportDiscoveryAdapter:
    vertical = "customer_support"

    def discover(self, case: SupportCase) -> DecisionContract:
        if type(case) is not SupportCase:
            raise DecisionContractError("customer-support input is not a visible support case")
        facts = {item.fact_id for item in case.facts}
        candidates: list[tuple[int, str, str, str, str]] = []
        for policy in case.policies:
            if policy.required_fact_id not in facts:
                raise DecisionContractError(
                    f"policy {policy.rule_id} lacks required visible fact {policy.required_fact_id}"
                )
            candidates.append(
                (
                    policy.priority,
                    policy.rule_id,
                    policy.action,
                    policy.required_fact_id,
                    policy.human_question,
                )
            )
        if not candidates:
            raise DecisionContractError("no visible policy can authorize a decision")

        highest = max(item[0] for item in candidates)
        selected = tuple(item for item in candidates if item[0] == highest)
        actions = {item[2] for item in selected}
        questions = tuple(sorted(item[4] for item in selected if item[4]))
        if len(actions) > 1:
            action = "escalate"
            status = "NEEDS_HUMAN_DECISION"
            questions = tuple(
                sorted(
                    {
                        *questions,
                        "Equal-priority visible policies authorize contradictory actions; "
                        "choose precedence.",
                    }
                )
            )
        else:
            action = next(iter(actions))
            status = "NEEDS_HUMAN_DECISION" if action == "escalate" or questions else "ADMITTED"
        fact_refs = tuple(sorted({item[3] for item in selected}))
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
