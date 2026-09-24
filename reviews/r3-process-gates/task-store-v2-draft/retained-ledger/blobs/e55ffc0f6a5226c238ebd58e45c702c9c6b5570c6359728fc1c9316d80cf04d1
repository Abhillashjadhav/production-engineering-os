"""API/server/readme templates for the python-stdlib-crud-api stack.

Split from stdlib_code.py (storage/auth live there) to honor the module size
budget; both halves share the naming helpers in pmpe.stacks.
"""

from __future__ import annotations

from pmpe.domain.models import MvpSpec
from pmpe.stacks import (
    capabilities_for,
    collection_route,
    entity_var,
    has_auth,
    has_health,
    table_name,
)
from pmpe.stacks.stdlib_code import py_str


def api_module(spec: MvpSpec) -> str:
    auth = has_auth(spec)
    lines = [
        '"""HTTP API: routing, request validation, JSON error contract."""',
        "",
        "import json",
        "import logging",
        "from http.server import BaseHTTPRequestHandler",
        "from urllib.parse import parse_qs, urlsplit",
        "",
    ]
    if auth:
        lines += ["from app import auth", ""]
    lines += [
        f"SERVICE_NAME = {py_str(spec.product_name)}",
        "logger = logging.getLogger(SERVICE_NAME.lower())",
        "",
        "",
        "class ApiHandler(BaseHTTPRequestHandler):",
        "",
        "    def log_message(self, fmt, *args):",
        '        logger.debug("%s " + fmt, self.address_string(), *args)',
        "",
        "    def _send_json(self, status, payload):",
        '        body = json.dumps(payload).encode("utf-8")',
        "        self.send_response(status)",
        '        self.send_header("Content-Type", "application/json")',
        '        self.send_header("Content-Length", str(len(body)))',
        "        self.end_headers()",
        "        self.wfile.write(body)",
        "",
        "    def _send_empty(self, status):",
        "        self.send_response(status)",
        '        self.send_header("Content-Length", "0")',
        "        self.end_headers()",
        "",
        "    def _read_body(self):",
        '        length = int(self.headers.get("Content-Length") or 0)',
        '        raw = self.rfile.read(length) if length else b""',
        "        if not raw:",
        "            return {}",
        "        try:",
        '            data = json.loads(raw.decode("utf-8"))',
        "        except (UnicodeDecodeError, ValueError):",
        "            return None",
        "        return data if isinstance(data, dict) else None",
        "",
        "    def _split_path(self):",
        "        parsed = urlsplit(self.path)",
        '        path = parsed.path.rstrip("/") or "/"',
        "        return path, parse_qs(parsed.query)",
        "",
        "    def _match_item(self, path, route):",
        '        prefix = route + "/"',
        "        if path.startswith(prefix):",
        "            tail = path[len(prefix):]",
        "            if tail.isdigit():",
        "                return int(tail)",
        "        return None",
        "",
        "    def _storage(self):",
        "        return self.server.storage",
    ]
    if auth:
        lines += [
            "",
            "    def _authorized(self):",
            '        token = auth.token_from_header(self.headers.get("Authorization"))',
            "        return auth.verify_token(token)",
            "",
            "    def _reject_unauthorized(self):",
            "        self._send_json(",
            '            401, {"error": {"message": "missing or invalid bearer token"}}',
            "        )",
        ]
    lines += _api_get(spec, auth)
    lines += _api_post(spec, auth)
    lines += _api_patch(spec, auth)
    lines += _api_delete(spec, auth)
    return "\n".join(lines) + "\n"


def _guard(auth: bool) -> list[str]:
    if not auth:
        return []
    return [
        "            if not self._authorized():",
        "                self._reject_unauthorized()",
        "                return",
    ]


def _api_get(spec: MvpSpec, auth: bool) -> list[str]:
    lines = ["", "    def do_GET(self):", "        path, query = self._split_path()"]
    if has_health(spec):
        lines += [
            '        if path == "/health":',
            '            self._send_json(200, {"status": "ok", "service": SERVICE_NAME})',
            "            return",
        ]
    for entity in spec.entities:
        caps = capabilities_for(spec, entity)
        var, route, table = entity_var(entity), collection_route(entity), table_name(entity)
        has_status = any(f.name == "status" for f in entity.fields)
        if "entity.list" in caps:
            lines += [f'        if path == "{route}":'] + _guard(auth)
            if has_status:
                lines += [
                    '            status = query.get("status", [None])[0]',
                    f"            self._send_json(200, self._storage().list_{table}"
                    "(status=status))",
                ]
            else:
                lines += [f"            self._send_json(200, self._storage().list_{table}())"]
            lines += ["            return"]
        if "entity.read" in caps:
            lines += (
                [
                    f'        {var}_id = self._match_item(path, "{route}")',
                    f"        if {var}_id is not None:",
                ]
                + _guard(auth)
                + [
                    f"            {var} = self._storage().get_{var}({var}_id)",
                    f"            if {var} is None:",
                    f'                self._send_json(404, {{"error": {{"message": '
                    f'"{var} not found"}}}})',
                    "            else:",
                    f"                self._send_json(200, {var})",
                    "            return",
                ]
            )
    lines += ['        self._send_json(404, {"error": {"message": "not found"}})']
    return lines


def _api_post(spec: MvpSpec, auth: bool) -> list[str]:
    creatable = [e for e in spec.entities if "entity.create" in capabilities_for(spec, e)]
    if not creatable:
        return []
    lines = ["", "    def do_POST(self):", "        path, _query = self._split_path()"]
    for entity in creatable:
        var, route = entity_var(entity), collection_route(entity)
        allowed = ", ".join(f'"{f.name}"' for f in entity.fields)
        required = [f.name for f in entity.fields if f.required]
        lines += (
            [f'        if path == "{route}":']
            + _guard(auth)
            + [
                "            body = self._read_body()",
                "            if body is None:",
                '                self._send_json(400, {"error": {"message": "invalid JSON body"}})',
                "                return",
                f"            allowed = ({allowed},)",
                "            unknown = sorted(k for k in body if k not in allowed)",
                "            if unknown:",
                "                self._send_json(",
                "                    400,",
                '                    {"error": {"field": unknown[0], "message": "unknown field"}},',
                "                )",
                "                return",
            ]
        )
        for name in required:
            lines += [
                # falsy values (0, False, "") are PRESENT; only None/blank-string is missing
                f'            value = body.get("{name}")',
                "            if value is None or (isinstance(value, str) and not value.strip()):",
                "                self._send_json(",
                "                    400,",
                f'                    {{"error": {{"field": "{name}", "message": '
                f'"{name} is required"}}}},',
                "                )",
                "                return",
            ]
        lines += [
            f"            created = self._storage().create_{var}(body)",
            "            self._send_json(201, created)",
            "            return",
        ]
    lines += ['        self._send_json(404, {"error": {"message": "not found"}})']
    return lines


def _api_patch(spec: MvpSpec, auth: bool) -> list[str]:
    updatable = [e for e in spec.entities if "entity.update" in capabilities_for(spec, e)]
    if not updatable:
        return []
    lines = ["", "    def do_PATCH(self):", "        path, _query = self._split_path()"]
    for entity in updatable:
        var, route = entity_var(entity), collection_route(entity)
        allowed = ", ".join(f'"{f.name}"' for f in entity.fields)
        lines += (
            [
                f'        {var}_id = self._match_item(path, "{route}")',
                f"        if {var}_id is not None:",
            ]
            + _guard(auth)
            + [
                "            body = self._read_body()",
                "            if body is None:",
                '                self._send_json(400, {"error": {"message": "invalid JSON body"}})',
                "                return",
                f"            allowed = ({allowed},)",
                "            unknown = sorted(k for k in body if k not in allowed)",
                "            if unknown:",
                "                self._send_json(",
                "                    400,",
                '                    {"error": {"field": unknown[0], "message": "unknown field"}},',
                "                )",
                "                return",
                f"            updated = self._storage().update_{var}({var}_id, body)",
                "            if updated is None:",
                f'                self._send_json(404, {{"error": {{"message": '
                f'"{var} not found"}}}})',
                "            else:",
                "                self._send_json(200, updated)",
                "            return",
            ]
        )
    lines += ['        self._send_json(404, {"error": {"message": "not found"}})']
    return lines


def _api_delete(spec: MvpSpec, auth: bool) -> list[str]:
    deletable = [e for e in spec.entities if "entity.delete" in capabilities_for(spec, e)]
    if not deletable:
        return []
    lines = ["", "    def do_DELETE(self):", "        path, _query = self._split_path()"]
    for entity in deletable:
        var, route = entity_var(entity), collection_route(entity)
        lines += (
            [
                f'        {var}_id = self._match_item(path, "{route}")',
                f"        if {var}_id is not None:",
            ]
            + _guard(auth)
            + [
                f"            if self._storage().delete_{var}({var}_id):",
                "                self._send_empty(204)",
                "            else:",
                f'                self._send_json(404, {{"error": {{"message": '
                f'"{var} not found"}}}})',
                "            return",
            ]
        )
    lines += ['        self._send_json(404, {"error": {"message": "not found"}})']
    return lines


def server_module(spec: MvpSpec) -> str:
    auth_check = ""
    if has_auth(spec):
        auth_check = """    if not os.environ.get("APP_TOKEN"):
        logger.error("APP_TOKEN environment variable is required; refusing to start")
        return 2
"""
    if spec.entities:
        storage_import = "\nfrom app.storage import Storage"
        storage_create = 'Storage(db_path or os.environ.get("APP_DB", "data.db"))'
        token_doc = "required" if has_auth(spec) else "not used (no auth capability)"
    else:
        # no entities -> no storage module is generated; server.storage stays None
        # so tests and the deployer can treat the attribute uniformly
        storage_import = ""
        storage_create = "None"
        token_doc = "required" if has_auth(spec) else "not used (no auth capability)"
    logger_name = py_str(spec.product_name.lower())
    return f'''"""Process entrypoint. Configuration comes from the environment:

- APP_TOKEN: bearer token ({token_doc})
- APP_DB:    SQLite database path (default: data.db)
- APP_PORT:  listen port (default: 8000)
"""

import logging
import os
import sys
from http.server import ThreadingHTTPServer

from app.api import ApiHandler{storage_import}

logger = logging.getLogger({logger_name})


def create_server(port=0, db_path=None):
    storage = {storage_create}
    bind = os.environ.get("APP_BIND", "127.0.0.1")
    server = ThreadingHTTPServer((bind, port), ApiHandler)
    server.storage = storage
    return server


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
{auth_check}    port = int(os.environ.get("APP_PORT", "8000"))
    server = create_server(port=port)
    logger.info("listening on http://127.0.0.1:%s", server.server_address[1])
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("shutting down")
    finally:
        server.server_close()
        if server.storage is not None:
            server.storage.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def readme(spec: MvpSpec) -> str:
    endpoints = []
    if has_health(spec):
        endpoints.append("- `GET /health` — service status (public)")
    for entity in spec.entities:
        caps = capabilities_for(spec, entity)
        route = collection_route(entity)
        if "entity.create" in caps:
            endpoints.append(f"- `POST {route}` — create")
        if "entity.list" in caps:
            endpoints.append(f"- `GET {route}` — list (newest first)")
        if "entity.read" in caps:
            endpoints.append(f"- `GET {route}/{{id}}` — read")
        if "entity.update" in caps:
            endpoints.append(f"- `PATCH {route}/{{id}}` — update")
        if "entity.delete" in caps:
            endpoints.append(f"- `DELETE {route}/{{id}}` — delete")
    auth_note = (
        "All endpoints except `/health` require `Authorization: Bearer $APP_TOKEN`.\n"
        "A leaked token must be rotated by restarting with a new APP_TOKEN value.\n"
        if has_auth(spec)
        else ""
    )
    return f"""# {spec.product_name}

{spec.problem_statement}

Generated by PM Production Engineering OS. Single-process JSON API,
SQLite persistence, no third-party runtime dependencies.

## Run

```bash
export APP_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
export APP_DB=data.db
export APP_PORT=8000
python3 -m app.server
```

## Endpoints

{chr(10).join(endpoints)}

{auth_note}
## Test

```bash
python3 -m unittest discover -s tests -t .
```

## Known limitations

- Single static token per deployment (single-user product by spec).
- Single process, no high-availability story (see deploy/ROLLBACK.md).
"""
