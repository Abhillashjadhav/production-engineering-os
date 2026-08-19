from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from pmpe.evals.support_corpus import generate_support_corpus
from pmpe.workflows.decision import create_decision_contract
from pmpe.workflows.runtime import (
    WorkflowEvidenceError,
    compile_workflow,
    execute_workflow,
    verify_workflow_report,
    write_workflow_report,
)
from pmpe.workflows.support_discovery import CustomerSupportDiscoveryAdapter


def _run(case_index: int = 0):  # type: ignore[no-untyped-def]
    case = generate_support_corpus(seed=110).visible_cases[case_index]
    adapter = CustomerSupportDiscoveryAdapter()
    contract = adapter.discover(case)
    plan = compile_workflow(contract)
    report = execute_workflow(case, contract, plan)
    return case, contract, plan, report


def test_compile_and_execute_produces_complete_digest_chain() -> None:
    case, contract, plan, report = _run()

    assert report.selected_action == "refund"
    assert report.status == "COMPLETED"
    assert report.input_digest == contract.input_digest
    assert report.contract_digest == contract.contract_digest
    assert report.plan_digest == plan.plan_digest
    assert report.execution_digest.startswith("sha256:")
    assert report.report_digest.startswith("sha256:")
    assert report.evidence_complete
    assert verify_workflow_report(case, contract, plan, report)


def test_all_cases_execute_to_hidden_expected_outcome() -> None:
    corpus = generate_support_corpus(seed=110)
    expected = {item.case_id: item.expected_outcome for item in corpus.hidden_oracles}
    adapter = CustomerSupportDiscoveryAdapter()

    reports = tuple(
        execute_workflow(case, contract, compile_workflow(contract))
        for case in corpus.visible_cases
        for contract in (adapter.discover(case),)
    )

    assert {item.case_id: item.selected_action for item in reports} == expected
    assert all(item.evidence_complete for item in reports)
    assert all(item.status in {"COMPLETED", "NEEDS_HUMAN_DECISION"} for item in reports)


def test_replay_is_byte_deterministic() -> None:
    case, contract, plan, first = _run(6)
    second = execute_workflow(case, contract, plan)

    assert first == second
    assert first.canonical_bytes() == second.canonical_bytes()


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("input_digest", "sha256:" + "0" * 64),
        ("contract_digest", "sha256:" + "0" * 64),
        ("plan_digest", "sha256:" + "0" * 64),
        ("execution_digest", "sha256:" + "0" * 64),
        ("selected_action", "refund"),
        ("evidence_complete", False),
    ),
)
def test_tampered_report_cannot_claim_verified_completion(field: str, value: object) -> None:
    case, contract, plan, report = _run(10)
    tampered = replace(report, **{field: value})

    assert not verify_workflow_report(case, contract, plan, tampered)


def test_report_writer_emits_minimal_json_and_markdown(tmp_path: Path) -> None:
    case, contract, plan, report = _run(20)

    paths = write_workflow_report(tmp_path, case, contract, plan, report)
    payload = json.loads(paths.json_path.read_text())
    markdown = paths.markdown_path.read_text()

    assert payload["case_id"] == case.case_id
    assert payload["selected_action"] == "reject"
    assert payload["evidence_complete"] is True
    assert "Evidence complete: yes" in markdown
    assert report.report_digest in markdown


def test_execution_rejects_mismatched_contract_or_plan() -> None:
    case, contract, plan, _report = _run()
    other_case = generate_support_corpus(seed=110).visible_cases[5]

    with pytest.raises(WorkflowEvidenceError, match="input digest"):
        execute_workflow(other_case, contract, plan)
    with pytest.raises(WorkflowEvidenceError, match="plan digest"):
        execute_workflow(case, contract, replace(plan, plan_digest="sha256:" + "0" * 64))


def test_digest_valid_caller_contract_cannot_authorize_arbitrary_action() -> None:
    case = generate_support_corpus(seed=110).visible_cases[0]
    forged = create_decision_contract(
        vertical="customer_support",
        case_id=case.case_id,
        input_digest=CustomerSupportDiscoveryAdapter().discover(case).input_digest,
        selected_action="wire_cash",
        status="ADMITTED",
        action_fact_refs=(case.facts[0].fact_id,),
        action_rule_refs=(case.policies[0].rule_id,),
    )
    plan = compile_workflow(forged)

    with pytest.raises(WorkflowEvidenceError, match="independently authorized"):
        execute_workflow(case, forged, plan)
