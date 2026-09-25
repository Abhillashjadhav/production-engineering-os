"""Benign metadata fixtures for the existing cache guard; no fixture code is run."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import pmpe.process_sources as sources


@pytest.mark.parametrize("source_kind", ["engine", "manifested_adapter", "manifested_helper"])
def test_active_cache_metadata_uses_location_not_import_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source_kind: str
) -> None:
    root = tmp_path / source_kind
    root.mkdir()
    source = root / "helper.py"
    source.write_text("# Data-only source inventory fixture; never imported.\n")
    previous_cache = tmp_path / "previous-prefix" / "helper.pyc"
    previous_cache.parent.mkdir()
    previous_cache.write_bytes(b"inert cache-presence marker; never executed")
    module_metadata = SimpleNamespace(__file__=str(source), __cached__=str(previous_cache))
    # Replace the guard's registry view with metadata; do not register or load a module.
    monkeypatch.setattr(
        sources, "sys", SimpleNamespace(modules={"arbitrary_unrelated_alias": module_metadata})
    )
    monkeypatch.setattr(sys, "pycache_prefix", str(tmp_path / "current-prefix"))
    assert not Path(importlib.util.cache_from_source(str(source))).exists()

    with pytest.raises(ValueError, match="active uninventoried bytecode") as error:
        sources.reject_bytecode([root])

    assert str(previous_cache) in str(error.value)


@pytest.mark.parametrize("optimization", ["", "1", "2"])
def test_future_cache_metadata_does_not_require_a_loaded_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, optimization: str
) -> None:
    root = tmp_path / "adapter"
    root.mkdir()
    source = root / "future.py"
    source.write_text("# Data-only source inventory fixture; never imported.\n")
    monkeypatch.setattr(sources, "sys", SimpleNamespace(modules={}))
    monkeypatch.setattr(sys, "pycache_prefix", str(tmp_path / "current-prefix"))
    cached = Path(importlib.util.cache_from_source(str(source), optimization=optimization))
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"inert cache-presence marker; never executed")

    with pytest.raises(ValueError, match="active or future uninventoried bytecode") as error:
        sources.reject_bytecode([root])

    assert str(cached) in str(error.value)


@pytest.mark.parametrize("suffix", [".pyc", ".pyo"])
def test_local_cache_metadata_is_rejected_without_a_source_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, suffix: str
) -> None:
    root = tmp_path / "adapter"
    root.mkdir()
    (root / ("orphan" + suffix)).write_bytes(b"inert cache-presence marker; never executed")
    monkeypatch.setattr(sources, "sys", SimpleNamespace(modules={}))

    with pytest.raises(ValueError, match="bytecode under source root"):
        sources.reject_bytecode([root])


def test_clean_inventory_with_active_helper_metadata_is_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "adapter"
    helper = root / "nested" / "helper.py"
    helper.parent.mkdir(parents=True)
    helper.write_text("# Data-only source inventory fixture; never imported.\n")
    module_metadata = SimpleNamespace(
        __file__=str(helper), __cached__=str(tmp_path / "absent-prefix" / "helper.pyc")
    )
    monkeypatch.setattr(sources, "sys", SimpleNamespace(modules={"helper_alias": module_metadata}))
    monkeypatch.setattr(sys, "pycache_prefix", str(tmp_path / "current-prefix"))

    sources.reject_bytecode([root, helper.parent])
