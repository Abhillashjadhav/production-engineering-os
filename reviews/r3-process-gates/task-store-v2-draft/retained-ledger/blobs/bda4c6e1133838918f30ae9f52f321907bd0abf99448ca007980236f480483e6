"""Canonical contract digest.

All contract identities use the RFC 8785 implementation in
``pmpe.contracts.canonical``.  Keeping this compatibility module means older
callers retain one import path without creating a second digest grammar.
"""

from __future__ import annotations

from typing import Any

from pmpe.contracts.canonical import (
    canonical_digest as rfc8785_digest,
)
from pmpe.contracts.canonical import (
    canonical_json_bytes,
)
from pmpe.domain.serialize import jsonable


def canonical_json(data: Any) -> str:
    return canonical_json_bytes(jsonable(data)).decode("utf-8")


def canonical_digest(data: Any) -> str:
    return rfc8785_digest(jsonable(data))
