"""Four deterministic checks over run-owned observations, never an LLM verdict."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from pmpe.contracts.canonical import canonical_digest
from pmpe.evidence.process_gate_validation import BlobReader, negative_control_reasons
from pmpe.process_sources import raw_digest

if TYPE_CHECKING:
    from pmpe.barebones import Finding
    from pmpe.evidence.ledger import EvidenceLedger
    from pmpe.process_collection import RecordingSandbox


def criterion_evidence(
    results: Mapping[str, tuple[Finding, ...]], ids: Sequence[str]
) -> list[dict[str, Any]]:
    return [
        {
            "criterion_id": identifier,
            "status": "NOT_EVALUATED"
            if identifier not in results
            else "FAIL"
            if results[identifier]
            else "PASS",
            "findings": [asdict(item) for item in results.get(identifier, ())],
        }
        for identifier in ids
    ]


def negative_controls_result(
    binding: Mapping[str, Any],
    baseline: Sequence[Finding],
    controls: Sequence[Mapping[str, Any]],
    criterion_ids: Sequence[str],
    baseline_ids: set[str],
    read_blob: BlobReader,
) -> tuple[str, dict[str, Any]]:
    evidence = {
        "baseline_findings": [asdict(item) for item in baseline],
        "mutants": list(controls),
        "run_id": controls[0]["run_id"] if controls else "",
        "attempt": controls[0]["attempt"] if controls else 0,
    }
    reasons = negative_control_reasons(
        binding,
        evidence,
        criterion_ids=criterion_ids,
        baseline_ids=baseline_ids,
        read_blob=read_blob,
    )
    return ("FAIL" if reasons else "PASS"), {**evidence, "reasons": reasons}


def digest_boundaries_result(
    collector: RecordingSandbox,
    attempt: int,
    criterion_ids: Sequence[str],
    mutant_ids: Sequence[str],
) -> tuple[str, dict[str, Any]]:
    observations = collector.selected(collector.observations, attempt)
    records = collector.selected(collector.records, attempt)
    expected: list[tuple[str, str, int, str]] = [("command_before", "baseline", 0, "")]
    for identifier in criterion_ids:
        expected.extend((stage, "baseline", 0, identifier) for stage in ("before", "after"))
    expected.extend(
        [("command_after", "baseline", 0, ""), ("command_before", "candidate", attempt, "")]
    )
    for phase in ["candidate", *("mutant:" + identifier for identifier in mutant_ids)]:
        for identifier in criterion_ids:
            expected.extend((stage, phase, attempt, identifier) for stage in ("before", "after"))
    expected.extend(
        [("command_after", "candidate", attempt, ""), ("release_before", "candidate", attempt, "")]
    )
    actual = [
        (item["stage"], item["phase"], item["attempt"], item["criterion_id"])
        for item in observations
    ]
    reasons: list[str] = []
    if actual != expected:
        reasons.append("BOUNDARY_SEQUENCE_INCOMPLETE_OR_REORDERED")
    source_inventory = dict(collector.expected)
    process_inventory = {
        **source_inventory,
        **{
            "protected/" + path: raw_digest(payload)
            for path, payload in collector.protected.items()
        },
    }
    by_index = {item["process_index"]: item for item in records}
    for item in observations:
        inventory = process_inventory if item["stage"] in {"before", "after"} else source_inventory
        if (
            item["mismatches"]
            or item["expected_inventory_digest"] != canonical_digest(inventory)
            or item["observed_inventory_digest"] != canonical_digest(inventory)
            or item["checked"] != len(inventory)
        ):
            reasons.append("INVENTORY_IDENTITY_OR_DIGEST_MISMATCH")
        if item["stage"] in {"before", "after"}:
            record = by_index.get(item["process_index"])
            if record is None or any(
                item[key] != record[key] for key in ("run_id", "phase", "attempt", "criterion_id")
            ):
                reasons.append("PROCESS_IDENTITY_MISMATCH")
    return ("PASS" if not reasons else "FAIL"), {
        "reasons": sorted(set(reasons)),
        "observations": observations,
        "expected_boundaries": [list(item) for item in expected],
        "source_inventory": source_inventory,
        "protected_inventory": {
            "protected/" + path: raw_digest(payload)
            for path, payload in collector.protected.items()
        },
        "process_records": records,
    }


def generation_provenance_result(
    *,
    ledger: EvidenceLedger,
    snapshot: Mapping[str, bytes],
    origin: Mapping[str, bytes],
    process_records: list[dict[str, Any]],
    criterion_ids: Sequence[str],
    criterion_results: Mapping[str, tuple[Finding, ...]],
    attempt: int,
    generation_mode: str,
    provider_attestation: Mapping[str, str],
    provider_class: str,
    contract_digest: str,
) -> tuple[str, dict[str, Any]]:
    expected = dict(origin)
    coder_events: list[int] = []
    reasons: list[str] = []
    import json

    for event in ledger.verify():
        if event["event_type"] != "coder_completed" or event["payload"]["attempt"] > attempt:
            continue
        payload = event["payload"]
        request = json.loads(ledger.read_blob(payload["request_blob_digest"]))
        response = json.loads(ledger.read_blob(payload["response_blob_digest"]))
        request_body = {key: value for key, value in request.items() if key != "request_digest"}
        if (
            canonical_digest(request.get("contract")) != contract_digest
            or request.get("request_digest") != canonical_digest(request_body)
            or response.get("request_digest") != request.get("request_digest")
            or event["run_id"] != ledger.run_id
        ):
            reasons.append("CODER_REQUEST_BINDING_INVALID")
        for path, content in response["files"].items():
            expected[path] = content.encode("utf-8")
        coder_events.append(event["sequence"])
    if not coder_events:
        reasons.append("CODER_EVIDENCE_MISSING")
    if expected != snapshot:
        reasons.append("OUT_OF_BAND_CHANGE")
    observed = [
        record
        for record in process_records
        if record["phase"] == "candidate" and record["attempt"] == attempt
    ]
    if {record["criterion_id"] for record in observed} != set(criterion_ids) or set(
        criterion_results
    ) != set(criterion_ids):
        reasons.append("CRITERION_EVIDENCE_INCOMPLETE")
    for record in observed:
        if (
            not record.get("executed_argv")
            or any(key not in record for key in ("exit_code", "stdout_digest", "stderr_digest"))
            or record["run_id"] != ledger.run_id
        ):
            reasons.append("PROCESS_EVIDENCE_INCOMPLETE")
        else:
            ledger.read_blob(record["stdout_digest"])
            ledger.read_blob(record["stderr_digest"])
    # A label is an explicit attestation, not proof of a model behind the provider.
    fresh_attested = generation_mode == "fresh" and provider_attestation.get("kind") == "live_model"
    status = "FAIL" if reasons else "NOT_EVALUATED"
    return status, {
        "reasons": reasons
        if reasons
        else ["FRESH_GENERATION_NOT_MECHANICALLY_VERIFIED"]
        if fresh_attested
        else ["FRESH_MODEL_SESSION_NOT_ATTESTED"],
        "freshness_attested": fresh_attested,
        "freshness_verified": False,
        "generation_mode": generation_mode,
        "provider_attestation": dict(provider_attestation),
        "provider_class": provider_class,
        "attestation_limit": (
            "Provider identity and freshness are operator attestations; "
            "engine records cannot prove a live model."
        ),
        "coder_events": coder_events,
        "process_records": process_records,
        "origin_file_digests": {path: raw_digest(payload) for path, payload in origin.items()},
        "criterion_results": criterion_evidence(criterion_results, criterion_ids),
    }


def execution_disclosure_result(
    binding: Mapping[str, Any], disclosure: Mapping[str, Any]
) -> tuple[str, dict[str, Any]]:
    reasons: list[str] = []
    if disclosure["execution_profile_sha256"] != binding["execution_profile_sha256"]:
        reasons.append("PROFILE_DIGEST_MISMATCH")
    if (
        disclosure["full_isolation_claimed"] is not False
        or disclosure["readiness_scope"] == "general"
    ):
        reasons.append("UNSUPPORTED_ISOLATION_OR_READINESS_CLAIM")
    if disclosure["is_root"] != (disclosure["effective_uid"] == 0):
        reasons.append("ROOT_DISCLOSURE_INCONSISTENT")
    return ("FAIL" if reasons else "PASS"), {**disclosure, "reasons": reasons}
