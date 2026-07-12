"""Implementation agent.

``ImplementationAgent`` is the provider seam (ADR-002): V1 ships the deterministic
``StdlibCrudGenerator``; an LLM-backed provider implements the same protocol in V2.

The agent works in small changes — files are grouped per plan task so the
orchestrator can commit task-by-task — and it only ever produces files for
components the plan names.
"""

from __future__ import annotations

from typing import Protocol

from pmpe.domain.errors import StepFailure
from pmpe.domain.models import (
    EngineeringPlan,
    GeneratedFile,
    Implementation,
    MvpSpec,
)
from pmpe.stacks import SUPPORTED_STACKS
from pmpe.stacks.stdlib_code import (
    api_module,
    app_init_module,
    auth_module,
    readme,
    server_module,
    storage_module,
)


class ImplementationAgent(Protocol):
    def implement(self, spec: MvpSpec, plan: EngineeringPlan) -> Implementation: ...


class StdlibCrudGenerator:
    """Deterministic template-based generator for the python-stdlib stack."""

    def implement(self, spec: MvpSpec, plan: EngineeringPlan) -> Implementation:
        if spec.preferred_stack not in SUPPORTED_STACKS:
            raise StepFailure(
                "implement", f"no code templates for stack '{spec.preferred_stack}'"
            )
        app_init = GeneratedFile("app/__init__.py", app_init_module(spec), "code")
        files_by_task: dict[str, list[GeneratedFile]] = {}
        for task in plan.tasks:
            if task.kind != "feature":
                continue
            if task.component == "storage":
                files_by_task[task.id] = [
                    app_init,
                    GeneratedFile("app/storage.py", storage_module(spec), "code"),
                ]
            elif task.component == "auth":
                files_by_task[task.id] = [
                    app_init,
                    GeneratedFile("app/auth.py", auth_module(), "code"),
                ]
            elif task.component == "api":
                files_by_task[task.id] = [
                    app_init,
                    GeneratedFile("app/api.py", api_module(spec), "code"),
                ]
            elif task.component == "server":
                files_by_task[task.id] = [
                    GeneratedFile("app/server.py", server_module(spec), "code"),
                    GeneratedFile("README.md", readme(spec), "doc"),
                ]
            else:
                raise StepFailure(
                    "implement",
                    f"plan task {task.id} names unknown component '{task.component}'",
                )

        code_by_requirement: dict[str, list[str]] = {}
        for fr in spec.functional_requirements:
            if fr.capability.startswith("entity."):
                code_by_requirement[fr.id] = ["app/storage.py", "app/api.py"]
            elif fr.capability == "auth.bearer_token":
                code_by_requirement[fr.id] = ["app/auth.py", "app/api.py"]
            elif fr.capability == "health.check":
                code_by_requirement[fr.id] = ["app/api.py", "app/server.py"]
            else:
                raise StepFailure(
                    "implement", f"{fr.id}: unsupported capability '{fr.capability}'"
                )
        return Implementation(
            files_by_task=files_by_task, code_by_requirement=code_by_requirement
        )
