"""PD-V3-13: the OpenAPI document is the frontend/backend contract — promised
APIs must be documented, and the committed document must match the live app."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pmpe.fullstack.api_contract import (
    canonical_openapi_text,
    verify_committed_schema,
    verify_openapi_covers_contract,
)
from pmpe.fullstack.contract import load_fullstack_contract

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "tests" / "fixtures" / "v3" / "fullstack_contract_approved.json"
COMMITTED = ROOT / "products" / "pm-evals-web" / "backend" / "openapi.json"


@pytest.fixture()
def contract():  # noqa: ANN201
    return load_fullstack_contract(EXAMPLE)


def _openapi(paths: dict[str, Any]) -> dict[str, Any]:
    return {"openapi": "3.1.0", "info": {"title": "t", "version": "1"}, "paths": paths}


def test_committed_backend_contract_covers_the_product_contract(contract) -> None:  # noqa: ANN001
    """The real committed document must document every API the pm-evals Web
    contract promises (API-1..3)."""
    openapi = json.loads(COMMITTED.read_text())
    assert verify_openapi_covers_contract(openapi, contract) == []


def test_missing_promised_path_is_a_violation(contract) -> None:  # noqa: ANN001
    openapi = _openapi({"/api/health": {"get": {}}})
    problems = verify_openapi_covers_contract(openapi, contract)
    assert any("API-1" in p and "/api/compare" in p for p in problems)


def test_wrong_method_is_a_violation(contract) -> None:  # noqa: ANN001
    openapi = json.loads(COMMITTED.read_text())
    openapi["paths"]["/api/compare"] = {"get": openapi["paths"]["/api/compare"]["post"]}
    problems = verify_openapi_covers_contract(openapi, contract)
    assert any("API-1" in p and "POST" in p for p in problems)


def test_document_without_paths_fails_closed(contract) -> None:  # noqa: ANN001
    assert verify_openapi_covers_contract({}, contract) == [
        "the OpenAPI document has no 'paths' section"
    ]


def test_committed_schema_matches_itself_canonically() -> None:
    live = json.loads(COMMITTED.read_text())
    assert verify_committed_schema(COMMITTED, live) == []


def test_committed_schema_drift_fails_closed(tmp_path: Path) -> None:
    live = json.loads(COMMITTED.read_text())
    drifted = tmp_path / "openapi.json"
    stale = dict(live)
    stale["info"] = {**live["info"], "version": "0.0.9"}
    drifted.write_text(canonical_openapi_text(stale))
    problems = verify_committed_schema(drifted, live)
    assert problems and "does not match" in problems[0]


def test_missing_committed_schema_fails_closed(tmp_path: Path) -> None:
    problems = verify_committed_schema(tmp_path / "absent.json", {})
    assert problems and "no committed OpenAPI contract" in problems[0]
