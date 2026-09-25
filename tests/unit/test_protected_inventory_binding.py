"""The protected inventory must be exactly what the bound plan protects (Codex #220 P2)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest

from pmpe.contracts.canonical import canonical_digest
from pmpe.evidence.process_gate_validation import (
    expected_boundaries,
    validate_process_gate_evidence,
)

EVALUATOR = "sha256:" + hashlib.sha256(b"def judge():\n    return True\n").hexdigest()


def packet(protected: dict[str, str]) -> tuple[dict[str, Any], dict[str, Any], Any, dict[str, str]]:
    blobs: dict[str, bytes] = {}

    def put(value: Any) -> str:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        blobs[digest] = payload
        return digest

    blobs[EVALUATOR] = b"def judge():\n    return True\n"
    manifest = {"artifacts": {"source": put("source bytes")}}
    manifest_digest = put(manifest)
    publisher = {"test": "input"}
    contract = {"source_digest": canonical_digest(publisher)}
    contract_digest = canonical_digest(contract)
    draft = {"test": "draft"}
    plan: dict[str, Any] = {
        "contract_digest": contract_digest,
        "criteria": [],
        "trusted_test_digests": [["tests/judge.py", EVALUATOR]],
    }
    plan["plan_digest"] = canonical_digest(plan)
    receipt = {"approved_contract_digest": contract_digest, "draft_digest": canonical_digest(draft)}
    receipt["receipt_digest"] = canonical_digest(receipt)
    freeze = {
        "artifacts": {
            "contract": put(contract),
            "plan": put(plan),
            "receipt": put(receipt),
            "draft": put(draft),
            "publisher_input": put(publisher),
            "source_manifest": manifest_digest,
        }
    }
    source = {
        **manifest["artifacts"],
        **{"approval/" + key: value for key, value in freeze["artifacts"].items()},
    }
    sequence = expected_boundaries(1, ["AC-1"], [])
    records = [
        {
            "run_id": "test-only",
            "phase": phase,
            "attempt": attempt,
            "criterion_id": "AC-1",
            "process_index": index,
        }
        for index, (phase, attempt) in enumerate([("baseline", 0), ("candidate", 1)])
    ]
    observations = []
    for stage, phase, attempt, criterion in sequence:
        # A re-chained packet recomputes every digest and count consistently.
        inventory = {**source, **protected} if stage in {"before", "after"} else source
        observations.append(
            {
                "stage": stage,
                "phase": phase,
                "attempt": attempt,
                "criterion_id": criterion,
                "run_id": "test-only",
                "process_index": (0 if phase == "baseline" else 1) if criterion else None,
                "expected_inventory_digest": canonical_digest(inventory),
                "observed_inventory_digest": canonical_digest(inventory),
                "checked": len(inventory),
                "mismatches": [],
            }
        )
    evidence = {
        "reasons": [],
        "run_id": "test-only",
        "attempt": 1,
        "source_manifest_digest": manifest_digest,
        "approval_freeze_digest": put(freeze),
        "source_inventory": source,
        "protected_inventory": protected,
        "expected_boundaries": sequence,
        "observations": observations,
        "process_records": records,
        "source_checks_status": "PASS",
    }
    binding = {"kind": "digest_boundaries", "source_manifest_digest": manifest_digest}
    expected = {
        "contract_digest": contract_digest,
        "plan_digest": plan["plan_digest"],
        "receipt_digest": receipt["receipt_digest"],
    }
    return binding, evidence, blobs.__getitem__, expected


def validate(protected: dict[str, str]) -> None:
    binding, evidence, read_blob, expected = packet(protected)
    validate_process_gate_evidence(
        binding,
        evidence,
        criterion_ids=["AC-1"],
        baseline_ids={"AC-1"},
        read_blob=read_blob,
        expected=expected,
    )


def test_exact_plan_protected_inventory_is_accepted() -> None:
    validate({"protected/tests/judge.py": EVALUATOR})


@pytest.mark.parametrize(
    "protected",
    [
        {},
        {"protected/tests/judge.py": "sha256:" + "0" * 64},
        {"protected/tests/judge.py": EVALUATOR, "protected/tests/extra.py": EVALUATOR},
    ],
    ids=["emptied", "wrong-digest", "extra-path"],
)
def test_rechained_protected_inventory_is_refused(protected: dict[str, str]) -> None:
    with pytest.raises(ValueError, match="PROTECTED_INVENTORY"):
        validate(protected)
