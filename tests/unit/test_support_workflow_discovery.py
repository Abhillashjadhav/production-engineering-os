from __future__ import annotations

from dataclasses import replace

import pytest

from pmpe.evals.support_corpus import generate_support_corpus
from pmpe.workflows.decision import DecisionContractError, create_decision_contract
from pmpe.workflows.support import (
    VisibleCorpusError,
    VisibleFact,
    create_policy_rule,
)
from pmpe.workflows.support_discovery import CustomerSupportDiscoveryAdapter


def test_all_synthetic_cases_compile_to_hidden_expected_decision() -> None:
    corpus = generate_support_corpus(seed=110)
    expected = {item.case_id: item.expected_outcome for item in corpus.hidden_oracles}
    adapter = CustomerSupportDiscoveryAdapter()

    decisions = tuple(adapter.discover(case) for case in corpus.visible_cases)

    assert len(decisions) == 30
    assert all(item.digest_is_valid() for item in decisions)
    assert {item.case_id: item.selected_action for item in decisions} == expected


def test_contract_is_deterministic_and_traces_action_to_visible_truth() -> None:
    case = generate_support_corpus(seed=12).visible_cases[0]
    adapter = CustomerSupportDiscoveryAdapter()

    first = adapter.discover(case)
    second = adapter.discover(case)

    assert first == second
    assert first.canonical_bytes() == second.canonical_bytes()
    assert first.selected_action == "refund"
    assert set(first.action_fact_refs) <= {item.fact_id for item in case.facts}
    assert set(first.action_rule_refs) <= {item.rule_id for item in case.policies}
    assert first.action_fact_refs and first.action_rule_refs


def test_equal_priority_policy_conflict_escalates_with_named_question() -> None:
    corpus = generate_support_corpus(seed=13)
    case = next(item for item in corpus.visible_cases if len(item.policies) == 2)

    decision = CustomerSupportDiscoveryAdapter().discover(case)

    assert decision.selected_action == "escalate"
    assert decision.status == "NEEDS_HUMAN_DECISION"
    assert decision.unresolved_questions
    assert set(decision.action_rule_refs) == {"RULE-FINAL-SALE", "RULE-RETURN-WINDOW"}


def test_missing_evidence_requests_evidence_instead_of_inventing_it() -> None:
    corpus = generate_support_corpus(seed=14)
    case = next(
        item
        for item in corpus.visible_cases
        if any(policy.action == "request_evidence" for policy in item.policies)
    )

    decision = CustomerSupportDiscoveryAdapter().discover(case)

    assert decision.selected_action == "request_evidence"
    assert decision.status == "ADMITTED"
    assert decision.action_fact_refs == ("FACT-NO-RECEIPT",)


def test_new_policy_identifier_uses_structured_semantics_not_corpus_vocabulary() -> None:
    case = generate_support_corpus(seed=15).visible_cases[0]
    mutated = replace(
        case,
        policies=(
            create_policy_rule(
                "RULE-NEW-VERTICAL-ID",
                "A verified in-window purchase may be refunded.",
                90,
                action="refund",
                required_fact=case.facts[0],
            ),
        ),
    )

    decision = CustomerSupportDiscoveryAdapter().discover(mutated)

    assert decision.selected_action == "refund"
    assert decision.action_rule_refs == ("RULE-NEW-VERTICAL-ID",)


def test_policy_text_change_invalidates_bound_structured_semantics() -> None:
    case = generate_support_corpus(seed=15).visible_cases[0]

    with pytest.raises(VisibleCorpusError, match="policy rule is malformed"):
        replace(case.policies[0], text="Refunds are forbidden.")


def test_policy_priority_change_invalidates_bound_structured_semantics() -> None:
    case = generate_support_corpus(seed=15).visible_cases[0]

    with pytest.raises(VisibleCorpusError, match="policy rule is malformed"):
        replace(case.policies[0], priority=case.policies[0].priority + 1)


def test_non_escalation_action_with_human_question_stays_human_bound() -> None:
    case = generate_support_corpus(seed=19).visible_cases[0]
    policy = case.policies[0]
    human_bound = create_policy_rule(
        policy.rule_id,
        policy.text,
        policy.priority,
        action=policy.action,
        required_fact=case.facts[0],
        human_question="A manager must approve this otherwise eligible refund.",
    )

    decision = CustomerSupportDiscoveryAdapter().discover(replace(case, policies=(human_bound,)))

    assert decision.selected_action == "refund"
    assert decision.status == "NEEDS_HUMAN_DECISION"
    assert decision.unresolved_questions == (
        "A manager must approve this otherwise eligible refund.",
    )


def test_admitted_contract_cannot_carry_unresolved_questions() -> None:
    with pytest.raises(DecisionContractError, match="malformed or incomplete"):
        create_decision_contract(
            vertical="customer_support",
            case_id="SUP-1",
            input_digest="sha256:input",
            selected_action="refund",
            status="ADMITTED",
            action_fact_refs=("FACT-1",),
            action_rule_refs=("RULE-1",),
            unresolved_questions=("Who approves this action?",),
        )


def test_escalation_policy_requires_a_named_human_question() -> None:
    for question in ("", "   "):
        with pytest.raises(VisibleCorpusError, match="policy rule is malformed"):
            create_policy_rule(
                "RULE-ESCALATE",
                "Escalate this case.",
                100,
                action="escalate",
                required_fact=VisibleFact("FACT-1", "Visible escalation fact.", "TICKET-1"),
                human_question=question,
            )


def test_conflict_preserves_rule_specific_human_questions() -> None:
    corpus = generate_support_corpus(seed=18)
    case = next(
        item
        for item in corpus.visible_cases
        if any(policy.human_question for policy in item.policies)
    )
    existing = case.policies[0]
    conflicting = create_policy_rule(
        "RULE-SECOND-HUMAN-BOUNDARY",
        "This claim must be rejected unless legal approves it.",
        existing.priority,
        action="reject",
        required_fact=case.facts[0],
        human_question="A legal approver must decide whether rejection is required.",
    )

    decision = CustomerSupportDiscoveryAdapter().discover(
        replace(case, policies=(*case.policies, conflicting))
    )

    assert decision.selected_action == "escalate"
    assert len(decision.unresolved_questions) == 3
    assert any("named human approver" in item for item in decision.unresolved_questions)
    assert any("legal approver" in item for item in decision.unresolved_questions)
    assert any("choose precedence" in item for item in decision.unresolved_questions)


def test_rule_without_required_fact_fails_closed() -> None:
    case = generate_support_corpus(seed=16).visible_cases[0]
    mutated = replace(
        case,
        facts=(VisibleFact("FACT-UNRELATED", "A different fact is visible.", "TICKET-X"),),
    )

    with pytest.raises(DecisionContractError, match="bound visible fact"):
        CustomerSupportDiscoveryAdapter().discover(mutated)


def test_changed_fact_text_invalidates_policy_authorization() -> None:
    case = generate_support_corpus(seed=16).visible_cases[0]
    changed = replace(case.facts[0], text="Order delivered 100 days ago and is used.")

    with pytest.raises(DecisionContractError, match="bound visible fact"):
        CustomerSupportDiscoveryAdapter().discover(replace(case, facts=(changed,)))


def test_contract_constructor_rejects_payload_digest_mismatch() -> None:
    contract = CustomerSupportDiscoveryAdapter().discover(
        generate_support_corpus(seed=16).visible_cases[0]
    )

    with pytest.raises(DecisionContractError, match="malformed or incomplete"):
        replace(contract, selected_action="reject")


def test_contract_core_is_vertical_neutral() -> None:
    case = generate_support_corpus(seed=17).visible_cases[0]
    payload = CustomerSupportDiscoveryAdapter().discover(case).as_dict()

    assert payload["vertical"] == "customer_support"
    assert "refund_window" not in payload
    assert "replacement_policy" not in payload
    assert set(payload) == {
        "action_fact_refs",
        "action_rule_refs",
        "case_id",
        "contract_digest",
        "input_digest",
        "schema_version",
        "selected_action",
        "status",
        "unresolved_questions",
        "vertical",
    }
