"""Test templates for the python-stdlib-crud-api stack.

Generated BEFORE implementation (workflow step 6 vs 8). Every test carries a
``Covers: FR-xxx`` marker; the mapping returned alongside the files feeds the
traceability report. Negative and edge cases (401/400/404, persistence across
restart) are generated wherever the capability exists.
"""

from __future__ import annotations

import json

from pmpe.domain.models import Entity, GeneratedFile, GeneratedTests, MvpSpec
from pmpe.stacks import (
    capabilities_for,
    entity_var,
    fr_id_for,
    frs_by_capability,
    has_auth,
    status_default,
    table_name,
)

_SAMPLE_VALUES = {
    "string": '"sample {name}"',
    "text": '"sample {name}"',
    "int": "1",
    "bool": "True",
    "timestamp": '"2026-01-01T00:00:00+00:00"',
}


def _required_payload(entity: Entity) -> str:
    parts = []
    for f in entity.fields:
        if f.required:
            value = _SAMPLE_VALUES.get(f.type, '"sample"').format(name=f.name)
            parts.append(f'"{f.name}": {value}')
    return "{" + ", ".join(parts) + "}"


def _payload_with(entity: Entity, field_name: str, value_literal: str) -> str:
    """Required-fields payload with one field overridden by a literal expression."""
    parts = []
    for f in entity.fields:
        if f.name == field_name:
            parts.append(f'"{f.name}": {value_literal}')
        elif f.required:
            value = _SAMPLE_VALUES.get(f.type, '"sample"').format(name=f.name)
            parts.append(f'"{f.name}": {value}')
    return "{" + ", ".join(parts) + "}"


def _changed_status(entity: Entity) -> str:
    """A status value guaranteed to differ from the declared default."""
    return "closed" if status_default(entity) == "done" else "done"


def _mutable_field(entity: Entity) -> tuple[str, str]:
    """Field used by update tests: prefer status (value != default), else first string."""
    for f in entity.fields:
        if f.name == "status":
            return "status", _changed_status(entity)
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
    # local import: stdlib_tests_api imports helpers from this module
    from pmpe.stacks.stdlib_tests_api import _api_tests

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
        files.append(GeneratedFile("tests/unit/test_auth.py", _auth_tests(spec, mapping), "test"))
    files.append(GeneratedFile("tests/integration/test_api.py", _api_tests(spec, mapping), "test"))
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


def _storage_entity_class(spec: MvpSpec, entity: Entity, mapping: _Mapping, path: str) -> list[str]:
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
        for test in (
            f"test_create_{var}_assigns_id",
            f"test_created_{var}_persists_across_reconnect",
        ):
            mapping.add(fr, ref(test))
        default_check = ""
        if has_status:
            default = status_default(entity)
            if default is not None:
                default_check = (
                    f'        self.assertEqual(created["status"], {json.dumps(default)})\n'
                )
            else:
                default_check = '        self.assertIsNone(created["status"])\n'
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
        default = status_default(entity)
        if has_status and default is not None and "entity.update" in caps:
            changed = _changed_status(entity)
            mapping.add(fr, ref(f"test_list_{table}_filters_by_status"))
            lines += [
                "",
                f"    def test_list_{table}_filters_by_status(self):",
                f'        """Covers: {fr} — optional status filter."""',
                f"        kept = self.storage.create_{var}({payload})",
                f"        other = self.storage.create_{var}({payload})",
                f'        self.storage.update_{var}(other["id"], '
                f'{{"status": {json.dumps(changed)}}})',
                f"        rows = self.storage.list_{table}(status={json.dumps(default)})",
                '        self.assertIn(kept["id"], [row["id"] for row in rows])',
                '        self.assertNotIn(other["id"], [row["id"] for row in rows])',
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
            f'{{"{mut_field}": {json.dumps(mut_value)}}})',
            f'        self.assertEqual(updated["{mut_field}"], {json.dumps(mut_value)})',
            "",
            f"    def test_update_{var}_unknown_returns_none(self):",
            f'        """Covers: {fr} — negative case: unknown id."""',
            f"        self.assertIsNone(self.storage.update_{var}(999999, "
            f'{{"{mut_field}": {json.dumps(mut_value)}}}))',
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
