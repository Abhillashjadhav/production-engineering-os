"""Portfolio Auditor M1 — policy config, schemas, and digest binding.

The auditor-specific vocabulary (AI-slop policy, verdict scales, evidence
model, prioritization, remediation gates) lives in a policy config validated
against a SchemaValidator-subset schema, with range rules the schema language
cannot express enforced in the typed loader. The policy is digest-bound with
the same canonical digest the contract store uses.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pmpe.portfolio.models import (
    AISlopVerdict,
    BusinessAccuracyVerdict,
    RecommendationVerdict,
)
from pmpe.portfolio.policy import (
    finding_schema_path,
    load_policy,
    policy_path,
    policy_schema_path,
    validate_finding_dict,
)

from pmpe.contracts.digest import canonical_digest
from pmpe.domain.errors import ConfigError

REPO_ROOT = Path(__file__).resolve().parents[2]


def _policy_data() -> dict[str, object]:
    return json.loads(policy_path().read_text())


def _write_policy(tmp_path: Path, data: dict[str, object]) -> Path:
    p = tmp_path / "policy.json"
    p.write_text(json.dumps(data))
    return p


class TestPolicyLoad:
    def test_shipped_policy_loads_and_validates(self) -> None:
        policy = load_policy(policy_path())
        assert policy.slop.hard_verdict_min_confidence == 70
        assert policy.slop.require_counter_evidence_review is True
        assert policy.evidence.min_origins_normal == 2
        assert policy.evidence.min_origins_high_impact == 3
        assert policy.scoring.high_confidence_floor == 70

    def test_policy_vocabulary_agrees_with_model_enums(self) -> None:
        policy = load_policy(policy_path())
        assert set(policy.recommendation_verdicts) == {v.value for v in RecommendationVerdict}
        assert set(policy.slop.verdicts) == {v.value for v in AISlopVerdict}
        assert set(policy.business_accuracy_scale) == {v.value for v in BusinessAccuracyVerdict}
        assert len(policy.assessment_dimensions) == 10

    def test_policy_pins_six_forbidden_sole_bases(self) -> None:
        policy = load_policy(policy_path())
        assert set(policy.slop.forbidden_sole_bases) == {
            "writing_style",
            "disclosed_ai_assistance",
            "commit_volume",
            "repository_size",
            "generated_file_count",
            "lack_of_popularity",
        }

    def test_missing_slop_section_fails_closed(self, tmp_path: Path) -> None:
        data = _policy_data()
        del data["ai_slop_policy"]
        with pytest.raises(ConfigError, match="ai_slop_policy"):
            load_policy(_write_policy(tmp_path, data))

    def test_out_of_range_confidence_fails_closed(self, tmp_path: Path) -> None:
        for bad in (-1, 101):
            data = _policy_data()
            slop = data["ai_slop_policy"]
            assert isinstance(slop, dict)
            slop["hard_verdict_min_confidence"] = bad
            with pytest.raises(ConfigError, match="hard_verdict_min_confidence"):
                load_policy(_write_policy(tmp_path, data))

    def test_policy_digest_is_canonical_and_stable(self, tmp_path: Path) -> None:
        policy = load_policy(policy_path())
        assert policy.digest == canonical_digest(_policy_data())
        # Key order must not matter: rewrite with reversed key order.
        shuffled = dict(reversed(list(_policy_data().items())))
        assert load_policy(_write_policy(tmp_path, shuffled)).digest == policy.digest


class TestSchemas:
    def test_schema_files_exist_in_package(self) -> None:
        assert policy_schema_path().is_file()
        assert finding_schema_path().is_file()

    def test_finding_schema_accepts_a_complete_finding(self) -> None:
        good = {
            "finding_id": "PA-F-001",
            "repository": "acme/healthy-lib",
            "dimension": "technical_health",
            "summary": "tests never run in CI",
            "evidence": [
                {
                    "evidence_id": "EV-1",
                    "kind": "ci_workflow",
                    "origin": "ci_config",
                    "reference": ".github/workflows/ci.yml#L1",
                    "content_digest": "sha256:" + "0" * 64,
                }
            ],
            "confidence": 80,
            "severity": "HIGH",
            "affected_capability": "tests_ci_evaluations",
            "reasoning": "CI workflow exists but has no test step.",
            "remediation_recommendation": "Add a test job to the workflow.",
        }
        assert validate_finding_dict(good) == []

    def test_finding_schema_rejects_each_missing_required_field(self) -> None:
        required = (
            "finding_id",
            "evidence",
            "confidence",
            "severity",
            "affected_capability",
            "reasoning",
            "remediation_recommendation",
        )
        base = {
            "finding_id": "PA-F-001",
            "repository": "acme/healthy-lib",
            "dimension": "technical_health",
            "summary": "s",
            "evidence": [],
            "confidence": 80,
            "severity": "HIGH",
            "affected_capability": "tests_ci_evaluations",
            "reasoning": "r",
            "remediation_recommendation": "m",
        }
        for missing in required:
            data = {k: v for k, v in base.items() if k != missing}
            errors = validate_finding_dict(data)
            assert any(missing in e for e in errors), f"expected error for {missing}"


class TestNoPrototypeDependency:
    def test_portfolio_package_never_imports_loop_engineering(self) -> None:
        pkg = REPO_ROOT / "src" / "pmpe" / "portfolio"
        offenders = [
            p for p in pkg.rglob("*.py") if "loop_engineering" in p.read_text(encoding="utf-8")
        ]
        assert offenders == []
