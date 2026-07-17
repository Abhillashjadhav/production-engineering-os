"""The deterministic comparison engine: locked verdict semantics (PD-V3-04/05/07).

Fixture-building helpers produce realistic runs inline; the two committed
fixture files under fixtures/ are parsed here too so the files the browser
tests will later upload are proven valid from day one.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pm_evals_compare.compare import CompareConfig, check_compatibility, compare_runs
from pm_evals_compare.models import EvalRun, parse_run
from pm_evals_compare.report import render_json, render_markdown, to_json_report

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def _run(
    run_id: str,
    *,
    suite: str = "support-copilot",
    criteria: list[dict[str, Any]] | None = None,
    traces: list[dict[str, Any]] | None = None,
) -> EvalRun:
    payload = {
        "format_version": 1,
        "run_id": run_id,
        "suite": suite,
        "criteria": criteria
        or [
            {"id": "C-ACC", "description": "Answer is accurate", "hard_gate": True},
            {"id": "C-TONE", "description": "Tone is professional", "hard_gate": False},
        ],
        "traces": traces or [],
    }
    result = parse_run(json.dumps(payload))
    assert result.ok, result.issues
    assert result.run is not None
    return result.run


def _traces(rows: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    return [
        {"trace_id": trace_id, "label": f"case {trace_id}", "results": results}
        for trace_id, results in rows.items()
    ]


def _pair(candidate_rows: dict[str, dict[str, str]]) -> tuple[EvalRun, EvalRun]:
    baseline_rows = {f"T-{i}": {"C-ACC": "pass", "C-TONE": "pass"} for i in range(1, 7)}
    baseline = _run("base-1", traces=_traces(baseline_rows))
    candidate = _run("cand-1", traces=_traces(candidate_rows))
    return baseline, candidate


_CLEAN_CANDIDATE = {f"T-{i}": {"C-ACC": "pass", "C-TONE": "pass"} for i in range(1, 7)}


# --- parsing -------------------------------------------------------------------------------


def test_not_json_reports_an_issue() -> None:
    result = parse_run("{nope", source_name="baseline")
    assert not result.ok
    assert result.issues[0].location == "baseline"
    assert "not valid JSON" in result.issues[0].message


def test_wrong_format_version_is_refused() -> None:
    result = parse_run(json.dumps({"format_version": 2}))
    assert any("unsupported format_version" in i.message for i in result.issues)


def test_unknown_fields_are_refused() -> None:
    payload = {
        "format_version": 1,
        "run_id": "r",
        "suite": "s",
        "criteria": [{"id": "C", "surprise": True}],
        "traces": [{"trace_id": "T", "results": {"C": "pass"}}],
    }
    result = parse_run(json.dumps(payload))
    assert any("surprise" in i.location for i in result.issues)


def test_duplicate_ids_and_undeclared_criteria_are_reported() -> None:
    payload = {
        "format_version": 1,
        "run_id": "r",
        "suite": "s",
        "criteria": [{"id": "C"}, {"id": "C"}],
        "traces": [
            {"trace_id": "T", "results": {"C": "pass"}},
            {"trace_id": "T", "results": {"GHOST": "fail"}},
        ],
    }
    result = parse_run(json.dumps(payload))
    blob = " ".join(i.message for i in result.issues)
    assert "duplicate criterion id" in blob
    assert "duplicate trace_id" in blob
    assert "undeclared criteria" in blob


def test_result_values_are_constrained() -> None:
    payload = {
        "format_version": 1,
        "run_id": "r",
        "suite": "s",
        "criteria": [{"id": "C"}],
        "traces": [{"trace_id": "T", "results": {"C": "maybe"}}],
    }
    result = parse_run(json.dumps(payload))
    assert not result.ok


def test_committed_fixture_files_parse_clean() -> None:
    for name in ("baseline.json", "candidate_regression.json", "candidate_improved.json"):
        result = parse_run((FIXTURES / name).read_bytes(), source_name=name)
        assert result.ok, (name, result.issues)


# --- compatibility -------------------------------------------------------------------------


def test_suite_mismatch_is_incompatible() -> None:
    a = _run("a", traces=_traces({"T-1": {"C-ACC": "pass"}}))
    b = _run("b", suite="other-suite", traces=_traces({"T-1": {"C-ACC": "pass"}}))
    assert any("suite mismatch" in p for p in check_compatibility(a, b))


def test_disjoint_traces_are_incompatible() -> None:
    a = _run("a", traces=_traces({"T-1": {"C-ACC": "pass"}}))
    b = _run("b", traces=_traces({"X-1": {"C-ACC": "pass"}}))
    assert any("no trace ids" in p for p in check_compatibility(a, b))


# --- verdicts ------------------------------------------------------------------------------


def test_clean_candidate_proceeds() -> None:
    baseline, candidate = _pair(_CLEAN_CANDIDATE)
    comparison = compare_runs(baseline, candidate)
    assert comparison.verdict == "PROCEED"
    assert comparison.reasons == []
    assert comparison.matched_traces == 6


def test_hard_gate_regression_holds_with_trace_evidence() -> None:
    rows = dict(_CLEAN_CANDIDATE)
    rows["T-3"] = {"C-ACC": "fail", "C-TONE": "pass"}
    baseline, candidate = _pair(rows)
    comparison = compare_runs(baseline, candidate)
    assert comparison.verdict == "HOLD"
    assert comparison.hard_gate_regressions == ["C-ACC"]
    reason = next(r for r in comparison.reasons if r.kind == "hard_gate_regression")
    assert reason.trace_ids == ["T-3"]  # PD-V3-05: trace-level evidence


def test_soft_criterion_regression_alone_still_proceeds() -> None:
    rows = dict(_CLEAN_CANDIDATE)
    rows["T-3"] = {"C-ACC": "pass", "C-TONE": "fail"}
    baseline, candidate = _pair(rows)
    comparison = compare_runs(baseline, candidate)
    assert comparison.verdict == "PROCEED"
    delta = next(d for d in comparison.criteria if d.criterion_id == "C-TONE")
    assert delta.newly_failing == ["T-3"]


def test_guardrail_threshold_violation_holds() -> None:
    criteria = [
        {"id": "C-ACC", "hard_gate": True},
        {"id": "C-TONE", "min_pass_rate": 0.9},
    ]
    baseline_rows = {f"T-{i}": {"C-ACC": "pass", "C-TONE": "pass"} for i in range(1, 7)}
    candidate_rows = dict(baseline_rows)
    candidate_rows["T-2"] = {"C-ACC": "pass", "C-TONE": "fail"}
    baseline = _run("b", criteria=criteria, traces=_traces(baseline_rows))
    candidate = _run("c", criteria=criteria, traces=_traces(candidate_rows))
    comparison = compare_runs(baseline, candidate)
    assert comparison.verdict == "HOLD"
    reason = next(r for r in comparison.reasons if r.kind == "guardrail")
    assert reason.criterion_id == "C-TONE" and reason.trace_ids == ["T-2"]


def test_partial_hard_gate_coverage_holds() -> None:
    rows = dict(_CLEAN_CANDIDATE)
    rows["T-4"] = {"C-TONE": "pass"}  # C-ACC result missing on a matched trace
    baseline, candidate = _pair(rows)
    comparison = compare_runs(baseline, candidate)
    assert comparison.verdict == "HOLD"
    reason = next(r for r in comparison.reasons if r.kind == "coverage")
    assert reason.criterion_id == "C-ACC" and "T-4" in reason.trace_ids


def test_thin_evidence_is_insufficient() -> None:
    baseline = _run("b", traces=_traces({"T-1": {"C-ACC": "pass", "C-TONE": "pass"}}))
    candidate = _run("c", traces=_traces({"T-1": {"C-ACC": "pass", "C-TONE": "pass"}}))
    comparison = compare_runs(baseline, candidate)
    assert comparison.verdict == "INSUFFICIENT_EVIDENCE"
    assert any(r.kind == "thin_evidence" for r in comparison.reasons)


def test_hold_outranks_thin_evidence() -> None:
    """A demonstrated hard-gate regression on thin evidence is still HOLD."""
    baseline = _run("b", traces=_traces({"T-1": {"C-ACC": "pass", "C-TONE": "pass"}}))
    candidate = _run("c", traces=_traces({"T-1": {"C-ACC": "fail", "C-TONE": "pass"}}))
    comparison = compare_runs(baseline, candidate)
    assert comparison.verdict == "HOLD"
    kinds = {r.kind for r in comparison.reasons}
    assert "hard_gate_regression" in kinds and "thin_evidence" in kinds


def test_incompatible_runs_hold() -> None:
    a = _run("a", traces=_traces({f"T-{i}": {"C-ACC": "pass"} for i in range(1, 7)}))
    b = _run(
        "b",
        suite="other-suite",
        traces=_traces({f"T-{i}": {"C-ACC": "pass"} for i in range(1, 7)}),
    )
    comparison = compare_runs(a, b)
    assert comparison.verdict == "HOLD"
    assert any(r.kind == "incompatible" for r in comparison.reasons)


def test_unevaluable_hard_gate_is_insufficient() -> None:
    criteria = [{"id": "C-ACC", "hard_gate": True}, {"id": "C-TONE"}]
    rows_b = {f"T-{i}": {"C-TONE": "pass"} for i in range(1, 7)}
    baseline = _run("b", criteria=criteria, traces=_traces(rows_b))
    candidate = _run("c", criteria=criteria, traces=_traces(rows_b))
    comparison = compare_runs(baseline, candidate)
    assert comparison.verdict == "INSUFFICIENT_EVIDENCE"
    assert any(r.kind == "unevaluable_gate" for r in comparison.reasons)


def test_min_matched_traces_is_configurable() -> None:
    baseline = _run("b", traces=_traces({"T-1": {"C-ACC": "pass", "C-TONE": "pass"}}))
    candidate = _run("c", traces=_traces({"T-1": {"C-ACC": "pass", "C-TONE": "pass"}}))
    comparison = compare_runs(baseline, candidate, config=CompareConfig(min_matched_traces=1))
    assert comparison.verdict == "PROCEED"


# --- determinism (PD-V3-07) ----------------------------------------------------------------


def test_identical_inputs_identical_outputs() -> None:
    rows = dict(_CLEAN_CANDIDATE)
    rows["T-5"] = {"C-ACC": "fail", "C-TONE": "fail"}
    b1, c1 = _pair(rows)
    b2, c2 = _pair(rows)
    first = compare_runs(b1, c1)
    second = compare_runs(b2, c2)
    assert first.model_dump() == second.model_dump()
    assert render_markdown(first) == render_markdown(second)
    assert render_json(first) == render_json(second)


def test_trace_dict_order_does_not_change_the_verdict() -> None:
    rows = dict(_CLEAN_CANDIDATE)
    reversed_rows = dict(reversed(list(rows.items())))
    b1, c1 = _pair(rows)
    b2, c2 = _pair(reversed_rows)
    assert compare_runs(b1, c1).model_dump() == compare_runs(b2, c2).model_dump()


# --- reports -------------------------------------------------------------------------------


def test_markdown_report_carries_verdict_evidence_and_digests() -> None:
    rows = dict(_CLEAN_CANDIDATE)
    rows["T-3"] = {"C-ACC": "fail", "C-TONE": "pass"}
    baseline, candidate = _pair(rows)
    comparison = compare_runs(
        baseline, candidate, baseline_digest="sha256:aaa", candidate_digest="sha256:bbb"
    )
    md = render_markdown(comparison)
    assert "## Verdict: HOLD" in md
    assert "T-3" in md and "hard_gate_regression" in md
    assert "sha256:aaa" in md and "sha256:bbb" in md


def test_json_report_round_trips_and_isolates_timestamps() -> None:
    baseline, candidate = _pair(_CLEAN_CANDIDATE)
    comparison = compare_runs(baseline, candidate)
    plain = to_json_report(comparison)
    assert "generated_at" not in plain
    stamped = to_json_report(comparison, generated_at="2026-07-17T00:00:00Z")
    assert stamped["generated_at"] == "2026-07-17T00:00:00Z"
    parsed = json.loads(render_json(comparison))
    assert parsed["comparison"]["verdict"] == "PROCEED"
    assert parsed["report_format_version"] == 1
