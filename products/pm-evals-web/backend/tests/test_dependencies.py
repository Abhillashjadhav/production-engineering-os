"""Supply-chain reproducibility (dogfood F-3): the backend runtime is installed
from a committed, hash-pinned lockfile — not resolved fresh at build time. Floor
pins (`>=`) in pyproject let two builds of the same commit resolve different
versions; the lockfile is what makes the deployed runtime reproducible and
auditable."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

BACKEND = Path(__file__).resolve().parents[1]
LOCKFILE = BACKEND / "requirements.lock"
PYPROJECT = BACKEND / "pyproject.toml"


def _runtime_requirements() -> list[Requirement]:
    data = tomllib.loads(PYPROJECT.read_text())
    return [Requirement(spec) for spec in data["project"]["dependencies"]]


def _lockfile_pins() -> dict[str, str]:
    """Canonical name -> pinned version for every `name==version` line."""
    return {
        canonicalize_name(m.group(1)): m.group(2)
        for m in re.finditer(r"(?m)^([A-Za-z0-9._-]+)==([^\s\\]+)", LOCKFILE.read_text())
    }


def _lockfile_via_names() -> set[str]:
    """Canonical names referenced in `# via` annotations, excluding the local
    project sentinel (`# via pm-evals-web-backend (pyproject.toml)`). Every such
    referenced dependent must itself be pinned, or a transitive package was
    dropped from the lock while something still needs it."""
    names: set[str] = set()
    in_block = False
    for line in LOCKFILE.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("# via "):
            rest = stripped[len("# via ") :].strip()
            in_block = rest == ""
            if rest and not rest.endswith("(pyproject.toml)"):
                names.add(canonicalize_name(rest))
        elif in_block and stripped.startswith("#"):
            ref = stripped[1:].strip()
            if ref and not ref.endswith("(pyproject.toml)"):
                names.add(canonicalize_name(ref))
            elif not ref:
                in_block = False
        else:
            in_block = False
    return names


def test_backend_ships_a_lockfile() -> None:
    assert LOCKFILE.exists(), "the backend requires a committed requirements.lock (F-3)"


def test_lockfile_pins_every_runtime_dependency_exactly_with_hashes() -> None:
    text = LOCKFILE.read_text()
    pinned = set(_lockfile_pins())
    missing = {canonicalize_name(r.name) for r in _runtime_requirements()} - pinned
    assert not missing, f"runtime deps not pinned in the lockfile: {sorted(missing)}"
    # Exact, hash-bound pins only — no floating range may leak into the lockfile.
    assert "--hash=" in text, "the lockfile must be hash-pinned (--generate-hashes)"
    assert not re.search(r"(?m)^[A-Za-z0-9._-]+\s*(>=|<=|~=|>|<)", text), (
        "the lockfile must pin exact versions, not ranges"
    )


def test_locked_versions_satisfy_the_pyproject_specifiers() -> None:
    """A floor bump in pyproject without regenerating the lock would silently
    ship a version older than the declared minimum — `pip install --no-deps .`
    never re-checks it. Assert each locked version satisfies its own specifier."""
    pins = _lockfile_pins()
    for req in _runtime_requirements():
        version = pins[canonicalize_name(req.name)]
        assert req.specifier.contains(Version(version), prereleases=True), (
            f"locked {req.name}=={version} violates pyproject specifier '{req.specifier}'"
        )


def test_lockfile_transitive_closure_is_self_consistent() -> None:
    """Every package a lock entry declares itself needed by (`# via <dep>`) must
    itself be pinned. Dropping a transitive package (e.g. starlette) while a
    dependent still references it — which would break `--require-hashes` — is
    caught here, not only at the Docker build."""
    dangling = _lockfile_via_names() - set(_lockfile_pins())
    assert not dangling, f"lockfile references unpinned dependencies: {sorted(dangling)}"
