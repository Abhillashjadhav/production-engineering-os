"""The packaged schema is the single admission contract; the root copy is the
documented one. This guard keeps them byte-identical."""

from __future__ import annotations

from pathlib import Path

from pmpe.config import packaged_schema_path


def test_packaged_schema_exists() -> None:
    assert packaged_schema_path().exists()


def test_packaged_schema_stays_in_sync_with_repo_contract(repo_root: Path) -> None:
    """schemas/mvp_spec.schema.json is the documented contract; the packaged copy
    must never drift from it."""
    contract = (repo_root / "schemas" / "mvp_spec.schema.json").read_bytes()
    assert packaged_schema_path().read_bytes() == contract
