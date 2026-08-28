"""Small standard-library HTTP surface for connector-free guided PMOS use."""

from __future__ import annotations

import ipaddress
import json
from contextlib import suppress
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pmpe.domain.errors import ContractViolation, SpecError
from pmpe.guided.experience import GuidedExperience

MAX_REQUEST_BYTES = 6 * 1024 * 1024
STATIC_ROOT = Path(__file__).with_name("static")


class GuidedServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], experience: GuidedExperience) -> None:
        super().__init__(address, GuidedHandler)
        self.experience = experience


class GuidedHandler(BaseHTTPRequestHandler):
    server: GuidedServer

    def log_message(self, format: str, *args: Any) -> None:
        # Keep the runnable demo quiet unless the operator explicitly inspects its output.
        return

    def _headers(self, content_type: str, length: int, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'",
        )
        self.end_headers()

    def _json(self, payload: dict[str, Any], status: int = 200) -> None:
        encoded = (json.dumps(payload, sort_keys=True) + "\n").encode()
        self._headers("application/json; charset=utf-8", len(encoded), status)
        self.wfile.write(encoded)

    def _read_json(self) -> dict[str, Any]:
        host = self.headers.get("Host", "").split(":", 1)[0].strip("[]")
        if host not in {"127.0.0.1", "localhost"}:
            raise SpecError("guided local mode requires a loopback Host header")
        origin = self.headers.get("Origin")
        if origin is not None:
            parsed_origin = urlsplit(origin)
            if parsed_origin.hostname not in {"127.0.0.1", "localhost"}:
                raise SpecError("cross-origin guided writes are blocked")
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise SpecError("guided writes require application/json")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise SpecError("Content-Length must be an integer") from exc
        if length <= 0 or length > MAX_REQUEST_BYTES:
            raise SpecError("request body must be present and no larger than 6 MiB")
        try:
            value = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SpecError("request body must be a JSON object") from exc
        if not isinstance(value, dict):
            raise SpecError("request body must be a JSON object")
        return value

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path == "/api/health":
            self._json(
                {
                    "connector_mode": "disabled",
                    "status": "ok",
                    "contract_finalization_requires_approval": True,
                }
            )
            return
        if path == "/api/guided/questions":
            self._json(self.server.experience.questionnaire())
            return
        if path == "/api/workflows/catalog":
            self._json(self.server.experience.workflow_catalog())
            return
        names = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            "/styles.css": ("styles.css", "text/css; charset=utf-8"),
        }
        resource = names.get(path)
        if resource is None:
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        file_name, content_type = resource
        payload = (STATIC_ROOT / file_name).read_bytes()
        self._headers(content_type, len(payload))
        self.wfile.write(payload)

    def do_POST(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        try:
            payload = self._read_json()
            if path == "/api/guided/review":
                result = self.server.experience.review(payload.get("answers", {}))
            elif path == "/api/guided/approve":
                if payload.get("confirmed_exact_digest") is not True:
                    raise ContractViolation("explicit exact-digest confirmation is required")
                result = self.server.experience.approve(
                    expected_digest=str(payload.get("expected_digest", "")),
                    approver=str(payload.get("approver", "")),
                )
            elif path == "/api/guided/change-request":
                result = self.server.experience.create_change_request(payload)
            elif path == "/api/bundles/intake":
                result = self.server.experience.intake_canonical(
                    str(payload.get("bundle_text", "")),
                    str(payload.get("manifest_text", "")),
                )
            else:
                self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                return
        except (ContractViolation, SpecError, ValueError) as exc:
            self._json({"error": str(exc), "status": "BLOCKED"}, HTTPStatus.BAD_REQUEST)
            return
        except Exception:
            self._json(
                {"error": "the local request could not be completed", "status": "ERROR"},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )
            return
        self._json(result)


def serve(workspace: Path, host: str, port: int) -> None:
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise SpecError("guided local mode requires host 127.0.0.1") from exc
    if str(address) != "127.0.0.1":
        raise SpecError("guided local mode requires host 127.0.0.1")
    experience = GuidedExperience(workspace)
    with GuidedServer((host, port), experience) as server:
        print(f"PMOS guided experience: http://{host}:{server.server_port}")
        print(f"Local workspace: {experience.workspace}")
        print("Connector access: disabled")
        with suppress(KeyboardInterrupt):
            server.serve_forever()


__all__ = ["GuidedHandler", "GuidedServer", "serve"]
