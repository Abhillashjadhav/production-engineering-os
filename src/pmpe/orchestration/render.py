"""Markdown rendering for run artifacts (plan, architecture, ADRs, review)."""

from __future__ import annotations

from pmpe.domain.models import (
    Adr,
    ArchitectureOutput,
    EngineeringPlan,
    GeneratedFile,
)


def _generated(path: str, content: str) -> GeneratedFile:
    return GeneratedFile(path=path, content=content, kind="code")


def _plan_markdown(plan: EngineeringPlan) -> str:
    lines = [
        "# Engineering plan",
        "",
        "| Task | Title | Component | Covers | Depends on | Size |",
        "|---|---|---|---|---|---|",
    ]
    for t in plan.tasks:
        lines.append(
            f"| {t.id} | {t.title} | {t.component} | {', '.join(t.requirement_ids) or '—'} "
            f"| {', '.join(t.depends_on) or '—'} | {t.complexity} |"
        )
    lines += [
        "",
        f"Order: {' → '.join(plan.order)}",
        "",
        f"APIs: {', '.join(plan.apis)}",
        "",
        "Risks:",
        *[f"- {r}" for r in plan.risks],
    ]
    return "\n".join(lines) + "\n"


def _architecture_markdown(arch: ArchitectureOutput) -> str:
    lines = ["# Architecture", "", arch.doc.overview, "", "## Components"]
    lines += [f"- **{name}**: {desc}" for name, desc in arch.doc.components.items()]
    lines += ["", "## Implications"]
    lines += [f"- **{k}**: {v}" for k, v in arch.doc.implications.items()]
    lines += ["", "## Decisions"]
    lines += [f"- {adr.id}: {adr.title}" for adr in arch.adrs]
    return "\n".join(lines) + "\n"


def _adr_markdown(adr: Adr) -> str:
    return (
        f"# {adr.id}: {adr.title}\n\n"
        f"Risk: {adr.risk.value} · Reversibility: {adr.reversibility} · "
        f"Covers: {', '.join(adr.requirement_ids) or '—'}\n\n"
        f"## Context\n{adr.context}\n\n## Decision\n{adr.decision}\n\n"
        f"## Consequences\n{adr.consequences}\n"
    )
