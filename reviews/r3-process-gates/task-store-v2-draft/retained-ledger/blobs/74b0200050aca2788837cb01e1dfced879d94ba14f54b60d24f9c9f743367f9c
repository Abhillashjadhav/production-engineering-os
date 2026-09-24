"""Routing validation: the Engineer Router agent proposes, Python enforces (PD-05).

The router must select the MINIMUM set of specialists that covers every task,
justify each selection, and explicitly justify every profile it did not select.
Profiles are vocabulary; an agent definition file is only required for a
specialist that is actually selected — an unused persona file would be theatre.
"""

from __future__ import annotations

from typing import Any

from pmpe.agents.registry import AgentRegistry
from pmpe.domain.errors import PmpeError

# capability -> specialist profile that owns it
SPECIALIST_PROFILES: dict[str, str] = {
    "backend": "v2-backend-engineer",
    "frontend": "frontend-engineer",
    "data": "data-migration-engineer",
    "eval": "eval-engineer",
    "security": "security-engineer",
    "platform": "platform-reliability-engineer",
    "test": "v2-test-engineer",
}

ALL_PROFILES = sorted(set(SPECIALIST_PROFILES.values()))


class RoutingError(PmpeError):
    """The proposed routing decision violates minimum-routing policy."""


def validate_routing(
    tasks: list[dict[str, Any]],
    routing: dict[str, Any],
    registry: AgentRegistry,
) -> None:
    selected: list[dict[str, Any]] = list(routing.get("selected", []))
    not_selected: list[dict[str, Any]] = list(routing.get("not_selected", []))

    assigned: dict[str, str] = {}
    empty_selections: list[str] = []
    for entry in selected:
        agent = str(entry.get("agent", ""))
        entry_tasks = [str(t) for t in entry.get("tasks", [])]
        reason = str(entry.get("reason", "")).strip()
        if not registry.has(agent):
            raise RoutingError(
                f"selected specialist '{agent}' has no agent definition — "
                "create .claude/agents/" + agent + ".md before routing work to it"
            )
        if not reason:
            raise RoutingError(f"selected specialist '{agent}' has no justification")
        if not entry_tasks:
            empty_selections.append(agent)
        for task_id in entry_tasks:
            if task_id in assigned:
                raise RoutingError(
                    f"task {task_id} assigned to both {assigned[task_id]} and {agent}"
                )
            assigned[task_id] = agent

    by_id = {str(t["id"]): t for t in tasks}
    missing = sorted(set(by_id) - set(assigned))
    if missing:
        raise RoutingError(f"unrouted task(s): {', '.join(missing)}")
    unknown = sorted(set(assigned) - set(by_id))
    if unknown:
        raise RoutingError(f"routing references unknown task(s): {', '.join(unknown)}")
    if empty_selections:
        raise RoutingError(
            "selected specialist(s) with no assigned tasks — violates minimum routing: "
            + ", ".join(empty_selections)
        )

    for task_id, agent in assigned.items():
        capability = str(by_id[task_id].get("required_capability", ""))
        owner = SPECIALIST_PROFILES.get(capability)
        if owner is None:
            raise RoutingError(f"task {task_id} needs unknown capability '{capability}'")
        if owner != agent:
            raise RoutingError(
                f"task {task_id} needs capability '{capability}' owned by {owner}, "
                f"but was routed to {agent}"
            )

    selected_names = {str(e.get("agent")) for e in selected}
    explained = {str(e.get("agent")) for e in not_selected if str(e.get("reason", "")).strip()}
    unexplained = sorted(set(ALL_PROFILES) - selected_names - explained)
    if unexplained:
        raise RoutingError(
            "not_selected must explain why each unused profile is unnecessary; missing: "
            + ", ".join(unexplained)
        )
