"""Owner-approved source-only admission (2026-09-25): gated runs start without bytecode.

The guard no longer scans the module registry. Instead it refuses any interpreter that
was not started with bytecode writes disabled and an empty private cache prefix, so no
module in it can have been loaded from a cache. Subprocess probes exercise real startup
flags; nothing here executes planted bytecode.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from pmpe.process_sources import implementation_identity

ROOT = Path(__file__).resolve().parents[2]

PROBE = """
import sys
from pathlib import Path
{pre}
from pmpe.barebones import default_template
from pmpe.process_sources import build_source_manifest
try:
    build_source_manifest(default_template(), {{"adapter": Path({adapter!r})}}, b"{{}}")
except ValueError as error:
    print("REFUSED:", error)
    raise SystemExit(3)
print("ADMITTED")
"""


def run_probe(
    tmp_path: Path, flags: list[str], *, pre: str = ""
) -> subprocess.CompletedProcess[str]:
    adapter = tmp_path / "adapter" / "runner.py"
    adapter.parent.mkdir(exist_ok=True)
    adapter.write_text("# exact adapter source; never imported\n")
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX", "PYTHONPATH"}
    }
    environment["PYTHONPATH"] = str(ROOT / "src")
    return subprocess.run(
        [sys.executable, *flags, "-c", PROBE.format(pre=pre, adapter=str(adapter))],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def empty_prefix(tmp_path: Path, name: str = "private-cache") -> Path:
    prefix = tmp_path / name
    prefix.mkdir()
    return prefix


def test_source_only_interpreter_is_admitted(tmp_path: Path) -> None:
    prefix = empty_prefix(tmp_path)
    result = run_probe(tmp_path, ["-B", "-X", f"pycache_prefix={prefix}"])
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ADMITTED" in result.stdout
    assert not any(path.is_file() for path in prefix.rglob("*"))


def test_interpreter_without_startup_cache_prefix_is_refused(tmp_path: Path) -> None:
    result = run_probe(tmp_path, ["-B"])
    assert result.returncode == 3, result.stdout + result.stderr
    assert "source-only" in result.stdout and "bytecode" in result.stdout


def test_interpreter_that_may_write_bytecode_is_refused(tmp_path: Path) -> None:
    prefix = empty_prefix(tmp_path)
    result = run_probe(tmp_path, ["-X", f"pycache_prefix={prefix}"])
    assert result.returncode == 3, result.stdout + result.stderr
    assert "bytecode" in result.stdout


def test_cache_prefix_changed_after_startup_is_refused(tmp_path: Path) -> None:
    """A prefix assigned at runtime cannot vouch for modules imported before it."""
    prefix = empty_prefix(tmp_path)
    runtime_prefix = empty_prefix(tmp_path, "runtime-cache")
    result = run_probe(
        tmp_path,
        ["-B", "-X", f"pycache_prefix={prefix}"],
        pre=f"sys.pycache_prefix = {str(runtime_prefix)!r}",
    )
    assert result.returncode == 3, result.stdout + result.stderr
    assert "source-only" in result.stdout


def test_runtime_prefix_without_startup_prefix_is_refused(tmp_path: Path) -> None:
    """The previous migration bootstrap set the prefix only after interpreter start."""
    runtime_prefix = empty_prefix(tmp_path, "runtime-cache")
    result = run_probe(
        tmp_path,
        ["-B"],
        pre=f"sys.pycache_prefix = {str(runtime_prefix)!r}",
    )
    assert result.returncode == 3, result.stdout + result.stderr
    assert "source-only" in result.stdout


def test_non_empty_startup_cache_prefix_is_refused(tmp_path: Path) -> None:
    prefix = empty_prefix(tmp_path)
    (prefix / "leftover.pyc").write_bytes(b"inert cache-presence marker; never executed")
    result = run_probe(tmp_path, ["-B", "-X", f"pycache_prefix={prefix}"])
    assert result.returncode == 3, result.stdout + result.stderr
    assert "not empty" in result.stdout


class CanonicalImplementation:
    def run(self) -> str:
        return "canonical"


def test_module_level_implementation_identity_is_accepted() -> None:
    identity = implementation_identity(CanonicalImplementation())
    assert identity["class"] == (
        CanonicalImplementation.__module__ + "." + CanonicalImplementation.__qualname__
    )
    assert identity["source_digest"].startswith("sha256:")


def test_alias_only_spoof_of_canonical_class_is_refused() -> None:
    class Spoof(CanonicalImplementation):
        run = CanonicalImplementation.run

    Spoof.__module__ = CanonicalImplementation.__module__
    Spoof.__qualname__ = CanonicalImplementation.__qualname__
    with pytest.raises(ValueError, match="canonical"):
        implementation_identity(Spoof())


def test_spoof_with_own_code_is_refused() -> None:
    class Spoof(CanonicalImplementation):
        def run(self) -> str:
            return "spoofed"

    Spoof.__module__ = CanonicalImplementation.__module__
    Spoof.__qualname__ = CanonicalImplementation.__qualname__
    with pytest.raises(ValueError, match="canonical"):
        implementation_identity(Spoof())
