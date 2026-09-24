"""Pure checks of retained process observations; no execution or freshness authority."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from pmpe.contracts.canonical import canonical_digest, strict_loads

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
BlobReader = Callable[[str], bytes]


def snapshot_digest(snapshot: Mapping[str, bytes]) -> str:
    return canonical_digest(
        {path: "sha256:" + hashlib.sha256(value).hexdigest() for path, value in snapshot.items()}
    )


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _blob(digest: Any, read_blob: BlobReader) -> bytes:
    _require(isinstance(digest, str) and bool(_DIGEST.fullmatch(digest)), "INVALID_BLOB_DIGEST")
    payload = read_blob(digest)
    _require("sha256:" + hashlib.sha256(payload).hexdigest() == digest, "BLOB_DIGEST_MISMATCH")
    return payload


def _object(digest: Any, read_blob: BlobReader) -> dict[str, Any]:
    value = strict_loads(_blob(digest, read_blob), "application/json")
    _require(isinstance(value, dict), "BLOB_NOT_OBJECT")
    return dict(value)


def observer_failure(value: Any) -> bool:
    """Observer markers apply to mutants, never to the intentionally broken baseline."""
    if isinstance(value, dict):
        if (
            value.get("invalid_json") is True
            or value.get("timeout") is True
            or value.get("timed_out") is True
            or value.get("exit_code") == "timeout"
        ):
            return True
        return any(observer_failure(item) for item in value.values())
    if isinstance(value, list):
        return any(observer_failure(item) for item in value)
    return False


def _validate_negative(
    binding: Mapping[str, Any],
    evidence: Mapping[str, Any],
    criterion_ids: Sequence[str],
    baseline_ids: set[str],
    read_blob: BlobReader,
) -> None:
    baseline = evidence["baseline_findings"]
    _require(isinstance(baseline, list), "BASELINE_NOT_MEANINGFUL_RED")
    _require(
        {item["subject_id"] for item in baseline} == baseline_ids
        and all(item["code"] == "ASSERTION_FAILED" for item in baseline),
        "BASELINE_NOT_MEANINGFUL_RED",
    )
    required = binding["mutants"]
    controls = evidence["mutants"]
    _require(isinstance(controls, list) and len(controls) == len(required), "MUTANT_SET_MISMATCH")
    _require(
        len({item["snapshot_digest"] for item in required}) == len(required), "MUTANTS_NOT_DISTINCT"
    )
    _require(
        [item["mutant_id"] for item in controls] == [item["id"] for item in required],
        "MUTANT_SET_MISMATCH",
    )
    for expected, control in zip(required, controls, strict=True):
        identifier = expected["id"]
        _require(
            control["mutant_digest"] == expected["snapshot_digest"], "MUTANT_IDENTITY_MISMATCH"
        )
        mutant = _object(control["mutant_digest"], read_blob)
        candidate = _object(control["candidate_digest"], read_blob)
        _require(bool(mutant) and set(mutant) == set(candidate), "MUTANT_INVENTORY_MISMATCH")
        for digest in (*mutant.values(), *candidate.values()):
            _blob(digest, read_blob)
        changed = sorted(path for path in mutant if mutant[path] != candidate[path])
        _require(bool(changed) and changed == control["changed_paths"], "INVALID_MUTATION")
        _require(
            not any(
                path.startswith(prefix) for path in changed for prefix in expected["must_not_touch"]
            ),
            "PROTECTED_MUTATION",
        )
        _require(
            control["invalid_mutation"] is False and control["error"] == "", "UNRELATED_FAILURE"
        )
        checks = control["criterion_results"]
        _require(
            [item["criterion_id"] for item in checks] == list(criterion_ids),
            "MUTANT_RESULTS_INCOMPLETE",
        )
        failed: set[str] = set()
        for check in checks:
            findings = check["findings"]
            _require(isinstance(findings, list), "MUTANT_FINDINGS_INVALID")
            _require(
                check["status"] == ("FAIL" if findings else "PASS"), "MUTANT_STATUS_CONTRADICTION"
            )
            _require(
                all(
                    item["code"] == "ASSERTION_FAILED"
                    and item["subject_id"] == check["criterion_id"]
                    for item in findings
                ),
                "UNRELATED_FAILURE",
            )
            if findings:
                failed.add(check["criterion_id"])
        _require(set(expected["must_fail"]).issubset(failed), "REQUIRED_ASSERTION_NOT_FAILED")
        records = control["process_records"]
        _require(
            [item["criterion_id"] for item in records] == list(criterion_ids),
            "MUTANT_PROCESS_EVIDENCE_INCOMPLETE",
        )
        for record in records:
            _require(
                record["phase"] == "mutant:" + identifier
                and record["run_id"] == evidence["run_id"] == control["run_id"]
                and record["attempt"] == evidence["attempt"] == control["attempt"]
                and bool(record["executed_argv"])
                and type(record["exit_code"]) is int
                and record["exit_code"] == 0
                and not record.get("error"),
                "MUTANT_PROCESS_FAILED",
            )
            output = strict_loads(_blob(record["stdout_digest"], read_blob), "application/json")
            stderr = _blob(record["stderr_digest"], read_blob)
            _require(
                not observer_failure(output)
                and b"Traceback (most recent call last):" not in stderr,
                "MUTANT_OBSERVER_CRASH_OR_TIMEOUT",
            )


def negative_control_reasons(
    binding: Mapping[str, Any],
    evidence: Mapping[str, Any],
    *,
    criterion_ids: Sequence[str],
    baseline_ids: set[str],
    read_blob: BlobReader,
) -> list[str]:
    try:
        _validate_negative(binding, evidence, criterion_ids, baseline_ids, read_blob)
    except (ValueError, KeyError, TypeError, AttributeError, OSError) as exc:
        return [str(exc) or "NEGATIVE_CONTROL_EVIDENCE_INVALID"]
    return []


def expected_boundaries(
    attempt: int,
    criterion_ids: Sequence[str],
    mutant_ids: Sequence[str],
) -> list[list[Any]]:
    expected: list[list[Any]] = [["command_before", "baseline", 0, ""]]
    for identifier in criterion_ids:
        expected.extend([stage, "baseline", 0, identifier] for stage in ("before", "after"))
    expected.extend(
        [["command_after", "baseline", 0, ""], ["command_before", "candidate", attempt, ""]]
    )
    for phase in ["candidate", *("mutant:" + identifier for identifier in mutant_ids)]:
        for identifier in criterion_ids:
            expected.extend([stage, phase, attempt, identifier] for stage in ("before", "after"))
    expected.extend(
        [["command_after", "candidate", attempt, ""], ["release_before", "candidate", attempt, ""]]
    )
    return expected


def _validate_boundaries(
    binding: Mapping[str, Any],
    evidence: Mapping[str, Any],
    criterion_ids: Sequence[str],
    bindings: Sequence[Mapping[str, Any]],
    read_blob: BlobReader,
    context: Mapping[str, str],
) -> None:
    _require(
        evidence["source_manifest_digest"] == binding["source_manifest_digest"],
        "SOURCE_MANIFEST_MISMATCH",
    )
    manifest = _object(binding["source_manifest_digest"], read_blob)
    freeze = _object(evidence["approval_freeze_digest"], read_blob)
    contract = _object(freeze["artifacts"]["contract"], read_blob)
    plan = _object(freeze["artifacts"]["plan"], read_blob)
    receipt = _object(freeze["artifacts"]["receipt"], read_blob)
    draft = _object(freeze["artifacts"]["draft"], read_blob)
    publisher_input = _object(freeze["artifacts"]["publisher_input"], read_blob)
    plan_body = {key: value for key, value in plan.items() if key != "plan_digest"}
    receipt_body = {key: value for key, value in receipt.items() if key != "receipt_digest"}
    _require(
        canonical_digest(contract)
        == context["contract_digest"]
        == plan["contract_digest"]
        == receipt["approved_contract_digest"],
        "APPROVAL_CONTRACT_CONTEXT_MISMATCH",
    )
    _require(
        plan["plan_digest"] == context["plan_digest"] == canonical_digest(plan_body),
        "APPROVAL_PLAN_CONTEXT_MISMATCH",
    )
    _require(
        receipt["receipt_digest"] == context["receipt_digest"] == canonical_digest(receipt_body),
        "APPROVAL_RECEIPT_CONTEXT_MISMATCH",
    )
    _require(
        canonical_digest(draft) == receipt["draft_digest"]
        and canonical_digest(publisher_input) == contract["source_digest"],
        "APPROVAL_SOURCE_CONTEXT_MISMATCH",
    )
    _require(
        freeze["artifacts"]["source_manifest"] == binding["source_manifest_digest"],
        "APPROVAL_SOURCE_MANIFEST_MISMATCH",
    )
    for value in bindings:
        if value["kind"] == "negative_controls":
            for mutant in value["mutants"]:
                _require(
                    freeze["artifacts"].get("mutant/" + mutant["id"]) == mutant["snapshot_digest"],
                    "APPROVAL_MUTANT_IDENTITY_MISMATCH",
                )
    source = evidence["source_inventory"]
    _require(
        source
        == {
            **manifest["artifacts"],
            **{"approval/" + key: value for key, value in freeze["artifacts"].items()},
        },
        "SOURCE_INVENTORY_MISMATCH",
    )
    _require(
        {"contract", "receipt", "draft", "plan", "source_manifest", "publisher_input"}.issubset(
            freeze["artifacts"]
        ),
        "APPROVAL_PACKET_INCOMPLETE",
    )
    for digest in source.values():
        _blob(digest, read_blob)
    protected = evidence["protected_inventory"]
    _require(
        isinstance(protected, dict) and all(key.startswith("protected/") for key in protected),
        "PROTECTED_INVENTORY_INVALID",
    )
    for digest in protected.values():
        _blob(digest, read_blob)
    mutant_ids = list(
        dict.fromkeys(
            item["id"]
            for value in bindings
            if value["kind"] == "negative_controls"
            for item in value["mutants"]
        )
    )
    expected = expected_boundaries(evidence["attempt"], criterion_ids, mutant_ids)
    observations = evidence["observations"]
    _require(evidence["expected_boundaries"] == expected, "BOUNDARY_OBLIGATIONS_MISMATCH")
    _require(
        [
            [item[key] for key in ("stage", "phase", "attempt", "criterion_id")]
            for item in observations
        ]
        == expected,
        "BOUNDARY_SEQUENCE_INCOMPLETE_OR_REORDERED",
    )
    records = evidence["process_records"]
    by_index = {item["process_index"]: item for item in records}
    _require(len(by_index) == len(records), "DUPLICATE_PROCESS_ID")
    checked_records: set[int] = set()
    for item in observations:
        inventory = {**source, **protected} if item["stage"] in {"before", "after"} else source
        _require(
            item["mismatches"] == []
            and item["expected_inventory_digest"]
            == canonical_digest(inventory)
            == item["observed_inventory_digest"]
            and type(item["checked"]) is int
            and item["checked"] == len(inventory),
            "INVENTORY_IDENTITY_OR_DIGEST_MISMATCH",
        )
        _require(item["run_id"] == evidence["run_id"], "BOUNDARY_RUN_MISMATCH")
        if item["stage"] in {"before", "after"}:
            record = by_index[item["process_index"]]
            _require(
                all(
                    item[key] == record[key]
                    for key in ("run_id", "phase", "attempt", "criterion_id")
                ),
                "PROCESS_IDENTITY_MISMATCH",
            )
            checked_records.add(item["process_index"])
    _require(checked_records == set(by_index), "UNBOUND_PROCESS_RECORD")
    _require(
        evidence["source_checks_status"] == "PASS" and not evidence.get("boundary_error"),
        "SOURCE_CHECKS_NOT_PASS",
    )


def _validate_disclosure(
    binding: Mapping[str, Any], evidence: Mapping[str, Any], read_blob: BlobReader
) -> None:
    _require(
        evidence["execution_profile_sha256"] == binding["execution_profile_sha256"],
        "PROFILE_DIGEST_MISMATCH",
    )
    profile = _object(binding["execution_profile_sha256"], read_blob)
    _require(
        evidence["full_isolation_claimed"] is False and evidence["readiness_scope"] != "general",
        "UNSUPPORTED_ISOLATION_OR_READINESS_CLAIM",
    )
    _require(
        type(evidence["effective_uid"]) is int
        and type(evidence["is_root"]) is bool
        and evidence["is_root"] == (evidence["effective_uid"] == 0),
        "ROOT_DISCLOSURE_INCONSISTENT",
    )
    _require(
        evidence["isolation_report_self_reported"] is True, "ISOLATION_ATTESTATION_UNDISCLOSED"
    )
    _require(
        evidence["sandbox_identity"]["class"] == evidence["sandbox_class"],
        "SANDBOX_IDENTITY_MISMATCH",
    )
    report = evidence["validated_isolation_report"]
    _require(
        report
        == {
            "mode": evidence["isolation_mode"],
            "missing_isolations": evidence["missing_isolations"],
            "full_isolation_claimed": False,
        },
        "ISOLATION_REPORT_CHANGED",
    )
    if report["mode"] == "authorized_host_fallback":
        _require(
            bool(report["missing_isolations"])
            and report["missing_isolations"]
            == profile["authorized_fallback"]["unavailable_additional_protections"],
            "FALLBACK_LIMITS_MISMATCH",
        )
    else:
        _require(
            report["mode"] == "bubblewrap"
            and evidence["sandbox_class"] == "pmpe.barebones.BubblewrapCandidateSandbox",
            "SANDBOX_IDENTITY_MISMATCH",
        )
    _require(
        evidence["real_sandbox_leg"]["status"] in {"ATTEMPTED", "BLOCKED", "NOT_ATTEMPTED"}
        and bool(evidence["real_sandbox_leg"]["reason"]),
        "SANDBOX_LEG_INVALID",
    )
    for key in ("approval_receipt_authentication", "isolation_report_limit", "tamper_limit"):
        _require(isinstance(evidence[key], str) and bool(evidence[key]), "DISCLOSURE_INCOMPLETE")


def validate_process_gate_evidence(
    binding: Mapping[str, Any],
    evidence: Mapping[str, Any],
    *,
    criterion_ids: Sequence[str],
    baseline_ids: set[str],
    read_blob: BlobReader,
    expected: Mapping[str, str],
    bindings: Sequence[Mapping[str, Any]] = (),
) -> None:
    """Raise on a claimed PASS that the retained facts cannot support. No owner authentication."""
    try:
        _require(evidence["reasons"] == [], "PROCESS_GATE_REASONS_NOT_EMPTY")
        _require(
            isinstance(evidence["run_id"], str)
            and bool(evidence["run_id"])
            and type(evidence["attempt"]) is int
            and evidence["attempt"] > 0,
            "PROCESS_RUN_IDENTITY_INVALID",
        )
        kind = binding["kind"]
        if kind == "negative_controls":
            for control in evidence["mutants"]:
                _require(
                    control["candidate_digest"] == expected["candidate_digest"]
                    and control["plan_digest"] == expected["plan_digest"],
                    "MUTANT_RELEASE_CONTEXT_MISMATCH",
                )
            _validate_negative(binding, evidence, criterion_ids, baseline_ids, read_blob)
        elif kind == "digest_boundaries":
            _validate_boundaries(binding, evidence, criterion_ids, bindings, read_blob, expected)
        elif kind == "execution_disclosure":
            _validate_disclosure(binding, evidence, read_blob)
        elif kind == "generation_provenance":
            raise ValueError("FRESH_GENERATION_NOT_MECHANICALLY_VERIFIED")
        else:
            raise ValueError("UNKNOWN_PROCESS_GATE_KIND")
    except (KeyError, TypeError, AttributeError, OSError, json.JSONDecodeError) as exc:
        raise ValueError("PROCESS_GATE_EVIDENCE_INVALID: " + str(exc)) from exc
