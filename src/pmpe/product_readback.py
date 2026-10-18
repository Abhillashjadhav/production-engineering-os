"""Read-only semantic verification of protected product build evidence."""

from __future__ import annotations

import re
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from pmpe.barebones import (
    _materialize_snapshot,
    _security_findings,
    compile_barebones_plan,
    default_template,
)
from pmpe.contracts.canonical import CanonicalInputError, canonical_digest, strict_loads
from pmpe.contracts.task_graph import TaskGraphError, compile_task_graph
from pmpe.core_harness import CoreHarnessInvalidError, compile_required_harness
from pmpe.evidence.ledger import EvidenceIntegrityError, EvidenceLedger
from pmpe.product_acceptance_readback import verify_observation_predicates
from pmpe.product_checks import candidate_manifest_digest, evaluate_required_checks
from pmpe.product_profile import ProductProfileError, compile_product_profile
from pmpe.task_tracker_harness import fixed_template

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SAFE_PATH = re.compile(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\Z")


def _require(condition: bool, detail: str) -> None:
    if not condition:
        raise EvidenceIntegrityError("product build evidence invalid: " + detail)


def _payload(event: Mapping[str, Any]) -> Mapping[str, Any]:
    result = event.get("payload")
    _require(isinstance(result, Mapping), "event payload")
    return cast(Mapping[str, Any], result)


def _blobs(event: Mapping[str, Any]) -> list[str]:
    result = event.get("blob_digests")
    _require(
        isinstance(result, list) and all(isinstance(item, str) for item in result),
        "blob references",
    )
    return cast(list[str], result)


def _blob_object(
    ledger: EvidenceLedger, event: Mapping[str, Any], digest: object
) -> dict[str, Any]:
    _require(isinstance(digest, str) and digest in _blobs(event), "unreferenced blob")
    try:
        value = strict_loads(ledger.read_blob(cast(str, digest)), "application/json")
    except CanonicalInputError as exc:
        raise EvidenceIntegrityError("product build evidence invalid: malformed JSON blob") from exc
    _require(isinstance(value, dict), "blob is not an object")
    return value


def _only(events: Sequence[Mapping[str, Any]], kind: str) -> Mapping[str, Any]:
    matches = [event for event in events if event.get("event_type") == kind]
    _require(len(matches) == 1, f"{kind} event count")
    return matches[0]


def _candidate(
    ledger: EvidenceLedger, event: Mapping[str, Any], digest: object
) -> dict[str, bytes]:
    manifest = _blob_object(ledger, event, digest)
    _require(bool(manifest), "empty candidate manifest")
    result: dict[str, bytes] = {}
    for name, file_digest in manifest.items():
        _require(
            isinstance(name, str)
            and _SAFE_PATH.fullmatch(name) is not None
            and all(part not in {".", ".."} for part in name.split("/")),
            "unsafe candidate path",
        )
        _require(
            isinstance(file_digest, str) and file_digest in _blobs(event),
            "candidate file unreferenced",
        )
        result[name] = ledger.read_blob(cast(str, file_digest))
    _require(candidate_manifest_digest(result) == digest, "candidate manifest mismatch")
    return result


def _observations(
    ledger: EvidenceLedger,
    event: Mapping[str, Any],
    *,
    candidate_digest: str,
    plan_digest: str,
    contract_digest: str,
    template_digest: str,
    criterion_ids: tuple[str, ...],
) -> dict[str, dict[str, Any]]:
    payload = _payload(event)
    evidence_digest = payload.get("evidence_digest")
    body = {key: value for key, value in payload.items() if key != "evidence_digest"}
    _require(
        isinstance(evidence_digest, str)
        and canonical_digest(body) == evidence_digest
        and _blob_object(ledger, event, evidence_digest) == body,
        "supervisor observation blob",
    )
    _require(
        event.get("state") == "VERIFYING"
        and event.get("subject_digest") == contract_digest
        and payload.get("protocol") == "external-json-response-v1"
        and payload.get("candidate_digest") == candidate_digest
        and payload.get("plan_digest") == plan_digest
        and payload.get("contract_digest") == contract_digest
        and payload.get("template_digest") == template_digest
        and payload.get("required_criterion_ids") == sorted(criterion_ids),
        "observation binding",
    )
    entries = payload.get("observations")
    _require(
        isinstance(entries, list) and len(entries) == len(criterion_ids), "observation coverage"
    )
    result: dict[str, dict[str, Any]] = {}
    for entry in cast(list[Any], entries):
        _require(isinstance(entry, dict), "observation entry")
        _require(
            {"criterion_id", "action", "target", "response_digest", "assertions_passed"}
            <= set(entry)
            <= {
                "criterion_id",
                "action",
                "target",
                "response_digest",
                "assertions_passed",
                "trace_digest",
            },
            "observation entry shape",
        )
        criterion_id = entry["criterion_id"]
        _require(
            isinstance(criterion_id, str)
            and criterion_id in criterion_ids
            and criterion_id not in result
            and isinstance(entry["action"], str)
            and isinstance(entry["target"], str)
            and type(entry["assertions_passed"]) is bool,
            "observation identity",
        )
        response = _blob_object(ledger, event, entry["response_digest"])
        item = {
            "criterion_id": criterion_id,
            "action": entry["action"],
            "target": entry["target"],
            "response": response,
            "response_digest": entry["response_digest"],
            "assertions_passed": entry["assertions_passed"],
        }
        if "trace_digest" in entry:
            trace_digest = entry["trace_digest"]
            _require(
                isinstance(trace_digest, str) and trace_digest in _blobs(event),
                "trace unreferenced",
            )
            try:
                trace = strict_loads(ledger.read_blob(trace_digest), "application/json")
            except CanonicalInputError as exc:
                raise EvidenceIntegrityError(
                    "product build evidence invalid: malformed trace"
                ) from exc
            _require(isinstance(trace, list), "observation trace shape")
            item["trace"] = trace
        result[criterion_id] = item
    _require(set(result) == set(criterion_ids), "observation criterion closure")
    return result


def _scanner_codes(source: Mapping[str, bytes]) -> tuple[str, ...]:
    try:
        with tempfile.TemporaryDirectory(prefix="pmpe-readback-") as directory:
            workspace = Path(directory)
            _materialize_snapshot(workspace, source)
            return tuple(item.code for item in _security_findings(workspace))
    except (ValueError, OSError, RuntimeError) as exc:
        raise EvidenceIntegrityError("product build evidence invalid: static scan failed") from exc


def verify_product_build_evidence(
    ledger: EvidenceLedger, events: Sequence[Mapping[str, Any]]
) -> None:
    """REV_PRODUCT_READBACK: rederive every profile check from protected blobs.

    Old ledgers without a product profile retain their historical interpretation;
    they acquire no profile or delivery qualification from this function.
    """

    check_events = [
        event for event in events if event.get("event_type") == "required_checks_evaluated"
    ]
    profiled = [
        event
        for event in events
        if event.get("event_type") == "contract_validated"
        and _payload(event).get("product_profile") is not None
    ]
    if not profiled:
        _require(not check_events, "checks without profile")
        return
    validation = _only(events, "contract_validated")
    validation_payload = _payload(validation)
    metadata = validation_payload.get("product_profile")
    _require(
        isinstance(metadata, dict) and set(metadata) == {"profile_id", "manifest_digest"},
        "profile metadata",
    )
    metadata = cast(dict[str, Any], metadata)
    profile_id = metadata["profile_id"]
    profile_digest = metadata["manifest_digest"]
    _require(profile_id in {"barebones-health-v1", "pmos-task-tracker-v1"}, "profile ID")
    contract_digest = validation_payload.get("contract_digest")
    contract = _blob_object(ledger, validation, contract_digest)
    _require(
        canonical_digest(contract) == contract_digest == validation.get("subject_digest"),
        "contract binding",
    )
    template = default_template() if profile_id == "barebones-health-v1" else fixed_template()
    mapping_digest = validation_payload.get("harness_mapping_blob_digest")
    mapping = (
        _blob_object(ledger, validation, mapping_digest) if mapping_digest is not None else None
    )
    try:
        harness = compile_required_harness(contract, mapping)
        profile = compile_product_profile(
            profile_id, contract=contract, template=template, harness_plan=harness
        )
        plan = compile_barebones_plan(
            contract=contract, repository_root=ledger.root.parent, template=template
        )
    except (CoreHarnessInvalidError, ProductProfileError, ValueError, OSError) as exc:
        raise EvidenceIntegrityError(
            "product build evidence invalid: protected recompile failed"
        ) from exc
    _require(profile.manifest_digest == profile_digest, "protected profile digest")
    _require(
        validation_payload.get("template_digest") == profile.template_digest
        and profile_digest in _blobs(validation)
        and _blob_object(ledger, validation, profile_digest) == profile.manifest,
        "protected manifest blob",
    )
    plan_blob = validation_payload.get("plan_blob_digest")
    _require(
        validation_payload.get("plan_digest") == plan.plan_digest
        and canonical_digest(_blob_object(ledger, validation, plan_blob))
        == canonical_digest(plan.as_dict()),
        "compiled plan blob",
    )
    graph_blob = validation_payload.get("task_graph_blob_digest")
    recorded_graph = _blob_object(ledger, validation, graph_blob)
    graph_mapping: dict[str, Any] = {
        key: recorded_graph[key]
        for key in ("plan_digest", "architecture_digest", "tasks")
        if key in recorded_graph
    }
    try:
        graph = compile_task_graph(
            plan,
            graph_mapping if recorded_graph.get("architecture_digest") is not None else None,
            protected_paths=tuple(proof.path for proof in template.proofs.values()),
        )
    except (TaskGraphError, ValueError) as exc:
        raise EvidenceIntegrityError(
            "product build evidence invalid: task graph recompile failed"
        ) from exc
    _require(
        canonical_digest(recorded_graph) == canonical_digest(graph.as_dict())
        and validation_payload.get("task_graph_digest") == graph.graph_digest,
        "task graph binding",
    )
    observed = [event for event in events if event.get("event_type") == "supervisor_observations"]
    _require(
        all(event.get("state") in {"BUILDING", "VERIFYING"} for event in observed),
        "supervisor observation state",
    )
    observations_events = [event for event in observed if event.get("state") == "VERIFYING"]
    if not check_events and not observations_events:
        latest = events[-1]
        _require(
            latest.get("state") in {"VALIDATED", "BUILDING"}
            or (
                latest.get("state") in {"HALTED", "STOPPED"}
                and _payload(latest).get("candidate_digest") is None
            ),
            "missing required checks",
        )
        return
    _require(bool(check_events), "missing required checks")
    _require(len(check_events) == len(observations_events), "required-check observation coverage")
    consumed: set[str] = set()
    for event in check_events:
        payload = _payload(event)
        report_blob = payload.get("evidence_digest")
        body = {key: value for key, value in payload.items() if key != "evidence_digest"}
        _require(
            isinstance(report_blob, str)
            and _blob_object(ledger, event, report_blob) == body
            and canonical_digest(body) == report_blob,
            "required-check report blob",
        )
        binding = payload.get("binding")
        _require(isinstance(binding, dict), "required-check binding")
        candidate_digest = cast(dict[str, Any], binding).get("candidate_digest")
        _require(isinstance(candidate_digest, str), "candidate identity")
        candidate_digest = cast(str, candidate_digest)
        source = _candidate(ledger, event, candidate_digest)
        obs_digest = payload.get("observation_evidence_digest")
        matching = [
            item
            for item in observations_events
            if _payload(item).get("evidence_digest") == obs_digest
        ]
        _require(
            len(matching) == 1 and isinstance(obs_digest, str) and obs_digest not in consumed,
            "missing or duplicate supervisor observation",
        )
        observed_event = matching[0]
        consumed.add(cast(str, obs_digest))
        _require(
            obs_digest in _blobs(event)
            and event.get("subject_digest") == contract_digest
            and event.get("state") == "VERIFYING"
            and type(payload.get("attempt")) is int
            and payload["attempt"] == _payload(observed_event).get("attempt"),
            "required-check event binding",
        )
        observations = _observations(
            ledger,
            observed_event,
            candidate_digest=candidate_digest,
            plan_digest=plan.plan_digest,
            contract_digest=cast(str, contract_digest),
            template_digest=profile.template_digest,
            criterion_ids=profile.criterion_ids,
        )
        verify_observation_predicates(plan, template, observations)
        security = _scanner_codes(source)
        check_evidence = {
            "source_files": _blob_object(ledger, event, candidate_digest),
            "observations": observations,
            "security_findings": list(security),
        }
        check_evidence_digest = canonical_digest(check_evidence)
        _require(
            check_evidence_digest in _blobs(event)
            and _blob_object(ledger, event, check_evidence_digest) == check_evidence,
            "required-check source evidence",
        )
        expected = evaluate_required_checks(
            profile,
            candidate_digest=candidate_digest,
            source_files=source,
            acceptance_observations=observations,
            security_findings=security,
        ).as_dict()
        expected["binding"]["plan_digest"] = plan.plan_digest
        expected["binding"]["task_graph_digest"] = graph.graph_digest
        expected["binding_digest"] = canonical_digest(expected["binding"])
        expected["attempt"] = payload["attempt"]
        expected["observation_evidence_digest"] = obs_digest
        tool_identity = payload.get("tool_identity")
        _require(
            isinstance(tool_identity, dict)
            and set(tool_identity) == {"python_version", "implementation", "interpreter_digest"}
            and isinstance(tool_identity["python_version"], list)
            and len(tool_identity["python_version"]) == 3
            and all(type(value) is int for value in tool_identity["python_version"])
            and tool_identity["implementation"] in {"cpython", "pypy"}
            and isinstance(tool_identity["interpreter_digest"], str)
            and _DIGEST.fullmatch(tool_identity["interpreter_digest"]) is not None,
            "tool identity shape",
        )
        expected["tool_identity"] = tool_identity
        _require(body == expected, "required-check semantic mismatch")
    _require(len(consumed) == len(observations_events), "orphaned supervisor observation")
    terminal = events[-1]
    terminal_candidate = _payload(terminal).get("candidate_digest")
    if terminal_candidate is not None:
        latest_check = max(check_events, key=lambda item: int(item.get("sequence", 0)))
        latest_binding = _payload(latest_check).get("binding")
        _require(
            isinstance(latest_binding, Mapping)
            and terminal_candidate == latest_binding.get("candidate_digest")
            and terminal_candidate in _blobs(terminal),
            "terminal candidate differs from latest required checks",
        )
