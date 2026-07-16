"""Requirement-to-deployment traceability.

A requirement is traceable when it maps to plan task(s), ADR(s), code file(s),
and test(s). Deployment evidence is attached when available but is not a gap
criterion — the merge gate runs before deployment by design.
"""

from __future__ import annotations

from pathlib import Path

from pmpe.domain.models import (
    DeploymentResult,
    EngineeringPlan,
    Finding,
    MvpSpec,
    TraceabilityEntry,
    TraceabilityReport,
)


class TraceabilityBuilder:
    def build(
        self,
        *,
        spec: MvpSpec,
        plan: EngineeringPlan,
        adr_ids_by_requirement: dict[str, list[str]],
        tests_by_requirement: dict[str, list[str]],
        code_by_requirement: dict[str, list[str]],
        findings: list[Finding],
        deployment: DeploymentResult | None,
        workspace: Path | None = None,
    ) -> TraceabilityReport:
        entries: list[TraceabilityEntry] = []
        gaps: list[str] = []
        evidence = ""
        if deployment is not None and deployment.healthy and deployment.journey_passed:
            evidence = f"{deployment.environment} deploy verified: {deployment.details}"

        for fr in spec.functional_requirements:
            tasks = [t.id for t in plan.tasks if fr.id in t.requirement_ids]
            adrs = adr_ids_by_requirement.get(fr.id, [])
            code = code_by_requirement.get(fr.id, [])
            if workspace is not None:
                # the mapping is the generator's claim; the merge gate needs disk truth
                missing = [c for c in code if not (workspace / c).exists()]
                for path in missing:
                    gaps.append(f"{fr.id} maps to '{path}' which does not exist on disk")
                code = [c for c in code if c not in missing]
            tests = tests_by_requirement.get(fr.id, [])
            finding_ids = [
                f.id for f in findings if f.file and any(f.file in c or c in f.file for c in code)
            ]
            entries.append(
                TraceabilityEntry(
                    requirement_id=fr.id,
                    tasks=tasks,
                    adrs=adrs,
                    code_files=code,
                    tests=tests,
                    finding_ids=finding_ids,
                    deployment_evidence=evidence,
                )
            )
            if not tasks:
                gaps.append(f"{fr.id} maps to no plan task")
            if not adrs:
                gaps.append(f"{fr.id} maps to no architecture decision")
            if not code:
                gaps.append(f"{fr.id} maps to no code")
            if not tests:
                gaps.append(f"{fr.id} has no tests")

        return TraceabilityReport(entries=entries, complete=not gaps, gaps=gaps)
