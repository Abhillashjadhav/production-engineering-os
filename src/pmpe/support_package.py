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
from pathlib import Path
from typing import Any

from pmpe.contracts.canonical import canonical_digest, canonical_json_bytes, strict_loads

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
    if root["contract_status"] != "APPROVED" or not _IDENTIFIER.fullmatch(
        str(root["approved_by"])
    ):
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
        frozenset(
            {"max_model_calls_per_ticket", "max_processing_seconds", "max_response_bytes"}
        ),
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


_RECORDED_CORPUS = {
    "schema_version": "1.0.0",
    "mode": "recorded",
    "responses": {
        "delivery_damage": {
            "draft": (
                "I’m sorry the item arrived damaged. "
                "A support specialist will review the replacement evidence."
            ),
            "priority": "high",
        },
        "general": {
            "draft": "Thank you for contacting support. A specialist will review your request.",
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
        result = {
            "ticket_id": ticket_id,
            "status": "DRAFTED",
            "priority": response["priority"],
            "draft": response["draft"],
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

_FORBIDDEN_TESTS = '''from __future__ import annotations

import unittest
import importlib.util
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
        spec = importlib.util.spec_from_file_location("reference_support_app", path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


if __name__ == "__main__":
    unittest.main()
'''

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
COPY app.py recorded-corpus.json ./
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
    completed = subprocess.run(
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


def assemble_support_package(contract_path: Path, output: Path) -> PackageResult:
    """Assemble one content-addressed, reference-adapter-only v1 package."""
    contract = load_support_package_contract(contract_path)
    destination = Path(output)
    if destination.exists():
        if not destination.is_dir() or any(destination.iterdir()):
            raise PackageContractError("package output must be absent or an empty directory")
        destination.rmdir()
    destination.parent.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
    try:
        _write(staged / "app.py", _APP_SOURCE.encode())
        corpus_bytes = canonical_json_bytes(_RECORDED_CORPUS) + b"\n"
        _write(staged / "recorded-corpus.json", corpus_bytes)
        _write(staged / "config" / "schema.json", canonical_json_bytes(_CONFIG_SCHEMA) + b"\n")
        _write(staged / "tests" / "test_forbidden_capabilities.py", _FORBIDDEN_TESTS.encode())
        _write(staged / "Dockerfile", _DOCKERFILE.encode())
        _write(staged / "compose.yaml", _COMPOSE.encode())
        _write(staged / "requirements.lock", b"# standard-library runtime; no packages\n")
        _write(staged / "README.md", _README.encode())
        _write(staged / "sbom.spdx.json", canonical_json_bytes(_spdx()) + b"\n")
        _write(staged / "contract.json", canonical_json_bytes(contract.payload) + b"\n")
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


def verify_support_package(bundle: Path) -> PackageResult:
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
    _secret_scan(root)
    return PackageResult(_PACKAGE_STATE, root, claimed_manifest_digest)
