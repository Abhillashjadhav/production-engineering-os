"""Agreement gate between package metadata and the required Python CI matrix."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class RuntimeMatrixDecision:
    valid: bool
    declared_targets: tuple[str, ...]
    tested_targets: tuple[str, ...]
    reasons: tuple[str, ...]


def _declared_minors(specifier: str) -> tuple[str, ...]:
    lower_match = re.fullmatch(r">=(\d+)\.(\d+),<(\d+)\.(\d+)", specifier.replace(" ", ""))
    if lower_match is None:
        raise ValueError("requires-python must use a bounded >=major.minor,<major.minor range")
    low_major, low_minor, high_major, high_minor = map(int, lower_match.groups())
    if low_major != high_major or high_minor <= low_minor:
        raise ValueError("cross-major or empty runtime ranges require an explicit matrix policy")
    return tuple(f"{low_major}.{minor}" for minor in range(low_minor, high_minor))


def verify_runtime_matrix(
    pyproject: Path, workflow: Path, *, job_name: str = "tests"
) -> RuntimeMatrixDecision:
    project = tomllib.loads(Path(pyproject).read_text())["project"]
    try:
        declared = _declared_minors(str(project["requires-python"]))
    except (KeyError, ValueError) as exc:
        return RuntimeMatrixDecision(False, (), (), (str(exc),))
    raw = yaml.safe_load(Path(workflow).read_text())
    jobs = raw.get("jobs", {}) if isinstance(raw, dict) else {}
    tests = jobs.get(job_name, {}) if isinstance(jobs, dict) else {}
    strategy = tests.get("strategy", {}) if isinstance(tests, dict) else {}
    matrix = strategy.get("matrix", {}) if isinstance(strategy, dict) else {}
    versions = matrix.get("python-version", ()) if isinstance(matrix, dict) else ()
    tested = tuple(sorted(str(version) for version in versions))
    reasons: list[str] = []
    missing = sorted(set(declared) - set(tested))
    undeclared = sorted(set(tested) - set(declared))
    if missing:
        reasons.append("declared runtimes missing from CI: " + ", ".join(missing))
    if undeclared:
        reasons.append("CI tests unsupported runtimes: " + ", ".join(undeclared))
    return RuntimeMatrixDecision(not reasons, declared, tested, tuple(reasons))
