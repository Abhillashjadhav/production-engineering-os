"""Canonical contract digest.

The digest is computed over the canonical JSON form (sorted keys, minimal
separators, UTF-8) so formatting, key order, and whitespace never change it —
only content does. It is the identity every run, review, approval, and
deployment binds to.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pmpe.domain.serialize import jsonable


def canonical_json(data: Any) -> str:
    return json.dumps(jsonable(data), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_digest(data: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()
