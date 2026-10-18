"""Protected built-in capability profiles for the two admitted barebones starters.

These are deliberately narrow execution envelopes, not a generic product registry.
The approval and acceptance compiler retain ownership of contract meaning.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from pmpe.barebones import Template, default_template
from pmpe.contracts.canonical import canonical_digest
from pmpe.core_harness import CoreHarnessPlan
from pmpe.task_tracker_harness import REGISTRY_NAME, fixed_template, registry_identity


class ProductProfileError(ValueError):
    """The requested built-in profile does not cover the approved contract."""


@dataclass(frozen=True)
class RequiredCheck:
    check_id: str
    stage: str
    adapter: str
    command: tuple[str, ...]
    tool_version: str
    evidence: str
    required: bool = True


@dataclass(frozen=True)
class CompiledProductProfile:
    profile_id: str
    profile_version: str
    contract_digest: str
    template_version: str
    template_digest: str
    harness_digest: str | None
    capability_ids: tuple[str, ...]
    criterion_ids: tuple[str, ...]
    checks: tuple[RequiredCheck, ...]
    manifest: dict[str, Any]
    manifest_digest: str


_TRACKER_CAPABILITIES = (
    "task.complete",
    "task.create",
    "task.filter",
    "task.persist",
    "task.repeat",
    "task.validate",
)
_TRACKER_CRITERIA = tuple(f"AC-{number:03d}" for number in range(1, 15))


def _checks() -> tuple[RequiredCheck, ...]:
    """Trusted adapters are fixed; unavailable tools never become inferred PASS."""

    return (
        RequiredCheck(
            "python-syntax",
            "candidate",
            "supervisor.python_compile/v1",
            (),
            "python-stdlib",
            "sealed source bytes and syntax result",
        ),
        RequiredCheck(
            "source-security",
            "candidate",
            "supervisor.source_security/v1",
            (),
            "pmpe-static-v1",
            "trusted scanner findings for sealed candidate",
        ),
        RequiredCheck(
            "functional-acceptance",
            "candidate",
            "barebones.fixed_observer/v1",
            (),
            "barebones-observer-v1",
            "all approved criterion observations and response digests",
        ),
        RequiredCheck(
            "type-analysis",
            "delivery",
            "unavailable",
            (),
            "unavailable",
            "trusted type-check command and output for sealed candidate",
        ),
        RequiredCheck(
            "lint",
            "delivery",
            "unavailable",
            (),
            "unavailable",
            "trusted lint command and output for sealed candidate",
        ),
        RequiredCheck(
            "dependency-security",
            "delivery",
            "unavailable",
            (),
            "unavailable",
            "locked dependency inventory and trusted advisory scan",
        ),
        RequiredCheck(
            "clean-install",
            "delivery",
            "unavailable",
            (),
            "unavailable",
            "clean supported environment installation and start trace",
        ),
        RequiredCheck(
            "release-target",
            "delivery",
            "unavailable",
            (),
            "unavailable",
            "approved target and independently observed customer journey",
        ),
    )


def _criterion_ids(contract: Mapping[str, Any]) -> tuple[str, ...]:
    raw = contract.get("acceptance_criteria")
    if isinstance(raw, Mapping):
        if not all(isinstance(item, str) for item in raw):
            raise ProductProfileError("acceptance criterion IDs are malformed")
        ids = tuple(sorted(raw))
    elif isinstance(raw, list) and all(isinstance(item, Mapping) for item in raw):
        ids = tuple(item.get("id") for item in raw)
    else:
        raise ProductProfileError("acceptance criteria have no supported profile shape")
    if any(not isinstance(item, str) or not item for item in ids) or len(ids) != len(set(ids)):
        raise ProductProfileError("acceptance criterion IDs are missing or duplicated")
    return ids


def _capabilities(contract: Mapping[str, Any]) -> tuple[str, ...]:
    raw = contract.get("functional_requirements")
    if not isinstance(raw, list) or not all(isinstance(item, Mapping) for item in raw):
        raise ProductProfileError("task-tracker functional requirements are unavailable")
    values = [item.get("capability") for item in raw]
    if any(not isinstance(item, str) or not item for item in values):
        raise ProductProfileError("task-tracker capability is missing")
    return tuple(sorted(values))


def compile_product_profile(
    profile_id: str,
    *,
    contract: Mapping[str, Any],
    template: Template,
    harness_plan: CoreHarnessPlan | None,
) -> CompiledProductProfile:
    """Bind a protected profile to existing exact template/harness admission.

    REV_PROFILE_ADMISSION: no provider call or candidate execution may precede this
    check. The manifest intentionally makes missing delivery adapters explicit.
    """

    if profile_id == "auto":
        profile_id = (
            "pmos-task-tracker-v1" if template.version == REGISTRY_NAME else "barebones-health-v1"
        )
    if profile_id == "barebones-health-v1":
        expected = default_template()
        if template.version != expected.version or canonical_digest(
            asdict(template)
        ) != canonical_digest(asdict(expected)):
            raise ProductProfileError("health profile requires exact barebones-1 template")
        if harness_plan is not None or contract.get("required_harness_digest") is not None:
            raise ProductProfileError("health profile cannot bind a core harness")
        criteria = _criterion_ids(contract)
        if not criteria or not isinstance(contract.get("functional_requirements"), Mapping):
            raise ProductProfileError("health profile requires health criteria")
        raw = contract["acceptance_criteria"]
        health_criteria = raw.values() if isinstance(raw, Mapping) else raw
        for criterion in health_criteria:
            when = criterion.get("when") if isinstance(criterion, Mapping) else None
            if not isinstance(when, Mapping) or when.get("action") != "health":
                raise ProductProfileError("health profile requires the health observer")
        capability_ids: tuple[str, ...] = ("e1.health",)
        stack, target, harness_digest = "python-stdlib-function", "local-function", None
        entrypoint: list[str] | None = None
        integrations: list[str] = []
        configuration_schema: dict[str, Any] = {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }
    elif profile_id == "pmos-task-tracker-v1":
        expected = fixed_template()
        if template.version != expected.version or canonical_digest(
            asdict(template)
        ) != canonical_digest(asdict(expected)):
            raise ProductProfileError("task-tracker profile requires exact fixed template")
        harness_digest = harness_plan.mapping_digest if harness_plan is not None else None
        if not harness_digest or contract.get("required_harness_digest") != harness_digest:
            raise ProductProfileError(
                "task-tracker profile requires the matching bound core harness"
            )
        criteria = _criterion_ids(contract)
        if criteria != _TRACKER_CRITERIA:
            raise ProductProfileError("task-tracker criterion envelope is unsupported")
        capability_ids = _capabilities(contract)
        gaps = sorted(set(capability_ids) - set(_TRACKER_CAPABILITIES))
        if gaps:
            raise ProductProfileError("unsupported task-tracker capabilities: " + ", ".join(gaps))
        if capability_ids != _TRACKER_CAPABILITIES:
            raise ProductProfileError("task-tracker capability envelope is incomplete")
        raw = contract["acceptance_criteria"]
        for criterion in raw:
            if not isinstance(criterion, Mapping):
                raise ProductProfileError("task-tracker criterion is malformed")
            when = criterion.get("when")
            if when is None:
                if criterion.get("measure") != "task_tracker.missing_acknowledged_records":
                    raise ProductProfileError("task-tracker measure is unsupported")
            elif not isinstance(when, Mapping) or when.get("action") != "task_tracker.observe":
                raise ProductProfileError("task-tracker action is unsupported")
        stack, target = "python-stdlib-cli-json", "local-cli"
        entrypoint = ["python", "product.py", "--store", "<local-path>"]
        integrations = ["local-filesystem"]
        configuration_schema = {
            "type": "object",
            "properties": {"store": {"type": "string", "description": "local task store path"}},
            "required": ["store"],
            "additionalProperties": False,
        }
    else:
        raise ProductProfileError(f"unsupported built-in product profile: {profile_id}")

    checks = _checks()
    manifest: dict[str, Any] = {
        "schema_version": "peos-product-profile/v1",
        "profile_id": profile_id,
        "profile_version": "1.0.0",
        "stack": stack,
        "delivery_target": target,
        "entrypoint": entrypoint,
        "configuration_schema": configuration_schema,
        "starter_file_digests": {
            path: "sha256:" + hashlib.sha256(source.encode("utf-8")).hexdigest()
            for path, source in sorted(template.files.items())
        },
        "permitted_dependencies": ["python-stdlib"],
        "lockfiles": [],
        "runtime_integrations": integrations,
        "contract_digest": canonical_digest(contract),
        "template_version": template.version,
        "template_digest": canonical_digest(asdict(template)),
        "harness_digest": harness_digest,
        "registry": registry_identity() if profile_id == "pmos-task-tracker-v1" else None,
        "capability_ids": list(capability_ids),
        "criterion_ids": list(criteria),
        "checks": [{**asdict(item), "command": list(item.command)} for item in checks],
    }
    return CompiledProductProfile(
        profile_id,
        "1.0.0",
        manifest["contract_digest"],
        template.version,
        manifest["template_digest"],
        harness_digest,
        capability_ids,
        criteria,
        checks,
        manifest,
        canonical_digest(manifest),
    )
