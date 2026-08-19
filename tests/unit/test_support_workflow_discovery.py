from __future__ import annotations

from dataclasses import replace

import pytest

from pmpe.evals.support_corpus import generate_support_corpus
from pmpe.workflows.decision import DecisionContractError
from pmpe.workflows.support import PolicyRule, VisibleFact
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
    case = next(item for item in corpus.visible_cases if "CONTRADICTION" in item.case_id)

    decision = CustomerSupportDiscoveryAdapter().discover(case)

    assert decision.selected_action == "escalate"
    assert decision.status == "NEEDS_HUMAN_DECISION"
    assert decision.unresolved_questions
    assert set(decision.action_rule_refs) == {"RULE-FINAL-SALE", "RULE-RETURN-WINDOW"}


def test_missing_evidence_requests_evidence_instead_of_inventing_it() -> None:
    corpus = generate_support_corpus(seed=14)
    case = next(item for item in corpus.visible_cases if "MISSING" in item.case_id)

    decision = CustomerSupportDiscoveryAdapter().discover(case)

    assert decision.selected_action == "request_evidence"
    assert decision.status == "ADMITTED"
    assert decision.action_fact_refs == ("FACT-NO-RECEIPT",)


def test_unknown_policy_fails_closed() -> None:
    case = generate_support_corpus(seed=15).visible_cases[0]
    mutated = replace(
        case,
        policies=(PolicyRule("RULE-UNKNOWN", "An unrecognized action may be taken.", 90),),
    )

    with pytest.raises(DecisionContractError, match="unsupported policy"):
        CustomerSupportDiscoveryAdapter().discover(mutated)


def test_rule_without_required_fact_fails_closed() -> None:
    case = generate_support_corpus(seed=16).visible_cases[0]
    mutated = replace(
        case,
        facts=(VisibleFact("FACT-UNRELATED", "A different fact is visible.", "TICKET-X"),),
    )

    with pytest.raises(DecisionContractError, match="required visible fact"):
        CustomerSupportDiscoveryAdapter().discover(mutated)


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
