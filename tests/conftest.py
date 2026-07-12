"""Shared fixtures for the pmpe test suite.

Failure-path specs are derived from the golden example by explicit mutation
(see tests/fixtures/README.md); standalone malformed inputs live in tests/fixtures/.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_SPEC = REPO_ROOT / "examples" / "taskflow_mvp_spec.yaml"
SCHEMA_PATH = REPO_ROOT / "schemas" / "mvp_spec.schema.json"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"

SpecMutator = Callable[[dict[str, Any]], None]


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
            "criterion": "Given a valid token, when POST /projects is called with a name, then the response status is 201.",
        }
    )


@pytest.fixture()
def pipeline_workdir(tmp_path: Path) -> Path:
    """Isolated runs/ directory for orchestrator tests."""
    d = tmp_path / "runs"
    d.mkdir()
    return d
