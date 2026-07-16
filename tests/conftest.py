"""Shared fixtures for the pmpe test suite.

Failure-path specs are derived from the golden example by explicit mutation
(see tests/fixtures/README.md); standalone malformed inputs live in tests/fixtures/.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_SPEC = REPO_ROOT / "examples" / "taskflow_mvp_spec.yaml"
SCHEMA_PATH = REPO_ROOT / "schemas" / "mvp_spec.schema.json"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"


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
