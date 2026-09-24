"""Findings reconciliation (PD-07).

Deterministic policy:
- duplicates (same file+line+title across reviewers) are LINKED, never erased
- product-decision findings become ProductChangeRequests — engineering never
  accepts or fixes them
- low-severity + mechanically-fixable findings auto-accept under a named rule
- everything else requires a recorded owner decision; undecided findings are
  reported, not silently dropped
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pmpe.assurance.findings import FindingsStore
from pmpe.contracts.change_request import ChangeRequestStore

AUTO_ACCEPT_RULE = "REC-001: low severity AND mechanically fixable -> ACCEPTED by policy"


@dataclass(frozen=True)
class OwnerDecision:
    status: str  # ACCEPTED | REJECTED
    owner: str
    reason: str


@dataclass
class ReconciliationResult:
    accepted: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)
    product_decisions: list[str] = field(default_factory=list)
    undecided: list[str] = field(default_factory=list)


def reconcile(
    store: FindingsStore,
    *,
    decisions: dict[str, OwnerDecision],
    pcr_store: ChangeRequestStore | None,
    contract_id: str = "",
    contract_version: int = 0,
    decision_owner: str = "",
) -> ReconciliationResult:
    result = ReconciliationResult()
    seen: dict[tuple[str, int, str], str] = {}

    for finding in store.all():
        if finding.status != "PROPOSED":
            _tally(result, finding.finding_id, finding.status)
            key = (finding.file, finding.line, finding.title.casefold())
            seen.setdefault(key, finding.finding_id)
            continue

        key = (finding.file, finding.line, finding.title.casefold())
        original = seen.get(key)
        if original is not None:
            store.set_status(
                finding.finding_id,
                "DUPLICATE",
                decided_by="reconciliation",
                reason=f"duplicate of {original} (same file, line, and title)",
                duplicate_of=original,
            )
            result.duplicates.append(finding.finding_id)
            continue
        seen[key] = finding.finding_id

        if finding.requires_product_decision:
            store.set_status(
                finding.finding_id,
                "PRODUCT_DECISION_REQUIRED",
                decided_by="reconciliation",
                reason="finding requires a product decision (PD-07)",
            )
            result.product_decisions.append(finding.finding_id)
            if pcr_store is not None:
                pcr_store.create(
                    source_contract_id=contract_id,
                    source_contract_version=contract_version,
                    affected_requirement_ids=(
                        [finding.affected_requirement] if finding.affected_requirement else []
                    ),
                    engineering_finding=f"{finding.finding_id}: {finding.title} — "
                    f"{finding.evidence}",
                    reason=finding.failure_mechanism
                    or "implementation cannot proceed without a product decision",
                    options=[finding.recommended_fix_direction or "(owner to define options)"],
                    engineering_consequences=finding.failure_mechanism,
                    recommended_technical_default=finding.recommended_fix_direction,
                    decision_owner=decision_owner or "product-owner",
                )
            continue

        decision = decisions.get(finding.finding_id)
        if decision is not None:
            store.set_status(
                finding.finding_id,
                decision.status,
                decided_by=decision.owner,
                reason=decision.reason,
            )
            _tally(result, finding.finding_id, decision.status)
            continue

        if finding.severity == "low" and finding.mechanically_fixable:
            store.set_status(
                finding.finding_id, "ACCEPTED", decided_by="policy", reason=AUTO_ACCEPT_RULE
            )
            result.accepted.append(finding.finding_id)
            continue

        result.undecided.append(finding.finding_id)

    return result


def _tally(result: ReconciliationResult, finding_id: str, status: str) -> None:
    if status == "ACCEPTED":
        result.accepted.append(finding_id)
    elif status == "REJECTED":
        result.rejected.append(finding_id)
    elif status == "DUPLICATE":
        result.duplicates.append(finding_id)
    elif status == "PRODUCT_DECISION_REQUIRED":
        result.product_decisions.append(finding_id)
