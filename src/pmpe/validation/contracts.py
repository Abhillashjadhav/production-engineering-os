"""Deterministic semantic admission for canonical PMOS contract bundles.

Structural validity is owned by the issue #62 JSON Schema and source conversion
by the issue #76 compiler.  This module extends the existing validation package
with the single canonical semantic boundary: named, versioned rules evaluate an
immutable bundle and emit digest-bound, PM-actionable evidence.  Evaluation is
pure; the file evidence store is an explicit, separate persistence step.
"""

from __future__ import annotations

import copy
import fcntl
import hashlib
import hmac
import inspect
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from jsonschema import Draft202012Validator

from pmpe.artifacts.store import ArtifactStore
from pmpe.config import packaged_schema_dir
from pmpe.contracts.canonical import canonical_digest, canonical_json_bytes
from pmpe.contracts.intake import (
    CorrectionReference,
    IntakeReceipt,
    KeyedFingerprintProvider,
)

VALIDATOR_VERSION = "1.0.0"
RULE_SET_VERSION = "1.0.0"
SUPPORTED_SCHEMA_VERSIONS = frozenset({"1.0.0"})
SUPPORTED_EXTENSION_SCHEMAS = frozenset(
    {("https://example.invalid/schemas/repository-extension.schema.json", "1.0.0")}
)

_SAFE_ID = re.compile(r"^[A-Z][A-Z0-9-]{0,127}$")
_SECRET_PATTERNS = (
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(
        r"(?i)\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)"
        r"\s*[:=]\s*[\"']?[A-Za-z0-9_./+=-]{12,}"
    ),
)
_PERSONAL_PATTERNS = (re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),)
_INTAKE_EVIDENCE_PROFILE = "PMPE-VALIDATION-INTAKE-EVIDENCE-1"
_OWNERSHIP_PATTERNS = (
    re.compile(r"(?i)\b(?:engineering|peos)\s+(?:will\s+)?decide\b"),
    re.compile(r"(?i)\bto be decided by (?:engineering|peos)\b"),
    re.compile(r"(?i)\btbd by (?:engineering|peos)\b"),
    re.compile(r"(?i)\bunnamed future engineering decision\b"),
)
_STOP_WORDS = frozenset(
    {
        "about",
        "after",
        "against",
        "approved",
        "before",
        "being",
        "between",
        "could",
        "every",
        "from",
        "have",
        "into",
        "more",
        "must",
        "only",
        "other",
        "should",
        "their",
        "there",
        "these",
        "those",
        "through",
        "using",
        "when",
        "where",
        "which",
        "without",
        "would",
    }
)
_SEMANTIC_TOP_LEVEL_SECTIONS = frozenset(
    {
        "acceptance_criteria",
        "api_contracts",
        "approvals",
        "assumptions",
        "backend_capabilities",
        "data",
        "dependencies",
        "extensions",
        "functional_requirements",
        "guardrails",
        "integrations",
        "metrics",
        "non_functional_requirements",
        "observability",
        "open_questions",
        "privacy",
        "product",
        "product_decisions",
        "quality_assurance",
        "release",
        "required_approvals",
        "risks",
        "rollback",
        "scope",
        "security",
        "technical_constraints",
        "ux",
    }
)


class Disposition(StrEnum):
    ERROR = "ERROR"
    PRODUCT_INPUT_REQUIRED = "PRODUCT_INPUT_REQUIRED"
    WARNING = "WARNING"
    UNSUPPORTED_REPOSITORY_EXTENSION = "UNSUPPORTED_REPOSITORY_EXTENSION"
    ADMITTED = "ADMITTED"


class RuleCategory(StrEnum):
    CORE = "CORE"
    COMPLETENESS = "COMPLETENESS"
    REFERENCE = "REFERENCE"
    APPROVAL = "APPROVAL"
    QUESTION = "QUESTION"
    ALIGNMENT = "ALIGNMENT"
    OWNERSHIP = "OWNERSHIP"
    EXTENSION = "EXTENSION"
    METRIC_POLICY = "METRIC_POLICY"
    LINEAGE = "LINEAGE"


class Owner(StrEnum):
    PMOS = "PMOS"
    PEOS = "PEOS"
    SECURITY = "SECURITY"
    REPOSITORY_OWNER = "REPOSITORY_OWNER"
    NAMED_HUMAN_ROLE = "NAMED_HUMAN_ROLE"


@dataclass(frozen=True)
class AdvisorySuggestion:
    suggestion_id: str
    field_path: str
    explanation: str

    def sanitized(self) -> AdvisorySuggestion:
        return AdvisorySuggestion(
            suggestion_id=_sanitize(self.suggestion_id),
            field_path=_sanitize_path(self.field_path),
            explanation="ADVISORY_TEXT_WITHHELD_REQUIRES_NAMED_HUMAN_REVIEW",
        )

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class ApprovalAuthorityGrant:
    actor_id: str
    role: str
    authority_policy_id: str
    authority_policy_version: str
    valid_from: str
    expires_at: str
    status: str = "ACTIVE"

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class IntakeIdentityEvidence:
    receipt: dict[str, Any]
    receipt_digest: str
    key_version: str
    fingerprint: str
    profile: str = _INTAKE_EVIDENCE_PROFILE

    @classmethod
    def create(
        cls,
        receipt: IntakeReceipt,
        fingerprint_provider: KeyedFingerprintProvider,
    ) -> IntakeIdentityEvidence:
        receipt_payload = receipt.as_dict()
        evidence_payload = {
            "profile": _INTAKE_EVIDENCE_PROFILE,
            "receipt": receipt_payload,
        }
        return cls(
            receipt=copy.deepcopy(receipt_payload),
            receipt_digest=canonical_digest(receipt_payload),
            key_version=fingerprint_provider.key_version,
            fingerprint=fingerprint_provider.fingerprint(
                "validation-intake-evidence",
                canonical_json_bytes(evidence_payload),
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "key_version": self.key_version,
            "profile": self.profile,
            "receipt": copy.deepcopy(self.receipt),
            "receipt_digest": self.receipt_digest,
        }

    def verify(self, fingerprint_provider: KeyedFingerprintProvider) -> bool:
        try:
            receipt_digest = canonical_digest(self.receipt)
            payload = canonical_json_bytes({"profile": self.profile, "receipt": self.receipt})
        except (TypeError, ValueError):
            return False
        if (
            self.profile != _INTAKE_EVIDENCE_PROFILE
            or self.receipt_digest != receipt_digest
            or not re.fullmatch(r"[0-9a-fA-F]{32,}", self.fingerprint)
        ):
            return False
        candidate = next(
            (
                item
                for item in fingerprint_provider.candidate_fingerprints(
                    "validation-intake-evidence", payload
                )
                if item.key_version == self.key_version
            ),
            None,
        )
        return candidate is not None and hmac.compare_digest(candidate.value, self.fingerprint)


@dataclass(frozen=True)
class ValidationContext:
    lineage_id: str
    ingestion_attempt_id: str
    bundle_digest: str
    evaluated_at: str
    lineage_received_at: str
    correction_reference: CorrectionReference | None = None
    possible_duplicate: bool = False
    authority_grants: tuple[ApprovalAuthorityGrant, ...] = ()
    intake_identity: IntakeIdentityEvidence | None = None

    @classmethod
    def from_intake_receipt(
        cls,
        receipt: Any,
        *,
        bundle_digest: str,
        evaluated_at: str,
        lineage_received_at: str | None = None,
        possible_duplicate: bool = False,
        authority_grants: tuple[ApprovalAuthorityGrant, ...] = (),
        fingerprint_provider: KeyedFingerprintProvider,
    ) -> ValidationContext:
        if receipt.correction_reference is not None and lineage_received_at is None:
            raise ValueError(
                "correction validation requires the durable original lineage receipt time"
            )
        return cls(
            lineage_id=str(receipt.lineage_id),
            ingestion_attempt_id=str(receipt.attempt_id),
            bundle_digest=bundle_digest,
            evaluated_at=evaluated_at,
            lineage_received_at=lineage_received_at or str(receipt.received_at),
            correction_reference=receipt.correction_reference,
            possible_duplicate=possible_duplicate,
            authority_grants=authority_grants,
            intake_identity=IntakeIdentityEvidence.create(receipt, fingerprint_provider),
        )


@dataclass(frozen=True)
class Finding:
    field_path: str
    explanation: str
    next_action: str
    relationship: str | None = None
    owner: Owner | None = None
    disposition: Disposition | None = None
    severity: str | None = None


RuleEvaluator = Callable[[Mapping[str, Any], ValidationContext], tuple[Finding, ...]]


class ValidationEvidenceLookup(Protocol):
    def load_attempt(self, attempt_id: str) -> dict[str, Any]: ...

    def lineage_summary(self, lineage_id: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ValidationRule:
    rule_id: str
    version: str
    category: RuleCategory
    owner: Owner
    severity: str
    disposition: Disposition
    blocking: bool
    applicable_schema_versions: tuple[str, ...]
    evaluator: RuleEvaluator
    remediation_action: str

    def digest_metadata(self) -> dict[str, Any]:
        return {
            "applicable_schema_versions": list(self.applicable_schema_versions),
            "blocking": self.blocking,
            "category": self.category.value,
            "disposition": self.disposition.value,
            "evaluator": f"{self.evaluator.__module__}:{self.evaluator.__qualname__}",
            "evaluator_digest": _evaluator_digest(self.evaluator),
            "owner": self.owner.value,
            "remediation_action": self.remediation_action,
            "rule_id": self.rule_id,
            "severity": self.severity,
            "version": self.version,
        }


@dataclass(frozen=True)
class RuleOutcome:
    rule_id: str
    rule_version: str
    status: str
    diagnostic_count: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ValidationDiagnostic:
    rule_id: str
    rule_version: str
    category: str
    severity: str
    disposition: str
    field_path: str
    relationship: str | None
    owner: str
    explanation: str
    next_action: str
    remediation: dict[str, Any] | None
    input_digest: str
    lineage_id: str
    ingestion_attempt_id: str
    rule_set_digest: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ValidationResult:
    lineage_id: str
    ingestion_attempt_id: str
    correction_reference: CorrectionReference | None
    bundle_digest: str
    validator_version: str
    rule_set_version: str
    rule_set_digest: str
    evaluated_at: str
    lineage_received_at: str
    intake_evidence_digest: str
    authority_evidence_digest: str
    disposition: Disposition
    rule_outcomes: tuple[RuleOutcome, ...]
    diagnostics: tuple[ValidationDiagnostic, ...]
    advisory_suggestions: tuple[AdvisorySuggestion, ...]
    metric_eligibility: dict[str, dict[str, str | None]]

    @property
    def engineering_admissible(self) -> bool:
        return self.disposition in {Disposition.ADMITTED, Disposition.WARNING}

    def as_dict(self) -> dict[str, Any]:
        return {
            "advisory_suggestions": [item.as_dict() for item in self.advisory_suggestions],
            "bundle_digest": self.bundle_digest,
            "authority_evidence_digest": self.authority_evidence_digest,
            "correction_reference": (
                self.correction_reference.as_dict() if self.correction_reference else None
            ),
            "diagnostics": [item.as_dict() for item in self.diagnostics],
            "disposition": self.disposition.value,
            "evaluated_at": self.evaluated_at,
            "ingestion_attempt_id": self.ingestion_attempt_id,
            "intake_evidence_digest": self.intake_evidence_digest,
            "lineage_id": self.lineage_id,
            "lineage_received_at": self.lineage_received_at,
            "metric_eligibility": self.metric_eligibility,
            "rule_outcomes": [item.as_dict() for item in self.rule_outcomes],
            "rule_set_digest": self.rule_set_digest,
            "rule_set_version": self.rule_set_version,
            "validator_version": self.validator_version,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.as_dict())


class RuleRegistry:
    def __init__(self, rules: Sequence[ValidationRule], *, version: str) -> None:
        self.rules = tuple(sorted(rules, key=lambda rule: rule.rule_id))
        self.version = version

    @property
    def digest(self) -> str:
        return canonical_digest(
            {
                "rules": [rule.digest_metadata() for rule in self.rules],
                "version": self.version,
            }
        )

    def without(self, rule_id: str) -> RuleRegistry:
        return RuleRegistry(
            [rule for rule in self.rules if rule.rule_id != rule_id],
            version=self.version,
        )

    def with_rule_metadata(self, rule_id: str, **changes: Any) -> RuleRegistry:
        return RuleRegistry(
            [replace(rule, **changes) if rule.rule_id == rule_id else rule for rule in self.rules],
            version=self.version,
        )

    def with_evaluator(self, rule_id: str, evaluator: RuleEvaluator) -> RuleRegistry:
        return RuleRegistry(
            [
                replace(rule, evaluator=evaluator) if rule.rule_id == rule_id else rule
                for rule in self.rules
            ],
            version=self.version,
        )

    def integrity_errors(self) -> tuple[str, ...]:
        by_id = {rule.rule_id: rule for rule in self.rules}
        errors: list[str] = []
        if len(by_id) != len(self.rules):
            errors.append("duplicate rule ID")
        for rule_id, expected in _MANDATORY_RULE_METADATA.items():
            rule = by_id.get(rule_id)
            if rule is None:
                errors.append(f"missing mandatory rule {rule_id}")
                continue
            if rule.digest_metadata() != expected:
                errors.append(f"changed mandatory rule implementation or metadata {rule_id}")
            if rule.evaluator is not _MANDATORY_RULE_EVALUATORS[rule_id]:
                errors.append(f"unregistered mandatory rule evaluator {rule_id}")
        return tuple(errors)


def _evaluator_digest(evaluator: RuleEvaluator) -> str:
    try:
        source = inspect.getsource(evaluator)
    except (OSError, TypeError):
        return "sha256:" + "0" * 64
    return "sha256:" + hashlib.sha256(source.encode("utf-8")).hexdigest()


def _rule(
    rule_id: str,
    category: RuleCategory,
    owner: Owner,
    evaluator: RuleEvaluator,
    *,
    severity: str = "ERROR",
    disposition: Disposition = Disposition.PRODUCT_INPUT_REQUIRED,
    blocking: bool = True,
) -> ValidationRule:
    return ValidationRule(
        rule_id=rule_id,
        version="1.0.0",
        category=category,
        owner=owner,
        severity=severity,
        disposition=disposition,
        blocking=blocking,
        applicable_schema_versions=("1.0.0",),
        evaluator=evaluator,
        remediation_action=(
            "PMOS must publish corrected, explicitly approved product truth."
            if owner is Owner.PMOS
            else "The named owner must correct the governed evidence before retry."
        ),
    )


def default_rule_registry(*, rule_set_version: str = RULE_SET_VERSION) -> RuleRegistry:
    return RuleRegistry(
        [
            _rule("ALIGN.AUTONOMY", RuleCategory.ALIGNMENT, Owner.PMOS, _alignment_autonomy),
            _rule(
                "ALIGN.CROSS_CHANNEL", RuleCategory.ALIGNMENT, Owner.PMOS, _alignment_cross_channel
            ),
            _rule("ALIGN.DEPENDENCY", RuleCategory.ALIGNMENT, Owner.PMOS, _alignment_dependency),
            _rule("ALIGN.LEADING_DISTINCT", RuleCategory.ALIGNMENT, Owner.PMOS, _leading_distinct),
            _rule("ALIGN.METRIC_OUTCOME", RuleCategory.ALIGNMENT, Owner.PMOS, _metric_outcome),
            _rule(
                "ALIGN.POLICY_CONSISTENCY",
                RuleCategory.ALIGNMENT,
                Owner.PMOS,
                _policy_consistency,
            ),
            _rule(
                "ALIGN.OBSERVABILITY_REPORTING",
                RuleCategory.ALIGNMENT,
                Owner.PMOS,
                _observability_reporting,
            ),
            _rule(
                "ALIGN.OUTCOME_HYPOTHESIS",
                RuleCategory.ALIGNMENT,
                Owner.PMOS,
                _outcome_hypothesis,
            ),
            _rule(
                "ALIGN.RELEASE_APPROVAL",
                RuleCategory.ALIGNMENT,
                Owner.PMOS,
                _release_approval,
            ),
            _rule(
                "ALIGN.RELEASE_ROLLBACK",
                RuleCategory.ALIGNMENT,
                Owner.PMOS,
                _release_rollback,
            ),
            _rule(
                "ALIGN.REQUIREMENT_SCOPE",
                RuleCategory.ALIGNMENT,
                Owner.PMOS,
                _requirement_scope,
            ),
            _rule("ALIGN.SCOPE_NON_GOAL", RuleCategory.ALIGNMENT, Owner.PMOS, _scope_non_goal),
            _rule(
                "ALIGN.SECURITY_PRIVACY",
                RuleCategory.ALIGNMENT,
                Owner.SECURITY,
                _security_privacy,
            ),
            _rule(
                "ALIGN.SOLUTION_NON_GOAL",
                RuleCategory.ALIGNMENT,
                Owner.PMOS,
                _solution_non_goal,
            ),
            _rule(
                "ALIGN.TARGET_GUARDRAIL",
                RuleCategory.ALIGNMENT,
                Owner.PMOS,
                _target_guardrail,
            ),
            _rule("APPROVAL.ACTIVE", RuleCategory.APPROVAL, Owner.PMOS, _approval_active),
            _rule("APPROVAL.AUTHORITY", RuleCategory.APPROVAL, Owner.PMOS, _approval_authority),
            _rule("APPROVAL.FRESHNESS", RuleCategory.APPROVAL, Owner.PMOS, _approval_freshness),
            _rule("APPROVAL.REQUIRED", RuleCategory.APPROVAL, Owner.PMOS, _approval_required),
            _rule("APPROVAL.SUBJECT", RuleCategory.APPROVAL, Owner.PMOS, _approval_subject),
            _rule("COMP.COMPLETENESS", RuleCategory.COMPLETENESS, Owner.PMOS, _completeness),
            _rule(
                "COMP.TEMPORAL",
                RuleCategory.COMPLETENESS,
                Owner.PMOS,
                _temporal_validity,
            ),
            _rule(
                "COMP.UNRESOLVED_PRODUCT_TRUTH",
                RuleCategory.COMPLETENESS,
                Owner.PMOS,
                _unresolved_product_truth,
            ),
            _rule(
                "EXTENSION.CONSTRAINT",
                RuleCategory.EXTENSION,
                Owner.REPOSITORY_OWNER,
                _extension_constraint,
                disposition=Disposition.UNSUPPORTED_REPOSITORY_EXTENSION,
            ),
            _rule(
                "EXTENSION.SUPPORTED",
                RuleCategory.EXTENSION,
                Owner.REPOSITORY_OWNER,
                _extension_supported,
                disposition=Disposition.UNSUPPORTED_REPOSITORY_EXTENSION,
            ),
            _rule(
                "LINEAGE.CORRECTION_BINDING",
                RuleCategory.LINEAGE,
                Owner.PEOS,
                _correction_binding,
                disposition=Disposition.ERROR,
            ),
            _rule(
                "LINEAGE.POSSIBLE_DUPLICATE",
                RuleCategory.LINEAGE,
                Owner.PMOS,
                _possible_duplicate,
                severity="WARNING",
                disposition=Disposition.WARNING,
                blocking=False,
            ),
            _rule(
                "METRIC.MATURITY_POLICY",
                RuleCategory.METRIC_POLICY,
                Owner.PMOS,
                _metric_maturity_policy,
            ),
            _rule(
                "OWNERSHIP.PRODUCT_TRUTH",
                RuleCategory.OWNERSHIP,
                Owner.PMOS,
                _ownership_product_truth,
            ),
            _rule("QUESTION.UNRESOLVED", RuleCategory.QUESTION, Owner.PMOS, _open_questions),
            _rule("REF.ACCEPTANCE", RuleCategory.REFERENCE, Owner.PMOS, _ref_acceptance),
            _rule("REF.APPROVAL", RuleCategory.REFERENCE, Owner.PMOS, _ref_approval),
            _rule("REF.ENTITY", RuleCategory.REFERENCE, Owner.PMOS, _ref_entity),
            _rule("REF.GUARDRAIL", RuleCategory.REFERENCE, Owner.PMOS, _ref_guardrail),
            _rule("REF.METRIC", RuleCategory.REFERENCE, Owner.PMOS, _ref_metric),
            _rule("REF.METRIC_POLICY", RuleCategory.REFERENCE, Owner.PMOS, _ref_metric_policy),
            _rule(
                "REF.REPORTING_POLICY",
                RuleCategory.REFERENCE,
                Owner.PMOS,
                _ref_reporting_policy,
            ),
            _rule("REF.REQUIREMENT", RuleCategory.REFERENCE, Owner.PMOS, _ref_requirement),
            _rule(
                "REF.SOURCE_IDENTITY",
                RuleCategory.REFERENCE,
                Owner.PMOS,
                _ref_source_identity,
            ),
            _rule("REF.UX", RuleCategory.REFERENCE, Owner.PMOS, _ref_ux),
        ],
        version=rule_set_version,
    )


_MANDATORY_RULE_METADATA: dict[str, dict[str, Any]] = {}
_MANDATORY_RULE_EVALUATORS: dict[str, RuleEvaluator] = {}


class ContractSemanticValidator:
    def __init__(
        self,
        registry: RuleRegistry | None = None,
        *,
        fingerprint_provider: KeyedFingerprintProvider | None = None,
        evidence_lookup: ValidationEvidenceLookup | None = None,
    ) -> None:
        self.registry = registry or default_rule_registry()
        self.fingerprint_provider = fingerprint_provider
        self.evidence_lookup = evidence_lookup
        schema = json.loads(
            (packaged_schema_dir() / "pmos_contract_bundle.schema.json").read_text()
        )
        self._schema_validator = Draft202012Validator(schema)

    def validate(
        self,
        bundle: Mapping[str, Any],
        context: ValidationContext,
        *,
        advisory_suggestions: Sequence[AdvisorySuggestion] = (),
    ) -> ValidationResult:
        rule_set_digest = self.registry.digest
        try:
            actual_bundle_digest: str | None = canonical_digest(bundle)
        except Exception:
            actual_bundle_digest = None
        core_findings = self._preflight(bundle, context, actual_bundle_digest)
        outcomes: list[RuleOutcome] = []
        diagnostics: list[ValidationDiagnostic] = [
            self._core_diagnostic(finding, context, rule_set_digest) for finding in core_findings
        ]
        integrity_errors = self.registry.integrity_errors()
        if integrity_errors:
            finding = Finding(
                field_path="/rule-set",
                explanation="The registered rule set is incomplete or weakens a mandatory rule.",
                next_action="Restore the complete versioned rule set and rerun validation.",
                owner=Owner.PEOS,
                disposition=Disposition.ERROR,
            )
            diagnostics.append(
                self._core_diagnostic(
                    finding,
                    context,
                    rule_set_digest,
                    rule_id="CORE.RULE_SET_INTEGRITY",
                )
            )
        if not core_findings and not integrity_errors:
            schema_version = str(bundle.get("schema_version", ""))
            for rule in self.registry.rules:
                if schema_version not in rule.applicable_schema_versions:
                    continue
                try:
                    findings = rule.evaluator(bundle, context)
                except Exception:
                    finding = Finding(
                        field_path="/",
                        explanation="A mandatory deterministic rule could not complete.",
                        next_action="Repair the evaluator and rerun the entire rule set.",
                        owner=Owner.PEOS,
                        disposition=Disposition.ERROR,
                    )
                    diagnostics.append(
                        self._core_diagnostic(
                            finding,
                            context,
                            rule_set_digest,
                            rule_id="CORE.RULE_EVALUATION",
                            relationship=rule.rule_id,
                        )
                    )
                    outcomes.append(
                        RuleOutcome(rule.rule_id, rule.version, "ERROR", diagnostic_count=1)
                    )
                    continue
                outcomes.append(
                    RuleOutcome(
                        rule.rule_id,
                        rule.version,
                        "FAIL" if findings else "PASS",
                        len(findings),
                    )
                )
                diagnostics.extend(
                    self._diagnostic(rule, finding, context, rule_set_digest)
                    for finding in findings
                )
        diagnostics.sort(key=lambda item: (item.rule_id, item.field_path, item.relationship or ""))
        try:
            metric_eligibility = (
                _metric_eligibility(bundle, context) if actual_bundle_digest is not None else {}
            )
        except Exception:
            metric_eligibility = {}
        disposition = _overall_disposition(diagnostics)
        sanitized_suggestions = tuple(item.sanitized() for item in advisory_suggestions)
        return ValidationResult(
            lineage_id=context.lineage_id,
            ingestion_attempt_id=context.ingestion_attempt_id,
            correction_reference=context.correction_reference,
            bundle_digest=actual_bundle_digest or context.bundle_digest,
            validator_version=VALIDATOR_VERSION,
            rule_set_version=self.registry.version,
            rule_set_digest=rule_set_digest,
            evaluated_at=context.evaluated_at,
            lineage_received_at=context.lineage_received_at,
            intake_evidence_digest=(
                context.intake_identity.receipt_digest
                if context.intake_identity is not None
                else canonical_digest({"status": "MISSING"})
            ),
            authority_evidence_digest=canonical_digest(
                [grant.as_dict() for grant in context.authority_grants]
            ),
            disposition=disposition,
            rule_outcomes=tuple(outcomes),
            diagnostics=tuple(diagnostics),
            advisory_suggestions=sanitized_suggestions,
            metric_eligibility=metric_eligibility,
        )

    def _preflight(
        self,
        bundle: Mapping[str, Any],
        context: ValidationContext,
        actual_bundle_digest: str | None,
    ) -> tuple[Finding, ...]:
        findings: list[Finding] = []
        if (
            not _valid_context(context, self.fingerprint_provider)
            or actual_bundle_digest is None
            or actual_bundle_digest != context.bundle_digest
        ):
            findings.append(
                Finding(
                    field_path="/evidence-binding",
                    explanation=(
                        "Validation evidence is not bound to the exact intake identity and bundle."
                    ),
                    next_action="Rebind the immutable intake receipt and exact canonical digest.",
                    owner=Owner.PEOS,
                    disposition=Disposition.ERROR,
                )
            )
        correction = context.correction_reference
        if (
            correction is not None
            and correction.lineage_id == context.lineage_id
            and not self._valid_correction_predecessor(context)
        ):
            findings.append(
                Finding(
                    field_path="/correction_reference",
                    explanation=(
                        "Correction evidence is not bound to an immutable stored predecessor."
                    ),
                    next_action=(
                        "Restore and verify the referenced validation artifact before retry."
                    ),
                    owner=Owner.PEOS,
                    disposition=Disposition.ERROR,
                )
            )
        if str(bundle.get("schema_version", "")) not in SUPPORTED_SCHEMA_VERSIONS:
            findings.append(
                Finding(
                    field_path="/schema_version",
                    explanation="The canonical schema version has no supported semantic rule set.",
                    next_action=(
                        "Use a registered schema/rule-set pair or add a reviewed migration."
                    ),
                    owner=Owner.PEOS,
                    disposition=Disposition.ERROR,
                )
            )
        if self.registry.version != RULE_SET_VERSION:
            findings.append(
                Finding(
                    field_path="/rule-set/version",
                    explanation="The requested semantic rule-set version is not supported.",
                    next_action="Use the registered rule-set version or add a reviewed migration.",
                    owner=Owner.PEOS,
                    disposition=Disposition.ERROR,
                )
            )
        try:
            structural_errors = sorted(
                self._schema_validator.iter_errors(bundle),
                key=lambda error: tuple(str(part) for part in error.absolute_path),
            )
        except Exception:
            structural_errors = [None]
        product_truth_errors = [
            error
            for error in structural_errors
            if error is not None and _missing_product_truth_schema_error(error)
        ]
        runtime_errors = [error for error in structural_errors if error not in product_truth_errors]
        if product_truth_errors:
            first_product_error = product_truth_errors[0]
            findings.append(
                Finding(
                    field_path=_semantic_error_path(first_product_error, bundle),
                    explanation="Required product truth is absent or empty.",
                    next_action="PMOS must supply and approve the missing canonical field.",
                    owner=Owner.PMOS,
                    disposition=Disposition.PRODUCT_INPUT_REQUIRED,
                )
            )
        if runtime_errors:
            first_error = runtime_errors[0]
            path = (
                _json_pointer(list(first_error.absolute_path)) if first_error is not None else "/"
            )
            findings.append(
                Finding(
                    field_path=path or "/",
                    explanation="The canonical bundle violates its registered structural schema.",
                    next_action=(
                        "Return the artifact to canonical compilation before semantic validation."
                    ),
                    owner=Owner.PEOS,
                    disposition=Disposition.ERROR,
                )
            )
        return tuple(findings)

    def _valid_correction_predecessor(self, context: ValidationContext) -> bool:
        correction = context.correction_reference
        if correction is None or self.evidence_lookup is None:
            return False
        try:
            predecessor = self.evidence_lookup.load_attempt(correction.attempt_id)
            lineage = self.evidence_lookup.lineage_summary(context.lineage_id)
        except (OSError, ValueError, KeyError, ValidationEvidenceError):
            return False
        attempt_ids = lineage.get("attempt_ids")
        return (
            predecessor.get("lineage_id") == context.lineage_id
            and predecessor.get("ingestion_attempt_id") == correction.attempt_id
            and predecessor.get("lineage_received_at") == context.lineage_received_at
            and bool(predecessor.get("intake_evidence_digest"))
            and isinstance(attempt_ids, list)
            and bool(attempt_ids)
            and attempt_ids[-1] == correction.attempt_id
        )

    @staticmethod
    def _core_diagnostic(
        finding: Finding,
        context: ValidationContext,
        rule_set_digest: str,
        *,
        rule_id: str | None = None,
        relationship: str | None = None,
    ) -> ValidationDiagnostic:
        selected = rule_id or (
            "COMP.COMPLETENESS"
            if finding.disposition is Disposition.PRODUCT_INPUT_REQUIRED
            else (
                "CORE.EVIDENCE_BINDING"
                if finding.field_path in {"/correction_reference", "/evidence-binding"}
                else (
                    "CORE.UNSUPPORTED_VERSION"
                    if finding.field_path in {"/schema_version", "/rule-set/version"}
                    else "CORE.STRUCTURE"
                )
            )
        )
        product_input = finding.disposition is Disposition.PRODUCT_INPUT_REQUIRED
        completeness_rule = next(
            rule for rule in default_rule_registry().rules if rule.rule_id == "COMP.COMPLETENESS"
        )
        return ValidationDiagnostic(
            rule_id=selected,
            rule_version="1.0.0",
            category=(
                RuleCategory.COMPLETENESS.value if product_input else RuleCategory.CORE.value
            ),
            severity="ERROR",
            disposition=(
                Disposition.PRODUCT_INPUT_REQUIRED.value
                if product_input
                else Disposition.ERROR.value
            ),
            field_path=_sanitize_path(finding.field_path),
            relationship=relationship,
            owner=(finding.owner or Owner.PEOS).value,
            explanation=_sanitize(finding.explanation),
            next_action=_sanitize(finding.next_action),
            remediation=(
                _remediation(completeness_rule, finding, context) if product_input else None
            ),
            input_digest=context.bundle_digest,
            lineage_id=context.lineage_id,
            ingestion_attempt_id=context.ingestion_attempt_id,
            rule_set_digest=rule_set_digest,
        )

    @staticmethod
    def _diagnostic(
        rule: ValidationRule,
        finding: Finding,
        context: ValidationContext,
        rule_set_digest: str,
    ) -> ValidationDiagnostic:
        owner = finding.owner or rule.owner
        disposition = finding.disposition or rule.disposition
        remediation = (
            _remediation(rule, finding, context, owner)
            if owner is Owner.PMOS and disposition is Disposition.PRODUCT_INPUT_REQUIRED
            else None
        )
        return ValidationDiagnostic(
            rule_id=rule.rule_id,
            rule_version=rule.version,
            category=rule.category.value,
            severity=(
                finding.severity
                or ("WARNING" if disposition is Disposition.WARNING else rule.severity)
            ),
            disposition=disposition.value,
            field_path=_sanitize_path(finding.field_path),
            relationship=_sanitize(finding.relationship) if finding.relationship else None,
            owner=owner.value,
            explanation=_sanitize(finding.explanation),
            next_action=_sanitize(finding.next_action),
            remediation=remediation,
            input_digest=context.bundle_digest,
            lineage_id=context.lineage_id,
            ingestion_attempt_id=context.ingestion_attempt_id,
            rule_set_digest=rule_set_digest,
        )


def _remediation(
    rule: ValidationRule,
    finding: Finding,
    context: ValidationContext,
    owner: Owner | None = None,
) -> dict[str, Any]:
    token = (
        hashlib.sha256(
            f"{context.lineage_id}:{context.ingestion_attempt_id}:{rule.rule_id}:{finding.field_path}".encode()
        )
        .hexdigest()[:16]
        .upper()
    )
    return {
        "affected_requirement_ids": _requirement_ids(finding.relationship),
        "created_at": context.evaluated_at,
        "decision_owner": (owner or rule.owner).value,
        "engineering_consequences": (
            "Engineering admission remains blocked until corrected evidence passes."
        ),
        "engineering_finding": _sanitize(finding.explanation),
        "options": ["PMOS publishes explicit corrected truth with exact approval evidence."],
        "reason": _sanitize(finding.next_action),
        "recommended_technical_default": "NO_DEFAULT_ENGINEERING_MUST_NOT_INVENT_PRODUCT_TRUTH",
        "request_id": f"PCR-VALIDATION-{token}",
        "source_contract_id": context.lineage_id,
        "source_contract_version": 1,
        "status": "OPEN",
    }


def _requirement_ids(value: str | None) -> list[str]:
    if not value:
        return []
    return sorted(set(re.findall(r"\bFR-[A-Z0-9-]+\b", value)))


def _sanitize(value: str) -> str:
    sanitized = value
    for pattern in (*_SECRET_PATTERNS, *_PERSONAL_PATTERNS):
        sanitized = pattern.sub("[REDACTED]", sanitized)
    return sanitized[:1000]


def _sanitize_path(value: str) -> str:
    if not value.startswith("/") or len(value) > 512:
        return "/"
    return _sanitize(value)


def _valid_context(
    context: ValidationContext,
    fingerprint_provider: KeyedFingerprintProvider | None,
) -> bool:
    try:
        evaluated_at = _parse_time(context.evaluated_at)
        lineage_received_at = _parse_time(context.lineage_received_at)
        evidence = context.intake_identity
        if (
            evidence is None
            or fingerprint_provider is None
            or not evidence.verify(fingerprint_provider)
        ):
            return False
        receipt = evidence.receipt
        receipt_received_at = _parse_time(str(receipt.get("received_at", "")))
        expected_correction = (
            context.correction_reference.as_dict() if context.correction_reference else None
        )
    except (TypeError, ValueError):
        return False
    return (
        bool(_SAFE_ID.fullmatch(context.lineage_id))
        and bool(_SAFE_ID.fullmatch(context.ingestion_attempt_id))
        and bool(re.fullmatch(r"sha256:[0-9a-f]{64}", context.bundle_digest))
        and receipt.get("lineage_id") == context.lineage_id
        and receipt.get("attempt_id") == context.ingestion_attempt_id
        and receipt.get("correction_reference") == expected_correction
        and lineage_received_at <= receipt_received_at <= evaluated_at
        and (context.correction_reference is not None or lineage_received_at == receipt_received_at)
    )


def _missing_product_truth_schema_error(error: Any) -> bool:
    """Separate missing PM truth from malformed canonical runtime structure.

    The schema's APPROVED branch uses a root ``oneOf`` requiring every product
    section.  Missing one of those sections is the product-input disposition,
    while missing identity/provenance fields or invalid types remains ERROR.
    """

    instance = error.instance
    path = list(error.absolute_path)
    if error.validator == "oneOf" and not path and isinstance(instance, Mapping):
        return bool(_SEMANTIC_TOP_LEVEL_SECTIONS - set(instance))
    return (
        error.validator in {"required", "minItems", "minProperties", "minLength"}
        and bool(path)
        and str(path[0]) in _SEMANTIC_TOP_LEVEL_SECTIONS
    )


def _semantic_error_path(error: Any, bundle: Mapping[str, Any]) -> str:
    path = list(error.absolute_path)
    if path:
        return _json_pointer(path)
    missing = sorted(_SEMANTIC_TOP_LEVEL_SECTIONS - set(bundle))
    return f"/{missing[0]}" if missing else "/"


def _overall_disposition(diagnostics: Sequence[ValidationDiagnostic]) -> Disposition:
    order = (
        Disposition.ERROR,
        Disposition.UNSUPPORTED_REPOSITORY_EXTENSION,
        Disposition.PRODUCT_INPUT_REQUIRED,
        Disposition.WARNING,
    )
    present = {item.disposition for item in diagnostics}
    return next((item for item in order if item.value in present), Disposition.ADMITTED)


def _finding(path: str, explanation: str, action: str, relationship: str | None = None) -> Finding:
    return Finding(path, explanation, action, relationship)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else ()


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (Mapping, Sequence)):
        return bool(value)
    return True


def _get(bundle: Mapping[str, Any], path: str) -> Any:
    current: Any = bundle
    for part in path.strip("/").split("/") if path.strip("/") else ():
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _completeness(bundle: Mapping[str, Any], _context: ValidationContext) -> tuple[Finding, ...]:
    required_paths = {
        "/product": "product identity, problem, outcome, hypothesis, users, and platform",
        "/product/product_name": "product identity",
        "/product/problem/statement": "problem statement",
        "/product/outcome/customer_outcome": "customer outcome",
        "/product/outcome/business_outcome": "business outcome",
        "/product/outcome/measurable_change": "measurable outcome change",
        "/product/hypothesis/statement": "product hypothesis",
        "/product/hypothesis/falsification_condition": "hypothesis falsification condition",
        "/product/target_customers": "target users",
        "/metrics": "success, leading, North Star, maturity, and reporting metrics",
        "/metrics/success": "success metrics",
        "/metrics/leading": "leading indicators",
        "/metrics/north_stars/mvp": "MVP North Star",
        "/metrics/north_stars/end_state": "outcome North Star",
        "/metrics/maturity_policies": "metric maturity policies",
        "/metrics/reporting_policies": "metric reporting policies",
        "/guardrails": "quality and safety guardrails",
        "/scope": "scope and non-goals",
        "/scope/in_scope": "declared scope",
        "/scope/non_goals": "declared non-goals",
        "/functional_requirements": "functional requirements",
        "/acceptance_criteria": "acceptance criteria",
        "/ux": "UX journeys, stories, accessibility, and edge cases",
        "/ux/primary_journey": "primary journey",
        "/ux/user_stories": "user stories",
        "/ux/flows": "UX flows",
        "/ux/edge_cases": "UX edge cases",
        "/ux/accessibility": "accessibility intent",
        "/release": "rollout and release intent",
        "/release/launch_intent": "launch intent",
        "/rollback": "rollback expectations",
        "/rollback/requirements": "rollback requirements",
        "/rollback/rto": "rollback recovery-time objective",
        "/observability": "observability and reporting intent",
        "/observability/requirements": "observability requirements",
        "/quality_assurance": "quality-assurance expectations and release gates",
        "/quality_assurance/expectations": "quality-assurance expectations",
        "/quality_assurance/release_gates": "quality-assurance release gates",
        "/non_functional_requirements": "non-functional requirements",
        "/approvals": "approval evidence",
        "/required_approvals": "required approval policy",
        "/product_decisions": "product decisions and trade-offs",
    }
    findings = [
        _finding(
            path,
            f"Required {label} is absent from the canonical product truth.",
            f"PMOS must supply and approve {label}.",
        )
        for path, label in required_paths.items()
        if not _present(_get(bundle, path))
    ]
    risk_requires_controls = any(
        _mapping(risk).get("severity") in {"HIGH", "CRITICAL"}
        for risk in _mapping(bundle.get("risks")).values()
    )
    data_is_applicable = risk_requires_controls or any(
        _present(_mapping(requirement).get("entity_ref"))
        for requirement in _mapping(bundle.get("functional_requirements")).values()
    )
    integration_is_applicable = bool(_mapping(bundle.get("integrations"))) or any(
        str(_mapping(requirement).get("capability", "")).startswith("integration.")
        for requirement in _mapping(bundle.get("functional_requirements")).values()
    )
    platform = str(_get(bundle, "/product/target_platform/kind") or "")
    applicable_paths: dict[str, str] = {}
    if data_is_applicable:
        applicable_paths.update(
            {
                "/data": "data truth",
                "/data/requirements": "data requirements",
                "/security": "security intent for the declared risk/data class",
                "/security/requirements": "security requirements",
                "/privacy": "privacy and telemetry intent for the declared risk/data class",
                "/privacy/requirements": "privacy requirements",
                "/privacy/telemetry": "telemetry intent",
            }
        )
    if integration_is_applicable:
        applicable_paths.update(
            {
                "/dependencies": "declared dependencies for integrations",
                "/integrations": "integration product truth",
            }
        )
    if platform in {"API", "WEB", "MOBILE"}:
        applicable_paths["/api_contracts"] = "API contract truth for the selected platform"
    stage = str(_get(bundle, "/release/requested_autonomy_stage") or "")
    if stage in {"STAGING", "CANARY", "PRODUCTION"}:
        applicable_paths["/technical_constraints"] = (
            "technical constraints for deployment-capable autonomy"
        )
    findings.extend(
        _finding(
            path,
            f"Applicable {label} is absent from the canonical product truth.",
            f"PMOS must supply and approve {label}.",
        )
        for path, label in applicable_paths.items()
        if not _present(_get(bundle, path))
    )
    for policy_id, policy in sorted(_mapping(_get(bundle, "/metrics/maturity_policies")).items()):
        record = _mapping(policy)
        for field in (
            "delivery_window",
            "evaluation_window",
            "observation_window",
            "owner_ref",
            "policy_version",
            "reporting_policy_ref",
            "reporting_window",
            "target",
        ):
            if not _present(record.get(field)):
                findings.append(
                    _finding(
                        f"/metrics/maturity_policies/{policy_id}/{field}",
                        "A metric maturity policy omits required target, owner, or window truth.",
                        (
                            "The named PMOS metric owner must supply and approve the missing "
                            "policy field."
                        ),
                        policy_id,
                    )
                )
    for policy_id, policy in sorted(_mapping(_get(bundle, "/metrics/reporting_policies")).items()):
        record = _mapping(policy)
        for field in (
            "calculation",
            "denominator",
            "inclusion_criteria",
            "owner_ref",
            "policy_version",
        ):
            if not _present(record.get(field)):
                findings.append(
                    _finding(
                        f"/metrics/reporting_policies/{policy_id}/{field}",
                        "A reporting policy omits required calculation or denominator truth.",
                        "The named PMOS metric owner must supply and approve the reporting field.",
                        policy_id,
                    )
                )
    for requirement_id, requirement in sorted(
        _mapping(bundle.get("non_functional_requirements")).items()
    ):
        record = _mapping(requirement)
        if record.get("category") == "OTHER" and not _present(record.get("source_category")):
            findings.append(
                _finding(
                    f"/non_functional_requirements/{requirement_id}/source_category",
                    "An OTHER non-functional category omits its exact source classification.",
                    "PMOS must preserve the source category without reinterpretation.",
                    requirement_id,
                )
            )
    if platform in {"WEB", "MOBILE", "DESKTOP"}:
        for path, label in (
            ("/ux/screens", "screen truth"),
            ("/ux/ui_states", "UI state truth"),
            ("/ux/responsive_requirements", "responsive behavior"),
        ):
            if not _present(_get(bundle, path)):
                findings.append(
                    _finding(
                        path,
                        f"The selected product platform requires {label}.",
                        f"PMOS must provide and approve {label}.",
                    )
                )
    return tuple(findings)


def _temporal_validity(
    bundle: Mapping[str, Any], _context: ValidationContext
) -> tuple[Finding, ...]:
    timestamps: list[tuple[str, Any]] = [
        ("/provenance/published_at", _get(bundle, "/provenance/published_at")),
    ]
    for approval_id, approval in sorted(_mapping(bundle.get("approvals")).items()):
        record = _mapping(approval)
        for field in ("approved_at", "expires_at", "revoked_at", "valid_from"):
            if record.get(field) is not None:
                timestamps.append((f"/approvals/{approval_id}/{field}", record.get(field)))
    findings: list[Finding] = []
    for path, value in timestamps:
        try:
            _parse_time(str(value))
        except ValueError:
            findings.append(
                _finding(
                    path,
                    "A canonical timestamp is not a real UTC instant.",
                    "PMOS must publish a valid UTC timestamp with an explicit Z offset.",
                )
            )

    durations: list[tuple[str, Any]] = []
    for policy_id, policy in sorted(_mapping(_get(bundle, "/metrics/maturity_policies")).items()):
        record = _mapping(policy)
        for field in (
            "delivery_window",
            "evaluation_window",
            "observation_window",
            "reporting_window",
        ):
            durations.append(
                (
                    f"/metrics/maturity_policies/{policy_id}/{field}/duration",
                    _mapping(record.get(field)).get("duration"),
                )
            )
    for path, value in durations:
        try:
            _duration(str(value))
        except ValueError:
            findings.append(
                _finding(
                    path,
                    "A duration cannot be evaluated deterministically by this rule set.",
                    (
                        "PMOS must use a fixed week/day/time duration without calendar "
                        "months or years."
                    ),
                )
            )
    return tuple(findings)


def _unresolved_product_truth(
    bundle: Mapping[str, Any], _context: ValidationContext
) -> tuple[Finding, ...]:
    unresolved = _mapping(bundle.get("unresolved_product_truth"))
    return tuple(
        _finding(
            f"/unresolved_product_truth/{item_id}",
            "Loss-aware compilation identified unresolved required product truth.",
            "PMOS must correct the source contract and publish a new approved attempt.",
            item_id,
        )
        for item_id in sorted(unresolved)
    )


def _open_questions(bundle: Mapping[str, Any], _context: ValidationContext) -> tuple[Finding, ...]:
    questions = _mapping(bundle.get("open_questions"))
    return tuple(
        Finding(
            f"/open_questions/{question_id}",
            (
                "A product-critical question remains unresolved."
                if bool(question.get("blocking"))
                else "A non-blocking product question remains unresolved."
            ),
            (
                "The named PMOS owner must resolve and approve the question."
                if bool(question.get("blocking"))
                else "The named PMOS owner should resolve the advisory question."
            ),
            question_id,
            Owner.PMOS,
            (
                Disposition.PRODUCT_INPUT_REQUIRED
                if bool(question.get("blocking"))
                else Disposition.WARNING
            ),
        )
        for question_id, question in sorted(questions.items())
        if isinstance(question, Mapping) and not _present(question.get("resolution"))
    )


def _ref_requirement(bundle: Mapping[str, Any], _context: ValidationContext) -> tuple[Finding, ...]:
    functional_requirements = set(_mapping(bundle.get("functional_requirements")))
    non_functional_requirements = set(_mapping(bundle.get("non_functional_requirements")))
    findings: list[Finding] = []
    reference_registries = (
        (
            "/acceptance_criteria",
            _mapping(bundle.get("acceptance_criteria")),
            functional_requirements,
            "FR",
        ),
        (
            "/ux/edge_cases",
            _mapping(_get(bundle, "/ux/edge_cases")),
            functional_requirements,
            "FR",
        ),
        (
            "/quality_assurance/expectations",
            _mapping(_get(bundle, "/quality_assurance/expectations")),
            functional_requirements | non_functional_requirements,
            "FR or NFR",
        ),
    )
    for base_path, registry, allowed_requirements, expected_namespace in reference_registries:
        for record_id, record in sorted(registry.items()):
            for reference in _sequence(_mapping(record).get("requirement_refs")):
                if reference in allowed_requirements:
                    continue
                findings.append(
                    _finding(
                        f"{base_path}/{record_id}/requirement_refs",
                        "A record references a missing or wrong-type requirement.",
                        f"PMOS must reference an existing {expected_namespace} identifier.",
                        f"{record_id}->{reference}",
                    )
                )
    return tuple(findings)


def _ref_acceptance(bundle: Mapping[str, Any], _context: ValidationContext) -> tuple[Finding, ...]:
    criteria = set(_mapping(bundle.get("acceptance_criteria")))
    findings: list[Finding] = []
    for requirement_id, requirement in sorted(
        _mapping(bundle.get("functional_requirements")).items()
    ):
        for reference in _sequence(_mapping(requirement).get("acceptance_criterion_refs")):
            if reference not in criteria:
                findings.append(
                    _finding(
                        f"/functional_requirements/{requirement_id}/acceptance_criterion_refs",
                        "A requirement references a missing or wrong-type acceptance criterion.",
                        "PMOS must reference an existing AC identifier.",
                        f"{requirement_id}->{reference}",
                    )
                )
    return tuple(findings)


def _ref_entity(bundle: Mapping[str, Any], _context: ValidationContext) -> tuple[Finding, ...]:
    entities = set(_mapping(_get(bundle, "/data/entities")))
    return tuple(
        _finding(
            f"/functional_requirements/{requirement_id}/entity_ref",
            "A functional requirement references a missing or wrong-type data entity.",
            "PMOS must reference an existing ENTITY identifier.",
            f"{requirement_id}->{reference}",
        )
        for requirement_id, requirement in sorted(
            _mapping(bundle.get("functional_requirements")).items()
        )
        if (reference := _mapping(requirement).get("entity_ref")) is not None
        and reference not in entities
    )


def _ref_guardrail(bundle: Mapping[str, Any], _context: ValidationContext) -> tuple[Finding, ...]:
    guardrails = set(_mapping(bundle.get("guardrails")))
    return tuple(
        _finding(
            f"/release/guardrail_refs/{index}",
            "Release intent references a missing or wrong-type guardrail.",
            "PMOS must reference an existing GUARD identifier.",
            str(reference),
        )
        for index, reference in enumerate(_sequence(_get(bundle, "/release/guardrail_refs")))
        if reference not in guardrails
    )


def _ref_metric(bundle: Mapping[str, Any], _context: ValidationContext) -> tuple[Finding, ...]:
    metrics = _mapping(bundle.get("metrics"))
    metric_ids = set(_mapping(metrics.get("leading")))
    metric_ids.update(
        str(_mapping(item).get("metric_id"))
        for item in _mapping(metrics.get("north_stars")).values()
    )
    metric_ids.update(_mapping(metrics.get("success")))
    return tuple(
        _finding(
            f"/metrics/maturity_policies/{policy_id}/metric_ref",
            "A maturity policy references a missing or wrong-type metric.",
            "PMOS must reference an existing named metric identifier.",
            f"{policy_id}->{reference}",
        )
        for policy_id, policy in sorted(_mapping(metrics.get("maturity_policies")).items())
        if (reference := _mapping(policy).get("metric_ref")) not in metric_ids
    )


def _ref_metric_policy(
    bundle: Mapping[str, Any], _context: ValidationContext
) -> tuple[Finding, ...]:
    metrics = _mapping(bundle.get("metrics"))
    policies = set(_mapping(metrics.get("maturity_policies")))
    references: list[tuple[str, Any]] = []
    for name, north_star in _mapping(metrics.get("north_stars")).items():
        references.append(
            (
                f"/metrics/north_stars/{name}/maturity_policy_ref",
                _mapping(north_star).get("maturity_policy_ref"),
            )
        )
    for metric_id, metric in _mapping(metrics.get("leading")).items():
        references.append(
            (
                f"/metrics/leading/{metric_id}/maturity_policy_ref",
                _mapping(metric).get("maturity_policy_ref"),
            )
        )
    return tuple(
        _finding(
            path,
            "A metric references a missing or wrong-type maturity policy.",
            "PMOS must reference an existing named metric maturity policy.",
            str(reference),
        )
        for path, reference in references
        if reference not in policies
    )


def _ref_reporting_policy(
    bundle: Mapping[str, Any], _context: ValidationContext
) -> tuple[Finding, ...]:
    metrics = _mapping(bundle.get("metrics"))
    reporting = set(_mapping(metrics.get("reporting_policies")))
    return tuple(
        _finding(
            f"/metrics/maturity_policies/{policy_id}/reporting_policy_ref",
            "A maturity policy references a missing or wrong-type reporting policy.",
            "PMOS must reference an existing named reporting policy.",
            f"{policy_id}->{reference}",
        )
        for policy_id, policy in sorted(_mapping(metrics.get("maturity_policies")).items())
        if (reference := _mapping(policy).get("reporting_policy_ref")) not in reporting
    )


def _ref_approval(bundle: Mapping[str, Any], _context: ValidationContext) -> tuple[Finding, ...]:
    approvals = set(_mapping(bundle.get("approvals")))
    references: list[tuple[str, Any]] = []
    for index, reference in enumerate(_sequence(_get(bundle, "/release/approval_refs"))):
        references.append((f"/release/approval_refs/{index}", reference))
    for policy_id, policy in _mapping(_get(bundle, "/metrics/maturity_policies")).items():
        references.append(
            (
                f"/metrics/maturity_policies/{policy_id}/approval_ref",
                _mapping(policy).get("approval_ref"),
            )
        )
    for policy_id, policy in _mapping(_get(bundle, "/metrics/reporting_policies")).items():
        references.append(
            (
                f"/metrics/reporting_policies/{policy_id}/approval_ref",
                _mapping(policy).get("approval_ref"),
            )
        )
    for decision_id, decision in _mapping(bundle.get("product_decisions")).items():
        references.append(
            (
                f"/product_decisions/{decision_id}/approval_ref",
                _mapping(decision).get("approval_ref"),
            )
        )
    for approval_id, approval in _mapping(bundle.get("approvals")).items():
        record = _mapping(approval)
        for index, reference in enumerate(_sequence(record.get("supersedes_approval_refs"))):
            references.append(
                (f"/approvals/{approval_id}/supersedes_approval_refs/{index}", reference)
            )
        if record.get("superseded_by_approval_ref") is not None:
            references.append(
                (
                    f"/approvals/{approval_id}/superseded_by_approval_ref",
                    record.get("superseded_by_approval_ref"),
                )
            )
    return tuple(
        _finding(
            path,
            "A governed record references missing approval evidence.",
            "PMOS must attach the exact active approval record.",
            str(reference),
        )
        for path, reference in references
        if reference not in approvals
    )


def _ref_ux(bundle: Mapping[str, Any], _context: ValidationContext) -> tuple[Finding, ...]:
    screens = set(_mapping(_get(bundle, "/ux/screens")))
    states = set(_mapping(_get(bundle, "/ux/ui_states")))
    findings: list[Finding] = []
    for step_id, step in _mapping(_get(bundle, "/ux/primary_journey")).items():
        reference = _mapping(step).get("screen_ref")
        if reference is not None and reference not in screens:
            findings.append(
                _finding(
                    f"/ux/primary_journey/{step_id}/screen_ref",
                    "A journey step references a missing or wrong-type screen.",
                    "PMOS must reference an existing SCREEN identifier.",
                    f"{step_id}->{reference}",
                )
            )
    for screen_id, screen in _mapping(_get(bundle, "/ux/screens")).items():
        for reference in _sequence(_mapping(screen).get("state_refs")):
            if reference not in states:
                findings.append(
                    _finding(
                        f"/ux/screens/{screen_id}/state_refs",
                        "A screen references a missing or wrong-type UI state.",
                        "PMOS must reference an existing UI-STATE identifier.",
                        f"{screen_id}->{reference}",
                    )
                )
    return tuple(findings)


def _ref_source_identity(
    bundle: Mapping[str, Any], _context: ValidationContext
) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    mappings = _mapping(bundle.get("source_identity_mappings"))
    compiler_provenance = _mapping(_get(bundle, "/provenance/compiler_provenance"))
    if compiler_provenance and bundle.get("contract_status") == "APPROVED":
        provenance = _mapping(bundle.get("provenance"))
        bundle_mapping_present = any(
            _mapping(item).get("canonical_pointer") == "/bundle_id"
            and _mapping(item).get("source_id") == provenance.get("source_id")
            for item in mappings.values()
        )
        if not bundle_mapping_present:
            findings.append(
                Finding(
                    "/source_identity_mappings",
                    "Compiler-produced approved truth lacks its root source identity mapping.",
                    "PEOS must reconcile compiler provenance before semantic admission.",
                    str(provenance.get("source_id", "")),
                    Owner.PEOS,
                    Disposition.ERROR,
                )
            )
    source_keys: set[tuple[str, str, str]] = set()
    canonical_pointers: set[str] = set()
    for mapping_id, item in sorted(mappings.items()):
        record = _mapping(item)
        pointer = str(record.get("canonical_pointer", ""))
        source_key = (
            str(record.get("source_id", "")),
            str(record.get("source_pointer", "")),
            str(record.get("source_version", "")),
        )
        if (
            not _pointer_exists(bundle, pointer)
            or pointer in canonical_pointers
            or source_key in source_keys
        ):
            findings.append(
                _finding(
                    f"/source_identity_mappings/{mapping_id}",
                    "A source identity mapping is broken or not one-to-one.",
                    "PMOS must preserve one exact source identity for each canonical record.",
                    mapping_id,
                )
            )
        canonical_pointers.add(pointer)
        source_keys.add(source_key)
    return tuple(findings)


def _approval_required(
    bundle: Mapping[str, Any], _context: ValidationContext
) -> tuple[Finding, ...]:
    approvals = _mapping(bundle.get("approvals"))
    active_roles = {
        str(item.get("role"))
        for item in approvals.values()
        if isinstance(item, Mapping)
        and item.get("status") == "ACTIVE"
        and item.get("decision") == "APPROVED"
    }
    findings: list[Finding] = []
    if bundle.get("contract_status") != "APPROVED":
        findings.append(
            _finding(
                "/contract_status",
                "The canonical candidate is not product-approved.",
                "PMOS must publish an exact approved candidate.",
            )
        )
    for requirement_id, requirement in sorted(_mapping(bundle.get("required_approvals")).items()):
        role = str(_mapping(requirement).get("role", ""))
        if role not in active_roles:
            findings.append(
                _finding(
                    f"/required_approvals/{requirement_id}",
                    "A required product approval has no active matching authority.",
                    "PMOS must provide active approval evidence from the required role.",
                    requirement_id,
                )
            )
    return tuple(findings)


def _approval_active(bundle: Mapping[str, Any], _context: ValidationContext) -> tuple[Finding, ...]:
    approvals = _mapping(bundle.get("approvals"))
    findings: list[Finding] = []
    for approval_id, approval in sorted(approvals.items()):
        record = _mapping(approval)
        status = record.get("status")
        if status != "ACTIVE" or record.get("decision") != "APPROVED":
            findings.append(
                _finding(
                    f"/approvals/{approval_id}/status",
                    "Referenced approval evidence is revoked, superseded, or rejected.",
                    "PMOS must publish current active approval evidence.",
                    approval_id,
                )
            )
        superseded_by = record.get("superseded_by_approval_ref")
        if status == "SUPERSEDED":
            replacement = _mapping(approvals.get(str(superseded_by)))
            if (
                not superseded_by
                or replacement.get("status") != "ACTIVE"
                or approval_id not in _sequence(replacement.get("supersedes_approval_refs"))
            ):
                findings.append(
                    _finding(
                        f"/approvals/{approval_id}/superseded_by_approval_ref",
                        "Superseded approval evidence has no consistent active replacement.",
                        "PMOS must provide the reciprocal exact supersession relationship.",
                        approval_id,
                    )
                )
        for predecessor_id in _sequence(record.get("supersedes_approval_refs")):
            predecessor = _mapping(approvals.get(str(predecessor_id)))
            if (
                predecessor.get("status") != "SUPERSEDED"
                or predecessor.get("superseded_by_approval_ref") != approval_id
            ):
                findings.append(
                    _finding(
                        f"/approvals/{approval_id}/supersedes_approval_refs",
                        "Approval supersession evidence is missing or not reciprocal.",
                        "PMOS must bind both sides of the exact supersession relationship.",
                        f"{approval_id}->{predecessor_id}",
                    )
                )
    return tuple(findings)


def _approval_freshness(
    bundle: Mapping[str, Any], context: ValidationContext
) -> tuple[Finding, ...]:
    evaluated = _parse_time(context.evaluated_at)
    findings: list[Finding] = []
    for approval_id, approval in sorted(_mapping(bundle.get("approvals")).items()):
        record = _mapping(approval)
        try:
            valid_from = _parse_time(str(record.get("valid_from", "")))
            expires_at = _parse_time(str(record.get("expires_at", "")))
            approved_at = _parse_time(str(record.get("approved_at", "")))
        except ValueError:
            invalid = True
        else:
            invalid = not (approved_at <= evaluated and valid_from <= evaluated < expires_at)
        if invalid:
            findings.append(
                _finding(
                    f"/approvals/{approval_id}",
                    "Approval evidence is not active at the evaluation instant.",
                    "PMOS must provide fresh, temporally valid approval evidence.",
                    approval_id,
                )
            )
    return tuple(findings)


def _approval_authority(
    bundle: Mapping[str, Any], context: ValidationContext
) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    evaluated = _parse_time(context.evaluated_at)
    maturity = _mapping(_get(bundle, "/metrics/maturity_policies"))
    reporting = _mapping(_get(bundle, "/metrics/reporting_policies"))
    for approval_id, approval in sorted(_mapping(bundle.get("approvals")).items()):
        record = _mapping(approval)
        try:
            approved_at = _parse_time(str(record.get("approved_at", "")))
        except ValueError:
            approved_at = evaluated + timedelta(seconds=1)
        subject = _mapping(record.get("subject"))
        scope = subject.get("digest_scope")
        subject_id = str(subject.get("id", ""))
        expected_role: str | None = None
        expected_owner: str | None = None
        if scope == "CANONICAL_BUNDLE_EXCLUDING_APPROVALS":
            expected_role = "PRODUCT_OWNER"
        elif scope == "NAMED_METRIC_MATURITY_POLICY":
            expected_role = "METRIC_POLICY_OWNER"
            expected_owner = str(_mapping(maturity.get(subject_id)).get("owner_ref", ""))
        elif scope == "NAMED_METRIC_REPORTING_POLICY":
            expected_role = "METRIC_POLICY_OWNER"
            expected_owner = str(_mapping(reporting.get(subject_id)).get("owner_ref", ""))
        if (
            not _has_active_authority_grant(
                record, context.authority_grants, (approved_at, evaluated)
            )
            or (expected_role is not None and record.get("role") != expected_role)
            or (expected_owner is not None and record.get("actor_id") != expected_owner)
        ):
            findings.append(
                _finding(
                    f"/approvals/{approval_id}",
                    "Approval authority is not backed by an exact active governed grant.",
                    "Attach exact actor-role-policy grant evidence from the authority source.",
                    approval_id,
                )
            )
    return tuple(findings)


def _has_active_authority_grant(
    approval: Mapping[str, Any],
    grants: Sequence[ApprovalAuthorityGrant],
    required_instants: Sequence[datetime],
) -> bool:
    for grant in grants:
        if not (
            grant.actor_id == approval.get("actor_id")
            and grant.role == approval.get("role")
            and grant.authority_policy_id == approval.get("authority_policy_ref")
            and grant.authority_policy_version == approval.get("authority_policy_version")
            and grant.status == "ACTIVE"
        ):
            continue
        try:
            valid_from = _parse_time(grant.valid_from)
            expires_at = _parse_time(grant.expires_at)
            if all(valid_from <= instant < expires_at for instant in required_instants):
                return True
        except ValueError:
            continue
    return False


def _approval_subject(
    bundle: Mapping[str, Any], _context: ValidationContext
) -> tuple[Finding, ...]:
    projection = copy.deepcopy(dict(bundle))
    projection.pop("approvals", None)
    expected_bundle_digest = canonical_digest(projection)
    findings: list[Finding] = []
    maturity = _mapping(_get(bundle, "/metrics/maturity_policies"))
    reporting = _mapping(_get(bundle, "/metrics/reporting_policies"))
    for approval_id, approval in sorted(_mapping(bundle.get("approvals")).items()):
        subject = _mapping(_mapping(approval).get("subject"))
        scope = subject.get("digest_scope")
        subject_id = subject.get("id")
        if scope == "CANONICAL_BUNDLE_EXCLUDING_APPROVALS":
            expected = expected_bundle_digest
            expected_id = bundle.get("bundle_id")
            expected_version = bundle.get("bundle_version")
        elif scope == "NAMED_METRIC_MATURITY_POLICY" and subject_id in maturity:
            expected = canonical_digest(maturity[str(subject_id)])
            expected_id = subject_id
            expected_version = _mapping(maturity[str(subject_id)]).get("policy_version")
        elif scope == "NAMED_METRIC_REPORTING_POLICY" and subject_id in reporting:
            expected = canonical_digest(reporting[str(subject_id)])
            expected_id = subject_id
            expected_version = _mapping(reporting[str(subject_id)]).get("policy_version")
        else:
            expected = None
            expected_id = None
            expected_version = None
        if (
            expected is None
            or subject.get("digest") != expected
            or subject.get("id") != expected_id
            or subject.get("version") != expected_version
        ):
            findings.append(
                _finding(
                    f"/approvals/{approval_id}/subject",
                    "Approval evidence does not bind the exact current canonical subject.",
                    "PMOS must approve the exact ID, version, scope, and canonical digest.",
                    approval_id,
                )
            )
    subject_bindings = (
        (
            "/metrics/maturity_policies",
            maturity,
            "NAMED_METRIC_MATURITY_POLICY",
        ),
        (
            "/metrics/reporting_policies",
            reporting,
            "NAMED_METRIC_REPORTING_POLICY",
        ),
    )
    approvals = _mapping(bundle.get("approvals"))
    for base_path, registry, expected_scope in subject_bindings:
        for subject_id, subject_record in sorted(registry.items()):
            record = _mapping(subject_record)
            approval_ref = str(record.get("approval_ref", ""))
            approval_subject = _mapping(_mapping(approvals.get(approval_ref)).get("subject"))
            if (
                approval_subject.get("digest_scope") != expected_scope
                or approval_subject.get("id") != subject_id
                or approval_subject.get("version") != record.get("policy_version")
                or approval_subject.get("digest") != canonical_digest(record)
            ):
                findings.append(
                    _finding(
                        f"{base_path}/{subject_id}/approval_ref",
                        "A policy references approval evidence for a different exact subject.",
                        "PMOS must bind the policy to its own exact active approval subject.",
                        f"{subject_id}->{approval_ref}",
                    )
                )
    for index, approval_ref in enumerate(_sequence(_get(bundle, "/release/approval_refs"))):
        subject = _mapping(_mapping(approvals.get(str(approval_ref))).get("subject"))
        if (
            subject.get("digest_scope") != "CANONICAL_BUNDLE_EXCLUDING_APPROVALS"
            or subject.get("id") != bundle.get("bundle_id")
            or subject.get("version") != bundle.get("bundle_version")
            or subject.get("digest") != expected_bundle_digest
        ):
            findings.append(
                _finding(
                    f"/release/approval_refs/{index}",
                    "Release intent references approval for a different exact candidate.",
                    "PMOS must bind release intent to exact canonical bundle approval.",
                    str(approval_ref),
                )
            )
    return tuple(findings)


def _words(value: Any) -> set[str]:
    if not isinstance(value, str):
        return set()
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.casefold())
        if len(token) >= 4 and token not in _STOP_WORDS
    }


def _outcome_hypothesis(
    bundle: Mapping[str, Any], _context: ValidationContext
) -> tuple[Finding, ...]:
    problem = _words(_get(bundle, "/product/problem/statement"))
    hypothesis = _words(_get(bundle, "/product/hypothesis/statement")) | _words(
        _get(bundle, "/product/hypothesis/falsification_condition")
    )
    outcome = set()
    for key in ("statement", "customer_outcome", "business_outcome", "measurable_change"):
        outcome |= _words(_get(bundle, f"/product/outcome/{key}"))
    findings: list[Finding] = []
    if problem and hypothesis and not problem & hypothesis:
        findings.append(
            _finding(
                "/product/hypothesis",
                "The hypothesis has no deterministic concept link to the stated problem.",
                "PMOS must state the explicit problem-to-hypothesis relationship.",
            )
        )
    if hypothesis and outcome and not hypothesis & outcome:
        findings.append(
            _finding(
                "/product/outcome",
                "The hypothesis has no deterministic measurable link to the stated outcome.",
                "PMOS must state the hypothesis-to-outcome relationship and measurable change.",
            )
        )
    return tuple(findings)


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value).strip().casefold())


def _scope_non_goal(bundle: Mapping[str, Any], _context: ValidationContext) -> tuple[Finding, ...]:
    scope = {_norm(item) for item in _sequence(_get(bundle, "/scope/in_scope"))}
    non_goals = {_norm(item) for item in _sequence(_get(bundle, "/scope/non_goals"))}
    return (
        (
            _finding(
                "/scope",
                "The same capability is declared both in scope and as an explicit non-goal.",
                "PMOS must choose one scope disposition.",
            ),
        )
        if scope & non_goals
        else ()
    )


def _solution_non_goal(
    bundle: Mapping[str, Any], _context: ValidationContext
) -> tuple[Finding, ...]:
    non_goals = {_norm(item) for item in _sequence(_get(bundle, "/scope/non_goals"))}
    findings: list[Finding] = []
    for requirement_id, requirement in sorted(
        _mapping(bundle.get("functional_requirements")).items()
    ):
        statement = _norm(_mapping(requirement).get("statement"))
        if statement in non_goals:
            findings.append(
                _finding(
                    f"/functional_requirements/{requirement_id}/statement",
                    "A functional requirement implements an explicit non-goal.",
                    "PMOS must reconcile requirement scope and the non-goal.",
                    requirement_id,
                )
            )
    outcome_values = {_norm(value) for value in _mapping(_get(bundle, "/product/outcome")).values()}
    if outcome_values & non_goals:
        findings.append(
            _finding(
                "/product/outcome",
                "The declared outcome depends on an explicitly excluded capability.",
                "PMOS must reconcile the outcome dependency and non-goal.",
            )
        )
    return tuple(findings)


def _metric_outcome(bundle: Mapping[str, Any], _context: ValidationContext) -> tuple[Finding, ...]:
    outcome_words: set[str] = set()
    for value in _mapping(_get(bundle, "/product/outcome")).values():
        outcome_words |= _words(value)
    findings: list[Finding] = []
    for metric_id, metric in sorted(_mapping(_get(bundle, "/metrics/success")).items()):
        metric_words = _words(_mapping(metric).get("definition"))
        if metric_words and outcome_words and not metric_words & outcome_words:
            findings.append(
                _finding(
                    f"/metrics/success/{metric_id}",
                    "A success metric has no deterministic concept link to the stated outcome.",
                    "PMOS must define how the metric measures the customer or business outcome.",
                    metric_id,
                )
            )
    return tuple(findings)


def _policy_consistency(
    bundle: Mapping[str, Any], _context: ValidationContext
) -> tuple[Finding, ...]:
    reporting_policies = _mapping(_get(bundle, "/metrics/reporting_policies"))
    by_metric: dict[str, list[tuple[str, Mapping[str, Any]]]] = {}
    for policy_id, policy in sorted(_mapping(_get(bundle, "/metrics/maturity_policies")).items()):
        record = _mapping(policy)
        by_metric.setdefault(str(record.get("metric_ref", "")), []).append((policy_id, record))
    findings: list[Finding] = []
    for metric_id, policies in by_metric.items():
        if len(policies) < 2:
            continue
        canonical_policies = {
            canonical_digest(
                {
                    "delivery_window": policy.get("delivery_window"),
                    "evaluation_window": policy.get("evaluation_window"),
                    "reporting_policy": reporting_policies.get(
                        str(policy.get("reporting_policy_ref", ""))
                    ),
                    "reporting_policy_ref": policy.get("reporting_policy_ref"),
                    "reporting_window": policy.get("reporting_window"),
                    "target": policy.get("target"),
                }
            )
            for _policy_id, policy in policies
        }
        if len(canonical_policies) > 1:
            findings.append(
                _finding(
                    "/metrics/maturity_policies",
                    "The same metric has incompatible approved target or window definitions.",
                    "PMOS must select one prospective policy definition for the metric.",
                    metric_id,
                )
            )
    return tuple(findings)


def _leading_distinct(
    bundle: Mapping[str, Any], _context: ValidationContext
) -> tuple[Finding, ...]:
    outcome_definitions = {
        _norm(_mapping(item).get("definition"))
        for item in _mapping(_get(bundle, "/metrics/success")).values()
    } | {
        _norm(_mapping(item).get("definition"))
        for item in _mapping(_get(bundle, "/metrics/north_stars")).values()
    }
    return tuple(
        _finding(
            f"/metrics/leading/{metric_id}/definition",
            "A leading indicator is indistinguishable from an outcome metric.",
            "PMOS must define a genuinely leading signal or classify it as an outcome metric.",
            metric_id,
        )
        for metric_id, metric in sorted(_mapping(_get(bundle, "/metrics/leading")).items())
        if _norm(_mapping(metric).get("definition")) in outcome_definitions
    )


def _target_guardrail(
    bundle: Mapping[str, Any], _context: ValidationContext
) -> tuple[Finding, ...]:
    upper_bounds: list[float] = []
    for guardrail in _mapping(bundle.get("guardrails")).values():
        match = re.search(
            r"(?i)at most\s+([0-9]+(?:\.[0-9]+)?)", str(_mapping(guardrail).get("threshold", ""))
        )
        if match:
            upper_bounds.append(float(match.group(1)))
    if not upper_bounds:
        return ()
    for policy_id, policy in sorted(_mapping(_get(bundle, "/metrics/maturity_policies")).items()):
        target = _mapping(_mapping(policy).get("target"))
        value = target.get("value")
        if (
            target.get("operator") == "AT_LEAST"
            and isinstance(value, (int, float))
            and value > min(upper_bounds)
        ):
            return (
                _finding(
                    f"/metrics/maturity_policies/{policy_id}/target",
                    "An approved metric target exceeds a declared guardrail upper bound.",
                    "PMOS must reconcile the target and guardrail threshold.",
                    policy_id,
                ),
            )
    return ()


def _alignment_dependency(
    bundle: Mapping[str, Any], _context: ValidationContext
) -> tuple[Finding, ...]:
    dependency_text = " ".join(
        f"{dependency_id} {json.dumps(item, sort_keys=True)}"
        for dependency_id, item in sorted(_mapping(bundle.get("dependencies")).items())
    ).casefold()
    findings: list[Finding] = []
    for requirement_id, requirement in sorted(
        _mapping(bundle.get("functional_requirements")).items()
    ):
        capability = str(_mapping(requirement).get("capability", ""))
        if capability.startswith("integration."):
            dependency_name = capability.partition(".")[2].casefold()
            if dependency_name and dependency_name not in dependency_text:
                findings.append(
                    _finding(
                        f"/functional_requirements/{requirement_id}/capability",
                        "A required external integration has no declared dependency.",
                        "PMOS must declare the dependency, owner, and product consequences.",
                        requirement_id,
                    )
                )
    return tuple(findings)


def _requirement_scope(
    bundle: Mapping[str, Any], _context: ValidationContext
) -> tuple[Finding, ...]:
    scope_words: set[str] = set()
    for item in _sequence(_get(bundle, "/scope/in_scope")):
        scope_words |= _words(item)
    findings: list[Finding] = []
    for requirement_id, requirement in sorted(
        _mapping(bundle.get("functional_requirements")).items()
    ):
        record = _mapping(requirement)
        if record.get("priority") != "MUST":
            continue
        requirement_words = _words(record.get("title")) | _words(record.get("statement"))
        if requirement_words and scope_words and not requirement_words & scope_words:
            findings.append(
                _finding(
                    f"/functional_requirements/{requirement_id}",
                    "A mandatory requirement has no deterministic relationship to declared scope.",
                    "PMOS must explicitly connect the requirement to scope or remove it.",
                    requirement_id,
                )
            )
    return tuple(findings)


def _alignment_autonomy(
    bundle: Mapping[str, Any], _context: ValidationContext
) -> tuple[Finding, ...]:
    stage = str(_get(bundle, "/release/requested_autonomy_stage") or "")
    policies = _mapping(_get(bundle, "/metrics/maturity_policies"))
    north_stars = _mapping(_get(bundle, "/metrics/north_stars"))
    required_north_star = "mvp" if stage == "DRAFT_PR" else "end_state"
    north_star = _mapping(north_stars.get(required_north_star))
    policy_ref = str(north_star.get("maturity_policy_ref", ""))
    policy = _mapping(policies.get(policy_ref))
    findings: list[Finding] = []
    if stage not in _sequence(policy.get("applicable_autonomy_stages")):
        findings.append(
            _finding(
                f"/metrics/north_stars/{required_north_star}/maturity_policy_ref",
                "Requested autonomy exceeds the applicable North Star maturity policy.",
                "PMOS must lower the stage or approve the exact North Star policy for it.",
                policy_ref,
            )
        )
    expected_environment = {
        "DRAFT_PR": "LOCAL",
        "STAGING": "STAGING",
        "CANARY": "CANARY",
        "PRODUCTION": "PRODUCTION",
    }.get(stage)
    actual_environment = _get(bundle, "/release/deployment_target/environment")
    if expected_environment is not None and actual_environment != expected_environment:
        findings.append(
            _finding(
                "/release/deployment_target/environment",
                "Deployment target contradicts the requested autonomy stage.",
                "PMOS must reconcile the release stage and exact deployment environment.",
                stage,
            )
        )
    expectation_environments = {
        str(_mapping(item).get("environment", ""))
        for item in _mapping(_get(bundle, "/release/expectations")).values()
    }
    if stage not in expectation_environments:
        findings.append(
            _finding(
                "/release/expectations",
                "Release expectations do not cover the requested autonomy stage.",
                "PMOS must state the exact stage-specific release expectation.",
                stage,
            )
        )
    launch_intent = str(_get(bundle, "/release/launch_intent") or "")
    if stage == "PRODUCTION" and launch_intent not in {
        "LIMITED_AVAILABILITY",
        "GENERAL_AVAILABILITY",
    }:
        findings.append(
            _finding(
                "/release/launch_intent",
                "Production autonomy contradicts the declared non-production launch intent.",
                "PMOS must choose an eligible production launch intent or lower autonomy.",
                launch_intent,
            )
        )
    return tuple(findings)


def _release_approval(
    bundle: Mapping[str, Any], _context: ValidationContext
) -> tuple[Finding, ...]:
    stage = str(_get(bundle, "/release/requested_autonomy_stage") or "")
    required_before = {
        str(_mapping(item).get("required_before", ""))
        for item in _mapping(bundle.get("required_approvals")).values()
    }
    required = {
        "DRAFT_PR": {"CONTRACT_APPROVAL", "DRAFT_PR"},
        "STAGING": {"STAGING"},
        "CANARY": {"CANARY"},
        "PRODUCTION": {"PRODUCTION"},
    }.get(stage, set())
    if stage == "DRAFT_PR" and required_before & required:
        return ()
    if stage != "DRAFT_PR" and stage in required_before:
        return ()
    return (
        _finding(
            "/required_approvals",
            "Release intent lacks the human approval gate required for its autonomy stage.",
            "PMOS must declare and bind the stage-specific human approval.",
            stage,
        ),
    )


def _release_rollback(
    bundle: Mapping[str, Any], _context: ValidationContext
) -> tuple[Finding, ...]:
    stage = str(_get(bundle, "/release/requested_autonomy_stage") or "")
    rpo = str(_get(bundle, "/rollback/rpo") or "")
    tolerance = _norm(_get(bundle, "/rollback/data_loss_tolerance"))
    if (
        stage in {"STAGING", "CANARY", "PRODUCTION"}
        and "no data loss" in tolerance
        and rpo != "PT0S"
    ):
        return (
            _finding(
                "/rollback/rpo",
                "Rollback recovery-point objective contradicts the stated zero-loss tolerance.",
                "PMOS must reconcile rollback timing and data-loss intent.",
            ),
        )
    return ()


def _security_privacy(
    bundle: Mapping[str, Any], _context: ValidationContext
) -> tuple[Finding, ...]:
    allowed = {str(item) for item in _sequence(_get(bundle, "/privacy/telemetry/allowed_fields"))}
    prohibited = {
        str(item) for item in _sequence(_get(bundle, "/privacy/telemetry/prohibited_fields"))
    }
    findings: list[Finding] = []
    if allowed & prohibited:
        findings.append(
            _finding(
                "/privacy/telemetry",
                "Telemetry permits fields that the same privacy policy prohibits.",
                "PMOS and the privacy owner must reconcile allowed and prohibited telemetry.",
            )
        )
    return tuple(findings)


def _observability_reporting(
    bundle: Mapping[str, Any], _context: ValidationContext
) -> tuple[Finding, ...]:
    prohibited = {
        str(item).casefold()
        for item in _sequence(_get(bundle, "/privacy/telemetry/prohibited_fields"))
    }
    return tuple(
        _finding(
            f"/observability/requirements/{record_id}/signal",
            "An observability signal conflicts with prohibited telemetry intent.",
            "PMOS, security, and privacy owners must approve a compliant signal.",
            record_id,
        )
        for record_id, record in sorted(
            _mapping(_get(bundle, "/observability/requirements")).items()
        )
        if str(_mapping(record).get("signal", "")).casefold() in prohibited
    )


def _contradictory_text(left: str, right: str) -> bool:
    first = _norm(left)
    second = _norm(right)
    for positive, negative in ((first, second), (second, first)):
        if "must not " in negative:
            subject = negative.partition("must not ")[2]
            if subject and (f"must {subject}" in positive or positive == subject):
                return True
    return False


def _alignment_cross_channel(
    bundle: Mapping[str, Any], _context: ValidationContext
) -> tuple[Finding, ...]:
    ux_text = list(_walk_strings(bundle.get("ux"), "/ux"))
    technical_text = [
        (path, value)
        for section in ("api_contracts", "data")
        for path, value in _walk_strings(bundle.get(section), f"/{section}")
    ]
    hypothesis_text = list(
        _walk_strings(_get(bundle, "/product/hypothesis"), "/product/hypothesis")
    )
    outcome_text = list(_walk_strings(_get(bundle, "/product/outcome"), "/product/outcome"))
    requirement_text = list(
        _walk_strings(bundle.get("functional_requirements"), "/functional_requirements")
    )
    pairs = [(left, right) for left in ux_text for right in technical_text]
    pairs.extend((left, right) for left in hypothesis_text for right in requirement_text)
    pairs.extend((left, right) for left in hypothesis_text for right in outcome_text)
    pairs.extend((left, right) for left in requirement_text for right in technical_text)
    for (left_path, left), (right_path, right) in pairs:
        if _contradictory_text(left, right):
            return (
                _finding(
                    left_path,
                    "Canonical product channels contain directly contradictory obligations.",
                    (
                        "PMOS must reconcile the exact hypothesis, requirement, UX, API, "
                        "or data truth."
                    ),
                    right_path,
                ),
            )
    return ()


def _ownership_product_truth(
    bundle: Mapping[str, Any], _context: ValidationContext
) -> tuple[Finding, ...]:
    product_owned_sections = (
        "product",
        "scope",
        "metrics",
        "functional_requirements",
        "acceptance_criteria",
        "ux",
        "release",
        "rollback",
        "security",
        "privacy",
        "data",
        "open_questions",
        "product_decisions",
    )
    findings: list[Finding] = []
    for section in product_owned_sections:
        for path, value in _walk_strings(bundle.get(section), f"/{section}"):
            if any(pattern.search(value) for pattern in _OWNERSHIP_PATTERNS):
                findings.append(
                    _finding(
                        path,
                        (
                            "Product-owned truth is delegated to an unnamed future "
                            "engineering decision."
                        ),
                        "PMOS or a named human product authority must decide and approve it.",
                    )
                )
    return tuple(findings)


def _extension_supported(
    bundle: Mapping[str, Any], _context: ValidationContext
) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    for extension_id, extension in sorted(_mapping(bundle.get("extensions")).items()):
        record = _mapping(extension)
        key = (str(record.get("schema_id", "")), str(record.get("schema_version", "")))
        if key not in SUPPORTED_EXTENSION_SCHEMAS:
            findings.append(
                Finding(
                    f"/extensions/{extension_id}",
                    "The repository extension schema/version is not supported by this rule set.",
                    "Register and review the extension schema before engineering admission.",
                    extension_id,
                    Owner.REPOSITORY_OWNER,
                    Disposition.UNSUPPORTED_REPOSITORY_EXTENSION,
                )
            )
        if record.get("payload_digest") != canonical_digest(record.get("payload")):
            findings.append(
                Finding(
                    f"/extensions/{extension_id}/payload_digest",
                    "The extension payload does not match its declared canonical digest.",
                    "Republish the exact extension payload and digest.",
                    extension_id,
                    Owner.REPOSITORY_OWNER,
                    Disposition.UNSUPPORTED_REPOSITORY_EXTENSION,
                )
            )
    return tuple(findings)


def _extension_constraint(
    bundle: Mapping[str, Any], _context: ValidationContext
) -> tuple[Finding, ...]:
    all_ids = _all_registry_ids(bundle)
    findings: list[Finding] = []
    for extension_id, extension in sorted(_mapping(bundle.get("extensions")).items()):
        record = _mapping(extension)
        for reference in _sequence(record.get("target_refs")):
            if reference not in all_ids:
                findings.append(
                    Finding(
                        f"/extensions/{extension_id}/target_refs",
                        "The extension targets a missing canonical record.",
                        (
                            "PMOS must restore the exact canonical target or remove the "
                            "extension reference."
                        ),
                        str(reference),
                        Owner.PMOS,
                        Disposition.PRODUCT_INPUT_REQUIRED,
                    )
                )
        constraints = _mapping(_get(record, "/payload/constraints"))
        for constraint_id, constraint in sorted(constraints.items()):
            constraint_record = _mapping(constraint)
            pointer = str(constraint_record.get("target_pointer", ""))
            if (
                not _pointer_exists(bundle, pointer)
                or pointer.startswith("/extensions")
                or pointer.startswith("/approvals")
                or not _constraint_satisfied(bundle, constraint_record)
            ):
                findings.append(
                    Finding(
                        f"/extensions/{extension_id}/payload/constraints/{constraint_id}",
                        "An extension constraint has an unknown or governance-weakening target.",
                        "Restrict the extension to an existing non-governance canonical field.",
                        constraint_id,
                        Owner.REPOSITORY_OWNER,
                        Disposition.UNSUPPORTED_REPOSITORY_EXTENSION,
                    )
                )
    return tuple(findings)


def _constraint_satisfied(bundle: Mapping[str, Any], constraint: Mapping[str, Any]) -> bool:
    pointer = str(constraint.get("target_pointer", ""))
    exists, target = _resolve_pointer(bundle, pointer)
    if not exists:
        return False
    operator = str(constraint.get("operator", ""))
    raw_value = str(constraint.get("constraint_value", ""))
    if operator == "REQUIRE_PRESENT":
        return True
    if operator == "FORBID_VALUE":
        return isinstance(target, str) and target != raw_value
    if operator == "MATCH_PATTERN":
        if not isinstance(target, str):
            return False
        try:
            return re.fullmatch(raw_value, target) is not None
        except re.error:
            return False
    if operator == "LIMIT_ALLOWED_VALUES":
        try:
            allowed = json.loads(raw_value)
        except json.JSONDecodeError:
            return False
        return isinstance(allowed, list) and target in allowed
    if operator in {"SET_MAXIMUM", "SET_MINIMUM"}:
        if not isinstance(target, (int, float)) or isinstance(target, bool):
            return False
        try:
            boundary = float(raw_value)
        except ValueError:
            return False
        return target <= boundary if operator == "SET_MAXIMUM" else target >= boundary
    return False


def _metric_maturity_policy(
    bundle: Mapping[str, Any], _context: ValidationContext
) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    policies = _mapping(_get(bundle, "/metrics/maturity_policies"))
    approvals = _mapping(bundle.get("approvals"))
    for policy_id, policy in sorted(policies.items()):
        record = _mapping(policy)
        target = _mapping(record.get("target"))
        approval = _mapping(approvals.get(str(record.get("approval_ref", ""))))
        subject = _mapping(approval.get("subject"))
        ready = (
            target.get("status") == "APPROVED"
            and approval.get("status") == "ACTIVE"
            and approval.get("decision") == "APPROVED"
            and subject.get("digest") == canonical_digest(record)
        )
        if not ready:
            findings.append(
                _finding(
                    f"/metrics/maturity_policies/{policy_id}",
                    "A metric maturity policy is pending, inactive, or not exactly approved.",
                    "The named owner must approve a prospective versioned policy and target.",
                    policy_id,
                )
            )
    return tuple(findings)


def _correction_binding(
    _bundle: Mapping[str, Any], context: ValidationContext
) -> tuple[Finding, ...]:
    correction = context.correction_reference
    if correction is not None and correction.lineage_id != context.lineage_id:
        return (
            Finding(
                "/correction_reference/lineage_id",
                "A correction attempts to replace the immutable intake lineage.",
                "Preserve the original lineage and create a new attempt through normal intake.",
                correction.attempt_id,
                Owner.PEOS,
                Disposition.ERROR,
            ),
        )
    return ()


def _possible_duplicate(
    _bundle: Mapping[str, Any], context: ValidationContext
) -> tuple[Finding, ...]:
    if not context.possible_duplicate:
        return ()
    return (
        Finding(
            "/lineage",
            (
                "Intake marked this new lineage as a possible duplicate without a valid "
                "correction reference."
            ),
            "PMOS should reconcile the publisher correction reference; do not coalesce lineages.",
            None,
            Owner.PMOS,
            Disposition.WARNING,
        ),
    )


def _metric_eligibility(
    bundle: Mapping[str, Any], context: ValidationContext
) -> dict[str, dict[str, str | None]]:
    result: dict[str, dict[str, str | None]] = {}
    approvals = _mapping(bundle.get("approvals"))
    evaluated = _parse_time(context.evaluated_at)
    for policy_id, policy in sorted(_mapping(_get(bundle, "/metrics/maturity_policies")).items()):
        record = _mapping(policy)
        approval = _mapping(approvals.get(str(record.get("approval_ref", ""))))
        target = _mapping(record.get("target"))
        subject = _mapping(approval.get("subject"))
        try:
            approved_at = _parse_time(str(approval.get("approved_at")))
            temporally_active = approved_at <= evaluated and _parse_time(
                str(approval.get("valid_from"))
            ) <= evaluated < _parse_time(str(approval.get("expires_at")))
        except ValueError:
            approved_at = None
            temporally_active = False
        ready = all(
            (
                target.get("status") == "APPROVED",
                approval.get("status") == "ACTIVE",
                approval.get("decision") == "APPROVED",
                subject.get("digest_scope") == "NAMED_METRIC_MATURITY_POLICY",
                subject.get("id") == policy_id,
                subject.get("version") == record.get("policy_version"),
                subject.get("digest") == canonical_digest(record),
                temporally_active,
                approval.get("role") == "METRIC_POLICY_OWNER",
                approval.get("actor_id") == record.get("owner_ref"),
                _has_active_authority_grant(
                    approval,
                    context.authority_grants,
                    (approved_at, evaluated) if approved_at is not None else (),
                )
                if approved_at is not None
                else False,
            )
        )
        if not ready:
            result[policy_id] = {"due_at": None, "eligible_at": None}
            continue
        try:
            eligible = max(
                _parse_time(context.lineage_received_at),
                _parse_time(str(approval.get("approved_at"))),
                _parse_time(str(approval.get("valid_from"))),
            )
            duration = str(_mapping(record.get("delivery_window")).get("duration", ""))
            due = eligible + _duration(duration)
        except ValueError:
            result[policy_id] = {"due_at": None, "eligible_at": None}
            continue
        result[policy_id] = {"due_at": _format_time(due), "eligible_at": _format_time(eligible)}
    return result


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be UTC")
    return parsed.astimezone(UTC)


def _format_time(value: datetime) -> str:
    timespec = "microseconds" if value.microsecond else "seconds"
    return value.astimezone(UTC).isoformat(timespec=timespec).replace("+00:00", "Z")


def _duration(value: str) -> timedelta:
    match = re.fullmatch(
        r"P(?:(\d+)W|(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?)",
        value,
    )
    if not match or not any(item is not None for item in match.groups()):
        raise ValueError("unsupported duration")
    weeks, days, hours, minutes, seconds_text = match.groups()
    try:
        seconds = Decimal(seconds_text or "0")
        microseconds = seconds * Decimal(1_000_000)
    except InvalidOperation as exc:
        raise ValueError("unsupported duration") from exc
    if microseconds != microseconds.to_integral_value():
        raise ValueError("duration precision exceeds deterministic microseconds")
    try:
        return timedelta(
            weeks=int(weeks or 0),
            days=int(days or 0),
            hours=int(hours or 0),
            minutes=int(minutes or 0),
            microseconds=int(microseconds),
        )
    except OverflowError as exc:
        raise ValueError("duration exceeds supported range") from exc


def _walk_strings(value: Any, path: str) -> tuple[tuple[str, str], ...]:
    found: list[tuple[str, str]] = []
    if isinstance(value, Mapping):
        for key, child in sorted(value.items()):
            found.extend(_walk_strings(child, f"{path}/{_escape_pointer(str(key))}"))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, child in enumerate(value):
            found.extend(_walk_strings(child, f"{path}/{index}"))
    elif isinstance(value, str):
        found.append((path, value))
    return tuple(found)


def _escape_pointer(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _json_pointer(parts: Sequence[Any]) -> str:
    return "/" + "/".join(_escape_pointer(str(part)) for part in parts) if parts else ""


def _pointer_exists(value: Any, pointer: str) -> bool:
    exists, _resolved = _resolve_pointer(value, pointer)
    return exists


def _resolve_pointer(value: Any, pointer: str) -> tuple[bool, Any]:
    if pointer == "":
        return True, value
    if not pointer.startswith("/"):
        return False, None
    current = value
    for raw in pointer[1:].split("/"):
        part = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        elif (
            isinstance(current, Sequence)
            and not isinstance(current, (str, bytes))
            and part.isdigit()
            and int(part) < len(current)
        ):
            current = current[int(part)]
        else:
            return False, None
    return True, current


def _all_registry_ids(bundle: Mapping[str, Any]) -> set[str]:
    identifiers: set[str] = set()
    for _key, value in bundle.items():
        if isinstance(value, Mapping):
            identifiers.update(str(item) for item in value if isinstance(item, str))
            for nested in value.values():
                if isinstance(nested, Mapping):
                    identifiers.update(str(item) for item in nested if isinstance(item, str))
    return identifiers


class ValidationEvidenceError(RuntimeError):
    """Validation evidence conflicts with immutable lineage accounting."""


def _safe_evidence_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise ValidationEvidenceError(f"{label} is not a safe opaque identifier")
    return value


class FileValidationEvidenceStore:
    """Write-once validation artifacts using the repository ArtifactStore.

    The lineage index preserves the first attempt permanently.  Corrections add
    attempts but never add a second first-pass denominator entry.  A file lock
    serializes writers; ``reconcile`` can rebuild lineage indexes from immutable
    attempt artifacts after an interrupted index write.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.artifacts = ArtifactStore(self.root)
        self._lock_path = self.root / ".validation-evidence.lock"
        self._lock_path.touch(mode=0o600, exist_ok=True)

    def record(self, result: ValidationResult) -> None:
        _safe_evidence_id(result.ingestion_attempt_id, "ingestion attempt ID")
        _safe_evidence_id(result.lineage_id, "lineage ID")
        if result.correction_reference is not None:
            _safe_evidence_id(result.correction_reference.lineage_id, "correction lineage ID")
            _safe_evidence_id(result.correction_reference.attempt_id, "correction attempt ID")
        with self._lock_path.open("rb") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                self._record_locked(result)
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _record_locked(self, result: ValidationResult) -> None:
        attempt_id = _safe_evidence_id(result.ingestion_attempt_id, "ingestion attempt ID")
        lineage_id = _safe_evidence_id(result.lineage_id, "lineage ID")
        correction = result.correction_reference
        if correction is not None:
            _safe_evidence_id(correction.lineage_id, "correction lineage ID")
            _safe_evidence_id(correction.attempt_id, "correction attempt ID")
        attempt_name = f"attempts/{attempt_id}.json"
        payload = result.as_dict()
        if self.artifacts.exists(attempt_name):
            if self.artifacts.read_json(attempt_name) != payload:
                raise ValidationEvidenceError("attempt already contains different evidence")
            lineage_name = f"lineages/{lineage_id}.json"
            if not self.artifacts.exists(
                lineage_name
            ) or attempt_id not in self.artifacts.read_json(lineage_name).get("attempt_ids", []):
                self._reconcile_locked()
            return
        lineage_name = f"lineages/{lineage_id}.json"
        if not self.artifacts.exists(lineage_name):
            self._reconcile_locked()
        existing = (
            self.artifacts.read_json(lineage_name) if self.artifacts.exists(lineage_name) else None
        )
        if correction is not None:
            if correction.lineage_id != lineage_id:
                raise ValidationEvidenceError("correction changes immutable lineage")
            original_name = f"attempts/{correction.attempt_id}.json"
            if not self.artifacts.exists(original_name):
                raise ValidationEvidenceError("correction references unknown original attempt")
            original = self.artifacts.read_json(original_name)
            if original.get("lineage_id") != result.lineage_id:
                raise ValidationEvidenceError("correction references another lineage")
            if original.get("lineage_received_at") != result.lineage_received_at:
                raise ValidationEvidenceError(
                    "correction changes the immutable original lineage receipt time"
                )
            existing_attempt_ids = existing.get("attempt_ids") if existing is not None else None
            if (
                not isinstance(existing_attempt_ids, list)
                or not existing_attempt_ids
                or correction.attempt_id != existing_attempt_ids[-1]
            ):
                raise ValidationEvidenceError(
                    "correction must extend the latest immutable lineage attempt"
                )
        elif existing is not None:
            raise ValidationEvidenceError(
                "new attempt in an existing lineage requires correction evidence"
            )
        self.artifacts.write_json(attempt_name, payload)
        if existing is None:
            lineage = {
                "attempt_ids": [result.ingestion_attempt_id],
                "denominator_entries": 1,
                "first_pass_attempt_id": result.ingestion_attempt_id,
                "first_pass_disposition": result.disposition.value,
                "latest_disposition": result.disposition.value,
                "lineage_id": result.lineage_id,
                "lineage_received_at": result.lineage_received_at,
            }
        else:
            lineage = dict(existing)
            attempt_ids = lineage.get("attempt_ids")
            if not isinstance(attempt_ids, list) or not all(
                isinstance(item, str) for item in attempt_ids
            ):
                raise ValidationEvidenceError("stored lineage attempt index is malformed")
            lineage["attempt_ids"] = [*attempt_ids, result.ingestion_attempt_id]
            lineage["latest_disposition"] = result.disposition.value
        self.artifacts.write_json(lineage_name, lineage)

    def load_attempt(self, attempt_id: str) -> dict[str, Any]:
        safe_attempt_id = _safe_evidence_id(attempt_id, "ingestion attempt ID")
        value = self.artifacts.read_json(f"attempts/{safe_attempt_id}.json")
        if not isinstance(value, dict):
            raise ValidationEvidenceError("stored attempt evidence is malformed")
        return value

    def lineage_summary(self, lineage_id: str) -> dict[str, Any]:
        safe_lineage_id = _safe_evidence_id(lineage_id, "lineage ID")
        value = self.artifacts.read_json(f"lineages/{safe_lineage_id}.json")
        if not isinstance(value, dict):
            raise ValidationEvidenceError("stored lineage evidence is malformed")
        return value

    def metric_summary(self) -> dict[str, int]:
        lineages = self.artifacts.root / "lineages"
        summaries = (
            [json.loads(path.read_text()) for path in sorted(lineages.glob("*.json"))]
            if lineages.exists()
            else []
        )
        return {
            "first_pass_denominator": sum(int(item["denominator_entries"]) for item in summaries),
            "first_pass_passed": sum(
                1 for item in summaries if item["first_pass_disposition"] in {"ADMITTED", "WARNING"}
            ),
        }

    def reconcile(self) -> None:
        with self._lock_path.open("rb") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                self._reconcile_locked()
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _reconcile_locked(self) -> None:
        attempts = self.artifacts.root / "attempts"
        if not attempts.exists():
            return
        grouped: dict[str, list[dict[str, Any]]] = {}
        for path in sorted(attempts.glob("*.json")):
            record = json.loads(path.read_text())
            if not isinstance(record, dict):
                raise ValidationEvidenceError("stored attempt evidence is malformed")
            attempt_id = _safe_evidence_id(
                record.get("ingestion_attempt_id"), "stored ingestion attempt ID"
            )
            lineage_id = _safe_evidence_id(record.get("lineage_id"), "stored lineage ID")
            if path.name != f"{attempt_id}.json":
                raise ValidationEvidenceError("stored attempt filename does not match evidence")
            grouped.setdefault(lineage_id, []).append(record)
        for lineage_id, records in grouped.items():
            by_attempt = {str(item["ingestion_attempt_id"]): item for item in records}
            if len(by_attempt) != len(records):
                raise ValidationEvidenceError("lineage contains duplicate attempt evidence")
            roots = [item for item in records if item.get("correction_reference") is None]
            if len(roots) != 1:
                raise ValidationEvidenceError(
                    "lineage must contain exactly one first-pass artifact"
                )
            ordered = [roots[0]]
            while len(ordered) < len(records):
                parent_id = ordered[-1]["ingestion_attempt_id"]
                children = [
                    item
                    for item in records
                    if isinstance(item.get("correction_reference"), dict)
                    and item["correction_reference"].get("lineage_id") == lineage_id
                    and item["correction_reference"].get("attempt_id") == parent_id
                ]
                if len(children) != 1:
                    raise ValidationEvidenceError(
                        "lineage correction graph is branched, orphaned, or cyclic"
                    )
                ordered.append(children[0])
            first = ordered[0]
            summary = {
                "attempt_ids": [item["ingestion_attempt_id"] for item in ordered],
                "denominator_entries": 1,
                "first_pass_attempt_id": first["ingestion_attempt_id"],
                "first_pass_disposition": first["disposition"],
                "latest_disposition": ordered[-1]["disposition"],
                "lineage_id": lineage_id,
                "lineage_received_at": first["lineage_received_at"],
            }
            self.artifacts.write_json(f"lineages/{lineage_id}.json", summary)

    def _write_attempt_for_test(self, attempt_id: str, payload: dict[str, Any]) -> None:
        safe_attempt_id = _safe_evidence_id(attempt_id, "ingestion attempt ID")
        name = f"attempts/{safe_attempt_id}.json"
        if self.artifacts.exists(name) and self.artifacts.read_json(name) != payload:
            raise ValidationEvidenceError("attempt already contains different evidence")
        self.artifacts.write_json(name, payload)


_MANDATORY_RULE_METADATA.update(
    {rule.rule_id: rule.digest_metadata() for rule in default_rule_registry().rules}
)
_MANDATORY_RULE_EVALUATORS.update(
    {rule.rule_id: rule.evaluator for rule in default_rule_registry().rules}
)
