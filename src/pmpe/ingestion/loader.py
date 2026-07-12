"""Load a specification file (JSON or YAML) into a raw mapping."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from pmpe.domain.errors import SpecError


def load_spec_data(path: Path) -> dict[str, Any]:
    """Read JSON (.json) or YAML (anything else) and require a mapping at top level."""
    if not path.exists():
        raise SpecError(f"specification file not found: {path}")
    text = path.read_text()
    if path.suffix.lower() == ".json":
        try:
            data: Any = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SpecError(f"invalid JSON in {path}: {exc}") from exc
    else:
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise SpecError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SpecError(
            f"specification {path} must be a mapping/object at the top level, "
            f"got {type(data).__name__}"
        )
    return data
