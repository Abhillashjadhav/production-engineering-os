"""pm-evals-compare: the deterministic eval-run comparison engine.

Pure domain logic for pm-evals Web (PD-V3): parse and validate eval-run files,
check pair compatibility, compute trace-level deltas, evaluate the locked
release rules (PROCEED / HOLD / INSUFFICIENT_EVIDENCE), and render reports.
No I/O beyond the bytes handed in, no clock, no randomness, no network.
"""

from pm_evals_compare.compare import (
    CompareConfig,
    Comparison,
    CriterionDelta,
    VerdictReason,
    check_compatibility,
    compare_runs,
)
from pm_evals_compare.models import EvalRun, ParseIssue, ParseResult, parse_run
from pm_evals_compare.report import render_json, render_markdown, to_json_report

__all__ = [
    "CompareConfig",
    "Comparison",
    "CriterionDelta",
    "EvalRun",
    "ParseIssue",
    "ParseResult",
    "VerdictReason",
    "check_compatibility",
    "compare_runs",
    "parse_run",
    "render_json",
    "render_markdown",
    "to_json_report",
]
