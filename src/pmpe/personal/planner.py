"""Compile an approved personal objective into bounded workflow task packets."""

from __future__ import annotations

from typing import TypedDict

from pmpe.contracts.canonical import canonical_digest
from pmpe.personal.catalog import (
    ALL_EXTENDED_WORKFLOWS,
    GENERIC_WORKFLOW_CATALOG,
    TIER_1_WORKFLOWS,
)
from pmpe.personal.models import PersonalWorkContract, TaskPacket, create_task_packet

WORKFLOW_ORDER = TIER_1_WORKFLOWS + ALL_EXTENDED_WORKFLOWS


class WorkflowDefinition(TypedDict):
    objective: str
    allowed: tuple[str, ...]
    done: tuple[str, ...]
    budget: str
    approvals: tuple[str, ...]
    verifier: str


_WORKFLOW_DEFINITIONS: dict[str, WorkflowDefinition] = {
    "goal-to-verified-release": {
        "objective": (
            "Convert an approved goal into a release verdict bound to acceptance evidence."
        ),
        "allowed": ("evidence.read", "artifact.write", "codex.task.prepare"),
        "done": (
            "Bind the release candidate to deterministic acceptance checks.",
            "Create bounded research, build, and independent-verification packets.",
            "Hold merge and deployment for named approval.",
        ),
        "budget": "20 minutes or 12000 tokens; no external writes",
        "approvals": ("git.merge", "production.deploy"),
        "verifier": "release-evidence-reviewer",
    },
    "ai-eval-release-gate": {
        "objective": (
            "Evaluate an AI candidate against frozen quality, cost, latency, and safety gates."
        ),
        "allowed": ("evidence.read", "eval.calculate", "artifact.write"),
        "done": (
            "Run every supplied golden case before issuing a verdict.",
            "Calculate pass rate, p95 latency, average cost, and safety failures.",
            "Hold candidate release unless every frozen threshold passes.",
        ),
        "budget": "15 minutes or 8000 tokens; deterministic scoring only",
        "approvals": ("model.release",),
        "verifier": "eval-integrity-reviewer",
    },
    "weekly-pm-command-centre": {
        "objective": "Produce a weekly operating plan from commitments, messages, and schedule.",
        "allowed": ("calendar.read", "messages.read", "commitments.read", "artifact.write"),
        "done": (
            "Rank the three highest-impact open commitments deterministically.",
            "Surface schedule conflicts and requested actions.",
            "Draft, but do not apply, calendar and communication changes.",
        ),
        "budget": "10 minutes or 6000 tokens; no external writes",
        "approvals": ("calendar.write", "message.send"),
        "verifier": "weekly-plan-reviewer",
    },
    "meeting-to-decision": {
        "objective": "Prepare a meeting and close its decisions, owners, deadlines, and follow-up.",
        "allowed": ("evidence.read", "calendar.read", "artifact.write"),
        "done": (
            "Carry forward explicit prior decisions and agenda evidence.",
            "Produce owner- and deadline-complete action drafts.",
            "Hold task creation and follow-up sending for approval.",
        ),
        "budget": "10 minutes or 6000 tokens; no external writes",
        "approvals": ("task.create", "message.send"),
        "verifier": "decision-record-reviewer",
    },
    "evidence-to-roadmap-to-release": {
        "objective": (
            "Turn sourced product evidence and an explicit human option choice into a release plan."
        ),
        "allowed": ("evidence.read", "roadmap.draft", "artifact.write"),
        "done": (
            "Preserve claim-to-source provenance and expose unsupported claims.",
            "Use only the explicitly approved option; never auto-select product strategy.",
            "Hold roadmap mutation and release publication for approval.",
        ),
        "budget": "20 minutes or 12000 tokens; no product decision invention",
        "approvals": ("roadmap.update", "release.publish"),
        "verifier": "product-conformance-reviewer",
    },
    "issue-to-draft-pr": {
        "objective": "Convert an approved issue into a test-bound, reviewable draft-PR payload.",
        "allowed": ("repository.read", "tests.read", "artifact.write", "codex.task.prepare"),
        "done": (
            "Bind impact paths, dependencies, checks, and candidate digest to the issue.",
            "Issue a READY verdict only when every supplied deterministic check passes.",
            "Hold remote PR creation and merge for named approval.",
        ),
        "budget": "25 minutes or 16000 tokens; isolated workspace only",
        "approvals": ("git.pr.create", "git.merge"),
        "verifier": "independent-code-reviewer",
    },
}

for _workflow_id, _entry in GENERIC_WORKFLOW_CATALOG.items():
    _WORKFLOW_DEFINITIONS[_workflow_id] = {
        "objective": _entry["objective"],
        "allowed": _entry["allowed"],
        "done": _entry["done"],
        "budget": _entry["budget"],
        "approvals": _entry["approvals"],
        "verifier": _entry["verifier"],
    }

_PROHIBITED = (
    "calendar.write",
    "email.send",
    "message.send",
    "task.create",
    "roadmap.update",
    "release.publish",
    "model.release",
    "git.pr.create",
    "git.merge",
    "production.deploy",
    "purchase.execute",
)


def compile_task_graph(contract: PersonalWorkContract) -> tuple[TaskPacket, ...]:
    unsupported = set(contract.workflow_ids) - set(_WORKFLOW_DEFINITIONS)
    if unsupported:
        raise ValueError(f"unsupported personal workflow: {sorted(unsupported)[0]}")
    packets: list[TaskPacket] = []
    for index, workflow_id in enumerate(WORKFLOW_ORDER, start=1):
        if workflow_id not in contract.workflow_ids:
            continue
        definition = _WORKFLOW_DEFINITIONS[workflow_id]
        packets.append(
            create_task_packet(
                task_id=f"TASK-{index:03d}",
                workflow_id=workflow_id,
                objective=definition["objective"],
                input_refs=contract.workflow_source_ids[workflow_id],
                allowed_capabilities=definition["allowed"],
                prohibited_capabilities=_PROHIBITED,
                depends_on=(),
                definition_of_done=definition["done"],
                budget=definition["budget"],
                approval_required=definition["approvals"],
                verification_owner=definition["verifier"],
                contract_digest=contract.contract_digest,
            )
        )
    return tuple(packets)


def task_graph_digest(packets: tuple[TaskPacket, ...]) -> str:
    return canonical_digest({"tasks": [packet.as_dict() for packet in packets]})
