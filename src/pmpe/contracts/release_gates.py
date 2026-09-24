"""Explicit mechanical bindings for binary release gates; never interpret prose."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from pmpe.contracts.gate_declarations import validate_gate_declaration_placement
from pmpe.contracts.process_gate_bindings import validate_process_binding


@dataclass(frozen=True)
class CompiledReleaseGate:
    gate_id: str
    acceptance_criterion_refs: tuple[str, ...] = ()
    binding: Mapping[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        if self.binding is not None:
            return {"gate_id": self.gate_id, "binding": dict(self.binding)}
        return {
            "gate_id": self.gate_id,
            "acceptance_criterion_refs": self.acceptance_criterion_refs,
        }


def compile_release_gates(
    contract: Mapping[str, Any],
    *,
    criterion_ids: frozenset[str],
    diagnostic: Callable[[str, str, str], None],
) -> tuple[CompiledReleaseGate, ...]:
    """Resolve declared conjunctions against executable criteria, failing closed."""

    validate_gate_declaration_placement(contract, diagnostic)
    quality = contract.get("quality_assurance", {})
    if not isinstance(quality, Mapping):
        return ()
    native = "binary_release_gates" in contract
    canonical = "release_gates" in quality
    if native and canonical:
        diagnostic(
            "RELEASE_GATE_DECLARATIONS_CONFLICT",
            "contract",
            "declare binary_release_gates or quality_assurance.release_gates, not both",
        )
        return ()
    if not native and not canonical:
        return ()
    source = "binary_release_gates" if native else "quality_assurance.release_gates"
    raw = contract.get("binary_release_gates") if native else quality["release_gates"]
    entries: list[tuple[Any, Any]]
    if isinstance(raw, Mapping):
        entries = list(raw.items())
    elif native and isinstance(raw, list):
        entries = [(item.get("id") if isinstance(item, Mapping) else None, item) for item in raw]
    else:
        diagnostic("RELEASE_GATE_COLLECTION_INVALID", source, "requires ID-keyed gate objects")
        return ()
    if not entries:
        diagnostic("RELEASE_GATE_COLLECTION_EMPTY", source, "a declared gate collection is empty")
        return ()

    seen: set[str] = set()
    compiled: list[CompiledReleaseGate] = []
    allowed = {"id", "description", "evidence_expectation", "acceptance_criterion_refs", "binding"}
    for index, (gate_id, item) in enumerate(entries):
        if not isinstance(gate_id, str) or not gate_id.strip() or gate_id != gate_id.strip():
            diagnostic(
                "RELEASE_GATE_ID_INVALID",
                f"{source}[{index}]",
                "requires a non-empty ID without surrounding whitespace",
            )
            continue
        if gate_id in seen:
            diagnostic("RELEASE_GATE_ID_DUPLICATE", gate_id, "release gate ID is duplicated")
            continue
        seen.add(gate_id)
        if not isinstance(item, Mapping) or item.get("id", gate_id) != gate_id:
            diagnostic("RELEASE_GATE_INVALID", gate_id, "requires an object with a matching ID")
            continue
        if set(item) - allowed:
            diagnostic("RELEASE_GATE_UNSUPPORTED", gate_id, "contains unsupported gate fields")
            continue
        if not isinstance(item.get("description"), str) or not item["description"].strip():
            diagnostic("RELEASE_GATE_INVALID", gate_id, "requires a non-empty description")
            continue
        if "evidence_expectation" in item and (
            not isinstance(item["evidence_expectation"], str)
            or not item["evidence_expectation"].strip()
        ):
            diagnostic("RELEASE_GATE_INVALID", gate_id, "evidence_expectation must be text")
            continue
        if "binding" in item:
            if "acceptance_criterion_refs" in item:
                diagnostic("RELEASE_GATE_BINDING_INVALID", gate_id, "bind exactly one gate kind")
                continue
            try:
                binding = validate_process_binding(item["binding"], criterion_ids)
            except ValueError as exc:
                diagnostic("RELEASE_GATE_BINDING_INVALID", gate_id, str(exc))
                continue
            compiled.append(CompiledReleaseGate(gate_id, binding=binding))
            continue
        refs = item.get("acceptance_criterion_refs")
        if not isinstance(refs, list) or not refs:
            diagnostic(
                "RELEASE_GATE_UNBOUND",
                gate_id,
                "requires explicit non-empty acceptance_criterion_refs; prose is not executable",
            )
            continue
        if any(not isinstance(ref, str) or not ref.strip() for ref in refs) or len(refs) != len(
            set(refs)
        ):
            diagnostic("RELEASE_GATE_BINDING_INVALID", gate_id, "requires unique criterion IDs")
            continue
        unknown = sorted(set(refs) - criterion_ids)
        if unknown:
            diagnostic(
                "RELEASE_GATE_CRITERION_UNKNOWN",
                gate_id,
                "references criteria without executable checks: " + ", ".join(unknown),
            )
            continue
        compiled.append(CompiledReleaseGate(gate_id, tuple(sorted(refs))))
    return tuple(sorted(compiled, key=lambda gate: gate.gate_id))
