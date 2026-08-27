"""Assemble and verify the monolithic customer-support reference package."""

from __future__ import annotations

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

from pmpe.contracts.canonical import canonical_digest, canonical_json_bytes, strict_loads
from pmpe.evidence.ledger import EvidenceIntegrityError, EvidenceLedger

_EVIDENCE_SCHEMA_VERSION = "2.0.0-package"
_CONTRACT_SCHEMA_VERSION = "1.0.0"
_PACKAGE_STATE = "PACKAGE_READY"
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")

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
    evidence_root: Path, run_id: str, contract: SupportPackageContract
) -> ReleaseCandidate:
    try:
        ledger = EvidenceLedger.open_existing(Path(evidence_root), run_id)
        events = tuple(ledger.verify())
    except (ValueError, EvidenceIntegrityError) as exc:
        raise PackageContractError("RELEASE_READY evidence is invalid") from exc
    if not events:
        raise PackageContractError("RELEASE_READY evidence is empty")
    terminal = events[-1]
    payload = terminal.get("payload")
    blob_digests = terminal.get("blob_digests")
    if (
        terminal.get("event_type") != "release_ready"
        or terminal.get("state") != "RELEASE_READY"
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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CORPUS = json.loads((ROOT / "recorded-corpus.json").read_text())
POLICY = json.loads((ROOT / "runtime-policy.json").read_text())
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
            payload = json.loads(self.rfile.read(length))
        except (ValueError, json.JSONDecodeError):
            self._json(400, {"error": "invalid bounded JSON"})
            return
        status, result = decide(payload)
        self._json(status, result)

    def log_message(self, format: str, *args: object) -> None:
        print(json.dumps({"event": "http", "message": format % args}, sort_keys=True), flush=True)

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()

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
    return {
        "SPDXID": "SPDXRef-DOCUMENT",
        "creationInfo": {"creators": ["Tool: pmpe-support-package-v1"]},
        "dataLicense": "CC0-1.0",
        "documentNamespace": "https://pmpe.local/spdx/customer-support-agent/1.0.0",
        "name": "customer-support-agent-sbom",
        "packages": [
            {
                "SPDXID": "SPDXRef-Package-customer-support-agent",
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": True,
                "name": "customer-support-agent",
                "versionInfo": "1.0.0",
            }
        ],
        "spdxVersion": "SPDX-2.3",
    }


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _file_digests(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "manifest.json"
    }


def _secret_scan(root: Path) -> None:
    patterns = (
        re.compile(rb"OPENAI_API_KEY\s*="),
        re.compile(rb"DATABASE_URL\s*="),
        re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        re.compile(rb"sk-[A-Za-z0-9_-]{20,}"),
    )
    for path in root.rglob("*"):
        if path.is_file() and any(pattern.search(path.read_bytes()) for pattern in patterns):
            raise PackageContractError(f"secret value pattern found in {path.name}")


def _run_reference_verification(root: Path) -> dict[str, Any]:
    try:
        compile((root / "app.py").read_text(), "app.py", "exec")
    except (OSError, UnicodeError, SyntaxError) as exc:
        raise PackageContractError("generated reference runtime does not compile") from exc
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    completed = subprocess.run(  # nosec B603 - fixed interpreter and fixed arguments
        [
            os.fspath(Path(sys.executable).resolve()),
            "-m",
            "unittest",
            "discover",
            "-s",
            "tests",
            "-p",
            "test_*.py",
        ],
        cwd=root,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
        timeout=10,
    )
    if completed.returncode != 0:
        raise PackageContractError("forbidden-capability negative verification failed")
    return {
        "forbidden_capability_tests": "PASS",
        "runtime_compile": "PASS",
        "runtime_dependencies": "STANDARD_LIBRARY_ONLY",
        "vulnerability_gate": "PASS_NO_THIRD_PARTY_RUNTIME_DEPENDENCIES",
    }


def assemble_support_package(
    contract_path: Path,
    approval_receipt_path: Path,
    release_evidence_root: Path,
    release_run_id: str,
    expected_approver: str,
    output: Path,
) -> PackageResult:
    """Assemble one content-addressed, reference-adapter-only v1 package."""
    contract = load_support_package_contract(contract_path)
    approval = load_package_approval(approval_receipt_path, contract, expected_approver)
    candidate = _load_release_candidate(release_evidence_root, release_run_id, contract)
    destination = Path(output)
    if destination.exists():
        if not destination.is_dir() or any(destination.iterdir()):
            raise PackageContractError("package output must be absent or an empty directory")
        destination.rmdir()
    destination.parent.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
    try:
        for name, content in candidate.files.items():
            _write(staged / name, content)
        corpus_bytes = canonical_json_bytes(_RECORDED_CORPUS) + b"\n"
        _write(staged / "recorded-corpus.json", corpus_bytes)
        _write(
            staged / "runtime-policy.json",
            canonical_json_bytes(
                {
                    "additional_confidence_below": contract.payload["escalation"][
                        "additional_confidence_below"
                    ]
                }
            )
            + b"\n",
        )
        _write(staged / "config" / "schema.json", canonical_json_bytes(_CONFIG_SCHEMA) + b"\n")
        _write(staged / "tests" / "test_forbidden_capabilities.py", _FORBIDDEN_TESTS.encode())
        _write(staged / "Dockerfile", _DOCKERFILE.encode())
        _write(staged / "compose.yaml", _COMPOSE.encode())
        _write(staged / "requirements.lock", b"# standard-library runtime; no packages\n")
        _write(staged / "README.md", _README.encode())
        _write(staged / "sbom.spdx.json", canonical_json_bytes(_spdx()) + b"\n")
        _write(staged / "contract.json", canonical_json_bytes(contract.payload) + b"\n")
        _write(
            staged / "approval-receipt.json",
            canonical_json_bytes(approval.payload) + b"\n",
        )
        _write(
            staged / "release-evidence" / ".pmpe" / "runs" / candidate.run_id / "events.jsonl",
            candidate.events,
        )
        for digest, content in candidate.blobs.items():
            _write(
                staged / "release-evidence" / ".pmpe" / "blobs" / digest.removeprefix("sha256:"),
                content,
            )
        _secret_scan(staged)
        verification = _run_reference_verification(staged)
        files = _file_digests(staged)
        corpus_digest = files["recorded-corpus.json"]
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
                "model_gateway": {"mode": "recorded", "corpus_digest": corpus_digest},
                "ticket_repository": {"mode": "memory"},
                "ticket_connector": {"mode": "fixture"},
            },
            "files": files,
            "source_digest": canonical_digest(
                {name: digest for name, digest in files.items() if name.endswith(".py")}
            ),
            "lockfile_digest": files["requirements.lock"],
            "sbom_digest": files["sbom.spdx.json"],
            "verification": verification,
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
        _write(staged / "manifest.json", canonical_json_bytes(manifest) + b"\n")
        os.replace(staged, destination)
    except BaseException:
        shutil.rmtree(staged, ignore_errors=True)
        raise
    return verify_support_package(destination)


def verify_support_package(
    bundle: Path, *, expected_manifest_digest: str | None = None
) -> PackageResult:
    """Verify exact files, structural mode/corpus binding, and manifest integrity."""
    root = Path(bundle)
    try:
        manifest = strict_loads((root / "manifest.json").read_bytes())
    except (OSError, UnicodeError, ValueError) as exc:
        raise PackageContractError("package manifest is unreadable") from exc
    if not isinstance(manifest, dict):
        raise PackageContractError("package manifest must be an object")
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
    if expected_manifest_digest is not None and claimed_manifest_digest != expected_manifest_digest:
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
    ports = manifest.get("ports")
    corpus_digest = files.get("recorded-corpus.json")
    if not isinstance(ports, dict) or ports.get("model_gateway") != {
        "mode": "recorded",
        "corpus_digest": corpus_digest,
    }:
        raise PackageContractError("recorded corpus digest or model mode binding is invalid")
    if manifest.get("package_subject_digest") != canonical_digest(files):
        raise PackageContractError("package subject digest is invalid")
    contract = load_support_package_contract(root / "contract.json")
    release = manifest.get("release_candidate")
    if (
        not isinstance(release, dict)
        or set(release) != {"run_id", "candidate_digest", "head_event_digest"}
        or not isinstance(release.get("run_id"), str)
    ):
        raise PackageContractError("package release candidate binding is malformed")
    candidate = _load_release_candidate(root / "release-evidence", str(release["run_id"]), contract)
    forbidden = contract.payload["capabilities"]["forbidden"]
    expected_claims = {
        "recorded_mode_only": True,
        "live_model_quality": "NOT_PROVEN",
        "injection_resistance": "NOT_PROVEN",
        "vendor_connector": "NOT_PROVEN",
        "production_deployment": "OUT_OF_SCOPE",
        "container_reproducibility": "NOT_CLAIMED",
    }
    expected_verification = _run_reference_verification(root)
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
        or approval.get("status") != "VERIFIED"
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
