"""Versioned contracts for case-level production eval observations and diagnoses.

Raw evaluator facts, dependency-based localization, and causal evidence remain
separate so the dashboard can explain what it knows without overstating why a
failure happened.
"""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

ObservationStatus = Literal["PASS", "FAIL", "BLOCKED", "NOT_EVALUATED"]
Attribution = Literal["LIKELY_STARTING_FAILURE", "DOWNSTREAM_SYMPTOM", "UNCONFIRMED"]
RunHealth = Literal["HEALTHY", "DEGRADED", "FAILING", "BLOCKED"]
EvalLayer = Literal[
    "INPUT",
    "SYSTEM",
    "RETRIEVAL_TOOL",
    "TOOL_TRAJECTORY",
    "OUTPUT",
    "OUTCOME",
]
EvalConcern = Literal[
    "INVARIANT",
    "CAPABILITY",
    "QUALITY",
    "PRIVACY",
    "SAFETY",
    "TOXICITY",
    "POLICY_COMPLIANCE",
]
EvalMethod = Literal["DETERMINISTIC", "MODEL_JUDGE", "HUMAN", "HYBRID"]
CauseCategory = Literal[
    "PRODUCT_REGRESSION",
    "MODEL_REGRESSION",
    "PROMPT_CONFIG_TOOL_CHANGE",
    "USE_CASE_DRIFT",
    "EVAL_DETERIORATION",
    "GOLDEN_DATASET_GAP",
    "UNCONFIRMED",
]
EvidenceLevel = Literal[
    "DEPENDENCY_ONLY",
    "CHANGE_CORRELATION",
    "CONTROLLED_REPLAY",
    "HUMAN_ADJUDICATION",
]
CauseConfidence = Literal["UNCONFIRMED", "CANDIDATE", "SUPPORTED", "CONFIRMED"]
MaintenanceAction = Literal["KEEP", "INVESTIGATE", "REVIEW_AFTER_ADJUDICATION"]
ChangeDimension = Literal[
    "USE_CASE",
    "DEPLOYMENT",
    "MODEL",
    "PROMPT",
    "CONFIGURATION",
    "TOOLSET",
    "EVALUATOR",
    "RUBRIC",
    "GOLDEN_DATASET",
    "PRODUCTION_COHORT",
]

OVERVIEW_TREND_RUNS_PER_PRODUCT = 30


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ProductRef(StrictModel):
    id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    environment: str = Field(min_length=1)


class ModelRef(StrictModel):
    provider: str = Field(min_length=1)
    name: str = Field(min_length=1)
    snapshot: str = Field(min_length=1)


class ChangeManifest(StrictModel):
    """Human-readable versions needed to explain what changed between runs."""

    use_case_version: str = Field(min_length=1)
    deployment_id: str = Field(min_length=1)
    model: ModelRef
    prompt_version: str = Field(min_length=1)
    config_version: str = Field(min_length=1)
    toolset_version: str = Field(min_length=1)
    evaluator_version: str = Field(min_length=1)
    rubric_version: str = Field(min_length=1)
    golden_dataset_version: str = Field(min_length=1)
    production_cohort: str = Field(min_length=1)


class Provenance(StrictModel):
    """Tamper-evident identifiers; no raw private case content belongs here."""

    contract_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    config_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    production_data_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    golden_dataset_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    prompt_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    toolset_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class CaseRef(StrictModel):
    case_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1, max_length=160)
    use_case_id: str = Field(min_length=1)
    segment: str = Field(min_length=1, max_length=160)
    input_fingerprint: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")


class EvaluationRef(StrictModel):
    layer: EvalLayer
    concern: EvalConcern
    suite_id: str = Field(min_length=1)
    suite_version: str = Field(min_length=1)
    method: EvalMethod


class Location(StrictModel):
    component_id: str = Field(min_length=1)
    stage_id: str = Field(min_length=1)
    stage_index: int = Field(ge=1)
    parameter_id: str = Field(min_length=1)
    owner_id: str = Field(min_length=1)
    fix_location: str = Field(min_length=1, max_length=240)


class EvidenceRef(StrictModel):
    uri: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class CauseSignal(StrictModel):
    category: CauseCategory
    evidence_level: EvidenceLevel
    supports: bool = True
    summary: str = Field(min_length=1, max_length=500)
    control_ref: str | None = None
    candidate_ref: str | None = None
    control_status: ObservationStatus | None = None
    candidate_status: ObservationStatus | None = None
    held_constant: list[ChangeDimension] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_controlled_replay(self) -> CauseSignal:
        if self.evidence_level != "CONTROLLED_REPLAY":
            return self
        if not self.control_ref or not self.candidate_ref:
            raise ValueError("controlled replay requires control_ref and candidate_ref")
        if self.control_ref == self.candidate_ref:
            raise ValueError(
                "controlled replay requires distinct control and candidate references"
            )
        if self.control_status is None or self.candidate_status is None:
            raise ValueError("controlled replay requires both replay statuses")
        if self.supports and not (
            self.control_status == "PASS" and self.candidate_status == "FAIL"
        ):
            raise ValueError("a supporting controlled replay must move from PASS to FAIL")
        if not self.held_constant:
            raise ValueError("controlled replay must declare what was held constant")
        return self


class Remediation(StrictModel):
    action: str = Field(min_length=1, max_length=500)


class Observation(StrictModel):
    observation_id: str = Field(min_length=1)
    case: CaseRef
    evaluation: EvaluationRef
    location: Location
    status: ObservationStatus
    current_value: float | None = None
    expected_value: float | None = None
    current_summary: str = Field(min_length=1, max_length=500)
    expected_summary: str = Field(min_length=1, max_length=500)
    threshold: float | None = None
    tolerance: float = Field(default=0.0, ge=0.0)
    unit: str = ""
    higher_is_better: bool = True
    required: bool = True
    reason_code: str = Field(min_length=1)
    depends_on: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    cause_signals: list[CauseSignal] = Field(default_factory=list)
    remediation: Remediation
    extensions: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_measurement(self) -> Observation:
        if self.status in ("PASS", "FAIL") and self.current_value is None:
            raise ValueError("PASS and FAIL observations require current_value")
        if self.observation_id in self.depends_on:
            raise ValueError("an observation cannot depend on itself")
        if len(self.depends_on) != len(set(self.depends_on)):
            raise ValueError("depends_on contains duplicates")
        return self


class ComparisonRef(StrictModel):
    run_id: str = Field(min_length=1)
    label: str = Field(default="Last approved good run", min_length=1, max_length=120)


class RunEnvelope(StrictModel):
    contract_version: Literal["0.2"] = "0.2"
    run_id: str = Field(min_length=1)
    comparison: ComparisonRef
    observed_at: AwareDatetime
    product: ProductRef
    change_manifest: ChangeManifest
    provenance: Provenance
    observations: list[Observation] = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_graph(self) -> RunEnvelope:
        by_id = {item.observation_id: item for item in self.observations}
        if len(by_id) != len(self.observations):
            raise ValueError("observation_id values must be unique within a run")
        for item in self.observations:
            unknown = sorted(set(item.depends_on) - set(by_id))
            if unknown:
                raise ValueError(
                    f"{item.observation_id} depends on unknown observations: {', '.join(unknown)}"
                )

        remaining_dependencies = {
            observation_id: len(item.depends_on) for observation_id, item in by_id.items()
        }
        dependents: dict[str, list[str]] = defaultdict(list)
        for observation_id, item in by_id.items():
            for dependency_id in item.depends_on:
                dependents[dependency_id].append(observation_id)
        ready = deque(
            observation_id
            for observation_id, remaining in remaining_dependencies.items()
            if remaining == 0
        )
        visited_count = 0
        while ready:
            observation_id = ready.popleft()
            visited_count += 1
            for dependent_id in dependents[observation_id]:
                remaining_dependencies[dependent_id] -= 1
                if remaining_dependencies[dependent_id] == 0:
                    ready.append(dependent_id)
        if visited_count != len(by_id):
            raise ValueError("observation dependency graph contains a cycle")
        return self


class ObservationDiagnosis(StrictModel):
    observation_id: str
    attribution: Attribution
    root_observation_ids: list[str] = Field(default_factory=list)
    signed_delta: float | None = None
    regression_magnitude: float | None = None
    localization_reason: str
    cause_category: CauseCategory
    cause_confidence: CauseConfidence
    evidence_level: EvidenceLevel
    cause_reason: str


class RunDiagnosis(StrictModel):
    diagnosis_version: Literal["0.2"] = "0.2"
    run_id: str
    product_id: str
    health: RunHealth
    pass_count: int
    fail_count: int
    blocked_count: int
    not_evaluated_count: int
    likely_starting_observation_ids: list[str]
    diagnoses: list[ObservationDiagnosis]


class CoverageHealth(StrictModel):
    name: str
    health: RunHealth
    pass_count: int
    fail_count: int
    blocked_count: int


class ProductHealth(StrictModel):
    product_id: str
    display_name: str
    version: str
    environment: str
    latest_run_id: str
    observed_at: datetime
    health: RunHealth
    pass_count: int
    fail_count: int
    blocked_count: int
    layers: list[CoverageHealth]
    concerns: list[CoverageHealth]


class ChangeItem(StrictModel):
    dimension: ChangeDimension
    previous: str
    current: str


class MaintenanceAssessment(StrictModel):
    eval_action: MaintenanceAction
    golden_dataset_action: MaintenanceAction
    reason: str


class Incident(StrictModel):
    incident_id: str
    product_id: str
    product_name: str
    environment: str
    run_id: str
    comparison_run_id: str
    comparison_label: str
    observed_at: datetime
    observation_id: str
    case: CaseRef
    component_id: str
    stage_id: str
    parameter_id: str
    owner_id: str
    fix_location: str
    layer: EvalLayer
    concern: EvalConcern
    current_value: float | None
    expected_value: float | None
    current_summary: str
    expected_summary: str
    threshold: float | None
    unit: str
    regression_magnitude: float | None
    downstream_observation_ids: list[str]
    reason_code: str
    cause_category: CauseCategory
    cause_confidence: CauseConfidence
    evidence_level: EvidenceLevel
    cause_reason: str
    changes_since_comparison: list[ChangeItem]
    maintenance: MaintenanceAssessment
    remediation: Remediation
    evidence_refs: list[EvidenceRef]


class TrendPoint(StrictModel):
    product_id: str
    environment: str
    observed_at: datetime
    health: RunHealth
    pass_rate: float


class AttributionMetrics(StrictModel):
    correctly_localized_rate: float | None
    attribution_coverage: float | None
    false_attribution_rate: float | None
    known_cause_sample_size: int
    production_adjudicated_sample_size: int
    false_attribution_target: float = 0.02
    guardrail_proven: bool = False
    label: str


class MonitoringOverview(StrictModel):
    generated_at: datetime
    mode: Literal["PLANTED_DEMO", "LIVE"]
    products: list[ProductHealth]
    incidents: list[Incident]
    trend: list[TrendPoint]
    attribution_metrics: AttributionMetrics


class IngestResponse(StrictModel):
    stored: bool
    duplicate: bool
    diagnosis: RunDiagnosis
