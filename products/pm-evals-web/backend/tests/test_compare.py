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


def test_duplicate_object_key_in_results_is_refused_not_silently_coalesced() -> None:
    """json.loads keeps the LAST value for a duplicate key, so a results map with
    two entries for the same criterion silently collapses — a candidate could
    hide a 'fail' behind a trailing 'pass' (or vice versa). The parser must
    refuse duplicate object keys with a named issue, never coalesce them."""
    raw = (
        '{"format_version": 1, "run_id": "r", "suite": "s",'
        ' "criteria": [{"id": "C"}],'
        ' "traces": [{"trace_id": "T", "results": {"C": "pass", "C": "fail"}}]}'
    )
    result = parse_run(raw, source_name="candidate")
    assert not result.ok
    blob = " ".join(i.message for i in result.issues)
    assert "duplicate key" in blob
    assert "C" in blob  # the offending key is named


def test_duplicate_key_anywhere_in_the_document_is_refused() -> None:
    """Duplicate keys are ambiguous at any depth, not only in results — a
    repeated top-level field (here format_version) must also be refused."""
    raw = (
        '{"format_version": 1, "format_version": 2, "run_id": "r", "suite": "s",'
        ' "criteria": [{"id": "C"}],'
        ' "traces": [{"trace_id": "T", "results": {"C": "pass"}}]}'
    )
    result = parse_run(raw, source_name="baseline")
    assert not result.ok
    assert any("duplicate key" in i.message for i in result.issues)


def test_non_finite_numbers_are_refused() -> None:
    """json.loads accepts NaN, Infinity and -Infinity by default — non-standard
    tokens no other JSON reader need accept and that break deterministic
    re-serialization (json.dumps emits them back as bare NaN/Infinity). Any
    non-finite number must be a named refusal, wherever it appears."""
    for token in ("NaN", "Infinity", "-Infinity"):
        raw = (
            '{"format_version": 1, "run_id": "r", "suite": "s",'
            ' "config": {"threshold": ' + token + "},"
            ' "criteria": [{"id": "C"}],'
            ' "traces": [{"trace_id": "T", "results": {"C": "pass"}}]}'
        )
        result = parse_run(raw, source_name="candidate")
        assert not result.ok, token
        assert any("non-finite" in i.message for i in result.issues), token


def test_numeric_overflow_to_infinity_is_refused() -> None:
    """A finite-looking literal that overflows to inf (e.g. 1e400) is parsed by
    parse_float, NOT the bare-token parse_constant path — so it slips past a
    NaN/Infinity-token-only guard and lands as inf. The refusal must cover the
    overflow path too, or the non-finite guarantee is hollow."""
    for token in ("1e400", "-1e400"):
        raw = (
            '{"format_version": 1, "run_id": "r", "suite": "s",'
            ' "config": {"threshold": ' + token + "},"
            ' "criteria": [{"id": "C"}],'
            ' "traces": [{"trace_id": "T", "results": {"C": "pass"}}]}'
        )
        result = parse_run(raw, source_name="candidate")
        assert not result.ok, token
        assert any("non-finite" in i.message for i in result.issues), token


def test_a_valid_file_with_no_duplicates_or_non_finite_numbers_still_parses() -> None:
    """The hardening must not reject well-formed files: a run with a numeric
    config value and no repeated keys parses clean."""
    raw = (
        '{"format_version": 1, "run_id": "r", "suite": "s",'
        ' "config": {"threshold": 0.5},'
        ' "criteria": [{"id": "C"}],'
        ' "traces": [{"trace_id": "T", "results": {"C": "pass"}}]}'
    )
    result = parse_run(raw, source_name="candidate")
    assert result.ok, result.issues


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


def test_baseline_declared_guardrail_still_applies_to_the_candidate() -> None:
    """The threshold falls back to the BASELINE's declaration when the candidate
    omits one — stricter, fail-closed: a candidate cannot escape a guardrail by
    not declaring it."""
    base_criteria = [
        {"id": "C-ACC", "hard_gate": True},
        {"id": "C-TONE", "min_pass_rate": 0.9},
    ]
    cand_criteria = [
        {"id": "C-ACC", "hard_gate": True},
        {"id": "C-TONE"},  # candidate declares no threshold
    ]
    rows = {f"T-{i}": {"C-ACC": "pass", "C-TONE": "pass"} for i in range(1, 7)}
    regressed = dict(rows)
    regressed["T-2"] = {"C-ACC": "pass", "C-TONE": "fail"}
    baseline = _run("b", criteria=base_criteria, traces=_traces(rows))
    candidate = _run("c", criteria=cand_criteria, traces=_traces(regressed))
    comparison = compare_runs(baseline, candidate)
    assert comparison.verdict == "HOLD"
    assert any(r.kind == "guardrail" for r in comparison.reasons)


def test_thin_evidence_boundary_is_exact() -> None:
    """matched == min-1 is insufficient; matched == min is sufficient."""
    rows4 = {f"T-{i}": {"C-ACC": "pass", "C-TONE": "pass"} for i in range(1, 5)}
    rows5 = {f"T-{i}": {"C-ACC": "pass", "C-TONE": "pass"} for i in range(1, 6)}
    four = compare_runs(_run("b", traces=_traces(rows4)), _run("c", traces=_traces(rows4)))
    five = compare_runs(_run("b", traces=_traces(rows5)), _run("c", traces=_traces(rows5)))
    assert four.verdict == "INSUFFICIENT_EVIDENCE"
    assert five.verdict == "PROCEED"


# --- S-3 Trace Detail: per-trace, per-criterion comparison (contract S-3) -------------------

_EDGE_CRITERIA_BASE = [
    {"id": "C-REG", "description": "Regression gate", "hard_gate": True},
    {"id": "C-UNCH", "description": "Stable criterion", "hard_gate": False},
    {"id": "C-CONF", "description": "Conflicting definition", "hard_gate": False},
    {"id": "C-MISS", "description": "Baseline-only result", "hard_gate": False},
    {"id": "C-INSUF", "description": "Hard gate, one side", "hard_gate": True},
    {"id": "C-NONE", "description": "Never recorded", "hard_gate": False},
]
# candidate flips C-CONF's hard_gate → a metadata conflict on any shared trace
_EDGE_CRITERIA_CAND = [dict(c) for c in _EDGE_CRITERIA_BASE]
_EDGE_CRITERIA_CAND[2]["hard_gate"] = True


def _edge_pair() -> tuple[EvalRun, EvalRun]:
    filler = {f"F-{i}": {"C-REG": "pass", "C-UNCH": "pass"} for i in range(1, 6)}
    base_traces = [
        {
            "trace_id": "T-EDGE",
            "label": "baseline case label",
            "notes": "baseline note",
            "results": {"C-REG": "pass", "C-UNCH": "pass", "C-CONF": "pass", "C-MISS": "pass"},
        },
        *_traces(filler),
    ]
    cand_traces = [
        {
            "trace_id": "T-EDGE",
            "label": "candidate case label",
            "notes": "candidate note",
            # C-CONF: same result as baseline (pass) but a differing hard_gate flag
            # → "conflicting" (an unchanged result whose definition still differs)
            "results": {"C-REG": "fail", "C-UNCH": "pass", "C-CONF": "pass", "C-INSUF": "fail"},
        },
        *_traces(filler),
    ]
    baseline = _run("b", criteria=_EDGE_CRITERIA_BASE, traces=base_traces)
    candidate = _run("c", criteria=_EDGE_CRITERIA_CAND, traces=cand_traces)
    return baseline, candidate


def _cells(comparison: Any, trace_id: str) -> dict[str, Any]:
    detail = next(t for t in comparison.trace_details if t.trace_id == trace_id)
    return {c.criterion_id: c for c in detail.criteria}


def test_trace_details_exist_only_for_changed_traces() -> None:
    baseline, candidate = _edge_pair()
    comparison = compare_runs(baseline, candidate)
    # only T-EDGE changed (a hard-gate regression); the 5 filler traces are unchanged
    assert [t.trace_id for t in comparison.trace_details] == ["T-EDGE"]


def test_a_changed_trace_lists_every_shared_criterion_not_only_flips() -> None:
    baseline, candidate = _edge_pair()
    comparison = compare_runs(baseline, candidate)
    detail = comparison.trace_details[0]
    # the contract requires per-criterion baseline vs candidate for EVERY criterion,
    # not just the flipped ones — all six shared criteria appear, in criterion order
    assert [c.criterion_id for c in detail.criteria] == [
        "C-REG",
        "C-UNCH",
        "C-CONF",
        "C-MISS",
        "C-INSUF",
        "C-NONE",
    ]


def test_every_criterion_cell_state_is_computed_in_the_domain() -> None:
    baseline, candidate = _edge_pair()
    comparison = compare_runs(baseline, candidate)
    cells = _cells(comparison, "T-EDGE")
    assert (
        cells["C-REG"].state,
        cells["C-REG"].baseline_result,
        cells["C-REG"].candidate_result,
    ) == (
        "regressed",
        "pass",
        "fail",
    )
    assert cells["C-REG"].changed is True and cells["C-REG"].hard_gate is True
    assert cells["C-UNCH"].state == "unchanged" and cells["C-UNCH"].changed is False
    assert cells["C-CONF"].state == "conflicting"  # hard_gate differs between runs
    assert cells["C-MISS"].state == "missing" and cells["C-MISS"].provenance == "baseline_only"
    assert (
        cells["C-INSUF"].state == "insufficient"
        and cells["C-INSUF"].provenance == "candidate_only"
    )
    assert cells["C-NONE"].state == "not_evaluated" and cells["C-NONE"].provenance == "neither"


def test_each_cell_carries_a_verdict_and_rationale() -> None:
    baseline, candidate = _edge_pair()
    cells = _cells(compare_runs(baseline, candidate), "T-EDGE")
    for cell in cells.values():
        assert cell.verdict, f"{cell.criterion_id} needs a verdict"
        assert cell.rationale, f"{cell.criterion_id} needs a rationale"
    assert "hard-gate" in cells["C-REG"].rationale.lower()


def test_trace_detail_carries_both_sides_evidence_fields() -> None:
    baseline, candidate = _edge_pair()
    detail = compare_runs(baseline, candidate).trace_details[0]
    assert detail.baseline_label == "baseline case label"
    assert detail.candidate_label == "candidate case label"
    assert detail.baseline_notes == "baseline note"
    assert detail.candidate_notes == "candidate note"


def test_trace_direction_is_mixed_when_both_improve_and_regress() -> None:
    base_traces = [
        {
            "trace_id": "T-MIX",
            "results": {"C-REG": "pass", "C-UNCH": "fail"},
        },
        *_traces({f"F-{i}": {"C-REG": "pass", "C-UNCH": "pass"} for i in range(1, 6)}),
    ]
    cand_traces = [
        {
            "trace_id": "T-MIX",
            "results": {"C-REG": "fail", "C-UNCH": "pass"},  # C-REG regressed, C-UNCH improved
        },
        *_traces({f"F-{i}": {"C-REG": "pass", "C-UNCH": "pass"} for i in range(1, 6)}),
    ]
    baseline = _run("b", criteria=_EDGE_CRITERIA_BASE, traces=base_traces)
    candidate = _run("c", criteria=_EDGE_CRITERIA_BASE, traces=cand_traces)
    detail = next(
        t for t in compare_runs(baseline, candidate).trace_details if t.trace_id == "T-MIX"
    )
    assert detail.direction == "mixed"


def test_trace_details_are_deterministic() -> None:
    baseline, candidate = _edge_pair()
    first = compare_runs(baseline, candidate).model_dump()
    second = compare_runs(baseline, candidate).model_dump()
    assert first == second
    assert [t["trace_id"] for t in first["trace_details"]] == ["T-EDGE"]


def test_a_flip_on_a_metadata_conflicting_criterion_is_still_a_regression() -> None:
    """A criterion whose hard_gate flag changed between runs but whose result
    flips pass->fail must render as a *regressed* (changed) cell — never masked
    to 'conflicting' or a trace mislabeled 'improved'. The cell direction must
    agree with the engine's own newly_failing_traces aggregation."""
    base_criteria = [
        {"id": "C-X", "description": "Was a hard gate", "hard_gate": True},
        {"id": "C-Y", "description": "Soft", "hard_gate": False},
    ]
    cand_criteria = [
        {"id": "C-X", "description": "Was a hard gate", "hard_gate": False},  # demoted
        {"id": "C-Y", "description": "Soft", "hard_gate": False},
    ]
    filler = {f"F-{i}": {"C-X": "pass", "C-Y": "pass"} for i in range(1, 6)}
    base = _run(
        "b",
        criteria=base_criteria,
        traces=[{"trace_id": "T", "results": {"C-X": "pass", "C-Y": "pass"}}, *_traces(filler)],
    )
    cand = _run(
        "c",
        criteria=cand_criteria,
        traces=[{"trace_id": "T", "results": {"C-X": "fail", "C-Y": "pass"}}, *_traces(filler)],
    )
    comparison = compare_runs(base, cand)
    assert "T" in comparison.newly_failing_traces  # the aggregation sees the flip
    detail = next(t for t in comparison.trace_details if t.trace_id == "T")
    assert detail.direction == "regressed"  # NOT the old "improved" fallback
    cell = next(c for c in detail.criteria if c.criterion_id == "C-X")
    assert cell.state == "regressed" and cell.changed is True
    assert "differs between the runs" in cell.rationale  # the conflict is disclosed, not hidden
