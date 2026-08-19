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


def test_extended_pack_complete_record_must_match_admitted_artifact() -> None:
    context = synthetic_personal_context(workflow_ids=("verified-executive-update",))
    claim = context["workflow_inputs"]["verified-executive-update"]["records"][0]["content"][
        "claims"
    ][0]
    claim["claim"] = "Unsupported executive claim"
    execution = run_personal_execution(context)
    assert execution.results[0].output["validation"]["verdict"] == "HOLD"
    assert (
        "records-bound-to-admitted-artifacts"
        in execution.results[0].output["details"]["failed_check_ids"]
    )
    assert execution.approvals == ()


def test_extended_pack_approval_payload_binds_verified_artifact_digest() -> None:
    execution = run_personal_execution(
        synthetic_personal_context(workflow_ids=("idea-to-deploy-starter",))
    )
    result = execution.results[0]
    artifact = result.output["details"]["artifact"]
    assert result.output["details"]["artifact_digest"] == canonical_digest(artifact)
    assert execution.approvals[0].payload["artifact_digest"] == canonical_digest(artifact)


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


def test_extended_pack_holds_when_a_declared_input_check_fails() -> None:
    context = synthetic_personal_context(workflow_ids=("release-readiness-room",))
    context["workflow_inputs"]["release-readiness-room"]["checks"][0]["status"] = "FAIL"
    execution = run_personal_execution(context)
    validation = execution.results[0].output["validation"]
    assert validation["verdict"] == "HOLD"
    assert (
        "declared-input-checks-pass" in execution.results[0].output["details"]["failed_check_ids"]
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


def test_customer_quote_source_ids_must_be_a_non_empty_list() -> None:
    context = synthetic_personal_context(workflow_ids=("customer-research-synthesis",))
    quote = context["workflow_inputs"]["customer-research-synthesis"]["records"][0]["content"][
        "quotes"
    ][0]
    quote["source_ids"] = "SRC-NOT-ADMITTED"
    execution = run_personal_execution(context)
    assert execution.results[0].output["validation"]["verdict"] == "HOLD"
    assert execution.approvals == ()


def test_repo_doctor_requires_every_verification_command_to_have_evidence() -> None:
    context = synthetic_personal_context(workflow_ids=("repo-doctor",))
    content = context["workflow_inputs"]["repo-doctor"]["records"][0]["content"]
    content["verification_commands"].append("python -m ruff check .")
    execution = run_personal_execution(context)
    assert execution.results[0].output["validation"]["verdict"] == "HOLD"
    assert (
        "verification-commands-bound-to-results"
        in execution.results[0].output["details"]["failed_check_ids"]
    )
    assert execution.approvals == ()


@pytest.mark.parametrize(
    ("workflow_id", "collection", "ids_field"),
    [
        ("docs-runbook-drift-maintainer", "drift_items", "evidence_source_ids"),
        ("competitive-market-watch", "changes", "source_ids"),
        ("verified-executive-update", "claims", "source_ids"),
    ],
)
def test_extended_provenance_fields_require_non_empty_id_lists(
    workflow_id: str, collection: str, ids_field: str
) -> None:
    context = synthetic_personal_context(workflow_ids=(workflow_id,))
    item = context["workflow_inputs"][workflow_id]["records"][0]["content"][collection][0]
    item[ids_field] = "SRC-NOT-ADMITTED"
    execution = run_personal_execution(context)
    assert execution.results[0].output["validation"]["verdict"] == "HOLD"
    assert execution.approvals == ()


def test_release_check_pass_must_match_an_admitted_result_artifact() -> None:
    context = synthetic_personal_context(workflow_ids=("release-readiness-room",))
    source_id = context["workflow_inputs"]["release-readiness-room"]["evidence_source_ids"][0]
    source = next(item for item in context["evidence_sources"] if item["source_id"] == source_id)
    source["content"]["check_results"] = []
    source["content_digest"] = canonical_digest(source["content"])
    execution = run_personal_execution(context)
    assert execution.results[0].output["validation"]["verdict"] == "HOLD"
    assert (
        "declared-results-bound-to-admitted-artifacts"
        in execution.results[0].output["details"]["failed_check_ids"]
    )
    assert execution.approvals == ()


def test_compiler_task_requirement_ids_must_resolve() -> None:
    context = synthetic_personal_context(workflow_ids=("prd-architecture-task-compiler",))
    content = context["workflow_inputs"]["prd-architecture-task-compiler"]["records"][0]["content"]
    content["tasks"][0]["requirement_ids"] = ["REQ-NOT-EXIST"]
    execution = run_personal_execution(context)
    assert execution.results[0].output["validation"]["verdict"] == "HOLD"
    assert (
        "tasks-trace-to-requirements" in execution.results[0].output["details"]["failed_check_ids"]
    )
    assert execution.approvals == ()


def test_compiler_requires_every_requirement_to_map_to_a_task() -> None:
    context = synthetic_personal_context(workflow_ids=("prd-architecture-task-compiler",))
    content = context["workflow_inputs"]["prd-architecture-task-compiler"]["records"][0]["content"]
    content["requirements"].append(
        {"requirement_id": "REQ-ORPHAN", "text": "This requirement must not be orphaned."}
    )
    execution = run_personal_execution(context)
    assert execution.results[0].output["validation"]["verdict"] == "HOLD"
    assert (
        "tasks-trace-to-requirements" in execution.results[0].output["details"]["failed_check_ids"]
    )
    assert execution.approvals == ()


def test_compiler_rejects_duplicate_task_ids() -> None:
    context = synthetic_personal_context(workflow_ids=("prd-architecture-task-compiler",))
    content = context["workflow_inputs"]["prd-architecture-task-compiler"]["records"][0]["content"]
    content["tasks"].append({"task_id": "TASK-001", "requirement_ids": ["REQ-001"]})
    execution = run_personal_execution(context)
    assert execution.results[0].output["validation"]["verdict"] == "HOLD"
    assert "task-ids-unique" in execution.results[0].output["details"]["failed_check_ids"]
    assert execution.approvals == ()


def test_goal_release_acceptance_must_bind_to_candidate_evidence() -> None:
    context = synthetic_personal_context(workflow_ids=("goal-to-verified-release",))
    for source in context["evidence_sources"]:
        content = source["content"]
        if isinstance(content, dict) and "acceptance_results" in content:
            content["acceptance_results"] = []
            source["content_digest"] = canonical_digest(content)
    execution = run_personal_execution(context)
    validation = execution.results[0].output["validation"]
    assert validation["verdict"] == "HOLD"
    check = next(
        item
        for item in validation["checks"]
        if item["check_id"] == "acceptance-results-bound-to-candidate"
    )
    assert not check["passed"]
    assert execution.approvals == ()


def test_ai_eval_results_must_bind_to_selected_candidate() -> None:
    context = synthetic_personal_context(workflow_ids=("ai-eval-release-gate",))
    context["workflow_inputs"]["ai-eval-release-gate"]["candidate_id"] = "OTHER-CANDIDATE"
    execution = run_personal_execution(context)
    validation = execution.results[0].output["validation"]
    assert validation["verdict"] == "HOLD"
    assert not next(
        item
        for item in validation["checks"]
        if item["check_id"] == "golden-results-bound-to-candidate"
    )["passed"]
    assert execution.approvals == ()


def test_ai_eval_thresholds_must_bind_to_admitted_policy() -> None:
    context = synthetic_personal_context(workflow_ids=("ai-eval-release-gate",))
    context["workflow_inputs"]["ai-eval-release-gate"]["thresholds"]["max_p95_latency_ms"] = 999
    execution = run_personal_execution(context)
    assert execution.results[0].output["validation"]["verdict"] == "HOLD"
    assert execution.approvals == ()


def test_ai_eval_policy_requires_the_complete_golden_set() -> None:
    context = synthetic_personal_context(workflow_ids=("ai-eval-release-gate",))
    context["workflow_inputs"]["ai-eval-release-gate"]["golden_cases"] = context["workflow_inputs"][
        "ai-eval-release-gate"
    ]["golden_cases"][:1]
    execution = run_personal_execution(context)
    assert execution.results[0].output["validation"]["verdict"] == "HOLD"
    assert execution.approvals == ()


def test_roadmap_release_checks_must_bind_to_admitted_results() -> None:
    context = synthetic_personal_context(workflow_ids=("evidence-to-roadmap-to-release",))
    for source in context["evidence_sources"]:
        content = source["content"]
        if isinstance(content, dict) and "roadmap_release_results" in content:
            content["roadmap_release_results"] = []
            source["content_digest"] = canonical_digest(content)
    execution = run_personal_execution(context)
    assert execution.results[0].output["validation"]["verdict"] == "HOLD"
    assert execution.approvals == ()


def test_roadmap_claims_and_decision_must_bind_to_admitted_evidence() -> None:
    context = synthetic_personal_context(workflow_ids=("evidence-to-roadmap-to-release",))
    supplied = context["workflow_inputs"]["evidence-to-roadmap-to-release"]
    supplied["claims"][0]["text"] = "Unsupported replacement claim."
    supplied["approved_option_id"] = "OPTION-AUTONOMOUS"
    execution = run_personal_execution(context)
    assert execution.results[0].output["validation"]["verdict"] == "HOLD"
    assert execution.approvals == ()


def test_roadmap_requirements_must_bind_to_admitted_decision() -> None:
    context = synthetic_personal_context(workflow_ids=("evidence-to-roadmap-to-release",))
    context["workflow_inputs"]["evidence-to-roadmap-to-release"]["requirements"] = [
        "Unadmitted roadmap requirement"
    ]
    execution = run_personal_execution(context)
    assert execution.results[0].output["validation"]["verdict"] == "HOLD"
    assert execution.approvals == ()


def test_draft_pr_checks_must_bind_to_candidate_digest() -> None:
    context = synthetic_personal_context(workflow_ids=("issue-to-draft-pr",))
    context["workflow_inputs"]["issue-to-draft-pr"]["candidate_digest"] = canonical_digest(
        {"candidate": "untested"}
    )
    execution = run_personal_execution(context)
    assert execution.results[0].output["validation"]["verdict"] == "HOLD"
    assert execution.approvals == ()


def test_draft_pr_issue_contract_must_bind_to_admitted_evidence() -> None:
    context = synthetic_personal_context(workflow_ids=("issue-to-draft-pr",))
    context["workflow_inputs"]["issue-to-draft-pr"]["issue_title"] = "Unadmitted scope"
    execution = run_personal_execution(context)
    assert execution.results[0].output["validation"]["verdict"] == "HOLD"
    assert execution.approvals == ()


def test_draft_pr_text_must_bind_to_admitted_evidence() -> None:
    context = synthetic_personal_context(workflow_ids=("issue-to-draft-pr",))
    context["workflow_inputs"]["issue-to-draft-pr"]["pr_body"] = "Unsupported PR claim"
    execution = run_personal_execution(context)
    assert execution.results[0].output["validation"]["verdict"] == "HOLD"
    assert execution.approvals == ()


def test_career_proof_evidence_links_must_be_admitted() -> None:
    context = synthetic_personal_context(workflow_ids=("career-proof-pack",))
    content = context["workflow_inputs"]["career-proof-pack"]["records"][0]["content"]
    content["evidence_source_ids"] = ["SRC-NOT-ADMITTED"]
    with pytest.raises(PersonalExecutionError, match="unknown evidence source"):
        run_personal_execution(context)


def test_weekly_command_centre_enumerates_non_adjacent_overlaps() -> None:
    context = synthetic_personal_context(workflow_ids=("weekly-pm-command-centre",))
    context["workflow_inputs"]["weekly-pm-command-centre"]["calendar_events"] = [
        {
            "event_id": "CAL-A",
            "start": "2026-08-20T09:00:00+05:30",
            "end": "2026-08-20T12:00:00+05:30",
            "title": "Long event",
        },
        {
            "event_id": "CAL-B",
            "start": "2026-08-20T10:00:00+05:30",
            "end": "2026-08-20T10:30:00+05:30",
            "title": "First short event",
        },
        {
            "event_id": "CAL-C",
            "start": "2026-08-20T11:00:00+05:30",
            "end": "2026-08-20T11:30:00+05:30",
            "title": "Second short event",
        },
    ]
    execution = run_personal_execution(context)
    assert execution.results[0].output["details"]["conflicts"] == [
        {"first_event_id": "CAL-A", "second_event_id": "CAL-B"},
        {"first_event_id": "CAL-A", "second_event_id": "CAL-C"},
    ]


def test_weekly_command_centre_requires_exact_admitted_snapshots() -> None:
    context = synthetic_personal_context(workflow_ids=("weekly-pm-command-centre",))
    context["workflow_inputs"]["weekly-pm-command-centre"]["messages"][0]["action_requested"] = (
        "Unadmitted action"
    )
    execution = run_personal_execution(context)
    assert execution.results[0].output["validation"]["verdict"] == "HOLD"
    assert execution.approvals == ()


def test_weekly_command_centre_compares_mixed_offsets_as_instants() -> None:
    context = synthetic_personal_context(workflow_ids=("weekly-pm-command-centre",))
    supplied = context["workflow_inputs"]["weekly-pm-command-centre"]
    supplied["calendar_events"] = [
        {
            "event_id": "CAL-INDIA",
            "start": "2026-08-20T09:00:00+05:30",
            "end": "2026-08-20T10:00:00+05:30",
            "title": "India event",
        },
        {
            "event_id": "CAL-UTC",
            "start": "2026-08-20T04:00:00+00:00",
            "end": "2026-08-20T05:00:00+00:00",
            "title": "UTC event",
        },
    ]
    calendar_source = next(
        source for source in context["evidence_sources"] if source["source_id"] == "SRC-CALENDAR"
    )
    calendar_source["content"]["calendar_snapshots"][0]["events"] = supplied["calendar_events"]
    calendar_source["content_digest"] = canonical_digest(calendar_source["content"])
    execution = run_personal_execution(context)
    assert execution.results[0].output["details"]["conflicts"] == [
        {"first_event_id": "CAL-INDIA", "second_event_id": "CAL-UTC"}
    ]


def test_meeting_output_requires_exact_admitted_record() -> None:
    context = synthetic_personal_context(workflow_ids=("meeting-to-decision",))
    context["workflow_inputs"]["meeting-to-decision"]["notes"] = ["Unadmitted decision note"]
    execution = run_personal_execution(context)
    assert execution.results[0].output["validation"]["verdict"] == "HOLD"
    assert execution.approvals == ()


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
