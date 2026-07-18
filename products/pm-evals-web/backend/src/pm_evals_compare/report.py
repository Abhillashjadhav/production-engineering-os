"""Deterministic report rendering: the comparison as Markdown and as JSON.

Identical comparisons render identical reports (PD-V3-07). The generation
timestamp is caller-injected and isolated to clearly labeled fields; omitting
it omits the fields entirely — nothing here reads a clock.
"""

from __future__ import annotations

import json
from typing import Any

from pm_evals_compare.compare import Comparison

REPORT_FORMAT_VERSION = 1


def to_json_report(comparison: Comparison, *, generated_at: str | None = None) -> dict[str, Any]:
    report: dict[str, Any] = {
        "report_format_version": REPORT_FORMAT_VERSION,
        "comparison": comparison.model_dump(),
    }
    if generated_at is not None:
        report["generated_at"] = generated_at
    return report


def render_json(comparison: Comparison, *, generated_at: str | None = None) -> str:
    return json.dumps(to_json_report(comparison, generated_at=generated_at), indent=2) + "\n"


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def render_markdown(comparison: Comparison, *, generated_at: str | None = None) -> str:
    c = comparison
    lines: list[str] = [
        f"# Eval comparison — {c.suite}",
        "",
        f"Baseline `{c.baseline_run_id}` vs candidate `{c.candidate_run_id}`.",
    ]
    if generated_at is not None:
        lines.append(f"Generated at: {generated_at}")
    lines += [
        "",
        f"## Verdict: {c.verdict}",
        "",
    ]
    if c.reasons:
        for reason in c.reasons:
            traces = f" (traces: {', '.join(reason.trace_ids)})" if reason.trace_ids else ""
            lines.append(f"- **{reason.kind}**: {reason.detail}{traces}")
    else:
        lines.append(
            "- All required evidence is available, no hard-gate regression exists, "
            "and configured guardrails pass."
        )
    lines += [
        "",
        "## Overall",
        "",
        "| | Baseline | Candidate | Net change |",
        "|---|---|---|---|",
        f"| Pass rate | {_pct(c.baseline_pass_rate)} | {_pct(c.candidate_pass_rate)} "
        f"| {_pct(c.net_change)} |",
        "",
        f"Matched traces: {c.matched_traces} · baseline-only: "
        f"{len(c.baseline_only_traces)} · candidate-only: {len(c.candidate_only_traces)}",
        "",
        "## Criteria",
        "",
        "| Criterion | Hard gate | Baseline | Candidate | Δ | Newly passing | Newly failing |",
        "|---|---|---|---|---|---|---|",
    ]
    for d in c.criteria:
        lines.append(
            f"| {d.criterion_id} | {'yes' if d.hard_gate else 'no'} "
            f"| {_pct(d.baseline_pass_rate)} | {_pct(d.candidate_pass_rate)} "
            f"| {_pct(d.delta)} | {len(d.newly_passing)} | {len(d.newly_failing)} |"
        )
    lines += [
        "",
        "## Guardrails",
        "",
        "Policy: **baseline-authoritative** — the baseline governs each "
        "`min_pass_rate` guardrail; a candidate may strengthen a threshold but "
        "never weaken it.",
        "",
        "| Criterion | Baseline | Candidate | Effective | Candidate effect |",
        "|---|---|---|---|---|",
    ]
    for d in c.criteria:
        g = d.guardrail
        candidate = "—" if g.candidate_threshold is None else _pct(g.candidate_threshold)
        lines.append(
            f"| {d.criterion_id} | {_pct(g.baseline_threshold)} | {candidate} "
            f"| {_pct(g.effective_threshold)} | {g.candidate_effect} |"
        )
    lines += ["", "## Changed traces", ""]
    if c.newly_failing_traces:
        lines.append("Newly failing: " + ", ".join(f"`{t}`" for t in c.newly_failing_traces))
    if c.newly_passing_traces:
        lines.append("Newly passing: " + ", ".join(f"`{t}`" for t in c.newly_passing_traces))
    if not c.newly_failing_traces and not c.newly_passing_traces:
        lines.append("No trace changed outcome on any shared criterion.")
    lines += [
        "",
        "## Evidence inputs",
        "",
        f"- Baseline digest: `{c.baseline_digest or 'n/a'}`",
        f"- Candidate digest: `{c.candidate_digest or 'n/a'}`",
        "",
    ]
    return "\n".join(lines)
