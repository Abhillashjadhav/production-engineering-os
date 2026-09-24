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

    evidence = {"run_id": "test-only", "attempt": 1, **evidence}
    with pytest.raises(ValueError) as raised:
        validate_process_gate_evidence(
            {"kind": kind},
            evidence,
            criterion_ids=["AC-001"],
            baseline_ids={"AC-001"},
            read_blob=lambda digest: b"{}",
            expected={},
        )
    assert "PROCESS_RUN_IDENTITY_INVALID" not in str(raised.value)


@pytest.mark.parametrize("marker", [None, {"invalid_json": True}, {"exit_code": "timeout"}])
def test_negative_control_rederives_observer_markers(marker: Any) -> None:
    import hashlib
    import json

    from pmpe.evidence.process_gate_validation import validate_process_gate_evidence

    blobs: dict[str, bytes] = {}

    def put(value: Any) -> str:
        payload = (
            value
            if isinstance(value, bytes)
            else json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        )
        digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        blobs[digest] = payload
        return digest

    candidate = put({"product.py": put(b"original")})
    mutant = put({"product.py": put(b"mutated")})
    binding = {
        "kind": "negative_controls",
        "mutants": [
            {
                "id": "m",
                "snapshot_digest": mutant,
                "must_fail": ["AC-1"],
                "must_not_touch": ["tests/"],
            }
        ],
    }
    finding = {"code": "ASSERTION_FAILED", "subject_id": "AC-1"}
    evidence = {
        "run_id": "test-only",
        "attempt": 1,
        "reasons": [],
        "baseline_findings": [finding],
        "mutants": [
            {
                "mutant_id": "m",
                "run_id": "test-only",
                "attempt": 1,
                "mutant_digest": mutant,
                "candidate_digest": candidate,
                "plan_digest": "sha256:" + "a" * 64,
                "changed_paths": ["product.py"],
                "invalid_mutation": False,
                "error": "",
                "criterion_results": [
                    {"criterion_id": "AC-1", "status": "FAIL", "findings": [finding]}
                ],
                "process_records": [
                    {
                        "criterion_id": "AC-1",
                        "phase": "mutant:m",
                        "run_id": "test-only",
                        "attempt": 1,
                        "executed_argv": ["observer"],
                        "exit_code": 0,
                        "stdout_digest": put({"observations": [marker or {"value": "wrong"}]}),
                        "stderr_digest": put(b""),
                    }
                ],
            }
        ],
    }
    if marker is None:
        validate_process_gate_evidence(
            binding,
            evidence,
            criterion_ids=["AC-1"],
            baseline_ids={"AC-1"},
            read_blob=blobs.__getitem__,
            expected={"candidate_digest": candidate, "plan_digest": "sha256:" + "a" * 64},
        )
    else:
        with pytest.raises(ValueError, match="MUTANT_OBSERVER_CRASH_OR_TIMEOUT"):
            validate_process_gate_evidence(
                binding,
                evidence,
                criterion_ids=["AC-1"],
                baseline_ids={"AC-1"},
                read_blob=blobs.__getitem__,
            expected={"candidate_digest": candidate, "plan_digest": "sha256:" + "a" * 64},
            )
