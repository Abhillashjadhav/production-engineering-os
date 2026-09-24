"""Parallel workflow execution with evidence, validation, and approval joins."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pmpe.contracts.authoring import write_json_atomic
from pmpe.contracts.canonical import canonical_digest
from pmpe.personal.catalog import workflow_catalog_payload
from pmpe.personal.input import (
    PersonalInputError,
    load_personal_request,
    validate_personal_context,
)
from pmpe.personal.models import (
    ApprovalItem,
    EvidenceRecord,
    PersonalExecutionReport,
    PersonalWorkContract,
    TaskPacket,
    TaskResult,
    create_personal_work_contract,
)
from pmpe.personal.planner import compile_task_graph, task_graph_digest
from pmpe.personal.workers import execute_task, validate_worker_output


class PersonalExecutionError(ValueError):
    """Raised when personal inputs or execution evidence fail closed."""


@dataclass(frozen=True)
class PersonalExecution:
    contract: PersonalWorkContract
    packets: tuple[TaskPacket, ...]
    results: tuple[TaskResult, ...]
    approvals: tuple[ApprovalItem, ...]
    evidence: tuple[EvidenceRecord, ...]
    report: PersonalExecutionReport


def _contract_digest_is_intact(contract: PersonalWorkContract) -> bool:
    payload = contract.as_dict()
    claimed = payload.pop("contract_digest", None)
    return isinstance(claimed, str) and canonical_digest(payload) == claimed


def load_personal_context(path: Path) -> dict[str, Any]:
    try:
        context, _evidence = load_personal_request(path)
    except PersonalInputError as exc:
        raise PersonalExecutionError(str(exc)) from exc
    return context


def _build_contract(
    context: dict[str, Any],
    evidence: tuple[EvidenceRecord, ...],
    approval_policy_bindings: dict[str, str],
) -> PersonalWorkContract:
    success = context["success"]
    workflow_source_ids = {
        workflow_id: tuple(context["workflow_inputs"][workflow_id]["evidence_source_ids"])
        for workflow_id in context["workflow_ids"]
    }
    return create_personal_work_contract(
        contract_id=f"PERSONAL-{context['request_id']}",
        problem=context["problem"],
        hypothesis=context["hypothesis"],
        proposed_answer=context["proposed_answer"],
        target_outcome=context["target_outcome"],
        deadline=context["deadline"],
        north_star_metric=success["north_star"],
        leading_metrics=tuple(success["leading"]),
        guardrails=tuple(success["guardrails"]),
        trade_off=context["trade_off"],
        scope=tuple(context["scope"]),
        non_goals=tuple(context["non_goals"]),
        workflow_ids=tuple(context["workflow_ids"]),
        workflow_source_ids=workflow_source_ids,
        evidence_source_bindings={
            item.source_id: canonical_digest(item.as_dict()) for item in evidence
        },
        approval_policy_bindings=approval_policy_bindings,
        input_digest=canonical_digest(context),
        approved_by=context["approved_by"],
    )


def _approval_policy_payload(approvals: tuple[ApprovalItem, ...]) -> list[dict[str, Any]]:
    return [
        {
            "action_type": approval.action_type,
            "approval_id": approval.approval_id,
            "evidence_refs": list(approval.evidence_refs),
            "payload": approval.payload,
            "reason": approval.reason,
            "reversibility": approval.reversibility,
            "target": approval.target,
        }
        for approval in approvals
    ]


def _admit_approval_policy_bindings(
    context: dict[str, Any], evidence: tuple[EvidenceRecord, ...]
) -> dict[str, str]:
    """Derive policies before the immutable execution contract is created."""

    provisional_bindings = {
        workflow_id: canonical_digest([]) for workflow_id in context["workflow_ids"]
    }
    provisional = _build_contract(context, evidence, provisional_bindings)
    bindings: dict[str, str] = {}
    for packet in compile_task_graph(provisional):
        _result, approvals = execute_task(packet, context, "POLICY-ADMISSION")
        bindings[packet.workflow_id] = canonical_digest(_approval_policy_payload(approvals))
    return bindings


def _status_and_outcome(
    results: tuple[TaskResult, ...], approvals: tuple[ApprovalItem, ...]
) -> tuple[str, str]:
    held = [
        result.workflow_id for result in results if result.output["validation"]["verdict"] == "HOLD"
    ]
    if held:
        return (
            "BLOCKED_BY_VALIDATION",
            f"{len(results) - len(held)} of {len(results)} workflow outcomes passed; "
            f"validation holds: {', '.join(held)}.",
        )
    if approvals:
        return (
            "COMPLETED_WITH_PENDING_APPROVALS",
            f"{len(results)} verified workflow outcomes completed; "
            f"{len(approvals)} consequential actions await approval.",
        )
    return "COMPLETED", f"{len(results)} verified workflow outcomes completed."


def mobile_review_payload(
    *,
    run_id: str,
    results: tuple[TaskResult, ...],
    approvals: tuple[ApprovalItem, ...],
) -> dict[str, Any]:
    status, outcome = _status_and_outcome(results, approvals)
    held = [
        result.workflow_id for result in results if result.output["validation"]["verdict"] == "HOLD"
    ]
    next_decision = (
        f"Repair and rerun: {held[0]}" if held else f"Review {len(approvals)} exact approvals"
    )
    return {
        "schema_version": "1.0.0",
        "run_id": run_id,
        "status": status,
        "outcome": outcome,
        "workflow_cards": [
            {
                "workflow_id": result.workflow_id,
                "evidence_count": len(result.evidence_refs),
                **result.output["mobile_review"],
            }
            for result in results
        ],
        "approval_cards": [
            {
                "approval_id": item.approval_id,
                "action_type": item.action_type,
                "target": item.target,
                "reason": item.reason,
                "reversibility": item.reversibility,
                "evidence_refs": list(item.evidence_refs),
                "payload": item.payload,
                "payload_digest": item.payload_digest,
                "status": item.status,
            }
            for item in approvals
        ],
        "single_next_decision": next_decision,
    }


def _report(
    *,
    run_id: str,
    contract: PersonalWorkContract,
    packets: tuple[TaskPacket, ...],
    results: tuple[TaskResult, ...],
    approvals: tuple[ApprovalItem, ...],
    evidence: tuple[EvidenceRecord, ...],
) -> PersonalExecutionReport:
    graph_digest = task_graph_digest(packets)
    evidence_payload = {
        "records": [item.as_dict() for item in evidence],
        "schema_version": "1.0.0",
    }
    mobile = mobile_review_payload(run_id=run_id, results=results, approvals=approvals)
    status, outcome = _status_and_outcome(results, approvals)
    packet_by_workflow = {packet.workflow_id: packet for packet in packets}
    evidence_source_ids = {item.source_id for item in evidence}
    evidence_source_bindings = {
        item.source_id: canonical_digest(item.as_dict()) for item in evidence
    }
    required_source_ids = (
        {source_id for packet in packets for source_id in packet.input_refs}
        | {source_id for result in results for source_id in result.evidence_refs}
        | {source_id for approval in approvals for source_id in approval.evidence_refs}
    )
    result_task_ids = [result.task_id for result in results]
    evidence_complete = (
        _contract_digest_is_intact(contract)
        and len(results) == len(packets)
        and len(set(result_task_ids)) == len(result_task_ids)
        and set(result_task_ids) == {packet.task_id for packet in packets}
        and required_source_ids <= evidence_source_ids
        and evidence_source_bindings == contract.evidence_source_bindings
        and all(
            canonical_digest(result.output["details"].get("approval_policy"))
            == contract.approval_policy_bindings.get(result.workflow_id)
            for result in results
        )
        and all(
            result.workflow_id in packet_by_workflow
            and validate_worker_output(
                result, set(packet_by_workflow[result.workflow_id].input_refs)
            )
            for result in results
        )
    )
    payload: dict[str, Any] = {
        "contract_digest": contract.contract_digest,
        "evidence_complete": evidence_complete,
        "evidence_ledger_digest": canonical_digest(evidence_payload),
        "mobile_review_digest": canonical_digest(mobile),
        "outcome": outcome,
        "parallel_batches": len({result.execution_batch for result in results}),
        "pending_approval_ids": [item.approval_id for item in approvals],
        "report_digest": "",
        "result_digests": [result.result_digest for result in results],
        "run_id": run_id,
        "schema_version": "1.0.0",
        "status": status,
        "task_graph_digest": graph_digest,
        "unauthorized_external_actions": 0,
    }
    digest_payload = dict(payload)
    del digest_payload["report_digest"]
    payload["report_digest"] = canonical_digest(digest_payload)
    return PersonalExecutionReport(
        schema_version=payload["schema_version"],
        run_id=run_id,
        contract_digest=contract.contract_digest,
        task_graph_digest=graph_digest,
        status=status,
        outcome=outcome,
        result_digests=tuple(payload["result_digests"]),
        pending_approval_ids=tuple(payload["pending_approval_ids"]),
        parallel_batches=payload["parallel_batches"],
        unauthorized_external_actions=0,
        evidence_complete=evidence_complete,
        evidence_ledger_digest=payload["evidence_ledger_digest"],
        mobile_review_digest=payload["mobile_review_digest"],
        report_digest=payload["report_digest"],
    )


def verify_personal_execution(execution: PersonalExecution) -> bool:
    try:
        if not _contract_digest_is_intact(execution.contract):
            return False
        packets = compile_task_graph(execution.contract)
        if packets != execution.packets or len(execution.results) != len(packets):
            return False
        result_task_ids = [result.task_id for result in execution.results]
        if len(set(result_task_ids)) != len(result_task_ids) or set(result_task_ids) != {
            packet.task_id for packet in packets
        }:
            return False
        known_sources = {item.source_id for item in execution.evidence}
        if len(known_sources) != len(execution.evidence):
            return False
        actual_source_bindings = {
            item.source_id: canonical_digest(item.as_dict()) for item in execution.evidence
        }
        if actual_source_bindings != execution.contract.evidence_source_bindings:
            return False
        required_sources = (
            {source_id for packet in packets for source_id in packet.input_refs}
            | {source_id for result in execution.results for source_id in result.evidence_refs}
            | {
                source_id
                for approval in execution.approvals
                for source_id in approval.evidence_refs
            }
        )
        if not required_sources <= known_sources:
            return False
        packet_by_id = {packet.task_id: packet for packet in packets}
        if len(packet_by_id) != len(packets):
            return False
        for result in execution.results:
            packet = packet_by_id.get(result.task_id)
            if (
                packet is None
                or result.workflow_id != packet.workflow_id
                or result.packet_digest != packet.packet_digest
                or not validate_worker_output(result, set(packet.input_refs))
            ):
                return False
            result_payload = {
                "evidence_refs": list(result.evidence_refs),
                "execution_batch": result.execution_batch,
                "output": result.output,
                "packet_digest": result.packet_digest,
                "status": result.status,
                "task_id": result.task_id,
                "workflow_id": result.workflow_id,
            }
            if result.status != "COMPLETED" or result.result_digest != canonical_digest(
                result_payload
            ):
                return False
        workflow_packets = {packet.workflow_id: packet for packet in packets}
        result_by_workflow = {result.workflow_id: result for result in execution.results}
        approvals_by_workflow: dict[str, list[ApprovalItem]] = {}
        for approval in execution.approvals:
            approvals_by_workflow.setdefault(approval.workflow_id, []).append(approval)
        if len({item.approval_id for item in execution.approvals}) != len(execution.approvals):
            return False
        for approval in execution.approvals:
            packet = workflow_packets.get(approval.workflow_id)
            approval_result = result_by_workflow.get(approval.workflow_id)
            if (
                packet is None
                or approval_result is None
                or approval.action_type not in packet.approval_required
                or not set(approval.evidence_refs) <= set(packet.input_refs)
                or approval.payload_digest != canonical_digest(approval.payload)
                or approval_result.output["validation"]["verdict"] != "PASS"
            ):
                return False
            policies = approval_result.output["details"].get("approval_policy")
            if not isinstance(policies, list) or not any(
                approval.action_type == policy["action_type"]
                and approval.approval_id == policy["approval_id"]
                and approval.target == policy["target"]
                and approval.reason == policy["reason"]
                and approval.reversibility == policy["reversibility"]
                and approval.payload == policy["payload"]
                and list(approval.evidence_refs) == policy["evidence_refs"]
                for policy in policies
            ):
                return False
        for workflow_id, result in result_by_workflow.items():
            policies = result.output["details"].get("approval_policy")
            if not isinstance(policies, list):
                return False
            if canonical_digest(policies) != execution.contract.approval_policy_bindings.get(
                workflow_id
            ):
                return False
            expected_count = (
                len(policies) if result.output["validation"]["verdict"] == "PASS" else 0
            )
            if len(approvals_by_workflow.get(workflow_id, [])) != expected_count:
                return False
        expected_report = _report(
            run_id=execution.report.run_id,
            contract=execution.contract,
            packets=execution.packets,
            results=execution.results,
            approvals=execution.approvals,
            evidence=execution.evidence,
        )
        return execution.report == expected_report and execution.report.evidence_complete
    except (KeyError, PersonalExecutionError, ValueError, TypeError):
        return False


def run_personal_execution(
    context: dict[str, Any], *, run_id: str = "PERSONAL-ALL-TIERS-001"
) -> PersonalExecution:
    try:
        evidence = validate_personal_context(context)
        approval_policy_bindings = _admit_approval_policy_bindings(context, evidence)
        contract = _build_contract(context, evidence, approval_policy_bindings)
        packets = compile_task_graph(contract)
    except (PersonalInputError, ValueError, KeyError, TypeError) as exc:
        raise PersonalExecutionError(str(exc)) from exc
    if not packets:
        raise PersonalExecutionError("personal task graph is empty")
    execution_batch = "PARALLEL-BATCH-001"
    barrier = threading.Barrier(len(packets))

    def run(packet: TaskPacket) -> tuple[TaskResult, tuple[ApprovalItem, ...]]:
        barrier.wait(timeout=10)
        return execute_task(packet, context, execution_batch)

    with ThreadPoolExecutor(
        max_workers=len(packets), thread_name_prefix="personal-workflow"
    ) as pool:
        futures = {packet.task_id: pool.submit(run, packet) for packet in packets}
        completed = [futures[packet.task_id].result() for packet in packets]
    results = tuple(item[0] for item in completed)
    approvals = tuple(
        sorted(
            (approval for _result, items in completed for approval in items),
            key=lambda item: item.approval_id,
        )
    )
    report = _report(
        run_id=run_id,
        contract=contract,
        packets=packets,
        results=results,
        approvals=approvals,
        evidence=evidence,
    )
    execution = PersonalExecution(contract, packets, results, approvals, evidence, report)
    if not verify_personal_execution(execution):
        raise PersonalExecutionError("personal execution evidence failed verification")
    return execution


def write_personal_execution(root: Path, execution: PersonalExecution) -> dict[str, Path]:
    if not verify_personal_execution(execution):
        raise PersonalExecutionError("unverified personal execution cannot be persisted")
    output = Path(root)
    paths = {
        "contract": output / "personal-work-contract.json",
        "task_graph": output / "task-graph.json",
        "results": output / "workflow-results.json",
        "evidence": output / "evidence-ledger.json",
        "approvals": output / "approval-outbox.json",
        "mobile_review": output / "mobile-review.json",
        "report": output / "personal-execution-report.json",
        "workflow_catalog": output / "workflow-catalog.json",
    }
    write_json_atomic(paths["contract"], execution.contract.as_dict())
    write_json_atomic(
        paths["task_graph"],
        {
            "schema_version": "1.0.0",
            "task_graph_digest": task_graph_digest(execution.packets),
            "tasks": [packet.as_dict() for packet in execution.packets],
        },
    )
    write_json_atomic(
        paths["results"],
        {
            "results": [result.as_dict() for result in execution.results],
            "schema_version": "1.0.0",
        },
    )
    evidence_payload = {
        "records": [item.as_dict() for item in execution.evidence],
        "schema_version": "1.0.0",
    }
    write_json_atomic(paths["evidence"], evidence_payload)
    write_json_atomic(
        paths["approvals"],
        {
            "items": [item.as_dict() for item in execution.approvals],
            "schema_version": "1.0.0",
        },
    )
    mobile = mobile_review_payload(
        run_id=execution.report.run_id,
        results=execution.results,
        approvals=execution.approvals,
    )
    if canonical_digest(mobile) != execution.report.mobile_review_digest:
        raise PersonalExecutionError("mobile review is not bound to the verified report")
    write_json_atomic(paths["mobile_review"], mobile)
    write_json_atomic(paths["report"], execution.report.as_dict())
    write_json_atomic(paths["workflow_catalog"], workflow_catalog_payload())
    return paths
