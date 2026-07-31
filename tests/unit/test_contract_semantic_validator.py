"""Issue #63 RED contract for canonical PMOS semantic admission.

The tests load the schema-valid issue #62 fixture, bind its approval subjects to
exact RFC 8785 digests, and then introduce one semantic defect at a time.  The
module import is deliberately deferred so this test-only commit collects and
fails because the issue #63 API is absent, rather than because of an import or
syntax error.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import importlib
import json
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from pmpe.contracts.canonical import canonical_digest, canonical_json_bytes
from pmpe.contracts.intake import CorrectionReference, IntakeReceipt, KeyedFingerprint

ROOT = Path(__file__).resolve().parents[2]
VALID_BUNDLE = ROOT / "tests" / "fixtures" / "pmos" / "v1" / "valid_bundle.json"
EVALUATED_AT = "2026-07-31T00:00:00Z"
RECEIVED_AT = "2026-07-30T12:00:00Z"


class TestFingerprintProvider:
    key_version = "TEST-KEY-V1"
    _key = b"issue-63-deterministic-test-key"

    def fingerprint(self, domain: str, payload: bytes) -> str:
        return hmac.new(self._key, domain.encode() + b"\x00" + payload, hashlib.sha256).hexdigest()

    def candidate_fingerprints(self, domain: str, payload: bytes) -> tuple[KeyedFingerprint, ...]:
        return (KeyedFingerprint(self.key_version, self.fingerprint(domain, payload)),)


FINGERPRINTS = TestFingerprintProvider()


def _api() -> ModuleType:
    try:
        return importlib.import_module("pmpe.validation.contracts")
    except ModuleNotFoundError:
        pytest.fail(
            "issue #63 canonical semantic validator is not implemented",
            pytrace=False,
        )


class TestAuthorityEvidenceVerifier:
    """Test-only trust root; production validation exposes verification only."""

    issuer_id = "TEST-AUTHORITY-001"
    key_version = "TEST-AUTHORITY-KEY-V1"
    _key = b"issue-63-external-authority-test-key"

    def issue(
        self,
        bundle: dict[str, Any],
        authority_grants: tuple[Any, ...],
        requirement_grants: tuple[Any, ...],
    ) -> Any:
        api = _api()
        grants = tuple(
            sorted((item.as_dict() for item in authority_grants), key=canonical_json_bytes)
        )
        requirements = tuple(
            sorted((item.as_dict() for item in requirement_grants), key=canonical_json_bytes)
        )
        evidence = api.ApprovalAuthorityEvidence(
            bundle_digest=canonical_digest(bundle),
            approvals_digest=canonical_digest(bundle.get("approvals", {})),
            authority_grants=grants,
            requirement_grants=requirements,
            issuer_id=self.issuer_id,
            key_version=self.key_version,
            attestation="",
        )
        attestation = hmac.new(
            self._key,
            b"validation-authority-attestation\x00"
            + canonical_json_bytes(evidence.signed_payload()),
            hashlib.sha256,
        ).hexdigest()
        return replace(evidence, attestation=attestation)

    def verify(self, evidence: Any) -> bool:
        if evidence.issuer_id != self.issuer_id or evidence.key_version != self.key_version:
            return False
        expected = hmac.new(
            self._key,
            b"validation-authority-attestation\x00"
            + canonical_json_bytes(evidence.signed_payload()),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, evidence.attestation)


AUTHORITY = TestAuthorityEvidenceVerifier()


def _ready_bundle() -> dict[str, Any]:
    bundle = json.loads(VALID_BUNDLE.read_text())
    for policy in bundle["metrics"]["maturity_policies"].values():
        policy["target"] = {
            "operator": "AT_LEAST",
            "status": "APPROVED",
            "unit": "ratio",
            "value": 0.8,
        }
    for approval in bundle["approvals"].values():
        subject = approval["subject"]
        if subject["digest_scope"] == "NAMED_METRIC_MATURITY_POLICY":
            subject["digest"] = canonical_digest(
                bundle["metrics"]["maturity_policies"][subject["id"]]
            )
        elif subject["digest_scope"] == "NAMED_METRIC_REPORTING_POLICY":
            subject["digest"] = canonical_digest(
                bundle["metrics"]["reporting_policies"][subject["id"]]
            )
    for extension in bundle["extensions"].values():
        extension["payload_digest"] = canonical_digest(extension["payload"])
    projection = copy.deepcopy(bundle)
    projection.pop("approvals")
    bundle["approvals"]["APR-CONTRACT-001"]["subject"]["digest"] = canonical_digest(projection)
    return bundle


def _context(
    bundle: dict[str, Any],
    *,
    lineage_id: str = "LINEAGE-000001",
    attempt_id: str = "ATTEMPT-000001",
    correction_reference: CorrectionReference | None = None,
    possible_duplicate: bool = False,
) -> Any:
    api = _api()
    authority_grants = (
        api.ApprovalAuthorityGrant(
            actor_id="OWNER-PRODUCT-001",
            role="PRODUCT_OWNER",
            authority_policy_id="AUTH-POLICY-CONTRACT-001",
            authority_policy_version="1.0.0",
            valid_from="2026-01-01T00:00:00Z",
            expires_at="2027-01-01T00:00:00Z",
        ),
        api.ApprovalAuthorityGrant(
            actor_id="OWNER-PRODUCT-001",
            role="METRIC_POLICY_OWNER",
            authority_policy_id="AUTH-POLICY-METRIC-001",
            authority_policy_version="1.0.0",
            valid_from="2026-01-01T00:00:00Z",
            expires_at="2027-01-01T00:00:00Z",
        ),
    )
    requirement_grants = (
        api.ApprovalRequirementGrant(
            requirement_id="APPROVAL-REQ-CONTRACT",
            approval_id="APR-CONTRACT-001",
        ),
    )
    receipt = IntakeReceipt(
        lineage_id=lineage_id,
        attempt_id=attempt_id,
        received_at=("2026-07-30T13:00:00Z" if correction_reference else RECEIVED_AT),
        publisher="PMOS",
        channel="TEST",
        content_type="application/json",
        quarantine_handle=f"QUARANTINE-{attempt_id}",
        key_version="TEST-PAYLOAD-KEY-V1",
        fingerprint="a" * 64,
        correction_reference=correction_reference,
    )
    return api.ValidationContext(
        lineage_id=lineage_id,
        ingestion_attempt_id=attempt_id,
        bundle_digest=canonical_digest(bundle),
        evaluated_at=EVALUATED_AT,
        lineage_received_at=RECEIVED_AT,
        correction_reference=correction_reference,
        possible_duplicate=possible_duplicate,
        authority_grants=authority_grants,
        approval_requirement_grants=requirement_grants,
        intake_identity=api.IntakeIdentityEvidence.create(receipt, FINGERPRINTS),
        authority_identity=AUTHORITY.issue(bundle, authority_grants, requirement_grants),
    )


def _with_authority_evidence(
    context: Any,
    bundle: dict[str, Any],
    *,
    authority_grants: tuple[Any, ...] | None = None,
    requirement_grants: tuple[Any, ...] | None = None,
) -> Any:
    selected_authority = (
        authority_grants if authority_grants is not None else context.authority_grants
    )
    selected_requirements = (
        requirement_grants
        if requirement_grants is not None
        else context.approval_requirement_grants
    )
    return replace(
        context,
        authority_grants=selected_authority,
        approval_requirement_grants=selected_requirements,
        authority_identity=AUTHORITY.issue(bundle, selected_authority, selected_requirements),
    )


def _validator(registry: Any = None, *, evidence_lookup: Any = None) -> Any:
    return _api().ContractSemanticValidator(
        registry,
        fingerprint_provider=FINGERPRINTS,
        authority_evidence_verifier=AUTHORITY,
        evidence_lookup=evidence_lookup,
    )


def _validate(bundle: dict[str, Any], **context: Any) -> Any:
    return _validator().validate(
        bundle,
        _context(bundle, **context),
    )


def _codes(result: Any) -> set[str]:
    return {item.rule_id for item in result.diagnostics}


def _reseal(bundle: dict[str, Any]) -> None:
    for approval in bundle.get("approvals", {}).values():
        subject = approval["subject"]
        if subject["digest_scope"] == "NAMED_METRIC_MATURITY_POLICY":
            policy = bundle["metrics"]["maturity_policies"].get(subject["id"])
            if policy is not None:
                subject["digest"] = canonical_digest(policy)
        elif subject["digest_scope"] == "NAMED_METRIC_REPORTING_POLICY":
            policy = bundle["metrics"]["reporting_policies"].get(subject["id"])
            if policy is not None:
                subject["digest"] = canonical_digest(policy)
    projection = copy.deepcopy(bundle)
    projection.pop("approvals", None)
    for approval in bundle.get("approvals", {}).values():
        if approval["subject"]["digest_scope"] == "CANONICAL_BUNDLE_EXCLUDING_APPROVALS":
            approval["subject"]["digest"] = canonical_digest(projection)


def test_complete_exactly_approved_bundle_is_admitted() -> None:
    api = _api()
    result = _validate(_ready_bundle())
    assert result.disposition is api.Disposition.ADMITTED
    assert result.diagnostics == ()
    assert result.validator_version == "1.0.0"
    assert result.rule_set_version == "1.0.0"


@pytest.mark.parametrize(
    "section",
    [
        "product",
        "metrics",
        "guardrails",
        "scope",
        "functional_requirements",
        "acceptance_criteria",
        "ux",
        "data",
        "dependencies",
        "integrations",
        "api_contracts",
        "assumptions",
        "backend_capabilities",
        "extensions",
        "non_functional_requirements",
        "open_questions",
        "quality_assurance",
        "risks",
        "technical_constraints",
        "release",
        "rollback",
        "observability",
        "security",
        "privacy",
        "approvals",
        "required_approvals",
        "product_decisions",
    ],
)
def test_each_missing_product_truth_section_blocks_for_pm_input(section: str) -> None:
    api = _api()
    bundle = _ready_bundle()
    del bundle[section]
    result = _validate(bundle)
    assert result.disposition is api.Disposition.PRODUCT_INPUT_REQUIRED
    assert "COMP.COMPLETENESS" in _codes(result)


def test_schema_or_runtime_failure_is_error_not_product_input() -> None:
    api = _api()
    bundle = _ready_bundle()
    del bundle["bundle_id"]
    result = _validate(bundle)
    assert result.disposition is api.Disposition.ERROR
    assert "CORE.STRUCTURE" in _codes(result)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("functional_requirements", "FR-001", "statement"), ""),
        (("product", "problem", "affected_customers"), ""),
        (("release", "approval_refs"), []),
    ],
)
def test_empty_required_product_truth_never_falls_through_schema_validation(
    path: tuple[str, ...], value: Any
) -> None:
    api = _api()
    bundle = _ready_bundle()
    parent = bundle
    for part in path[:-1]:
        parent = parent[part]
    parent[path[-1]] = value
    result = _validate(bundle)
    assert result.disposition is api.Disposition.PRODUCT_INPUT_REQUIRED
    assert "COMP.COMPLETENESS" in _codes(result)


def test_stage_specific_optionality_does_not_require_production_approval_for_draft_pr() -> None:
    api = _api()
    bundle = _ready_bundle()
    assert bundle["release"]["requested_autonomy_stage"] == "DRAFT_PR"
    assert all(
        requirement.get("required_before") != "PRODUCTION"
        for requirement in bundle["required_approvals"].values()
    )
    assert _validate(bundle).disposition is api.Disposition.ADMITTED


def test_nonapplicable_integrations_and_dependencies_may_be_explicitly_empty() -> None:
    api = _api()
    bundle = _ready_bundle()
    bundle["functional_requirements"]["FR-001"]["capability"] = "contract.validation"
    bundle["dependencies"] = {}
    bundle["integrations"] = {}
    _reseal(bundle)
    assert _validate(bundle).disposition is api.Disposition.ADMITTED


def test_blocking_open_question_requires_product_input() -> None:
    api = _api()
    bundle = _ready_bundle()
    bundle["open_questions"]["QUESTION-001"]["blocking"] = True
    bundle["open_questions"]["QUESTION-001"].pop("resolution")
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition is api.Disposition.PRODUCT_INPUT_REQUIRED
    assert "QUESTION.UNRESOLVED" in _codes(result)
    assert result.diagnostics[0].remediation is not None


def test_publisher_cannot_self_downgrade_unresolved_product_truth_to_warning() -> None:
    api = _api()
    bundle = _ready_bundle()
    bundle["open_questions"]["QUESTION-001"]["question"] = (
        "What privacy consent is required before production telemetry collection?"
    )
    bundle["open_questions"]["QUESTION-001"]["blocking"] = False
    bundle["open_questions"]["QUESTION-001"].pop("resolution")
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition is api.Disposition.PRODUCT_INPUT_REQUIRED
    diagnostic = next(item for item in result.diagnostics if item.rule_id == "QUESTION.UNRESOLVED")
    assert diagnostic.disposition == "PRODUCT_INPUT_REQUIRED"
    assert diagnostic.severity == "ERROR"
    assert diagnostic.remediation is not None


def test_compiler_unresolved_product_truth_blocks() -> None:
    api = _api()
    bundle = _ready_bundle()
    bundle["contract_status"] = "DRAFT"
    bundle["unresolved_product_truth"] = {
        "UNRESOLVED-OUTCOME": {
            "blocking": True,
            "question": "What customer outcome is approved?",
            "reason_code": "REQUIRED_PRODUCT_TRUTH_ABSENT",
            "target_pointer": "/product/outcome/customer_outcome",
        }
    }
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition is api.Disposition.PRODUCT_INPUT_REQUIRED
    assert "COMP.UNRESOLVED_PRODUCT_TRUTH" in _codes(result)


@pytest.mark.parametrize(
    ("mutation", "expected_rule"),
    [
        ("missing_requirement", "REF.REQUIREMENT"),
        ("wrong_entity", "REF.ENTITY"),
        ("wrong_acceptance", "REF.ACCEPTANCE"),
        ("missing_metric_policy", "REF.METRIC_POLICY"),
        ("missing_reporting_policy", "REF.REPORTING_POLICY"),
        ("missing_approval", "REF.APPROVAL"),
        ("missing_screen", "REF.UX"),
        ("edge_requirement", "REF.REQUIREMENT"),
        ("qa_requirement", "REF.REQUIREMENT"),
        ("release_guardrail", "REF.GUARDRAIL"),
        ("policy_metric", "REF.METRIC"),
        ("bad_source_mapping", "REF.SOURCE_IDENTITY"),
    ],
)
def test_reference_and_identity_failures_block(mutation: str, expected_rule: str) -> None:
    api = _api()
    bundle = _ready_bundle()
    if mutation == "missing_requirement":
        bundle["acceptance_criteria"]["AC-001"]["requirement_refs"] = ["FR-MISSING"]
    elif mutation == "wrong_entity":
        bundle["functional_requirements"]["FR-001"]["entity_ref"] = "ENTITY-MISSING"
    elif mutation == "wrong_acceptance":
        bundle["functional_requirements"]["FR-001"]["acceptance_criterion_refs"] = ["AC-MISSING"]
    elif mutation == "missing_metric_policy":
        bundle["metrics"]["north_stars"]["mvp"]["maturity_policy_ref"] = "POLICY-METRIC-X"
    elif mutation == "missing_reporting_policy":
        bundle["metrics"]["maturity_policies"]["POLICY-METRIC-EADPR"]["reporting_policy_ref"] = (
            "POLICY-REPORTING-X"
        )
    elif mutation == "missing_approval":
        bundle["release"]["approval_refs"] = ["APR-MISSING"]
    elif mutation == "missing_screen":
        bundle["ux"]["primary_journey"]["JOURNEY-STEP-PUBLISH"]["screen_ref"] = "SCREEN-MISSING"
    elif mutation == "edge_requirement":
        bundle["ux"]["edge_cases"]["EDGE-001"]["requirement_refs"] = ["FR-MISSING"]
    elif mutation == "qa_requirement":
        bundle["quality_assurance"]["expectations"]["QA-001"]["requirement_refs"] = ["FR-MISSING"]
    elif mutation == "release_guardrail":
        bundle["release"]["guardrail_refs"] = ["GUARD-MISSING"]
    elif mutation == "policy_metric":
        bundle["metrics"]["maturity_policies"]["POLICY-METRIC-EADPR"]["metric_ref"] = (
            "METRIC-NSM-MVP-MISSING"
        )
    else:
        bundle["source_identity_mappings"] = {
            "SOURCE-MAP-A": {
                "canonical_pointer": "/functional_requirements/FR-MISSING",
                "source_id": "FR-001",
                "source_pointer": "/functional_requirements/0",
            }
        }
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition is not api.Disposition.ADMITTED
    assert expected_rule in _codes(result)


@pytest.mark.parametrize(
    ("case", "expected_rule"),
    [
        ("missing", "APPROVAL.REQUIRED"),
        ("revoked", "APPROVAL.ACTIVE"),
        ("superseded", "APPROVAL.ACTIVE"),
        ("expired", "APPROVAL.FRESHNESS"),
        ("wrong_authority", "APPROVAL.AUTHORITY"),
        ("fabricated_actor", "APPROVAL.AUTHORITY"),
        ("stale_subject", "APPROVAL.SUBJECT"),
    ],
)
def test_required_approval_failures_block(case: str, expected_rule: str) -> None:
    api = _api()
    bundle = _ready_bundle()
    approval = bundle["approvals"]["APR-CONTRACT-001"]
    if case == "missing":
        del bundle["approvals"]["APR-CONTRACT-001"]
    elif case == "revoked":
        approval["status"] = "REVOKED"
        approval["revoked_at"] = "2026-07-30T01:00:00Z"
        approval["revocation_reason"] = "Product decision withdrawn"
    elif case == "superseded":
        approval["status"] = "SUPERSEDED"
        approval["superseded_by_approval_ref"] = "APR-CONTRACT-NEW"
    elif case == "expired":
        approval["expires_at"] = "2026-07-30T23:59:59Z"
    elif case == "wrong_authority":
        approval["role"] = "ENGINEER"
    elif case == "fabricated_actor":
        approval["actor_id"] = "OWNER-FABRICATED-001"
    else:
        approval["subject"]["digest"] = "sha256:" + "0" * 64
    result = _validate(bundle)
    assert result.disposition is api.Disposition.PRODUCT_INPUT_REQUIRED
    assert expected_rule in _codes(result)


def test_approval_subject_binds_exact_bundle_version_and_id() -> None:
    bundle = _ready_bundle()
    bundle["approvals"]["APR-CONTRACT-001"]["subject"]["version"] = "2.0.0"
    result = _validate(bundle)
    assert "APPROVAL.SUBJECT" in _codes(result)


def test_policy_and_release_approval_references_bind_their_exact_subjects() -> None:
    bundle = _ready_bundle()
    bundle["metrics"]["maturity_policies"]["POLICY-METRIC-EADPR"]["approval_ref"] = (
        "APR-METRIC-VAPDR"
    )
    bundle["release"]["approval_refs"] = ["APR-METRIC-EADPR"]
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition.value == "PRODUCT_INPUT_REQUIRED"
    assert "APPROVAL.SUBJECT" in _codes(result)


def test_product_decision_requires_exact_bundle_approval_subject() -> None:
    bundle = _ready_bundle()
    bundle["product_decisions"]["DECISION-CANONICAL-SCHEMA"]["approval_ref"] = "APR-METRIC-EADPR"
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition.value == "PRODUCT_INPUT_REQUIRED"
    assert "APPROVAL.SUBJECT" in _codes(result)


def test_approval_authority_requires_external_governed_grant_evidence() -> None:
    api = _api()
    bundle = _ready_bundle()
    context = _with_authority_evidence(_context(bundle), bundle, authority_grants=())
    result = _validator().validate(bundle, context)
    assert result.disposition is api.Disposition.PRODUCT_INPUT_REQUIRED
    assert "APPROVAL.AUTHORITY" in _codes(result)
    assert all(
        evidence["eligible_at"] is None and evidence["due_at"] is None
        for evidence in result.metric_eligibility.values()
    )


def test_caller_cannot_append_a_fabricated_unsigned_authority_grant() -> None:
    api = _api()
    bundle = _ready_bundle()
    bundle["approvals"]["APR-CONTRACT-001"]["actor_id"] = "OWNER-FABRICATED-001"
    fabricated = api.ApprovalAuthorityGrant(
        actor_id="OWNER-FABRICATED-001",
        role="PRODUCT_OWNER",
        authority_policy_id="AUTH-POLICY-CONTRACT-001",
        authority_policy_version="1.0.0",
        valid_from="2026-01-01T00:00:00Z",
        expires_at="2027-01-01T00:00:00Z",
    )
    context = _context(bundle)
    tampered = replace(
        context,
        authority_grants=(*context.authority_grants, fabricated),
    )
    result = _validator().validate(bundle, tampered)
    assert result.disposition is api.Disposition.ERROR
    assert "CORE.EVIDENCE_BINDING" in _codes(result)


def test_validator_exposes_no_authority_evidence_issuer_and_rejects_replay() -> None:
    api = _api()
    assert not hasattr(api.ApprovalAuthorityEvidence, "create")

    bundle = _ready_bundle()
    original_context = _context(bundle)
    bundle["product"]["outcome"]["customer_outcome"] = (
        "Customers complete a materially different approved workflow."
    )
    _reseal(bundle)
    replayed_context = replace(original_context, bundle_digest=canonical_digest(bundle))
    result = _validator().validate(bundle, replayed_context)
    assert result.disposition is api.Disposition.ERROR
    assert "CORE.EVIDENCE_BINDING" in _codes(result)


def test_declared_production_gate_is_not_a_granted_production_approval() -> None:
    api = _api()
    bundle = _ready_bundle()
    bundle["release"]["requested_autonomy_stage"] = "PRODUCTION"
    bundle["release"]["deployment_target"]["environment"] = "PRODUCTION"
    bundle["release"]["deployment_target"]["kind"] = "CLOUD"
    bundle["release"]["launch_intent"] = "GENERAL_AVAILABILITY"
    bundle["release"]["expectations"]["REL-001"]["environment"] = "PRODUCTION"
    bundle["required_approvals"]["APPROVAL-REQ-PRODUCTION"] = {
        "purpose": "Approve production promotion",
        "required_before": "PRODUCTION",
        "role": "PRODUCT_OWNER",
    }
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition is api.Disposition.PRODUCT_INPUT_REQUIRED
    assert {"APPROVAL.REQUIRED", "ALIGN.RELEASE_APPROVAL"} <= _codes(result)


def test_approval_authority_grant_must_cover_the_approval_instant() -> None:
    api = _api()
    bundle = _ready_bundle()
    context = _context(bundle)
    grants = tuple(
        replace(grant, valid_from="2026-07-30T12:00:00Z") for grant in context.authority_grants
    )
    result = _validator().validate(
        bundle,
        _with_authority_evidence(context, bundle, authority_grants=grants),
    )
    assert result.disposition is api.Disposition.PRODUCT_INPUT_REQUIRED
    assert "APPROVAL.AUTHORITY" in _codes(result)


def test_metric_policy_requires_metric_owner_role_and_named_owner_actor() -> None:
    api = _api()
    bundle = _ready_bundle()
    approval = bundle["approvals"]["APR-METRIC-EADPR"]
    approval["role"] = "PRODUCT_OWNER"
    context = _context(bundle)
    wrong_role_grant = api.ApprovalAuthorityGrant(
        actor_id="OWNER-PRODUCT-001",
        role="PRODUCT_OWNER",
        authority_policy_id="AUTH-POLICY-METRIC-001",
        authority_policy_version="1.0.0",
        valid_from="2026-01-01T00:00:00Z",
        expires_at="2027-01-01T00:00:00Z",
    )
    result = _validator().validate(
        bundle,
        _with_authority_evidence(
            context,
            bundle,
            authority_grants=(*context.authority_grants, wrong_role_grant),
        ),
    )
    assert result.disposition is api.Disposition.PRODUCT_INPUT_REQUIRED
    assert "APPROVAL.AUTHORITY" in _codes(result)

    bundle = _ready_bundle()
    bundle["metrics"]["maturity_policies"]["POLICY-METRIC-EADPR"]["owner_ref"] = "OWNER-OTHER-001"
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition is api.Disposition.PRODUCT_INPUT_REQUIRED
    assert "APPROVAL.AUTHORITY" in _codes(result)


def test_approval_supersession_references_must_exist_and_be_reciprocal() -> None:
    bundle = _ready_bundle()
    bundle["approvals"]["APR-CONTRACT-001"]["supersedes_approval_refs"] = ["APR-MISSING"]
    result = _validate(bundle)
    assert result.disposition.value == "PRODUCT_INPUT_REQUIRED"
    assert "REF.APPROVAL" in _codes(result)

    bundle = _ready_bundle()
    bundle["approvals"]["APR-CONTRACT-001"]["supersedes_approval_refs"] = ["APR-METRIC-EADPR"]
    result = _validate(bundle)
    assert result.disposition.value == "PRODUCT_INPUT_REQUIRED"
    assert "APPROVAL.ACTIVE" in _codes(result)


def test_expired_historical_approval_can_be_validly_superseded() -> None:
    api = _api()
    bundle = _ready_bundle()
    current = bundle["approvals"]["APR-CONTRACT-001"]
    current["approval_version"] = "2.0.0"
    predecessor = copy.deepcopy(current)
    predecessor["approval_version"] = "1.0.0"
    predecessor["status"] = "SUPERSEDED"
    predecessor["approved_at"] = "2026-07-29T00:00:00Z"
    predecessor["valid_from"] = "2026-07-01T00:00:00Z"
    predecessor["expires_at"] = "2026-07-30T12:00:00Z"
    predecessor["superseded_by_approval_ref"] = "APR-CONTRACT-001"
    predecessor["supersedes_approval_refs"] = []
    bundle["approvals"]["APR-CONTRACT-OLD"] = predecessor
    current["supersedes_approval_refs"] = ["APR-CONTRACT-OLD"]
    _reseal(bundle)

    result = _validate(bundle)
    assert result.disposition is api.Disposition.ADMITTED
    assert not ({"APPROVAL.ACTIVE", "APPROVAL.FRESHNESS", "APPROVAL.SUBJECT"} & _codes(result))

    bundle["product_decisions"]["DECISION-CANONICAL-SCHEMA"]["approval_ref"] = "APR-CONTRACT-OLD"
    _reseal(bundle)
    stale_reference = _validate(bundle)
    assert stale_reference.disposition is api.Disposition.PRODUCT_INPUT_REQUIRED
    assert "APPROVAL.ACTIVE" in _codes(stale_reference)


def test_supersession_cannot_cross_exact_subject_scope() -> None:
    bundle = _ready_bundle()
    predecessor = bundle["approvals"]["APR-METRIC-EADPR"]
    predecessor["status"] = "SUPERSEDED"
    predecessor["approval_version"] = "1.0.0"
    predecessor["approved_at"] = "2026-07-29T00:00:00Z"
    predecessor["superseded_by_approval_ref"] = "APR-CONTRACT-001"
    successor = bundle["approvals"]["APR-CONTRACT-001"]
    successor["approval_version"] = "2.0.0"
    successor["supersedes_approval_refs"] = ["APR-METRIC-EADPR"]
    _reseal(bundle)

    result = _validate(bundle)
    assert result.disposition.value == "PRODUCT_INPUT_REQUIRED"
    assert "APPROVAL.ACTIVE" in _codes(result)


def test_supersession_cannot_cross_an_exact_subject_digest() -> None:
    bundle = _ready_bundle()
    current = bundle["approvals"]["APR-CONTRACT-001"]
    current["approval_version"] = "2.0.0"
    predecessor = copy.deepcopy(current)
    predecessor["approval_version"] = "1.0.0"
    predecessor["status"] = "SUPERSEDED"
    predecessor["approved_at"] = "2026-07-29T00:00:00Z"
    predecessor["superseded_by_approval_ref"] = "APR-CONTRACT-001"
    predecessor["supersedes_approval_refs"] = []
    bundle["approvals"]["APR-CONTRACT-OLD"] = predecessor
    current["supersedes_approval_refs"] = ["APR-CONTRACT-OLD"]
    _reseal(bundle)
    predecessor["subject"]["digest"] = "sha256:" + "d" * 64

    result = _validate(bundle)
    assert result.disposition.value == "PRODUCT_INPUT_REQUIRED"
    assert "APPROVAL.ACTIVE" in _codes(result)


@pytest.mark.parametrize(
    ("case", "expected_rule"),
    [
        ("problem_hypothesis", "ALIGN.OUTCOME_HYPOTHESIS"),
        ("solution_non_goal", "ALIGN.SOLUTION_NON_GOAL"),
        ("metric_outcome", "ALIGN.METRIC_OUTCOME"),
        ("leading_equals_outcome", "ALIGN.LEADING_DISTINCT"),
        ("target_guardrail", "ALIGN.TARGET_GUARDRAIL"),
        ("scope_non_goal", "ALIGN.SCOPE_NON_GOAL"),
        ("undeclared_dependency", "ALIGN.DEPENDENCY"),
        ("autonomy_stage", "ALIGN.AUTONOMY"),
        ("production_without_approval", "ALIGN.RELEASE_APPROVAL"),
        ("telemetry_privacy", "ALIGN.SECURITY_PRIVACY"),
        ("ownership", "OWNERSHIP.PRODUCT_TRUTH"),
    ],
)
def test_named_contradiction_classes_block(case: str, expected_rule: str) -> None:
    api = _api()
    bundle = _ready_bundle()
    if case == "problem_hypothesis":
        bundle["product"]["hypothesis"]["statement"] = (
            "A decorative logo change will improve office catering."
        )
        bundle["product"]["hypothesis"]["falsification_condition"] = "The logo remains blue."
    elif case == "solution_non_goal":
        bundle["functional_requirements"]["FR-001"]["statement"] = bundle["scope"]["non_goals"][0]
    elif case == "metric_outcome":
        bundle["metrics"]["success"]["METRIC-SUCCESS-001"]["definition"] = (
            "Count decorative logo impressions."
        )
    elif case == "leading_equals_outcome":
        bundle["metrics"]["leading"]["METRIC-LEAD-001"]["definition"] = bundle["metrics"][
            "success"
        ]["METRIC-SUCCESS-001"]["definition"]
    elif case == "target_guardrail":
        bundle["guardrails"]["GUARD-SECURITY-001"]["description"] = "Bound POLICY-METRIC-EADPR"
        bundle["guardrails"]["GUARD-SECURITY-001"]["threshold"] = "At most 0.5 ratio"
    elif case == "scope_non_goal":
        bundle["scope"]["non_goals"].append(bundle["scope"]["in_scope"][0])
    elif case == "undeclared_dependency":
        bundle["functional_requirements"]["FR-001"]["capability"] = "integration.stripe"
    elif case == "autonomy_stage":
        bundle["release"]["requested_autonomy_stage"] = "PRODUCTION"
        for policy in bundle["metrics"]["maturity_policies"].values():
            policy["applicable_autonomy_stages"] = ["DRAFT_PR"]
    elif case == "production_without_approval":
        bundle["release"]["requested_autonomy_stage"] = "PRODUCTION"
        bundle["required_approvals"]["APPROVAL-REQ-CONTRACT"]["required_before"] = "DRAFT_PR"
    elif case == "telemetry_privacy":
        bundle["privacy"]["telemetry"]["allowed_fields"].append("customer_records")
    else:
        bundle["product"]["outcome"]["customer_outcome"] = (
            "PEOS engineering will decide the customer outcome later."
        )
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition is api.Disposition.PRODUCT_INPUT_REQUIRED
    assert expected_rule in _codes(result)


@pytest.mark.parametrize(
    ("operator", "value", "threshold"),
    [
        ("AT_LEAST", 0.8, "At most 0.5 ratio"),
        ("AT_LEAST", 0.8, "No more than 0.5 ratio"),
        ("AT_LEAST", 0.8, "At most 50 percent"),
        ("AT_LEAST", 0.8, "Must not exceed 50 percent"),
        ("EXACT", 0.8, "At most 0.5 ratio"),
        ("AT_MOST", 0.2, "At least 0.5 ratio"),
        ("EXACT", 0.2, "At least 0.5 ratio"),
    ],
)
def test_metric_target_interval_must_intersect_guardrail(
    operator: str,
    value: float,
    threshold: str,
) -> None:
    bundle = _ready_bundle()
    target = bundle["metrics"]["maturity_policies"]["POLICY-METRIC-EADPR"]["target"]
    target["operator"] = operator
    target["value"] = value
    bundle["guardrails"]["GUARD-SECURITY-001"]["description"] = "Bound POLICY-METRIC-EADPR"
    bundle["guardrails"]["GUARD-SECURITY-001"]["threshold"] = threshold
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition.value == "PRODUCT_INPUT_REQUIRED"
    assert "ALIGN.TARGET_GUARDRAIL" in _codes(result)


def test_guardrail_with_different_unit_does_not_constrain_metric_target() -> None:
    bundle = _ready_bundle()
    bundle["guardrails"]["GUARD-SECURITY-001"]["description"] = "Bound POLICY-METRIC-EADPR"
    bundle["guardrails"]["GUARD-SECURITY-001"]["threshold"] = "At most 0.5 seconds"
    _reseal(bundle)
    assert "ALIGN.TARGET_GUARDRAIL" not in _codes(_validate(bundle))


def test_generic_engineering_delivery_words_do_not_prove_metric_outcome_alignment() -> None:
    bundle = _ready_bundle()
    for metric in bundle["metrics"]["success"].values():
        metric["definition"] = "Engineering delivery wallpaper pixels rendered."
    for metric in bundle["metrics"]["north_stars"].values():
        metric["definition"] = "Engineering delivery wallpaper pixels rendered."
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition.value == "PRODUCT_INPUT_REQUIRED"
    assert "ALIGN.METRIC_OUTCOME" in _codes(result)


def test_incidental_traceability_and_owner_words_do_not_prove_metric_alignment() -> None:
    bundle = _ready_bundle()
    for metric in bundle["metrics"]["success"].values():
        metric["definition"] = "Traceable owner wallpaper preference count."
    for metric in bundle["metrics"]["north_stars"].values():
        metric["definition"] = "Traceable owner wallpaper preference count."
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition.value == "PRODUCT_INPUT_REQUIRED"
    assert "ALIGN.METRIC_OUTCOME" in _codes(result)


def test_scope_non_goal_support_negation_is_a_contradiction() -> None:
    bundle = _ready_bundle()
    bundle["scope"]["in_scope"].append("Customer data export")
    bundle["scope"]["non_goals"].append("Do not support customer data export")
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition.value == "PRODUCT_INPUT_REQUIRED"
    assert "ALIGN.SCOPE_NON_GOAL" in _codes(result)


def test_requirement_cannot_implement_a_lexically_nonidentical_non_goal() -> None:
    bundle = _ready_bundle()
    bundle["functional_requirements"]["FR-001"]["statement"] = (
        "Canonical account export download is provided."
    )
    bundle["scope"]["non_goals"].append("Do not support account export download")
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition.value == "PRODUCT_INPUT_REQUIRED"
    assert "ALIGN.SOLUTION_NON_GOAL" in _codes(result)


def test_ux_retention_and_data_prohibition_are_cross_channel_contradictions() -> None:
    bundle = _ready_bundle()
    bundle["ux"]["user_stories"]["US-001"]["i_want"] = "retain customer records"
    bundle["data"]["requirements"]["DATA-001"]["requirement"] = (
        "customer records are prohibited from retention"
    )
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition.value == "PRODUCT_INPUT_REQUIRED"
    assert "ALIGN.CROSS_CHANNEL" in _codes(result)


def test_natural_language_upper_bound_conflicts_with_metric_target() -> None:
    bundle = _ready_bundle()
    bundle["guardrails"]["GUARD-QUALITY-002"] = {
        "category": "QUALITY",
        "description": "Bound POLICY-METRIC-EADPR wallpaper rate",
        "response": "BLOCK",
        "threshold": "Must remain below 50 percent",
    }
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition.value == "PRODUCT_INPUT_REQUIRED"
    assert "ALIGN.TARGET_GUARDRAIL" in _codes(result)


def test_numeric_guardrail_without_exact_subject_fails_closed_as_ambiguous() -> None:
    bundle = _ready_bundle()
    bundle["guardrails"]["GUARD-QUALITY-002"] = {
        "category": "QUALITY",
        "description": "Limit cafeteria satisfaction",
        "response": "BLOCK",
        "threshold": "At most 50 percent",
    }
    _reseal(bundle)
    result = _validate(bundle)
    diagnostic = next(
        item
        for item in result.diagnostics
        if item.rule_id == "ALIGN.TARGET_GUARDRAIL"
        and item.field_path == "/guardrails/GUARD-QUALITY-002/threshold"
    )
    assert result.disposition.value == "PRODUCT_INPUT_REQUIRED"
    assert "exact metric or maturity-policy reference" in diagnostic.explanation


def test_unknown_or_tampered_extension_fails_closed() -> None:
    api = _api()
    bundle = _ready_bundle()
    extension = bundle["extensions"]["EXT-REPOSITORY-001"]
    extension["schema_id"] = "https://unknown.invalid/extension.json"
    extension["payload_digest"] = canonical_digest(extension["payload"])
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition is api.Disposition.UNSUPPORTED_REPOSITORY_EXTENSION
    assert "EXTENSION.SUPPORTED" in _codes(result)


def test_extension_payload_digest_and_target_are_verified() -> None:
    api = _api()
    bundle = _ready_bundle()
    constraint = bundle["extensions"]["EXT-REPOSITORY-001"]["payload"]["constraints"][
        "EXT-CONSTRAINT-001"
    ]
    constraint["target_pointer"] = "/product/unknown"
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition is api.Disposition.UNSUPPORTED_REPOSITORY_EXTENSION
    assert "EXTENSION.CONSTRAINT" in _codes(result)


def test_supported_extension_cannot_contradict_approved_core_truth() -> None:
    api = _api()
    bundle = _ready_bundle()
    extension = bundle["extensions"]["EXT-REPOSITORY-001"]
    constraint = extension["payload"]["constraints"]["EXT-CONSTRAINT-001"]
    constraint.update(
        {
            "constraint_value": "DRAFT_PR",
            "operator": "FORBID_VALUE",
            "target_pointer": "/release/requested_autonomy_stage",
        }
    )
    extension["payload_digest"] = canonical_digest(extension["payload"])
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition is api.Disposition.UNSUPPORTED_REPOSITORY_EXTENSION
    assert "EXTENSION.CONSTRAINT" in _codes(result)


def test_extension_pattern_rejects_nested_quantifiers_without_evaluation() -> None:
    api = _api()
    bundle = _ready_bundle()
    extension = bundle["extensions"]["EXT-REPOSITORY-001"]
    constraint = extension["payload"]["constraints"]["EXT-CONSTRAINT-001"]
    constraint.update(
        {
            "constraint_value": "(a+)+$",
            "operator": "MATCH_PATTERN",
            "target_pointer": "/product/problem/statement",
        }
    )
    bundle["product"]["problem"]["statement"] = "a" * 4095 + "X"
    extension["payload_digest"] = canonical_digest(extension["payload"])
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition is api.Disposition.UNSUPPORTED_REPOSITORY_EXTENSION
    assert "EXTENSION.CONSTRAINT" in _codes(result)


def test_extension_mapping_values_fail_closed_independent_of_insertion_order() -> None:
    api = _api()
    first = _ready_bundle()
    second = copy.deepcopy(first)
    first_constraint = first["extensions"]["EXT-REPOSITORY-001"]["payload"]["constraints"][
        "EXT-CONSTRAINT-001"
    ]
    second_constraint = second["extensions"]["EXT-REPOSITORY-001"]["payload"]["constraints"][
        "EXT-CONSTRAINT-001"
    ]
    first_constraint.update(
        {
            "constraint_value": {"first": 1, "second": 2},
            "operator": "FORBID_VALUE",
            "target_pointer": "/product/hypothesis",
        }
    )
    second_constraint.update(
        {
            "constraint_value": {"second": 2, "first": 1},
            "operator": "FORBID_VALUE",
            "target_pointer": "/product/hypothesis",
        }
    )
    for bundle in (first, second):
        extension = bundle["extensions"]["EXT-REPOSITORY-001"]
        extension["payload_digest"] = canonical_digest(extension["payload"])
        _reseal(bundle)
    assert canonical_digest(first) == canonical_digest(second)
    first_result = _validate(first)
    second_result = _validate(second)
    assert first_result.disposition is api.Disposition.ERROR
    assert first_result.canonical_bytes() == second_result.canonical_bytes()


def test_pmos_owned_extension_blocker_keeps_pmos_remediation_owner() -> None:
    bundle = _ready_bundle()
    extension = bundle["extensions"]["EXT-REPOSITORY-001"]
    extension["target_refs"] = ["FR-MISSING"]
    extension["payload_digest"] = canonical_digest(extension["payload"])
    _reseal(bundle)
    result = _validate(bundle)
    diagnostic = next(item for item in result.diagnostics if item.rule_id == "EXTENSION.CONSTRAINT")
    assert diagnostic.owner == "PMOS"
    assert diagnostic.remediation is not None
    assert diagnostic.remediation["decision_owner"] == "PMOS"


def test_hypothesis_and_requirement_direct_obligations_cannot_conflict() -> None:
    bundle = _ready_bundle()
    bundle["product"]["hypothesis"]["statement"] = "Customers must retain customer records"
    bundle["functional_requirements"]["FR-001"]["statement"] = (
        "Customers must not retain customer records"
    )
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition.value == "PRODUCT_INPUT_REQUIRED"
    assert "ALIGN.CROSS_CHANNEL" in _codes(result)


def test_scope_and_non_goal_direct_obligations_cannot_conflict() -> None:
    bundle = _ready_bundle()
    bundle["scope"]["in_scope"] = ["The system must retain customer records"]
    bundle["scope"]["non_goals"] = ["The system must not retain customer records"]
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition.value == "PRODUCT_INPUT_REQUIRED"
    assert "ALIGN.SCOPE_NON_GOAL" in _codes(result)


def test_product_truth_cannot_delegate_choice_by_responsibility_wording() -> None:
    bundle = _ready_bundle()
    bundle["product_decisions"]["DECISION-CANONICAL-SCHEMA"]["decision"] = (
        "Engineering is responsible for choosing the deployment target"
    )
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition.value == "PRODUCT_INPUT_REQUIRED"
    assert "OWNERSHIP.PRODUCT_TRUTH" in _codes(result)


def test_hypothesis_and_outcome_direct_obligations_cannot_conflict() -> None:
    bundle = _ready_bundle()
    bundle["product"]["hypothesis"]["statement"] = "Customers must retain customer records"
    bundle["product"]["outcome"]["customer_outcome"] = "Customers must not retain customer records"
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition.value == "PRODUCT_INPUT_REQUIRED"
    assert "ALIGN.CROSS_CHANNEL" in _codes(result)


def test_functional_requirement_and_data_obligations_cannot_conflict() -> None:
    bundle = _ready_bundle()
    bundle["functional_requirements"]["FR-001"]["statement"] = (
        "The system must accept canonical contracts"
    )
    bundle["data"]["requirements"]["DATA-001"]["requirement"] = (
        "The system must not accept canonical contracts"
    )
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition.value == "PRODUCT_INPUT_REQUIRED"
    assert "ALIGN.CROSS_CHANNEL" in _codes(result)


def test_mandatory_requirement_outside_declared_scope_blocks() -> None:
    bundle = _ready_bundle()
    requirement = bundle["functional_requirements"]["FR-001"]
    requirement["title"] = "Orbital catering telemetry"
    requirement["statement"] = "Provide orbital catering telemetry"
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition.value == "PRODUCT_INPUT_REQUIRED"
    assert "ALIGN.REQUIREMENT_SCOPE" in _codes(result)


def test_same_metric_cannot_have_incompatible_target_or_window_policies() -> None:
    bundle = _ready_bundle()
    policies = bundle["metrics"]["maturity_policies"]
    policies["POLICY-METRIC-EADPR-ALT"] = copy.deepcopy(policies["POLICY-METRIC-EADPR"])
    policies["POLICY-METRIC-EADPR-ALT"]["target"]["value"] = 0.95
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition.value == "PRODUCT_INPUT_REQUIRED"
    assert "ALIGN.POLICY_CONSISTENCY" in _codes(result)


def test_same_metric_policy_cannot_conflict_only_by_reporting_policy() -> None:
    bundle = _ready_bundle()
    policies = bundle["metrics"]["maturity_policies"]
    policies["POLICY-METRIC-EADPR-ALT"] = copy.deepcopy(policies["POLICY-METRIC-EADPR"])
    policies["POLICY-METRIC-EADPR-ALT"]["reporting_policy_ref"] = "POLICY-REPORTING-END-STATE"
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition.value == "PRODUCT_INPUT_REQUIRED"
    assert "ALIGN.POLICY_CONSISTENCY" in _codes(result)


def test_other_nonfunctional_category_requires_exact_source_category() -> None:
    bundle = _ready_bundle()
    del bundle["non_functional_requirements"]["NFR-LEGACY-CATEGORY"]["source_category"]
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition.value == "PRODUCT_INPUT_REQUIRED"
    assert "COMP.COMPLETENESS" in _codes(result)


def test_approved_compiler_output_requires_root_source_identity_mapping() -> None:
    bundle = _ready_bundle()
    bundle["provenance"]["compiler_provenance"] = {
        "compiler_id": "PMPE-PMOS-COMPILER",
        "compiler_version": "1.0.0",
        "input_digest": "sha256:" + "1" * 64,
    }
    bundle["source_identity_mappings"] = {}
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition.value == "ERROR"
    assert "REF.SOURCE_IDENTITY" in _codes(result)


def test_advisory_model_suggestions_cannot_block_or_admit() -> None:
    api = _api()
    bundle = _ready_bundle()
    suggestion = api.AdvisorySuggestion(
        suggestion_id="MODEL-001",
        field_path="/product/hypothesis",
        explanation="Possible contradiction",
    )
    result = _validator().validate(
        bundle,
        _context(bundle),
        advisory_suggestions=(suggestion,),
    )
    assert result.disposition is api.Disposition.ADMITTED
    assert result.advisory_suggestions[0].suggestion_id == suggestion.suggestion_id
    assert result.advisory_suggestions[0].field_path == suggestion.field_path
    assert (
        result.advisory_suggestions[0].explanation
        == "ADVISORY_TEXT_WITHHELD_REQUIRES_NAMED_HUMAN_REVIEW"
    )


def test_validation_is_pure_repeatable_and_byte_deterministic() -> None:
    bundle = _ready_bundle()
    before = copy.deepcopy(bundle)
    first = _validate(bundle)
    second = _validate(bundle)
    assert bundle == before
    assert first.canonical_bytes() == second.canonical_bytes()


def test_rule_set_digest_and_input_binding_change_independently() -> None:
    api = _api()
    bundle = _ready_bundle()
    default = _validator().validate(bundle, _context(bundle))
    registry = api.default_rule_registry(rule_set_version="1.0.1")
    changed_rules = _validator(registry).validate(bundle, _context(bundle))
    assert changed_rules.rule_set_digest != default.rule_set_digest
    changed_bundle = copy.deepcopy(bundle)
    changed_bundle["assumptions"]["ASM-001"]["statement"] += " Clarified."
    _reseal(changed_bundle)
    changed_input = _validate(changed_bundle)
    assert changed_input.bundle_digest != default.bundle_digest

    mutated_evaluator = api.default_rule_registry().with_evaluator(
        "ALIGN.SCOPE_NON_GOAL", lambda _bundle, _context: ()
    )
    assert mutated_evaluator.digest != api.default_rule_registry().digest
    changed_rule_version = api.default_rule_registry().with_rule_metadata(
        "ALIGN.SCOPE_NON_GOAL", version="1.0.1"
    )
    assert changed_rule_version.digest != api.default_rule_registry().digest


def test_evaluator_identity_cannot_be_spoofed_with_module_and_qualname() -> None:
    api = _api()
    bundle = _ready_bundle()
    bundle["approvals"]["APR-CONTRACT-001"]["subject"]["digest"] = "sha256:" + "0" * 64
    original = next(
        rule for rule in api.default_rule_registry().rules if rule.rule_id == "APPROVAL.SUBJECT"
    ).evaluator

    def bypass(_bundle: Any, _context: Any) -> tuple[Any, ...]:
        return ()

    bypass.__module__ = original.__module__
    bypass.__qualname__ = original.__qualname__
    registry = api.default_rule_registry().with_evaluator("APPROVAL.SUBJECT", bypass)
    assert registry.digest != api.default_rule_registry().digest
    result = _validator(registry).validate(bundle, _context(bundle))
    assert result.disposition is api.Disposition.ERROR
    assert "CORE.RULE_SET_INTEGRITY" in _codes(result)


def test_missing_or_weakened_mandatory_rule_fails_closed() -> None:
    api = _api()
    bundle = _ready_bundle()
    missing = api.default_rule_registry().without("APPROVAL.SUBJECT")
    result = _validator(missing).validate(bundle, _context(bundle))
    assert result.disposition is api.Disposition.ERROR
    assert "CORE.RULE_SET_INTEGRITY" in _codes(result)

    weakened = api.default_rule_registry().with_rule_metadata(
        "APPROVAL.SUBJECT", blocking=False, severity="WARNING"
    )
    result = _validator(weakened).validate(bundle, _context(bundle))
    assert result.disposition is api.Disposition.ERROR
    assert "CORE.RULE_SET_INTEGRITY" in _codes(result)


def test_rule_exception_fails_closed_and_never_admits() -> None:
    api = _api()
    bundle = _ready_bundle()

    def explode(_bundle: Any, _context: Any) -> Any:
        raise RuntimeError("planted evaluator failure")

    registry = api.default_rule_registry().with_evaluator("ALIGN.SCOPE_NON_GOAL", explode)
    result = _validator(registry).validate(bundle, _context(bundle))
    assert result.disposition is api.Disposition.ERROR
    assert "CORE.RULE_SET_INTEGRITY" in _codes(result)


def test_approval_evaluator_bypass_is_not_an_approved_rule_implementation() -> None:
    api = _api()
    bundle = _ready_bundle()
    bundle["approvals"]["APR-CONTRACT-001"]["subject"]["digest"] = "sha256:" + "0" * 64
    bypass = api.default_rule_registry().with_evaluator(
        "APPROVAL.SUBJECT", lambda _bundle, _context: ()
    )
    result = _validator(bypass).validate(bundle, _context(bundle))
    assert result.disposition is api.Disposition.ERROR
    assert "CORE.RULE_SET_INTEGRITY" in _codes(result)


def test_noncanonical_runtime_value_fails_closed_without_raising() -> None:
    api = _api()
    bundle = _ready_bundle()
    bundle["assumptions"]["ASM-001"]["statement"] = {"not-json"}
    context = api.ValidationContext(
        lineage_id="LINEAGE-000001",
        ingestion_attempt_id="ATTEMPT-000001",
        bundle_digest="sha256:" + "0" * 64,
        evaluated_at=EVALUATED_AT,
        lineage_received_at=RECEIVED_AT,
    )
    result = _validator().validate(bundle, context)
    assert result.disposition is api.Disposition.ERROR
    assert "CORE.EVIDENCE_BINDING" in _codes(result)


def test_validator_never_fabricates_a_missing_product_default() -> None:
    bundle = _ready_bundle()
    del bundle["product"]
    before = copy.deepcopy(bundle)
    result = _validate(bundle)
    assert bundle == before
    assert result.disposition.value == "PRODUCT_INPUT_REQUIRED"
    assert all(
        item.remediation["recommended_technical_default"]
        == "NO_DEFAULT_ENGINEERING_MUST_NOT_INVENT_PRODUCT_TRUTH"
        for item in result.diagnostics
        if item.remediation is not None
    )


def test_unsupported_schema_or_rule_set_version_fails_closed() -> None:
    api = _api()
    bundle = _ready_bundle()
    bundle["schema_version"] = "9.0.0"
    result = _validate(bundle)
    assert result.disposition is api.Disposition.ERROR
    assert "CORE.UNSUPPORTED_VERSION" in _codes(result)

    bundle = _ready_bundle()
    unsupported = api.default_rule_registry(rule_set_version="9.0.0")
    result = _validator(unsupported).validate(bundle, _context(bundle))
    assert result.disposition is api.Disposition.ERROR
    assert "CORE.UNSUPPORTED_VERSION" in _codes(result)


def test_context_digest_lineage_and_attempt_binding_is_mandatory() -> None:
    api = _api()
    bundle = _ready_bundle()
    context = api.ValidationContext(
        lineage_id="LINEAGE-000001",
        ingestion_attempt_id="ATTEMPT-000001",
        bundle_digest="sha256:" + "0" * 64,
        evaluated_at=EVALUATED_AT,
        lineage_received_at=RECEIVED_AT,
    )
    result = _validator().validate(bundle, context)
    assert result.disposition is api.Disposition.ERROR
    assert "CORE.EVIDENCE_BINDING" in _codes(result)


def test_intake_identity_attestation_is_mandatory_and_tamper_evident() -> None:
    api = _api()
    bundle = _ready_bundle()
    context = _context(bundle)
    missing = _validator().validate(bundle, replace(context, intake_identity=None))
    assert missing.disposition is api.Disposition.ERROR
    assert "CORE.EVIDENCE_BINDING" in _codes(missing)

    assert context.intake_identity is not None
    tampered_identity = replace(context.intake_identity, fingerprint="0" * 64)
    tampered = _validator().validate(
        bundle,
        replace(context, intake_identity=tampered_identity),
    )
    assert tampered.disposition is api.Disposition.ERROR
    assert "CORE.EVIDENCE_BINDING" in _codes(tampered)


def test_same_lineage_correction_requires_latest_persisted_predecessor() -> None:
    api = _api()
    bundle = _ready_bundle()
    result = _validate(
        bundle,
        attempt_id="ATTEMPT-000002",
        correction_reference=CorrectionReference(
            lineage_id="LINEAGE-000001",
            attempt_id="ATTEMPT-000001",
        ),
    )
    assert result.disposition is api.Disposition.ERROR
    assert "CORE.EVIDENCE_BINDING" in _codes(result)


def test_correction_lineage_mismatch_blocks() -> None:
    api = _api()
    bundle = _ready_bundle()
    result = _validate(
        bundle,
        lineage_id="LINEAGE-000002",
        attempt_id="ATTEMPT-000002",
        correction_reference=CorrectionReference(
            lineage_id="LINEAGE-000001",
            attempt_id="ATTEMPT-000001",
        ),
    )
    assert result.disposition is api.Disposition.ERROR
    assert "LINEAGE.CORRECTION_BINDING" in _codes(result)


def test_correction_context_requires_original_durable_lineage_time() -> None:
    api = _api()
    receipt = SimpleNamespace(
        lineage_id="LINEAGE-000001",
        attempt_id="ATTEMPT-000002",
        received_at="2026-07-31T00:00:00Z",
        correction_reference=CorrectionReference(
            lineage_id="LINEAGE-000001",
            attempt_id="ATTEMPT-000001",
        ),
    )
    with pytest.raises(ValueError, match="original lineage receipt time"):
        api.ValidationContext.from_intake_receipt(
            receipt,
            bundle_digest="sha256:" + "0" * 64,
            evaluated_at=EVALUATED_AT,
            fingerprint_provider=FINGERPRINTS,
        )


def test_possible_duplicate_is_visible_but_does_not_coalesce_lineage() -> None:
    api = _api()
    bundle = _ready_bundle()
    result = _validate(
        bundle,
        lineage_id="LINEAGE-000002",
        attempt_id="ATTEMPT-000002",
        possible_duplicate=True,
    )
    assert result.disposition is api.Disposition.WARNING
    assert "LINEAGE.POSSIBLE_DUPLICATE" in _codes(result)


def test_pending_policy_has_no_eligibility_or_due_time() -> None:
    api = _api()
    bundle = _ready_bundle()
    policy = bundle["metrics"]["maturity_policies"]["POLICY-METRIC-EADPR"]
    policy["target"] = {
        "baseline_plan": "Approve after the first prospective cohort.",
        "status": "BASELINE_REQUIRED",
        "unit": "ratio",
    }
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition is api.Disposition.PRODUCT_INPUT_REQUIRED
    evidence = result.metric_eligibility["POLICY-METRIC-EADPR"]
    assert evidence["eligible_at"] is None
    assert evidence["due_at"] is None


def test_blocked_bundle_never_receives_metric_eligibility_or_due_time() -> None:
    api = _api()
    bundle = _ready_bundle()
    del bundle["product"]
    result = _validate(bundle)
    assert result.disposition is api.Disposition.PRODUCT_INPUT_REQUIRED
    assert result.metric_eligibility
    assert all(
        evidence["eligible_at"] is None and evidence["due_at"] is None
        for evidence in result.metric_eligibility.values()
    )


@pytest.mark.parametrize(
    ("section", "record", "field"),
    [
        ("maturity_policies", "POLICY-METRIC-EADPR", "target"),
        ("maturity_policies", "POLICY-METRIC-EADPR", "delivery_window"),
        ("maturity_policies", "POLICY-METRIC-EADPR", "reporting_window"),
        ("reporting_policies", "POLICY-REPORTING-MVP", "denominator"),
        ("reporting_policies", "POLICY-REPORTING-MVP", "calculation"),
    ],
)
def test_missing_metric_target_window_or_denominator_requires_product_input(
    section: str,
    record: str,
    field: str,
) -> None:
    api = _api()
    bundle = _ready_bundle()
    del bundle["metrics"][section][record][field]
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition is api.Disposition.PRODUCT_INPUT_REQUIRED
    assert "COMP.COMPLETENESS" in _codes(result)


def test_invalid_semantic_field_type_is_a_structural_error() -> None:
    api = _api()
    bundle = _ready_bundle()
    bundle["metrics"]["success"] = ["not", "a", "registry"]
    result = _validate(bundle)
    assert result.disposition is api.Disposition.ERROR
    assert "CORE.STRUCTURE" in _codes(result)


@pytest.mark.parametrize(
    ("case", "expected_rule"),
    [
        ("ux_api", "ALIGN.CROSS_CHANNEL"),
        ("release_rollback", "ALIGN.RELEASE_ROLLBACK"),
        ("observability_privacy", "ALIGN.OBSERVABILITY_REPORTING"),
    ],
)
def test_cross_section_contradictions_block(case: str, expected_rule: str) -> None:
    api = _api()
    bundle = _ready_bundle()
    if case == "ux_api":
        bundle["ux"]["user_stories"]["US-001"]["i_want"] = "must retain customer records"
        bundle["data"]["requirements"]["DATA-001"]["requirement"] = (
            "must not retain customer records"
        )
    elif case == "release_rollback":
        bundle["release"]["requested_autonomy_stage"] = "PRODUCTION"
        bundle["rollback"]["data_loss_tolerance"] = "No data loss"
        bundle["rollback"]["rpo"] = "P1D"
        bundle["required_approvals"]["APPROVAL-REQ-PRODUCTION"] = {
            "purpose": "Approve production promotion",
            "required_before": "PRODUCTION",
            "role": "PRODUCT_OWNER",
        }
    else:
        bundle["observability"]["requirements"]["OBS-001"]["signal"] = "customer_records"
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition is api.Disposition.PRODUCT_INPUT_REQUIRED
    assert expected_rule in _codes(result)


def test_direct_paraphrased_ownership_and_prohibition_conflicts_block() -> None:
    bundle = _ready_bundle()
    bundle["product"]["outcome"]["customer_outcome"] = (
        "Engineering will choose the customer outcome after intake."
    )
    _reseal(bundle)
    ownership_result = _validate(bundle)
    assert "OWNERSHIP.PRODUCT_TRUTH" in _codes(ownership_result)

    bundle = _ready_bundle()
    bundle["ux"]["user_stories"]["US-001"]["i_want"] = "must retain customer records"
    bundle["data"]["requirements"]["DATA-001"]["requirement"] = "must never retain customer records"
    _reseal(bundle)
    contradiction_result = _validate(bundle)
    assert "ALIGN.CROSS_CHANNEL" in _codes(contradiction_result)

    bundle = _ready_bundle()
    bundle["ux"]["user_stories"]["US-001"]["i_want"] = "shall retain customer records"
    bundle["data"]["requirements"]["DATA-001"]["requirement"] = "must not store customer records"
    _reseal(bundle)
    paraphrased_result = _validate(bundle)
    assert "ALIGN.CROSS_CHANNEL" in _codes(paraphrased_result)


def test_one_generic_shared_word_does_not_prove_metric_outcome_alignment() -> None:
    bundle = _ready_bundle()
    bundle["metrics"]["success"]["METRIC-SUCCESS-001"]["definition"] = (
        "Contract logo impression count."
    )
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition.value == "PRODUCT_INPUT_REQUIRED"
    assert "ALIGN.METRIC_OUTCOME" in _codes(result)


def test_every_north_star_requires_deterministic_outcome_alignment() -> None:
    bundle = _ready_bundle()
    for north_star in bundle["metrics"]["north_stars"].values():
        north_star["definition"] = "Orbital catering and wallpaper color impression count."
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition.value == "PRODUCT_INPUT_REQUIRED"
    assert "ALIGN.METRIC_OUTCOME" in _codes(result)
    paths = {
        diagnostic.field_path
        for diagnostic in result.diagnostics
        if diagnostic.rule_id == "ALIGN.METRIC_OUTCOME"
    }
    assert paths == {"/metrics/north_stars/end_state", "/metrics/north_stars/mvp"}


def test_production_autonomy_uses_end_state_policy_and_exact_environment() -> None:
    bundle = _ready_bundle()
    release = bundle["release"]
    release["requested_autonomy_stage"] = "PRODUCTION"
    release["deployment_target"] = {
        "description": "Approved production delivery target.",
        "environment": "PRODUCTION",
        "kind": "CLOUD",
    }
    release["expectations"] = {
        "REL-001": {
            "environment": "PRODUCTION",
            "expectation": "Promote only with exact production admission evidence.",
        }
    }
    release["launch_intent"] = "GENERAL_AVAILABILITY"
    bundle["required_approvals"]["APPROVAL-REQ-PRODUCTION"] = {
        "purpose": "Approve production promotion",
        "required_before": "PRODUCTION",
        "role": "PRODUCT_OWNER",
    }
    bundle["approvals"]["APR-PRODUCTION-001"] = copy.deepcopy(
        bundle["approvals"]["APR-CONTRACT-001"]
    )
    release["approval_refs"].append("APR-PRODUCTION-001")
    _reseal(bundle)
    context = _context(bundle)
    production_grant = _api().ApprovalRequirementGrant(
        requirement_id="APPROVAL-REQ-PRODUCTION",
        approval_id="APR-PRODUCTION-001",
    )
    context = _with_authority_evidence(
        context,
        bundle,
        requirement_grants=(*context.approval_requirement_grants, production_grant),
    )
    assert _validator().validate(bundle, context).disposition.value == "ADMITTED"

    policies = bundle["metrics"]["maturity_policies"]
    policies["POLICY-METRIC-VAPDR"]["applicable_autonomy_stages"] = ["DRAFT_PR"]
    policies["POLICY-METRIC-FIRST-PASS"]["applicable_autonomy_stages"] = ["PRODUCTION"]
    release["deployment_target"]["environment"] = "LOCAL"
    _reseal(bundle)
    context = _with_authority_evidence(
        _context(bundle),
        bundle,
        requirement_grants=(*_context(bundle).approval_requirement_grants, production_grant),
    )
    result = _validator().validate(bundle, context)
    assert result.disposition.value == "PRODUCT_INPUT_REQUIRED"
    assert "ALIGN.AUTONOMY" in _codes(result)


def test_retrospective_policy_approval_never_backdates_eligibility() -> None:
    bundle = _ready_bundle()
    approval = bundle["approvals"]["APR-METRIC-EADPR"]
    approval["approved_at"] = "2026-07-30T18:00:00Z"
    approval["valid_from"] = "2026-07-30T18:00:00Z"
    _reseal(bundle)
    result = _validate(bundle)
    evidence = result.metric_eligibility["POLICY-METRIC-EADPR"]
    assert evidence["eligible_at"] == "2026-07-30T18:00:00Z"
    assert evidence["eligible_at"] != RECEIVED_AT


@pytest.mark.parametrize(
    ("duration", "expected_disposition", "expected_due"),
    [
        ("P1W", "ADMITTED", "2026-08-06T12:00:00Z"),
        ("PT0.5S", "ADMITTED", "2026-07-30T12:00:00.500000Z"),
        ("P1M", "PRODUCT_INPUT_REQUIRED", None),
    ],
)
def test_metric_policy_duration_semantics_are_explicit_and_deterministic(
    duration: str,
    expected_disposition: str,
    expected_due: str | None,
) -> None:
    bundle = _ready_bundle()
    bundle["metrics"]["maturity_policies"]["POLICY-METRIC-EADPR"]["delivery_window"]["duration"] = (
        duration
    )
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition.value == expected_disposition
    assert result.metric_eligibility["POLICY-METRIC-EADPR"]["due_at"] == expected_due
    if expected_due is None:
        assert "COMP.TEMPORAL" in _codes(result)


def test_metric_eligibility_evaluation_failure_is_an_error_not_admission() -> None:
    api = _api()
    bundle = _ready_bundle()
    bundle["metrics"]["maturity_policies"]["POLICY-METRIC-EADPR"]["delivery_window"]["duration"] = (
        "P3000000D"
    )
    _reseal(bundle)
    result = _validate(bundle)
    assert result.disposition is api.Disposition.ERROR
    assert "CORE.METRIC_EVIDENCE" in _codes(result)
    assert all(
        evidence == {"due_at": None, "eligible_at": None}
        for evidence in result.metric_eligibility.values()
    )


def test_invalid_calendar_timestamp_and_evaluation_before_receipt_fail_closed() -> None:
    api = _api()
    bundle = _ready_bundle()
    bundle["provenance"]["published_at"] = "2026-02-31T00:00:00Z"
    _reseal(bundle)
    invalid_date = _validate(bundle)
    assert invalid_date.disposition is api.Disposition.PRODUCT_INPUT_REQUIRED
    assert "COMP.TEMPORAL" in _codes(invalid_date)

    bundle = _ready_bundle()
    context = replace(_context(bundle), evaluated_at="2026-07-30T11:59:59Z")
    before_receipt = _validator().validate(bundle, context)
    assert before_receipt.disposition is api.Disposition.ERROR
    assert "CORE.EVIDENCE_BINDING" in _codes(before_receipt)


def test_secret_values_never_appear_in_diagnostics_or_advisories() -> None:
    api = _api()
    secret = "ghp_0123456789abcdefghijklmnop"
    bundle = _ready_bundle()
    bundle["product"]["outcome"]["customer_outcome"] = f"Engineering decides {secret}"
    _reseal(bundle)
    result = _validator().validate(
        bundle,
        _context(bundle),
        advisory_suggestions=(
            api.AdvisorySuggestion(
                suggestion_id="MODEL-SECRET",
                field_path="/product/outcome/customer_outcome",
                explanation=f"Possible concern: {secret}",
            ),
        ),
    )
    assert secret not in result.canonical_bytes().decode()


def test_unrestricted_source_identity_never_appears_in_diagnostics() -> None:
    bundle = _ready_bundle()
    secret = "opaque-source-credential-Z9x4Q7n2L8m5"
    bundle["provenance"]["source_id"] = secret
    bundle["provenance"]["compiler_provenance"] = {
        "compiler_id": "PMPE-CANONICAL-COMPILER",
        "compiler_version": "1.0.0",
        "input_digest": "sha256:" + "c" * 64,
    }
    _reseal(bundle)
    result = _validate(bundle)
    assert "REF.SOURCE_IDENTITY" in _codes(result)
    assert secret not in result.canonical_bytes().decode()


def test_diagnostic_contract_is_machine_readable_and_pm_actionable() -> None:
    bundle = _ready_bundle()
    del bundle["product"]
    diagnostic = _validate(bundle).diagnostics[0]
    payload = diagnostic.as_dict()
    assert set(payload) == {
        "category",
        "disposition",
        "explanation",
        "field_path",
        "ingestion_attempt_id",
        "input_digest",
        "lineage_id",
        "next_action",
        "owner",
        "relationship",
        "remediation",
        "rule_id",
        "rule_set_digest",
        "rule_version",
        "severity",
    }
    assert payload["owner"] == "PMOS"
    assert payload["remediation"]["status"] == "OPEN"
