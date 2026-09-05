"""Product-independent connection checks and explicit baseline binding."""

from __future__ import annotations

from .models import Observation, RunEnvelope, canonical_run_digest


def compatible_check(left: Observation, right: Observation) -> bool:
    return (
        left.case == right.case
        and left.evaluation == right.evaluation
        and left.location.component_id == right.location.component_id
        and left.location.stage_id == right.location.stage_id
        and left.location.parameter_id == right.location.parameter_id
        and left.unit == right.unit
        and left.higher_is_better == right.higher_is_better
    )


def bind_baseline(
    run: RunEnvelope, baseline: RunEnvelope, *, stored_digest: str | None = None
) -> RunEnvelope:
    """Bind an explicitly selected baseline, never choose or approve one implicitly.

    An existing server ledger's digest must be supplied by a trusted receipt. For
    newly imported baselines, the canonical digest is the server's storage digest.
    """
    if (run.product.id, run.product.environment) != (
        baseline.product.id,
        baseline.product.environment,
    ):
        raise ValueError("baseline belongs to a different product or environment")
    if run.run_id == baseline.run_id:
        raise ValueError("a run cannot be its own baseline")
    bound = run.model_copy(deep=True)
    bound.comparison.run_id = baseline.run_id
    bound.comparison.sha256 = stored_digest or canonical_run_digest(baseline)
    previous = {item.observation_id: item for item in baseline.observations}
    for item in bound.observations:
        prior = previous.get(item.observation_id)
        if prior is not None and compatible_check(item, prior):
            item.expected_value = prior.current_value
    return RunEnvelope.model_validate(bound.model_dump(mode="python"))


def comparison_reason(
    run: RunEnvelope, observation: Observation, baseline: RunEnvelope | None
) -> str:
    if baseline is None:
        return "No verified baseline is available. Select and import a baseline with its digest."
    if baseline.observed_at >= run.observed_at:
        return "The selected baseline is not earlier than this run."
    prior = next(
        (o for o in baseline.observations if o.observation_id == observation.observation_id), None
    )
    if prior is None or prior.case != observation.case:
        return "The baseline has no matching case and input."
    if prior.evaluation.suite_version != observation.evaluation.suite_version:
        return "The evaluation versions differ; these results cannot be compared."
    if not compatible_check(observation, prior):
        return "The check definition, location, or measurement unit differs."
    if prior.status != "PASS" or prior.current_value is None:
        return "The baseline check did not pass with a measured value."
    if prior.current_value != observation.expected_value:
        return "The expected value does not exactly match the baseline measurement."
    return "The selected baseline is not healthy enough to establish a regression."


def connection_report(run: RunEnvelope) -> dict[str, object]:
    missing = [
        o.observation_id
        for o in run.observations
        if o.required and o.status in {"BLOCKED", "NOT_EVALUATED"}
    ]
    layers = {
        name: any(
            o.evaluation.layer == name and o.status in {"PASS", "FAIL"} for o in run.observations
        )
        for name in ("TOOL_TRAJECTORY", "SYSTEM", "OUTPUT")
    }
    return {
        "product": run.product.id,
        "run_id": run.run_id,
        "format_valid": True,
        "required_evidence_complete": not missing,
        "missing_observations": missing,
        "measured_layers": layers,
        "baseline_digest_present": run.comparison.sha256 is not None,
        "delivery_outcome": run.delivery_outcome,
        "source_fact_count": len(run.source_facts),
        "message": "Connection validated; product quality and detection accuracy require separate evidence.",
    }
