"""Closed, mechanical binding grammar for the four process obligations."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from typing import Any

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
PROVENANCE_REQUIREMENTS = [
    "request_blob",
    "response_blob",
    "candidate_equals_applied_responses",
    "process_record_per_criterion",
    "criterion_result_per_criterion",
]
DISCLOSURE_REQUIREMENTS = [
    "effective_uid",
    "is_root",
    "sandbox_class",
    "isolation_mode",
    "missing_isolations",
    "approval_receipt_authentication",
    "generation_mode",
    "real_sandbox_leg",
    "readiness_scope",
]


def _strings(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and bool(item.strip()) for item in value)
        and len(value) == len(set(value))
    )


def validate_process_binding(value: Any, criterion_ids: frozenset[str]) -> dict[str, Any]:
    """Reject unknown options rather than interpreting obligation descriptions."""
    if not isinstance(value, Mapping):
        raise ValueError("binding must be an object")
    kind = value.get("kind")
    if kind == "negative_controls":
        if set(value) != {"kind", "baseline", "required_failure_code", "mutants"}:
            raise ValueError("negative_controls requires baseline, failure code and mutants")
        if (
            value["baseline"]
            != {"event": "meaningful_red_confirmed", "required_failure_code": "ASSERTION_FAILED"}
            or value["required_failure_code"] != "ASSERTION_FAILED"
        ):
            raise ValueError("negative controls require meaningful assertion failures")
        mutants = value["mutants"]
        if not isinstance(mutants, list) or not mutants:
            raise ValueError("mutants must be a nonempty list")
        ids: set[str] = set()
        digests: set[str] = set()
        for mutant in mutants:
            if not isinstance(mutant, dict) or set(mutant) != {
                "id",
                "must_fail",
                "must_not_touch",
                "snapshot_digest",
            }:
                raise ValueError(
                    "mutant requires id, must_fail, must_not_touch and snapshot_digest"
                )
            identifier = mutant["id"]
            if not isinstance(identifier, str) or not identifier.strip() or identifier in ids:
                raise ValueError("mutant IDs must be nonempty and unique")
            ids.add(identifier)
            digest = mutant["snapshot_digest"]
            if not isinstance(digest, str) or not _DIGEST.fullmatch(digest) or digest in digests:
                raise ValueError("mutant snapshot digests must be exact SHA-256 and distinct")
            digests.add(digest)
            if not _strings(mutant["must_fail"]) or set(mutant["must_fail"]) - criterion_ids:
                raise ValueError("must_fail requires unique executable criterion IDs")
            if not _strings(mutant["must_not_touch"]):
                raise ValueError("must_not_touch requires path prefixes")
            if any(
                prefix.startswith("/") or ".." in prefix.split("/")
                for prefix in mutant["must_not_touch"]
            ):
                raise ValueError("must_not_touch requires relative path prefixes")
    elif kind == "digest_boundaries":
        if set(value) != {
            "kind",
            "source_manifest_digest",
            "per_check",
            "require_command_boundary",
            "require_release_boundary",
        }:
            raise ValueError("digest_boundaries requires explicit manifest and complete boundaries")
        if not isinstance(value["source_manifest_digest"], str) or not _DIGEST.fullmatch(
            value["source_manifest_digest"]
        ):
            raise ValueError("source_manifest_digest must be SHA-256")
        if (
            value["per_check"] != ["before", "after"]
            or value["require_command_boundary"] is not True
            or value["require_release_boundary"] is not True
        ):
            raise ValueError("all before/after, command and release boundaries are required")
    elif kind == "generation_provenance":
        if (
            set(value) != {"kind", "mode", "roles", "require"}
            or value["mode"] != "fresh"
            or value["roles"] != ["code"]
            or value["require"] != PROVENANCE_REQUIREMENTS
        ):
            raise ValueError("generation_provenance requires fresh code and all provenance checks")
    elif kind == "execution_disclosure":
        if set(value) != {"kind", "execution_profile_sha256", "required", "forbid"}:
            raise ValueError("execution_disclosure requires profile, complete fields and limits")
        digest = value["execution_profile_sha256"]
        if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
            raise ValueError("execution_profile_sha256 must be SHA-256")
        if value["required"] != DISCLOSURE_REQUIREMENTS or value["forbid"] != {
            "full_isolation_claimed": True,
            "readiness_scope": "general",
        }:
            raise ValueError("execution disclosure limits cannot be weakened")
    else:
        raise ValueError("unsupported process gate kind")
    return copy.deepcopy(dict(value))
