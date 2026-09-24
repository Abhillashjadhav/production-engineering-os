"""Acyclic outer approval packet: externally pinned, then guarded with sources."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from pmpe.contracts.authoring import build_contract_draft
from pmpe.contracts.canonical import canonical_digest, strict_loads
from pmpe.domain.errors import ContractViolation, SpecError
from pmpe.process_sources import raw_digest

if TYPE_CHECKING:
    from pmpe.contracts.acceptance import AcceptanceBuildPlan
    from pmpe.process_gate_inputs import ProcessGateInputs


def validate_approval_packet(
    inputs: ProcessGateInputs,
    plan: AcceptanceBuildPlan,
    *,
    receipt_bytes: bytes | None,
    approval_verified: bool,
) -> tuple[dict[str, Path], dict[str, str]]:
    """The external expected digest is an operator anchor, not a signature."""
    supplied = (
        bool(inputs.approval_freeze),
        bool(inputs.approval_paths),
        bool(inputs.approval_freeze_expected_digest),
    )
    if not any(supplied):
        return {}, {}
    if not all(supplied) or not approval_verified or receipt_bytes is None:
        raise ValueError("approval packet requires verified receipt and complete outer inputs")
    if raw_digest(inputs.approval_freeze) != inputs.approval_freeze_expected_digest:
        raise ValueError("approval packet differs from externally pinned digest")
    freeze = strict_loads(inputs.approval_freeze, "application/json")
    if (
        not isinstance(freeze, dict)
        or set(freeze) != {"schema_version", "artifacts"}
        or freeze["schema_version"] != "1"
    ):
        raise ValueError("approval packet manifest shape is invalid")
    expected = freeze["artifacts"]
    required = {"contract", "receipt", "draft", "plan", "source_manifest", "publisher_input"}
    if (
        not isinstance(expected, Mapping)
        or not required.issubset(expected)
        or set(expected) != set(inputs.approval_paths)
    ):
        raise ValueError("approval packet omits required artifacts or exact path inventory")
    payloads: dict[str, bytes] = {}
    for key, path in inputs.approval_paths.items():
        if path.is_symlink() or not path.is_file():
            raise ValueError("approval packet artifact missing or replaced by symlink")
        payloads[key] = path.read_bytes()
        if raw_digest(payloads[key]) != expected[key]:
            raise ValueError("approval packet artifact digest mismatch: " + key)
    contract = strict_loads(payloads["contract"], "application/json")
    receipt = strict_loads(payloads["receipt"], "application/json")
    proposed_plan = strict_loads(payloads["plan"], "application/json")
    draft = strict_loads(payloads["draft"], "application/json")
    publisher_input = strict_loads(payloads["publisher_input"], "application/json")
    if (
        not isinstance(contract, dict)
        or contract.get("contract_status") != "APPROVED"
        or canonical_digest(contract) != plan.contract_digest
    ):
        raise ValueError("approval packet contract differs from this approved run")
    if not isinstance(publisher_input, dict) or canonical_digest(publisher_input) != contract.get(
        "source_digest"
    ):
        raise ValueError("approval packet publisher input differs from contract source")
    try:
        published = build_contract_draft(publisher_input)
    except (SpecError, ContractViolation) as exc:
        raise ValueError("approval packet publisher input is invalid") from exc
    if published.draft is None or canonical_digest(published.draft) != canonical_digest(draft):
        raise ValueError("approval packet publisher cannot reconstruct reviewed draft")
    if (
        payloads["receipt"] != receipt_bytes
        or not isinstance(receipt, dict)
        or canonical_digest(draft) != receipt.get("draft_digest")
    ):
        raise ValueError("approval packet receipt/draft differs from this approved run")
    if (
        canonical_digest(proposed_plan) != canonical_digest(plan.as_dict())
        or payloads["source_manifest"] != inputs.source_manifest
    ):
        raise ValueError("approval packet plan/source manifest differs from this run")
    return (
        {"approval/" + key: path for key, path in inputs.approval_paths.items()},
        {"approval/" + key: str(value) for key, value in expected.items()},
    )
