"""Serialization helper: dataclasses/enums/paths -> JSON-compatible structures."""

from __future__ import annotations

import dataclasses
from enum import Enum
from pathlib import Path
from typing import Any


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
