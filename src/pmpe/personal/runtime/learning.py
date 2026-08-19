"""Outcome learning that may propose, but never install, regression cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pmpe.personal.runtime.models import EvidenceSubject, digest_for
from pmpe.personal.runtime.registry import EventRegistry


@dataclass(frozen=True)
class RegressionProposal:
    proposal_id: str
    status: str
    source_event_digest: str
    subject: EvidenceSubject
    proposed_case: dict[str, Any]
    proposal_digest: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "proposal_digest": self.proposal_digest,
            "proposal_id": self.proposal_id,
            "proposed_case": self.proposed_case,
            "source_event_digest": self.source_event_digest,
            "status": self.status,
            "subject": self.subject.as_dict(),
        }


class OutcomeLearningLoop:
    """Derive reviewable regression proposals from failed evaluation evidence."""

    def __init__(self, registry: EventRegistry) -> None:
        self.registry = registry

    def propose(self, *, occurred_at: str) -> tuple[RegressionProposal, ...]:
        events = self.registry.read()
        already_proposed = {
            str(event.payload.get("source_event_digest"))
            for event in events
            if event.event_type == "learning.regression_proposed"
        }
        failures = [
            event
            for event in events
            if event.event_type == "evaluation.recorded"
            and event.payload.get("verdict") == "FAIL"
            and event.event_digest not in already_proposed
        ]
        proposals: list[RegressionProposal] = []
        first_index = len(already_proposed) + 1
        for index, event in enumerate(failures, start=first_index):
            proposed_case = {
                "case_id": f"PROPOSED-{event.payload['case_id']}",
                "expected_outcome": "The observed failure class does not recur.",
                "failure_class": event.payload["failure_class"],
                "source_case_id": event.payload["case_id"],
            }
            unsigned: dict[str, Any] = {
                "proposal_id": f"REGRESSION-PROPOSAL-{index:03d}",
                "proposed_case": proposed_case,
                "source_event_digest": event.event_digest,
                "status": "PROPOSED",
                "subject": event.subject.as_dict(),
            }
            proposal = RegressionProposal(
                proposal_id=unsigned["proposal_id"],
                status="PROPOSED",
                source_event_digest=event.event_digest,
                subject=event.subject,
                proposed_case=proposed_case,
                proposal_digest=digest_for(unsigned),
            )
            self.registry.append(
                event_type="learning.regression_proposed",
                occurred_at=occurred_at,
                subject=event.subject,
                payload={
                    "proposal_digest": proposal.proposal_digest,
                    "proposal_id": proposal.proposal_id,
                    "source_event_digest": event.event_digest,
                    "status": "PROPOSED",
                },
            )
            proposals.append(proposal)
        return tuple(proposals)
