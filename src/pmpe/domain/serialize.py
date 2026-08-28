"""Serialization helpers: dataclasses/enums/paths -> JSON, atomic JSON writes."""

from __future__ import annotations

import dataclasses
import json
from enum import Enum
from pathlib import Path
from typing import Any


def atomic_write_json(path: Path, obj: Any) -> None:
    """Write JSON via tmp+rename so a crash never leaves a torn file.

    Every persistence site (state, escalations, approvals, artifacts) uses this —
    a torn escalation/approval file would make legacy state unreadable.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(jsonable(obj), indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def jsonable(obj: Any) -> Any:
    """Recursively convert domain objects into JSON-serializable structures."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(v) for v in obj]
    return obj
