"""Pure retained-evidence decisions must reject contradictions without executing code."""

from __future__ import annotations

from typing import Any

import pytest


@pytest.mark.parametrize(
    "kind,evidence",
    [
        ("negative_controls", {"reasons": ["UNRELATED_FAILURE:mutant"], "mutants": []}),
        ("digest_boundaries", {"reasons": [], "x": 1}),
        (
            "digest_boundaries",
            {
                "reasons": [],
                "approval_freeze_digest": "sha256:" + "a" * 64,
                "observations": [{"mismatches": ["engine/source.py"]}],
            },
        ),
        (
            "generation_provenance",
            {
                "reasons": [],
                "generation_mode": "fresh",
                "provider_attestation": {"kind": "live_model"},
            },
        ),
        ("execution_disclosure", {"reasons": [], "full_isolation_claimed": True}),
    ],
)
def test_claimed_process_pass_is_rederived(kind: str, evidence: dict[str, Any]) -> None:
    from pmpe.evidence.process_gate_validation import validate_process_gate_evidence

    with pytest.raises(ValueError):
        validate_process_gate_evidence(
            {"kind": kind},
            evidence,
            criterion_ids=["AC-001"],
            baseline_ids={"AC-001"},
            read_blob=lambda digest: b"{}",
        )
