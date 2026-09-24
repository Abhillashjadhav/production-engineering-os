"""Test architect — delegates to the stack adapter's test templates.

The contract this module owns: tests exist for every functional requirement,
they carry ``Covers:`` markers, and they are handed to the pipeline BEFORE any
implementation file exists (the orchestrator enforces the order; confirm_red
proves it at runtime).
"""

from __future__ import annotations

from pmpe.domain.errors import StepFailure
from pmpe.domain.models import EngineeringPlan, GeneratedTests, MvpSpec
from pmpe.stacks import SUPPORTED_STACKS
from pmpe.stacks.stdlib_tests import generate_tests


class TestArchitect:
    def design(self, spec: MvpSpec, plan: EngineeringPlan) -> GeneratedTests:
        if spec.preferred_stack not in SUPPORTED_STACKS:
            raise StepFailure(
                "generate_tests",
                f"no test templates for stack '{spec.preferred_stack}'",
            )
        generated = generate_tests(spec)
        missing = [
            fr.id
            for fr in spec.functional_requirements
            if not generated.tests_by_requirement.get(fr.id)
        ]
        if missing:
            raise StepFailure(
                "generate_tests",
                "generated suite does not cover requirement(s): " + ", ".join(missing),
            )
        return generated
