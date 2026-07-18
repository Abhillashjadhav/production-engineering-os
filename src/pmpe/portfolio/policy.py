"""Typed loader for the auditor policy config.

The policy carries the auditor-specific vocabulary the generic
ProductDecisionContract schema cannot express (AI-slop gating, evidence
corroboration floors, prioritization, remediation gates). It is validated
in two layers, both fail-closed:

1. structurally against ``schemas/portfolio_policy.schema.json`` via the
   OS SchemaValidator (documented keyword subset);
2. semantically here for the range rules the schema language cannot state
   (0..100 confidence bands, corroboration floor ordering).

The loaded policy is digest-bound with the same canonical digest the
contract store uses, so runs can pin (contract digest, policy digest).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pmpe.contracts.digest import canonical_digest
from pmpe.domain.errors import ConfigError
from pmpe.ingestion.schema import SchemaValidator
from pmpe.portfolio.models import SlopPolicy

_SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"


def policy_schema_path() -> Path:
    return _SCHEMA_DIR / "portfolio_policy.schema.json"


def finding_schema_path() -> Path:
    return _SCHEMA_DIR / "portfolio_finding.schema.json"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def policy_path() -> Path:
    """The shipped policy config under the auditor's product root."""
    return _repo_root() / "products" / "portfolio-auditor" / "policy.json"


@dataclass(frozen=True)
class EvidencePolicy:
    valid_evidence_kinds: tuple[str, ...]
    independence_key: str
    min_origins_normal: int
    min_origins_high_impact: int


@dataclass(frozen=True)
class ScoringPolicy:
    high_confidence_floor: int
    numeric_score_never_overrides_material_finding: bool


@dataclass(frozen=True)
class SlopPolicyConfig(SlopPolicy):
    """SlopPolicy plus the config-only fields the gate itself does not need."""

    verdicts: tuple[str, ...] = ()
    default_when_uncertain: str = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True)
class RemediationPolicy:
    auto_merge_scope: str
    never_auto_merges_the_auditor_feature_branch: bool
    auto_merge_required_gates: tuple[str, ...]
    forbidden_auto_merge_actions: tuple[str, ...]


@dataclass(frozen=True)
class AuditorPolicy:
    """The full, digest-bound auditor policy."""

    policy_version: int
    recommendation_verdicts: tuple[str, ...]
    assessment_dimensions: tuple[str, ...]
    business_accuracy_scale: tuple[str, ...]
    slop: SlopPolicyConfig
    evidence: EvidencePolicy
    scoring: ScoringPolicy
    prioritization_formula: str
    prioritization_order: tuple[str, ...]
    remediation: RemediationPolicy
    safety_privacy: dict[str, bool]
    digest: str


def _confidence_band(value: int, label: str) -> int:
    if not 0 <= value <= 100:
        raise ConfigError(f"{label} must be within 0..100, got {value}")
    return value


def load_policy(path: Path | None = None) -> AuditorPolicy:
    """Load, validate (fail-closed), and digest-bind the auditor policy."""
    source = path or policy_path()
    try:
        data: dict[str, Any] = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot load auditor policy {source}: {exc}") from exc

    errors = SchemaValidator(policy_schema_path()).validate(data)
    if errors:
        raise ConfigError("auditor policy is structurally invalid:\n  " + "\n  ".join(errors))

    slop_raw = data["ai_slop_policy"]
    evidence_raw = data["evidence_model"]
    scoring_raw = data["scoring_model"]
    prioritization_raw = data["prioritization"]
    remediation_raw = data["remediation_policy"]

    slop = SlopPolicyConfig(
        hard_verdict_min_confidence=_confidence_band(
            int(slop_raw["hard_verdict_min_confidence"]),
            "ai_slop_policy.hard_verdict_min_confidence",
        ),
        require_counter_evidence_review=bool(slop_raw["require_counter_evidence_review"]),
        forbidden_sole_bases=tuple(str(b) for b in slop_raw["forbidden_sole_bases"]),
        verdicts=tuple(str(v) for v in slop_raw["verdicts"]),
        default_when_uncertain=str(slop_raw["default_when_uncertain"]),
    )
    evidence = EvidencePolicy(
        valid_evidence_kinds=tuple(str(k) for k in evidence_raw["valid_evidence_kinds"]),
        independence_key=str(evidence_raw["independence_key"]),
        min_origins_normal=int(evidence_raw["min_origins_normal"]),
        min_origins_high_impact=int(evidence_raw["min_origins_high_impact"]),
    )
    if evidence.min_origins_normal < 1:
        raise ConfigError("evidence_model.min_origins_normal must be >= 1")
    if evidence.min_origins_high_impact < evidence.min_origins_normal:
        raise ConfigError(
            "evidence_model.min_origins_high_impact must be >= min_origins_normal — "
            "high-impact findings never need less corroboration"
        )
    scoring = ScoringPolicy(
        high_confidence_floor=_confidence_band(
            int(scoring_raw["high_confidence_floor"]), "scoring_model.high_confidence_floor"
        ),
        numeric_score_never_overrides_material_finding=bool(
            scoring_raw["numeric_score_never_overrides_material_finding"]
        ),
    )
    remediation = RemediationPolicy(
        auto_merge_scope=str(remediation_raw["auto_merge_scope"]),
        never_auto_merges_the_auditor_feature_branch=bool(
            remediation_raw["never_auto_merges_the_auditor_feature_branch"]
        ),
        auto_merge_required_gates=tuple(
            str(g) for g in remediation_raw["auto_merge_required_gates"]
        ),
        forbidden_auto_merge_actions=tuple(
            str(a) for a in remediation_raw["forbidden_auto_merge_actions"]
        ),
    )

    return AuditorPolicy(
        policy_version=int(data["policy_version"]),
        recommendation_verdicts=tuple(str(v) for v in data["recommendation_verdicts"]),
        assessment_dimensions=tuple(str(d) for d in data["assessment_dimensions"]),
        business_accuracy_scale=tuple(str(s) for s in data["business_accuracy_scale"]),
        slop=slop,
        evidence=evidence,
        scoring=scoring,
        prioritization_formula=str(prioritization_raw["formula"]),
        prioritization_order=tuple(str(p) for p in prioritization_raw["priority_order"]),
        remediation=remediation,
        safety_privacy={k: bool(v) for k, v in data["safety_privacy"].items()},
        digest=canonical_digest(data),
    )


def validate_finding_dict(data: dict[str, Any]) -> list[str]:
    """Structural validation of one serialized finding; [] means valid."""
    return SchemaValidator(finding_schema_path()).validate(data)
