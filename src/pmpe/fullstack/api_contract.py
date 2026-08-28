"""API-contract verification (PD-V3-13): the committed OpenAPI document is the
contract between frontend and backend.

Two checks, both fail closed:
- every API the FullStackProductContract promises exists in the OpenAPI
  document with the promised method (a promised-but-undocumented API is a
  contract violation);
- the committed document matches the live application's schema byte-for-byte
  under the canonical serialization (drift between what reviewers read and
  what the app serves is a violation).

The generated TypeScript client types are checked in CI by regenerating them
from the committed document and failing on any diff — the UI can never depend
on an undocumented field.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pmpe.fullstack.contract import FullStackProductContract


def verify_openapi_covers_contract(
    openapi: dict[str, Any], contract: FullStackProductContract
) -> list[str]:
    """Problems ([] = every promised API is documented)."""
    problems: list[str] = []
    paths = openapi.get("paths")
    if not isinstance(paths, dict):
        return ["the OpenAPI document has no 'paths' section"]
    for api in contract.api_contracts:
        documented = paths.get(api.path)
        if not isinstance(documented, dict):
            problems.append(
                f"{api.api_id}: promised path '{api.path}' is not documented in the "
                "OpenAPI contract"
            )
            continue
        if api.method.lower() not in documented:
            problems.append(
                f"{api.api_id}: '{api.path}' is documented, but not for method {api.method}"
            )
    return problems


def canonical_openapi_text(openapi: dict[str, Any]) -> str:
    """The one serialization the committed document must use."""
    return json.dumps(openapi, indent=2, sort_keys=True) + "\n"


def verify_committed_schema(committed_path: Path, live: dict[str, Any]) -> list[str]:
    """Fail closed on any drift between the committed contract and the live app."""
    committed_path = Path(committed_path)
    if not committed_path.exists():
        return [f"no committed OpenAPI contract at {committed_path}"]
    committed = committed_path.read_text()
    expected = canonical_openapi_text(live)
    if committed != expected:
        return [
            f"the committed OpenAPI contract at {committed_path} does not match the "
            "live application's schema — regenerate and re-review before merging"
        ]
    return []
