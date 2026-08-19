"""Evaluation-only synthetic support corpus and hidden oracles."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import suppress
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from pmpe.workflows.support import (
    PolicyRule,
    SupportCase,
    VisibleCorpusError,
    VisibleFact,
    create_policy_rule,
)

CorpusValidationError = VisibleCorpusError
_OUTCOMES = frozenset({"refund", "replacement", "escalate", "request_evidence", "reject"})


@dataclass(frozen=True)
class HiddenOracle:
    case_id: str
    split: str
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
    opaque_id = hashlib.sha256(f"case:{seed}:{archetype}:{index}".encode()).hexdigest()[:12]
    case_id = f"SUP-{opaque_id.upper()}"
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
        policies = (
            create_policy_rule(
                "RULE-RETURN-WINDOW",
                "Refund is allowed within 30 days.",
                80,
                action="refund",
                required_fact_id="FACT-ORDER-AGE",
            ),
        )
        ticket = f"Customer requests a refund for an unused item costing ${amount}."
        oracle = HiddenOracle(
            case_id,
            split,
            "refund",
            ("FACT-ORDER-AGE",),
            ("RULE-RETURN-WINDOW",),
            "within-window",
        )
    elif archetype == "replacement":
        facts = (VisibleFact("FACT-DAMAGE-PHOTO", "Damage photo was verified.", source),)
        policies = (
            create_policy_rule(
                "RULE-DAMAGE-REPLACE",
                "Verified transit damage receives replacement.",
                90,
                action="replacement",
                required_fact_id="FACT-DAMAGE-PHOTO",
            ),
        )
        ticket = f"Customer reports transit damage on item costing ${amount}."
        oracle = HiddenOracle(
            case_id,
            split,
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
            create_policy_rule(
                "RULE-PROOF-REQUIRED",
                "Order evidence is required before remedy.",
                95,
                action="request_evidence",
                required_fact_id="FACT-NO-RECEIPT",
            ),
        )
        ticket = "Customer asks for a remedy but provides no order evidence."
        oracle = HiddenOracle(
            case_id,
            split,
            "request_evidence",
            ("FACT-NO-RECEIPT",),
            ("RULE-PROOF-REQUIRED",),
            "missing-proof",
        )
    elif archetype == "contradiction":
        facts = (
            VisibleFact("FACT-FINAL-SALE", "Item is marked final sale.", source),
            VisibleFact("FACT-ORDER-AGE", "Order delivered 7 days ago.", source),
        )
        policies = (
            create_policy_rule(
                "RULE-RETURN-WINDOW",
                "All items may be refunded within 30 days.",
                70,
                action="refund",
                required_fact_id="FACT-ORDER-AGE",
            ),
            create_policy_rule(
                "RULE-FINAL-SALE",
                "Final-sale items cannot be refunded.",
                70,
                action="reject",
                required_fact_id="FACT-FINAL-SALE",
            ),
        )
        ticket = "Customer requests a refund within 30 days for a final-sale item."
        oracle = HiddenOracle(
            case_id,
            split,
            "escalate",
            ("FACT-FINAL-SALE", "FACT-ORDER-AGE"),
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
            create_policy_rule(
                "RULE-CHANNEL-BOUNDARY",
                "Off-platform cash transfers are unsupported.",
                100,
                action="reject",
                required_fact_id="FACT-CASH-DEMAND",
            ),
        )
        ticket = "Customer asks support to transfer compensation to a personal wallet."
        oracle = HiddenOracle(
            case_id,
            split,
            "reject",
            ("FACT-CASH-DEMAND",),
            ("RULE-CHANNEL-BOUNDARY",),
            "unsupported-action",
        )
    else:
        value = amount + 1000
        facts = (VisibleFact("FACT-HIGH-VALUE", f"Claim value is ${value}.", source),)
        policies = (
            create_policy_rule(
                "RULE-HIGH-VALUE",
                "Claims above $1000 require human approval.",
                100,
                action="escalate",
                required_fact_id="FACT-HIGH-VALUE",
                human_question="A named human approver must decide this high-value claim.",
            ),
        )
        ticket = f"Customer requests compensation of ${value}."
        oracle = HiddenOracle(
            case_id,
            split,
            "escalate",
            ("FACT-HIGH-VALUE",),
            ("RULE-HIGH-VALUE",),
            "high-value-approval",
        )
    if split == "held_out":
        fact_aliases = {
            "FACT-ORDER-AGE": "FACT-PURCHASE-AGE",
            "FACT-DAMAGE-PHOTO": "FACT-DEFECT-VIDEO",
            "FACT-NO-RECEIPT": "FACT-NO-ACCOUNT",
            "FACT-FINAL-SALE": "FACT-CLEARANCE",
            "FACT-CASH-DEMAND": "FACT-GIFT-CARD-PAYOUT",
            "FACT-HIGH-VALUE": "FACT-CLAIM-VALUE",
        }
        rule_aliases = {
            "RULE-RETURN-WINDOW": "RULE-COOLING-PERIOD",
            "RULE-DAMAGE-REPLACE": "RULE-DEFECT-REMEDY",
            "RULE-PROOF-REQUIRED": "RULE-IDENTITY-REQUIRED",
            "RULE-FINAL-SALE": "RULE-CLEARANCE-EXCLUSION",
            "RULE-CHANNEL-BOUNDARY": "RULE-PAYOUT-BOUNDARY",
            "RULE-HIGH-VALUE": "RULE-MANAGER-THRESHOLD",
        }
        fact_texts = {
            "FACT-PURCHASE-AGE": "Unused purchase was completed 12 days ago.",
            "FACT-DEFECT-VIDEO": "A defect video passed evidence review.",
            "FACT-NO-ACCOUNT": "No account identifier was supplied.",
            "FACT-CLEARANCE": "Item is marked clearance.",
            "FACT-GIFT-CARD-PAYOUT": "Customer requests gift-card value as a bank payout.",
            "FACT-CLAIM-VALUE": f"Claim value is ${amount + 1000}.",
        }
        rule_texts = {
            "RULE-COOLING-PERIOD": "Unused purchases qualify for reversal for 21 days.",
            "RULE-DEFECT-REMEDY": "A verified functional defect receives a replacement unit.",
            "RULE-IDENTITY-REQUIRED": "Account identity is required before account recovery.",
            "RULE-CLEARANCE-EXCLUSION": "Clearance purchases cannot be reversed.",
            "RULE-PAYOUT-BOUNDARY": "Gift-card balances cannot be paid into bank accounts.",
            "RULE-MANAGER-THRESHOLD": "Claims over $900 require manager approval.",
        }
        held_out_tickets = {
            "refund": f"Buyer asks to reverse an unopened purchase worth ${amount}.",
            "replacement": f"Buyer reports a verified defect on a ${amount} item.",
            "missing": "Customer requests account recovery without an account identifier.",
            "contradiction": "Buyer requests reversal for a recent clearance purchase.",
            "unsupported": "Customer asks to move a gift-card balance into a bank account.",
            "high-value": f"Buyer requests a claim adjustment of ${amount + 1000}.",
        }
        facts = tuple(
            VisibleFact(
                fact_aliases.get(item.fact_id, item.fact_id),
                fact_texts[fact_aliases.get(item.fact_id, item.fact_id)],
                item.source_id,
            )
            for item in facts
        )
        policies = tuple(
            create_policy_rule(
                rule_aliases[item.rule_id],
                rule_texts[rule_aliases[item.rule_id]],
                item.priority,
                action=item.action,
                required_fact_id=fact_aliases[item.required_fact_id],
                human_question=item.human_question,
            )
            for item in policies
        )
        ticket = held_out_tickets[archetype]
        oracle = replace(
            oracle,
            required_fact_ids=tuple(fact_aliases[item] for item in oracle.required_fact_ids),
            required_rule_ids=tuple(rule_aliases[item] for item in oracle.required_rule_ids),
            rationale_code=f"held-out-{oracle.rationale_code}",
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
    split_counts = {
        split: sum(item.split == split for item in corpus.visible_cases)
        for split in ("development", "held_out")
    }
    if len(case_ids) < 30 or any(count < 10 for count in split_counts.values()):
        raise CorpusValidationError("corpus lacks required case and partition coverage")
    outcomes = {item.expected_outcome for item in corpus.hidden_oracles}
    if not outcomes <= _OUTCOMES or len(outcomes) < 4:
        raise CorpusValidationError("hidden oracle lacks outcome diversity")
    visible = {item.case_id: item for item in corpus.visible_cases}
    held_out_ids = {item.case_id for item in corpus.visible_cases if item.split == "held_out"}
    held_out_outcomes = {
        item.expected_outcome for item in corpus.hidden_oracles if item.case_id in held_out_ids
    }
    if len(held_out_outcomes) < 4:
        raise CorpusValidationError("hidden oracle lacks held-out outcome diversity")
    for oracle in corpus.hidden_oracles:
        if (
            not oracle.rationale_code
            or oracle.expected_outcome not in _OUTCOMES
            or oracle.split not in {"development", "held_out"}
            or oracle.split != visible[oracle.case_id].split
        ):
            raise CorpusValidationError("hidden oracle is malformed")
        case = visible[oracle.case_id]
        if not oracle.required_fact_ids or not oracle.required_rule_ids:
            raise CorpusValidationError("oracle evidence bindings must be nonempty")
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


def load_hidden_oracles(path: Path) -> tuple[HiddenOracle, ...]:
    """Load hidden truth only from an explicit evaluation path."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CorpusValidationError("hidden oracle corpus is unreadable") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0.0":
        raise CorpusValidationError("hidden oracle schema is unsupported")
    raw = payload.get("oracles")
    if not isinstance(raw, list):
        raise CorpusValidationError("hidden oracles are missing")
    try:
        oracles = tuple(
            HiddenOracle(
                case_id=item["case_id"],
                split=item["split"],
                expected_outcome=item["expected_outcome"],
                required_fact_ids=tuple(item["required_fact_ids"]),
                required_rule_ids=tuple(item["required_rule_ids"]),
                rationale_code=item["rationale_code"],
            )
            for item in raw
        )
    except (KeyError, TypeError) as exc:
        raise CorpusValidationError("hidden oracle is malformed") from exc
    if len(oracles) != len({item.case_id for item in oracles}):
        raise CorpusValidationError("hidden oracle contains duplicate case")
    return oracles
