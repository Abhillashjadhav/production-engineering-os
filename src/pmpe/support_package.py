"""Assemble and verify the monolithic customer-support reference package."""

from __future__ import annotations

import ast
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import Draft7Validator

from pmpe.contracts.canonical import canonical_digest, canonical_json_bytes, strict_loads
from pmpe.contracts.intake import contains_prohibited_secret
from pmpe.evidence.ledger import EvidenceIntegrityError, EvidenceLedger
from pmpe.quality.security_scan import contains_hardcoded_secret
from pmpe.repository.redaction import contains_known_credential

_EVIDENCE_SCHEMA_VERSION = "2.0.0-package"
_CONTRACT_SCHEMA_VERSION = "1.0.0"
_PACKAGE_STATE = "PACKAGE_READY"
_REFERENCE_VERIFICATION = {
    "forbidden_capability_tests": "PASS",
    "runtime_compile": "PASS",
    "runtime_dependencies": "STANDARD_LIBRARY_ONLY",
    "vulnerability_gate": "PASS_NO_THIRD_PARTY_RUNTIME_DEPENDENCIES",
}
_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "evidence_schema_version",
        "state",
        "state_vocabulary",
        "approval",
        "release_candidate",
        "contract_digest",
        "capabilities",
        "forbidden_capability_proofs",
        "ports",
        "files",
        "source_digest",
        "lockfile_digest",
        "sbom_digest",
        "verification",
        "package_subject_digest",
        "claims",
        "manifest_digest",
    }
)
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_SPDX_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "SPDXID",
        "creationInfo",
        "dataLicense",
        "documentNamespace",
        "name",
        "packages",
        "spdxVersion",
    ],
    "properties": {
        "SPDXID": {"const": "SPDXRef-DOCUMENT"},
        "creationInfo": {
            "type": "object",
            "required": ["created", "creators"],
            "properties": {
                "created": {"type": "string", "format": "date-time"},
                "creators": {"type": "array", "minItems": 1, "items": {"type": "string"}},
            },
            "additionalProperties": False,
        },
        "dataLicense": {"const": "CC0-1.0"},
        "documentNamespace": {"type": "string"},
        "name": {"type": "string"},
        "packages": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": [
                    "SPDXID",
                    "copyrightText",
                    "downloadLocation",
                    "filesAnalyzed",
                    "licenseConcluded",
                    "licenseDeclared",
                    "name",
                    "versionInfo",
                ],
                "properties": {
                    "SPDXID": {"type": "string"},
                    "copyrightText": {"type": "string"},
                    "downloadLocation": {"type": "string"},
                    "filesAnalyzed": {"type": "boolean"},
                    "licenseConcluded": {"type": "string"},
                    "licenseDeclared": {"type": "string"},
                    "name": {"type": "string"},
                    "versionInfo": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        "spdxVersion": {"const": "SPDX-2.3"},
    },
    "additionalProperties": False,
}

_REQUIRED_CAPABILITIES = frozenset(
    {
        "ticket_intake",
        "policy_bound_decision",
        "prioritization",
        "response_drafting",
        "human_escalation",
    }
)
_KNOWN_FORBIDDEN_CAPABILITIES = frozenset(
    {"autonomous_refund_payment", "credential_collection", "delete_customer_data"}
)
_FORBIDDEN_PROOFS = {
    "autonomous_refund_payment": (
        "tests/test_forbidden_capabilities.py::ForbiddenCapabilityTests::test_no_payment"
    ),
    "credential_collection": (
        "tests/test_forbidden_capabilities.py::ForbiddenCapabilityTests::test_no_credentials"
    ),
}
_DETERMINISTIC_ESCALATIONS = frozenset(
    {
        "missing_required_fact",
        "contradictory_facts",
        "forbidden_capability_attempt",
        "outside_policy_bounds",
    }
)
_PROOF_RUNNER = """import json, os, subprocess, sys, tempfile, time, urllib.request
capability = sys.argv[1]
emit = os.write
payload = json.loads(sys.stdin.buffer.read())
source = payload["app_source"].encode()
with tempfile.TemporaryDirectory(prefix="pmpe-pinned-runtime-") as directory:
    runtime_policy = dict(payload["policy"])
    base_threshold = float(runtime_policy["additional_confidence_below"])
    if capability == "policy_draft":
        runtime_policy["additional_confidence_below"] = 0.6 if base_threshold > 0.7 else 0.8
    for name, content in {
        "app.py": source,
        "recorded-corpus.json": json.dumps(payload["corpus"], sort_keys=True).encode(),
        "runtime-policy.json": json.dumps(runtime_policy, sort_keys=True).encode(),
    }.items():
        path = os.path.join(directory, name)
        with open(path, "xb") as handle:
            handle.write(content)
    documented = subprocess.Popen(
        [sys.executable, "-I", "app.py", "--port", "8080"],
        cwd=directory,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        documented_health = None
        documented_url = "http://127.0.0.1:8080/health"
        for _ in range(30):
            try:
                with urllib.request.urlopen(documented_url, timeout=0.1) as response:
                    documented_health = json.loads(response.read())
                assert documented.poll() is None
                break
            except Exception:
                if documented.poll() is not None:
                    raise SystemExit(9)
                time.sleep(0.02)
        assert documented_health == {"status":"healthy"}
    finally:
        documented.terminate()
        try:
            documented.wait(timeout=2)
        except subprocess.TimeoutExpired:
            documented.kill()
            documented.wait(timeout=2)
    port_file = os.path.join(directory, "verified-port")
    process = subprocess.Popen(
        [sys.executable, "-I", "app.py", "--port", "0", "--port-file", port_file],
        cwd=directory,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(50):
        try:
            with open(port_file, encoding="utf-8") as handle:
                port = int(handle.read())
            break
        except (FileNotFoundError, ValueError):
            if process.poll() is not None:
                raise SystemExit(8)
            time.sleep(0.02)
    else:
        raise SystemExit(8)
    base = "http://127.0.0.1:" + str(port)
    def request(path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(base + path, data=data)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=1) as response:
            assert response.status == 200
            return json.loads(response.read())
    try:
        for _ in range(50):
            try:
                health = request("/health")
                break
            except Exception:
                if process.poll() is not None:
                    raise SystemExit(8)
                time.sleep(0.02)
        else:
            raise SystemExit(8)
        assert health == {"status":"healthy"}
        assert request("/ready")["status"] == "ready"
        assert request("/version") == {"product":"customer-support-agent","version":"1.0.0"}
        tickets = {
            "autonomous_refund_payment": {
                "ticket_id":"F-1","text":"Transfer money to my wallet","facts":["request"]
            },
            "credential_collection": {
                "ticket_id":"F-2","text":"My password is secret","facts":["request"]
            },
            "ordinary_ticket": {
                "ticket_id":"O-1","text":"Damaged delivery","facts":["delivery_damage"]
            },
            "low_confidence": {
                "ticket_id":"L-" + str(os.getpid()),"text":"General question","facts":["request"]
            },
            "policy_draft": {
                "ticket_id":"P-" + str(os.getpid()),"text":"General question","facts":["request"]
            },
        }
        result = request("/tickets", tickets[capability])
    finally:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
if capability == "autonomous_refund_payment":
    assert b"payment_provider" not in source and b"execute_refund" not in source
    assert result["status"] == "NEEDS_HUMAN_DECISION"
    assert "forbidden_capability_attempt" in result["reasons"] and "action" not in result
elif capability == "credential_collection":
    assert b"OPENAI_API_KEY" not in source and b"DATABASE_URL" not in source
    assert result["status"] == "NEEDS_HUMAN_DECISION"
    assert "forbidden_capability_attempt" in result["reasons"] and "credentials" not in result
elif capability == "ordinary_ticket":
    expected = "NEEDS_HUMAN_DECISION" if 0.9 < base_threshold else "DRAFTED"
    assert result["status"] == expected
    if expected == "DRAFTED":
        assert result["priority"] == "high" and result["connector_mode"] == "fixture"
elif capability == "low_confidence":
    expected = "NEEDS_HUMAN_DECISION" if 0.7 < base_threshold else "DRAFTED"
    assert result["status"] == expected
    if expected == "NEEDS_HUMAN_DECISION":
        assert result["reasons"] == ["recorded_confidence_below_threshold"]
    assert result["confidence"] == 0.7
elif capability == "policy_draft":
    alternate = float(runtime_policy["additional_confidence_below"])
    expected = "NEEDS_HUMAN_DECISION" if 0.7 < alternate else "DRAFTED"
    assert result["status"] == expected
    assert result["confidence"] == 0.7
else:
    raise SystemExit(3)
emit(1, ("PMPE_PROOF_COMPLETE:" + capability).encode())
"""


class PackageContractError(ValueError):
    """The package contract or sealed bundle is malformed or inconsistent."""


@dataclass(frozen=True)
class SupportPackageContract:
    payload: Mapping[str, Any]
    digest: str


@dataclass(frozen=True)
class PackageResult:
    state: str
    bundle: Path
    manifest_digest: str


@dataclass(frozen=True)
class PackageApproval:
    authority: str
    receipt_digest: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class ReleaseCandidate:
    run_id: str
    candidate_digest: str
    head_event_digest: str
    files: Mapping[str, bytes]
    events: bytes
    blobs: Mapping[str, bytes]


def _exact_fields(value: object, expected: frozenset[str], subject: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise PackageContractError(f"{subject} must be an object")
    keys = frozenset(value)
    unknown = keys - expected
    missing = expected - keys
    if unknown:
        raise PackageContractError(f"{subject} has unknown field: {sorted(unknown)[0]}")
    if missing:
        raise PackageContractError(f"{subject} is missing field: {sorted(missing)[0]}")
    return value


def _string_set(value: object, subject: str) -> frozenset[str]:
    if (
        not isinstance(value, list)
        or not value
        or any(type(item) is not str or not _IDENTIFIER.fullmatch(item) for item in value)
        or len(value) != len(set(value))
    ):
        raise PackageContractError(f"{subject} must be a non-empty unique identifier array")
    return frozenset(value)


def load_support_package_contract(path: Path) -> SupportPackageContract:
    """Load one exact approved contract; prose and unknown fields fail closed."""
    try:
        raw = Path(path).read_bytes()
        payload = strict_loads(raw)
    except (OSError, UnicodeError, ValueError) as exc:
        raise PackageContractError("package contract is unreadable") from exc
    root = _exact_fields(
        payload,
        frozenset(
            {
                "schema_version",
                "contract_status",
                "approved_by",
                "product",
                "capabilities",
                "runtime",
                "limits",
                "escalation",
            }
        ),
        "contract",
    )
    if root["schema_version"] != _CONTRACT_SCHEMA_VERSION:
        raise PackageContractError("contract schema version is unsupported")
    if root["contract_status"] != "APPROVED" or not _IDENTIFIER.fullmatch(str(root["approved_by"])):
        raise PackageContractError("package contract is not approved by a valid authority")

    product = _exact_fields(
        root["product"],
        frozenset({"name", "product_type", "product_version"}),
        "product",
    )
    if product != {
        "name": "customer-support-agent",
        "product_type": "customer_support",
        "product_version": "1.0.0",
    }:
        raise PackageContractError("product identity or version is unsupported")

    capabilities = _exact_fields(
        root["capabilities"], frozenset({"required", "forbidden"}), "capabilities"
    )
    required = _string_set(capabilities["required"], "required capabilities")
    forbidden = _string_set(capabilities["forbidden"], "forbidden capabilities")
    unsupported_required = required - _REQUIRED_CAPABILITIES
    if unsupported_required:
        raise PackageContractError(
            f"unsupported required capability: {sorted(unsupported_required)[0]}"
        )
    if required != _REQUIRED_CAPABILITIES:
        raise PackageContractError("required capability set is incomplete")
    unsupported_forbidden = forbidden - _KNOWN_FORBIDDEN_CAPABILITIES
    if unsupported_forbidden:
        raise PackageContractError(
            f"unsupported forbidden capability: {sorted(unsupported_forbidden)[0]}"
        )
    missing_proof = forbidden - _FORBIDDEN_PROOFS.keys()
    if missing_proof:
        raise PackageContractError(
            f"forbidden capability lacks negative proof: {sorted(missing_proof)[0]}"
        )

    runtime = _exact_fields(
        root["runtime"],
        frozenset({"model_gateway", "ticket_repository", "ticket_connector"}),
        "runtime",
    )
    if runtime != {
        "model_gateway": "recorded",
        "ticket_repository": "memory",
        "ticket_connector": "fixture",
    }:
        raise PackageContractError("v1 supports only recorded/memory/fixture runtime modes")

    limits = _exact_fields(
        root["limits"],
        frozenset({"max_model_calls_per_ticket", "max_processing_seconds", "max_response_bytes"}),
        "limits",
    )
    for name, lower, upper in (
        ("max_model_calls_per_ticket", 1, 8),
        ("max_processing_seconds", 1, 120),
        ("max_response_bytes", 1024, 1_000_000),
    ):
        value = limits[name]
        if type(value) is not int or not lower <= value <= upper:
            raise PackageContractError(f"limit {name} is outside the supported bound")

    escalation = _exact_fields(
        root["escalation"],
        _DETERMINISTIC_ESCALATIONS | {"additional_confidence_below"},
        "escalation",
    )
    if any(escalation[name] is not True for name in _DETERMINISTIC_ESCALATIONS):
        raise PackageContractError("all deterministic escalation triggers are mandatory")
    confidence = escalation["additional_confidence_below"]
    if type(confidence) not in {int, float} or not 0 < float(confidence) < 1:
        raise PackageContractError("additional confidence trigger must be between zero and one")
    return SupportPackageContract(root, canonical_digest(root))


def load_package_approval(
    path: Path, contract: SupportPackageContract, expected_approver: str
) -> PackageApproval:
    try:
        payload = strict_loads(Path(path).read_bytes())
    except (OSError, UnicodeError, ValueError) as exc:
        raise PackageContractError("package approval receipt is unreadable") from exc
    receipt = _exact_fields(
        payload,
        frozenset(
            {
                "schema_version",
                "decision",
                "approved_by",
                "approved_contract_digest",
                "receipt_digest",
            }
        ),
        "approval receipt",
    )
    claimed = receipt["receipt_digest"]
    projection = dict(receipt)
    projection.pop("receipt_digest")
    if (
        receipt["schema_version"] != "1.0.0"
        or receipt["decision"] != "APPROVED"
        or receipt["approved_by"] != expected_approver
        or receipt["approved_by"] != contract.payload["approved_by"]
        or receipt["approved_contract_digest"] != contract.digest
        or type(claimed) is not str
        or not _DIGEST.fullmatch(claimed)
        or canonical_digest(projection) != claimed
    ):
        raise PackageContractError("package approval receipt is invalid or stale")
    return PackageApproval(expected_approver, claimed, receipt)


def _safe_candidate_path(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        bool(value)
        and "\\" not in value
        and not path.is_absolute()
        and path.as_posix() == value
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _load_release_candidate(
    evidence_root: Path,
    run_id: str,
    contract: SupportPackageContract,
    expected_head_digest: str | None = None,
) -> ReleaseCandidate:
    try:
        ledger = EvidenceLedger.open_existing(Path(evidence_root), run_id)
        events = tuple(ledger.verify())
    except (ValueError, EvidenceIntegrityError) as exc:
        raise PackageContractError("RELEASE_READY evidence is invalid") from exc
    if not events:
        raise PackageContractError("RELEASE_READY evidence is empty")
    validation_events = [
        event for event in events if event.get("event_type") == "contract_validated"
    ]
    if len(validation_events) != 1:
        raise PackageContractError("run has no verified release approval")
    validation = validation_events[0]
    validation_payload = validation.get("payload")
    validation_blobs = validation.get("blob_digests")
    if not isinstance(validation_payload, dict) or not isinstance(validation_blobs, list):
        raise PackageContractError("run has no verified release approval")
    approval = validation_payload.get("approval")
    contract_digest = validation_payload.get("contract_digest")
    if (
        not isinstance(approval, dict)
        or approval.get("status") != "VERIFIED"
        or not isinstance(approval.get("authority"), str)
        or not isinstance(approval.get("receipt_digest"), str)
        or not isinstance(approval.get("receipt_blob_digest"), str)
        or not isinstance(contract_digest, str)
        or validation.get("subject_digest") != contract_digest
        or contract_digest not in validation_blobs
        or approval["receipt_blob_digest"] not in validation_blobs
    ):
        raise PackageContractError("run has no verified release approval")
    try:
        release_contract = strict_loads(ledger.read_blob(contract_digest))
        release_receipt = strict_loads(ledger.read_blob(approval["receipt_blob_digest"]))
    except (ValueError, EvidenceIntegrityError) as exc:
        raise PackageContractError("run has no verified release approval") from exc
    if not isinstance(release_contract, dict) or not isinstance(release_receipt, dict):
        raise PackageContractError("run has no verified release approval")
    unsigned_receipt = dict(release_receipt)
    claimed_receipt_digest = unsigned_receipt.pop("receipt_digest", None)
    if (
        claimed_receipt_digest != approval["receipt_digest"]
        or canonical_digest(unsigned_receipt) != claimed_receipt_digest
        or release_receipt.get("decision") != "APPROVED"
        or release_receipt.get("approved_by") != approval["authority"]
        or approval["authority"] != contract.payload["approved_by"]
        or release_receipt.get("approved_contract_digest") != contract_digest
        or canonical_digest(release_contract) != contract_digest
        or contract_digest != contract.digest
    ):
        raise PackageContractError("run has no verified release approval")
    terminal = events[-1]
    payload = terminal.get("payload")
    blob_digests = terminal.get("blob_digests")
    if (
        terminal.get("event_type") != "release_ready"
        or terminal.get("state") != "RELEASE_READY"
        or terminal.get("subject_digest") != contract.digest
        or not isinstance(payload, dict)
        or not isinstance(blob_digests, list)
    ):
        raise PackageContractError("run has no sealed RELEASE_READY candidate")
    candidate_digest = payload.get("candidate_digest")
    if not isinstance(candidate_digest, str) or candidate_digest not in blob_digests:
        raise PackageContractError("release event does not bind a candidate manifest")
    try:
        candidate_manifest = strict_loads(ledger.read_blob(candidate_digest))
    except (ValueError, EvidenceIntegrityError) as exc:
        raise PackageContractError("release candidate manifest is invalid") from exc
    if set(candidate_manifest) != {"app.py", "package-contract-digest.txt"}:
        raise PackageContractError("v1 release candidate has an unsupported file surface")
    files: dict[str, bytes] = {}
    blobs: dict[str, bytes] = {}
    for name, digest in candidate_manifest.items():
        if (
            not isinstance(name, str)
            or not _safe_candidate_path(name)
            or not isinstance(digest, str)
            or digest not in blob_digests
        ):
            raise PackageContractError("release candidate file binding is invalid")
        try:
            content = ledger.read_blob(digest)
        except EvidenceIntegrityError as exc:
            raise PackageContractError("release candidate blob is invalid") from exc
        files[name] = content
        blobs[digest] = content
    manifest_bytes = ledger.read_blob(candidate_digest)
    blobs[candidate_digest] = manifest_bytes
    for event in events:
        referenced = event.get("blob_digests")
        if not isinstance(referenced, list):
            raise PackageContractError("release evidence blob inventory is malformed")
        for digest in referenced:
            if not isinstance(digest, str):
                raise PackageContractError("release evidence blob digest is malformed")
            try:
                blobs[digest] = ledger.read_blob(digest)
            except EvidenceIntegrityError as exc:
                raise PackageContractError("release evidence references an invalid blob") from exc
    if files["package-contract-digest.txt"] != (contract.digest + "\n").encode():
        raise PackageContractError("RELEASE_READY candidate is not bound to package contract")
    head = terminal.get("event_digest")
    if not isinstance(head, str) or not _DIGEST.fullmatch(head):
        raise PackageContractError("release evidence head is invalid")
    if expected_head_digest is not None and head != expected_head_digest:
        raise PackageContractError("release evidence does not match trusted expected head")
    return ReleaseCandidate(
        run_id,
        candidate_digest,
        head,
        files,
        ledger.events_path.read_bytes(),
        blobs,
    )


_RECORDED_CORPUS = {
    "schema_version": "1.0.0",
    "mode": "recorded",
    "responses": {
        "delivery_damage": {
            "draft": (
                "I’m sorry the item arrived damaged. "
                "A support specialist will review the replacement evidence."
            ),
            "confidence": 0.9,
            "priority": "high",
        },
        "general": {
            "draft": "Thank you for contacting support. A specialist will review your request.",
            "confidence": 0.7,
            "priority": "normal",
        },
    },
}

_APP_SOURCE = r'''"""Portable customer-support reference runtime; standard library only."""
from __future__ import annotations

import argparse
import json
import re
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CORPUS = globals().get("_VERIFIED_CORPUS") or json.loads(
    (ROOT / "recorded-corpus.json").read_text()
)
POLICY = globals().get("_VERIFIED_POLICY") or json.loads(
    (ROOT / "runtime-policy.json").read_text()
)
MEMORY: dict[str, dict[str, object]] = {}

def decide(payload: object) -> tuple[int, dict[str, object]]:
    if not isinstance(payload, dict) or set(payload) != {"ticket_id", "text", "facts"}:
        return 400, {"error": "ticket must contain exactly ticket_id, text, and facts"}
    ticket_id, text, facts = payload["ticket_id"], payload["text"], payload["facts"]
    if not isinstance(ticket_id, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", ticket_id
    ):
        return 400, {"error": "ticket_id is invalid"}
    if not isinstance(text, str) or not 0 < len(text.encode()) <= 4096:
        return 400, {"error": "ticket text is invalid"}
    if not isinstance(facts, list) or any(not isinstance(item, str) for item in facts):
        return 400, {"error": "facts must be an array of strings"}
    fact_set = set(facts)
    reasons = []
    if not fact_set:
        reasons.append("missing_required_fact")
    if {"refund_eligible", "final_sale"} <= fact_set:
        reasons.append("contradictory_facts")
    lowered = text.lower()
    if any(term in lowered for term in ("transfer money", "password", "api key")):
        reasons.append("forbidden_capability_attempt")
    amounts = [int(item) for item in re.findall(r"\$(\d+)", text)]
    if any(amount > 500 for amount in amounts):
        reasons.append("outside_policy_bounds")
    if reasons:
        result = {
            "ticket_id": ticket_id,
            "status": "NEEDS_HUMAN_DECISION",
            "reasons": sorted(set(reasons)),
            "model_mode": "recorded",
            "connector_mode": "fixture",
        }
    else:
        key = "delivery_damage" if "delivery_damage" in fact_set else "general"
        response = CORPUS["responses"][key]
        confidence = float(response["confidence"])
        if confidence < float(POLICY["additional_confidence_below"]):
            result = {
                "ticket_id": ticket_id,
                "status": "NEEDS_HUMAN_DECISION",
                "reasons": ["recorded_confidence_below_threshold"],
                "confidence": confidence,
                "model_mode": "recorded",
                "connector_mode": "fixture",
            }
        else:
            result = {
                "ticket_id": ticket_id,
                "status": "DRAFTED",
                "priority": response["priority"],
                "draft": response["draft"],
                "confidence": confidence,
                "model_mode": "recorded",
                "connector_mode": "fixture",
            }
    MEMORY[ticket_id] = result
    return 200, result

class Handler(BaseHTTPRequestHandler):
    def handle_one_request(self) -> None:
        self._request_deadline = time.monotonic() + float(
            POLICY["max_processing_seconds"]
        )

        def expire_request() -> None:
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        watchdog = threading.Timer(
            float(POLICY["max_processing_seconds"]), expire_request
        )
        watchdog.daemon = True
        watchdog.start()
        try:
            super().handle_one_request()
        finally:
            watchdog.cancel()

    def _read_body(self, length: int) -> bytes:
        body = bytearray()
        while len(body) < length:
            remaining_seconds = self._request_deadline - time.monotonic()
            if remaining_seconds <= 0:
                raise TimeoutError
            self.connection.settimeout(remaining_seconds)
            chunk = self.rfile.read1(min(16384, length - len(body)))
            if not chunk:
                raise ValueError
            body.extend(chunk)
        return bytes(body)

    def _json(self, status: int, payload: object) -> None:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json(200, {"status": "healthy"})
        elif self.path == "/ready":
            self._json(
                200,
                {
                    "status": "ready",
                    "ports": {
                        "model": "recorded",
                        "repository": "memory",
                        "connector": "fixture",
                    },
                },
            )
        elif self.path == "/version":
            self._json(200, {"product": "customer-support-agent", "version": "1.0.0"})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/tickets":
            self._json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 16384:
                raise ValueError
            payload = json.loads(self._read_body(length))
        except (ValueError, json.JSONDecodeError, TimeoutError):
            self._json(400, {"error": "invalid bounded JSON"})
            return
        status, result = decide(payload)
        self._json(status, result)

    def log_message(self, format: str, *args: object) -> None:
        print(
            json.dumps({"event": "http", "message": "request completed"}, sort_keys=True),
            flush=True,
        )

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--port-file", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    if args.port_file is not None:
        Path(args.port_file).write_text(str(server.server_address[1]), encoding="utf-8")
    server.serve_forever()

if __name__ == "__main__":
    main()
'''

_FORBIDDEN_TESTS = """from __future__ import annotations

import unittest
import types
from pathlib import Path


class ForbiddenCapabilityTests(unittest.TestCase):
    def source(self) -> str:
        return (Path(__file__).parents[1] / "app.py").read_text()

    def test_no_payment(self) -> None:
        source = self.source()
        self.assertNotIn("payment_provider", source)
        self.assertNotIn("execute_refund", source)
        app = self.load_app()
        status, result = app.decide(
            {
                "ticket_id": "FORBIDDEN-1",
                "text": "Transfer money to my wallet",
                "facts": ["request"],
            }
        )
        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "NEEDS_HUMAN_DECISION")
        self.assertIn("forbidden_capability_attempt", result["reasons"])
        self.assertNotIn("action", result)

    def test_no_credentials(self) -> None:
        source = self.source()
        self.assertNotIn("OPENAI_API_KEY", source)
        self.assertNotIn("DATABASE_URL", source)
        app = self.load_app()
        status, result = app.decide(
            {"ticket_id": "FORBIDDEN-2", "text": "My password is secret", "facts": ["request"]}
        )
        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "NEEDS_HUMAN_DECISION")
        self.assertIn("forbidden_capability_attempt", result["reasons"])
        self.assertNotIn("credentials", result)

    def load_app(self):
        path = Path(__file__).parents[1] / "app.py"
        module = types.SimpleNamespace()
        namespace = vars(module)
        namespace["__file__"] = str(path)
        namespace["__name__"] = "reference_support_app"
        exec(compile(path.read_text(), str(path), "exec"), namespace)
        return module


if __name__ == "__main__":
    unittest.main()
"""

_CONFIG_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "additionalProperties": False,
    "properties": {
        "host": {"type": "string"},
        "port": {"maximum": 65535, "minimum": 1, "type": "integer"},
    },
    "required": ["host", "port"],
    "title": "Customer support reference runtime configuration",
    "type": "object",
}

_DOCKERFILE = """FROM python:3.12.13-slim
WORKDIR /app
COPY app.py recorded-corpus.json runtime-policy.json ./
USER 65532:65532
EXPOSE 8080
CMD ["python", "app.py", "--host", "0.0.0.0", "--port", "8080"]
"""

_COMPOSE = """services:
  customer-support:
    build: .
    ports: ["8080:8080"]
    read_only: true
    tmpfs: ["/tmp"]
    security_opt: ["no-new-privileges:true"]
"""

_README = """# Customer support reference package

This package runs with in-memory storage, recorded model responses, and a fixture connector.
It requires no paid account and makes no live-model, vendor-connector, hosting, or production claim.

Run: `python app.py --port 8080`

Endpoints: `GET /health`, `GET /ready`, `GET /version`, and `POST /tickets`.
"""


def _spdx() -> dict[str, Any]:
    document = {
        "SPDXID": "SPDXRef-DOCUMENT",
        "creationInfo": {
            "created": "2026-08-27T00:00:00Z",
            "creators": ["Tool: pmpe-support-package-v1"],
        },
        "dataLicense": "CC0-1.0",
        "documentNamespace": "https://pmpe.local/spdx/customer-support-agent/1.0.0",
        "name": "customer-support-agent-sbom",
        "packages": [
            {
                "SPDXID": "SPDXRef-Package-customer-support-agent",
                "copyrightText": "NOASSERTION",
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": "NOASSERTION",
                "name": "customer-support-agent",
                "versionInfo": "1.0.0",
            }
        ],
        "spdxVersion": "SPDX-2.3",
    }
    Draft7Validator(_SPDX_SCHEMA, format_checker=Draft7Validator.FORMAT_CHECKER).validate(document)
    return document


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _file_digests(root: Path) -> dict[str, str]:
    if root.is_symlink() or not root.is_dir():
        raise PackageContractError("package root must be a real directory")
    files: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise PackageContractError("package contains a symbolic link")
        if path.is_dir():
            continue
        if not path.is_file():
            raise PackageContractError("package contains an unsupported filesystem entry")
        if path.relative_to(root).as_posix() != "manifest.json":
            files[path.relative_to(root).as_posix()] = (
                "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
            )
    return files


def _secret_scan(root: Path) -> None:
    patterns = (
        re.compile(rb"OPENAI_API_KEY\s*="),
        re.compile(rb"DATABASE_URL\s*="),
        re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        re.compile(rb"AKIA[0-9A-Z]{16}"),
        re.compile(rb"sk-[A-Za-z0-9_-]{20,}"),
    )
    for path in root.rglob("*"):
        if path.is_file():
            content = path.read_bytes()
            copied_evidence = path.relative_to(root).parts[:1] == ("release-evidence",)
            try:
                decoded = content.decode("utf-8")
            except UnicodeDecodeError as exc:
                if copied_evidence:
                    raise PackageContractError(
                        f"copied evidence is not UTF-8: {path.name}"
                    ) from exc
                decoded = content.decode("utf-8", errors="replace")
            if (
                any(pattern.search(content) for pattern in patterns)
                or contains_prohibited_secret(content)
                or contains_hardcoded_secret(decoded)
                or copied_evidence
                and contains_known_credential(decoded)
            ):
                raise PackageContractError(f"secret value pattern found in {path.name}")


def seal_support_release(
    contract_path: Path,
    approval_receipt_path: Path,
    evidence_root: Path,
    run_id: str,
    expected_approver: str,
) -> dict[str, str]:
    """Produce the canonical v1 RELEASE_READY evidence consumed by package build."""
    contract = load_support_package_contract(contract_path)
    approval = load_package_approval(approval_receipt_path, contract, expected_approver)
    try:
        EvidenceLedger.validate_run_id(run_id)
    except ValueError as exc:
        raise PackageContractError("release run id is invalid") from exc
    target_root = Path(evidence_root)
    target_run = target_root / ".pmpe" / "runs" / run_id

    def existing_result() -> dict[str, str]:
        candidate = _load_release_candidate(target_root, run_id, contract)
        if candidate.files != {
            "app.py": _APP_SOURCE.encode(),
            "package-contract-digest.txt": (contract.digest + "\n").encode(),
        }:
            raise PackageContractError("existing release run is not the canonical candidate")
        return {
            "candidate_digest": candidate.candidate_digest,
            "head_event_digest": candidate.head_event_digest,
            "run_id": run_id,
            "state": "RELEASE_READY",
        }

    if target_run.exists():
        return existing_result()
    app = _APP_SOURCE.encode()
    binding = (contract.digest + "\n").encode()
    with tempfile.TemporaryDirectory(prefix="pmpe-support-release-") as directory:
        staged = Path(directory)
        runtime_files = {
            "app.py": app,
            "recorded-corpus.json": canonical_json_bytes(_RECORDED_CORPUS),
            "runtime-policy.json": canonical_json_bytes(
                {
                    "additional_confidence_below": contract.payload["escalation"][
                        "additional_confidence_below"
                    ],
                    "max_processing_seconds": contract.payload["limits"]["max_processing_seconds"],
                }
            ),
        }
        for name, content in runtime_files.items():
            _write(staged / name, content)
        expected = {
            name: "sha256:" + hashlib.sha256(content).hexdigest()
            for name, content in runtime_files.items()
        }
        _run_reference_verification(
            staged, sorted(contract.payload["capabilities"]["forbidden"]), expected
        )
    if target_run.exists():
        return existing_result()
    target_root.parent.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(tempfile.mkdtemp(prefix=".pmpe-support-ledger-", dir=target_root.parent))
    try:
        ledger = EvidenceLedger(temporary_root, run_id)
        contract_blob = ledger.put_blob(canonical_json_bytes(contract.payload))
        receipt_blob = ledger.put_blob(canonical_json_bytes(approval.payload))
        ledger.append(
            event_type="contract_validated",
            state="VALIDATED",
            subject_digest=contract.digest,
            blob_digests=(contract_blob, receipt_blob),
            payload={
                "approval": {
                    "status": "VERIFIED",
                    "authority": approval.authority,
                    "receipt_digest": approval.receipt_digest,
                    "receipt_blob_digest": receipt_blob,
                },
                "contract_digest": contract_blob,
                "plan_digest": canonical_digest({"producer": "support-package-v1"}),
            },
        )
        app_digest = ledger.put_blob(app)
        binding_digest = ledger.put_blob(binding)
        candidate_manifest = {
            "app.py": app_digest,
            "package-contract-digest.txt": binding_digest,
        }
        candidate_digest = ledger.put_blob(canonical_json_bytes(candidate_manifest))
        terminal = ledger.append(
            event_type="release_ready",
            state="RELEASE_READY",
            subject_digest=contract.digest,
            blob_digests=(app_digest, binding_digest, candidate_digest),
            payload={"candidate_digest": candidate_digest},
        )
        tuple(ledger.verify())
        target_blobs = target_root / ".pmpe" / "blobs"
        target_runs = target_root / ".pmpe" / "runs"
        target_blobs.mkdir(parents=True, exist_ok=True)
        target_runs.mkdir(parents=True, exist_ok=True)
        for source in sorted(ledger.blobs_directory.iterdir()):
            destination = target_blobs / source.name
            if destination.exists():
                if destination.read_bytes() != source.read_bytes():
                    raise PackageContractError("release blob collision is invalid")
                continue
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{source.name}-", dir=target_blobs
            )
            os.close(descriptor)
            temporary_blob = Path(temporary_name)
            try:
                shutil.copyfile(source, temporary_blob)
                os.replace(temporary_blob, destination)
            finally:
                temporary_blob.unlink(missing_ok=True)
        if target_run.exists():
            return existing_result()
        os.rename(ledger.run_directory, target_run)
    except OSError as exc:
        if target_run.exists():
            return existing_result()
        raise PackageContractError("release ledger publication failed") from exc
    except EvidenceIntegrityError as exc:
        raise PackageContractError("release ledger publication failed") from exc
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)
    return {
        "candidate_digest": candidate_digest,
        "head_event_digest": str(terminal["event_digest"]),
        "run_id": run_id,
        "state": "RELEASE_READY",
    }


def _run_reference_verification(
    root: Path, forbidden: list[str], expected_files: Mapping[str, str]
) -> dict[str, Any]:
    try:
        app_source = (root / "app.py").read_bytes()
        corpus_source = (root / "recorded-corpus.json").read_bytes()
        policy_source = (root / "runtime-policy.json").read_bytes()
    except OSError as exc:
        raise PackageContractError("generated reference runtime is unreadable") from exc
    pinned = {
        "app.py": app_source,
        "recorded-corpus.json": corpus_source,
        "runtime-policy.json": policy_source,
    }
    if any(
        "sha256:" + hashlib.sha256(content).hexdigest() != expected_files.get(name)
        for name, content in pinned.items()
    ):
        raise PackageContractError("runtime inputs changed before immutable verification")
    try:
        syntax_tree = ast.parse(app_source, "app.py")
        compile(syntax_tree, "app.py", "exec")
        proof_input = canonical_json_bytes(
            {
                "app_source": app_source.decode(),
                "corpus": strict_loads(corpus_source),
                "policy": strict_loads(policy_source),
            }
        )
    except (UnicodeError, ValueError, SyntaxError) as exc:
        raise PackageContractError("generated reference runtime does not compile") from exc
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    imported_roots = {
        alias.name.partition(".")[0]
        for node in ast.walk(syntax_tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        str(node.module).partition(".")[0]
        for node in ast.walk(syntax_tree)
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module is not None
    }
    if any(name not in sys.stdlib_module_names for name in imported_roots):
        raise PackageContractError("generated runtime imports a non-standard-library dependency")
    unresolved_import_primitives = [
        node
        for node in ast.walk(syntax_tree)
        if isinstance(node, ast.Name)
        and node.id in {"__import__", "__builtins__", "builtins", "importlib"}
        or isinstance(node, ast.Constant)
        and node.value in {"__import__", "import_module"}
        or isinstance(node, ast.Attribute)
        and node.attr == "import_module"
        or isinstance(node, ast.Call)
        and (
            isinstance(node.func, ast.Name)
            and node.func.id == "__import__"
            or isinstance(node.func, ast.Attribute)
            and node.func.attr == "import_module"
        )
    ]
    if unresolved_import_primitives:
        raise PackageContractError("generated runtime contains an unresolved dynamic import")
    if app_source != _APP_SOURCE.encode():
        raise PackageContractError("release candidate runtime differs from canonical v1")
    proof_cases = [*sorted(forbidden), "ordinary_ticket", "low_confidence", "policy_draft"]
    for capability in proof_cases:
        completed = subprocess.run(  # nosec B603 - fixed interpreter and verifier-owned proof
            [
                os.fspath(Path(sys.executable).resolve()),
                "-I",
                "-c",
                _PROOF_RUNNER,
                capability,
            ],
            env=environment,
            input=proof_input,
            capture_output=True,
            check=False,
            timeout=10,
        )
        expected_receipt = f"PMPE_PROOF_COMPLETE:{capability}".encode()
        if completed.returncode != 0 or completed.stdout != expected_receipt:
            raise PackageContractError(f"forbidden-capability proof did not execute: {capability}")
    return dict(_REFERENCE_VERIFICATION)


def _populate_package(
    root: Path,
    contract: SupportPackageContract,
    approval: PackageApproval,
    candidate: ReleaseCandidate,
) -> None:
    for name, content in candidate.files.items():
        _write(root / name, content)
    _write(root / "recorded-corpus.json", canonical_json_bytes(_RECORDED_CORPUS) + b"\n")
    _write(
        root / "runtime-policy.json",
        canonical_json_bytes(
            {
                "additional_confidence_below": contract.payload["escalation"][
                    "additional_confidence_below"
                ],
                "max_processing_seconds": contract.payload["limits"]["max_processing_seconds"],
            }
        )
        + b"\n",
    )
    for name, content in {
        "config/schema.json": canonical_json_bytes(_CONFIG_SCHEMA) + b"\n",
        "tests/test_forbidden_capabilities.py": _FORBIDDEN_TESTS.encode(),
        "Dockerfile": _DOCKERFILE.encode(),
        "compose.yaml": _COMPOSE.encode(),
        "requirements.lock": b"# standard-library runtime; no packages\n",
        "README.md": _README.encode(),
        "sbom.spdx.json": canonical_json_bytes(_spdx()) + b"\n",
        "contract.json": canonical_json_bytes(contract.payload) + b"\n",
        "approval-receipt.json": canonical_json_bytes(approval.payload) + b"\n",
    }.items():
        _write(root / name, content)
    _write(
        root / "release-evidence" / ".pmpe" / "runs" / candidate.run_id / "events.jsonl",
        candidate.events,
    )
    for digest, content in candidate.blobs.items():
        _write(
            root / "release-evidence" / ".pmpe" / "blobs" / digest.removeprefix("sha256:"),
            content,
        )


def _package_manifest(
    contract: SupportPackageContract,
    approval: PackageApproval,
    candidate: ReleaseCandidate,
    files: Mapping[str, str],
) -> dict[str, Any]:
    forbidden = contract.payload["capabilities"]["forbidden"]
    manifest: dict[str, Any] = {
        "schema_version": "1.0.0",
        "evidence_schema_version": _EVIDENCE_SCHEMA_VERSION,
        "state": _PACKAGE_STATE,
        "state_vocabulary": {
            "candidate_terminal": "RELEASE_READY",
            "package_terminal": _PACKAGE_STATE,
        },
        "contract_digest": contract.digest,
        "release_candidate": {
            "run_id": candidate.run_id,
            "candidate_digest": candidate.candidate_digest,
            "head_event_digest": candidate.head_event_digest,
        },
        "approval": {
            "authority": approval.authority,
            "receipt_digest": approval.receipt_digest,
            "status": "VERIFIED",
        },
        "capabilities": contract.payload["capabilities"],
        "forbidden_capability_proofs": {
            item: _FORBIDDEN_PROOFS[item] for item in sorted(forbidden)
        },
        "ports": {
            "model_gateway": {
                "mode": "recorded",
                "corpus_digest": files["recorded-corpus.json"],
            },
            "ticket_repository": {"mode": "memory"},
            "ticket_connector": {"mode": "fixture"},
        },
        "files": files,
        "source_digest": canonical_digest(
            {name: digest for name, digest in files.items() if name.endswith(".py")}
        ),
        "lockfile_digest": files["requirements.lock"],
        "sbom_digest": files["sbom.spdx.json"],
        "verification": dict(_REFERENCE_VERIFICATION),
        "package_subject_digest": canonical_digest(files),
        "claims": {
            "recorded_mode_only": True,
            "live_model_quality": "NOT_PROVEN",
            "injection_resistance": "NOT_PROVEN",
            "vendor_connector": "NOT_PROVEN",
            "production_deployment": "OUT_OF_SCOPE",
            "container_reproducibility": "NOT_CLAIMED",
        },
    }
    manifest["manifest_digest"] = canonical_digest(manifest)
    return manifest


def assemble_support_package(
    contract_path: Path,
    approval_receipt_path: Path,
    release_evidence_root: Path,
    release_run_id: str,
    expected_release_head_digest: str,
    expected_approver: str,
    output: Path,
) -> PackageResult:
    """Assemble one content-addressed, reference-adapter-only v1 package."""
    contract = load_support_package_contract(contract_path)
    approval = load_package_approval(approval_receipt_path, contract, expected_approver)
    if not _DIGEST.fullmatch(expected_release_head_digest):
        raise PackageContractError("trusted expected release head is malformed")
    candidate = _load_release_candidate(
        release_evidence_root,
        release_run_id,
        contract,
        expected_release_head_digest,
    )
    if candidate.files != {
        "app.py": _APP_SOURCE.encode(),
        "package-contract-digest.txt": (contract.digest + "\n").encode(),
    }:
        raise PackageContractError("RELEASE_READY candidate is not the canonical v1 runtime")
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
    try:
        _populate_package(staged, contract, approval, candidate)
        _secret_scan(staged)
        forbidden = contract.payload["capabilities"]["forbidden"]
        files = _file_digests(staged)
        manifest = _package_manifest(contract, approval, candidate, files)
        _write(staged / "manifest.json", canonical_json_bytes(manifest) + b"\n")
        if destination.exists():
            if not destination.is_dir():
                raise PackageContractError(
                    "package output is not the requested deterministic build"
                )
            if not any(destination.iterdir()):
                destination.rmdir()
            else:
                expected_inventory = _file_digests(staged) | {
                    "manifest.json": "sha256:"
                    + hashlib.sha256((staged / "manifest.json").read_bytes()).hexdigest()
                }
                observed_inventory = _file_digests(destination) | {
                    "manifest.json": "sha256:"
                    + hashlib.sha256((destination / "manifest.json").read_bytes()).hexdigest()
                }
                if observed_inventory != expected_inventory:
                    raise PackageContractError(
                        "package output is not the requested deterministic build"
                    )
                return PackageResult(_PACKAGE_STATE, destination, str(manifest["manifest_digest"]))
        verification = _run_reference_verification(staged, forbidden, files)
        if verification != _REFERENCE_VERIFICATION:
            raise PackageContractError("reference verification result is inconsistent")
        verified = _verify_support_package(
            staged,
            expected_manifest_digest=str(manifest["manifest_digest"]),
            run_runtime_proof=False,
        )
        os.replace(staged, destination)
    except BaseException:
        shutil.rmtree(staged, ignore_errors=True)
        raise
    return PackageResult(
        state=verified.state,
        bundle=destination,
        manifest_digest=verified.manifest_digest,
    )


def _verify_support_package(
    bundle: Path, *, expected_manifest_digest: str, run_runtime_proof: bool
) -> PackageResult:
    """Verify exact files, structural mode/corpus binding, and manifest integrity."""
    root = Path(bundle)
    try:
        manifest = strict_loads((root / "manifest.json").read_bytes())
    except (OSError, UnicodeError, ValueError) as exc:
        raise PackageContractError("package manifest is unreadable") from exc
    if not isinstance(manifest, dict):
        raise PackageContractError("package manifest must be an object")
    if set(manifest) != _MANIFEST_FIELDS or manifest.get("schema_version") != "1.0.0":
        raise PackageContractError("package manifest schema is invalid")
    claimed_manifest_digest = manifest.get("manifest_digest")
    unsigned = dict(manifest)
    unsigned.pop("manifest_digest", None)
    if (
        manifest.get("state") != _PACKAGE_STATE
        or manifest.get("evidence_schema_version") != _EVIDENCE_SCHEMA_VERSION
        or not isinstance(claimed_manifest_digest, str)
        or not _DIGEST.fullmatch(claimed_manifest_digest)
        or canonical_digest(unsigned) != claimed_manifest_digest
    ):
        raise PackageContractError("package manifest digest or state is invalid")
    if not _DIGEST.fullmatch(expected_manifest_digest):
        raise PackageContractError("trusted expected manifest digest is malformed")
    if claimed_manifest_digest != expected_manifest_digest:
        raise PackageContractError("package manifest does not match the trusted expected digest")
    files = manifest.get("files")
    if not isinstance(files, dict) or any(
        type(name) is not str or type(digest) is not str or not _DIGEST.fullmatch(digest)
        for name, digest in files.items()
    ):
        raise PackageContractError("package file digest inventory is malformed")
    observed = _file_digests(root)
    if observed != files:
        raise PackageContractError("package file digest inventory does not match bundle")
    if (root / "recorded-corpus.json").read_bytes() != canonical_json_bytes(
        _RECORDED_CORPUS
    ) + b"\n":
        raise PackageContractError("recorded corpus differs from the trusted v1 corpus")
    if (root / "tests" / "test_forbidden_capabilities.py").read_bytes() != (
        _FORBIDDEN_TESTS.encode()
    ):
        raise PackageContractError("forbidden proof implementation is not trusted")
    corpus_digest = files.get("recorded-corpus.json")
    expected_ports = {
        "model_gateway": {"mode": "recorded", "corpus_digest": corpus_digest},
        "ticket_repository": {"mode": "memory"},
        "ticket_connector": {"mode": "fixture"},
    }
    if manifest.get("ports") != expected_ports:
        raise PackageContractError("runtime port binding is invalid")
    if manifest.get("package_subject_digest") != canonical_digest(files):
        raise PackageContractError("package subject digest is invalid")
    contract = load_support_package_contract(root / "contract.json")
    expected_policy = (
        canonical_json_bytes(
            {
                "additional_confidence_below": contract.payload["escalation"][
                    "additional_confidence_below"
                ],
                "max_processing_seconds": contract.payload["limits"]["max_processing_seconds"],
            }
        )
        + b"\n"
    )
    if (root / "runtime-policy.json").read_bytes() != expected_policy:
        raise PackageContractError("runtime policy differs from the approved contract")
    release = manifest.get("release_candidate")
    if (
        not isinstance(release, dict)
        or set(release) != {"run_id", "candidate_digest", "head_event_digest"}
        or not isinstance(release.get("run_id"), str)
    ):
        raise PackageContractError("package release candidate binding is malformed")
    candidate = _load_release_candidate(
        root / "release-evidence",
        str(release["run_id"]),
        contract,
        str(release["head_event_digest"]),
    )
    forbidden = contract.payload["capabilities"]["forbidden"]
    expected_claims = {
        "recorded_mode_only": True,
        "live_model_quality": "NOT_PROVEN",
        "injection_resistance": "NOT_PROVEN",
        "vendor_connector": "NOT_PROVEN",
        "production_deployment": "OUT_OF_SCOPE",
        "container_reproducibility": "NOT_CLAIMED",
    }
    expected_verification = (
        _run_reference_verification(root, forbidden, files)
        if run_runtime_proof
        else dict(_REFERENCE_VERIFICATION)
    )
    expected_source_digest = canonical_digest(
        {name: digest for name, digest in files.items() if name.endswith(".py")}
    )
    if (
        manifest.get("state_vocabulary")
        != {"candidate_terminal": "RELEASE_READY", "package_terminal": _PACKAGE_STATE}
        or manifest.get("contract_digest") != contract.digest
        or release
        != {
            "run_id": candidate.run_id,
            "candidate_digest": candidate.candidate_digest,
            "head_event_digest": candidate.head_event_digest,
        }
        or any((root / name).read_bytes() != content for name, content in candidate.files.items())
        or manifest.get("capabilities") != contract.payload["capabilities"]
        or manifest.get("forbidden_capability_proofs")
        != {item: _FORBIDDEN_PROOFS[item] for item in sorted(forbidden)}
        or manifest.get("source_digest") != expected_source_digest
        or manifest.get("lockfile_digest") != files.get("requirements.lock")
        or manifest.get("sbom_digest") != files.get("sbom.spdx.json")
        or manifest.get("claims") != expected_claims
        or manifest.get("verification") != expected_verification
    ):
        raise PackageContractError("package manifest derived claims are invalid")
    approval = manifest.get("approval")
    if (
        not isinstance(approval, dict)
        or set(approval) != {"authority", "receipt_digest", "status"}
        or approval.get("status") != "VERIFIED"
        or approval.get("authority") != contract.payload["approved_by"]
        or not _IDENTIFIER.fullmatch(str(approval.get("authority", "")))
        or not _DIGEST.fullmatch(str(approval.get("receipt_digest", "")))
    ):
        raise PackageContractError("package approval binding is malformed")
    verified_approval = load_package_approval(
        root / "approval-receipt.json", contract, str(approval["authority"])
    )
    if verified_approval.receipt_digest != approval["receipt_digest"]:
        raise PackageContractError("package approval receipt binding is invalid")
    _secret_scan(root)
    return PackageResult(_PACKAGE_STATE, root, claimed_manifest_digest)


def verify_support_package(bundle: Path, *, expected_manifest_digest: str) -> PackageResult:
    """Independently verify a sealed package, including its runtime proof."""
    return _verify_support_package(
        bundle,
        expected_manifest_digest=expected_manifest_digest,
        run_runtime_proof=True,
    )
