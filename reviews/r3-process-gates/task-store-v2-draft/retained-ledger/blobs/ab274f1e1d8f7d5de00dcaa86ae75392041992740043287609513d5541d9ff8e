"""API test templates (integration over real HTTP) for the stdlib stack.

Split from stdlib_tests.py (storage/auth tests live there); shares payload and
status helpers with that module.
"""

from __future__ import annotations

import json
import urllib.parse
from collections.abc import Callable

from pmpe.domain.models import Entity, MvpSpec
from pmpe.stacks import (
    auth_probe,
    capabilities_for,
    collection_route,
    entity_var,
    fr_id_for,
    frs_by_capability,
    has_auth,
    has_health,
    status_default,
)
from pmpe.stacks.stdlib_tests import (
    _changed_status,
    _entity_fr_ids,
    _Mapping,
    _mutable_field,
    _payload_with,
    _required_payload,
)


def _api_tests(spec: MvpSpec, mapping: _Mapping) -> str:
    path = "tests/integration/test_api.py"
    cls = "ApiTests"
    auth = has_auth(spec)
    covered: list[str] = []
    if has_health(spec):
        covered.append(frs_by_capability(spec, "health.check")[0].id)
    if auth:
        covered.append(frs_by_capability(spec, "auth.bearer_token")[0].id)
    for entity in spec.entities:
        covered.extend(_entity_fr_ids(spec, entity))

    def ref(test: str) -> str:
        return f"{path}::{cls}::{test}"

    token_default = '"test-token-123"' if auth else "None"
    lines = [
        '"""API tests over real HTTP (generated before implementation).',
        "",
        f"Covers: {', '.join(sorted(set(covered)))}",
        '"""',
        "",
        "import json",
        "import os",
        "import tempfile",
        "import threading",
        "import unittest",
        "import urllib.error",
        "import urllib.request",
        "",
        "from app.server import create_server",
        "",
        'TOKEN = "test-token-123"',
        "",
        "",
        f"class {cls}(unittest.TestCase):",
        "    def setUp(self):",
    ]
    if auth:
        lines += ['        os.environ["APP_TOKEN"] = TOKEN']
    lines += [
        "        self._tmp = tempfile.TemporaryDirectory()",
        "        self.server = create_server(",
        '            port=0, db_path=os.path.join(self._tmp.name, "test.db")',
        "        )",
        '        self.base = "http://127.0.0.1:%d" % self.server.server_address[1]',
        "        self._thread = threading.Thread(",
        "            target=self.server.serve_forever, daemon=True",
        "        )",
        "        self._thread.start()",
        "",
        "    def tearDown(self):",
        "        self.server.shutdown()",
        "        self.server.server_close()",
        "        if self.server.storage is not None:",
        "            self.server.storage.close()",
        "        self._tmp.cleanup()",
        "",
        f"    def _request(self, method, path, body=None, token={token_default}):",
        '        data = json.dumps(body).encode("utf-8") if body is not None else None',
        "        req = urllib.request.Request(self.base + path, data=data, method=method)",
        "        if token:",
        '            req.add_header("Authorization", "Bearer " + token)',
        "        if data is not None:",
        '            req.add_header("Content-Type", "application/json")',
        "        try:",
        "            with urllib.request.urlopen(req) as resp:",
        "                raw = resp.read()",
        "                return resp.status, json.loads(raw) if raw else None",
        "        except urllib.error.HTTPError as err:",
        "            raw = err.read()",
        "            return err.code, json.loads(raw) if raw else None",
    ]
    if has_health(spec):
        fr = frs_by_capability(spec, "health.check")[0].id
        mapping.add(fr, ref("test_health_returns_ok_without_token"))
        lines += [
            "",
            "    def test_health_returns_ok_without_token(self):",
            f'        """Covers: {fr} — health is public and reports ok."""',
            '        status, body = self._request("GET", "/health", token=None)',
            "        self.assertEqual(status, 200)",
            '        self.assertEqual(body["status"], "ok")',
        ]
    probe = auth_probe(spec)
    if auth and probe is not None:
        fr = frs_by_capability(spec, "auth.bearer_token")[0].id
        method, path_probe = probe
        mapping.add(fr, ref("test_missing_token_returns_401"))
        mapping.add(fr, ref("test_invalid_token_returns_401"))
        lines += [
            "",
            "    def test_missing_token_returns_401(self):",
            f'        """Covers: {fr} — negative case: no Authorization header."""',
            f'        status, body = self._request("{method}", "{path_probe}", token=None)',
            "        self.assertEqual(status, 401)",
            '        self.assertIn("error", body)',
            "",
            "    def test_invalid_token_returns_401(self):",
            f'        """Covers: {fr} — negative case: wrong token."""',
            f'        status, _ = self._request("{method}", "{path_probe}", token="wrong-token")',
            "        self.assertEqual(status, 401)",
        ]
    for entity in spec.entities:
        lines += _api_entity_tests(spec, entity, mapping, ref)
    lines += ["", "", 'if __name__ == "__main__":', "    unittest.main()"]
    return "\n".join(lines) + "\n"


def _api_entity_tests(
    spec: MvpSpec, entity: Entity, mapping: _Mapping, ref: Callable[[str], str]
) -> list[str]:
    caps = capabilities_for(spec, entity)
    var, route = entity_var(entity), collection_route(entity)
    payload = _required_payload(entity)
    required = [f.name for f in entity.fields if f.required]
    has_status = any(f.name == "status" for f in entity.fields)
    mut_field, mut_value = _mutable_field(entity)
    lines: list[str] = []

    if "entity.create" in caps:
        fr = fr_id_for(spec, entity, "entity.create")
        mapping.add(fr, ref(f"test_create_{var}_returns_201"))
        lines += [
            "",
            f"    def test_create_{var}_returns_201(self):",
            f'        """Covers: {fr} — create returns 201 with id and defaults."""',
            f'        status, body = self._request("POST", "{route}", {payload})',
            "        self.assertEqual(status, 201)",
            '        self.assertIsNotNone(body["id"])',
        ]
        if has_status:
            default = status_default(entity)
            if default is not None:
                lines += [f'        self.assertEqual(body["status"], {json.dumps(default)})']
            else:
                lines += ['        self.assertIsNone(body["status"])']
        if required:
            mapping.add(fr, ref(f"test_create_{var}_without_required_field_returns_400"))
            lines += [
                "",
                f"    def test_create_{var}_without_required_field_returns_400(self):",
                f'        """Covers: {fr} — negative case: missing required field."""',
                f'        status, body = self._request("POST", "{route}", {{}})',
                "        self.assertEqual(status, 400)",
                f'        self.assertEqual(body["error"]["field"], "{required[0]}")',
            ]
        falsy_field = next(
            (f for f in entity.fields if f.required and f.type in ("int", "bool")), None
        )
        if falsy_field is not None:
            falsy_value = "0" if falsy_field.type == "int" else "False"
            falsy_payload = _payload_with(entity, falsy_field.name, falsy_value)
            mapping.add(fr, ref(f"test_create_{var}_accepts_falsy_{falsy_field.name}"))
            lines += [
                "",
                f"    def test_create_{var}_accepts_falsy_{falsy_field.name}(self):",
                f'        """Covers: {fr} — edge case: falsy value for a required field '
                'is PRESENT, not missing."""',
                f'        status, body = self._request("POST", "{route}", {falsy_payload})',
                "        self.assertEqual(status, 201)",
            ]
    if "entity.list" in caps:
        fr = fr_id_for(spec, entity, "entity.list")
        mapping.add(fr, ref(f"test_list_{var}s_returns_all_newest_first"))
        lines += [
            "",
            f"    def test_list_{var}s_returns_all_newest_first(self):",
            f'        """Covers: {fr} — all rows, newest first."""',
            "        for _ in range(3):",
            f'            self._request("POST", "{route}", {payload})',
            f'        status, body = self._request("GET", "{route}")',
            "        self.assertEqual(status, 200)",
            "        self.assertEqual(len(body), 3)",
            '        ids = [row["id"] for row in body]',
            "        self.assertEqual(ids, sorted(ids, reverse=True))",
        ]
        default = status_default(entity)
        if has_status and default is not None and "entity.update" in caps:
            changed = _changed_status(entity)
            encoded_default = urllib.parse.quote(default, safe="")
            mapping.add(fr, ref(f"test_list_{var}s_filters_by_status"))
            lines += [
                "",
                f"    def test_list_{var}s_filters_by_status(self):",
                f'        """Covers: {fr} — ?status= filter."""',
                f'        _, kept = self._request("POST", "{route}", {payload})',
                f'        _, other = self._request("POST", "{route}", {payload})',
                f'        self._request("PATCH", "{route}/%d" % other["id"], '
                f'{{"status": {json.dumps(changed)}}})',
                f'        status, body = self._request("GET", "{route}?status={encoded_default}")',
                "        self.assertEqual(status, 200)",
                '        ids = [row["id"] for row in body]',
                '        self.assertIn(kept["id"], ids)',
                '        self.assertNotIn(other["id"], ids)',
            ]
    if "entity.read" in caps:
        fr = fr_id_for(spec, entity, "entity.read")
        mapping.add(fr, ref(f"test_read_{var}_returns_stored"))
        mapping.add(fr, ref(f"test_read_unknown_{var}_returns_404"))
        lines += [
            "",
            f"    def test_read_{var}_returns_stored(self):",
            f'        """Covers: {fr} — read returns the stored row."""',
            f'        _, created = self._request("POST", "{route}", {payload})',
            f'        status, body = self._request("GET", "{route}/%d" % created["id"])',
            "        self.assertEqual(status, 200)",
            '        self.assertEqual(body["id"], created["id"])',
            "",
            f"    def test_read_unknown_{var}_returns_404(self):",
            f'        """Covers: {fr} — negative case: unknown id."""',
            f'        status, _ = self._request("GET", "{route}/999999")',
            "        self.assertEqual(status, 404)",
        ]
    if "entity.update" in caps:
        fr = fr_id_for(spec, entity, "entity.update")
        mapping.add(fr, ref(f"test_update_{var}_persists_change"))
        mapping.add(fr, ref(f"test_update_{var}_unknown_field_returns_400"))
        lines += [
            "",
            f"    def test_update_{var}_persists_change(self):",
            f'        """Covers: {fr} — PATCH persists; a later read sees it."""',
            f'        _, created = self._request("POST", "{route}", {payload})',
            f'        status, body = self._request("PATCH", "{route}/%d" % created["id"], '
            f'{{"{mut_field}": "{mut_value}"}})',
            "        self.assertEqual(status, 200)",
            f'        _, read_back = self._request("GET", "{route}/%d" % created["id"])'
            if "entity.read" in caps
            else "        read_back = body",
            f'        self.assertEqual(read_back["{mut_field}"], "{mut_value}")',
            "",
            f"    def test_update_{var}_unknown_field_returns_400(self):",
            f'        """Covers: {fr} — negative case: unknown field is rejected."""',
            f'        _, created = self._request("POST", "{route}", {payload})',
            f'        status, body = self._request("PATCH", "{route}/%d" % created["id"], '
            '{"bogus_field": 1})',
            "        self.assertEqual(status, 400)",
            '        self.assertEqual(body["error"]["field"], "bogus_field")',
        ]
    if "entity.delete" in caps:
        fr = fr_id_for(spec, entity, "entity.delete")
        mapping.add(fr, ref(f"test_delete_{var}_returns_204_then_404"))
        read_back = (
            f'        status, _ = self._request("GET", "{route}/%d" % created["id"])\n'
            "        self.assertEqual(status, 404)"
            if "entity.read" in caps
            else "        pass"
        )
        lines += [
            "",
            f"    def test_delete_{var}_returns_204_then_404(self):",
            f'        """Covers: {fr} — delete then read-back fails."""',
            f'        _, created = self._request("POST", "{route}", {payload})',
            f'        status, _ = self._request("DELETE", "{route}/%d" % created["id"])',
            "        self.assertEqual(status, 204)",
            read_back,
        ]
    return lines
