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

from pydantic import BaseModel, ConfigDict, Field

from pm_evals_compare.models import EvalRun

VERDICTS = ("PROCEED", "HOLD", "INSUFFICIENT_EVIDENCE")


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
        verdict=verdict,
        reasons=reasons,
    )
