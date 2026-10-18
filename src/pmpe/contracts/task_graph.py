"""Bound task dependencies for build context; completion requires separate trusted proof.

The current core executes and verifies a whole candidate. This graph does not turn a
dependency-ready label into a completed task or authorize skipping any protected check.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from dataclasses import asdict, dataclass
from typing import Any

from pmpe.contracts.acceptance import AcceptanceBuildPlan
from pmpe.contracts.canonical import canonical_digest

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
_SAFE_FILE = re.compile(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MODE = "whole_candidate_with_dependency_context"
_GRAPH_FIELDS = frozenset({"plan_digest", "architecture_digest", "tasks"})
_TASK_FIELDS = frozenset(
    {
        "task_id",
        "requirement_refs",
        "acceptance_ids",
        "prerequisites",
        "data_owners",
        "interface_owners",
        "allowed_files",
        "outputs",
        "affected_checks",
    }
)
_MAX_TASK_ID = 128
_MAX_LIST_ITEMS = 64
_MAX_ITEM_LENGTH = 1024


class TaskGraphError(ValueError):
    """An explicit graph cannot be bound to the approved acceptance plan."""

    def __init__(self, code: str, subject: str) -> None:
        self.code = code
        self.subject = subject
        super().__init__(f"{code}:{subject}")


@dataclass(frozen=True)
class GraphTask:
    task_id: str
    requirement_refs: tuple[str, ...]
    acceptance_ids: tuple[str, ...]
    prerequisites: tuple[str, ...]
    data_owners: tuple[str, ...]
    interface_owners: tuple[str, ...]
    allowed_files: tuple[str, ...]
    outputs: tuple[str, ...]
    affected_checks: tuple[str, ...]


@dataclass(frozen=True)
class CompiledTaskGraph:
    plan_digest: str
    architecture_digest: str | None
    tasks: tuple[GraphTask, ...]
    graph_digest: str
    execution_mode: str = _MODE

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def completed_slice(self, completed_ids: Collection[str]) -> tuple[GraphTask, ...]:
        """Check a caller's claimed completions for dependency closure; never prove them."""

        completed = set(completed_ids)
        known = {task.task_id for task in self.tasks}
        for unknown in sorted(completed - known):
            raise TaskGraphError("UNKNOWN_COMPLETED_TASK", unknown)
        for task in self.tasks:
            if task.task_id in completed and not set(task.prerequisites) <= completed:
                raise TaskGraphError("PREREQUISITE_INCOMPLETE", task.task_id)
        return tuple(task for task in self.tasks if task.task_id in completed)

    def ready(self, completed_ids: Collection[str]) -> tuple[GraphTask, ...]:
        """Select prerequisite-ready tasks from externally verified completions."""

        completed = {task.task_id for task in self.completed_slice(completed_ids)}
        return tuple(
            task
            for task in self.tasks
            if task.task_id not in completed and set(task.prerequisites) <= completed
        )


def _strings(
    raw: Mapping[str, Any], field: str, task_id: str, *, required: bool
) -> tuple[str, ...]:
    value = raw.get(field)
    if not isinstance(value, list) or (required and not value):
        raise TaskGraphError(f"{field.upper()}_MISSING", task_id)
    if len(value) > _MAX_LIST_ITEMS or any(
        isinstance(item, str) and len(item) > _MAX_ITEM_LENGTH for item in value
    ):
        raise TaskGraphError(f"{field.upper()}_LIMIT_EXCEEDED", task_id)
    if any(not isinstance(item, str) or not item for item in value):
        raise TaskGraphError(f"{field.upper()}_INVALID", task_id)
    if len(value) != len(set(value)):
        raise TaskGraphError(f"{field.upper()}_DUPLICATE", task_id)
    return tuple(sorted(value))


def _reject_unknown_fields(raw: Mapping[str, Any], allowed: frozenset[str], *, code: str) -> None:
    for field in raw:
        if not isinstance(field, str) or field not in allowed:
            raise TaskGraphError(code, str(field)[:_MAX_ITEM_LENGTH])


def _has_path_overlap(left: str, right: str) -> bool:
    return left == right or left.startswith(f"{right}/") or right.startswith(f"{left}/")


def _check_ownership(tasks: tuple[GraphTask, ...], protected: Collection[str]) -> None:
    owners: dict[str, dict[str, str]] = {
        "FILE": {},
        "DATA": {},
        "INTERFACE": {},
    }
    for task in tasks:
        for path in task.allowed_files:
            if not _SAFE_FILE.fullmatch(path) or any(
                part in {".", ".."} for part in path.split("/")
            ):
                raise TaskGraphError("UNSAFE_ALLOWED_FILE", path)
            if any(_has_path_overlap(path, item) for item in protected):
                raise TaskGraphError("PROTECTED_FILE", path)
        for kind, entries in (
            ("FILE", task.allowed_files),
            ("DATA", task.data_owners),
            ("INTERFACE", task.interface_owners),
        ):
            for entry in entries:
                for existing in owners[kind]:
                    conflict = (
                        _has_path_overlap(entry, existing) if kind == "FILE" else entry == existing
                    )
                    if conflict:
                        raise TaskGraphError(f"{kind}_OWNER_CONFLICT", entry)
                owners[kind][entry] = task.task_id


def _check_dependencies(tasks: tuple[GraphTask, ...]) -> None:
    by_id = {task.task_id: task for task in tasks}
    dependents: dict[str, list[str]] = {task.task_id: [] for task in tasks}
    remaining: dict[str, int] = {}
    for task in tasks:
        remaining[task.task_id] = len(task.prerequisites)
        for prerequisite in task.prerequisites:
            if prerequisite not in by_id:
                raise TaskGraphError("UNKNOWN_PREREQUISITE", prerequisite)
            dependents[prerequisite].append(task.task_id)
    ready = [task_id for task_id, count in remaining.items() if count == 0]
    processed = 0
    while ready:
        processed += 1
        for dependent in dependents[ready.pop()]:
            remaining[dependent] -= 1
            if remaining[dependent] == 0:
                ready.append(dependent)
    if processed != len(tasks):
        raise TaskGraphError(
            "DEPENDENCY_CYCLE", min(key for key, count in remaining.items() if count)
        )


def compile_task_graph(
    plan: AcceptanceBuildPlan,
    mapping: Mapping[str, Any] | None = None,
    *,
    protected_paths: Collection[str] = (),
) -> CompiledTaskGraph:
    """Validate an optional graph against exact plan IDs and bind its immutable digest.

    Missing architecture/task decomposition preserves the existing whole-candidate
    behavior. An explicit graph informs dependency context; the current runtime must
    still perform baseline RED and final whole-plan checks before any success claim.
    """

    criterion_requirements = {
        item.criterion_id: frozenset(item.requirement_refs) for item in plan.criteria
    }
    protected = (*protected_paths, *(path for path, _digest in plan.trusted_test_digests))
    architecture_digest: str | None = None
    tasks: tuple[GraphTask, ...]
    if mapping is None:
        tasks = (
            GraphTask(
                "WHOLE-CANDIDATE",
                tuple(sorted(plan.requirements)),
                tuple(sorted(criterion_requirements)),
                (),
                (),
                (),
                (),
                ("whole verified candidate",),
                tuple(sorted(criterion_requirements)),
            ),
        )
    else:
        _reject_unknown_fields(mapping, _GRAPH_FIELDS, code="UNKNOWN_GRAPH_FIELD")
        if mapping.get("plan_digest") != plan.plan_digest:
            raise TaskGraphError("PLAN_DIGEST_MISMATCH", plan.plan_digest)
        architecture_digest = mapping.get("architecture_digest")
        if architecture_digest is None:
            raise TaskGraphError("ARCHITECTURE_DIGEST_MISSING", plan.plan_digest)
        if not isinstance(architecture_digest, str) or not _DIGEST.fullmatch(architecture_digest):
            raise TaskGraphError("ARCHITECTURE_DIGEST_INVALID", plan.plan_digest)
        raw_tasks = mapping.get("tasks")
        if not isinstance(raw_tasks, list) or not raw_tasks:
            raise TaskGraphError("TASKS_MISSING", plan.plan_digest)
        if len(raw_tasks) > 256:
            raise TaskGraphError("TASK_LIMIT_EXCEEDED", plan.plan_digest)
        seen: set[str] = set()
        parsed: list[GraphTask] = []
        for raw in raw_tasks:
            if not isinstance(raw, Mapping):
                raise TaskGraphError("TASK_INVALID", plan.plan_digest)
            _reject_unknown_fields(raw, _TASK_FIELDS, code="UNKNOWN_TASK_FIELD")
            task_id = raw.get("task_id")
            if (
                not isinstance(task_id, str)
                or len(task_id) > _MAX_TASK_ID
                or not _ID.fullmatch(task_id)
            ):
                raise TaskGraphError("TASK_ID_INVALID", str(task_id))
            if task_id in seen:
                raise TaskGraphError("DUPLICATE_TASK_ID", task_id)
            seen.add(task_id)
            parsed.append(
                GraphTask(
                    task_id,
                    _strings(raw, "requirement_refs", task_id, required=True),
                    _strings(raw, "acceptance_ids", task_id, required=True),
                    _strings(raw, "prerequisites", task_id, required=False),
                    _strings(raw, "data_owners", task_id, required=False),
                    _strings(raw, "interface_owners", task_id, required=False),
                    _strings(raw, "allowed_files", task_id, required=True),
                    _strings(raw, "outputs", task_id, required=True),
                    _strings(raw, "affected_checks", task_id, required=True),
                )
            )
        tasks = tuple(sorted(parsed, key=lambda task: task.task_id))
        requirements = set(plan.requirements)
        criteria = set(criterion_requirements)
        for task in tasks:
            for ref in task.requirement_refs:
                if ref not in requirements:
                    raise TaskGraphError("UNKNOWN_REQUIREMENT_ID", ref)
            for criterion_id in (*task.acceptance_ids, *task.affected_checks):
                if criterion_id not in criteria:
                    raise TaskGraphError("UNKNOWN_ACCEPTANCE_ID", criterion_id)
            for criterion_id in task.acceptance_ids:
                if not criterion_requirements[criterion_id].intersection(task.requirement_refs):
                    raise TaskGraphError("ACCEPTANCE_MISMATCH", criterion_id)
                if criterion_id not in task.affected_checks:
                    raise TaskGraphError("AFFECTED_CHECKS_UNCOVERED", criterion_id)
        for requirement in sorted(
            requirements - {ref for task in tasks for ref in task.requirement_refs}
        ):
            raise TaskGraphError("REQUIREMENT_UNCOVERED", requirement)
        for criterion in sorted(criteria - {ref for task in tasks for ref in task.acceptance_ids}):
            raise TaskGraphError("ACCEPTANCE_UNCOVERED", criterion)
        _check_dependencies(tasks)
        _check_ownership(tasks, protected)
    shell = {
        "plan_digest": plan.plan_digest,
        "architecture_digest": architecture_digest,
        "tasks": [asdict(task) for task in tasks],
        "execution_mode": _MODE,
    }
    return CompiledTaskGraph(
        plan_digest=plan.plan_digest,
        architecture_digest=architecture_digest,
        tasks=tasks,
        graph_digest=canonical_digest(shell),
    )
