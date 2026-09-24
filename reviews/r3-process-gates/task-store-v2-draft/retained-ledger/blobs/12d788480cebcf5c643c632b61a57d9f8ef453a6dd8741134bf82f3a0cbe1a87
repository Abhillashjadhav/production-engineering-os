"""Specification ingestion: load, schema-validate, normalize."""

from __future__ import annotations

from pathlib import Path

from pmpe.domain.errors import SpecError
from pmpe.domain.models import MvpSpec
from pmpe.ingestion.loader import load_spec_data
from pmpe.ingestion.normalizer import normalize_spec
from pmpe.ingestion.schema import SchemaValidator


def ingest(spec_path: Path, schema_path: Path) -> MvpSpec:
    """Load -> schema-validate -> normalize. Raises SpecError on any failure."""
    data = load_spec_data(spec_path)
    errors = SchemaValidator(schema_path).validate(data)
    if errors:
        raise SpecError(f"specification {spec_path} violates the schema", errors)
    return normalize_spec(data)


__all__ = ["SchemaValidator", "ingest", "load_spec_data", "normalize_spec"]
