"""Workflow contracts, evidence joins, validation, and approval boundaries."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from pmpe.contracts.canonical import canonical_digest
from pmpe.personal.catalog import GENERIC_WORKFLOW_CATALOG, workflow_catalog_payload
from pmpe.personal.executor import (
    PersonalExecution,
    PersonalExecutionError,
    load_personal_context,
    run_personal_execution,
    verify_personal_execution,
    write_personal_execution,
)
from pmpe.personal.models import (
    PersonalContractError,
    create_approval_item,
    create_personal_work_contract,
)
from pmpe.personal.planner import WORKFLOW_ORDER
from pmpe.personal.synthetic import synthetic_personal_context, write_synthetic_personal_context


def test_synthetic_context_is_deterministic() -> None:
    assert synthetic_personal_context(7) == synthetic_personal_context(7)
    assert synthetic_personal_context(7) != synthetic_personal_context(8)


def test_work_contract_requires_an_outcome_metric() -> None:
    with pytest.raises(PersonalContractError):
        create_personal_work_contract(
            contract_id="PERSONAL-001",
            problem="Incomplete work cannot be trusted.",
            hypothesis="Verified outcomes reduce rework.",
            proposed_answer="Run one governed workflow.",
            target_outcome="A reviewer can inspect the completed outcome.",
            deadline="2026-08-29",
            north_star_metric="",
            leading_metrics=("Time to first result",),
            guardrails=("Zero unauthorized writes",),
            trade_off="Approval latency for safety.",
            scope=("Local artifacts",),
            non_goals=("External writes",),
            workflow_ids=("goal-to-verified-release",),
            workflow_source_ids={"goal-to-verified-release": ("SRC-001",)},
            input_digest=canonical_digest({"input": "approved"}),
            approved_by="user",
        )


def test_all_workflows_execute_in_one_parallel_batch() -> None:
    execution = run_personal_execution(synthetic_personal_context())
    assert tuple(result.workflow_id for result in execution.results) == WORKFLOW_ORDER
    assert {result.execution_batch for result in execution.results} == {"PARALLEL-BATCH-001"}
    assert execution.report.parallel_batches == 1
    assert execution.report.evidence_complete
    assert execution.report.status == "COMPLETED_WITH_PENDING_APPROVALS"


@pytest.mark.parametrize("workflow_id", WORKFLOW_ORDER)
def test_every_pack_has_a_runnable_synthetic_starter(workflow_id: str) -> None:
    context = synthetic_personal_context(workflow_ids=(workflow_id,))
    execution = run_personal_execution(context)
    assert [result.workflow_id for result in execution.results] == [workflow_id]
    assert verify_personal_execution(execution)


def test_catalog_declares_product_and_control_contracts_for_every_pack() -> None:
    payload = workflow_catalog_payload()
    assert payload["schema_version"] == "1.0.0"
    workflows = payload["workflows"]
    assert isinstance(workflows, list) and len(workflows) == 21
    assert tuple(item["workflow_id"] for item in workflows) == WORKFLOW_ORDER
    assert all(
        item["problem_solved"] and item["output_name"] and item["approvals"] and item["done"]
        for item in workflows
    )


def test_extended_pack_holds_output_and_approvals_when_a_check_fails() -> None:
    context = synthetic_personal_context(workflow_ids=("release-readiness-room",))
    record = context["workflow_inputs"]["release-readiness-room"]["records"][0]
    record["content"]["release_checks"][0]["status"] = "FAIL"
    execution = run_personal_execution(context)
    assert execution.results[0].output["validation"]["verdict"] == "HOLD"
    assert execution.approvals == ()
    assert execution.report.status == "BLOCKED_BY_VALIDATION"


def test_extended_pack_does_not_trust_a_caller_declared_pass() -> None:
    context = synthetic_personal_context(workflow_ids=("repo-doctor",))
    supplied = context["workflow_inputs"]["repo-doctor"]
    supplied["checks"][0]["status"] = "PASS"
    supplied["records"][0]["content"]["command_runs"][0]["exit_code"] = 1
    execution = run_personal_execution(context)
    validation = execution.results[0].output["validation"]
    assert validation["verdict"] == "HOLD"
    assert (
        "commands-bound-to-admitted-results"
        in execution.results[0].output["details"]["failed_check_ids"]
    )
    assert execution.approvals == ()


def test_repo_doctor_binds_exit_code_to_admitted_command_result() -> None:
    context = synthetic_personal_context(workflow_ids=("repo-doctor",))
    source_id = context["workflow_inputs"]["repo-doctor"]["evidence_source_ids"][0]
    source = next(item for item in context["evidence_sources"] if item["source_id"] == source_id)
    source["content"]["command_results"] = []
    source["content_digest"] = canonical_digest(source["content"])
    execution = run_personal_execution(context)
    validation = execution.results[0].output["validation"]
    assert validation["verdict"] == "HOLD"
    assert (
        "commands-bound-to-admitted-results"
        in execution.results[0].output["details"]["failed_check_ids"]
    )
    assert execution.approvals == ()


def test_market_watch_enforces_freshness_cutoff() -> None:
    context = synthetic_personal_context(workflow_ids=("competitive-market-watch",))
    supplied = context["workflow_inputs"]["competitive-market-watch"]
    supplied["records"][0]["content"]["changes"][0]["observed_at"] = "2020-01-01T00:00:00+05:30"
    execution = run_personal_execution(context)
    assert execution.results[0].output["validation"]["verdict"] == "HOLD"
    assert execution.approvals == ()


def test_customer_quote_source_must_be_in_the_admitted_packet() -> None:
    context = synthetic_personal_context(workflow_ids=("customer-research-synthesis",))
    quote = context["workflow_inputs"]["customer-research-synthesis"]["records"][0]["content"][
        "quotes"
    ][0]
    quote["source_ids"] = ["SRC-NOT-ADMITTED"]
    with pytest.raises(PersonalExecutionError, match="unknown evidence source"):
        run_personal_execution(context)


def test_roadmap_validation_hold_returns_without_consequential_approvals() -> None:
    context = synthetic_personal_context(workflow_ids=("evidence-to-roadmap-to-release",))
    context["workflow_inputs"]["evidence-to-roadmap-to-release"]["release_checks"][0]["status"] = (
        "FAIL"
    )
    execution = run_personal_execution(context)
    assert execution.results[0].output["validation"]["verdict"] == "HOLD"
    assert execution.approvals == ()
    assert execution.report.status == "BLOCKED_BY_VALIDATION"


def test_extended_approval_cannot_escape_exact_action_policy() -> None:
    execution = run_personal_execution(
        synthetic_personal_context(workflow_ids=("verified-executive-update",))
    )
    original = execution.approvals[0]
    changed = create_approval_item(
        approval_id=original.approval_id,
        workflow_id=original.workflow_id,
        action_type=original.action_type,
        target="unapproved-target",
        reason=original.reason,
        reversibility=original.reversibility,
        evidence_refs=original.evidence_refs,
        payload=original.payload,
    )
    tampered = PersonalExecution(
        execution.contract,
        execution.packets,
        execution.results,
        (changed,),
        execution.evidence,
        execution.report,
    )
    assert not verify_personal_execution(tampered)


def test_consequential_actions_are_exact_approval_payloads() -> None:
    execution = run_personal_execution(synthetic_personal_context())
    tier_one_actions = {
        "calendar.write",
        "git.merge",
        "git.pr.create",
        "message.send",
        "model.release",
        "production.deploy",
        "release.publish",
        "roadmap.update",
        "task.create",
    }
    extended_actions = {
        action for entry in GENERIC_WORKFLOW_CATALOG.values() for action in entry["approvals"]
    }
    assert {item.action_type for item in execution.approvals} == (
        tier_one_actions | extended_actions
    )
    assert all(item.status == "PENDING_APPROVAL" for item in execution.approvals)
    assert all(item.target and item.reason and item.reversibility for item in execution.approvals)
    assert all(
        item.payload_digest == canonical_digest(item.payload) for item in execution.approvals
    )
    assert execution.report.unauthorized_external_actions == 0


def test_goal_workflow_emits_parallel_codex_task_packets() -> None:
    execution = run_personal_execution(synthetic_personal_context())
    result = next(
        item for item in execution.results if item.workflow_id == "goal-to-verified-release"
    )
    details = result.output["details"]
    assert [item["task_id"] for item in details["parallel_codex_tasks"]] == [
        "CODEX-RESEARCH-001",
        "CODEX-BUILD-001",
    ]
    assert details["verification_task"]["depends_on"] == ["CODEX-BUILD-001"]


def test_all_results_have_deterministic_validation_and_provenance() -> None:
    execution = run_personal_execution(synthetic_personal_context())
    known_sources = {item.source_id for item in execution.evidence}
    for result in execution.results:
        assert result.output["validation"]["verdict"] == "PASS"
        assert result.output["validation"]["checks"]
        assert result.output["provenance"]
        assert set(result.evidence_refs) <= known_sources
        assert result.output["mobile_review"]["next_decision"]


def test_failed_eval_threshold_holds_release_and_reports_blocker() -> None:
    context = synthetic_personal_context(workflow_ids=("ai-eval-release-gate",))
    context["workflow_inputs"]["ai-eval-release-gate"]["golden_cases"][0]["actual"] = (
        "Incorrect answer"
    )
    execution = run_personal_execution(context)
    result = execution.results[0]
    assert result.output["validation"]["verdict"] == "HOLD"
    assert execution.report.status == "BLOCKED_BY_VALIDATION"
    assert execution.approvals == ()
    assert "QUALITY_MISMATCH" in result.output["details"]["failure_taxonomy"]


def test_tampered_result_fails_verification() -> None:
    execution = run_personal_execution(synthetic_personal_context())
    changed_result = replace(execution.results[0], status="FAILED")
    changed = PersonalExecution(
        execution.contract,
        execution.packets,
        (changed_result, *execution.results[1:]),
        execution.approvals,
        execution.evidence,
        execution.report,
    )
    assert not verify_personal_execution(changed)


def test_tampered_evidence_digest_is_rejected() -> None:
    context = synthetic_personal_context()
    context["evidence_sources"][0]["content_digest"] = canonical_digest({"tampered": True})
    with pytest.raises(PersonalExecutionError, match="content_digest"):
        run_personal_execution(context)


def test_nested_evidence_must_be_admitted_by_its_workflow_packet() -> None:
    context = synthetic_personal_context(workflow_ids=("goal-to-verified-release",))
    context["evidence_sources"].append(
        {
            "source_id": "SRC-UNAUTHORIZED",
            "kind": "document",
            "title": "Unadmitted source",
            "uri": "local://unadmitted",
            "observed_at": "2026-08-19T12:00:00Z",
            "content": {"claim": "not admitted to this task"},
            "content_digest": canonical_digest({"claim": "not admitted to this task"}),
        }
    )
    context["workflow_inputs"]["goal-to-verified-release"]["acceptance_checks"][0][
        "evidence_source_ids"
    ] = ["SRC-UNAUTHORIZED"]
    with pytest.raises(PersonalExecutionError, match="outside its task packet"):
        run_personal_execution(context)


def test_selected_workflow_requires_matching_input() -> None:
    context = synthetic_personal_context(workflow_ids=("issue-to-draft-pr",))
    context["workflow_inputs"] = {}
    with pytest.raises(PersonalExecutionError, match="exactly the selected"):
        run_personal_execution(context)


def test_verified_execution_writes_reviewable_artifacts(tmp_path: Path) -> None:
    execution = run_personal_execution(synthetic_personal_context())
    paths = write_personal_execution(tmp_path, execution)
    assert set(paths) == {
        "contract",
        "task_graph",
        "results",
        "evidence",
        "approvals",
        "mobile_review",
        "report",
        "workflow_catalog",
    }
    report = json.loads(paths["report"].read_text())
    mobile = json.loads(paths["mobile_review"].read_text())
    assert report["status"] == "COMPLETED_WITH_PENDING_APPROVALS"
    assert report["mobile_review_digest"] == canonical_digest(mobile)
    assert len(mobile["workflow_cards"]) == 21
    assert mobile["single_next_decision"] == "Review 25 exact approvals"
    assert all(len(card["facts"]) <= 4 for card in mobile["workflow_cards"])


def test_synthetic_context_round_trip(tmp_path: Path) -> None:
    path = write_synthetic_personal_context(tmp_path, 12)
    assert load_personal_context(path) == synthetic_personal_context(12)
