"""Readback must independently verify profile checks from sealed evidence."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from pmpe.barebones import compile_barebones_plan, default_template
from pmpe.contracts.acceptance import AcceptanceBuildPlan, CompiledCriterion, Operator
from pmpe.contracts.canonical import canonical_digest, canonical_json_bytes
from pmpe.contracts.task_graph import compile_task_graph
from pmpe.evidence.ledger import EvidenceIntegrityError, EvidenceLedger
from pmpe.product_acceptance_readback import verify_observation_predicates
from pmpe.product_checks import candidate_manifest_digest, evaluate_required_checks
from pmpe.product_profile import compile_product_profile
from pmpe.product_readback import verify_product_build_evidence
from pmpe.task_tracker_harness import MEASURE_TARGET, fixed_template

ROOT = Path(__file__).resolve().parents[2]


def _evidence(
    root: Path,
    *,
    change: str | None = None,
    include_check: bool = True,
    baseline: bool = False,
    final_observation: bool = True,
    terminal_state: str | None = None,
    response_status: str = "ok",
    recorded_pass: bool = True,
    observation_action: str = "health",
    observation_target: str = "product:health",
) -> tuple[EvidenceLedger, tuple[dict[str, Any], ...]]:
    contract = json.loads((ROOT / "examples/barebones/e1-contract.json").read_text())
    template = default_template()
    profile = compile_product_profile(
        "barebones-health-v1", contract=contract, template=template, harness_plan=None
    )
    plan = compile_barebones_plan(contract=contract, repository_root=root, template=template)
    graph = compile_task_graph(plan)
    ledger = EvidenceLedger(root, "readback")
    contract_blob = ledger.put_blob(canonical_json_bytes(contract))
    plan_blob = ledger.put_blob(canonical_json_bytes(plan.as_dict()))
    graph_blob = ledger.put_blob(canonical_json_bytes(graph.as_dict()))
    profile_blob = ledger.put_blob(canonical_json_bytes(profile.manifest))
    ledger.append(
        event_type="contract_validated",
        state="VALIDATED",
        subject_digest=contract_blob,
        blob_digests=(contract_blob, plan_blob, graph_blob, profile_blob),
        payload={
            "contract_digest": contract_blob,
            "plan_digest": plan.plan_digest,
            "plan_blob_digest": plan_blob,
            "template_digest": profile.template_digest,
            "task_graph_digest": graph.graph_digest,
            "task_graph_blob_digest": graph_blob,
            "product_profile": {
                "profile_id": profile.profile_id,
                "manifest_digest": profile.manifest_digest,
            },
        },
    )
    source = {"product.py": b"def health():\n    return {'status': 'ok'}\n"}
    files = {path: ledger.put_blob(content) for path, content in source.items()}
    candidate = ledger.put_blob(json.dumps(files, sort_keys=True, separators=(",", ":")).encode())
    assert candidate == candidate_manifest_digest(source)
    response = {"status": response_status}
    response_blob = ledger.put_blob(canonical_json_bytes(response))
    raw_observations = {
        "AC-001": {
            "criterion_id": "AC-001",
            "action": observation_action,
            "target": observation_target,
            "response": response,
            "response_digest": response_blob,
            "assertions_passed": recorded_pass,
        }
    }
    observation = {
        "protocol": "external-json-response-v1",
        "attempt": 1,
        "contract_digest": contract_blob,
        "plan_digest": plan.plan_digest,
        "template_digest": profile.template_digest,
        "candidate_digest": candidate,
        "required_criterion_ids": ["AC-001"],
        "observations": [
            {
                "criterion_id": "AC-001",
                "action": observation_action,
                "target": observation_target,
                "response_digest": response_blob,
                "assertions_passed": recorded_pass,
            }
        ],
    }
    observation_blob = ledger.put_blob(canonical_json_bytes(observation))
    if baseline:
        baseline_body = {**observation, "attempt": 0}
        baseline_blob = ledger.put_blob(canonical_json_bytes(baseline_body))
        ledger.append(
            event_type="supervisor_observations",
            state="BUILDING",
            subject_digest=contract_blob,
            blob_digests=(baseline_blob, candidate, *files.values(), response_blob),
            payload={**baseline_body, "evidence_digest": baseline_blob},
        )
    if final_observation:
        ledger.append(
            event_type="supervisor_observations",
            state="VERIFYING",
            subject_digest=contract_blob,
            blob_digests=(observation_blob, candidate, *files.values(), response_blob),
            payload={**observation, "evidence_digest": observation_blob},
        )
    if include_check and final_observation:
        report = evaluate_required_checks(
            profile,
            candidate_digest=candidate,
            source_files=source,
            acceptance_observations=raw_observations,
            security_findings=(),
        )
        check_evidence = {
            "source_files": files,
            "observations": raw_observations,
            "security_findings": [],
        }
        check_evidence_blob = ledger.put_blob(canonical_json_bytes(check_evidence))
        body = report.as_dict()
        body["binding"]["plan_digest"] = plan.plan_digest
        body["binding"]["task_graph_digest"] = graph.graph_digest
        body["binding_digest"] = canonical_digest(body["binding"])
        body["attempt"] = 1
        body["observation_evidence_digest"] = observation_blob
        body["tool_identity"] = {
            "python_version": list(sys.version_info[:3]),
            "implementation": "cpython",
            "interpreter_digest": "sha256:" + "a" * 64,
        }
        if change == "false_pass":
            body["results"][-1]["status"] = "PASS"
            body["delivery_qualified"] = True
        elif change == "stale_candidate":
            body["binding"]["candidate_digest"] = canonical_digest({"old": 1})
            body["binding_digest"] = canonical_digest(body["binding"])
        elif change == "missing_check":
            body["results"].pop()
        elif change == "unbound_observation":
            body["observation_evidence_digest"] = canonical_digest({"other": 1})
        elif change == "missing_tool_identity":
            del body["tool_identity"]
        report_blob = ledger.put_blob(canonical_json_bytes(body))
        ledger.append(
            event_type="required_checks_evaluated",
            state="VERIFYING",
            subject_digest=contract_blob,
            blob_digests=(
                report_blob,
                check_evidence_blob,
                candidate,
                *files.values(),
                observation_blob,
            ),
            payload={**body, "evidence_digest": report_blob},
        )
        if change == "stale_terminal":
            ledger.append(
                event_type="halted",
                state="HALTED",
                subject_digest=contract_blob,
                payload={
                    "cause": "PROVIDER_WRITE_ISOLATION_UNVERIFIED",
                    "candidate_digest": canonical_digest({"old": 1}),
                },
            )
    if terminal_state is not None:
        ledger.append(
            event_type="halted" if terminal_state == "HALTED" else "release_ready",
            state=terminal_state,
            subject_digest=contract_blob,
            payload={"cause": "MODEL_PROVIDER_FAILED" if terminal_state == "HALTED" else "PASS"},
        )
    events = tuple(dict(item) for item in ledger.verify())
    return ledger, events


def test_readback_recomputes_exact_protected_results(tmp_path: Path) -> None:
    ledger, events = _evidence(tmp_path, baseline=True)
    verify_product_build_evidence(ledger, events)


def test_legacy_release_without_validation_remains_readable(tmp_path: Path) -> None:
    ledger = EvidenceLedger(tmp_path, "historical")
    event = ledger.append(
        event_type="release_ready",
        state="RELEASE_READY",
        subject_digest="sha256:" + "a" * 64,
        payload={"candidate_digest": "sha256:" + "b" * 64},
    )
    verify_product_build_evidence(ledger, [event])


@pytest.mark.parametrize("terminal_state", [None, "HALTED"])
def test_baseline_only_run_is_readable_without_candidate_qualification(
    tmp_path: Path, terminal_state: str | None
) -> None:
    ledger, events = _evidence(
        tmp_path, baseline=True, final_observation=False, terminal_state=terminal_state
    )
    verify_product_build_evidence(ledger, events)


def test_final_observation_without_check_remains_invalid_with_baseline(tmp_path: Path) -> None:
    ledger, events = _evidence(tmp_path, baseline=True, include_check=False)
    with pytest.raises(EvidenceIntegrityError):
        verify_product_build_evidence(ledger, events)


def test_release_claim_without_candidate_checks_is_invalid(tmp_path: Path) -> None:
    ledger, events = _evidence(
        tmp_path, baseline=True, final_observation=False, terminal_state="RELEASE_READY"
    )
    with pytest.raises(EvidenceIntegrityError):
        verify_product_build_evidence(ledger, events)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"response_status": "not-ready", "recorded_pass": True},
        {"observation_action": "other"},
        {"observation_target": "other:health"},
    ],
)
def test_consistently_rehashed_false_acceptance_semantics_fail(
    tmp_path: Path, kwargs: dict[str, Any]
) -> None:
    ledger, events = _evidence(tmp_path, **kwargs)
    with pytest.raises(EvidenceIntegrityError):
        verify_product_build_evidence(ledger, events)


def test_honest_failed_acceptance_result_remains_readable(tmp_path: Path) -> None:
    ledger, events = _evidence(tmp_path, response_status="not-ready", recorded_pass=False)
    verify_product_build_evidence(ledger, events)
    report = next(item for item in events if item["event_type"] == "required_checks_evaluated")
    assert report["payload"]["candidate_qualified"] is False


def test_measure_readback_rechecks_sample_and_value() -> None:
    template = fixed_template()
    criterion = CompiledCriterion(
        "AC-013",
        ("FR-001",),
        "measure",
        measure="task_tracker.missing_acknowledged_records",
        operator=Operator.EQ,
        value=0,
        minimum_sample=10,
    )
    plan = AcceptanceBuildPlan("", (), (), (criterion,), (), "")
    observation = {
        "AC-013": {
            "action": criterion.measure,
            "target": MEASURE_TARGET,
            "response": {"sample_size": 10, "value": 1},
            "trace": [],
            "assertions_passed": True,
        }
    }
    with pytest.raises(EvidenceIntegrityError, match="assertion differs"):
        verify_observation_predicates(plan, template, observation)
    observation["AC-013"]["assertions_passed"] = False
    verify_observation_predicates(plan, template, observation)


@pytest.mark.parametrize(
    "change",
    [
        "false_pass",
        "stale_candidate",
        "missing_check",
        "unbound_observation",
        "missing_tool_identity",
        "stale_terminal",
    ],
)
def test_readback_rejects_rehashed_but_semantically_false_report(
    tmp_path: Path, change: str
) -> None:
    ledger, events = _evidence(tmp_path, change=change)
    with pytest.raises(EvidenceIntegrityError):
        verify_product_build_evidence(ledger, events)


def test_missing_profile_check_fails_but_legacy_without_profile_stays_readable(
    tmp_path: Path,
) -> None:
    ledger, events = _evidence(tmp_path, include_check=False)
    with pytest.raises(EvidenceIntegrityError):
        verify_product_build_evidence(ledger, events)
    legacy = [dict(event) for event in events]
    legacy[0] = {
        **legacy[0],
        "payload": {"contract_digest": events[0]["payload"]["contract_digest"]},
    }
    verify_product_build_evidence(ledger, legacy)
