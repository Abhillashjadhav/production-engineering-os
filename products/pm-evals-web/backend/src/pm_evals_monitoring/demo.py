"""Clearly labelled planted cases for the first dashboard run."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from .diagnosis import build_overview
from .models import (
    AttributionMetrics,
    CaseRef,
    CauseSignal,
    ChangeManifest,
    ComparisonRef,
    EvaluationRef,
    EvidenceRef,
    Location,
    ModelRef,
    MonitoringOverview,
    Observation,
    ProductRef,
    Provenance,
    Remediation,
    RunEnvelope,
)

DEMO_NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _evidence(product: str, run_id: str, name: str) -> list[EvidenceRef]:
    uri = f"artifact://demo/{product}/{run_id}/{name}.json"
    return [EvidenceRef(uri=uri, sha256=_digest(uri))]


def _case(case_id: str, display_name: str, use_case: str, segment: str) -> CaseRef:
    return CaseRef(
        case_id=case_id,
        display_name=display_name,
        use_case_id=use_case,
        segment=segment,
        input_fingerprint=_digest(case_id),
    )


def _observation(
    *,
    product: str,
    run_id: str,
    observation_id: str,
    case: CaseRef,
    layer: str,
    concern: str,
    method: str,
    component: str,
    stage: str,
    stage_index: int,
    parameter: str,
    owner: str,
    fix_location: str,
    action: str,
    status: str,
    current: float,
    expected: float,
    current_summary: str,
    expected_summary: str,
    threshold: float,
    unit: str,
    depends_on: list[str] | None = None,
    higher_is_better: bool = True,
    reason_code: str = "WITHIN_EXPECTATION",
    cause_signals: list[CauseSignal] | None = None,
) -> Observation:
    return Observation(
        observation_id=observation_id,
        case=case,
        evaluation=EvaluationRef(
            layer=layer,  # type: ignore[arg-type]
            concern=concern,  # type: ignore[arg-type]
            suite_id=f"{product}-production-evals",
            suite_version="2.0",
            method=method,  # type: ignore[arg-type]
        ),
        location=Location(
            component_id=component,
            stage_id=stage,
            stage_index=stage_index,
            parameter_id=parameter,
            owner_id=owner,
            fix_location=fix_location,
        ),
        status=status,  # type: ignore[arg-type]
        current_value=current,
        expected_value=expected,
        current_summary=current_summary,
        expected_summary=expected_summary,
        threshold=threshold,
        tolerance=0.01,
        unit=unit,
        higher_is_better=higher_is_better,
        reason_code=reason_code,
        depends_on=depends_on or [],
        evidence_refs=_evidence(product, run_id, observation_id),
        cause_signals=cause_signals or [],
        remediation=Remediation(action=action),
    )


def _manifest(product: str, day: int, *, changed_toolset: bool = False) -> ChangeManifest:
    return ChangeManifest(
        use_case_version="dream-job-search@3" if product == "dream-job" else "linkedin-research@2",
        deployment_id=f"{product}-2026.08.{24 + day:02d}",
        model=ModelRef(
            provider="openai",
            name="gpt-5.6-sol",
            snapshot="2026-08-15",
        ),
        prompt_version="search-prompt@4" if product == "dream-job" else "research-prompt@3",
        config_version="production@7" if product == "dream-job" else "production@5",
        toolset_version=("connectors@2" if changed_toolset else "connectors@1"),
        evaluator_version="pm-verifier@2.0",
        rubric_version="production-rubric@2",
        golden_dataset_version=(
            "dream-job-golden@5" if product == "dream-job" else "linkedin-research-golden@3"
        ),
        production_cohort=f"2026-08-{24 + day:02d}",
    )


def _provenance(product: str, day: int, *, changed_toolset: bool = False) -> Provenance:
    toolset = "v2" if changed_toolset else "v1"
    return Provenance(
        contract_digest=_digest(f"{product}:contract:v2"),
        config_digest=_digest(f"{product}:config:v1"),
        production_data_digest=_digest(f"{product}:production:{day}"),
        golden_dataset_digest=_digest(f"{product}:golden:v1"),
        prompt_digest=_digest(f"{product}:prompt:v1"),
        toolset_digest=_digest(f"{product}:tools:{toolset}"),
    )


def _dream_job_run(day: int, *, planted_failure: bool) -> RunEnvelope:
    run_id = f"dream-job-2026-08-{24 + day:02d}"
    case = _case(
        "dj-linkedin-pm-bengaluru-042",
        "LinkedIn PM search · Bengaluru · remote",
        "dream-job-search",
        "product-manager / Bengaluru / remote",
    )
    source = 0.42 if planted_failure else 0.91 - day * 0.005
    eligible = 0.48 if planted_failure else 0.90 - day * 0.004
    enrichment = 0.57 if planted_failure else 0.92 - day * 0.004
    scoring = 0.62 if planted_failure else 0.91 - day * 0.003
    resume = 0.55 if planted_failure else 0.90 - day * 0.003
    outcome = 0.51 if planted_failure else 0.88 - day * 0.002
    replay_signals: list[CauseSignal] = []
    if planted_failure:
        replay_signals = [
            CauseSignal(
                category="PROMPT_CONFIG_TOOL_CHANGE",
                evidence_level="CONTROLLED_REPLAY",
                control_ref="dream-job-2026-08-24#source-linkedin-coverage",
                candidate_ref=f"{run_id}#source-linkedin-coverage",
                control_status="PASS",
                candidate_status="FAIL",
                held_constant=[
                    "USE_CASE",
                    "DEPLOYMENT",
                    "MODEL",
                    "PROMPT",
                    "CONFIGURATION",
                    "EVALUATOR",
                    "RUBRIC",
                    "GOLDEN_DATASET",
                    "PRODUCTION_COHORT",
                ],
                varied_dimensions=["TOOLSET"],
                summary=(
                    "Connector v1 passed this same case and connector v2 failed while the "
                    "model, prompt, evaluator, and approved case stayed fixed."
                ),
                evidence_refs=_evidence("dream-job", run_id, "connector-controlled-replay"),
            )
        ]
    failed = "FAIL" if planted_failure else "PASS"
    observations = [
        _observation(
            product="dream-job",
            run_id=run_id,
            observation_id="input-constraint-completeness",
            case=case,
            layer="INPUT",
            concern="INVARIANT",
            method="DETERMINISTIC",
            component="request-normalizer",
            stage="input",
            stage_index=1,
            parameter="required-search-constraints",
            owner="dream-job-input-owner",
            fix_location="request normalizer / search constraint mapping",
            action="Check whether role, location, and work-mode constraints were normalized.",
            status="PASS",
            current=1.0,
            expected=1.0,
            current_summary="Role, location, and remote preference were captured.",
            expected_summary="All required search constraints are present.",
            threshold=1.0,
            unit="ratio",
        ),
        _observation(
            product="dream-job",
            run_id=run_id,
            observation_id="source-linkedin-coverage",
            case=case,
            layer="RETRIEVAL_TOOL",
            concern="INVARIANT",
            method="DETERMINISTIC",
            component="source-acquisition",
            stage="retrieval",
            stage_index=2,
            parameter="linkedin-source-coverage",
            owner="dream-job-source-owner",
            fix_location="LinkedIn source adapter / connector-v2 mapping",
            action=(
                "Open the LinkedIn source adapter and connector-v2 configuration; restore "
                "coverage before changing scoring, output, evals, or the approved case set."
            ),
            status=failed,
            current=source,
            expected=0.91,
            current_summary=f"LinkedIn returned {source:.0%} of the expected eligible jobs.",
            expected_summary="The approved comparison returned 91% source coverage.",
            threshold=0.85,
            unit="ratio",
            depends_on=["input-constraint-completeness"],
            reason_code=(
                "UPSTREAM_SOURCE_COVERAGE_COLLAPSE" if planted_failure else "WITHIN_EXPECTATION"
            ),
            cause_signals=replay_signals,
        ),
        _observation(
            product="dream-job",
            run_id=run_id,
            observation_id="eligible-job-coverage",
            case=case,
            layer="SYSTEM",
            concern="CAPABILITY",
            method="DETERMINISTIC",
            component="job-filter",
            stage="filtering",
            stage_index=3,
            parameter="eligible-job-coverage",
            owner="dream-job-ranking-owner",
            fix_location="job filter / eligibility rules",
            action="Re-run after source coverage is restored; inspect filters only if this remains red.",
            status=failed,
            current=eligible,
            expected=0.90,
            current_summary=f"Only {eligible:.0%} of eligible jobs survived filtering.",
            expected_summary="The approved comparison retained 90% of eligible jobs.",
            threshold=0.80,
            unit="ratio",
            depends_on=["source-linkedin-coverage"],
            reason_code="LOW_INPUT_COVERAGE" if planted_failure else "WITHIN_EXPECTATION",
        ),
        _observation(
            product="dream-job",
            run_id=run_id,
            observation_id="enrichment-completeness",
            case=case,
            layer="RETRIEVAL_TOOL",
            concern="QUALITY",
            method="DETERMINISTIC",
            component="job-enrichment",
            stage="enrichment",
            stage_index=4,
            parameter="required-field-completeness",
            owner="dream-job-enrichment-owner",
            fix_location="job enrichment / required fields",
            action="Re-run after the source fix; inspect enrichment only if incomplete fields remain.",
            status=failed,
            current=enrichment,
            expected=0.92,
            current_summary=f"Required job fields were {enrichment:.0%} complete.",
            expected_summary="The approved comparison was 92% complete.",
            threshold=0.85,
            unit="ratio",
            depends_on=["eligible-job-coverage"],
            reason_code=("INCOMPLETE_UPSTREAM_JOBS" if planted_failure else "WITHIN_EXPECTATION"),
        ),
        _observation(
            product="dream-job",
            run_id=run_id,
            observation_id="score-evidence-coverage",
            case=case,
            layer="TOOL_TRAJECTORY",
            concern="INVARIANT",
            method="DETERMINISTIC",
            component="job-scorer",
            stage="scoring",
            stage_index=5,
            parameter="score-evidence-coverage",
            owner="dream-job-ranking-owner",
            fix_location="job scorer / evidence binding",
            action="Treat this as downstream until retrieval and enrichment are healthy.",
            status=failed,
            current=scoring,
            expected=0.91,
            current_summary=f"Only {scoring:.0%} of scores had complete source evidence.",
            expected_summary="The approved comparison had 91% evidence coverage.",
            threshold=0.85,
            unit="ratio",
            depends_on=["enrichment-completeness"],
            reason_code="MISSING_SCORE_EVIDENCE" if planted_failure else "WITHIN_EXPECTATION",
        ),
        _observation(
            product="dream-job",
            run_id=run_id,
            observation_id="resume-evidence-coverage",
            case=case,
            layer="OUTPUT",
            concern="QUALITY",
            method="MODEL_JUDGE",
            component="resume-tailor",
            stage="output",
            stage_index=6,
            parameter="resume-evidence-coverage",
            owner="dream-job-resume-owner",
            fix_location="resume tailor / evidence selection",
            action="Do not rewrite the output eval until upstream source evidence is restored.",
            status=failed,
            current=resume,
            expected=0.90,
            current_summary=f"The tailored resume used {resume:.0%} of required evidence.",
            expected_summary="The approved comparison used 90% of required evidence.",
            threshold=0.82,
            unit="ratio",
            depends_on=["score-evidence-coverage"],
            reason_code="LOW_RESUME_EVIDENCE" if planted_failure else "WITHIN_EXPECTATION",
        ),
        _observation(
            product="dream-job",
            run_id=run_id,
            observation_id="qualified-recommendation-rate",
            case=case,
            layer="OUTCOME",
            concern="CAPABILITY",
            method="HYBRID",
            component="recommendation-outcome",
            stage="outcome",
            stage_index=7,
            parameter="qualified-recommendation-rate",
            owner="dream-job-product-owner",
            fix_location="recommendation outcome / qualified job set",
            action="Re-measure the outcome after upstream coverage is restored.",
            status=failed,
            current=outcome,
            expected=0.88,
            current_summary=f"Only {outcome:.0%} of recommendations met the qualified-job bar.",
            expected_summary="The approved comparison reached an 88% qualified recommendation rate.",
            threshold=0.80,
            unit="ratio",
            depends_on=["resume-evidence-coverage"],
            reason_code="LOW_QUALIFIED_OUTCOME" if planted_failure else "WITHIN_EXPECTATION",
        ),
        _observation(
            product="dream-job",
            run_id=run_id,
            observation_id="pii-disclosure-rate",
            case=case,
            layer="OUTPUT",
            concern="PRIVACY",
            method="DETERMINISTIC",
            component="privacy-gate",
            stage="output",
            stage_index=8,
            parameter="pii-disclosure-rate",
            owner="dream-job-safety-owner",
            fix_location="output privacy gate",
            action="Inspect redaction only if the privacy rate exceeds zero.",
            status="PASS",
            current=0.0,
            expected=0.0,
            current_summary="No private data was disclosed.",
            expected_summary="No private data may be disclosed.",
            threshold=0.0,
            unit="ratio",
            higher_is_better=False,
        ),
    ]
    return RunEnvelope(
        run_id=run_id,
        comparison=ComparisonRef(run_id="dream-job-2026-08-24"),
        observed_at=DEMO_NOW - timedelta(days=4 - day),
        product=ProductRef(
            id="dream-job-agent",
            display_name="Dream Job Agent",
            version=f"2026.08.{24 + day:02d}",
            environment="production",
        ),
        change_manifest=_manifest("dream-job", day, changed_toolset=planted_failure),
        provenance=_provenance("dream-job", day, changed_toolset=planted_failure),
        observations=observations,
    )


def _linkedin_run(day: int) -> RunEnvelope:
    run_id = f"linkedin-os-2026-08-{24 + day:02d}"
    case = _case(
        "li-research-series-b-017",
        "Series B AI company research",
        "linkedin-research",
        "company research / AI / Series B",
    )
    specs = [
        (
            "input-scope",
            "INPUT",
            "INVARIANT",
            "request-parser",
            "input",
            "scope-completeness",
            1.0,
            1.0,
        ),
        (
            "research-tool-success",
            "RETRIEVAL_TOOL",
            "CAPABILITY",
            "research-tools",
            "retrieval",
            "tool-success-rate",
            0.94,
            0.93,
        ),
        (
            "trajectory-completeness",
            "TOOL_TRAJECTORY",
            "INVARIANT",
            "research-orchestrator",
            "trajectory",
            "required-step-coverage",
            1.0,
            1.0,
        ),
        (
            "entity-resolution",
            "SYSTEM",
            "QUALITY",
            "entity-resolver",
            "synthesis",
            "entity-resolution-rate",
            0.91,
            0.90,
        ),
        (
            "evidence-coverage",
            "OUTPUT",
            "QUALITY",
            "research-writer",
            "output",
            "claim-evidence-coverage",
            0.94,
            0.93,
        ),
        (
            "research-usefulness",
            "OUTCOME",
            "CAPABILITY",
            "research-outcome",
            "outcome",
            "decision-usefulness",
            0.89,
            0.87,
        ),
        (
            "privacy-rate",
            "OUTPUT",
            "PRIVACY",
            "privacy-gate",
            "output",
            "private-data-rate",
            0.0,
            0.0,
        ),
        (
            "safety-rate",
            "OUTCOME",
            "SAFETY",
            "safety-gate",
            "outcome",
            "unsafe-claim-rate",
            0.0,
            0.0,
        ),
        (
            "toxicity-rate",
            "OUTPUT",
            "TOXICITY",
            "toxicity-gate",
            "output",
            "toxic-content-rate",
            0.0,
            0.0,
        ),
    ]
    observations = []
    for index, (
        obs_id,
        layer,
        concern,
        component,
        stage,
        parameter,
        current,
        expected,
    ) in enumerate(specs, start=1):
        lower_is_better = concern in {"PRIVACY", "SAFETY", "TOXICITY"}
        observations.append(
            _observation(
                product="linkedin-os",
                run_id=run_id,
                observation_id=obs_id,
                case=case,
                layer=layer,
                concern=concern,
                method="DETERMINISTIC" if concern != "CAPABILITY" else "HYBRID",
                component=component,
                stage=stage,
                stage_index=index,
                parameter=parameter,
                owner="linkedin-research-owner",
                fix_location=f"{component} / {parameter}",
                action=f"Inspect {component} only if this case crosses its approved bar.",
                status="PASS",
                current=current,
                expected=expected,
                current_summary=f"Current result is {current:.0%}.",
                expected_summary=f"Approved comparison result is {expected:.0%}.",
                threshold=expected if lower_is_better else max(0.0, expected - 0.08),
                unit="ratio",
                higher_is_better=not lower_is_better,
            )
        )
    return RunEnvelope(
        run_id=run_id,
        comparison=ComparisonRef(run_id="linkedin-os-2026-08-24"),
        observed_at=DEMO_NOW - timedelta(days=4 - day, hours=2),
        product=ProductRef(
            id="linkedin-research-os",
            display_name="LinkedIn Research OS",
            version=f"2026.08.{24 + day:02d}",
            environment="production",
        ),
        change_manifest=_manifest("linkedin-os", day),
        provenance=_provenance("linkedin-os", day),
        observations=observations,
    )


def build_demo_runs() -> list[RunEnvelope]:
    runs: list[RunEnvelope] = []
    for day in range(5):
        runs.append(_dream_job_run(day, planted_failure=day == 4))
        runs.append(_linkedin_run(day))
    return runs


def build_demo_overview() -> MonitoringOverview:
    return build_overview(
        build_demo_runs(),
        mode="PLANTED_DEMO",
        generated_at=DEMO_NOW,
        attribution_metrics=AttributionMetrics(
            correctly_localized_rate=1.0,
            attribution_coverage=1.0,
            false_attribution_rate=0.0,
            known_cause_sample_size=1,
            production_adjudicated_sample_size=0,
            guardrail_proven=False,
            label="One planted controlled-replay case; production guardrail not proven",
        ),
    )
