"""Evaluation-only synthetic support corpus and hidden oracles."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pmpe.workflows.support import (
    PolicyRule,
    SupportCase,
    VisibleCorpusError,
    VisibleFact,
)

CorpusValidationError = VisibleCorpusError
_OUTCOMES = frozenset({"refund", "replacement", "escalate", "request_evidence", "reject"})


@dataclass(frozen=True)
class HiddenOracle:
    case_id: str
    expected_outcome: str
    required_fact_ids: tuple[str, ...]
    required_rule_ids: tuple[str, ...]
    rationale_code: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SupportCorpus:
    visible_cases: tuple[SupportCase, ...]
    hidden_oracles: tuple[HiddenOracle, ...]


@dataclass(frozen=True)
class CorpusPaths:
    visible_path: Path
    oracle_path: Path


def _variant(seed: int, archetype: str, index: int, modulus: int) -> int:
    payload = f"{seed}:{archetype}:{index}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % modulus


def _make_case(seed: int, archetype: str, index: int) -> tuple[SupportCase, HiddenOracle]:
    suffix = _variant(seed, archetype, index, 997)
    case_id = f"SUP-{archetype.upper()}-{index + 1:02d}-{suffix:03d}"
    split = "held_out" if index >= 3 else "development"
    source = f"TICKET-{case_id}"
    amount = 40 + _variant(seed, archetype, index, 460)
    constraints = ("Only named policy actions may execute; otherwise escalate.",)
    facts: tuple[VisibleFact, ...]
    policies: tuple[PolicyRule, ...]
    ticket: str
    oracle: HiddenOracle
    if archetype == "refund":
        facts = (VisibleFact("FACT-ORDER-AGE", "Order delivered 7 days ago.", source),)
        policies = (PolicyRule("RULE-RETURN-WINDOW", "Refund is allowed within 30 days.", 80),)
        ticket = f"Customer requests a refund for an unused item costing ${amount}."
        oracle = HiddenOracle(
            case_id,
            "refund",
            ("FACT-ORDER-AGE",),
            ("RULE-RETURN-WINDOW",),
            "within-window",
        )
    elif archetype == "replacement":
        facts = (VisibleFact("FACT-DAMAGE-PHOTO", "Damage photo was verified.", source),)
        policies = (
            PolicyRule("RULE-DAMAGE-REPLACE", "Verified transit damage receives replacement.", 90),
        )
        ticket = f"Customer reports transit damage on item costing ${amount}."
        oracle = HiddenOracle(
            case_id,
            "replacement",
            ("FACT-DAMAGE-PHOTO",),
            ("RULE-DAMAGE-REPLACE",),
            "verified-damage",
        )
    elif archetype == "missing":
        facts = (
            VisibleFact("FACT-NO-RECEIPT", "No receipt or order identifier was supplied.", source),
        )
        policies = (
            PolicyRule("RULE-PROOF-REQUIRED", "Order evidence is required before remedy.", 95),
        )
        ticket = "Customer asks for a remedy but provides no order evidence."
        oracle = HiddenOracle(
            case_id,
            "request_evidence",
            ("FACT-NO-RECEIPT",),
            ("RULE-PROOF-REQUIRED",),
            "missing-proof",
        )
    elif archetype == "contradiction":
        facts = (VisibleFact("FACT-FINAL-SALE", "Item is marked final sale.", source),)
        policies = (
            PolicyRule("RULE-RETURN-WINDOW", "All items may be refunded within 30 days.", 70),
            PolicyRule("RULE-FINAL-SALE", "Final-sale items cannot be refunded.", 70),
        )
        ticket = "Customer requests a refund within 30 days for a final-sale item."
        oracle = HiddenOracle(
            case_id,
            "escalate",
            ("FACT-FINAL-SALE",),
            ("RULE-RETURN-WINDOW", "RULE-FINAL-SALE"),
            "equal-priority-conflict",
        )
    elif archetype == "unsupported":
        facts = (
            VisibleFact(
                "FACT-CASH-DEMAND", "Customer requests an off-platform cash transfer.", source
            ),
        )
        policies = (
            PolicyRule(
                "RULE-CHANNEL-BOUNDARY", "Off-platform cash transfers are unsupported.", 100
            ),
        )
        ticket = "Customer asks support to transfer compensation to a personal wallet."
        oracle = HiddenOracle(
            case_id,
            "reject",
            ("FACT-CASH-DEMAND",),
            ("RULE-CHANNEL-BOUNDARY",),
            "unsupported-action",
        )
    else:
        value = amount + 1000
        facts = (VisibleFact("FACT-HIGH-VALUE", f"Claim value is ${value}.", source),)
        policies = (
            PolicyRule("RULE-HIGH-VALUE", "Claims above $1000 require human approval.", 100),
        )
        ticket = f"Customer requests compensation of ${value}."
        oracle = HiddenOracle(
            case_id,
            "escalate",
            ("FACT-HIGH-VALUE",),
            ("RULE-HIGH-VALUE",),
            "high-value-approval",
        )
    return SupportCase(case_id, split, ticket, facts, policies, constraints), oracle


def generate_support_corpus(*, seed: int) -> SupportCorpus:
    if type(seed) is not int or not 0 <= seed <= 2**31 - 1:
        raise CorpusValidationError("seed is outside the deterministic domain")
    pairs = tuple(
        _make_case(seed, archetype, index)
        for archetype in (
            "refund",
            "replacement",
            "missing",
            "contradiction",
            "unsupported",
            "high-value",
        )
        for index in range(5)
    )
    corpus = SupportCorpus(tuple(item[0] for item in pairs), tuple(item[1] for item in pairs))
    validate_support_corpus(corpus)
    return corpus


def validate_support_corpus(corpus: SupportCorpus) -> None:
    case_ids = [item.case_id for item in corpus.visible_cases]
    oracle_ids = [item.case_id for item in corpus.hidden_oracles]
    if len(case_ids) != len(set(case_ids)):
        raise CorpusValidationError("duplicate case identifier")
    if len(oracle_ids) != len(set(oracle_ids)):
        raise CorpusValidationError("duplicate case oracle")
    if set(case_ids) != set(oracle_ids):
        raise CorpusValidationError("every visible case requires exactly one oracle")
    if len(case_ids) < 30 or {item.split for item in corpus.visible_cases} != {
        "development",
        "held_out",
    }:
        raise CorpusValidationError("corpus lacks required case and partition coverage")
    outcomes = {item.expected_outcome for item in corpus.hidden_oracles}
    if not outcomes <= _OUTCOMES or len(outcomes) < 4:
        raise CorpusValidationError("hidden oracle lacks outcome diversity")
    visible = {item.case_id: item for item in corpus.visible_cases}
    for oracle in corpus.hidden_oracles:
        if not oracle.rationale_code or oracle.expected_outcome not in _OUTCOMES:
            raise CorpusValidationError("hidden oracle is malformed")
        case = visible[oracle.case_id]
        if not set(oracle.required_fact_ids) <= {item.fact_id for item in case.facts}:
            raise CorpusValidationError("oracle references unknown visible fact")
        if not set(oracle.required_rule_ids) <= {item.rule_id for item in case.policies}:
            raise CorpusValidationError("oracle references unknown visible rule")


def _canonical_bytes(payload: object) -> bytes:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return (encoded + "\n").encode()


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        with suppress(FileNotFoundError):
            os.unlink(temporary)
        raise


def write_support_corpus(root: Path, *, seed: int) -> CorpusPaths:
    corpus = generate_support_corpus(seed=seed)
    visible_path = Path(root) / "visible" / "cases.json"
    oracle_path = Path(root) / "eval-only" / "oracles.json"
    _write_atomic(
        visible_path,
        _canonical_bytes(
            {
                "cases": [item.as_dict() for item in corpus.visible_cases],
                "schema_version": "1.0.0",
            }
        ),
    )
    _write_atomic(
        oracle_path,
        _canonical_bytes(
            {
                "oracles": [item.as_dict() for item in corpus.hidden_oracles],
                "schema_version": "1.0.0",
            }
        ),
    )
    return CorpusPaths(visible_path, oracle_path)
