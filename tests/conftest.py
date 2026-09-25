"""Shared fixtures for the pmpe test suite.

Failure-path specs are derived from the golden example by explicit mutation
(see tests/fixtures/README.md); standalone malformed inputs live in tests/fixtures/.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_SPEC = REPO_ROOT / "examples" / "taskflow_mvp_spec.yaml"
SCHEMA_PATH = REPO_ROOT / "schemas" / "mvp_spec.schema.json"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"

SpecMutator = Callable[[dict[str, Any]], None]


def _cache_entries(prefix: str | None) -> list[str]:
    if not prefix or not os.path.isdir(prefix):
        return []
    return sorted(os.listdir(prefix))


def _source_bytecode() -> list[str]:
    return sorted(str(path) for path in (REPO_ROOT / "src").rglob("*.pyc"))


@pytest.fixture(autouse=True)
def _private_cache_prefix_stays_empty() -> Iterator[None]:
    """Name the test whose child process writes bytecode into the startup cache prefix.

    Gated runs admit only an empty startup prefix (source-only admission), and CI shares
    one prefix across the whole test job. One polluting child would otherwise surface as
    "bytecode prefix is not empty" in every later gated test.
    """
    prefix = os.environ.get("PYTHONPYCACHEPREFIX")
    was_empty = not _cache_entries(prefix)
    source_was_clean = not _source_bytecode()
    yield
    written = _cache_entries(prefix)
    if was_empty and written:
        pytest.fail(
            f"test wrote into the shared bytecode prefix {prefix}: {written[:3]}; "
            "run child interpreters with -B and without PYTHONPYCACHEPREFIX"
        )
    # Gated runs also refuse bytecode beside the engine's own sources.
    stray = _source_bytecode()
    if source_was_clean and stray:
        pytest.fail(f"test wrote bytecode under src/: {stray[:3]}; run child interpreters with -B")


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def schema_path() -> Path:
    return SCHEMA_PATH


@pytest.fixture(scope="session")
def golden_spec_path() -> Path:
    return GOLDEN_SPEC


@pytest.fixture()
def golden_spec_dict() -> dict[str, Any]:
    with GOLDEN_SPEC.open() as fh:
        data: dict[str, Any] = yaml.safe_load(fh)
    return copy.deepcopy(data)


@pytest.fixture()
def fixtures_dir() -> Path:
    return FIXTURES_DIR


class _LocalCandidateTestSandbox:
    """Test-only runner; production defaults are exercised by dedicated boundary tests."""

    def run(
        self,
        workspace: Path,
        argv: list[str] | tuple[str, ...],
        *,
        timeout_seconds: float,
        environment: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        translated: list[str] = []
        for index, argument in enumerate(argv):
            if index == 0 and argument == sys.executable:
                translated.append(argument)
                continue
            rewritten = argument.replace("'/workspace'", repr(str(workspace)))
            if rewritten == "/workspace" or rewritten.startswith("/workspace/"):
                rewritten = str(workspace) + rewritten.removeprefix("/workspace")
            elif rewritten.startswith("--rootdir=/workspace"):
                rewritten = "--rootdir=" + str(workspace)
            translated.append(rewritten)
        try:
            return subprocess.run(
                translated,
                cwd=workspace,
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
                env={
                    **environment,
                    "PATH": os.environ.get("PATH", environment.get("PATH", "")),
                },
            )
        except subprocess.TimeoutExpired as exc:
            from pmpe.barebones import ContractInvalidError

            raise ContractInvalidError("candidate execution timed out") from exc


@pytest.fixture(autouse=True)
def local_candidate_sandbox_for_barebones_tests(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    if request.path.name not in {
        "test_barebones_cli.py",
        "test_barebones_e1.py",
        "test_barebones_evals.py",
        "test_release_gate_runtime.py",
    }:
        return
    if (
        request.path.name == "test_barebones_e1.py"
        and os.environ.get("PMPE_TEST_REAL_SANDBOX") == "true"
    ):
        return
    from pmpe import barebones

    monkeypatch.setattr(barebones, "BubblewrapCandidateSandbox", _LocalCandidateTestSandbox)


@pytest.fixture()
def make_spec_file(tmp_path: Path, golden_spec_dict: dict[str, Any]) -> Callable[..., Path]:
    """Write a (possibly mutated) copy of the golden spec to a temp file.

    Usage: make_spec_file(lambda d: d.pop("product_name"), fmt="yaml")
    """

    def _make(mutate: SpecMutator | None = None, fmt: str = "yaml", name: str = "spec") -> Path:
        data = copy.deepcopy(golden_spec_dict)
        if mutate is not None:
            mutate(data)
        path = tmp_path / f"{name}.{fmt}"
        if fmt == "json":
            path.write_text(json.dumps(data, indent=2))
        else:
            path.write_text(yaml.safe_dump(data, sort_keys=False))
        return path

    return _make


# --- canonical mutations used across test layers -------------------------------------


def mutate_contradictory(data: dict[str, Any]) -> None:
    """Plant the same item in scope and non_goals (a product contradiction)."""
    data["scope"].append("Bulk task import")
    data["non_goals"].append("Bulk task import")


def mutate_activity_nsm(data: dict[str, Any]) -> None:
    """Plant an activity-only North Star Metric."""
    data["north_star_metric"] = "Daily signups and pageviews"


def mutate_production_target(data: dict[str, Any]) -> None:
    """Request a production deployment (high-risk in V1)."""
    data["deployment_target"] = "production"


def mutate_vague_ac(data: dict[str, Any]) -> None:
    """Plant an untestable acceptance criterion."""
    data["acceptance_criteria"].append(
        {
            "id": "AC-VAGUE",
            "requirement": "FR-002",
            "criterion": "The app should feel fast and intuitive for everyone.",
        }
    )


def mutate_unknown_requirement_ac(data: dict[str, Any]) -> None:
    data["acceptance_criteria"].append(
        {
            "id": "AC-GHOST",
            "requirement": "FR-999",
            "criterion": "Given a thing, when it happens, then the response status is 200.",
        }
    )


def mutate_missing_entity(data: dict[str, Any]) -> None:
    """FR references an entity that is not declared in entities[]."""
    data["functional_requirements"].append(
        {
            "id": "FR-100",
            "title": "Create a project",
            "capability": "entity.create",
            "entity": "Project",
        }
    )
    data["acceptance_criteria"].append(
        {
            "id": "AC-100",
            "requirement": "FR-100",
            "criterion": "Given a valid token, when POST /projects is called "
            "with a name, then the response status is 201.",
        }
    )


@pytest.fixture()
def pipeline_workdir(tmp_path: Path) -> Path:
    """Isolated runs/ directory for orchestrator tests."""
    d = tmp_path / "runs"
    d.mkdir()
    return d
