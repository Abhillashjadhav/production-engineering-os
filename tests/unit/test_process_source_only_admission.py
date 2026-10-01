"""Source-only admission probes for named roots and observed startup prerequisites.

The guard does not broadly scan the module registry. These tests do not establish
historical prefix emptiness or every past/future import. No planted bytecode runs.
"""

from __future__ import annotations

import os
import subprocess
import sys
import types
import zipfile
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
    tmp_path: Path, flags: list[str], *, pre: str = "", pythonpath: Path | None = None
) -> subprocess.CompletedProcess[str]:
    adapter = tmp_path / "adapter" / "runner.py"
    adapter.parent.mkdir(exist_ok=True)
    adapter.write_text("# exact adapter source; never imported\n")
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX", "PYTHONPATH"}
    }
    environment["PYTHONPATH"] = str(pythonpath or ROOT / "src")
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


def test_missing_kernel_startup_records_cannot_be_replaced_by_runtime_values(
    tmp_path: Path,
) -> None:
    prefix = empty_prefix(tmp_path)
    result = run_probe(
        tmp_path,
        ["-B", "-X", f"pycache_prefix={prefix}"],
        pre=(
            "import pmpe.process_sources as sources\nsources._startup_record = lambda _name: None"
        ),
    )
    assert result.returncode == 3, result.stdout + result.stderr
    assert "startup records" in result.stdout


@pytest.mark.parametrize("origin", ["zip", "sourceless"])
def test_named_engine_origin_must_be_a_regular_python_source(tmp_path: Path, origin: str) -> None:
    prefix = empty_prefix(tmp_path)
    suffix = "process_sources.py" if origin == "zip" else "process_sources.pyc"
    fake_source = tmp_path / "unsupported.zip" / "pmpe" / suffix
    result = run_probe(
        tmp_path,
        ["-B", "-X", f"pycache_prefix={prefix}"],
        pre=(f"import pmpe.process_sources as sources\nsources.__file__ = {str(fake_source)!r}"),
    )
    assert result.returncode == 3, result.stdout + result.stderr
    assert "regular Python source" in result.stdout


def test_zipimported_engine_source_is_refused(tmp_path: Path) -> None:
    """Benign source ZIP import cannot be mistaken for a listed filesystem source."""

    archive = tmp_path / "engine.zip"
    source_root = ROOT / "src"
    with zipfile.ZipFile(archive, "w") as packed:
        for path in (source_root / "pmpe").rglob("*.py"):
            packed.write(path, path.relative_to(source_root))
    prefix = empty_prefix(tmp_path)
    result = run_probe(
        tmp_path,
        ["-B", "-X", f"pycache_prefix={prefix}"],
        pythonpath=archive,
    )
    assert result.returncode == 3, result.stdout + result.stderr
    assert "regular Python source" in result.stdout


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


def test_class_in_a_fake_module_namespace_is_refused() -> None:
    """A dict that only claims the canonical module's name is not that module (Codex #227)."""

    def forged_run(self: object) -> str:
        return "forged"

    fake: dict[str, object] = {"__name__": CanonicalImplementation.__module__}
    # The forgery dynamic code would build, written statically: a method whose globals
    # are the fake dict, in a class labelled with the canonical module and name.
    run = types.FunctionType(forged_run.__code__, fake, "run")
    forged = type("CanonicalImplementation", (), {"__module__": fake["__name__"], "run": run})
    fake["CanonicalImplementation"] = forged
    with pytest.raises(ValueError, match="canonical"):
        implementation_identity(forged())


@pytest.mark.skipif(not Path("/proc/self/cmdline").exists(), reason="needs /proc startup records")
def test_script_arguments_are_not_startup_options(tmp_path: Path) -> None:
    """`-X pycache_prefix=...` after the script or -c code is an argument, not an option."""
    prefix = empty_prefix(tmp_path)
    adapter = tmp_path / "adapter" / "runner.py"
    adapter.parent.mkdir(exist_ok=True)
    adapter.write_text("# exact adapter source; never imported\n")
    forge = (
        f"sys._xoptions['pycache_prefix'] = {str(prefix)!r}\nsys.pycache_prefix = {str(prefix)!r}"
    )
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX", "PYTHONPATH"}
    }
    environment["PYTHONPATH"] = str(ROOT / "src")
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            PROBE.format(pre=forge, adapter=str(adapter)),
            "-X",
            f"pycache_prefix={prefix}",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 3, result.stdout + result.stderr
    assert "source-only" in result.stdout


@pytest.mark.skipif(not Path("/proc/self/cmdline").exists(), reason="needs /proc startup records")
def test_deleted_startup_xoption_cannot_fall_back_to_the_environment(tmp_path: Path) -> None:
    """A startup -X prefix overrides the environment even after sys._xoptions is edited.

    Codex #227: with environment prefix A and -X prefix B, deleting the runtime -X entry
    and pointing sys.pycache_prefix at A must not admit A; imports before that used B.
    """
    environment_prefix = empty_prefix(tmp_path, "environment-cache")
    startup_prefix = empty_prefix(tmp_path, "startup-cache")
    (startup_prefix / "stale.pyc").write_bytes(b"stale")
    adapter = tmp_path / "adapter" / "runner.py"
    adapter.parent.mkdir(exist_ok=True)
    adapter.write_text("# exact adapter source; never imported\n")
    forge = f"del sys._xoptions['pycache_prefix']\nsys.pycache_prefix = {str(environment_prefix)!r}"
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX", "PYTHONPATH"}
    }
    environment.update(PYTHONPATH=str(ROOT / "src"), PYTHONPYCACHEPREFIX=str(environment_prefix))
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-X",
            f"pycache_prefix={startup_prefix}",
            "-c",
            PROBE.format(pre=forge, adapter=str(adapter)),
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 3, result.stdout + result.stderr
    assert "source-only" in result.stdout


def test_class_in_a_registered_replacement_module_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Registering the forged namespace in sys.modules does not make its code canonical.

    Codex #227: a replacement module under the approved name, holding a forged class and
    pointing __file__ at the approved source, must not borrow that source's identity.
    """
    real = sys.modules[CanonicalImplementation.__module__]
    replacement = types.ModuleType(real.__name__)
    replacement.__file__ = real.__file__

    def forged_run(self: object) -> str:
        return "forged"

    run = types.FunctionType(forged_run.__code__, vars(replacement), "run")
    forged = type("CanonicalImplementation", (), {"__module__": real.__name__, "run": run})
    forged.__qualname__ = CanonicalImplementation.__qualname__
    replacement.CanonicalImplementation = forged  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, real.__name__, replacement)
    with pytest.raises(ValueError, match="canonical"):
        implementation_identity(forged())
