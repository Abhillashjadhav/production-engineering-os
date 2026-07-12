"""Test templates for the python-stdlib-crud-api stack.

Generated BEFORE implementation (workflow step 6 vs 8). Every test carries a
``Covers: FR-xxx`` marker; the mapping returned alongside the files feeds the
traceability report. Negative and edge cases (401/400/404, persistence across
restart) are generated wherever the capability exists.
"""

from __future__ import annotations

from pmpe.domain.models import Entity, GeneratedFile, GeneratedTests, MvpSpec
from pmpe.stacks import (
    capabilities_for,
    collection_route,
    entity_var,
    fr_id_for,
    frs_by_capability,
    has_auth,
    has_health,
    table_name,
)

_SAMPLE_VALUES = {"string": '"sample {name}"', "text": '"sample {name}"', "int": "1",
                  "bool": "True", "timestamp": '"2026-01-01T00:00:00+00:00"'}


def _required_payload(entity: Entity) -> str:
    parts = []
    for f in entity.fields:
        if f.required:
            value = _SAMPLE_VALUES.get(f.type, '"sample"').format(name=f.name)
            parts.append(f'"{f.name}": {value}')
    return "{" + ", ".join(parts) + "}"


def _mutable_field(entity: Entity) -> tuple[str, str]:
    """Field used by update tests: prefer status -> 'done', else first string field."""
    for f in entity.fields:
        if f.name == "status":
            return "status", "done"
    for f in entity.fields:
        if f.type in ("string", "text"):
            return f.name, "updated value"
    return entity.fields[0].name, "updated value"


class _Mapping:
    def __init__(self) -> None:
        self.by_requirement: dict[str, list[str]] = {}

    def add(self, fr_id: str, test_ref: str) -> None:
        if fr_id:
            self.by_requirement.setdefault(fr_id, []).append(test_ref)


def generate_tests(spec: MvpSpec) -> GeneratedTests:
    mapping = _Mapping()
    files: list[GeneratedFile] = [
        GeneratedFile("tests/__init__.py", "", "test"),
        GeneratedFile("tests/unit/__init__.py", "", "test"),
        GeneratedFile("tests/integration/__init__.py", "", "test"),
    ]
    if spec.entities:
        files.append(
            GeneratedFile("tests/unit/test_storage.py", _storage_tests(spec, mapping), "test")
        )
    if has_auth(spec):
        files.append(
            GeneratedFile("tests/unit/test_auth.py", _auth_tests(spec, mapping), "test")
        )
    files.append(
        GeneratedFile("tests/integration/test_api.py", _api_tests(spec, mapping), "test")
    )
    return GeneratedTests(files=files, tests_by_requirement=mapping.by_requirement)


# --- unit: storage --------------------------------------------------------------------


def _storage_tests(spec: MvpSpec, mapping: _Mapping) -> str:
    path = "tests/unit/test_storage.py"
    covered = sorted({fr for e in spec.entities for fr in _entity_fr_ids(spec, e)})
    lines = [
        '"""Storage-layer tests (generated before implementation).',
        "",
        f"Covers: {', '.join(covered)}",
        '"""',
        "",
        "import os",
        "import tempfile",
        "import unittest",
        "",
        "from app.storage import Storage",
        "",
    ]
    for entity in spec.entities:
        lines += _storage_entity_class(spec, entity, mapping, path)
    lines += ["", "", 'if __name__ == "__main__":', "    unittest.main()"]
    return "\n".join(lines) + "\n"


def _entity_fr_ids(spec: MvpSpec, entity: Entity) -> list[str]:
    return [
        fr.id
        for fr in spec.functional_requirements
        if fr.entity == entity.name and fr.capability.startswith("entity.")
    ]


def _storage_entity_class(
    spec: MvpSpec, entity: Entity, mapping: _Mapping, path: str
) -> list[str]:
    caps = capabilities_for(spec, entity)
    var, table = entity_var(entity), table_name(entity)
    cls = f"{entity.name}StorageTests"
    payload = _required_payload(entity)
    has_status = any(f.name == "status" for f in entity.fields)
    mut_field, mut_value = _mutable_field(entity)

    def ref(test: str) -> str:
        return f"{path}::{cls}::{test}"

    lines = [
        "",
        f"class {cls}(unittest.TestCase):",
        "    def setUp(self):",
        "        self._tmp = tempfile.TemporaryDirectory()",
        '        self.db_path = os.path.join(self._tmp.name, "test.db")',
        "        self.storage = Storage(self.db_path)",
        "",
        "    def tearDown(self):",
        "        self.storage.close()",
        "        self._tmp.cleanup()",
    ]
    if "entity.create" in caps:
        fr = fr_id_for(spec, entity, "entity.create")
        for test in (f"test_create_{var}_assigns_id", f"test_created_{var}_persists_across_reconnect"):
            mapping.add(fr, ref(test))
        default_check = ""
        if has_status:
            default_field = next(f for f in entity.fields if f.name == "status")
            default_check = (
                f'        self.assertEqual(created["status"], "{default_field.default or "open"}")\n'
            )
        lines += [
            "",
            f"    def test_create_{var}_assigns_id(self):",
            f'        """Covers: {fr} — create assigns id and defaults."""',
            f"        created = self.storage.create_{var}({payload})",
            '        self.assertIsNotNone(created["id"])',
            default_check.rstrip("\n") if default_check else "        self.assertTrue(created)",
            "",
            f"    def test_created_{var}_persists_across_reconnect(self):",
            f'        """Covers: {fr} — data survives a restart (reliability NFR)."""',
            f"        created = self.storage.create_{var}({payload})",
            "        self.storage.close()",
            "        reopened = Storage(self.db_path)",
            "        try:",
            f'            self.assertIsNotNone(reopened.get_{var}(created["id"]))',
            "        finally:",
            "            reopened.close()",
            "            self.storage = Storage(self.db_path)",
        ]
    if "entity.list" in caps:
        fr = fr_id_for(spec, entity, "entity.list")
        mapping.add(fr, ref(f"test_list_{table}_newest_first"))
        lines += [
            "",
            f"    def test_list_{table}_newest_first(self):",
            f'        """Covers: {fr} — list returns newest first."""',
            "        for _ in range(3):",
            f"            self.storage.create_{var}({payload})",
            f'        ids = [row["id"] for row in self.storage.list_{table}()]',
            "        self.assertEqual(ids, sorted(ids, reverse=True))",
        ]
        if has_status:
            mapping.add(fr, ref(f"test_list_{table}_filters_by_status"))
            lines += [
                "",
                f"    def test_list_{table}_filters_by_status(self):",
                f'        """Covers: {fr} — optional status filter."""',
                f"        kept = self.storage.create_{var}({payload})",
                f"        other = self.storage.create_{var}({payload})",
                f'        self.storage.update_{var}(other["id"], {{"status": "done"}})'
                if "entity.update" in caps
                else f"        _ = other",
                f'        rows = self.storage.list_{table}(status="open")',
                f'        self.assertIn(kept["id"], [row["id"] for row in rows])',
            ]
            if "entity.update" in caps:
                lines += [
                    f'        self.assertNotIn(other["id"], [row["id"] for row in rows])',
                ]
    if "entity.read" in caps:
        fr = fr_id_for(spec, entity, "entity.read")
        mapping.add(fr, ref(f"test_get_{var}_unknown_returns_none"))
        lines += [
            "",
            f"    def test_get_{var}_unknown_returns_none(self):",
            f'        """Covers: {fr} — negative case: unknown id."""',
            f"        self.assertIsNone(self.storage.get_{var}(999999))",
        ]
    if "entity.update" in caps:
        fr = fr_id_for(spec, entity, "entity.update")
        mapping.add(fr, ref(f"test_update_{var}_changes_field"))
        mapping.add(fr, ref(f"test_update_{var}_unknown_returns_none"))
        lines += [
            "",
            f"    def test_update_{var}_changes_field(self):",
            f'        """Covers: {fr} — update persists the change."""',
            f"        created = self.storage.create_{var}({payload})",
            f'        updated = self.storage.update_{var}(created["id"], '
            f'{{"{mut_field}": "{mut_value}"}})',
            f'        self.assertEqual(updated["{mut_field}"], "{mut_value}")',
            "",
            f"    def test_update_{var}_unknown_returns_none(self):",
            f'        """Covers: {fr} — negative case: unknown id."""',
            f'        self.assertIsNone(self.storage.update_{var}(999999, '
            f'{{"{mut_field}": "{mut_value}"}}))',
        ]
    if "entity.delete" in caps:
        fr = fr_id_for(spec, entity, "entity.delete")
        mapping.add(fr, ref(f"test_delete_{var}_removes_it"))
        lines += [
            "",
            f"    def test_delete_{var}_removes_it(self):",
            f'        """Covers: {fr} — delete removes; deleting again fails."""',
            f"        created = self.storage.create_{var}({payload})",
            f'        self.assertTrue(self.storage.delete_{var}(created["id"]))',
            f'        self.assertIsNone(self.storage.get_{var}(created["id"]))',
            f'        self.assertFalse(self.storage.delete_{var}(created["id"]))',
        ]
    return lines


# --- unit: auth -----------------------------------------------------------------------


def _auth_tests(spec: MvpSpec, mapping: _Mapping) -> str:
    fr = frs_by_capability(spec, "auth.bearer_token")[0].id
    path = "tests/unit/test_auth.py"
    for test in (
        "test_valid_token_accepted",
        "test_invalid_token_rejected",
        "test_missing_env_token_rejects_everything",
        "test_header_parsing",
    ):
        mapping.add(fr, f"{path}::AuthTests::{test}")
    return f'''"""Auth tests (generated before implementation).

Covers: {fr}
"""

import os
import unittest

from app import auth


class AuthTests(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.get(auth.TOKEN_ENV)
        os.environ[auth.TOKEN_ENV] = "test-token-123"

    def tearDown(self):
        if self._saved is None:
            os.environ.pop(auth.TOKEN_ENV, None)
        else:
            os.environ[auth.TOKEN_ENV] = self._saved

    def test_valid_token_accepted(self):
        """Covers: {fr} — the configured token verifies."""
        self.assertTrue(auth.verify_token("test-token-123"))

    def test_invalid_token_rejected(self):
        """Covers: {fr} — negative case: wrong token."""
        self.assertFalse(auth.verify_token("wrong-token"))
        self.assertFalse(auth.verify_token(""))

    def test_missing_env_token_rejects_everything(self):
        """Covers: {fr} — negative case: unconfigured server rejects all."""
        os.environ.pop(auth.TOKEN_ENV, None)
        self.assertFalse(auth.verify_token("test-token-123"))

    def test_header_parsing(self):
        """Covers: {fr} — Authorization header edge cases."""
        self.assertEqual(auth.token_from_header("Bearer abc"), "abc")
        self.assertEqual(auth.token_from_header("bearer abc"), "abc")
        self.assertEqual(auth.token_from_header("Basic abc"), "")
        self.assertEqual(auth.token_from_header(None), "")
        self.assertEqual(auth.token_from_header(""), "")


if __name__ == "__main__":
    unittest.main()
'''


# --- integration: API over real HTTP --------------------------------------------------


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
        "        self.server.storage.close()",
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
    if auth and spec.entities:
        fr = frs_by_capability(spec, "auth.bearer_token")[0].id
        first_route = collection_route(spec.entities[0])
        mapping.add(fr, ref("test_missing_token_returns_401"))
        mapping.add(fr, ref("test_invalid_token_returns_401"))
        lines += [
            "",
            "    def test_missing_token_returns_401(self):",
            f'        """Covers: {fr} — negative case: no Authorization header."""',
            f'        status, body = self._request("GET", "{first_route}", token=None)',
            "        self.assertEqual(status, 401)",
            '        self.assertIn("error", body)',
            "",
            "    def test_invalid_token_returns_401(self):",
            f'        """Covers: {fr} — negative case: wrong token."""',
            f'        status, _ = self._request("GET", "{first_route}", '
            'token="wrong-token")',
            "        self.assertEqual(status, 401)",
        ]
    for entity in spec.entities:
        lines += _api_entity_tests(spec, entity, mapping, ref)
    lines += ["", "", 'if __name__ == "__main__":', "    unittest.main()"]
    return "\n".join(lines) + "\n"


def _api_entity_tests(
    spec: MvpSpec, entity: Entity, mapping: _Mapping, ref: object
) -> list[str]:
    assert callable(ref)
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
            lines += ['        self.assertEqual(body["status"], "open")']
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
        if has_status and "entity.update" in caps:
            mapping.add(fr, ref(f"test_list_{var}s_filters_by_status"))
            lines += [
                "",
                f"    def test_list_{var}s_filters_by_status(self):",
                f'        """Covers: {fr} — ?status= filter."""',
                f'        _, kept = self._request("POST", "{route}", {payload})',
                f'        _, done = self._request("POST", "{route}", {payload})',
                f'        self._request("PATCH", "{route}/%d" % done["id"], '
                '{"status": "done"})',
                f'        status, body = self._request("GET", "{route}?status=open")',
                "        self.assertEqual(status, 200)",
                '        ids = [row["id"] for row in body]',
                '        self.assertIn(kept["id"], ids)',
                '        self.assertNotIn(done["id"], ids)',
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
            if "entity.read" in caps else "        read_back = body",
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
