"""Run the exact synthetic Phase C fixture without credentials or network."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from pmpe.barebones_selection import (
    RECORDED_TOOL_AGENT_CONTENT_DIGEST,
    RECORDED_TOOL_AGENT_FIXTURE_DIGEST,
    phase_b_approval_subject,
)
from pmpe.contracts.canonical import canonical_digest
from pmpe.recorded_tool_agent import run_recorded_tool_agent


def _contract() -> dict[str, object]:
    capabilities = [
        ("agent.recorded_model", "AC-001", "recorded_replay.strict/v1"),
        ("tool.pure_transform", "AC-002", "tool_dispatch.closed/v1"),
        ("tool.repository_lookup", "AC-003", "tool_dispatch.closed/v1"),
    ]
    return {
        "approved_at": "2026-08-31T09:00:00Z",
        "approved_by": "fixture-human",
        "contract_id": "RECORDED-AGENT-EXAMPLE",
        "contract_status": "APPROVED",
        "contract_version": 1,
        "functional_requirements": {
            f"FR-{index:03d}": {
                "acceptance_criterion_refs": [criterion],
                "priority": "MUST",
                "statement": f"Verify {capability}.",
                "title": capability,
            }
            for index, (capability, criterion, _) in enumerate(capabilities, start=1)
        },
        "acceptance_criteria": {
            criterion: {
                "criterion": f"Verify {capability}.",
                "requirement_refs": [f"FR-{index:03d}"],
                "verification_method": verifier,
            }
            for index, (capability, criterion, verifier) in enumerate(capabilities, start=1)
        },
        "implementation_selection": {
            "schema_version": "phase-b-template-selection/v1",
            "template_type": "recorded_tool_agent",
            "template_version": "1.0.0",
            "template_content_digest": RECORDED_TOOL_AGENT_CONTENT_DIGEST,
            "capability_vocabulary_version": "phase-b-capabilities/v1",
            "capability_ids": [item[0] for item in capabilities],
            "capability_bindings": [
                {
                    "acceptance_criterion_ids": [criterion],
                    "capability_id": capability,
                    "verifier_id": verifier,
                }
                for capability, criterion, verifier in capabilities
            ],
            "runtime_model_mode": "recorded",
            "configuration": {"dataset_id": "support-kb-v1"},
            "tools": [
                {
                    "resource_scopes": ["fixtures/support-kb-v1.json"],
                    "tool_id": "repository.lookup/v1",
                },
                {"resource_scopes": [], "tool_id": "pure.transform/v1"},
            ],
            "budgets": {
                "max_attempts": 3,
                "max_bytes": 262144,
                "max_steps": 12,
                "max_tool_calls": 6,
                "max_wall_time_ms": 30000,
            },
            "fixture": {
                "fixture_id": "recorded-tool-agent-happy/v1",
                "fixture_digest": RECORDED_TOOL_AGENT_FIXTURE_DIGEST,
            },
        },
    }


def main() -> int:
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "recorded-agent-example-output")
    contract = _contract()
    unsigned = {
        "approved_at": "2026-08-31T09:00:00Z",
        "approved_by": "fixture-human",
        "decision": "APPROVED",
        "expires_at": "2026-09-01T09:00:00Z",
        "schema_version": "phase-b-template-approval/v1",
        "subject": phase_b_approval_subject(contract),
    }
    approval = {**unsigned, "receipt_digest": canonical_digest(unsigned)}
    result = run_recorded_tool_agent(
        contract=contract,
        approval=approval,
        repository_root=output,
        run_id="recorded-agent-example",
        expected_approver="fixture-human",
        trusted_clock=lambda: datetime(2026, 8, 31, 9, 30, tzinfo=UTC),
    )
    print(
        json.dumps({**result.__dict__, "evidence_path": str(result.evidence_path)}, sort_keys=True)
    )
    return 0 if result.state == "RELEASE_READY" else 3


if __name__ == "__main__":
    raise SystemExit(main())
