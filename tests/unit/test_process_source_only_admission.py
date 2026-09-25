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


@pytest.mark.parametrize("prefix", [None, "absolute", "relative"])
def test_bytecode_paths_match_the_import_system(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, prefix: str | None
) -> None:
    """The guard derives cache paths without importlib; they must match it exactly."""
    import importlib.util

    from pmpe.process_sources import bytecode_paths

    source = tmp_path / "pkg" / "module.name.py"
    source.parent.mkdir()
    source.write_text("# never imported\n")
    monkeypatch.chdir(tmp_path)
    if prefix == "absolute":
        monkeypatch.setattr(sys, "pycache_prefix", str(tmp_path / "cache"))
    elif prefix == "relative":
        monkeypatch.setattr(sys, "pycache_prefix", "relative-cache")
    else:
        monkeypatch.setattr(sys, "pycache_prefix", None)
    expected = tuple(
        Path(importlib.util.cache_from_source(str(source), optimization=level)).absolute()
        for level in ("", "1", "2")
    )
    assert tuple(path.absolute() for path in bytecode_paths(source)) == expected


def test_relative_startup_cache_prefix_is_refused(tmp_path: Path) -> None:
    """A relative prefix names a different directory after a chdir (Codex #227 P1)."""
    (tmp_path / "relative-cache").mkdir()
    result = run_probe(tmp_path, ["-B", "-X", "pycache_prefix=relative-cache"])
    assert result.returncode == 3, result.stdout + result.stderr
    assert "absolute" in result.stdout


@pytest.mark.parametrize("entry", ["directory-symlink", "empty-directory", "file-symlink"])
def test_any_entry_in_startup_cache_prefix_is_refused(tmp_path: Path, entry: str) -> None:
    """CPython follows directory symlinks in the parallel cache tree; rglob files do not
    see through them, so a supposedly empty prefix must hold no entry at all (Codex #227 P1).
    """
    prefix = empty_prefix(tmp_path)
    outside = tmp_path / "outside-cache"
    outside.mkdir()
    (outside / "stale.pyc").write_bytes(b"inert cache-presence marker; never executed")
    if entry == "directory-symlink":
        (prefix / "usr").symlink_to(outside, target_is_directory=True)
    elif entry == "empty-directory":
        (prefix / "usr").mkdir()
    else:
        (prefix / "stale.pyc").symlink_to(outside / "stale.pyc")
    result = run_probe(tmp_path, ["-B", "-X", f"pycache_prefix={prefix}"])
    assert result.returncode == 3, result.stdout + result.stderr
    assert "not empty" in result.stdout


@pytest.mark.skipif(not Path("/proc/self/cmdline").exists(), reason="needs /proc startup records")
@pytest.mark.parametrize("forged", ["environment", "xoption"])
def test_prefix_forged_after_startup_is_refused(tmp_path: Path, forged: str) -> None:
    """Runtime edits to os.environ or sys._xoptions are not startup evidence (Codex #227 P1)."""
    runtime_prefix = empty_prefix(tmp_path, "runtime-cache")
    if forged == "environment":
        forge = f"import os; os.environ['PYTHONPYCACHEPREFIX'] = {str(runtime_prefix)!r}"
    else:
        forge = f"sys._xoptions['pycache_prefix'] = {str(runtime_prefix)!r}"
    result = run_probe(
        tmp_path,
        ["-B"],
        pre=forge + f"\nsys.pycache_prefix = {str(runtime_prefix)!r}",
    )
    assert result.returncode == 3, result.stdout + result.stderr
    assert "source-only" in result.stdout


def test_environment_prefix_fixed_at_startup_is_admitted(tmp_path: Path) -> None:
    prefix = empty_prefix(tmp_path)
    adapter = tmp_path / "adapter" / "runner.py"
    adapter.parent.mkdir(exist_ok=True)
    adapter.write_text("# exact adapter source; never imported\n")
    environment = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH"}}
    environment.update(
        PYTHONPATH=str(ROOT / "src"), PYTHONDONTWRITEBYTECODE="1", PYTHONPYCACHEPREFIX=str(prefix)
    )
    result = subprocess.run(
        [sys.executable, "-c", PROBE.format(pre="", adapter=str(adapter))],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ADMITTED" in result.stdout
