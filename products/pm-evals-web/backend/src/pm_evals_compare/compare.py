"""Deterministic baseline-vs-candidate comparison with locked verdict semantics.

Verdict precedence (PD-V3-04, documented and deterministic):
1. **HOLD** — any newly failing hard-gate trace; incompatible evidence;
   hard-gate result coverage below requirement; a `min_pass_rate` guardrail
   violated on the candidate.
2. **INSUFFICIENT_EVIDENCE** — fewer matched traces than the configured
   minimum; a hard-gate criterion with zero matched results (release rules
   cannot be evaluated).
3. **PROCEED** — otherwise.

HOLD outranks INSUFFICIENT_EVIDENCE: a demonstrated regression on thin
evidence is still a demonstrated regression. Identical inputs produce
identical output (no clock, no randomness, sorted iteration everywhere);
every verdict reason carries trace-level evidence (PD-V3-05).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from pm_evals_compare.models import Criterion, EvalRun, Trace

VERDICTS = ("PROCEED", "HOLD", "INSUFFICIENT_EVIDENCE")

Result = Literal["pass", "fail"]
CellState = Literal[
    "improved",
    "regressed",
    "unchanged",
    "missing",
    "insufficient",
    "conflicting",
    "not_evaluated",
]
Provenance = Literal["both", "baseline_only", "candidate_only", "neither"]


class CompareConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_matched_traces: int = Field(default=5, ge=1)
    hard_gate_coverage: float = Field(default=1.0, ge=0.0, le=1.0)


class CriterionDelta(BaseModel):
    criterion_id: str
    description: str
    hard_gate: bool
    baseline_pass_rate: float
    candidate_pass_rate: float
    delta: float
    newly_passing: list[str]
    newly_failing: list[str]
    covered_traces: int


class VerdictReason(BaseModel):
    kind: str  # hard_gate_regression | incompatible | coverage | guardrail | thin_evidence | unevaluable_gate
    criterion_id: str = ""
    trace_ids: list[str] = Field(default_factory=list)
    detail: str


class CriterionCell(BaseModel):
    """One criterion's baseline-vs-candidate outcome for a single trace (S-3).

    The state, verdict, and rationale are computed here in the domain layer; the
    frontend renders them and never re-derives an outcome.
    """

    criterion_id: str
    name: str
    hard_gate: bool
    baseline_result: Result | None
    candidate_result: Result | None
    changed: bool
    state: CellState
    verdict: str
    rationale: str
    provenance: Provenance


class TraceComparison(BaseModel):
    """One changed trace's full per-criterion detail and evidence fields (S-3)."""

    trace_id: str
    direction: Literal["improved", "regressed", "mixed"]
    changed: bool
    baseline_label: str
    baseline_notes: str
    candidate_label: str
    candidate_notes: str
    criteria: list[CriterionCell]


class Comparison(BaseModel):
    suite: str
    baseline_run_id: str
    candidate_run_id: str
    baseline_digest: str
    candidate_digest: str
    matched_traces: int
    baseline_only_traces: list[str]
    candidate_only_traces: list[str]
    baseline_pass_rate: float
    candidate_pass_rate: float
    net_change: float
    criteria: list[CriterionDelta]
    newly_passing_traces: list[str]
    newly_failing_traces: list[str]
    hard_gate_regressions: list[str]  # criterion ids with newly failing hard-gate traces
    trace_details: list[TraceComparison]  # per-criterion detail for each changed trace (S-3)
    verdict: str
    reasons: list[VerdictReason]


def check_compatibility(baseline: EvalRun, candidate: EvalRun) -> list[str]:
    """Named incompatibilities ([] = comparable)."""
    problems: list[str] = []
    if baseline.suite != candidate.suite:
        problems.append(
            f"suite mismatch: baseline is '{baseline.suite}', candidate is '{candidate.suite}'"
        )
    shared_criteria = set(baseline.criterion_ids()) & set(candidate.criterion_ids())
    if not shared_criteria:
        problems.append("the runs share no criteria — nothing is comparable")
    shared_traces = set(baseline.trace_by_id()) & set(candidate.trace_by_id())
    if not shared_traces:
        problems.append("the runs share no trace ids — nothing is comparable")
    return problems


def _pass_rate(passes: int, total: int) -> float:
    return round(passes / total, 6) if total else 0.0


def _criterion_cell(
    base_def: Criterion, cand_def: Criterion, base_trace: Trace, cand_trace: Trace
) -> CriterionCell:
    """Compute one trace/criterion cell — the whole verdict lives here (PD-V3-04)."""
    b = base_trace.results.get(base_def.id)
    c = cand_trace.results.get(base_def.id)
    hard_gate = base_def.hard_gate or cand_def.hard_gate
    metadata_conflict = base_def.hard_gate != cand_def.hard_gate

    if b is not None and c is not None:
        provenance: Provenance = "both"
        if metadata_conflict:
            state: CellState = "conflicting"
        elif b == c:
            state = "unchanged"
        elif b == "fail" and c == "pass":
            state = "improved"
        else:
            state = "regressed"
    elif b is not None:
        provenance = "baseline_only"
        state = "insufficient" if hard_gate else "missing"
    elif c is not None:
        provenance = "candidate_only"
        state = "insufficient" if hard_gate else "missing"
    else:
        provenance = "neither"
        state = "not_evaluated"

    gate = " — hard gate" if base_def.hard_gate else ""
    verdicts: dict[CellState, str] = {
        "improved": "Improved",
        "regressed": f"Regressed{gate}",
        "unchanged": "Unchanged — passing" if b == "pass" else "Unchanged — failing",
        "missing": "Not comparable — result missing on one side",
        "insufficient": "Insufficient — hard-gate result missing on one side",
        "conflicting": "Conflicting definition between runs",
        "not_evaluated": "Not evaluated on either run",
    }
    present = "baseline" if b is not None else "candidate"
    rationales: dict[CellState, str] = {
        "improved": "Baseline failed and the candidate passes.",
        "regressed": "Baseline passed and the candidate fails"
        + (" — this is a hard-gate regression." if base_def.hard_gate else "."),
        "unchanged": "Both runs pass this criterion."
        if b == "pass"
        else "Both runs fail this criterion.",
        "missing": f"Recorded on the {present} run only, so the two runs cannot be compared "
        "on this criterion for this trace.",
        "insufficient": f"This hard gate is recorded on the {present} run only; the gate "
        "cannot be evaluated for this trace.",
        "conflicting": "The criterion's hard-gate flag differs between the runs "
        f"(baseline={base_def.hard_gate}, candidate={cand_def.hard_gate}); the definitions "
        "conflict, so the results are not comparable.",
        "not_evaluated": "Neither run recorded a result for this criterion on this trace.",
    }
    return CriterionCell(
        criterion_id=base_def.id,
        name=base_def.description,
        hard_gate=base_def.hard_gate,
        baseline_result=b,
        candidate_result=c,
        changed=state in ("improved", "regressed"),
        state=state,
        verdict=verdicts[state],
        rationale=rationales[state],
        provenance=provenance,
    )


def _trace_comparison(
    trace_id: str,
    shared_criteria: list[Criterion],
    cand_defs: dict[str, Criterion],
    base_trace: Trace,
    cand_trace: Trace,
) -> TraceComparison:
    cells = [
        _criterion_cell(bc, cand_defs[bc.id], base_trace, cand_trace) for bc in shared_criteria
    ]
    improved = any(cell.state == "improved" for cell in cells)
    regressed = any(cell.state == "regressed" for cell in cells)
    direction: Literal["improved", "regressed", "mixed"] = (
        "mixed" if improved and regressed else "regressed" if regressed else "improved"
    )
    return TraceComparison(
        trace_id=trace_id,
        direction=direction,
        changed=improved or regressed,
        baseline_label=base_trace.label,
        baseline_notes=base_trace.notes,
        candidate_label=cand_trace.label,
        candidate_notes=cand_trace.notes,
        criteria=cells,
    )


def compare_runs(
    baseline: EvalRun,
    candidate: EvalRun,
    *,
    config: CompareConfig | None = None,
    baseline_digest: str = "",
    candidate_digest: str = "",
) -> Comparison:
    cfg = config or CompareConfig()
    reasons: list[VerdictReason] = []

    incompatibilities = check_compatibility(baseline, candidate)
    base_traces = baseline.trace_by_id()
    cand_traces = candidate.trace_by_id()
    matched_ids = sorted(set(base_traces) & set(cand_traces))
    shared_criteria = [c for c in baseline.criteria if c.id in set(candidate.criterion_ids())]

    criteria_deltas: list[CriterionDelta] = []
    newly_passing_traces: set[str] = set()
    newly_failing_traces: set[str] = set()
    hard_gate_regressions: list[str] = []
    base_pass = base_total = cand_pass = cand_total = 0

    for criterion in shared_criteria:
        b_pass = b_total = c_pass = c_total = covered = 0
        newly_pass: list[str] = []
        newly_fail: list[str] = []
        for trace_id in matched_ids:
            b_result = base_traces[trace_id].results.get(criterion.id)
            c_result = cand_traces[trace_id].results.get(criterion.id)
            if b_result is not None:
                b_total += 1
                b_pass += b_result == "pass"
            if c_result is not None:
                c_total += 1
                c_pass += c_result == "pass"
            if b_result is not None and c_result is not None:
                covered += 1
                if b_result == "fail" and c_result == "pass":
                    newly_pass.append(trace_id)
                elif b_result == "pass" and c_result == "fail":
                    newly_fail.append(trace_id)
        base_pass += b_pass
        base_total += b_total
        cand_pass += c_pass
        cand_total += c_total
        newly_passing_traces.update(newly_pass)
        newly_failing_traces.update(newly_fail)

        delta = CriterionDelta(
            criterion_id=criterion.id,
            description=criterion.description,
            hard_gate=criterion.hard_gate,
            baseline_pass_rate=_pass_rate(b_pass, b_total),
            candidate_pass_rate=_pass_rate(c_pass, c_total),
            delta=round(_pass_rate(c_pass, c_total) - _pass_rate(b_pass, b_total), 6),
            newly_passing=newly_pass,
            newly_failing=newly_fail,
            covered_traces=covered,
        )
        criteria_deltas.append(delta)

        if criterion.hard_gate and newly_fail:
            hard_gate_regressions.append(criterion.id)
            reasons.append(
                VerdictReason(
                    kind="hard_gate_regression",
                    criterion_id=criterion.id,
                    trace_ids=newly_fail,
                    detail=f"hard-gate criterion {criterion.id} newly fails on "
                    f"{len(newly_fail)} trace(s)",
                )
            )
        if criterion.hard_gate and matched_ids:
            coverage = covered / len(matched_ids)
            if covered and coverage < cfg.hard_gate_coverage:
                missing = [
                    t
                    for t in matched_ids
                    if criterion.id not in base_traces[t].results
                    or criterion.id not in cand_traces[t].results
                ]
                reasons.append(
                    VerdictReason(
                        kind="coverage",
                        criterion_id=criterion.id,
                        trace_ids=missing,
                        detail=f"hard-gate criterion {criterion.id} has results for only "
                        f"{covered}/{len(matched_ids)} matched traces "
                        f"(required {cfg.hard_gate_coverage:.0%})",
                    )
                )
            elif covered == 0:
                reasons.append(
                    VerdictReason(
                        kind="unevaluable_gate",
                        criterion_id=criterion.id,
                        trace_ids=list(matched_ids),
                        detail=f"hard-gate criterion {criterion.id} has no matched results — "
                        "release rules cannot be evaluated",
                    )
                )
        candidate_criterion = next(c for c in candidate.criteria if c.id == criterion.id)
        threshold = candidate_criterion.min_pass_rate or criterion.min_pass_rate
        if threshold is not None and c_total:
            rate = _pass_rate(c_pass, c_total)
            if rate < threshold:
                failing = [
                    t for t in matched_ids if cand_traces[t].results.get(criterion.id) == "fail"
                ]
                reasons.append(
                    VerdictReason(
                        kind="guardrail",
                        criterion_id=criterion.id,
                        trace_ids=failing,
                        detail=f"candidate pass rate {rate:.1%} for {criterion.id} is below "
                        f"the configured guardrail {threshold:.1%}",
                    )
                )

    for problem in incompatibilities:
        reasons.append(VerdictReason(kind="incompatible", detail=problem))
    if len(matched_ids) < cfg.min_matched_traces:
        reasons.append(
            VerdictReason(
                kind="thin_evidence",
                trace_ids=list(matched_ids),
                detail=f"only {len(matched_ids)} matched trace(s); "
                f"{cfg.min_matched_traces} required for a release-grade comparison",
            )
        )

    # S-3: per-criterion detail for every changed trace (both improved and
    # regressed), each covering EVERY shared criterion, sorted for determinism.
    cand_defs = {c.id: c for c in candidate.criteria}
    changed_trace_ids = sorted(newly_passing_traces | newly_failing_traces)
    trace_details = [
        _trace_comparison(tid, shared_criteria, cand_defs, base_traces[tid], cand_traces[tid])
        for tid in changed_trace_ids
    ]

    hold_kinds = {"hard_gate_regression", "incompatible", "coverage", "guardrail"}
    ie_kinds = {"thin_evidence", "unevaluable_gate"}
    if any(r.kind in hold_kinds for r in reasons):
        verdict = "HOLD"
    elif any(r.kind in ie_kinds for r in reasons):
        verdict = "INSUFFICIENT_EVIDENCE"
    else:
        verdict = "PROCEED"

    return Comparison(
        suite=baseline.suite,
        baseline_run_id=baseline.run_id,
        candidate_run_id=candidate.run_id,
        baseline_digest=baseline_digest,
        candidate_digest=candidate_digest,
        matched_traces=len(matched_ids),
        baseline_only_traces=sorted(set(base_traces) - set(cand_traces)),
        candidate_only_traces=sorted(set(cand_traces) - set(base_traces)),
        baseline_pass_rate=_pass_rate(base_pass, base_total),
        candidate_pass_rate=_pass_rate(cand_pass, cand_total),
        net_change=round(_pass_rate(cand_pass, cand_total) - _pass_rate(base_pass, base_total), 6),
        criteria=criteria_deltas,
        newly_passing_traces=sorted(newly_passing_traces),
        newly_failing_traces=sorted(newly_failing_traces),
        hard_gate_regressions=hard_gate_regressions,
        trace_details=trace_details,
        verdict=verdict,
        reasons=reasons,
    )
