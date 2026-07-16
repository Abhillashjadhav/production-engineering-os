"""Configuration helpers: the packaged schema location."""

from __future__ import annotations

from pathlib import Path


def packaged_schema_path() -> Path:
    """The schema shipped inside the package (kept byte-identical to schemas/
    mvp_spec.schema.json at the repo root — a unit test guards the sync)."""
    return Path(__file__).parent / "schemas" / "mvp_spec.schema.json"
