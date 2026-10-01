"""Render a new DRAFT mapping from the unchanged PMOS task-tracker packet.

This makes no approval receipt, executes no candidate, and confers no release
authority. The original PMOS source files must match their frozen raw digests.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from pmpe.barebones import compile_barebones_plan
from pmpe.contracts.authoring import build_contract_draft, verify_contract_approval
from pmpe.contracts.canonical import canonical_digest
from pmpe.task_tracker_harness import fixed_template, registry_identity

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source"
SOURCE_COMMIT = "2acc3fa0c81f1237f8ab7b5681b478630c530931"
SOURCE_RAW_SHA256 = {
    "ACCEPTANCE.md": "7788286762d679c26769e4abc05406597829cdb89da57a0425d4353d79c5e7a8",
    "README.md": "a9fc43ca99cdc023628b0098c2d0c6df1e2e3d3a52fc92b7aeea260c3c23a775",
    "approval-receipt.json": "856ef2b3257a54c3834c44f95d61b245be4906807db50d2f88dc63e219b1d09c",
    "bindings.json": "3414ac07671405b6d69a41af91b1e96b8324d1c4455b0e262f5e04123540dac0",
    "contract.approved.json": "41f93f23ca57cef11201fe685b18d66be882c122e5a3c7192e37e9018de0f0e2",
    "evaluator.py": "7a5a3064d8ec07ae1d941aaa2145330076c8acf62bbbc7cc65e158b9f9cf4d66",
    "execution-profile.json": "4a46f594d269e130b8933cd032fa7fb400c0a510553f77140efa2a1fab683120",
    "publisher-input.json": "37303040df5b8dc6a9d3ae8182654872e629b59e1212dca736586693ecd50c40",
    "scenarios.json": "0c5bd5d6f5b0130333c823be2f136df31487b26b22a6b74837bdfc8061806620",
}
CONDITION_STAGES = {
    "GATE-001": "product_acceptance",
    "GATE-002": "meaningful_red_and_regressions",
    "GATE-003": "approval_bound_integrity",
    "GATE-004": "build_provenance",
    "GATE-005": "limitations_report",
}
APPROVAL_SOURCE = "Sentinel_9c3320c8e9d881919428b5e6e1ff6341"


def _read_source() -> dict[str, Any]:
    for name, expected in SOURCE_RAW_SHA256.items():
        observed = hashlib.sha256((SOURCE / name).read_bytes()).hexdigest()
        if observed != expected:
            raise ValueError(f"PMOS source changed: {name}")
    return {
        name: json.loads((SOURCE / name).read_text())
        for name in SOURCE_RAW_SHA256
        if name.endswith(".json")
    }


def _write_json(path: Path, body: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def render(output: Path) -> dict[str, Any]:
    source = _read_source()
    original = source["contract.approved.json"]
    receipt = source["approval-receipt.json"]
    answers = source["publisher-input.json"]
    scenarios = source["scenarios.json"]
    bindings = source["bindings.json"]
    identity = registry_identity()
    if (
        hashlib.sha256(bindings["files"]["tests/acceptance/task_tracker.py"].encode()).hexdigest()
        != SOURCE_RAW_SHA256["evaluator.py"]
    ):
        raise ValueError("historical PMOS evaluator binding changed")
    if identity["evaluator_digest"] != "sha256:" + SOURCE_RAW_SHA256["evaluator.py"]:
        raise ValueError("packaged task-tracker evaluator differs from PMOS source")

    if original.get("contract_status") != "APPROVED":
        raise ValueError("historical PMOS contract is not approved")
    approver = original.get("approved_by")
    if not isinstance(approver, str) or not approver:
        raise ValueError("historical PMOS approver is missing")
    receipt_digest = verify_contract_approval(original, receipt, expected_approver=approver)
    criteria = original.get("acceptance_criteria")
    gates = original.get("binary_release_gates")
    if not isinstance(criteria, list) or not isinstance(gates, list):
        raise ValueError("historical PMOS criteria or conditions are missing")
    criterion_ids = [item["id"] for item in criteria]
    if criterion_ids != [f"AC-{index:03}" for index in range(1, 15)]:
        raise ValueError("historical PMOS criteria are not the approved 14 cases")
    if [item["id"] for item in gates] != list(CONDITION_STAGES):
        raise ValueError("historical PMOS release conditions changed")
    if any("acceptance_criterion_refs" in item for item in gates):
        raise ValueError("historical condition bindings changed")
    if not isinstance(scenarios, list) or len(scenarios) != len(criteria):
        raise ValueError("historical PMOS scenario grid is incomplete")
    if [
        {key: value for key, value in scenario.items() if key != "severity"}
        for scenario in scenarios
    ] != criteria:
        raise ValueError("historical PMOS scenarios diverge from approved criteria")
    ac13 = criteria[12]
    if (
        ac13.get("measure") != "task_tracker.missing_acknowledged_records"
        or ac13.get("sample") != {"minimum": 10}
        or ac13.get("operator") != "eq"
        or ac13.get("value") != 0
    ):
        raise ValueError("approved sequential measurement changed")

    conditions = [
        {
            "condition_id": gate["id"],
            "description": gate["description"],
            "harness_stage": CONDITION_STAGES[gate["id"]],
            "required": True,
            "criterion_refs": criterion_ids if gate["id"] == "GATE-001" else [],
        }
        for gate in gates
    ]
    mapping = {
        "schema_version": "pmos-core-harness-mapping-v1",
        "source_repository": "Abhillashjadhav/PM-agent-OS",
        "source_commit": SOURCE_COMMIT,
        "source_raw_sha256": SOURCE_RAW_SHA256,
        "source_contract_digest": canonical_digest(original),
        "source_receipt_digest": receipt_digest,
        "mapping_approval_source": APPROVAL_SOURCE,
        "mapping_approval_scope": "all 14 criteria and all five release conditions",
        "criterion_ids": criterion_ids,
        "required_conditions": conditions,
        "registry": identity,
    }
    mapped_answers = copy.deepcopy(answers)
    mapped_answers["contract_version"] = original["contract_version"] + 1
    mapped_answers["binary_release_gates"] = [
        {**copy.deepcopy(gates[0]), "acceptance_criterion_refs": criterion_ids}
    ]
    mapped_answers["required_harness_digest"] = canonical_digest(mapping)
    draft_result = build_contract_draft(mapped_answers)
    if draft_result.draft is None or draft_result.draft_digest is None:
        raise ValueError("mapped PMOS input did not publish a draft")
    draft = draft_result.draft
    if draft["acceptance_criteria"] != criteria:
        raise ValueError("mapped draft changed approved product cases")
    template = fixed_template()
    plan = compile_barebones_plan(contract=draft, repository_root=ROOT, template=template)
    if [item.criterion_id for item in plan.criteria] != criterion_ids:
        raise ValueError("mapped compile dropped an approved case")
    if plan.criteria[12].form != "measure" or len(plan.release_gates) != 1:
        raise ValueError("mapped compile changed the required measure or acceptance gate")
    summary = {
        "status": "DRAFT_READY_FOR_EXACT_DIGEST_REVIEW",
        "mapped_answers_digest": canonical_digest(mapped_answers),
        "mapped_draft_digest": draft_result.draft_digest,
        "mapped_plan_digest": plan.plan_digest,
        "required_harness_digest": canonical_digest(mapping),
        "criterion_count": len(criterion_ids),
        "required_condition_count": len(conditions),
        "exact_draft_digest_approved": False,
        "runtime_or_live_provider_proof": False,
        "release_eligible": False,
    }
    _write_json(output / "publisher-input.mapped.json", mapped_answers)
    _write_json(output / "contract.draft.json", draft)
    _write_json(output / "core-harness-mapping.json", mapping)
    _write_json(output / "mapping-summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "mapped")
    arguments = parser.parse_args()
    result = render(arguments.output)
    print(
        json.dumps(
            {
                "status": "DRAFT_READY_FOR_EXACT_DIGEST_REVIEW",
                "draft_digest": result["mapped_draft_digest"],
                "criteria": result["criterion_count"],
                "required_conditions": result["required_condition_count"],
                "release_eligible": False,
            },
            sort_keys=True,
        )
    )
