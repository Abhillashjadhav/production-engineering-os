"""Supply-chain reproducibility (dogfood F-3): the backend runtime is installed
from a committed, hash-pinned lockfile — not resolved fresh at build time. Floor
pins (`>=`) in pyproject let two builds of the same commit resolve different
versions; the lockfile is what makes the deployed artifact reproducible and
auditable."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
LOCKFILE = BACKEND / "requirements.lock"
PYPROJECT = BACKEND / "pyproject.toml"


def _runtime_dependency_names() -> set[str]:
    data = tomllib.loads(PYPROJECT.read_text())
    names: set[str] = set()
    for spec in data["project"]["dependencies"]:
        name = re.split(r"[<>=!~ \[]", spec, maxsplit=1)[0]
        names.add(name.strip().lower().replace("_", "-"))
    return names


def test_backend_ships_a_lockfile() -> None:
    assert LOCKFILE.exists(), "the backend requires a committed requirements.lock (F-3)"


def test_lockfile_pins_every_runtime_dependency_exactly_with_hashes() -> None:
    text = LOCKFILE.read_text()
    pinned = {
        match.group(1).lower().replace("_", "-")
        for match in re.finditer(r"(?m)^([A-Za-z0-9._-]+)==", text)
    }
    missing = _runtime_dependency_names() - pinned
    assert not missing, f"runtime deps not pinned in the lockfile: {sorted(missing)}"
    # Exact, hash-bound pins only — no floating range may leak into the lockfile.
    assert "--hash=" in text, "the lockfile must be hash-pinned (--generate-hashes)"
    assert not re.search(r"(?m)^[A-Za-z0-9._-]+\s*(>=|<=|~=|>|<)", text), (
        "the lockfile must pin exact versions, not ranges"
    )
