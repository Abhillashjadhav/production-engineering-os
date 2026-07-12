"""Structural validation against schemas/mvp_spec.schema.json.

Implements the documented subset of JSON Schema the contract uses:
``type`` (string/array/object/boolean/integer), ``required``, ``properties``,
``items``, ``enum``, ``minItems``, ``minLength``. The schema file itself is the
single source of truth — nothing structural is hardcoded here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pmpe.domain.errors import ConfigError

_TYPE_CHECKS: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "array": list,
    "object": dict,
    "boolean": bool,
    "integer": int,
    "number": (int, float),
}


class SchemaValidator:
    def __init__(self, schema_path: Path) -> None:
        try:
            self.schema: dict[str, Any] = json.loads(schema_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"cannot load schema {schema_path}: {exc}") from exc

    def validate(self, data: Any) -> list[str]:
        """Return a flat list of error strings; empty means structurally valid."""
        errors: list[str] = []
        self._validate_node(data, self.schema, path="", errors=errors)
        return errors

    def _validate_node(
        self, value: Any, schema: dict[str, Any], path: str, errors: list[str]
    ) -> None:
        label = path or "specification"

        expected = schema.get("type")
        if expected is not None:
            py_type = _TYPE_CHECKS.get(expected)
            if py_type is None:
                raise ConfigError(f"schema uses unsupported type '{expected}' at {label}")
            # bool is an int subclass; don't let True pass as integer
            if expected == "integer" and isinstance(value, bool):
                errors.append(f"{label}: expected integer, got boolean")
                return
            if not isinstance(value, py_type):
                errors.append(f"{label}: expected {expected}, got {type(value).__name__}")
                return

        if "enum" in schema and value not in schema["enum"]:
            allowed = ", ".join(repr(v) for v in schema["enum"])
            errors.append(f"{label}: value {value!r} not one of [{allowed}]")
            return

        if (
            isinstance(value, str)
            and "minLength" in schema
            and len(value.strip()) < int(schema["minLength"])
        ):
            errors.append(f"{label}: shorter than minLength {schema['minLength']}")

        if isinstance(value, list):
            if "minItems" in schema and len(value) < int(schema["minItems"]):
                errors.append(f"{label}: needs at least {schema['minItems']} item(s)")
            item_schema = schema.get("items")
            if isinstance(item_schema, dict):
                for i, item in enumerate(value):
                    self._validate_node(item, item_schema, f"{label}[{i}]", errors)

        if isinstance(value, dict):
            for req in schema.get("required", []):
                if req not in value:
                    errors.append(f"{label}: missing required field '{req}'")
            props = schema.get("properties", {})
            for key, sub in props.items():
                if key in value:
                    child = f"{path}.{key}" if path else key
                    self._validate_node(value[key], sub, child, errors)
