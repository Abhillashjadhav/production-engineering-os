"""Release-gate evidence derives only from explicit mechanical check outcomes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from pmpe.contracts.release_gates import CompiledReleaseGate

if TYPE_CHECKING:
    from pmpe.barebones import Finding


def release_gate_results(
    gates: Sequence[CompiledReleaseGate],
    criterion_results: Mapping[str, tuple[Finding, ...]],
    *,
    process_results: Mapping[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """A missing result never means PASS, including an interrupted verification."""

    results: list[dict[str, Any]] = []
    for gate in gates:
        if gate.binding is not None:
            results.append(
                (process_results or {}).get(
                    gate.gate_id,
                    {
                        "gate_id": gate.gate_id,
                        "binding": dict(gate.binding),
                        "status": "NOT_EVALUATED",
                        "evidence": {"reason": "PROCESS_EVIDENCE_MISSING"},
                    },
                )
            )
            continue
        checks = []
        for criterion_id in gate.acceptance_criterion_refs:
            observed = criterion_results.get(criterion_id)
            valid = isinstance(observed, tuple)
            status = "NOT_EVALUATED" if not valid else "FAIL" if observed else "PASS"
            checks.append(
                {
                    "criterion_id": criterion_id,
                    "status": status,
                    "findings": [asdict(item) for item in observed or ()] if valid else [],
                }
            )
        statuses = {check["status"] for check in checks}
        status = (
            "FAIL"
            if "FAIL" in statuses
            else "PASS"
            if checks and statuses == {"PASS"}
            else "NOT_EVALUATED"
        )
        results.append(
            {
                "gate_id": gate.gate_id,
                "acceptance_criterion_refs": list(gate.acceptance_criterion_refs),
                "status": status,
                "criterion_results": checks,
            }
        )
    return results
