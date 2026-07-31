"""Strict JSON/YAML admission and RFC 8785 canonicalization for PMOS intake."""

from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal
from typing import Any, NoReturn

import rfc8785
import yaml

MAX_INTEROPERABLE_INTEGER = 2**53 - 1
MAX_STRUCTURE_DEPTH = 128
MAX_STRUCTURE_NODES = 100_000


class CanonicalInputError(ValueError):
    """A safe, classified failure raised before contract format detection."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CanonicalInputError("DUPLICATE_OBJECT_KEY", "duplicate object member")
        result[key] = value
    return result


def _reject_constant(_value: str) -> NoReturn:
    raise CanonicalInputError("NON_JSON_NUMBER", "non-JSON numeric constant")


def _parse_float(token: str) -> float:
    value = float(token)
    if not math.isfinite(value):
        raise CanonicalInputError("NON_JSON_NUMBER", "non-finite numeric value")
    exact = Decimal(token)
    if exact == exact.to_integral_value() and abs(exact) > MAX_INTEROPERABLE_INTEGER:
        raise CanonicalInputError(
            "NON_JSON_NUMBER",
            "integer-valued number exceeds the interoperable IEEE-754 range",
        )
    return value


def _parse_int(token: str) -> int:
    value = int(token)
    if abs(value) > MAX_INTEROPERABLE_INTEGER:
        raise CanonicalInputError(
            "NON_JSON_NUMBER",
            "integer exceeds the interoperable IEEE-754 range",
        )
    return value


def _admit_unicode(
    value: Any,
    *,
    depth: int = 0,
    nodes: list[int] | None = None,
) -> Any:
    budget = nodes if nodes is not None else [0]
    budget[0] += 1
    if depth > MAX_STRUCTURE_DEPTH or budget[0] > MAX_STRUCTURE_NODES:
        raise CanonicalInputError(
            "INPUT_COMPLEXITY_EXCEEDED",
            "contract structure exceeds the admitted complexity bound",
        )
    if isinstance(value, str):
        try:
            normalized = value.encode("utf-16-le", "surrogatepass").decode("utf-16-le")
        except UnicodeDecodeError as exc:
            raise CanonicalInputError("INVALID_UNICODE", "unpaired Unicode surrogate") from exc
        if any(
            0xFDD0 <= ord(character) <= 0xFDEF or ord(character) & 0xFFFF in {0xFFFE, 0xFFFF}
            for character in normalized
        ):
            raise CanonicalInputError("INVALID_UNICODE", "Unicode noncharacter")
        return normalized
    if isinstance(value, dict):
        normalized_object: dict[str, Any] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                raise CanonicalInputError("MALFORMED_SOURCE", "object member names must be strings")
            normalized_key = _admit_unicode(
                key,
                depth=depth + 1,
                nodes=budget,
            )
            if normalized_key in normalized_object:
                raise CanonicalInputError(
                    "DUPLICATE_OBJECT_KEY",
                    "duplicate object member after Unicode normalization",
                )
            normalized_object[normalized_key] = _admit_unicode(
                child,
                depth=depth + 1,
                nodes=budget,
            )
        return normalized_object
    if isinstance(value, list):
        return [_admit_unicode(child, depth=depth + 1, nodes=budget) for child in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise CanonicalInputError(
        "MALFORMED_SOURCE", f"unsupported YAML value type: {type(value).__name__}"
    )


class _DuplicateAwareSafeLoader(yaml.SafeLoader):
    pass


def _construct_mapping(
    loader: _DuplicateAwareSafeLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[str, Any]:
    loader.flatten_mapping(node)
    result: dict[str, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise CanonicalInputError(
                "MALFORMED_SOURCE", "YAML object member names must be strings"
            )
        if key in result:
            raise CanonicalInputError("DUPLICATE_OBJECT_KEY", "duplicate YAML object member")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_DuplicateAwareSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


def strict_loads(payload: bytes, content_type: str = "application/json") -> dict[str, Any]:
    """Parse duplicate-aware JSON/YAML into the RFC 8785 interoperable domain."""

    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CanonicalInputError("INVALID_UNICODE", "source must be UTF-8") from exc
    try:
        if content_type == "application/json":
            value = json.loads(
                text,
                object_pairs_hook=_reject_duplicate_pairs,
                parse_constant=_reject_constant,
                parse_float=_parse_float,
                parse_int=_parse_int,
            )
        elif content_type in {"application/yaml", "application/x-yaml"}:
            value = yaml.load(text, Loader=_DuplicateAwareSafeLoader)
        else:
            raise CanonicalInputError("CONTENT_TYPE_REJECTED", "unsupported contract content type")
    except CanonicalInputError:
        raise
    except (json.JSONDecodeError, yaml.YAMLError, RecursionError) as exc:
        raise CanonicalInputError("MALFORMED_SOURCE", "malformed contract source") from exc
    try:
        value = _admit_unicode(value)
    except RecursionError as exc:
        raise CanonicalInputError(
            "INPUT_COMPLEXITY_EXCEEDED",
            "contract structure exceeds the admitted complexity bound",
        ) from exc
    if not isinstance(value, dict):
        raise CanonicalInputError("MALFORMED_SOURCE", "contract source must be an object")
    try:
        canonical_json_bytes(value)
    except rfc8785.CanonicalizationError as exc:
        raise CanonicalInputError(
            "NON_JSON_NUMBER", "source is outside the RFC 8785 interoperable domain"
        ) from exc
    return value


def canonical_json_bytes(value: Any) -> bytes:
    """Return RFC 8785 bytes using the pinned, dependency-free implementation."""

    return rfc8785.dumps(value)


def canonical_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()
