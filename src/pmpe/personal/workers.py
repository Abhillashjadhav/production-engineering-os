"""Bounded deterministic workers for Tier-1, Tier-2, and Tier-3 workflow packs."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

from pmpe.personal.catalog import GENERIC_WORKFLOW_CATALOG
from pmpe.personal.models import (
    ApprovalItem,
    TaskPacket,
    TaskResult,
    create_approval_item,
    create_task_result,
)

WorkerReturn = tuple[TaskResult, tuple[ApprovalItem, ...]]
Worker = Callable[[TaskPacket, dict[str, Any], str], WorkerReturn]


def _provenance(claim_id: str, source_ids: tuple[str, ...]) -> dict[str, Any]:
    return {"claim_id": claim_id, "source_ids": list(source_ids)}


def _result(
    packet: TaskPacket,
    execution_batch: str,
    *,
    outcome: str,
    verdict: str,
    checks: list[dict[str, Any]],
    provenance: list[dict[str, Any]],
    summary: str,
    facts: list[str],
    next_decision: str,
    details: dict[str, Any],
) -> TaskResult:
    output = {
        "outcome": outcome,
        "validation": {"checks": checks, "verdict": verdict},
        "provenance": provenance,
        "mobile_review": {
            "facts": facts[:4],
            "next_decision": next_decision,
            "status": verdict,
            "summary": summary,
            "title": packet.workflow_id.replace("-", " ").title(),
        },
        "details": details,
    }
    evidence_refs = tuple(
        sorted({source_id for record in provenance for source_id in record.get("source_ids", [])})
    )
    return create_task_result(
        packet=packet,
        output=output,
        evidence_refs=evidence_refs,
        execution_batch=execution_batch,
    )


def _approval(
    packet: TaskPacket,
    *,
    approval_id: str,
    action_type: str,
    target: str,
    reason: str,
    reversibility: str,
    evidence_refs: tuple[str, ...],
    payload: dict[str, Any],
) -> ApprovalItem:
    return create_approval_item(
        approval_id=approval_id,
        workflow_id=packet.workflow_id,
        action_type=action_type,
        target=target,
        reason=reason,
        reversibility=reversibility,
        evidence_refs=evidence_refs,
        payload=payload,
    )


def _goal_to_verified_release(
    packet: TaskPacket, context: dict[str, Any], execution_batch: str
) -> WorkerReturn:
    supplied = context["workflow_inputs"][packet.workflow_id]
    acceptance_checks = supplied["acceptance_checks"]
    failed = sorted(item["check_id"] for item in acceptance_checks if item["status"] != "PASS")
    verdict = "PASS" if not failed else "HOLD"
    codex_packets = [
        {
            "task_id": "CODEX-RESEARCH-001",
            "objective": "Reconcile release evidence and open product questions.",
            "depends_on": [],
            "definition_of_done": "Every material claim links to an admitted source.",
            "write_boundary": "local artifacts only",
        },
        {
            "task_id": "CODEX-BUILD-001",
            "objective": "Implement only the digest-bound approved release scope.",
            "depends_on": [],
            "definition_of_done": "Candidate and deterministic checks are reproducible.",
            "write_boundary": "isolated worktree only",
        },
        {
            "task_id": "CODEX-VERIFY-001",
            "objective": "Independently verify the exact release candidate digest.",
            "depends_on": ["CODEX-BUILD-001"],
            "definition_of_done": "Verdict is bound to candidate and evidence digests.",
            "write_boundary": "read-only candidate review",
        },
    ]
    provenance = [
        _provenance(f"acceptance:{item['check_id']}", tuple(item["evidence_source_ids"]))
        for item in acceptance_checks
    ]
    checks = [
        {
            "check_id": "all-acceptance-checks-pass",
            "passed": not failed,
            "observed": failed or "all PASS",
        },
        {
            "check_id": "candidate-digest-bound",
            "passed": True,
            "observed": supplied["release_candidate_digest"],
        },
    ]
    result = _result(
        packet,
        execution_batch,
        outcome=(
            "Release candidate is verified and ready for human release approval."
            if verdict == "PASS"
            else f"Release is held because acceptance checks failed: {', '.join(failed)}."
        ),
        verdict=verdict,
        checks=checks,
        provenance=provenance,
        summary=f"{len(acceptance_checks) - len(failed)}/{len(acceptance_checks)} checks passed.",
        facts=[
            f"Candidate: {supplied['release_candidate_digest']}",
            f"Target: {supplied['release_target']}",
            f"Failed checks: {len(failed)}",
        ],
        next_decision=(
            "Approve or reject merge and deployment."
            if verdict == "PASS"
            else "Repair the failed checks and rerun verification."
        ),
        details={
            "candidate_digest": supplied["release_candidate_digest"],
            "failed_check_ids": failed,
            "parallel_codex_tasks": codex_packets[:2],
            "verification_task": codex_packets[2],
        },
    )
    approvals: tuple[ApprovalItem, ...] = ()
    if verdict == "PASS":
        common = {
            "candidate_digest": supplied["release_candidate_digest"],
            "goal_id": supplied["goal_id"],
        }
        approvals = (
            _approval(
                packet,
                approval_id="APPROVAL-GOAL-MERGE-001",
                action_type="git.merge",
                target=supplied["release_target"],
                reason="All supplied acceptance checks pass for the exact candidate digest.",
                reversibility="Merge can be reverted; review the exact candidate before approval.",
                evidence_refs=result.evidence_refs,
                payload={**common, "action": "merge"},
            ),
            _approval(
                packet,
                approval_id="APPROVAL-GOAL-DEPLOY-001",
                action_type="production.deploy",
                target=supplied["release_target"],
                reason="Deployment remains a named human decision after verification.",
                reversibility=(
                    "Use the target's documented rollback; no deployment is executed here."
                ),
                evidence_refs=result.evidence_refs,
                payload={**common, "action": "deploy"},
            ),
        )
    return result, approvals


def _ai_eval_release_gate(
    packet: TaskPacket, context: dict[str, Any], execution_batch: str
) -> WorkerReturn:
    supplied = context["workflow_inputs"][packet.workflow_id]
    cases = supplied["golden_cases"]
    thresholds = supplied["thresholds"]
    correct = sum(item["actual"] == item["expected"] for item in cases)
    pass_rate = correct / len(cases)
    latencies = sorted(int(item["latency_ms"]) for item in cases)
    p95_latency = latencies[max(0, math.ceil(0.95 * len(latencies)) - 1)]
    average_cost = sum(float(item["cost_usd"]) for item in cases) / len(cases)
    safety_failures = sum(not item["safety_pass"] for item in cases)
    checks = [
        {
            "check_id": "quality-pass-rate",
            "passed": pass_rate >= thresholds["min_pass_rate"],
            "observed": round(pass_rate, 6),
            "threshold": thresholds["min_pass_rate"],
        },
        {
            "check_id": "p95-latency-ms",
            "passed": p95_latency <= thresholds["max_p95_latency_ms"],
            "observed": p95_latency,
            "threshold": thresholds["max_p95_latency_ms"],
        },
        {
            "check_id": "average-cost-usd",
            "passed": average_cost <= thresholds["max_average_cost_usd"],
            "observed": round(average_cost, 6),
            "threshold": thresholds["max_average_cost_usd"],
        },
        {
            "check_id": "safety-failures",
            "passed": safety_failures <= thresholds["max_safety_failures"],
            "observed": safety_failures,
            "threshold": thresholds["max_safety_failures"],
        },
    ]
    verdict = "PASS" if all(item["passed"] for item in checks) else "HOLD"
    failure_taxonomy: set[str] = set()
    if any(item["actual"] != item["expected"] for item in cases):
        failure_taxonomy.add("QUALITY_MISMATCH")
    if any(not item["safety_pass"] for item in cases):
        failure_taxonomy.add("SAFETY_FAILURE")
    if not checks[1]["passed"]:
        failure_taxonomy.add("LATENCY_BREACH")
    if not checks[2]["passed"]:
        failure_taxonomy.add("COST_BREACH")
    provenance = [
        _provenance(f"golden:{item['case_id']}", tuple(item["evidence_source_ids"]))
        for item in cases
    ]
    result = _result(
        packet,
        execution_batch,
        outcome=(
            "AI candidate passed every frozen release threshold."
            if verdict == "PASS"
            else "AI candidate is held by one or more frozen release thresholds."
        ),
        verdict=verdict,
        checks=checks,
        provenance=provenance,
        summary=f"{sum(item['passed'] for item in checks)}/{len(checks)} release gates passed.",
        facts=[
            f"Quality pass rate: {pass_rate:.1%}",
            f"p95 latency: {p95_latency} ms",
            f"Average cost: ${average_cost:.4f}",
            f"Safety failures: {safety_failures}",
        ],
        next_decision=(
            "Approve or reject candidate release."
            if verdict == "PASS"
            else "Fix the candidate and rerun the complete golden set."
        ),
        details={
            "candidate_id": supplied["candidate_id"],
            "failure_taxonomy": sorted(failure_taxonomy),
            "golden_case_count": len(cases),
        },
    )
    approvals: tuple[ApprovalItem, ...] = ()
    if verdict == "PASS":
        approvals = (
            _approval(
                packet,
                approval_id="APPROVAL-AI-RELEASE-001",
                action_type="model.release",
                target=supplied["release_target"],
                reason=(
                    "The candidate passed all frozen quality, latency, cost, and safety gates."
                ),
                reversibility="Release through a dial-up with rollback to the prior candidate.",
                evidence_refs=result.evidence_refs,
                payload={
                    "action": "release-ai-candidate",
                    "candidate_id": supplied["candidate_id"],
                    "release_target": supplied["release_target"],
                },
            ),
        )
    return result, approvals


def _weekly_pm_command_centre(
    packet: TaskPacket, context: dict[str, Any], execution_batch: str
) -> WorkerReturn:
    supplied = context["workflow_inputs"][packet.workflow_id]
    impact_rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    commitments = sorted(
        (item for item in supplied["commitments"] if item["status"] == "OPEN"),
        key=lambda item: (impact_rank[item["impact"]], item["due"], item["commitment_id"]),
    )
    messages = sorted(
        supplied["messages"],
        key=lambda item: (-int(item["importance"]), str(item["message_id"])),
    )
    events = sorted(supplied["calendar_events"], key=lambda item: (item["start"], item["event_id"]))
    conflicts: list[dict[str, str]] = []
    for left, right in zip(events, events[1:], strict=False):
        if right["start"] < left["end"]:
            conflicts.append(
                {"first_event_id": left["event_id"], "second_event_id": right["event_id"]}
            )
    priorities = [item["text"] for item in commitments[:3]]
    if len(priorities) < 3:
        priorities.extend(item["action_requested"] for item in messages[: 3 - len(priorities)])
    source_ids = tuple(supplied["evidence_source_ids"])
    checks = [
        {
            "check_id": "priorities-bounded",
            "passed": len(priorities[:3]) <= 3,
            "observed": len(priorities[:3]),
        },
        {"check_id": "conflicts-enumerated", "passed": True, "observed": len(conflicts)},
    ]
    result = _result(
        packet,
        execution_batch,
        outcome="A bounded weekly plan is ready; calendar and status writes remain drafts.",
        verdict="PASS",
        checks=checks,
        provenance=[_provenance("weekly-plan", source_ids)],
        summary=f"{len(priorities[:3])} priorities and {len(conflicts)} conflicts surfaced.",
        facts=[
            f"Open commitments: {len(commitments)}",
            f"Schedule conflicts: {len(conflicts)}",
            f"Requested messages: {len(messages)}",
        ],
        next_decision="Approve or edit the proposed calendar change and weekly status.",
        details={
            "conflicts": conflicts,
            "focus_plan": priorities[:3],
            "timezone": supplied["timezone"],
            "weekly_status_draft": {
                "priorities": priorities[:3],
                "risks": [f"Calendar overlap: {item}" for item in conflicts],
            },
        },
    )
    approvals: list[ApprovalItem] = [
        _approval(
            packet,
            approval_id="APPROVAL-WEEKLY-STATUS-001",
            action_type="message.send",
            target="configured-weekly-status-channel",
            reason="The weekly status is a draft derived from admitted commitments and messages.",
            reversibility="A sent message cannot be recalled reliably; edit before approval.",
            evidence_refs=result.evidence_refs,
            payload={"action": "send-weekly-status", "priorities": priorities[:3]},
        )
    ]
    if conflicts:
        approvals.append(
            _approval(
                packet,
                approval_id="APPROVAL-WEEKLY-CALENDAR-001",
                action_type="calendar.write",
                target=conflicts[0]["second_event_id"],
                reason="Resolve the first detected overlap without silently changing the calendar.",
                reversibility="Calendar edits can be changed again, but attendees may be notified.",
                evidence_refs=result.evidence_refs,
                payload={"action": "reschedule", "conflict": conflicts[0]},
            )
        )
    return result, tuple(approvals)


def _meeting_to_decision(
    packet: TaskPacket, context: dict[str, Any], execution_batch: str
) -> WorkerReturn:
    supplied = context["workflow_inputs"][packet.workflow_id]
    actions = supplied["action_items"]
    source_ids = tuple(supplied["evidence_source_ids"])
    checks = [
        {
            "check_id": "actions-have-owner-and-due-date",
            "passed": all(item["owner"] and item["due"] for item in actions),
            "observed": len(actions),
        },
        {
            "check_id": "prior-decisions-preserved",
            "passed": bool(supplied["prior_decisions"]),
            "observed": len(supplied["prior_decisions"]),
        },
    ]
    verdict = "PASS" if all(item["passed"] for item in checks) else "HOLD"
    follow_up = {
        "decisions": supplied["prior_decisions"],
        "meeting_id": supplied["meeting_id"],
        "owners_and_deadlines": actions,
        "summary": supplied["notes"],
        "target": supplied["follow_up_target"],
    }
    result = _result(
        packet,
        execution_batch,
        outcome="The meeting has an evidence-bound decision record and owner-complete actions.",
        verdict=verdict,
        checks=checks,
        provenance=[_provenance("meeting-decision-record", source_ids)],
        summary=(
            f"{len(supplied['prior_decisions'])} decisions and {len(actions)} actions prepared."
        ),
        facts=[
            f"Meeting: {supplied['title']}",
            f"Scheduled: {supplied['scheduled_at']}",
            f"Action owners: {len({item['owner'] for item in actions})}",
        ],
        next_decision="Approve task creation and the exact follow-up payload.",
        details={
            "agenda": supplied["agenda"],
            "follow_up_draft": follow_up,
            "pre_brief": {"prior_decisions": supplied["prior_decisions"]},
        },
    )
    approvals = (
        _approval(
            packet,
            approval_id="APPROVAL-MEETING-TASKS-001",
            action_type="task.create",
            target="configured-task-system",
            reason="Owner-complete actions are drafted but not written to an external task system.",
            reversibility="Created tasks can be closed, but assignees may be notified.",
            evidence_refs=result.evidence_refs,
            payload={"action": "create-tasks", "items": actions},
        ),
        _approval(
            packet,
            approval_id="APPROVAL-MEETING-FOLLOWUP-001",
            action_type="message.send",
            target=supplied["follow_up_target"],
            reason="The recipients and exact decision record require human confirmation.",
            reversibility="A sent follow-up cannot be reliably recalled.",
            evidence_refs=result.evidence_refs,
            payload={"action": "send-follow-up", "draft": follow_up},
        ),
    )
    return result, approvals


def _evidence_to_roadmap_to_release(
    packet: TaskPacket, context: dict[str, Any], execution_batch: str
) -> WorkerReturn:
    supplied = context["workflow_inputs"][packet.workflow_id]
    option = next(
        item for item in supplied["options"] if item["option_id"] == supplied["approved_option_id"]
    )
    failed = sorted(
        item["check_id"] for item in supplied["release_checks"] if item["status"] != "PASS"
    )
    verdict = "PASS" if not failed else "HOLD"
    provenance = [
        _provenance(f"claim:{item['claim_id']}", tuple(item["source_ids"]))
        for item in supplied["claims"]
    ]
    checks = [
        {
            "check_id": "approved-option-explicit",
            "passed": True,
            "observed": option["option_id"],
        },
        {
            "check_id": "claims-have-provenance",
            "passed": all(item["source_ids"] for item in supplied["claims"]),
            "observed": len(supplied["claims"]),
        },
        {
            "check_id": "release-checks-pass",
            "passed": not failed,
            "observed": failed or "all PASS",
        },
    ]
    result = _result(
        packet,
        execution_batch,
        outcome=(
            "The approved roadmap option has a sourced delivery and release plan."
            if verdict == "PASS"
            else "The roadmap draft is prepared, but release is held by failed checks."
        ),
        verdict=verdict,
        checks=checks,
        provenance=provenance,
        summary=f"{len(supplied['claims'])} claims support option {option['option_id']}.",
        facts=[
            f"Approved option: {option['title']}",
            f"Requirements: {len(supplied['requirements'])}",
            f"Failed release checks: {len(failed)}",
        ],
        next_decision=(
            "Approve roadmap mutation and release publication."
            if verdict == "PASS"
            else "Approve the roadmap draft only; repair release checks before publication."
        ),
        details={
            "approved_option": option,
            "delivery_plan": [
                {"sequence": index, "requirement": requirement}
                for index, requirement in enumerate(supplied["requirements"], start=1)
            ],
            "failed_release_check_ids": failed,
        },
    )
    approvals: list[ApprovalItem] = [
        _approval(
            packet,
            approval_id="APPROVAL-ROADMAP-UPDATE-001",
            action_type="roadmap.update",
            target=supplied["roadmap_target"],
            reason="The selected option came from explicit user input, not agent prioritization.",
            reversibility="Roadmap changes can be reverted, but stakeholders may act on them.",
            evidence_refs=result.evidence_refs,
            payload={
                "action": "update-roadmap",
                "approved_option_id": option["option_id"],
                "requirements": supplied["requirements"],
            },
        )
    ]
    if verdict == "PASS":
        approvals.append(
            _approval(
                packet,
                approval_id="APPROVAL-RELEASE-PUBLISH-001",
                action_type="release.publish",
                target=supplied["roadmap_target"],
                reason="All supplied release checks pass, but publication remains human-owned.",
                reversibility="Published release communication may be corrected but not unseen.",
                evidence_refs=result.evidence_refs,
                payload={"action": "publish-release", "option_id": option["option_id"]},
            )
        )
    return result, tuple(approvals)


def _issue_to_draft_pr(
    packet: TaskPacket, context: dict[str, Any], execution_batch: str
) -> WorkerReturn:
    supplied = context["workflow_inputs"][packet.workflow_id]
    failed = sorted(item["check_id"] for item in supplied["checks"] if item["status"] != "PASS")
    verdict = "PASS" if not failed else "HOLD"
    provenance = [
        _provenance(f"check:{item['check_id']}", tuple(item["evidence_source_ids"]))
        for item in supplied["checks"]
    ]
    checks = [
        {
            "check_id": "deterministic-checks-pass",
            "passed": not failed,
            "observed": failed or "all PASS",
        },
        {
            "check_id": "candidate-digest-bound",
            "passed": True,
            "observed": supplied["candidate_digest"],
        },
        {
            "check_id": "impact-scope-present",
            "passed": bool(supplied["impact_paths"]),
            "observed": len(supplied["impact_paths"]),
        },
    ]
    draft_pr = {
        "body": supplied["pr_body"],
        "candidate_digest": supplied["candidate_digest"],
        "issue_number": supplied["issue_number"],
        "repository": supplied["repository"],
        "title": supplied["pr_title"],
    }
    result = _result(
        packet,
        execution_batch,
        outcome=(
            "A test-bound draft-PR payload is ready for human approval."
            if verdict == "PASS"
            else "Draft PR creation is held because deterministic checks failed."
        ),
        verdict=verdict,
        checks=checks,
        provenance=provenance,
        summary=(
            f"{len(supplied['checks']) - len(failed)}/{len(supplied['checks'])} checks passed."
        ),
        facts=[
            f"Issue: #{supplied['issue_number']} {supplied['issue_title']}",
            f"Impacted paths: {len(supplied['impact_paths'])}",
            f"Dependencies: {len(supplied['dependencies'])}",
            f"Failed checks: {len(failed)}",
        ],
        next_decision=(
            "Approve or edit the exact draft-PR payload."
            if verdict == "PASS"
            else "Fix failed checks, freeze a new candidate, and rerun."
        ),
        details={
            "dependencies": supplied["dependencies"],
            "draft_pr": draft_pr,
            "failed_check_ids": failed,
            "impact_paths": supplied["impact_paths"],
            "merge_eligibility": "NOT_EVALUATED",
        },
    )
    approvals: tuple[ApprovalItem, ...] = ()
    if verdict == "PASS":
        approvals = (
            _approval(
                packet,
                approval_id="APPROVAL-DRAFT-PR-001",
                action_type="git.pr.create",
                target=f"{supplied['repository']}#issue-{supplied['issue_number']}",
                reason="The exact draft payload is bound to passing checks and candidate digest.",
                reversibility="A draft PR can be closed; no merge permission is implied.",
                evidence_refs=result.evidence_refs,
                payload={"action": "create-draft-pr", "draft_pr": draft_pr},
            ),
        )
    return result, approvals


def _generic_outcome_pack(
    packet: TaskPacket, context: dict[str, Any], execution_batch: str
) -> WorkerReturn:
    supplied = context["workflow_inputs"][packet.workflow_id]
    entry = GENERIC_WORKFLOW_CATALOG[packet.workflow_id]
    failed = sorted(item["check_id"] for item in supplied["checks"] if item["status"] != "PASS")
    declared_actions = tuple(item["action_type"] for item in supplied["approval_actions"])
    policy_matches = declared_actions == packet.approval_required and len(declared_actions) == len(
        set(declared_actions)
    )
    checks = [
        {
            "check_id": "declared-checks-pass",
            "passed": not failed,
            "observed": failed or "all PASS",
        },
        {
            "check_id": "records-present",
            "passed": bool(supplied["records"]),
            "observed": len(supplied["records"]),
        },
        {
            "check_id": "approval-policy-exact",
            "passed": policy_matches,
            "observed": list(declared_actions),
            "expected": list(packet.approval_required),
        },
    ]
    verdict = "PASS" if all(item["passed"] for item in checks) else "HOLD"
    provenance = [
        _provenance(f"record:{item['record_id']}", tuple(item["evidence_source_ids"]))
        for item in supplied["records"]
    ] + [
        _provenance(f"check:{item['check_id']}", tuple(item["evidence_source_ids"]))
        for item in supplied["checks"]
    ]
    artifact = {
        "artifact_type": entry["output_name"],
        "objective": supplied["objective"],
        "records": supplied["records"],
        "subject_id": supplied["subject_id"],
        "target": supplied["output_target"],
        "tier": entry["tier"],
    }
    approval_policy = [
        {
            "action_type": item["action_type"],
            "target": item["target"],
            "reason": item["reason"],
            "reversibility": item["reversibility"],
            "payload": {
                "operation": item["operation"],
                "output_target": supplied["output_target"],
                "subject_id": supplied["subject_id"],
            },
        }
        for item in supplied["approval_actions"]
    ]
    result = _result(
        packet,
        execution_batch,
        outcome=(
            f"{entry['output_name']} is verified and ready for explicit approval."
            if verdict == "PASS"
            else f"{entry['output_name']} is held by deterministic validation."
        ),
        verdict=verdict,
        checks=checks,
        provenance=provenance,
        summary=(
            f"Tier {entry['tier']} · {len(supplied['records'])} evidence-backed records · "
            f"{len(failed)} failed declared checks."
        ),
        facts=[
            f"Problem: {entry['problem_solved']}",
            f"Output: {entry['output_name']}",
            f"Evidence records: {len(supplied['records'])}",
            f"Approval actions: {len(approval_policy)}",
        ],
        next_decision=(
            "Review the exact output and approval payload."
            if verdict == "PASS"
            else "Repair failed checks or the action policy, then rerun."
        ),
        details={
            "approval_policy": approval_policy,
            "artifact": artifact,
            "failed_check_ids": failed,
            "problem_solved": entry["problem_solved"],
        },
    )
    approvals: list[ApprovalItem] = []
    if verdict == "PASS":
        for index, policy in enumerate(approval_policy, start=1):
            approvals.append(
                _approval(
                    packet,
                    approval_id=f"APPROVAL-{packet.task_id}-{index:02d}",
                    action_type=policy["action_type"],
                    target=policy["target"],
                    reason=policy["reason"],
                    reversibility=policy["reversibility"],
                    evidence_refs=result.evidence_refs,
                    payload=policy["payload"],
                )
            )
    return result, tuple(approvals)


_WORKERS: dict[str, Worker] = {
    "goal-to-verified-release": _goal_to_verified_release,
    "ai-eval-release-gate": _ai_eval_release_gate,
    "weekly-pm-command-centre": _weekly_pm_command_centre,
    "meeting-to-decision": _meeting_to_decision,
    "evidence-to-roadmap-to-release": _evidence_to_roadmap_to_release,
    "issue-to-draft-pr": _issue_to_draft_pr,
}
_WORKERS.update(dict.fromkeys(GENERIC_WORKFLOW_CATALOG, _generic_outcome_pack))


def validate_worker_output(result: TaskResult, allowed_source_ids: set[str]) -> bool:
    output = result.output
    if not isinstance(output, dict) or set(output) != {
        "details",
        "mobile_review",
        "outcome",
        "provenance",
        "validation",
    }:
        return False
    validation = output.get("validation")
    review = output.get("mobile_review")
    provenance = output.get("provenance")
    if (
        not isinstance(validation, dict)
        or validation.get("verdict") not in {"PASS", "HOLD"}
        or not isinstance(validation.get("checks"), list)
        or not validation["checks"]
        or not all(type(item.get("passed")) is bool for item in validation["checks"])
        or not isinstance(review, dict)
        or review.get("status") != validation["verdict"]
        or not isinstance(provenance, list)
        or not provenance
    ):
        return False
    checks = validation["checks"]
    all_passed = all(item["passed"] is True for item in checks)
    if (validation["verdict"] == "PASS") != all_passed:
        return False
    referenced = {
        source_id
        for record in provenance
        if isinstance(record, dict)
        for source_id in record.get("source_ids", [])
    }
    return (
        bool(referenced)
        and referenced == set(result.evidence_refs)
        and referenced <= allowed_source_ids
    )


def execute_task(
    packet: TaskPacket,
    context: dict[str, Any],
    execution_batch: str,
) -> WorkerReturn:
    worker = _WORKERS.get(packet.workflow_id)
    if worker is None:
        raise ValueError(f"no worker registered for {packet.workflow_id}")
    return worker(packet, context, execution_batch)
