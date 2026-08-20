"""Content-addressed evidence manifests for exact-subject delivery gates.

The manifest is the authority.  PR descriptions, comments, logs, and model prose may
link to a sealed bundle, but their mutable text is never accepted as evidence.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType

from pmpe.contracts.digest import canonical_digest
from pmpe.domain.serialize import atomic_write_json, jsonable

_SHA = re.compile(r"^[0-9a-f]{40,64}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_RESULTS = frozenset({"PASS", "FAIL", "HOLD"})
_EXECUTION_MODES = frozenset(
    {"AUTOMATED", "HUMAN_TECHNICAL", "HUMAN_INTERPRETATION", "HUMAN_GOVERNANCE"}
)
_IMMUTABLE_MEDIA = frozenset(
    {
        "ATTESTATION",
        "CHECK_ARTIFACT",
        "FORMAL_REVIEW",
        "ADVISORY_ANALYSIS",
        "DEPLOYMENT_RECORD",
        "OBSERVATION_RECORD",
        "INTAKE_SAFE_METADATA",
    }
)
_MUTABLE_POINTER_MEDIA = frozenset({"PR_COMMENT", "PR_METADATA", "MODEL_TEXT"})


class EvidenceViolation(ValueError):  # noqa: N818 — deliberate domain violation
    """Evidence is absent, mutable, stale, tampered, or bound to another subject."""


@dataclass(frozen=True)
class EnvironmentFingerprint:
    os: str
    architecture: str
    runtime: str
    dependency_digest: str
    container_digest: str
    configuration_digest: str
    hardware_class: str = "not-applicable"

    @property
    def digest(self) -> str:
        return canonical_digest(asdict(self))


@dataclass(frozen=True)
class ToolIdentity:
    name: str
    version: str
    executable_digest: str
    policy_digest: str

    @property
    def digest(self) -> str:
        return canonical_digest(asdict(self))


@dataclass(frozen=True)
class EvidenceProducer:
    producer_id: str
    authority_digest: str
    execution_mode: str

    def __post_init__(self) -> None:
        if self.execution_mode not in _EXECUTION_MODES:
            raise EvidenceViolation(f"unsupported execution mode: {self.execution_mode}")


@dataclass(frozen=True)
class EvidenceSubject:
    """Every available immutable subject in the delivery chain.

    Empty fields are allowed before their stages exist.  Stage profiles declare which
    fields must be present.  Git object IDs and content digests intentionally remain
    distinct, even when both happen to use hexadecimal encodings.
    """

    intake_lineage_digest: str = ""
    contract_digest: str = ""
    repository_snapshot_digest: str = ""
    architecture_digest: str = ""
    test_plan_digest: str = ""
    protected_base_sha: str = ""
    pr_head_sha: str = ""
    prospective_merge_tree_digest: str = ""
    observed_merge_sha: str = ""
    observed_merge_tree_digest: str = ""
    artifact_digest: str = ""
    configuration_digest: str = ""
    deployment_digest: str = ""
    observation_digest: str = ""

    @property
    def digest(self) -> str:
        return canonical_digest(asdict(self))


@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    evidence_class: str
    stage: str
    subject_digest: str
    result: str
    producer: EvidenceProducer
    tool: ToolIdentity
    environment: EnvironmentFingerprint
    invocation: tuple[str, ...]
    output_digest: str
    observed_at: str
    retention_class: str
    authentication_evidence_digest: str
    attestation_format: str
    medium: str = "ATTESTATION"
    committed_script_digest: str = ""
    expires_at: str = ""
    payload_ref: str = ""
    executed_count: int = 0
    passed_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0

    def __post_init__(self) -> None:
        if self.result not in _RESULTS:
            raise EvidenceViolation(f"unsupported evidence result: {self.result}")
        if self.medium not in _IMMUTABLE_MEDIA | _MUTABLE_POINTER_MEDIA:
            raise EvidenceViolation(f"unsupported evidence medium: {self.medium}")
        if (
            min(
                self.executed_count,
                self.passed_count,
                self.failed_count,
                self.skipped_count,
            )
            < 0
        ):
            raise EvidenceViolation("execution counts cannot be negative")

    @property
    def digest(self) -> str:
        return canonical_digest(asdict(self))


@dataclass(frozen=True)
class StageProfile:
    name: str
    required_classes: tuple[str, ...]
    required_subject_fields: tuple[str, ...]
    environment_sensitive_classes: tuple[str, ...] = ()
    required_any_groups: tuple[tuple[str, ...], ...] = ()


STAGE_PROFILES: Mapping[str, StageProfile] = MappingProxyType(
    {
        "contract_admission": StageProfile(
            "contract_admission",
            ("intake_reservation", "intake_disposition"),
            ("intake_lineage_digest",),
            required_any_groups=(("intake_receipt", "receipt_finalization_failure"),),
        ),
        "pre_code": StageProfile(
            "pre_code",
            ("repository_snapshot", "architecture", "test_plan", "meaningful_red"),
            (
                "contract_digest",
                "repository_snapshot_digest",
                "architecture_digest",
                "test_plan_digest",
            ),
            ("meaningful_red",),
        ),
        "candidate_review": StageProfile(
            "candidate_review",
            ("candidate", "required_checks", "advisory_review", "finding_inventory"),
            ("protected_base_sha", "pr_head_sha", "prospective_merge_tree_digest"),
            ("required_checks", "advisory_review"),
        ),
        "merge_admission": StageProfile(
            "merge_admission",
            (
                "candidate",
                "required_checks",
                "advisory_review",
                "formal_review",
                "finding_inventory",
                "merge_gate",
            ),
            ("protected_base_sha", "pr_head_sha", "prospective_merge_tree_digest"),
            ("required_checks", "advisory_review", "merge_gate"),
        ),
        "staging": StageProfile(
            "staging",
            ("observed_merge", "artifact", "configuration", "finding_inventory"),
            (
                "observed_merge_sha",
                "observed_merge_tree_digest",
                "artifact_digest",
                "configuration_digest",
            ),
            ("artifact", "configuration"),
        ),
        "completion": StageProfile(
            "completion",
            (
                "observed_merge",
                "artifact",
                "configuration",
                "deployment",
                "live_observation",
                "rollback_readiness",
                "final_head_attestation",
            ),
            (
                "pr_head_sha",
                "prospective_merge_tree_digest",
                "observed_merge_sha",
                "observed_merge_tree_digest",
                "artifact_digest",
                "configuration_digest",
                "deployment_digest",
                "observation_digest",
            ),
            (
                "artifact",
                "configuration",
                "deployment",
                "live_observation",
                "rollback_readiness",
                "final_head_attestation",
            ),
        ),
        "rollback_incident": StageProfile(
            "rollback_incident",
            ("rollback_execution", "restored_state", "rto_rpo"),
            ("observed_merge_sha", "artifact_digest", "configuration_digest"),
            ("rollback_execution", "restored_state", "rto_rpo"),
        ),
    }
)


@dataclass(frozen=True)
class EvidenceManifest:
    schema_version: str
    profile: str
    subject: EvidenceSubject
    policy_digest: str
    created_at: str
    items: tuple[EvidenceItem, ...]
    supersedes_digest: str = ""

    @property
    def digest(self) -> str:
        return canonical_digest(asdict(self))


@dataclass(frozen=True)
class SealedEvidenceBundle:
    manifest: EvidenceManifest
    bundle_digest: str


@dataclass(frozen=True)
class EvidenceValidation:
    valid: bool
    completeness: float
    reasons: tuple[str, ...]
    present_classes: tuple[str, ...]
    missing_classes: tuple[str, ...]


def _timestamp(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceViolation(f"{label} is not an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise EvidenceViolation(f"{label} must include a timezone")
    return parsed


def _valid_subject_field(name: str, value: str) -> bool:
    if name.endswith("_sha"):
        return bool(_SHA.fullmatch(value))
    return bool(_DIGEST.fullmatch(value))


def verify_manifest(
    manifest: EvidenceManifest,
    *,
    expected_profile: str | None = None,
    expected_subject: EvidenceSubject | None = None,
    expected_policy_digest: str | None = None,
    expected_environment: EnvironmentFingerprint | None = None,
    as_of: str | None = None,
) -> EvidenceValidation:
    reasons: list[str] = []
    profile = STAGE_PROFILES.get(manifest.profile)
    if profile is None:
        return EvidenceValidation(False, 0.0, ("unknown stage profile",), (), ())
    if expected_profile is not None and manifest.profile != expected_profile:
        reasons.append("wrong stage profile")
    if expected_subject is not None and manifest.subject != expected_subject:
        reasons.append("wrong exact subject")
    if expected_policy_digest is not None and manifest.policy_digest != expected_policy_digest:
        reasons.append("policy digest changed")
    if not _DIGEST.fullmatch(manifest.policy_digest):
        reasons.append("policy digest is malformed")
    if manifest.supersedes_digest and not _DIGEST.fullmatch(manifest.supersedes_digest):
        reasons.append("superseded bundle digest is malformed")
    try:
        created = _timestamp(manifest.created_at, "created_at")
        current = _timestamp(as_of, "as_of") if as_of else created
    except EvidenceViolation as exc:
        reasons.append(str(exc))
        current = datetime.max.astimezone()

    for field_name in profile.required_subject_fields:
        value = str(getattr(manifest.subject, field_name))
        if not _valid_subject_field(field_name, value):
            reasons.append(f"required subject field {field_name} is missing or malformed")

    seen_ids: dict[str, str] = {}
    present: set[str] = set()
    for item in manifest.items:
        previous = seen_ids.get(item.evidence_id)
        if previous is not None:
            reasons.append(
                "duplicate evidence id" if previous == item.digest else "conflicting evidence id"
            )
        seen_ids[item.evidence_id] = item.digest
        if item.stage != manifest.profile:
            reasons.append(f"{item.evidence_id}: wrong stage")
        if item.subject_digest != manifest.subject.digest:
            reasons.append(f"{item.evidence_id}: wrong subject digest")
        if item.result != "PASS":
            reasons.append(f"{item.evidence_id}: result is {item.result}")
        if item.medium in _MUTABLE_POINTER_MEDIA:
            reasons.append(f"{item.evidence_id}: mutable {item.medium} is only a pointer")
        if (
            not item.producer.producer_id
            or not _DIGEST.fullmatch(item.producer.authority_digest)
            or not _DIGEST.fullmatch(item.authentication_evidence_digest)
            or not item.attestation_format
        ):
            reasons.append(f"{item.evidence_id}: producer attestation is absent or malformed")
        if not item.invocation and not _DIGEST.fullmatch(item.committed_script_digest):
            reasons.append(f"{item.evidence_id}: executable invocation or script digest is absent")
        if not item.tool.name or not item.tool.version:
            reasons.append(f"{item.evidence_id}: tool identity/version is absent")
        if not _DIGEST.fullmatch(item.tool.executable_digest):
            reasons.append(f"{item.evidence_id}: executable digest is malformed")
        if not _DIGEST.fullmatch(item.tool.policy_digest):
            reasons.append(f"{item.evidence_id}: tool policy digest is malformed")
        if not _DIGEST.fullmatch(item.output_digest):
            reasons.append(f"{item.evidence_id}: output digest is malformed")
        if item.evidence_class == "required_checks" and (
            item.executed_count <= 0
            or item.passed_count != item.executed_count
            or item.failed_count
            or item.skipped_count
        ):
            reasons.append(f"{item.evidence_id}: checks were missing, failed, or skipped")
        if item.evidence_class == "meaningful_red" and (
            item.executed_count <= 0 or item.failed_count <= 0 or item.skipped_count
        ):
            reasons.append(f"{item.evidence_id}: meaningful assertion red is not proven")
        try:
            observed = _timestamp(item.observed_at, f"{item.evidence_id}.observed_at")
            if observed > current:
                reasons.append(f"{item.evidence_id}: observation is from the future")
            if item.expires_at and current >= _timestamp(
                item.expires_at, f"{item.evidence_id}.expires_at"
            ):
                reasons.append(f"{item.evidence_id}: evidence is stale")
        except EvidenceViolation as exc:
            reasons.append(str(exc))
        if item.evidence_class in profile.environment_sensitive_classes:
            if expected_environment is None:
                reasons.append(f"{item.evidence_id}: expected environment is not supplied")
            elif item.environment != expected_environment:
                reasons.append(f"{item.evidence_id}: execution environment is inapplicable")
        present.add(item.evidence_class)

    missing = tuple(sorted(set(profile.required_classes) - present))
    reasons.extend(f"missing required evidence class: {name}" for name in missing)
    missing_groups = tuple(
        group for group in profile.required_any_groups if not set(group).intersection(present)
    )
    reasons.extend(
        "missing one required evidence class from: " + ", ".join(group) for group in missing_groups
    )
    total_requirements = len(profile.required_classes) + len(profile.required_any_groups)
    satisfied_requirements = total_requirements - len(missing) - len(missing_groups)
    completeness = satisfied_requirements / total_requirements if total_requirements else 1.0
    return EvidenceValidation(
        not reasons,
        round(completeness, 4),
        tuple(reasons),
        tuple(sorted(present)),
        missing,
    )


def seal_manifest(
    manifest: EvidenceManifest,
    *,
    expected_environment: EnvironmentFingerprint | None = None,
    as_of: str | None = None,
) -> SealedEvidenceBundle:
    validation = verify_manifest(
        manifest,
        expected_profile=manifest.profile,
        expected_subject=manifest.subject,
        expected_policy_digest=manifest.policy_digest,
        expected_environment=expected_environment,
        as_of=as_of,
    )
    if not validation.valid:
        raise EvidenceViolation("; ".join(validation.reasons))
    return SealedEvidenceBundle(manifest, manifest.digest)


def verify_bundle(
    bundle: SealedEvidenceBundle,
    *,
    expected_profile: str,
    expected_subject: EvidenceSubject,
    expected_policy_digest: str,
    expected_environment: EnvironmentFingerprint | None = None,
    as_of: str | None = None,
) -> EvidenceValidation:
    validation = verify_manifest(
        bundle.manifest,
        expected_profile=expected_profile,
        expected_subject=expected_subject,
        expected_policy_digest=expected_policy_digest,
        expected_environment=expected_environment,
        as_of=as_of,
    )
    if bundle.bundle_digest != bundle.manifest.digest:
        return EvidenceValidation(
            False,
            validation.completeness,
            ("sealed bundle digest mismatch", *validation.reasons),
            validation.present_classes,
            validation.missing_classes,
        )
    return validation


class ImmutableEvidenceStore:
    """Append-only content store with idempotent event identities and crash-safe writes."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.objects = self.root / "objects"
        self.events = self.root / "evidence-events.jsonl"
        self.lock = self.root / "evidence.lock"

    def append(self, bundle: SealedEvidenceBundle, *, event_id: str) -> str:
        if not event_id:
            raise EvidenceViolation("event_id is required")
        if bundle.bundle_digest != bundle.manifest.digest:
            raise EvidenceViolation("cannot store a tampered bundle")
        self.objects.mkdir(parents=True, exist_ok=True)
        object_name = bundle.bundle_digest.replace(":", "-")
        object_path = self.objects / f"{object_name}.json"
        payload = jsonable(bundle.manifest)
        event = {
            "event_id": event_id,
            "bundle_digest": bundle.bundle_digest,
            "profile": bundle.manifest.profile,
            "subject_digest": bundle.manifest.subject.digest,
        }
        self.lock.parent.mkdir(parents=True, exist_ok=True)
        with self.lock.open("a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            prior_events = self.read_events()
            prior = next((item for item in prior_events if item["event_id"] == event_id), None)
            if prior is not None:
                if prior != event:
                    raise EvidenceViolation("event identity was reused with different evidence")
                return bundle.bundle_digest
            if object_path.exists():
                if json.loads(object_path.read_text()) != payload:
                    raise EvidenceViolation("content address contains different bytes")
            else:
                atomic_write_json(object_path, payload)
            with self.events.open("a") as stream:
                stream.write(json.dumps(event, sort_keys=True) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            return bundle.bundle_digest

    def read_events(self) -> list[dict[str, str]]:
        if not self.events.exists():
            return []
        return [
            {str(key): str(value) for key, value in json.loads(line).items()}
            for line in self.events.read_text().splitlines()
            if line.strip()
        ]
