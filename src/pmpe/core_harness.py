"""Digest-bound admission of PMOS-derived core release conditions.

Admission binds the complete required-condition map to a publisher contract.
It does not turn a condition description or untrusted status into proof that a
gate passed. The current runner has no trusted executor for every core stage.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pmpe.contracts.canonical import canonical_digest
from pmpe.task_tracker_harness import registry_identity

_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
_REQUIRED_STAGES = frozenset(
    {
        "product_acceptance",
        "meaningful_red_and_regressions",
        "approval_bound_integrity",
        "build_provenance",
        "limitations_report",
    }
)
_MAPPING_FIELDS = frozenset(
    {
        "schema_version",
        "source_repository",
        "source_commit",
        "source_raw_sha256",
        "source_contract_digest",
        "source_receipt_digest",
        "mapping_approval_source",
        "mapping_approval_scope",
        "criterion_ids",
        "required_conditions",
        "registry",
    }
)
_CONDITION_FIELDS = frozenset(
    {"condition_id", "description", "harness_stage", "required", "criterion_refs"}
)


class CoreHarnessInvalidError(ValueError):
    """A required core condition mapping is absent or inconsistent."""


@dataclass(frozen=True)
class CoreCondition:
    condition_id: str
    description: str
    stage: str
    criterion_refs: tuple[str, ...]


@dataclass(frozen=True)
class CoreHarnessPlan:
    mapping_digest: str
    conditions: tuple[CoreCondition, ...]

    def unproven_conditions(self) -> tuple[str, ...]:
        """No static mapping or compiler result is a trusted runtime gate proof."""

        return tuple(item.condition_id for item in self.conditions)

    def observed_stages(
        self, acceptance_gates: Sequence[Mapping[str, Any]]
    ) -> tuple[dict[str, str], ...]:
        """Report checked product cases without inventing process-gate proof."""

        observed = []
        for condition in self.conditions:
            if condition.stage == "product_acceptance":
                gate = next(
                    (
                        item
                        for item in acceptance_gates
                        if item.get("gate_id") == condition.condition_id
                    ),
                    None,
                )
                raw_status = gate.get("status") if gate is not None else None
                status = raw_status if raw_status in {"PASS", "FAIL"} else "BLOCKED"
                reason = "candidate_response_only" if status == "PASS" else "acceptance_incomplete"
            else:
                status = "BLOCKED"
                reason = "required_independent_proof_missing"
            observed.append(
                {
                    "condition_id": condition.condition_id,
                    "stage": condition.stage,
                    "status": status,
                    "reason": reason,
                }
            )
        return tuple(observed)


def compile_required_harness(
    contract: Mapping[str, Any], mapping: Mapping[str, Any] | None
) -> CoreHarnessPlan | None:
    """Require the complete mapped packet when its digest is in the contract."""

    required_digest = contract.get("required_harness_digest")
    if required_digest is None:
        if mapping is not None:
            raise CoreHarnessInvalidError("contract does not bind a core harness mapping")
        return None
    if not isinstance(required_digest, str) or _SHA256.fullmatch(required_digest) is None:
        raise CoreHarnessInvalidError("contract required_harness_digest is malformed")
    if mapping is None:
        raise CoreHarnessInvalidError("required core harness mapping is missing")
    if (
        set(mapping) != _MAPPING_FIELDS
        or mapping.get("schema_version") != "pmos-core-harness-mapping-v1"
    ):
        raise CoreHarnessInvalidError("core harness mapping shape is unsupported")
    if canonical_digest(dict(mapping)) != required_digest:
        raise CoreHarnessInvalidError("core harness mapping differs from contract digest")
    if mapping.get("registry") != registry_identity():
        raise CoreHarnessInvalidError(
            "core harness registry identity differs from reviewed mapping"
        )

    criteria = contract.get("acceptance_criteria")
    gates = contract.get("binary_release_gates")
    if not isinstance(criteria, list) or not isinstance(gates, list):
        raise CoreHarnessInvalidError("mapped contract criteria or acceptance gate is missing")
    criterion_ids = [item.get("id") if isinstance(item, Mapping) else None for item in criteria]
    if (
        not criterion_ids
        or any(not isinstance(item, str) or not item for item in criterion_ids)
        or len(set(criterion_ids)) != len(criterion_ids)
        or mapping.get("criterion_ids") != criterion_ids
    ):
        raise CoreHarnessInvalidError("core harness criteria do not match the contract")
    raw_conditions = mapping.get("required_conditions")
    if not isinstance(raw_conditions, list) or len(raw_conditions) != len(_REQUIRED_STAGES):
        raise CoreHarnessInvalidError("all five core release conditions are required")
    stages: set[str] = set()
    ids: set[str] = set()
    conditions: list[CoreCondition] = []
    for raw in raw_conditions:
        if not isinstance(raw, Mapping) or set(raw) != _CONDITION_FIELDS:
            raise CoreHarnessInvalidError("core release condition shape is unsupported")
        condition_id = raw["condition_id"]
        description = raw["description"]
        stage = raw["harness_stage"]
        refs = raw["criterion_refs"]
        if (
            not isinstance(condition_id, str)
            or not condition_id
            or condition_id in ids
            or not isinstance(description, str)
            or not description.strip()
            or not isinstance(stage, str)
            or stage not in _REQUIRED_STAGES
            or stage in stages
            or raw["required"] is not True
            or not isinstance(refs, list)
            or any(not isinstance(ref, str) for ref in refs)
        ):
            raise CoreHarnessInvalidError("core release condition is missing or invalid")
        if stage == "product_acceptance":
            if refs != criterion_ids:
                raise CoreHarnessInvalidError("acceptance condition must bind every approved case")
        elif refs:
            raise CoreHarnessInvalidError("process condition cannot invent acceptance references")
        ids.add(condition_id)
        stages.add(stage)
        conditions.append(CoreCondition(condition_id, description, stage, tuple(refs)))
    if stages != _REQUIRED_STAGES:
        raise CoreHarnessInvalidError("core release condition stages are incomplete")
    acceptance = next(item for item in conditions if item.stage == "product_acceptance")
    if gates != [
        {
            "id": acceptance.condition_id,
            "description": acceptance.description,
            "acceptance_criterion_refs": list(acceptance.criterion_refs),
        }
    ]:
        raise CoreHarnessInvalidError("mapped acceptance gate differs from required condition")
    return CoreHarnessPlan(required_digest, tuple(conditions))
