"""Visible-only customer-support workflow inputs.

This module deliberately has no dependency on ``pmpe.evals``. Production
discovery code can consume these types without importing hidden oracle data.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

_FORBIDDEN_ORACLE_FIELDS = frozenset(
    {
        "expected_outcome",
        "hidden_oracles",
        "oracle",
        "rationale_code",
        "required_fact_ids",
        "required_rule_ids",
    }
)


class VisibleCorpusError(ValueError):
    """Raised when a visible corpus is malformed or leaks evaluation truth."""


def _bounded_identifier(value: object) -> bool:
    return (
        type(value) is str
        and 0 < len(value) <= 128
        and value[0].isalnum()
        and all(character.isalnum() or character in "-_.:" for character in value)
    )


def _bounded_text(value: object, *, maximum: int = 4096) -> bool:
    return type(value) is str and 0 < len(value.encode("utf-8")) <= maximum and "\0" not in value


@dataclass(frozen=True)
class VisibleFact:
    fact_id: str
    text: str
    source_id: str

    def __post_init__(self) -> None:
        if not (
            _bounded_identifier(self.fact_id)
            and _bounded_identifier(self.source_id)
            and _bounded_text(self.text)
        ):
            raise VisibleCorpusError("visible fact is malformed")


@dataclass(frozen=True)
class PolicyRule:
    rule_id: str
    text: str
    priority: int

    def __post_init__(self) -> None:
        if not (
            _bounded_identifier(self.rule_id)
            and _bounded_text(self.text)
            and type(self.priority) is int
            and 0 <= self.priority <= 100
        ):
            raise VisibleCorpusError("policy rule is malformed")


@dataclass(frozen=True)
class SupportCase:
    case_id: str
    split: str
    ticket_text: str
    facts: tuple[VisibleFact, ...]
    policies: tuple[PolicyRule, ...]
    product_constraints: tuple[str, ...]

    def __post_init__(self) -> None:
        fact_ids = [item.fact_id for item in self.facts]
        rule_ids = [item.rule_id for item in self.policies]
        if not (
            _bounded_identifier(self.case_id)
            and self.split in {"development", "held_out"}
            and _bounded_text(self.ticket_text)
            and self.facts
            and self.policies
            and all(type(item) is VisibleFact for item in self.facts)
            and all(type(item) is PolicyRule for item in self.policies)
            and all(_bounded_text(item, maximum=512) for item in self.product_constraints)
            and len(fact_ids) == len(set(fact_ids))
            and len(rule_ids) == len(set(rule_ids))
        ):
            raise VisibleCorpusError("support case is malformed or duplicate")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _reject_oracle_fields(value: object) -> None:
    if isinstance(value, dict):
        if _FORBIDDEN_ORACLE_FIELDS.intersection(value):
            raise VisibleCorpusError("visible corpus contains hidden oracle field")
        for item in value.values():
            _reject_oracle_fields(item)
    elif isinstance(value, list):
        for item in value:
            _reject_oracle_fields(item)


def load_visible_cases(path: Path) -> tuple[SupportCase, ...]:
    """Load only visible inputs and reject embedded evaluation truth."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise VisibleCorpusError("visible corpus is unreadable") from exc
    _reject_oracle_fields(payload)
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0.0":
        raise VisibleCorpusError("visible corpus schema is unsupported")
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list):
        raise VisibleCorpusError("visible corpus cases are missing")
    if any(
        not isinstance(item, dict)
        or not isinstance(item.get("product_constraints"), list)
        for item in raw_cases
    ):
        raise VisibleCorpusError("visible corpus product constraints must be an array")
    try:
        cases = tuple(
            SupportCase(
                case_id=item["case_id"],
                split=item["split"],
                ticket_text=item["ticket_text"],
                facts=tuple(VisibleFact(**fact) for fact in item["facts"]),
                policies=tuple(PolicyRule(**rule) for rule in item["policies"]),
                product_constraints=tuple(item["product_constraints"]),
            )
            for item in raw_cases
        )
    except (KeyError, TypeError, VisibleCorpusError) as exc:
        raise VisibleCorpusError("visible corpus case is malformed") from exc
    case_ids = [item.case_id for item in cases]
    if not cases or len(case_ids) != len(set(case_ids)):
        raise VisibleCorpusError("visible corpus contains duplicate case")
    return cases
