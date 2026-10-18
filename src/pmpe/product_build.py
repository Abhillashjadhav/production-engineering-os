"""Join protected build configuration to the canonical runtime and its evidence."""

from __future__ import annotations

import hashlib
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pmpe.contracts.acceptance import AcceptanceBuildPlan
from pmpe.contracts.canonical import canonical_digest, canonical_json_bytes
from pmpe.contracts.task_graph import CompiledTaskGraph, TaskGraphError, compile_task_graph
from pmpe.core_harness import CoreHarnessPlan
from pmpe.evidence.ledger import EvidenceLedger

if TYPE_CHECKING:
    from pmpe.barebones import Template
    from pmpe.product_profile import CompiledProductProfile


@dataclass(frozen=True)
class BuildBindings:
    graph: CompiledTaskGraph
    profile: CompiledProductProfile | None


def admit_build_bindings(
    *,
    contract: Mapping[str, Any],
    plan: AcceptanceBuildPlan,
    template: Template,
    harness_plan: CoreHarnessPlan | None,
    profile: CompiledProductProfile | None,
    graph_mapping: Mapping[str, Any] | None,
) -> BuildBindings:
    from pmpe.barebones import ContractInvalidError
    from pmpe.product_profile import ProductProfileError, compile_product_profile

    if profile is not None:
        try:
            expected = compile_product_profile(
                profile.profile_id, contract=contract, template=template, harness_plan=harness_plan
            )
            if canonical_digest(asdict(profile)) != canonical_digest(asdict(expected)):
                raise ProductProfileError("profile differs from protected built-in")
        except (ProductProfileError, ValueError) as exc:
            raise ContractInvalidError("product profile admission failed") from exc
        profile = expected
    protected = tuple(proof.path for proof in template.proofs.values())
    try:
        graph = compile_task_graph(plan, graph_mapping, protected_paths=protected)
    except TaskGraphError as exc:
        raise ContractInvalidError("task graph admission failed: " + exc.code) from exc
    return BuildBindings(graph, profile)


def store_build_bindings(
    ledger: EvidenceLedger,
    bindings: BuildBindings,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    graph_blob = ledger.put_blob(canonical_json_bytes(bindings.graph.as_dict()))
    payload: dict[str, Any] = {
        "task_graph_digest": bindings.graph.graph_digest,
        "task_graph_blob_digest": graph_blob,
        "execution_mode": bindings.graph.execution_mode,
    }
    blobs = [graph_blob]
    if bindings.profile is not None:
        profile_blob = ledger.put_blob(canonical_json_bytes(bindings.profile.manifest))
        blobs.append(profile_blob)
        payload["product_profile"] = {
            "profile_id": bindings.profile.profile_id,
            "manifest_digest": bindings.profile.manifest_digest,
        }
    return payload, tuple(blobs)


def record_required_checks(
    *,
    ledger: EvidenceLedger,
    bindings: BuildBindings,
    plan: AcceptanceBuildPlan,
    candidate_digest: str,
    candidate_blobs: Sequence[str],
    snapshot: Mapping[str, bytes],
    observations: Mapping[str, Mapping[str, Any]],
    security_findings: Sequence[str],
    attempt: int,
    observation_evidence_digest: str,
) -> bool:
    """Only the supervisor calls this after executing checks on its frozen snapshot."""
    from pmpe.product_checks import evaluate_required_checks

    if bindings.profile is None:
        return True
    if not observation_evidence_digest:
        return False
    report = evaluate_required_checks(
        bindings.profile,
        candidate_digest=candidate_digest,
        source_files=snapshot,
        acceptance_observations=observations,
        security_findings=security_findings,
    )
    body = report.as_dict()
    body["binding"]["plan_digest"] = plan.plan_digest
    body["binding"]["task_graph_digest"] = bindings.graph.graph_digest
    body["binding_digest"] = canonical_digest(body["binding"])
    body["attempt"] = attempt
    body["observation_evidence_digest"] = observation_evidence_digest
    check_evidence = ledger.put_blob(canonical_json_bytes(report.evidence))
    if any(item.evidence_digest not in (None, check_evidence) for item in report.results):
        raise ValueError("required check evidence identity changed")
    body["tool_identity"] = {
        "python_version": list(sys.version_info[:3]),
        "implementation": sys.implementation.name,
        "interpreter_digest": "sha256:"
        + hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
    }
    blob = ledger.put_blob(canonical_json_bytes(body))
    ledger.append(
        event_type="required_checks_evaluated",
        state="VERIFYING",
        subject_digest=plan.contract_digest,
        blob_digests=(
            blob,
            check_evidence,
            candidate_digest,
            *candidate_blobs,
            *((observation_evidence_digest,) if observation_evidence_digest else ()),
        ),
        payload={**body, "evidence_digest": blob},
    )
    return report.candidate_qualified
