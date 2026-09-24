#!/usr/bin/env python3
"""Build an unapproved v2 proposal and optional offline replay; never approve or call a model."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pmpe.barebones import BudgetCaps, Template, compile_barebones_plan, run_to_release_ready
from pmpe.contracts.canonical import canonical_digest
from pmpe.contracts.model import load_contract
from pmpe.contracts.process_gate_bindings import DISCLOSURE_REQUIREMENTS, PROVENANCE_REQUIREMENTS
from pmpe.evidence.ledger import EvidenceLedger
from pmpe.process_gates import ProcessGateInputs, build_source_manifest, raw_digest


def write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def snapshot(path: Path) -> dict[str, bytes]:
    return {
        str(item.relative_to(path)): item.read_bytes()
        for item in sorted(path.rglob("*"))
        if item.is_file()
    }


class RetainedReplayProvider:
    """Deterministic retained bytes; categorically not a fresh model provider."""

    def __init__(self, product: bytes) -> None:
        self.product = product.decode("utf-8")

    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        if purpose == "code":
            return {
                "request_digest": request["request_digest"],
                "files": {"product.py": self.product},
            }
        return {
            "request_digest": request["request_digest"],
            "annotation": "OFFLINE RETAINED REPLAY; no model called",
        }


class HistoricalHostExecution:
    """Keep the historical execution controls; new core owns authoritative identity/evidence."""

    def __init__(self, delegate: Any, missing_isolations: list[str]) -> None:
        self.delegate = delegate
        self.missing_isolations = missing_isolations

    def isolation_report(self) -> dict[str, Any]:
        return {
            "mode": "authorized_host_fallback",
            "missing_isolations": self.missing_isolations,
            "full_isolation_claimed": False,
        }

    def run(
        self,
        workspace: Path,
        argv: Sequence[str],
        *,
        timeout_seconds: float,
        environment: Mapping[str, str],
    ) -> Any:
        return self.delegate.run(
            workspace, argv, timeout_seconds=timeout_seconds, environment=environment
        )


def load_historical_adapter(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("frozen_task_store_adapter", path)
    if spec is None or spec.loader is None:
        raise ValueError("historical adapter is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--historical-engine", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--replay", action="store_true")
    args = parser.parse_args()
    packet, historical, output = (
        args.packet.resolve(),
        args.historical_engine.resolve(),
        args.output.resolve(),
    )
    if output.exists():
        raise ValueError("output must be new; retained evidence is never overwritten")
    output.mkdir(parents=True)
    adapter_path = historical / "examples/barebones/contract-file.py"
    adapter = load_historical_adapter(adapter_path)
    freeze_bytes = (packet / "freeze-manifest.json").read_bytes()
    guard = adapter.DigestGuard(
        packet / "freeze-manifest.json",
        {"PM-agent-OS": packet.parents[1], "production-engineering-os": historical},
        "sha256:1dd281e55cc20ce1861e3bed55799617191f38c5cc4e2322c7e463ef9a6e37f2",
        output / "historical-digest-checks.jsonl",
    )
    # Verify original 218-artifact freeze before interpreting or executing its evaluator.
    guard.check("migration_before", "frozen-v1")
    original_bytes = (packet / "contract.approved.json").read_bytes()
    original = json.loads(original_bytes)
    bindings_bytes = (packet / "bindings.json").read_bytes()
    template = Template(**json.loads(bindings_bytes))
    evaluator_bytes = (packet / "evaluator.py").read_bytes()
    if template.files["tests/acceptance/task_tracker.py"].encode() != evaluator_bytes:
        raise ValueError("frozen bindings and evaluator bytes differ")
    profile_bytes = (packet / "execution-profile.json").read_bytes()
    profile = json.loads(profile_bytes)
    delegate = adapter.HostExecution(
        guard, template, profile["resource_caps"], (), output / "historical-processes.jsonl"
    )
    sandbox = HistoricalHostExecution(
        delegate, profile["authorized_fallback"]["unavailable_additional_protections"]
    )
    sources = {
        "adapter": Path(__file__).resolve(),
        "historical_adapter": adapter_path,
        "evaluator": packet / "evaluator.py",
        "bindings": packet / "bindings.json",
        "execution_profile": packet / "execution-profile.json",
        "historical_freeze_manifest": packet / "freeze-manifest.json",
        "approved_scenarios": packet / "scenarios.json",
        "original_publisher_input": packet / "publisher-input.json",
        "acceptance_grid": packet / "ACCEPTANCE.md",
    }
    manifest = build_source_manifest(template, sources, profile_bytes, sandbox=sandbox)
    (output / "source-manifest.json").write_bytes(manifest)
    write(output / "source-paths.json", {key: str(path) for key, path in sources.items()})
    draft = json.loads(original_bytes)
    draft["approved_at"] = ""
    draft["approved_by"] = ""
    draft["contract_status"] = "DRAFT"
    draft["contract_version"] = 2
    draft["contract_id"] += "-V2-DRAFT"
    criteria = [item["id"] for item in draft["acceptance_criteria"]]
    gates = draft["binary_release_gates"]
    gates[0]["acceptance_criterion_refs"] = criteria
    gates[1]["binding"] = {
        "kind": "negative_controls",
        "baseline": {
            "event": "meaningful_red_confirmed",
            "required_failure_code": "ASSERTION_FAILED",
        },
        "required_failure_code": "ASSERTION_FAILED",
        "mutants": [
            {
                "id": "persistence",
                "must_fail": ["AC-002", "AC-005", "AC-013"],
                "must_not_touch": ["tests/"],
            },
            {"id": "filtering", "must_fail": ["AC-004"], "must_not_touch": ["tests/"]},
        ],
    }
    gates[2]["binding"] = {
        "kind": "digest_boundaries",
        "source_manifest_digest": raw_digest(manifest),
        "per_check": ["before", "after"],
        "require_command_boundary": True,
        "require_release_boundary": True,
    }
    gates[3]["binding"] = {
        "kind": "generation_provenance",
        "mode": "fresh",
        "roles": ["code"],
        "require": PROVENANCE_REQUIREMENTS,
    }
    gates[4]["binding"] = {
        "kind": "execution_disclosure",
        "execution_profile_sha256": raw_digest(profile_bytes),
        "required": DISCLOSURE_REQUIREMENTS,
        "forbid": {"full_isolation_claimed": True, "readiness_scope": "general"},
    }
    for key in ("acceptance_criteria", "functional_requirements", "golden_cases", "guardrails"):
        if draft[key] != original[key]:
            raise ValueError("frozen product semantics changed: " + key)
    write(output / "contract.draft.json", draft)
    if load_contract(output / "contract.draft.json").runnable:
        raise ValueError("migration artifact must remain an unapproved draft")
    plan = compile_barebones_plan(contract=draft, repository_root=output, template=template)
    write(output / "compiled-plan.proposed.json", plan.as_dict())
    write(
        output / "migration.json",
        {
            "status": "DRAFT_NOT_APPROVED",
            "original_contract_raw_digest": raw_digest(original_bytes),
            "original_contract_canonical_digest": canonical_digest(original),
            "proposed_contract_digest": canonical_digest(draft),
            "source_manifest_digest": raw_digest(manifest),
            "historical_freeze_digest": canonical_digest(json.loads(freeze_bytes)),
            "approval_receipt_created": False,
            "fresh_model_calls": 0,
            "source_approval": (
                "Pending owner review of exact new source/adapter/manifest and proposed bindings"
            ),
            "outer_freeze_after_approval": [
                "reviewed draft",
                "approved contract",
                "source manifest",
                "approval receipt",
                "compiled plan",
                "current adapter",
                "profile and evaluator/bindings",
            ],
            "excluded_from_source_manifest": [
                "this draft",
                "approved contract",
                "approval receipt",
                "outer freeze",
            ],
            "legacy_verify_limit": (
                "Historical adapter verify/_verify_snapshot alone is "
                "behavioral replay, not release-gate proof."
            ),
        },
    )
    if args.replay:
        retained = historical / "docs/evidence/task-tracker-live-20260918"
        inputs = ProcessGateInputs(
            generation_mode="replay",
            provider_attestation={
                "kind": "replay",
                "statement": (
                    "Retained 2026-09-18 product bytes; no in-session "
                    "generation and no live model call."
                ),
            },
            source_manifest=manifest,
            source_paths=sources,
            execution_profile=profile_bytes,
            negative_controls={
                name: snapshot(retained / "mutations" / name / "candidate")
                for name in ("persistence", "filtering")
            },
            real_sandbox_leg={
                "status": "BLOCKED",
                "reason": (
                    "Historical approved profile reports uid-map failure; no new sandbox attempt."
                ),
            },
        )
        result = run_to_release_ready(
            contract=draft,
            repository_root=output,
            workspace=output / "candidate",
            run_id="draft-v2-offline-retained-replay",
            provider=RetainedReplayProvider((retained / "live/candidate/product.py").read_bytes()),
            template=template,
            candidate_sandbox=sandbox,
            budget=BudgetCaps(max_attempts=1),
            process_gate_inputs=inputs,
        )
        events = list(EvidenceLedger.open_existing(output, result.run_id).verify())
        gate_event = next(
            event for event in events if event["event_type"] == "release_gates_evaluated"
        )
        gates = gate_event["payload"]["gates"]
        summary = {
            "status": "OFFLINE_REPLAY_NOT_APPROVED",
            "state": result.state,
            "cause": result.cause,
            "run_id": result.run_id,
            "contract_digest": canonical_digest(draft),
            "plan_digest": plan.plan_digest,
            "gates": {gate["gate_id"]: gate["status"] for gate in gates},
            "process_records": len(gates[3]["evidence"]["process_records"]),
            "digest_boundaries": len(gates[2]["evidence"]["observations"]),
            "fresh_model_calls": 0,
            "approval": events[0]["payload"]["approval"],
            "gate_evidence_event_digest": gate_event["event_digest"],
        }
        write(output / "replay-summary.json", summary)
        write(output / "gate-evidence.json", gate_event["payload"])
        shutil.copytree(output / ".pmpe", output / "retained-ledger")
        if result.state != "HALTED" or list(summary["gates"].values()) != [
            "PASS",
            "PASS",
            "NOT_EVALUATED",
            "NOT_EVALUATED",
            "PASS",
        ]:
            raise ValueError("offline retained replay did not produce required fail-closed verdict")
    guard.check("migration_after", "frozen-v1")
    print(
        json.dumps({"output": str(output), "status": "DRAFT_NOT_APPROVED", "replay": args.replay})
    )
    return 0


if __name__ == "__main__":
    import r3_task_store_migration

    raise SystemExit(r3_task_store_migration.main())
