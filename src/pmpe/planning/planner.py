"""Deterministic engineering planner for the python-stdlib-crud-api stack.

The plan is a pure function of the spec: same spec, same plan. Tasks are derived
from capabilities, never invented; every functional requirement must land in at
least one task or the traceability gate will refuse the merge later.
"""

from __future__ import annotations

from pmpe.domain.errors import PmpeError
from pmpe.domain.models import EngineeringPlan, FunctionalRequirement, MvpSpec, PlanTask

_ENTITY_CAPABILITIES = (
    "entity.create",
    "entity.read",
    "entity.update",
    "entity.delete",
    "entity.list",
)


def _complexity(requirement_count: int, component: str) -> str:
    if component == "auth":
        return "M"  # security-sensitive work is never "small"
    if requirement_count >= 4:
        return "L"
    if requirement_count >= 2:
        return "M"
    return "S"


def _collection_route(entity_name: str) -> str:
    return "/" + entity_name.lower() + "s"


class EngineeringPlanner:
    def plan(self, spec: MvpSpec) -> EngineeringPlan:
        frs = spec.functional_requirements
        auth_frs = [f for f in frs if f.capability == "auth.bearer_token"]
        health_frs = [f for f in frs if f.capability == "health.check"]
        entity_frs: dict[str, list[FunctionalRequirement]] = {}
        for f in frs:
            if f.capability in _ENTITY_CAPABILITIES and f.entity:
                entity_frs.setdefault(f.entity, []).append(f)

        tasks: list[PlanTask] = []
        counter = 1

        def add(
            title: str,
            component: str,
            kind: str,
            requirement_ids: list[str],
            depends_on: list[str],
            complexity: str,
        ) -> PlanTask:
            nonlocal counter
            task = PlanTask(
                id=f"T-{counter:03d}",
                title=title,
                component=component,
                kind=kind,
                requirement_ids=requirement_ids,
                depends_on=depends_on,
                complexity=complexity,
            )
            counter += 1
            tasks.append(task)
            return task

        scaffold = add(
            "Scaffold workspace (package layout, gitignore, README stub)",
            "project",
            "scaffold",
            [],
            [],
            "S",
        )
        add(
            "Generated test suite (written before implementation)",
            "tests",
            "test",
            [f.id for f in frs],
            [scaffold.id],
            "M",
        )

        feature_deps_for_api: list[str] = []
        for entity_name in sorted(entity_frs):
            ids = [f.id for f in entity_frs[entity_name]]
            task = add(
                f"Storage layer for {entity_name} (SQLite, parameterized queries)",
                "storage",
                "feature",
                ids,
                [scaffold.id],
                _complexity(len(ids), "storage"),
            )
            feature_deps_for_api.append(task.id)

        if auth_frs:
            task = add(
                "Bearer-token auth (env-injected token, constant-time compare)",
                "auth",
                "feature",
                [f.id for f in auth_frs],
                [scaffold.id],
                _complexity(len(auth_frs), "auth"),
            )
            feature_deps_for_api.append(task.id)

        api_req_ids = sorted(
            {f.id for group in entity_frs.values() for f in group}
            | {f.id for f in auth_frs}
            | {f.id for f in health_frs}
        )
        api_task = add(
            "HTTP API handlers (routing, request validation, JSON errors)",
            "api",
            "feature",
            api_req_ids,
            feature_deps_for_api or [scaffold.id],
            _complexity(len(api_req_ids), "api"),
        )
        add(
            "Server entrypoint, configuration, and product README",
            "server",
            "feature",
            [f.id for f in health_frs] or api_req_ids[:1],
            [api_task.id],
            "S",
        )

        order = [t.id for t in tasks]  # insertion order is topological — verified below
        graph = {t.id: list(t.depends_on) for t in tasks}
        position = {tid: i for i, tid in enumerate(order)}
        for task in tasks:
            for dep in task.depends_on:
                if position[dep] >= position[task.id]:
                    raise PmpeError(
                        f"planner produced a non-topological order: {dep} must precede "
                        f"{task.id} — planner bug, not a spec problem"
                    )

        components = ["project", "tests"]
        if entity_frs:
            components.append("storage")
        if auth_frs:
            components.append("auth")
        components.append("api")

        data_model = [
            "{name}({fields} + id, created_at, updated_at)".format(
                name=e.name,
                fields=", ".join(f"{fld.name}: {fld.type}" for fld in e.fields),
            )
            for e in spec.entities
        ]

        apis: list[str] = []
        if health_frs:
            apis.append("GET /health")
        for entity_name in sorted(entity_frs):
            route = _collection_route(entity_name)
            caps = {f.capability for f in entity_frs[entity_name]}
            if "entity.create" in caps:
                apis.append(f"POST {route}")
            if "entity.list" in caps:
                apis.append(f"GET {route}")
            if "entity.read" in caps:
                apis.append(f"GET {route}/{{id}}")
            if "entity.update" in caps:
                apis.append(f"PATCH {route}/{{id}}")
            if "entity.delete" in caps:
                apis.append(f"DELETE {route}/{{id}}")

        risks = [r.description for r in spec.risks]
        if auth_frs:
            risks.append(
                "Auth is security-sensitive: token handling reviewed by the security gate "
                "and flagged medium-risk by policy"
            )

        return EngineeringPlan(
            tasks=tasks,
            order=order,
            graph=graph,
            components=components,
            data_model=data_model,
            apis=apis,
            risks=risks,
        )
